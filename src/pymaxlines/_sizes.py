"""Build and render a code-line breakdown of every file (--show-sizes mode)."""

from __future__ import annotations

import ast
import io
import sys
from dataclasses import dataclass
from itertools import groupby
from operator import attrgetter
from typing import TYPE_CHECKING, NamedTuple

from pymaxlines._analysis import (
    _finish,
    _walk_error,
    analyze_file,
    report,
)
from pymaxlines._lines import (
    FUNCTION_DEF_TYPES,
    CodeLines,
    FunctionDefNode,
    _headers_end,
    _node_end,
    function_code_line_count,
    span_code_line_count,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from pymaxlines._analysis import Config, FileAnalysis

_COMPOUND_STMT_TYPES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.Try,
    ast.TryStar,
    ast.With,
    ast.AsyncWith,
    ast.Match,
)

_IMPORT_TYPES = (ast.Import, ast.ImportFrom)
_MAX_LABEL_LEN = 40

_RUN_LABELS: dict[str, str] = {"import": "imports", "code": "module-level code"}

_INDENT = "  "
_NO_TRUNK = "  "
_TRUNK = "│ "
_LAST_BRANCH = "└ "
_BRANCH = "├ "


@dataclass(frozen=True, slots=True)
class SizeEntry:
    """One node in the code-line breakdown tree."""

    label: str
    start: int
    end: int
    code_lines: int
    limit: int | None
    children: tuple[SizeEntry, ...]


@dataclass(frozen=True, slots=True)
class FileSize:
    """Aggregated code-line breakdown for a single file."""

    path: Path
    code_lines: int
    limit: int
    entries: tuple[SizeEntry, ...]


@dataclass(frozen=True, slots=True)
class _BuildContext:
    """Read-only state threaded through the entry-building recursion."""

    code_lines: CodeLines
    headers_end: dict[int, int]
    source_lines: Sequence[str]
    function_limit: int


def _sorted_children(children: list[SizeEntry]) -> tuple[SizeEntry, ...]:
    return tuple(sorted(children, key=attrgetter("start")))


def _block_label(node: ast.stmt, source_lines: Sequence[str]) -> str:
    """Truncates to ``_MAX_LABEL_LEN`` characters with a trailing ellipsis."""
    line_idx = node.lineno - 1
    raw = source_lines[line_idx].strip() if line_idx < len(source_lines) else ""
    if len(raw) > _MAX_LABEL_LEN:
        return raw[:_MAX_LABEL_LEN] + "…"
    return raw


def _compound_bodies(node: ast.stmt) -> list[list[ast.stmt]]:
    bodies = [b for a in ("body", "orelse", "finalbody") if (b := getattr(node, a, None))]
    bodies += [h.body for h in getattr(node, "handlers", ())]
    bodies += [c.body for c in getattr(node, "cases", ())]
    return bodies


def _has_nested_defs(node: ast.stmt) -> bool:
    """Return True if *node* contains any function or class definition."""
    return any(
        isinstance(n, (*FUNCTION_DEF_TYPES, ast.ClassDef)) for n in ast.walk(node) if n is not node
    )


def _decorated_start(node: FunctionDefNode | ast.ClassDef) -> int:
    """Return the line a def/class starts on, including any decorators."""
    if node.decorator_list:
        return min(d.lineno for d in node.decorator_list)
    return node.lineno


def _compound_children(node: ast.stmt, ctx: _BuildContext) -> list[SizeEntry]:
    children: list[SizeEntry] = []
    for sub_body in _compound_bodies(node):
        children.extend(_nested_children(sub_body, ctx))
    return children


def _nested_children(body: list[ast.stmt], ctx: _BuildContext) -> list[SizeEntry]:
    """Recurse into compound statements (``if``, ``try``, ``with``, etc.).

    Definitions hidden inside them are surfaced as child entries.
    """
    children: list[SizeEntry] = []
    for child in body:
        if isinstance(child, FUNCTION_DEF_TYPES):
            children.append(_function_entry(child, ctx))
        elif isinstance(child, ast.ClassDef):
            children.append(_class_entry(child, ctx))
        elif isinstance(child, _COMPOUND_STMT_TYPES):
            children.extend(_compound_children(child, ctx))
    return children


def _compound_entry(node: ast.stmt, ctx: _BuildContext) -> SizeEntry:
    end = _node_end(node)
    return SizeEntry(
        label=_block_label(node, ctx.source_lines),
        start=node.lineno,
        end=end,
        code_lines=span_code_line_count(node.lineno, end, ctx.code_lines),
        limit=None,
        children=_sorted_children(_compound_children(node, ctx)),
    )


def _block_entries(node: FunctionDefNode, ctx: _BuildContext) -> list[SizeEntry]:
    return [
        _compound_entry(child, ctx)
        for child in node.body
        if isinstance(child, _COMPOUND_STMT_TYPES)
    ]


def _function_entry(node: FunctionDefNode, ctx: _BuildContext) -> SizeEntry:
    end = _node_end(node)
    count = function_code_line_count(node, ctx.code_lines, ctx.headers_end)
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    label = f"{prefix} {node.name}"
    limit: int | None = ctx.function_limit if ctx.function_limit > 0 else None

    children = _nested_children(node.body, ctx)

    if ctx.function_limit > 0 and count > ctx.function_limit:
        children.extend(_block_entries(node, ctx))

    start = _decorated_start(node)

    return SizeEntry(
        label=label,
        start=start,
        end=end,
        code_lines=count,
        limit=limit,
        children=_sorted_children(children),
    )


def _class_entry(node: ast.ClassDef, ctx: _BuildContext) -> SizeEntry:
    start = _decorated_start(node)
    end = _node_end(node)
    count = span_code_line_count(start, end, ctx.code_lines)

    children = _nested_children(node.body, ctx)

    return SizeEntry(
        label=f"class {node.name}",
        start=start,
        end=end,
        code_lines=count,
        limit=None,
        children=_sorted_children(children),
    )


def _run_entry(
    run: list[ast.stmt],
    label: str,
    code_lines: CodeLines,
) -> SizeEntry | None:
    """Returns ``None`` when the run spans zero code lines."""
    start = run[0].lineno
    end = _node_end(run[-1])
    count = span_code_line_count(start, end, code_lines)
    if count == 0:
        return None
    return SizeEntry(
        label=label,
        start=start,
        end=end,
        code_lines=count,
        limit=None,
        children=(),
    )


def _stmt_kind(stmt: ast.stmt) -> str:
    """A compound statement without nested defs counts as plain code."""
    if isinstance(stmt, _IMPORT_TYPES):
        return "import"
    if isinstance(stmt, (*FUNCTION_DEF_TYPES, ast.ClassDef)):
        return "def"
    if isinstance(stmt, _COMPOUND_STMT_TYPES) and _has_nested_defs(stmt):
        return "compound"
    return "code"


def _build_entries(
    analysis: FileAnalysis,
    source_lines: Sequence[str],
) -> tuple[SizeEntry, ...]:
    ctx = _BuildContext(
        code_lines=analysis.code_lines,
        headers_end=_headers_end(analysis.header_ranges),
        source_lines=source_lines,
        function_limit=analysis.function_limit,
    )
    entries: list[SizeEntry] = []
    for kind, group in groupby(analysis.tree.body, key=_stmt_kind):
        stmts = list(group)
        if kind == "def":
            entries.extend(_nested_children(stmts, ctx))
        elif kind == "compound":
            entries.extend(_compound_entry(s, ctx) for s in stmts)
        else:
            entry = _run_entry(stmts, _RUN_LABELS[kind], ctx.code_lines)
            if entry is not None:
                entries.append(entry)
    return tuple(entries)


def _build_file_size(path: Path, analysis: FileAnalysis) -> FileSize:
    entries = _build_entries(analysis, analysis.source_lines)
    return FileSize(
        path=path,
        code_lines=len(analysis.code_lines),
        limit=analysis.file_limit,
        entries=entries,
    )


class _Row(NamedTuple):
    """One flattened line of a text-rendered breakdown."""

    span: str
    label: str
    count: str
    is_last_chain: tuple[bool, ...]


def _gutter(row: _Row) -> str:
    """Map ``is_last_chain`` to a gutter column per entry.

    Each middle entry selects a continuation bar or blank; the root
    (index 0) contributes no column, since depth-0 rows render no glyph;
    the final entry is consumed by the ``└``/``├`` choice on the next line.
    """
    if len(row.is_last_chain) == 1:
        return _INDENT
    parts = [_INDENT]
    parts.extend(_NO_TRUNK if is_last else _TRUNK for is_last in row.is_last_chain[1:-1])
    parts.append(_LAST_BRANCH if row.is_last_chain[-1] else _BRANCH)
    return "".join(parts)


def _format_file(file_size: FileSize) -> str:
    marker = "!" if file_size.code_lines > file_size.limit else ""
    header = f"{file_size.path}: {file_size.code_lines}/{file_size.limit} code lines{marker}"

    if not file_size.entries:
        return header

    rows: list[_Row] = []
    _collect_rows(file_size.entries, rows)

    span_width = max(len(row.span) for row in rows)
    prefixes = [f"{_gutter(row)}{row.span:<{span_width}}  {row.label}" for row in rows]
    count_width = max(len(row.count.removesuffix("!")) for row in rows)
    prefix_width = max(len(p) for p in prefixes)

    lines = [header]
    for prefix, row in zip(prefixes, rows, strict=True):
        if row.count.endswith("!"):
            base = row.count.removesuffix("!")
            lines.append(f"{prefix:<{prefix_width}}  {base:>{count_width}}!")
        else:
            lines.append(f"{prefix:<{prefix_width}}  {row.count:>{count_width}}")

    return "\n".join(lines)


def _collect_rows(
    entries: tuple[SizeEntry, ...],
    rows: list[_Row],
    is_last_chain: tuple[bool, ...] = (),
) -> None:
    last_idx = len(entries) - 1
    for idx, entry in enumerate(entries):
        span = f"{entry.start}-{entry.end}"
        if entry.limit is not None:
            marker = "!" if entry.code_lines > entry.limit else ""
            count_str = f"{entry.code_lines}/{entry.limit}{marker}"
        else:
            count_str = str(entry.code_lines)
        is_last = idx == last_idx
        child_chain = (*is_last_chain, is_last)
        rows.append(_Row(span, entry.label, count_str, child_chain))
        if entry.children:
            _collect_rows(entry.children, rows, child_chain)


def _collect_file_sizes(
    files: Sequence[Path],
    config: Config,
) -> tuple[list[FileSize], list[str]]:
    """Analyze every file and return its size breakdown.

    Diagnostics for unreadable/unparsable files and directive errors are
    collected alongside, in file order.
    """
    file_sizes: list[FileSize] = []
    error_messages: list[str] = []
    for path in files:
        analysis = analyze_file(path, config)
        if isinstance(analysis, str):
            error_messages.append(analysis)
            continue
        error_messages.extend(analysis.directives.errors)
        file_sizes.append(_build_file_size(path, analysis))

    def _sort_key(fs: FileSize) -> tuple[int, str]:
        return (-fs.code_lines, str(fs.path))

    file_sizes.sort(key=_sort_key)
    return file_sizes, error_messages


def run_sizes(
    files: Sequence[Path],
    walk_errors: Sequence[OSError],
    config: Config,
) -> int:
    """Print a code-line breakdown of every file and return an exit code.

    Diagnostics for unreadable/unparsable files are collected and printed
    after all listings, followed by the ``Found N errors.`` summary.
    """
    error_messages = [_walk_error(exc) for exc in walk_errors]

    file_sizes, analysis_errors = _collect_file_sizes(files, config)
    error_messages.extend(analysis_errors)

    output_parts = [_format_file(fs) for fs in file_sizes]

    if output_parts and sys.stdout is not None:
        if isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout.reconfigure(encoding="utf-8")
        # Write each file separately so a broken pipe raises on the next
        # write rather than being silently swallowed by a single large call.
        last = len(output_parts) - 1
        for idx, part in enumerate(output_parts):
            sys.stdout.write(part)
            sys.stdout.write("\n" if idx == last else "\n\n")

    return _finish(sum(report(msg) for msg in error_messages))
