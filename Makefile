.PHONY: ingest-nextseek-docs image-preflight image-stage bats-check shellcheck-check

ingest-nextseek-docs:
	@uv run python -m build_tools.ingest_nextseek_docs $(ARGS); \
	code=$$?; \
	if [ $$code -eq 2 ]; then \
	  echo ""; \
	  echo "NExtSEEK docs changed. Review the diff, commit, and rebuild the Docker image."; \
	fi; \
	exit $$code

image-preflight:
	@uv run python -m build_tools.ingest_nextseek_docs $(ARGS) >/dev/null; \
	code=$$?; \
	if [ $$code -eq 2 ]; then \
	  echo "" >&2; \
	  echo "=========================================================" >&2; \
	  echo "  DRIFT DETECTED in container/CLAUDE.md or docs/nextseek/" >&2; \
	  echo "=========================================================" >&2; \
	  uv run python -c 'from pathlib import Path; from build_tools.drift_report import format_drift_summary; import sys; sys.stderr.write(format_drift_summary(Path(".")))' >&2; \
	  echo "" >&2; \
	  echo "Review the diff, commit, and rebuild the image when ready." >&2; \
	elif [ $$code -ne 0 ]; then \
	  echo "image-preflight: ingestion returned unexpected code $$code (ignored; warn-only)" >&2; \
	fi; \
	exit 0

image-stage:
	@uv run python -m build_tools.stage_plugins \
	  --source $${HOME}/.claude/plugins/local/nextseek-api \
	  --dest ./build_context

bats-check:
	@command -v bats >/dev/null 2>&1 || (echo 'Install bats: brew install bats-core' && exit 1)

shellcheck-check:
	@command -v shellcheck >/dev/null 2>&1 || (echo 'Install shellcheck: brew install shellcheck' && exit 1)
