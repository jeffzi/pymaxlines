"""Discover ``.py`` files from paths given on the command line (or CWD)."""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

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


def _is_excluded(name: str, rel_path: str, reported_path: str, exclude: tuple[str, ...]) -> bool:
    return any(
        fnmatch(rel_path, pat) or fnmatch(name, pat) or fnmatch(reported_path, pat)
        for pat in exclude
    )


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
            and not _is_excluded(
                d,
                (dirpath / d).relative_to(root).as_posix(),
                (root / (dirpath / d).relative_to(root)).as_posix(),
                exclude,
            )
        )

        for fname in sorted(filenames):
            if not fname.endswith(".py"):
                continue
            rel_file = (dirpath / fname).relative_to(root).as_posix()
            reported_file = (root / rel_file).as_posix()
            if not _is_excluded(fname, rel_file, reported_file, exclude):
                results.append(dirpath / fname)
    return results, errors


def discover_files(
    paths: list[Path],
    exclude: tuple[str, ...],
) -> tuple[list[Path], list[OSError]]:
    """Resolve *paths* into a flat list of files to check.

    When *paths* is empty, walks the current directory.

    Returns ``(file_list, errors)`` where *errors* collects any ``OSError``
    raised while listing a directory (e.g. permission denied).  Duplicate
    paths (by resolved location) are reported only once, in first-seen order.
    """
    if not paths:
        paths = [Path()]

    result: list[Path] = []
    seen: set[Path] = set()
    errors: list[OSError] = []

    for path in paths:
        if path.is_dir():
            files, walk_errors = _walk_directory(path, exclude)
            for f in files:
                resolved = f.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    result.append(f)
            errors.extend(walk_errors)
        else:
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                result.append(path)

    return result, errors
