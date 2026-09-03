"""Shared pytest configuration for the test suite."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import mock

import pytest
from pytest import Item
from typer.testing import CliRunner


@pytest.fixture
def cli_runner() -> CliRunner:
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

    repo_root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as temporary_directory:
        # out_file persists until end of fixture (tempdir cleanup happens after yield)
        out_file = Path(temporary_directory) / "template-repo.bundle"
        create_template_bundle(repo_root=repo_root, out_file=out_file)
        with mock.patch.object(
            init, "_get_template_bundle_path", return_value=out_file
        ):
            yield out_file


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


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add the opt-in switch for tests requiring external services."""

    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="Run integration tests that require Docker and external services.",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[Item],
) -> None:
    """Exclude integration tests unless the explicit opt-in flag is supplied."""

    if config.getoption("--integration"):
        return

    selected: list[Item] = []
    deselected: list[Item] = []
    for item in items:
        if "integration" in item.keywords:
            deselected.append(item)
        else:
            selected.append(item)

    items[:] = selected
    config.hook.pytest_deselected(items=deselected)
