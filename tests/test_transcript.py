import hashlib
import json
from pathlib import Path

import pytest

from shipment_review.extractors.transcript import TranscriptError, load_contract_transcript


def test_load_contract_transcript_builds_readable_contract(tmp_path):
    pdf = tmp_path / "ZHDEMO-20250625-01（双章）代理商丁.pdf"
    pdf.write_bytes(b"%PDF scanned")
    sidecar = tmp_path / "ZHDEMO-20250625-01（双章）代理商丁.pdf.transcript.json"
    sidecar.write_text(
        json.dumps(
            {
                "contract_number": "ZHDEMO-20250625-01",
                "buyer_name": "四川省代理商丁信息技术有限公司",
                "seller_name": "智核（成都）信息技术有限公司",
                "items": [
                    {"name": "智核ZClass5专业版系统", "model": "V5.0", "unit": "套", "quantity": 200, "unit_price": 1035, "amount": 207000}
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    contract = load_contract_transcript(pdf)

    assert contract is not None
    assert contract.contract_number == "ZHDEMO-20250625-01"
    assert contract.buyer_name == "四川省代理商丁信息技术有限公司"
    assert contract.readable is True
    assert contract.ocr_extracted is False  # an authored transcript is trusted, not OCR
    assert len(contract.items) == 1
    item = contract.items[0]
    assert item.name == "智核ZClass5专业版系统"
    assert item.model == "V5.0"
    assert item.quantity == 200
    assert item.unit_price == 1035


def test_load_contract_transcript_absent_returns_none(tmp_path):
    pdf = tmp_path / "scanned.pdf"
    pdf.write_bytes(b"x")
    assert load_contract_transcript(pdf) is None


def test_load_contract_transcript_coerces_string_numbers(tmp_path):
    pdf = tmp_path / "c.pdf"
    pdf.write_bytes(b"x")
    (tmp_path / "c.pdf.transcript.json").write_text(
        json.dumps(
            {
                "contract_number": "ZHDEMO-20250625-01",
                "items": [{"name": "X", "quantity": "200", "unit_price": "1035", "amount": "207000"}],
            }
        ),
        encoding="utf-8",
    )

    contract = load_contract_transcript(pdf)

    assert contract.items[0].quantity == 200.0
    assert isinstance(contract.items[0].quantity, float)
    assert contract.items[0].unit_price == 1035.0


def test_load_contract_transcript_malformed_json_raises_transcript_error(tmp_path):
    pdf = tmp_path / "c.pdf"
    pdf.write_bytes(b"x")
    (tmp_path / "c.pdf.transcript.json").write_text("{not valid json", encoding="utf-8")

    with pytest.raises(TranscriptError):
        load_contract_transcript(pdf)


def test_load_contract_transcript_missing_name_raises_transcript_error(tmp_path):
    pdf = tmp_path / "c.pdf"
    pdf.write_bytes(b"x")
    (tmp_path / "c.pdf.transcript.json").write_text(
        json.dumps({"items": [{"quantity": 1, "unit_price": 1035}]}), encoding="utf-8"
    )

    with pytest.raises(TranscriptError):
        load_contract_transcript(pdf)


def _write_transcript(tmp_path, payload):
    pdf = tmp_path / "c.pdf"
    pdf.write_bytes(b"x")
    (tmp_path / "c.pdf.transcript.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return pdf


def test_transcript_missing_contract_number_raises(tmp_path):
    pdf = _write_transcript(tmp_path, {"items": [{"name": "X", "quantity": 1, "unit_price": 100, "amount": 100}]})
    with pytest.raises(TranscriptError, match="contract_number"):
        load_contract_transcript(pdf)


def test_transcript_no_items_raises(tmp_path):
    pdf = _write_transcript(tmp_path, {"contract_number": "ZHDEMO-20250625-01", "items": []})
    with pytest.raises(TranscriptError, match="品項"):
        load_contract_transcript(pdf)


def test_transcript_item_missing_price_or_quantity_raises(tmp_path):
    pdf = _write_transcript(
        tmp_path, {"contract_number": "ZHDEMO-20250625-01", "items": [{"name": "X", "amount": 100}]}
    )
    with pytest.raises(TranscriptError, match="unit_price|quantity"):
        load_contract_transcript(pdf)


def test_transcript_item_amount_inconsistent_raises(tmp_path):
    # 2 × 100 = 200, but amount says 999 — a typo the validator must catch.
    pdf = _write_transcript(
        tmp_path,
        {"contract_number": "ZHDEMO-20250625-01", "items": [{"name": "X", "quantity": 2, "unit_price": 100, "amount": 999}]},
    )
    with pytest.raises(TranscriptError, match="金額|amount"):
        load_contract_transcript(pdf)


def test_transcript_total_mismatch_raises(tmp_path):
    # Σ(unit_price×quantity) = 100 + 200 = 300, but stated total 合计 is 4500.
    pdf = _write_transcript(
        tmp_path,
        {
            "contract_number": "ZHDEMO-20250625-01",
            "total": 4500,
            "items": [
                {"name": "A", "quantity": 1, "unit_price": 100, "amount": 100},
                {"name": "B", "quantity": 1, "unit_price": 200, "amount": 200},
            ],
        },
    )
    with pytest.raises(TranscriptError, match="合計|total"):
        load_contract_transcript(pdf)


def test_transcript_consistent_math_loads(tmp_path):
    pdf = _write_transcript(
        tmp_path,
        {
            "contract_number": "ZHDEMO-20260515-01",
            "total": 4500,
            "items": [{"name": "ZClass", "model": "V5.0", "quantity": 1, "unit_price": 4500, "amount": 4500}],
        },
    )
    contract = load_contract_transcript(pdf)
    assert contract is not None and contract.items[0].amount == 4500


# ---------------------------------------------------------------------------
# Task 2 — fail-closed provenance + AI two-pass verification
# ---------------------------------------------------------------------------

_ITEM = {"name": "X", "model": "V5.0", "unit": "套", "quantity": 1, "unit_price": 100, "amount": 100}


def _pdf(tmp_path) -> Path:
    p = tmp_path / "c.pdf"
    p.write_bytes(b"%PDF scanned bytes")
    return p


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _write(tmp_path, payload) -> Path:
    p = _pdf(tmp_path)
    (tmp_path / "c.pdf.transcript.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


def test_human_transcript_is_trusted(tmp_path):
    p = _write(tmp_path, {"authored_by": "human", "contract_number": "X", "items": [dict(_ITEM)]})
    c = load_contract_transcript(p)
    assert c.readable and c.ai_unconfirmed is False


def test_legacy_no_provenance_is_untrusted(tmp_path):
    # fail-closed: unknown authored_by → untrusted
    p = _write(tmp_path, {"contract_number": "X", "items": [dict(_ITEM)]})
    c = load_contract_transcript(p)
    assert c.ai_unconfirmed is True


def test_ai_two_pass_agree_is_trusted(tmp_path):
    p = _pdf(tmp_path)
    payload = {"authored_by": "ai", "source_sha256": _sha(p),
               "pass_a": {"contract_number": "X", "items": [dict(_ITEM)]},
               "pass_b": {"contract_number": "X", "items": [dict(_ITEM)]}}
    (tmp_path / "c.pdf.transcript.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    c = load_contract_transcript(p)
    assert c.contract_number == "X" and c.ai_unconfirmed is False


def test_ai_two_pass_disagree_is_untrusted(tmp_path):
    p = _pdf(tmp_path)
    payload = {"authored_by": "ai", "source_sha256": _sha(p),
               "pass_a": {"contract_number": "X", "items": [dict(_ITEM)]},
               "pass_b": {"contract_number": "X", "items": [dict(_ITEM, unit_price=999)]}}
    (tmp_path / "c.pdf.transcript.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    c = load_contract_transcript(p)
    assert c.ai_unconfirmed is True


def test_ai_missing_sha_is_untrusted(tmp_path):
    p = _pdf(tmp_path)
    payload = {"authored_by": "ai",
               "pass_a": {"contract_number": "X", "items": [dict(_ITEM)]},
               "pass_b": {"contract_number": "X", "items": [dict(_ITEM)]}}
    (tmp_path / "c.pdf.transcript.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert load_contract_transcript(p).ai_unconfirmed is True


def test_ai_sha_mismatch_raises(tmp_path):
    p = _pdf(tmp_path)
    payload = {"authored_by": "ai", "source_sha256": "deadbeef",
               "pass_a": {"contract_number": "X", "items": [dict(_ITEM)]},
               "pass_b": {"contract_number": "X", "items": [dict(_ITEM)]}}
    (tmp_path / "c.pdf.transcript.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(TranscriptError):
        load_contract_transcript(p)


def test_ai_unreadable_pdf_raises_transcript_error_not_oserror(tmp_path):
    """If the PDF disappears/becomes unreadable after the sidecar is written, the sha
    read_bytes() OSError must be wrapped as TranscriptError, not escape as a bare OSError."""
    p = _pdf(tmp_path)
    payload = {
        "authored_by": "ai",
        "source_sha256": _sha(p),
        "pass_a": {"contract_number": "X", "items": [dict(_ITEM)]},
        "pass_b": {"contract_number": "X", "items": [dict(_ITEM)]},
    }
    (tmp_path / "c.pdf.transcript.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    p.unlink()  # PDF gone — document.read_bytes() in _resolve_ai will raise OSError

    with pytest.raises(TranscriptError):
        load_contract_transcript(p)
