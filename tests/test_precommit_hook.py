"""End-to-end tests for the pre-commit hook integration."""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

from conftest import (
    CODE_LINE,
    REPO_ROOT,
    file_diagnostic,
    function_diagnostic,
    make_oversized_function,
)

from pymaxlines import MAX_LINES_SRC

_CONNECTIVITY_SIGNATURES = (
    "Could not resolve host",
    "unable to access",
    "Connection timed out",
    "Connection refused",
    "Failed to connect",
    "index server",
)


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
    with contextlib.ExitStack() as stack:
        if tmp_path.anchor != REPO_ROOT.anchor:
            work = Path(stack.enter_context(tempfile.TemporaryDirectory(dir=REPO_ROOT.parent)))
        else:
            work = tmp_path

        _git(work, "init")
        _git(work, "config", "user.email", "test@test.com")
        _git(work, "config", "user.name", "Test")
        yield work


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
    try:
        result = subprocess.run(  # noqa: S603 — fixed interpreter and args, no shell
            [
                sys.executable,
                "-m",
                "pre_commit",
                "try-repo",
                str(REPO_ROOT),
                "check-max-lines",
                "--all-files",
            ],
            capture_output=True,
            text=True,
            check=False,
            cwd=repo,
            env=env,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("pre-commit try-repo timed out")
    combined = result.stdout + result.stderr
    if any(sig in combined for sig in _CONNECTIVITY_SIGNATURES):
        pytest.skip(f"network: {combined.strip()[:200]}")
    return result


# ---------------------------------------------------------------------------
# pre-commit hook — end-to-end
# ---------------------------------------------------------------------------


def test_hook_when_py_within_limit_and_oversized_non_py_staged_does_pass(git_repo: Path) -> None:
    _stage(git_repo, "module.py", CODE_LINE * MAX_LINES_SRC)
    _stage(git_repo, "data.txt", CODE_LINE * (MAX_LINES_SRC + 1))

    result = _run_hook(git_repo)

    assert result.returncode == 0


def test_hook_when_file_or_function_exceeds_limit_does_fail_with_diagnostics(
    git_repo: Path,
) -> None:
    _stage(git_repo, "oversized.py", CODE_LINE * (MAX_LINES_SRC + 1))
    func_source, func_count = make_oversized_function()
    _stage(git_repo, "big_function.py", func_source)

    result = _run_hook(git_repo)

    assert result.returncode == 1
    assert file_diagnostic(MAX_LINES_SRC + 1, path="oversized.py") in result.stdout
    assert function_diagnostic(1, "big", func_count, path="big_function.py") in result.stdout
