import json
from pathlib import Path

from shipment_review.extractors.ocr_gaps import (
    OcrGap,
    collect_ocr_gaps,
    contract_gap_reason,
)
from shipment_review.extractors.text import Extraction, OcrToken
from shipment_review.models import Contract, ContractItem, Issue, IssueSeverity


def _contract(**over):
    data = dict(
        source_file="c.pdf",
        contract_number="ZHDEMO-20260515-01",
        buyer_name="买方",
        seller_name="卖方",
        school_name=None,
        items=[ContractItem(code="T5-3", name="ZClass", model="V5.0", unit="套", quantity=1, unit_price=4500)],
        readable=True,
    )
    data.update(over)
    return Contract(**data)


def test_gap_reason_none_when_contract_parsed_cleanly():
    extraction = Extraction(text="ok", tokens=[OcrToken(text="x", confidence=0.95, x=0, y=0)])
    assert contract_gap_reason(extraction, _contract()) is None


def test_gap_reason_flags_low_ocr_confidence():
    extraction = Extraction(
        issues=[Issue(IssueSeverity.MANUAL_REVIEW, "OCR 信心不足：此文件有 3 個欄位信心值偏低（最低 0.21），請人工確認掃描件可讀性。")]
    )
    reason = contract_gap_reason(extraction, _contract())
    assert reason is not None and "OCR 信心不足" in reason


def test_gap_reason_flags_missing_contract_number():
    reason = contract_gap_reason(Extraction(text="x"), _contract(contract_number=None))
    assert reason is not None and "合同號" in reason


def test_gap_reason_flags_no_items():
    reason = contract_gap_reason(Extraction(text="x"), _contract(items=[]))
    assert reason is not None and "品項" in reason


def _write_case(tmp_path: Path, contract_text: str = "雜訊內容，無表格。") -> Path:
    (tmp_path / "出货审批.txt").write_text(
        "出货审批\n合同编号 ZHDEMO-20260515-01\n实际出货为：\nT5-3，1套ZClassV5.0\n",
        encoding="utf-8",
    )
    (tmp_path / "模組金核算表.txt").write_text("合同单号 产品名称 单价 金额\n", encoding="utf-8")
    (tmp_path / "ZHDEMO-20260515-01合同.txt").write_text(contract_text, encoding="utf-8")
    return tmp_path / "ZHDEMO-20260515-01合同.txt"


def test_collect_ocr_gaps_flags_unparseable_contract(tmp_path):
    _write_case(tmp_path)
    gaps = collect_ocr_gaps(tmp_path)
    assert len(gaps) == 1
    assert isinstance(gaps[0], OcrGap)
    assert gaps[0].file.endswith("ZHDEMO-20260515-01合同.txt")


def test_run_ocr_gaps_lists_gap_with_reason(tmp_path):
    from shipment_review.cli import run_ocr_gaps

    _write_case(tmp_path)
    output = run_ocr_gaps(tmp_path)
    assert "ZHDEMO-20260515-01合同.txt" in output
    assert "\t" in output  # path<TAB>reason


def test_run_ocr_gaps_clean_case_reports_no_gap(tmp_path):
    from shipment_review.cli import run_ocr_gaps

    contract = _write_case(tmp_path)
    (contract.with_name(contract.name + ".transcript.json")).write_text(
        json.dumps(
            {"contract_number": "ZHDEMO-20260515-01", "items": [{"name": "ZClass", "quantity": 1, "unit_price": 4500, "amount": 4500}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert "無 OCR 缺口" in run_ocr_gaps(tmp_path)


def test_gap_reason_flags_items_with_no_price_or_amount():
    # Garbled OCR can yield item rows that carry a name but no money — a real 购销合同
    # line always has a price, so an all-priceless parse means the table is unreadable.
    junk_item = ContractItem(code=None, name="雜訊", model=None, unit=None, quantity=None, unit_price=None, amount=None)
    reason = contract_gap_reason(Extraction(text="x"), _contract(items=[junk_item]))
    assert reason is not None and ("單價" in reason or "金額" in reason)


def test_gap_reason_flags_garbled_scan_with_untied_line_amounts():
    # Bug A: a pure-image scan can OCR into a valid number + items carrying SOME prices,
    # yet the table is garbled so 单价×数量 ≠ 金额 (代理商甲 real data: 2850 read as 850,
    # 102600 as 600). This slips past the number / items / all-priceless checks but the
    # parse cannot be trusted → must be flagged as needing a transcript.
    garbled = ContractItem(code="T5-3", name="ZClass", model="V5.0", unit="套",
                           quantity=36, unit_price=850, amount=600)
    reason = contract_gap_reason(Extraction(text="x"), _contract(ocr_extracted=True, items=[garbled]))
    assert reason is not None and "金額不符" in reason


def test_gap_reason_flags_garbled_scan_with_amount_but_no_rate():
    # 易网 real data: OCR mashes the table so a row carries an 金额 but NO 单价/数量
    # (names become prose fragments). An amount that cannot be reconciled to 单价×数量
    # means the scan's table is unreadable → must be flagged for a transcript. (Distinct
    # from all-priceless: an amount IS present, so the old all-priceless check misses it.)
    garbled = ContractItem(code=None, name="记录总表下载：总表内容包含本节课的出席情况", model=None,
                           unit=None, quantity=None, unit_price=None, amount=30800)
    reason = contract_gap_reason(Extraction(text="x"), _contract(ocr_extracted=True, items=[garbled]))
    assert reason is not None and "金額不符" in reason


def test_gap_reason_no_garble_flag_when_ocr_lines_tie_out():
    # Guard: an OCR contract whose lines DO tie out (单价×数量 = 金额) is not falsely
    # flagged by the garble check.
    tied = ContractItem(code="T5-3", name="ZClass", model="V5.0", unit="套",
                        quantity=2, unit_price=4500, amount=9000)
    clean = Extraction(text="ok", tokens=[OcrToken(text="x", confidence=0.95, x=0, y=0)])
    assert contract_gap_reason(clean, _contract(ocr_extracted=True, items=[tied])) is None


def test_gap_reason_garble_check_gated_to_ocr_only():
    # Safety boundary: the "untied amount ⇒ garble" inference is valid ONLY for OCR
    # scans. A NON-OCR (native-text / structured) contract with an untied line must NOT
    # be flagged — that gate is what keeps this signal from ever touching a digitally
    # extracted contract. (Pins the verdict-neutrality-protecting condition.)
    untied = ContractItem(code="T5-3", name="ZClass", model="V5.0", unit="套",
                          quantity=36, unit_price=850, amount=600)
    assert contract_gap_reason(Extraction(text="x"), _contract(ocr_extracted=False, items=[untied])) is None


def test_gap_reason_no_garble_flag_when_amount_column_absent():
    # Guard: a clean OCR contract may omit the 金额 column entirely (amount=None); with
    # 单价/数量 present there is nothing to reconcile, so it must NOT be flagged.
    no_amount = ContractItem(code="T5-3", name="ZClass", model="V5.0", unit="套",
                             quantity=2, unit_price=4500, amount=None)
    clean = Extraction(text="ok", tokens=[OcrToken(text="x", confidence=0.95, x=0, y=0)])
    assert contract_gap_reason(clean, _contract(ocr_extracted=True, items=[no_amount])) is None


def test_collect_ocr_gaps_flags_contract_with_invalid_transcript(tmp_path):
    # A present-but-invalid transcript must NOT read as "filled": the contract still
    # needs a real transcript, so --ocr-gaps must surface it (not silently skip).
    contract = _write_case(tmp_path)
    (contract.with_name(contract.name + ".transcript.json")).write_text(
        json.dumps({"items": []}, ensure_ascii=False), encoding="utf-8"  # invalid: no number, no items
    )
    gaps = collect_ocr_gaps(tmp_path)
    assert len(gaps) == 1
    assert "transcript" in gaps[0].reason.lower() or "無效" in gaps[0].reason


def test_collect_ocr_gaps_includes_sha256(tmp_path):
    import hashlib
    from pathlib import Path
    from shipment_review.extractors.ocr_gaps import collect_ocr_gaps
    _write_case(tmp_path)
    gaps = collect_ocr_gaps(tmp_path)
    assert gaps and gaps[0].sha256 == hashlib.sha256(Path(gaps[0].file).read_bytes()).hexdigest()


def test_collect_ocr_gaps_sha_oserror_invalid_transcript_returns_empty_sha(tmp_path, monkeypatch):
    """An OSError reading the contract for sha256 (invalid-transcript path) must not crash;
    the gap should still be reported with sha256 == ''."""
    contract = _write_case(tmp_path)
    (contract.with_name(contract.name + ".transcript.json")).write_text(
        json.dumps({"items": []}, ensure_ascii=False), encoding="utf-8"
    )
    original_read_bytes = Path.read_bytes
    def patched_read_bytes(self):
        if self.resolve() == contract.resolve():
            raise OSError("simulated disk error")
        return original_read_bytes(self)
    monkeypatch.setattr(Path, "read_bytes", patched_read_bytes)

    gaps = collect_ocr_gaps(tmp_path)
    assert len(gaps) == 1
    assert gaps[0].sha256 == ""


def test_collect_ocr_gaps_sha_oserror_no_transcript_returns_empty_sha(tmp_path, monkeypatch):
    """An OSError reading the contract for sha256 (no-transcript gap path) must not crash;
    the gap should still be reported with sha256 == ''."""
    contract = _write_case(tmp_path)  # no transcript; OCR can't parse → real gap
    original_read_bytes = Path.read_bytes
    def patched_read_bytes(self):
        if self.resolve() == contract.resolve():
            raise OSError("simulated disk error")
        return original_read_bytes(self)
    monkeypatch.setattr(Path, "read_bytes", patched_read_bytes)

    gaps = collect_ocr_gaps(tmp_path)
    assert len(gaps) == 1
    assert gaps[0].sha256 == ""


def test_collect_ocr_gaps_skips_contract_with_transcript(tmp_path):
    contract = _write_case(tmp_path)
    (contract.with_name(contract.name + ".transcript.json")).write_text(
        json.dumps(
            {
                "contract_number": "ZHDEMO-20260515-01",
                "items": [{"name": "ZClass", "model": "V5.0", "quantity": 1, "unit_price": 4500, "amount": 4500}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert collect_ocr_gaps(tmp_path) == []


# ---------------------------------------------------------------------------
# Task 5: OcrGap.kind + module-table detection
# ---------------------------------------------------------------------------

def test_ocr_gaps_default_kind_is_contract(tmp_path):
    from shipment_review.extractors.ocr_gaps import OcrGap
    assert OcrGap(file="c.pdf", reason="x").kind == "contract"

def _case_with_module(tmp_path, module_name, contract_name="智核AI教研中心智能终端系统"):
    (tmp_path / "出货审批.txt").write_text(
        f"出货审批\n合同编号 ZHDEMO-20251223-01\n实际出货为：\nA5-3，1套{contract_name}V1.0\n", encoding="utf-8")
    (tmp_path / "ZHDEMO-20251223-01合同.txt").write_text(
        f"购销合同 订单号 ZHDEMO-20251223-01\n名称 {contract_name} 型号 V1.0 单位 套 数量 1 单价 91850 金额 91850\n",
        encoding="utf-8")
    from PIL import Image
    png = tmp_path / "模組金核算表.png"; Image.new("RGB", (4, 4), "white").save(png)  # REAL png; gather_case OCRs it (returns empty), then the patched parse_module_table supplies rows
    return png

def test_module_gap_when_row_matches_nothing(tmp_path, monkeypatch):
    # Force the module rapidocr parse to produce the garbled "A教研中心" row.
    png = _case_with_module(tmp_path, module_name="x")
    import shipment_review.report as report
    from shipment_review.models import ModuleRow
    def fake(extraction, src):
        return [ModuleRow(source_file=str(src), contract_number="ZHDEMO-20251223-01", purchasing_company=None,
                          product_name="智核A教研中心智能终端系统", model="V1.0", unit="套",
                          quantity=1, unit_price=91850, amount=91850, royalty=13500)]
    monkeypatch.setattr(report, "parse_module_table", fake)
    gaps = collect_ocr_gaps(tmp_path)
    mod = [g for g in gaps if g.kind == "module_table"]
    assert len(mod) == 1 and "對不上" in mod[0].reason and mod[0].file.endswith("模組金核算表.png")

def test_no_module_gap_when_rows_match(tmp_path, monkeypatch):
    png = _case_with_module(tmp_path, module_name="x")
    import shipment_review.report as report
    from shipment_review.models import ModuleRow
    def fake(extraction, src):
        return [ModuleRow(source_file=str(src), contract_number="ZHDEMO-20251223-01", purchasing_company=None,
                          product_name="智核AI教研中心智能终端系统", model="V1.0", unit="套",
                          quantity=1, unit_price=91850, amount=91850, royalty=13500)]
    monkeypatch.setattr(report, "parse_module_table", fake)
    assert [g for g in collect_ocr_gaps(tmp_path) if g.kind == "module_table"] == []

def test_non_image_module_never_a_gap(tmp_path):
    (tmp_path / "出货审批.txt").write_text("出货审批\n", encoding="utf-8")
    (tmp_path / "模組金核算表.xlsx").write_bytes(b"PK fake xlsx")
    assert [g for g in collect_ocr_gaps(tmp_path) if g.kind == "module_table"] == []


# ---------------------------------------------------------------------------
# Task 6: CLI emits `kind` in `--ocr-gaps --json`
# ---------------------------------------------------------------------------

def test_run_ocr_gaps_json_includes_kind(tmp_path):
    import json as _json
    from shipment_review.cli import run_ocr_gaps
    (tmp_path / "出货审批.txt").write_text("出货审批\n合同编号 ZHDEMO-20260515-01\n实际出货为：\nT5-3，1套ZClassV5.0\n", encoding="utf-8")
    (tmp_path / "ZHDEMO-20260515-01合同.txt").write_text("雜訊，無表格。", encoding="utf-8")
    out = run_ocr_gaps(tmp_path, as_json=True)
    data = _json.loads(out)
    assert data and all("kind" in g for g in data)
