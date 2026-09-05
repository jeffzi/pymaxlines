"""Tests for [tool.pymaxlines] configuration support."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

import pytest
from conftest import capture_main, expect_exit_two, file_diagnostic, write_code_lines

from pymaxlines import MAX_LINES_SRC, main

if TYPE_CHECKING:
    from pathlib import Path


def _write_pyproject(tmp_path: Path, toml_body: str) -> Path:
    path = tmp_path / "pyproject.toml"
    path.write_text(textwrap.dedent(toml_body))
    return path


def _project_with_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, toml_body: str, *, code_lines: int = 1
) -> Path:
    _write_pyproject(tmp_path, toml_body)
    file = write_code_lines(tmp_path, code_lines)
    monkeypatch.chdir(tmp_path)
    return file


# ---------------------------------------------------------------------------
# Behavior 1: config from pyproject.toml in CWD overrides built-in defaults
# ---------------------------------------------------------------------------


def test_load_config_when_cwd_has_pyproject_with_higher_limit_does_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = _project_with_config(
        tmp_path,
        monkeypatch,
        """\
        [tool.pymaxlines]
        max-lines = 9999
    """,
        code_lines=MAX_LINES_SRC + 1,
    )

    exit_code = main([str(file)])

    assert exit_code == 0


def test_load_config_when_cwd_has_pyproject_with_lower_limit_does_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured_limit = 5
    line_count = configured_limit + 1
    file = _project_with_config(
        tmp_path,
        monkeypatch,
        f"""\
        [tool.pymaxlines]
        max-lines = {configured_limit}
    """,
        code_lines=line_count,
    )

    exit_code, output = capture_main([str(file)])

    assert exit_code == 1
    expected = file_diagnostic(line_count, limit=configured_limit, path=str(file))
    assert expected in output


# ---------------------------------------------------------------------------
# Behavior 2: CLI flag wins over config; absent keys keep defaults
# ---------------------------------------------------------------------------


def test_load_config_when_cli_flag_overrides_config_does_use_flag_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = _project_with_config(
        tmp_path,
        monkeypatch,
        """\
        [tool.pymaxlines]
        max-lines = 5
    """,
        code_lines=10,
    )

    exit_code = main(["--max-lines", "9999", str(file)])

    assert exit_code == 0


def test_load_config_when_key_absent_from_config_does_keep_builtin_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = _project_with_config(
        tmp_path,
        monkeypatch,
        """\
        [tool.pymaxlines]
        skip-blank-lines = true
    """,
        code_lines=MAX_LINES_SRC + 1,
    )

    exit_code = main([str(file)])

    assert exit_code == 1


# ---------------------------------------------------------------------------
# Behavior 3: no pyproject.toml or no [tool.pymaxlines] -> built-in defaults
# ---------------------------------------------------------------------------


def test_load_config_when_no_pyproject_in_cwd_does_use_builtin_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = write_code_lines(tmp_path, MAX_LINES_SRC)
    monkeypatch.chdir(tmp_path)

    exit_code = main([str(file)])

    assert exit_code == 0


def test_load_config_when_pyproject_has_no_tool_table_does_use_builtin_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = _project_with_config(
        tmp_path,
        monkeypatch,
        """\
        [project]
        name = "something"
    """,
        code_lines=MAX_LINES_SRC,
    )

    exit_code = main([str(file)])

    assert exit_code == 0


# ---------------------------------------------------------------------------
# Behavior 4: --config PATH reads from given path
# ---------------------------------------------------------------------------


def test_load_config_when_config_flag_given_does_read_from_that_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "elsewhere"
    config_dir.mkdir()
    config_path = _write_pyproject(
        config_dir,
        """\
        [tool.pymaxlines]
        max-lines = 9999
    """,
    )
    file = write_code_lines(tmp_path, MAX_LINES_SRC + 1)
    monkeypatch.chdir(tmp_path)

    exit_code = main(["--config", str(config_path), str(file)])

    assert exit_code == 0


def test_load_config_when_config_flag_has_no_value_does_exit_two_with_program_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    file = write_code_lines(tmp_path, 1)
    monkeypatch.chdir(tmp_path)

    expect_exit_two([str(file), "--config"])

    err = capsys.readouterr().err
    assert err.startswith("usage: pymaxlines")


@pytest.mark.parametrize(
    ("explicit", "filename", "payload"),
    [
        pytest.param(True, "nonexistent.toml", None, id="path-does-not-exist"),
        pytest.param(False, "pyproject.toml", "mkdir", id="implicit-is-directory"),
        pytest.param(True, "some_dir", "mkdir", id="explicit-is-directory"),
        pytest.param(False, "pyproject.toml", b"\x80\x81\x82", id="implicit-is-not-valid-utf8"),
        pytest.param(True, "bad.toml", b"\x80\x81\x82", id="explicit-is-not-valid-utf8"),
        pytest.param(True, "bad.toml", "[invalid toml content\n", id="config-path-is-invalid-toml"),
    ],
)
def test_load_config_when_config_source_is_bad_does_exit_two(  # noqa: PLR0913, PLR0917 — parametrize fixtures
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    explicit: bool,
    filename: str,
    payload: str | bytes | None,
) -> None:
    config_path = tmp_path / filename
    if payload == "mkdir":
        config_path.mkdir()
    elif isinstance(payload, bytes):
        config_path.write_bytes(payload)
    elif isinstance(payload, str):
        config_path.write_text(payload)
    file = write_code_lines(tmp_path, 1)
    monkeypatch.chdir(tmp_path)
    argv = ["--config", str(config_path), str(file)] if explicit else [str(file)]

    expect_exit_two(argv)

    err = capsys.readouterr().err
    assert (str(config_path) if explicit else "pyproject.toml") in err


@pytest.mark.parametrize(
    ("toml_body", "expected_key"),
    [
        pytest.param(
            """\
            tool = "not a table"
        """,
            "[tool]",
            id="tool-not-table",
        ),
        pytest.param(
            """\
            [tool]
            pymaxlines = "not a table"
        """,
            "[tool.pymaxlines]",
            id="pymaxlines-not-table",
        ),
    ],
)
def test_load_config_when_key_is_not_table_does_exit_two(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    toml_body: str,
    expected_key: str,
) -> None:
    file = _project_with_config(tmp_path, monkeypatch, toml_body)

    expect_exit_two([str(file)])

    err = capsys.readouterr().err
    assert expected_key in err
    assert "pyproject.toml" in err


# ---------------------------------------------------------------------------
# Behavior 5: unknown key in table exits 2
# ---------------------------------------------------------------------------


def test_load_config_when_unknown_key_in_table_does_exit_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = _project_with_config(
        tmp_path,
        monkeypatch,
        """\
        [tool.pymaxlines]
        bogus-key = 42
    """,
    )

    expect_exit_two([str(file)])


# ---------------------------------------------------------------------------
# Behavior 6: wrong type value exits 2
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "value"),
    [
        pytest.param("max-lines", '"banana"', id="string-for-limit"),
        pytest.param("skip-blank-lines", "42", id="int-for-bool"),
        pytest.param("force-exclude", '"banana"', id="string-for-bool"),
        pytest.param("exclude", '"banana"', id="string-for-exclude"),
        pytest.param("exclude", "[42]", id="list-of-ints-for-exclude"),
    ],
)
def test_load_config_when_value_has_wrong_type_does_exit_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str, value: str
) -> None:
    file = _project_with_config(
        tmp_path,
        monkeypatch,
        f"""\
        [tool.pymaxlines]
        {key} = {value}
    """,
    )

    expect_exit_two([str(file)])


# ---------------------------------------------------------------------------
# Behavior 7: negative limit in table exits 2
# ---------------------------------------------------------------------------


_LIMIT_KEY_PARAMS = [
    pytest.param("max-lines", id="max-lines"),
    pytest.param("max-lines-test", id="max-lines-test"),
    pytest.param("max-lines-per-function", id="max-lines-per-function"),
    pytest.param("max-lines-per-function-test", id="max-lines-per-function-test"),
]


@pytest.mark.parametrize("key", _LIMIT_KEY_PARAMS)
def test_load_config_when_negative_limit_in_table_does_exit_two_with_config_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    key: str,
) -> None:
    file = _project_with_config(
        tmp_path,
        monkeypatch,
        f"""\
        [tool.pymaxlines]
        {key} = -1
    """,
    )

    expect_exit_two([str(file)])

    err = capsys.readouterr().err
    assert f"'{key}' in [tool.pymaxlines] of pyproject.toml must be a non-negative integer" in err


@pytest.mark.parametrize("key", _LIMIT_KEY_PARAMS)
def test_load_config_when_zero_limit_in_table_does_accept_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    file = _project_with_config(
        tmp_path,
        monkeypatch,
        f"""\
        [tool.pymaxlines]
        {key} = 0
    """,
        code_lines=0,
    )

    exit_code = main([str(file)])

    assert exit_code == 0


# ---------------------------------------------------------------------------
# Behavior 8: exclude accepted as list of glob strings
# ---------------------------------------------------------------------------


def test_load_config_when_exclude_is_valid_list_does_not_alter_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = _project_with_config(
        tmp_path,
        monkeypatch,
        """\
        [tool.pymaxlines]
        exclude = ["*.generated.py"]
    """,
        code_lines=MAX_LINES_SRC + 1,
    )

    exit_code = main([str(file)])

    assert exit_code == 1


# ---------------------------------------------------------------------------
# Behavior 9: force-exclude config and CLI precedence
# ---------------------------------------------------------------------------


def test_load_config_when_force_exclude_true_in_config_does_apply_exclude_to_explicit_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project_with_config(
        tmp_path,
        monkeypatch,
        """\
        [tool.pymaxlines]
        force-exclude = true
        exclude = ["generated"]
    """,
    )
    target_path = write_code_lines(tmp_path, MAX_LINES_SRC + 1, "generated/auto.py")

    exit_code, output = capture_main([str(target_path)])

    assert exit_code == 0
    assert output == ""


def test_load_config_when_no_force_exclude_cli_overrides_config_true_does_check_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project_with_config(
        tmp_path,
        monkeypatch,
        """\
        [tool.pymaxlines]
        force-exclude = true
        exclude = ["generated"]
    """,
    )
    target = write_code_lines(tmp_path, MAX_LINES_SRC + 1, "generated/auto.py")

    exit_code, _output = capture_main(["--no-force-exclude", str(target)])

    assert exit_code == 1


# ---------------------------------------------------------------------------
# Guard: every spec dest name is a Config field
# ---------------------------------------------------------------------------


def test_every_spec_dest_name_is_a_config_field() -> None:
    from dataclasses import fields

    from pymaxlines._cli import Config
    from pymaxlines._config import BOOL_SPECS, LIMIT_SPECS, dest_name

    config_fields = {f.name for f in fields(Config)}
    for name, _, _ in (*LIMIT_SPECS, *BOOL_SPECS):
        assert dest_name(name) in config_fields, f"spec '{name}' has no Config field"
