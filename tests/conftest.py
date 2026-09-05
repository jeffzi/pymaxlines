"""Shared test infrastructure: fixtures, helpers, and constants."""

from __future__ import annotations

import contextlib
import io
from pathlib import Path

import pytest

from pymaxlines import MAX_LINES_PER_FUNCTION, MAX_LINES_SRC, main

REPO_ROOT = Path(__file__).resolve().parent.parent

CODE_LINE = "x = 1\n"
INDENTED_CODE_LINE = "    x = 1\n"

PLACEHOLDER = "FILE"


def diagnostic(lineno: int, message: str, path: str = PLACEHOLDER) -> str:
    """Return `path:lineno: message`, the shared diagnostic-line format."""
    return f"{path}:{lineno}: {message}"


def file_diagnostic(count: int, limit: int = MAX_LINES_SRC, path: str = PLACEHOLDER) -> str:
    """Return the expected file-level diagnostic line: `path: count code lines (max limit)`."""
    return f"{path}: {count} code lines (max {limit})"


def function_diagnostic(
    lineno: int,
    name: str,
    count: int,
    limit: int = MAX_LINES_PER_FUNCTION,
    path: str = PLACEHOLDER,
) -> str:
    """Return `path:lineno: function 'name' has count code lines (max limit)`."""
    return diagnostic(lineno, f"function '{name}' has {count} code lines (max {limit})", path)


def make_oversized_function(*, body_lines: int = MAX_LINES_PER_FUNCTION + 1) -> tuple[str, int]:
    """Return ``(source, code_line_count)`` for a ``def big()`` that exceeds the limit."""
    source = "def big():\n" + INDENTED_CODE_LINE * body_lines
    return source, body_lines + 1


def write_module(tmp_path: Path, content: str, name: str = "module.py") -> Path:
    """Write *content* to `tmp_path/name`, creating parent directories as needed, and return the path."""
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def write_code_lines(tmp_path: Path, count: int, name: str = "module.py") -> Path:
    """Write *count* repetitions of `CODE_LINE` to `tmp_path/name` and return the path."""
    return write_module(tmp_path, CODE_LINE * count, name)


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


def expect_exit_two(argv: list[str]) -> None:
    """Run ``main(argv)`` and assert it raises ``SystemExit`` with code 2."""
    with pytest.raises(SystemExit) as exc_info:
        main(argv)
    assert exc_info.value.code == 2


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run every test with cwd set to its tmp_path.

    Prevents in-process ``main()`` from reading the repo's own
    ``pyproject.toml`` or classifying paths against the repo root.
    """
    monkeypatch.chdir(tmp_path)
