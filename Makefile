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

.PHONY: hibayes-eval hibayes-eval-build

# Build the eval image (idempotent; uses docker's layer cache after first build).
hibayes-eval-build:
	@HIBAYES_SHA=$$(git ls-remote https://github.com/UKGovernmentBEIS/hibayes.git HEAD | awk '{print $$1}'); \
	docker build \
		--platform linux/amd64 \
		--build-arg HIBAYES_SHA=$${HIBAYES_SHA} \
		-f Dockerfile.hibayes-eval \
		-t hibayes-runtime-reliability:dev \
		.

# Run the analysis end-to-end. Caller may override INPUT / OUT.
INPUT ?= data/hibayes_eval_rows.csv
OUT   ?= out/hibayes_runtime_reliability

hibayes-eval:
	@scripts/run_hibayes_eval.sh python -m dmac_assistant.eval.hibayes_runtime_reliability.run_hibayes \
		--input $(INPUT) \
		--out $(OUT)

# -----------------------------------------------------------------------------
# T4.2 — HiBayes evaluator expansion: Stage A/B/C + in-image Stage D axes + combined report
# -----------------------------------------------------------------------------
# Hardener Pass 2 restructure (2026-05-18): each produced artifact is declared
# as a FILE TARGET rule with concrete file prereqs and a recipe that produces
# the file. User-facing PHONY names (`hibayes-stage-a`, `hibayes-eval-artifact`,
# …) are declared as ALIAS targets that depend on their file output. This
# pattern gives GNU Make's mtime check the inputs it needs to deliver DL-026's
# skip-up-to-date semantics, and makes `hibayes-eval-build` correctly avoid
# rebuild-on-every-invocation when declared as an order-only prereq (per the
# GNU Make manual: "even order-only prerequisites marked as phony will not
# cause the target to be rebuilt"). Note the order-only guarantee applies
# only because the dependent is a file target; a PHONY target's recipe runs
# unconditionally regardless of order-only state.
# -----------------------------------------------------------------------------

# Variables (overridable via `make TARGET MANIFEST_PATH=...`).
#
# OPERATOR-SUPPLIED PREREQS (Pass 3 D3 resolution). The following inputs are
# expected to EXIST on disk before invoking `make hibayes-axes`; no Make rule
# produces them, and they are declared as file-existence prerequisites of the
# downstream file-target rules. If an operator overrides `MANIFEST_PATH` /
# `ARTIFACT_ROOT` / `RUNTIME_CSV` to a path that does not exist, GNU Make will
# refuse with `*** No rule to make target …` — this is intentional: each input
# must be produced by an upstream pipeline (the e2e headless runner for the
# manifest + artifact root; the bridge runtime emitter for the runtime CSV).
#   * MANIFEST_PATH — path to the run's `manifest.json` emitted by
#     `tools/e2e/run_batch.py`. Default points at the 20260507T224850Z reference
#     fixture, which exists on the developer's machine; override per-run via
#     `make hibayes-axes MANIFEST_PATH=evidence/headless/<RUN>/manifest.json`.
#   * ARTIFACT_ROOT — directory containing the run's artifacts (passed through
#     to the artifact_validator). Default points at the same 20260507T224850Z
#     reference fixture on the developer's Dropbox path.
#   * GEO_TEMPLATE — repo-tracked file at `tools/hibayes/resources/GEO-updated.json`.
#   * RUNTIME_CSV — bridge-emitted task-family CSV; default
#     `data/hibayes_eval_rows.csv` is repo-tracked.
MANIFEST_PATH ?= evidence/headless/20260507T224850Z/manifest.json
ARTIFACT_ROOT ?= ~/Library/CloudStorage/Dropbox/DMAC_Data/example-project/demo/20260507T224850Z/artifacts
GEO_TEMPLATE ?= tools/hibayes/resources/GEO-updated.json
RUNTIME_CSV ?= data/hibayes_eval_rows.csv
MAX_PARALLEL_QUERIES ?= 4
ARTIFACT_VALIDITY_CSV ?= out/hibayes_artifact_validity.csv
FUNCTIONAL_INPUTS_CSV ?= out/hibayes_functional_eval_inputs.csv
FUNCTIONAL_USEFULNESS_CSV ?= out/hibayes_functional_usefulness.csv
REVIEW_SIDECAR_CSV ?= out/hibayes_review_sidecar.csv
RUNTIME_POSTERIOR_CSV ?= out/hibayes_runtime_reliability/posterior_task_family_reliability.csv
ARTIFACT_POSTERIOR_JSON ?= out/hibayes_artifact_validity/posterior.json
FUNCTIONAL_POSTERIOR_JSON ?= out/hibayes_functional_usefulness/posterior.json
RUNTIME_POSTERIOR_JSON ?= out/hibayes_runtime_reliability/posterior.json
COMBINED_HTML ?= out/hibayes_combined_report.html

# task-7R1 — BAML codegen sentinel for `make baml-generate` (regenerates the
# gitignored host-side e2e BAML client from baml_src/). Pinned on sync_client.py
# because Stage C imports `from tools.e2e.baml_client import b` and `b` is
# exported there. `:=` for BAML_SOURCES so $(wildcard) evaluates once at parse.
BAML_CLIENT_SENTINEL ?= tools/e2e/baml_client/sync_client.py
BAML_SOURCES         := $(wildcard baml_src/*.baml)

# ----------------------------------------------------------------------------
# FILE TARGETS (the load-bearing rules; recipes produce the file)
# ----------------------------------------------------------------------------

# Stage A — host-side artifact validator → out/hibayes_artifact_validity.csv.
$(ARTIFACT_VALIDITY_CSV): $(MANIFEST_PATH) $(GEO_TEMPLATE)
	@uv run python -m tools.hibayes.artifact_validator \
		--manifest-path $(MANIFEST_PATH) \
		--artifact-root $(ARTIFACT_ROOT) \
		--geo-template-path $(GEO_TEMPLATE) \
		--out-csv $(ARTIFACT_VALIDITY_CSV)

# task-7R1 — BAML client regeneration. File-target keyed on `baml_src/*.baml`,
# so `baml-cli generate` only runs when a source is newer than the sentinel
# (DL-026 idempotency). `baml-cli generate --from baml_src` writes BOTH codegen
# targets per `baml_src/generators.baml` — the gitignored `tools/e2e/baml_client/`
# (sync; Stage C consumer) AND the tracked `src/dmac_assistant/router/baml_client/`
# (async; router subsystem). The router-client rewrite is a documented side
# effect; per the session-15 user decision, those tracked files stay
# uncommitted regardless of dirty status after invocation.
$(BAML_CLIENT_SENTINEL): $(BAML_SOURCES)
	@uv run baml-cli generate --from baml_src

.PHONY: baml-generate
baml-generate: $(BAML_CLIENT_SENTINEL)

# Stage B — host-side functional inputs builder.
$(FUNCTIONAL_INPUTS_CSV): $(ARTIFACT_VALIDITY_CSV) $(RUNTIME_CSV) $(MANIFEST_PATH)
	@uv run python -m tools.hibayes.functional_inputs \
		--manifest-path $(MANIFEST_PATH) \
		--runtime-csv $(RUNTIME_CSV) \
		--artifact-csv $(ARTIFACT_VALIDITY_CSV) \
		--out-csv $(FUNCTIONAL_INPUTS_CSV)

# Stage C — host-side BAML-driven evaluator.
$(FUNCTIONAL_USEFULNESS_CSV): $(FUNCTIONAL_INPUTS_CSV) $(ARTIFACT_VALIDITY_CSV) $(BAML_CLIENT_SENTINEL)
	@uv run python -m tools.e2e.functional_evaluator \
		--fei-csv $(FUNCTIONAL_INPUTS_CSV) \
		--av-csv $(ARTIFACT_VALIDITY_CSV) \
		--out-usefulness $(FUNCTIONAL_USEFULNESS_CSV) \
		--out-sidecar $(REVIEW_SIDECAR_CSV) \
		--max-parallel-queries $(MAX_PARALLEL_QUERIES)

# Stage D — in-image artifact-validity axis posterior.json.
# `hibayes-eval-build` is an ORDER-ONLY prereq (after `|`) per plan T4.2 row.
# Because this is a FILE TARGET (not PHONY), GNU Make's order-only guarantee
# applies: the image-build prereq drives ordering but does not retrigger a
# rebuild on every invocation when the posterior.json is newer than the CSV.
$(ARTIFACT_POSTERIOR_JSON): $(ARTIFACT_VALIDITY_CSV) | hibayes-eval-build
	@scripts/run_hibayes_eval_artifact.sh \
		python -m dmac_assistant.eval.hibayes_artifact_validity.run_hibayes \
		--input $(ARTIFACT_VALIDITY_CSV) \
		--out-dir /work/out/hibayes_artifact_validity

# Stage D — in-image functional-usefulness axis posterior.json.
$(FUNCTIONAL_POSTERIOR_JSON): $(FUNCTIONAL_USEFULNESS_CSV) | hibayes-eval-build
	@scripts/run_hibayes_eval_functional.sh \
		python -m dmac_assistant.eval.hibayes_functional_usefulness.run_hibayes \
		--input $(FUNCTIONAL_USEFULNESS_CSV) \
		--out-dir /work/out/hibayes_functional_usefulness

# Runtime-axis CSV (produced by the existing `hibayes-eval` target — Makefile:133).
# Pass 3 D4 resolution: declare a file-target rule whose recipe delegates to
# `$(MAKE) hibayes-eval` so Make's prereq graph is complete end-to-end. The
# existing `hibayes-eval` rule invokes `scripts/run_hibayes_eval.sh python -m
# dmac_assistant.eval.hibayes_runtime_reliability.run_hibayes --input $(INPUT)
# --out $(OUT)`, which writes `posterior_task_family_reliability.csv` into the
# `--out` directory (default `out/hibayes_runtime_reliability`). The
# `hibayes-eval-build` order-only prereq ensures the docker image is built
# before the sub-make invocation.
$(RUNTIME_POSTERIOR_CSV): $(RUNTIME_CSV) | hibayes-eval-build
	@$(MAKE) hibayes-eval INPUT=$(RUNTIME_CSV) OUT=out/hibayes_runtime_reliability

# Runtime-axis posterior.json adapter (T3.3).
# PYTHONPATH=src is REQUIRED: the host venv does NOT install `dmac_assistant`
# (pyproject has no [build-system]); the pytest-only `pythonpath = ["src", "."]`
# at pyproject.toml:48 does NOT apply to `uv run python`. This mirrors the
# in-container precedent at scripts/run_hibayes_eval.sh:22-30.
$(RUNTIME_POSTERIOR_JSON): $(RUNTIME_POSTERIOR_CSV)
	@PYTHONPATH=src uv run python -c "from pathlib import Path; \
from dmac_assistant.eval.hibayes_runtime_reliability.posterior_json_adapter import adapt_runtime_csv_to_posterior_json; \
adapt_runtime_csv_to_posterior_json(csv_path=Path('$(RUNTIME_POSTERIOR_CSV)'), out_path=Path('$(RUNTIME_POSTERIOR_JSON)'), prior_sigma_group_scale=2.0, run_id='make-run', thresholds={'strong': 0.9, 'acceptable': 0.8})"

# Combined HTML report — runs IN-IMAGE per locked DD-21 line 226 + DD-41 line 381.
$(COMBINED_HTML): $(RUNTIME_POSTERIOR_JSON) $(ARTIFACT_POSTERIOR_JSON) $(FUNCTIONAL_POSTERIOR_JSON) | hibayes-eval-build
	@scripts/run_hibayes_combined_report.sh \
		python -m dmac_assistant.eval.hibayes_combined_report.render \
		--runtime $(RUNTIME_POSTERIOR_JSON) \
		--artifact $(ARTIFACT_POSTERIOR_JSON) \
		--functional $(FUNCTIONAL_POSTERIOR_JSON) \
		--out-html $(COMBINED_HTML)

# ----------------------------------------------------------------------------
# PHONY ALIAS TARGETS (user-facing names; thin wrappers around file targets)
# ----------------------------------------------------------------------------

# Hardener Pass 4 D3 — explicit .PHONY: declarations for the 7 alias targets and
# the orchestrator. Without these declarations, if any file or directory ever
# appears in the repo with one of these names (e.g., a stale `hibayes-axes/`
# directory from a future experiment), GNU Make would treat the alias as a real
# file and either silently skip the recipe (file "exists", no prereqs newer) or
# attempt implicit-rule resolution — a silent-skip hazard with no error
# message. Declaring them PHONY makes the contract explicit and matches the
# existing Makefile convention at line 1 and line 117.
.PHONY: hibayes-stage-a hibayes-stage-b hibayes-stage-c \
        hibayes-eval-artifact hibayes-eval-functional \
        hibayes-runtime-posterior-json hibayes-combined-report \
        hibayes-axes

hibayes-stage-a: $(ARTIFACT_VALIDITY_CSV)
hibayes-stage-b: $(FUNCTIONAL_INPUTS_CSV)
hibayes-stage-c: $(FUNCTIONAL_USEFULNESS_CSV)
hibayes-eval-artifact: $(ARTIFACT_POSTERIOR_JSON)
hibayes-eval-functional: $(FUNCTIONAL_POSTERIOR_JSON)
hibayes-runtime-posterior-json: $(RUNTIME_POSTERIOR_JSON)
hibayes-combined-report: $(COMBINED_HTML)

# Orchestrator — 9-step chain in strict order per DL-020.
#
# Hardener Pass 4 D1+D2 — `hibayes-axes` depends ONLY on the terminal alias
# `hibayes-combined-report`, whose file target `$(COMBINED_HTML)` transitively
# pulls in every upstream file target via concrete file-existence prereqs:
#   $(COMBINED_HTML)
#     ← $(RUNTIME_POSTERIOR_JSON) ← $(RUNTIME_POSTERIOR_CSV) ← $(RUNTIME_CSV) [+ |hibayes-eval-build]
#     ← $(ARTIFACT_POSTERIOR_JSON) ← $(ARTIFACT_VALIDITY_CSV) ← $(MANIFEST_PATH) + $(GEO_TEMPLATE)  [+ |hibayes-eval-build]
#     ← $(FUNCTIONAL_POSTERIOR_JSON) ← $(FUNCTIONAL_USEFULNESS_CSV) ← $(FUNCTIONAL_INPUTS_CSV) ← $(ARTIFACT_VALIDITY_CSV) + $(RUNTIME_CSV) + $(MANIFEST_PATH)  [+ |hibayes-eval-build]
#     [+ |hibayes-eval-build]
# `hibayes-eval-build` is reached via order-only prereqs (`|` syntax) on every
# in-image file target — present at invocation time but not driving rebuilds
# via timestamp. `hibayes-eval` (the existing PHONY runtime-axis target) is
# reached EXCLUSIVELY via `$(RUNTIME_POSTERIOR_CSV)`'s `@$(MAKE) hibayes-eval`
# recipe — guarded by the file-target mtime check so the sub-make only fires
# when the runtime posterior CSV is stale relative to the runtime CSV. This
# resolves Pass 3 D1 HIGH (`hibayes-eval` and `hibayes-eval-build` were PHONY
# DIRECT prereqs of `hibayes-axes`, so they ran unconditionally on every
# `make hibayes-axes` invocation, breaking DL-026's "skip up-to-date steps on
# re-invocation" invariant) and Pass 3 D2 MED (duplicate runtime-axis fit
# invocation path collapses with D1: both the direct prereq and the
# sub-make in `$(RUNTIME_POSTERIOR_CSV)` would have fired the runtime fit;
# now only the sub-make path can fire, and only when the CSV is stale).
#
# The recipe's `@echo` line documents the chain ordering for both operator
# visibility and the §5 `test_hibayes_axes_chain_invokes_all_9_steps_in_order`
# regex (which captures the rule body and asserts the 9 step names appear in
# order).
hibayes-axes: hibayes-combined-report
	@echo "hibayes-axes chain (9 steps): hibayes-eval-build -> hibayes-eval -> hibayes-stage-a -> hibayes-stage-b -> hibayes-stage-c -> hibayes-eval-artifact -> hibayes-eval-functional -> hibayes-runtime-posterior-json -> hibayes-combined-report"
	@echo "hibayes-axes: complete; combined report at $(COMBINED_HTML)"

# T4.3 — Stage A in-container smoke gate (DD-04). Runs Stage A inside the image
# (Linux base, no macOS Keychain) on the reference fixture. Renamed per DL-020 to
# avoid collision with `hibayes-eval-artifact` (Stage D axis fit).
#
# Uses a DIRECT `docker run` invocation (NOT scripts/run_hibayes_eval_artifact.sh)
# because the smoke gate needs `evidence/` bind-mounted into the container to
# reach the reference manifest, and the per-axis wrapper does not mount evidence/.
# This `docker run` shape mirrors plan BP-9 verbatim. See §9 for the rationale.
#
# `hibayes-eval-build` is declared as an ORDER-ONLY prereq (after `|`) so the
# smoke recipe does not retrigger a network + docker-cache check (which
# `hibayes-eval-build` performs via `git ls-remote https://github.com/.../hibayes.git`)
# on every invocation; the image presence is required, but its .PHONY recipe
# should not drive smoke-target rebuilds. This preserves the CI-portability
# proof in offline environments. Pattern matches task-14's order-only positioning
# on `hibayes-eval-artifact` / `hibayes-eval-functional` / `hibayes-combined-report`.
#
# `mkdir -p out` runs BEFORE the `docker run` so that the host-side `out/`
# directory exists prior to the `-v $(CURDIR)/out:/work/out:rw` bind-mount.
# Without this, on Linux Docker (and some macOS Docker Desktop configurations),
# Docker will auto-create the missing host-side path as root-owned, breaking
# subsequent host-side writes / rm / edits. Same precedent as
# `scripts/run_hibayes_eval.sh` lines 19-20 (`mkdir -p "${REPO}/out"`).
#
# The in-container entry is `uv run python -m tools.hibayes.artifact_validator`.
# The image is built with `uv sync --no-install-project` (Dockerfile.hibayes-eval),
# so runtime deps such as `pydantic` (imported transitively via
# `tools/hibayes/__init__.py -> exporter.py`) live ONLY in `/work/.venv`, not in
# the system Python. A bare `python -m ...` fails with
# `ModuleNotFoundError: No module named 'pydantic'`; `uv run` activates the venv.
# Same `uv run` pattern as the canonical sibling wrappers
# `scripts/run_hibayes_eval.sh` and `scripts/run_hibayes_eval_artifact.sh`.
#
# Asserts the produced CSV exists, has the locked-design 29-column header, and
# has the expected number of data rows (one per manifest summary).
#
# The header extraction pipes through `tr -d '\r'`: `tools/hibayes/artifact_validator.py`
# writes the CSV via `csv.writer` (default dialect), whose `lineterminator` is
# `\r\n` (CRLF). Without stripping the trailing CR, the extracted header carries
# an invisible `\r` and the exact-equality test against the LF-terminated
# `SMOKE_EXPECTED_HEADER` literal fails. The row-count check uses `wc -l` (counts
# `\n`), which is unaffected by CRLF.

SMOKE_MANIFEST ?= /work/evidence/headless/20260507T224850Z/manifest.json
SMOKE_ARTIFACT_ROOT ?= /work/evidence/headless/20260507T224850Z/artifacts
SMOKE_IMAGE ?= hibayes-runtime-reliability:dev
SMOKE_EXPECTED_ROWS ?= 103
SMOKE_EXPECTED_HEADER ?= run_id,query_id,task_family,artifact_eval_id,artifact_expected,expected_artifact_kind,artifact_declared,artifact_path,artifact_basename,artifact_ext,runtime_success,failure_mode,artifact_exists,artifact_accessible,file_size_bytes,parser_used,parse_success,sheet_count,row_count,column_count,nonempty_cell_count,null_cell_fraction,required_fields_present,required_fields_complete,missing_required_fields,all_required_rows_complete,artifact_validity_status,artifact_success,validation_notes

.PHONY: hibayes-stage-a-smoke
hibayes-stage-a-smoke: | hibayes-eval-build
	@mkdir -p out
	@docker run --rm \
		--platform linux/amd64 \
		-v $(CURDIR)/tools:/work/tools:ro \
		-v $(CURDIR)/src:/work/src:ro \
		-v $(CURDIR)/evidence:/work/evidence:ro \
		-v $(CURDIR)/out:/work/out:rw \
		-e PYTHONPATH=/work/src:/work/tools \
		$(SMOKE_IMAGE) \
		uv run python -m tools.hibayes.artifact_validator \
			--manifest-path $(SMOKE_MANIFEST) \
			--artifact-root $(SMOKE_ARTIFACT_ROOT) \
			--geo-template-path /work/tools/hibayes/resources/GEO-updated.json \
			--out-csv /work/out/hibayes_artifact_validity_smoke.csv \
			--ignore-rebase-failures
	@test -s out/hibayes_artifact_validity_smoke.csv \
		|| { echo "ERROR: smoke gate did not produce output CSV"; exit 1; }
	@HEADER=$$(head -n 1 out/hibayes_artifact_validity_smoke.csv | tr -d '\r'); \
		test "$$HEADER" = "$(SMOKE_EXPECTED_HEADER)" \
		|| { echo "ERROR: smoke gate CSV header mismatch."; \
		     echo "  expected: $(SMOKE_EXPECTED_HEADER)"; \
		     echo "  actual:   $$HEADER"; exit 1; }
	@ROWS=$$(tail -n +2 out/hibayes_artifact_validity_smoke.csv | wc -l | tr -d ' '); \
		test "$$ROWS" -eq $(SMOKE_EXPECTED_ROWS) \
		|| { echo "ERROR: smoke gate produced $$ROWS data rows; expected $(SMOKE_EXPECTED_ROWS)."; exit 1; }; \
		echo "hibayes-stage-a-smoke: $$ROWS rows, header OK"
	@echo "hibayes-stage-a-smoke: PASS"
