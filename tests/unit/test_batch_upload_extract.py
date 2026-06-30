import sys, types, pathlib
sys.path.insert(0, str(pathlib.Path("build_context/plugins/nextseek/bin")))
import _batch_upload_extract as ex


def test_extract_text_uses_markitdown(monkeypatch, tmp_path):
    f = tmp_path / "protocol.pdf"
    f.write_text("dummy")
    calls = {}
    class _Result:
        text_content = "Subject: A123\nSex: M"
    class _MID:
        def convert(self, p):
            calls["path"] = p
            return _Result()
    fake = types.ModuleType("markitdown")
    fake.MarkItDown = lambda *a, **k: _MID()
    monkeypatch.setitem(sys.modules, "markitdown", fake)
    out = ex.extract_text(str(f))
    assert "Subject: A123" in out and calls["path"] == str(f)


def test_extract_text_config_missing_when_markitdown_absent(monkeypatch, tmp_path):
    # Cosmetic close-out: exercise the CONFIG_MISSING / SystemExit(2) branch (host case, markitdown
    # not installed). A fake module that lacks `MarkItDown` makes `from markitdown import MarkItDown`
    # raise ImportError, which the wrapper maps to SystemExit(2).
    import types, pytest
    f = tmp_path / "p.pdf"; f.write_text("x")
    fake = types.ModuleType("markitdown")  # present but no MarkItDown attribute -> ImportError on import
    monkeypatch.setitem(sys.modules, "markitdown", fake)
    with pytest.raises(SystemExit) as ei:
        ex.extract_text(str(f))
    assert ei.value.code == 2
