# Shipment-Approval Reviewer ｜ 出貨審批稽核引擎

**語言 / Language:** [中文](#中文) ｜ [English](#english)

> 真實 AI 導入顧問案的匿名化作品。repo 內所有公司、學校、人名、合同號、品牌
> 皆為**合成**(虛構廠商 `智核` / 合同前綴 `ZHDEMO`)。真實識別符不進原始碼,
> 執行時由 git-ignored 的 `.env` 注入。
>
> Anonymized case study from a real AI-adoption consulting engagement. Every
> company, school, person, contract number and brand here is **synthetic**; real
> identifiers stay out of source and are injected at runtime via a git-ignored
> `.env`.

---

## 中文

一個**離線、確定性**的稽核引擎:讀入一個出貨審批文件包,輸出
**可出貨 / 不可出貨 / 需人工確認**,並逐條給出理由——而 AI **只用來「讀」**
讀不清的掃描件,**從不參與判斷**。

### 問題

後台審批一筆出貨,要人工交叉比對三份文件:一份**出貨審批單**、一張
**模組金額核算表**(掃描圖),以及 1~3 份**購銷合同**(掃描蓋章 PDF)。
審核員逐項重打、用眼睛核對價格、數量、品名、合同號——慢,而且賭的是錢。

### 核心設計:確定性的「閘」,AI 只被限制在「讀取」

判定由**確定性規則**(`src/shipment_review/rules.py`)決定——同輸入同輸出、
每條結論都可稽核。當某份掃描件 OCR 爛到不可信時,工具**不讓 AI「下判斷」**,而是:

1. `--ocr-gaps` 精準標出哪一份掃描件讀不了。
2. AI 對那份做**兩次獨立盲讀**,凍結成 `<檔>.transcript.json` sidecar
   (`authored_by:"ai"`、兩次讀、來源檔的 SHA-256)。
3. 確定性的**載入器自己重算兩次盲讀是否一致**、且算術對得上
   (单价 × 数量 = 金额)。一致才信任;不一致、對不上、或檔案被竄改 → 退回人工。

**AI 讀,引擎判。** 結果保持可重現、可稽核、fail-closed——錯的數字永遠不會
靜默通過一道「錢的閘」。

### 查核項

- 每個出貨品項都在合同裡——**正規化後精準比對**,不是模糊評分
  (對一道閘而言,「OCR 錯一個字」和「真的換了版本」絕不能長得一樣)。
- 模組表單價 = 合同單價。
- 出貨總額與模組表加總對得上。
- 合同號在 審批 ↔ 模組表 ↔ 合同 三方都對得起來。
- 任何無法安全比對的 → **需人工確認**,絕不自動放行。

### 快速開始

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,ocr]"      # 不接 ,ocr 則略過掃描件讀取
.venv/bin/python -m pytest -q              # ~260 測試,可跑的證明
.venv/bin/shipment-review /path/to/case-folder
```

一個案件資料夾包含一份審批(PDF/文字)、一張模組表(圖/CSV)、1~3 份合同(PDF)。
輸出是分層報告,全平台 UTF-8(Windows-ready):

```
審核結果：需人工確認

⚠️ 待人工核實：
1. 欄位：單價　「智核ZClass5专业版系统」
   模組表（模组金额核算表.png）：2100　⟷　合同（ZHDEMO-20240101-01合同.pdf）：2000

✅ 已確認：
- 出貨項目均可在合同中找到
- 模組表合同單號均可對應合同
```

### 初始化(建 `.env`)

clone 後互動式建立 `.env`(直接 Enter 即用合成 demo,有真值就填):

```bash
python scripts/init.py
```

或在 **Claude Code / Codex** 開這個資料夾,請 AI「初始化」——它會依
[`AGENTS.md`](AGENTS.md) 的協定設好 venv、再**和你一問一答**填出 `.env`。
`.env` 是 git-ignored,真值只留本機、永不進版控。

### 跑真實文件

公開版預設是合成值。要跑真實資料,把 `.env.example` 複製成 git-ignored 的
`.env`、填入真值即可在執行時覆蓋品牌 / 合同前綴 / 品名關鍵字等常數;
比對與判定邏輯完全不變,只差客戶專用字串。

```env
SAR_BRAND=YourBrand
SAR_CONTRACT_PREFIX=ABCD
SAR_PRODUCT_KEYWORDS=YourBrand,接收终端
# 其餘變數(SAR_COMMENT_MARKER、SAR_OCR_NAME_CONFUSIONS)完整列在 .env.example
```

### 其他輸出

報告分三層 **❌ 違規 / ⚠️ 待人工核實 / ✅ 已確認**。CLI 另有
`--ocr-gaps`(列出需補讀的掃描件)、`--html PATH`(離線審核頁,內嵌原始 PNG/PDF)、
`--json`(機器可讀)、`--unverified {manual,block}`(把「無法核實」這層當需人工或直接擋)。

### 為什麼這樣設計

對一道「錢的閘」,「一個通常會對的 LLM」是錯的工具。真正有價值的決定是:
把判斷留在**確定性、可稽核**這端,只在 AI 真的比傳統 OCR 強的那一點
——*讀一張爛掃描*——放它進來,而且包在一個會**重新驗證它工作**的
fail-closed 邊界裡,才信任任何一個數字。

---

## English

An offline, **deterministic** reviewer that reads a shipment-approval document
bundle and returns **可出貨 / 不可出貨 / 需人工確認 (ship / block / needs-human)**
with line-by-line reasons — and uses AI **only to read** unreadable scans, never
to decide the verdict.

### The problem

A back office approves a shipment by hand-cross-checking three documents: an
**approval form**, a **module-fee table** (a scanned image), and one to three
**purchase contracts** (scanned, stamped PDFs). Reviewers re-key and eyeball
prices, quantities, product names and contract numbers across all three — slow,
and real money rides on each pass.

### The idea: a deterministic gate, with AI bounded to *reading*

The verdict is decided by **deterministic rules** (`src/shipment_review/rules.py`)
— same input, same output, with an auditable reason per finding. Where a scan's
OCR is too garbled to trust, the tool does **not** let an AI "decide":

1. `--ocr-gaps` flags exactly which scan can't be read.
2. An AI does **two independent blind reads** and freezes them into a
   `<file>.transcript.json` sidecar (`authored_by:"ai"`, both passes, a SHA-256 of
   the source file).
3. The deterministic **loader re-computes whether the two reads agree** and that
   the arithmetic ties out (单价 × 数量 = 金额). Only then is the read trusted; a
   disagreement, a failed tie-out, or a tampered file is rejected → human.

**AI reads; the engine judges.** Reproducible, auditable, fail-closed — a wrong
number can never silently pass a money gate.

### What it checks

- Every shipped item exists in a contract — **canonical exact** matching, not
  fuzzy scoring (a one-char OCR typo and a real edition swap must never look the
  same to a gate).
- Module-table unit prices match the contract.
- The shipment total reconciles against the module table.
- Contract numbers tie out across approval ↔ module table ↔ contracts.
- Anything unmatched safely → **需人工確認**, never an automated pass.

### Quickstart

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,ocr]"      # omit ,ocr to skip scanned-doc reading
.venv/bin/python -m pytest -q              # ~260 tests, the runnable proof
.venv/bin/shipment-review /path/to/case-folder
```

A case folder holds one approval (PDF/text), one module-fee table (image/CSV) and
one to three contracts (PDF). Output is a tiered report (UTF-8 on every platform,
Windows-ready) — see the sample above.

### Setup (build `.env`)

After cloning, build `.env` interactively (press Enter for the synthetic demo, or
type real values):

```bash
python scripts/init.py
```

Or open the folder in **Claude Code / Codex** and ask the agent to "init" — it
follows the protocol in [`AGENTS.md`](AGENTS.md): set up the venv, then build
`.env` with you question-by-question. `.env` is git-ignored — real values stay
local and never enter version control.

### Running on a real document set

Committed defaults are synthetic. To run real data, copy `.env.example` to a
git-ignored `.env` and fill in the brand / contract-prefix / product-keyword
overrides; the matching and verdict logic is unchanged.

### How it's built

| Layer | What |
|---|---|
| Extraction | `pypdf` / Pillow / rapidocr (optional) → structured items |
| Normalization | OCR-tolerant canonical matching; unit / price / contract-number rules |
| Verdict | pure deterministic rules; fail-closed on anything unverifiable |
| AI-OCR fallback | two-pass blind read → frozen sidecar → loader re-judged |
| Offline | no network, no LLM API in the verdict path, no MCP |

The optional AI-OCR orchestration lives as two Claude Code skills under
`.claude/skills/` — `shipment-review-auto` (run engine → fill gaps → re-scan) and
`shipment-ocr-gap-transcribing` (the two-pass blind-read recipe). They dispatch the
blind reads and write the sidecar, but the **verdict always comes from the
deterministic engine**, never the AI.

### Why this design

For a money gate, "an LLM that's usually right" is the wrong tool. Keep the
decision deterministic and auditable, and let AI in only where it genuinely beats
traditional OCR — *reading a bad scan* — behind a fail-closed boundary that
re-verifies its work before trusting a single number.

## License

MIT
