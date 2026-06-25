from __future__ import annotations

import re
import unicodedata

from shipment_review import config


_CONTRACT_RE = re.compile(rf"(?<![A-Z0-9]){config.CONTRACT_PREFIX}\d*[-－]\d{{8}}[-－]\d{{2}}(?![A-Z0-9])", re.IGNORECASE)
_PRODUCT_CODE_RE = re.compile(r"(?<![A-Z0-9])([A-Z]\d+)\s*[-－]\s*(\d+)(?![A-Z0-9])", re.IGNORECASE)


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKC", value).lower()
    normalized = normalized.replace("（", "(").replace("）", ")")
    return re.sub(r"[\s,，、:：;；()（）\-－_/]+", "", normalized)


def normalize_company(value: str | None) -> str:
    return normalize_text(value)


def normalize_money(value: str | int | float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    compact = unicodedata.normalize("NFKC", value)
    compact = re.sub(r"(人民币|RMB|CNY|元|¥|￥)", "", compact, flags=re.IGNORECASE)
    compact = re.sub(r"[,\s，]", "", compact)
    if not compact:
        return None
    try:
        return float(compact)
    except ValueError:
        return None


def extract_contract_numbers(text: str) -> list[str]:
    found = []
    for match in _CONTRACT_RE.finditer(text):
        value = unicodedata.normalize("NFKC", match.group(0)).upper().replace("－", "-")
        if value not in found:
            found.append(value)
    return found


def extract_product_code(text: str | None) -> str | None:
    if not text:
        return None
    match = _PRODUCT_CODE_RE.search(unicodedata.normalize("NFKC", text))
    if not match:
        return None
    return f"{match.group(1).upper()}-{match.group(2)}"


def normalize_contract_number(value: str | None) -> str | None:
    if not value:
        return None
    normalized = unicodedata.normalize("NFKC", value).upper().replace("－", "-")
    normalized = re.sub(r"\s+", "", normalized)
    return normalized or None


def product_key(code: str | None, name: str, model: str | None) -> str:
    model_part = normalize_text(model)
    if code:
        code_part = unicodedata.normalize("NFKC", code).lower()
        code_part = re.sub(r"[\s,，、:：;；()（）－_/]+", "", code_part)
        return f"code:{code_part}|model:{model_part}"
    return f"name:{normalize_text(name)}|model:{model_part}"


def product_match_keys(code: str | None, name: str | None, model: str | None) -> frozenset[str]:
    """Return the set of lookup keys for this product reference.

    Always includes a name+model key so that a code-bearing approval item and a
    code-less contract item can match on their shared name+model key.
    """
    model_part = normalize_text(model)
    keys = {f"name:{normalize_text(name)}|model:{model_part}"}
    if code:
        keys.add(f"code:{normalize_text(code)}|model:{model_part}")
    return frozenset(keys)


# Product names on space-less CJK can't be safely fuzzy-scored: a single-char OCR
# typo and a two-char edition swap land at indistinguishable similarities. So we
# match by EXACT equality after aggressive, deterministic canonicalization —
# stripping only true noise (序号 / spec-or-serial parentheticals / a code echo)
# and folding known OCR character confusions. Anything we cannot canonicalize to
# equality falls to manual review, which is the safe failure direction for a gate.

# Known OCR character confusions seen in real product names (deterministic map).
_OCR_NAME_CONFUSIONS = str.maketrans(config.OCR_NAME_CONFUSIONS)

# A leaked section marker on the front of a display name: 「（二）」 / 「（二）-1」 / 「（二）1、」.
_DISPLAY_SECTION_RE = re.compile(r"^[\s（(]*[一二三四五六七八九十]+[）)]\s*[-－]?\s*\d*\s*[、.．]?\s*")


def clean_display_name(name: str | None) -> str:
    """Tidy a product name for DISPLAY only (never for matching): drop a leaked section
    marker like 「（二）-1」 and fold the 桉→核 OCR confusion. Matching already canonicalizes
    these away, so this only affects what a human reads."""
    if not name:
        return ""
    return _DISPLAY_SECTION_RE.sub("", name).translate(_OCR_NAME_CONFUSIONS).strip()

# A parenthetical containing one of these names an edition/variant (different
# product) and is KEPT; any other parenthetical is a spec/serial and is stripped.
_EDITION_MARKERS = ("版", "型", "配", "款", "系列")

_CLOSED_PAREN_RE = re.compile(r"[（(]([^（()）]*)[）)]")
_OPEN_PAREN_RE = re.compile(r"[（(]([^（）)]*)$")
# 【…】 annotations (e.g. 授权 detail) are spec noise; the closing 】 is often line-
# or OCR-truncated, so handle the open form too.
_CLOSED_BRACKET_RE = re.compile(r"【([^【】]*)】")
_OPEN_BRACKET_RE = re.compile(r"【([^【】]*)$")
# A mis-split "1-1" row leaks a leading "-1" onto the next item's name.
_LEADING_DASH_NUM_RE = re.compile(r"^\s*[-－]\d+\s*")
# A 序号 index is N-N(-N…) with a trailing separator/space ("1-1 "), or a number
# with a dot/、 terminator ("1.", "1、"). A number glued straight onto a name is NOT
# an index (4K, 5G, 5-合一, 360全景, 4-6岁, 2-3年级).
_LEADING_INDEX_RE = re.compile(
    r"^\s*(?:\d+(?:\s*[-－.、]\s*\d+)+[\s.、]+|\d+\s*[.、]\s*)"
)
_LEADING_CODE_RE = re.compile(r"^[A-Za-z]{1,4}\d+(?:\s*[-－]\s*\d+)*\s+")

# Brand prefix and a trailing generic category word are pure noise: the same product
# is written "智核X系统" in one document and "X" in another. Stripping them (then exact
# match) is safe because any real discriminator — edition (专业版/基础版), version digit
# (ZClass5 vs 6) — lives in the middle and survives. Guarded by a minimum remaining
# length so a bare "系统"/"智核" is never stripped to nothing.
_BRAND_PREFIXES = (config.BRAND,)
_GENERIC_SUFFIXES = ("系统", "系統")
_MIN_CORE_AFTER_STRIP = 4


def _strip_brand_and_generic(core: str) -> str:
    brand_stripped = False
    for brand in _BRAND_PREFIXES:
        if core.startswith(brand) and len(core) - len(brand) >= _MIN_CORE_AFTER_STRIP:
            core = core[len(brand):]
            brand_stripped = True
            break
    # Strip a trailing generic category word ONLY when a brand was present, matching the
    # motivation ("智核X系统" vs "X"). A brandless "X系统" vs "X" is left un-merged — it
    # could be a distinct hardware-vs-system SKU, so it falls to manual review (safe).
    if brand_stripped:
        for suffix in _GENERIC_SUFFIXES:
            if core.endswith(suffix) and len(core) - len(suffix) >= _MIN_CORE_AFTER_STRIP:
                core = core[: -len(suffix)]
                break
    return core


def _has_edition_marker(text: str) -> bool:
    return any(marker in text for marker in _EDITION_MARKERS)


def _strip_spec_parentheticals(text: str) -> str:
    """Drop spec/serial （）/【】 annotations; keep edition/variant ones (they discriminate)."""
    for closed, open_re in ((_CLOSED_PAREN_RE, _OPEN_PAREN_RE), (_CLOSED_BRACKET_RE, _OPEN_BRACKET_RE)):
        text = closed.sub(lambda m: m.group(0) if _has_edition_marker(m.group(1)) else "", text)
        open_match = open_re.search(text)  # OCR/line break may have dropped the closing ）/】
        if open_match and not _has_edition_marker(open_match.group(1)):
            text = text[: open_match.start()]
    return text


def _strip_leading_code_echo(text: str, code: str | None) -> tuple[str, bool]:
    """Strip a leading alphanumeric token only when it echoes the `code` field.

    The contract parser sometimes glues the code onto the front of the name
    ("C5-2-1 智核…"). That token belongs to the code field, but stripping it
    removes a potential discriminator, so we report whether it fired.
    """
    if not code:
        return text, False
    match = _LEADING_CODE_RE.match(text)
    if not match:
        return text, False
    lead, nc = normalize_text(match.group(0)), normalize_text(code)
    if lead == nc or lead.startswith(nc) or nc.startswith(lead):
        return text[match.end():], True
    return text, False


def _product_name_core(name: str | None, code: str | None = None) -> tuple[str, bool]:
    """Return (canonical core, whether a leading code echo was stripped)."""
    if not name:
        return "", False
    core = _strip_spec_parentheticals(name)
    # A 序号 and a leaked sub-index can stack ("1、-1名称"); stripping the 序号 exposes
    # the dash leak, so repeat both until the prefix is stable.
    while True:
        stripped = _LEADING_INDEX_RE.sub("", core)
        stripped = _LEADING_DASH_NUM_RE.sub("", stripped)
        if stripped == core:
            break
        core = stripped
    core, code_stripped = _strip_leading_code_echo(core, code)
    core = core.translate(_OCR_NAME_CONFUSIONS)
    return _strip_brand_and_generic(normalize_text(core)), code_stripped


# Trailing software-version token (v5.0, v1.0, v5 ...) of a normalized model.
_MODEL_VERSION_RE = re.compile(r"v\d+(?:\.\d+)*$")


def _model_version(normalized_model: str) -> str | None:
    """The trailing version token of an already-normalized model, or None.

    A contract's 型号 column often echoes the full product name before the version
    (``智核zclass5专业版系统v5.0``) while the module-fee table / approval carry only
    the version (``v5.0``). The version is the discriminating tail; the name echo is
    noise already guarded by the exact core-name comparison in ``products_match``.
    """
    match = _MODEL_VERSION_RE.search(normalized_model)
    return match.group(0) if match else None


def _models_compatible(model_a: str | None, model_b: str | None) -> bool:
    """Models match when both normalize equal, or at least one is absent, or both
    carry the same trailing version token (one side echoing the product name first).

    One side often omits the model (the approval frequently does) while the other
    carries it; treating absence as agreement avoids false negatives there. When both
    carry a version token, compare versions and ignore any product-name echo — so a
    contract line ``智核…系统v5.0`` matches a module row ``v5.0`` (same v5.0) but a
    genuine version difference (v5.0 vs v6.0) stays incompatible.
    """
    na, nb = normalize_text(model_a), normalize_text(model_b)
    if not na or not nb:
        return True
    if na == nb:
        return True
    va, vb = _model_version(na), _model_version(nb)
    # Only ignore a prefix when the OTHER side is a bare version — the real data shape
    # (module row "v5.0" vs contract "<name>v5.0"). If BOTH carry a prefix, that prefix
    # is a discriminator (a SKU like RF-35 vs RF-55), not a name echo, so compare strictly.
    if va and vb and (va == na or vb == nb):
        return va == vb
    return False


# Single-character units seen in this domain. Containment counts as an OCR merge
# only when every character of the longer unit is one of these — so a true merge
# (年套 = 年 + 套) is tolerated but a multiplier prefix (千克 vs 克) or unrelated
# superstring (套装 vs 套, 个人 vs 个) is not.
_SINGLE_UNITS = set("年套个個台件块塊月份张張只隻项項次根箱批组組盒条條本")


def units_compatible(unit_a: str | None, unit_b: str | None) -> bool:
    """Units are compatible when either is absent, they are equal, or one is an
    OCR merge of units containing the other. The module-fee table is OCR'd from a
    thin image, where two rows' units get merged (年 read as 年套) or one is dropped
    — neither is a real conflict. A genuine difference (年 vs 套) stays incompatible."""
    na, nb = normalize_text(unit_a), normalize_text(unit_b)
    if not na or not nb:
        return True
    if na == nb:
        return True
    short, long = sorted((na, nb), key=len)
    return short in long and all(ch in _SINGLE_UNITS for ch in long)


def _codes_compatible(code_a: str | None, code_b: str | None) -> bool:
    """Codes are compatible when absent on a side, equal, or one is the other's
    prefix (C5-2 vs the contract sub-index C5-2-1). A genuine difference (C5-2 vs
    C5-3) is incompatible."""
    ca, cb = normalize_text(code_a), normalize_text(code_b)
    if not ca or not cb:
        return True
    return ca == cb or ca.startswith(cb) or cb.startswith(ca)


def products_match(
    code_a: str | None, name_a: str | None, model_a: str | None,
    code_b: str | None, name_b: str | None, model_b: str | None,
) -> bool:
    """Return True when two product references refer to the same product.

    Match when either:
    - the key sets intersect (codes (+ model) match, or name+model match), OR
    - models are compatible AND the canonical core names are exactly equal, with
      one guard: if a leading code echo was stripped from either name, the codes
      themselves were a discriminator, so they must be compatible. (When no code
      echo was stripped, divergent codes are treated as OCR noise — e.g. AI服务
      coded T5-3 vs TS-3-1.)

    There is no fuzzy scoring: identity is exact after canonicalization, so an
    edition/version/spec difference can never produce a false 可出貨.
    """
    if product_match_keys(code_a, name_a, model_a) & product_match_keys(code_b, name_b, model_b):
        return True
    if not _models_compatible(model_a, model_b):
        return False
    core_a, stripped_a = _product_name_core(name_a, code_a)
    core_b, stripped_b = _product_name_core(name_b, code_b)
    if not core_a or not core_b or core_a != core_b:
        return False
    if stripped_a or stripped_b:
        return _codes_compatible(code_a, code_b)
    return True


# --- OCR-tolerant identifier helpers ---

# Characters OCR commonly swaps in product codes / models.
_CODE_CONFUSIONS = {"$": "S"}
_MODEL_CONFUSIONS = {"W": "V"}

# The digits part of a contract number is reliable; the alpha prefix is not.
_CONTRACT_CORE_RE = re.compile(r"([A-Z]+\d*)[-－]?(\d{8})[-－]?(\d{2})", re.IGNORECASE)
_CANONICAL_CONTRACT_PREFIX = config.CONTRACT_PREFIX


def ocr_canonical_code(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = unicodedata.normalize("NFKC", value).strip().upper()
    if not cleaned:
        return None
    first, rest = cleaned[0], cleaned[1:]
    first = _CODE_CONFUSIONS.get(first, first)
    return first + rest


def ocr_canonical_model(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = unicodedata.normalize("NFKC", value).strip().upper()
    if not cleaned:
        return None
    first, rest = cleaned[0], cleaned[1:]
    first = _MODEL_CONFUSIONS.get(first, first)
    return first + rest


def contract_number_candidates(value: str | None) -> list[str]:
    """Return plausible canonical contract numbers for an OCR'd value.

    The 8-digit date and 2-digit suffix are trusted; the alpha prefix is
    repaired toward the canonical ``ZHDEMO`` because OCR drops/inserts letters
    there (ZDEMO, TIDYX, ...).
    """
    if not value:
        return []
    text = unicodedata.normalize("NFKC", value).upper().replace("－", "-")
    match = _CONTRACT_CORE_RE.search(text)
    if not match:
        return []
    prefix, date, suffix = match.group(1), match.group(2), match.group(3)
    canonical = f"{_CANONICAL_CONTRACT_PREFIX}-{date}-{suffix}"
    as_read = f"{prefix}-{date}-{suffix}"
    candidates = [as_read]
    if canonical not in candidates:
        candidates.append(canonical)
    return candidates


def contract_numbers_match(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    left_keys = set(contract_number_candidates(left))
    right_keys = set(contract_number_candidates(right))
    if left_keys & right_keys:
        return True
    # Fall back to trusting the date+suffix core when prefixes differ by OCR.
    return _contract_core(left) is not None and _contract_core(left) == _contract_core(right)


def _contract_core(value: str | None) -> tuple[str, str] | None:
    if not value:
        return None
    match = _CONTRACT_CORE_RE.search(unicodedata.normalize("NFKC", value).upper())
    return (match.group(2), match.group(3)) if match else None
