from shipment_review.normalization import (
    contract_numbers_match,
    extract_contract_numbers,
    extract_product_code,
    normalize_money,
    normalize_text,
    product_key,
    products_match,
    units_compatible,
)


def test_normalize_text_removes_spacing_width_and_punctuation():
    assert normalize_text(" 智核 ZGroup 小組學習系統　V5.0 ") == "智核zgroup小組學習系統v5.0"
    assert normalize_text("ZHDEMO－20251124－01") == "zhdemo2025112401"


def test_extract_contract_numbers_from_mixed_text():
    text = "合同编号 ZHDEMO-20251124-01、ZHDEMO-20231211-01"
    assert extract_contract_numbers(text) == ["ZHDEMO-20251124-01", "ZHDEMO-20231211-01"]
    assert extract_contract_numbers("xZHDEMO-20251124-01y") == []


def test_extract_contract_numbers_accepts_digit_suffixed_prefix():
    text = "合同编号 ZHDEMO2-20250926-01、ZHDEMO-20251030-01"
    assert extract_contract_numbers(text) == ["ZHDEMO2-20250926-01", "ZHDEMO-20251030-01"]


def test_contract_numbers_match_with_digit_suffixed_prefix():
    assert contract_numbers_match("ZHDEMO2-20250926-01", "ZHDEMO2-20250926-01")
    assert not contract_numbers_match("ZHDEMO2-20250926-01", "ZHDEMO-20251030-01")


def test_extract_product_code():
    assert extract_product_code("A5-3，1套智核AI教研中心智能终端系统V1.0") == "A5-3"
    assert extract_product_code("A12 - 30 智核AI教研中心智能终端系统") == "A12-30"
    assert extract_product_code("智核ZGroup小组学习系统") is None


def test_normalize_money_accepts_commas_and_chinese_spacing():
    assert normalize_money("286,000.00") == 286000.0
    assert normalize_money(" 91 850 ") == 91850.0
    assert normalize_money("￥286,000.00") == 286000.0
    assert normalize_money("人民币286,000.00元") == 286000.0
    assert normalize_money("") is None
    assert normalize_money("未填写") is None


def test_product_key_prefers_code_and_model():
    assert product_key(code="S5-6", name="智核ZGroup小组学习系统", model="V5.0") == "code:s5-6|model:v5.0"
    assert product_key(code=None, name="智核ZClass5专业版系统", model="V5.0") == "name:智核zclass5专业版系统|model:v5.0"


def test_products_match_ignores_parenthetical_spec_and_leading_index():
    # 0421 real data: approval item name polluted by a leaked "-1"序号 prefix and a
    # trailing （…） spec, while the contract carries the bare core product name.
    assert products_match(
        "C5-2", "-1智核启思云平台服务（管理权限+100G空间）", None,
        "C5-2-1", "智核启思云平台服务", None,
    )


def test_products_match_short_name_with_serial_number_suffix():
    # 0421: a very short core name ("AI服务") buried under a long serial-number
    # parenthetical must still match the bare contract name.
    assert products_match(
        "T5-3", "-1AI服务（授权序列号为：SNDEMO01-6M83-QNW1-133X-T91K）", None,
        "TS-3-1", "AI服务", None,
    )


def test_products_match_ignores_embedded_product_code_in_name():
    # 0421: the contract parser can leave the row's 序号 + product code glued into
    # the name ("1-1 C5-2-1 智核..."); the bare module/approval name must match.
    assert products_match(
        None, "智核启思云平台服务", None,
        "C5-2", "1-1 C5-2-1 智核启思云平台服务", None,
    )


def test_products_match_rejects_edition_variants():
    # 专业版 vs 标准版 differ by two chars in a long name — different SKUs, must
    # not auto-match (a false 可出貨 ships the wrong edition).
    assert not products_match(
        None, "智核ZClass5专业版系统", None,
        None, "智核ZClass5标准版系统", None,
    )


def test_products_match_ignores_brand_prefix_and_generic_suffix():
    # 智核 brand prefix and a trailing generic 系统 are noise: the same product is
    # written "智核X系统" in one doc and "X" in another. Strip both, then exact-match.
    assert products_match(
        None, "智核学生互动反馈系统", "V5.0",
        None, "学生互动反馈", "V5.0",
    )


def test_products_match_bundle_name_vs_contract_line():
    # A shipment bundle name (智核AI教研中心智能终端系统, model V1.0) and the contract
    # line (AI教研中心-智能终端, SKU XW-A700 in the code field, no model) are the same
    # product after stripping 智核/系统 — model absent on the contract side, so it matches.
    assert products_match(
        None, "智核AI教研中心智能终端系统", "V1.0",
        "XW-A700", "AI教研中心-智能终端", None,
    )


def test_products_match_generic_suffix_does_not_merge_different_bodies():
    # Both sides actually strip 系统 (bodies ≥4): the strip must NOT collapse two
    # genuinely different products — 录播主机 ≠ 录播终端 survives.
    assert not products_match(
        None, "智核录播主机系统", None,
        None, "智核录播终端系统", None,
    )


def test_products_match_generic_suffix_stripped_only_with_brand():
    # Brand present → 系统 strips, "智核录播主机系统" == "智核录播主机".
    assert products_match(None, "智核录播主机系统", None, None, "智核录播主机", None)
    # Brandless → 系统 is NOT stripped, so "录播主机系统" stays distinct from "录播主机"
    # (could be a hardware-vs-system SKU); falls to manual review, never a false match.
    assert not products_match(None, "录播主机系统", None, None, "录播主机", None)


def test_products_match_generic_suffix_min_length_boundary():
    # Body of 4 strips (录播主机), body of 3 does not (录播机) — locks the =4 cutoff.
    assert products_match(None, "智核录播主机系统", None, None, "智核录播主机", None)
    assert not products_match(None, "智核录播机系统", None, None, "智核录播机", None)


def test_products_match_rejects_version_digit_in_name():
    # Version digit lives in the name, not the model field; 5 ≠ 6 → different.
    assert not products_match(
        None, "智核ZClass5系统", None,
        None, "智核ZClass6系统", None,
    )


def test_products_match_rejects_leading_spec_digit_products():
    # The 序号 strip must not eat a meaningful leading number (4K ≠ 8K).
    assert not products_match(
        None, "4K高清摄像头", None,
        None, "8K高清摄像头", None,
    )


def test_products_match_model_echoes_product_name_before_version():
    # Real 0610 / Desktop代理商甲 data: a contract's 型号 column echoes the full product
    # name before the version ("智核ZClass5专业版系统V5.0"), while the module-fee
    # table / approval carry only the version ("V5.0"). Same product, same version V5.0
    # → must match. (Before the fix, the module-row check raised a false 查無此項.)
    assert products_match(
        None, "智核ZClass5专业版系统", "V5.0",
        "T5-3", "智核ZClass5专业版系统", "智核ZClass5专业版系统V5.0",
    )


def test_products_match_name_echoed_model_still_rejects_version_diff():
    # Guard: a version echoed inside a name-prefixed model must still discriminate —
    # V5.0 ≠ V6.0 even when the model carries the same product-name echo.
    assert not products_match(
        None, "智核ZClass5专业版系统", "V5.0",
        "T5-3", "智核ZClass5专业版系统", "智核ZClass5专业版系统V6.0",
    )


def test_products_match_version_token_only_trusted_when_one_side_is_bare_version():
    # Adversarial: if BOTH models carry a non-version prefix, the prefix is a real
    # discriminator (a SKU), not a name echo — two different SKUs sharing the same
    # trailing version must NOT match. Only when one side is a bare version (the
    # actual data shape: module row "V5.0" vs contract "名称…V5.0") do we ignore the
    # echo. RF-35 ≠ RF-55 even though both end V5.0.
    assert not products_match(
        None, "智核录播主机系统", "RF-35V5.0",
        None, "智核录播主机系统", "RF-55V5.0",
    )


def test_products_match_distinct_skus_same_name_no_match():
    # Guard: no version token on either side → fall to strict model inequality;
    # two different hardware SKUs under the same name stay incompatible.
    assert not products_match(
        None, "智核录播主机系统", "RF-35",
        None, "智核录播主机系统", "RF-17",
    )


def test_products_match_rejects_short_generic_near_name():
    assert not products_match(
        None, "AI服务", None,
        None, "AI云服务", None,
    )


def test_products_match_rejects_fuzzy_name_with_incompatible_codes():
    # Names are fuzzily close but both carry codes that are not prefix-compatible
    # (C5-2 vs C5-3) → the differing identifier vetoes the fuzzy name match.
    assert not products_match(
        "C5-2", "智核启思云平台云服务", None,
        "C5-3", "智核启思云平台服务", None,
    )


def test_products_match_allows_code_subindex():
    # C5-2 (approval) vs C5-2-1 (contract sub-index) are the same product.
    assert products_match(
        "C5-2", "智核启思云平台服务", None,
        "C5-2-1", "智核启思云平台服务", None,
    )


def test_products_match_handles_unclosed_parenthetical():
    # OCR dropped the closing ） of the serial spec; the tail must not pollute the
    # core, so the bare contract name still matches.
    assert products_match(
        None, "AI服务（授权序列号为：SNDEMO01", None,
        None, "AI服务", None,
    )


def test_products_match_allows_single_char_ocr_typo_in_long_name():
    # 桉 vs 核 is a known OCR confusion; in a long specific name this is the same
    # product and should still match (regression lock against over-tightening).
    assert products_match(
        None, "智核AI教研中心智能终端系统", None,
        None, "智桉AI教研中心智能终端系统", None,
    )


def test_products_match_rejects_paren_only_edition():
    # The only discriminator is an edition inside a parenthetical; it must NOT be
    # stripped away, otherwise both sides collapse to the same core.
    assert not products_match(
        None, "教学服务（基础版）", None,
        None, "教学服务（专业版）", None,
    )


def test_products_match_rejects_leading_code_echo_with_different_codes():
    # A leading alphanumeric that echoes a code is stripped, but then the differing
    # codes (C9 vs C8) must veto the otherwise-identical core.
    assert not products_match(
        "C9", "C9 云盒", None,
        "C8", "C8 云盒", None,
    )


def test_products_match_rejects_glued_numeric_range_in_name():
    # "4-6岁" is a glued age range (part of the name), not a 序号 index — a real
    # 序号 always has a trailing separator/space ("1-1 ").
    assert not products_match(
        None, "4-6岁阅读机", None,
        None, "2-3岁阅读机", None,
    )


def test_products_match_rejects_dashed_count_variant():
    # "5-合一" vs "3-合一": the leading number is product-meaningful (5-in-1), not a
    # 序号, so it must not be stripped.
    assert not products_match(
        None, "5-合一读卡器", None,
        None, "3-合一读卡器", None,
    )


def test_products_match_rejects_near_name_without_threshold():
    # 一体机 (all-in-one) vs 体验机 (demo unit): different products that a fuzzy
    # ratio would pass at ~90; exact-after-canonicalization rejects them.
    assert not products_match(
        None, "多媒体互动教学一体机", None,
        None, "多媒体互动教学体验机", None,
    )


def test_products_match_rejects_unclosed_edition_tail():
    # OCR dropped the closing ）but the tail is an edition (高配/低配) → keep it.
    assert not products_match(
        None, "服务器（高配", None,
        None, "服务器（低配", None,
    )


def test_products_match_rejects_different_products():
    assert not products_match(
        None, "智核ZClass5专业版系统", "V5.0",
        None, "智核ZGroup小组学习系统", "V5.0",
    )


def test_units_compatible_tolerates_absence_and_ocr_merge():
    # OCR can merge two rows' units (年 read as 年套) or drop one entirely.
    assert units_compatible("年套", "年")
    assert units_compatible("年", "年套")
    assert units_compatible(None, "套")
    assert units_compatible("套", "")
    assert units_compatible("套", "套")


def test_units_compatible_rejects_genuine_mismatch():
    assert not units_compatible("年", "套")
    assert not units_compatible("组", "套")


def test_units_compatible_rejects_substring_that_is_not_a_unit_merge():
    # Containment is only an OCR merge when the extra characters are themselves
    # units — not a multiplier prefix or an unrelated superstring.
    assert not units_compatible("克", "千克")  # 1000× different
    assert not units_compatible("套", "套装")
    assert not units_compatible("个", "个人")


def test_products_match_rejects_same_name_different_model():
    # Fuzzy name matching must not override a genuine model difference.
    assert not products_match(
        None, "智核ZClass5专业版系统", "V1.0",
        None, "智核ZClass5专业版系统", "V5.0",
    )


def test_clean_display_name_strips_section_marker_and_folds_ocr():
    from shipment_review.normalization import clean_display_name

    # leaked 「（二）-1」 section marker dropped (display only)
    assert clean_display_name("（二）-1智核智慧学校云平台（基础版）") == "智核智慧学校云平台（基础版）"
    # 桉→核 OCR confusion folded
    assert clean_display_name("智桉ZClass5专业版系统") == "智核ZClass5专业版系统"
    # a clean name / contract number is untouched
    assert clean_display_name("智核ZClass5专业版系统") == "智核ZClass5专业版系统"
    assert clean_display_name("ZHDEMO-20251223-01") == "ZHDEMO-20251223-01"


def test_normalize_contract_number_canonicalizes():
    from shipment_review.normalization import normalize_contract_number
    assert normalize_contract_number("zhdemo－20231211－01") == "ZHDEMO-20231211-01"  # fullwidth dash + lowercase
    assert normalize_contract_number("  ZHDEMO-20231211-01 ") == "ZHDEMO-20231211-01"  # whitespace
    assert normalize_contract_number(None) == "" or normalize_contract_number(None) is None
    assert normalize_contract_number("") is None
