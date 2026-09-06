"""Shared test infrastructure: fixtures, helpers, and constants."""

from __future__ import annotations

import contextlib
import io
import re
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from pymaxlines import MAX_LINES_PER_FUNCTION, MAX_LINES_SRC, main

CODE_LINE = "x = 1\n"
INDENTED_CODE_LINE = "    x = 1\n"

PLACEHOLDER = "FILE"

_SUMMARY_RE = re.compile(r"^Found \d+ errors?\.$")


def diagnostic(lineno: int, message: str, path: str = PLACEHOLDER) -> str:
    """Return `path:lineno: message`, the shared diagnostic-line format."""
    return f"{path}:{lineno}: {message}"


def file_diagnostic(count: int, limit: int = MAX_LINES_SRC, path: str = PLACEHOLDER) -> str:
    """Return the expected file-level diagnostic.

    Format: ``path:1: Too many lines in module (count > limit) [max-lines]``
    """
    return f"{path}:1: Too many lines in module ({count} > {limit}) [max-lines]"


def function_diagnostic(
    lineno: int,
    name: str,
    count: int,
    end_lineno: int,
    *,
    limit: int = MAX_LINES_PER_FUNCTION,
) -> str:
    """Return the expected function-level diagnostic.

    Format: ``PLACEHOLDER:lineno: Too many lines in function 'name' (count > limit, lines L-E) [max-lines-per-function]``
    """
    return diagnostic(
        lineno,
        f"Too many lines in function '{name}'"
        f" ({count} > {limit}, lines {lineno}-{end_lineno}) [max-lines-per-function]",
    )


def make_oversized_function(*, body_lines: int = MAX_LINES_PER_FUNCTION + 1) -> tuple[str, int]:
    """Return ``(source, function_line_count)`` for a ``def big()`` that exceeds the limit.

    ``function_line_count`` excludes the ``def`` header.
    """
    source = "def big():\n" + INDENTED_CODE_LINE * body_lines
    return source, body_lines


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


def diagnostic_lines(output: str) -> list[str]:
    """Split output into lines and strip the trailing summary line if present."""
    lines = output.strip().splitlines()
    if lines and _SUMMARY_RE.match(lines[-1]):
        lines.pop()
    return lines


def run_check(file: Path, *extra_args: str) -> tuple[int, list[str]]:
    """Run ``main()`` and return ``(exit_code, diagnostic_lines)`` with the path normalized.

    The summary line (``Found N errors.``) is stripped from the output. Only
    the diagnostic lines are returned so that existing ``lines == [...]``
    assertions keep working; summary/diagnostic-count consistency is checked
    by the dedicated summary-line tests, not here.
    """
    exit_code, output = capture_main([*extra_args, str(file)])
    output = output.replace(str(file), PLACEHOLDER)
    return exit_code, diagnostic_lines(output)


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
