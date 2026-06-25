from __future__ import annotations

from shipment_review import config

import re
from pathlib import Path

from shipment_review.extractors.text import Extraction, OcrToken, rows_from_tokens
from shipment_review.models import Contract, ContractItem
from shipment_review.normalization import (
    _CONTRACT_RE,
    extract_contract_numbers,
    extract_product_code,
    normalize_money,
    ocr_canonical_code,
    ocr_canonical_model,
)

MODEL_RE = re.compile(r"(V\d+(?:\.\d+)?|W\d+(?:\.\d+)?|IRS[A-Z]*-?\d+[A-Z0-9-]*)", re.IGNORECASE)
MONEY_RE = re.compile(r"[¥￥$]?\s*\d[\d,]*(?:\.\d+)?")
COLUMN_KEYS = {
    "name": ("名称", "產品", "产品", "项目", "項目"),
    "model": ("型号", "型號", "规格", "規格"),
    "quantity": ("数量", "數量"),
    "unit": ("单位", "單位"),
    "unit_price": ("单价", "單價"),
    "amount": ("金额", "金額"),
}


def parse_contract(extraction: Extraction, source_file: Path, attached_files: list[str]) -> Contract:
    text = extraction.text
    buyer_name = _search(r"(?:单位名称|甲方（买方）|采购方)[:：]?\s*([^\s\n]*?(?:有限公司|公司|学校|学院|研究院))", text)
    seller_name = _search(r"(?:供应商（乙方）|乙方（卖方）|销售方)[:：]?\s*([^\s\n]*?(?:有限公司|公司|学校|学院|研究院))", text)
    school_names = _all_schools(text)
    contract_number = _contract_number(text, source_file, attached_files)

    if extraction.tokens:
        items = _items_from_tokens(extraction.tokens)
    else:
        items = _items_from_text(text)

    readable = bool(text.strip()) or bool(extraction.tokens)
    return Contract(
        source_file=str(source_file),
        contract_number=contract_number,
        buyer_name=buyer_name,
        seller_name=seller_name,
        school_name=school_names[0] if school_names else None,
        items=items,
        readable=readable,
        school_names=school_names,
        ocr_extracted=bool(extraction.tokens),
    )


def _items_from_tokens(tokens: list[OcrToken]) -> list[ContractItem]:
    rows = rows_from_tokens(tokens)
    header_index, columns = _find_header(rows)
    if header_index is None:
        return _items_from_text("\n".join(" ".join(t.text for t in row) for row in rows))
    body_rows = rows[header_index + 1 :]
    row_texts = [" ".join(token.text for token in row) for row in body_rows]
    end = _table_end_index(row_texts)
    items: list[ContractItem] = []
    for row, row_text in zip(body_rows[:end], row_texts[:end]):
        if _TABLE_TOTAL_RE.match(row_text) or _TABLE_SUBTOTAL_RE.match(row_text):
            continue
        if not _MONEY_TOKEN_RE.search(row_text):
            continue
        items.append(_row_to_item(row, columns))
    return items


def _find_header(rows: list[list[OcrToken]]) -> tuple[int | None, dict[str, float]]:
    for index, row in enumerate(rows):
        columns: dict[str, float] = {}
        for token in row:
            field = _best_field(token.text)
            if field is not None and field not in columns:
                columns[field] = token.x
        if "name" in columns and ("unit_price" in columns or "amount" in columns):
            return index, columns
    return None, {}


def _best_field(text: str) -> str | None:
    """Assign a header token to the field whose marker matches most specifically.

    Prevents a column like ``采购公司名称`` from being claimed by ``product_name``
    via the bare ``名称`` substring before the real ``产品名称`` column is seen.
    """
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


def _row_to_item(row: list[OcrToken], columns: dict[str, float]) -> ContractItem:
    fields = _bucket_row_by_columns(row, columns)
    name = fields.get("name")
    model_token = fields.get("model")
    model = _model(model_token) or _model(name)
    quantity = _to_number(fields.get("quantity"))
    unit = fields.get("unit")
    unit_price = _money(fields.get("unit_price"))
    amount = _money(fields.get("amount"))
    code = ocr_canonical_code(extract_product_code(" ".join(t.text for t in row)))
    clean_name = _strip_leading_serial_and_code(name).strip() if name else name
    return ContractItem(
        name=clean_name or name or " ".join(t.text for t in row),
        model=model,
        unit=unit,
        quantity=quantity,
        unit_price=unit_price,
        code=code,
        amount=amount,
    )


# A per-section subtotal (小计) does NOT end the table; only a grand total does.
_TABLE_TOTAL_RE = re.compile(r"^\s*(合计|合計|总计|總計)")
_TABLE_SUBTOTAL_RE = re.compile(r"^\s*(小计|小計)")
# Money has a currency mark, a decimal, or thousands grouping — a bare integer
# (quantity, a 序号, a digit inside a code) is not money.
_MONEY_TOKEN_RE = re.compile(r"[¥￥$]\s*\d[\d,]*(?:\.\d+)?|\d[\d,]*\.\d+|\d{1,3}(?:,\d{3})+")
_UNIT_CHARS = "年套个個台件块塊份月根箱批项項人次张張只隻"
_TRAILING_QTY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*$")
_TRAILING_UNIT_RE = re.compile(r"([" + _UNIT_CHARS + r"])\s*$")
_LEADING_ROW_NUMBER_RE = re.compile(r"^\s*\d+(?:\s*[-－]\s*\d+)*\s+")
# A leading product code: letters then digit groups joined by dashes — covers both
# "C5-2-1" (letter+digit) and "TS-3-1" (letters then -digit).
_LEADING_CODE_RE = re.compile(r"^[A-Za-z]{1,4}\d*(?:\s*[-－]\s*\d+)+\s+")
# A table header names the product column and a price/amount column. 序号 is
# optional — some native contracts omit it.
_HEADER_NAME_MARKERS = ("品项名称", "品名", "名称", "名稱", "项目", "項目", "产品", "產品")
_HEADER_PRICE_MARKERS = ("单价", "單價", "金额", "金額")


def _strip_leading_serial_and_code(text: str) -> str:
    """Drop a leading 序号 and a leading product-code token, but keep a leading
    model token (IRS-300, V5-2) which `_model` needs and which identifies the item."""
    text = _LEADING_ROW_NUMBER_RE.sub("", text)
    code_match = _LEADING_CODE_RE.match(text)
    if code_match and not MODEL_RE.match(code_match.group(0).strip()):
        text = text[code_match.end() :]
    return text


def _items_from_text(text: str) -> list[ContractItem]:
    lines = text.splitlines()
    header_index = _text_header_index(lines)
    if header_index is not None:
        return _items_from_text_table(lines, header_index)
    return _items_from_text_by_keyword(lines)


def _text_header_index(lines: list[str]) -> int | None:
    """Index of the item-table header (a product column plus a price/amount column).

    A real header carries column labels, never money — so a money-bearing summary
    line (项目总金额 ¥3.00) is not mistaken for the header.
    """
    for index, line in enumerate(lines):
        if _MONEY_TOKEN_RE.search(line):
            continue
        if any(n in line for n in _HEADER_NAME_MARKERS) and any(
            p in line for p in _HEADER_PRICE_MARKERS
        ):
            return index
    return None


def _table_end_index(row_texts: list[str]) -> int:
    """Rows up to (and excluding) the LAST grand total are the item table; a
    per-section 合计/小计 before it does not end the table."""
    totals = [i for i, text in enumerate(row_texts) if _TABLE_TOTAL_RE.match(text)]
    return totals[-1] if totals else len(row_texts)


def _items_from_text_table(lines: list[str], header_index: int) -> list[ContractItem]:
    body = lines[header_index + 1 :]
    end = _table_end_index(body)
    items: list[ContractItem] = []
    for line in body[:end]:
        if _TABLE_TOTAL_RE.match(line) or _TABLE_SUBTOTAL_RE.match(line):
            continue
        if not _MONEY_TOKEN_RE.search(line):
            continue
        items.append(_text_table_row_to_item(line))
    return items


def _text_table_row_to_item(line: str) -> ContractItem:
    monies = _MONEY_TOKEN_RE.findall(line)
    amount = _clean_money(monies[-1]) if monies else None
    unit_price = _clean_money(monies[-2]) if len(monies) >= 2 else None

    first_money = _MONEY_TOKEN_RE.search(line)
    head = line[: first_money.start()] if first_money else line
    code = ocr_canonical_code(extract_product_code(head))
    model = _model(head)

    body = _strip_leading_serial_and_code(head)
    body = body.strip()
    quantity = None
    qty_match = _TRAILING_QTY_RE.search(body)
    if qty_match:
        quantity = float(qty_match.group(1))
        body = body[: qty_match.start()].strip()
    unit = None
    unit_match = _TRAILING_UNIT_RE.search(body)
    if unit_match:
        unit = unit_match.group(1)
        body = body[: unit_match.start()].strip()

    return ContractItem(
        name=body or head.strip(),
        model=model,
        unit=unit,
        quantity=quantity,
        unit_price=unit_price,
        code=code,
        amount=amount,
    )


def _clean_money(token: str) -> float | None:
    return normalize_money(token.lstrip("¥￥$ "))


def _items_from_text_by_keyword(lines: list[str]) -> list[ContractItem]:
    items: list[ContractItem] = []
    for line in lines:
        if not any(kw in line for kw in config.PRODUCT_KEYWORDS):
            continue
        numbers = re.findall(r"\d+(?:\.\d+)?", line)
        unit_price = normalize_money(numbers[-2]) if len(numbers) >= 2 else None
        quantity = float(numbers[-3]) if len(numbers) >= 3 else None
        amount = normalize_money(numbers[-1]) if numbers else None
        items.append(
            ContractItem(
                name=line.strip(),
                model=_model(line),
                unit=None,
                quantity=quantity,
                unit_price=unit_price,
                code=ocr_canonical_code(extract_product_code(line)),
                amount=amount,
            )
        )
    return items


def _file_match_key(name: str) -> str:
    """Normalize a contract filename so the approval's reference and the on-disk name
    resolve to the same key, despite the ways the two drift apart: drop the extension, any
    contract-number token, a leading 双章/盖章/公章 seal marker, each ``(N)`` copy-suffix /
    複製/副本/复制, and whitespace. Lets us tell whether an attached-file entry names THIS
    contract regardless of a leading number, seal note, or copy noise."""
    stem = Path(name).stem
    # Strip the number FIRST so a "ZHDEMO-…（双章）公司" name leaves the seal marker at
    # position 0 where the anchored seal pattern can remove it next.
    stem = _CONTRACT_RE.sub("", stem)
    stem = re.sub(r"^\s*[（(](?:双章|雙章|盖章|蓋章|公章)[)）]", "", stem)
    # Copy noise: a numeric index or a 複製/副本/复制 word, in half- or full-width parens.
    stem = re.sub(r"[（(]\d+[)）]|[（(]?(?:複製|複制|副本|复制)[)）]?", "", stem)
    return re.sub(r"\s+", "", stem)


def _contract_number(text: str, source_file: Path, attached_files: list[str]) -> str | None:
    for source in (text, source_file.name):
        numbers = extract_contract_numbers(source)
        if numbers:
            return numbers[0]
    # Last resort: the approval's attached-file reference may carry the number when both the
    # scan and the on-disk name lack it. Use ONLY the attached entry that names THIS contract
    # — never a sibling's. With several contracts in one folder, the old blind scan over all
    # attached_files returned attached_files[0], stealing another contract's number (0610:
    # 代理商乙 inherited 代理商甲's ZHDEMO-20251124-01, colliding both contracts on one number).
    own_key = _file_match_key(source_file.name)
    for attached in attached_files:
        if _file_match_key(attached) == own_key:
            numbers = extract_contract_numbers(attached)
            if numbers:
                return numbers[0]
    return None


def _all_schools(text: str) -> list[str]:
    raw = _search(r"(?:学校完整名称|学校全称|學校完整名稱)[:：]?\s*([^\n]+)", text)
    if not raw:
        return []
    return [part.strip() for part in re.split(r"[、,，]", raw) if part.strip()]


def _model(value: str | None) -> str | None:
    if not value:
        return None
    match = MODEL_RE.search(value)
    return ocr_canonical_model(match.group(1)) if match else None


def _money(value: str | None) -> float | None:
    if not value:
        return None
    match = MONEY_RE.search(value)
    return normalize_money(match.group(0).lstrip("¥￥$ ")) if match else None


def _to_number(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"\d+(?:\.\d+)?", value)
    return float(match.group(0)) if match else None


def _search(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(1).strip() if match else None
