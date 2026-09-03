"""Argument parsing, per-file checks, and diagnostic reporting."""

from __future__ import annotations

import argparse
import ast
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pymaxlines._directives import (
    MAX_LINES_PER_FUNCTION_RULE,
    MAX_LINES_RULE,
    UNUSED_MSG,
    DirectiveResult,
    ValidDirective,
    diagnostic,
    parse_directives,
)
from pymaxlines._lines import (
    OversizedFunction,
    code_line_numbers,
    oversized_functions,
    scan_tokens,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

MAX_LINES_SRC = 400
MAX_LINES_TEST = 800
MAX_LINES_PER_FUNCTION = 60
MAX_LINES_PER_FUNCTION_TEST = 0

DESCRIPTION = "Fail when a Python file or function exceeds a code-line limit."


@dataclass(frozen=True, slots=True)
class Config:
    files: list[Path]
    max_lines: int
    max_lines_test: int
    max_lines_per_function: int
    max_lines_per_function_test: int
    skip_blank_lines: bool
    skip_comments: bool
    skip_docstrings: bool
    report_unused_disable_directives: bool


LIMIT_FLAGS = (
    "max_lines",
    "max_lines_test",
    "max_lines_per_function",
    "max_lines_per_function_test",
)


def is_test_file(path: Path) -> bool:
    return "tests" in path.parts or path.name.startswith("test_") or path.name.endswith("_test.py")


def report(message: str) -> int:
    sys.stdout.write(f"{message}\n")
    return 1


def would_exceed_defs(tree: ast.Module, code_lines: set[int], function_limit: int) -> set[int]:
    if function_limit > 0:
        return {f.lineno for f in oversized_functions(tree, code_lines, function_limit)}
    return set()


def directive_is_unused(
    directive: ValidDirective,
    *,
    file_exceeds: bool,
    would_oversized: set[int],
    function_limit: int,
) -> bool:
    if directive.def_line is not None:
        return function_limit == 0 or directive.def_line not in would_oversized
    suppressed = (MAX_LINES_RULE in directive.rules and file_exceeds) or (
        MAX_LINES_PER_FUNCTION_RULE in directive.rules and bool(would_oversized)
    )
    return not suppressed


def report_unused(
    directives: DirectiveResult,
    *,
    file_exceeds: bool,
    would_oversized: set[int],
    function_limit: int,
    path: Path,
) -> int:
    exit_code = 0
    for directive in directives.valid_directives:
        if directive_is_unused(
            directive,
            file_exceeds=file_exceeds,
            would_oversized=would_oversized,
            function_limit=function_limit,
        ):
            exit_code |= report(diagnostic(path, directive.lineno, UNUSED_MSG))
    return exit_code


@dataclass(frozen=True, slots=True)
class FileAnalysis:
    tree: ast.Module
    code_lines: set[int]
    directives: DirectiveResult
    oversized: tuple[OversizedFunction, ...]
    file_limit: int
    function_limit: int


def analyze_file(path: Path, config: Config) -> FileAnalysis | str:
    """Read and analyze *path*; return the "could not read" message on failure."""
    is_test = is_test_file(path)
    file_limit = config.max_lines_test if is_test else config.max_lines
    function_limit = (
        config.max_lines_per_function_test if is_test else config.max_lines_per_function
    )
    try:
        with tokenize.open(path) as handle:
            source = handle.read()
        tree = ast.parse(source)
        scan = scan_tokens(source)
        directives = parse_directives(
            scan.comments, scan.comment_only_lines, tree, scan.header_ranges, path
        )
        code_lines = code_line_numbers(
            source,
            tree,
            skip_blank_lines=config.skip_blank_lines,
            skip_comment_lines=scan.comment_only_lines if config.skip_comments else frozenset(),
            skip_docstrings=config.skip_docstrings,
        )
        oversized: list[OversizedFunction] = []
        if function_limit > 0 and not directives.skip_all_functions:
            oversized = oversized_functions(
                tree,
                code_lines,
                function_limit,
                exempt_lines=directives.exempt_def_lines,
            )
    except (
        OSError,
        UnicodeDecodeError,
        SyntaxError,
        tokenize.TokenError,
        ValueError,
        RecursionError,
    ) as exc:
        return f"{path}: could not read ({exc})"
    return FileAnalysis(
        tree=tree,
        code_lines=code_lines,
        directives=directives,
        oversized=tuple(oversized),
        file_limit=file_limit,
        function_limit=function_limit,
    )


def check_file(path: Path, config: Config) -> int:
    analysis = analyze_file(path, config)
    if isinstance(analysis, str):
        return report(analysis)

    exit_code = 0
    for error in analysis.directives.errors:
        exit_code |= report(error)
    file_exceeds = len(analysis.code_lines) > analysis.file_limit
    if not analysis.directives.skip_file_check and file_exceeds:
        exit_code |= report(
            f"{path}: {len(analysis.code_lines)} code lines (max {analysis.file_limit})"
        )
    for func in analysis.oversized:
        exit_code |= report(
            diagnostic(
                path,
                func.lineno,
                f"function '{func.name}' has {func.count} code lines"
                f" (max {analysis.function_limit})",
            )
        )
    if config.report_unused_disable_directives and analysis.directives.valid_directives:
        exit_code |= report_unused(
            analysis.directives,
            file_exceeds=file_exceeds,
            would_oversized=would_exceed_defs(
                analysis.tree, analysis.code_lines, analysis.function_limit
            ),
            function_limit=analysis.function_limit,
            path=path,
        )
    return exit_code


def parse_args(argv: Sequence[str]) -> Config:
    parser = argparse.ArgumentParser(prog="pymaxlines", description=DESCRIPTION)
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
    parser.add_argument(
        "--report-unused-disable-directives",
        action="store_true",
        default=False,
        help="report pymaxlines-disable directives that suppress no findings",
    )
    ns = parser.parse_args(argv)
    for flag in LIMIT_FLAGS:
        if getattr(ns, flag) < 0:
            parser.error(f"--{flag.replace('_', '-')} must be a non-negative integer")
    return Config(**vars(ns))


def main(argv: Sequence[str] | None = None) -> int:
    """Check each file; return 1 if any is unreadable or exceeds a limit.

    ``argv`` defaults to ``sys.argv[1:]`` so the function doubles as the
    console-script entry point.
    """
    config = parse_args(sys.argv[1:] if argv is None else argv)
    exit_code = 0
    for path in config.files:
        exit_code |= check_file(path, config)
    return exit_code
