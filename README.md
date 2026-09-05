# pymaxlines

[![PyPI](https://img.shields.io/pypi/v/pymaxlines)](https://pypi.org/project/pymaxlines/)
[![Python: 3.12 | 3.13 | 3.14](https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14-blue.svg)](https://github.com/jeffzi/pymaxlines)
[![CI](https://github.com/jeffzi/pymaxlines/actions/workflows/pytest.yml/badge.svg)](https://github.com/jeffzi/pymaxlines/actions/workflows/pytest.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/jeffzi/pymaxlines/blob/main/LICENSE)

A Python linter that fails when a file or function has too many code lines. Run it standalone or as
a pre-commit hook.

Requires Python 3.12+.

- [Why](#why)
- [Quick example](#quick-example)
- [Installation](#installation)
  - [Pre-commit hook](#pre-commit-hook)
- [Usage](#usage)
  - [File discovery](#file-discovery)
  - [Exclude globs](#exclude-globs)
  - [Source and test files](#source-and-test-files)
  - [Flags](#flags)
  - [Exit codes](#exit-codes)
- [Configuration](#configuration)
  - [Supported keys](#supported-keys)
  - [Precedence](#precedence)
  - [Error handling](#error-handling)
- [Suppressing a finding](#suppressing-a-finding)
  - [File-level](#file-level)
  - [Function-level](#function-level)
  - [Bare disable](#bare-disable)
- [What counts as a code line](#what-counts-as-a-code-line)
- [Contributing](#contributing)
- [License](#license)

## Why

A file that runs into the thousands of lines is hard to navigate, test, and review, yet few Python
linters enforce a limit. Ruff has no `max-lines` rule and [does not plan to add one][ruff-c0302].
McCabe complexity catches convoluted control flow but ignores sheer size — a 600-line function with
simple branches passes just fine.

The problem compounds with large language model (LLM) coding agents. Long files exhaust the context
window and push agents toward destructive rewrites — splitting a file on a token boundary instead of
a logical one. Enforcing a line budget per file and per function keeps the codebase in a shape that
both humans and agents can work with.

`pymaxlines` counts only code lines, the way oxlint's [`max-lines`][oxlint-max-lines] rule does
with `skipBlankLines` and `skipComments`, so docstrings, comments, and blank lines stay free. It
applies one limit per file and one per function, with separate thresholds for test files.

[ruff-c0302]: https://github.com/astral-sh/ruff/issues/25001
[oxlint-max-lines]: https://oxc.rs/docs/guide/usage/linter/rules/eslint/max-lines.html

## Quick example

A failing run prints one line per finding, a summary, and exits 1:

```console
$ pymaxlines src/app/service.py
src/app/service.py:1: Too many lines in module (412 > 400) [max-lines]
src/app/service.py:88: Too many lines in function 'handle_request' (73 > 60) [max-lines-per-function]
Found 2 errors.
```

Each limit finding ends with its rule id — `[max-lines]` or `[max-lines-per-function]` — which is the
name you pass to `# pymaxlines: disable=<rule>`. The `[unused-disable-directive]` id identifies a
finding only; it is not a rule you can disable.

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
`pipx run pymaxlines` work the same way.

When installed, `python -m pymaxlines` is equivalent to the `pymaxlines` command.

### Pre-commit hook

Add the hook to `.pre-commit-config.yaml` and run `pre-commit install` or
[`prek install`][prek]:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/jeffzi/pymaxlines
    rev: v0.5.0
    hooks:
      - id: check-max-lines
```

The hook receives explicit file paths from the pre-commit framework and checks only those files. The
shipped hook passes `--force-exclude`, so `pymaxlines` honors `exclude` patterns from
`[tool.pymaxlines]` automatically. To check every file pre-commit passes and ignore `exclude`
patterns, add `args: [--no-force-exclude]`. Pre-commit's own `exclude:` key remains available for
coarser filtering. Limits and `skip-*` settings from `[tool.pymaxlines]` in the repo root still
apply.

[prek]: https://github.com/j178/prek

## Usage

### File discovery

With no arguments, `pymaxlines` checks every `*.py` file under the current directory recursively:

```console
$ pymaxlines
pkg/big.py:1: Too many lines in module (412 > 400) [max-lines]
Found 1 error.
```

Pass one or more directories to scope the check:

```bash
pymaxlines src/ tests/
```

Discovery skips these directories at any depth: `.git`, `.venv*`, `node_modules`, `__pycache__`,
`.tox`, `.nox`, `.eggs`. The `.venv*` entry is a glob, so `.venv`, `.venv-3.12`, and `.venv312` are
all pruned. `pymaxlines` also skips symlinked directories. When a path appears more than once (for
example a file also covered by a directory argument), `pymaxlines` reports it once, in first-seen
order. Within each directory, `pymaxlines` visits files in sorted order for deterministic output.

`pymaxlines` checks files named explicitly on the command line as given, even if they match a skip
directory, an `exclude` glob, or lack a `.py` suffix. Pass `--force-exclude` to apply `exclude`
globs to explicit paths too. Files and directories can be mixed in one invocation.

### Exclude globs

Use `--exclude` to skip files or directories by glob pattern:

```bash
pymaxlines --exclude "migrations" --exclude "generated"
```

Each exclude glob is tested against three candidates: the filename alone (`parser.py`), the path
relative to the walked directory (`generated/parser.py`), and that relative path re-joined to the
walked directory (`src/generated/parser.py` when walking `src/`). A pattern must match the entire
candidate string, so `generated/*.py` works only when `generated/` sits directly under the walked
root — use `generated` to match the directory component at any depth. `pymaxlines` skips a matched
directory and everything beneath it. `--exclude` on the command line replaces the `exclude` list
from the config file.

### Source and test files

A file is a **test file** when, relative to the current directory, the path has a `tests` component,
or the filename starts with `test_` or ends with `_test.py`. `pymaxlines` classifies a file outside
the current directory by its filename only. Everything else is a **source file**.

### Flags

| Flag                                 | Applies to | Default | Meaning                                           |
| ------------------------------------ | ---------- | ------- | ------------------------------------------------- |
| `--max-lines`                        | source     | 400     | code lines per file                               |
| `--max-lines-test`                   | test       | 800     | code lines per file                               |
| `--max-lines-per-function`           | source     | 60      | code lines per function; `0` disables             |
| `--max-lines-per-function-test`      | test       | 0       | code lines per function; `0` disables             |
| `--skip-blank-lines`                 | all        | True    | exclude blank lines from counts                   |
| `--skip-comments`                    | all        | True    | exclude comment-only lines                        |
| `--skip-docstrings`                  | all        | True    | exclude standalone docstrings                     |
| `--report-unused-disable-directives` | all        | False   | fail on directives that suppress nothing          |
| `--force-exclude`                    | explicit   | False   | apply exclude globs to explicitly passed paths    |
| `--exclude GLOB`                     | discovery  | —       | skip matching files/directories (repeatable)      |
| `--config PATH`                      | —          | —       | read config from PATH instead of `pyproject.toml` |
| `-v`, `--version`                    | —          | —       | print version and exit                            |

Each `--skip-*` flag has a `--no-skip-*` counterpart, and `--report-unused-disable-directives` has
`--no-report-unused-disable-directives`. `--max-lines` and `--max-lines-test` have no disable
value — `0` fails any file containing code. All four limit flags reject negative values.

### Exit codes

| Code | Meaning                                                                                                        |
| ---- | -------------------------------------------------------------------------------------------------------------- |
| 0    | No findings. When discovery matches no `.py` files, `pymaxlines` prints a warning to stderr and still exits 0. |
| 1    | One or more findings, or a file that could not be read or parsed.                                              |
| 2    | Invalid command-line usage, a negative limit, or an invalid/unknown config key.                                |

## Configuration

`pymaxlines` reads defaults from `[tool.pymaxlines]` in the working directory's `pyproject.toml`:

```toml
[tool.pymaxlines]
max-lines = 300
max-lines-per-function = 40
exclude = ["migrations", "generated"]
```

### Supported keys

| Key                                | Type            | Default |
| ---------------------------------- | --------------- | ------- |
| `max-lines`                        | integer         | 400     |
| `max-lines-test`                   | integer         | 800     |
| `max-lines-per-function`           | integer         | 60      |
| `max-lines-per-function-test`      | integer         | 0       |
| `skip-blank-lines`                 | boolean         | true    |
| `skip-comments`                    | boolean         | true    |
| `skip-docstrings`                  | boolean         | true    |
| `report-unused-disable-directives` | boolean         | false   |
| `force-exclude`                    | boolean         | false   |
| `exclude`                          | list of strings | `[]`    |

### Precedence

A flag on the command line overrides the config file. A key absent from the config file keeps its
built-in default. Order: built-in default < config file < CLI flag.

### Error handling

An unknown key, a wrong-typed value, or a negative limit in the config file exits 2 with an error
naming the key and the file. `--config PATH` reads from a specific file; a missing or malformed
configuration file exits 2 with an error naming the path.

## Suppressing a finding

Add a `# pymaxlines: disable` comment to exempt a file or function from the checks instead of
raising the global limit.

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

Trail the directive on any line of the `def` header, from `def` through the colon. On a decorated
function, place it on the `def` line, not a decorator line:

```python
def big_handler(
    request: Request,
    db: Session,
):  # pymaxlines: disable=max-lines-per-function
    ...
```

### Bare disable

`# pymaxlines: disable` without `=rule` disables every rule at its scope.
At file scope it suppresses both the file check and every function check; on a `def` line it exempts
that function.

Separate several rules with commas: `# pymaxlines: disable=max-lines,max-lines-per-function`.
Only one directive is allowed per line — a second `pymaxlines:` segment is an error.

A directive can share its `#` line with other comments:
`def big_handler(...):  # noqa: C901  # pymaxlines: disable`.

Any `#` segment whose first word is `pymaxlines` (any case, not followed by a word character) is a
directive attempt and must use the canonical `pymaxlines: <action>` form. A segment that matches but
does not parse fails the run. Common causes: a wrong-case prefix (`PYMAXLINES:`), a missing colon
(`pymaxlines disable`), and a non-colon separator (`pymaxlines-disable`). Any other non-canonical
form triggers the same error. A word character immediately after `pymaxlines` suppresses the check,
so `pymaxlines` does not treat `pymaxlines_disable` as an attempt.

Each rule is only valid at certain scopes:

| Rule                     | Valid scopes |
| ------------------------ | ------------ |
| `max-lines`              | file         |
| `max-lines-per-function` | file, `def`  |

An unknown rule name, a malformed directive, or a misplaced directive fails the run with a finding,
even when the file is within its limits. A directive is misplaced when it
appears on a comment-only line after the module's first statement, inside a function body, or
trailing a non-`def` statement (including decorator lines). Naming a file-scope-only rule on a `def`
line is a separate error —
`# pymaxlines: disable=max-lines` on a `def` line fails with
`rule 'max-lines' does not apply to a function; use max-lines-per-function`.

Pass `--report-unused-disable-directives` to fail the run on directives that suppress no findings.
`pymaxlines` reports a directive for a disabled check (limit 0) as unused. It reports a bare
`disable` as unused only when neither check would have fired, and never reports a directive that
already failed validation.

## What counts as a code line

By default (all `--skip-*` flags on):

- Blank lines, comment-only lines, and standalone docstrings (module, class, or function) are free.
- Whitespace-only lines inside a multi-line string are free.
- Every other line counts once, including non-blank lines inside multi-line strings.
- A `def` header (the `def` keyword through the closing `:`) counts toward the file total but not
  toward that function's own count; a nested function's header counts toward the enclosing function.
- A one-liner's body line (`def f(): return 1`) still counts because it carries body code.
- `pymaxlines` includes nested functions in the enclosing function's count.
- `pymaxlines` checks methods, async functions, and nested functions against the per-function limit;
  it does not check lambdas.
- A function-level directive exempts only the function whose `def` line it sits on — a nested
  function still needs its own directive.
- Decorator lines count toward the file total but not toward the decorated function's count.

Turning a `--skip-*` flag off (e.g. `--no-skip-blank-lines`) makes that category count toward both
file and function totals.

`pymaxlines` reports unreadable files and directories it cannot list (missing, permission denied,
undecodable, or syntax errors) and fails the run.

## Contributing

Install [Task](https://taskfile.dev), [uv](https://docs.astral.sh/uv/), and
[dprint](https://dprint.dev/install/), then run `task install` to sync dependencies and install
the git hooks. `task --list` shows the full development workflow. `task check` runs every hook;
`task test:matrix` runs the suite on each supported Python version.

## License

MIT. See [LICENSE](https://github.com/jeffzi/pymaxlines/blob/main/LICENSE).
