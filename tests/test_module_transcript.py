# tests/test_module_transcript.py
import hashlib, json
import pytest
from shipment_review.extractors.transcript import load_module_transcript, TranscriptError

def _png(tmp_path):
    p = tmp_path / "模組金核算表.png"; p.write_bytes(b"\x89PNG fake"); return p

def _sidecar(png, **over):
    row = {"contract_number": "ZHDEMO-20251223-01", "product_name": "智核AI教研中心智能终端系统",
           "model": "V1.0", "unit": "套", "quantity": 1, "unit_price": 91850, "amount": 91850,
           "royalty": 13500, "code": None}
    data = {"authored_by": "ai", "source_sha256": hashlib.sha256(png.read_bytes()).hexdigest(),
            "pass_a": {"rows": [dict(row)]}, "pass_b": {"rows": [dict(row)]}}
    data.update(over)
    (png.with_name(png.name + ".transcript.json")).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

def test_absent_sidecar_returns_none(tmp_path):
    assert load_module_transcript(_png(tmp_path)) is None

def test_valid_sidecar_returns_rows(tmp_path):
    png = _png(tmp_path); _sidecar(png)
    rows = load_module_transcript(png)
    assert len(rows) == 1 and rows[0].product_name == "智核AI教研中心智能终端系统"
    assert rows[0].unit_price == 91850 and rows[0].source_file == str(png)

def test_sha_mismatch_raises(tmp_path):
    png = _png(tmp_path); _sidecar(png, source_sha256="deadbeef")
    with pytest.raises(TranscriptError): load_module_transcript(png)

def test_disagreement_raises(tmp_path):
    png = _png(tmp_path); _sidecar(png)
    data = json.loads((png.with_name(png.name + ".transcript.json")).read_text(encoding="utf-8"))
    data["pass_b"]["rows"][0]["unit_price"] = 210; data["pass_b"]["rows"][0]["amount"] = 210
    (png.with_name(png.name + ".transcript.json")).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(TranscriptError): load_module_transcript(png)

def test_untied_amount_raises(tmp_path):
    png = _png(tmp_path)
    _sidecar(png)
    data = json.loads((png.with_name(png.name + ".transcript.json")).read_text(encoding="utf-8"))
    for p in ("pass_a", "pass_b"): data[p]["rows"][0]["amount"] = 99999  # 91850*1 != 99999
    (png.with_name(png.name + ".transcript.json")).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(TranscriptError): load_module_transcript(png)

def test_non_ai_sidecar_raises(tmp_path):
    png = _png(tmp_path); _sidecar(png, authored_by="human")
    with pytest.raises(TranscriptError): load_module_transcript(png)

def test_missing_product_name_raises(tmp_path):
    png = _png(tmp_path); _sidecar(png)
    data = json.loads((png.with_name(png.name + ".transcript.json")).read_text(encoding="utf-8"))
    for p in ("pass_a", "pass_b"): data[p]["rows"][0]["product_name"] = ""
    (png.with_name(png.name + ".transcript.json")).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(TranscriptError): load_module_transcript(png)
