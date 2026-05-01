"""Hermetic unit test that Makefile wires sync-vendor-deps correctly."""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"


def test_makefile_defines_sync_vendor_deps():
    text = MAKEFILE.read_text()
    # Allow the target header to carry comments or order-only prereqs
    # (e.g. `sync-vendor-deps: ## help text`), so we don't over-specify.
    assert re.search(r"^sync-vendor-deps:", text, re.MULTILINE), \
        "Makefile must define a `sync-vendor-deps` target"
    # AMD4-M2 fix: the recipe must actually invoke the sync script.
    # A no-op `sync-vendor-deps:` followed by `@true` would game the previous
    # version of this test; this assertion forces the recipe to exist.
    assert re.search(r"^\s+@?\./scripts/sync-vendor-deps\.sh\b", text, re.MULTILINE), \
        "Makefile `sync-vendor-deps` recipe must invoke ./scripts/sync-vendor-deps.sh"


def test_image_build_depends_on_sync_vendor_deps():
    text = MAKEFILE.read_text()
    assert re.search(r"^image-build:\s.*\bsync-vendor-deps\b", text, re.MULTILINE), \
        "Makefile `image-build` target must declare `sync-vendor-deps` as a prerequisite"


def test_makefile_no_ssh_default_drift():
    text = MAKEFILE.read_text()
    assert "--ssh default" not in text, \
        "Amendment 4 forbids `--ssh default` in Makefile recipes (vendored-source build needs no SSH forwarding)"
