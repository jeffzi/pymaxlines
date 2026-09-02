"""Fail when a Python file or function exceeds a code-line limit.

By default, blank lines, comment-only lines, and standalone docstrings are
free — matching oxlint's ``max-lines`` with ``skipBlankLines`` and
``skipComments``. Each category can be counted via ``--no-skip-blank-lines``,
``--no-skip-comments``, or ``--no-skip-docstrings``.

Two checks per file, mirroring oxlint's size rules:

- ``max-lines`` — whole-file code-line count. Default 400 for source files,
  800 for test files.
- ``max-lines-per-function`` — per-function code-line count. Default 60 for
  source files, disabled for test files. A limit of 0 disables the check.

Test files are those under a ``tests/`` directory or named ``test_*.py`` /
``*_test.py``. All limits are configurable via CLI flags.
"""

from __future__ import annotations

import argparse
import ast
import io
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "MAX_LINES_PER_FUNCTION",
    "MAX_LINES_PER_FUNCTION_TEST",
    "MAX_LINES_SRC",
    "MAX_LINES_TEST",
    "main",
]

MAX_LINES_SRC = 400
MAX_LINES_TEST = 800
MAX_LINES_PER_FUNCTION = 60
MAX_LINES_PER_FUNCTION_TEST = 0


@dataclass(frozen=True, slots=True)
class _Config:
    files: list[Path]
    max_lines: int
    max_lines_test: int
    max_lines_per_function: int
    max_lines_per_function_test: int
    skip_blank_lines: bool
    skip_comments: bool
    skip_docstrings: bool


_NON_CODE_TOKENS = frozenset(
    {
        tokenize.COMMENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENDMARKER,
    }
)

_DOCSTRING_CONTAINERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def _docstring_lines(tree: ast.Module) -> set[int]:
    """A docstring is a bare ``ast.Expr(value=ast.Constant(str))``.

    Specifically, it is the first statement in a module, class, or
    function/async-function body.
    """
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, _DOCSTRING_CONTAINERS):
            continue
        if not node.body:
            continue
        first = node.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return lines


def _comment_only_lines(source: str) -> set[int]:
    """A line is comment-only when it has a COMMENT token but no code token.

    The comparison is per-line: a line with both a comment and a code token is
    not comment-only.
    """
    comment_lines: set[int] = set()
    code_lines: set[int] = set()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            comment_lines.add(token.start[0])
        elif token.type not in _NON_CODE_TOKENS:
            code_lines.update(range(token.start[0], token.end[0] + 1))
    return comment_lines - code_lines


def _code_line_numbers(
    source: str,
    tree: ast.Module,
    *,
    skip_blank_lines: bool = True,
    skip_comments: bool = True,
    skip_docstrings: bool = True,
) -> set[int]:
    lines = source.splitlines()
    all_line_numbers = set(range(1, len(lines) + 1))

    skip: set[int] = set()
    if skip_blank_lines:
        skip.update(i for i, line in enumerate(lines, 1) if not line.strip())
    if skip_comments:
        skip.update(_comment_only_lines(source))
    if skip_docstrings:
        skip.update(_docstring_lines(tree))

    return all_line_numbers - skip


@dataclass(frozen=True, slots=True)
class _OversizedFunction:
    name: str
    lineno: int
    count: int


def _oversized_functions(
    tree: ast.Module, code_lines: set[int], limit: int
) -> list[_OversizedFunction]:
    oversized: list[_OversizedFunction] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end = node.end_lineno or node.lineno
        count = sum(1 for number in code_lines if node.lineno <= number <= end)
        if count > limit:
            oversized.append(_OversizedFunction(node.name, node.lineno, count))
    return oversized


def _is_test_file(path: Path) -> bool:
    return "tests" in path.parts or path.name.startswith("test_") or path.name.endswith("_test.py")


def _report(message: str) -> int:
    sys.stdout.write(f"{message}\n")
    return 1


def _check_file(path: Path, config: _Config) -> int:
    is_test = _is_test_file(path)
    file_limit = config.max_lines_test if is_test else config.max_lines
    function_limit = (
        config.max_lines_per_function_test if is_test else config.max_lines_per_function
    )
    try:
        with tokenize.open(path) as handle:
            source = handle.read()
        tree = ast.parse(source)
        code_lines = _code_line_numbers(
            source,
            tree,
            skip_blank_lines=config.skip_blank_lines,
            skip_comments=config.skip_comments,
            skip_docstrings=config.skip_docstrings,
        )
        oversized = _oversized_functions(tree, code_lines, function_limit) if function_limit else []
    except (OSError, UnicodeDecodeError, SyntaxError, tokenize.TokenError) as exc:
        return _report(f"{path}: could not read ({exc})")
    exit_code = 0
    if len(code_lines) > file_limit:
        exit_code = _report(f"{path}: {len(code_lines)} code lines (max {file_limit})")
    for func in oversized:
        exit_code = _report(
            f"{path}:{func.lineno}: function '{func.name}' has {func.count} code lines "
            f"(max {function_limit})"
        )
    return exit_code


def _parse_args(argv: Sequence[str]) -> _Config:
    parser = argparse.ArgumentParser(prog="pymaxlines", description=__doc__.split("\n", 1)[0])
    parser.add_argument("files", nargs="*", type=Path, help="files to check")
    parser.add_argument(
        "--max-lines",
        type=int,
        default=MAX_LINES_SRC,
        help="code-line limit for source files (default: %(default)s)",
    )
    parser.add_argument(
        "--max-lines-test",
        type=int,
        default=MAX_LINES_TEST,
        help="code-line limit for test files (default: %(default)s)",
    )
    parser.add_argument(
        "--max-lines-per-function",
        type=int,
        default=MAX_LINES_PER_FUNCTION,
        help="per-function code-line limit for source files; 0 disables (default: %(default)s)",
    )
    parser.add_argument(
        "--max-lines-per-function-test",
        type=int,
        default=MAX_LINES_PER_FUNCTION_TEST,
        help="per-function code-line limit for test files; 0 disables (default: %(default)s)",
    )
    parser.add_argument(
        "--skip-blank-lines",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="exclude blank lines from counts (default: %(default)s)",
    )
    parser.add_argument(
        "--skip-comments",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="exclude comment-only lines from counts (default: %(default)s)",
    )
    parser.add_argument(
        "--skip-docstrings",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="exclude docstring lines from counts (default: %(default)s)",
    )
    ns = parser.parse_args(argv)
    return _Config(**vars(ns))


def main(argv: Sequence[str] | None = None) -> int:
    """Check each file; return 1 if any is unreadable or exceeds a limit.

    ``argv`` defaults to ``sys.argv[1:]`` so the function doubles as the
    console-script entry point.
    """
    config = _parse_args(sys.argv[1:] if argv is None else argv)
    exit_code = 0
    for path in config.files:
        exit_code |= _check_file(path, config)
    return exit_code
