# CLAUDE.md

Project setup, usage, and agent rules live in **[AGENTS.md](AGENTS.md)** — read it
first (initialization protocol + how to build `.env` interactively with the user).

Claude Code specifics:
- Two project skills under `.claude/skills/`: `shipment-review-auto` (run engine →
  auto-fill OCR gaps → re-scan → verdict) and `shipment-ocr-gap-transcribing` (the
  fail-closed two-pass blind-read recipe). Invoke `/shipment-review-auto <case-path>`.
- The verdict always comes from the deterministic engine, never from the AI.
- `.env` is git-ignored; never commit real identifiers.
