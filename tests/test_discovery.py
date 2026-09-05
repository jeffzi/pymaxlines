"""Tests for file discovery: no-argument runs, directory walks, --exclude, and edge cases."""

from __future__ import annotations

import os
import textwrap
from typing import TYPE_CHECKING

import pytest
from conftest import CODE_LINE, capture_main, file_diagnostic, write_code_lines, write_module

from pymaxlines import MAX_LINES_SRC, MAX_LINES_TEST, main

if TYPE_CHECKING:
    from pathlib import Path


def _posix(text: str) -> str:
    """Normalize Windows path separators to POSIX for portable assertions."""
    return text.replace(os.sep, "/")


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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "pkg/big.py")
    monkeypatch.chdir(tmp_path)

    exit_code, output = capture_main([])

    assert exit_code == 1
    assert _posix(output.strip()) == file_diagnostic(MAX_LINES_SRC + 1, path="pkg/big.py")


def test_discover_when_no_args_and_clean_tree_does_exit_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_code_lines(tmp_path, 1, "ok.py")
    write_code_lines(tmp_path, 1, "sub/also_ok.py")
    monkeypatch.chdir(tmp_path)

    exit_code, output = capture_main([])

    assert exit_code == 0
    assert output == ""


# ---------------------------------------------------------------------------
# Behavior 2: directory arguments walked recursively; order preserved
# ---------------------------------------------------------------------------


def test_discover_when_directory_arg_does_walk_recursively_and_report_joined_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "src/pkg/big.py")
    monkeypatch.chdir(tmp_path)

    exit_code, output = capture_main(["src/"])

    assert exit_code == 1
    assert _posix(output.strip()) == file_diagnostic(MAX_LINES_SRC + 1, path="src/pkg/big.py")


def test_discover_when_multiple_directory_args_does_walk_in_given_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "beta/fail.py")
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "alpha/fail.py")
    monkeypatch.chdir(tmp_path)

    _exit_code, output = capture_main(["beta", "alpha"])

    lines = _posix(output).strip().splitlines()
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, skip_dir: str
) -> None:
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, f"{skip_dir}/bad.py")
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "found.py")
    monkeypatch.chdir(tmp_path)

    exit_code, output = capture_main([])

    assert exit_code == 1
    assert "found.py" in output
    assert skip_dir not in output


def test_discover_when_skip_directory_nested_deeply_does_not_check_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "a/b/.venv/bad.py")
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "a/found.py")
    monkeypatch.chdir(tmp_path)

    exit_code, output = capture_main([])

    assert exit_code == 1
    assert "a/found.py" in _posix(output)
    assert ".venv" not in output


# ---------------------------------------------------------------------------
# Behavior 4: --exclude flag and config exclude
# ---------------------------------------------------------------------------


def test_discover_when_exclude_glob_matches_file_does_skip_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "src/generated/auto.py")
    write_code_lines(tmp_path, 1, "src/real.py")
    monkeypatch.chdir(tmp_path)

    exit_code, _output = capture_main(["--exclude", "src/generated/*.py"])

    assert exit_code == 0


def test_discover_when_exclude_matches_final_component_does_skip_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "migrations/0001.py")
    write_code_lines(tmp_path, 1, "app.py")
    monkeypatch.chdir(tmp_path)

    exit_code, _output = capture_main(["--exclude", "migrations"])

    assert exit_code == 0


def test_discover_when_multiple_exclude_flags_does_skip_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "gen/auto.py")
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "vendor/lib.py")
    write_code_lines(tmp_path, 1, "app.py")
    monkeypatch.chdir(tmp_path)

    exit_code, _output = capture_main(["--exclude", "gen", "--exclude", "vendor"])

    assert exit_code == 0


def test_discover_when_cli_exclude_does_replace_config_exclude(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent("""\
        [tool.pymaxlines]
        exclude = ["conf_excluded"]
    """)
    )
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "conf_excluded/bad.py")
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "cli_excluded/bad.py")
    monkeypatch.chdir(tmp_path)

    _exit_code, output = capture_main(["--exclude", "cli_excluded"])

    assert "conf_excluded/bad.py" in _posix(output)
    assert "cli_excluded" not in _posix(output)


def test_discover_when_config_exclude_and_no_cli_exclude_does_use_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent("""\
        [tool.pymaxlines]
        exclude = ["conf_excluded"]
    """)
    )
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "conf_excluded/bad.py")
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "visible.py")
    monkeypatch.chdir(tmp_path)

    exit_code, output = capture_main([])

    assert exit_code == 1
    assert "visible.py" in output
    assert "conf_excluded" not in output


# ---------------------------------------------------------------------------
# Behavior 5: explicit file paths bypass skip dirs and exclude globs
# ---------------------------------------------------------------------------


def test_discover_when_explicit_file_in_skip_dir_does_check_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = write_code_lines(tmp_path, MAX_LINES_SRC + 1, ".venv/bad.py")
    monkeypatch.chdir(tmp_path)

    exit_code, _output = capture_main([str(target)])

    assert exit_code == 1


def test_discover_when_explicit_file_matches_exclude_does_check_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = write_code_lines(tmp_path, MAX_LINES_SRC + 1, "generated/auto.py")
    monkeypatch.chdir(tmp_path)

    exit_code, _output = capture_main(["--exclude", "generated", str(target)])

    assert exit_code == 1


def test_discover_when_explicit_file_without_py_suffix_does_check_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = CODE_LINE * (MAX_LINES_SRC + 1)
    target = write_module(tmp_path, content, "script")
    monkeypatch.chdir(tmp_path)

    exit_code, _output = capture_main([str(target)])

    assert exit_code == 1


# ---------------------------------------------------------------------------
# Behavior 6: mixed file and directory arguments, order preserved
# ---------------------------------------------------------------------------


def test_discover_when_mixed_file_and_directory_args_does_report_in_argument_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    explicit = write_code_lines(tmp_path, MAX_LINES_SRC + 1, "explicit.py")
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "subdir/inner.py")
    monkeypatch.chdir(tmp_path)

    _exit_code, output = capture_main([str(explicit), "subdir"])

    lines = _posix(output).strip().splitlines()
    explicit_idx = _line_index(lines, "explicit.py")
    inner_idx = _line_index(lines, "subdir/inner.py")
    assert explicit_idx < inner_idx


# ---------------------------------------------------------------------------
# Behavior 7: discovered files within a directory are in sorted order
# ---------------------------------------------------------------------------


def test_discover_when_directory_has_multiple_files_does_report_in_sorted_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ["z.py", "a.py", "m.py"]:
        write_code_lines(tmp_path, MAX_LINES_SRC + 1, f"pkg/{name}")
    monkeypatch.chdir(tmp_path)

    _exit_code, output = capture_main(["pkg"])

    lines = _posix(output).strip().splitlines()
    reported = [line.split(":")[0] for line in lines if "pkg/" in line]
    assert len(reported) == 3
    assert reported == sorted(reported)


# ---------------------------------------------------------------------------
# Behavior 8: symlinked directories are not descended into
# ---------------------------------------------------------------------------


def test_discover_when_symlinked_directory_does_not_descend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    monkeypatch.chdir(tmp_path)

    exit_code, _output = capture_main(["pkg"])

    assert exit_code == 0


# ---------------------------------------------------------------------------
# Behavior 9: test-file detection applies to discovered paths
# ---------------------------------------------------------------------------


def test_discover_when_discovered_test_file_does_apply_test_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    count = MAX_LINES_SRC + 1
    write_code_lines(tmp_path, count, "tests/test_x.py")
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "src/over.py")
    monkeypatch.chdir(tmp_path)

    exit_code, output = capture_main([])

    assert exit_code == 1
    assert "src/over.py" in _posix(output)
    assert "test_x.py" not in output


# ---------------------------------------------------------------------------
# Behavior 10: empty discovery prints warning on stderr, exits 0
# ---------------------------------------------------------------------------


def test_discover_when_empty_tree_does_warn_no_py_files_and_exit_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)

    exit_code = main([])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no .py files" in captured.err.lower()


def test_discover_when_exclude_filters_everything_does_warn_no_py_files_and_exit_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "generated/auto.py")
    monkeypatch.chdir(tmp_path)

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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``pymaxlines src --exclude "src/generated/*.py"`` must exclude src/generated/auto.py.

    The glob should match the reported path (src/generated/auto.py), not
    just the path relative to the walk root (generated/auto.py).
    """
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "src/generated/auto.py")
    write_code_lines(tmp_path, 1, "src/real.py")
    monkeypatch.chdir(tmp_path)

    exit_code, output = capture_main(["src", "--exclude", "src/generated/*.py"])

    assert exit_code == 0
    assert "auto.py" not in output


def test_discover_when_config_exclude_glob_has_path_prefix_does_skip_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Config exclude behaves the same as --exclude for glob-with-prefix patterns."""
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent("""\
        [tool.pymaxlines]
        exclude = ["src/generated/*.py"]
    """)
    )
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "src/generated/auto.py")
    write_code_lines(tmp_path, 1, "src/real.py")
    monkeypatch.chdir(tmp_path)

    exit_code, output = capture_main(["src"])

    assert exit_code == 0
    assert "auto.py" not in output


def test_discover_when_exclude_glob_matches_directory_in_reported_path_does_prune(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``pymaxlines src --exclude "src/generated"`` should prune the directory."""
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "src/generated/auto.py")
    write_code_lines(tmp_path, 1, "src/real.py")
    monkeypatch.chdir(tmp_path)

    exit_code, output = capture_main(["src", "--exclude", "src/generated"])

    assert exit_code == 0
    assert "auto.py" not in output


# ---------------------------------------------------------------------------
# Behavior 12: overlapping arguments report each finding once
# ---------------------------------------------------------------------------


def test_discover_when_same_directory_given_twice_does_report_each_file_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "src/big.py")
    monkeypatch.chdir(tmp_path)

    _exit_code, output = capture_main(["src", "src"])

    lines = [line for line in _posix(output).strip().splitlines() if "big.py" in line]
    assert len(lines) == 1


def test_discover_when_file_also_found_via_directory_walk_does_report_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "src/big.py")
    monkeypatch.chdir(tmp_path)

    _exit_code, output = capture_main([".", "src/big.py"])

    lines = [line for line in _posix(output).strip().splitlines() if "big.py" in line]
    assert len(lines) == 1


def test_discover_when_overlapping_args_does_deduplicate_and_preserve_first_seen_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit file before directory walk: file appears once at its first position."""
    explicit = write_code_lines(tmp_path, MAX_LINES_SRC + 1, "src/big.py")
    write_code_lines(tmp_path, MAX_LINES_SRC + 1, "src/alpha.py")
    monkeypatch.chdir(tmp_path)

    _exit_code, output = capture_main([str(explicit), "src"])

    lines = _posix(output).strip().splitlines()
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
