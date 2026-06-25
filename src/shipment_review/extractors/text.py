from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from shipment_review.models import Issue, IssueSeverity

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}
TEXT_SUFFIXES = {".txt", ".csv"}
# Prefix of the low-confidence OCR issue; downstream code (ocr_gaps) keys off it.
OCR_LOW_CONFIDENCE_MARK = "OCR 信心不足"


@dataclass(frozen=True)
class OcrToken:
    text: str
    confidence: float
    x: float
    y: float


@dataclass(frozen=True)
class Extraction:
    text: str = ""
    tokens: list[OcrToken] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)


def extract_document(path: Path | str, *, min_confidence: float = 0.6) -> Extraction:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return Extraction(text=path.read_text(encoding="utf-8", errors="ignore"))
    if suffix == ".pdf":
        return _extract_pdf(path, min_confidence=min_confidence)
    if suffix in IMAGE_SUFFIXES:
        return _extract_image(path, min_confidence=min_confidence)
    return Extraction()


def read_pdf_native_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def rows_from_tokens(tokens: list[OcrToken], y_tolerance: float = 12.0) -> list[list[OcrToken]]:
    """Cluster tokens into rows by vertical position, ordered left-to-right."""
    rows: list[list[OcrToken]] = []
    for token in sorted(tokens, key=lambda t: t.y):
        placed = False
        for row in rows:
            if abs(row[0].y - token.y) <= y_tolerance:
                row.append(token)
                placed = True
                break
        if not placed:
            rows.append([token])
    for row in rows:
        row.sort(key=lambda t: t.x)
    return rows


def _extract_pdf(path: Path, *, min_confidence: float) -> Extraction:
    try:
        native = read_pdf_native_text(path)
    except Exception:
        native = ""
    if native.strip():
        return Extraction(text=native)
    # Scanned/stamped PDF: render each page and OCR it.
    if not _ocr_available():
        return Extraction()
    import fitz

    tokens: list[OcrToken] = []
    document = fitz.open(str(path))
    try:
        for index in range(document.page_count):
            page = document[index]
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), alpha=False)
            image_path = path.with_suffix(f".ocr-page-{index + 1}.png")
            pixmap.save(str(image_path))
            try:
                page_tokens = _ocr_tokens(image_path)
            finally:
                image_path.unlink(missing_ok=True)
            tokens.extend(page_tokens)
    finally:
        document.close()
    return _extraction_from_tokens(tokens, min_confidence)


def _extract_image(path: Path, *, min_confidence: float) -> Extraction:
    if not _ocr_available():
        return Extraction()
    tokens = _ocr_tokens(path, pad=40, scale=3)
    return _extraction_from_tokens(tokens, min_confidence)


def _extraction_from_tokens(tokens: list[OcrToken], min_confidence: float) -> Extraction:
    if not tokens:
        return Extraction()
    low_conf = [t for t in tokens if t.confidence < min_confidence]
    issues: list[Issue] = []
    if low_conf:
        lowest = min(t.confidence for t in low_conf)
        issues.append(
            Issue(
                IssueSeverity.MANUAL_REVIEW,
                f"{OCR_LOW_CONFIDENCE_MARK}：此文件有 {len(low_conf)} 個欄位信心值偏低（最低 {lowest:.2f}），請人工確認掃描件可讀性。",
            )
        )
    rows = rows_from_tokens(tokens)
    text = "\n".join(" ".join(tok.text for tok in row) for row in rows)
    return Extraction(text=text, tokens=tokens, issues=issues)


def _ocr_tokens(path: Path, *, pad: int = 0, scale: int = 1) -> list[OcrToken]:
    """Run OCR on an image, padding+upscaling thin strips so detection works."""
    from PIL import Image, ImageOps

    image = Image.open(str(path)).convert("RGB")
    if pad or scale != 1:
        if pad:
            image = ImageOps.expand(image, border=(20, pad, 20, pad), fill="white")
        if scale != 1:
            image = image.resize((image.size[0] * scale, image.size[1] * scale))
    work_path = Path(str(path) + ".prep.png")
    image.save(str(work_path))
    try:
        engine = _ocr_engine()
        result, _ = engine(str(work_path))
    finally:
        work_path.unlink(missing_ok=True)
    if not result:
        return []
    tokens: list[OcrToken] = []
    for box, text, confidence in result:
        xs = [point[0] for point in box]
        ys = [point[1] for point in box]
        tokens.append(OcrToken(text=text, confidence=float(confidence), x=min(xs), y=min(ys)))
    return tokens


def _ocr_available() -> bool:
    try:
        import fitz  # noqa: F401
        from PIL import Image  # noqa: F401
        from rapidocr_onnxruntime import RapidOCR  # noqa: F401
    except Exception:
        return False
    return True


_ENGINE = None


def _ocr_engine():
    global _ENGINE
    if _ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR

        _ENGINE = RapidOCR()
    return _ENGINE
