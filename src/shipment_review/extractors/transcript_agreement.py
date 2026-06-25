"""Compare two independent AI reads of the same scanned contract. Agreement is the
trust signal for an AI transcript; this is re-computed by the loader, never trusted
from a self-asserted flag in the file."""
from __future__ import annotations

_ITEM_FIELDS = ("code", "name", "model", "unit", "quantity", "unit_price", "amount")


def _norm(value: object) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)):
        return f"{float(value):.4f}"
    return str(value).strip()


def transcripts_agree(a: dict, b: dict) -> tuple[bool, list[str]]:
    diffs: list[str] = []
    if _norm(a.get("contract_number")) != _norm(b.get("contract_number")):
        diffs.append(f"contract_number: {a.get('contract_number')!r} vs {b.get('contract_number')!r}")
    items_a = a.get("items", []) or []
    items_b = b.get("items", []) or []
    if len(items_a) != len(items_b):
        diffs.append(f"item count: {len(items_a)} vs {len(items_b)}")
    else:
        for i, (ia, ib) in enumerate(zip(items_a, items_b)):
            for field in _ITEM_FIELDS:
                if _norm(ia.get(field)) != _norm(ib.get(field)):
                    diffs.append(f"item[{i}].{field}: {ia.get(field)!r} vs {ib.get(field)!r}")
    return (not diffs, diffs)


_MODULE_ROW_FIELDS = ("contract_number", "purchasing_company", "product_name", "model", "unit", "quantity", "unit_price", "amount")


def module_rows_agree(a: dict, b: dict) -> tuple[bool, list[str]]:
    """Agreement for two blind reads of a module-fee table. Compares SORTED full-field
    tuples (NOT product_key — the engine groups multiple rows per product_key, so keying
    would collapse them); order-insensitive, count-sensitive, divergence-sensitive."""
    rows_a = a.get("rows", []) or []
    rows_b = b.get("rows", []) or []
    if len(rows_a) != len(rows_b):
        return (False, [f"row count: {len(rows_a)} vs {len(rows_b)}"])
    def _key(r: dict) -> tuple[str, ...]:
        return tuple(_norm(r.get(f)) for f in _MODULE_ROW_FIELDS)
    sorted_a = sorted(_key(r) for r in rows_a)
    sorted_b = sorted(_key(r) for r in rows_b)
    diffs = [f"row[{i}]: {ta} vs {tb}" for i, (ta, tb) in enumerate(zip(sorted_a, sorted_b)) if ta != tb]
    return (not diffs, diffs)
