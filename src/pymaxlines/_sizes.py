"""Build and render a code-line breakdown of every file (--show-sizes mode)."""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from operator import attrgetter
from pathlib import Path
from typing import TYPE_CHECKING, Literal, NamedTuple

from pymaxlines._analysis import (
    _analysis_error,
    _finish,
    analyze_file,
    report,
)
from pymaxlines._lines import (
    FUNCTION_DEF_TYPES,
    _node_end,
    build_headers_by_def,
    function_code_line_count,
    span_code_line_count,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

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

type EntryKind = Literal["function", "class", "block", "imports", "code"]
type RunKind = Literal["import", "code"]

KIND_FUNCTION: EntryKind = "function"
KIND_CLASS: EntryKind = "class"
KIND_BLOCK: EntryKind = "block"
KIND_IMPORTS: EntryKind = "imports"
KIND_CODE: EntryKind = "code"

RUN_KIND_IMPORT: RunKind = "import"
RUN_KIND_CODE: RunKind = "code"


@dataclass(frozen=True, slots=True)
class SizeEntry:
    """One node in the code-line breakdown tree."""

    kind: EntryKind
    label: str
    start: int
    end: int
    code_lines: int
    limit: int | None
    children: tuple[SizeEntry, ...]
    name: str = ""


@dataclass(frozen=True, slots=True)
class FileSize:
    """Aggregated code-line breakdown for a single file."""

    path: Path
    code_lines: int
    limit: int
    entries: tuple[SizeEntry, ...]


def _block_label(node: ast.stmt, source_lines: Sequence[str]) -> str:
    """Build the display label for a compound-statement block entry.

    Returns the first physical line of the statement stripped of leading
    whitespace, truncated to ``_MAX_LABEL_LEN`` characters with a trailing
    ellipsis when cut.
    """
    line_idx = node.lineno - 1
    raw = source_lines[line_idx].strip() if line_idx < len(source_lines) else ""
    if len(raw) > _MAX_LABEL_LEN:
        return raw[:_MAX_LABEL_LEN] + "…"
    return raw


def _decorated_start(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> int:
    """Return the line a def/class starts on, including any decorators."""
    if node.decorator_list:
        return min(d.lineno for d in node.decorator_list)
    return node.lineno


def _nested_children(
    body: list[ast.stmt],
    code_lines: set[int] | frozenset[int],
    headers_by_def: dict[int, frozenset[int]],
    source_lines: Sequence[str],
    function_limit: int,
) -> list[SizeEntry]:
    """Build SizeEntry children for nested function and class definitions in a body."""
    children: list[SizeEntry] = []
    for child in body:
        if isinstance(child, FUNCTION_DEF_TYPES):
            children.append(
                _function_entry(child, code_lines, headers_by_def, source_lines, function_limit)
            )
        elif isinstance(child, ast.ClassDef):
            children.append(
                _class_entry(child, code_lines, headers_by_def, source_lines, function_limit)
            )
    return children


def _block_entries(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    code_lines: set[int] | frozenset[int],
    source_lines: Sequence[str],
) -> list[SizeEntry]:
    """Build block SizeEntry children for the compound statements in *node*'s body."""
    entries: list[SizeEntry] = []
    for child in node.body:
        if not isinstance(child, _COMPOUND_STMT_TYPES):
            continue
        block_end = _node_end(child)
        block_count = span_code_line_count(child.lineno, block_end, code_lines)
        entries.append(
            SizeEntry(
                kind=KIND_BLOCK,
                label=_block_label(child, source_lines),
                start=child.lineno,
                end=block_end,
                code_lines=block_count,
                limit=None,
                children=(),
            )
        )
    return entries


def _function_entry(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    code_lines: set[int] | frozenset[int],
    headers_by_def: dict[int, frozenset[int]],
    source_lines: Sequence[str],
    function_limit: int,
) -> SizeEntry:
    """Build a SizeEntry for a function node, with nested children and optional blocks."""
    end = _node_end(node)
    count = function_code_line_count(node, code_lines, headers_by_def)
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    label = f"{prefix} {node.name}"
    limit: int | None = function_limit if function_limit > 0 else None

    children = _nested_children(node.body, code_lines, headers_by_def, source_lines, function_limit)

    if function_limit > 0 and count > function_limit:
        children.extend(_block_entries(node, code_lines, source_lines))

    start = _decorated_start(node)

    return SizeEntry(
        kind=KIND_FUNCTION,
        label=label,
        start=start,
        end=end,
        code_lines=count,
        limit=limit,
        children=tuple(sorted(children, key=attrgetter("start"))),
        name=node.name,
    )


def _class_entry(
    node: ast.ClassDef,
    code_lines: set[int] | frozenset[int],
    headers_by_def: dict[int, frozenset[int]],
    source_lines: Sequence[str],
    function_limit: int,
) -> SizeEntry:
    """Build a SizeEntry for a class node with nested function and class children."""
    start = _decorated_start(node)
    end = _node_end(node)
    count = span_code_line_count(start, end, code_lines)

    children = _nested_children(node.body, code_lines, headers_by_def, source_lines, function_limit)

    return SizeEntry(
        kind=KIND_CLASS,
        label=f"class {node.name}",
        start=start,
        end=end,
        code_lines=count,
        limit=None,
        children=tuple(sorted(children, key=attrgetter("start"))),
        name=node.name,
    )


def _run_entry(
    run: list[ast.stmt],
    run_kind: RunKind,
    code_lines: set[int] | frozenset[int],
) -> SizeEntry | None:
    """Build a SizeEntry for a consecutive run of imports or module-level code.

    Returns ``None`` when the run spans zero code lines.
    """
    first = run[0]
    last = run[-1]
    start = first.lineno
    end = _node_end(last)
    count = span_code_line_count(start, end, code_lines)
    if count == 0:
        return None
    kind, label = (
        (KIND_IMPORTS, "imports")
        if run_kind == RUN_KIND_IMPORT
        else (KIND_CODE, "module-level code")
    )
    return SizeEntry(
        kind=kind,
        label=label,
        start=start,
        end=end,
        code_lines=count,
        limit=None,
        children=(),
    )


def _def_entry(
    stmt: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    code_lines: set[int] | frozenset[int],
    headers_by_def: dict[int, frozenset[int]],
    source_lines: Sequence[str],
    function_limit: int,
) -> SizeEntry:
    """Build a SizeEntry for a top-level function or class definition."""
    if isinstance(stmt, FUNCTION_DEF_TYPES):
        return _function_entry(stmt, code_lines, headers_by_def, source_lines, function_limit)
    return _class_entry(stmt, code_lines, headers_by_def, source_lines, function_limit)


def _build_entries(
    analysis: FileAnalysis,
    source_lines: Sequence[str],
) -> tuple[SizeEntry, ...]:
    """Build top-level SizeEntry nodes from a file's AST and code-line data."""
    headers_by_def = build_headers_by_def(analysis.header_ranges)
    entries: list[SizeEntry] = []
    run: list[ast.stmt] = []
    run_kind: RunKind | None = None

    def _flush_run() -> None:
        if run and run_kind is not None:
            entry = _run_entry(run, run_kind, analysis.code_lines)
            if entry is not None:
                entries.append(entry)

    def _start_run(kind: RunKind | None) -> None:
        nonlocal run, run_kind
        _flush_run()
        run = []
        run_kind = kind

    for stmt in analysis.tree.body:
        if isinstance(stmt, _IMPORT_TYPES):
            if run_kind != RUN_KIND_IMPORT:
                _start_run(RUN_KIND_IMPORT)
            run.append(stmt)
        elif isinstance(stmt, (*FUNCTION_DEF_TYPES, ast.ClassDef)):
            _start_run(None)
            entries.append(
                _def_entry(
                    stmt,
                    analysis.code_lines,
                    headers_by_def,
                    source_lines,
                    analysis.function_limit,
                )
            )
        else:
            if run_kind != RUN_KIND_CODE:
                _start_run(RUN_KIND_CODE)
            run.append(stmt)

    _flush_run()
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

    depth: int
    span: str
    label: str
    count: str


def _format_file(file_size: FileSize) -> str:
    """Render a single file's breakdown to text."""
    header = f"{file_size.path}: {file_size.code_lines} code lines (limit {file_size.limit}"
    if file_size.code_lines > file_size.limit:
        header += f", over by {file_size.code_lines - file_size.limit}"
    header += ")"

    if not file_size.entries:
        return header

    rows: list[_Row] = []
    _collect_rows(file_size.entries, 0, rows)

    count_width = max(len(row.count) for row in rows)
    # Compute how wide the prefix (indent + span + gap + label) needs to be so
    # the right-aligned count column lands in the same position for every row.
    prefix_width = max(2 * (row.depth + 1) + len(row.span) + 2 + len(row.label) for row in rows)

    lines = [header]
    for row in rows:
        indent = "  " * (row.depth + 1)
        prefix = f"{indent}{row.span}  {row.label}"
        lines.append(f"{prefix:<{prefix_width}}  {row.count:>{count_width}}")

    return "\n".join(lines)


def _collect_rows(
    entries: tuple[SizeEntry, ...],
    depth: int,
    rows: list[_Row],
) -> None:
    """Flatten entries into ``_Row`` records."""
    for entry in entries:
        span = f"{entry.start}-{entry.end}"
        if entry.kind == KIND_FUNCTION and entry.limit is not None:
            count_str = f"{entry.code_lines}/{entry.limit}"
        else:
            count_str = str(entry.code_lines)
        rows.append(_Row(depth, span, entry.label, count_str))
        if entry.children:
            _collect_rows(entry.children, depth + 1, rows)


def _collect_file_sizes(
    files: Sequence[Path],
    config: Config,
) -> tuple[list[FileSize], list[str]]:
    """Analyze every file, returning built ``FileSize`` entries sorted for display.

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
    error_messages = [_analysis_error(Path(exc.filename), "read", exc) for exc in walk_errors]

    if not files:
        sys.stderr.write("warning: no .py files found\n")
        return _finish(sum(report(msg) for msg in error_messages))

    file_sizes, analysis_errors = _collect_file_sizes(files, config)
    error_messages.extend(analysis_errors)

    output_parts = [_format_file(fs) for fs in file_sizes]

    if output_parts:
        sys.stdout.write("\n\n".join(output_parts) + "\n")

    error_count = 0
    for msg in error_messages:
        error_count += report(msg)

    return _finish(error_count)
