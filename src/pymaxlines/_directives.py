"""Parse ``# pymaxlines: disable[=rule]`` comments and validate their placement."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pymaxlines._lines import is_docstring_stmt

if TYPE_CHECKING:
    import ast
    from pathlib import Path

MAX_LINES_RULE = "max-lines"
MAX_LINES_PER_FUNCTION_RULE = "max-lines-per-function"

KNOWN_RULES = frozenset({MAX_LINES_RULE, MAX_LINES_PER_FUNCTION_RULE})
FUNCTION_APPLICABLE_RULES = frozenset({MAX_LINES_PER_FUNCTION_RULE})

PYMAXLINES_RE = re.compile(r"pymaxlines\s*:\s*(.*)")
PYMAXLINES_ATTEMPT_RE = re.compile(r"pymaxlines(?=\s|:|$)", re.IGNORECASE)
DISABLE_RE = re.compile(r"disable\s*(?:=\s*(.+))?$")

MALFORMED_MSG = (
    "malformed pymaxlines directive;"
    " expected '# pymaxlines: disable' or '# pymaxlines: disable=<rule>[,<rule>]'"
)

UNUSED_MSG = "unused pymaxlines-disable directive (no findings were reported)"


@dataclass(frozen=True, slots=True)
class ValidDirective:
    lineno: int
    rules: frozenset[str]
    def_line: int | None


@dataclass(frozen=True, slots=True)
class DirectiveResult:
    skip_file_check: bool
    skip_all_functions: bool
    exempt_def_lines: frozenset[int]
    errors: tuple[str, ...]
    valid_directives: tuple[ValidDirective, ...]


class DirectiveError(Exception):
    """A pymaxlines directive comment is malformed or names an unknown rule."""


def diagnostic(path: Path, lineno: int, message: str) -> str:
    return f"{path}:{lineno}: {message}"


def find_pymaxlines_segment(comment_text: str, path: Path, lineno: int) -> str | None:
    """Extract the ``pymaxlines:`` segment from a ``#``-delimited comment.

    Raises ``DirectiveError`` when the comment looks like a directive attempt
    but uses wrong case or omits the colon (near-miss).
    """
    for part in comment_text.split("#"):
        stripped = part.strip()
        match = PYMAXLINES_RE.match(stripped)
        if match:
            return match.group(1).strip()
        if PYMAXLINES_ATTEMPT_RE.match(stripped):
            raise DirectiveError(diagnostic(path, lineno, MALFORMED_MSG))
    return None


def first_statement_line(tree: ast.Module) -> int | None:
    for i, stmt in enumerate(tree.body):
        if i == 0 and is_docstring_stmt(stmt):
            continue
        return stmt.lineno
    return None


def validate_directive(directive_text: str, path: Path, lineno: int) -> list[str] | None:
    """Return the disabled rule names, or ``None`` for a bare ``disable``.

    Raises ``DirectiveError`` when *directive_text* doesn't parse or names an
    unknown rule.
    """
    disable_match = DISABLE_RE.match(directive_text)
    if not disable_match:
        raise DirectiveError(diagnostic(path, lineno, MALFORMED_MSG))

    rules_str = disable_match.group(1)
    if rules_str is None:
        return None

    rules = [r.strip() for r in rules_str.split(",")]
    if any(not r for r in rules):
        raise DirectiveError(diagnostic(path, lineno, MALFORMED_MSG))

    unknown = [r for r in rules if r not in KNOWN_RULES]
    if unknown:
        raise DirectiveError(
            diagnostic(path, lineno, f"unknown rule '{unknown[0]}' in pymaxlines directive")
        )
    return rules


def function_scope_error(rules: list[str] | None, path: Path, lineno: int) -> str | None:
    if rules is None:
        return None
    invalid_rules = [r for r in rules if r not in FUNCTION_APPLICABLE_RULES]
    if not invalid_rules:
        return None
    return diagnostic(
        path,
        lineno,
        f"rule '{invalid_rules[0]}' does not apply to a function;"
        f" use {MAX_LINES_PER_FUNCTION_RULE}",
    )


def parse_directives(
    comments: tuple[tuple[int, str], ...],
    comment_only: frozenset[int],
    tree: ast.Module,
    header_ranges: dict[int, int],
    path: Path,
) -> DirectiveResult:
    first_stmt = first_statement_line(tree)

    skip_file = False
    skip_all_functions = False
    exempt: set[int] = set()
    errors: list[str] = []
    valid: list[ValidDirective] = []

    for lineno, text in comments:
        try:
            directive_text = find_pymaxlines_segment(text, path, lineno)
            if directive_text is None:
                continue
            rules = validate_directive(directive_text, path, lineno)
        except DirectiveError as exc:
            errors.append(str(exc))
            continue

        effective = frozenset(rules) if rules is not None else KNOWN_RULES

        def_line = header_ranges.get(lineno)
        if def_line is not None and lineno not in comment_only:
            scope_error = function_scope_error(rules, path, lineno)
            if scope_error:
                errors.append(scope_error)
            else:
                exempt.add(def_line)
                valid.append(ValidDirective(lineno=lineno, rules=effective, def_line=def_line))
            continue

        is_file_scope = lineno in comment_only and (first_stmt is None or lineno < first_stmt)
        if is_file_scope:
            skip_file = skip_file or MAX_LINES_RULE in effective
            skip_all_functions = skip_all_functions or MAX_LINES_PER_FUNCTION_RULE in effective
            valid.append(ValidDirective(lineno=lineno, rules=effective, def_line=None))
            continue

        errors.append(
            diagnostic(
                path,
                lineno,
                "misplaced pymaxlines directive;"
                " put it on a comment-only line before the first statement"
                " or on a def header line",
            )
        )

    return DirectiveResult(
        skip_file_check=skip_file,
        skip_all_functions=skip_all_functions,
        exempt_def_lines=frozenset(exempt),
        errors=tuple(errors),
        valid_directives=tuple(valid),
    )
