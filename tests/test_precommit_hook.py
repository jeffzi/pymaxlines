"""End-to-end tests for the pre-commit hook integration."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

from pymaxlines import MAX_LINES_PER_FUNCTION, MAX_LINES_SRC

_HOOK_REPO = Path(__file__).resolve().parent.parent
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
def git_repo(tmp_path: Path) -> Iterator[Path]:
    """A disposable git repo on the same drive as the hook source.

    ``pre-commit try-repo`` computes a relative path between the test repo and
    the hook source. On Windows CI the default ``tmp_path`` can land on a
    different drive (C:) than the checkout (D:), making ``os.path.relpath``
    impossible and causing exit code 3.
    """
    if tmp_path.anchor != _HOOK_REPO.anchor:
        td = tempfile.TemporaryDirectory(dir=_HOOK_REPO.parent)
        work = Path(td.name)
    else:
        td = None
        work = tmp_path

    _git(work, "init")
    _git(work, "config", "user.email", "test@test.com")
    _git(work, "config", "user.name", "Test")
    yield work

    if td is not None:
        td.cleanup()


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
            str(_HOOK_REPO),
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
