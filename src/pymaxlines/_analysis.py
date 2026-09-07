"""Shared per-file analysis: ``Config``, ``FileAnalysis``, and ``analyze_file``.

Isolating these here breaks the import cycle that would otherwise exist between
``_cli`` (argument parsing) and ``_sizes`` (``--show-sizes`` rendering), both of
which depend on this analysis pipeline.
"""

from __future__ import annotations

import ast
import os
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pymaxlines._directives import DirectiveResult, diagnostic, parse_directives
from pymaxlines._lines import (
    OversizedFunction,
    _split_source_lines,
    code_line_numbers,
    oversized_functions,
    scan_tokens,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class Config:
    """The fully merged CLI configuration."""

    files: list[Path]
    max_lines: int
    max_lines_test: int
    max_lines_per_function: int
    max_lines_per_function_test: int
    skip_blank_lines: bool
    skip_comments: bool
    skip_docstrings: bool
    report_unused_disable_directives: bool
    force_exclude: bool
    show_sizes: bool
    exclude: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FileAnalysis:
    """The AST, counted code lines, parsed directives, and computed limits for one file."""

    tree: ast.Module
    code_lines: set[int]
    directives: DirectiveResult
    oversized: tuple[OversizedFunction, ...]
    file_limit: int
    function_limit: int
    header_ranges: Mapping[int, int]
    source_lines: tuple[str, ...]


def is_test_file(path: Path) -> bool:
    """Classify *path* as a test file.

    True if the path lives under a ``tests`` directory or matches
    ``test_*``/``*_test.py`` naming. The ``tests`` directory check only
    considers path components relative to the current working directory, so
    an ancestor directory named ``tests`` outside the project (e.g.
    ``~/tests-workspace/project/module.py``) does not count.

    When the relative path starts with ``..``, the file is outside cwd and the
    directory-based check is skipped — only the filename conventions apply.
    """
    try:
        rel = Path(os.path.relpath(path, Path.cwd()))
    except ValueError:
        rel = None
    if rel is not None and rel.parts[0] != ".." and "tests" in rel.parts:
        return True
    return path.name.startswith("test_") or path.name.endswith("_test.py")


def report(message: str) -> int:
    """Write *message* to stdout and return 1, the diagnostic count it contributes."""
    if sys.stdout is not None:
        sys.stdout.write(f"{message}\n")
    return 1


def _analysis_error(path: Path, verb: str, exc: Exception) -> str:
    """Format the "could not {verb}" diagnostic message for *path*."""
    return diagnostic(path, 1, f"could not {verb} ({exc})")


def _walk_error(exc: OSError) -> str:
    """Format a directory-walk ``OSError`` as a diagnostic message."""
    return _analysis_error(Path(exc.filename), "read", exc)


def analyze_file(path: Path, config: Config) -> FileAnalysis | str:
    """Read and analyze *path*; return a "could not read"/"could not parse" message on failure."""
    is_test = is_test_file(path)
    file_limit = config.max_lines_test if is_test else config.max_lines
    function_limit = (
        config.max_lines_per_function_test if is_test else config.max_lines_per_function
    )
    try:
        with tokenize.open(path) as handle:
            source = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        return _analysis_error(path, "read", exc)
    except SyntaxError as exc:
        # tokenize.open raises SyntaxError for null bytes and encoding issues
        return _analysis_error(path, "parse", exc)
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError) as exc:
        return _analysis_error(path, "parse", exc)
    try:
        scan = scan_tokens(source)
    except tokenize.TokenError as exc:
        return _analysis_error(path, "parse", exc)

    directives = parse_directives(scan, tree, path)
    code_lines = code_line_numbers(
        source,
        tree,
        scan,
        skip_blank_lines=config.skip_blank_lines,
        skip_comments=config.skip_comments,
        skip_docstrings=config.skip_docstrings,
    )
    oversized: list[OversizedFunction] = []
    if function_limit > 0 and not directives.skip_all_functions:
        oversized = oversized_functions(
            tree,
            code_lines,
            function_limit,
            exempt_lines=directives.exempt_def_lines,
            header_ranges=scan.header_ranges,
        )
    return FileAnalysis(
        tree=tree,
        code_lines=code_lines,
        directives=directives,
        oversized=tuple(oversized),
        file_limit=file_limit,
        function_limit=function_limit,
        header_ranges=scan.header_ranges,
        source_lines=tuple(_split_source_lines(source)),
    )


def _finish(total: int) -> int:
    """Write the "Found N errors." summary, flush stdout, and return the exit code."""
    if sys.stdout is not None:
        if total > 0:
            noun = "error" if total == 1 else "errors"
            sys.stdout.write(f"Found {total} {noun}.\n")
        sys.stdout.flush()
    return 1 if total > 0 else 0
