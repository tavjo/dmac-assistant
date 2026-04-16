.PHONY: ingest-nextseek-docs bats-check shellcheck-check

ingest-nextseek-docs:
	@uv run python -m build_tools.ingest_nextseek_docs $(ARGS); \
	code=$$?; \
	if [ $$code -eq 2 ]; then \
	  echo ""; \
	  echo "NExtSEEK docs changed. Review the diff, commit, and rebuild the Docker image."; \
	fi; \
	exit $$code

bats-check:
	@command -v bats >/dev/null 2>&1 || (echo 'Install bats: brew install bats-core' && exit 1)

shellcheck-check:
	@command -v shellcheck >/dev/null 2>&1 || (echo 'Install shellcheck: brew install shellcheck' && exit 1)
