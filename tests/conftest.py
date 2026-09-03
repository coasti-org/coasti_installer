"""Shared pytest configuration for the test suite."""

from __future__ import annotations

import pytest
from pytest import Item


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
