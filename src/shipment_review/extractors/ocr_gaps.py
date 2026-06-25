"""Detect contracts whose OCR is too weak to review, so an agent (Claude Code) can
read the scan and author a `<file>.transcript.json` sidecar — the second path when
OCR fails. Pure detection only: this never writes files and never decides a verdict.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from shipment_review.extractors.contract import parse_contract
from shipment_review.extractors.files import detect_case_files
from shipment_review.extractors.text import IMAGE_SUFFIXES, OCR_LOW_CONFIDENCE_MARK, Extraction, extract_document
from shipment_review.extractors.transcript import (
    TranscriptError,
    load_contract_transcript,
    transcript_path,
)
from shipment_review.models import Contract


def _sha(path: Path) -> str:
    """Return SHA-256 hex digest of path; '' if the file cannot be read."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


@dataclass(frozen=True)
class OcrGap:
    file: str
    reason: str
    sha256: str = ""
    kind: str = "contract"


def _line_amount_unreconciled(item) -> bool:
    """True when a contract line carries an 金额 that cannot be verified as 单价×数量.

    Reconciled = unit_price and quantity are both present and 单价×数量 = 金额. A line
    with NO amount is skipped (nothing to reconcile; a clean contract may omit the
    amount column). Used only on OCR scans, where an unreconciled amount signals a
    garbled table — not a real (always-tying) 购销合同 line.
    """
    if item.amount is None:
        return False
    if item.unit_price is None or item.quantity is None:
        return True
    return round(item.unit_price * item.quantity, 2) != round(item.amount, 2)


def contract_gap_reason(extraction: Extraction, contract: Contract) -> str | None:
    """Why this contract needs a transcript, or None if OCR reconstructed it cleanly.

    Four independent signals: low OCR confidence (the extractor already flags it); a
    structural miss (no contract number or no item rows); a garbled-but-nonempty parse
    where every item lacks a price (a real 购销合同 line always carries money, so an
    all-priceless table means the OCR text could not be read); and — on an OCR scan — a
    line whose 金额 cannot be reconciled to 单价×数量 (garbled cells that still carry some
    money, see `_line_amount_unreconciled`). Any one means the deterministic rules
    cannot trust this contract.
    """
    reasons: list[str] = []
    if any(OCR_LOW_CONFIDENCE_MARK in issue.message for issue in extraction.issues):
        reasons.append(OCR_LOW_CONFIDENCE_MARK)
    if not contract.contract_number:
        reasons.append("無法解析合同號")
    if not contract.items:
        reasons.append("無法解析品項")
    elif not any(item.unit_price is not None or item.amount is not None for item in contract.items):
        reasons.append("品項皆無單價/金額（疑似 OCR 雜訊）")
    elif contract.ocr_extracted and any(_line_amount_unreconciled(item) for item in contract.items):
        # A scan can OCR into a number + items with SOME money yet have a garbled table:
        # either 单价×数量 ≠ 金额 (代理商甲: 2850 read as 850, 102600 as 600) or a row carries
        # an 金额 with no 单价/数量 at all (易网: cells mashed into prose). A real 购销合同
        # line always ties out (no line discounts in this dataset — the same assumption
        # the transcript validator makes), so an amount that can't be reconciled on a scan
        # means the table could not be reconstructed → the rules must not trust it.
        reasons.append("品項金額不符（疑似 OCR 雜訊）")
    return "；".join(reasons) if reasons else None


def collect_ocr_gaps(case_dir: Path | str) -> list[OcrGap]:
    """Contracts in the case folder that need an authored transcript. A contract with a
    valid transcript sidecar is skipped (gap already filled); a present-but-invalid one
    is itself a gap — it still needs a real transcript and must not read as filled.

    The module branch calls gather_case (intentional dependency on the verdict-assembly
    layer; pure read, no verdict).
    """
    detected = detect_case_files(case_dir)
    gaps: list[OcrGap] = []
    for path in detected.contracts:
        file = str(path.resolve())
        if transcript_path(path).exists():
            try:
                load_contract_transcript(path)
                continue  # valid transcript → gap already filled
            except TranscriptError as exc:
                sha = _sha(path)
                gaps.append(OcrGap(file=file, reason=f"transcript 無效：{exc}", sha256=sha))
                continue
        extraction = extract_document(path)
        contract = parse_contract(extraction, path, [])
        reason = contract_gap_reason(extraction, contract)
        if reason:
            sha = _sha(path)
            gaps.append(OcrGap(file=file, reason=reason, sha256=sha))

    module_table = detected.module_table
    if module_table is not None and module_table.suffix.lower() in IMAGE_SUFFIXES:
        if transcript_path(module_table).exists():
            try:
                from shipment_review.extractors.transcript import load_module_transcript
                load_module_transcript(module_table)  # valid → gap filled, skip
            except TranscriptError as exc:
                gaps.append(OcrGap(file=str(module_table.resolve()),
                                   reason=f"transcript 無效：{exc}", sha256=_sha(module_table), kind="module_table"))
        else:
            # matching-aware: needs the engine's assembled case (contracts w/ transcripts + approval)
            from shipment_review.report import gather_case
            from shipment_review.rules import module_rows_matching_nothing
            unmatched = module_rows_matching_nothing(gather_case(case_dir).case)
            if unmatched:
                names = "、".join(r.product_name for r in unmatched[:3])
                gaps.append(OcrGap(file=str(module_table.resolve()),
                                   reason=f"模組表項目「{names}」對不上任何合同/審批（疑似 OCR 字錯）",
                                   sha256=_sha(module_table), kind="module_table"))
    return gaps
