from unittest import mock

import pytest

import coasti.cli as cli


@pytest.mark.parametrize(
    "verbose_args,expected_level",
    [
        ([], 0),
        (["--verbose"], 1),
        (["--verbose", "--verbose"], 2),
        (["--verbose", "--verbose", "--verbose"], 3),
        (["-v"], 1),
        (["-vv"], 2),
        (["-vvv"], 3),
    ],
)
def test_verbose_levels(cli_runner, verbose_args, expected_level):
    """Test verbosity levels map to correct log levels."""
    with mock.patch("coasti.cli.setup_logging_handler") as mock_setup:
        # Combine verbose args with --help to trigger the CLI
        args = verbose_args + ["version"]
        cli_runner.invoke(cli.app, args)
        mock_setup.assert_called_once_with(expected_level)
