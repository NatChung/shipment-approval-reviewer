from shipment_review.formatters import format_result
from shipment_review.models import Issue, IssueSeverity, ReviewResult


def test_format_approved_shows_confirmed_tier():
    text = format_result(ReviewResult.from_issues([], ["出貨審批已完成"]))

    assert text.startswith("審核結果：可出貨")
    assert "✅ 已確認：" in text
    assert "- 出貨審批已完成" in text


def test_format_unverified_only_lists_under_warning_tier():
    text = format_result(ReviewResult.from_issues([
        Issue(IssueSeverity.MANUAL_REVIEW, "模組表單價不一致，請確認。"),
        Issue(IssueSeverity.MANUAL_REVIEW, "OCR 信心不足，請確認合同單號。"),
    ]))

    assert text.startswith("審核結果：需人工確認")
    assert "⚠️ 待人工核實：" in text
    assert "1. 模組表單價不一致，請確認。" in text
    assert "2. OCR 信心不足，請確認合同單號。" in text
    assert "❌ 違規事項：" not in text


def test_format_separates_violation_and_unverified_tiers():
    text = format_result(ReviewResult.from_issues([
        Issue(IssueSeverity.HARD_BLOCK, "採購公司與合同買方不一致。"),
        Issue(IssueSeverity.MANUAL_REVIEW, "合同為掃描件，OCR 核不到。"),
    ]))

    assert text.startswith("審核結果：不可出貨")
    assert "❌ 違規事項：" in text
    assert "1. 採購公司與合同買方不一致。" in text
    # The could-not-verify item is still shown — under its own ⚠️ tier, not hidden.
    assert "⚠️ 待人工核實：" in text
    assert "合同為掃描件" in text


def test_format_confirmed_check_suppressed_when_contradicted():
    text = format_result(ReviewResult.from_issues(
        [Issue(IssueSeverity.MANUAL_REVIEW, "模組表合同單號 X 的「Y」單價不一致：模組表 1，合同 2。")],
        ["模組表合同單號均可對應合同", "出貨項目均可在合同中找到", "模組表單價與合同單價一致"],
    ))

    assert "- 模組表合同單號均可對應合同" in text  # unrelated check still confirmed
    assert "模組表單價與合同單價一致" not in text  # contradicted → not shown


def test_format_unverified_hard_block_is_warning_not_violation():
    text = format_result(ReviewResult.from_issues(
        [Issue(IssueSeverity.HARD_BLOCK, "缺少模組金核算表。", unverified=True)]
    ))

    assert text.startswith("審核結果：需人工確認")
    assert "⚠️ 待人工核實：" in text
    assert "❌ 違規事項：" not in text
