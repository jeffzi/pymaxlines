"""Tests for --show-sizes mode: flag dispatch, tree construction, and text rendering."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

import pytest
from conftest import (
    CODE_LINE,
    INDENTED_CODE_LINE,
    capture_main,
    write_code_lines,
    write_module,
)

from pymaxlines import MAX_LINES_PER_FUNCTION, MAX_LINES_SRC, main

if TYPE_CHECKING:
    from pathlib import Path


def _sizes_output(file: Path, *extra_args: str) -> tuple[int, str]:
    """Run main with --show-sizes and return (exit_code, stdout)."""
    return capture_main(["--show-sizes", *extra_args, str(file)])


def _big_function_with_block(total_body_lines: int) -> str:
    """Return def big(): source with total_body_lines code lines, including one if-block."""
    return "def big():\n    if True:\n        pass\n" + INDENTED_CODE_LINE * (total_body_lines - 2)


# ---------------------------------------------------------------------------
# Group A: Flags and dispatch
# ---------------------------------------------------------------------------


def test_show_sizes_when_flag_given_does_print_listing_and_exit_zero(tmp_path: Path) -> None:
    file = write_code_lines(tmp_path, 10)

    exit_code, output = _sizes_output(file)

    assert exit_code == 0
    assert str(file) in output


def test_show_sizes_when_help_flag_given_does_describe_show_sizes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "--show-sizes" in help_text
    assert "code-line breakdown" in help_text
    assert "--skip-" in help_text


def test_show_sizes_when_empty_discovery_does_warn_and_exit_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)

    exit_code = main(["--show-sizes"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no .py files" in captured.err.lower()


@pytest.mark.parametrize(
    ("source", "unexpected_rule"),
    [
        pytest.param(CODE_LINE * (MAX_LINES_SRC + 1), "max-lines", id="file-over-limit"),
        pytest.param(
            "def big():\n" + INDENTED_CODE_LINE * (MAX_LINES_PER_FUNCTION + 1),
            "max-lines-per-function",
            id="function-over-limit",
        ),
    ],
)
def test_show_sizes_when_limit_exceeded_does_not_emit_diagnostic(
    tmp_path: Path, source: str, unexpected_rule: str
) -> None:
    file = write_module(tmp_path, source)

    exit_code, output = _sizes_output(file)

    assert exit_code == 0
    assert unexpected_rule not in output
    assert "Too many lines" not in output


def test_show_sizes_when_unreadable_file_does_report_error_and_exit_one(
    tmp_path: Path,
) -> None:
    absent = tmp_path / "absent.py"
    clean = write_code_lines(tmp_path, 5, "clean.py")

    exit_code, output = capture_main(["--show-sizes", str(absent), str(clean)])

    assert exit_code == 1
    assert "could not read" in output
    assert "Found 1 error." in output
    assert str(clean) in output


def test_show_sizes_when_directive_has_error_does_report_after_listing_and_exit_one(
    tmp_path: Path,
) -> None:
    content = "# pymaxlines: disable=banana\n" + CODE_LINE * 5
    file = write_module(tmp_path, content)

    exit_code, output = _sizes_output(file)

    assert exit_code == 1
    listing_pos = output.index("code lines")
    error_pos = output.index("unknown rule")
    assert listing_pos < error_pos
    assert "Found 1 error." in output


def test_show_sizes_when_exclude_flag_given_does_exclude_matching_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_code_lines(tmp_path, 10, "src/module.py")
    write_code_lines(tmp_path, 10, "generated/auto.py")
    monkeypatch.chdir(tmp_path)

    exit_code, output = capture_main(["--show-sizes", "--exclude", "generated", "."])

    assert exit_code == 0
    assert "module.py" in output
    assert "auto.py" not in output


@pytest.mark.parametrize(
    ("extra_args", "expected"),
    [
        ((), "5 code lines"),
        (("--no-skip-comments",), "7 code lines"),
    ],
)
def test_show_sizes_when_skip_flags_change_does_affect_code_line_counts(
    tmp_path: Path, extra_args: tuple[str, ...], expected: str
) -> None:
    source = "# comment\n# comment\n" + CODE_LINE * 5
    file = write_module(tmp_path, source)

    _exit_code, output = _sizes_output(file, *extra_args)

    assert expected in output


def test_show_sizes_when_unused_disable_directive_does_not_report_it(
    tmp_path: Path,
) -> None:
    content = "# pymaxlines: disable=max-lines-per-function\ndef small():\n    x = 1\n"
    file = write_module(tmp_path, content)

    exit_code, output = _sizes_output(file, "--report-unused-disable-directives")

    assert exit_code == 0
    assert "unused pymaxlines-disable directive" not in output


# ---------------------------------------------------------------------------
# Group B: Tree construction
# ---------------------------------------------------------------------------


def test_show_sizes_when_file_has_functions_does_list_them_with_code_line_counts(
    tmp_path: Path,
) -> None:
    source = "def foo():\n" + INDENTED_CODE_LINE * 5 + "\ndef bar():\n" + INDENTED_CODE_LINE * 3
    file = write_module(tmp_path, source)

    exit_code, output = _sizes_output(file)

    assert exit_code == 0
    lines = output.splitlines()
    foo_line = next(line for line in lines if "def foo" in line)
    bar_line = next(line for line in lines if "def bar" in line)
    assert foo_line.startswith("  1-6  def foo")
    assert foo_line.endswith(f"5/{MAX_LINES_PER_FUNCTION}")
    assert bar_line.startswith("  8-11  def bar")
    assert bar_line.endswith(f"3/{MAX_LINES_PER_FUNCTION}")


def test_show_sizes_when_file_has_async_def_does_label_async_def(tmp_path: Path) -> None:
    source = "async def handler():\n" + INDENTED_CODE_LINE * 3
    file = write_module(tmp_path, source)

    exit_code, output = _sizes_output(file)

    assert exit_code == 0
    assert "async def handler" in output


def test_show_sizes_when_file_has_class_does_list_class_with_children(
    tmp_path: Path,
) -> None:
    source = textwrap.dedent("""\
        class MyClass:
            def method(self):
                x = 1
                y = 2

            def other(self):
                z = 3
    """)
    file = write_module(tmp_path, source)

    exit_code, output = _sizes_output(file)

    assert exit_code == 0
    lines = output.splitlines()
    class_line = next(line for line in lines if "class MyClass" in line)
    method_line = next(line for line in lines if "def method" in line)
    other_line = next(line for line in lines if "def other" in line)
    assert class_line.startswith("  1-7  class MyClass")
    assert class_line.endswith("6")
    assert method_line.startswith("    2-4  def method")
    assert method_line.endswith(f"2/{MAX_LINES_PER_FUNCTION}")
    assert other_line.startswith("    6-7  def other")
    assert other_line.endswith(f"1/{MAX_LINES_PER_FUNCTION}")


def test_show_sizes_when_file_has_imports_does_group_consecutive_imports(
    tmp_path: Path,
) -> None:
    source = "import os\nimport sys\nfrom pathlib import Path\n\nx = 1\n"
    file = write_module(tmp_path, source)

    exit_code, output = _sizes_output(file)

    assert exit_code == 0
    lines = output.splitlines()
    imports_line = next(line for line in lines if "imports" in line)
    assert imports_line.startswith("  1-3  imports")
    assert imports_line.endswith("3")


def test_show_sizes_when_file_has_module_level_code_does_group_it(
    tmp_path: Path,
) -> None:
    source = "x = 1\ny = 2\nz = 3\n"
    file = write_module(tmp_path, source)

    exit_code, output = _sizes_output(file)

    assert exit_code == 0
    lines = output.splitlines()
    code_line = next(line for line in lines if "module-level code" in line)
    assert code_line.startswith("  1-3  module-level code")
    assert code_line.endswith("3")


def test_show_sizes_when_multiple_files_does_order_by_code_lines_descending(
    tmp_path: Path,
) -> None:
    small = write_code_lines(tmp_path, 5, "small.py")
    big = write_code_lines(tmp_path, 20, "big.py")
    medium = write_code_lines(tmp_path, 10, "medium.py")

    exit_code, output = capture_main(
        [
            "--show-sizes",
            str(small),
            str(big),
            str(medium),
        ]
    )

    assert exit_code == 0
    big_pos = output.index(str(big))
    medium_pos = output.index(str(medium))
    small_pos = output.index(str(small))
    assert big_pos < medium_pos < small_pos


def test_show_sizes_when_files_have_same_code_lines_does_order_by_path_ascending(
    tmp_path: Path,
) -> None:
    a_file = write_code_lines(tmp_path, 5, "aaa.py")
    z_file = write_code_lines(tmp_path, 5, "zzz.py")

    exit_code, output = capture_main(["--show-sizes", str(z_file), str(a_file)])

    assert exit_code == 0
    a_pos = output.index(str(a_file))
    z_pos = output.index(str(z_file))
    assert a_pos < z_pos


@pytest.mark.parametrize(
    ("total_body_lines", "extra_args", "expect_block"),
    [
        pytest.param(MAX_LINES_PER_FUNCTION + 1, (), True, id="over-limit"),
        pytest.param(4, (), False, id="under-limit"),
        pytest.param(102, ("--max-lines-per-function", "0"), False, id="limit-zero"),
    ],
)
def test_show_sizes_when_function_has_block_does_list_blocks_only_when_over_limit(
    tmp_path: Path, total_body_lines: int, extra_args: tuple[str, ...], expect_block: bool
) -> None:
    source = _big_function_with_block(total_body_lines)
    file = write_module(tmp_path, source)

    exit_code, output = _sizes_output(file, *extra_args)

    assert exit_code == 0
    assert "def big" in output
    assert ("if True:" in output) is expect_block


def test_show_sizes_when_class_has_decorator_does_span_from_decorator(
    tmp_path: Path,
) -> None:
    source = textwrap.dedent("""\
        import dataclasses

        @dataclasses.dataclass
        class Point:
            x: int = 0
            y: int = 0
    """)
    file = write_module(tmp_path, source)

    exit_code, output = _sizes_output(file)

    assert exit_code == 0
    lines = output.splitlines()
    class_line = next(line for line in lines if "class Point" in line)
    assert class_line.startswith("  3-6  class Point")
    assert class_line.endswith("4")


def test_show_sizes_when_exempted_function_does_appear_in_listing(
    tmp_path: Path,
) -> None:
    source = "# pymaxlines: disable=max-lines-per-function\ndef big():\n" + INDENTED_CODE_LINE * (
        MAX_LINES_PER_FUNCTION + 10
    )
    file = write_module(tmp_path, source)

    exit_code, output = _sizes_output(file)

    assert exit_code == 0
    assert "def big" in output


def test_show_sizes_when_nested_function_does_show_as_child(tmp_path: Path) -> None:
    source = textwrap.dedent("""\
        def outer():
            def inner():
                x = 1
            y = 2
    """)
    file = write_module(tmp_path, source)

    exit_code, output = _sizes_output(file)

    assert exit_code == 0
    lines = output.splitlines()
    outer_line = next(line for line in lines if "def outer" in line)
    inner_line = next(line for line in lines if "def inner" in line)
    assert outer_line.startswith("  1-4  def outer")
    assert outer_line.endswith(f"3/{MAX_LINES_PER_FUNCTION}")
    assert inner_line.startswith("    2-3  def inner")
    assert inner_line.endswith(f"1/{MAX_LINES_PER_FUNCTION}")


def test_show_sizes_when_block_label_is_long_does_truncate_to_40_chars(
    tmp_path: Path,
) -> None:
    long_condition = "x" * 60
    source = (
        "def big():\n"
        f"    if {long_condition}:\n"
        "        pass\n" + INDENTED_CODE_LINE * MAX_LINES_PER_FUNCTION
    )
    file = write_module(tmp_path, source)

    exit_code, output = _sizes_output(file)

    assert exit_code == 0
    lines = output.splitlines()
    block_lines = [line for line in lines if "if " in line and "x" in line]
    assert len(block_lines) == 1
    expected_label = "if " + "x" * 37
    assert f"{expected_label}…" in block_lines[0]


# ---------------------------------------------------------------------------
# Group C: Text rendering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("count", "expect_over_by"),
    [
        pytest.param(MAX_LINES_SRC + 5, 5, id="over-limit"),
        pytest.param(MAX_LINES_SRC, None, id="at-limit"),
    ],
)
def test_show_sizes_when_file_size_varies_does_show_over_by_only_when_exceeded(
    tmp_path: Path, count: int, expect_over_by: int | None
) -> None:
    file = write_code_lines(tmp_path, count)

    exit_code, output = _sizes_output(file)

    assert exit_code == 0
    assert f"{count} code lines" in output
    assert f"limit {MAX_LINES_SRC}" in output
    if expect_over_by is None:
        assert "over by" not in output
    else:
        assert f"over by {expect_over_by}" in output


@pytest.mark.parametrize(
    ("extra_args", "expected_count_str"),
    [
        pytest.param((), f"10/{MAX_LINES_PER_FUNCTION}", id="limit-set"),
        pytest.param(("--max-lines-per-function", "0"), "10", id="limit-zero"),
    ],
)
def test_show_sizes_when_function_limit_varies_does_show_count_format(
    tmp_path: Path, extra_args: tuple[str, ...], expected_count_str: str
) -> None:
    body = 10
    source = "def foo():\n" + INDENTED_CODE_LINE * body
    file = write_module(tmp_path, source)

    exit_code, output = _sizes_output(file, *extra_args)

    assert exit_code == 0
    lines = output.splitlines()
    func_lines = [line for line in lines if "def foo" in line]
    assert len(func_lines) == 1
    assert func_lines[0].rstrip().endswith(expected_count_str)


def test_show_sizes_when_entries_have_varying_widths_does_align_counts(
    tmp_path: Path,
) -> None:
    source = textwrap.dedent("""\
        import os

        x = 1

        def short_name():
            a = 1

        def a_function_with_a_very_long_name():
            b = 1
    """)
    file = write_module(tmp_path, source)

    exit_code, output = _sizes_output(file)

    assert exit_code == 0
    entry_lines = [line for line in output.splitlines() if line.startswith("  ")]
    assert len(entry_lines) == 4
    count_positions = [len(line.rstrip()) for line in entry_lines]
    assert len(set(count_positions)) == 1


def test_show_sizes_when_multiple_files_does_separate_with_blank_line(
    tmp_path: Path,
) -> None:
    file_a = write_code_lines(tmp_path, 5, "aaa.py")
    file_b = write_code_lines(tmp_path, 3, "bbb.py")

    exit_code, output = capture_main(["--show-sizes", str(file_a), str(file_b)])

    assert exit_code == 0
    first_block, second_block = output.rstrip("\n").split("\n\n")
    assert first_block.startswith(str(file_a))
    assert second_block.startswith(str(file_b))


def test_show_sizes_when_empty_file_does_print_only_header(tmp_path: Path) -> None:
    file = write_module(tmp_path, "")

    exit_code, output = _sizes_output(file)

    assert exit_code == 0
    lines = output.strip().splitlines()
    assert len(lines) == 1
    assert "0 code lines" in lines[0]


def test_show_sizes_when_errors_occur_does_print_diagnostics_after_listing(
    tmp_path: Path,
) -> None:
    good = write_code_lines(tmp_path, 5, "good.py")
    bad = write_module(tmp_path, "def f(\n", "bad.py")

    exit_code, output = capture_main(["--show-sizes", str(good), str(bad)])

    assert exit_code == 1
    good_pos = output.index(str(good))
    error_pos = output.index("could not parse")
    assert good_pos < error_pos
    assert "Found 1 error." in output
