from pathlib import Path

from shipment_review.extractors.text import (
    Extraction,
    OcrToken,
    extract_document,
    rows_from_tokens,
)


def test_extract_txt_returns_native_text(tmp_path):
    path = tmp_path / "approval.txt"
    path.write_text("出货审批\n合同编号 ZHDEMO-20251124-01\n", encoding="utf-8")

    extraction = extract_document(path)

    assert isinstance(extraction, Extraction)
    assert "出货审批" in extraction.text
    assert extraction.tokens == []
    assert extraction.issues == []


def test_rows_from_tokens_clusters_by_y_and_orders_by_x():
    tokens = [
        OcrToken(text="型号", confidence=0.9, x=30, y=10),
        OcrToken(text="名称", confidence=0.9, x=10, y=12),
        OcrToken(text="V5.0", confidence=0.9, x=30, y=60),
        OcrToken(text="智核ZClass5", confidence=0.9, x=10, y=62),
    ]

    rows = rows_from_tokens(tokens, y_tolerance=15)

    assert [tok.text for tok in rows[0]] == ["名称", "型号"]
    assert [tok.text for tok in rows[1]] == ["智核ZClass5", "V5.0"]


def test_low_confidence_token_produces_manual_review_issue(monkeypatch, tmp_path):
    image = tmp_path / "module.png"
    image.write_bytes(b"fake")

    fake_tokens = [
        OcrToken(text="合同单号", confidence=0.95, x=0, y=0),
        OcrToken(text="ZDEMO-20251223-01", confidence=0.55, x=50, y=0),
    ]
    monkeypatch.setattr("shipment_review.extractors.text._ocr_available", lambda: True)
    monkeypatch.setattr("shipment_review.extractors.text._ocr_tokens", lambda path, **kw: fake_tokens)

    extraction = extract_document(image, min_confidence=0.7)

    assert "ZDEMO-20251223-01" in extraction.text
    assert any("OCR 信心不足" in issue.message for issue in extraction.issues)


def test_multiple_low_confidence_tokens_produce_single_issue(monkeypatch, tmp_path):
    image = tmp_path / "module.png"
    image.write_bytes(b"fake")

    fake_tokens = [
        OcrToken(text="合同单号", confidence=0.95, x=0, y=0),
        OcrToken(text="ZDEMO-20251223-01", confidence=0.55, x=50, y=0),
        OcrToken(text="金额", confidence=0.45, x=0, y=20),
        OcrToken(text="¥99999", confidence=0.50, x=50, y=20),
    ]
    monkeypatch.setattr("shipment_review.extractors.text._ocr_available", lambda: True)
    monkeypatch.setattr("shipment_review.extractors.text._ocr_tokens", lambda path, **kw: fake_tokens)

    extraction = extract_document(image, min_confidence=0.7)

    ocr_issues = [i for i in extraction.issues if "OCR 信心不足" in i.message]
    assert len(ocr_issues) == 1, f"Expected 1 summary issue, got {len(ocr_issues)}"


def test_image_without_ocr_returns_empty_extraction(monkeypatch, tmp_path):
    image = tmp_path / "module.png"
    image.write_bytes(b"fake")
    monkeypatch.setattr("shipment_review.extractors.text._ocr_available", lambda: False)

    extraction = extract_document(image)

    assert extraction.text == ""
    assert extraction.tokens == []
    assert extraction.issues == []
