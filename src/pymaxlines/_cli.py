"""Argument parsing, per-file checks, and diagnostic reporting."""

from __future__ import annotations

import argparse
import ast
import contextlib
import errno
import importlib.metadata
import os
import stat
import sys
import tokenize
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pymaxlines._config import BOOL_SPECS, LIMIT_SPECS, dest_name, load_config
from pymaxlines._directives import (
    RULES_DISABLING_FILE,
    RULES_DISABLING_FUNCTIONS,
    DirectiveResult,
    diagnostic,
    parse_directives,
)
from pymaxlines._discovery import discover_files
from pymaxlines._lines import (
    OversizedFunction,
    code_line_numbers,
    oversized_functions,
    scan_tokens,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

DESCRIPTION = "Fail when a Python file or function exceeds a code-line limit."
PACKAGE_NAME = "pymaxlines"


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
    exclude: tuple[str, ...] = ()


UNUSED_MSG = "unused pymaxlines-disable directive (no findings were reported)"


def _file_diagnostic(path: Path, message: str) -> str:
    """Format a file-level diagnostic: ``path: message``."""
    return f"{path}: {message}"


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
    if rel is not None and not rel.parts[0].startswith("..") and "tests" in rel.parts:
        return True
    return path.name.startswith("test_") or path.name.endswith("_test.py")


def report(message: str) -> int:
    """Write *message* to stdout and return the exit-code contribution (always 1)."""
    sys.stdout.write(f"{message}\n")
    return 1


def report_unused(
    directives: DirectiveResult,
    *,
    file_exceeds: bool,
    would_oversized: set[int],
    path: Path,
) -> int:
    """Report every valid directive that suppressed nothing.

    Returns the accumulated exit code.
    """
    exit_code = 0
    for directive in directives.valid_directives:
        if directive.def_line is not None:
            unused = directive.def_line not in would_oversized
        else:
            suppresses_file = bool(directive.rules & RULES_DISABLING_FILE) and file_exceeds
            suppresses_func = bool(directive.rules & RULES_DISABLING_FUNCTIONS) and bool(
                would_oversized
            )
            unused = not (suppresses_file or suppresses_func)
        if unused:
            exit_code |= report(diagnostic(path, directive.lineno, UNUSED_MSG))
    return exit_code


@dataclass(frozen=True, slots=True)
class FileAnalysis:
    """The AST, counted code lines, parsed directives, and computed limits for one file."""

    tree: ast.Module
    code_lines: set[int]
    directives: DirectiveResult
    oversized: tuple[OversizedFunction, ...]
    file_limit: int
    function_limit: int


def _analysis_error(path: Path, verb: str, exc: Exception) -> str:
    """Format the "could not {verb}" diagnostic message for *path*."""
    return _file_diagnostic(path, f"could not {verb} ({exc})")


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
    effective_scan = scan if config.skip_comments else replace(scan, comment_only_lines=frozenset())
    code_lines = code_line_numbers(
        source,
        tree,
        effective_scan,
        skip_blank_lines=config.skip_blank_lines,
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
    return FileAnalysis(
        tree=tree,
        code_lines=code_lines,
        directives=directives,
        oversized=tuple(oversized),
        file_limit=file_limit,
        function_limit=function_limit,
    )


def check_file(path: Path, config: Config) -> int:
    """Run every configured check on *path* and return a non-zero exit code on violation.

    Unused-directive detection re-runs ``oversized_functions`` *without*
    ``exempt_lines`` so it can compare what would have been oversized against
    what the directives actually suppressed.
    """
    analysis = analyze_file(path, config)
    if isinstance(analysis, str):
        return report(analysis)

    exit_code = 0
    for error in analysis.directives.errors:
        exit_code |= report(error)
    file_exceeds = len(analysis.code_lines) > analysis.file_limit
    if not analysis.directives.skip_file_check and file_exceeds:
        exit_code |= report(
            _file_diagnostic(
                path, f"{len(analysis.code_lines)} code lines (max {analysis.file_limit})"
            )
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
        would_oversized: set[int] = set()
        if analysis.function_limit > 0:
            would_oversized = {
                f.lineno
                for f in oversized_functions(
                    analysis.tree, analysis.code_lines, analysis.function_limit
                )
            }
        exit_code |= report_unused(
            analysis.directives,
            file_exceeds=file_exceeds,
            would_oversized=would_oversized,
            path=path,
        )
    return exit_code


def _add_config_flag(parser: argparse.ArgumentParser) -> None:
    """Declare ``--config`` on *parser* — single source of truth for the flag."""
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        dest="config",
        help="path to pyproject.toml (default: pyproject.toml in the working directory)",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI's ArgumentParser with the full flag set (defaults only — no config applied)."""
    parser = argparse.ArgumentParser(prog=PACKAGE_NAME, description=DESCRIPTION)
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"{PACKAGE_NAME} {importlib.metadata.version(PACKAGE_NAME)}",
    )
    _add_config_flag(parser)
    parser.add_argument("files", nargs="*", type=Path, help="files to check")
    for name, default, help_text in LIMIT_SPECS:
        parser.add_argument(
            f"--{name}", type=int, default=default, help=f"{help_text} (default: %(default)s)"
        )
    for name, default, help_text in BOOL_SPECS:
        parser.add_argument(
            f"--{name}", action=argparse.BooleanOptionalAction, default=default, help=help_text
        )
    parser.add_argument(
        "--exclude",
        action="append",
        default=None,
        dest="exclude",
        help="glob pattern to exclude from discovery (repeatable; replaces config list)",
    )
    return parser


def parse_args(argv: Sequence[str]) -> Config:
    """Merge config-file defaults with CLI flags into a Config.

    Precedence: built-in defaults < config file < explicit CLI flags.
    """
    parser = build_parser()

    config_parser = argparse.ArgumentParser(prog=PACKAGE_NAME, add_help=False)
    _add_config_flag(config_parser)
    config_parser.add_argument("-h", "--help", action="store_true", default=False, dest="help")
    config_parser.add_argument(
        "-v", "--version", action="store_true", default=False, dest="version"
    )
    config_ns, _ = config_parser.parse_known_args(argv)

    if config_ns.help or config_ns.version:
        defaults: dict[str, Any] = {}
    else:
        defaults = load_config(config_ns.config, parser)
    config_exclude = defaults.pop("exclude", ())
    parser.set_defaults(**defaults)

    ns = parser.parse_args(argv)
    for name, _, _ in LIMIT_SPECS:
        if getattr(ns, dest_name(name)) < 0:
            parser.error(f"--{name} must be a non-negative integer")

    exclude = tuple(ns.exclude) if ns.exclude is not None else config_exclude
    return Config(
        files=ns.files,
        max_lines=ns.max_lines,
        max_lines_test=ns.max_lines_test,
        max_lines_per_function=ns.max_lines_per_function,
        max_lines_per_function_test=ns.max_lines_per_function_test,
        skip_blank_lines=ns.skip_blank_lines,
        skip_comments=ns.skip_comments,
        skip_docstrings=ns.skip_docstrings,
        report_unused_disable_directives=ns.report_unused_disable_directives,
        force_exclude=ns.force_exclude,
        exclude=exclude,
    )


def _silence_broken_stdout() -> None:
    """Redirect the stdout fd to devnull to suppress a broken-pipe flush error.

    Interpreter shutdown otherwise re-raises and prints "Exception ignored"
    when flushing stdout. Only redirect when stdout is actually a pipe
    (FIFO); when the error originates from a higher-level wrapper the fd
    itself is fine.
    """
    # The process is already exiting on a broken pipe; a failed redirect changes nothing.
    with contextlib.suppress(OSError, ValueError):
        stdout_fd = sys.stdout.fileno()
        if stat.S_ISFIFO(os.fstat(stdout_fd).st_mode):
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, stdout_fd)
            os.close(devnull)


def main(argv: Sequence[str] | None = None) -> int:
    """Check each file; return 1 if any is unreadable or exceeds a limit.

    ``argv`` defaults to ``sys.argv[1:]`` so the function doubles as the
    console-script entry point.
    """
    config = parse_args(sys.argv[1:] if argv is None else argv)
    files, walk_errors = discover_files(
        config.files, config.exclude, force_exclude=config.force_exclude
    )
    exit_code = 0
    try:
        for exc in walk_errors:
            exit_code |= report(_analysis_error(Path(exc.filename), "read", exc))
        if not files:
            sys.stderr.write("warning: no .py files found\n")
            return exit_code
        for path in files:
            exit_code |= check_file(path, config)
        sys.stdout.flush()
    except OSError as exc:
        # BrokenPipeError (EPIPE) on Unix; EINVAL on Windows when the reader
        # closes the pipe.  Re-raise anything unrelated.
        if not isinstance(exc, BrokenPipeError) and exc.errno != errno.EINVAL:
            raise
        _silence_broken_stdout()
        return 1
    return exit_code
