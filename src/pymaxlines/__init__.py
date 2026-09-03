"""Fail when a Python file or function exceeds a code-line limit.

Inline ``# pymaxlines: disable[=rule]`` directives can exempt individual files
or functions from the checks.

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
import re
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection, Iterator, Sequence

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

_FUNCTION_DEF_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)
_DOCSTRING_CONTAINERS = (ast.Module, ast.ClassDef, *_FUNCTION_DEF_TYPES)


def _iter_functions(tree: ast.Module) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Yield every function and async-function definition in *tree*, at any nesting depth."""
    for node in ast.walk(tree):
        if isinstance(node, _FUNCTION_DEF_TYPES):
            yield node


def _is_docstring_stmt(stmt: ast.stmt) -> bool:
    """A docstring is a bare ``ast.Expr(value=ast.Constant(str))``."""
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _docstring_lines(tree: ast.Module) -> set[int]:
    """Line numbers covered by the docstring of the module, a class, or a function.

    A docstring is the first statement in a module, class, or
    function/async-function body.
    """
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, _DOCSTRING_CONTAINERS):
            continue
        if not node.body:
            continue
        first = node.body[0]
        if _is_docstring_stmt(first):
            lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return lines


def _tokenize_comments(source: str) -> tuple[set[int], list[tuple[int, str]]]:
    """A line is comment-only when it carries a COMMENT token but no code token.

    The token list feeds directive parsing without a second tokenize pass.
    """
    comment_lines: set[int] = set()
    code_lines: set[int] = set()
    comments: list[tuple[int, str]] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            comment_lines.add(token.start[0])
            comments.append((token.start[0], token.string))
        elif token.type not in _NON_CODE_TOKENS:
            code_lines.update(range(token.start[0], token.end[0] + 1))
    return comment_lines - code_lines, comments


def _code_line_numbers(
    source: str,
    tree: ast.Module,
    *,
    skip_blank_lines: bool = True,
    skip_comment_lines: Collection[int] = frozenset(),
    skip_docstrings: bool = True,
) -> set[int]:
    lines = source.splitlines()
    all_line_numbers = set(range(1, len(lines) + 1))

    skip: set[int] = set()
    if skip_blank_lines:
        skip.update(i for i, line in enumerate(lines, 1) if not line.strip())
    skip.update(skip_comment_lines)
    if skip_docstrings:
        skip.update(_docstring_lines(tree))

    return all_line_numbers - skip


@dataclass(frozen=True, slots=True)
class _OversizedFunction:
    name: str
    lineno: int
    count: int


def _oversized_functions(
    tree: ast.Module,
    code_lines: set[int],
    limit: int,
    *,
    exempt_lines: frozenset[int] = frozenset(),
) -> list[_OversizedFunction]:
    oversized: list[_OversizedFunction] = []
    for node in _iter_functions(tree):
        if node.lineno in exempt_lines:
            continue
        end = node.end_lineno or node.lineno
        count = sum(1 for number in code_lines if node.lineno <= number <= end)
        if count > limit:
            oversized.append(_OversizedFunction(node.name, node.lineno, count))
    return oversized


_MAX_LINES_RULE = "max-lines"
_MAX_LINES_PER_FUNCTION_RULE = "max-lines-per-function"

_KNOWN_RULES = frozenset({_MAX_LINES_RULE, _MAX_LINES_PER_FUNCTION_RULE})
_FUNCTION_APPLICABLE_RULES = frozenset({_MAX_LINES_PER_FUNCTION_RULE})

_PYMAXLINES_RE = re.compile(r"pymaxlines\s*:\s*(.*)")
_DISABLE_RE = re.compile(r"disable\s*(?:=\s*(.+))?$")


@dataclass(frozen=True, slots=True)
class _DirectiveResult:
    skip_file_check: bool
    skip_all_functions: bool
    exempt_def_lines: frozenset[int]
    errors: tuple[str, ...]


def _find_pymaxlines_segment(comment_text: str) -> str | None:
    """Extract the ``pymaxlines:`` segment from a ``#``-delimited comment."""
    for part in comment_text.split("#"):
        match = _PYMAXLINES_RE.match(part.strip())
        if match:
            return match.group(1).strip()
    return None


def _first_statement_line(tree: ast.Module) -> int | None:
    """Line of the first non-docstring statement in the module body."""
    for i, stmt in enumerate(tree.body):
        if i == 0 and _is_docstring_stmt(stmt):
            continue
        return stmt.lineno
    return None


def _signature_end_lineno(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Last source line touched by the def's parameters, defaults, or return annotation."""
    end = node.lineno
    for part in (node.args, node.returns, *node.type_params):
        if part is None:
            continue
        for sub in ast.walk(part):
            sub_end = getattr(sub, "end_lineno", None)
            if sub_end is not None:
                end = max(end, sub_end)
    return end


def _function_signature_ranges(tree: ast.Module) -> dict[int, int]:
    """Map every line in a function's signature range to the ``def`` line.

    A one-liner ``def f(): ...`` has its body on the ``def`` line itself, so
    the range still covers it. A wrapped signature whose closing line also
    carries the first body statement extends
    the range to that shared line. A decorated nested ``def`` as the first
    body statement ends the range at the line before its own decorator, not
    at the nested ``def`` line, so a directive on the decorator is never
    misattributed to the enclosing function.
    """
    ranges: dict[int, int] = {}
    for node in _iter_functions(tree):
        if not node.body:
            continue
        first_stmt = node.body[0]
        decorators = getattr(first_stmt, "decorator_list", None)
        first_body_line = decorators[0].lineno if decorators else first_stmt.lineno

        end = max(node.lineno, first_body_line - 1)
        sig_end = _signature_end_lineno(node)
        if sig_end > node.lineno and sig_end == first_body_line - 1:
            end = first_body_line

        for line in range(node.lineno, end + 1):
            # Inner function wins when ranges overlap.
            if line not in ranges or node.lineno > ranges[line]:
                ranges[line] = node.lineno
    return ranges


_MALFORMED_MSG = "malformed pymaxlines directive; expected 'disable' or 'disable=<rule>[,<rule>]'"


def _locate(path: Path, lineno: int, message: str) -> str:
    return f"{path}:{lineno}: {message}"


class _DirectiveError(Exception):
    """A pymaxlines directive comment is malformed or names an unknown rule."""


def _validate_directive(directive_text: str, path: Path, lineno: int) -> list[str] | None:
    """Return the disabled rule names, or ``None`` for a bare ``disable``.

    Raises ``_DirectiveError`` when *directive_text* doesn't parse or names an
    unknown rule.
    """
    disable_match = _DISABLE_RE.match(directive_text)
    if not disable_match:
        raise _DirectiveError(_locate(path, lineno, _MALFORMED_MSG))

    rules_str = disable_match.group(1)
    if rules_str is None:
        return None

    rules = [r.strip() for r in rules_str.split(",")]
    if any(not r for r in rules):
        raise _DirectiveError(_locate(path, lineno, _MALFORMED_MSG))

    unknown = [r for r in rules if r not in _KNOWN_RULES]
    if unknown:
        raise _DirectiveError(
            _locate(path, lineno, f"unknown rule '{unknown[0]}' in pymaxlines directive")
        )
    return rules


def _function_scope_error(rules: list[str] | None, path: Path, lineno: int) -> str | None:
    """Error text when *rules* names a rule that doesn't apply to a function, else ``None``."""
    if rules is None:
        return None
    invalid_rules = [r for r in rules if r not in _FUNCTION_APPLICABLE_RULES]
    if not invalid_rules:
        return None
    return _locate(
        path,
        lineno,
        f"rule '{invalid_rules[0]}' does not apply to a function;"
        f" use {_MAX_LINES_PER_FUNCTION_RULE}",
    )


def _parse_directives(
    comments: list[tuple[int, str]],
    comment_only: set[int],
    tree: ast.Module,
    path: Path,
) -> _DirectiveResult:
    first_stmt = _first_statement_line(tree)
    sig_ranges = _function_signature_ranges(tree)

    skip_file = False
    skip_all_functions = False
    exempt: set[int] = set()
    errors: list[str] = []

    for lineno, text in comments:
        directive_text = _find_pymaxlines_segment(text)
        if directive_text is None:
            continue

        try:
            rules = _validate_directive(directive_text, path, lineno)
        except _DirectiveError as exc:
            errors.append(str(exc))
            continue

        if lineno in sig_ranges and lineno not in comment_only:
            scope_error = _function_scope_error(rules, path, lineno)
            if scope_error:
                errors.append(scope_error)
            else:
                exempt.add(sig_ranges[lineno])
            continue

        is_file_scope = lineno in comment_only and (first_stmt is None or lineno < first_stmt)
        if is_file_scope:
            disabled = set(rules) if rules is not None else _KNOWN_RULES
            skip_file = skip_file or _MAX_LINES_RULE in disabled
            skip_all_functions = skip_all_functions or _MAX_LINES_PER_FUNCTION_RULE in disabled
            continue

        errors.append(
            _locate(
                path,
                lineno,
                "misplaced pymaxlines directive;"
                " put it before the first statement or on a def line",
            )
        )

    return _DirectiveResult(
        skip_file_check=skip_file,
        skip_all_functions=skip_all_functions,
        exempt_def_lines=frozenset(exempt),
        errors=tuple(errors),
    )


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
        comment_only, comments = _tokenize_comments(source)
        directives = _parse_directives(comments, comment_only, tree, path)
        code_lines = _code_line_numbers(
            source,
            tree,
            skip_blank_lines=config.skip_blank_lines,
            skip_comment_lines=comment_only if config.skip_comments else frozenset(),
            skip_docstrings=config.skip_docstrings,
        )
        oversized: list[_OversizedFunction] = []
        if function_limit > 0 and not directives.skip_all_functions:
            oversized = _oversized_functions(
                tree,
                code_lines,
                function_limit,
                exempt_lines=directives.exempt_def_lines,
            )
    except (OSError, UnicodeDecodeError, SyntaxError, tokenize.TokenError) as exc:
        return _report(f"{path}: could not read ({exc})")
    exit_code = 0
    for error in directives.errors:
        exit_code = _report(error)
    if not directives.skip_file_check and len(code_lines) > file_limit:
        exit_code = _report(f"{path}: {len(code_lines)} code lines (max {file_limit})")
    for func in oversized:
        exit_code = _report(
            _locate(
                path,
                func.lineno,
                f"function '{func.name}' has {func.count} code lines (max {function_limit})",
            )
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
    for flag in (
        "max_lines",
        "max_lines_test",
        "max_lines_per_function",
        "max_lines_per_function_test",
    ):
        if getattr(ns, flag) < 0:
            parser.error(f"--{flag.replace('_', '-')} must be a non-negative integer")
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
