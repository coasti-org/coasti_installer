"""Pytest configuration and fixtures for coasti tests."""

import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

import pytest
from typer.testing import CliRunner


@pytest.fixture
def cli_runner():
    """Return a Typer CliRunner for testing CLI commands."""
    return CliRunner()


@pytest.fixture(scope="module")
def coasti_template_bundle():
    """
    Create bundle resources for the coasti template.

    We cannot include the bundle in git, because this would be circular, but still
    need to ship it - thus needed in tests.
    """
    from coasti import init
    from coasti.create_template_bundle import create_template_bundle

    repo_root = Path(__file__).resolve().parents[2]

    with tempfile.TemporaryDirectory() as tmpdir:
        # out_file persists until end of fixture (tempdir cleanup happens after yield)
        out_file = Path(tmpdir) / "template-repo.bundle"
        create_template_bundle(repo_root=repo_root, out_file=out_file)

        with mock.patch.object(
            init, "_get_template_bundle_path", return_value=out_file
        ):
            yield out_file

    return out_file


@pytest.fixture(scope="class")
def coasti_instance_dir(coasti_template_bundle):
    """
    A working instance of coasti with local version control.
    """
    import coasti.cli as cli

    cli_runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmp_path:
        coasti_dir = Path(tmp_path) / "coasti"
        command = ["init", "--data", '{"vcs_repo_type" : "local"}']
        command += ["--vcs-ref", "HEAD"]
        command += [str(coasti_dir)]
        result = cli_runner.invoke(cli.app, command)
        assert result.exit_code == 0, (
            f"coasti init failed.\n"
            f"exit_code={result.exit_code}\n"
            f"stdout:\n{result.stdout}\n"
            f"exception:\n{result.exception!r}\n"
        )
        assert coasti_dir.is_dir()
        assert (coasti_dir / "products").is_dir()

        yield coasti_dir

    return coasti_dir


@pytest.fixture(scope="class")
def mock_product_repo():
    """
    Create a fake repo from which to add/install products.

    We inlcude the folder structure under /templates but still need to convert
    it into a proper git repo with tags, so that copier can install from it.
    """

    repo_root = Path(__file__).resolve().parents[2]
    product_repo_src = repo_root / "templates" / "mock_product"

    with tempfile.TemporaryDirectory() as temp_dir:
        repo_path = Path(temp_dir) / "mock_product_repo"
        shutil.copytree(product_repo_src, repo_path)

        def run(cmd: list[str]):
            # kwargs expansion creates type issues in subprocess.run, so we wrap it.
            return subprocess.run(cmd, cwd=repo_path, check=True, capture_output=True)

        # Initialize git repo
        run(["git", "init"])
        run(["git", "config", "user.email", "test@example.com"])
        run(["git", "config", "user.name", "Test User"])

        # Add and commit files
        run(["git", "add", "."])
        run(["git", "commit", "-m", "Initial commit"])

        # Create a tag
        run(["git", "tag", "v1.0.0"])

        yield repo_path
