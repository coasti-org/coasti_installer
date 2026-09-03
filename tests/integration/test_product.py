import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

import coasti.cli as cli

from .product_test_helpers import add_product, force_authentication, install_product


class TestPublicProduct:
    """Exercise product workflows that do not require repository credentials."""

    @pytest.mark.integration
    def test_product_add_writes_to_yaml(
        self,
        cli_runner: CliRunner,
        coasti_instance_dir: Path,
        public_mock_product_repository,
    ):
        result = add_product(
            cli_runner,
            coasti_instance_dir,
            public_mock_product_repository.http_url,
            "mock_public",
            vcs_auth_type="skip",
        )

        assert result.exit_code == 0, result.exception
        products_file = coasti_instance_dir / "config" / "products.yml"
        yaml_data = yaml.safe_load(products_file.read_text())
        product = yaml_data["products"][0]
        assert product["id"] == "mock_public"
        assert product["dst_path"] == "products/mock_public"
        assert product["vcs_repo"] == public_mock_product_repository.http_url
        assert product["vcs_ref"] == "main"
        assert product["vcs_auth_type"] == "skip"

    @pytest.mark.integration
    def test_added_products_are_listed(
        self,
        cli_runner: CliRunner,
        coasti_instance_dir: Path,
        public_mock_product_repository,
    ):
        for product_id in ("mock_one", "mock_two", "mock_three"):
            result = add_product(
                cli_runner,
                coasti_instance_dir,
                public_mock_product_repository.http_url,
                product_id,
                vcs_auth_type="skip",
            )
            assert result.exit_code == 0, result.exception

        result = cli_runner.invoke(
            cli.app,
            ["--quiet", "product", "list"],
            env={
                "COASTI_BASE_DIR": str(coasti_instance_dir),
                "COLUMNS": "1000",
            },
        )

        assert result.exit_code == 0
        assert public_mock_product_repository.http_url in result.output
        for product_id in ("mock_one", "mock_two", "mock_three"):
            assert f"id │ {product_id}" in result.output

    @pytest.mark.integration
    def test_product_install_creates_folders(
        self,
        cli_runner: CliRunner,
        coasti_instance_dir: Path,
        public_mock_product_repository,
    ):
        result = add_product(
            cli_runner,
            coasti_instance_dir,
            public_mock_product_repository.http_url,
            "mock_public_product",
            vcs_auth_type="skip",
        )
        assert result.exit_code == 0, result.exception

        result = install_product(
            cli_runner,
            coasti_instance_dir,
            "mock_public_product",
        )
        assert result.exit_code == 0, result.exception

        product_directory = coasti_instance_dir / "products" / "mock_public_product"
        assert (product_directory / "config").is_dir()
        assert (product_directory / "logs").is_dir()
        assert (product_directory / "data").is_dir()
        assert (product_directory / "README.md").is_file()
        assert (product_directory / "config" / ".env").is_file()



class TestPrivateProduct:
    """Exercise product workflows that require private repository credentials."""

    @pytest.mark.integration
    @pytest.mark.parametrize("secret_kind", ["SSH Key", "Auth Token"])
    def test_product_add_writes_to_yaml(
        self,
        cli_runner: CliRunner,
        coasti_instance_dir: Path,
        private_mock_product_repository,
        ssh_authentication,
        secret_kind: str,
        monkeypatch,
    ):
        force_authentication(monkeypatch)
        environment: dict[str, str] | None = None
        if secret_kind == "SSH Key":
            environment = ssh_authentication(private_mock_product_repository)
            repository_url = private_mock_product_repository.ssh_url
            authentication_data = {
                "vcs_auth_type": secret_kind,
                "vcs_auth_sshkeypath": str(
                    private_mock_product_repository.ssh_private_key
                ),
            }
        else:
            repository_url = private_mock_product_repository.http_url
            authentication_data = {
                "vcs_auth_type": secret_kind,
                "vcs_auth_token": private_mock_product_repository.http_token,
            }

        result = add_product(
            cli_runner,
            coasti_instance_dir,
            repository_url,
            f"mock_private_{secret_kind.lower().replace(' ', '_')}",
            environment=environment,
            **authentication_data,
        )

        assert result.exit_code == 0, result.exception
        products_file = coasti_instance_dir / "config" / "products.yml"
        yaml_data = yaml.safe_load(products_file.read_text())
        product_id = f"mock_private_{secret_kind.lower().replace(' ', '_')}"
        product = next(
            product for product in yaml_data["products"] if product["id"] == product_id
        )
        assert product["id"] == product_id
        assert product["dst_path"] == f"products/{product_id}"
        assert product["vcs_repo"] == repository_url
        assert product["vcs_ref"] == "main"
        assert product["vcs_auth_type"] == secret_kind

    @pytest.mark.integration
    @pytest.mark.parametrize("secret_kind", ["SSH Key", "Auth Token"])
    def test_product_add_writes_secret(
        self,
        cli_runner: CliRunner,
        coasti_instance_dir: Path,
        private_mock_product_repository,
        ssh_authentication,
        secret_kind: str,
        monkeypatch,
    ):
        force_authentication(monkeypatch)
        product_id = f"mock_{secret_kind.lower().replace(' ', '_')}"
        environment = {"COASTI_BASE_DIR": str(coasti_instance_dir)}
        if secret_kind == "SSH Key":
            repository_url = private_mock_product_repository.ssh_url
            ssh_environment_data = ssh_authentication(private_mock_product_repository)
            environment.update(ssh_environment_data)
            authentication_data = {
                "vcs_auth_type": secret_kind,
                "vcs_auth_sshkeypath": str(
                    private_mock_product_repository.ssh_private_key
                ),
            }
            expected_secret = private_mock_product_repository.ssh_private_key.as_posix()
        else:
            repository_url = private_mock_product_repository.http_url
            authentication_data = {
                "vcs_auth_type": secret_kind,
                "vcs_auth_token": private_mock_product_repository.http_token,
            }
            expected_secret = private_mock_product_repository.http_token

        result = cli_runner.invoke(
            cli.app,
            [
                "--quiet",
                "product",
                "add",
                "--data",
                json.dumps(
                    {
                        "id": product_id,
                        "dst_path": f"products/{product_id}",
                        "vcs_repo": repository_url,
                        "vcs_ref": "main",
                        **authentication_data,
                    }
                ),
            ],
            env=environment,
        )

        assert result.exit_code == 0, result.exception
        secret_file = (
            coasti_instance_dir / "config" / "secrets" / f"vcs_auth_{product_id}"
        )
        assert secret_file.read_text() == expected_secret
