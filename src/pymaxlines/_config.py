"""Load and validate ``[tool.pymaxlines]`` from a TOML configuration file."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

if TYPE_CHECKING:
    import argparse

MAX_LINES_SRC = 400
MAX_LINES_TEST = 800
MAX_LINES_PER_FUNCTION = 60
MAX_LINES_PER_FUNCTION_TEST = 0

# Single source of truth for the limit/bool key names, shared between CLI flag
# declarations (_cli.py) and TOML config validation (below), so adding one
# without the other is impossible.
LIMIT_SPECS: tuple[tuple[str, int, str], ...] = (
    ("max-lines", MAX_LINES_SRC, "code-line limit for source files"),
    ("max-lines-test", MAX_LINES_TEST, "code-line limit for test files"),
    (
        "max-lines-per-function",
        MAX_LINES_PER_FUNCTION,
        "per-function code-line limit for source files; 0 disables",
    ),
    (
        "max-lines-per-function-test",
        MAX_LINES_PER_FUNCTION_TEST,
        "per-function code-line limit for test files; 0 disables",
    ),
)

BOOL_SPECS: tuple[tuple[str, bool, str], ...] = (
    ("skip-blank-lines", True, "exclude blank lines from counts (default: %(default)s)"),
    ("skip-comments", True, "exclude comment-only lines from counts (default: %(default)s)"),
    ("skip-docstrings", True, "exclude docstring lines from counts (default: %(default)s)"),
    (
        "report-unused-disable-directives",
        False,
        "report pymaxlines-disable directives that suppress no findings (default: %(default)s)",
    ),
    (
        "force-exclude",
        False,
        "apply exclude globs to explicitly passed paths (default: %(default)s)",
    ),
)

_LIMIT_KEYS = frozenset(name for name, _, _ in LIMIT_SPECS)
_BOOL_KEYS = frozenset(name for name, _, _ in BOOL_SPECS)
_ALLOWED_KEYS = _LIMIT_KEYS | _BOOL_KEYS | {"exclude"}


def _type_error(
    key: str,
    expected: str,
    config_path: Path,
    parser: argparse.ArgumentParser,
) -> NoReturn:
    parser.error(f"'{key}' in [tool.pymaxlines] of {config_path} must be {expected}")


def dest_name(key: str) -> str:
    """Convert a kebab-case TOML key to its argparse destination name."""
    return key.replace("-", "_")


def _validate_limit(
    key: str, value: object, config_path: Path, parser: argparse.ArgumentParser
) -> int:
    """Validate and return a limit value, exiting on type or sign error."""
    if not isinstance(value, int) or isinstance(value, bool):
        _type_error(key, "an integer", config_path, parser)
    if value < 0:
        _type_error(key, "a non-negative integer", config_path, parser)
    return value


def _validate_table(
    table: dict[str, Any],
    config_path: Path,
    parser: argparse.ArgumentParser,
) -> dict[str, Any]:
    """Validate keys and types in the pymaxlines table, returning argparse-ready defaults."""
    for key in table:
        if key not in _ALLOWED_KEYS:
            parser.error(f"unknown key '{key}' in [tool.pymaxlines] of {config_path}")

    defaults: dict[str, Any] = {}

    for key, value in table.items():
        if key in _LIMIT_KEYS:
            defaults[dest_name(key)] = _validate_limit(key, value, config_path, parser)
        elif key in _BOOL_KEYS:
            if not isinstance(value, bool):
                _type_error(key, "a boolean", config_path, parser)
            defaults[dest_name(key)] = value
        elif key == "exclude":
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                _type_error("exclude", "a list of strings", config_path, parser)
            defaults["exclude"] = tuple(value)

    return defaults


def load_config(
    config_path: Path | None,
    parser: argparse.ArgumentParser,
) -> dict[str, Any]:
    """Read ``[tool.pymaxlines]`` from *config_path* (or ``pyproject.toml`` in CWD).

    Returns a dict of argparse destination names suitable for
    ``parser.set_defaults()``.  Calls ``parser.error()`` on validation failures,
    which exits with code 2.
    """
    explicit = config_path is not None
    if config_path is None:
        config_path = Path("pyproject.toml")

    try:
        text = config_path.read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError):
        if explicit:
            parser.error(f"config file not found: {config_path}")
        return {}
    except UnicodeDecodeError:
        parser.error(f"could not decode {config_path}: not valid UTF-8")
    except OSError as exc:
        parser.error(f"could not read {config_path}: {exc}")

    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        parser.error(f"invalid TOML in {config_path}: {exc}")

    tool = data.get("tool", {})
    if not isinstance(tool, dict):
        parser.error(f"[tool] in {config_path} must be a table")
    table = tool.get("pymaxlines")
    if table is None:
        return {}
    if not isinstance(table, dict):
        parser.error(f"[tool.pymaxlines] in {config_path} must be a table")

    return _validate_table(table, config_path, parser)
