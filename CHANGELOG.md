# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/jeffzi/pymaxlines/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/jeffzi/pymaxlines/releases/tag/v0.3.0
