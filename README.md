# pymaxlines

[![PyPI version](https://img.shields.io/pypi/v/pymaxlines)](https://pypi.org/project/pymaxlines/)
[![Python: 3.12 | 3.13 | 3.14](https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14-blue.svg)](https://github.com/jeffzi/pymaxlines)
[![CI status](https://github.com/jeffzi/pymaxlines/actions/workflows/pytest.yml/badge.svg)](https://github.com/jeffzi/pymaxlines/actions/workflows/pytest.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/jeffzi/pymaxlines/blob/main/LICENSE)

A Python linter that fails when a file or function has too many code lines. Run it standalone or as
a pre-commit hook.

Requires Python 3.12+.

- [Why](#why)
- [Quick example](#quick-example)
- [Installation](#installation)
  - [Pre-commit hook](#pre-commit-hook)
- [Usage](#usage)
  - [Flags](#flags)
  - [Exit codes](#exit-codes)
  - [Size breakdown](#size-breakdown)
- [Configuration](#configuration)
- [Suppressing a finding](#suppressing-a-finding)
  - [File-level](#file-level)
  - [Function-level](#function-level)
  - [Directive syntax](#directive-syntax)
- [What counts as a code line](#what-counts-as-a-code-line)
- [Contributing](#contributing)
- [License](#license)

## Why

A file that runs into the thousands of lines is hard to navigate, test, and review, yet few Python
linters enforce a limit. Ruff has no `max-lines` rule and [does not plan to add one][ruff-c0302].
McCabe complexity catches convoluted control flow but ignores sheer size — a 600-line function with
simple branches passes just fine.

The problem compounds with LLM coding agents. Long files exhaust the context window and push agents
toward destructive rewrites — splitting a file on a token boundary instead of a logical one.
Enforcing a line budget keeps the codebase in a shape that both humans and agents can work with.

`pymaxlines` counts only code lines, the way oxlint's [`max-lines`][oxlint-max-lines] rule does
with `skipBlankLines` and `skipComments`, so docstrings, comments, and blank lines stay free. It
applies one limit per file and one per function, with separate thresholds for test files.

[ruff-c0302]: https://github.com/astral-sh/ruff/issues/25001
[oxlint-max-lines]: https://oxc.rs/docs/guide/usage/linter/rules/eslint/max-lines.html

## Quick example

```console
$ pymaxlines src/app/service.py
src/app/service.py:1: Too many lines in module (412 > 400) [max-lines]
src/app/service.py:52: Too many lines in function 'handle_request' (73 > 60, lines 52-161) [max-lines-per-function]
Found 2 errors.
```

Findings from the two size rules end with `[max-lines]` or `[max-lines-per-function]`, which are
the names you pass to `# pymaxlines: disable=<rule>`. The `[unused-disable-directive]` id appears
only with `--report-unused-disable-directives`; it counts as an error like any other finding and
cannot itself be suppressed.

## Installation

Run directly with `uvx` (no install needed):

```bash
uvx pymaxlines
```

Or install into a project:

```bash
uv add --dev pymaxlines
```

The package is a standard PyPI wheel with no dependencies — `pip install pymaxlines` and
`pipx run pymaxlines` work the same way. `python -m pymaxlines` is equivalent to the `pymaxlines`
command.

### Pre-commit hook

Add the hook to `.pre-commit-config.yaml` and run `pre-commit install` or
[`prek install`][prek]:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/jeffzi/pymaxlines
    rev: v0.6.0
    hooks:
      - id: check-max-lines
```

The shipped hook passes `--force-exclude`, so `exclude` patterns from `[tool.pymaxlines]` apply
automatically. Add `args: [--no-force-exclude]` to skip them.

[prek]: https://github.com/j178/prek

## Usage

With no arguments, `pymaxlines` checks every `*.py` file under the current directory recursively.
Pass directories or files to scope the check:

```bash
pymaxlines src/ tests/
```

Discovery skips `.git`, `.venv*`, `node_modules`, `__pycache__`, `.tox`, `.nox`, `.eggs`, and
symlinked directories. Files named explicitly on the command line are checked as given, even if they
match a skip directory or lack a `.py` suffix.

Use `--exclude` to skip files or directories by glob pattern (repeatable):

```bash
pymaxlines --exclude "migrations" --exclude "generated"
```

`pymaxlines` matches each pattern against the bare filename, the path relative to the directory
being walked, and that path prefixed with the walked directory. A bare name like `generated` matches
at any depth; running `pymaxlines src/` accepts either `generated/*.py` or `src/generated/*.py`.
`--exclude` on the command line replaces the `exclude` list from the config file.

A file is a **test file** when its path, relative to the working directory, contains a `tests`
component, or when its name starts with `test_` or ends with `_test.py`. A `tests` directory
above the working directory does not count; only the filename conventions apply there. Everything
else is a **source file**. Source and test files have separate limits.

### Flags

| Flag                                 | Scope        | Default | Meaning                                                |
| ------------------------------------ | ------------ | ------- | ------------------------------------------------------ |
| `--max-lines`                        | source files | 400     | code lines per file                                    |
| `--max-lines-test`                   | test files   | 800     | code lines per file                                    |
| `--max-lines-per-function`           | source files | 60      | code lines per function; `0` disables                  |
| `--max-lines-per-function-test`      | test files   | 0       | code lines per function; `0` disables                  |
| `--skip-blank-lines`                 | all files    | True    | exclude blank lines from counts                        |
| `--skip-comments`                    | all files    | True    | exclude comment-only lines                             |
| `--skip-docstrings`                  | all files    | True    | exclude standalone docstrings                          |
| `--report-unused-disable-directives` | all files    | False   | fail on directives that suppress nothing               |
| `--force-exclude`                    | —            | False   | apply exclude globs to explicit paths too              |
| `--exclude GLOB`                     | —            | —       | skip matching files/directories (repeatable)           |
| `--show-sizes`                       | all files    | False   | print a code-line breakdown instead of checking limits |
| `--config PATH`                      | —            | —       | read config from PATH instead of pyproject             |
| `-v`, `--version`                    | —            | —       | print version and exit                                 |

The `--skip-*`, `--report-unused-disable-directives`, and `--force-exclude` flags each have a
`--no-` counterpart. All four limit flags reject negative values.

### Exit codes

| Code | Meaning                                                                                                                                  |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| 0    | No findings (empty discovery prints a warning and still exits 0)                                                                         |
| 1    | One or more findings, an invalid `# pymaxlines:` directive, or a file that could not be read or parsed                                   |
| 2    | Invalid usage, negative limit, or config-file error (unknown key, wrong type, unparsable file, or a `--config` path that does not exist) |

### Size breakdown

`--show-sizes` prints a code-line breakdown of every file instead of checking limits, largest first.
Counts respect `--skip-*` settings, so they match what the check enforces. The run exits 0 even when
files exceed their limits; only unreadable files, parse failures, and directive errors produce
exit 1.

Function rows show `count/limit`; other rows show a plain count.

```console
$ pymaxlines --show-sizes src/app/service.py
src/app/service.py: 412 code lines (limit 400, over by 12)
  1-3  imports                       3
  12-180  class RequestHandler     142
    52-161  def handle_request   73/60
  182-220  def validate          38/60
```

## Configuration

`pymaxlines` reads defaults from `[tool.pymaxlines]` in the working directory's `pyproject.toml`:

```toml
[tool.pymaxlines]
max-lines = 300
max-lines-per-function = 40
exclude = ["migrations", "generated"]
```

Supported keys: `max-lines`, `max-lines-test`, `max-lines-per-function`,
`max-lines-per-function-test`, `skip-blank-lines`, `skip-comments`, `skip-docstrings`,
`report-unused-disable-directives`, `force-exclude`, and `exclude` (list of strings). `--config`,
`--version`, and `--show-sizes` are command-line only. CLI flags override the
config file; absent keys keep their built-in defaults.

## Suppressing a finding

Add a `# pymaxlines: disable` comment to exempt a file or function instead of raising the global
limit.

### File-level

Place the directive on a comment-only line before the first statement (after the module docstring is
fine):

```python
"""This generated module is intentionally large."""
# pymaxlines: disable=max-lines

import re
# ...
```

### Function-level

Trail the directive on any line of the `def` header, from `def` through the colon. A decorator line
sits above the header and does not count — a directive there is reported as misplaced:

```python
def big_handler(
    request: Request,
    db: Session,
):  # pymaxlines: disable=max-lines-per-function
    ...
```

### Directive syntax

`# pymaxlines: disable` without `=rule` disables every rule at its scope. Separate multiple rules
with commas: `# pymaxlines: disable=max-lines,max-lines-per-function`.

A directive can share its `#` line with other comments:
`def big_handler(...):  # noqa: C901  # pymaxlines: disable`.

`max-lines` is valid only at file scope. `max-lines-per-function` is valid at file scope and on
`def` lines. The directive is case-sensitive and the colon is required; `# PyMaxLines: disable` or
`# pymaxlines disable` exits 1. Use at most one `pymaxlines:` directive per line — combine rules
with commas instead. An unknown rule, a malformed directive, or a misplaced directive exits 1.

## What counts as a code line

By default (all `--skip-*` flags on):

- Blank lines, comment-only lines, and standalone docstrings are free.
- Every other line counts, including non-blank lines inside multi-line strings.
- A `def` header counts toward the file total but not toward that function's own count.
- Nested functions count toward the enclosing function.
- Decorator lines count toward the file total but not toward the decorated function.
- `pymaxlines` checks methods, async functions, and nested functions. It does not check lambdas.
- A function-level directive exempts only its own `def` — nested functions still need their own.

Turning a `--skip-*` flag off makes that category count toward both file and function totals.

## Contributing

Install [Task](https://taskfile.dev), [uv](https://docs.astral.sh/uv/), and
[dprint](https://dprint.dev/install/), then run `task install` to sync dependencies and install
the git hooks. `task --list` shows the full development workflow. `task check` runs every hook;
`task test:matrix` runs the suite on each supported Python version.

## License

MIT. See [LICENSE](https://github.com/jeffzi/pymaxlines/blob/main/LICENSE).
