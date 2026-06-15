"""OI-3 T6 deterministic validator over a paid-acceptance run dir.

Run from the repo root:

    uv run python tools/oi3-acceptance/validate_acceptance.py tools/oi3-acceptance/runs/<ts>

This script reads the COMMITTED artifacts written by ``run_acceptance.py`` into a
``runs/<ts>/`` directory and exits 0 ONLY IF all seven success conditions of the
T6 task spec hold. It performs NO network, NO Docker, and NO Bedrock call — it is
a pure file-reading function, which is exactly why it can be exercised against
synthetic pass/fail fixtures with no money spent (the T6 verification path).

The seven conditions (from the locked plan, T6 "Success (non-gameable)"):

  1. ``ledger.json`` total ≤ $5.00.
  2. ``turn_transcript.jsonl`` last result ``is_error == false`` AND model reply
     length > 0.
  3. container-identity provenance — ``agent_env_scan.txt`` records a container
     id/name AND contains the RAW ``Config.Env`` block (not merely a summary).
  4. ``agent_env_scan.txt`` ``aws-token-hits: 0`` AND
     ``bearer-key-name-present: false``.
  5. proxy-traversal provenance — ``proxylog-bytes-after > proxylog-bytes-before``
     AND the per-run sentinel appears in ``proxy_log.txt`` AND the
     prompt-embedded sentinel appears in the model reply inside
     ``turn_transcript.jsonl``.
  6. ``proxy_log.txt`` ``token-hits: 0``.
  7. ``classifier_verdict.json`` parses.

The validator never trusts a single self-asserted summary line: condition 3
requires the literal RAW ``Config.Env`` JSON block (a marker the harness writes
ONLY when it actually inspected the container), and condition 5 cross-matches a
sentinel that the proxy logs AND that the MODEL echoes into its reply — neither
of which a hand-edited summary can fabricate without also forging the raw blocks.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

LEDGER_CAP_USD = 5.00

# Machine-readable lines the harness writes; the validator parses these literally.
_RE_AWS_TOKEN_HITS = re.compile(r"^aws-token-hits:\s*(\d+)\s*$", re.MULTILINE)
_RE_BEARER_KEY_PRESENT = re.compile(
    r"^bearer-key-name-present:\s*(true|false)\s*$", re.MULTILINE | re.IGNORECASE
)
_RE_PROXYLOG_BEFORE = re.compile(r"^proxylog-bytes-before:\s*(\d+)\s*$", re.MULTILINE)
_RE_PROXYLOG_AFTER = re.compile(r"^proxylog-bytes-after:\s*(\d+)\s*$", re.MULTILINE)
_RE_TOKEN_HITS = re.compile(r"^token-hits:\s*(\d+)\s*$", re.MULTILINE)
_RE_SENTINEL = re.compile(r"^run-sentinel:\s*(\S+)\s*$", re.MULTILINE)
_RE_CONTAINER_ID = re.compile(r"^container-id:\s*(\S+)\s*$", re.MULTILINE)
_RE_CONTAINER_NAME = re.compile(r"^container-name:\s*(\S+)\s*$", re.MULTILINE)
# The harness brackets the verbatim docker inspect Config.Env block with these
# markers so the validator can confirm the RAW block is present (defeats a
# summary-only fake). Everything between the markers is the literal JSON list.
_RAW_ENV_BEGIN = "----BEGIN RAW Config.Env----"
_RAW_ENV_END = "----END RAW Config.Env----"


@dataclass
class Condition:
    name: str
    passed: bool
    detail: str = ""


def _read_text(run_dir: Path, name: str) -> str | None:
    p = run_dir / name
    if not p.is_file():
        return None
    return p.read_text(encoding="utf-8")


def _extract_reply_text(transcript_text: str) -> tuple[bool, str]:
    """Parse the stream-json transcript; return (is_error, concatenated reply).

    The reply text is the concatenation of every ``assistant`` frame's
    ``message.content[].text`` PLUS the terminal ``result`` frame's ``result``
    field if it carries text — this mirrors how Claude Code ``--print`` emits a
    turn. ``is_error`` is read from the LAST ``result`` frame: ``is_error: true``
    if present, otherwise inferred from a non-"success" ``subtype``.
    """
    is_error = True  # fail-closed: no result frame ⇒ treat as error
    reply_parts: list[str] = []
    last_result: dict | None = None

    for raw_line in transcript_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            frame = json.loads(line)
        except json.JSONDecodeError:
            # A non-JSON line in the transcript is itself a corruption signal.
            continue
        if not isinstance(frame, dict):
            continue
        ftype = frame.get("type")
        if ftype == "assistant":
            content = (frame.get("message") or {}).get("content") or []
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        txt = block.get("text")
                        if isinstance(txt, str):
                            reply_parts.append(txt)
        elif ftype == "result":
            last_result = frame
            res = frame.get("result")
            if isinstance(res, str):
                reply_parts.append(res)

    if last_result is not None:
        if "is_error" in last_result:
            is_error = bool(last_result["is_error"])
        else:
            is_error = last_result.get("subtype") != "success"

    return is_error, "".join(reply_parts)


def _check_ledger(run_dir: Path) -> Condition:
    text = _read_text(run_dir, "ledger.json")
    if text is None:
        return Condition("ledger-total-within-cap", False, "ledger.json missing")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return Condition("ledger-total-within-cap", False, f"ledger.json invalid JSON: {exc}")
    total = data.get("total_usd")
    if not isinstance(total, (int, float)):
        return Condition(
            "ledger-total-within-cap", False, "ledger.json has no numeric 'total_usd'"
        )
    ok = total <= LEDGER_CAP_USD
    return Condition(
        "ledger-total-within-cap", ok,
        f"total_usd={total} cap=${LEDGER_CAP_USD:.2f}",
    )


def _check_transcript(run_dir: Path) -> tuple[Condition, str]:
    """Returns (condition-2, reply_text) so condition 5 can reuse the reply."""
    text = _read_text(run_dir, "turn_transcript.jsonl")
    if text is None:
        return Condition("turn-no-error-and-reply", False, "turn_transcript.jsonl missing"), ""
    is_error, reply = _extract_reply_text(text)
    ok = (not is_error) and len(reply) > 0
    detail = f"is_error={is_error} reply_len={len(reply)}"
    return Condition("turn-no-error-and-reply", ok, detail), reply


def _check_container_provenance(env_scan: str | None) -> Condition:
    if env_scan is None:
        return Condition("container-identity-provenance", False, "agent_env_scan.txt missing")
    cid = _RE_CONTAINER_ID.search(env_scan)
    cname = _RE_CONTAINER_NAME.search(env_scan)
    has_raw = _RAW_ENV_BEGIN in env_scan and _RAW_ENV_END in env_scan
    # The raw block must be NON-EMPTY between the markers (a wrong/empty container
    # scan would emit empty markers).
    raw_nonempty = False
    if has_raw:
        start = env_scan.index(_RAW_ENV_BEGIN) + len(_RAW_ENV_BEGIN)
        end = env_scan.index(_RAW_ENV_END)
        raw_nonempty = len(env_scan[start:end].strip()) > 0
    ok = bool(cid) and bool(cname) and has_raw and raw_nonempty
    detail = (
        f"container-id={'yes' if cid else 'MISSING'} "
        f"container-name={'yes' if cname else 'MISSING'} "
        f"raw-Config.Env-block={'present+nonempty' if (has_raw and raw_nonempty) else 'MISSING/empty'}"
    )
    return Condition("container-identity-provenance", ok, detail)


def _check_env_clean(env_scan: str | None) -> Condition:
    if env_scan is None:
        return Condition("agent-env-token-clean", False, "agent_env_scan.txt missing")
    hits_m = _RE_AWS_TOKEN_HITS.search(env_scan)
    bearer_m = _RE_BEARER_KEY_PRESENT.search(env_scan)
    if hits_m is None or bearer_m is None:
        return Condition(
            "agent-env-token-clean", False,
            f"missing machine lines (aws-token-hits={'yes' if hits_m else 'no'}, "
            f"bearer-key-name-present={'yes' if bearer_m else 'no'})",
        )
    hits = int(hits_m.group(1))
    bearer_present = bearer_m.group(1).lower() == "true"
    ok = hits == 0 and not bearer_present
    return Condition(
        "agent-env-token-clean", ok,
        f"aws-token-hits={hits} bearer-key-name-present={bearer_present}",
    )


def _check_proxy_traversal(run_dir: Path, env_scan: str | None, reply: str) -> Condition:
    proxy_log = _read_text(run_dir, "proxy_log.txt")
    if proxy_log is None:
        return Condition("proxy-traversal-provenance", False, "proxy_log.txt missing")
    before_m = _RE_PROXYLOG_BEFORE.search(proxy_log)
    after_m = _RE_PROXYLOG_AFTER.search(proxy_log)
    if before_m is None or after_m is None:
        return Condition(
            "proxy-traversal-provenance", False,
            f"missing byte-count lines (before={'yes' if before_m else 'no'}, "
            f"after={'yes' if after_m else 'no'})",
        )
    before = int(before_m.group(1))
    after = int(after_m.group(1))
    grew = after > before

    # The per-run sentinel is recorded in agent_env_scan.txt (the harness's
    # canonical "what sentinel did THIS run use" record). It must appear in the
    # proxy log AND be echoed by the model into the transcript reply.
    sentinel = None
    if env_scan is not None:
        sm = _RE_SENTINEL.search(env_scan)
        if sm:
            sentinel = sm.group(1)
    if not sentinel:
        return Condition(
            "proxy-traversal-provenance", False,
            "no 'run-sentinel:' line in agent_env_scan.txt (cannot cross-match)",
        )
    sentinel_in_proxy = sentinel in proxy_log
    sentinel_in_reply = sentinel in reply

    ok = grew and sentinel_in_proxy and sentinel_in_reply
    detail = (
        f"proxylog grew={grew} ({before}->{after}); "
        f"sentinel-in-proxy_log={sentinel_in_proxy}; "
        f"sentinel-in-model-reply={sentinel_in_reply}"
    )
    return Condition("proxy-traversal-provenance", ok, detail)


def _check_proxy_token_clean(run_dir: Path) -> Condition:
    proxy_log = _read_text(run_dir, "proxy_log.txt")
    if proxy_log is None:
        return Condition("proxy-log-token-clean", False, "proxy_log.txt missing")
    m = _RE_TOKEN_HITS.search(proxy_log)
    if m is None:
        return Condition("proxy-log-token-clean", False, "no 'token-hits:' line")
    hits = int(m.group(1))
    return Condition("proxy-log-token-clean", hits == 0, f"token-hits={hits}")


def _check_classifier_verdict(run_dir: Path) -> Condition:
    text = _read_text(run_dir, "classifier_verdict.json")
    if text is None:
        return Condition("classifier-verdict-parses", False, "classifier_verdict.json missing")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return Condition("classifier-verdict-parses", False, f"invalid JSON: {exc}")
    if not isinstance(data, dict) or "classifier_blocked_proxy" not in data:
        return Condition(
            "classifier-verdict-parses", False,
            "missing 'classifier_blocked_proxy' key",
        )
    return Condition(
        "classifier-verdict-parses", True,
        f"classifier_blocked_proxy={data['classifier_blocked_proxy']}",
    )


def validate(run_dir: Path) -> list[Condition]:
    """Run all seven conditions over ``run_dir``; return the Condition list."""
    env_scan = _read_text(run_dir, "agent_env_scan.txt")
    cond1 = _check_ledger(run_dir)
    cond2, reply = _check_transcript(run_dir)
    cond3 = _check_container_provenance(env_scan)
    cond4 = _check_env_clean(env_scan)
    cond5 = _check_proxy_traversal(run_dir, env_scan, reply)
    cond6 = _check_proxy_token_clean(run_dir)
    cond7 = _check_classifier_verdict(run_dir)
    return [cond1, cond2, cond3, cond4, cond5, cond6, cond7]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: validate_acceptance.py <run_dir>", file=sys.stderr)
        return 2
    run_dir = Path(args[0])
    if not run_dir.is_dir():
        print(f"FAIL: run dir does not exist: {run_dir}", file=sys.stderr)
        return 2

    conditions = validate(run_dir)
    print(f"validate_acceptance: run_dir={run_dir}")
    print("-" * 72)
    for i, c in enumerate(conditions, start=1):
        status = "PASS" if c.passed else "FAIL"
        print(f"[{i}] {status}  {c.name}  — {c.detail}")
    print("-" * 72)

    failures = [c for c in conditions if not c.passed]
    if failures:
        print(f"RESULT: FAIL — {len(failures)} of {len(conditions)} condition(s) failed")
        return 1
    print(f"RESULT: PASS — all {len(conditions)} conditions met")
    return 0


if __name__ == "__main__":
    sys.exit(main())
