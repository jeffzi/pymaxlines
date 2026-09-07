"""Tests for file discovery: no-argument runs, directory walks, --exclude, and edge cases."""

from __future__ import annotations

import os
import sys
import textwrap
from typing import TYPE_CHECKING

import pytest
from conftest import (
    CODE_LINE,
    capture_main,
    diagnostic_lines,
    file_diagnostic,
    write_code_lines,
    write_module,
)

from pymaxlines import MAX_LINES_SRC, MAX_LINES_TEST, main

if TYPE_CHECKING:
    from pathlib import Path


def _posix(text: str) -> str:
    """Normalize Windows path separators to POSIX for portable assertions."""
    return text.replace(os.sep, "/")


def _output_lines(output: str) -> list[str]:
    """Return the diagnostic lines of *output*, normalized to POSIX separators."""
    return diagnostic_lines(_posix(output))


# test_discover_when_discovered_test_file_does_apply_test_limits relies on this
# holding, so the same count lands over the src limit and under the test limit.
assert MAX_LINES_SRC + 1 <= MAX_LINES_TEST


def _line_index(lines: list[str], needle: str) -> int:
    """Return the index of the first line in *lines* containing *needle*."""
    return next(i for i, line in enumerate(lines) if needle in line)


# ---------------------------------------------------------------------------
# Behavior 1: no-argument invocation discovers *.py files under CWD
# ---------------------------------------------------------------------------


def test_discover_when_no_args_and_oversized_nested_file_does_report_relative_path(
    tmp_path: Path,
) -> None:
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "pkg/big.py")

    exit_code, output = capture_main([])

    assert exit_code == 1
    lines = _output_lines(output)
    assert lines == [file_diagnostic(MAX_LINES_SRC + 1, path="pkg/big.py")]


def test_discover_when_no_args_and_clean_tree_does_exit_zero(tmp_path: Path) -> None:
    write_code_lines(tmp_path, 1, "ok.py")
    write_code_lines(tmp_path, 1, "sub/also_ok.py")

    exit_code, output = capture_main([])

    assert exit_code == 0
    assert output == ""


# ---------------------------------------------------------------------------
# Behavior 2: directory arguments walked recursively; order preserved
# ---------------------------------------------------------------------------


def test_discover_when_directory_arg_does_walk_recursively_and_report_joined_path(
    tmp_path: Path,
) -> None:
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "src/pkg/big.py")

    exit_code, output = capture_main(["src/"])

    assert exit_code == 1
    lines = _output_lines(output)
    assert lines == [file_diagnostic(MAX_LINES_SRC + 1, path="src/pkg/big.py")]


def test_discover_when_multiple_directory_args_does_walk_in_given_order(tmp_path: Path) -> None:
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "beta/fail.py")
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "alpha/fail.py")

    _exit_code, output = capture_main(["beta", "alpha"])

    lines = _output_lines(output)
    beta_idx = _line_index(lines, "beta/fail.py")
    alpha_idx = _line_index(lines, "alpha/fail.py")
    assert beta_idx < alpha_idx


# ---------------------------------------------------------------------------
# Behavior 3: fixed skip directories are never checked
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "skip_dir",
    [
        ".git",
        ".venv",
        pytest.param(".venv-3.12", id="venv-with-suffix"),
        pytest.param(".venv312", id="venv-no-dash-suffix"),
        "node_modules",
        "__pycache__",
        ".tox",
        ".nox",
        ".eggs",
    ],
)
def test_discover_when_file_in_skip_directory_does_not_check_it(
    tmp_path: Path, skip_dir: str
) -> None:
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, f"{skip_dir}/bad.py")
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "found.py")

    exit_code, output = capture_main([])

    assert exit_code == 1
    assert "found.py" in output
    assert skip_dir not in output


def test_discover_when_skip_directory_nested_deeply_does_not_check_it(tmp_path: Path) -> None:
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "a/b/.venv/bad.py")
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "a/found.py")

    exit_code, output = capture_main([])

    assert exit_code == 1
    assert "a/found.py" in _posix(output)
    assert ".venv" not in output


# ---------------------------------------------------------------------------
# Behavior 4: --exclude flag and config exclude
# ---------------------------------------------------------------------------


def test_discover_when_exclude_glob_matches_file_does_skip_it(tmp_path: Path) -> None:
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "src/generated/auto.py")
    write_code_lines(tmp_path, 1, "src/real.py")

    exit_code, _output = capture_main(["--exclude", "src/generated/*.py"])

    assert exit_code == 0


def test_discover_when_exclude_matches_final_component_does_skip_directory(tmp_path: Path) -> None:
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "migrations/0001.py")
    write_code_lines(tmp_path, 1, "app.py")

    exit_code, _output = capture_main(["--exclude", "migrations"])

    assert exit_code == 0


def test_discover_when_multiple_exclude_flags_does_skip_all(tmp_path: Path) -> None:
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "gen/auto.py")
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "vendor/lib.py")
    write_code_lines(tmp_path, 1, "app.py")

    exit_code, _output = capture_main(["--exclude", "gen", "--exclude", "vendor"])

    assert exit_code == 0


def test_discover_when_cli_exclude_does_replace_config_exclude(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent("""\
        [tool.pymaxlines]
        exclude = ["conf_excluded"]
    """)
    )
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "conf_excluded/bad.py")
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "cli_excluded/bad.py")

    _exit_code, output = capture_main(["--exclude", "cli_excluded"])

    assert "conf_excluded/bad.py" in _posix(output)
    assert "cli_excluded" not in _posix(output)


def test_discover_when_config_exclude_and_no_cli_exclude_does_use_config(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent("""\
        [tool.pymaxlines]
        exclude = ["conf_excluded"]
    """)
    )
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "conf_excluded/bad.py")
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "visible.py")

    exit_code, output = capture_main([])

    assert exit_code == 1
    assert "visible.py" in output
    assert "conf_excluded" not in output


# ---------------------------------------------------------------------------
# Behavior 5: explicit file paths bypass skip dirs and exclude globs
# ---------------------------------------------------------------------------


def test_discover_when_explicit_file_in_skip_dir_does_check_it(tmp_path: Path) -> None:
    target = write_code_lines(tmp_path, MAX_LINES_SRC + 1, ".venv/bad.py")

    exit_code, _output = capture_main([str(target)])

    assert exit_code == 1


def test_discover_when_explicit_file_matches_exclude_does_check_it(tmp_path: Path) -> None:
    target = write_code_lines(tmp_path, MAX_LINES_SRC + 1, "generated/auto.py")

    exit_code, _output = capture_main(["--exclude", "generated", str(target)])

    assert exit_code == 1


def test_discover_when_explicit_file_without_py_suffix_does_check_it(tmp_path: Path) -> None:
    content = CODE_LINE * (MAX_LINES_SRC + 1)
    target = write_module(tmp_path, content, "script")

    exit_code, _output = capture_main([str(target)])

    assert exit_code == 1


# ---------------------------------------------------------------------------
# Behavior 6: mixed file and directory arguments, order preserved
# ---------------------------------------------------------------------------


def test_discover_when_mixed_file_and_directory_args_does_report_in_argument_order(
    tmp_path: Path,
) -> None:
    explicit = write_code_lines(tmp_path, MAX_LINES_SRC + 1, "explicit.py")
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "subdir/inner.py")

    _exit_code, output = capture_main([str(explicit), "subdir"])

    lines = _output_lines(output)
    explicit_idx = _line_index(lines, "explicit.py")
    inner_idx = _line_index(lines, "subdir/inner.py")
    assert explicit_idx < inner_idx


# ---------------------------------------------------------------------------
# Behavior 7: discovered files within a directory are in sorted order
# ---------------------------------------------------------------------------


def test_discover_when_directory_has_multiple_files_does_report_in_sorted_order(
    tmp_path: Path,
) -> None:
    for name in ["z.py", "a.py", "m.py"]:
        write_code_lines(tmp_path, MAX_LINES_SRC + 1, f"pkg/{name}")

    _exit_code, output = capture_main(["pkg"])

    lines = _output_lines(output)
    reported = [line.split(":")[0] for line in lines if "pkg/" in line]
    assert len(reported) == 3
    assert reported == sorted(reported)


# ---------------------------------------------------------------------------
# Behavior 8: symlinked directories are not descended into
# ---------------------------------------------------------------------------


def test_discover_when_symlinked_directory_does_not_descend(tmp_path: Path) -> None:
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "real/bad.py")

    link = tmp_path / "pkg" / "linked"
    (tmp_path / "pkg").mkdir()
    try:
        link.symlink_to(real_dir)
    except OSError:
        pytest.skip("symlink creation not permitted on this platform")

    write_code_lines(tmp_path, 1, "pkg/ok.py")

    exit_code, _output = capture_main(["pkg"])

    assert exit_code == 0


# ---------------------------------------------------------------------------
# Behavior 9: test-file detection applies to discovered paths
# ---------------------------------------------------------------------------


def test_discover_when_discovered_test_file_does_apply_test_limits(tmp_path: Path) -> None:
    count = MAX_LINES_SRC + 1
    write_code_lines(tmp_path, count, "tests/test_x.py")
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "src/over.py")

    exit_code, output = capture_main([])

    assert exit_code == 1
    assert "src/over.py" in _posix(output)
    assert "test_x.py" not in output


# ---------------------------------------------------------------------------
# Behavior 10: empty discovery prints warning on stderr, exits 0
# ---------------------------------------------------------------------------


def test_discover_when_empty_tree_does_warn_no_py_files_and_exit_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:

    exit_code = main([])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no .py files" in captured.err.lower()


def test_discover_when_exclude_filters_everything_does_warn_no_py_files_and_exit_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "generated/auto.py")

    exit_code = main(["--exclude", "generated"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no .py files" in captured.err.lower()


# ---------------------------------------------------------------------------
# Behavior 11: --exclude glob matches the reported path, not just the walk-
#              root-relative path
# ---------------------------------------------------------------------------


def test_discover_when_exclude_glob_includes_directory_arg_prefix_does_skip_file(
    tmp_path: Path,
) -> None:
    """``pymaxlines src --exclude "src/generated/*.py"`` must exclude src/generated/auto.py.

    The glob should match the reported path (src/generated/auto.py), not
    just the path relative to the walk root (generated/auto.py).
    """
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "src/generated/auto.py")
    write_code_lines(tmp_path, 1, "src/real.py")

    exit_code, output = capture_main(["src", "--exclude", "src/generated/*.py"])

    assert exit_code == 0
    assert "auto.py" not in output


def test_discover_when_config_exclude_glob_has_path_prefix_does_skip_file(tmp_path: Path) -> None:
    """Config exclude behaves the same as --exclude for glob-with-prefix patterns."""
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent("""\
        [tool.pymaxlines]
        exclude = ["src/generated/*.py"]
    """)
    )
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "src/generated/auto.py")
    write_code_lines(tmp_path, 1, "src/real.py")

    exit_code, output = capture_main(["src"])

    assert exit_code == 0
    assert "auto.py" not in output


def test_discover_when_exclude_glob_matches_directory_in_reported_path_does_prune(
    tmp_path: Path,
) -> None:
    """``pymaxlines src --exclude "src/generated"`` should prune the directory."""
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "src/generated/auto.py")
    write_code_lines(tmp_path, 1, "src/real.py")

    exit_code, output = capture_main(["src", "--exclude", "src/generated"])

    assert exit_code == 0
    assert "auto.py" not in output


# ---------------------------------------------------------------------------
# Behavior 12: overlapping arguments report each finding once
# ---------------------------------------------------------------------------


def test_discover_when_same_directory_given_twice_does_report_each_file_once(
    tmp_path: Path,
) -> None:
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "src/big.py")

    _exit_code, output = capture_main(["src", "src"])

    lines = [line for line in _output_lines(output) if "big.py" in line]
    assert len(lines) == 1


def test_discover_when_file_also_found_via_directory_walk_does_report_once(tmp_path: Path) -> None:
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "src/big.py")

    _exit_code, output = capture_main([".", "src/big.py"])

    lines = [line for line in _output_lines(output) if "big.py" in line]
    assert len(lines) == 1


def test_discover_when_overlapping_args_does_deduplicate_and_preserve_first_seen_order(
    tmp_path: Path,
) -> None:
    """Explicit file before directory walk: file appears once at its first position."""
    explicit = write_code_lines(tmp_path, MAX_LINES_SRC + 1, "src/big.py")
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "src/alpha.py")

    _exit_code, output = capture_main([str(explicit), "src"])

    lines = _output_lines(output)
    big_lines = [line for line in lines if "big.py" in line]
    assert len(big_lines) == 1
    big_idx = _line_index(lines, "big.py")
    alpha_idx = _line_index(lines, "alpha.py")
    assert big_idx < alpha_idx


# ---------------------------------------------------------------------------
# Behavior 13: --force-exclude applies exclude globs to explicit paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("target_name", "exclude_pattern"),
    [
        pytest.param("generated/auto.py", "generated/*.py", id="glob-matches-file"),
        pytest.param("migrations/0001_init.py", "migrations", id="dir-matches-parent"),
        pytest.param("app/migrations/0001_init.py", "migrations", id="dir-matches-ancestor"),
    ],
)
def test_discover_when_force_exclude_and_explicit_file_under_excluded_path_does_skip_it(
    tmp_path: Path, target_name: str, exclude_pattern: str
) -> None:
    target = write_code_lines(tmp_path, MAX_LINES_SRC + 1, target_name)

    exit_code, output = capture_main(["--force-exclude", "--exclude", exclude_pattern, str(target)])

    assert exit_code == 0
    assert output == ""


def test_discover_when_force_exclude_and_explicit_directory_matches_exclude_does_not_walk_it(
    tmp_path: Path,
) -> None:
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "migrations/0001.py")

    exit_code, output = capture_main(["--force-exclude", "--exclude", "migrations", "migrations"])

    assert exit_code == 0
    assert output == ""


def test_discover_when_force_exclude_and_non_matching_explicit_file_does_check_it(
    tmp_path: Path,
) -> None:
    target = write_code_lines(tmp_path, MAX_LINES_SRC + 1, "app/main.py")

    exit_code, _output = capture_main(["--force-exclude", "--exclude", "generated", str(target)])

    assert exit_code == 1


def test_discover_when_force_exclude_and_directory_walk_does_not_change_results(
    tmp_path: Path,
) -> None:
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "generated/auto.py")
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "src/app.py")

    exit_code, output = capture_main(["--force-exclude", "--exclude", "generated"])

    assert exit_code == 1
    assert "src/app.py" in _posix(output)
    assert "generated/auto.py" not in _posix(output)


# ---------------------------------------------------------------------------
# Behavior 14: --force-exclude with absolute path outside cwd tests filename
#              only, not ancestor components
# ---------------------------------------------------------------------------


def test_discover_when_force_exclude_and_absolute_path_outside_cwd_does_not_exclude_by_ancestor(
    tmp_path: Path,
) -> None:
    """An absolute path NOT under cwd has only its filename tested against globs.

    ``cwd=work``, ``--exclude build``, path ``/outside/build/proj/app.py``.
    ``build`` is an ancestor component outside cwd — it must NOT match the
    exclude glob.  The file should be checked.
    """
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    outside = tmp_path / "outside" / "build" / "proj"
    outside.mkdir(parents=True)
    target = outside / "app.py"
    target.write_text("x = 1\n" * (MAX_LINES_SRC + 1))

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.chdir(work_dir)
    try:
        exit_code, output = capture_main(["--force-exclude", "--exclude", "build", str(target)])
    finally:
        monkeypatch.undo()

    assert exit_code == 1
    assert "app.py" in output


def test_discover_when_force_exclude_and_absolute_path_outside_cwd_does_exclude_by_filename(
    tmp_path: Path,
) -> None:
    """An absolute path NOT under cwd is still excluded when its filename matches."""
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    outside = tmp_path / "outside" / "proj"
    outside.mkdir(parents=True)
    target = outside / "generated.py"
    target.write_text("x = 1\n" * (MAX_LINES_SRC + 1))

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.chdir(work_dir)
    try:
        exit_code, output = capture_main(
            ["--force-exclude", "--exclude", "generated*", str(target)]
        )
    finally:
        monkeypatch.undo()

    assert exit_code == 0
    assert output == ""


# ---------------------------------------------------------------------------
# Behavior 15: directory symlinks during walk are silently skipped
# ---------------------------------------------------------------------------


def test_discover_when_walk_encounters_symlink_to_directory_does_not_report_error(
    tmp_path: Path,
) -> None:
    """A ``.py``-named symlink pointing to a directory must be silently skipped.

    ``Path.walk(follow_symlinks=False)`` places symlinked directories in
    ``filenames``, not ``dirnames``.  Without filtering, the checker tries to
    open the symlink as a file and emits a ``could not read (Is a directory)``
    diagnostic.  The ``.py`` suffix is needed to trigger the bug — non-``.py``
    names are already filtered out before open.
    """
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    (real_dir / "inner.py").write_text("x = 1\n")

    pkg = tmp_path / "pkg"
    pkg.mkdir()
    link = pkg / "linked.py"
    try:
        link.symlink_to(real_dir)
    except OSError:
        pytest.skip("symlink creation not permitted on this platform")

    write_code_lines(tmp_path, 1, "pkg/ok.py")

    exit_code, output = capture_main(["pkg"])

    assert exit_code == 0
    assert "could not read" not in output
    assert "Is a directory" not in output


def test_discover_when_walk_encounters_symlink_to_file_does_check_it(
    tmp_path: Path,
) -> None:
    """A symlink to a regular .py file is still discovered and checked normally."""
    real_file = tmp_path / "real" / "source.py"
    real_file.parent.mkdir()
    real_file.write_text("x = 1\n" * (MAX_LINES_SRC + 1))

    pkg = tmp_path / "pkg"
    pkg.mkdir()
    link = pkg / "linked.py"
    try:
        link.symlink_to(real_file)
    except OSError:
        pytest.skip("symlink creation not permitted on this platform")

    exit_code, output = capture_main(["pkg"])

    assert exit_code == 1
    assert "linked.py" in output


# ---------------------------------------------------------------------------
# Behavior 16: overlapping arguments deduplicate walk errors
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    sys.platform == "win32" or getattr(os, "getuid", lambda: -1)() == 0,
    reason="Windows ignores POSIX permission bits; root bypasses them",
)
def test_discover_when_overlapping_args_hit_same_walk_error_does_report_once(
    tmp_path: Path,
) -> None:
    """``pymaxlines . src`` with unreadable ``src/restricted`` prints one error, not two."""
    restricted = tmp_path / "src" / "restricted"
    restricted.mkdir(parents=True)
    write_code_lines(tmp_path, 1, "src/ok.py")
    restricted.chmod(0o000)

    try:
        _exit_code, output = capture_main([".", "src"])
    finally:
        restricted.chmod(0o755)

    error_lines = [line for line in output.splitlines() if "restricted" in line]
    assert len(error_lines) == 1
