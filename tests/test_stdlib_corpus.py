"""Corpus test: run the linter over every .py file in the interpreter's standard library."""

from __future__ import annotations

import sysconfig
from pathlib import Path

import pytest
from conftest import capture_main

_STDLIB_DIR = Path(sysconfig.get_paths()["stdlib"])

_CORPUS: list[Path] = sorted(p for p in _STDLIB_DIR.rglob("*.py") if "site-packages" not in p.parts)

if not _CORPUS:
    pytest.fail(
        f"stdlib corpus is empty — no .py files found under {_STDLIB_DIR}",
        pytrace=False,
    )

_HUGE_LIMIT = str(10**9)

_IDS = [str(p.relative_to(_STDLIB_DIR)) for p in _CORPUS]


@pytest.mark.parametrize("path", _CORPUS, ids=_IDS)
def test_check_file_when_limits_above_any_file_does_emit_zero_diagnostics(path: Path):
    exit_code, output = capture_main(
        [
            "--max-lines",
            _HUGE_LIMIT,
            "--max-lines-test",
            _HUGE_LIMIT,
            "--max-lines-per-function",
            _HUGE_LIMIT,
            "--max-lines-per-function-test",
            _HUGE_LIMIT,
            str(path),
        ]
    )

    assert exit_code == 0, output
    assert output == ""


@pytest.mark.parametrize("path", _CORPUS, ids=_IDS)
def test_check_file_when_module_limit_zero_does_report_only_module_diagnostic(path: Path):
    exit_code, output = capture_main(
        [
            "--max-lines",
            "0",
            "--max-lines-test",
            "0",
            "--max-lines-per-function",
            _HUGE_LIMIT,
            "--max-lines-per-function-test",
            _HUGE_LIMIT,
            str(path),
        ]
    )

    if exit_code == 0:
        assert output == ""
    else:
        assert exit_code == 1, output
        lines = output.strip().splitlines()
        diagnostics = [ln for ln in lines if not ln.startswith("Found ")]
        assert len(diagnostics) == 1, output
        assert "Too many lines in module" in diagnostics[0]
        assert str(path) in diagnostics[0]
