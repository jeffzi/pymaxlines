from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from conftest import (
    CODE_LINE,
    INDENTED_CODE_LINE,
    PLACEHOLDER,
    capture_main,
    oversized_file_and_function,
    run_check,
    write_module,
)

from pymaxlines import MAX_LINES_PER_FUNCTION, MAX_LINES_SRC

if TYPE_CHECKING:
    from pathlib import Path

_DISABLE = "# pymaxlines: disable=max-lines-per-function"
_OVERSIZED_BODY = INDENTED_CODE_LINE * (MAX_LINES_PER_FUNCTION + 1)
_BODY_LINES = MAX_LINES_PER_FUNCTION + 1
_MISPLACED_MSG = (
    "misplaced pymaxlines directive;"
    " put it on a comment-only line before the first statement or on a def header line"
)
_MALFORMED_MSG = (
    "malformed pymaxlines directive;"
    " expected '# pymaxlines: disable' or '# pymaxlines: disable=<rule>[,<rule>]'"
)
_WRONG_SCOPE_MSG = "rule 'max-lines' does not apply to a function; use max-lines-per-function"
_UNUSED_MSG = "unused pymaxlines-disable directive (no findings were reported)"
_REPORT_FLAG = "--report-unused-disable-directives"
_EXEMPT: tuple[int, list[str]] = (0, [])


def _run_check_unused(file: Path, *extra_args: str) -> tuple[int, list[str]]:
    return run_check(file, _REPORT_FLAG, *extra_args)


def _misplaced(directive_lineno: int, def_lineno: int, code_count: int) -> tuple[int, list[str]]:
    return (
        1,
        [
            f"{PLACEHOLDER}:{directive_lineno}: {_MISPLACED_MSG}",
            (
                f"{PLACEHOLDER}:{def_lineno}: function 'big' has {code_count} code lines"
                f" (max {MAX_LINES_PER_FUNCTION})"
            ),
        ],
    )


def _unknown_rule(lineno: int, rule: str = "banana") -> str:
    return f"{PLACEHOLDER}:{lineno}: unknown rule '{rule}' in pymaxlines directive"


# ---------------------------------------------------------------------------
# file-scope disable=max-lines
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(
            "# pymaxlines: disable=max-lines\n" + CODE_LINE * (MAX_LINES_SRC + 1),
            id="before-first-statement",
        ),
        pytest.param(
            '"""Module docstring."""\n# pymaxlines: disable=max-lines\n'
            + CODE_LINE * (MAX_LINES_SRC + 1),
            id="after-docstring",
        ),
        pytest.param(
            '# pymaxlines: disable=max-lines\n"""Module docstring."""\n'
            + CODE_LINE * (MAX_LINES_SRC + 1),
            id="above-docstring",
        ),
    ],
)
def test_main_when_file_has_disable_max_lines_does_skip_file_check(
    tmp_path: Path, content: str
) -> None:
    file = write_module(tmp_path, content)

    exit_code, lines = run_check(file)

    assert (exit_code, lines) == (0, [])


# ---------------------------------------------------------------------------
# sibling functions — only the non-exempt one is reported
# ---------------------------------------------------------------------------


def test_main_when_def_has_disable_but_sibling_does_not_does_still_report_sibling(
    tmp_path: Path,
) -> None:
    body_count = MAX_LINES_PER_FUNCTION + 1
    content = (
        f"def exempt():  {_DISABLE}\n"
        + INDENTED_CODE_LINE * body_count
        + "\n\ndef big():\n"
        + INDENTED_CODE_LINE * body_count
    )
    file = write_module(tmp_path, content)

    exit_code, lines = run_check(file)

    big_lineno = 1 + body_count + 3
    big_total = body_count + 1
    assert exit_code == 1
    assert lines == [
        (
            f"{PLACEHOLDER}:{big_lineno}: function 'big' has {big_total} code lines"
            f" (max {MAX_LINES_PER_FUNCTION})"
        )
    ]


# ---------------------------------------------------------------------------
# nested function — directive on outer does not exempt nested
# ---------------------------------------------------------------------------


def test_main_when_outer_has_disable_but_nested_is_oversized_does_still_report_nested(
    tmp_path: Path,
) -> None:
    body_count = MAX_LINES_PER_FUNCTION + 1
    nested_body = "        x = 1\n" * body_count
    content = f"def outer():  {_DISABLE}\n    def nested():\n" + nested_body + "    pass\n"
    file = write_module(tmp_path, content)

    exit_code, lines = run_check(file)

    nested_total = body_count + 1
    assert exit_code == 1
    assert lines == [
        (
            f"{PLACEHOLDER}:2: function 'nested' has {nested_total} code lines"
            f" (max {MAX_LINES_PER_FUNCTION})"
        )
    ]


# ---------------------------------------------------------------------------
# bare disable and comma-separated rules — file + functions suppressed
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
    content = oversized_file_and_function(directive)
    file = write_module(tmp_path, content)

    exit_code, lines = run_check(file)

    assert (exit_code, lines) == (0, [])


# ---------------------------------------------------------------------------
# partial file-scope disable
# ---------------------------------------------------------------------------


def test_main_when_file_scope_disable_per_function_does_exempt_functions_but_check_file(
    tmp_path: Path,
) -> None:
    content = oversized_file_and_function("# pymaxlines: disable=max-lines-per-function\n")
    file = write_module(tmp_path, content)

    exit_code, lines = run_check(file)

    total = 1 + (MAX_LINES_PER_FUNCTION + 1) + MAX_LINES_SRC
    assert exit_code == 1
    assert lines == [f"{PLACEHOLDER}: {total} code lines (max {MAX_LINES_SRC})"]


def test_main_when_file_scope_disable_max_lines_does_still_report_oversized_functions(
    tmp_path: Path,
) -> None:
    content = oversized_file_and_function("# pymaxlines: disable=max-lines\n")
    file = write_module(tmp_path, content)

    exit_code, lines = run_check(file)

    func_total = MAX_LINES_PER_FUNCTION + 1 + 1
    assert exit_code == 1
    assert lines == [
        (
            f"{PLACEHOLDER}:2: function 'big' has {func_total} code lines"
            f" (max {MAX_LINES_PER_FUNCTION})"
        )
    ]


# ---------------------------------------------------------------------------
# error: unknown rule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "relative_path",
    [
        pytest.param("module.py", id="src-file"),
        pytest.param("tests/test_module.py", id="test-file-zero-function-limit"),
    ],
)
def test_main_when_directive_has_unknown_rule_does_report_error(
    tmp_path: Path, relative_path: str
) -> None:
    content = "# pymaxlines: disable=banana\n" + CODE_LINE * 5
    file = write_module(tmp_path, content, relative_path)

    exit_code, lines = run_check(file)

    assert exit_code == 1
    assert lines == [_unknown_rule(1)]


# ---------------------------------------------------------------------------
# error: malformed directive
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        pytest.param("# pymaxlines: enable\n", id="enable-instead-of-disable"),
        pytest.param("# pymaxlines: disable=\n", id="disable-equals-empty"),
        pytest.param("# pymaxlines: disable max-lines\n", id="space-instead-of-equals"),
        pytest.param("# pymaxlines:\n", id="bare-pymaxlines-colon"),
        pytest.param("# pymaxlines disable\n", id="near-miss-no-colon"),
        pytest.param("# PYMAXLINES: disable\n", id="near-miss-wrong-case"),
        pytest.param("# PyMaxLines: disable\n", id="near-miss-mixed-case"),
        pytest.param("# PYMAXLINES disable\n", id="near-miss-wrong-case-no-colon"),
        pytest.param("# pymaxlines: disable=max-lines,\n", id="trailing-comma"),
    ],
)
def test_main_when_directive_is_malformed_does_report_malformed(tmp_path: Path, line: str) -> None:
    content = line + CODE_LINE * 5
    file = write_module(tmp_path, content)

    exit_code, lines = run_check(file)

    assert exit_code == 1
    assert lines == [f"{PLACEHOLDER}:1: {_MALFORMED_MSG}"]


# ---------------------------------------------------------------------------
# error: misplaced directive
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "expected_lineno"),
    [
        pytest.param(
            "x = 1  # pymaxlines: disable\n" + CODE_LINE * 5,
            1,
            id="on-assignment",
        ),
        pytest.param(
            "class C:  # pymaxlines: disable\n    pass\n",
            1,
            id="on-class",
        ),
        pytest.param(
            "x = 1\n# pymaxlines: disable=max-lines\n" + CODE_LINE * 5,
            2,
            id="after-first-statement",
        ),
        pytest.param(
            "def big():\n    # pymaxlines: disable=max-lines-per-function\n"
            + INDENTED_CODE_LINE * 2,
            2,
            id="comment-inside-function-body",
        ),
    ],
)
def test_main_when_directive_is_misplaced_does_report_misplaced(
    tmp_path: Path, content: str, expected_lineno: int
) -> None:
    file = write_module(tmp_path, content)

    exit_code, lines = run_check(file)

    assert exit_code == 1
    assert lines == [f"{PLACEHOLDER}:{expected_lineno}: {_MISPLACED_MSG}"]


# ---------------------------------------------------------------------------
# error: file-only rule on a def line
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(
            "def big():  # pymaxlines: disable=max-lines\n" + INDENTED_CODE_LINE * 5,
            id="multi-line-def",
        ),
        pytest.param(
            "def stub(): ...  # pymaxlines: disable=max-lines\n",
            id="one-liner-def",
        ),
        pytest.param(
            "def big():  # pymaxlines: disable=max-lines-per-function,max-lines\n"
            + INDENTED_CODE_LINE * 5,
            id="mixed-rules",
        ),
    ],
)
def test_main_when_def_has_disable_max_lines_does_report_wrong_scope(
    tmp_path: Path, content: str
) -> None:
    file = write_module(tmp_path, content)

    exit_code, lines = run_check(file)

    assert exit_code == 1
    assert lines == [f"{PLACEHOLDER}:1: {_WRONG_SCOPE_MSG}"]


# ---------------------------------------------------------------------------
# error priority: syntax before placement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("directive_line", "expected_output"),
    [
        pytest.param(
            "x = 1  # pymaxlines: enable\n",
            f"{PLACEHOLDER}:1: {_MALFORMED_MSG}",
            id="malformed-syntax",
        ),
        pytest.param(
            "x = 1  # pymaxlines: disable=banana\n",
            _unknown_rule(1),
            id="unknown-rule",
        ),
    ],
)
def test_main_when_directive_has_validation_error_does_skip_placement_check(
    tmp_path: Path, directive_line: str, expected_output: str
) -> None:
    content = directive_line + CODE_LINE * 5
    file = write_module(tmp_path, content)

    exit_code, lines = run_check(file)

    assert exit_code == 1
    assert lines == [expected_output]


# ---------------------------------------------------------------------------
# error does not stop checks
# ---------------------------------------------------------------------------


def test_main_when_directive_has_error_does_still_report_oversized_findings(
    tmp_path: Path,
) -> None:
    total = MAX_LINES_SRC + 1
    content = "# pymaxlines: disable=banana\n" + CODE_LINE * total
    file = write_module(tmp_path, content)

    exit_code, lines = run_check(file)

    assert exit_code == 1
    assert lines == [
        _unknown_rule(1),
        f"{PLACEHOLDER}: {total} code lines (max {MAX_LINES_SRC})",
    ]


def test_main_when_file_has_error_and_valid_directive_does_honor_valid_directive(
    tmp_path: Path,
) -> None:
    content = (
        "# pymaxlines: disable=max-lines\n"
        "x = 1  # pymaxlines: disable=banana\n" + CODE_LINE * (MAX_LINES_SRC + 1)
    )
    file = write_module(tmp_path, content)

    exit_code, lines = run_check(file)

    assert exit_code == 1
    assert lines == [_unknown_rule(2)]


# ---------------------------------------------------------------------------
# interaction with --no-skip-comments
# ---------------------------------------------------------------------------


def test_main_when_directive_present_does_honor_it_regardless_of_skip_comments(
    tmp_path: Path,
) -> None:
    content = "# pymaxlines: disable=max-lines\n" + CODE_LINE * (MAX_LINES_SRC + 1)
    file = write_module(tmp_path, content)

    exit_code, lines = run_check(file, "--no-skip-comments")

    assert (exit_code, lines) == (0, [])


# ---------------------------------------------------------------------------
# isolation between files
# ---------------------------------------------------------------------------


def test_main_when_directive_in_one_file_does_not_affect_another(
    tmp_path: Path,
) -> None:
    exempt = write_module(
        tmp_path,
        "# pymaxlines: disable=max-lines\n" + CODE_LINE * (MAX_LINES_SRC + 1),
        "exempt.py",
    )
    total = MAX_LINES_SRC + 1
    oversized = write_module(tmp_path, CODE_LINE * total, "oversized.py")

    exit_code, out = capture_main([str(exempt), str(oversized)])

    assert exit_code == 1
    assert out == f"{oversized}: {total} code lines (max {MAX_LINES_SRC})\n"


# ---------------------------------------------------------------------------
# placement contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            f"def big():  {_DISABLE}\n" + _OVERSIZED_BODY,
            _EXEMPT,
            id="def-line",
        ),
        pytest.param(
            "def big():  # pymaxlines: disable\n" + _OVERSIZED_BODY,
            _EXEMPT,
            id="bare-disable",
        ),
        pytest.param(
            f"def big():  # noqa: C901  {_DISABLE}\n" + _OVERSIZED_BODY,
            _EXEMPT,
            id="shared-with-noqa",
        ),
        pytest.param(
            f"def big(\n    a,  {_DISABLE}\n    b,\n):\n" + _OVERSIZED_BODY,
            _EXEMPT,
            id="intermediate-param",
        ),
        pytest.param(
            f"def big(\n    a,\n    b,\n):  {_DISABLE}\n" + _OVERSIZED_BODY,
            _EXEMPT,
            id="closing-paren-own-line",
        ),
        pytest.param(
            f"def big(\n    a,\n    b,\n): x = 1  {_DISABLE}\n",
            _EXEMPT,
            id="closing-body-trailing-comma",
        ),
        pytest.param(
            f"def big(\n    a,\n    b): x = 1  {_DISABLE}\n",
            _EXEMPT,
            id="closing-body-no-trailing-comma",
        ),
        pytest.param(
            f"def big(\n    b):\n    x = 1  {_DISABLE}\n" + _OVERSIZED_BODY,
            _misplaced(3, 1, _BODY_LINES + 3),
            id="body-under-b-paren-colon",
        ),
        pytest.param(
            f"def big(\n    b) -> int:\n    x = 1  {_DISABLE}\n" + _OVERSIZED_BODY,
            _misplaced(3, 1, _BODY_LINES + 3),
            id="body-under-b-arrow-int-colon",
        ),
        pytest.param(
            f"def big(\n    a,\n):\n    x = 1  {_DISABLE}\n" + _OVERSIZED_BODY,
            _misplaced(4, 1, _BODY_LINES + 4),
            id="body-under-paren-colon-own-line",
        ),
        pytest.param(
            f"@decorator  {_DISABLE}\ndef big():\n" + _OVERSIZED_BODY,
            _misplaced(1, 2, _BODY_LINES + 1),
            id="decorator-line",
        ),
        pytest.param(
            f"@decorator\ndef big():  {_DISABLE}\n" + _OVERSIZED_BODY,
            _EXEMPT,
            id="def-of-decorated",
        ),
        pytest.param(
            f"def big(\n    {_DISABLE}\n    a,\n):\n" + _OVERSIZED_BODY,
            _misplaced(2, 1, _BODY_LINES + 3),
            id="comment-in-wrapped-sig",
        ),
        pytest.param(
            f"def f(): ...  {_DISABLE}\n",
            _EXEMPT,
            id="one-liner",
        ),
        pytest.param(
            f"async def big():  {_DISABLE}\n" + _OVERSIZED_BODY,
            _EXEMPT,
            id="async-def",
        ),
        pytest.param(
            f"class C:\n    def big(self):  {_DISABLE}\n"
            + "        x = 1\n" * (MAX_LINES_PER_FUNCTION + 1),
            _EXEMPT,
            id="method",
        ),
        pytest.param(
            f"def f[T](x: T):  {_DISABLE}\n" + _OVERSIZED_BODY,
            _EXEMPT,
            id="generic",
        ),
    ],
)
def test_main_when_directive_placed_on_def_construct_does_apply_placement_rules(
    tmp_path: Path, source: str, expected: tuple[int, list[str]]
) -> None:
    file = write_module(tmp_path, source)

    exit_code, lines = run_check(file)

    assert (exit_code, lines) == expected


def test_placement_contract_when_nested_def_has_directive_does_exempt_only_nested(
    tmp_path: Path,
) -> None:
    body_count = MAX_LINES_PER_FUNCTION + 1
    nested_body = "        x = 1\n" * body_count
    content = (
        "def outer():\n"
        f"    def nested():  {_DISABLE}\n"
        + nested_body
        + "    pass\n"
        + INDENTED_CODE_LINE * MAX_LINES_PER_FUNCTION
    )
    file = write_module(tmp_path, content)

    exit_code, lines = run_check(file)

    outer_count = 1 + 1 + body_count + 1 + MAX_LINES_PER_FUNCTION
    assert exit_code == 1
    assert lines == [
        (
            f"{PLACEHOLDER}:1: function 'outer' has {outer_count} code lines"
            f" (max {MAX_LINES_PER_FUNCTION})"
        )
    ]


# ---------------------------------------------------------------------------
# contract gaps (T3)
# ---------------------------------------------------------------------------


def test_main_when_file_has_multiple_bad_directives_does_report_all_in_source_order(
    tmp_path: Path,
) -> None:
    content = "# pymaxlines: enable\n# pymaxlines: disable=banana\n" + CODE_LINE * 5
    file = write_module(tmp_path, content)

    exit_code, lines = run_check(file)

    assert exit_code == 1
    assert lines == [
        f"{PLACEHOLDER}:1: {_MALFORMED_MSG}",
        _unknown_rule(2),
    ]


# ---------------------------------------------------------------------------
# near-miss: pymaxlines mentioned but not as a directive
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        pytest.param("# TODO pymaxlines: disable\n", id="not-first-word"),
        pytest.param("# pymaxlines_config\n", id="longer-identifier"),
        pytest.param("# see pymaxlines documentation\n", id="prose-mention"),
    ],
)
def test_main_when_comment_mentions_pymaxlines_not_as_directive_does_ignore(
    tmp_path: Path, line: str
) -> None:
    content = line + CODE_LINE * 5
    file = write_module(tmp_path, content)

    exit_code, lines = run_check(file)

    assert (exit_code, lines) == (0, [])


# ---------------------------------------------------------------------------
# behavior 1: without the flag, unused directives produce no output
# ---------------------------------------------------------------------------


def test_main_when_no_report_flag_and_directive_suppresses_nothing_does_stay_silent(
    tmp_path: Path,
) -> None:
    content = f"def small():  {_DISABLE}\n    x = 1\n"
    file = write_module(tmp_path, content)

    exit_code, lines = run_check(file)

    assert (exit_code, lines) == (0, [])


# ---------------------------------------------------------------------------
# behavior 2: def-scope directive on a within-limit function
# ---------------------------------------------------------------------------


def test_main_when_report_flag_and_def_directive_suppresses_nothing_does_report_unused(
    tmp_path: Path,
) -> None:
    content = f"def small():  {_DISABLE}\n    x = 1\n"
    file = write_module(tmp_path, content)

    exit_code, lines = _run_check_unused(file)

    assert exit_code == 1
    assert lines == [f"{PLACEHOLDER}:1: {_UNUSED_MSG}"]


# ---------------------------------------------------------------------------
# behavior 3: file-scope directive on a within-limit file
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("directive", "directive_lineno"),
    [
        pytest.param(
            "# pymaxlines: disable=max-lines\n",
            1,
            id="max-lines-within-limit",
        ),
        pytest.param(
            "# pymaxlines: disable=max-lines-per-function\n",
            1,
            id="max-lines-per-function-no-violations",
        ),
    ],
)
def test_main_when_report_flag_and_file_scope_single_rule_suppresses_nothing_does_report_unused(
    tmp_path: Path, directive: str, directive_lineno: int
) -> None:
    content = directive + CODE_LINE * 5
    file = write_module(tmp_path, content)

    exit_code, lines = _run_check_unused(file)

    assert exit_code == 1
    assert lines == [f"{PLACEHOLDER}:{directive_lineno}: {_UNUSED_MSG}"]


# ---------------------------------------------------------------------------
# behavior 4: bare file-scope disable reported only when both checks clean
# ---------------------------------------------------------------------------


def test_main_when_report_flag_and_bare_disable_with_no_findings_does_report_unused(
    tmp_path: Path,
) -> None:
    content = "# pymaxlines: disable\n" + CODE_LINE * 5
    file = write_module(tmp_path, content)

    exit_code, lines = _run_check_unused(file)

    assert exit_code == 1
    assert lines == [f"{PLACEHOLDER}:1: {_UNUSED_MSG}"]


def test_main_when_report_flag_and_bare_disable_suppresses_file_finding_does_not_report_unused(
    tmp_path: Path,
) -> None:
    content = "# pymaxlines: disable\n" + CODE_LINE * (MAX_LINES_SRC + 1)
    file = write_module(tmp_path, content)

    exit_code, lines = _run_check_unused(file)

    assert (exit_code, lines) == (0, [])


def test_main_when_report_flag_and_bare_disable_suppresses_function_finding_does_not_report_unused(
    tmp_path: Path,
) -> None:
    content = "# pymaxlines: disable\ndef big():\n" + INDENTED_CODE_LINE * (
        MAX_LINES_PER_FUNCTION + 1
    )
    file = write_module(tmp_path, content)

    exit_code, lines = _run_check_unused(file)

    assert (exit_code, lines) == (0, [])


# ---------------------------------------------------------------------------
# behavior 5: directive for a rule with limit 0 is reported as unused
# ---------------------------------------------------------------------------


def test_main_when_report_flag_and_disable_for_zero_limit_rule_does_report_unused(
    tmp_path: Path,
) -> None:
    content = "# pymaxlines: disable=max-lines-per-function\ndef big():\n" + ("    x = 1\n" * 100)
    file = write_module(tmp_path, content, "tests/test_module.py")

    exit_code, lines = _run_check_unused(file)

    assert exit_code == 1
    assert lines == [f"{PLACEHOLDER}:1: {_UNUSED_MSG}"]


# ---------------------------------------------------------------------------
# behavior 6: unused findings printed after file/function findings, in order
# ---------------------------------------------------------------------------


def test_main_when_report_flag_and_mixed_findings_does_print_unused_after_limit_findings(
    tmp_path: Path,
) -> None:
    body_count = MAX_LINES_PER_FUNCTION + 1
    content = (
        "# pymaxlines: disable=max-lines\n"
        f"def small():  {_DISABLE}\n"
        "    x = 1\n"
        "\n\ndef big():\n" + INDENTED_CODE_LINE * body_count
    )
    file = write_module(tmp_path, content)

    exit_code, lines = _run_check_unused(file)

    big_lineno = 6
    big_total = body_count + 1
    assert exit_code == 1
    assert lines == [
        (
            f"{PLACEHOLDER}:{big_lineno}: function 'big' has {big_total} code lines"
            f" (max {MAX_LINES_PER_FUNCTION})"
        ),
        f"{PLACEHOLDER}:1: {_UNUSED_MSG}",
        f"{PLACEHOLDER}:2: {_UNUSED_MSG}",
    ]


# ---------------------------------------------------------------------------
# behavior 7: error directives are never also reported as unused
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("directive_line", "expected_msg"),
    [
        pytest.param(
            "# pymaxlines: enable\n",
            f"{PLACEHOLDER}:1: {_MALFORMED_MSG}",
            id="malformed",
        ),
        pytest.param(
            "# pymaxlines: disable=banana\n",
            _unknown_rule(1),
            id="unknown-rule",
        ),
    ],
)
def test_main_when_report_flag_and_directive_has_error_does_not_also_report_unused(
    tmp_path: Path, directive_line: str, expected_msg: str
) -> None:
    content = directive_line + CODE_LINE * 5
    file = write_module(tmp_path, content)

    exit_code, lines = _run_check_unused(file)

    assert exit_code == 1
    assert lines == [expected_msg]


def test_main_when_report_flag_and_misplaced_directive_does_not_also_report_unused(
    tmp_path: Path,
) -> None:
    content = "x = 1\n# pymaxlines: disable=max-lines\n" + CODE_LINE * 5
    file = write_module(tmp_path, content)

    exit_code, lines = _run_check_unused(file)

    assert exit_code == 1
    assert lines == [f"{PLACEHOLDER}:2: {_MISPLACED_MSG}"]


def test_main_when_report_flag_and_wrong_scope_directive_does_not_also_report_unused(
    tmp_path: Path,
) -> None:
    content = "def small():  # pymaxlines: disable=max-lines\n    x = 1\n"
    file = write_module(tmp_path, content)

    exit_code, lines = _run_check_unused(file)

    assert exit_code == 1
    assert lines == [f"{PLACEHOLDER}:1: {_WRONG_SCOPE_MSG}"]
