# tests/test_report_module_transcript.py
import hashlib, json
from pathlib import Path
from shipment_review.report import gather_case

def test_gather_case_uses_valid_module_sidecar(tmp_path):
    from PIL import Image
    (tmp_path / "出货审批.txt").write_text(
        "出货审批\n合同编号 ZHDEMO-20251223-01\n实际出货为：\nA5-3，1套智核AI教研中心智能终端系统V1.0\n",
        encoding="utf-8")
    # REAL but blank png: at RED (no precedence yet) it OCRs to nothing → module_rows empty →
    # the assert fails cleanly; at GREEN the valid sidecar populates the rows. (Fake bytes
    # would crash extract_document at the RED step in an OCR-enabled venv.)
    png = tmp_path / "模組金核算表.png"; Image.new("RGB", (4, 4), "white").save(png)
    row = {"contract_number": "ZHDEMO-20251223-01", "product_name": "智核AI教研中心智能终端系统",
           "model": "V1.0", "unit": "套", "quantity": 1, "unit_price": 91850, "amount": 91850}
    (png.with_name(png.name + ".transcript.json")).write_text(json.dumps(
        {"authored_by": "ai", "source_sha256": hashlib.sha256(png.read_bytes()).hexdigest(),
         "pass_a": {"rows": [dict(row)]}, "pass_b": {"rows": [dict(row)]}}, ensure_ascii=False), encoding="utf-8")
    case = gather_case(tmp_path).case
    assert [r.product_name for r in case.module_rows] == ["智核AI教研中心智能终端系统"]

def test_gather_case_invalid_module_sidecar_falls_back_and_flags(tmp_path):
    from PIL import Image
    (tmp_path / "出货审批.txt").write_text("出货审批\n", encoding="utf-8")
    png = tmp_path / "模組金核算表.png"; Image.new("RGB", (4, 4), "white").save(png)  # REAL png (OCR-enabled venv would crash on fake bytes)
    (png.with_name(png.name + ".transcript.json")).write_text(
        json.dumps({"authored_by": "ai", "pass_a": {"rows": []}}, ensure_ascii=False), encoding="utf-8")  # missing pass_b/sha → invalid → fallback
    case = gather_case(tmp_path).case
    assert any("模組表 transcript" in i.message for i in case.extraction_issues)
