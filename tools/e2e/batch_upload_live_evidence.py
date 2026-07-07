"""Pure evidence/verdict logic for the T10 live paid batch-upload E2E ($0, hermetic).

Split from the live driver (``run_batch_upload_live_e2e.py``) so ALL verdict + cost logic is
unit-testable without spending a cent. Mirrors the NExtSEEK ``step7d`` harness discipline
(owner directive 2026-07-07 — that harness is a rigor reference, not a target):

* authoritative-cost-first with ``cost_source`` provenance + an estimate fallback that NEVER
  overrides a real >0 figure;
* invocation proof parsed from the transcript (the agent must actually Bash-exec the shim), with
  basename-exact tokenization so ``nextseek-api`` never matches ``nextseek-api-write`` and
  ``command -v <shim>`` / ``echo <shim>`` argument-only mentions do not count;
* a verdict taxonomy that separates HARD failures (red) from GREEN-but-flagged review notes so
  LLM route nondeterminism does not manufacture false reds.

The WS frame contract this consumes (emitted by ``src/dmac_assistant/ws.py``):
  route_decided  {type, route, model_class}
  tool_use       {type, tool, input, id}          # tool=="Bash", input.command names a shim
  assistant_message {type, content}
  session_ended  {type, session_id, usage, total_cost_usd}   # total_cost_usd = CC authoritative

SCOPE CAVEATS (honest limits of what the WS surface can prove — documented, not bugs):
* ``tool_use`` frames are the agent's tool-call REQUESTS; the bridge emits no paired
  ``tool_result``/exit-status frame, so a shim that was auto-mode-denied or exited non-zero still
  counts as "invoked" (M4). Deep artifact correctness — that the delivered workbook actually
  VALIDATES ``valid==true`` — is the merge gate T9.5's job (assert (iv)), not T10's; T10 green means
  "a real paid turn routed container_cc and genuinely ran the batch-upload deliverable path", the
  paid superset "see it work", NOT a second correctness oracle (M6).
* Fresh-session over the WS is presence-only for a single turn (M5); the driver GUARANTEES freshness
  structurally by opening a new ``/ws/chat`` connection with no session id and never passing
  ``--resume``. The presence check is a backstop, not the guarantee.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shlex
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Constants

# The batch-upload shims the agent is expected to Bash-exec (basename-exact match set).
BATCH_UPLOAD_SHIMS: tuple[str, ...] = (
    "nextseek-project-resolve",
    "nextseek-sampletype-attrs",
    "nextseek-sample-search",
    "nextseek-assay-resolve",
    "nextseek-build-payload",
    "nextseek-validate-upload",
)
# The load-bearing terminal shim: the delivered-workbook validate. A turn that never reaches
# this did not exercise the skill's core deliverable (build + validate a workbook).
VALIDATE_SHIM = "nextseek-validate-upload"

EXPECTED_ROUTE = "container_cc"

# Published Opus-4.8 Bedrock rates (USD per token) for the timeout ESTIMATE fallback ONLY.
# Authoritative cost is Claude Code's own ``total_cost_usd``; this table prices a killed turn's
# aggregate usage when no result frame arrived. Mirrors step7d ``_OPUS48_RATES``.
PUBLISHED_RATE_TABLE_VERSION = "2026-07-opus48-bedrock"
_OPUS48_RATES = {
    "input": 5.0 / 1_000_000,
    "output": 25.0 / 1_000_000,
    "cache_write": 6.25 / 1_000_000,  # 5-minute cache write = 1.25x input
    "cache_read": 0.50 / 1_000_000,  # cache read = 0.1x input
}

COST_SOURCE_AUTHORITATIVE = "claude_code_result"
COST_SOURCE_ESTIMATE = "usage_estimate_on_timeout"
COST_SOURCE_NONE = "unavailable"

# Command operators only ( ; | & families ) are treated as punctuation for lexing — NOT ( ) < >.
# Excluding parens/redirects is deliberate: it prevents a shim dequoted out of a NON-executing
# context — a single-quoted string, a `#` comment, an escaped `\$(...)`, a heredoc body, or a
# `print('shim')` — from being exposed as a bare segment head (fix CRITICAL-1 / re-vet round 2).
# Quote- and comment-awareness come from shlex itself (posix + commenters='#').
_LEX_PUNCTUATION = ";|&"
_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# Wrapper heads that simply delegate to a following command word (strip to reach the real head).
# Shell KEYWORDS (then/do/else) are deliberately NOT wrappers: a bare `then <shim>` is a bash
# syntax error — nothing executes — so stripping them forged invocations from non-executing
# input (fix MEDIUM-1 / re-vet round 3).
_SIMPLE_WRAPPERS = frozenset({"env", "nohup", "sudo", "exec", "time", "stdbuf", "nice"})
# A combined short-flag ending in c (bash -lc / sh -ec) — the NEXT token is the inner command.
_INNER_C_FLAG = re.compile(r"^-[A-Za-z]*c$")
_MAX_RECURSION = 4


# ---------------------------------------------------------------------------
# Cost


@dataclass
class CostResult:
    cost_usd: float
    cost_source: str
    usage: dict[str, Any]
    has_result_frame: bool


def session_ended_frames(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [frame for frame in frames if frame.get("type") == "session_ended"]


def _session_ended(frames: list[dict[str, Any]]) -> dict[str, Any] | None:
    # The TERMINAL session_ended is authoritative — a decoy cheap result frame emitted
    # before the real one must not mask the true cost/session id (fix M2). The verifier
    # additionally flags a transcript carrying more than one (see session_ended_frames).
    ended = session_ended_frames(frames)
    return ended[-1] if ended else None


def estimate_cost_from_usage(usage: dict[str, Any]) -> float:
    """Price an aggregate usage block at published Opus-4.8 rates (fallback only)."""
    inp = int(usage.get("input_tokens", 0) or 0)
    out = int(usage.get("output_tokens", 0) or 0)
    cache_write = int(usage.get("cache_creation_input_tokens", 0) or 0)
    cache_read = int(usage.get("cache_read_input_tokens", 0) or 0)
    return (
        inp * _OPUS48_RATES["input"]
        + out * _OPUS48_RATES["output"]
        + cache_write * _OPUS48_RATES["cache_write"]
        + cache_read * _OPUS48_RATES["cache_read"]
    )


def extract_cost(frames: list[dict[str, Any]]) -> CostResult:
    """Authoritative-cost-first cost extraction with provenance.

    * ``session_ended.total_cost_usd`` present and numeric -> authoritative (even 0.0, which the
      verdict layer then flags as a hard failure because a real CC turn always spends).
    * else ``session_ended.usage`` present -> estimate at published rates (the killed-turn path).
    * else -> 0.0, ``unavailable``.
    The estimate NEVER overrides a real total_cost_usd.
    """
    frame = _session_ended(frames)
    usage = {}
    if frame is not None and isinstance(frame.get("usage"), dict):
        usage = frame["usage"]
    if frame is not None:
        total = frame.get("total_cost_usd")
        if isinstance(total, (int, float)) and not isinstance(total, bool):
            return CostResult(float(total), COST_SOURCE_AUTHORITATIVE, usage, True)
    if usage:
        return CostResult(estimate_cost_from_usage(usage), COST_SOURCE_ESTIMATE, usage, False)
    return CostResult(0.0, COST_SOURCE_NONE, {}, False)


# ---------------------------------------------------------------------------
# Route + reply + fresh session


def classify_route(frames: list[dict[str, Any]]) -> str | None:
    for frame in frames:
        if frame.get("type") == "route_decided":
            route = frame.get("route")
            return route if isinstance(route, str) else None
    return None


def extract_reply(frames: list[dict[str, Any]]) -> str:
    parts = [
        frame["content"]
        for frame in frames
        if frame.get("type") == "assistant_message" and isinstance(frame.get("content"), str)
    ]
    return "\n".join(parts).strip()


def detect_error(frames: list[dict[str, Any]]) -> bool:
    """Transcript-only error detection: an explicit ``error`` frame, or no ``session_ended`` at all
    (a turn that never terminated cleanly — e.g. a killed/timed-out turn)."""
    if any(frame.get("type") == "error" for frame in frames):
        return True
    return _session_ended(frames) is None


def session_id_of(frames: list[dict[str, Any]]) -> str | None:
    frame = _session_ended(frames)
    if frame is None:
        return None
    sid = frame.get("session_id")
    return sid if isinstance(sid, str) and sid else None


def assert_fresh_sessions(session_ids: list[str | None]) -> list[str]:
    """Return a list of fresh-session violations (empty == all fresh).

    Fresh means every turn has a non-null session id AND all ids are distinct (no warm/resumed
    session silently riding another turn).
    """
    violations: list[str] = []
    seen: set[str] = set()
    for idx, sid in enumerate(session_ids):
        if not sid:
            violations.append(f"turn {idx}: missing session id")
            continue
        if sid in seen:
            violations.append(f"turn {idx}: duplicate session id {sid!r} (not a fresh session)")
        seen.add(sid)
    return violations


# ---------------------------------------------------------------------------
# Invocation proof


@dataclass
class Invocation:
    shim: str
    command_excerpt: str
    frame_id: str | None


def _lex(command: str) -> list[str] | None:
    """Shell-aware lex: quotes honored, ``#`` comments stripped, only ``; | &`` operators become
    their own tokens. Returns None on a lexer error (unbalanced quote) — a syntax-error command
    executes nothing, so we conservatively detect no invocation."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=_LEX_PUNCTUATION)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return None


def _effective_tokens(seg: list[str]) -> list[str]:
    """Strip leading subshell/brace openers, ``VAR=val`` assignments, and wrapper prefixes
    (env/nohup/sudo/exec/time/stdbuf/nice, ``timeout <dur>``, ``uv run``) to reach the real
    command word + its args. ``uv`` strips ONLY when followed by ``run`` — a bare
    ``uv <shim>`` errors and executes nothing (fix MEDIUM-1 / re-vet round 3)."""
    toks = list(seg)
    while toks and toks[0] in {"(", "{"}:
        toks = toks[1:]
    # A GLUED subshell opener: bash runs `(cmd ...)` as a subshell with no space required after
    # `(`. `((...))` is arithmetic (no command word executes) so it is deliberately NOT stripped;
    # exactly ONE trailing `)` is dropped so a one-token `(shim)` still basename-matches while a
    # malformed `(shim))` (bash syntax error) stays a miss.
    if toks and toks[0].startswith("(") and not toks[0].startswith("(("):
        head = toks[0][1:]
        if head.endswith(")"):
            head = head[:-1]
        toks[0] = head
    i = 0
    while i < len(toks):
        tok = toks[i]
        base = os.path.basename(tok)
        if _ENV_ASSIGN.match(tok) and "/" not in tok.split("=", 1)[0]:
            i += 1
        elif base in _SIMPLE_WRAPPERS:
            i += 1
        elif base == "timeout":
            i += 1
            while i < len(toks) and toks[i].startswith("-"):
                i += 1
            if i < len(toks):  # the DURATION argument
                i += 1
        elif base == "uv" and i + 1 < len(toks) and toks[i + 1] == "run":
            i += 2
            while i < len(toks) and toks[i].startswith("-"):
                i += 1
        else:
            break
    return toks[i:]


def _heads_from_tokens(toks: list[str], shims: set[str], depth: int) -> list[str]:
    """Classify one segment's effective tokens into shim invocations."""
    if not toks or depth > _MAX_RECURSION:
        return []
    base = os.path.basename(toks[0])
    if base in shims:
        return [base]
    if base in {"bash", "sh"}:  # bash -c/-lc "<inner>" — the inner string is a real command
        for j in range(1, len(toks)):
            if toks[j] == "-c" or _INNER_C_FLAG.match(toks[j]):
                return _command_heads(toks[j + 1], shims, depth + 1) if j + 1 < len(toks) else []
        return []
    if base == "eval":  # eval joins its args and runs the result
        return _command_heads(" ".join(toks[1:]), shims, depth + 1)
    if base == "xargs":  # xargs [flags] <shim> — first non-flag token is the command word
        for tok in toks[1:]:
            if tok.startswith("-"):
                continue
            b = os.path.basename(tok)
            return [b] if b in shims else []
    return []


def _split_logical_lines(command: str) -> list[str]:
    """Split ``command`` on UNQUOTED, UNESCAPED newlines — in bash a newline separates commands
    exactly like ``;`` (fix HIGH-1 / re-vet round 3: multi-line Bash blocks previously collapsed
    into ONE segment and only the first word was classified, so a genuine multi-line turn was
    scored RED).

    Quote/comment/escape awareness so NO forgery vector re-opens:
    * a newline inside a quoted string does NOT split (``echo "a\\n<shim>"`` stays one argument);
    * a backslash-escaped newline is a line continuation, not a separator;
    * ``#`` at a word start opens a comment through end-of-line (quote chars inside a comment
      carry no quoting power, so an apostrophe in a comment cannot mask later real lines);
    * after an unquoted ``<<`` the REMAINDER is left unsplit: heredoc bodies do not execute, so
      their lines must never be exposed as command positions — the tail degrades to the old
      single-segment lexing (a safe false-negative for any post-heredoc line);
    * a lone ``\\r`` is NOT a separator (bash treats it as an ordinary word char — splitting on
      it would forge invocations); the ``\\r`` of a CRLF pair is consumed with the split.
    """
    lines: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    escaped = False
    in_comment = False
    frozen = False  # unquoted << seen — stop splitting so heredoc bodies never become heads
    prev = ""  # previous unquoted, unescaped char (word-start detection for `#` and `<<`)
    for ch in command:
        if frozen:
            buf.append(ch)
            continue
        if in_comment:
            if ch == "\n":
                in_comment = False
                lines.append("".join(buf))
                buf = []
                prev = ""
            else:
                buf.append(ch)
            continue
        if escaped:
            buf.append(ch)
            escaped = False
            prev = ""
            continue
        if ch == "\\" and quote != "'":
            buf.append(ch)
            escaped = True
            prev = ""
            continue
        if quote is not None:
            if ch == quote:
                quote = None
                prev = ch
            buf.append(ch)
            continue
        if ch == "\n":
            if buf and buf[-1] == "\r":  # CRLF: the \r belongs to the break, not the line
                buf.pop()
            lines.append("".join(buf))
            buf = []
            prev = ""
            continue
        if ch in "'\"":
            quote = ch
            buf.append(ch)
            prev = ""
            continue
        if ch == "#" and (prev == "" or prev in " \t;|&("):
            in_comment = True
            buf.append(ch)
            continue
        if ch == "<" and prev == "<":
            frozen = True
        buf.append(ch)
        prev = ch
    lines.append("".join(buf))
    return lines


def _command_heads(command: str, shims: set[str], depth: int = 0) -> list[str]:
    """Return every shim basename genuinely INVOKED as a command word in ``command``.

    The command is first split into logical lines on unquoted, unescaped newlines (a bash newline
    separates commands exactly like ``;`` — fix HIGH-1 / re-vet round 3); each line is then
    segmented on LEXED operator tokens only, so an operator or newline inside a quoted literal
    never splits, and a shim appearing in a single-quoted string, a ``#`` comment, an escaped
    ``\\$(...)``, a heredoc, or a ``print('shim')`` is NOT counted (it does not execute). Handles
    env/wrapper prefixes, ``timeout``/``uv run``, ``bash -c``/``eval`` inner commands, and
    ``xargs`` — all recursively. basename-exact, so ``nextseek-api`` never matches
    ``nextseek-api-write``. A line that fails to lex (unbalanced quote) contributes nothing —
    conservative: bash executes the complete prior commands but nothing from the malformed one.
    Conservative: a genuine ``$(shim)`` substitution is NOT detected (a safe false-negative — a
    real turn calls the shim directly per SKILL.md), because detecting it would re-open the
    forgery vector."""
    if depth > _MAX_RECURSION:
        return []
    found: list[str] = []
    for line in _split_logical_lines(command):
        tokens = _lex(line)
        if tokens is None:
            continue
        segment: list[str] = []
        for tok in tokens:
            if tok and set(tok) <= set(_LEX_PUNCTUATION):  # an operator run (&&, ||, ;, ...)
                if segment:
                    found.extend(_heads_from_tokens(_effective_tokens(segment), shims, depth))
                    segment = []
            else:
                segment.append(tok)
        if segment:
            found.extend(_heads_from_tokens(_effective_tokens(segment), shims, depth))
    return found


def extract_tool_invocations(
    frames: list[dict[str, Any]], shims: tuple[str, ...] = BATCH_UPLOAD_SHIMS
) -> list[Invocation]:
    """Parse tool_use Bash frames into genuine shim invocations (basename-exact, execution-position
    only; robust against quoted-operator forgery and command substitutions)."""
    shim_set = set(shims)
    found: list[Invocation] = []
    for frame in frames:
        if frame.get("type") != "tool_use" or frame.get("tool") != "Bash":
            continue
        command = (frame.get("input") or {}).get("command")
        if not isinstance(command, str):
            continue
        fid = frame.get("id") if isinstance(frame.get("id"), str) else None
        for shim in _command_heads(command, shim_set):
            found.append(Invocation(shim=shim, command_excerpt=command[:500], frame_id=fid))
    return found


# ---------------------------------------------------------------------------
# Verdict


@dataclass
class TurnRow:
    query: str
    route: str | None
    expected_route: str
    cc_session_id: str | None
    is_error: bool
    cost_usd: float
    cost_source: str
    invoked_shims: list[str]
    validate_invoked: bool
    answer_excerpt: str
    problems: list[str] = field(default_factory=list)
    review_notes: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return bool(self.review_notes) and not self.problems

    @property
    def passed(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "route": self.route,
            "expected_route": self.expected_route,
            "cc_session_id": self.cc_session_id,
            "is_error": self.is_error,
            "cost_usd": self.cost_usd,
            "cost_source": self.cost_source,
            "invoked_shims": self.invoked_shims,
            "validate_invoked": self.validate_invoked,
            "answer_excerpt": self.answer_excerpt,
            "passed": self.passed,
            "needs_review": self.needs_review,
            "problems": self.problems,
            "review_notes": self.review_notes,
        }


def evaluate_turn(
    *,
    query: str,
    frames: list[dict[str, Any]],
    is_error: bool,
    expected_route: str = EXPECTED_ROUTE,
) -> TurnRow:
    """Build a TurnRow verdict from the captured WS frames.

    HARD failures (problems -> red): transport/agent error; cost <= 0 (a real CC turn always
    spends a Bedrock turn); empty reply; the validate shim never invoked (core deliverable did
    not run); route != expected. GREEN-but-flagged review notes: an expected shim other than
    validate was skipped though validate ran (the agent took a valid shorter path).
    """
    route = classify_route(frames)
    cost = extract_cost(frames)
    invocations = extract_tool_invocations(frames)
    invoked_shims = sorted({inv.shim for inv in invocations})
    validate_invoked = VALIDATE_SHIM in invoked_shims
    reply = extract_reply(frames)
    row = TurnRow(
        query=query,
        route=route,
        expected_route=expected_route,
        cc_session_id=session_id_of(frames),
        is_error=is_error,
        cost_usd=cost.cost_usd,
        cost_source=cost.cost_source,
        invoked_shims=invoked_shims,
        validate_invoked=validate_invoked,
        answer_excerpt=reply[:1000],
    )
    if is_error:
        row.problems.append("turn errored (transport/agent error or timeout)")
    if route != expected_route:
        row.problems.append(f"route {route!r} != expected {expected_route!r}")
    if cost.cost_usd <= 0:
        row.problems.append(
            f"cost_usd={cost.cost_usd} <= 0 (a real CC turn always spends a Bedrock turn; "
            f"cost_source={cost.cost_source})"
        )
    if not reply:
        row.problems.append("empty agent reply")
    if not validate_invoked:
        row.problems.append(
            f"{VALIDATE_SHIM} was never invoked — the batch-upload deliverable (build+validate) "
            "did not run"
        )
    else:
        skipped = [s for s in BATCH_UPLOAD_SHIMS if s != VALIDATE_SHIM and s not in invoked_shims]
        if skipped:
            row.review_notes.append(
                "validate ran but these expected shims were not observed: " + ", ".join(skipped)
            )
    return row


def build_summary(
    row: TurnRow,
    *,
    ledger_total_usd: float,
    cap_usd: float,
    aborted_on_budget: bool,
    rate_table_version: str = PUBLISHED_RATE_TABLE_VERSION,
) -> dict[str, Any]:
    """Top-level per-turn summary (step7d ``per_op_summary`` analog)."""
    fresh_violations = assert_fresh_sessions([row.cc_session_id])
    within_cap = ledger_total_usd <= cap_usd
    return {
        "all_pass": (
            row.passed and within_cap and not aborted_on_budget and not fresh_violations
        ),
        "aborted_on_budget": aborted_on_budget,
        "fresh_session_violations": fresh_violations,
        "total_cost_usd": ledger_total_usd,
        "cap_usd": cap_usd,
        "within_cap": ledger_total_usd <= cap_usd,
        "rate_table_version": rate_table_version,
        "expected_route": row.expected_route,
        "turn": row.to_dict(),
    }


# ---------------------------------------------------------------------------
# Evidence bundle (kept here, covered, so the driver's only uncovered surface is the
# closed set of live-orchestration functions the plan permits to carry ``# pragma: no cover``)


def render_summary_txt(
    summary: dict[str, Any], *, reproduce_cmd: str, evidence_dir_name: str
) -> str:
    turn = summary["turn"]
    lines = [
        "T10 LIVE PAID batch-upload E2E — SUMMARY",
        f"bundle: evidence/batch-upload-e2e/{evidence_dir_name}/",
        "",
        f"all_pass:            {summary['all_pass']}",
        f"route:               {turn['route']} (expected {turn['expected_route']})",
        f"validate_invoked:    {turn['validate_invoked']}",
        f"invoked_shims:       {', '.join(turn['invoked_shims']) or '(none)'}",
        f"is_error:            {turn['is_error']}",
        f"needs_review:        {turn['needs_review']}",
        f"aborted_on_budget:   {summary['aborted_on_budget']}",
        f"fresh_violations:    {summary['fresh_session_violations'] or 'none'}",
        "",
        "--- cost ---",
        f"total_cost_usd:      {summary['total_cost_usd']:.6f}",
        f"cost_source:         {turn['cost_source']}",
        f"cap_usd:             {summary['cap_usd']:.2f}",
        f"within_cap:          {summary['within_cap']}",
        f"rate_table_version:  {summary['rate_table_version']}",
        "",
    ]
    if turn["problems"]:
        lines.append("PROBLEMS (hard failures):")
        lines += [f"  - {p}" for p in turn["problems"]]
    if turn["review_notes"]:
        lines.append("REVIEW NOTES (green-but-flagged):")
        lines += [f"  - {n}" for n in turn["review_notes"]]
    lines += ["", "--- reproduce ---", reproduce_cmd, ""]
    return "\n".join(lines)


def write_evidence_bundle(
    out_dir: pathlib.Path,
    *,
    query: str,
    frames: list[dict[str, Any]],
    cap_usd: float,
    ledger_total_usd: float,
    transport_error: str | None,
    aborted_on_budget: bool,
    reproduce_cmd: str,
    extra_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write the full evidence bundle and return the summary.

    Files: ``live_e2e_transcript.json`` (all WS frames + meta), ``per_turn_summary.json`` (the
    verdict), ``SUMMARY.txt`` (human-readable + reproduce command). The ledger JSONL is written
    separately by the driver via ``SpendLedger.save``.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    is_error = bool(transport_error) or detect_error(frames)
    row = evaluate_turn(query=query, frames=frames, is_error=is_error)
    summary = build_summary(
        row,
        ledger_total_usd=ledger_total_usd,
        cap_usd=cap_usd,
        aborted_on_budget=aborted_on_budget,
    )
    meta = {"query": query, "cap_usd": cap_usd, "transport_error": transport_error}
    if extra_meta:
        meta.update(extra_meta)
    (out_dir / "live_e2e_transcript.json").write_text(
        json.dumps({"meta": meta, "frames": frames}, indent=2, sort_keys=True), encoding="utf-8"
    )
    (out_dir / "per_turn_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    (out_dir / "SUMMARY.txt").write_text(
        render_summary_txt(summary, reproduce_cmd=reproduce_cmd, evidence_dir_name=out_dir.name),
        encoding="utf-8",
    )
    return summary
