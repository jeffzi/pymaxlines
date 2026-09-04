# pymaxlines

[![PyPI](https://img.shields.io/pypi/v/pymaxlines)](https://pypi.org/project/pymaxlines/)
[![Python: 3.12 | 3.13 | 3.14](https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14-blue.svg)](https://github.com/jeffzi/pymaxlines)
[![CI](https://github.com/jeffzi/pymaxlines/actions/workflows/pytest.yml/badge.svg)](https://github.com/jeffzi/pymaxlines/actions/workflows/pytest.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/jeffzi/pymaxlines/blob/main/LICENSE)

A pre-commit hook that fails when a Python file or function has too many lines of code.

Requires Python 3.12+.

- [Why](#why)
- [Quick example](#quick-example)
- [Installation](#installation)
- [Usage](#usage)
- [Suppressing a finding](#suppressing-a-finding)
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

A failing run prints one line per finding and exits 1:

```console
$ pymaxlines src/app/service.py
src/app/service.py: 412 code lines (max 400)
src/app/service.py:88: function 'handle_request' has 73 code lines (max 60)
```

## Installation

Add the hook to `.pre-commit-config.yaml` and run `pre-commit install` or
[`prek install`][prek]:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/jeffzi/pymaxlines
    rev: v0.3.0
    hooks:
      - id: check-max-lines
```

[pre-commit]: https://pre-commit.com
[prek]: https://github.com/j178/prek

To run it outside [pre-commit][pre-commit]:

```bash
uvx pymaxlines file1.py file2.py
```

When the package is installed in an environment, `python -m pymaxlines` is equivalent to the
`pymaxlines` command and lets you pick the interpreter explicitly.

## Usage

The hook runs on `.py` and `.pyi` files. A file is a **test file** when the path passed on the
command line contains a `tests/` component, or the filename matches `test_*.py`, `test_*.pyi`, or
`*_test.py`. Everything else is a **source file**. The flag table below uses these terms in its
"Applies to" column.

Defaults, all overridable with flags:

| Flag                                 | Applies to | Default | Meaning                                                                      |
| ------------------------------------ | ---------- | ------- | ---------------------------------------------------------------------------- |
| `--max-lines`                        | source     | 400     | code lines per file                                                          |
| `--max-lines-test`                   | test       | 800     | code lines per file                                                          |
| `--max-lines-per-function`           | source     | 60      | code lines per function, `0` disables                                        |
| `--max-lines-per-function-test`      | test       | 0       | code lines per function, `0` disables                                        |
| `--skip-blank-lines`                 | all        | True    | exclude blank lines from counts                                              |
| `--skip-comments`                    | all        | True    | exclude comment-only lines                                                   |
| `--skip-docstrings`                  | all        | True    | exclude standalone docstrings                                                |
| `--report-unused-disable-directives` | all        | False   | fail on directives that suppress nothing _(unreleased — ships after v0.3.0)_ |

`--max-lines` and `--max-lines-test` have no disable value — `0` fails any file containing code.
All four limit flags reject negative values.

Pass flags through the hook's `args`:

```yaml
- id: check-max-lines
  args: [--max-lines, "300", --max-lines-per-function, "40"]
```

Each `--skip-*` flag has a `--no-skip-*` counterpart. To count comment-only and blank lines:

```yaml
- id: check-max-lines
  args: [--no-skip-comments, --no-skip-blank-lines]
```

### Suppressing a finding

Add a `# pymaxlines: disable` comment to exempt a file or function from the checks instead of
raising the global limit.

**File-level** — place the directive on a comment-only line before the first statement (after the
module docstring is fine):

```python
"""This generated module is intentionally large."""
# pymaxlines: disable=max-lines

import re
# ...
```

**Function-level** — trail the directive on any line of the `def` header, from `def` through the
colon. On a decorated function, place it on the `def` line, not a decorator line:

```python
def big_handler(
    request: Request,
    db: Session,
):  # pymaxlines: disable=max-lines-per-function
    ...
```

**Bare disable** — `# pymaxlines: disable` without `=rule` disables every rule at its scope.
At file scope it suppresses both the file check and every function check; on a `def` line it exempts
that function.

Separate several rules with commas: `# pymaxlines: disable=max-lines,max-lines-per-function`.

A directive can share its `#` line with other comments:
`def big_handler(...):  # noqa: C901  # pymaxlines: disable`.

Any `#` segment whose first word is `pymaxlines` (any case) is a directive attempt and must use the
canonical `pymaxlines: <action>` form. `pymaxlines` rejects three near-misses and fails the run: a
wrong-case prefix (`PYMAXLINES:`), a missing colon (`pymaxlines disable`), and a non-colon separator
(`pymaxlines-disable`).

Each rule is only valid at certain scopes:

| Rule                     | Valid scopes |
| ------------------------ | ------------ |
| `max-lines`              | file         |
| `max-lines-per-function` | file, `def`  |

An unknown rule name, a malformed directive, or a misplaced directive fails the run with a
diagnostic message, even when the file is within its limits. A directive is misplaced when it
appears on a comment-only line after the module's first statement, inside a function body, or
trailing a non-`def` statement (including decorator lines). Naming a file-scope-only rule on a `def`
line is a separate error —
`# pymaxlines: disable=max-lines` on a `def` line fails with
`rule 'max-lines' does not apply to a function; use max-lines-per-function`.

Pass `--report-unused-disable-directives` to fail the run on directives that suppress no findings.
`pymaxlines` reports a directive for a disabled check (limit 0) as unused. It reports a bare
`disable` as unused only when neither check would have fired, and never reports a directive that
already failed validation.

### What counts as a code line

By default (all `--skip-*` flags on):

- Blank lines, comment-only lines, and standalone docstrings (module, class, or function) are free.
- Whitespace-only lines inside a multi-line string are free.
- Every other line counts once, including non-blank lines inside multi-line strings.
- A function's count includes its `def` line and every code line up to the end of its body, nested
  functions included.
- Methods, async functions, and nested functions are each checked against the per-function limit;
  lambdas are not.
- A function-level directive exempts only the function whose `def` line it sits on — a nested
  function still needs its own directive.
- Decorator lines count toward the file total but not toward the decorated function's count.

Turning a `--skip-*` flag off (e.g. `--no-skip-blank-lines`) makes that category count toward both
file and function totals.

`pymaxlines` reports unreadable files (missing, undecodable, or syntax errors) and fails the run.

## Contributing

Install [Task](https://taskfile.dev), [uv](https://docs.astral.sh/uv/), and
[dprint](https://dprint.dev/install/), then run `task install` to sync dependencies and install
the git hooks. `task --list` shows the full development workflow. `task check` runs every hook;
`task test:matrix` runs the suite on each supported Python version.

## License

MIT. See [LICENSE](https://github.com/jeffzi/pymaxlines/blob/main/LICENSE).
