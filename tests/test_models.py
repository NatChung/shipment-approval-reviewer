from copy import deepcopy
from dataclasses import asdict

import pytest

from shipment_review.models import (
    Approval,
    CaseData,
    Contract,
    ContractItem,
    FrozenDict,
    Issue,
    IssueSeverity,
    ModuleRow,
    ReviewResult,
    ReviewStatus,
    UnverifiedPolicy,
)


def test_review_result_prefers_hard_block_over_manual_review():
    result = ReviewResult.from_issues([
        Issue(IssueSeverity.MANUAL_REVIEW, "單價需確認"),
        Issue(IssueSeverity.HARD_BLOCK, "缺少出貨審批"),
    ])

    assert result.status is ReviewStatus.BLOCKED
    assert result.title == "不可出貨"


def test_review_result_manual_review_when_no_hard_block():
    result = ReviewResult.from_issues([
        Issue(IssueSeverity.MANUAL_REVIEW, "OCR 無法確認合同單號"),
    ])

    assert result.status is ReviewStatus.MANUAL_REVIEW
    assert result.title == "需人工確認"


def test_review_result_pass_when_no_issues():
    assert ReviewResult.from_issues([]).status is ReviewStatus.APPROVED


def test_unverified_only_is_manual_under_default_policy():
    # An ⚠️ "could-not-verify" issue (e.g. missing module table) maps to 需人工確認 under
    # the default focused-manual policy, even when carried as a HARD_BLOCK severity.
    result = ReviewResult.from_issues([
        Issue(IssueSeverity.HARD_BLOCK, "缺少模組金核算表。", unverified=True),
    ])
    assert result.status is ReviewStatus.MANUAL_REVIEW


def test_unverified_only_blocks_under_fail_closed_policy():
    result = ReviewResult.from_issues(
        [Issue(IssueSeverity.HARD_BLOCK, "缺少模組金核算表。", unverified=True)],
        unverified_policy=UnverifiedPolicy.BLOCK,
    )
    assert result.status is ReviewStatus.BLOCKED


def test_real_violation_blocks_regardless_of_policy():
    # A proven violation (not unverified) blocks even under focused-manual.
    for policy in (UnverifiedPolicy.MANUAL, UnverifiedPolicy.BLOCK):
        result = ReviewResult.from_issues(
            [Issue(IssueSeverity.HARD_BLOCK, "出貨項目未在任何合同中找到。")],
            unverified_policy=policy,
        )
        assert result.status is ReviewStatus.BLOCKED


def test_manual_severity_is_unverified_tier():
    # A MANUAL_REVIEW issue is an ⚠️ tier (could-not-verify) → manual under default,
    # block under fail-closed.
    issues = [Issue(IssueSeverity.MANUAL_REVIEW, "模組表單價不一致。")]
    assert ReviewResult.from_issues(issues).status is ReviewStatus.MANUAL_REVIEW
    assert ReviewResult.from_issues(
        issues, unverified_policy=UnverifiedPolicy.BLOCK
    ).status is ReviewStatus.BLOCKED


def test_violation_wins_over_unverified():
    result = ReviewResult.from_issues([
        Issue(IssueSeverity.MANUAL_REVIEW, "OCR 核不到。"),
        Issue(IssueSeverity.HARD_BLOCK, "採購公司與合同買方不一致。"),
    ])
    assert result.status is ReviewStatus.BLOCKED


def test_models_hold_case_data():
    approval = Approval(
        source_file="approval.pdf",
        approval_code="202606091044000425537",
        contract_numbers=["ZHDEMO-20251124-01"],
        shipment_companies=["四川代理商甲信息技术有限公司"],
        school_name="示范乙校",
        actual_items=[],
        approver_statuses={"财务确认": "已同意"},
        attached_contract_files=["ZHDEMO-20251124-01.pdf"],
    )
    contract = Contract(
        source_file="ZHDEMO-20251124-01.pdf",
        contract_number="ZHDEMO-20251124-01",
        buyer_name="四川代理商甲信息技术有限公司",
        seller_name="智核（成都）信息技术有限公司",
        school_name="示范乙校",
        items=[ContractItem(name="智核ZClass5专业版系统", model="V5.0", unit="套", quantity=1, unit_price=2500.0)],
        readable=True,
    )
    row = ModuleRow(
        source_file="module.png",
        contract_number="ZHDEMO-20251124-01",
        purchasing_company="四川代理商甲信息技术有限公司",
        product_name="智核ZClass5专业版系统",
        model="V5.0",
        unit="套",
        quantity=1,
        unit_price=2500.0,
        amount=2500.0,
        royalty=750.0,
    )
    case = CaseData(
        approval=approval,
        contracts=[contract],
        module_rows=[row],
        expected_contract_files=["ZHDEMO-20251124-01.pdf"],
    )

    assert case.approval == approval
    assert case.contracts == (contract,)
    assert case.module_rows == (row,)
    assert approval.contract_numbers == (contract.contract_number,)
    assert row.purchasing_company == contract.buyer_name


def test_case_data_carries_extraction_state():
    issue = Issue(IssueSeverity.MANUAL_REVIEW, "OCR 信心不足，請確認合同單號。")
    case = CaseData(
        approval=None,
        contracts=[],
        module_rows=[],
        extraction_issues=[issue],
    )

    assert case.extraction_issues == (issue,)


def test_collection_fields_are_isolated_and_immutable_after_construction():
    contract_numbers = ["ZHDEMO-20251124-01"]
    approver_statuses = {"财务确认": "已同意"}
    approval = Approval(
        source_file="approval.pdf",
        approval_code="202606091044000425537",
        contract_numbers=contract_numbers,
        shipment_companies=["四川代理商甲信息技术有限公司"],
        school_name="示范乙校",
        actual_items=[],
        approver_statuses=approver_statuses,
    )
    contract_numbers.append("MUTATED")
    approver_statuses["财务确认"] = "MUTATED"

    assert approval.contract_numbers == ("ZHDEMO-20251124-01",)
    assert approval.approver_statuses["财务确认"] == "已同意"
    with pytest.raises(AttributeError):
        approval.contract_numbers.append("MUTATED AGAIN")
    with pytest.raises(TypeError):
        approval.approver_statuses["财务确认"] = "MUTATED AGAIN"
    with pytest.raises(TypeError):
        approval.approver_statuses |= {"新角色": "已同意"}

    issue = Issue(IssueSeverity.MANUAL_REVIEW, "單價需確認")
    issues = [issue]
    checks = ["合同存在"]
    result = ReviewResult.from_issues(issues, checks=checks)
    issues.append(Issue(IssueSeverity.HARD_BLOCK, "缺少出貨審批"))
    checks.append("MUTATED")

    assert result.status is ReviewStatus.MANUAL_REVIEW
    assert result.issues == (issue,)
    assert result.checks == ("合同存在",)


def test_frozen_dict_supports_copy_and_dataclass_conversion():
    approval = Approval(
        source_file="approval.pdf",
        approval_code="202606091044000425537",
        contract_numbers=["ZHDEMO-20251124-01"],
        shipment_companies=["四川代理商甲信息技术有限公司"],
        school_name="示范乙校",
        actual_items=[],
        approver_statuses={"财务确认": "已同意"},
    )

    copied = deepcopy(approval)
    converted = asdict(approval)

    assert isinstance(approval.approver_statuses, FrozenDict)
    assert copied.approver_statuses["财务确认"] == "已同意"
    assert converted["approver_statuses"] == {"财务确认": "已同意"}


def test_contract_number_inferred_defaults_false_and_replaceable():
    from dataclasses import replace
    c = Contract(source_file="x.pdf", contract_number=None, buyer_name=None, seller_name=None,
                 school_name=None, items=[], readable=True)
    assert c.number_inferred is False
    c2 = replace(c, contract_number="ZHDEMO-20231211-01", number_inferred=True)
    assert c2.number_inferred is True and c2.contract_number == "ZHDEMO-20231211-01"
