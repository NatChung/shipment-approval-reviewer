from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from shipment_review.extractors.text import IMAGE_SUFFIXES

DOCUMENT_SUFFIXES = {".pdf", ".txt"}
# Formats extract_document can actually read (images via OCR, plain-text exports).
READABLE_MODULE_SUFFIXES = IMAGE_SUFFIXES | {".txt", ".csv"}
# A module table may also arrive as a spreadsheet the extractor cannot read yet.
MODULE_TABLE_SUFFIXES = READABLE_MODULE_SUFFIXES | {".xlsx", ".xls"}
MODULE_NAME_MARKERS = ("模組", "模组", "核算", "权益金", "權益金")
APPROVAL_MARKER = "出货审批"
APPROVAL_EXCLUDE_MARKER = "审批"
# A 通用审批 (general approval) can authorize 0元 service items that appear in no
# contract. This marker is deliberately narrower than APPROVAL_EXCLUDE_MARKER so that
# unrelated 审批 documents (出货审批, 折扣审批, …) never trigger that authorization path.
GENERAL_APPROVAL_MARKER = "通用审批"


@dataclass(frozen=True)
class DetectedFiles:
    case_dir: Path
    approval: Path | None
    module_table: Path | None
    contracts: list[Path]


def detect_case_files(case_dir: Path | str) -> DetectedFiles:
    root = Path(case_dir)
    files = sorted(path for path in root.iterdir() if path.is_file() and not path.name.startswith("."))
    approval = _find_approval(files)
    module_table = _find_module_table(files)
    contracts = [
        path
        for path in files
        if path.suffix.lower() in DOCUMENT_SUFFIXES
        and path != approval
        and path != module_table
        and APPROVAL_EXCLUDE_MARKER not in path.name
    ]
    return DetectedFiles(case_dir=root, approval=approval, module_table=module_table, contracts=contracts)


def _find_approval(files: list[Path]) -> Path | None:
    for path in files:
        if path.suffix.lower() in DOCUMENT_SUFFIXES and APPROVAL_MARKER in path.name:
            return path
    for path in files:
        if path.suffix.lower() in DOCUMENT_SUFFIXES and APPROVAL_MARKER in _read_head(path):
            return path
    return None


def _find_module_table(files: list[Path]) -> Path | None:
    # 1. A name-marked table in a format the extractor can read.
    for path in files:
        if path.suffix.lower() in READABLE_MODULE_SUFFIXES and any(marker in path.name for marker in MODULE_NAME_MARKERS):
            return path
    # 2. Any image — real module tables are DingTalk pngs whose names carry no marker.
    #    Preferred over an unreadable spreadsheet so a readable png next to a 模组金.xlsx wins.
    images = [path for path in files if path.suffix.lower() in IMAGE_SUFFIXES]
    if images:
        return images[0]
    # 3. Last resort: a name-marked spreadsheet we cannot parse yet, so the review
    #    reports "detected but could not parse" instead of "missing module table".
    for path in files:
        if path.suffix.lower() in MODULE_TABLE_SUFFIXES and any(marker in path.name for marker in MODULE_NAME_MARKERS):
            return path
    return None


def _read_head(path: Path) -> str:
    try:
        if path.suffix.lower() == ".pdf":
            from shipment_review.extractors.text import read_pdf_native_text

            return read_pdf_native_text(path)[:5000]
        return path.read_text(encoding="utf-8", errors="ignore")[:5000]
    except Exception:
        return ""
