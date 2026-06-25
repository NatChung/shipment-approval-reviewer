# AGENTS.md — for AI coding agents (Claude Code, Codex, …)

Offline, deterministic shipment-approval reviewer. The **verdict is always the
deterministic engine's**; AI is used only to *read* unreadable scans, never to
decide. See `README.md` for the full design.

## Initialization protocol

Run this the first time you set up the repo (or whenever `.env` is missing).
Ask the user before doing it — do not run it silently.

1. **Environment**
   ```
   python3 -m venv .venv
   .venv/bin/pip install -e ".[dev,ocr]"    # omit ,ocr to skip scanned-doc OCR
   ```
2. **`.env` (client identifiers) — build it WITH the user.**
   If `.env` does not exist, create it interactively. For each variable, show the
   synthetic default and let the user press Enter (keeps a runnable demo) or type a
   real value. Either run the helper:
   ```
   python scripts/init.py
   ```
   or ask the five questions yourself and write `.env` (keys + synthetic defaults
   are in `.env.example`):
   `SAR_BRAND` (智核) · `SAR_CONTRACT_PREFIX` (ZHDEMO) ·
   `SAR_PRODUCT_KEYWORDS` (智核,接收终端) · `SAR_COMMENT_MARKER` (智核产品实际出货内容) ·
   `SAR_OCR_NAME_CONFUSIONS` (桉:核).
   `.env` is git-ignored — **never commit it** and never put real identifiers in
   tracked files.
3. **Verify**: `.venv/bin/python -m pytest -q` (≈260 tests) and
   `.venv/bin/shipment-review --help`.

## Usage

Review one case folder (approval + module-fee table + 1–3 contracts):
```
.venv/bin/shipment-review /path/to/case-folder
```
In Claude Code you can drive the whole flow — run the engine, auto-fill OCR gaps
with two-pass blind reads, re-scan — via the `shipment-review-auto` skill:
`/shipment-review-auto /path/to/case-folder`. The skill orchestrates; the
deterministic engine still decides the verdict.

## Rules for agents

- Never write a real client identifier into a tracked file (only into `.env`).
- Never let AI assert the verdict; it always comes from `shipment-review`.
- Never weaken the fail-closed transcript rules in `.claude/skills/`.
