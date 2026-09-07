from importlib import metadata
from unittest import mock

import pytest

import coasti.cli as cli


@pytest.mark.parametrize(
    "package_version,expected_output",
    [
        ("0.1.0", "Coasti version 0.1.0"),
        ("2.0.0-beta.1", "Coasti version 2.0.0-beta.1"),
        ("3.14.159", "Coasti version 3.14.159"),
    ],
)
def test_version_command_various_versions(cli_runner, package_version, expected_output):
    """Test version command with different package versions."""
    with mock.patch.object(metadata, "version", return_value=package_version):
        result = cli_runner.invoke(cli.app, ["version"])

        assert result.exit_code == 0
        assert expected_output in result.output


def test_version_command_package_not_found(cli_runner):
    """Test version command when package is not installed."""
    # Mock metadata.version to raise PackageNotFoundError
    with mock.patch.object(
        metadata, "version", side_effect=metadata.PackageNotFoundError
    ):
        result = cli_runner.invoke(cli.app, ["version"])

        assert result.exit_code == 0
        assert (
            "Coasti version [not found] Use `uv sync` when developing!" in result.output
        )
