# DMAC Assistant — Software Design Specification (SDS)

**Version:** 1.0 — POC  
**Author:** Taisha Joseph  
**Date:** April 2026  
**Status:** Draft  
**Organization:** MIT BioMicro Center (BMC)

---

## 1. Introduction

### 1.1 Purpose

This document specifies the design of the DMAC (Data Management and Analytics Core) Assistant system — a tool that provides BMC lab members with an AI-powered data management assistant. DMAC leverages Claude Code as its agent runtime within isolated Docker containers, giving users natural-language access to lab data management workflows, the NExtSEEK API, and data transformation tools — all scoped to the user's authorized project directories.

### 1.2 POC Scope

The POC validates the core containerization and integration pattern with a single user, while architecting for multi-user isolation. Specifically, the POC delivers:

- A Docker image with Claude Code pre-installed, configured to use AWS Bedrock as its model provider.
- Dynamic volume mounting that restricts a user's container to only their authorized DropBox project directories (read-only), a writable scratch/output area, and their persisted `.claude/` session directory.
- Environment variable injection for NExtSEEK basic auth credentials and the AWS Bedrock bearer token, with no secrets persisted to disk or baked into images.
- A FastAPI WebSocket bridge that relays messages between the existing chat UI and the Claude Code process running inside the container.
- Session persistence — users can resume prior Claude Code conversations across container restarts.
- Plugin availability: the NExtSEEK API plugin and 1–2 data transformation plugins (Python + Bash, CLI-invoked) pre-loaded in the container image.

**Out of POC scope:** production deployment on institutional VM, multi-user concurrency, container orchestration/lifecycle management, institutional SSO integration, bearer token refresh automation.

### 1.3 Definitions

| Term | Definition |
|------|-----------|
| DMAC | Data Management and Analytics Core — the team/function this system supports |
| Claude Code | Anthropic's CLI-based agentic coding tool |
| Plugin | A CLI-invocable script (Python or Bash) with accompanying documentation that Claude Code reads and uses autonomously |
| NExtSEEK | The lab's data/sample tracking system, accessed via REST API |
| Bedrock | AWS service providing access to Claude models |
| Scratch area | A writable directory inside the container for Claude Code to produce output files |

---

## 2. System Architecture

### 2.1 Architecture Overview

```
┌──────────────────────────────────────────────────────────┐
│                     Host Machine (MBP / VM)               │
│                                                           │
│  ┌─────────────┐     ┌──────────────────────────────┐     │
│  │  Chat UI     │────▶│  FastAPI Backend              │     │
│  │  (Browser)   │◀────│  (WebSocket Bridge)           │     │
│  └─────────────┘     └──────────┬───────────────────┘     │
│                                 │                          │
│                    docker run   │  stdin/stdout             │
│                    (per-user)   │  (stream-json)            │
│                                 ▼                          │
│  ┌──────────────────────────────────────────────────┐     │
│  │           Docker Container (dmac-assistant)       │     │
│  │                                                   │     │
│  │  ┌──────────────────────────────────────────┐    │     │
│  │  │  Claude Code (headless, stream-json)     │    │     │
│  │  │  Model: AWS Bedrock (bearer token)       │    │     │
│  │  └────────────┬─────────────────────────────┘    │     │
│  │               │ reads docs, invokes CLI tools     │     │
│  │               ▼                                   │     │
│  │  ┌───────────────────────────────────────────┐   │     │
│  │  │  /app/plugins/          (baked in image)  │   │     │
│  │  │  /app/docs/             (baked in image)  │   │     │
│  │  │  /app/CLAUDE.md         (baked in image)  │   │     │
│  │  │  /data/projects/        (mounted, RO)     │   │     │
│  │  │  /data/scratch/         (mounted, RW)     │   │     │
│  │  │  /home/user/.claude/    (mounted, RW)     │   │     │
│  │  └───────────────────────────────────────────┘   │     │
│  │                                                   │     │
│  │  ENV: AWS_BEARER_TOKEN_BEDROCK                   │     │
│  │  ENV: NEXTSEEK_USERNAME / NEXTSEEK_PASSWORD      │     │
│  │  ENV: AWS_REGION                                  │     │
│  │  ENV: CLAUDE_CODE_USE_BEDROCK=1                  │     │
│  └──────────────────────────────────────────────────┘     │
│                                                           │
│  Host Filesystem:                                         │
│  ├── /persistent/claude-users/{user_id}/.claude/          │
│  ├── /persistent/scratch/{user_id}/                       │
│  └── ~/Library/CloudStorage/Dropbox/DMAC_Data/{project}/  │
└──────────────────────────────────────────────────────────┘
```

### 2.2 Component Descriptions

#### 2.2.1 Docker Image (`dmac-assistant`)

A pre-built image containing:

- **Base:** Ubuntu or Node.js LTS (required for Claude Code runtime)
- **Claude Code:** Installed globally via npm
- **uv:** Installed for Python plugin dependency management
- **Plugins:** Copied into `/app/plugins/` with their dependencies pre-installed
- **Documentation:** CLAUDE.md and docs/ folder copied into `/app/docs/`
- **Entrypoint:** A bash script that sets environment variables and launches Claude Code in headless mode

The image contains zero secrets. All credentials are injected at runtime.

#### 2.2.2 FastAPI WebSocket Bridge

A lightweight Python service that:

1. Accepts WebSocket connections from the chat UI.
2. Authenticates the user against a local credential store.
3. Resolves the user's authorized project directories (hardcoded mapping for POC).
4. Starts a Docker container with the correct mounts and environment variables.
5. Relays messages bidirectionally between the WebSocket and Claude Code's stdin/stdout (using `--output-format stream-json`).
6. Handles session resumption by passing `--resume` or `--session-id` flags to Claude Code.

#### 2.2.3 Plugin System

Plugins are CLI tools that Claude Code invokes autonomously based on user instructions and the documentation in CLAUDE.md / docs/. Each plugin consists of:

- The executable script(s) (Python or Bash)
- A markdown documentation file describing usage, arguments, and examples
- Any dependency specifications (e.g., `pyproject.toml` for Python plugins)

Claude Code discovers plugins by reading CLAUDE.md at startup, which references the docs/ folder for detailed per-plugin documentation.

#### 2.2.4 Session Persistence

Each user has a persistent `.claude/` directory stored on the host at `/persistent/claude-users/{user_id}/.claude/`. This directory is mounted into the container at `/home/user/.claude/` and contains Claude Code's session history, conversation state, and user-specific settings. The entrypoint script scrubs any secrets from `settings.local.json` on startup to prevent credential leakage across sessions.

---

## 3. Data Flow

### 3.1 User Authentication and Container Startup

```
User ──▶ Chat UI ──▶ FastAPI Backend
                         │
                         ├─ 1. Validate credentials against local store
                         ├─ 2. Look up user's project directory mapping
                         ├─ 3. Ensure /persistent/claude-users/{user_id}/.claude/ exists
                         ├─ 4. Ensure /persistent/scratch/{user_id}/ exists
                         ├─ 5. docker run with:
                         │      -v dropbox/{project}:/data/projects/{project}:ro
                         │      -v /persistent/claude-users/{user_id}/.claude:/home/user/.claude
                         │      -v /persistent/scratch/{user_id}:/data/scratch
                         │      -e AWS_BEARER_TOKEN_BEDROCK=...
                         │      -e NEXTSEEK_USERNAME=...
                         │      -e NEXTSEEK_PASSWORD=...
                         │      -e CLAUDE_CODE_USE_BEDROCK=1
                         │      -e AWS_REGION=us-east-1
                         └─ 6. Attach to container stdin/stdout
```

### 3.2 Message Flow (Steady State)

```
User types message
  ──▶ Chat UI (WebSocket)
    ──▶ FastAPI Backend
      ──▶ Container stdin (JSON)
        ──▶ Claude Code processes
          ──▶ (may invoke plugins via CLI)
          ──▶ (may read/write /data/scratch/)
          ──▶ (may call NExtSEEK API using env credentials)
        ──▶ Container stdout (stream-json)
      ──▶ FastAPI Backend
    ──▶ Chat UI (WebSocket)
  ──▶ Rendered to user
```

### 3.3 Session Resumption

```
User reconnects
  ──▶ FastAPI Backend
    ──▶ Lists sessions from /persistent/claude-users/{user_id}/.claude/
    ──▶ User selects session (or starts new)
    ──▶ docker run ... claude --resume --session-id {id}
```

---

## 4. Security Model

### 4.1 Directory Isolation

Data directories are mounted read-only into the container. The user can only see project directories they are authorized for — this is enforced at the Docker volume mount level, not by application logic. Claude Code inside the container has no filesystem path to unauthorized data because it simply is not mounted.

### 4.2 Secret Management

| Secret | Storage | Lifetime |
|--------|---------|----------|
| AWS_BEARER_TOKEN_BEDROCK | Runtime env var only | Expires (typically hourly); passed fresh on each container start |
| NEXTSEEK_USERNAME / PASSWORD | Runtime env var only | Same as user's chat session |
| User credentials (chat UI) | Local credential store on host | Persistent; never enters container |

**Invariant:** No secret is ever written to the Docker image, to the `.claude/` session directory, or to any mounted volume. The entrypoint script actively scrubs `settings.local.json` on startup.

### 4.3 Network Isolation (Future)

For the POC, the container has default network access (required for Bedrock API calls and NExtSEEK API calls). In production, the container's network should be restricted to only the Bedrock endpoint and the NExtSEEK API host.

---

## 5. Container Specification

### 5.1 Dockerfile (Conceptual)

```dockerfile
FROM node:20-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3 python3-pip curl git bash \
    && rm -rf /var/lib/apt/lists/*

# Install uv (for Python plugin dependencies)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# Install Claude Code globally
RUN npm install -g @anthropic-ai/claude-code

# Create app structure
WORKDIR /app
COPY plugins/ /app/plugins/
COPY docs/ /app/docs/
COPY CLAUDE.md /app/CLAUDE.md
COPY entrypoint.sh /app/entrypoint.sh

# Install plugin dependencies
RUN cd /app/plugins && uv sync  # or per-plugin install

# Create non-root user
RUN useradd -m -s /bin/bash user
USER user

ENTRYPOINT ["/app/entrypoint.sh"]
```

### 5.2 Entrypoint Script (Conceptual)

```bash
#!/bin/bash
set -euo pipefail

# Secrets come from env vars — never touch disk
export CLAUDE_CODE_USE_BEDROCK=1
export AWS_REGION="${AWS_REGION:-us-east-1}"
# AWS_BEARER_TOKEN_BEDROCK, NEXTSEEK_USERNAME, NEXTSEEK_PASSWORD
# are already in environment via docker run -e

# Scrub any cached secrets from persisted session directory
if [ -f /home/user/.claude/settings.local.json ]; then
    python3 -c "
import json, sys
try:
    with open('/home/user/.claude/settings.local.json') as f:
        settings = json.load(f)
    settings.pop('env', None)
    with open('/home/user/.claude/settings.local.json', 'w') as f:
        json.dump(settings, f, indent=2)
except: pass
"
fi

# Launch Claude Code in headless mode (idle-container boot CMD).
# NOTE (OI-5, 2026-06-05): real per-turn CC turns are docker-exec'd with
# `--permission-mode auto` (a per-tool-call classifier), NOT the bypass flag;
# this boot CMD is cosmetic — idle containers run `sleep infinity`. See ADR-012.
cd /app
exec claude --print --output-format stream-json --dangerously-skip-permissions "$@"
```

### 5.3 Volume Mounts

| Container Path | Host Path | Mode | Purpose |
|---------------|-----------|------|---------|
| `/data/projects/{name}` | `~/Library/CloudStorage/Dropbox/DMAC_Data/{name}` | `ro` | Authorized project data |
| `/data/scratch` | `/persistent/scratch/{user_id}` | `rw` | Output / working files |
| `/data/output/` | `/persistent/output/{user_id}/` (Linux prod) · `~/dmac-dev/output/` (dev) | `ro` | Per-user published artifacts (post-turn copier writes here) |
| `/home/user/.claude` | `/persistent/claude-users/{user_id}/.claude` | `rw` | Session persistence |

### 5.4 Environment Variables

| Variable | Source | Required |
|----------|--------|----------|
| `CLAUDE_CODE_USE_BEDROCK` | Hardcoded `1` in entrypoint | Yes |
| `AWS_BEARER_TOKEN_BEDROCK` | Passed from backend at container start | Yes |
| `AWS_REGION` | Passed from backend, defaults to `us-east-1` | Yes |
| `NEXTSEEK_USERNAME` | User's login credentials | Yes |
| `NEXTSEEK_PASSWORD` | User's login credentials | Yes |
| `GCP_API_KEY` | Bridge host process env only — **not forwarded to the agent container** (sidecar build, T10/U-1) | Optional — needed only on the bridge host for the LLM router's BAML route decisions; `chat_nextseek`'s GCP-profile use runs server-side on NExtSEEK |
| `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` | **Not forwarded to the agent container** (sidecar build, T10/U-1) | n/a in-container — NExtSEEK holds Neo4j access server-side for graph queries; `NEO4J_PASSWORD` is no longer an in-container exfiltration surface |
| `DMAC_PATH_MAPPINGS` | Bridge-constructed JSON; emitted by `_build_bridge_env(config, identity)` | Yes (Plan A) — maps container roots `/data/output` and `/data/scratch` to per-user host roots so plugins can report host-side paths to users |

#### New environment variables (Plan A) — detail

- `GCP_API_KEY` — **no longer forwarded to the agent container** (sidecar build, T10/U-1). It is needed only on the bridge host for the LLM router's BAML route decisions; `chat_nextseek`'s GCP-profile use now runs server-side on NExtSEEK. The former in-container exfiltration surface is closed; the Bedrock token (`AWS_BEARER_TOKEN_BEDROCK`) remains the open one (see Known Issues — Bedrock token exposure).
- `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` — **no longer forwarded to the agent container** (sidecar build, T10/U-1). NExtSEEK holds Neo4j access server-side for graph queries; these are absent from the agent container, so `NEO4J_PASSWORD` is no longer an in-container exfiltration surface.
- `MYSQL_*` / `SESSION_DB_*` — **not forwarded to the agent container** either; they are among the 16 shared-credential keys `_build_environment` removed (T10/U-1). NExtSEEK's MySQL / session store is reached server-side; these credentials are not present in the agent container. (Together, `GCP_API_KEY` + `NEO4J_*` + `MYSQL_*` + `SESSION_DB_*` are the full set ADR-013 describes as contained.)
- `DMAC_OUTPUT_ROOT` — host directory mounted at `/data/output/` ro inside the container. Bridge writes to this directory via the post-turn copier (see "Bridge-side artifact copier" below). **D19 (CC reports host-side paths to the user) is implemented end-to-end: the bridge injects `DMAC_PATH_MAPPINGS` (Plan A T9b) and the `nextseek` plugin's `SKILL.md` consumes it (Plan B, merged 2026-05-06).**

#### D19 — Host-path reporting

D19 (host-path reporting) is implemented by `DMAC_PATH_MAPPINGS`; see Plan A T9b. Implemented by Plan A T9b: the bridge constructs `DMAC_PATH_MAPPINGS` in `_build_bridge_env(config, identity)` and passes it to the container via `bridge_env`. The shape is `{"output": {"container_root": "/data/output", "host_root": "<config.output_root>/<user_id>"}, "scratch": {"container_root": "/data/scratch", "host_root": "<config.scratch_root>/<user_id>"}}`. Plan B's `SKILL.md` consumes it for path translation so plugin output messages can report host-side paths back to the user.

**Status:** complete end-to-end. The bridge-side injection landed in Plan A (T9b), and the in-container `nextseek` plugin `SKILL.md` consumer that translates container paths to host paths in user-facing messages shipped with Plan B (merged 2026-05-06, `adb54aa`). The in-container agent now both receives the mapping and consumes it for output translation.

### 5.5 Bridge-side artifact copier

After every container turn, the bridge copies `<scratch_root>/<user_id>/<run_id>/` to `<output_root>/<user_id>/<run_id>/`. Run-ids are discovered by the bridge via a directory-listing diff: it snapshots `<scratch_root>/<user_id>/` subdirs before the turn starts and again after CC's terminating message; new subdirs are the run_ids the copier publishes. Symlinks within the source tree are skipped to prevent path-traversal exfiltration via plugin-staged symlinks. Copier failures are logged but never raise — partial publish is acceptable; a session crash from publishing is not.

Image v2: the copier infra landed in Plan A; the new `nextseek` plugin swap-in shipped with Plan B (Dockerfile swap `5c517b5`, merged 2026-05-06). The image now ships only the `nextseek` plugin; the old `nextseek-api` plugin is preserved host-side under `build_context/plugins/nextseek-api/` for reuse but no longer runs in the image.

---

## 6. FastAPI Bridge Specification

### 6.1 Endpoints

| Endpoint | Type | Purpose |
|----------|------|---------|
| `POST /auth/login` | HTTP | Authenticate user, return session token |
| `GET /sessions/{user_id}` | HTTP | List available Claude Code sessions for user |
| `WS /ws/chat` | WebSocket | Bidirectional message relay to Claude Code container |

### 6.2 WebSocket Protocol

**Client → Server (user message):**
```json
{
  "type": "user_message",
  "content": "Show me the latest samples in project X",
  "session_id": "optional-session-id-to-resume"
}
```

**Server → Client (Claude Code streaming response):**
```json
{
  "type": "assistant_message",
  "content": "...",
  "stream": true
}
```

**Server → Client (tool use notification):**
```json
{
  "type": "tool_use",
  "tool": "bash",
  "status": "running"
}
```

### 6.3 Container Lifecycle (POC)

For the POC, the backend manages a single container per WebSocket connection:

1. On WebSocket connect: start container (or attach to existing).
2. On each message: write to container stdin, stream stdout back.
3. On WebSocket disconnect: leave container running for a configurable timeout (default: 30 minutes).
4. On timeout: `docker stop` and `docker rm` the container. Session data persists in the mounted `.claude/` directory.

---

## 7. Plugin Architecture

### 7.1 Plugin Directory Structure

```
/app/
├── CLAUDE.md                  # Top-level context for Claude Code
├── docs/
│   ├── nextseek-api.md        # NExtSEEK API plugin documentation
│   ├── transform-plugin.md    # Data transformation plugin docs
│   └── lab-workflows.md       # General BMC lab procedures / training docs
└── plugins/
    ├── nextseek/
    │   ├── ...                # NExtSEEK plugin files
    │   └── pyproject.toml     # Dependencies (managed by uv)
    ├── transform/
    │   ├── transform.py       # Python transformation script
    │   └── process.sh         # Bash processing script
    └── ...
```

### 7.2 How Claude Code Discovers and Uses Plugins

1. On startup, Claude Code reads `/app/CLAUDE.md`.
2. CLAUDE.md describes each available plugin: what it does, where its executable lives, how to invoke it, and points to the detailed docs in `/app/docs/`.
3. When a user asks Claude Code to perform a task, Claude Code reads the relevant documentation, determines which plugin and arguments to use, and invokes it via CLI (e.g., `python /app/plugins/transform/transform.py --input /data/projects/proj-a/file.csv --output /data/scratch/result.csv`).
4. Claude Code reads the output and reports results to the user.

### 7.3 Plugin I/O Convention

- **Input:** Plugins read from `/data/projects/` (read-only mounted data).
- **Output:** Plugins write to `/data/scratch/` (writable scratch area).
- **Credentials:** Plugins that need NExtSEEK access read `NEXTSEEK_USERNAME` and `NEXTSEEK_PASSWORD` from environment variables.

---

## 8. Multi-User Architecture (Post-POC)

While the POC targets a single user, the architecture is designed for multi-user operation:

1. Each authenticated user gets their own Docker container with unique volume mounts and credentials.
2. The FastAPI backend maintains a mapping of `user_id → container_id`.
3. Containers are started on demand and stopped after an idle timeout.
4. No container can access another user's `.claude/` directory or unauthorized project directories — enforced by Docker, not application logic.
5. The FastAPI backend would need a container pool manager to track active containers, enforce limits, and handle cleanup.

---

## 9. Development and Testing Plan

### 9.1 POC Milestones

| Day | Milestone |
|-----|-----------|
| 1–2 | Validate Claude Code + Bedrock locally. Test headless mode (`--print --output-format stream-json`). Verify plugin invocation works end-to-end. |
| 3–4 | Build Dockerfile. Bake in plugins and docs. Test container with correct mounts and env vars. Verify directory isolation (cannot escape mounted paths). |
| 5–6 | Build FastAPI WebSocket bridge. Connect chat UI ↔ bridge ↔ container stdin/stdout. Test session persistence (stop container, restart, resume session). |
| 7 | End-to-end testing: authenticate, start container, invoke NExtSEEK plugin, run data transformation, verify output in scratch directory, resume session. |

### 9.2 Acceptance Criteria

1. Claude Code inside the container can query NExtSEEK using credentials passed as environment variables.
2. Claude Code can read files from a mounted project directory and write output to the scratch area.
3. Claude Code cannot access any directory outside its mounts.
4. The chat UI can exchange messages with Claude Code via the WebSocket bridge.
5. A session can be resumed after the container is stopped and restarted.
6. No secrets appear in the Docker image, in `.claude/` session files, or in container logs.
