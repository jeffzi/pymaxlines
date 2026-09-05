# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.0] - 2026-09-05

### Added

- `--version` / `-v` flag to print the installed version and exit.
- `[tool.pymaxlines]` table in `pyproject.toml` for persistent configuration, with `--config PATH`
  to read from a specific file.
- File discovery: a no-argument run checks every `*.py` file under the current directory
  recursively, and directory arguments are walked the same way.
- `exclude` config key and `--exclude GLOB` flag to skip files or directories by glob pattern.
- `--force-exclude` flag and `force-exclude` config key to apply exclude globs to files passed
  explicitly on the command line.

### Changed

- **Breaking:** The shipped pre-commit hook now passes `--force-exclude`, so `exclude` patterns in
  `[tool.pymaxlines]` are honored when the framework passes explicit file paths. Add
  `args: [--no-force-exclude]` to restore the previous behavior.
- **Breaking:** A second `pymaxlines:` directive segment on the same comment line is now an error —
  combine rules with commas instead.

### Fixed

- Unreadable files are now reported as "could not read" and files that fail to parse as "could not
  parse".
- A malformed directive segment following a valid one on the same comment line is now reported
  instead of ignored.
- A directive comment inside a parenthesized decorator whose `@` sits alone on its line is now
  correctly classified as misplaced instead of being treated as file-scope.
- Test-file classification no longer depends on the invocation directory — a file outside the current
  directory is classified by its filename only, not by ancestor directory names.

## [0.4.0] - 2026-09-04

### Added

- Inline `# pymaxlines: disable` comments that exempt a file or a function from the checks, with
  malformed or misplaced directives reported as errors.
- `--report-unused-disable-directives` flag to detect directives that suppress no findings.

### Removed

- The `check-max-lines` hook no longer runs on `.pyi` stub files.

### Fixed

- Oversized-function diagnostics now print in source order.
- A broken stdout pipe (e.g. `pymaxlines files… | head -1`) now exits 1 cleanly instead of printing
  a traceback.
- A `def` or `class` header line that also carries an inline docstring (`def f(): "doc"`) is now
  counted as a code line instead of being skipped as a docstring.

## [0.3.0] - 2026-09-03

### Added

- `check-max-lines` pre-commit hook and `pymaxlines` command that fail when a Python file or
  function exceeds a code-line limit, counting only code lines and applying separate limits to test
  files.

[Unreleased]: https://github.com/jeffzi/pymaxlines/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/jeffzi/pymaxlines/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/jeffzi/pymaxlines/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/jeffzi/pymaxlines/releases/tag/v0.3.0
