"""Render a ReportData as the text scan output: the three tiers, each ❌/⚠️ item shown as
a comparison between the two files/fields it weighs against each other — a value mismatch
shows both values side by side; everything else shows 對比：A 檔案 ⟷ B 檔案 + 欄位 + 問題, so
the reviewer sees which file's which field disagrees without opening the HTML page.
"""
from __future__ import annotations

import re
from pathlib import Path

from shipment_review.normalization import clean_display_name, extract_contract_numbers
from shipment_review.report import (
    FILE_ROLE_LABEL,
    ReportData,
    SourceFile,
    issue_field,
    issue_source_files,
)

_ROLE_BY_LABEL = {"出貨審批": "approval", "合同": "contract", "模組表": "module"}
# "…「product」單價不一致：模組表 2286，合同 8000。" — a two-value comparison.
_MISMATCH_RE = re.compile(
    r"「([^」]*)」(單價|數量|單位)不一致：(出貨審批|合同|模組表)\s*([^，]+?)，\s*"
    r"(出貨審批|合同|模組表)\s*([^，。]+)"
)
_BRACKET_RE = re.compile(r"「([^」]*)」")
_LEADING_INDEX_RE = re.compile(r"^\s*\d+\s*[、.．]\s*")


def format_report_text(report: ReportData) -> str:
    lines = [f"審核結果：{report.result.title}", ""]
    # A transcript-backed contract has no raw OCR text (gather_case stores ""); a sidecar
    # that exists but failed validation falls back to OCR and is NOT marked.
    transcribed = [
        Path(c.source_file).name
        for c in report.contracts
        if report.contract_texts.get(c.source_file) == ""
    ]
    if transcribed:
        lines.append(f"〔已自動套用 transcript（非 OCR）：{'、'.join(transcribed)}〕")
        lines.append("")
    if report.violations:
        lines.append("❌ 違規事項：")
        lines.extend(_item_lines(report, report.violations))
    if report.unverified:
        lines.append("⚠️ 待人工核實：")
        lines.extend(_item_lines(report, report.unverified))
    if report.confirmed:
        lines.append("✅ 已確認：")
        lines.extend(f"- {check}" for check in report.confirmed)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _file_label(report: ReportData, role: str) -> str:
    for sf in report.source_files:
        if sf.role == role:
            return f"{FILE_ROLE_LABEL[role]}（{Path(sf.path).name}）"
    return FILE_ROLE_LABEL.get(role, role)


def _source_label(sf: SourceFile) -> str:
    return f"{FILE_ROLE_LABEL.get(sf.role, sf.role)}（{Path(sf.path).name}）"


def _item_lines(report: ReportData, issues) -> list[str]:
    out: list[str] = []
    for index, issue in enumerate(issues, start=1):
        out.extend(_one_item(report, index, issue.message))
    return out


def _one_item(report: ReportData, index: int, message: str) -> list[str]:
    field = issue_field(message) or "—"

    mismatch = _MISMATCH_RE.search(message)
    if mismatch:
        product, sub_field, label_a, value_a, label_b, value_b = mismatch.groups()
        return [
            f"{index}. 欄位：{sub_field}　「{clean_display_name(product)}」",
            f"   {_file_label(report, _ROLE_BY_LABEL[label_a])}：{value_a.strip()}"
            f"　⟷　{_file_label(report, _ROLE_BY_LABEL[label_b])}：{value_b.strip()}",
            "",
        ]

    sides = _presence_sides(report, message)
    if sides is not None:
        subject, left_role, right_role, reason = sides
        return [
            f"{index}. 欄位：{field}",
            f"   {_file_label(report, left_role)}：{subject}"
            f"　⟷　{_file_label(report, right_role)}：{reason}",
            "",
        ]

    files = issue_source_files(report, message)
    compare = "　⟷　".join(_source_label(sf) for sf in files) if files else "（無對應檔案）"
    return [f"{index}. 欄位：{field}", f"   對比：{compare}", f"   問題：{message}", ""]


# Only messages that genuinely say "the subject is missing / unverifiable on the other side"
# get the two-sided present⟷missing treatment. Anything else (a value mismatch the regex
# missed, a quantity-over-contract, a multi-unit ambiguity, a buyer mismatch) keeps its full
# message via the generic path — never rewritten to a false "查無此項".
_PRESENCE_MARKERS = (
    "未在任何合同中找到",
    "未在對應合同中找到",
    "無法在合同中核對",
    "未能在合同中確認",
    "無法在合同中確認",
    "未在出貨審批",
    "找不到對應合同",
    "未找到對應合同",
)


def _presence_sides(report: ReportData, message: str) -> tuple[str, str, str, str] | None:
    """For a 'present on one side, missing/unreadable on the other' issue, return
    (subject, left_role, right_role, reason). None when the message is not that shape."""
    if "對應多份" in message or not any(marker in message for marker in _PRESENCE_MARKERS):
        return None
    bracket = _BRACKET_RE.search(message)
    numbers = extract_contract_numbers(message)
    subject = bracket.group(1).strip() if bracket else (numbers[0] if numbers else "")
    subject = clean_display_name(_LEADING_INDEX_RE.sub("", subject))
    if not subject:
        return None

    if message.startswith("模組表"):
        left_role = "module"
    elif message.startswith("出貨項目") or message.startswith("出貨審批"):
        left_role = "approval"
    else:
        files = issue_source_files(report, message)
        left_role = files[0].role if files else "approval"

    right_role = "approval" if "未在出貨審批" in message else "contract"

    if "掃描件" in message:
        reason = "掃描件，OCR 可能讀不全，無法核對"
    elif "找不到對應合同" in message or "未找到對應合同" in message:
        reason = "查無對應合同"
    else:
        reason = "查無此項"
    return subject, left_role, right_role, reason
