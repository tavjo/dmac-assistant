"""Hermetic unit test that scripts/sync-vendor-deps.sh has a 40-char SHA pin."""
import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "sync-vendor-deps.sh"


def test_sync_script_exists_and_is_executable():
    assert SCRIPT.exists(), "scripts/sync-vendor-deps.sh missing"
    assert os.access(SCRIPT, os.X_OK), "scripts/sync-vendor-deps.sh not executable"


def test_sync_script_has_pinned_sha():
    text = SCRIPT.read_text()
    # The 40-char lowercase hex regex below already rejects floating refs
    # like "HEAD"/"main"/"master" (any non-hex string fails the regex).
    # The complementary `test_sync_script_no_floating_refs` test below
    # guards against `git checkout HEAD/main/master` appearing in the
    # script body. Together they cover the real drift vectors.
    match = re.search(r'^PIN="([0-9a-f]{40})"', text, re.MULTILINE)
    assert match, "PIN must be a 40-char lowercase hex SHA"
    sha = match.group(1)
    assert sha != "0" * 40, "PIN cannot be the null SHA"


def test_sync_script_no_floating_refs():
    text = SCRIPT.read_text()
    for forbidden in ("checkout HEAD", 'checkout "main"', 'checkout "master"', "checkout main", "checkout master"):
        assert forbidden not in text, f"floating ref found: {forbidden!r}"
