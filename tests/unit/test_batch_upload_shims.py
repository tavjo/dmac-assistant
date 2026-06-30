# tests/unit/test_batch_upload_shims.py
import os, stat, subprocess, pathlib, pytest

BIN = pathlib.Path("build_context/plugins/nextseek/bin")
SHIMS = ["nextseek-sampletype-attrs", "nextseek-sample-read", "nextseek-extract-text",
         "nextseek-build-payload", "nextseek-validate-upload"]

@pytest.mark.parametrize("name", SHIMS)
def test_shim_exists_and_is_executable(name):
    p = BIN / name
    assert p.exists(), f"{name} missing"
    assert p.stat().st_mode & stat.S_IXUSR, f"{name} not executable"

@pytest.mark.parametrize("name", SHIMS)
def test_shim_help_runs(name):
    r = subprocess.run([str(BIN / name), "--help"], capture_output=True, text=True)
    assert r.returncode == 0, f"{name} --help failed: {r.stderr}"

def test_no_shim_references_start_or_upload_endpoint():
    # Scan the shims AND the dispatcher + client modules — the brief's
    # success-condition grep explicitly includes _batch_upload_runner.py, and
    # the runner/client are the modules most likely to grow an upload path.
    for name in SHIMS + ["_batch_upload_runner.py", "_batch_upload_client.py"]:
        src = (BIN / name).read_text()
        assert "batch-upload/start" not in src
        assert "/start/" not in src

def test_validate_shim_rejects_write_flag():
    r = subprocess.run([str(BIN / "nextseek-validate-upload"), "--confirmed-write"],
                       capture_output=True, text=True)
    assert r.returncode == 3
