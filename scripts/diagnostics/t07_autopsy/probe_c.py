"""Probe C: attach path with --input-format stream-json added.

Hypothesis (RC-8): claude needs event-driven stdin (--input-format stream-json)
to emit frames without waiting for stdin EOF, because docker-py's attach_socket
half-close does not propagate EOF to container stdin.
"""
from __future__ import annotations

import json
import os
import struct
import time

import docker

client = docker.from_env()

CMD = [
    "claude",
    "--print",
    "--input-format",
    "stream-json",
    "--output-format",
    "stream-json",
    "--verbose",
    "--dangerously-skip-permissions",
]

env = {
    "CLAUDE_CODE_USE_BEDROCK": "1",
    "AWS_REGION": os.environ["AWS_REGION"],
    "AWS_BEARER_TOKEN_BEDROCK": os.environ["AWS_BEARER_TOKEN_BEDROCK"],
    "NEXTSEEK_URL": os.environ.get("NEXTSEEK_URL", ""),
    "NEXTSEEK_USERNAME": "probe",
    "NEXTSEEK_PASSWORD": "probe",
}

container = client.containers.run(
    image="dmac-assistant:poc",
    command=CMD,
    environment=env,
    volumes={},
    working_dir="/home/user",
    labels={"dmac-probe": "c"},
    platform="linux/amd64",
    detach=True,
    stdin_open=True,
    tty=False,
    stdout=True,
    stderr=True,
)

try:
    time.sleep(0.2)
    raw = container.attach_socket(
        params={"stdin": 1, "stdout": 1, "stderr": 1, "stream": 1, "logs": 1}
    )
    sock = getattr(raw, "_sock", raw)

    # Event-shaped stdin per Claude Code stream-json input contract.
    # Anthropics docs: {"type":"user","message":{"role":"user","content":"..."}}\n
    line = json.dumps({
        "type": "user",
        "message": {"role": "user", "content": "reply OK"},
    }) + "\n"
    sock.sendall(line.encode())

    total_stdout = bytearray()
    total_stderr = bytearray()
    deadline = time.time() + 45
    sock.settimeout(5)
    frames_seen = 0
    while time.time() < deadline:
        try:
            header = b""
            while len(header) < 8:
                chunk = sock.recv(8 - len(header))
                if not chunk:
                    break
                header += chunk
            if len(header) < 8:
                break
            stream_id, size = header[0], struct.unpack(">I", header[4:8])[0]
            body = b""
            while len(body) < size:
                chunk = sock.recv(size - len(body))
                if not chunk:
                    break
                body += chunk
            if stream_id == 1:
                total_stdout.extend(body)
            elif stream_id == 2:
                total_stderr.extend(body)
            frames_seen += 1
            # After any stdout, give a short grace then break if looks complete
            if b'"type":"result"' in total_stdout:
                print("  saw result event, breaking")
                break
        except Exception as e:
            print(f"  recv break: {e!r}")
            break

    print(f"  frames_seen: {frames_seen}")
    print(f"  stdout bytes: {len(total_stdout)}")
    print(f"  stderr bytes: {len(total_stderr)}")
    if total_stdout:
        text = bytes(total_stdout).decode("utf-8", errors="replace")
        for l in text.splitlines()[:4]:
            print(f"    stdout: {l[:220]}")
    if total_stderr:
        print(f"  stderr head: {bytes(total_stderr[:400])!r}")
    container.reload()
    print(f"  container state: {container.status}")
finally:
    try:
        container.stop(timeout=2)
    except Exception:
        pass
    try:
        container.remove(force=True)
    except Exception:
        pass
