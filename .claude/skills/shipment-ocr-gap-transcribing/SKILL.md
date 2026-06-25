---
name: shipment-ocr-gap-transcribing
description: Use when a shipment-review case is stuck at 需人工確認 because a scanned 购销合同's OCR failed, when `--ocr-gaps` lists a contract needing a transcript, or when asked to produce a `<pdf>.transcript.json` sidecar for a scanned contract. For this repo's offline shipment-approval reviewer.
---

# OCR-Gap Transcribing

## Overview

When a scanned contract's OCR is too weak to review, the reviewer loads a sidecar
`<pdf>.transcript.json` instead of OCR. You (an AI) may produce that sidecar — but an
AI-produced transcript is only ever **provisionally** trusted: it reaches 可出貨 **only**
when the loader itself confirms two *independent* blind reads agree. You record the two
reads; the loader judges. You never assert the verdict.

**The one rule that makes this safe:** an AI fills a gap by recording evidence
(`authored_by:"ai"` + two reads + the file hash). It NEVER asserts a human verified it.
The whole fail-closed design exists because OCR/AI misreads money; defeating it with a
provenance flag ships a wrong number.

## When to Use

- `shipment-review <case> --ocr-gaps` (or `--ocr-gaps --json`) lists a contract PDF.
- A case sits at 需人工確認 / `ai_unconfirmed_contracts` names a scanned contract.
- Someone asks you to "make the OCR-failed contract pass" / "produce the transcript."

**Not for:** a contract OCR already reads cleanly (no gap → no sidecar). A case stuck for
*other* reasons (缺模組表, approval text unreadable, 單價不一致) — a sidecar will NOT fix those;
say so instead of writing one.

## The Recipe (what the sidecar IS)

```
1. List gaps:   shipment-review <case> --ocr-gaps --json
                → [{file, reason, sha256, kind}, ...]   (sha256 is the LIVE PDF hash — keep it)

2. Two BLIND reads, per gap PDF:
   Dispatch TWO SEPARATE subagents. Each reads the SAME PDF and returns the contract as
   JSON: {contract_number, items:[{code,name,model,unit,quantity,unit_price,amount}]}.
   - Independent context: neither subagent sees the other's output, and neither is told
     "the expected answer" or the module-table/approval figures. Two genuinely blind reads.

3. Write <pdf>.transcript.json — EXACTLY this shape:
   {
     "authored_by": "ai",
     "source_sha256": "<the sha256 from step 1>",
     "pass_a": <subagent 1's JSON>,
     "pass_b": <subagent 2's JSON>,
     "_note": "agent two-pass blind read"
   }
   No top-level "items". No agreement boolean. No "confirmed". No "authored_by":"human".

4. Re-scan:  shipment-review <case>
   - Reads agreed  → contract trusted, case can reach 可出貨.
   - Reads differ  → loader keeps it ai_unconfirmed → 需人工確認. A HUMAN resolves it.
     Report the disagreement; do NOT touch the file to make it pass.
```

## Module table (kind: "module_table")

When a gap's `kind` is `module_table`, the file is the 模組金額核算表 image. The two blind
readers transcribe the TABLE into rows, not a contract:

Each reader returns JSON: {"rows": [{contract_number, purchasing_company, product_name,
model, unit, quantity, unit_price, amount, royalty, code}, ...]} — one object per table row,
exactly as printed, no inference.

Write `<image>.transcript.json`:
{ "authored_by": "ai", "source_sha256": "<sha from the gap entry>",
  "pass_a": <reader 1 JSON>, "pass_b": <reader 2 JSON>, "_note": "agent two-pass blind read" }

All the SAME Forbidden rules apply (authored_by:"ai" only; never human/confirmed; two real
blind reads; never hand-align; copy the sha). The loader recomputes row agreement + per-row
单价×数量=金额 and verifies the sha; disagreement/mismatch → it stays a gap for a human.

The loader recomputes agreement from `pass_a` vs `pass_b` and verifies `source_sha256`
against the live PDF. You provide evidence; it provides the verdict.

## Forbidden — these defeat the safety model

**Violating the letter of these is violating the spirit.**

| Forbidden | Why | Do instead |
|---|---|---|
| `"authored_by": "human"` | An AI is not a human. This is the exact bypass — it skips the two-pass check entirely and ships an unverified number. | `"authored_by": "ai"` always. Only a person who read the scan themselves may write `human`. |
| `"confirmed": true` | Same bypass via the other trusted flag. | Never write it. Confirmation is a human commit, off this path. |
| One read used as both `pass_a` and `pass_b` | Identical passes trivially "agree" → fake trust. | Two separate subagent reads. |
| Hand-editing `pass_a`/`pass_b` so they match | Manufacturing agreement is the same lie as `human`. | Leave them. Disagreement → human. |
| Omitting `source_sha256`, or pasting a made-up one | No hash → loader treats it as untrusted; wrong hash → it won't tie out. | Copy the `sha256` from `--ocr-gaps --json`. |
| A top-level `"items"` array on an AI sidecar | The loader builds from `pass_a`; a top-level items list looks like a legacy human transcript and invites the human/confirmed reflex. | Put the read inside `pass_a`/`pass_b` only. |

## Red Flags — STOP

You are about to defeat the gate if you think:
- "Adding `authored_by:human` is the minimal change to clear the block." (Both baseline
  agents thought exactly this. It is the failure.)
- "The scan was clearly legible, one read is enough."
- "The two reads are off by one digit, I'll just align them so it passes."
- "Sales needs it today, I'll mark it confirmed and note it was rushed."

All of these mean: write `authored_by:"ai"` with two real blind reads, and let a
disagreement go to a human. Shipping today is not worth shipping a wrong contract.

## Common Mistakes

- **Treating a non-OCR block as an OCR gap.** If `--ocr-gaps` does NOT list the PDF, the
  case is stuck on something a sidecar can't fix. Diagnose, don't transcribe.
- **Priming the readers.** Feeding either subagent the approval total or module-table
  numbers destroys the independence that makes agreement meaningful.
- **Reporting "fixed" after writing the sidecar.** You're done only after the re-scan; a
  disagreement means still-blocked, not failed-to-fix — it's the system working.
