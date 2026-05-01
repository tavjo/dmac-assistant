"""Probe B: reproduce the bridge's docker-py attach sequence exactly.

If this produces 'no frames' while Probe A (docker run -i) produced ~3.6KB,
the bug is in the attach path, not the CMD.
"""
from __future__ import annotations

import os
import struct
import time

import docker

client = docker.from_env()

CMD = [
    "claude",
    "--print",
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


def run_variant(label: str, *, logs: int) -> None:
    print(f"\n=== {label} (attach logs={logs}) ===")
    container = client.containers.run(
        image="dmac-assistant:poc",
        command=CMD,
        environment=env,
        volumes={},
        working_dir="/home/user",
        labels={"dmac-probe": "b"},
        platform="linux/amd64",
        detach=True,
        stdin_open=True,
        tty=False,
        stdout=True,
        stderr=True,
    )
    try:
        time.sleep(0.1)  # let container boot a tick; still racing
        raw = container.attach_socket(
            params={"stdin": 1, "stdout": 1, "stderr": 1, "stream": 1, "logs": logs}
        )
        sock = getattr(raw, "_sock", raw)
        payload = b'{"type":"user","message":{"role":"user","content":"reply OK"}}\n'
        sock.sendall(payload)
        sock.shutdown(1)  # half-close write

        total_stdout = bytearray()
        total_stderr = bytearray()
        deadline = time.time() + 30
        sock.settimeout(5)
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
            except Exception as e:
                print(f"  recv break: {e!r}")
                break
        print(f"  stdout bytes: {len(total_stdout)}")
        print(f"  stderr bytes: {len(total_stderr)}")
        if total_stdout:
            print(f"  stdout head: {bytes(total_stdout[:200])!r}")
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


# Variant 1: bridge's current sequence (NO logs=1). Hypothesis: race loses init.
run_variant("BRIDGE-CURRENT", logs=0)

# Variant 2: with logs=1. Hypothesis: replays full output, init present.
run_variant("WITH-LOGS-REPLAY", logs=1)
