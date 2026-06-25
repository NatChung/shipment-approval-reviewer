from shipment_review.normalization import (
    contract_number_candidates,
    contract_numbers_match,
    ocr_canonical_code,
    ocr_canonical_model,
    product_match_keys,
    products_match,
)


def test_ocr_canonical_code_fixes_dollar_for_s():
    assert ocr_canonical_code("$5-1") == "S5-1"
    assert ocr_canonical_code("s5-4") == "S5-4"
    assert ocr_canonical_code("A5-3") == "A5-3"
    assert ocr_canonical_code(None) is None


def test_ocr_canonical_model_fixes_w_for_v():
    assert ocr_canonical_model("W1.0") == "V1.0"
    assert ocr_canonical_model("v5.0") == "V5.0"
    assert ocr_canonical_model(None) is None


def test_contract_number_candidates_repairs_dropped_or_extra_chars():
    assert "ZHDEMO-20251223-01" in contract_number_candidates("ZDEMO-20251223-01")
    assert "ZHDEMO-20251223-01" in contract_number_candidates("TIDYX-20251223-01")
    assert "ZHDEMO-20251124-01" in contract_number_candidates("ZHDEMO-20251124-01")


def test_contract_numbers_match_is_ocr_tolerant():
    assert contract_numbers_match("ZDEMO-20251223-01", "ZHDEMO-20251223-01")
    assert contract_numbers_match("ZHDEMO-20251124-01", "zhdemo-20251124-01")
    assert not contract_numbers_match("ZHDEMO-20251124-01", "ZHDEMO-20231211-01")
    assert not contract_numbers_match(None, "ZHDEMO-20251124-01")


# --- products_match tests ---


def test_products_match_both_have_codes_same_code():
    assert products_match("T5-3", "智核ZClass5专业版系统", "V5.0", "T5-3", "智核ZClass5专业版系统", "V5.0")


def test_products_match_code_vs_no_code_same_name_model():
    # Approval item has a code; contract item has no code — must match on name+model.
    assert products_match("T5-3", "智核ZClass5专业版系统", "V5.0", None, "智核ZClass5专业版系统", "V5.0")


def test_products_match_different_name_model_no_match():
    assert not products_match("T5-3", "产品A", "V5.0", None, "产品B", "V5.0")
    assert not products_match(None, "产品A", "V5.0", None, "产品A", "V1.0")


def test_products_match_different_codes_same_name_model():
    # Different codes but same name+model → True (documented behavior: same product).
    assert products_match("T5-3", "智核ZClass5专业版系统", "V5.0", "A5-3", "智核ZClass5专业版系统", "V5.0")


def test_product_match_keys_always_includes_name_key():
    keys = product_match_keys("T5-3", "智核ZClass5专业版系统", "V5.0")
    assert any(k.startswith("name:") for k in keys)
    assert any(k.startswith("code:") for k in keys)


def test_product_match_keys_no_code_only_name_key():
    keys = product_match_keys(None, "智核ZClass5专业版系统", "V5.0")
    assert len(keys) == 1
    assert next(iter(keys)).startswith("name:")


def test_products_match_strips_bracket_annotation_on_approval_name():
    # An approval names the 授权 detail in a 【…】 annotation whose closing 】 is often
    # line-truncated; it must still match the clean module-table product name.
    polluted = "智核ZClass5专业版系统【即3位教师ID授权（三年服务）授权权限"
    assert products_match(None, polluted, None, None, "智核ZClass5专业版系统", "V5.0")


def test_products_match_strips_compound_index_then_dash_leak():
    # 序号 "1、" followed by a leaked sub-index "-1" ("1、-1智核…") must fully strip;
    # the dash leak is only exposed after the 序号 is removed.
    approval = "1、-1智核启思云平台管理服务（含100G空间）"
    assert products_match(None, approval, None, None, "智核启思云平台管理服务", None)
