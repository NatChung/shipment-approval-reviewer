from shipment_review.models import Issue, IssueSeverity, ReviewResult
from shipment_review.report import ReportData, SourceFile, build_report, issue_field
from shipment_review.text_report import format_report_text


def _case(tmp_path):
    # approval ships ZClass; the contract does NOT list it → a ❌ violation naming 出貨項目.
    (tmp_path / "出货审批.txt").write_text(
        "出货审批\n审批编码 1\n合同编号 ZHDEMO-20251124-01\n实际出货为：\n智核ZClass5专业版系统V5.0\n",
        encoding="utf-8",
    )
    (tmp_path / "ZHDEMO-20251124-01.txt").write_text(
        "购销合同\n订单号码 ZHDEMO-20251124-01\n", encoding="utf-8"
    )
    return tmp_path


def test_text_report_shows_two_sided_presence_comparison(tmp_path):
    out = format_report_text(build_report(_case(tmp_path)))

    assert "欄位：出貨項目" in out
    # left side: the file that lists the item, with its value; right side: the file it's
    # missing from, with the reason.
    assert "出貨審批（出货审批.txt）：智核ZClass5专业版系统 V5.0" in out
    assert "合同（ZHDEMO-20251124-01.txt）：查無此項" in out
    assert "⟷" in out


def test_text_report_value_mismatch_shows_both_sides(tmp_path):
    msg = "模組表合同單號 X 的「智核启思云平台管理服务」單價不一致：模組表 2286.0，合同 8000.0。"
    issue = Issue(IssueSeverity.MANUAL_REVIEW, msg)
    report = ReportData(
        case_name="t",
        result=ReviewResult.from_issues([issue]),
        violations=[],
        unverified=[issue],
        confirmed=[],
        approval=None,
        approval_text="",
        contracts=[],
        contract_texts={},
        module_rows=[],
        source_files=[
            SourceFile("module", "/x/模組金核算表.png", "image"),
            SourceFile("contract", "/x/代理商甲合同.pdf", "pdf", "X"),
        ],
    )
    out = format_report_text(report)

    assert "欄位：單價" in out and "「智核启思云平台管理服务」" in out
    assert "模組表（模組金核算表.png）：2286.0" in out
    assert "合同（代理商甲合同.pdf）：8000.0" in out
    assert "⟷" in out


def test_issue_field_picks_conflict_over_contract_number():
    msg = "模組表合同單號 ZHDEMO-20251124-01 的「X」單價不一致：模組表 1，合同 2。"
    assert issue_field(msg) == "單價"


def test_non_presence_messages_keep_full_text_not_a_false_missing():
    # Messages that are NOT "missing on the other side" must keep their full 問題 text and
    # never be rewritten to 「查無此項」 (regression guard for the over-greedy _presence_sides).
    for msg in (
        "模組表項目「智核ZClass5专业版系统」與出貨審批數量不一致：模組表 5，出貨審批 3。",
        "模組表合同單號 ZHDEMO-20251124-01 的「智核ZClass5专业版系统」出貨數量 5 超過合同數量 3，請人工確認。",
        "出貨審批項目「智核ZClass5专业版系统」有多種單位，請人工確認。",
        "模組表合同單號 ZHDEMO-20251124-01 的採購公司與合同買方不一致。",
    ):
        issue = Issue(IssueSeverity.MANUAL_REVIEW, msg)
        report = ReportData(
            case_name="t",
            result=ReviewResult.from_issues([issue]),
            violations=[],
            unverified=[issue],
            confirmed=[],
            approval=None,
            approval_text="",
            contracts=[],
            contract_texts={},
            module_rows=[],
            source_files=[SourceFile("module", "/x/m.png", "image")],
        )
        out = format_report_text(report)
        assert "查無此項" not in out
        assert msg in out  # the true message is preserved verbatim
