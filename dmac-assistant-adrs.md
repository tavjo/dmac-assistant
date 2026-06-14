# DMAC Assistant — Architecture Decision Records (ADRs)

**Project:** DMAC Assistant POC  
**Organization:** MIT BioMicro Center (BMC)  
**Date:** April 2026

---

## ADR-001: Use Claude Code as the Agent Runtime

**Status:** Accepted

**Context:**  
Building a multi-agent orchestration system from scratch would take months and require significant ongoing maintenance — time the author does not have before leaving for grad school. The system needs an LLM agent that can read documentation, invoke CLI tools autonomously, manage conversation context, and handle complex multi-step workflows.

**Decision:**  
Use Claude Code (Anthropic's CLI-based agentic tool) as the agent runtime. Claude Code will run in headless mode (`--print --output-format stream-json`) inside Docker containers, receiving user messages via stdin and emitting structured responses via stdout.

**Consequences:**  
- **Positive:** No custom agent loop to build or maintain. Claude Code handles tool invocation, context management, conversation flow, and error recovery out of the box. The successor inherits a well-supported, actively-maintained runtime.
- **Positive:** Plugin development is straightforward — write a CLI tool and a documentation file, and Claude Code figures out when and how to use it.
- **Negative:** Dependency on Anthropic's product roadmap. Breaking changes to Claude Code's CLI interface or stream-json format would require updates to the bridge layer.
- **Negative:** Limited control over Claude Code's internal behavior (e.g., how it decides which tool to call, how it handles ambiguity).
- **Mitigation:** The bridge layer is thin (~200 lines) and can be adapted quickly if the CLI interface changes. Pin Claude Code to a specific npm version in the Dockerfile.

---

## ADR-002: Docker-Based Isolation for User Scoping

**Status:** Accepted

**Context:**  
Users must only access data for projects they are authorized for. The system must prevent any cross-user data leakage — including through the AI agent, which could inadvertently reference data from another user's context. Multiple isolation strategies were considered: application-level access control within Claude Code, OS-level user permissions, and container-level isolation.

**Decision:**  
Use Docker containers as the isolation boundary. Each user session runs in its own container with only authorized directories mounted as volumes. Unauthorized data is never visible to the container's filesystem — it is not filtered or hidden, it is simply absent.

**Consequences:**  
- **Positive:** Isolation is enforced by the container runtime, not application logic. There is no code path through which Claude Code could access unauthorized data, because the data is not mounted.
- **Positive:** Simple mental model: the container *is* the user's sandbox. Everything inside it is safe to access.
- **Negative:** Each user session requires a running container, consuming memory and CPU. For the POC (single user) this is trivial; for production with many concurrent users, resource management becomes important (see ADR-007).
- **Negative:** Container startup adds latency to the first message (~5–15 seconds). Subsequent messages within the same session are fast.

---

## ADR-003: Read-Only Data Mounts with Separate Scratch Area

**Status:** Accepted

**Context:**  
Claude Code needs access to lab data (in DropBox-synced project directories) to perform analysis and transformations. However, the data in DropBox is the lab's source of truth and must not be modified by the AI agent — accidental deletion or corruption would be catastrophic. DropBox sync means any file change propagates immediately to all synced machines.

**Decision:**  
Mount project data directories as read-only (`:ro`). Provide a separate writable scratch directory (`/data/scratch/`) for Claude Code to write output files. The scratch area is per-user and persisted on the host.

**Consequences:**  
- **Positive:** Impossible for Claude Code to modify, delete, or corrupt source data. DropBox sync is never triggered by the agent.
- **Positive:** Output files in scratch are clearly separated from source data, making review easy.
- **Negative:** Plugins must be designed to read from `/data/projects/` and write to `/data/scratch/` — they cannot do in-place transformations. This is an intentional constraint.

---

## ADR-004: AWS Bedrock as Model Provider

**Status:** Accepted

**Context:**  
Claude Code defaults to using Anthropic's API directly, which would require a personal or organizational Anthropic API key. The BMC already has AWS Bedrock access with Claude models enabled, paid for by institutional budget. Using Bedrock avoids personal billing and leverages existing infrastructure.

**Decision:**  
Configure Claude Code to use AWS Bedrock via the `CLAUDE_CODE_USE_BEDROCK=1` environment variable and `AWS_BEARER_TOKEN_BEDROCK` for authentication.

**Consequences:**  
- **Positive:** No separate Anthropic API billing. Uses existing institutional AWS account.
- **Positive:** Authentication is straightforward — the bearer token is passed as an environment variable.
- **Negative:** Bearer tokens expire (typically hourly). For the POC, the token is passed at container start; if a session runs longer than the token's lifetime, Bedrock calls will fail. The user must re-authenticate or the system must refresh the token.
- **Negative:** Model availability depends on what the institutional Bedrock account has enabled. Claude Code may expect a specific model (e.g., Claude Sonnet) that needs to be explicitly enabled in Bedrock.
- **Mitigation (post-POC):** Implement token refresh — the FastAPI backend can obtain new tokens via AWS IAM Identity Center and inject them into the running container, or restart the container with a fresh token.

---

## ADR-005: Secrets as Runtime Environment Variables Only

**Status:** Accepted

**Context:**  
The system handles three categories of secrets: AWS Bedrock bearer tokens, NExtSEEK credentials (username/password), and chat UI login credentials. These must be available to Claude Code and its plugins at runtime, but must never be persisted to disk, baked into Docker images, or leaked into session logs.

**Decision:**  
All secrets are passed exclusively as environment variables via `docker run -e`. The container entrypoint script actively scrubs the `.claude/settings.local.json` file on startup to remove any `env` block that may have been cached from a prior session. No secret is ever written to a file inside the container or on a mounted volume.

**Consequences:**  
- **Positive:** Secrets exist only in the container's runtime environment, which is ephemeral. `docker inspect` can reveal them, but only to users with Docker access on the host (which is the admin).
- **Positive:** The Docker image can be shared, stored in a registry, or inspected without risk of credential exposure.
- **Negative:** Claude Code or a plugin could theoretically write environment variable values to a file (e.g., a log). Mitigation: CLAUDE.md explicitly instructs Claude Code to never log or write credentials. The scratch directory should be treated as potentially containing sensitive output and not shared between users.
- **Negative:** If Claude Code internally caches credentials in `.claude/`, the scrub-on-startup approach is reactive, not preventive. Monitoring is advisable.

---

## ADR-006: FastAPI WebSocket Bridge as the Integration Layer

**Status:** Accepted

**Context:**  
The existing chat UI communicates via WebSocket. Claude Code runs as a CLI process with stdin/stdout. A bridge is needed to translate between the two protocols. Options considered: modifying the chat UI to spawn processes directly; building a Django Channels integration; or a standalone FastAPI service.

**Decision:**  
Use a standalone FastAPI application with WebSocket endpoints as the bridge between the chat UI and the Docker container. The bridge manages authentication, container lifecycle, and stdin/stdout relay. It uses the Docker SDK for Python (`docker-py`) to manage containers programmatically.

**Rationale for FastAPI over Django Channels:**  
The existing chat UI was developed and tested against a FastAPI WebSocket backend. FastAPI's async-first design maps cleanly to the concurrent I/O pattern of relaying between a WebSocket and a subprocess stream. The bridge is a small, focused service (~200–400 lines) that does not need Django's ORM, admin, or middleware stack.

**Rationale for docker-py over subprocess:**  
The Docker SDK for Python provides a programmatic API for container lifecycle management (create, start, attach to streams, stop, remove), which is more robust than shelling out to the `docker` CLI — especially for stream attachment and error handling.

**Consequences:**  
- **Positive:** Clean separation of concerns. The bridge is stateless (all state lives in the container and its mounted volumes) and easy to reason about.
- **Positive:** The chat UI requires no changes — it connects to a WebSocket endpoint and exchanges messages, unaware of the Docker layer.
- **Negative:** An additional service to run alongside the chat UI. For the POC, this runs on the same machine; in production, it could be co-located or separate.

---

## ADR-007: Container Lifecycle with Idle Timeout

**Status:** Accepted (architecture); Deferred (implementation post-POC)

**Context:**  
Each user session requires a running Docker container. Containers consume resources (memory, CPU, disk) even when idle. The system must balance responsiveness (instant replies for active users) with resource efficiency (not running containers indefinitely for users who have left).

**Decision:**  
Containers remain running for a configurable idle timeout (default: 30 minutes) after the user's last message. On timeout, the container is stopped and removed. Session data persists in the mounted `.claude/` directory and can be resumed by starting a new container with the same mounts.

For the POC, this is managed manually (the developer starts/stops containers). Post-POC, the FastAPI backend will track last-activity timestamps and run a background task to stop idle containers.

**Consequences:**  
- **Positive:** Active users get instant responses with no container startup latency.
- **Positive:** Idle containers are cleaned up, freeing resources.
- **Positive:** Session resumption works because `.claude/` is on a persistent volume.
- **Negative:** Container startup latency (~5–15 seconds) when a user returns after timeout. This is acceptable for the use case.
- **Trade-off:** The timeout value balances resource usage against user experience. 30 minutes is a reasonable default — long enough for a user to take a coffee break and return, short enough to free resources for a small deployment.

---

## ADR-008: Plugin Architecture — CLI Tools with Markdown Documentation

**Status:** Accepted

**Context:**  
The DMAC assistant needs to invoke lab-specific tools (NExtSEEK API interactions, data transformations). These tools exist as Python and Bash scripts. The integration pattern must be simple enough for a successor to add new plugins without deep knowledge of the system's internals. Several patterns were considered: MCP (Model Context Protocol) servers, Python library imports, and CLI tools with documentation.

**Decision:**  
Plugins are CLI-invocable scripts accompanied by markdown documentation. Claude Code reads the documentation (referenced from CLAUDE.md) and autonomously determines when and how to invoke each plugin. Plugins read input from mounted data directories and write output to the scratch area. Plugins access credentials via environment variables.

**Rationale against MCP servers for the POC:**  
Converting existing scripts to MCP servers would add development time and complexity (each MCP server is a long-running process with a JSON-RPC interface). The existing scripts already work as CLI tools that Claude Code can invoke. MCP remains an option for future plugins that would benefit from persistent state or complex interaction patterns.

**Consequences:**  
- **Positive:** Zero conversion effort — existing scripts work as-is with only documentation added.
- **Positive:** Low barrier for the successor to add new plugins: write a script, write a markdown doc, reference it in CLAUDE.md.
- **Positive:** Claude Code natively understands CLI tool invocation and handles argument construction, output parsing, and error recovery.
- **Negative:** Less structured than MCP — Claude Code must infer the correct arguments from documentation rather than a formal tool schema. Good documentation is critical.
- **Negative:** Each plugin invocation is a fresh process — no persistent state between calls. For the POC plugins (stateless transformations and API calls), this is fine.

---

## ADR-009: Shared Credentials for Chat UI and NExtSEEK

**Status:** Accepted

**Context:**  
Users authenticate to the chat UI with username/password. The NExtSEEK API also uses basic authentication, and the credentials are the same. The question is whether to require users to authenticate separately for each system, or to pass through the chat UI credentials.

**Decision:**  
The chat UI login credentials are passed through to the Docker container as `NEXTSEEK_USERNAME` and `NEXTSEEK_PASSWORD` environment variables. Claude Code's plugins use these to authenticate against the NExtSEEK API. The user authenticates once.

**Consequences:**  
- **Positive:** Single sign-on experience — users log in once and have access to both the assistant and NExtSEEK.
- **Positive:** NExtSEEK operations are performed with the user's own permissions, maintaining the NExtSEEK access control model.
- **Negative:** The FastAPI backend must hold the user's plaintext password in memory for the duration of the session (to pass to Docker). It is never written to disk, but it is in process memory.
- **Negative:** If NExtSEEK credentials change independently of the chat UI store, they will diverge. For the POC with a small user base, this is manageable.

---

## ADR-010: Session Persistence via Mounted .claude/ Directory

**Status:** Accepted

**Context:**  
Users need to resume prior conversations with the DMAC assistant. Claude Code stores session data (conversation history, context) in a `.claude/` directory in the user's home folder. Since containers are ephemeral (stopped after idle timeout, removed), this data must be persisted externally.

**Decision:**  
Each user has a persistent directory on the host at `/persistent/claude-users/{user_id}/.claude/`. This is mounted into the container at `/home/user/.claude/`. When a container is stopped and later restarted, the session data is immediately available. Claude Code's `--resume` or `--session-id` flags are used to continue a prior conversation.

**Consequences:**  
- **Positive:** Sessions survive container restarts, host reboots, and idle timeouts.
- **Positive:** The user's conversation history and Claude Code preferences accumulate over time, improving the experience.
- **Negative:** The `.claude/` directory may grow over time. A cleanup policy (e.g., deleting sessions older than 90 days) may be needed post-POC.
- **Negative:** The directory may inadvertently contain cached secrets (see ADR-005). The entrypoint script mitigates this by scrubbing `settings.local.json` on startup.
- **Negative:** If the persistent storage is lost (disk failure, accidental deletion), all session history is lost. Backups are advisable for production.

---

## ADR-011: Intel macOS for POC Development, Linux VM for Production

**Status:** Accepted

**Context:**  
The POC will be developed on an Intel MacBook Pro with Docker Desktop. Production deployment targets a Linux VM on institutional infrastructure. Docker images built on macOS/Intel are `linux/amd64`, which runs natively on most Linux VMs.

**Decision:**  
Develop and test on the local MBP. The Dockerfile targets `linux/amd64` (the default for Intel Macs). No multi-platform build is needed for the POC. When moving to the institutional VM, the same image should run without modification.

**Consequences:**  
- **Positive:** No cross-compilation or multi-arch complexity for the POC.
- **Positive:** Docker behavior on Intel Mac closely matches Linux, minimizing "works on my machine" issues.
- **Negative:** If the institutional VM uses ARM (unlikely but possible), the image would need a multi-platform rebuild. This is a simple `docker buildx` change.
- **Note:** The DropBox path differs between macOS (`~/Library/CloudStorage/Dropbox/DMAC_Data/`) and Linux (likely `~/Dropbox/DMAC_Data/` or a custom sync path). The mount path in the `docker run` command is the only thing that changes — the container always sees `/data/projects/`.

---

## ADR-012: Skip Claude Code Permission Prompts (`--dangerously-skip-permissions`)

**Status:** Superseded for real turns (2026-06-05, OI-5) — see the Update note below.

> **Update (2026-06-05, OI-5):** `--permission-mode auto` (a per-tool-call classifier with turn/budget caps and a trusted-infra `autoMode.environment` allowlist) **replaced** `--dangerously-skip-permissions` for every real per-turn CC invocation, in commit `f9ce6af` (merged `189bfa3`). The bypass flag survives only in the idle-container boot CMD (`containers.py` `_BASE_COMMAND`), which is cosmetic — idle containers run `sleep infinity`, and every real turn is `docker exec`'d under auto mode via `exec_cc_turn`. The Docker-isolation reasoning below still holds; auto mode adds defense-in-depth on top of it. This does NOT retire the Bedrock-token exfiltration production-blocker (see ADR-013 and `known-issues/bedrock-token-exposure.md`).

**Context:**  
By default, Claude Code prompts the user for approval before executing bash commands, writing files, or performing other potentially impactful actions (e.g., "Allow Claude to run `python transform.py`? [y/n]"). In an interactive terminal, this is a useful safety check. However, in this system Claude Code runs headlessly behind a chat UI — there is no terminal for the user to approve prompts. Even if approval were relayed through the chat UI, the constant interruptions ("Can I run this command?", "Can I write this file?") would degrade the user experience significantly for a tool meant to operate autonomously on the user's behalf.

**Decision:**  
Invoke Claude Code with the `--dangerously-skip-permissions` flag, which bypasses all interactive permission prompts. Claude Code will execute commands, read/write files, and make API calls without asking for approval.

**Why this does not contradict the security model:**  
The system's security is not provided by Claude Code's permission prompts — it is provided by the Docker isolation layer (ADR-002) and read-only data mounts (ADR-003). Specifically:

- **Filesystem damage is bounded.** Project data directories are mounted read-only (`:ro`). Claude Code cannot modify, delete, or corrupt source data regardless of what commands it runs. The only writable areas are `/data/scratch/` (disposable output) and `/home/user/.claude/` (session data).
- **Blast radius is contained.** The container has no access to the host filesystem, other users' data, or any directory not explicitly mounted. A worst-case scenario (Claude Code runs `rm -rf /`) destroys only the container's ephemeral filesystem and the user's own scratch area.
- **Network scope is limited.** The container can reach the Bedrock API and NExtSEEK API, both of which require authentication. Post-POC, network egress should be restricted to only these endpoints (see SDS Section 4.3).

**Residual risks and mitigations:**

- **Credential exfiltration:** With no permission prompts, Claude Code could echo environment variables (containing `NEXTSEEK_PASSWORD`, `AWS_BEARER_TOKEN_BEDROCK`) to stdout or write them to a file in the scratch area without asking. **Mitigation:** CLAUDE.md explicitly instructs Claude Code to never log, print, or write credentials. The bridge layer could also filter stdout for known credential patterns before relaying to the chat UI.
- **Unintended API side effects:** Claude Code could make NExtSEEK API calls that modify data (POST/PUT/DELETE) without confirmation. **Mitigation:** If NExtSEEK supports read-only API tokens or role-based permissions, use a restricted token for researcher-level users. CLAUDE.md should instruct Claude Code to confirm destructive API operations with the user via conversation before executing.
- **Resource exhaustion:** Claude Code could run computationally expensive commands (e.g., processing a massive file) without asking. **Mitigation:** Docker resource limits (`--memory`, `--cpus`) can cap container resource usage. Not implemented in the POC, but straightforward to add.
- **Scratch area pollution:** Claude Code could fill the scratch directory with large or numerous files. **Mitigation:** Scratch directories can have disk quotas or be periodically cleaned. Low risk for the POC.

**Consequences:**  
- **Positive:** Seamless user experience — users give natural-language instructions and Claude Code executes without interruption, as intended for an autonomous assistant.
- **Positive:** Enables true headless operation. Without this flag, the system would need complex logic to relay permission prompts through the WebSocket bridge and back.
- **Negative:** The flag name ("dangerously") signals that this is a power-user setting. It is safe here *only because* the Docker isolation layer provides the actual security boundary. If the isolation model changes (e.g., running Claude Code directly on the host without Docker), this flag must be removed immediately.

---

## ADR-013: NExtSEEK Shared-Credential Sidecar Containment

**Status:** Accepted (2026-06-14, `nextseek-sidecar-build`)

**Context:**
The NExtSEEK plugin originally ran the `chat_nextseek` orchestrator **in-process inside each per-user agent container** (see ADR-008). To do its work, `chat_nextseek` needed the lab's shared institutional backend credentials — `GCP_API_KEY`, `NEO4J_*`, `MYSQL_*`, and `SESSION_DB_*`. Injecting those into the per-user agent container meant the in-container agent could read and exfiltrate institutional secrets that are **not** the user's own (unlike `NEXTSEEK_USERNAME`/`NEXTSEEK_PASSWORD`, which are the user's own NExtSEEK login and are fine to expose). This widened the credential-exfiltration surface documented in `known-issues/bedrock-token-exposure.md` beyond the Bedrock token alone.

**Decision:**
Move `chat_nextseek` execution out of the per-user agent container and behind a separate, high-trust hop, so the shared backend credentials never enter the agent container's runtime environment. The agent container's NExtSEEK env is reduced to only the user's own login (`NEXTSEEK_USERNAME`/`NEXTSEEK_PASSWORD`, translated to `API_USER`/`API_PASS` by the entrypoint) plus `NEXTSEEK_URL`. `src/dmac_assistant/containers.py::_build_environment` stops forwarding the 16 shared-credential keys (T10/U-1).

**As built (A-5 rewire, 2026-06-13/14):** the sidecar itself does **not** hold the shared backend credentials either. It is a thin HTTP forwarder to NExtSEEK's native granular assistant endpoints; it forwards the user's own NExtSEEK login per request as HTTP Basic auth and otherwise requires only `NEXTSEEK_BASE_URL` plus a staging directory (`sidecar/app/config.py`). The shared `GCP_API_KEY`/`NEO4J_*`/`MYSQL_*` credentials live **server-side on NExtSEEK**, which is where `chat_nextseek` actually runs. Per-request user credentials travel as Basic-auth arguments to the HTTP client and are never written into process env, so the earlier per-request `os.environ` mutation (and its cross-user-bleed race class) is removed, not merely mitigated.

**Relationship to existing ADRs (this is a pointer, not an amendment):**
- **ADR-005 (Secrets as Runtime Environment Variables Only)** is *extended*, not superseded: shared NExtSEEK backend secrets are removed from the agent container's runtime env entirely; ADR-005's invariant (secrets live only in ephemeral runtime env, never on disk or in images) still holds and now governs a much smaller in-agent secret set.
- **ADR-003 (Read-Only Data Mounts with Separate Scratch Area)** is reused: report/submission artifacts are downloaded from NExtSEEK over HTTP into per-user sidecar staging, swept into the user's scratch, then published to the output root via the existing post-turn copier — the same staging → scratch → publish path ADR-003 defines. (Delivery target is the current bridge output root `~/dmac-dev/output/<user_id>/…`; the separate Dropbox publish-path redesign is out of scope.)
- **ADR-006 (FastAPI WebSocket Bridge)** is reused: the agent↔sidecar hop rides a WebSocket contract analogous to the chat-UI↔bridge one.

**Consequences:**
- **Positive:** The in-container agent can no longer read or exfiltrate the shared institutional backend credentials — they are not present in its environment. Only the user's own NExtSEEK login is exposed, consistent with the NExtSEEK access-control model (ADR-009).
- **Positive:** A single high-trust boundary (the sidecar, and ultimately NExtSEEK) holds backend access; the per-user agent containers are de-credentialed for everything except the user's own identity.
- **Negative / scope limit:** This ADR contains the **NExtSEEK shared** credentials only. The Bedrock token (`AWS_BEARER_TOKEN_BEDROCK`) is **still present** in the agent container and remains the open production-blocker tracked in `known-issues/bedrock-token-exposure.md` and OI-3 (Option B Bedrock proxy sidecar) — a separate effort that reuses this sidecar's networking pattern.
- **Negative:** The NExtSEEK route now depends on NExtSEEK being reachable (the agent no longer carries a self-contained `chat_nextseek`); the sidecar must be running for any NExtSEEK granular op.

---

## ADR-014: NExtSEEK Plugin Runner as a Thin Client

**Status:** Accepted (2026-06-14, `nextseek-sidecar-build`)

**Context:**
The `nextseek` plugin runner (`_nextseek_runner.py`) originally imported `chat_nextseek` in-process at ~16 sites and executed the full orchestrator pipeline inside the agent container. That coupling is what forced the shared-credential exposure addressed in ADR-013 and bloated the agent image with `chat_nextseek` plus its heavy transitive dependencies (`torch`, `sentence-transformers`, ~2 GB). It also duplicated `chat_nextseek` across two runtimes (agent image vs. NExtSEEK's Django backend) — open item OI-2.

**Decision:**
Make the plugin runner a **thin network client** while keeping Claude Code's tool surface unchanged. The runner no longer imports `chat_nextseek`:
- The 7 granular ops (`entity`/`parse`/`graph`/`api-read`/`api-write`/`report`/`generate-submission`) are dispatched over a **WebSocket** to the sidecar (`_sidecar_client.py`); the sidecar (per ADR-013, as built) forwards them to NExtSEEK's native granular HTTP endpoints.
- `query`/`query_plan` are dispatched over **HTTP** to NExtSEEK's assistant viewset (async submit + progress polling) by the in-image viewset client (`runner_ns.py`).

The CC-visible 9-tool surface, the `SKILL.md` contract, and the bridge's UI frame contract are all unchanged — only the runner's *transport* changed (in-process import → network client).

**Relationship to existing ADRs (this is a pointer, not an amendment):**
- **ADR-008 (Plugin Architecture — CLI Tools with Markdown Documentation)** still holds: the plugin remains CLI-invocable scripts plus markdown docs; the in-container agent invokes the same tools and reads the same `SKILL.md`. Only the runner's implementation moved from an in-process library call to a network call.
- **ADR-006 (FastAPI WebSocket Bridge)** is reused for the agent↔sidecar granular-op transport.

**Consequences:**
- **Positive:** Removing `chat_nextseek` + `torch` from the agent image shrank it from ~4.95 GB to ~1.35 GB; the sidecar image (which no longer runs `chat_nextseek` after the A-5 rewire) is ~210 MB. (`vendor/chat_nextseek` is retained in the repo only for the bridge's host-side model-catalog default, not installed into either image.)
- **Positive:** Resolves OI-2: `chat_nextseek` no longer runs inside the agent container, so the agent-vs-NExtSEEK duplication is gone at the runtime level.
- **Positive:** Write-safety enforcement (L2) moved server-side (see the write-safety section of `SKILL.md`): the sidecar refuses `api-write` unless `confirmed_write` is exactly `True`, and NExtSEEK enforces its own server-side gate — the in-container agent cannot bypass either because neither runs in a process it controls.
- **Negative:** The runner now has a network dependency (sidecar WS + NExtSEEK HTTP) where it previously had a self-contained library; failures surface as typed transport/auth errors rather than in-process exceptions.
