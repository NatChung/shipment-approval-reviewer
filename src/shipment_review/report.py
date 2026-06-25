"""Assemble a structured review report: the verdict in three tiers plus the source
materials (approval text, contract items, module rows) so a reviewer can compare against
the originals. Shared by the text formatter and the HTML review page.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from shipment_review.extractors.approval import parse_approval_text
from shipment_review.extractors.contract import parse_contract
from shipment_review.extractors.files import detect_case_files
from shipment_review.extractors.module_table import parse_module_table
from shipment_review.extractors.text import IMAGE_SUFFIXES, extract_document
from shipment_review.extractors.transcript import TranscriptError, load_contract_transcript, load_module_transcript
from shipment_review.formatters import confirmed_checks, unverified_issues, violation_issues
from shipment_review.models import (
    Approval,
    CaseData,
    Contract,
    Issue,
    IssueSeverity,
    ModuleRow,
    ReviewResult,
    UnverifiedPolicy,
)
from shipment_review.normalization import (
    contract_numbers_match,
    extract_contract_numbers,
    normalize_text,
    products_match,
)
from shipment_review.rules import backfill_inferred_contract_numbers, review_case


@dataclass(frozen=True)
class SourceFile:
    role: str  # "approval" | "contract" | "module"
    path: str  # absolute
    kind: str  # "image" | "pdf" | "spreadsheet" | "text"
    contract_number: str | None = None


FILE_ROLE_LABEL = {"approval": "出貨審批", "contract": "合同", "module": "模組表"}

# Which column an issue is about, by the term its message names. Ordered so the conflicting
# field (單價/數量/單位…) wins over an incidental 合同單號, and 模組表項目 over 出貨項目.
_FIELD_KEYWORDS = (
    "單價", "數量", "單位", "採購公司", "買方", "出貨內容",
    "模組表項目", "出貨項目", "合同單號", "模組金核算表", "品項",
)


def issue_field(message: str) -> str | None:
    """The field/column an issue concerns, or None if it names no known field."""
    for keyword in _FIELD_KEYWORDS:
        if keyword in message:
            return keyword
    return None


def issue_source_files(report: "ReportData", message: str) -> list["SourceFile"]:
    """The original files an issue refers to, by what its text mentions (審批 / 模組表 /
    合同). A file missing from the case simply yields nothing."""
    by_role: dict[str, list[SourceFile]] = {}
    for sf in report.source_files:
        by_role.setdefault(sf.role, []).append(sf)
    picked: list[SourceFile] = []
    if any(k in message for k in ("出貨審批", "出貨項目", "出貨內容", "審批")):
        picked += by_role.get("approval", [])
    if "模組" in message:
        picked += by_role.get("module", [])
    if "合同" in message or "掃描件" in message:
        picked += by_role.get("contract", [])
    seen: set[str] = set()
    return [sf for sf in picked if not (sf.path in seen or seen.add(sf.path))]


def _kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".xlsx", ".xls"}:
        return "spreadsheet"
    return "text"


@dataclass(frozen=True)
class GatheredCase:
    case: CaseData
    approval_text: str
    contract_texts: dict[str, str]  # source_file → raw extracted text (empty for transcripts)
    source_files: list[SourceFile] = field(default_factory=list)


def gather_case(case_dir: Path | str) -> GatheredCase:
    """Run extraction once, keeping the raw texts the verdict path normally discards."""
    detected = detect_case_files(case_dir)
    issues: list[Issue] = []

    approval = None
    approval_text = ""
    attached_files: list[str] = []
    if detected.approval is not None:
        extraction = extract_document(detected.approval)
        issues.extend(extraction.issues)
        approval_text = extraction.text
        approval = parse_approval_text(extraction.text, detected.approval)
        attached_files = list(approval.attached_contract_files)

    contracts: list[Contract] = []
    contract_texts: dict[str, str] = {}
    for path in detected.contracts:
        try:
            transcribed = load_contract_transcript(path)
        except TranscriptError as exc:
            issues.append(Issue(IssueSeverity.MANUAL_REVIEW, f"合約 transcript 無法解析，改用 OCR：{exc}"))
            transcribed = None
        if transcribed is not None:
            contracts.append(transcribed)
            contract_texts[transcribed.source_file] = ""  # authored transcript, no raw text
            continue
        extraction = extract_document(path)
        issues.extend(extraction.issues)
        contract = parse_contract(extraction, path, attached_files)
        contracts.append(contract)
        contract_texts[contract.source_file] = extraction.text

    module_rows: list[ModuleRow] = []
    if detected.module_table is not None:
        transcribed_rows = None
        try:
            transcribed_rows = load_module_transcript(detected.module_table)
        except TranscriptError as exc:
            issues.append(Issue(IssueSeverity.MANUAL_REVIEW, f"模組表 transcript 無法解析，改用 OCR：{exc}"))
        if transcribed_rows is not None:
            module_rows = transcribed_rows
        else:
            extraction = extract_document(detected.module_table)
            issues.extend(extraction.issues)
            module_rows = parse_module_table(extraction, detected.module_table)

    if approval is not None:
        contracts = backfill_inferred_contract_numbers(contracts, approval.contract_numbers, module_rows)

    source_files: list[SourceFile] = []
    if detected.approval is not None:
        p = detected.approval.resolve()
        source_files.append(SourceFile("approval", str(p), _kind(p)))
    for contract in contracts:
        p = Path(contract.source_file).resolve()
        source_files.append(SourceFile("contract", str(p), _kind(p), contract.contract_number))
    if detected.module_table is not None:
        p = detected.module_table.resolve()
        source_files.append(SourceFile("module", str(p), _kind(p)))

    case = CaseData(
        approval=approval,
        contracts=contracts,
        module_rows=module_rows,
        module_table_present=detected.module_table is not None,
        expected_contract_files=attached_files,
        extraction_issues=issues,
    )
    return GatheredCase(case=case, approval_text=approval_text, contract_texts=contract_texts, source_files=source_files)


@dataclass(frozen=True)
class ReportData:
    case_name: str
    result: ReviewResult
    violations: list[Issue]
    unverified: list[Issue]
    confirmed: list[str]
    approval: Approval | None
    approval_text: str
    contracts: list[Contract]
    contract_texts: dict[str, str]
    module_rows: list[ModuleRow] = field(default_factory=list)
    source_files: list[SourceFile] = field(default_factory=list)
    ai_unconfirmed_contracts: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Anchor:
    panel_id: str
    row_index: int | None


_BRACKET_RE = re.compile(r"「([^」]*)」")


def _row_index_by_name(target: str | None, rows: list[tuple[str | None, str, str | None]]) -> int | None:
    """Match the bracket text against each row. `rows` is (code, name, model). The rule built
    the bracket as `f"{name} {model or ''}"` or `name`, so first try deterministic equality on
    both reconstructions (reliable when bracket and row share a source); then fall back to the
    project's `products_match` (handles cross-source brand/系统/version noise, e.g. a module
    product name matched against a contract line)."""
    if not target:
        return None
    want = normalize_text(target)
    for i, (code, name, model) in enumerate(rows):
        combined = f"{name} {model or ''}".strip()
        if normalize_text(combined) == want or normalize_text(name) == want:
            return i
    for i, (code, name, model) in enumerate(rows):
        if products_match(None, target, None, code, name, model):
            return i
    return None


def issue_anchor(message: str, report: ReportData) -> Anchor | None:
    bracket = (_BRACKET_RE.search(message) or [None, None])[1]
    bracket = bracket.strip() if bracket else None

    if message.startswith("出貨項目") and report.approval is not None:
        rows = [(it.code, it.name, it.model) for it in report.approval.actual_items]
        return Anchor("panel-approval", _row_index_by_name(bracket, rows))

    # 模組表… and 出貨審批項目… (unit/quantity mismatches) both carry a module product name.
    if message.startswith("模組表") or message.startswith("出貨審批項目"):
        rows = [(r.code, r.product_name, r.model) for r in report.module_rows]
        return Anchor("panel-module", _row_index_by_name(bracket, rows))

    # contract-number forms (e.g. 合同 X 中…). Pick the contract panel by number.
    numbers = extract_contract_numbers(message)
    for n, contract in enumerate(report.contracts):
        if any(contract_numbers_match(num, contract.contract_number) for num in numbers):
            rows = [(it.code, it.name, it.model) for it in contract.items]
            return Anchor(f"panel-contract-{n}", _row_index_by_name(bracket, rows))

    return None


def build_report(
    case_dir: Path | str, unverified_policy: UnverifiedPolicy = UnverifiedPolicy.MANUAL
) -> ReportData:
    gathered = gather_case(case_dir)
    result = review_case(gathered.case, unverified_policy)
    return ReportData(
        case_name=Path(case_dir).name,
        result=result,
        violations=violation_issues(result),
        unverified=unverified_issues(result),
        confirmed=confirmed_checks(result),
        approval=gathered.case.approval,
        approval_text=gathered.approval_text,
        contracts=list(gathered.case.contracts),
        contract_texts=gathered.contract_texts,
        module_rows=list(gathered.case.module_rows),
        source_files=gathered.source_files,
        ai_unconfirmed_contracts=[
            Path(c.source_file).name for c in gathered.case.contracts if c.ai_unconfirmed
        ],
    )
