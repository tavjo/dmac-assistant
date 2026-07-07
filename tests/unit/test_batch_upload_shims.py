from __future__ import annotations

import json
import os
import pathlib
import re
import stat
import subprocess


BIN = pathlib.Path("build_context/plugins/nextseek/bin")
NEW_SHIMS = {
    "nextseek-sample-search": "sample-search",
    "nextseek-project-resolve": "project-resolve",
    "nextseek-assay-resolve": "assay-resolve",
}
CORE_SHIMS = {
    "nextseek-build-payload": "build-payload",
    "nextseek-validate-upload": "build-validate",
    "nextseek-sampletype-attrs": "attrs",
    "nextseek-extract-text": "extract",
}
FORBIDDEN_WORDS = {
    "start",
    "upload",
    "sample-read",
    "--merge-existing",
    "--as-merge-map",
    "read_samples",
}


def _shim_names() -> list[str]:
    return sorted([*NEW_SHIMS, *CORE_SHIMS])


def _fake_python(tmp_path: pathlib.Path) -> pathlib.Path:
    fake = tmp_path / "python"
    fake.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$@\" > \"$NEXTSEEK_ARGV_CAPTURE\"\n"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    return fake


def _run_with_fake_python(tmp_path: pathlib.Path, shim: str, *args: str) -> list[str]:
    _fake_python(tmp_path)
    capture = tmp_path / "argv.txt"
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "NEXTSEEK_ARGV_CAPTURE": str(capture),
        "NEXTSEEK_OUTPUTS_DIR": str(tmp_path / "out"),
    }
    result = subprocess.run([str(BIN / shim), *args], capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    return capture.read_text().splitlines()


def _non_comment_tokens(path: pathlib.Path) -> list[str]:
    tokens: list[str] = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        tokens.extend(re.findall(r"--?[A-Za-z0-9_-]+|/[A-Za-z0-9_/-]+|[A-Za-z0-9_/-]+", line))
    return tokens


def test_build_payload_shim_writes_staging_only(tmp_path):
    rows = tmp_path / "rows.json"
    schema = tmp_path / "schema.json"
    titles = tmp_path / "titles.json"
    rows.write_text("[]")
    schema.write_text("[]")
    titles.write_text("{}")

    result = subprocess.run(
        [
            str(BIN / "nextseek-build-payload"),
            "--rows",
            str(rows),
            "--schema",
            str(schema),
            "--id-to-title",
            str(titles),
            "--out",
            "/data/scratch/out",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert '"gate":"staging"' in result.stdout
    assert not pathlib.Path("/data/scratch/out/payload_flat.xlsx").exists()


def test_shim_no_dynamic_forbidden_subcommand():
    assert not (BIN / "nextseek-sample-read").exists()
    for name in _shim_names():
        path = BIN / name
        assert path.exists(), f"{name} missing"
        assert path.stat().st_mode & stat.S_IXUSR, f"{name} not executable"
        text = "\n".join(
            line
            for line in path.read_text().splitlines()
            if not line.strip().startswith("#")
        )
        assert "/start/" not in text
        assert "batch-upload/start" not in text
        assert "sample-read" not in text
        assert "--merge-existing" not in text
        assert "--as-merge-map" not in text
        tokens = _non_comment_tokens(path)
        joined = " ".join(tokens)
        assert "read_samples" not in joined
        assert "upload" not in [token.strip("'\";") for token in tokens if token != "--upload"]


def test_shim_dynamic_execution_rejects_forbidden_argv(tmp_path):
    expected = {
        "nextseek-sample-search": ["sample-search", "--uid", "U1"],
        "nextseek-project-resolve": ["project-resolve", "--project-id", "1", "--confirmed", "--out", str(tmp_path / "project.json")],
        "nextseek-assay-resolve": ["assay-resolve", "--project-id", "1", "--title", "RNA-seq"],
    }
    registered = {
        "attrs",
        "extract",
        "project-resolve",
        "assay-resolve",
        "sample-search",
        "build-payload",
        "build-validate",
    }

    for shim, expected_argv in expected.items():
        argv = _run_with_fake_python(tmp_path, shim, *expected_argv[1:])
        assert pathlib.Path(argv[0]).name == "_batch_upload_runner.py"
        assert argv[1:] == expected_argv
        assert argv[1] in registered
        assert not (set(argv[1:]) & FORBIDDEN_WORDS)
        assert not any("/start/" in item or "batch-upload/start" in item for item in argv)

    for shim in _shim_names():
        result = subprocess.run([str(BIN / shim), "--help"], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert "sample-read" not in result.stdout
        assert "--merge-existing" not in result.stdout

    assert json.dumps(sorted(registered))
