"""Render a ReportData as a self-contained, offline HTML review page: ❌/⚠️/✅ tiers,
per-⚠️ 放行/駁回 controls with notes, the source materials for side-by-side comparison,
review-term annotation in the extracted text, and a client-side export of the reviewer's
decisions. No external assets, no backend.
"""
from __future__ import annotations

import html as _html
import re
from pathlib import Path

from shipment_review.models import Approval, Contract, ModuleRow, ReviewStatus
from shipment_review.normalization import extract_contract_numbers
from shipment_review.report import ReportData, SourceFile, issue_source_files

_STATUS_CLASS = {
    ReviewStatus.APPROVED: "ok",
    ReviewStatus.BLOCKED: "bad",
    ReviewStatus.MANUAL_REVIEW: "warn",
}
_BRACKET_RE = re.compile(r"「([^」]*)」")
_TRAILING_MODEL_RE = re.compile(r"^[VWvw]?\d")


def _esc(value: object) -> str:
    return _html.escape("" if value is None else str(value))


def _review_terms(report: ReportData) -> list[str]:
    """The product names and contract numbers a ⚠️/❌ issue points at — the spots a human
    should look for in the original text."""
    terms: set[str] = set()
    for issue in (*report.violations, *report.unverified):
        match = _BRACKET_RE.search(issue.message)
        if match:
            bracket = re.sub(r"^\s*\d+\s*[、.．]\s*", "", match.group(1).strip())  # drop a leading 序号
            terms.add(bracket)
            head, _, tail = bracket.rpartition(" ")
            if head and _TRAILING_MODEL_RE.match(tail):  # bracket was "name model" → also the name
                terms.add(head)
        terms.update(extract_contract_numbers(issue.message))
    return [t for t in terms if t and len(t) >= 2]


def _mark(text: str, terms: list[str]) -> str:
    """HTML-escape `text`, then wrap each review term occurrence in <mark>. Longest term
    first so a substring term cannot split a longer match; sub() never rescans inserted tags."""
    escaped = _esc(text)
    escaped_terms = sorted({_esc(t) for t in terms}, key=len, reverse=True)
    if not escaped_terms:
        return escaped
    pattern = re.compile("|".join(re.escape(t) for t in escaped_terms))
    return pattern.sub(lambda m: f"<mark>{m.group(0)}</mark>", escaped)


def render_html(report: ReportData) -> str:
    status_cls = _STATUS_CLASS.get(report.result.status, "warn")
    terms = _review_terms(report)
    return "".join(
        [
            "<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'>",
            "<meta name='viewport' content='width=device-width, initial-scale=1'>",
            f"<title>出貨審核 — {_esc(report.case_name)}</title>",
            _STYLE,
            "</head><body>",
            "<header>",
            f"<div class='case'><span class='dot {status_cls}'></span>{_esc(report.case_name)}</div>",
            f"<div class='verdict {status_cls}'>{_esc(report.result.title)}</div>",
            "</header>",
            "<div class='note-bar'>本頁引用本機原檔，請用 Chrome / Edge 開啟；點左欄事項可跳到右欄原文對應處</div>",
            "<main>",
            f"<div class='col col-issues'>{_verdict_sections(report)}</div>",
            f"<div class='col col-docs'>{_materials(report, terms)}</div>",
            "</main>",
            _SCRIPT,
            "</body></html>",
        ]
    )


def _verdict_sections(report: ReportData) -> str:
    out: list[str] = []
    if report.violations:
        out.append("<h2 class='bad'>違規事項</h2><ol class='issues'>")
        out.extend(f"<li>{_issue_html(report, i)}</li>" for i in report.violations)
        out.append("</ol>")
    if report.unverified:
        out.append("<h2 class='warn'>待人工核實</h2><div class='cards'>")
        for idx, issue in enumerate(report.unverified):
            out.append(
                f"<div class='card' data-id='u{idx}'>"
                f"<div class='msg'>{_issue_html(report, issue)}</div>"
                "<div class='actions'>"
                f"<button class='pass' onclick=\"decide('u{idx}','pass')\">放行</button>"
                f"<button class='reject' onclick=\"decide('u{idx}','reject')\">駁回</button>"
                "<span class='state'></span></div>"
                f"<textarea class='note' rows='1' placeholder='備註（選填）' "
                f"oninput=\"note('u{idx}',this.value)\"></textarea>"
                "</div>"
            )
        out.append("</div>")
    if report.confirmed:
        out.append("<h2 class='ok'>已確認</h2><ul class='confirmed'>")
        out.extend(f"<li>{_esc(c)}</li>" for c in report.confirmed)
        out.append("</ul>")
    out.append(
        "<div class='export'><button onclick='exportDecisions()'>匯出審核決定</button>"
        "<span id='summary'></span></div>"
    )
    return "".join(out)


def _materials(report: ReportData, terms: list[str]) -> str:
    by_role: dict[str, list[SourceFile]] = {}
    for sf in report.source_files:
        by_role.setdefault(sf.role, []).append(sf)
    out = ["<h2 class='docs-h'>原文比對</h2>"]
    if report.approval is not None:
        out.append(_approval_block(report.approval, report.approval_text, by_role.get("approval", [None])[0], terms))
    contract_srcs = by_role.get("contract", [])
    for n, contract in enumerate(report.contracts):
        src = contract_srcs[n] if n < len(contract_srcs) else None
        out.append(_contract_block(contract, report.contract_texts.get(contract.source_file, ""), n, src, terms))
    module_src = by_role.get("module", [None])[0]
    if report.module_rows or module_src is not None:
        out.append(_module_block(report.module_rows, module_src))
    return "".join(out)


def _raw_text(text: str, terms: list[str]) -> str:
    return f"<details><summary>抽取原文</summary><pre>{_mark(text, terms)}</pre></details>" if text else ""


def _approval_block(approval: Approval, text: str, source: SourceFile | None, terms: list[str]) -> str:
    rows = "".join(
        f'<tr id="panel-approval-row-{i}"><td>{_esc(it.code)}</td><td>{_esc(it.name)}</td>'
        f"<td>{_esc(it.model)}</td><td>{_esc(it.quantity)}</td><td>{_esc(it.unit)}</td></tr>"
        for i, it in enumerate(approval.actual_items)
    )
    meta = (
        f"審批編碼 {_esc(approval.approval_code)}　合同單號 {_esc('、'.join(approval.contract_numbers))}"
        f"　出货金额 {_esc(approval.shipment_amount)}"
    )
    return (
        '<details id="panel-approval" open><summary>出貨審批</summary>'
        f"<div class='meta'>{meta}</div>"
        "<table><thead><tr><th>代碼</th><th>名稱</th><th>型號</th><th>數量</th><th>單位</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        f"{_viewer(source)}{_raw_text(text, terms)}</details>"
    )


def _contract_block(contract: Contract, text: str, n: int, source: SourceFile | None, terms: list[str]) -> str:
    panel_id = f"panel-contract-{n}"
    rows = "".join(
        f'<tr id="{panel_id}-row-{i}"><td>{_esc(it.code)}</td><td>{_esc(it.name)}</td>'
        f"<td>{_esc(it.model)}</td><td>{_esc(it.quantity)}</td><td>{_esc(it.unit_price)}</td>"
        f"<td>{_esc(it.amount)}</td></tr>"
        for i, it in enumerate(contract.items)
    )
    if contract.number_inferred:
        origin = "OCR·合同號消去法推得"
    else:
        origin = "transcript" if not text else "OCR"
    return (
        f'<details id="{panel_id}" open><summary>合同 {_esc(contract.contract_number)}（{origin}）</summary>'
        f"<div class='meta'>買方 {_esc(contract.buyer_name)}　檔案 {_esc(contract.source_file)}</div>"
        "<table><thead><tr><th>代碼</th><th>名稱</th><th>型號</th><th>數量</th><th>單價</th><th>金額</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>{_viewer(source)}{_raw_text(text, terms)}</details>"
    )


def _module_block(rows: list[ModuleRow], source: SourceFile | None) -> str:
    if rows:
        body = "".join(
            f'<tr id="panel-module-row-{i}"><td>{_esc(r.contract_number)}</td>'
            f"<td>{_esc(r.product_name)}</td><td>{_esc(r.model)}</td>"
            f"<td>{_esc(r.quantity)}</td><td>{_esc(r.unit_price)}</td><td>{_esc(r.amount)}</td>"
            f"<td>{_esc(r.royalty)}</td></tr>"
            for i, r in enumerate(rows)
        )
        table = (
            "<table><thead><tr><th>合同單號</th><th>產品</th><th>型號</th><th>數量</th><th>單價</th>"
            f"<th>金額</th><th>權益金</th></tr></thead><tbody>{body}</tbody></table>"
        )
    else:
        table = "<p class='unparsed'>無法自動解析，請核對原檔</p>"
    return f'<details id="panel-module" open><summary>模組金核算表</summary>{table}{_viewer(source)}</details>'


def _file_link(source: SourceFile | None) -> str:
    """A chip linking to the original file so the reviewer can open it directly."""
    if source is None:
        return ""
    try:
        uri = _esc(Path(source.path).resolve().as_uri())
    except (ValueError, OSError):
        return ""
    return f"<a class='file' href=\"{uri}\" target='_blank' rel='noopener'>📄 {_esc(Path(source.path).name)}</a>"


def _issue_html(report: ReportData, issue) -> str:
    from shipment_review.report import issue_anchor

    anchor = issue_anchor(issue.message, report)
    msg = _esc(issue.message)
    if anchor is None:
        body = msg
    else:
        target = "" if anchor.row_index is None else f"{anchor.panel_id}-row-{anchor.row_index}"
        body = f"<a class='jump' onclick=\"jumpTo('{_esc(anchor.panel_id)}','{_esc(target)}')\">{msg}</a>"
    return body + "".join(_file_link(sf) for sf in issue_source_files(report, issue.message))


def _viewer(source: SourceFile | None) -> str:
    if source is None:
        return ""
    try:
        uri = _esc(Path(source.path).resolve().as_uri())
    except (ValueError, OSError):
        return f"<div class='viewer-missing'>原檔無法載入：{_esc(source.path)}</div>"
    if source.kind == "image":
        return f'<div class="viewer"><img src="{uri}" alt="原始掃描件"></div>'
    if source.kind == "pdf":
        return f'<div class="viewer"><iframe src="{uri}" title="原始 PDF"></iframe></div>'
    if source.kind == "spreadsheet":
        return f'<div class="viewer"><a class="open-file" href="{uri}">用本機程式開啟試算表 ↗</a></div>'
    return ""  # text kind already shown via the extracted-text <pre>


_STYLE = """<style>
:root{
 --bg:oklch(0.985 0.004 255); --surface:oklch(0.998 0.002 255); --ink:oklch(0.27 0.018 260);
 --muted:oklch(0.52 0.014 260); --line:oklch(0.915 0.006 258);
 --ok:oklch(0.55 0.12 150); --warn:oklch(0.63 0.14 65); --bad:oklch(0.55 0.19 26);
 --ok-bg:oklch(0.965 0.03 150); --warn-bg:oklch(0.97 0.04 80); --bad-bg:oklch(0.965 0.035 26);
 --accent:oklch(0.53 0.15 255); --mark:oklch(0.92 0.13 95); --head-h:104px;
}
*{box-sizing:border-box}
body{margin:0;color:var(--ink);background:var(--bg);
 font:15px/1.6 system-ui,-apple-system,'PingFang TC','Microsoft JhengHei',sans-serif;
 font-variant-numeric:tabular-nums}
header{position:sticky;top:0;z-index:5;display:flex;justify-content:space-between;align-items:center;
 gap:16px;padding:16px 28px;background:var(--surface);border-bottom:1px solid var(--line)}
.case{font-weight:650;font-size:17px;display:flex;align-items:center;gap:10px}
.dot{width:10px;height:10px;border-radius:50%}
.dot.ok{background:var(--ok)} .dot.warn{background:var(--warn)} .dot.bad{background:var(--bad)}
.verdict{padding:5px 16px;border-radius:999px;font-weight:650;font-size:14px;color:var(--surface)}
.verdict.ok{background:var(--ok)} .verdict.warn{background:var(--warn)} .verdict.bad{background:var(--bad)}
.note-bar{padding:8px 28px;font-size:13px;color:var(--muted);background:var(--bg);border-bottom:1px solid var(--line)}
main{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,3fr)}
.col{height:calc(100dvh - var(--head-h));overflow:auto;padding:22px 28px}
.col-issues{border-right:1px solid var(--line)}
@media(max-width:880px){main{grid-template-columns:1fr}.col{height:auto;border:0}}
h2{font-size:13px;letter-spacing:.04em;text-transform:none;font-weight:700;margin:26px 0 12px}
h2:first-child{margin-top:0}
h2.ok{color:var(--ok)} h2.warn{color:var(--warn)} h2.bad{color:var(--bad)}
.docs-h{color:var(--muted)}
ol.issues{margin:0;padding-left:20px} ol.issues li{margin:7px 0}
ul.confirmed{margin:0;padding-left:0;list-style:none}
ul.confirmed li{margin:5px 0;color:var(--muted);padding-left:22px;position:relative}
ul.confirmed li::before{content:'✓';position:absolute;left:0;color:var(--ok);font-weight:700}
.cards{display:flex;flex-direction:column;gap:14px}
.card{border:1px solid var(--line);border-radius:10px;padding:14px 16px;background:var(--surface)}
.card.done-pass{background:var(--ok-bg);border-color:color-mix(in oklch,var(--ok),transparent 60%)}
.card.done-reject{background:var(--bad-bg);border-color:color-mix(in oklch,var(--bad),transparent 55%)}
.card .msg{margin-bottom:10px;line-height:1.55}
.actions{display:flex;align-items:center;gap:8px}
.actions button{cursor:pointer;border:1px solid var(--line);background:var(--surface);border-radius:7px;
 padding:6px 16px;font:inherit;font-weight:600;transition:background .12s,border-color .12s,color .12s}
.actions .pass:hover{border-color:var(--ok);color:var(--ok);background:var(--ok-bg)}
.actions .reject:hover{border-color:var(--bad);color:var(--bad);background:var(--bad-bg)}
.actions .state{margin-left:auto;font-size:13px;font-weight:650}
.done-pass .state{color:var(--ok)} .done-reject .state{color:var(--bad)}
.note{display:block;width:100%;margin-top:10px;border:1px solid var(--line);border-radius:7px;
 padding:7px 9px;font:inherit;resize:vertical;background:var(--bg)}
.export{margin-top:24px;display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.export button{cursor:pointer;background:var(--ink);color:var(--surface);border:0;border-radius:8px;
 padding:9px 18px;font:inherit;font-weight:600}
#summary{font-size:13px;color:var(--muted)}
a.jump{cursor:pointer;color:var(--accent);text-decoration:underline;text-decoration-style:dotted;
 text-underline-offset:3px}
a.jump:hover{text-decoration-style:solid}
a.file{display:inline-block;margin-left:8px;font-size:12px;color:var(--muted);border:1px solid var(--line);
 border-radius:6px;padding:1px 9px;text-decoration:none;white-space:nowrap;vertical-align:middle}
a.file:hover{color:var(--accent);border-color:var(--accent)}
details{background:var(--surface);border:1px solid var(--line);border-radius:10px;margin:0 0 14px;padding:6px 16px 12px}
summary{cursor:pointer;font-weight:650;padding:8px 0;position:sticky;top:0;background:var(--surface)}
details details{border:0;background:transparent;padding:0;margin:6px 0 0}
details details summary{font-weight:500;color:var(--muted);font-size:13px}
.meta{color:var(--muted);font-size:13px;margin:2px 0 8px}
table{border-collapse:collapse;width:100%;margin:6px 0;font-size:13.5px}
th,td{border:1px solid var(--line);padding:6px 9px;text-align:left;vertical-align:top}
th{background:var(--bg);font-weight:600;color:var(--muted)}
tr{scroll-margin-top:46px}
tr.hl td{background:var(--mark);box-shadow:inset 0 0 0 9999px color-mix(in oklch,var(--mark),transparent 35%)}
tr.hl td{transition:background .25s}
mark{background:var(--mark);border-radius:3px;padding:0 2px;color:inherit}
.viewer{margin:10px 0}
.viewer img{max-width:100%;border:1px solid var(--line);border-radius:8px;display:block}
.viewer iframe{width:100%;height:60vh;border:1px solid var(--line);border-radius:8px}
.viewer .open-file{color:var(--accent)}
.viewer-missing,.unparsed{color:var(--bad);font-size:13px;margin:8px 0}
pre{white-space:pre-wrap;word-break:break-word;background:var(--bg);border:1px solid var(--line);
 border-radius:8px;padding:12px;max-height:340px;overflow:auto;font-size:12.5px;line-height:1.7;margin:8px 0 0}
</style>"""

_SCRIPT = """<script>
const KEY='shipment-review:'+document.title;
let D=JSON.parse(localStorage.getItem(KEY)||'{}');
function save(){localStorage.setItem(KEY,JSON.stringify(D));render();}
function decide(id,v){D[id]=D[id]||{};D[id].decision=(D[id].decision===v?null:v);save();}
function note(id,t){D[id]=D[id]||{};D[id].note=t;save();}
function render(){
 let pass=0,rej=0,total=document.querySelectorAll('.card').length;
 document.querySelectorAll('.card').forEach(c=>{
  const d=(D[c.dataset.id]||{}).decision;
  c.classList.toggle('done-pass',d==='pass');
  c.classList.toggle('done-reject',d==='reject');
  c.querySelector('.state').textContent=d==='pass'?'已放行':d==='reject'?'已駁回':'';
  if(d==='pass')pass++;if(d==='reject')rej++;
 });
 const s=document.getElementById('summary');
 if(s)s.textContent=total?`已決 ${pass+rej}/${total}（放行 ${pass}、駁回 ${rej}）`:'';
}
function restore(){
 document.querySelectorAll('.card').forEach(c=>{
  const e=D[c.dataset.id];if(e&&e.note)c.querySelector('.note').value=e.note;
 });render();
}
function exportDecisions(){
 const out={case:document.title,decisions:D};
 const b=new Blob([JSON.stringify(out,null,2)],{type:'application/json'});
 const a=document.createElement('a');a.href=URL.createObjectURL(b);
 a.download='review-decisions.json';a.click();
}
function jumpTo(panel,row){
 const p=document.getElementById(panel);
 if(p){p.open=true;p.scrollIntoView({behavior:'smooth',block:'start'});}
 document.querySelectorAll('.hl').forEach(e=>e.classList.remove('hl'));
 if(row){const r=document.getElementById(row);if(r){r.classList.add('hl');r.scrollIntoView({behavior:'smooth',block:'center'});}}
}
restore();
</script>"""
