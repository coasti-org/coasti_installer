"""Fixtures for tests that exercise a real Git service."""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from testcontainers.core.container import DockerContainer, ExecConfig
from testcontainers.core.wait_strategies import HttpWaitStrategy

GITEA_IMAGE = "gitea/gitea:1.24.6"
GITEA_USERNAME = "coasti-test"
GITEA_PASSWORD = "coasti-test-password"
GITEA_EMAIL = "coasti-test@example.com"


@dataclass(frozen=True)
class GiteaRepository:
    """Connection details for a private repository in the test Gitea instance."""

    http_url: str
    ssh_url: str
    http_token: str
    ssh_private_key: Path


@pytest.fixture(scope="session")
def gitea_container() -> Iterator[DockerContainer]:
    """Start an isolated Gitea instance for the integration test session."""

    try:
        container = (
            DockerContainer(GITEA_IMAGE)
            .with_exposed_ports(3000, 22)
            .with_env("GITEA__security__INSTALL_LOCK", "true")
            .with_env("GITEA__server__ROOT_URL", "http://localhost:3000/")
            .waiting_for(HttpWaitStrategy(3000, "/api/healthz"))
        )
        container.start()
    except Exception as error:
        pytest.skip(f"Docker/Gitea is unavailable: {error}")

    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def readme_only_repository(
    gitea_container: DockerContainer,
    tmp_path_factory: pytest.TempPathFactory,
) -> GiteaRepository:
    """Create the private README-only repository used by authentication smoke tests."""

    _create_gitea_user(gitea_container)
    key_directory = tmp_path_factory.mktemp("gitea-ssh")
    token, private_key = _create_authentication(gitea_container, key_directory)
    repository = _gitea_api_request(
        gitea_container,
        "/api/v1/user/repos",
        {
            "name": "readme-only-fixture",
            "description": "Repository used by Coasti integration tests",
            "private": True,
            "auto_init": True,
            "default_branch": "main",
            "readme": "Default",
        },
    )
    http_url, ssh_url = _repository_urls(gitea_container, str(repository["name"]))
    return GiteaRepository(http_url, ssh_url, token, private_key)


@pytest.fixture(scope="session")
def mock_product_repository(
    gitea_container: DockerContainer,
    readme_only_repository: GiteaRepository,
    tmp_path_factory: pytest.TempPathFactory,
) -> GiteaRepository:
    """Publish two tagged versions of the mock product template in Gitea.

    Version ``v1.0.0`` contains ``v1_test_file.txt``. Version ``v2.0.0`` removes
    that file and adds ``v2_test_file.txt`` so update tests can verify file
    additions and removals.
    """

    repository = _gitea_api_request(
        gitea_container,
        "/api/v1/user/repos",
        {
            "name": "mock-product-fixture",
            "description": "Mock product template for Coasti integration tests",
            "private": True,
            "default_branch": "main",
        },
    )
    http_url, ssh_url = _repository_urls(gitea_container, str(repository["name"]))
    local_repository = tmp_path_factory.mktemp("mock-product-repository")
    shutil.copytree(
        Path(__file__).parents[2] / "templates" / "mock_product",
        local_repository,
        dirs_exist_ok=True,
    )
    subprocess.run(["git", "init", "-b", "main"], cwd=local_repository, check=True)
    subprocess.run(
        ["git", "config", "user.email", GITEA_EMAIL],
        cwd=local_repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Coasti Integration Test"],
        cwd=local_repository,
        check=True,
    )
    (local_repository / "v1_test_file.txt").write_text(
        "This file exists only in version 1.\n"
    )
    subprocess.run(["git", "add", "."], cwd=local_repository, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial mock product"],
        cwd=local_repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "tag", "v1.0.0"],
        cwd=local_repository,
        check=True,
    )
    (local_repository / "v1_test_file.txt").unlink()
    (local_repository / "v2_test_file.txt").write_text(
        "This file exists only in version 2.\n"
    )
    subprocess.run(["git", "add", "-A"], cwd=local_repository, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Add version 2 test file"],
        cwd=local_repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "tag", "v2.0.0"],
        cwd=local_repository,
        check=True,
    )
    authenticated_url = http_url.replace(
        "http://", f"http://{GITEA_USERNAME}:{readme_only_repository.http_token}@"
    )
    subprocess.run(
        ["git", "push", authenticated_url, "main", "v1.0.0", "v2.0.0"],
        cwd=local_repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return GiteaRepository(
        http_url,
        ssh_url,
        readme_only_repository.http_token,
        readme_only_repository.ssh_private_key,
    )


def _gitea_api_request(
    container: DockerContainer,
    path: str,
    payload: dict[str, object],
    *,
    username: str = GITEA_USERNAME,
    password: str = GITEA_PASSWORD,
) -> dict[str, object]:
    """Call the Gitea API without adding an HTTP client dependency."""

    host = container.get_container_host_ip()
    port = container.get_exposed_port(3000)
    credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
    request = urllib.request.Request(
        f"http://{host}:{port}{path}",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())


def _create_gitea_user(container: DockerContainer) -> None:
    result = container.exec(
        ExecConfig(
            command=[
                "gitea",
                "admin",
                "user",
                "create",
                "--username",
                GITEA_USERNAME,
                "--password",
                GITEA_PASSWORD,
                "--email",
                GITEA_EMAIL,
                "--admin",
                "--must-change-password=false",
            ],
            user="git",
        )
    )
    output = result.output.decode()
    if result.exit_code != 0 and "already exists" not in output:
        pytest.fail(f"Could not create Gitea test user: {output}")


def _create_authentication(
    container: DockerContainer,
    key_directory: Path,
) -> tuple[str, Path]:
    token_result = _gitea_api_request(
        container,
        f"/api/v1/users/{GITEA_USERNAME}/tokens",
        {"name": "coasti-integration-test", "scopes": ["write:repository"]},
    )
    token = token_result.get("sha1") or token_result.get("token")
    if not isinstance(token, str):
        pytest.fail(f"Gitea did not return a token: {token_result}")

    private_key = key_directory / "id_ed25519"
    subprocess.run(
        [
            "ssh-keygen",
            "-q",
            "-t",
            "ed25519",
            "-N",
            "",
            "-f",
            str(private_key),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    _gitea_api_request(
        container,
        "/api/v1/user/keys",
        {
            "title": "coasti-integration-test",
            "key": private_key.with_name("id_ed25519.pub").read_text().strip(),
        },
    )
    return token, private_key


def _repository_urls(
    container: DockerContainer,
    repository_name: str,
) -> tuple[str, str]:
    host = container.get_container_host_ip()
    http_port = container.get_exposed_port(3000)
    ssh_port = container.get_exposed_port(22)
    return (
        f"http://{host}:{http_port}/{GITEA_USERNAME}/{repository_name}.git",
        f"ssh://git@{host}:{ssh_port}/{GITEA_USERNAME}/{repository_name}.git",
    )
