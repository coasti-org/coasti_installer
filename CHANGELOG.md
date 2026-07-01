# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

TLDR:
- Bugfixes 0.0.1 (Revision)
- Features 0.1.0 (Minor Version)
- Breaking Changes 1.0.0 (Major Version)


## 0.2.2 - 2026-07-01

### Added

- MIT License
- Now shipping superset-io as a dependency and sub-command

## 0.2.1 - 2026-03-30

### Added

- Getting-Started on readthedocs

## 0.2.0 - 2026-03-09

### Added

- We now check for coasti base dir before running product commands
- We now check git is reachable and auth flow works before adding products
- Product install questions no longer need to create a fake template folder
- Better abstraction for products and their yaml writing
- Tests for product installs with mock repo template (this can be aligned with proper demo content packages)
- Pre-commit hook
- `coasti product update` now takes a `--vcs-ref` (overrules and overwrites the value in products.yml)

### Fixed

- No longer installs on py 3.10 (which should not have been allowed) #4

### Dependencies

- copier 9.12.0

## 0.1.5 - 2026-02-19

### Fixed

- Product install would crash on windows when using git auth token

## 0.1.4 - 2026-02-17

### Fixed

- Fixed tests when running from main branch.
- Now using platformdirs to determine template cache dir.

## 0.1.3

### Added
- Now wrapping [copier](https://copier.readthedocs.io/en/stable/) for all template
  and content-installation logic
- Can now manage git authentication flows via auth token or ssh keypair
- Docker Dev container
- UV project for dependency management
- Github action for automatic testing

