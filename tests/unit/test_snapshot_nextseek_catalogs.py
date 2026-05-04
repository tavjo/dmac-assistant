"""Plan B · T13 — `make snapshot-nextseek-catalogs` target contract.

Tests cover:
  - Plan body line 2304-2322 success path: target copies the four catalog
    families from $(CHAT_NEXTSEEK_SRC)/src/chat_nextseek/context/ into
    build_context/plugins/nextseek/context/ relative to make's CWD.
  - NEW-6 missing-source guard: missing CHAT_NEXTSEEK_SRC tree fails the
    target with non-zero exit AND the ERROR: message wording.
  - NEW-6 partial-tree guard: source exists but the inner context/ subdir
    is absent → also fails with ERROR.
  - Idempotency: running the target twice in a row produces the same
    destination state (cp -f semantics, not cp -n).
  - mkdir -p semantics: target creates the destination dir if absent.

The test invokes `make snapshot-nextseek-catalogs` via subprocess against a
tmp-path working directory containing a copy of the real Makefile + a fake
$(CHAT_NEXTSEEK_SRC) tree. This isolates the test from the production
working tree (no clobbering of build_context/plugins/nextseek/context/).

No chat_nextseek import; no importorskip needed (per spec §3 Decisions).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = (REPO_ROOT / "Makefile").resolve()


def _has_make() -> bool:
    return shutil.which("make") is not None


@pytest.fixture(autouse=True)
def _require_make():
    if not _has_make():
        pytest.skip(
            "GNU Make is required for snapshot-nextseek-catalogs; install make "
            "on the host or run these tests inside the image (Dockerfile installs "
            "make in the build-essential apt-get block)"
        )


def _stage_fake_chat_nextseek_src(root: Path) -> Path:
    """Build a fake $(CHAT_NEXTSEEK_SRC) tree with the four catalog families.

    Returns the path that should be passed as CHAT_NEXTSEEK_SRC=... to make.
    """
    src = root / "fake_chat_nextseek"
    ctx = src / "src" / "chat_nextseek" / "context"
    ctx.mkdir(parents=True)
    (ctx / "min_endpoints.json").write_text('{"endpoints": ["x"]}')
    (ctx / "min_models.json").write_text('{"models": ["y"]}')
    (ctx / "projects_db.json").write_text('{"projects": []}')
    (ctx / "neo4j_schema.json").write_text('{"nodes": [], "edges": []}')
    (ctx / "capabilities.md").write_text("# capabilities\n\n- foo\n")
    return src


def _stage_tmp_workdir(root: Path) -> Path:
    """Stage a tmp workdir containing a copy of the real Makefile.

    Cleanly isolates make invocations from the production tree. Make writes
    `build_context/plugins/nextseek/context/` relative to its CWD, so all
    side-effects land under root/work/.
    """
    work = root / "work"
    work.mkdir()
    shutil.copy(MAKEFILE, work / "Makefile")
    return work


def _run_make(work: Path, src: Path, *, expect_returncode: int = 0):
    r = subprocess.run(
        ["make", "snapshot-nextseek-catalogs", f"CHAT_NEXTSEEK_SRC={src}"],
        cwd=work,
        capture_output=True,
        text=True,
        env={**os.environ},
    )
    assert r.returncode == expect_returncode, (
        f"make exit={r.returncode} stdout={r.stdout!r} stderr={r.stderr!r}"
    )
    return r


def test_snapshot_copies_expected_catalogs(tmp_path):
    """Plan body line 2313-2320 success path: each of the four catalog
    families lands under build_context/plugins/nextseek/context/ inside CWD.
    """
    work = _stage_tmp_workdir(tmp_path)
    src = _stage_fake_chat_nextseek_src(tmp_path)
    _run_make(work, src)
    out = work / "build_context" / "plugins" / "nextseek" / "context"
    assert out.is_dir(), "target must create destination dir"
    # min_*.json glob — both staged files must land
    assert (out / "min_endpoints.json").is_file()
    assert (out / "min_models.json").is_file()
    assert (out / "min_endpoints.json").read_text() == '{"endpoints": ["x"]}'
    # The other three named files
    assert (out / "projects_db.json").is_file()
    assert (out / "neo4j_schema.json").is_file()
    assert (out / "capabilities.md").is_file()
    assert (out / "capabilities.md").read_text().startswith("# capabilities")


def test_snapshot_emits_confirmation_message(tmp_path):
    """The recipe's final `@echo` line confirms what landed where.
    Plan body line 2321: 'Snapshotted catalogs to ... (from ...)'."""
    work = _stage_tmp_workdir(tmp_path)
    src = _stage_fake_chat_nextseek_src(tmp_path)
    r = _run_make(work, src)
    assert "Snapshotted catalogs to" in r.stdout, (
        f"expected confirmation message in stdout; got {r.stdout!r}"
    )
    # The message MUST quote the source path so the developer can verify
    # which checkout was snapshotted (this is load-bearing diagnostic — a
    # silent target would obscure CHAT_NEXTSEEK_SRC=/wrong/path bugs).
    assert str(src) in r.stdout


def test_snapshot_guard_fails_on_missing_source(tmp_path):
    """NEW-6 (plan body line 2310-2311): if CHAT_NEXTSEEK_SRC does not
    exist, make exits non-zero with the ERROR: message. This is the
    load-bearing anti-silent-empty-snapshot guard."""
    work = _stage_tmp_workdir(tmp_path)
    bogus = tmp_path / "does_not_exist"
    assert not bogus.exists()
    r = _run_make(work, bogus, expect_returncode=2)  # GNU make: 2 = recipe failed
    # Either stderr or stdout will carry the ERROR — both shells echo to
    # stderr conventionally, but make may capture/forward differently across
    # versions (BSD vs GNU vs gmake). Assert against the union.
    combined = r.stderr + r.stdout
    assert "ERROR: CHAT_NEXTSEEK_SRC not found at" in combined, (
        f"expected ERROR: message naming the missing path; got "
        f"stdout={r.stdout!r} stderr={r.stderr!r}"
    )
    assert str(bogus) in combined, (
        "ERROR message MUST quote the missing path so the developer can "
        "see which path was checked"
    )
    # Destination must NOT have been created (silent-empty-snapshot defence).
    out = work / "build_context" / "plugins" / "nextseek" / "context"
    assert not out.exists(), (
        "guard MUST run before mkdir -p; failed guard must leave destination "
        "untouched (no empty dir)"
    )


def test_snapshot_guard_fails_on_partial_source_tree(tmp_path):
    """If $(CHAT_NEXTSEEK_SRC) exists as a directory BUT the inner
    src/chat_nextseek/context/ subdir is absent, the guard must still fire.
    A partial source tree is a real failure mode — e.g., a developer pointing
    at a sibling repo that happens to share the parent name."""
    work = _stage_tmp_workdir(tmp_path)
    partial = tmp_path / "partial_src"
    partial.mkdir()  # exists but lacks the inner src/chat_nextseek/context tree
    r = _run_make(work, partial, expect_returncode=2)
    combined = r.stderr + r.stdout
    assert "ERROR: CHAT_NEXTSEEK_SRC not found at" in combined
    out = work / "build_context" / "plugins" / "nextseek" / "context"
    assert not out.exists()


def test_snapshot_is_idempotent(tmp_path):
    """Running the target twice produces the same destination state.
    cp -f semantics — overwrite, not skip. Verifies that a stale cached file
    in the destination gets refreshed when the source changes."""
    work = _stage_tmp_workdir(tmp_path)
    src = _stage_fake_chat_nextseek_src(tmp_path)
    out = work / "build_context" / "plugins" / "nextseek" / "context"
    # First run.
    _run_make(work, src)
    first_capabilities = (out / "capabilities.md").read_text()
    # Mutate the source file; second run must overwrite the destination.
    (src / "src" / "chat_nextseek" / "context" / "capabilities.md").write_text(
        "# capabilities (updated)\n\n- bar\n"
    )
    _run_make(work, src)
    second_capabilities = (out / "capabilities.md").read_text()
    assert first_capabilities != second_capabilities
    assert "(updated)" in second_capabilities, (
        "second run MUST overwrite stale cached capabilities.md (cp -f, not cp -n)"
    )
    # Other files unchanged across the second run; assert at least one of
    # them is still present and matches the staged content.
    assert (out / "min_endpoints.json").read_text() == '{"endpoints": ["x"]}'
