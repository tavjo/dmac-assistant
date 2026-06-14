from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_bin_copy_is_byte_identical_to_canonical():
    canon = (REPO / "sidecar/app/contract.py").read_bytes()
    binc = (REPO / "build_context/plugins/nextseek/bin/_ws_contract.py").read_bytes()
    assert canon == binc, "drift between sidecar/app/contract.py and the plugin-bin copy"
