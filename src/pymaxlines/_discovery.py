"""Discover ``.py`` files from paths given on the command line (or CWD)."""

from __future__ import annotations

import contextlib
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "node_modules",
        "__pycache__",
        ".tox",
        ".nox",
        ".eggs",
    }
)

_SKIP_DIR_GLOBS: tuple[str, ...] = (".venv*",)


def _is_skip_dir(name: str) -> bool:
    return name in SKIP_DIRS or any(fnmatch(name, pat) for pat in _SKIP_DIR_GLOBS)


def _is_excluded(candidates: Iterable[str], exclude: tuple[str, ...]) -> bool:
    return any(fnmatch(candidate, pat) for candidate in candidates for pat in exclude)


def _relative_paths(entry: Path, root: Path) -> tuple[str, str]:
    """Return *entry* relative to *root*, and re-rooted, both as posix strings for glob matching."""
    rel = entry.relative_to(root).as_posix()
    return rel, (root / rel).as_posix()


def _walk_directory(root: Path, exclude: tuple[str, ...]) -> tuple[list[Path], list[OSError]]:
    """Walk *root* and return discovered ``.py`` files in sorted order, plus any walk errors.

    Prunes skip directories and excluded directories in-place so ``Path.walk``
    never descends into them.  Symlinked directories are not followed.
    Directories that raise ``OSError`` while being listed (e.g. permission
    denied) are collected in the returned error list instead of being
    silently skipped.
    """
    results: list[Path] = []
    errors: list[OSError] = []
    for dirpath, dirnames, filenames in root.walk(on_error=errors.append):
        dirnames[:] = sorted(
            d
            for d in dirnames
            if not _is_skip_dir(d)
            and not (dirpath / d).is_symlink()
            and not _is_excluded((d, *_relative_paths(dirpath / d, root)), exclude)
        )

        for fname in sorted(filenames):
            if not fname.endswith(".py"):
                continue
            if not _is_excluded((fname, *_relative_paths(dirpath / fname, root)), exclude):
                results.append(dirpath / fname)
    return results, errors


def _explicit_path_excluded(path: Path, exclude: tuple[str, ...]) -> bool:
    """Check whether an explicitly passed path matches any exclude pattern.

    Builds prefixes from the path parts (``a``, ``a/migrations``,
    ``a/migrations/0001.py``) and checks each against the exclude globs using
    ``_is_excluded``.  This lets a directory-level glob like ``migrations``
    match a file deep inside that directory.

    For absolute paths, prefixes are built from the CWD-relative form when
    possible, so user globs written against relative paths still match and
    unrelated ancestor directories (e.g. a home directory named ``build``)
    are never tested.
    """
    candidate = path
    if path.is_absolute():
        with contextlib.suppress(ValueError):
            candidate = path.relative_to(Path.cwd())
    parts = candidate.parts
    for i, name in enumerate(parts, start=1):
        prefix = Path(*parts[:i]).as_posix()
        if _is_excluded((name, prefix), exclude):
            return True
    return False


def discover_files(
    paths: list[Path],
    exclude: tuple[str, ...],
    *,
    force_exclude: bool = False,
) -> tuple[list[Path], list[OSError]]:
    """Resolve *paths* into a flat list of files to check.

    When *paths* is empty, walks the current directory.

    When *force_exclude* is true, explicit arguments (both files and
    directories) are filtered through the exclude globs before processing.
    Directories that match are not walked; files that match are dropped.

    Returns ``(file_list, errors)`` where *errors* collects any ``OSError``
    raised while listing a directory (e.g. permission denied).  Duplicate
    paths (by resolved location) are reported only once, in first-seen order.
    """
    if not paths:
        paths = [Path()]

    result: list[Path] = []
    seen: set[Path] = set()
    errors: list[OSError] = []

    def _add_unseen(candidate: Path) -> None:
        resolved = candidate.resolve()
        if resolved not in seen:
            seen.add(resolved)
            result.append(candidate)

    for path in paths:
        if force_exclude and exclude and _explicit_path_excluded(path, exclude):
            continue
        if path.is_dir():
            files, walk_errors = _walk_directory(path, exclude)
            for f in files:
                _add_unseen(f)
            errors.extend(walk_errors)
        else:
            _add_unseen(path)

    return result, errors
