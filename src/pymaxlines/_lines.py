"""Count code lines in a source file, per file and per function."""

from __future__ import annotations

import ast
import io
import tokenize
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection, Iterator

NON_CODE_TOKENS = frozenset(
    {
        tokenize.COMMENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENDMARKER,
    }
)

OPEN_BRACKETS = frozenset({"(", "[", "{"})
CLOSE_BRACKETS = frozenset({")", "]", "}"})

FUNCTION_DEF_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)
DOCSTRING_CONTAINERS = (ast.Module, ast.ClassDef, *FUNCTION_DEF_TYPES)


def iter_functions(tree: ast.Module) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Yield every function and async-function definition in *tree*, at any nesting depth."""
    for node in ast.walk(tree):
        if isinstance(node, FUNCTION_DEF_TYPES):
            yield node


def is_docstring_stmt(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def docstring_lines(tree: ast.Module) -> set[int]:
    """Line numbers covered by the docstring of the module, a class, or a function.

    A docstring is the first statement in a module, class, or
    function/async-function body.
    """
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, DOCSTRING_CONTAINERS):
            continue
        if not node.body:
            continue
        first = node.body[0]
        if is_docstring_stmt(first):
            lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return lines


@dataclass(frozen=True, slots=True)
class TokenScan:
    comment_only_lines: frozenset[int]
    comments: tuple[tuple[int, str], ...]
    header_ranges: dict[int, int]


def scan_tokens(source: str) -> TokenScan:
    """Single-pass tokenizer that returns comment info and function header ranges.

    A line is comment-only when it carries a COMMENT token but no code token.

    Header ranges map every line from a ``def`` keyword through the first
    ``:`` at zero bracket depth to the ``def`` line number, so directive
    placement can be checked without AST end-position heuristics.
    """
    comment_lines: set[int] = set()
    code_lines: set[int] = set()
    comments: list[tuple[int, str]] = []

    header_ranges: dict[int, int] = {}
    in_header = False
    def_line = 0
    depth = 0

    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            comment_lines.add(token.start[0])
            comments.append((token.start[0], token.string))
        elif token.type not in NON_CODE_TOKENS:
            code_lines.update(range(token.start[0], token.end[0] + 1))

        if token.type == tokenize.NAME and token.string == "def":
            in_header = True
            def_line = token.start[0]
            depth = 0
        elif in_header and token.type == tokenize.OP:
            if token.string in OPEN_BRACKETS:
                depth += 1
            elif token.string in CLOSE_BRACKETS:
                depth -= 1
            elif token.string == ":" and depth == 0:
                for line in range(def_line, token.start[0] + 1):
                    header_ranges[line] = def_line
                in_header = False

    return TokenScan(
        comment_only_lines=frozenset(comment_lines - code_lines),
        comments=tuple(comments),
        header_ranges=header_ranges,
    )


def code_line_numbers(
    source: str,
    tree: ast.Module,
    *,
    skip_blank_lines: bool = True,
    skip_comment_lines: Collection[int] = frozenset(),
    skip_docstrings: bool = True,
) -> set[int]:
    lines = source.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    all_line_numbers = set(range(1, len(lines) + 1))

    skip: set[int] = set()
    if skip_blank_lines:
        skip.update(i for i, line in enumerate(lines, 1) if not line.strip())
    skip.update(skip_comment_lines)
    if skip_docstrings:
        skip.update(docstring_lines(tree))

    return all_line_numbers - skip


@dataclass(frozen=True, slots=True)
class OversizedFunction:
    name: str
    lineno: int
    count: int


def oversized_functions(
    tree: ast.Module,
    code_lines: set[int],
    limit: int,
    *,
    exempt_lines: frozenset[int] = frozenset(),
) -> list[OversizedFunction]:
    oversized: list[OversizedFunction] = []
    for node in iter_functions(tree):
        if node.lineno in exempt_lines:
            continue
        end = node.end_lineno or node.lineno
        count = sum(1 for number in code_lines if node.lineno <= number <= end)
        if count > limit:
            oversized.append(OversizedFunction(node.name, node.lineno, count))
    return oversized
