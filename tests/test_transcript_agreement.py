from shipment_review.extractors.transcript_agreement import transcripts_agree, module_rows_agree

_ITEM = {"code": "T5-3", "name": "智核ZClass5专业版系统", "model": "V5.0",
         "unit": "套", "quantity": 1, "unit_price": 4500, "amount": 4500}


def test_identical_transcripts_agree():
    a = {"contract_number": "ZHDEMO-20260515-01", "items": [dict(_ITEM)]}
    b = {"contract_number": "ZHDEMO-20260515-01", "items": [dict(_ITEM)]}
    assert transcripts_agree(a, b) == (True, [])


def test_unit_price_divergence_flagged():
    a = {"contract_number": "X", "items": [dict(_ITEM)]}
    b = {"contract_number": "X", "items": [dict(_ITEM, unit_price=9999)]}
    ok, diffs = transcripts_agree(a, b)
    assert ok is False and any("unit_price" in d for d in diffs)


def test_contract_number_divergence_flagged():
    a = {"contract_number": "X1", "items": [dict(_ITEM)]}
    b = {"contract_number": "X2", "items": [dict(_ITEM)]}
    ok, diffs = transcripts_agree(a, b)
    assert ok is False and any("contract_number" in d for d in diffs)


def test_item_count_divergence_flagged():
    a = {"contract_number": "X", "items": [dict(_ITEM)]}
    b = {"contract_number": "X", "items": [dict(_ITEM), dict(_ITEM)]}
    ok, diffs = transcripts_agree(a, b)
    assert ok is False and diffs


def _row(name, num="ZHDEMO-1", up=210, qty=1, amt=210, model="V1.0", unit="套"):
    return {"contract_number": num, "product_name": name, "model": model,
            "unit": unit, "quantity": qty, "unit_price": up, "amount": amt}


def test_module_rows_agree_identical():
    a = {"rows": [_row("AI教研中心")]}
    assert module_rows_agree(a, {"rows": [_row("AI教研中心")]})[0] is True


def test_module_rows_agree_order_insensitive():
    a = {"rows": [_row("X"), _row("Y", up=500, amt=500)]}
    b = {"rows": [_row("Y", up=500, amt=500), _row("X")]}
    assert module_rows_agree(a, b)[0] is True


def test_module_rows_disagree_on_a_field():
    a = {"rows": [_row("AI教研中心", up=210)]}
    b = {"rows": [_row("AI教研中心", up=280, amt=280)]}
    assert module_rows_agree(a, b)[0] is False


def test_module_rows_disagree_on_count():
    assert module_rows_agree({"rows": [_row("X")]}, {"rows": []})[0] is False


def test_module_rows_shared_product_key_not_collapsed():
    # Two rows, same (code,name,model) product_key but different contract/price; one pass
    # differs on the second row. A product_key-keyed compare would hide this; sorted-tuple
    # must catch it.
    a = {"rows": [_row("P", num="C1", up=100, amt=100), _row("P", num="C2", up=200, amt=200)]}
    b = {"rows": [_row("P", num="C1", up=100, amt=100), _row("P", num="C2", up=999, amt=999)]}
    assert module_rows_agree(a, b)[0] is False


def test_module_rows_disagree_on_purchasing_company():
    # purchasing_company feeds a HARD_BLOCK (模組表采购公司 ≠ 合同买方); the two blind reads
    # must agree on it too, or a single misread of the company is trusted uncorroborated.
    a = {"rows": [{**_row("X"), "purchasing_company": "甲公司"}]}
    b = {"rows": [{**_row("X"), "purchasing_company": "乙公司"}]}
    assert module_rows_agree(a, b)[0] is False
