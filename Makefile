.PHONY: ingest-nextseek-docs image-preflight image-stage clean-plugin-artifacts bats-check shellcheck-check image-check-docker sync-vendor-deps image-build image-e2e capture-streamjson-fixture

# Plan A · Amendment 7 v2 (2026-04-30): doc ingestion runs against the
# sibling `build_tools/` uv project (its own venv with markitdown[all]).
# `uv run --project build_tools python -m build_tools.X` activates the
# build_tools venv while keeping cwd at the repo root, so `python -m`
# finds `./build_tools/__init__.py` on its default sys.path.
ingest-nextseek-docs:
	@uv run --project build_tools python -m build_tools.ingest_nextseek_docs $(ARGS); \
	code=$$?; \
	if [ $$code -eq 2 ]; then \
	  echo ""; \
	  echo "NExtSEEK docs changed. Review the diff, commit, and rebuild the Docker image."; \
	fi; \
	exit $$code

image-preflight:
	@uv run --project build_tools python -m build_tools.ingest_nextseek_docs $(ARGS) >/dev/null; \
	code=$$?; \
	if [ $$code -eq 2 ]; then \
	  echo "" >&2; \
	  echo "=========================================================" >&2; \
	  echo "  DRIFT DETECTED in container/CLAUDE.md or docs/nextseek/" >&2; \
	  echo "=========================================================" >&2; \
	  uv run --project build_tools python -c 'from pathlib import Path; from build_tools.drift_report import format_drift_summary; import sys; sys.stderr.write(format_drift_summary(Path(".")))' >&2; \
	  echo "" >&2; \
	  echo "Review the diff, commit, and rebuild the image when ready." >&2; \
	elif [ $$code -ne 0 ]; then \
	  echo "image-preflight: ingestion returned unexpected code $$code (ignored; warn-only)" >&2; \
	fi; \
	exit 0

image-stage:
	@src="$${NEXTSEEK_PLUGIN_SOURCE:-$${HOME}/.claude/plugins/local/nextseek-api}"; \
	tmp="$$(mktemp -d)"; \
	filtered="$$tmp/nextseek-api"; \
	mkdir -p "$$filtered"; \
	for entry in .claude-plugin bin commands skills docs pyproject.toml uv.lock README.md CHANGELOG.md; do \
	  test -e "$$src/$$entry" || { echo "image-stage: missing $$src/$$entry" >&2; rm -rf "$$tmp"; exit 1; }; \
	  cp -R "$$src/$$entry" "$$filtered/"; \
	done; \
	uv run --project build_tools python -m build_tools.stage_plugins --source "$$filtered" --dest ./build_context; \
	code="$$?"; \
	rm -rf "$$tmp"; \
	exit "$$code"

# R-01 note: the above cp-to-$filtered is kept so the stager scans only the
# allowlisted top-level entries — the plugin dev tree legitimately contains
# .venv/ and .git/ which the old Makefile effectively skipped by never
# copying them. The REMOVED behavior was the silent pre-strip of
# pyc/__pycache__/.pytest_cache/.ruff_cache inside $filtered; those now
# surface as DD-03 refusal via the stager (operator cleans via
# `make clean-plugin-artifacts`).

# Non-destructive helper: strips Python cache artifacts from the user's
# plugin source tree. Required before `make image-stage` if the tree has
# leftover .pyc/__pycache__/.pytest_cache/.ruff_cache entries from dev work.
# Per DD-03 the stager refuses such artifacts; this target makes the cleanup
# an explicit, operator-invoked action instead of a silent pre-strip.
clean-plugin-artifacts:
	@src="$${NEXTSEEK_PLUGIN_SOURCE:-$${HOME}/.claude/plugins/local/nextseek-api}"; \
	echo "Cleaning Python cache artifacts under $$src ..."; \
	find "$$src" \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \) -prune -exec rm -rf {} + 2>/dev/null || true; \
	find "$$src" \( -name '*.pyc' -o -name '*.pyo' \) -delete 2>/dev/null || true; \
	echo "Done."

bats-check:
	@command -v bats >/dev/null 2>&1 || (echo 'Install bats: brew install bats-core' && exit 1)

shellcheck-check:
	@command -v shellcheck >/dev/null 2>&1 || (echo 'Install shellcheck: brew install shellcheck' && exit 1)

image-check-docker:
	@docker info >/dev/null 2>&1 || ( \
	    (uname | grep -q Darwin && open -a Docker 2>/dev/null && sleep 10 && docker info >/dev/null 2>&1) || \
	    (uname | grep -q Linux && echo "dockerd not running; or: add user to docker group: sudo usermod -aG docker $$USER" >&2 && exit 1) || \
	    (echo "Start Docker Desktop manually" >&2 && exit 1))

sync-vendor-deps:
	@./scripts/sync-vendor-deps.sh

image-build: image-check-docker image-preflight sync-vendor-deps
	@if docker image inspect dmac-assistant:poc >/dev/null 2>&1; then \
	  echo "Retagging prior dmac-assistant:poc -> dmac-assistant:poc-prev"; \
	  docker tag dmac-assistant:poc dmac-assistant:poc-prev; \
	fi
	@set -o pipefail; \
	  docker buildx build --platform=linux/amd64 --load -t dmac-assistant:poc . \
	    | tee /tmp/dmac-image-build.log
	@echo ""
	@echo "Built dmac-assistant:poc. Size: $$(docker image inspect dmac-assistant:poc --format '{{.Size}}')"

image-e2e: image-build
	@uv run pytest tests/test_bedrock_e2e.py tests/test_plugin_e2e.py -v -p no:xdist

capture-streamjson-fixture: image-check-docker
	@uv run python scripts/capture_streamjson_init.py

# NEW-6: parameterize the source path so other developers / CI can override.
CHAT_NEXTSEEK_SRC ?= /Users/taishajoseph/Documents/Projects/work/chat_nextseek

.PHONY: snapshot-nextseek-catalogs
snapshot-nextseek-catalogs:
	@test -d "$(CHAT_NEXTSEEK_SRC)/src/chat_nextseek/context" || \
		(echo "ERROR: CHAT_NEXTSEEK_SRC not found at $(CHAT_NEXTSEEK_SRC)/src/chat_nextseek/context. Override via 'make snapshot-nextseek-catalogs CHAT_NEXTSEEK_SRC=/path/to/chat_nextseek'." && exit 1)
	@mkdir -p build_context/plugins/nextseek/context
	@cp "$(CHAT_NEXTSEEK_SRC)"/src/chat_nextseek/context/min_*.json \
	    build_context/plugins/nextseek/context/
	@cp "$(CHAT_NEXTSEEK_SRC)"/src/chat_nextseek/context/projects_db.json \
	    build_context/plugins/nextseek/context/
	@cp "$(CHAT_NEXTSEEK_SRC)"/src/chat_nextseek/context/neo4j_schema.json \
	    build_context/plugins/nextseek/context/
	@cp "$(CHAT_NEXTSEEK_SRC)"/src/chat_nextseek/context/capabilities.md \
	    build_context/plugins/nextseek/context/
	@echo "Snapshotted catalogs to build_context/plugins/nextseek/context/ (from $(CHAT_NEXTSEEK_SRC))"
