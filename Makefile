.PHONY: ingest-nextseek-docs image-preflight image-stage bats-check shellcheck-check image-check-docker image-build image-e2e

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
	@src="$${NEXTSEEK_PLUGIN_SOURCE:-$${HOME}/.claude/plugins/local/nextseek-api}"; \
	tmp="$$(mktemp -d)"; \
	filtered="$$tmp/nextseek-api"; \
	mkdir -p "$$filtered"; \
	for entry in .claude-plugin bin commands skills docs pyproject.toml uv.lock README.md CHANGELOG.md; do \
	  test -e "$$src/$$entry" || { echo "image-stage: missing $$src/$$entry" >&2; rm -rf "$$tmp"; exit 1; }; \
	  cp -R "$$src/$$entry" "$$filtered/"; \
	done; \
	find "$$filtered" \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \) -exec rm -rf {} +; \
	find "$$filtered" \( -name '*.pyc' -o -name '*.pyo' \) -delete; \
	uv run python -m build_tools.stage_plugins --source "$$filtered" --dest ./build_context; \
	code="$$?"; \
	rm -rf "$$tmp"; \
	exit "$$code"

bats-check:
	@command -v bats >/dev/null 2>&1 || (echo 'Install bats: brew install bats-core' && exit 1)

shellcheck-check:
	@command -v shellcheck >/dev/null 2>&1 || (echo 'Install shellcheck: brew install shellcheck' && exit 1)

image-check-docker:
	@docker info >/dev/null 2>&1 || ( \
	    (uname | grep -q Darwin && open -a Docker 2>/dev/null && sleep 10 && docker info >/dev/null 2>&1) || \
	    (uname | grep -q Linux && echo "dockerd not running; or: add user to docker group: sudo usermod -aG docker $$USER" >&2 && exit 1) || \
	    (echo "Start Docker Desktop manually" >&2 && exit 1))

image-build: image-check-docker image-preflight image-stage
	@if docker image inspect dmac-assistant:poc >/dev/null 2>&1; then \
	  echo "Retagging prior dmac-assistant:poc -> dmac-assistant:poc-prev"; \
	  docker tag dmac-assistant:poc dmac-assistant:poc-prev; \
	fi
	@docker buildx build --platform=linux/amd64 --load -t dmac-assistant:poc .
	@echo ""
	@echo "Built dmac-assistant:poc. Size: $$(docker image inspect dmac-assistant:poc --format '{{.Size}}')"

image-e2e: image-build
	@uv run pytest tests/test_bedrock_e2e.py tests/test_plugin_e2e.py -v -p no:xdist
