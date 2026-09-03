import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

import coasti.cli as cli


class TestProductFlow:
    """
    Go through the usual flow of product setup:
    - add
    - list products
    - install
    - update
    """

    def test_product_add_writes_to_yaml(
        self,
        cli_runner: CliRunner,
        coasti_instance_dir: Path,
        mock_product_repo: Path,
    ):
        """
        This adds a product with id `mock_skip` to the yaml.
        """

        data = {
            "id": "mock_skip",
            "dst_path": "products/mock_skip",
            "vcs_repo": str(mock_product_repo),
            "vcs_ref": "main",
            "vcs_auth_type": "skip",
        }
        command = ["--quiet", "product", "add", "--data", json.dumps(data)]
        result = cli_runner.invoke(
            app=cli.app, args=command, env={"COASTI_BASE_DIR": str(coasti_instance_dir)}
        )

        assert result.exit_code == 0

        config_path = coasti_instance_dir / "config" / "products.yml"
        assert config_path.is_file()

        with config_path.open() as f:
            yaml_data = yaml.safe_load(f)

        # check expected format
        assert "products" in yaml_data.keys()

        products = yaml_data["products"]
        assert isinstance(products, list)
        assert len(products) == 1

        p = products[0]
        assert p["id"] == data["id"]
        assert p["dst_path"] == data["dst_path"]
        assert p["vcs_repo"] == data["vcs_repo"]
        assert p["vcs_ref"] == data["vcs_ref"]
        assert p["vcs_auth_type"] == data["vcs_auth_type"]

    @pytest.mark.parametrize(
        "secret_kind",
        ["SSH Key", "Auth Token"],
    )
    def test_product_add_writes_secret(
        self,
        cli_runner: CliRunner,
        coasti_instance_dir: Path,
        mock_product_repo: Path,
        tmp_path: Path,
        secret_kind,
    ):
        """
        This adds a product with following ids to the yaml:
        - mock_auth_token
        - mock_ssh_key
        """

        sid = f"mock_{secret_kind.lower().replace(' ', '_')}"
        data = {
            "id": sid,
            "dst_path": f"products/{sid}",
            "vcs_repo": str(mock_product_repo),
            "vcs_ref": "main",
            "vcs_auth_type": secret_kind,
        }

        # we ask questions conditionally
        if secret_kind == "SSH Key":
            data.update({"vcs_auth_sshkeypath": str(tmp_path)})
        elif secret_kind == "Auth Token":
            data.update({"vcs_auth_token": f"{sid}_secret"})

        command = ["--quiet", "product", "add", "--data", json.dumps(data)]
        result = cli_runner.invoke(
            app=cli.app, args=command, env={"COASTI_BASE_DIR": str(coasti_instance_dir)}
        )

        assert result.exit_code == 0
        secret_file = coasti_instance_dir / "config" / "secrets" / f"vcs_auth_{sid}"
        assert secret_file.is_file()

        if secret_kind == "SSH Key":
            assert secret_file.read_text() == data["vcs_auth_sshkeypath"]
        elif secret_kind == "Auth Token":
            assert secret_file.read_text() == data["vcs_auth_token"]

    def test_added_products_are_listed(
        self,
        cli_runner: CliRunner,
        coasti_instance_dir: Path,
        mock_product_repo: Path,
    ):
        """
        Test that the previously added ids are found, and the repo path.
        """

        command = ["--quiet", "product", "list"]
        result = cli_runner.invoke(
            app=cli.app,
            args=command,
            env={
                "COASTI_BASE_DIR": str(coasti_instance_dir),
                "COLUMNS": "1000",  # keep it wide so repo path is not truncated
            },
        )

        assert result.exit_code == 0
        assert f"vcs_repo │ {str(mock_product_repo)}" in result.output
        assert "id │ mock_skip" in result.output
        assert "id │ mock_auth_token" in result.output
        assert "id │ mock_ssh_key" in result.output
        # Note: the delimiters are not a simple pipe!

    def test_product_install_creates_folders(
        self,
        cli_runner: CliRunner,
        coasti_instance_dir: Path,
    ):
        command = ["product", "install", "mock_skip"]
        result = cli_runner.invoke(
            app=cli.app, args=command, env={"COASTI_BASE_DIR": str(coasti_instance_dir)}
        )

        assert result.exit_code == 0

        product_dir = coasti_instance_dir / "products" / "mock_skip"
        assert (product_dir / "config").is_dir()  # directories
        assert (product_dir / "logs").is_dir()
        assert (product_dir / "data").is_dir()
        assert (product_dir / "README.md").is_file()  # normal file
        assert (product_dir / "config" / ".env").is_file()  # .jinja template resolved
