# T07 Live-Gate Autopsy — Probe Scripts

Reproduction harness for the 2026-04-24 `/ultraplan autopsy` investigation of why
the DMAC bridge's live E2E test (T07) observed clean stdout EOF with zero
stream-json frames from the `dmac-assistant:poc` container. See
`.claude/plans/dmac-bridge-resume-2026-04-21.md` § Autopsy Log for the full
reasoning.

## Preconditions

- Docker daemon running.
- `dmac-assistant:poc` image built (`make image-build`).
- `.env` with `AWS_REGION`, `AWS_BEARER_TOKEN_BEDROCK`, `NEXTSEEK_URL`.
- Each probe must be invoked with the env loaded:
  `set -a && . ./.env && set +a && uv run python scripts/diagnostics/t07_autopsy/probe_X.py`

## Probe A — shell-only baseline

Not a script; ran as a one-liner. Mirrors the bridge's exact CMD shape but
delivers stdin via `docker run -i` (NOT docker-py attach):

```
printf '{"type":"user","message":{"role":"user","content":"reply OK"}}\n' \
| docker run --rm -i --platform linux/amd64 \
    -e CLAUDE_CODE_USE_BEDROCK=1 -e AWS_REGION -e AWS_BEARER_TOKEN_BEDROCK \
    -e NEXTSEEK_URL -e NEXTSEEK_USERNAME=probe -e NEXTSEEK_PASSWORD=probe \
    -w /home/user dmac-assistant:poc \
    claude --print --output-format stream-json --verbose --dangerously-skip-permissions
```

**Result**: exit 0, 3598 stdout bytes, full `system.init` + assistant +
`result` events. Bedrock call succeeded against real Sonnet 4.5. Proves the
CMD shape and Bedrock env are fine **when stdin EOF is delivered cleanly**.

## Probe B — docker-py attach, no `--input-format`

Two variants (`logs=0` and `logs=1`) of the bridge's exact attach sequence:
`run(detach=True, stdin_open=True, tty=False)` → `attach_socket(stdin,
stdout, stderr, stream)` → `sendall` JSON frame → `shutdown(SHUT_WR)` →
read multiplexed frames with the same 8-byte stdcopy demux the bridge uses.

**Result**: both variants 0 stdout bytes, 0 stderr bytes, container still
running after 30s. `sock.shutdown(SHUT_WR)` on a docker-py hijacked attach
socket does NOT propagate EOF to the container's stdin. `--print` blocks
forever on the stdin read.

## Probe C — docker-py attach with `--input-format stream-json`

Same attach sequence as Probe B but with `--input-format stream-json` added
to the CMD. Sends one event-shaped line; does not half-close (not needed in
streaming mode).

**Result**: 0 stdout bytes, 0 stderr bytes, container still running. This
is the key surprise — even with the correct CMD, the attach_socket read
path produces nothing against Docker 29.4.0. Combined with Probe D below,
this proves the attach hijacked-stream read path is broken independently
of CMD shape.

## Probe D — split I/O: attach for stdin, `container.logs()` for stdout

Two CMD variants (`single-print`, `streaming-input`). Writes stdin via
attach_socket (no shutdown); reads stdout via `container.logs(stream=True,
follow=True)`.

**Result**:
- `single-print` (no `--input-format`): 0 bytes (still blocked on EOF).
- `streaming-input` (with `--input-format stream-json`): **4782 bytes**,
  proper stream-json including `system.init`, real session_id, full
  assistant response, `result` event. Expected framing.

This is the conjunction of both fixes required. Without either one,
production path breaks.

## Summary — two distinct bugs

| Bug | Fix |
|---|---|
| `--input-format stream-json` missing from `_BASE_COMMAND` in `src/dmac_assistant/containers.py` | Append the flag |
| `attach_socket` read-side silent on Docker 29.4.0 regardless of `logs=0/1` | Switch to `container.logs(stream=True, follow=True)` for reads; keep `attach_socket` only for stdin writes |

Remediation shape and affected specs are enumerated in the plan's
Autopsy Log entry for 2026-04-24.
