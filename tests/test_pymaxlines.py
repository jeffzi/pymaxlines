from __future__ import annotations

import ast
import importlib.metadata
import os
import subprocess
import sys
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from conftest import (
    CODE_LINE,
    INDENTED_CODE_LINE,
    capture_main,
    diagnostic_lines,
    expect_exit_two,
    file_diagnostic,
    function_diagnostic,
    make_oversized_function,
    run_check,
    write_code_lines,
    write_module,
)

from pymaxlines import MAX_LINES_PER_FUNCTION, MAX_LINES_SRC, MAX_LINES_TEST, main
from pymaxlines._lines import (
    OversizedFunction,
    code_line_numbers,
    oversized_functions,
    scan_tokens,
)

if TYPE_CHECKING:
    from pathlib import Path


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
    file = write_code_lines(tmp_path, code_lines, relative_path)

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
    file = write_code_lines(tmp_path, MAX_LINES_SRC + 1, relative_path)

    exit_code = main([str(file)])

    assert exit_code == 0


def test_main_when_file_outside_cwd_has_tests_ancestor_does_use_source_limit(
    tmp_path: Path,
) -> None:
    # cwd is tmp_path (via _isolate_cwd).  Place the file under a sibling
    # directory whose path includes a ``tests`` component so the relative path
    # from cwd starts with ``../`` and contains ``tests``.
    sibling = tmp_path.parent / "tests" / "project"
    sibling.mkdir(parents=True, exist_ok=True)
    file = sibling / "module.py"
    file.write_text(CODE_LINE * (MAX_LINES_SRC + 1))

    exit_code = main([str(file)])

    assert exit_code == 1


def test_main_when_over_limit_does_report_path_count_and_limit(tmp_path: Path) -> None:
    file = write_code_lines(tmp_path, MAX_LINES_SRC + 1)

    exit_code, lines = run_check(file)

    assert exit_code == 1
    assert lines == [file_diagnostic(MAX_LINES_SRC + 1)]


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
    tmp_path: Path, tail: str
) -> None:
    file = write_module(tmp_path, CODE_LINE * (MAX_LINES_SRC - 2) + tail)

    exit_code, lines = run_check(file)

    assert exit_code == 1
    assert lines == [file_diagnostic(MAX_LINES_SRC + 2)]


@pytest.mark.parametrize(
    "header",
    [
        pytest.param('def f(): "doc"\n', id="def-inline-docstring"),
        pytest.param('class C: "doc"\n', id="class-inline-docstring"),
    ],
)
def test_main_when_inline_docstring_on_header_does_count_header_as_code(
    tmp_path: Path, header: str
) -> None:
    file = write_module(tmp_path, CODE_LINE * MAX_LINES_SRC + header)

    exit_code, lines = run_check(file)

    assert exit_code == 1
    assert lines == [file_diagnostic(MAX_LINES_SRC + 1)]


# ---------------------------------------------------------------------------
# main — unreadable files
# ---------------------------------------------------------------------------


def _error_prefix(path: Path, reason: str) -> str:
    """Return the expected `path:1: reason (` prefix of an error diagnostic line."""
    return f"{path}:1: {reason} ("


def _assert_error_message(output: str, path: Path, reason: str) -> None:
    """Assert *output* contains a single `path:1: reason (...)` diagnostic line."""
    diag_lines = diagnostic_lines(output)
    assert len(diag_lines) == 1
    assert diag_lines[0].startswith(_error_prefix(path, reason))
    assert diag_lines[0].endswith(")")


def test_main_when_file_cannot_be_read_does_report_error_and_return_one(
    tmp_path: Path,
) -> None:
    file = tmp_path / "absent.py"

    exit_code, output = capture_main([str(file)])

    assert exit_code == 1
    _assert_error_message(output, file, "could not read")


@pytest.mark.parametrize(
    ("content", "filename"),
    [
        pytest.param("def f(\n", "syntax.py", id="syntax-error"),
        pytest.param('x = "unterminated\n', "unterminated.py", id="unterminated-string"),
        pytest.param("x = 1\x00\n", "bad.py", id="null-byte"),
    ],
)
def test_main_when_file_cannot_be_parsed_does_report_error_and_return_one(
    tmp_path: Path, content: str, filename: str
) -> None:
    file = write_module(tmp_path, content, filename)

    exit_code, output = capture_main([str(file)])

    assert exit_code == 1
    _assert_error_message(output, file, "could not parse")


@pytest.mark.parametrize(
    "exc_class",
    [
        pytest.param(ValueError, id="value-error"),
        pytest.param(RecursionError, id="recursion-error"),
    ],
)
def test_main_when_scan_tokens_raises_internal_error_does_propagate(
    tmp_path: Path, exc_class: type[Exception]
) -> None:
    file = write_module(tmp_path, "x = 1\n")
    message = "internal bug"

    # scan_tokens is patched at its call site because no real source input
    # reliably raises from inside it: analyze_file's `except
    # tokenize.TokenError` is deliberately narrow, and this pins that any
    # other exception propagates instead of being swallowed.
    with (
        patch("pymaxlines._analysis.scan_tokens", autospec=True, side_effect=exc_class(message)),
        pytest.raises(exc_class, match=message),
    ):
        main([str(file)])


def test_main_when_mix_of_unreadable_unparsable_clean_and_oversized_does_report_only_offenders(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "absent.py"
    broken = write_module(tmp_path, "def f(\n", "broken.py")
    clean = write_code_lines(tmp_path, 10, "small.py")
    oversized = write_code_lines(tmp_path, MAX_LINES_SRC + 1, "big.py")

    exit_code, output = capture_main([str(missing), str(broken), str(clean), str(oversized)])

    assert exit_code == 1
    all_lines = output.splitlines()
    diag_lines = diagnostic_lines(output)
    assert len(diag_lines) == 3
    assert diag_lines[0].startswith(_error_prefix(missing, "could not read"))
    assert diag_lines[1].startswith(_error_prefix(broken, "could not parse"))
    assert diag_lines[2] == file_diagnostic(MAX_LINES_SRC + 1, path=str(oversized))
    assert all_lines[-1] == "Found 3 errors."


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
    file = write_code_lines(tmp_path, code_lines, relative_path)

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
    file = write_code_lines(tmp_path, 1)

    expect_exit_two([flag, "-1", str(file)])


@pytest.mark.parametrize("flag", _LIMIT_FLAG_PARAMS)
def test_main_when_zero_line_limit_given_does_accept_it(tmp_path: Path, flag: str) -> None:
    file = write_module(tmp_path, "")

    exit_code = main([flag, "0", str(file)])

    assert exit_code == 0


# ---------------------------------------------------------------------------
# main — per-function limits
# ---------------------------------------------------------------------------


def test_main_when_function_exceeds_limit_does_report_name_line_and_count(
    tmp_path: Path,
) -> None:
    source, count = make_oversized_function()
    file = write_module(tmp_path, source)

    exit_code, lines = run_check(file)

    assert exit_code == 1
    end_lineno = 1 + count
    assert lines == [function_diagnostic(1, "big", count, end_lineno)]


def test_main_when_nested_and_later_functions_oversized_does_report_in_line_order(
    tmp_path: Path,
) -> None:
    body = MAX_LINES_PER_FUNCTION + 1
    doubly_indented = "        x = 1\n"
    source = (
        "def outer():\n"  # line 1
        "    def inner():\n"  # line 2
        + doubly_indented * body  # lines 3..63
        + INDENTED_CODE_LINE  # line 64
        + "def later():\n"  # line 65
        + INDENTED_CODE_LINE * body  # lines 66..126
    )
    file = write_module(tmp_path, source)
    inner_start = 2
    outer_span = 1 + 1 + body + 1  # total lines in outer: def outer + def inner + body + trailing
    outer_code_lines = outer_span - 1  # def outer header excluded
    inner_code_lines = body  # body only (def inner header excluded)
    later_start = outer_span + 1
    later_code_lines = body  # body only (def later header excluded)

    exit_code, lines = run_check(file)

    assert exit_code == 1
    inner_end = inner_start + inner_code_lines
    later_end = later_start + later_code_lines
    assert lines == [
        function_diagnostic(1, "outer", outer_code_lines, outer_span),
        function_diagnostic(inner_start, "inner", inner_code_lines, inner_end),
        function_diagnostic(later_start, "later", later_code_lines, later_end),
    ]


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
    ("source", "expected_end_lineno"),
    [
        pytest.param("def f(): x = 1\n", 1, id="one-liner-body-on-def-line"),
        pytest.param('def f(\n    x,\n): "doc"\n', 3, id="docstring-on-closing-paren"),
    ],
)
def test_oversized_functions_when_body_code_shares_signature_line_does_set_correct_end_lineno(
    source: str, expected_end_lineno: int
) -> None:
    # ): "doc" closes the signature AND carries body code — the line must be
    # counted as body. A CLI-level assertion can't distinguish that count
    # (1) from the wrongly-excluded count (0) here: limit=0 disables the
    # function check entirely, and any positive limit accepts count=1 too.
    # Checking oversized_functions() directly with limit=0 makes
    # `count > limit` distinguish the two cases.
    tree = ast.parse(source)
    scan = scan_tokens(source)
    code_lines = code_line_numbers(source, tree, scan, skip_blank_lines=True, skip_docstrings=True)

    result = oversized_functions(tree, code_lines, limit=0, header_ranges=scan.header_ranges)

    assert result == [OversizedFunction("f", 1, 1, end_lineno=expected_end_lineno)]


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
    source, _ = make_oversized_function()
    file = write_module(tmp_path, source, relative_path)

    exit_code = main([*argv_prefix, str(file)])

    assert exit_code == expected_exit


# ---------------------------------------------------------------------------
# main — header lines excluded from function count
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "body_lines", "expected_exit", "expected_lines"),
    [
        pytest.param(
            "def big():\n",
            MAX_LINES_PER_FUNCTION,
            0,
            [],
            id="simple-header-at-limit",
        ),
        pytest.param(
            "def big(\n    a,\n):\n",
            MAX_LINES_PER_FUNCTION,
            0,
            [],
            id="multiline-sig-at-limit",
        ),
        pytest.param(
            "def big(\n    a,\n):\n",
            MAX_LINES_PER_FUNCTION + 1,
            1,
            [
                function_diagnostic(
                    1, "big", MAX_LINES_PER_FUNCTION + 1, 3 + MAX_LINES_PER_FUNCTION + 1
                )
            ],
            id="multiline-sig-over-limit",
        ),
        pytest.param(
            "async def big(\n    a,\n):\n",
            MAX_LINES_PER_FUNCTION + 1,
            1,
            [
                function_diagnostic(
                    1, "big", MAX_LINES_PER_FUNCTION + 1, 3 + MAX_LINES_PER_FUNCTION + 1
                )
            ],
            id="async-multiline-sig",
        ),
        pytest.param(
            "def big(\n    a,\n) -> dict[str, int]:\n",
            MAX_LINES_PER_FUNCTION + 1,
            1,
            [
                function_diagnostic(
                    1, "big", MAX_LINES_PER_FUNCTION + 1, 3 + MAX_LINES_PER_FUNCTION + 1
                )
            ],
            id="return-annotation-after-paren",
        ),
        pytest.param(
            "def big(x=lambda: 1) -> dict[str, int]:\n",
            MAX_LINES_PER_FUNCTION + 1,
            1,
            [
                function_diagnostic(
                    1, "big", MAX_LINES_PER_FUNCTION + 1, 1 + MAX_LINES_PER_FUNCTION + 1
                )
            ],
            id="default-with-lambda-and-annotation",
        ),
    ],
)
def test_main_when_multiline_signature_does_exclude_header_from_count(
    tmp_path: Path,
    header: str,
    body_lines: int,
    expected_exit: int,
    expected_lines: list[str],
) -> None:
    source = header + INDENTED_CODE_LINE * body_lines
    file = write_module(tmp_path, source)

    exit_code, lines = run_check(file)

    assert exit_code == expected_exit
    assert lines == expected_lines


def test_main_when_no_skip_comments_does_count_comment_after_header_but_not_header(
    tmp_path: Path,
) -> None:
    body = MAX_LINES_PER_FUNCTION + 1
    source = "def big():\n    # comment between header and body\n" + INDENTED_CODE_LINE * body
    file = write_module(tmp_path, source)

    exit_code, lines = run_check(file, "--no-skip-comments")

    assert exit_code == 1
    end_lineno = 2 + body
    assert lines == [function_diagnostic(1, "big", body + 1, end_lineno)]


def test_main_when_file_over_limit_does_count_header_lines_in_file_total(
    tmp_path: Path,
) -> None:
    source = "def f():\n" + INDENTED_CODE_LINE * MAX_LINES_SRC
    file = write_module(tmp_path, source)

    exit_code, lines = run_check(file, "--max-lines-per-function", "0")

    assert exit_code == 1
    assert lines == [file_diagnostic(MAX_LINES_SRC + 1)]


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


def test_main_when_all_no_skip_flags_given_does_count_every_line(tmp_path: Path) -> None:
    content = '"""Docstring."""\n# comment\n\n' + CODE_LINE * MAX_LINES_SRC
    file = write_module(tmp_path, content)

    exit_code, lines = run_check(
        file,
        "--no-skip-blank-lines",
        "--no-skip-comments",
        "--no-skip-docstrings",
    )

    assert exit_code == 1
    assert lines == [file_diagnostic(MAX_LINES_SRC + 3)]


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
    file = write_code_lines(tmp_path, MAX_LINES_SRC + 1)
    monkeypatch.setattr(sys, "argv", ["pymaxlines", str(file)])

    exit_code = main()

    assert exit_code == 1


def test_module_entry_when_file_over_limit_does_exit_one(tmp_path: Path) -> None:
    file = write_code_lines(tmp_path, MAX_LINES_SRC + 1)

    result = subprocess.run(  # noqa: S603 — fixed interpreter and args, no shell
        [sys.executable, "-m", "pymaxlines", str(file)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    stdout_lines = result.stdout.rstrip().splitlines()
    assert len(stdout_lines) == 2
    assert stdout_lines[0] == file_diagnostic(MAX_LINES_SRC + 1, path=str(file))
    assert stdout_lines[1] == "Found 1 error."


# ---------------------------------------------------------------------------
# entry points — version flag
# ---------------------------------------------------------------------------

_EXPECTED_VERSION_OUTPUT = f"pymaxlines {importlib.metadata.version('pymaxlines')}"


@pytest.mark.parametrize(
    ("flag", "with_oversized_file"),
    [
        pytest.param("--version", False, id="long-flag"),
        pytest.param("-v", False, id="short-flag"),
        pytest.param("--version", True, id="with-oversized-file"),
    ],
)
def test_main_when_version_flag_given_does_print_version_and_exit_zero(
    flag: str, with_oversized_file: bool, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = [flag]
    if with_oversized_file:
        argv.append(str(write_code_lines(tmp_path, MAX_LINES_SRC + 1)))

    with pytest.raises(SystemExit) as exc_info:
        main(argv)

    assert exc_info.value.code == 0
    assert capsys.readouterr().out.strip() == _EXPECTED_VERSION_OUTPUT


# ---------------------------------------------------------------------------
# entry points — --help and --version bypass config errors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "config_content",
    [
        pytest.param("[invalid toml content\n", id="invalid-toml"),
        pytest.param("[tool.pymaxlines]\nbogus-key = 42\n", id="unknown-key"),
    ],
)
@pytest.mark.parametrize(
    "flag",
    [
        pytest.param("--help", id="help"),
        pytest.param("--hel", id="help-abbreviated"),
        pytest.param("--version", id="version"),
        pytest.param("--vers", id="version-abbreviated"),
    ],
)
def test_main_when_cwd_config_is_broken_and_help_or_version_given_does_exit_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    flag: str,
    config_content: str,
) -> None:
    (tmp_path / "pyproject.toml").write_text(config_content)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        main([flag])

    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# entry points — --no-report-unused-disable-directives
# ---------------------------------------------------------------------------


def test_main_when_no_report_unused_flag_given_does_suppress_unused_warnings(
    tmp_path: Path,
) -> None:
    content = "# pymaxlines: disable=max-lines-per-function\ndef small():\n    x = 1\n"
    file = write_module(tmp_path, content)

    exit_code, lines = run_check(
        file,
        "--report-unused-disable-directives",
        "--no-report-unused-disable-directives",
    )

    assert exit_code == 0
    assert lines == []


# ---------------------------------------------------------------------------
# main — broken pipe handling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cmd_prefix",
    [
        pytest.param(["pymaxlines"], id="console-script"),
        pytest.param([sys.executable, "-m", "pymaxlines"], id="python-m"),
    ],
)
@pytest.mark.parametrize(
    "extra_env",
    [
        pytest.param({"PYTHONUNBUFFERED": "1"}, id="unbuffered"),
        pytest.param({}, id="block-buffered"),
    ],
)
def test_main_when_stdout_closed_mid_run_does_exit_one_without_traceback(
    tmp_path: Path, cmd_prefix: list[str], extra_env: dict[str, str]
) -> None:
    # Enough oversized files that the output exceeds the pipe buffer
    # (64 KB on Linux, 16 KB on macOS) even when block-buffered.
    files = [str(write_code_lines(tmp_path, MAX_LINES_SRC + 1, f"f{i:03d}.py")) for i in range(200)]
    env = {k: v for k, v in os.environ.items() if k != "PYTHONUNBUFFERED"} | extra_env

    with subprocess.Popen(  # noqa: S603 — fixed commands, no shell
        [*cmd_prefix, *files],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    ) as proc:
        assert proc.stdout is not None
        proc.stdout.readline()
        proc.stdout.close()
        # On Windows, communicate() spawns a reader thread per open pipe;
        # a closed-but-non-None stdout crashes that thread.
        proc.stdout = None
        _, stderr = proc.communicate(timeout=30)

    assert proc.returncode == 1
    assert "Traceback" not in stderr
    assert "Exception ignored" not in stderr
    assert "BrokenPipeError" not in stderr


def test_main_when_stdout_write_raises_broken_pipe_does_return_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = write_code_lines(tmp_path, MAX_LINES_SRC + 1)

    def _broken_write(_text: str) -> int:
        msg = "Broken pipe"
        raise BrokenPipeError(msg)

    monkeypatch.setattr(sys.stdout, "write", _broken_write)

    exit_code = main([str(file)])

    assert exit_code == 1


@pytest.mark.skipif(
    sys.platform == "win32" or getattr(os, "getuid", lambda: -1)() == 0,
    reason="Windows ignores POSIX permission bits; root bypasses them",
)
def test_main_when_stdout_pipe_breaks_during_walk_error_does_return_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    forbidden = tmp_path / "pkg" / "secret"
    forbidden.mkdir(parents=True)
    write_code_lines(tmp_path, 1, "pkg/ok.py")
    forbidden.chmod(0o000)
    monkeypatch.chdir(tmp_path)

    def _broken_write(_text: str) -> int:
        msg = "Broken pipe"
        raise BrokenPipeError(msg)

    monkeypatch.setattr(sys.stdout, "write", _broken_write)

    try:
        exit_code = main(["pkg"])
    finally:
        forbidden.chmod(0o755)

    assert exit_code == 1


# ---------------------------------------------------------------------------
# summary line
# ---------------------------------------------------------------------------


def test_main_when_no_diagnostics_does_not_print_summary(tmp_path: Path) -> None:
    file = write_module(tmp_path, CODE_LINE * 10)

    exit_code, output = capture_main([str(file)])

    assert exit_code == 0
    assert output == ""


@pytest.mark.parametrize(
    ("content", "expected_summary"),
    [
        pytest.param(CODE_LINE * (MAX_LINES_SRC + 1), "Found 1 error.", id="file-over-limit"),
        pytest.param(
            make_oversized_function()[0] + "\n" + CODE_LINE * MAX_LINES_SRC,
            "Found 2 errors.",
            id="file-and-function-over-limit",
        ),
    ],
)
def test_main_when_diagnostics_emitted_does_print_matching_summary_line(
    tmp_path: Path, content: str, expected_summary: str
) -> None:
    file = write_module(tmp_path, content)

    exit_code, output = capture_main([str(file)])

    assert exit_code == 1
    assert output.strip().splitlines()[-1] == expected_summary
