"""Argument parsing, per-file checks, and diagnostic reporting."""

from __future__ import annotations

import argparse
import contextlib
import errno
import importlib.metadata
import os
import stat
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pymaxlines._analysis import (
    Config,
    _analysis_error,
    _file_diagnostic,
    _finish,
    analyze_file,
    report,
)
from pymaxlines._config import BOOL_SPECS, LIMIT_SPECS, dest_name, load_config
from pymaxlines._directives import (
    MAX_LINES_PER_FUNCTION_RULE,
    MAX_LINES_RULE,
    RULES_DISABLING_FILE,
    RULES_DISABLING_FUNCTIONS,
    DirectiveResult,
    diagnostic,
)
from pymaxlines._discovery import discover_files
from pymaxlines._lines import oversized_functions
from pymaxlines._sizes import run_sizes

if TYPE_CHECKING:
    from collections.abc import Sequence

DESCRIPTION = "Fail when a Python file or function exceeds a code-line limit."
PACKAGE_NAME = "pymaxlines"


UNUSED_DISABLE_DIRECTIVE_RULE = "unused-disable-directive"
UNUSED_MSG = (
    "unused pymaxlines-disable directive (no findings were reported) "
    f"[{UNUSED_DISABLE_DIRECTIVE_RULE}]"
)


def report_unused(
    directives: DirectiveResult,
    *,
    file_exceeds: bool,
    would_oversized: set[int],
    path: Path,
) -> int:
    """Report every valid directive that suppressed nothing.

    Returns the number of diagnostics reported.
    """
    count = 0
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
            count += report(diagnostic(path, directive.lineno, UNUSED_MSG))
    return count


def check_file(path: Path, config: Config) -> int:
    """Run every configured check on *path* and return the number of diagnostics reported.

    Unused-directive detection re-runs ``oversized_functions`` *without*
    ``exempt_lines`` so it can compare what would have been oversized against
    what the directives actually suppressed.
    """
    analysis = analyze_file(path, config)
    if isinstance(analysis, str):
        return report(analysis)

    count = 0
    for error in analysis.directives.errors:
        count += report(error)
    file_exceeds = len(analysis.code_lines) > analysis.file_limit
    if not analysis.directives.skip_file_check and file_exceeds:
        count += report(
            _file_diagnostic(
                path,
                "Too many lines in module"
                f" ({len(analysis.code_lines)} > {analysis.file_limit}) [{MAX_LINES_RULE}]",
            )
        )
    for func in analysis.oversized:
        count += report(
            diagnostic(
                path,
                func.lineno,
                f"Too many lines in function '{func.name}'"
                f" ({func.count} > {analysis.function_limit},"
                f" lines {func.lineno}-{func.end_lineno})"
                f" [{MAX_LINES_PER_FUNCTION_RULE}]",
            )
        )
    if config.report_unused_disable_directives and analysis.directives.valid_directives:
        would_oversized: set[int] = set()
        if analysis.function_limit > 0:
            would_oversized = {
                f.lineno
                for f in oversized_functions(
                    analysis.tree,
                    analysis.code_lines,
                    analysis.function_limit,
                    header_ranges=analysis.header_ranges,
                )
            }
        count += report_unused(
            analysis.directives,
            file_exceeds=file_exceeds,
            would_oversized=would_oversized,
            path=path,
        )
    return count


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
    parser.add_argument(
        "--show-sizes",
        action="store_true",
        default=False,
        help=(
            "print a code-line breakdown of every file instead of checking limits;"
            " blank, comment, and docstring lines are excluded according to the --skip-* flags"
        ),
    )
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
        show_sizes=ns.show_sizes,
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
    try:
        if config.show_sizes:
            return run_sizes(files, walk_errors, config)
        total = 0
        for exc in walk_errors:
            total += report(_analysis_error(Path(exc.filename), "read", exc))
        if not files:
            sys.stderr.write("warning: no .py files found\n")
            return _finish(total)
        for path in files:
            total += check_file(path, config)
        return _finish(total)
    except OSError as exc:
        # BrokenPipeError (EPIPE) on Unix; EINVAL on Windows when the reader
        # closes the pipe.  Re-raise anything unrelated.
        if not isinstance(exc, BrokenPipeError) and exc.errno != errno.EINVAL:
            raise
        _silence_broken_stdout()
        return 1
