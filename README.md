# DMAC Assistant

Design-phase repository for the DMAC Assistant POC. See `dmac-assistant-sds.md` and `dmac-assistant-adrs.md` for the authoritative spec.

## Dev setup (macOS)

```sh
# Python toolchain
brew install uv
uv sync

# Shell-test runner for tests/entrypoint.bats
brew install bats-core

# POSIX compliance linter for container/entrypoint.sh
brew install shellcheck

# Sanity checks
make bats-check
make shellcheck-check
uv run pytest
```
