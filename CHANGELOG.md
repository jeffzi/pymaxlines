# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Inline `# pymaxlines: disable` comments that exempt a file or a function from the checks instead
  of raising the global limit.
- Near-miss detection for directive comments with wrong case (`PYMAXLINES:`) or a missing colon
  (`pymaxlines disable`), reported as malformed with the canonical form in the error message.
- `--report-unused-disable-directives` flag to detect directives that suppress no findings.

## [0.3.0] - 2026-09-03

### Added

- `check-max-lines` pre-commit hook and `pymaxlines` command that fail when a Python file or
  function exceeds a code-line limit, counting only code lines and applying separate limits to test
  files.

[Unreleased]: https://github.com/jeffzi/pymaxlines/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/jeffzi/pymaxlines/releases/tag/v0.3.0
