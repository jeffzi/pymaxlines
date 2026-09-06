"""Count code lines in a source file, per file and per function."""

from __future__ import annotations

import ast
import io
import tokenize
from collections.abc import Mapping  # noqa: TC003 — runtime-resolvable for typing.get_type_hints
from dataclasses import dataclass, field
from operator import attrgetter

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

# Tokens that do not make a line "code-bearing" for docstring-skip purposes.
# A docstring line is only skippable when every token on that line falls in
# this set — i.e. the line carries no keyword, name, operator, or number.
_DOCSTRING_SKIP_IGNORED_TOKENS = NON_CODE_TOKENS | frozenset({tokenize.STRING, tokenize.ENCODING})

OPEN_BRACKETS = frozenset({"(", "[", "{"})
CLOSE_BRACKETS = frozenset({")", "]", "}"})

FUNCTION_DEF_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)
DOCSTRING_CONTAINERS = (ast.Module, ast.ClassDef, *FUNCTION_DEF_TYPES)


def is_docstring_stmt(stmt: ast.stmt) -> bool:
    """True when *stmt* is a bare string-literal expression statement.

    That is the AST shape of a docstring.
    """
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _node_end(node: ast.stmt) -> int:
    """Return *node*'s end line, falling back to its start line when unset."""
    return node.end_lineno or node.lineno


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
            lines.update(range(first.lineno, _node_end(first) + 1))
    return lines


@dataclass(slots=True)
class _HeaderTracker:
    """Tracks a ``def`` header from the ``def`` keyword through its closing ``:``.

    Feed every token in source order; ``header_ranges`` accumulates the
    line-to-``def``-line mapping as headers close.
    """

    header_ranges: dict[int, int] = field(default_factory=dict)
    in_header: bool = False
    def_line: int = 0
    depth: int = 0
    async_line: int = 0

    def feed(self, token: tokenize.TokenInfo) -> None:
        if token.type == tokenize.NAME and token.string == "async":
            self.async_line = token.start[0]
            return
        if token.type == tokenize.NAME and token.string == "def":
            self.in_header = True
            # ast anchors AsyncFunctionDef.lineno at the `async` token, which
            # can sit on an earlier physical line than `def` (explicit line
            # joining). Prefer it so header_ranges matches the AST view.
            self.def_line = self.async_line or token.start[0]
            self.depth = 0
        elif self.in_header and token.type == tokenize.OP:
            if token.string in OPEN_BRACKETS:
                self.depth += 1
            elif token.string in CLOSE_BRACKETS:
                self.depth -= 1
            elif token.string == ":" and self.depth == 0:
                for line in range(self.def_line, token.start[0] + 1):
                    self.header_ranges[line] = self.def_line
                self.in_header = False
        self.async_line = 0


@dataclass(frozen=True, slots=True)
class TokenScan:
    """Result of a single tokenizer pass over a source file.

    - ``comment_only_lines``: lines carrying a COMMENT token but no code token.
    - ``comments``: every ``(line, text)`` comment token in source order.
    - ``header_ranges``: maps every line of a ``def`` header (from the ``def``
      keyword through its closing ``:``) to the ``def`` line number.
    - ``code_bearing_lines``: lines carrying a token that is not blank/comment/
      structural noise and not a bare string, used to tell a bare docstring
      line from one that also carries code.
    - ``decorator_at_lines``: the line of each ``@`` OP token that opens a
      logical line (i.e. a decorator prefix, not matrix-multiply).
    """

    comment_only_lines: frozenset[int]
    comments: tuple[tuple[int, str], ...]
    header_ranges: Mapping[int, int]
    code_bearing_lines: frozenset[int]
    decorator_at_lines: frozenset[int]


def scan_tokens(source: str) -> TokenScan:
    """Single-pass tokenizer that returns comment info and function header ranges.

    A line is comment-only when it carries a COMMENT token but no code token.

    Header ranges map every line from a ``def`` keyword through the first
    ``:`` at zero bracket depth to the ``def`` line number, so directive
    placement can be checked without AST end-position heuristics.

    ``code_bearing_lines`` collects the lines carrying a token outside
    ``_DOCSTRING_SKIP_IGNORED_TOKENS`` (i.e. excluding strings too), so
    ``code_line_numbers`` can tell a bare docstring line from one that also
    carries code without re-tokenizing the source.
    """
    comment_lines: set[int] = set()
    non_comment_token_lines: set[int] = set()
    code_bearing_lines: set[int] = set()
    comments: list[tuple[int, str]] = []
    decorator_at: set[int] = set()
    header = _HeaderTracker()
    at_logical_line_start = True

    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            comment_lines.add(token.start[0])
            comments.append((token.start[0], token.string))
        elif token.type == tokenize.NEWLINE:
            at_logical_line_start = True
        elif token.type not in NON_CODE_TOKENS:
            if at_logical_line_start and token.type == tokenize.OP and token.string == "@":
                decorator_at.add(token.start[0])
            at_logical_line_start = False
            non_comment_token_lines.update(range(token.start[0], token.end[0] + 1))

        if token.type not in _DOCSTRING_SKIP_IGNORED_TOKENS:
            code_bearing_lines.update(range(token.start[0], token.end[0] + 1))

        header.feed(token)

    return TokenScan(
        comment_only_lines=frozenset(comment_lines - non_comment_token_lines),
        comments=tuple(comments),
        header_ranges=header.header_ranges,
        code_bearing_lines=frozenset(code_bearing_lines),
        decorator_at_lines=frozenset(decorator_at),
    )


def code_line_numbers(
    source: str,
    tree: ast.Module,
    scan: TokenScan,
    *,
    skip_blank_lines: bool,
    skip_docstrings: bool,
) -> set[int]:
    """Return the set of 1-indexed line numbers counted as code.

    Blank lines, comment-only lines, and docstring lines are optionally
    excluded.  Comment-only lines are taken from *scan*; callers that do
    not want to skip comments pass a scan with an empty
    ``comment_only_lines``.  A docstring line is only skipped when it
    carries no other code token on the same line (e.g. a closing
    delimiter followed by an assignment is kept) — determined by
    ``scan.code_bearing_lines``.
    """
    lines = source.split("\n")
    if lines[-1] == "":
        lines.pop()
    all_line_numbers = set(range(1, len(lines) + 1))

    skip: set[int] = set()
    if skip_blank_lines:
        skip.update(i for i, line in enumerate(lines, 1) if not line.strip())
    skip.update(scan.comment_only_lines)
    if skip_docstrings:
        ds_lines = docstring_lines(tree)
        skip.update(ds_lines - scan.code_bearing_lines)

    return all_line_numbers - skip


@dataclass(frozen=True, slots=True)
class OversizedFunction:
    """A function whose code-line count exceeded the configured limit."""

    name: str
    lineno: int
    count: int
    end_lineno: int


def build_headers_by_def(header_ranges: Mapping[int, int]) -> dict[int, frozenset[int]]:
    """Group *header_ranges* by def line, returning ``{def_line: frozenset(header_lines)}``."""
    by_def: dict[int, set[int]] = {}
    for line, def_line in header_ranges.items():
        by_def.setdefault(def_line, set()).add(line)
    return {def_line: frozenset(lines) for def_line, lines in by_def.items()}


def span_code_line_count(start: int, end: int, code_lines: set[int] | frozenset[int]) -> int:
    """Return the number of *code_lines* in the closed interval ``[start, end]``."""
    return sum(1 for number in code_lines if start <= number <= end)


def function_code_line_count(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    code_lines: set[int] | frozenset[int],
    headers_by_def: dict[int, frozenset[int]],
) -> int:
    """Return the code-line count for *node*, excluding header lines before the body."""
    end = _node_end(node)
    body_start = node.body[0].lineno
    header_only = {
        line for line in headers_by_def.get(node.lineno, frozenset()) if line < body_start
    }
    return sum(
        1 for number in code_lines if node.lineno <= number <= end and number not in header_only
    )


def oversized_functions(
    tree: ast.Module,
    code_lines: set[int],
    limit: int,
    *,
    exempt_lines: frozenset[int] = frozenset(),
    header_ranges: Mapping[int, int],
) -> list[OversizedFunction]:
    """Find functions and async functions whose code-line count exceeds *limit*.

    A function's line count is the number of *code_lines* falling within its
    ``[lineno, end_lineno]`` span, excluding header lines (the ``def`` keyword
    through the closing ``:``).  A header line is only excluded when it
    precedes the first body statement; a one-liner's body line on the same
    line as the ``def`` is still counted.

    *header_ranges* maps each line of a ``def`` header to its ``def`` line
    number (from ``TokenScan.header_ranges``).  Functions whose ``def`` line
    is in *exempt_lines* are skipped entirely.  Results are sorted by line
    number.
    """
    headers_by_def = build_headers_by_def(header_ranges)

    oversized: list[OversizedFunction] = []
    for node in ast.walk(tree):
        if not isinstance(node, FUNCTION_DEF_TYPES):
            continue
        if node.lineno in exempt_lines:
            continue
        count = function_code_line_count(node, code_lines, headers_by_def)
        if count > limit:
            oversized.append(OversizedFunction(node.name, node.lineno, count, _node_end(node)))
    oversized.sort(key=attrgetter("lineno"))
    return oversized
