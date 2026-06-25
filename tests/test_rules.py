from shipment_review.models import (
    Approval,
    CaseData,
    Contract,
    ContractItem,
    Issue,
    IssueSeverity,
    ModuleRow,
    ReviewStatus,
    ShipmentItem,
    UnverifiedPolicy,
)
from shipment_review.rules import review_case


def approval(**overrides):
    data = dict(
        source_file="approval.pdf",
        approval_code="A1",
        contract_numbers=["ZHDEMO-20251124-01"],
        shipment_companies=["四川代理商甲信息技术有限公司"],
        school_name="示范乙校",
        actual_items=[
            ShipmentItem(
                code="T5-3",
                name="智核ZClass5专业版系统",
                model="V5.0",
                unit="套",
                quantity=1,
                source="field",
            )
        ],
        approver_statuses={"财务确认": "已同意", "产品管理经理": "已同意", "智核CEO": "已同意"},
        attached_contract_files=["ZHDEMO-20251124-01.pdf"],
    )
    data.update(overrides)
    return Approval(**data)


def contract(**overrides):
    data = dict(
        source_file="ZHDEMO-20251124-01.pdf",
        contract_number="ZHDEMO-20251124-01",
        buyer_name="四川代理商甲信息技术有限公司",
        seller_name="智核（成都）信息技术有限公司",
        school_name="示范乙校",
        items=[
            ContractItem(
                code="T5-3",
                name="智核ZClass5专业版系统",
                model="V5.0",
                unit="套",
                quantity=1,
                unit_price=2500.0,
            )
        ],
        readable=True,
    )
    data.update(overrides)
    return Contract(**data)


def module_row(**overrides):
    data = dict(
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
        code="T5-3",
    )
    data.update(overrides)
    return ModuleRow(**data)


def test_inferred_contract_items_are_not_trusted():
    # A number_inferred scan is unread — its (possibly garbled) parsed items must NOT silently
    # pass a shipment item via found_in_trusted. With no reliable contract and no module coverage,
    # the item must surface as a 掃描件 manual-review, never a silent pass.
    item = ShipmentItem(code="A9", name="智核某项", model="V1.0", unit="套", quantity=1, source="field")
    scan = contract(
        contract_number="ZHDEMO-20231211-01", ocr_extracted=True, number_inferred=True,
        items=[ContractItem(code="A9", name="智核某项", model="V1.0", unit="套", quantity=1, unit_price=100)])
    result = review_case(CaseData(
        approval=approval(actual_items=[item], contract_numbers=["ZHDEMO-20231211-01"]),
        contracts=[scan], module_rows=[]))
    assert any("掃描件" in i.message for i in result.issues)


def test_inferred_number_contract_does_not_conjure_module_hardblock():
    from shipment_review.rules import _check_module_row
    from shipment_review.models import IssueSeverity
    # An inferred-number scan: its OCR'd buyer_name disagrees with the module row's purchasing
    # company. Without Guard A this is a HARD_BLOCK (採購公司與合同買方不一致). With it: a single
    # honest manual note, no HARD_BLOCK.
    c = contract(contract_number="ZHDEMO-20231211-01", buyer_name="某亂碼买方", number_inferred=True)
    row = module_row(contract_number="ZHDEMO-20231211-01", purchasing_company="四川代理商乙昆吾信息产业有限公司",
                     product_name="智核AI教研中心智能终端系统")
    issues = _check_module_row(row, [c])
    assert not any(i.severity is IssueSeverity.HARD_BLOCK for i in issues)
    assert any("掃描件" in i.message for i in issues)


def test_ai_unconfirmed_contract_is_not_reliable():
    from shipment_review.rules import _has_reliable_contract
    assert _has_reliable_contract([contract()]) is True
    assert _has_reliable_contract([contract(ai_unconfirmed=True)]) is False


def test_missing_approval_blocks_shipment():
    result = review_case(CaseData(approval=None, contracts=[contract()], module_rows=[module_row()]))
    assert result.status is ReviewStatus.BLOCKED
    assert "缺少出貨審批" in result.issues[0].message


def test_no_readable_contract_is_unverified_policy_driven():
    # Missing/unreadable input is ⚠️ could-not-verify, not a proven violation: 需人工確認
    # under default focused-manual, 不可出貨 under fail-closed.
    case = CaseData(approval=approval(), contracts=[], module_rows=[module_row()])
    assert review_case(case).status is ReviewStatus.MANUAL_REVIEW
    assert review_case(case, UnverifiedPolicy.BLOCK).status is ReviewStatus.BLOCKED
    assert any("沒有可讀合同" in issue.message for issue in review_case(case).issues)


def test_missing_module_table_is_unverified_policy_driven():
    case = CaseData(approval=approval(), contracts=[contract()], module_rows=[])
    assert review_case(case).status is ReviewStatus.MANUAL_REVIEW
    assert review_case(case, UnverifiedPolicy.BLOCK).status is ReviewStatus.BLOCKED
    assert any("缺少模組金核算表" in issue.message for issue in review_case(case).issues)


def test_partial_unreadable_expected_contract_is_manual_review_with_filename():
    result = review_case(
        CaseData(
            approval=approval(),
            contracts=[contract(source_file="ZHDEMO-20251124-01.pdf")],
            module_rows=[module_row()],
            expected_contract_files=["ZHDEMO-20251124-01.pdf", "ZHDEMO-20231211-01.pdf"],
        )
    )

    assert result.status is ReviewStatus.MANUAL_REVIEW
    assert any("ZHDEMO-20231211-01.pdf" in issue.message for issue in result.issues)


def test_expected_contract_present_under_renamed_copy_not_flagged():
    # The approval names the attached contract with copy suffixes ("(1)(1)(1)"), while the
    # file on disk carries a different suffix — but the SAME contract number. The contract
    # is present and readable; it must not be reported missing. Match by contract number,
    # not by fragile filename (this is the 0512 代理商丁 regression).
    result = review_case(
        CaseData(
            approval=approval(
                attached_contract_files=["ZHDEMO-20251124-01（双章）智核-代理商丁(1)(1)(1)(1)(1)(1).pdf"]
            ),
            contracts=[
                contract(
                    source_file="/abs/case/ZHDEMO-20251124-01（双章）智核-代理商丁(1).pdf",
                    contract_number="ZHDEMO-20251124-01",
                )
            ],
            module_rows=[module_row()],
            expected_contract_files=["ZHDEMO-20251124-01（双章）智核-代理商丁(1)(1)(1)(1)(1)(1).pdf"],
        )
    )

    assert not any("無法讀取" in issue.message for issue in result.issues)
    assert result.status is ReviewStatus.APPROVED


def test_present_contract_with_full_path_not_reported_missing():
    # The CLI stores contract.source_file as a FULL PATH, while the approval text
    # yields bare filenames. A present, successfully-read contract must not be
    # reported "無法讀取" just because the path doesn't string-equal the basename.
    result = review_case(
        CaseData(
            approval=approval(
                attached_contract_files=[
                    "ZHDEMO-20251124-01.pdf",
                    "申请人乙提交的通用审批202605151455000368378.pdf",
                ]
            ),
            contracts=[contract(source_file="/abs/case-folder/ZHDEMO-20251124-01.pdf")],
            module_rows=[module_row()],
            expected_contract_files=[
                "ZHDEMO-20251124-01.pdf",
                "申请人乙提交的通用审批202605151455000368378.pdf",
            ],
        )
    )

    assert not any("無法讀取" in issue.message for issue in result.issues)


def test_attached_审批_document_not_counted_as_missing_contract():
    # A 通用审批 PDF attached to the approval is not a sales contract (it carries
    # the 审批 marker and is excluded from contracts). It must not be counted as an
    # expected-but-unreadable contract, even though it is physically present on disk.
    result = review_case(
        CaseData(
            approval=approval(
                attached_contract_files=[
                    "ZHDEMO-20251124-01.pdf",
                    "申请人乙提交的通用审批202605151455000368378.pdf",
                ]
            ),
            contracts=[contract(source_file="/abs/case-folder/ZHDEMO-20251124-01.pdf")],
            module_rows=[module_row()],
            expected_contract_files=[
                "ZHDEMO-20251124-01.pdf",
                "申请人乙提交的通用审批202605151455000368378.pdf",
            ],
        )
    )

    assert not any("通用审批" in issue.message for issue in result.issues)


def test_genuinely_missing_contract_still_flagged_despite_full_paths():
    # The genuine check must survive: a real second contract absent from the folder
    # is still reported by filename, while the present full-path contract is not.
    result = review_case(
        CaseData(
            approval=approval(),
            contracts=[contract(source_file="/abs/case-folder/ZHDEMO-20251124-01.pdf")],
            module_rows=[module_row()],
            expected_contract_files=["ZHDEMO-20251124-01.pdf", "ZHDEMO-20231211-01.pdf"],
        )
    )

    assert result.status is ReviewStatus.MANUAL_REVIEW
    assert any("ZHDEMO-20231211-01.pdf" in issue.message for issue in result.issues)
    assert not any("ZHDEMO-20251124-01.pdf" in issue.message for issue in result.issues)


def test_shipment_item_covered_by_matching_contract_module_row_not_blocked():
    # A scanned contract often compresses its line items, but the 模組金核算表 lists
    # the item under the same contract number. Such an item is covered by the deal —
    # it must not hard-block as "未在任何合同中找到".
    extra_item = ShipmentItem(
        code="S5-17", name="电子学生证互动反馈系统", model="V5.0", unit="套", quantity=1, source="field"
    )
    extra_module = module_row(
        code="S5-17", product_name="电子学生证互动反馈系统", unit_price=2000.0, amount=2000.0, royalty=600.0
    )
    result = review_case(
        CaseData(
            approval=approval(actual_items=[extra_item]),
            contracts=[contract()],  # contract lists only ZClass, NOT 电子学生证
            module_rows=[module_row(), extra_module],
        )
    )

    assert not any(
        "未在任何合同中找到" in issue.message and "电子学生证" in issue.message
        for issue in result.issues
    )
    assert result.status is not ReviewStatus.BLOCKED


def test_unmatched_item_with_attached_通用审批_is_manual_not_hard_block():
    # An item that is in neither the contract nor the 模組表, when the approval attaches
    # a 通用审批, is a candidate authorized service the engine cannot structurally verify
    # — escalate to 需人工確認 (AI/human), do not hard-block as 不可出貨.
    service_item = ShipmentItem(
        code="C5-5-1", name="智核智慧学校云平台（基础版）", model="V5.0", unit="年", quantity=3, source="field"
    )
    result = review_case(
        CaseData(
            approval=approval(
                actual_items=[service_item],
                attached_contract_files=[
                    "ZHDEMO-20251124-01.pdf",
                    "申请人乙提交的通用审批202605151455000368378.pdf",
                ],
            ),
            contracts=[contract()],  # no match
            module_rows=[module_row()],  # no match
        )
    )

    assert not any(issue.severity is IssueSeverity.HARD_BLOCK for issue in result.issues)
    assert result.status is ReviewStatus.MANUAL_REVIEW


def test_unrelated_审批_attachment_does_not_suppress_hard_block():
    # The escalation must key off 通用审批 specifically, not the bare 审批 substring.
    # An unrelated 审批 document (e.g. 折扣审批, or the 出货审批 itself) attached to the
    # approval must NOT downgrade a genuinely unsold item — that would silently disable
    # a legitimate hard block.
    rogue_item = ShipmentItem(
        code="Z9-9", name="未售產品", model="V1.0", unit="套", quantity=1, source="field"
    )
    result = review_case(
        CaseData(
            approval=approval(
                actual_items=[rogue_item],
                attached_contract_files=["ZHDEMO-20251124-01.pdf", "折扣审批20260101.pdf"],
            ),
            contracts=[contract()],
            module_rows=[module_row()],
        )
    )

    assert result.status is ReviewStatus.BLOCKED
    assert any("未在任何合同中找到" in issue.message for issue in result.issues)


def test_unmatched_item_without_通用审批_still_hard_blocks():
    # Without any 通用审批 to authorize it, shipping an item absent from every contract
    # remains a hard block — the loosening is scoped to 通用审批 cases only.
    rogue_item = ShipmentItem(
        code="Z9-9", name="未售產品", model="V1.0", unit="套", quantity=1, source="field"
    )
    result = review_case(
        CaseData(
            approval=approval(actual_items=[rogue_item], attached_contract_files=["ZHDEMO-20251124-01.pdf"]),
            contracts=[contract()],
            module_rows=[module_row()],
        )
    )

    assert result.status is ReviewStatus.BLOCKED
    assert any("未在任何合同中找到" in issue.message for issue in result.issues)


def test_unapproved_required_approver_no_longer_blocks():
    # Approver-status gating was removed: an in-progress approval flow (CEO/产品经理
    # not yet reached) is normal and must not block.
    bad = approval(approver_statuses={"财务确认": "已同意"})
    result = review_case(CaseData(approval=bad, contracts=[contract()], module_rows=[module_row()]))
    assert result.status is ReviewStatus.APPROVED
    assert not any("審批角色" in issue.message for issue in result.issues)


def test_module_row_product_in_other_contract_is_manual_review():
    other = contract(contract_number="ZHDEMO-20231211-01", source_file="other.pdf")
    stated = contract(items=[])
    result = review_case(
        CaseData(
            approval=approval(contract_numbers=["ZHDEMO-20251124-01", "ZHDEMO-20231211-01"]),
            contracts=[stated, other],
            module_rows=[module_row()],
        )
    )
    assert result.status is ReviewStatus.MANUAL_REVIEW
    assert any("出現在其他合同" in issue.message for issue in result.issues)


def test_approval_contract_number_mismatch_blocks_shipment():
    result = review_case(
        CaseData(
            approval=approval(contract_numbers=["ZHDEMO-20251124-02"]),
            contracts=[contract()],
            module_rows=[module_row()],
        )
    )

    assert result.status is ReviewStatus.BLOCKED
    assert any("出貨審批合同單號" in issue.message for issue in result.issues)


def test_contract_numbers_are_normalized_before_comparison():
    result = review_case(
        CaseData(
            approval=approval(contract_numbers=[" zhdemo－20251124－01 "]),
            contracts=[contract()],
            module_rows=[module_row()],
        )
    )

    assert result.status is ReviewStatus.APPROVED


def test_approval_contract_number_missing_from_module_rows_is_manual_review():
    second_contract = contract(
        source_file="second.pdf",
        contract_number="ZHDEMO-20251124-02",
        buyer_name="四川代理商乙昆吾信息产业有限公司",
        items=[],
    )
    result = review_case(
        CaseData(
            approval=approval(
                contract_numbers=["ZHDEMO-20251124-01", "ZHDEMO-20251124-02"],
                shipment_companies=["四川代理商甲信息技术有限公司", "四川代理商乙昆吾信息产业有限公司"],
            ),
            contracts=[contract(), second_contract],
            module_rows=[module_row()],
        )
    )

    assert result.status is ReviewStatus.MANUAL_REVIEW
    assert any("審批合同單號未出現在模組表" in issue.message for issue in result.issues)


def test_shipment_company_mismatch_no_longer_flagged():
    # 出貨公司 ↔ 合約買方/模組表採購公司 cross-checks were removed.
    result = review_case(
        CaseData(
            approval=approval(shipment_companies=["四川代理商乙昆吾信息产业有限公司"]),
            contracts=[contract()],
            module_rows=[module_row()],
        )
    )

    assert result.status is ReviewStatus.APPROVED
    assert not any("出貨公司" in issue.message or "買方" in issue.message for issue in result.issues)


def test_school_mismatch_no_longer_flagged():
    # 學校 identity check was removed.
    wrong_school = contract(
        source_file="other.pdf",
        contract_number="ZHDEMO-20251124-02",
        school_name="其他学校",
        items=[],
    )
    result = review_case(
        CaseData(
            approval=approval(contract_numbers=["ZHDEMO-20251124-01", "ZHDEMO-20251124-02"]),
            contracts=[contract(), wrong_school],
            module_rows=[module_row()],
        )
    )

    assert not any("學校" in issue.message for issue in result.issues)


def test_shipment_item_missing_from_all_contracts_blocks_shipment():
    missing_item = ShipmentItem(
        code="A5-3",
        name="智核AI教研中心智能终端系统",
        model="V1.0",
        unit="套",
        quantity=1,
        source="field",
    )
    # The item is in neither the contract nor the 模組表 (module table lists only the
    # unrelated ZClass line), and no 通用审批 is attached — a genuinely unsold item.
    result = review_case(
        CaseData(
            approval=approval(actual_items=[missing_item]),
            contracts=[contract()],
            module_rows=[module_row()],
        )
    )

    assert result.status is ReviewStatus.BLOCKED
    assert any("未在任何合同中找到" in issue.message for issue in result.issues)


def test_module_row_missing_contract_number_is_manual_review():
    result = review_case(
        CaseData(
            approval=approval(),
            contracts=[contract()],
            module_rows=[module_row(contract_number=None)],
        )
    )

    assert result.status is ReviewStatus.MANUAL_REVIEW
    assert any("缺少合同單號" in issue.message for issue in result.issues)


def test_module_purchasing_company_mismatch_blocks_shipment():
    result = review_case(
        CaseData(
            approval=approval(),
            contracts=[contract()],
            module_rows=[module_row(purchasing_company="四川代理商乙昆吾信息产业有限公司")],
        )
    )

    assert result.status is ReviewStatus.BLOCKED
    assert any("採購公司與合同買方不一致" in issue.message for issue in result.issues)


def test_unit_price_mismatch_is_manual_review():
    result = review_case(
        CaseData(
            approval=approval(),
            contracts=[
                contract(
                    items=[
                        ContractItem(
                            code="T5-3",
                            name="智核ZClass5专业版系统",
                            model="V5.0",
                            unit="套",
                            quantity=1,
                            unit_price=3000.0,
                        )
                    ]
                )
            ],
            module_rows=[module_row()],
        )
    )
    assert result.status is ReviewStatus.MANUAL_REVIEW
    assert any("單價不一致" in issue.message for issue in result.issues)


def test_module_row_quantity_mismatch_is_manual_review():
    result = review_case(
        CaseData(
            approval=approval(),
            contracts=[contract()],
            module_rows=[module_row(quantity=2)],
        )
    )

    assert result.status is ReviewStatus.MANUAL_REVIEW
    assert any("數量不一致" in issue.message for issue in result.issues)


def test_module_row_unit_mismatch_is_manual_review():
    result = review_case(
        CaseData(
            approval=approval(),
            contracts=[contract()],
            module_rows=[module_row(unit="组")],
        )
    )

    assert result.status is ReviewStatus.MANUAL_REVIEW
    assert any("單位不一致" in issue.message for issue in result.issues)


def test_module_row_ocr_merged_unit_is_not_mismatch():
    # OCR merged the two rows' units into 套年; it still contains the real unit.
    result = review_case(
        CaseData(
            approval=approval(),
            contracts=[contract()],
            module_rows=[module_row(unit="套年")],
        )
    )
    assert not any("單位不一致" in issue.message for issue in result.issues)


def test_module_row_missing_unit_is_not_mismatch():
    result = review_case(
        CaseData(
            approval=approval(),
            contracts=[contract()],
            module_rows=[module_row(unit=None)],
        )
    )
    assert not any("單位不一致" in issue.message for issue in result.issues)


def test_duplicate_contract_product_rows_are_manual_review():
    # Two identical lines at the SAME price: the module unit price cannot single one
    # out, so this stays a genuine manual-review ambiguity.
    duplicate_items = [
        ContractItem(
            code="T5-3",
            name="智核ZClass5专业版系统",
            model="V5.0",
            unit="套",
            quantity=1,
            unit_price=2500.0,
        ),
        ContractItem(
            code="T5-3",
            name="智核ZClass5专业版系统",
            model="V5.0",
            unit="套",
            quantity=1,
            unit_price=2500.0,
        ),
    ]
    result = review_case(
        CaseData(
            approval=approval(),
            contracts=[contract(items=duplicate_items)],
            module_rows=[module_row()],
        )
    )

    assert result.status is ReviewStatus.MANUAL_REVIEW
    assert any("多筆相同產品" in issue.message for issue in result.issues)


def test_multi_contract_same_product_split_can_pass_when_totals_match():
    result = review_case(
        CaseData(
            approval=approval(
                contract_numbers=["ZHDEMO-20251124-01", "ZHDEMO-20251124-02"],
                shipment_companies=["四川代理商甲信息技术有限公司", "四川代理商乙昆吾信息产业有限公司"],
                actual_items=[
                    ShipmentItem(
                        code="T5-3",
                        name="智核ZClass5专业版系统",
                        model="V5.0",
                        unit="套",
                        quantity=2,
                        source="field",
                    )
                ],
            ),
            contracts=[
                contract(),
                contract(
                    source_file="second.pdf",
                    contract_number="ZHDEMO-20251124-02",
                    buyer_name="四川代理商乙昆吾信息产业有限公司",
                ),
            ],
            module_rows=[
                module_row(),
                module_row(
                    contract_number="ZHDEMO-20251124-02",
                    purchasing_company="四川代理商乙昆吾信息产业有限公司",
                ),
            ],
        )
    )

    assert result.status is ReviewStatus.APPROVED


def test_module_row_missing_from_approval_is_manual_review():
    result = review_case(
        CaseData(
            approval=approval(actual_items=[]),
            contracts=[contract()],
            module_rows=[module_row()],
        )
    )

    assert result.status is ReviewStatus.MANUAL_REVIEW
    assert any("未在出貨審批實際出貨項目中找到" in issue.message for issue in result.issues)


def test_extraction_issues_flow_into_rules():
    extraction_issue = Issue(IssueSeverity.MANUAL_REVIEW, "文件解析信心不足，請人工確認。")
    result = review_case(
        CaseData(
            approval=approval(),
            contracts=[contract()],
            module_rows=[module_row()],
            extraction_issues=[extraction_issue],
        )
    )

    assert result.status is ReviewStatus.MANUAL_REVIEW
    assert extraction_issue in result.issues


def test_approval_field_and_comment_disagreement_is_manual_review():
    original = [
        ShipmentItem(
            code="S5-6",
            name="智核ZGroup小组学习系统",
            model="V5.0",
            unit="套",
            quantity=2,
            source="field",
        )
    ]
    comment = [
        ShipmentItem(
            code="S5-6",
            name="智核ZGroup小组学习系统",
            model="V5.0",
            unit="组",
            quantity=12,
            source="comment",
        )
    ]
    revised = approval(actual_items=comment, original_field_items=original, comment_items=comment)
    result = review_case(
        CaseData(
            approval=revised,
            contracts=[
                contract(
                    items=[
                        ContractItem(
                            code="S5-6",
                            name="智核ZGroup小组学习系统",
                            model="V5.0",
                            unit="套",
                            quantity=12,
                            unit_price=333.33,
                        )
                    ]
                )
            ],
            module_rows=[
                module_row(code="S5-6", product_name="智核ZGroup小组学习系统", quantity=12, unit_price=333.33)
            ],
        )
    )

    assert result.status is ReviewStatus.MANUAL_REVIEW
    assert any("出貨內容欄位與審批流程評論" in issue.message for issue in result.issues)


def test_module_row_disambiguates_same_named_contract_items_by_unit_price():
    # A contract can list the same product at two pricing tiers (200 教师ID @1035 vs a
    # 2000-student package @400000). The module row's unit price picks the right line.
    c = contract(
        items=[
            ContractItem(code=None, name="智核ZClass5专业版系统", model="V5.0", unit="套", quantity=1, unit_price=1035.0),
            ContractItem(code=None, name="智核ZClass5专业版系统", model="V5.0", unit="套", quantity=1, unit_price=400000.0),
        ]
    )
    result = review_case(
        CaseData(
            approval=approval(),
            contracts=[c],
            module_rows=[module_row(unit_price=1035.0)],
        )
    )

    assert not any("多筆相同產品" in issue.message for issue in result.issues)
    assert result.status is ReviewStatus.APPROVED


def test_partial_shipment_quantity_below_contract_is_not_flagged():
    # The contract is a 200-unit master order; this batch ships 1. A shipment at or
    # below the contracted quantity is a normal partial delivery, not a mismatch.
    c = contract(
        items=[ContractItem(code="T5-3", name="智核ZClass5专业版系统", model="V5.0", unit="套", quantity=200, unit_price=2500.0)]
    )
    result = review_case(
        CaseData(approval=approval(), contracts=[c], module_rows=[module_row(quantity=1)])
    )

    assert not any("數量" in issue.message and "合同" in issue.message for issue in result.issues)
    assert result.status is ReviewStatus.APPROVED


def test_shipment_quantity_above_contract_is_flagged():
    # Shipping MORE than the contracted quantity is a real over-delivery problem.
    c = contract(
        items=[ContractItem(code="T5-3", name="智核ZClass5专业版系统", model="V5.0", unit="套", quantity=3, unit_price=2500.0)]
    )
    result = review_case(
        CaseData(
            approval=approval(
                actual_items=[ShipmentItem(code="T5-3", name="智核ZClass5专业版系统", model="V5.0", unit="套", quantity=5, source="field")]
            ),
            contracts=[c],
            module_rows=[module_row(quantity=5)],
        )
    )

    assert any("超過合同" in issue.message for issue in result.issues)


def test_all_core_checks_pass_when_structured_data_matches():
    result = review_case(CaseData(approval=approval(), contracts=[contract()], module_rows=[module_row()]))
    assert result.status is ReviewStatus.APPROVED
    assert "出貨項目均可在合同中找到" in result.checks


def test_consistent_case_is_approved_without_module_fee_recompute():
    result = review_case(
        CaseData(
            approval=approval(shipment_amount=2500.0),
            contracts=[contract()],
            module_rows=[module_row()],
        )
    )
    assert result.status is ReviewStatus.APPROVED


def test_approval_amount_mismatch_with_module_unit_price_times_quantity_is_manual_review():
    result = review_case(
        CaseData(
            approval=approval(shipment_amount=9999.0),
            contracts=[contract()],
            module_rows=[module_row(unit_price=2500.0, quantity=1)],
        )
    )
    assert result.status is ReviewStatus.MANUAL_REVIEW
    assert any("出貨金額" in issue.message for issue in result.issues)


def test_approval_amount_matches_sum_over_multiple_module_rows():
    result = review_case(
        CaseData(
            approval=approval(
                shipment_amount=11400.0,
                actual_items=[
                    ShipmentItem(code="C5-2", name="智核启思云平台服务", model=None, unit="年", quantity=2, source="field"),
                    ShipmentItem(code="T5-3", name="AI服务", model=None, unit="套", quantity=1, source="field"),
                ],
            ),
            contracts=[
                contract(
                    items=[
                        ContractItem(code="C5-2", name="智核启思云平台服务", model=None, unit="年", quantity=2, unit_price=4800.0),
                        ContractItem(code="T5-3", name="AI服务", model=None, unit="套", quantity=1, unit_price=1800.0),
                    ]
                )
            ],
            module_rows=[
                module_row(code="C5-2", product_name="智核启思云平台服务", model=None, unit="年", quantity=2, unit_price=4800.0, amount=9600.0, royalty=2400.0),
                module_row(code="T5-3", product_name="AI服务", model=None, unit="套", quantity=1, unit_price=1800.0, amount=1800.0, royalty=450.0),
            ],
        )
    )
    assert result.status is ReviewStatus.APPROVED


def test_amount_check_skips_when_approval_ships_hardware_absent_from_module_table():
    # 接收终端 hardware is shipped (in the approval and contract) but never appears in
    # the 权益金 module table, so the approval total legitimately exceeds the module sum
    # by the hardware value. The amount reconciliation must not flag this.
    hardware_item = ShipmentItem(code="S5-4", name="接收终端", model="IRSRF-35", unit="个", quantity=6, source="field")
    hardware_contract_item = ContractItem(code="S5-4", name="接收终端", model="IRSRF-35", unit="个", quantity=6, unit_price=769.5)
    result = review_case(
        CaseData(
            approval=approval(
                shipment_amount=7117.0,  # 2500 (module ZClass) + 4617 (hardware, not in module)
                actual_items=[
                    ShipmentItem(code="T5-3", name="智核ZClass5专业版系统", model="V5.0", unit="套", quantity=1, source="field"),
                    hardware_item,
                ],
            ),
            contracts=[
                contract(
                    items=[
                        ContractItem(code="T5-3", name="智核ZClass5专业版系统", model="V5.0", unit="套", quantity=1, unit_price=2500.0),
                        hardware_contract_item,
                    ]
                )
            ],
            module_rows=[module_row()],
        )
    )
    assert not any("出貨金額" in issue.message for issue in result.issues)


def test_ai_only_item_without_module_corroboration_caps():
    from shipment_review.models import ReviewStatus
    item = ShipmentItem(code="A9", name="智核某AI讀到的项", model="V1.0", unit="套", quantity=1, source="field")
    ai_contract = contract(ai_unconfirmed=True, items=[
        ContractItem(code="A9", name="智核某AI讀到的项", model="V1.0", unit="套", quantity=1, unit_price=100)])
    result = review_case(CaseData(
        approval=approval(actual_items=[item]),
        contracts=[ai_contract],
        module_rows=[],  # no independent corroboration
    ))
    assert result.status is ReviewStatus.MANUAL_REVIEW
    assert any("AI" in i.message and i.unverified for i in result.issues)


def test_ai_item_corroborated_by_module_passes():
    # same item also in a module row tied to the contract → corroborated → no AI cap
    item = ShipmentItem(code="A9", name="智核某项", model="V1.0", unit="套", quantity=1, source="field")
    ci = ContractItem(code="A9", name="智核某项", model="V1.0", unit="套", quantity=1, unit_price=100)
    ai_contract = contract(ai_unconfirmed=True, contract_number="ZHDEMO-20251124-01", items=[ci])
    row = module_row(code="A9", product_name="智核某项", model="V1.0", unit_price=100.0, amount=100.0)
    result = review_case(CaseData(
        approval=approval(actual_items=[item], contract_numbers=["ZHDEMO-20251124-01"]),
        contracts=[ai_contract], module_rows=[row],
    ))
    assert not any("僅見於 AI" in i.message for i in result.issues)


def test_ai_dropped_line_does_not_fake_block():
    # AI mistranscription that DROPS a real shipped line: the item is in no contract and
    # the only contract is ai_unconfirmed (→ not reliable). Must stay ⚠️ (掃描件), NOT a
    # false ❌ HARD_BLOCK / 不可出貨.
    from shipment_review.models import ReviewStatus
    item = ShipmentItem(code="Z9", name="智核被漏抄的项", model="V5.0", unit="套", quantity=1, source="field")
    ai_contract = contract(ai_unconfirmed=True, items=[])  # AI dropped the line
    result = review_case(CaseData(
        approval=approval(actual_items=[item]), contracts=[ai_contract], module_rows=[module_row()]
    ))
    assert result.status is ReviewStatus.MANUAL_REVIEW
    assert not any(i.severity is IssueSeverity.HARD_BLOCK and not i.unverified for i in result.issues)
    assert any("掃描件" in i.message for i in result.issues)


def test_module_corroboration_requires_value_equality():
    # Presence-corroboration alone is not enough: an AI contract line at the WRONG price,
    # with a module row at the RIGHT price, must still cap — _check_module_row flags the
    # 單價不一致 (the value-equality guard behind Task 4's presence-based found_in_module).
    from shipment_review.models import ReviewStatus
    item = ShipmentItem(code="A9", name="智核某项", model="V1.0", unit="套", quantity=1, source="field")
    ci = ContractItem(code="A9", name="智核某项", model="V1.0", unit="套", quantity=1, unit_price=999)  # AI wrong
    ai_contract = contract(ai_unconfirmed=True, contract_number="ZHDEMO-20251124-01", items=[ci])
    row = module_row(code="A9", product_name="智核某项", model="V1.0", unit_price=100.0, amount=100.0)  # truth
    result = review_case(CaseData(
        approval=approval(actual_items=[item], contract_numbers=["ZHDEMO-20251124-01"]),
        contracts=[ai_contract], module_rows=[row]))
    assert result.status is ReviewStatus.MANUAL_REVIEW
    assert any("單價不一致" in i.message for i in result.issues)


def test_corroborated_requires_a_named_module_row_under_that_number():
    from shipment_review.rules import _corroborated
    rows = [module_row(contract_number="ZHDEMO-20231211-01", product_name="智核AI教研中心智能终端系统")]
    assert _corroborated("zhdemo－20231211－01", rows) is True       # normalized match, named product
    assert _corroborated("ZHDEMO-99999999-99", rows) is False        # number not in module table
    assert _corroborated(None, rows) is False
    blank = [module_row(contract_number="ZHDEMO-20231211-01", product_name="")]
    assert _corroborated("ZHDEMO-20231211-01", blank) is False       # tied but no product name


def test_backfill_assigns_unique_leftover_number_when_corroborated():
    from shipment_review.rules import backfill_inferred_contract_numbers
    contracts = [contract(contract_number="ZHDEMO-20251124-01"),          # 代理商甲:已有號
                 contract(contract_number=None)]                          # 代理商乙: 沒號
    approval_numbers = ["ZHDEMO-20251124-01", "ZHDEMO-20231211-01"]
    rows = [module_row(contract_number="ZHDEMO-20231211-01", product_name="智核AI教研中心智能终端系统")]
    out = backfill_inferred_contract_numbers(contracts, approval_numbers, rows)
    assert out[1].contract_number == "ZHDEMO-20231211-01" and out[1].number_inferred is True
    assert out[0].contract_number == "ZHDEMO-20251124-01" and out[0].number_inferred is False

def test_backfill_skips_when_ambiguous():
    from shipment_review.rules import backfill_inferred_contract_numbers
    contracts = [contract(contract_number=None), contract(contract_number=None)]   # 2 numberless
    approval_numbers = ["ZHDEMO-20251124-01", "ZHDEMO-20231211-01"]
    rows = [module_row(contract_number="ZHDEMO-20231211-01", product_name="x")]
    out = backfill_inferred_contract_numbers(contracts, approval_numbers, rows)
    assert all(c.contract_number is None and c.number_inferred is False for c in out)

def test_backfill_skips_when_uncorroborated():
    from shipment_review.rules import backfill_inferred_contract_numbers
    contracts = [contract(contract_number="ZHDEMO-20251124-01"), contract(contract_number=None)]
    approval_numbers = ["ZHDEMO-20251124-01", "ZHDEMO-20231211-01"]
    out = backfill_inferred_contract_numbers(contracts, approval_numbers, module_rows=[])  # no corroboration
    assert out[1].contract_number is None and out[1].number_inferred is False


def test_inferred_contract_module_row_does_not_suppress_hardblock():
    from shipment_review.models import IssueSeverity
    # L244 path. Mixed folder: one RELIABLE contract (native, not ocr) that does NOT list the
    # item, plus an inferred-number scan whose module row matches the item. Coverage must NOT be
    # granted by the scan's row → the missing item stays a real HARD_BLOCK (not silently passed).
    # NOTE: both contract numbers MUST be in the approval list, else _check_approval_contract_numbers
    # conjures an unrelated 「合同單號未出現在出貨審批中」HARD_BLOCK and the test passes for the wrong
    # reason (the RED would be fake). We assert on the SPECIFIC coverage message, not any HARD_BLOCK.
    item = ShipmentItem(code="A9", name="智核某项", model="V1.0", unit="套", quantity=1, source="field")
    reliable = contract(contract_number="ZHDEMO-20251124-01", items=[
        ContractItem(code="Z1", name="別的东西", model="V1.0", unit="套", quantity=1, unit_price=1)])  # ocr_extracted defaults False → reliable
    scan = contract(contract_number="ZHDEMO-20231211-01", ocr_extracted=True, number_inferred=True, items=[])
    row = module_row(contract_number="ZHDEMO-20231211-01", product_name="智核某项", model="V1.0")
    result = review_case(CaseData(
        approval=approval(actual_items=[item],
                          contract_numbers=["ZHDEMO-20251124-01", "ZHDEMO-20231211-01"]),
        contracts=[reliable, scan], module_rows=[row]))
    assert any("未在任何合同中找到" in i.message and not i.unverified for i in result.issues)


def test_inferred_contract_module_row_is_not_ai_corroboration():
    # L234 path (偽佐證). An AI-unconfirmed contract LISTS the item; its only "module corroboration"
    # ties to a separate inferred-number scan. That row must NOT corroborate → the AI item stays
    # capped at 需人工確認 (僅見於 AI…未經佐證), not silently passed.
    item = ShipmentItem(code="A9", name="智核某项", model="V1.0", unit="套", quantity=1, source="field")
    ai = contract(contract_number="ZHDEMO-20251124-01", ai_unconfirmed=True, items=[
        ContractItem(code="A9", name="智核某项", model="V1.0", unit="套", quantity=1, unit_price=100)])  # transcript → ocr_extracted False
    scan = contract(contract_number="ZHDEMO-20231211-01", ocr_extracted=True, number_inferred=True, items=[])
    row = module_row(contract_number="ZHDEMO-20231211-01", product_name="智核某项", model="V1.0")
    result = review_case(CaseData(
        approval=approval(actual_items=[item],
                          contract_numbers=["ZHDEMO-20251124-01", "ZHDEMO-20231211-01"]),
        contracts=[ai, scan], module_rows=[row]))
    assert any("僅見於 AI" in i.message and i.unverified for i in result.issues)


def test_reliable_contract_module_row_still_suppresses():
    from shipment_review.models import IssueSeverity
    # Regression: when the tied contract IS reliable (not ocr), module coverage still suppresses
    # the HARD_BLOCK (existing compressed-contract behavior preserved).
    item = ShipmentItem(code="A9", name="智核某项", model="V1.0", unit="套", quantity=1, source="field")
    reliable = contract(contract_number="ZHDEMO-20231211-01", items=[
        ContractItem(code="Z1", name="別的东西", model="V1.0", unit="套", quantity=1, unit_price=1)])  # reliable, compressed
    row = module_row(contract_number="ZHDEMO-20231211-01", product_name="智核某项", model="V1.0")
    result = review_case(CaseData(approval=approval(actual_items=[item],
                                                    contract_numbers=["ZHDEMO-20231211-01"]),
                                  contracts=[reliable], module_rows=[row]))
    assert not any(i.severity is IssueSeverity.HARD_BLOCK for i in result.issues)
