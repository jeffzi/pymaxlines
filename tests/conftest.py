"""Pytest plugin: gate e2e-marked tests behind --run-e2e."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the --run-e2e CLI flag."""
    parser.addoption(
        "--run-e2e",
        action="store_true",
        default=False,
        help="Run tests decorated with @pytest.mark.e2e",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Deselect e2e-marked tests unless --run-e2e was passed."""
    if config.getoption("--run-e2e"):
        return

    remaining: list[pytest.Item] = []
    deselected: list[pytest.Item] = []

    for item in items:
        if any(item.iter_markers(name="e2e")):
            deselected.append(item)
        else:
            remaining.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = remaining
