"""Parse ``# pymaxlines: disable[=rule]`` comments and validate their placement."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pymaxlines._lines import is_docstring_stmt

if TYPE_CHECKING:
    import ast
    from pathlib import Path

    from pymaxlines._lines import TokenScan


@dataclass(frozen=True, slots=True)
class RuleEffect:
    """What a rule disables and where its directive is allowed to apply."""

    disables_file_check: bool
    disables_function_check: bool


RULE_REGISTRY: dict[str, RuleEffect] = {
    "max-lines": RuleEffect(disables_file_check=True, disables_function_check=False),
    "max-lines-per-function": RuleEffect(disables_file_check=False, disables_function_check=True),
}

KNOWN_RULES = frozenset(RULE_REGISTRY)
RULES_DISABLING_FILE = frozenset(r for r, e in RULE_REGISTRY.items() if e.disables_file_check)
RULES_DISABLING_FUNCTIONS = frozenset(
    r for r, e in RULE_REGISTRY.items() if e.disables_function_check
)

PYMAXLINES_RE = re.compile(r"pymaxlines\s*:\s*(.*)")
PYMAXLINES_ATTEMPT_RE = re.compile(r"pymaxlines(?!\w)", re.IGNORECASE)
DISABLE_RE = re.compile(r"disable\s*(?:=\s*(.+))?$")

MALFORMED_MSG = (
    "malformed pymaxlines directive;"
    " expected '# pymaxlines: disable' or '# pymaxlines: disable=<rule>[,<rule>]'"
)

DUPLICATE_MSG = (
    "only one pymaxlines directive is allowed per line;"
    " combine rules with commas: '# pymaxlines: disable=rule1,rule2'"
)

MISPLACED_MSG = (
    "misplaced pymaxlines directive;"
    " put it on a comment-only line before the first statement"
    " or on a def header line"
)


@dataclass(frozen=True, slots=True)
class ValidDirective:
    """A directive comment that parsed and landed in a permitted location.

    ``def_line`` is ``None`` for a file-scope directive and set to the line
    of the exempted function's header for a def-scope directive.
    """

    lineno: int
    rules: frozenset[str]
    def_line: int | None


@dataclass(frozen=True, slots=True)
class DirectiveResult:
    """The outcome of parsing every directive comment in a file.

    Combines the file- and function-level suppressions in effect, the
    def lines exempted individually, every diagnostic string produced
    for malformed, unknown, or misplaced directives, and every directive
    that parsed successfully.
    """

    skip_file_check: bool
    skip_all_functions: bool
    exempt_def_lines: frozenset[int]
    errors: tuple[str, ...]
    valid_directives: tuple[ValidDirective, ...]


class DirectiveError(Exception):
    """A pymaxlines directive comment is malformed or names an unknown rule."""


def diagnostic(path: Path, lineno: int, message: str) -> str:
    """Format *message* as a ``path:lineno: message`` diagnostic string."""
    return f"{path}:{lineno}: {message}"


def find_pymaxlines_segment(comment_text: str, path: Path, lineno: int) -> str | None:
    """Extract the ``pymaxlines:`` segment from a ``#``-delimited comment.

    Raises ``DirectiveError`` when the comment looks like a directive attempt
    but uses wrong case or omits the colon (near-miss), when multiple
    ``pymaxlines:`` segments appear on the same line, or when a near-miss
    coexists with a valid directive.
    """
    matches: list[str] = []
    has_near_miss = False

    for part in comment_text.split("#"):
        stripped = part.strip()
        match = PYMAXLINES_RE.match(stripped)
        if match:
            matches.append(match.group(1).strip())
        elif PYMAXLINES_ATTEMPT_RE.match(stripped):
            has_near_miss = True

    if has_near_miss:
        raise DirectiveError(diagnostic(path, lineno, MALFORMED_MSG))
    if len(matches) > 1:
        raise DirectiveError(diagnostic(path, lineno, DUPLICATE_MSG))
    if matches:
        return matches[0]
    return None


def first_statement_line(
    tree: ast.Module,
    decorator_at_lines: frozenset[int] = frozenset(),
) -> int | None:
    r"""Return the line of the module's first real statement, skipping a module docstring.

    When the first statement is decorated, the earliest ``@`` token line
    (from the tokenizer) between any module docstring and the ``def``/``class``
    keyword is used instead of the AST decorator expression's ``lineno``.
    This handles parenthesized decorators like ``@(\n    expr\n)`` where
    the expression node sits on a later line than the ``@``.

    Returns ``None`` when the module has no statements (an empty file, or a
    file containing only a docstring).
    """
    body = tree.body
    if body and is_docstring_stmt(body[0]):
        docstring_end = body[0].end_lineno or body[0].lineno
        body = body[1:]
    else:
        docstring_end = 0
    if not body:
        return None
    stmt = body[0]
    stmt_line = stmt.lineno
    relevant = {line for line in decorator_at_lines if docstring_end < line <= stmt_line}
    if relevant:
        return min(relevant)
    return stmt_line


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


def function_scope_error(rules: list[str] | None, path: Path, lineno: int) -> None:
    """Raise ``DirectiveError`` if any rule does not apply at def scope."""
    if rules is None:
        return
    invalid_rules = [r for r in rules if r not in RULES_DISABLING_FUNCTIONS]
    if not invalid_rules:
        return
    applicable = ", ".join(sorted(RULES_DISABLING_FUNCTIONS))
    raise DirectiveError(
        diagnostic(
            path,
            lineno,
            f"rule '{invalid_rules[0]}' does not apply to a function; use {applicable}",
        )
    )


def parse_directives(
    scan: TokenScan,
    tree: ast.Module,
    path: Path,
) -> DirectiveResult:
    """Classify each comment as a def-scope, file-scope, or misplaced directive.

    Def-scope directives sit on a function-header line and exempt that function.
    File-scope directives appear on a comment-only line before the first
    statement and suppress file-level or all-function checks.  Everything else
    is misplaced.  Malformed or unknown-rule directives are collected as error
    strings rather than raising, so a single pass reports every problem.
    """
    first_stmt = first_statement_line(tree, scan.decorator_at_lines)

    skip_file = False
    skip_all_functions = False
    exempt: set[int] = set()
    errors: list[str] = []
    valid: list[ValidDirective] = []

    for lineno, text in scan.comments:
        try:
            directive_text = find_pymaxlines_segment(text, path, lineno)
            if directive_text is None:
                continue
            rules = validate_directive(directive_text, path, lineno)

            effective = frozenset(rules) if rules is not None else KNOWN_RULES

            def_line = scan.header_ranges.get(lineno)
            if def_line is not None and lineno not in scan.comment_only_lines:
                function_scope_error(rules, path, lineno)
                exempt.add(def_line)
                valid.append(ValidDirective(lineno=lineno, rules=effective, def_line=def_line))
                continue

            is_file_scope = lineno in scan.comment_only_lines and (
                first_stmt is None or lineno < first_stmt
            )
            if is_file_scope:
                skip_file = skip_file or bool(effective & RULES_DISABLING_FILE)
                skip_all_functions = skip_all_functions or bool(
                    effective & RULES_DISABLING_FUNCTIONS
                )
                valid.append(ValidDirective(lineno=lineno, rules=effective, def_line=None))
                continue

            errors.append(diagnostic(path, lineno, MISPLACED_MSG))
        except DirectiveError as exc:
            errors.append(str(exc))

    return DirectiveResult(
        skip_file_check=skip_file,
        skip_all_functions=skip_all_functions,
        exempt_def_lines=frozenset(exempt),
        errors=tuple(errors),
        valid_directives=tuple(valid),
    )
