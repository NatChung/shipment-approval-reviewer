"""Verified-transcript sidecars for documents OCR cannot reliably reconstruct.

A scanned 双章 contract is often a dense two-column legal page whose item table,
while present in the OCR text, gets spatially scrambled and cannot be rebuilt by the
heuristic parser. Instead of an OCR/vision API call, a reviewer (human or an agent
reading the page) authors a `<document>.transcript.json` sidecar; when present it is
trusted as the document's content, bypassing OCR entirely.

Convention: when a contract line identifies a product by a hardware SKU (e.g.
``XW-A700``) rather than a ``Vx.x`` software version, record the SKU in ``code`` and
leave ``model`` empty. A shipment that cites the software version (``V1.0``) then
matches it — the model is absent on one side, so it is not treated as a conflict.
(The recorded SKU is documentation only; the match rides on the canonical name plus
model-absence — a divergent SKU is not itself a discriminator here.)
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from shipment_review.extractors.transcript_agreement import module_rows_agree, transcripts_agree
from shipment_review.models import Contract, ContractItem, ModuleRow

TRANSCRIPT_SUFFIX = ".transcript.json"


class TranscriptError(Exception):
    """A transcript sidecar exists but is malformed (bad JSON, missing/typed fields)."""


def transcript_path(document: Path) -> Path:
    return document.with_name(document.name + TRANSCRIPT_SUFFIX)


def _as_number(value: object) -> float | None:
    """Coerce a hand-authored numeric field (often a string) to float."""
    if value is None or value == "":
        return None
    return float(value)


def _validate_transcript(name: str, data: dict, items: list[ContractItem]) -> None:
    """Hard-reject an authored transcript that is incomplete or internally inconsistent.

    A transcript is the trusted substitute for an unreadable scan, so it must be sound
    before the deterministic rules lean on it: a contract number, at least one priced
    item, and arithmetic that ties out (单价×数量 = 金额, and Σ = 合计 if a total is given).
    Raised as TranscriptError so the caller surfaces it as 需人工確認, never a silent pass.
    """
    if not (data.get("contract_number") and str(data["contract_number"]).strip()):
        raise TranscriptError(f"{name}: 缺少 contract_number")
    if not items:
        raise TranscriptError(f"{name}: 至少需要一個品項")
    for item in items:
        if item.unit_price is None or item.quantity is None:
            raise TranscriptError(f"{name}: 品項「{item.name}」缺少 unit_price/quantity")
        # Assumes lines tie out exactly (no line-level 优惠/discount where 金额≠单价×数量).
        # True for every contract in this dataset; a discounted line would hard-reject to
        # 需人工確認 — safe (never a silent bad pass), revisit if such contracts appear.
        if item.amount is not None and round(item.unit_price * item.quantity, 2) != round(item.amount, 2):
            raise TranscriptError(
                f"{name}: 品項「{item.name}」金額不符：{item.unit_price}×{item.quantity}≠{item.amount}"
            )
    total = _as_number(data.get("total"))
    if total is not None:
        computed = round(sum(item.unit_price * item.quantity for item in items), 2)
        if computed != round(total, 2):
            raise TranscriptError(f"{name}: 合計不符：Σ单价×数量={computed}≠total {total}")


def _items_from(data: dict) -> list[ContractItem]:
    return [
        ContractItem(
            code=entry.get("code"), name=entry["name"], model=entry.get("model"),
            unit=entry.get("unit"), quantity=_as_number(entry.get("quantity")),
            unit_price=_as_number(entry.get("unit_price")), amount=_as_number(entry.get("amount")),
        )
        for entry in data.get("items", [])
    ]


def load_contract_transcript(document: Path) -> Contract | None:
    """Return a Contract built from `<document>.transcript.json`, or None if absent.

    Raises TranscriptError when the sidecar exists but cannot be parsed, so the caller
    can surface a reason instead of crashing the whole review.
    """
    sidecar = transcript_path(document)
    if not sidecar.exists():
        return None
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TranscriptError(f"{sidecar.name}: {exc}") from exc

    authored_by = data.get("authored_by")
    try:
        if authored_by == "ai":
            content, ai_unconfirmed = _resolve_ai(sidecar, document, data)
        else:
            content = data
            ai_unconfirmed = not (authored_by == "human" or data.get("confirmed") is True)
        items = _items_from(content)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise TranscriptError(f"{sidecar.name}: {exc}") from exc

    _validate_transcript(sidecar.name, content, items)
    school = content.get("school_name") or data.get("school_name")
    return Contract(
        source_file=str(document), contract_number=content.get("contract_number"),
        buyer_name=content.get("buyer_name") or data.get("buyer_name"),
        seller_name=content.get("seller_name") or data.get("seller_name"),
        school_name=school, items=items, readable=True,
        school_names=[school] if school else [], ocr_extracted=False,
        ai_unconfirmed=ai_unconfirmed,
    )


def _resolve_ai(sidecar: Path, document: Path, data: dict) -> tuple[dict, bool]:
    """For an AI transcript: enforce sha256, re-compute two-pass agreement. Returns
    (content-dict used to build the contract, ai_unconfirmed)."""
    expected = data.get("source_sha256")
    if not expected:
        return data.get("pass_a") or {}, True  # no integrity proof → untrusted
    try:
        actual = hashlib.sha256(document.read_bytes()).hexdigest()
    except OSError as exc:
        raise TranscriptError(f"無法讀取合約檔以驗證 sha256：{exc}") from exc
    if actual != expected:
        raise TranscriptError(f"{sidecar.name}: source_sha256 不符（PDF 已變更，請重讀）")
    pass_a, pass_b = data.get("pass_a"), data.get("pass_b")
    if not pass_a or not pass_b:
        return pass_a or {}, True
    agree, _ = transcripts_agree(pass_a, pass_b)
    return pass_a, not agree


def _module_rows_from(data: dict, document: Path) -> list[ModuleRow]:
    rows: list[ModuleRow] = []
    for entry in data.get("rows", []):
        name = entry.get("product_name")
        if not (name and str(name).strip()):
            raise TranscriptError(f"{transcript_path(document).name}: 有一列缺少 product_name")
        rows.append(ModuleRow(
            source_file=str(document),
            contract_number=entry.get("contract_number"),
            purchasing_company=entry.get("purchasing_company"),
            product_name=name,
            model=entry.get("model"),
            unit=entry.get("unit"),
            quantity=_as_number(entry.get("quantity")),
            unit_price=_as_number(entry.get("unit_price")),
            amount=_as_number(entry.get("amount")),
            royalty=_as_number(entry.get("royalty")),
            code=entry.get("code"),
        ))
    return rows


def _validate_module_transcript(name: str, rows: list[ModuleRow]) -> None:
    if not rows:
        raise TranscriptError(f"{name}: 至少需要一列")
    for row in rows:
        if row.unit_price is not None and row.quantity is not None and row.amount is not None:
            if round(row.unit_price * row.quantity, 2) != round(row.amount, 2):
                raise TranscriptError(
                    f"{name}: 「{row.product_name}」金額不符：{row.unit_price}×{row.quantity}≠{row.amount}"
                )


def load_module_transcript(document: Path) -> list[ModuleRow] | None:
    """Return ModuleRow[] from `<module-table>.transcript.json`, or None if absent.

    AI two-pass only: authored_by:"ai" + pass_a + pass_b + source_sha256; loader recomputes
    agreement (module_rows_agree) and per-row arithmetic. Any bad sidecar RAISES
    TranscriptError (never a silent fallback) so the caller surfaces it and a present-but-bad
    sidecar reads as a gap, not as filled."""
    sidecar = transcript_path(document)
    if not sidecar.exists():
        return None
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TranscriptError(f"{sidecar.name}: {exc}") from exc
    if data.get("authored_by") != "ai":
        raise TranscriptError(f"{sidecar.name}: 模組表 transcript 必須為 authored_by:\"ai\" 兩次盲讀")
    pass_a, pass_b, expected = data.get("pass_a"), data.get("pass_b"), data.get("source_sha256")
    if not (pass_a and pass_b and expected):
        raise TranscriptError(f"{sidecar.name}: 缺少 pass_a/pass_b/source_sha256")
    try:
        actual = hashlib.sha256(document.read_bytes()).hexdigest()
    except OSError as exc:
        raise TranscriptError(f"無法讀取模組表檔以驗證 sha256：{exc}") from exc
    if actual != expected:
        raise TranscriptError(f"{sidecar.name}: source_sha256 不符（圖片已變更，請重讀）")
    agree, diffs = module_rows_agree(pass_a, pass_b)
    if not agree:
        raise TranscriptError(f"{sidecar.name}: 兩次盲讀不一致：{'; '.join(diffs[:3])}")
    rows = _module_rows_from(pass_a, document)
    _validate_module_transcript(sidecar.name, rows)
    return rows
