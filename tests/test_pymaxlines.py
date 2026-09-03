from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
from conftest import CODE_LINE, INDENTED_CODE_LINE, write_module

from pymaxlines import MAX_LINES_PER_FUNCTION, MAX_LINES_SRC, MAX_LINES_TEST, main

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def _write_code_lines(tmp_path: Path, count: int, name: str = "module.py") -> Path:
    return write_module(tmp_path, CODE_LINE * count, name)


def _write_function(tmp_path: Path, code_lines: int, name: str = "module.py") -> Path:
    return write_module(tmp_path, "def big():\n" + INDENTED_CODE_LINE * (code_lines - 1), name)


# ---------------------------------------------------------------------------
# main — file-level limits
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("relative_path", "code_lines", "expected_exit"),
    [
        pytest.param("module.py", MAX_LINES_SRC, 0, id="src-at-limit"),
        pytest.param("tests/test_module.py", MAX_LINES_TEST + 1, 1, id="test-over-limit"),
    ],
)
def test_main_when_file_hits_limit_boundary_does_return_expected_exit(
    tmp_path: Path, relative_path: str, code_lines: int, expected_exit: int
) -> None:
    file = _write_code_lines(tmp_path, code_lines, relative_path)

    exit_code = main([str(file)])

    assert exit_code == expected_exit


@pytest.mark.parametrize(
    "relative_path",
    [
        pytest.param("test_module.py", id="test-prefix"),
        pytest.param("module_test.py", id="test-suffix"),
        pytest.param("tests/module.py", id="tests-dir"),
    ],
)
def test_main_when_path_marks_a_test_file_does_apply_the_test_limit(
    tmp_path: Path, relative_path: str
) -> None:
    file = _write_code_lines(tmp_path, MAX_LINES_SRC + 1, relative_path)

    exit_code = main([str(file)])

    assert exit_code == 0


def test_main_when_over_limit_does_report_path_count_and_limit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file = _write_code_lines(tmp_path, MAX_LINES_SRC + 1)

    exit_code = main([str(file)])

    assert exit_code == 1
    assert (
        capsys.readouterr().out == f"{file}: {MAX_LINES_SRC + 1} code lines (max {MAX_LINES_SRC})\n"
    )


# ---------------------------------------------------------------------------
# main — non-code content exclusion (file-level)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(
            "# comment\n\nx = 1\n" * MAX_LINES_SRC,
            id="comments-and-blanks",
        ),
        pytest.param(
            CODE_LINE * (MAX_LINES_SRC - 4) + 's = """\na\n\nb\n"""\n',
            id="blank-in-multiline-string",
        ),
        pytest.param(
            '"""Module\ndocstring\nhere."""\n' + CODE_LINE * MAX_LINES_SRC,
            id="module-docstring",
        ),
        pytest.param(
            '"""First.\n\nThird.\n"""\n' + CODE_LINE * MAX_LINES_SRC,
            id="docstring-with-blank-lines",
        ),
        pytest.param(
            'class C:\n    """Docstring."""\n' + INDENTED_CODE_LINE * (MAX_LINES_SRC - 1),
            id="class-docstring",
        ),
    ],
)
def test_main_when_non_code_content_present_does_not_count_it(tmp_path: Path, content: str) -> None:
    file = write_module(tmp_path, content)

    exit_code = main([str(file)])

    assert exit_code == 0


@pytest.mark.parametrize(
    "tail",
    [
        pytest.param('s = """\na\nb\n"""\n', id="plain-string"),
        pytest.param('s = f"""\n{1}\nb\n"""\n', id="f-string"),
    ],
)
def test_main_when_multiline_string_present_does_count_every_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], tail: str
) -> None:
    file = write_module(tmp_path, CODE_LINE * (MAX_LINES_SRC - 2) + tail)

    exit_code = main([str(file)])

    assert exit_code == 1
    assert f"{MAX_LINES_SRC + 2} code lines (max {MAX_LINES_SRC})" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# main — unreadable files
# ---------------------------------------------------------------------------


def _missing_file(tmp_path: Path) -> Path:
    return tmp_path / "absent.py"


def _broken_file(tmp_path: Path) -> Path:
    return write_module(tmp_path, 'x = "unterminated\n', "broken.py")


@pytest.mark.parametrize(
    "make_file",
    [
        pytest.param(_missing_file, id="missing-file"),
        pytest.param(_broken_file, id="tokenize-error"),
    ],
)
def test_main_when_file_cannot_be_read_does_report_error_and_return_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_file: Callable[[Path], Path]
) -> None:
    file = make_file(tmp_path)

    exit_code = main([str(file)])

    assert exit_code == 1
    out = capsys.readouterr().out
    assert out.startswith(f"{file}: could not read (")
    assert out.endswith(")\n")


def test_main_when_a_file_cannot_be_read_does_still_check_later_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = _missing_file(tmp_path)
    big = _write_code_lines(tmp_path, MAX_LINES_SRC + 1, "big.py")

    exit_code = main([str(missing), str(big)])

    assert exit_code == 1
    out = capsys.readouterr().out
    assert f"{missing}: could not read (" in out
    assert f"{big}: {MAX_LINES_SRC + 1} code lines (max {MAX_LINES_SRC})\n" in out


def test_main_when_multiple_files_does_report_only_offenders(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = _write_code_lines(tmp_path, 10, "small.py")
    bad = _write_code_lines(tmp_path, MAX_LINES_SRC + 1, "big.py")

    exit_code = main([str(good), str(bad)])

    assert exit_code == 1
    out = capsys.readouterr().out
    assert str(bad) in out
    assert str(good) not in out


# ---------------------------------------------------------------------------
# main — CLI flag overrides
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("relative_path", "code_lines", "argv_prefix", "expected_exit"),
    [
        pytest.param(
            "module.py",
            MAX_LINES_SRC + 1,
            ["--max-lines", str(MAX_LINES_SRC + 1)],
            0,
            id="raised-src",
        ),
        pytest.param("test_module.py", 11, ["--max-lines-test", "10"], 1, id="lowered-test"),
    ],
)
def test_main_when_max_lines_flags_given_does_override_defaults(
    tmp_path: Path,
    relative_path: str,
    code_lines: int,
    argv_prefix: list[str],
    expected_exit: int,
) -> None:
    file = _write_code_lines(tmp_path, code_lines, relative_path)

    exit_code = main([*argv_prefix, str(file)])

    assert exit_code == expected_exit


# ---------------------------------------------------------------------------
# main — negative line-limit rejection
# ---------------------------------------------------------------------------

_LIMIT_FLAG_PARAMS = [
    pytest.param("--max-lines", id="max-lines"),
    pytest.param("--max-lines-test", id="max-lines-test"),
    pytest.param("--max-lines-per-function", id="max-lines-per-function"),
    pytest.param("--max-lines-per-function-test", id="max-lines-per-function-test"),
]


@pytest.mark.parametrize("flag", _LIMIT_FLAG_PARAMS)
def test_main_when_negative_line_limit_given_does_exit_two(tmp_path: Path, flag: str) -> None:
    file = _write_code_lines(tmp_path, 1)

    with pytest.raises(SystemExit) as exc_info:
        main([flag, "-1", str(file)])

    assert exc_info.value.code == 2


@pytest.mark.parametrize("flag", _LIMIT_FLAG_PARAMS)
def test_main_when_zero_line_limit_given_does_accept_it(tmp_path: Path, flag: str) -> None:
    file = write_module(tmp_path, "")

    exit_code = main([flag, "0", str(file)])

    assert exit_code == 0


# ---------------------------------------------------------------------------
# main — per-function limits
# ---------------------------------------------------------------------------


def test_main_when_function_exceeds_limit_does_report_name_line_and_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file = _write_function(tmp_path, MAX_LINES_PER_FUNCTION + 1)

    exit_code = main([str(file)])

    assert exit_code == 1
    out = capsys.readouterr().out
    assert out == (
        f"{file}:1: function 'big' has {MAX_LINES_PER_FUNCTION + 1} code lines"
        f" (max {MAX_LINES_PER_FUNCTION})\n"
    )


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(
            "def big():\n    # comment\n\n" + INDENTED_CODE_LINE * (MAX_LINES_PER_FUNCTION - 1),
            id="comments-and-blanks",
        ),
        pytest.param(
            'def big():\n    """Function\n    docstring\n    here."""\n'
            + INDENTED_CODE_LINE * (MAX_LINES_PER_FUNCTION - 1),
            id="function-docstring",
        ),
    ],
)
def test_main_when_function_has_non_code_content_does_not_count_it(
    tmp_path: Path, content: str
) -> None:
    file = write_module(tmp_path, content)

    exit_code = main([str(file)])

    assert exit_code == 0


@pytest.mark.parametrize(
    ("relative_path", "argv_prefix", "expected_exit"),
    [
        pytest.param("test_module.py", [], 0, id="test-file-skipped-by-default"),
        pytest.param(
            "test_module.py",
            ["--max-lines-per-function-test", str(MAX_LINES_PER_FUNCTION)],
            1,
            id="test-flag-enables",
        ),
        pytest.param("module.py", ["--max-lines-per-function", "0"], 0, id="zero-disables"),
    ],
)
def test_main_when_function_limit_flags_vary_does_gate_the_check(
    tmp_path: Path, relative_path: str, argv_prefix: list[str], expected_exit: int
) -> None:
    file = _write_function(tmp_path, MAX_LINES_PER_FUNCTION + 1, relative_path)

    exit_code = main([*argv_prefix, str(file)])

    assert exit_code == expected_exit


# ---------------------------------------------------------------------------
# main — skip-* toggle flags (file-level)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("flag", "content"),
    [
        pytest.param(
            "--no-skip-blank-lines",
            "x = 1\n\n" * 5 + CODE_LINE * (MAX_LINES_SRC - 5),
            id="blank-lines",
        ),
        pytest.param(
            "--no-skip-comments",
            "# comment\n" * 5 + CODE_LINE * MAX_LINES_SRC,
            id="comment-lines",
        ),
        pytest.param(
            "--no-skip-docstrings",
            '"""Module\ndocstring\nhere."""\n' + CODE_LINE * MAX_LINES_SRC,
            id="docstring-lines",
        ),
    ],
)
def test_main_when_no_skip_flag_given_does_count_non_code_content(
    tmp_path: Path, flag: str, content: str
) -> None:
    file = write_module(tmp_path, content)

    exit_code = main([flag, str(file)])

    assert exit_code == 1


def test_main_when_all_no_skip_flags_given_does_count_every_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    content = '"""Docstring."""\n# comment\n\n' + CODE_LINE * MAX_LINES_SRC
    file = write_module(tmp_path, content)

    exit_code = main(
        [
            "--no-skip-blank-lines",
            "--no-skip-comments",
            "--no-skip-docstrings",
            str(file),
        ]
    )

    assert exit_code == 1
    assert f"{MAX_LINES_SRC + 3} code lines (max {MAX_LINES_SRC})" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# main — skip-* toggle flags (per-function)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("flag", "content"),
    [
        pytest.param(
            "--no-skip-blank-lines",
            "def big():\n\n\n" + INDENTED_CODE_LINE * (MAX_LINES_PER_FUNCTION - 1),
            id="blank-lines",
        ),
        pytest.param(
            "--no-skip-comments",
            "def big():\n    # a\n    # b\n" + INDENTED_CODE_LINE * (MAX_LINES_PER_FUNCTION - 1),
            id="comment-lines",
        ),
        pytest.param(
            "--no-skip-docstrings",
            'def big():\n    """Function\n    docstring."""\n'
            + INDENTED_CODE_LINE * (MAX_LINES_PER_FUNCTION - 1),
            id="docstring-lines",
        ),
    ],
)
def test_main_when_no_skip_flag_given_does_count_non_code_in_function(
    tmp_path: Path, flag: str, content: str
) -> None:
    file = write_module(tmp_path, content)

    exit_code = main([flag, str(file)])

    assert exit_code == 1


# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------


def test_main_when_argv_omitted_does_read_sys_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = _write_code_lines(tmp_path, MAX_LINES_SRC + 1)
    monkeypatch.setattr(sys, "argv", ["pymaxlines", str(file)])

    exit_code = main()

    assert exit_code == 1


def test_main_when_help_flag_does_show_report_unused_disable_directives(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
    assert "--report-unused-disable-directives" in capsys.readouterr().out


def test_module_entry_when_file_over_limit_does_exit_one(tmp_path: Path) -> None:
    file = _write_code_lines(tmp_path, MAX_LINES_SRC + 1)

    result = subprocess.run(  # noqa: S603 — fixed interpreter and args, no shell
        [sys.executable, "-m", "pymaxlines", str(file)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert f"{file}: {MAX_LINES_SRC + 1} code lines" in result.stdout
