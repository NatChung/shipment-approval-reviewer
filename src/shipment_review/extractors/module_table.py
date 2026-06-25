from __future__ import annotations

from shipment_review import config

import re
from pathlib import Path

from shipment_review.extractors.text import Extraction, OcrToken, rows_from_tokens
from shipment_review.models import ModuleRow
from shipment_review.normalization import (
    extract_contract_numbers,
    extract_product_code,
    normalize_money,
    ocr_canonical_code,
    ocr_canonical_model,
)

COLUMN_KEYS = {
    "contract_number": ("合同单号", "合同單號", "订单号", "訂單號"),
    "region": ("区域", "區域"),
    "sales": ("销售经理", "銷售經理"),
    "purchasing_company": ("采购公司", "採購公司", "出货单位", "出貨單位", "公司名称"),
    "product_name": ("产品名称", "產品名稱", "项目", "項目", "名称"),
    "model": ("型号", "型號", "规格", "規格"),
    "unit": ("单位", "單位"),
    "quantity": ("数量", "數量", "数", "數"),
    "unit_price": ("单价", "單價", "终端", "終端"),
    "amount": ("金额", "金額", "总价", "總價"),
    "royalty": ("权益金", "權益金", "模组金", "模組金"),
}
CONTRACT_TOKEN_RE = re.compile(r"[A-Z$][A-Z0-9$]*[-－]?\d{8}[-－]?\d{2}", re.IGNORECASE)
MODEL_RE = re.compile(r"(V\d+(?:\.\d+)?|W\d+(?:\.\d+)?)", re.IGNORECASE)


def parse_module_table(extraction: Extraction, source_file: Path) -> list[ModuleRow]:
    if not extraction.tokens:
        return _rows_from_text(extraction.text, source_file)
    rows = rows_from_tokens(extraction.tokens)
    header_index, columns = _find_header(rows)
    if header_index is None:
        return _rows_from_text(extraction.text, source_file)
    parsed: list[ModuleRow] = []
    for row in rows[header_index + 1 :]:
        module_row = _row_to_module_row(row, columns, source_file)
        if module_row is not None:
            parsed.append(module_row)
    return parsed


def _find_header(rows: list[list[OcrToken]]) -> tuple[int | None, dict[str, float]]:
    for index, row in enumerate(rows):
        columns: dict[str, float] = {}
        for token in row:
            field = _best_field(token.text)
            if field is not None and field not in columns:
                columns[field] = token.x
        if "contract_number" in columns and "product_name" in columns:
            return index, columns
    return None, {}


def _best_field(text: str) -> str | None:
    """Assign a header token to the field whose marker matches most specifically,
    so ``采购公司名称`` is not stolen by ``product_name``'s bare ``名称`` marker."""
    best_field, best_len = None, 0
    for field, markers in COLUMN_KEYS.items():
        for marker in markers:
            if marker in text and len(marker) > best_len:
                best_field, best_len = field, len(marker)
    return best_field


def _bucket_row_by_columns(row: list[OcrToken], columns: dict[str, float]) -> dict[str, str]:
    buckets: dict[str, list[OcrToken]] = {}
    for token in row:
        field = min(columns, key=lambda f: abs(columns[f] - token.x))
        buckets.setdefault(field, []).append(token)
    return {
        field: " ".join(t.text for t in sorted(toks, key=lambda t: t.x))
        for field, toks in buckets.items()
    }


def _row_to_module_row(row: list[OcrToken], columns: dict[str, float], source_file: Path) -> ModuleRow | None:
    fields = _bucket_row_by_columns(row, columns)
    contract_text = fields.get("contract_number")
    if not contract_text or not CONTRACT_TOKEN_RE.search(contract_text):
        return None
    product_name = fields.get("product_name") or ""
    if not product_name:
        return None
    model_text = fields.get("model")
    return ModuleRow(
        source_file=str(source_file),
        contract_number=contract_text,
        purchasing_company=fields.get("purchasing_company"),
        product_name=product_name,
        model=ocr_canonical_model(_first_model(model_text or product_name)),
        unit=fields.get("unit"),
        quantity=_to_number(fields.get("quantity")),
        unit_price=normalize_money(fields.get("unit_price")),
        amount=normalize_money(fields.get("amount")),
        royalty=normalize_money(fields.get("royalty")),
        code=ocr_canonical_code(extract_product_code(" ".join(t.text for t in row))),
    )


def _rows_from_text(text: str, source_file: Path) -> list[ModuleRow]:
    rows: list[ModuleRow] = []
    for line in text.splitlines():
        numbers = extract_contract_numbers(line)
        if not numbers:
            continue
        parts = line.split()
        numeric = [p for p in parts if re.fullmatch(r"\d+(?:\.\d+)?", p)]
        rows.append(
            ModuleRow(
                source_file=str(source_file),
                contract_number=numbers[0],
                purchasing_company=None,
                product_name=next((p for p in parts if config.BRAND in p), line.strip()),
                model=ocr_canonical_model(_first_model(line)),
                unit=None,
                quantity=float(numeric[-4]) if len(numeric) >= 4 else None,
                unit_price=normalize_money(numeric[-3]) if len(numeric) >= 3 else None,
                amount=normalize_money(numeric[-2]) if len(numeric) >= 2 else None,
                royalty=normalize_money(numeric[-1]) if numeric else None,
                code=ocr_canonical_code(extract_product_code(line)),
            )
        )
    return rows


def _first_model(value: str | None) -> str | None:
    if not value:
        return None
    match = MODEL_RE.search(value)
    return match.group(1) if match else None


def _to_number(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"\d+(?:\.\d+)?", value)
    return float(match.group(0)) if match else None
