"""Shared test infrastructure: fixtures, helpers, and constants."""

from __future__ import annotations

import contextlib
import io
from pathlib import Path
from typing import TYPE_CHECKING

from pymaxlines import MAX_LINES_PER_FUNCTION, MAX_LINES_SRC, main

if TYPE_CHECKING:
    import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

CODE_LINE = "x = 1\n"
INDENTED_CODE_LINE = "    x = 1\n"

PLACEHOLDER = "FILE"


def file_diagnostic(count: int, limit: int = MAX_LINES_SRC, path: str = PLACEHOLDER) -> str:
    """Return the expected file-level diagnostic line for *path*."""
    return f"{path}: {count} code lines (max {limit})"


def function_diagnostic(
    lineno: int,
    name: str,
    count: int,
    limit: int = MAX_LINES_PER_FUNCTION,
    path: str = PLACEHOLDER,
) -> str:
    """Return the expected per-function diagnostic line for *name* at *lineno*."""
    return f"{path}:{lineno}: function '{name}' has {count} code lines (max {limit})"


def make_oversized_function(*, body_lines: int = MAX_LINES_PER_FUNCTION + 1) -> tuple[str, int]:
    """Return ``(source, code_line_count)`` for a ``def big()`` that exceeds the limit."""
    source = "def big():\n" + INDENTED_CODE_LINE * body_lines
    return source, body_lines + 1


def write_module(tmp_path: Path, content: str, name: str = "module.py") -> Path:
    """Write *content* to *name* under *tmp_path*, creating parent directories as needed."""
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def capture_main(argv: list[str]) -> tuple[int, str]:
    """Run ``main(argv)`` and return ``(exit_code, captured_stdout)``."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exit_code = main(argv)
    return exit_code, buf.getvalue()


def run_check(file: Path, *extra_args: str) -> tuple[int, list[str]]:
    """Run ``main()`` and return ``(exit_code, output_lines)`` with the path normalized."""
    exit_code, output = capture_main([*extra_args, str(file)])
    output = output.replace(str(file), PLACEHOLDER)
    return exit_code, output.splitlines()


# ---------------------------------------------------------------------------
# pytest plugin: gate e2e-marked tests behind --run-e2e
# ---------------------------------------------------------------------------


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
