---
name: shipment-review-auto
description: Use to review a shipment-approval case end-to-end and automatically. Runs the deterministic shipment-review engine, and when a scanned 购销合同's OCR is too garbled to review (it appears in --ocr-gaps), auto-dispatches blind AI reads to fill the gap, then re-scans and reports the engine's verdict. Trigger when asked to "自動審 / auto-review this case", or given a case folder path to decide 可出貨/不可出貨/需人工.
---

# Shipment Review (Auto-Orchestrator)

## Overview

Run the deterministic `shipment-review` engine; if it dead-ends because a scanned
contract's OCR is garbled, fill the gap automatically by delegating to the
`shipment-ocr-gap-transcribing` skill (two blind reads → an `authored_by:"ai"` sidecar the
loader re-judges), then re-scan and print the verdict.

**The verdict is ALWAYS the engine's.** You (the orchestrator) read, you never judge.
You add NO write authority beyond what `shipment-ocr-gap-transcribing` already permits.

## Flow

1. Run `shipment-review <case-path>` — note the initial verdict (context only, NOT a
   decision; the real verdict is step 5).
2. Run `shipment-review <case-path> --ocr-gaps --json` → `[{file, reason, sha256, kind}, ...]`.
3. No gaps → go to step 5.
4. ONE transcription pass. For EACH gap, FIRST check whether `<pdf>.transcript.json`
   (the gap's `file` + `.transcript.json`) exists. A gap that HAS a sidecar means that
   sidecar is invalid (valid ones are excluded from the gap list). Branch on existence,
   not on reason text:
   - **Sidecar DOES NOT EXIST** → this is the ONLY case where you may write. Delegate to
     `shipment-ocr-gap-transcribing`: dispatch TWO independent reader subagents, each given ONLY
     this gap's file path + the generic read instruction; write the `authored_by:"ai"`
     sidecar (pass_a + pass_b + source_sha256 copied from the gap entry). For a
     `kind:"module_table"` gap, dispatch the two blind readers with the module `{rows}`
     instruction (see shipment-ocr-gap-transcribing's "Module table" section) and write the
     sidecar with `pass_a`/`pass_b` = `{rows:[…]}`. SAFETY: module readers also get ONLY
     the image path, never expected names/figures — the same blind-dispatch rule applies.
   - **Sidecar EXISTS** → open it and read `authored_by`:
     - It is a recognized `authored_by:"ai"` two-pass sidecar (has pass_a + pass_b) →
       DO NOT re-read (re-reading cannot fix a structural/arithmetic rejection and never
       converges). Record "needs human: AI transcript present but invalid (<reason>)".
     - **ANYTHING ELSE** — `authored_by:"human"`, `confirmed:true`, missing or unknown
       `authored_by`, a legacy top-level-`items` transcript, a typo — DO NOT touch it.
       Record "needs human: existing transcript present but invalid (<reason>)". NEVER
       overwrite it.
   Do NOT pre-filter by the reason text — an OCR-failed-but-printed number is recoverable
   by a read; let the loader judge.
5. Run `shipment-review <case-path>` → this is THE verdict.
6. Print, in this order — a PLAIN-LANGUAGE explanation first, the raw engine report
   last. The reader is sales/finance, not an engineer.

   ```
   【審核結果】<可出貨 / 不可出貨 / 需人工確認>
   <if 需人工確認: one reassurance line, e.g. "不是不能出 — 是以下幾點證據不夠硬，需人花幾秒確認">
   <if 不可出貨: one severity line, e.g. "以下是擋下這批貨的硬問題">
   <if 可出貨: omit this line>

   〔已自動套用 transcript（非 OCR）：…〕   ← keep the engine's transcript-applied marker if present

   案件資料夾：<the case-folder name>

   要人確認：   (omit this whole block if 可出貨; for 不可出貨 title it 違規事項：)
   ① <PLAIN statement of the problem — name the real product/file in everyday words,
      NO jargon (not "僅見於 AI 補讀且未經佐證的合同" but "只有單次 AI 草讀的掃描合同這一個來源")>
      <1–3 short sentences of plain WHY: explain the cause like you would to a colleague —
       e.g. "這份合同是掃描檔，之前只用 AI 讀過一次、沒有第二次核對"; or "模組表那張圖掃糊了，
       把『AI』少看一個字母成『A』，電腦比對不到就報查無此項">
      → 人要做的：<one concrete action>
      📄 <FILENAME(s) of the file(s) the human must open to check this item — just the file
         name, not the full path. Name every file the action refers to (e.g. the scanned
         contract; the 模組表 png AND the approval pdf when the item compares two documents)>
   ② … (one entry per engine ⚠️ / ❌ item)

   沒問題（已確認）：<the engine's ✅ items, in plain words>

   AI 自動做了：<1–2 lines: which contracts were freshly blind-read and trusted this run;
     which existing sidecars were left untouched and why; or "無 OCR 缺口可補，未派任何盲讀">

   ───── 原始判定（稽核底稿，逐字）─────
   <the engine's step-5 text report VERBATIM — unchanged, for audit>
   ```

   The verdict line is the engine's. The plain block is a RE-WORDING of the engine's
   ⚠️/❌/✅ items for clarity — one plain entry per engine item, derived from the step-5
   report (the 仍需人工 items come from the ⚠️ section, not the residual gap list).

   THREE HARD RULES for the plain block (it must never distort the gate):
   - The verdict is ALWAYS the engine's — never change it to match a nicer explanation.
   - NEVER soften a ❌ violation into "a small issue" — a hard block stays hard.
   - Plain language is RE-WORDING, not RE-JUDGING. If you are unsure what an engine reason
     means, do NOT guess a friendly version — quote the engine line verbatim in the plain
     block too. The verbatim 稽核底稿 at the bottom is the source of truth.

## SAFETY — the gate-defeating surface (HARD rules)

After step 1 you hold the expected figures (module-table prices, approval 出货金额,
contract totals). If you leak any of them into the blind readers, both can anchor to the
same wrong-but-expected value, agree, and the loader will trust a wrong number into 可出貨.

- **Blind dispatch:** each reader gets ONLY the PDF path + the generic read instruction.
  NEVER pass the step-1 verdict, any total, any module/approval figure, any "expected"
  value, or the other reader's output. No "the answer should be ~X" priming, ever.
- **Red flag — STOP:** if you are about to put a number you learned from step 1 into a
  reader's prompt, don't. That is the false-可出貨 path.
- **No new write authority:** you inherit `shipment-ocr-gap-transcribing`'s ENTIRE Forbidden /
  Red-Flags list verbatim. Being autonomous NEVER licenses a shortcut write of
  `authored_by:"human"` / `confirmed:true` / a hand-aligned pass / a fabricated number to
  "finish the job". Unresolvable → report it, stop.
- **Never overwrite ANY existing `<pdf>.transcript.json`** — only a literally-absent
  sidecar file may be written; an existing sidecar that is not a recognized
  `authored_by:"ai"` two-pass (pass_a + pass_b) is always do-not-touch → report
  needs-human (see Flow 4).

## Not For

- A case stuck on a non-OCR blocker (缺模組表 / 缺审批) — these never appear in
  `--ocr-gaps`; a sidecar can't fix them. Report the engine's verdict as-is.
- Issuing your own verdict, or "fixing" a real discrepancy (e.g. 单价不一致) the engine
  reports — surface it, don't paper over it.
