"""Client-specific identifiers, overridable via environment or a `.env` file.

This is a public sample repo, so the committed defaults are SYNTHETIC (fictional
vendor `智核` / contract prefix `ZHDEMO`). To run against a real document set,
drop a git-ignored `.env` at the repo root (see `.env.example`) — its values
override the defaults below. The matching/verdict logic itself is unchanged.
"""
from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv() -> None:
    """Minimal, dependency-free `.env` loader: KEY=VALUE lines → os.environ
    (never overrides an already-set variable)."""
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def _get(name: str, default: str) -> str:
    return os.environ.get(name, default)


# Vendor/brand prefix stripped during canonical product-name matching.
BRAND = _get("SAR_BRAND", "智核")

# Canonical contract-number alpha prefix (the digits are trusted; the prefix is
# repaired toward this value when OCR drops/inserts letters).
CONTRACT_PREFIX = _get("SAR_CONTRACT_PREFIX", "ZHDEMO")

# Keywords that mark a line as a goods/item row (brand + a generic hardware term).
PRODUCT_KEYWORDS = tuple(k for k in _get("SAR_PRODUCT_KEYWORDS", "智核,接收终端").split(",") if k)

# The approval form's "actual shipment" comment marker.
COMMENT_MARKER = _get("SAR_COMMENT_MARKER", "智核产品实际出货内容")


def _parse_confusions(spec: str) -> dict[str, str]:
    """`"A:B,C:D"` → {"A":"B","C":"D"} — single-character OCR look-alike folds."""
    out: dict[str, str] = {}
    for pair in spec.split(","):
        pair = pair.strip()
        if ":" in pair:
            a, b = pair.split(":", 1)
            if a and b:
                out[a] = b
    return out


# OCR character confusions seen in product names (deterministic fold).
OCR_NAME_CONFUSIONS = _parse_confusions(_get("SAR_OCR_NAME_CONFUSIONS", "桉:核"))
