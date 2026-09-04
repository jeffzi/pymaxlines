"""End-to-end smoke tests: clone a real-world project and run pymaxlines against it."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest
from conftest import REPO_ROOT

from pymaxlines import main

if TYPE_CHECKING:
    from pathlib import Path

# Target repo — change these three to swap the e2e corpus.
_REPO_TAG = "v2.12.0"
_REPO_URL = "https://github.com/pydantic/httpx2.git"
_REPO_SLUG = hashlib.sha256(f"{_REPO_URL}@{_REPO_TAG}".encode()).hexdigest()[:12]
_REPO_DIR = REPO_ROOT / ".cache" / "e2e" / f"httpx2-{_REPO_SLUG}"

_CONNECTIVITY_SIGNATURES = (
    "Could not resolve host",
    "unable to access",
    "Connection timed out",
    "Connection refused",
    "Failed to connect",
)


def _clone_repo(git: str, target_dir: Path) -> Path:
    """Shallow-clone the target repo into *target_dir*, discriminating clone failures.

    Connectivity errors (DNS, timeout, refused) produce ``pytest.skip`` with the
    actual stderr.  All other ``CalledProcessError`` failures (wrong tag, repo not
    found, unknown) re-raise so the test run fails loudly.
    """
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(  # noqa: S603 — all arguments are hardcoded constants
            [
                git,
                "clone",
                "--depth",
                "1",
                "--branch",
                _REPO_TAG,
                _REPO_URL,
                str(target_dir),
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr_text = (exc.stderr or b"").decode(errors="replace")
        if any(sig in stderr_text for sig in _CONNECTIVITY_SIGNATURES):
            pytest.skip(stderr_text.strip())
        raise

    return target_dir


def _origin_matches(git: str, repo_dir: Path) -> bool:
    """Check whether *repo_dir*'s ``origin`` remote points at the pinned corpus URL."""
    result = subprocess.run(  # noqa: S603 — all arguments are hardcoded constants
        [git, "remote", "get-url", "origin"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() == _REPO_URL


@pytest.fixture(scope="session")
def e2e_checkout() -> Path:
    """Clone the target repo at a pinned tag; reuse the checkout on subsequent runs."""
    git = shutil.which("git")
    if not git:
        pytest.skip("git is not available")

    if _REPO_DIR.exists() and (_REPO_DIR / ".git").is_dir() and _origin_matches(git, _REPO_DIR):
        return _REPO_DIR

    if _REPO_DIR.exists():
        shutil.rmtree(_REPO_DIR)

    return _clone_repo(git, _REPO_DIR)


@pytest.fixture
def e2e_py_files(e2e_checkout: Path) -> list[str]:
    """All Python files in the e2e checkout, for running pymaxlines against."""
    py_files = [str(p) for p in sorted(e2e_checkout.rglob("*.py"))]
    if not py_files:
        pytest.fail("no .py files found in e2e checkout")
    return py_files


@pytest.mark.e2e
def test_pymaxlines_when_run_against_e2e_repo_does_detect_oversized_file(
    e2e_py_files: list[str], capsys: pytest.CaptureFixture[str]
):
    exit_code = main(e2e_py_files)

    assert exit_code == 1
    out = capsys.readouterr().out
    assert any("code lines (max" in line for line in out.splitlines())


# ---------------------------------------------------------------------------
# _clone_repo — git clone failure discrimination
# ---------------------------------------------------------------------------


def _run_clone_with_fake_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stderr: bytes
) -> Path:
    """Rig subprocess.run to fail, then call the helper the e2e_checkout fixture delegates to."""
    target_dir = tmp_path / "clone-target"
    error = subprocess.CalledProcessError(128, ["git", "clone"], output=b"", stderr=stderr)

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise error

    monkeypatch.setattr(subprocess, "run", _raise)

    return _clone_repo("/usr/bin/git", target_dir)


def test_clone_repo_when_connectivity_error_does_skip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stderr = b"fatal: unable to access 'https://...': Could not resolve host: github.com\n"

    with pytest.raises(pytest.skip.Exception) as exc_info:
        _run_clone_with_fake_error(monkeypatch, tmp_path, stderr)

    assert stderr.decode().strip() in str(exc_info.value)


def test_clone_repo_when_non_connectivity_error_does_not_skip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stderr = b"fatal: Remote branch v99.99.99 not found in upstream origin\n"

    with pytest.raises(subprocess.CalledProcessError):
        _run_clone_with_fake_error(monkeypatch, tmp_path, stderr)
