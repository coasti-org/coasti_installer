"""Shared helpers for product integration tests."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

from pytest import MonkeyPatch
from typer.testing import CliRunner

import coasti.cli as cli
import coasti.product.cli as product_cli
from coasti.git import GitProbeResult


def add_product(
    cli_runner: CliRunner,
    coasti_instance_dir: Path,
    repository_url: str,
    product_id: str,
    environment: Mapping[str, str] | None = None,
    **authentication_data: str,
):
    """Add one product through the CLI using pre-populated answers."""

    data = {
        "id": product_id,
        "dst_path": f"products/{product_id}",
        "vcs_repo": repository_url,
        "vcs_ref": "main",
        **authentication_data,
    }
    return cli_runner.invoke(
        cli.app,
        ["--quiet", "product", "add", "--data", json.dumps(data)],
        env={
            **(environment or {}),
            "COASTI_BASE_DIR": str(coasti_instance_dir),
        },
    )


def install_product(
    cli_runner: CliRunner,
    coasti_instance_dir: Path,
    product_id: str,
):
    """Install a product through the CLI without allowing Git prompts."""

    return cli_runner.invoke(
        cli.app,
        ["product", "install", product_id],
        env={
            **os.environ,
            "COASTI_BASE_DIR": str(coasti_instance_dir),
            "GIT_TERMINAL_PROMPT": "0",
        },
    )


def force_authentication(monkeypatch: MonkeyPatch) -> None:
    """Force the initial unauthenticated probe to fail.

    We need this because, even when we set the auth method to skip, we might
    have access to the public repo. git autodiscovers and uses credentials if
    it finds in the os setup, via ssh agents etc.

    ``product add`` first tries to access a repository without credentials. If
    that succeeds, it records ``skip`` and never exercises the supplied token or
    SSH key. This wrapper rejects the first probe for each URL and delegates all
    later probes to the real implementation. The later probe therefore still
    verifies the actual authentication mechanism against Gitea.
    """

    from coasti.git import check_access_to_git_repo as real_check_access_to_git_repo

    unauthenticated_urls: set[str] = set()

    def check_access_with_authentication(url: str) -> GitProbeResult:
        if url not in unauthenticated_urls:
            unauthenticated_urls.add(url)
            return GitProbeResult(is_accessible=False)
        return real_check_access_to_git_repo(url)

    monkeypatch.setattr(
        product_cli, "check_access_to_git_repo", check_access_with_authentication
    )


def ssh_environment(
    repository,
    home_directory: Path,
) -> tuple[dict[str, str], Path]:
    """Create SSH environment variables and known-hosts data for a test repo."""

    ssh_directory = home_directory / ".ssh"
    ssh_directory.mkdir(parents=True)
    host_and_path = repository.ssh_url.removeprefix("ssh://git@").split("/", maxsplit=1)
    host, port = host_and_path[0].split(":", maxsplit=1)
    scan_result = subprocess.run(
        ["ssh-keyscan", "-p", port, host],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    known_hosts_path = ssh_directory / "known_hosts"
    known_hosts_path.write_text(scan_result.stdout)
    return (
        {"HOME": str(home_directory), "USERPROFILE": str(home_directory)},
        known_hosts_path,
    )
