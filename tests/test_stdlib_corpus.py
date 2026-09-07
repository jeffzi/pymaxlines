"""Corpus test: run the linter over every .py file in the interpreter's standard library."""

from __future__ import annotations

import ast
import io
import sysconfig
import tokenize
from pathlib import Path

import pytest
from conftest import capture_main, diagnostic_lines

_STDLIB_DIR = Path(sysconfig.get_paths()["stdlib"])

_ALL_STDLIB: list[Path] = sorted(
    p for p in _STDLIB_DIR.rglob("*.py") if "site-packages" not in p.parts
)

if not _ALL_STDLIB:
    pytest.skip(
        f"stdlib corpus is empty — no .py files found under {_STDLIB_DIR}",
        allow_module_level=True,
    )

_HUGE_LIMIT = str(10**9)

_ALL_LIMITS_HUGE = [
    "--max-lines",
    _HUGE_LIMIT,
    "--max-lines-test",
    _HUGE_LIMIT,
    "--max-lines-per-function",
    _HUGE_LIMIT,
    "--max-lines-per-function-test",
    _HUGE_LIMIT,
]

_FUNCTION_LIMITS_HUGE = [
    "--max-lines-per-function",
    _HUGE_LIMIT,
    "--max-lines-per-function-test",
    _HUGE_LIMIT,
]


def _classify_stdlib_file(path: Path) -> str:
    """Classify *path* as ``"ok"``, ``"read"``, or ``"parse"``.

    Uses ``tokenize.open``, ``ast.parse``, and ``tokenize.generate_tokens``
    from the standard library — deliberately independent of ``analyze_file``
    so a regression that makes the linter reject valid files still fails the
    corpus test.

    The classification approximates what ``analyze_file`` would report: a file
    that fails ``tokenize.open`` with an I/O or encoding error maps to
    ``"could not read"``; one that fails ``ast.parse``,
    ``tokenize.generate_tokens``, or ``tokenize.open`` with a ``SyntaxError``
    maps to ``"could not parse"``.
    """
    try:
        with tokenize.open(path) as handle:
            source = handle.read()
    except (OSError, UnicodeDecodeError):
        return "read"
    except (SyntaxError, ValueError, RecursionError):
        return "parse"
    try:
        ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return "parse"
    try:
        list(tokenize.generate_tokens(io.StringIO(source).readline))
    except tokenize.TokenError:
        return "parse"
    return "ok"


_CLASSIFICATION = {p: _classify_stdlib_file(p) for p in _ALL_STDLIB}
_PARSEABLE = [p for p, c in _CLASSIFICATION.items() if c == "ok"]
_UNPARSABLE = [p for p, c in _CLASSIFICATION.items() if c != "ok"]


def _ids(paths: list[Path]) -> list[str]:
    return [str(p.relative_to(_STDLIB_DIR)) for p in paths]


# ---------------------------------------------------------------------------
# Parseable files
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", _PARSEABLE, ids=_ids(_PARSEABLE))
def test_check_file_when_limits_above_any_file_does_emit_zero_diagnostics(path: Path) -> None:
    exit_code, output = capture_main([*_ALL_LIMITS_HUGE, str(path)])

    assert exit_code == 0, output
    assert output == ""


@pytest.mark.parametrize("path", _PARSEABLE, ids=_ids(_PARSEABLE))
def test_check_file_when_module_limit_zero_does_report_module_diagnostic(path: Path) -> None:
    exit_code, output = capture_main(
        [
            "--max-lines",
            "0",
            "--max-lines-test",
            "0",
            "--no-skip-blank-lines",
            "--no-skip-comments",
            "--no-skip-docstrings",
            *_FUNCTION_LIMITS_HUGE,
            str(path),
        ]
    )

    if path.stat().st_size == 0:
        assert exit_code == 0, output
        assert output == ""
    else:
        assert exit_code == 1, output
        diagnostics = diagnostic_lines(output)
        assert len(diagnostics) == 1, output
        assert "Too many lines in module" in diagnostics[0]
        assert str(path) in diagnostics[0]


# ---------------------------------------------------------------------------
# Unparsable files
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", _UNPARSABLE, ids=_ids(_UNPARSABLE))
def test_check_file_when_file_is_unparsable_does_report_one_error(path: Path) -> None:
    exit_code, output = capture_main([*_ALL_LIMITS_HUGE, str(path)])

    expected_verb = "could not read" if _CLASSIFICATION[path] == "read" else "could not parse"
    assert exit_code == 1, output
    diagnostics = diagnostic_lines(output)
    assert len(diagnostics) == 1, output
    assert expected_verb in diagnostics[0]
    assert str(path) in diagnostics[0]
