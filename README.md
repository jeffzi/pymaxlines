# pymaxlines

[![CI](https://github.com/jeffzi/pymaxlines/actions/workflows/pytest.yml/badge.svg)](https://github.com/jeffzi/pymaxlines/actions/workflows/pytest.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A pre-commit hook that fails when a Python file or function has too many lines of code.

Requires Python 3.12+.

- [Why](#why)
- [Quick example](#quick-example)
- [Installation](#installation)
- [Usage](#usage)
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

A failing run prints one line per offender and exits 1:

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
    rev: main # pin to a release tag once one is published
    hooks:
      - id: check-max-lines
```

[pre-commit]: https://pre-commit.com
[prek]: https://github.com/jdx/prek

To run it outside [pre-commit][pre-commit]:

```bash
uvx pymaxlines file1.py file2.py
```

## Usage

The hook runs on `.py` and `.pyi` files. A file is a **test file** when it sits under a `tests/`
directory or is named `test_*.py` or `*_test.py`. Everything else is a **source file**. The flag
table below uses these terms in its "Applies to" column.

Defaults, all overridable with flags:

| Flag                            | Applies to | Default | Meaning                               |
| ------------------------------- | ---------- | ------- | ------------------------------------- |
| `--max-lines`                   | source     | 400     | code lines per file                   |
| `--max-lines-test`              | test       | 800     | code lines per file                   |
| `--max-lines-per-function`      | source     | 60      | code lines per function, `0` disables |
| `--max-lines-per-function-test` | test       | 0       | code lines per function, `0` disables |
| `--skip-blank-lines`            | all        | True    | exclude blank lines from counts       |
| `--skip-comments`               | all        | True    | exclude comment-only lines            |
| `--skip-docstrings`             | all        | True    | exclude standalone docstrings         |

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

### What counts as a code line

By default (all `--skip-*` flags on):

- Blank lines, comment-only lines, and standalone docstrings (module, class, or function) are free.
- Whitespace-only lines inside a multi-line string are free.
- Every other line counts once, including non-blank lines inside multi-line strings.
- A function's count includes its `def` line and every code line up to the end of its body, nested
  functions included.
- Decorator lines count toward the file total but not toward the decorated function's count.

Turning a `--skip-*` flag off (e.g. `--no-skip-blank-lines`) makes that category count toward both
file and function totals.

`pymaxlines` reports unreadable files (missing, undecodable, or syntax errors) and fails the run.

## Contributing

Run `task --list` for the development workflow. `task check` runs every hook; `task test:matrix`
runs the suite on each supported Python version.

## License

MIT. See [LICENSE](LICENSE).
