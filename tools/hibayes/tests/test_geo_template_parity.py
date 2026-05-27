"""tools/hibayes/tests/test_geo_template_parity.py — parity test for T0.3.

Asserts the in-repo copy of GEO-updated.json equals the vendor copy when the
vendored chat_nextseek checkout is present. Skips cleanly if vendor is absent
(developer machines without `make sync-vendor-deps`).

Per locked-spec DD-39 Option (a) (committed to repo) + plan-DD-02.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
IN_REPO_PATH = REPO_ROOT / "tools" / "hibayes" / "resources" / "GEO-updated.json"
VENDOR_PATH = (
    REPO_ROOT
    / "vendor"
    / "chat_nextseek"
    / "src"
    / "chat_nextseek"
    / "reports"
    / "GEO-updated.json"
)


def test_in_repo_geo_template_exists() -> None:
    """Locked DD-39 Option (a): in-repo copy at tools/hibayes/resources/GEO-updated.json."""
    assert IN_REPO_PATH.is_file(), f"Missing in-repo GEO template at {IN_REPO_PATH}"


def test_in_repo_geo_template_is_well_formed_json() -> None:
    """Sanity: the committed file is well-formed JSON."""
    with IN_REPO_PATH.open("r", encoding="utf-8") as fh:
        loaded = json.load(fh)
    # GEO template is a non-empty structure; precise shape is upstream's concern
    # but it should at minimum be a dict or list.
    assert isinstance(loaded, (dict, list))


def test_in_repo_geo_template_matches_vendor_when_present() -> None:
    """Best-effort parity check: in-repo == vendor copy when vendor is present.

    Skips when vendor is absent (developer machines without `make sync-vendor-deps`).
    Per locked-spec DD-39 Option (a) + plan-DD-02: vendor sync becomes documentation;
    the in-repo copy is the runtime authority.
    """
    if not VENDOR_PATH.is_file():
        pytest.skip(f"Vendor copy absent at {VENDOR_PATH}; skipping parity check")

    in_repo_bytes = IN_REPO_PATH.read_bytes()
    vendor_bytes = VENDOR_PATH.read_bytes()
    assert in_repo_bytes == vendor_bytes, (
        f"In-repo GEO template diverges from vendor copy. "
        f"Re-run `cp {VENDOR_PATH} {IN_REPO_PATH}` to resync."
    )


def test_readme_exists_in_resources_dir() -> None:
    """T0.3 ships a one-line refresh procedure in tools/hibayes/resources/README.md."""
    readme_path = REPO_ROOT / "tools" / "hibayes" / "resources" / "README.md"
    assert readme_path.is_file(), f"Missing README at {readme_path}"
    content = readme_path.read_text(encoding="utf-8")
    # The README must mention the refresh command at least conceptually.
    assert "GEO" in content
    assert ("sync" in content.lower()) or ("refresh" in content.lower())
