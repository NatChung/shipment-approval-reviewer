from pathlib import Path

import pytest

from shipment_review.cli import run
from shipment_review.extractors.text import _ocr_available
from shipment_review.models import ReviewStatus
from shipment_review.report import build_report

REPO_ROOT = Path(__file__).resolve().parents[1]
CHONGZHOU = REPO_ROOT / "test-data/2026/6月/0610-四川代理商甲信息技术有限公司-四川代理商乙昆吾信息产业有限公司-示范乙校"


@pytest.mark.skipif(not _ocr_available(), reason="OCR extras not installed")
@pytest.mark.skipif(not CHONGZHOU.exists(), reason="real test-data not present")
def test_chongzhou_case_runs_end_to_end():
    output = run(CHONGZHOU)

    assert output.startswith("審核結果：")
    assert any(status in output for status in ("可出貨", "不可出貨", "需人工確認"))


_DATA = Path(__file__).resolve().parents[1] / "test-data" / "2026"
# 可出貨 = ReviewStatus.APPROVED; 需人工確認 = ReviewStatus.MANUAL_REVIEW (verified against models.py).
_EXPECTED = {
    "0409": ReviewStatus.MANUAL_REVIEW, "0421": ReviewStatus.APPROVED,
    "0512": ReviewStatus.APPROVED, "0518-示范丁校": ReviewStatus.MANUAL_REVIEW,
    "0518-四川代理商甲": ReviewStatus.MANUAL_REVIEW, "0521": ReviewStatus.MANUAL_REVIEW,
    "0527": ReviewStatus.MANUAL_REVIEW, "0610": ReviewStatus.MANUAL_REVIEW,
}


@pytest.mark.skipif(not _ocr_available(), reason="OCR extras not installed")
@pytest.mark.skipif(not _DATA.exists(), reason="real test-data not present (gitignored)")
@pytest.mark.parametrize("prefix,expected", list(_EXPECTED.items()))
def test_batch_verdicts_after_elimination(prefix, expected):
    case = next(p for p in _DATA.glob("*/*") if p.is_dir() and p.name.startswith(prefix))
    assert build_report(case).result.status is expected
