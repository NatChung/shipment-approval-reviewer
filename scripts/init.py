#!/usr/bin/env python3
"""Interactive setup — write a git-ignored `.env`.

Press Enter to keep each synthetic default (a runnable demo); type a real value
to override. The `.env` is git-ignored and is never committed.
Run:  python scripts/init.py
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"

FIELDS = [
    ("SAR_BRAND", "智核", "Vendor/brand prefix stripped during product matching"),
    ("SAR_CONTRACT_PREFIX", "ZHDEMO", "Contract-number alpha prefix"),
    ("SAR_PRODUCT_KEYWORDS", "智核,接收终端", "Comma-separated item-row keywords"),
    ("SAR_COMMENT_MARKER", "智核产品实际出货内容", "Approval 'actual shipment' comment marker"),
    ("SAR_OCR_NAME_CONFUSIONS", "桉:核", "OCR look-alike folds, FROM:TO,FROM:TO"),
]


def main() -> int:
    if ENV.exists():
        ans = input(f".env already exists at {ENV}\n  Overwrite? [y/N] ").strip().lower()
        if ans != "y":
            print("Kept existing .env — nothing changed.")
            return 0
    print(
        "\nSetup — press Enter to keep the synthetic default (a runnable demo),\n"
        "or type a real value to override. Values are written to a git-ignored .env.\n"
    )
    lines = ["# Written by scripts/init.py — git-ignored. Never commit real identifiers."]
    for key, default, desc in FIELDS:
        try:
            entered = input(f"{key}  — {desc}\n  [{default}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted; no .env written.")
            return 1
        lines.append(f"{key}={entered or default}")
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"\nWrote {ENV}\n"
        "Next:\n"
        '  python3 -m venv .venv && .venv/bin/pip install -e ".[dev,ocr]"\n'
        "  .venv/bin/python -m pytest -q\n"
        "  .venv/bin/shipment-review /path/to/case-folder\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
