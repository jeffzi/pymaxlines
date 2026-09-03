"""End-to-end tests for the pre-commit hook integration."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from pymaxlines import MAX_LINES_PER_FUNCTION, MAX_LINES_SRC

_HOOK_REPO = str(Path(__file__).resolve().parent.parent)
_CODE_LINE = "x = 1\n"
_INDENTED_CODE_LINE = "    x = 1\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603 — fixed args, no user input
        ["git", *args],  # noqa: S607 — resolving git from PATH is intended in this test harness
        check=True,
        capture_output=True,
        cwd=repo,
    )


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A disposable git repo with minimal user config."""
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@test.com")
    _git(tmp_path, "config", "user.name", "Test")
    return tmp_path


def _stage(repo: Path, name: str, content: str) -> Path:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    _git(repo, "add", name)
    return path


def _run_hook(repo: Path) -> subprocess.CompletedProcess[str]:
    # Strip pytest-cov's COV_CORE_* vars so the pre-commit subprocess doesn't
    # start its own coverage collector and corrupt the parent's data.
    env = {k: v for k, v in os.environ.items() if not k.startswith("COV_CORE")}
    return subprocess.run(  # noqa: S603 — fixed interpreter and args, no shell
        [
            sys.executable,
            "-m",
            "pre_commit",
            "try-repo",
            _HOOK_REPO,
            "check-max-lines",
            "--all-files",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo,
        env=env,
    )


# ---------------------------------------------------------------------------
# pre-commit hook — end-to-end
# ---------------------------------------------------------------------------


def test_hook_when_file_within_limit_does_pass(git_repo: Path) -> None:
    _stage(git_repo, "module.py", _CODE_LINE * MAX_LINES_SRC)

    result = _run_hook(git_repo)

    assert result.returncode == 0


def test_hook_when_file_exceeds_limit_does_fail_with_diagnostic(git_repo: Path) -> None:
    _stage(git_repo, "module.py", _CODE_LINE * (MAX_LINES_SRC + 1))

    result = _run_hook(git_repo)

    assert result.returncode == 1
    assert f"module.py: {MAX_LINES_SRC + 1} code lines (max {MAX_LINES_SRC})" in result.stdout


def test_hook_when_function_exceeds_limit_does_fail_with_diagnostic(git_repo: Path) -> None:
    content = "def big():\n" + _INDENTED_CODE_LINE * MAX_LINES_PER_FUNCTION
    _stage(git_repo, "module.py", content)

    result = _run_hook(git_repo)

    assert result.returncode == 1
    assert (
        f"module.py:1: function 'big' has {MAX_LINES_PER_FUNCTION + 1} code lines" in result.stdout
    )


def test_hook_when_non_python_file_does_skip(git_repo: Path) -> None:
    _stage(git_repo, "data.txt", _CODE_LINE * (MAX_LINES_SRC + 1))

    result = _run_hook(git_repo)

    assert result.returncode == 0
