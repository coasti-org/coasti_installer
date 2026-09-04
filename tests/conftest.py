"""Shared pytest configuration for the test suite."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import mock

import pytest
from pytest import Item
from typer.testing import BytesIOCopy, CliRunner


@pytest.fixture
def cli_runner(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    """Return a CliRunner whose captured streams survive prompt cleanup."""

    # Prompt-toolkit can close Click's capture stream on Linux.  Click then
    # fails while converting the stream to a test result, masking the command's
    # actual exit code.  The stream is owned by the test runner, so closing it
    # must not discard output before ``CliRunner.invoke`` has collected it.
    monkeypatch.setattr(BytesIOCopy, "close", lambda stream: stream.flush())

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

    from coasti.init import init as init_command

    with tempfile.TemporaryDirectory() as tmp_path:
        coasti_dir = Path(tmp_path) / "coasti"
        # To avoid issues on CI runnter (ubuntu) we _do not_ use the cli runner here.
        # Calling the command function directly avoids Click's temporary stdout
        # stream being closed by Copier on Linux before CliRunner can collect it.
        init_command(
            coasti_dir=coasti_dir,
            data='{"vcs_repo_type" : "local"}',
            vcs_ref="HEAD",
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
