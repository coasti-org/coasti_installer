"""Smoke tests for the disposable Gitea authentication fixtures."""

import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from coasti.git import check_access_to_git_repo, copier_git_injection


@pytest.mark.integration
def test_private_readme_repository_is_accessible_with_http_token(
    readme_only_repository,
):
    """Verify that the private README-only repository accepts the generated token."""

    authenticated_url = readme_only_repository.http_url.replace(
        "http://",
        f"http://coasti-test:{readme_only_repository.http_token}@",
    )
    assert check_access_to_git_repo(authenticated_url)


@pytest.mark.integration
def test_private_readme_repository_is_accessible_with_ssh_key(
    readme_only_repository,
    tmp_path: Path,
):
    """Verify that the private README-only repository accepts the generated key."""

    ssh_directory = tmp_path / ".ssh"
    ssh_directory.mkdir()
    known_hosts = _create_known_hosts_file(
        readme_only_repository.ssh_url,
        ssh_directory,
    )
    with copier_git_injection(
        ssh_key_path=readme_only_repository.ssh_private_key,
        ssh_known_hosts_path=known_hosts,
    ):
        assert check_access_to_git_repo(readme_only_repository.ssh_url)


@pytest.mark.integration
def test_private_readme_repository_is_not_accessible_with_wrong_http_token(
    readme_only_repository,
):
    """Verify that an invalid HTTP token is rejected by the private repository."""

    wrong_credentials_url = readme_only_repository.http_url.replace(
        "http://",
        "http://coasti-test:wrong-token@",
    )
    assert not check_access_to_git_repo(wrong_credentials_url, timeout_seconds=5)


@pytest.mark.integration
def test_private_readme_repository_is_not_accessible_with_wrong_ssh_key(
    readme_only_repository,
    tmp_path: Path,
):
    """Verify that an SSH key not registered with Gitea is rejected."""

    wrong_private_key = tmp_path / "wrong_id_ed25519"
    subprocess.run(
        [
            "ssh-keygen",
            "-q",
            "-t",
            "ed25519",
            "-N",
            "",
            "-f",
            str(wrong_private_key),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    known_hosts = _create_known_hosts_file(
        readme_only_repository.ssh_url,
        tmp_path,
    )

    with copier_git_injection(
        ssh_key_path=wrong_private_key,
        ssh_known_hosts_path=known_hosts,
    ):
        assert not check_access_to_git_repo(
            readme_only_repository.ssh_url,
            timeout_seconds=5,
        )


@pytest.mark.integration
def test_private_mock_product_repository_exports_all_version_tags(
    private_mock_product_repository,
):
    """Verify that the mock product repository publishes all Copier versions."""

    authenticated_url = private_mock_product_repository.http_url.replace(
        "http://",
        f"http://coasti-test:{private_mock_product_repository.http_token}@",
    )
    result = subprocess.run(
        ["git", "ls-remote", "--tags", authenticated_url],
        check=True,
        capture_output=True,
        text=True,
    )
    exported_tags = {
        line.rsplit(maxsplit=1)[-1]
        for line in result.stdout.splitlines()
        if line.strip()
    }

    assert exported_tags == {
        "refs/tags/v1.0.0",
        "refs/tags/v2.0.0",
        "refs/tags/v3.0.0",
    }


def _create_known_hosts_file(repository_url: str, directory: Path) -> Path:
    parsed_url = urlsplit(repository_url)
    known_hosts = directory / "known_hosts"
    scan_result = subprocess.run(
        [
            "ssh-keyscan",
            "-p",
            str(parsed_url.port),
            parsed_url.hostname or "",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    known_hosts.write_text(scan_result.stdout)
    return known_hosts
