"""Probe D: separate the three variables — stdin delivery, output reading,
output existence.

Strategy: start container, attach stdin-only write path via one mechanism,
read stdout via `container.logs(stream=True, follow=True)` which is a
different docker-py codepath. If logs see frames while attach_socket doesn't,
attach_socket itself is the bug.
"""
from __future__ import annotations

import json
import os
import threading
import time

import docker

client = docker.from_env()

CMD_VARIANTS = {
    "single-print": [
        "claude", "--print", "--output-format", "stream-json", "--verbose",
        "--dangerously-skip-permissions",
    ],
    "streaming-input": [
        "claude", "--print", "--input-format", "stream-json",
        "--output-format", "stream-json", "--verbose",
        "--dangerously-skip-permissions",
    ],
}

env = {
    "CLAUDE_CODE_USE_BEDROCK": "1",
    "AWS_REGION": os.environ["AWS_REGION"],
    "AWS_BEARER_TOKEN_BEDROCK": os.environ["AWS_BEARER_TOKEN_BEDROCK"],
    "NEXTSEEK_URL": os.environ.get("NEXTSEEK_URL", ""),
    "NEXTSEEK_USERNAME": "probe",
    "NEXTSEEK_PASSWORD": "probe",
}


def run_variant(label: str, cmd: list[str]) -> None:
    print(f"\n=== {label} ===")
    container = client.containers.run(
        image="dmac-assistant:poc",
        command=cmd,
        environment=env,
        volumes={},
        working_dir="/home/user",
        labels={"dmac-probe": "d"},
        platform="linux/amd64",
        detach=True,
        stdin_open=True,
        tty=False,
        stdout=True,
        stderr=True,
    )
    try:
        time.sleep(0.2)
        # Write stdin via attach_socket but do NOT read from it.
        raw = container.attach_socket(
            params={"stdin": 1, "stdout": 0, "stderr": 0, "stream": 1}
        )
        sock = getattr(raw, "_sock", raw)
        line = json.dumps({
            "type": "user",
            "message": {"role": "user", "content": "reply OK"},
        }) + "\n"
        sock.sendall(line.encode())
        # Do NOT shutdown — keep stdin open. Read stdout via logs().

        stdout_bytes = bytearray()
        stderr_bytes = bytearray()

        def reader() -> None:
            # logs(stream=True, follow=True) is a generator over bytes from
            # stdout+stderr (demuxed when demux=True).
            try:
                for chunk in container.logs(
                    stream=True, follow=True, stdout=True, stderr=True,
                ):
                    stdout_bytes.extend(chunk or b"")
                    if b'"type":"result"' in stdout_bytes:
                        break
            except Exception as e:
                print(f"  logs reader exited: {e!r}")

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        t.join(timeout=40)
        print(f"  stdout bytes: {len(stdout_bytes)}")
        print(f"  stderr bytes: {len(stderr_bytes)}")
        container.reload()
        print(f"  container state: {container.status}")
        if stdout_bytes:
            text = bytes(stdout_bytes).decode("utf-8", errors="replace")
            for l in text.splitlines()[:3]:
                print(f"    stdout: {l[:200]}")
        if stderr_bytes:
            print(f"  stderr head: {bytes(stderr_bytes[:400])!r}")
    finally:
        try:
            container.stop(timeout=2)
        except Exception:
            pass
        try:
            container.remove(force=True)
        except Exception:
            pass


for label, cmd in CMD_VARIANTS.items():
    run_variant(label, cmd)
