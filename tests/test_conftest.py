"""Tests for the e2e marker gating plugin in conftest.py."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from _pytest.pytester import Pytester

pytest_plugins = ["pytester"]

_CONFTEST_SOURCE = (Path(__file__).parent / "conftest.py").read_text()
_SAMPLE_TESTS = """
import pytest

@pytest.mark.e2e
def test_e2e_clone_repo():
    pass

def test_unit_parse():
    pass
"""


@pytest.fixture
def pytester(pytester: Pytester) -> Pytester:
    """A pytester sandbox preloaded with the real conftest.py plugin and the e2e marker."""
    pytester.makeini("[pytest]\naddopts = -p no:sugar\nmarkers =\n    e2e: end-to-end test\n")
    pytester.makeconftest(_CONFTEST_SOURCE)
    pytester.makepyfile(_SAMPLE_TESTS)
    return pytester


def test_e2e_tests_when_run_e2e_flag_absent_does_deselect_them(pytester: Pytester):
    result = pytester.runpytest()

    result.assert_outcomes(passed=1, deselected=1)


def test_e2e_tests_when_run_e2e_flag_present_does_run_them(pytester: Pytester):
    result = pytester.runpytest("--run-e2e")

    result.assert_outcomes(passed=2)
