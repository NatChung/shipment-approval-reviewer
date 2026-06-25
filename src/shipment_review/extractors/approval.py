from __future__ import annotations

from shipment_review import config

import re
from pathlib import Path

from shipment_review.models import Approval, ShipmentItem
from shipment_review.normalization import extract_contract_numbers, extract_product_code, normalize_money

APPROVER_RE = re.compile(r"【(?P<role>[^】]+)】[^\n]*?(?P<status>已同意|不同意|驳回|拒绝|退回)")
COMMENT_MARKER = config.COMMENT_MARKER
FIELD_MARKERS = ("实际出货", "出货内容")
CONSOLIDATED_MARKERS = ("综上合计", "綜上合計")
ITEM_STOP_MARKERS = ("收货地址", "收货人", "收货人电话", "期望到货", "备注", "審批流程", "审批流程", "用釘釘")
MODEL_RE = re.compile(r"(V\d+(?:\.\d+)?|IRS[A-Z]*-?\d+[A-Z0-9-]*)", re.IGNORECASE)
QTY_UNIT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(套|个|個|組|组|台|支|件|年|套餐)")


def parse_approval_text(text: str, source_file: Path) -> Approval:
    approval_code = _search(r"審批編碼\s*(\d+)", text) or _search(r"审批编码\s*(\d+)", text)
    contract_numbers = extract_contract_numbers(text)
    shipment_companies = _split_names(_search(r"出货公司名称\s*([^\n]+)", text) or "")
    shipment_amount = normalize_money(
        _search(r"出货金额[（(][^）)]*[）)]\s*([\d,]+(?:\.\d+)?)", text)
        or _search(r"出货金额\s*([\d,]+(?:\.\d+)?)", text)
    )
    school_name = _search(r"(?:学校全称|学校完整名称|学校名称)[:：]\s*([^\s；;。，、]+)", text)
    approver_statuses = {m.group("role"): m.group("status") for m in APPROVER_RE.finditer(text)}

    original_field_items = _items_from_block(_field_item_block(text), source="field")
    comment_items = _items_from_block(_comment_item_block(text), source="comment")
    actual_items = comment_items or original_field_items
    attached_contract_files = re.findall(r"[^\s\n]+\.pdf", text, flags=re.IGNORECASE)

    return Approval(
        source_file=str(source_file),
        approval_code=approval_code,
        contract_numbers=contract_numbers,
        shipment_companies=shipment_companies,
        school_name=school_name,
        actual_items=actual_items,
        approver_statuses=approver_statuses,
        shipment_amount=shipment_amount,
        attached_contract_files=attached_contract_files,
        original_field_items=original_field_items,
        comment_items=comment_items,
    )


def _comment_item_block(text: str) -> list[str]:
    if COMMENT_MARKER in text:
        return _collect_item_lines(text.split(COMMENT_MARKER, 1)[1])
    return []


def _field_item_block(text: str) -> list[str]:
    for marker in FIELD_MARKERS:
        if marker in text:
            tail = text.split(marker, 1)[1]
            # A multi-contract approval repeats each item per contract and then once
            # more under a 综上合计 consolidated total; keep only the consolidated list.
            for consolidated in CONSOLIDATED_MARKERS:
                if consolidated in tail:
                    tail = tail.split(consolidated, 1)[1]
                    break
            return _collect_item_lines(tail)
    return []


def _collect_item_lines(tail: str) -> list[str]:
    collected: list[str] = []
    for line in tail.splitlines():
        stripped = line.strip().lstrip("为：:").strip()
        if not stripped:
            continue
        if any(stop in stripped for stop in ITEM_STOP_MARKERS):
            break
        collected.append(stripped)
    return collected


def _items_from_block(lines: list[str], source: str) -> list[ShipmentItem]:
    return [_parse_shipment_item(line, source) for line in lines if _looks_like_item(line)]


def _parse_shipment_item(line: str, source: str) -> ShipmentItem:
    code = extract_product_code(line)
    model_match = MODEL_RE.search(line)
    model = model_match.group(1).upper() if model_match else None
    qty_match = QTY_UNIT_RE.search(line)
    quantity = float(qty_match.group(1)) if qty_match else None
    unit = qty_match.group(2) if qty_match else None

    name = line
    if code:
        name = name.replace(code, "", 1)
    name = re.sub(r"^[\s、,，.]+", "", name)
    name = QTY_UNIT_RE.sub("", name, count=1)
    if model:
        name = re.sub(re.escape(model), "", name, count=1, flags=re.IGNORECASE)
    name = name.replace("，", "").replace(",", "").strip()
    return ShipmentItem(code=code, name=name, model=model, unit=unit, quantity=quantity, source=source)


def _looks_like_item(line: str) -> bool:
    return bool(extract_product_code(line) or any(kw in line for kw in config.PRODUCT_KEYWORDS))


def _search(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(1).strip() if match else None


def _split_names(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[、,，]", value) if part.strip()]
