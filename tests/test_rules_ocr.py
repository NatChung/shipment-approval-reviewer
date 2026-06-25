from shipment_review.models import (
    Approval,
    CaseData,
    Contract,
    ContractItem,
    IssueSeverity,
    ModuleRow,
    ReviewStatus,
    ShipmentItem,
    UnverifiedPolicy,
)
from shipment_review.rules import review_case


def _approval(**over):
    data = dict(
        source_file="a.pdf",
        approval_code="A1",
        contract_numbers=["ZHDEMO-20251124-01"],
        shipment_companies=["四川代理商甲信息技术有限公司"],
        school_name="示范乙校",
        actual_items=[ShipmentItem(code="T5-3", name="智核ZClass5专业版系统", model="V5.0", unit="套", quantity=1, source="field")],
        approver_statuses={"财务确认": "已同意", "产品管理经理": "已同意", "智核CEO": "已同意"},
        attached_contract_files=["ZHDEMO-20251124-01.pdf"],
    )
    data.update(over)
    return Approval(**data)


def _contract(**over):
    data = dict(
        source_file="ZHDEMO-20251124-01.pdf",
        contract_number="ZHDEMO-20251124-01",
        buyer_name="四川代理商甲信息技术有限公司",
        seller_name="智核（成都）信息技术有限公司",
        school_name="示范乙校",
        items=[ContractItem(code="T5-3", name="智核ZClass5专业版系统", model="V5.0", unit="套", quantity=1, unit_price=2500.0)],
        readable=True,
    )
    data.update(over)
    return Contract(**data)


def _module_row(**over):
    data = dict(
        source_file="m.png",
        contract_number="ZHDEMO-20251124-01",
        purchasing_company="四川代理商甲信息技术有限公司",
        product_name="智核ZClass5专业版系统",
        model="V5.0",
        unit="套",
        quantity=1,
        unit_price=2500.0,
        amount=2500.0,
        royalty=750.0,
        code="T5-3",
    )
    data.update(over)
    return ModuleRow(**data)


def test_ocr_misread_contract_number_still_matches_contract():
    row = _module_row(contract_number="ZDEMO-20251124-01")
    result = review_case(CaseData(
        approval=_approval(),
        contracts=[_contract()],
        module_rows=[row],
    ))

    assert not any("找不到對應合同" in issue.message for issue in result.issues)
    assert not any("未出現在出貨審批中" in issue.message for issue in result.issues)
    assert result.status is not ReviewStatus.BLOCKED


def test_approval_item_with_code_matches_contract_item_without_code():
    """Approval item has a product code; the contract lists the same product by name+model only.

    The cross-source match must succeed via name+model — no 未在任何合同中找到 hard block.
    """
    approval = _approval(
        actual_items=[ShipmentItem(code="T5-3", name="智核ZClass5专业版系统", model="V5.0", unit="套", quantity=1, source="field")],
    )
    # Contract item has NO code — mirrors real-data contracts.
    contract = _contract(
        items=[ContractItem(code=None, name="智核ZClass5专业版系统", model="V5.0", unit="套", quantity=1, unit_price=2500.0)],
    )
    module_row = _module_row(code=None)

    result = review_case(CaseData(
        approval=approval,
        contracts=[contract],
        module_rows=[module_row],
    ))

    item_not_found_issues = [
        issue for issue in result.issues
        if "未在任何合同中找到" in issue.message
    ]
    assert item_not_found_issues == [], (
        f"Expected no '未在任何合同中找到' hard blocks, got: {[i.message for i in item_not_found_issues]}"
    )
    assert not any(issue.severity is IssueSeverity.HARD_BLOCK for issue in result.issues), (
        f"Expected no hard blocks at all, got: {[i.message for i in result.issues if i.severity is IssueSeverity.HARD_BLOCK]}"
    )


def test_item_not_found_all_ocr_contracts_yields_manual_review():
    """When all contracts are OCR-extracted scans and an item isn't matched,
    the result must be MANUAL_REVIEW (not BLOCKED) with an honest 合同為掃描件 message.
    """
    ocr_contract = _contract(
        ocr_extracted=True,
        items=[],  # empty — OCR failed to extract items
    )
    approval = _approval(
        actual_items=[ShipmentItem(code="T5-3", name="智核ZClass5专业版系统", model="V5.0", unit="套", quantity=1, source="field")],
    )
    result = review_case(CaseData(
        approval=approval,
        contracts=[ocr_contract],
        module_rows=[_module_row()],
    ))

    assert result.status is ReviewStatus.MANUAL_REVIEW, (
        f"Expected MANUAL_REVIEW (not BLOCKED), got {result.status}. Issues: {[i.message for i in result.issues]}"
    )
    assert any("合同為掃描件" in issue.message for issue in result.issues), (
        f"Expected a '合同為掃描件' message, got: {[i.message for i in result.issues]}"
    )
    assert not any(issue.severity is IssueSeverity.HARD_BLOCK for issue in result.issues), (
        f"Expected no HARD_BLOCK issues, got: {[i.message for i in result.issues if issue.severity is IssueSeverity.HARD_BLOCK]}"
    )


def test_item_not_found_with_reliable_contract_still_hard_blocks():
    """When a reliable (non-OCR) contract is present and an item isn't found,
    the result must remain BLOCKED — regression guard for the reliable-contract path.
    """
    reliable_contract = _contract(
        ocr_extracted=False,
        items=[ContractItem(code="T5-3", name="智核ZClass5专业版系统", model="V5.0", unit="套", quantity=1, unit_price=2500.0)],
    )
    unknown_item = ShipmentItem(code=None, name="不存在的產品", model=None, unit="套", quantity=1, source="field")
    approval = _approval(actual_items=[unknown_item])
    result = review_case(CaseData(
        approval=approval,
        contracts=[reliable_contract],
        module_rows=[_module_row()],
    ))

    assert result.status is ReviewStatus.BLOCKED, (
        f"Expected BLOCKED when reliable contract present and item missing, got {result.status}"
    )
    assert any("未在任何合同中找到" in issue.message for issue in result.issues), (
        f"Expected '未在任何合同中找到' hard block, got: {[i.message for i in result.issues]}"
    )


def test_module_row_none_quantity_does_not_report_quantity_mismatch():
    """A module row with no quantity (OCR dropped it) must NOT trigger 數量不一致."""
    result = review_case(CaseData(
        approval=_approval(),
        contracts=[_contract()],
        module_rows=[_module_row(quantity=None)],
    ))
    assert not any("數量不一致" in i.message for i in result.issues), (
        f"Expected no 數量不一致 issues when module row quantity is None, got: {[i.message for i in result.issues if '數量不一致' in i.message]}"
    )


def test_module_row_quantity_mismatch_still_reported_when_both_present():
    """When both module row and contract/approval quantities are present but differ, 數量不一致 must still be reported."""
    result = review_case(CaseData(
        approval=_approval(),
        contracts=[_contract()],
        module_rows=[_module_row(quantity=9)],  # contract/approval qty is 1
    ))
    assert any("數量不一致" in i.message for i in result.issues), (
        f"Expected a 數量不一致 issue when module row quantity=9 vs contract/approval quantity=1, got: {[i.message for i in result.issues]}"
    )


def test_module_table_present_but_unparseable_is_manual_review():
    """A module table file that exists but yields 0 rows (xlsx / thin scan) must be
    MANUAL_REVIEW, not BLOCKED — the file is present, we just can't auto-parse it."""
    result = review_case(CaseData(
        approval=_approval(),
        contracts=[_contract()],
        module_rows=[],
        module_table_present=True,
    ))
    assert result.status is ReviewStatus.MANUAL_REVIEW, (
        f"Expected MANUAL_REVIEW when module table is present but unparseable, got {result.status}"
    )
    assert any("無法自動解析" in i.message for i in result.issues), (
        f"Expected a '無法自動解析' issue, got: {[i.message for i in result.issues]}"
    )


def test_module_table_truly_missing_is_unverified():
    """A truly-missing module table is ⚠️ could-not-verify, not a proven violation:
    需人工確認 under default focused-manual, 不可出貨 under fail-closed."""
    case = CaseData(
        approval=_approval(),
        contracts=[_contract()],
        module_rows=[],
        module_table_present=False,
    )
    assert review_case(case).status is ReviewStatus.MANUAL_REVIEW
    assert review_case(case, UnverifiedPolicy.BLOCK).status is ReviewStatus.BLOCKED
    assert any("缺少模組金核算表" in i.message for i in review_case(case).issues)


