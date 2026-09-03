from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from pymaxlines import MAX_LINES_PER_FUNCTION, MAX_LINES_SRC, MAX_LINES_TEST, main

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_CODE_LINE = "x = 1\n"
_INDENTED_CODE_LINE = "    x = 1\n"


def _write_module(tmp_path: Path, content: str, name: str = "module.py") -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _write_code_lines(tmp_path: Path, count: int, name: str = "module.py") -> Path:
    return _write_module(tmp_path, _CODE_LINE * count, name)


def _write_function(tmp_path: Path, code_lines: int, name: str = "module.py") -> Path:
    return _write_module(tmp_path, "def big():\n" + _INDENTED_CODE_LINE * (code_lines - 1), name)


def _oversized_file_and_function(directive: str) -> str:
    return (
        directive
        + "def big():\n"
        + _INDENTED_CODE_LINE * (MAX_LINES_PER_FUNCTION + 1)
        + "\n"
        + _CODE_LINE * MAX_LINES_SRC
    )


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
            _CODE_LINE * (MAX_LINES_SRC - 4) + 's = """\na\n\nb\n"""\n',
            id="blank-in-multiline-string",
        ),
        pytest.param(
            '"""Module\ndocstring\nhere."""\n' + _CODE_LINE * MAX_LINES_SRC,
            id="module-docstring",
        ),
        pytest.param(
            'class C:\n    """Docstring."""\n' + _INDENTED_CODE_LINE * (MAX_LINES_SRC - 1),
            id="class-docstring",
        ),
        pytest.param(
            '"""First.\n\nThird.\n"""\n' + _CODE_LINE * MAX_LINES_SRC,
            id="docstring-with-blank-lines",
        ),
    ],
)
def test_main_when_non_code_content_present_does_not_count_it(tmp_path: Path, content: str) -> None:
    file = _write_module(tmp_path, content)

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
    file = _write_module(tmp_path, _CODE_LINE * (MAX_LINES_SRC - 2) + tail)

    exit_code = main([str(file)])

    assert exit_code == 1
    assert f"{MAX_LINES_SRC + 2} code lines (max {MAX_LINES_SRC})" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# main — unreadable files
# ---------------------------------------------------------------------------


def _missing_file(tmp_path: Path) -> Path:
    return tmp_path / "absent.py"


def _broken_file(tmp_path: Path) -> Path:
    return _write_module(tmp_path, 'x = "unterminated\n', "broken.py")


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


@pytest.mark.parametrize(
    "flag",
    [
        pytest.param("--max-lines", id="max-lines"),
        pytest.param("--max-lines-test", id="max-lines-test"),
        pytest.param("--max-lines-per-function", id="max-lines-per-function"),
        pytest.param("--max-lines-per-function-test", id="max-lines-per-function-test"),
    ],
)
def test_main_when_negative_line_limit_given_does_exit_two(tmp_path: Path, flag: str) -> None:
    file = _write_code_lines(tmp_path, 1)

    with pytest.raises(SystemExit) as exc_info:
        main([flag, "-1", str(file)])

    assert exc_info.value.code == 2


@pytest.mark.parametrize(
    "flag",
    [
        pytest.param("--max-lines", id="max-lines"),
        pytest.param("--max-lines-test", id="max-lines-test"),
        pytest.param("--max-lines-per-function", id="max-lines-per-function"),
        pytest.param("--max-lines-per-function-test", id="max-lines-per-function-test"),
    ],
)
def test_main_when_zero_line_limit_given_does_accept_it(tmp_path: Path, flag: str) -> None:
    file = _write_module(tmp_path, "")

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
            "def big():\n    # comment\n\n" + _INDENTED_CODE_LINE * (MAX_LINES_PER_FUNCTION - 1),
            id="comments-and-blanks",
        ),
        pytest.param(
            'def big():\n    """Function\n    docstring\n    here."""\n'
            + _INDENTED_CODE_LINE * (MAX_LINES_PER_FUNCTION - 1),
            id="function-docstring",
        ),
    ],
)
def test_main_when_function_has_non_code_content_does_not_count_it(
    tmp_path: Path, content: str
) -> None:
    file = _write_module(tmp_path, content)

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
            "x = 1\n\n" * 5 + _CODE_LINE * (MAX_LINES_SRC - 5),
            id="blank-lines",
        ),
        pytest.param(
            "--no-skip-comments",
            "# comment\n" * 5 + _CODE_LINE * MAX_LINES_SRC,
            id="comment-lines",
        ),
        pytest.param(
            "--no-skip-docstrings",
            '"""Module\ndocstring\nhere."""\n' + _CODE_LINE * MAX_LINES_SRC,
            id="docstring-lines",
        ),
    ],
)
def test_main_when_no_skip_flag_given_does_count_non_code_content(
    tmp_path: Path, flag: str, content: str
) -> None:
    file = _write_module(tmp_path, content)

    exit_code = main([flag, str(file)])

    assert exit_code == 1


def test_main_when_all_no_skip_flags_given_does_count_every_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    content = '"""Docstring."""\n# comment\n\n' + _CODE_LINE * MAX_LINES_SRC
    file = _write_module(tmp_path, content)

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
            "def big():\n\n\n" + _INDENTED_CODE_LINE * (MAX_LINES_PER_FUNCTION - 1),
            id="blank-lines",
        ),
        pytest.param(
            "--no-skip-comments",
            "def big():\n    # a\n    # b\n" + _INDENTED_CODE_LINE * (MAX_LINES_PER_FUNCTION - 1),
            id="comment-lines",
        ),
        pytest.param(
            "--no-skip-docstrings",
            'def big():\n    """Function\n    docstring."""\n'
            + _INDENTED_CODE_LINE * (MAX_LINES_PER_FUNCTION - 1),
            id="docstring-lines",
        ),
    ],
)
def test_main_when_no_skip_flag_given_does_count_non_code_in_function(
    tmp_path: Path, flag: str, content: str
) -> None:
    file = _write_module(tmp_path, content)

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


# ---------------------------------------------------------------------------
# directives — file-scope disable=max-lines
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(
            "# pymaxlines: disable=max-lines\n" + _CODE_LINE * (MAX_LINES_SRC + 1),
            id="before-first-statement",
        ),
        pytest.param(
            '"""Module docstring."""\n# pymaxlines: disable=max-lines\n'
            + _CODE_LINE * (MAX_LINES_SRC + 1),
            id="after-docstring",
        ),
        pytest.param(
            '# pymaxlines: disable=max-lines\n"""Module docstring."""\n'
            + _CODE_LINE * (MAX_LINES_SRC + 1),
            id="above-docstring",
        ),
    ],
)
def test_main_when_file_has_disable_max_lines_does_skip_file_check(
    tmp_path: Path, content: str
) -> None:
    file = _write_module(tmp_path, content)

    exit_code = main([str(file)])

    assert exit_code == 0


# ---------------------------------------------------------------------------
# directives — function-scope disable=max-lines-per-function
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(
            "def big():  # pymaxlines: disable=max-lines-per-function\n"
            + _INDENTED_CODE_LINE * (MAX_LINES_PER_FUNCTION + 1),
            id="plain-def",
        ),
        pytest.param(
            "def big(\n"
            "    a,\n"
            "    b,\n"
            "):  # pymaxlines: disable=max-lines-per-function\n"
            + _INDENTED_CODE_LINE
            * (MAX_LINES_PER_FUNCTION + 1),
            id="wrapped-signature",
        ),
        pytest.param(
            "class C:\n"
            "    def big(self):  # pymaxlines: disable=max-lines-per-function\n"
            + "        x = 1\n"
            * (MAX_LINES_PER_FUNCTION + 1),
            id="method",
        ),
        pytest.param(
            "def big():  # pymaxlines: disable\n"
            + _INDENTED_CODE_LINE * (MAX_LINES_PER_FUNCTION + 1),
            id="bare-disable",
        ),
        pytest.param(
            "def big():  # noqa: C901  # pymaxlines: disable=max-lines-per-function\n"
            + _INDENTED_CODE_LINE * (MAX_LINES_PER_FUNCTION + 1),
            id="shared-with-noqa",
        ),
        pytest.param(
            "async def big():  # pymaxlines: disable=max-lines-per-function\n"
            + _INDENTED_CODE_LINE * (MAX_LINES_PER_FUNCTION + 1),
            id="async-def",
        ),
    ],
)
def test_main_when_def_has_disable_per_function_does_skip_that_function(
    tmp_path: Path, content: str
) -> None:
    file = _write_module(tmp_path, content)

    exit_code = main([str(file)])

    assert exit_code == 0


def test_main_when_def_has_disable_but_sibling_does_not_does_still_report_sibling(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    content = (
        "def exempt():  # pymaxlines: disable=max-lines-per-function\n"
        + _INDENTED_CODE_LINE * (MAX_LINES_PER_FUNCTION + 1)
        + "\n\ndef big():\n"
        + _INDENTED_CODE_LINE * (MAX_LINES_PER_FUNCTION + 1)
    )
    file = _write_module(tmp_path, content)

    exit_code = main([str(file)])

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "exempt" not in out
    assert "big" in out


# ---------------------------------------------------------------------------
# directives — method and nested function scope
# ---------------------------------------------------------------------------


def test_main_when_outer_has_disable_but_nested_is_oversized_does_still_report_nested(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    nested_body = "        x = 1\n" * (MAX_LINES_PER_FUNCTION + 1)
    content = (
        "def outer():  # pymaxlines: disable=max-lines-per-function\n"
        "    def nested():\n" + nested_body + "    pass\n"
    )
    file = _write_module(tmp_path, content)

    exit_code = main([str(file)])

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "function 'nested'" in out
    assert "function 'outer'" not in out


# ---------------------------------------------------------------------------
# directives — bare disable and comma-separated rules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "directive",
    [
        pytest.param("# pymaxlines: disable\n", id="bare-disable"),
        pytest.param(
            "# pymaxlines: disable=max-lines,max-lines-per-function\n",
            id="comma-separated",
        ),
        pytest.param(
            "#pymaxlines:disable = max-lines , max-lines-per-function\n",
            id="extra-whitespace",
        ),
    ],
)
def test_main_when_file_scope_disable_does_suppress_file_and_functions(
    tmp_path: Path, directive: str
) -> None:
    content = _oversized_file_and_function(directive)
    file = _write_module(tmp_path, content)

    exit_code = main([str(file)])

    assert exit_code == 0


# ---------------------------------------------------------------------------
# directives — partial file-scope disable
# ---------------------------------------------------------------------------


def test_main_when_file_scope_disable_per_function_does_exempt_functions_but_check_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    content = _oversized_file_and_function("# pymaxlines: disable=max-lines-per-function\n")
    file = _write_module(tmp_path, content)

    exit_code = main([str(file)])

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "code lines (max" in out
    assert "function" not in out


def test_main_when_file_scope_disable_max_lines_does_still_report_oversized_functions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    content = _oversized_file_and_function("# pymaxlines: disable=max-lines\n")
    file = _write_module(tmp_path, content)

    exit_code = main([str(file)])

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "function 'big'" in out
    assert f"{file}: " not in out


# ---------------------------------------------------------------------------
# directives — error: unknown rule
# ---------------------------------------------------------------------------


def test_main_when_directive_has_unknown_rule_does_report_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    content = "# pymaxlines: disable=banana\n" + _CODE_LINE * 5
    file = _write_module(tmp_path, content)

    exit_code = main([str(file)])

    assert exit_code == 1
    assert f"{file}:1: unknown rule 'banana' in pymaxlines directive" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# directives — error: malformed directive
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        pytest.param("# pymaxlines: enable\n", id="enable-instead-of-disable"),
        pytest.param("# pymaxlines: disable=\n", id="disable-equals-empty"),
        pytest.param(
            "# pymaxlines: disable max-lines\n",
            id="space-instead-of-equals",
        ),
        pytest.param("# pymaxlines:\n", id="bare-pymaxlines-colon"),
    ],
)
def test_main_when_directive_is_malformed_does_report_malformed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], line: str
) -> None:
    content = line + _CODE_LINE * 5
    file = _write_module(tmp_path, content)

    exit_code = main([str(file)])

    assert exit_code == 1
    assert (
        f"{file}:1: malformed pymaxlines directive;"
        " expected 'disable' or 'disable=<rule>[,<rule>]'" in capsys.readouterr().out
    )


# ---------------------------------------------------------------------------
# directives — error: misplaced directive
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(
            "x = 1  # pymaxlines: disable\n" + _CODE_LINE * 5,
            id="on-assignment",
        ),
        pytest.param(
            "class C:  # pymaxlines: disable\n    pass\n",
            id="on-class",
        ),
        pytest.param(
            "x = 1\n# pymaxlines: disable=max-lines\n" + _CODE_LINE * 5,
            id="after-first-statement",
        ),
        pytest.param(
            "def big():\n    # pymaxlines: disable=max-lines-per-function\n"
            + _INDENTED_CODE_LINE * 2,
            id="comment-inside-function-body",
        ),
    ],
)
def test_main_when_directive_is_misplaced_does_report_misplaced(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], content: str
) -> None:
    file = _write_module(tmp_path, content)

    exit_code = main([str(file)])

    assert exit_code == 1
    assert "misplaced pymaxlines directive" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# directives — error: file-only rule on a def line
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(
            "def big():  # pymaxlines: disable=max-lines\n" + _INDENTED_CODE_LINE * 5,
            id="multi-line-def",
        ),
        pytest.param(
            "def stub(): ...  # pymaxlines: disable=max-lines\n",
            id="one-liner-def",
        ),
    ],
)
def test_main_when_def_has_disable_max_lines_does_report_wrong_scope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], content: str
) -> None:
    file = _write_module(tmp_path, content)

    exit_code = main([str(file)])

    assert exit_code == 1
    assert (
        f"{file}:1: rule 'max-lines' does not apply to a function;"
        " use max-lines-per-function" in capsys.readouterr().out
    )


# ---------------------------------------------------------------------------
# directives — error priority: syntax before placement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("directive_line", "expected_fragment"),
    [
        pytest.param(
            "x = 1  # pymaxlines: enable\n",
            "malformed pymaxlines directive",
            id="malformed-syntax",
        ),
        pytest.param(
            "x = 1  # pymaxlines: disable=banana\n",
            "unknown rule 'banana'",
            id="unknown-rule",
        ),
    ],
)
def test_main_when_directive_has_validation_error_does_skip_placement_check(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    directive_line: str,
    expected_fragment: str,
) -> None:
    content = directive_line + _CODE_LINE * 5
    file = _write_module(tmp_path, content)

    exit_code = main([str(file)])

    assert exit_code == 1
    out = capsys.readouterr().out
    assert expected_fragment in out
    assert "misplaced" not in out


# ---------------------------------------------------------------------------
# directives — error does not stop checks
# ---------------------------------------------------------------------------


def test_main_when_directive_has_error_does_still_report_oversized_findings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    content = "# pymaxlines: disable=banana\n" + _CODE_LINE * (MAX_LINES_SRC + 1)
    file = _write_module(tmp_path, content)

    exit_code = main([str(file)])

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "unknown rule 'banana'" in out
    assert "code lines (max" in out


def test_main_when_file_has_error_and_valid_directive_does_honor_valid_directive(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    content = (
        "# pymaxlines: disable=max-lines\n"
        "x = 1  # pymaxlines: disable=banana\n" + _CODE_LINE * (MAX_LINES_SRC + 1)
    )
    file = _write_module(tmp_path, content)

    exit_code = main([str(file)])

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "unknown rule 'banana'" in out
    # File check is suppressed by valid directive, so no "code lines" finding
    assert "code lines (max" not in out


# ---------------------------------------------------------------------------
# directives — interaction with --no-skip-comments
# ---------------------------------------------------------------------------


def test_main_when_directive_present_does_honor_it_regardless_of_skip_comments(
    tmp_path: Path,
) -> None:
    content = "# pymaxlines: disable=max-lines\n" + _CODE_LINE * (MAX_LINES_SRC + 1)
    file = _write_module(tmp_path, content)

    exit_code = main(["--no-skip-comments", str(file)])

    assert exit_code == 0


# ---------------------------------------------------------------------------
# directives — isolation between files
# ---------------------------------------------------------------------------


def test_main_when_directive_in_one_file_does_not_affect_another(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exempt = _write_module(
        tmp_path,
        "# pymaxlines: disable=max-lines\n" + _CODE_LINE * (MAX_LINES_SRC + 1),
        "exempt.py",
    )
    oversized = _write_code_lines(tmp_path, MAX_LINES_SRC + 1, "oversized.py")

    exit_code = main([str(exempt), str(oversized)])

    assert exit_code == 1
    out = capsys.readouterr().out
    assert str(oversized) in out
    assert str(exempt) not in out
