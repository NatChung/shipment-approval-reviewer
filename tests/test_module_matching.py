from shipment_review.rules import module_rows_matching_nothing
from shipment_review.models import CaseData, Contract, ContractItem, ModuleRow, ShipmentItem, Approval


def _case(module_name, contract_name, approval_name):
    contract = Contract(source_file="c.pdf", contract_number="ZHDEMO-20251223-01", buyer_name="b", seller_name="s",
                        school_name=None, items=[ContractItem(code=None, name=contract_name, model="V1.0",
                        unit="套", quantity=1, unit_price=1, amount=1)], readable=True)
    # Approval has 7 required fields (models.py) — pass them all.
    approval = Approval(source_file="a.pdf", approval_code=None, contract_numbers=["ZHDEMO-20251223-01"],
                        shipment_companies=[], school_name=None,
                        actual_items=[ShipmentItem(code=None, name=approval_name, model="V1.0",
                        unit="套", quantity=1, source="x")], approver_statuses={})
    row = ModuleRow(source_file="m.png", contract_number="ZHDEMO-20251223-01", purchasing_company="b",
                    product_name=module_name, model="V1.0", unit="套", quantity=1, unit_price=1,
                    amount=1, royalty=0)
    return CaseData(approval=approval, contracts=[contract], module_rows=[row],
                    expected_contract_files=[], extraction_issues=[], module_table_present=True)


def test_module_row_matching_nothing_flagged():
    # rapidocr dropped the I → "A教研中心" matches neither side
    case = _case("智核A教研中心智能终端系统", "智核AI教研中心智能终端系统", "智核AI教研中心智能终端系统")
    out = module_rows_matching_nothing(case)
    assert len(out) == 1


def test_module_row_matching_contract_not_flagged():
    case = _case("智核AI教研中心智能终端系统", "智核AI教研中心智能终端系统", "智核AI教研中心智能终端系统")
    assert module_rows_matching_nothing(case) == []


def test_module_row_in_approval_only_not_flagged():
    # present in the approval (engine-査無此項 vs its contract, but NOT a name-OCR garble) → narrowing: not a module gap
    case = _case("智核ZGroup小组学习系统", "智核AI教研中心智能终端系统", "智核ZGroup小组学习系统")
    assert module_rows_matching_nothing(case) == []


def test_module_reread_company_mismatch_blocks():
    # I4: a module re-read (the AI sidecar's rows) whose corrected purchasing_company
    # mismatches the contract buyer drives a HARD_BLOCK → 不可出貨. The engine judges; the
    # re-read only supplies truer text. Guards that a module re-read can move the verdict in
    # the BLOCKING direction, not only clear 查無此項.
    from shipment_review.rules import review_case
    from shipment_review.models import ReviewStatus
    name = "智核AI教研中心智能终端系统"
    contract = Contract(source_file="c.pdf", contract_number="ZHDEMO-20251223-01", buyer_name="甲公司",
                        seller_name="s", school_name=None,
                        items=[ContractItem(code=None, name=name, model="V1.0", unit="套",
                        quantity=1, unit_price=1, amount=1)], readable=True)
    approval = Approval(source_file="a.pdf", approval_code=None, contract_numbers=["ZHDEMO-20251223-01"],
                        shipment_companies=[], school_name=None,
                        actual_items=[ShipmentItem(code=None, name=name, model="V1.0", unit="套",
                        quantity=1, source="x")], approver_statuses={})
    row = ModuleRow(source_file="m.png", contract_number="ZHDEMO-20251223-01", purchasing_company="乙公司",
                    product_name=name, model="V1.0", unit="套", quantity=1, unit_price=1,
                    amount=1, royalty=0)
    case = CaseData(approval=approval, contracts=[contract], module_rows=[row],
                    expected_contract_files=[], extraction_issues=[], module_table_present=True)
    result = review_case(case)
    assert result.status == ReviewStatus.BLOCKED
    assert any("採購公司" in i.message for i in result.issues)
