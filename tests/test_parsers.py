from pathlib import Path

from shipment_review.extractors.approval import parse_approval_text
from shipment_review.extractors.contract import parse_contract
from shipment_review.extractors.module_table import parse_module_table
from shipment_review.extractors.text import Extraction, OcrToken

REAL_APPROVAL_TEXT = """出货审批
審批編碼 202606091044000425537
申請人 申请人甲
合同编号 ZHDEMO-20251124-01、ZHDEMO-20231211-01
最终用户学段 小学
出货金额（元） 60,925.00 (陆万零玖佰贰拾伍元整)
附合同 ZHDEMO-20251124-01（双章）代理商甲-智核340107.5元(1)(1)(2).pdf
（双章）代理商乙-智核1551637.5元(7).pdf
收款方式 其他
出货公司名称 四川代理商甲信息技术有限公司、四川代理商乙昆吾信息产业有限公司
出货内容：
实际出货为：
A5-3，1套智核AI教研中心智能终端系统V1.0
T5-3 ，1套智核ZClass5专业版系统V5.0
S5-1 ，50套智核学生互动反馈系统V5.0
S5-4，1个接收终端IRSRF-35
S5-6，12套智核ZGroup小组学习系统V5.0
收货地址： 待出货时通知
收货人： 王钞
收货人电话 18113694002
备注 1、学校全称：示范乙校 代码：2151005439 简码：cczscb。
審批流程
【财务确认】 审批人甲 已同意 2026-06-09 10:55:56
【产品管理经理】 审批人乙 已同意 2026-06-09 10:57:11
【智核CEO】 审批人丙 已同意 2026-06-09 11:36:26
"""


def test_parse_approval_core_fields():
    approval = parse_approval_text(REAL_APPROVAL_TEXT, Path("approval.pdf"))

    assert approval.approval_code == "202606091044000425537"
    assert approval.contract_numbers == ("ZHDEMO-20251124-01", "ZHDEMO-20231211-01")
    assert approval.school_name == "示范乙校"
    assert approval.shipment_companies == (
        "四川代理商甲信息技术有限公司",
        "四川代理商乙昆吾信息产业有限公司",
    )


def test_parse_approval_shipment_amount():
    approval = parse_approval_text(REAL_APPROVAL_TEXT, Path("approval.pdf"))

    assert approval.shipment_amount == 60925.0


def test_parse_approval_prefers_consolidated_total_over_per_contract_breakdown():
    # Approvals that span two contracts list items once per contract AND again in a
    # 综上合计 (consolidated) section. Only the consolidated section is authoritative;
    # counting both double-counts every quantity.
    text = (
        "出货审批\n审批编码 1\n合同编号 ZHDEMO2-20250926-01、ZHDEMO-20251030-01\n"
        "出货内容：\n"
        "1、合同编号：ZHDEMO2-20250926-01合同出货内容如下：\n"
        "T5-3，6套智核ZClass5专业版系统 V5.0\n"
        "S5-1，190套智核学生互动反馈系统 V5.0\n"
        "2、合同编号：ZHDEMO-20251030-01合同出货内容如下：\n"
        "S5-1，110套智核学生互动反馈系统 V5.0\n"
        "综上合计出货内容如下：\n"
        "T5-3，6套智核ZClass5专业版系统 V5.0\n"
        "S5-1，300套智核学生互动反馈系统 V5.0\n"
        "收货人： 王\n"
    )
    ap = parse_approval_text(text, Path("a.pdf"))

    zclass = [it for it in ap.actual_items if it.code == "T5-3"]
    students = [it for it in ap.actual_items if it.code == "S5-1"]
    assert sum(it.quantity for it in zclass) == 6
    assert sum(it.quantity for it in students) == 300


def test_parse_approval_approver_statuses():
    approval = parse_approval_text(REAL_APPROVAL_TEXT, Path("approval.pdf"))

    assert approval.approver_statuses["财务确认"] == "已同意"
    assert approval.approver_statuses["产品管理经理"] == "已同意"
    assert approval.approver_statuses["智核CEO"] == "已同意"


def test_parse_approval_shipment_items_including_hardware():
    approval = parse_approval_text(REAL_APPROVAL_TEXT, Path("approval.pdf"))

    codes = [item.code for item in approval.actual_items]
    assert codes == ["A5-3", "T5-3", "S5-1", "S5-4", "S5-6"]

    irs = next(item for item in approval.actual_items if item.code == "S5-4")
    assert irs.model == "IRSRF-35"  # hardware model, not a V-version
    assert irs.quantity == 1

    students = next(item for item in approval.actual_items if item.code == "S5-1")
    assert students.quantity == 50
    assert students.unit == "套"


CONTRACT_TEXT = """购销合同
订单号码 ZHDEMO-20251124-01
单位名称 四川代理商甲信息技术有限公司
学校完整名称 示范乙校
智核ZClass5专业版系统 V5.0 套 1 2500 2500
"""


def test_parse_contract_native_text_with_filename_fallback():
    extraction = Extraction(text=CONTRACT_TEXT.replace("ZHDEMO-20251124-01", ""))
    contract = parse_contract(extraction, Path("ZHDEMO-20251124-01.pdf"), attached_files=[])

    assert contract.contract_number == "ZHDEMO-20251124-01"
    assert contract.buyer_name == "四川代理商甲信息技术有限公司"
    assert contract.school_name == "示范乙校"
    assert contract.readable is True
    assert contract.items[0].unit_price == 2500.0


def test_contract_number_not_stolen_from_sibling_attached_file():
    # 0610: a folder with TWO contracts. The 代理商乙 contract's own scan text and own filename
    # carry no contract number (合同编号 printed blank on the scan). The attached-file
    # fallback must NOT inherit the SIBLING (代理商甲) file's number — that cross-file theft made
    # both contracts collide on ZHDEMO-20251124-01 and orphaned 代理商乙's real number, so every
    # 代理商乙 item then read as "未在合同中找到" although the file was right there.
    extraction = Extraction(text="购销合同\n合同编号：\n货物明细")  # number field blank
    own = "（双章）代理商乙-智核1551637.5元(7).pdf"
    sibling = "ZHDEMO-20251124-01（双章）代理商甲-智核340107.5元(1)(1)(2).pdf"
    contract = parse_contract(extraction, Path(own), attached_files=[sibling, own])

    assert contract.contract_number is None  # was wrongly ZHDEMO-20251124-01 (the sibling's)


def test_contract_number_recovered_from_own_attached_entry_despite_copy_suffix():
    # The fallback's legitimate job: when the on-disk name lacks the number but the approval's
    # attached reference to THIS file carries it (with copy-suffix noise), recover it — while a
    # sibling reference is still ignored.
    extraction = Extraction(text="购销合同\n货物明细")  # no number in the body
    onfile = "代理商甲-智核340107.5元.pdf"                       # on-disk: no number
    attached_self = "ZHDEMO-20251124-01代理商甲-智核340107.5元(1)(1).pdf"  # approval ref: has it
    sibling = "（双章）代理商乙-智核1551637.5元(7).pdf"
    contract = parse_contract(extraction, Path(onfile), attached_files=[sibling, attached_self])

    assert contract.contract_number == "ZHDEMO-20251124-01"


def test_contract_number_recovered_despite_seal_prefix_mismatch():
    # Filenames drift: the on-disk file lacks the 双章 seal note that the approval's attached
    # reference carries (a real source of inconsistency). The match key strips the seal marker
    # so THIS file's own reference still resolves and its number is recovered.
    extraction = Extraction(text="购销合同\n货物明细")  # no number in the body
    onfile = "代理商乙-智核1551637.5元.pdf"                              # on-disk: no seal, no number
    attached_self = "（双章）ZHDEMO-20231211-01代理商乙-智核1551637.5元(7).pdf"  # ref: seal + number
    sibling = "ZHDEMO-20251124-01代理商甲-智核340107.5元(1)(1).pdf"
    contract = parse_contract(extraction, Path(onfile), attached_files=[sibling, attached_self])

    assert contract.contract_number == "ZHDEMO-20231211-01"  # own entry, not the sibling's


def test_contract_number_recovered_despite_cjk_paren_copy_suffix():
    # Copy markers also appear as full-width 「（副本）」, not just ASCII "(1)". The own entry
    # must still resolve so its number is recovered, while the sibling stays ignored.
    extraction = Extraction(text="购销合同\n货物明细")  # no number in the body
    onfile = "代理商乙-智核1551637.5元.pdf"                          # on-disk: plain
    attached_self = "ZHDEMO-20231211-01代理商乙-智核1551637.5元（副本）.pdf"  # ref: full-width copy mark
    sibling = "ZHDEMO-20251124-01代理商甲-智核340107.5元(1)(1).pdf"
    contract = parse_contract(extraction, Path(onfile), attached_files=[sibling, attached_self])

    assert contract.contract_number == "ZHDEMO-20231211-01"


CONTRACT_TABLE_TEXT = """购销合同
订单号码 ZHDEMO-20260410-04
单位名称 北京代理商丙科技有限公司
学校完整名称 北京市东城区示范丙校
序号 品项名称 单位 数量 单价（含税） 金额（含税）
1-1 C5-2-1 智核启思云平台服务 年 2 ¥4,800.00 ¥9,600.00
1-2 TS-3-1 AI服务 套 ¥1,800.00 ¥1,800.00
合计 启思云平台授权时间为：2026.04.20一2028.04.19 ¥11,400.00
付款方式 签订单后三日内支付
1.智核产品：版本内软件免费升级，硬件质保3年
户名：智核（成都）信息技术有限公司
智核
"""


def test_parse_contract_table_extracts_all_rows_and_drops_prose():
    extraction = Extraction(text=CONTRACT_TABLE_TEXT)
    contract = parse_contract(extraction, Path("ZHDEMO-20260410-04.pdf"), attached_files=[])

    names = [item.name.strip() for item in contract.items]
    # Both table rows captured — including AI服务, whose name lacks the 智核
    # keyword the old per-line filter required.
    assert names == ["智核启思云平台服务", "AI服务"]
    # Prose after 合计 (质保 clause, bank 户名, stamp residue) is NOT an item.
    assert all("质保" not in n and "户名" not in n for n in names)


def test_parse_contract_table_row_amounts_and_quantity():
    extraction = Extraction(text=CONTRACT_TABLE_TEXT)
    contract = parse_contract(extraction, Path("ZHDEMO-20260410-04.pdf"), attached_files=[])

    suge, ai = contract.items
    assert suge.unit == "年"
    assert suge.quantity == 2
    assert suge.unit_price == 4800.0
    assert suge.amount == 9600.0
    assert ai.unit == "套"
    assert ai.unit_price == 1800.0
    assert ai.amount == 1800.0


def test_parse_contract_table_keeps_multi_section_rows_across_subtotals():
    text = (
        "序号 品项名称 单位 数量 单价 金额\n"
        "1-1 智核甲校系统 套 1 ¥1.00 ¥1.00\n"
        "小计 ¥1.00\n"
        "2-1 智核乙校系统 套 1 ¥2.00 ¥2.00\n"
        "合计 ¥3.00\n"
        "户名：智核（成都）信息技术有限公司\n"
    )
    contract = parse_contract(Extraction(text=text), Path("c.pdf"), attached_files=[])
    names = [i.name for i in contract.items]
    assert names == ["智核甲校系统", "智核乙校系统"]  # 小计 must not end the table


def test_parse_contract_keyword_rows_not_hijacked_by_summary_line():
    # No real tabular header; a summary line carries name+price markers AND money.
    # It must NOT be taken as a header (which would skip the real rows above it).
    text = (
        "智核甲品 个 1 ¥1.00 ¥1.00\n"
        "智核乙品 个 1 ¥2.00 ¥2.00\n"
        "项目总金额 ¥3.00\n"
    )
    contract = parse_contract(Extraction(text=text), Path("c.pdf"), attached_files=[])
    names = [i.name for i in contract.items]
    assert any("甲品" in n for n in names) and any("乙品" in n for n in names)


def test_parse_contract_table_multi_section_with_per_section_total():
    # Some contracts label each section's total 合计 and the grand total 总计; the
    # table ends only at the LAST total, so no section is dropped.
    text = (
        "序号 品项名称 单位 数量 单价 金额\n"
        "1-1 智核甲校系统 套 1 ¥1.00 ¥1.00\n"
        "合计 ¥1.00\n"
        "2-1 智核乙校系统 套 1 ¥2.00 ¥2.00\n"
        "总计 ¥3.00\n"
    )
    contract = parse_contract(Extraction(text=text), Path("c.pdf"), attached_files=[])
    assert [i.name for i in contract.items] == ["智核甲校系统", "智核乙校系统"]


def test_parse_contract_table_header_without_serial_column():
    # A native header lacking 序号 must still be recognized, so a no-keyword row
    # (AI服务) is not dropped back to the keyword fallback.
    text = (
        "品名 单位 数量 单价 金额\n"
        "智核启思云平台服务 年 2 ¥4,800.00 ¥9,600.00\n"
        "AI服务 套 1 ¥1,800.00 ¥1,800.00\n"
        "合计 ¥11,400.00\n"
    )
    contract = parse_contract(Extraction(text=text), Path("c.pdf"), attached_files=[])
    names = [i.name for i in contract.items]
    assert any("AI服务" in n for n in names)
    assert any("启思云平台服务" in n for n in names)


def test_parse_contract_table_preserves_leading_model_token():
    # A leading IRS-300 is a model, not a 序号/code, and must not be stripped away.
    text = (
        "序号 品项名称 单位 数量 单价 金额\n"
        "1-1 IRS-300 智核接收终端 个 1 ¥1.00 ¥1.00\n"
        "合计 ¥1.00\n"
    )
    contract = parse_contract(Extraction(text=text), Path("c.pdf"), attached_files=[])
    assert contract.items[0].model == "IRS-300"


def test_parse_contract_from_ocr_tokens_captures_all_rows_and_stops_at_total():
    # 0421-shaped: a 序号/品项 table where one row (AI服务) lacks the 智核 keyword,
    # followed by a 合计 total and 智核-bearing prose that must NOT become items.
    header = [
        OcrToken("序号", 0.9, x=10, y=0),
        OcrToken("品项名称", 0.9, x=80, y=0),
        OcrToken("单位", 0.9, x=300, y=0),
        OcrToken("数量", 0.9, x=360, y=0),
        OcrToken("单价（含税）", 0.9, x=430, y=0),
        OcrToken("金额（含税）", 0.9, x=540, y=0),
    ]
    row1 = [
        OcrToken("1-1", 0.9, x=10, y=40),
        OcrToken("C5-2-1 智核启思云平台服务", 0.9, x=80, y=40),
        OcrToken("年", 0.9, x=300, y=40),
        OcrToken("2", 0.9, x=360, y=40),
        OcrToken("¥4,800.00", 0.9, x=430, y=40),
        OcrToken("¥9,600.00", 0.9, x=540, y=40),
    ]
    row2 = [
        OcrToken("1-2", 0.9, x=10, y=80),
        OcrToken("TS-3-1 AI服务", 0.9, x=80, y=80),
        OcrToken("套", 0.9, x=300, y=80),
        OcrToken("¥1,800.00", 0.9, x=430, y=80),
        OcrToken("¥1,800.00", 0.9, x=540, y=80),
    ]
    total = [OcrToken("合计", 0.9, x=10, y=120), OcrToken("¥11,400.00", 0.9, x=540, y=120)]
    prose = [OcrToken("户名：智核（成都）信息技术有限公司", 0.9, x=10, y=160)]

    extraction = Extraction(text="", tokens=header + row1 + row2 + total + prose)
    contract = parse_contract(extraction, Path("ZHDEMO-20260410-04.pdf"), attached_files=[])

    names = [item.name for item in contract.items]
    # Names are cleaned of the leading 序号 + product code (which live in their own
    # fields), so they match the bare names used elsewhere.
    assert names == ["智核启思云平台服务", "AI服务"]


def test_parse_module_table_handles_digit_suffixed_contract_and_bare_quantity_header():
    # Real png: contract numbers carry a digit suffix (ZHDEMO2-...), and the 数量
    # column header is OCR'd as the bare "数". Every row must still parse with a
    # distinct quantity and unit price (not collapsed into one garbled number).
    header = [
        OcrToken("合同单号", 0.9, x=222, y=137),
        OcrToken("采购公司名称", 0.9, x=711, y=137),
        OcrToken("产品名称", 0.9, x=1524, y=137),
        OcrToken("型号", 0.9, x=2164, y=137),
        OcrToken("单位", 0.9, x=2365, y=137),
        OcrToken("数", 0.9, x=2499, y=137),
        OcrToken("单价", 0.9, x=2652, y=137),
        OcrToken("金额", 0.9, x=2898, y=137),
        OcrToken("权益金", 0.9, x=3154, y=137),
    ]
    row1 = [
        OcrToken("ZHDEMO2-20250926-01", 0.9, x=100, y=206),
        OcrToken("四川代理商甲信息技术有限公司", 0.9, x=594, y=206),
        OcrToken("智核ZClass5专业版系统", 0.9, x=1369, y=206),
        OcrToken("V5.0", 0.9, x=2166, y=206),
        OcrToken("套", 0.9, x=2386, y=206),
        OcrToken("6", 0.9, x=2530, y=206),
        OcrToken("2850", 0.9, x=2650, y=206),
        OcrToken("17100", 0.9, x=2889, y=206),
        OcrToken("4500", 0.9, x=3169, y=206),
    ]
    row3 = [
        OcrToken("ZHDEMO-20251030-01", 0.9, x=113, y=333),
        OcrToken("四川易网四海科技有限公司", 0.9, x=593, y=333),
        OcrToken("智核学生互动反馈系统", 0.9, x=1407, y=333),
        OcrToken("V5.0", 0.9, x=2166, y=333),
        OcrToken("110", 0.9, x=2510, y=333),
        OcrToken("210", 0.9, x=2662, y=333),
        OcrToken("23100", 0.9, x=2888, y=333),
        OcrToken("5775", 0.9, x=3169, y=333),
    ]
    extraction = Extraction(text="", tokens=header + row1 + row3)
    rows = parse_module_table(extraction, Path("模組金額核算表.png"))

    assert len(rows) == 2
    first = rows[0]
    assert first.contract_number == "ZHDEMO2-20250926-01"
    assert first.product_name == "智核ZClass5专业版系统"
    assert first.quantity == 6
    assert first.unit_price == 2850.0
    assert first.amount == 17100.0
    assert first.royalty == 4500.0
    last = rows[1]
    assert last.contract_number == "ZHDEMO-20251030-01"
    assert last.quantity == 110
    assert last.unit_price == 210.0


def test_parse_contract_from_ocr_tokens_reconstructs_row():
    header = [
        OcrToken("名称", 0.9, x=10, y=0),
        OcrToken("型号", 0.9, x=120, y=0),
        OcrToken("数量", 0.9, x=200, y=0),
        OcrToken("单价（含税）", 0.9, x=280, y=0),
        OcrToken("金额（含税）", 0.9, x=380, y=0),
    ]
    row = [
        OcrToken("智核ZClass5专业版系统", 0.8, x=10, y=40),
        OcrToken("V5.0", 0.8, x=120, y=40),
        OcrToken("1", 0.8, x=200, y=40),
        OcrToken("¥2,500.00", 0.8, x=280, y=40),
        OcrToken("¥2,500.00", 0.8, x=380, y=40),
    ]
    extraction = Extraction(text="", tokens=header + row)
    contract = parse_contract(extraction, Path("ZHDEMO-20251124-01.pdf"), attached_files=[])

    assert contract.contract_number == "ZHDEMO-20251124-01"
    assert len(contract.items) == 1
    item = contract.items[0]
    assert item.name == "智核ZClass5专业版系统"
    assert item.model == "V5.0"
    assert item.quantity == 1
    assert item.unit_price == 2500.0


def test_parse_contract_buyer_name_stops_at_company_suffix():
    """OCR-jumbled line must not bleed past the company-name suffix."""
    extraction = Extraction(
        text=(
            "购销合同\n"
            "单位名称四川代理商甲信息技术有限公司 纳税识别号： 订单号码 91510107684562812F ZHDEMO-20251124-01\n"
            "智核ZClass5专业版系统 V5.0 套 1 2500 2500\n"
        )
    )
    contract = parse_contract(extraction, Path("ZHDEMO-20251124-01.pdf"), attached_files=[])

    assert contract.buyer_name == "四川代理商甲信息技术有限公司"


def test_parse_contract_unreadable_when_no_text_or_tokens():
    contract = parse_contract(Extraction(), Path("ZHDEMO-20251124-01.pdf"), attached_files=[])

    assert contract.readable is False
    assert contract.contract_number == "ZHDEMO-20251124-01"


def _module_extraction():
    header = [
        OcrToken("合同单号", 0.9, x=10, y=0),
        OcrToken("采购公司名称", 0.9, x=120, y=0),
        OcrToken("产品名称", 0.9, x=260, y=0),
        OcrToken("型号", 0.9, x=400, y=0),
        OcrToken("单位", 0.9, x=470, y=0),
        OcrToken("数量", 0.9, x=540, y=0),
        OcrToken("单价", 0.9, x=610, y=0),
        OcrToken("金额", 0.9, x=700, y=0),
        OcrToken("权益金", 0.9, x=800, y=0),
    ]
    row = [
        OcrToken("ZHDEMO-20251124-01", 0.8, x=10, y=40),
        OcrToken("四川代理商甲信息技术有限公司", 0.8, x=120, y=40),
        OcrToken("智核ZClass5专业版系统", 0.8, x=260, y=40),
        OcrToken("V5.0", 0.8, x=400, y=40),
        OcrToken("套", 0.8, x=470, y=40),
        OcrToken("1", 0.8, x=540, y=40),
        OcrToken("2500", 0.8, x=610, y=40),
        OcrToken("2500", 0.8, x=700, y=40),
        OcrToken("750", 0.8, x=800, y=40),
    ]
    return Extraction(text="", tokens=header + row)


def test_parse_module_table_reconstructs_row():
    rows = parse_module_table(_module_extraction(), Path("module.png"))

    assert len(rows) == 1
    row = rows[0]
    assert row.contract_number == "ZHDEMO-20251124-01"
    assert row.purchasing_company == "四川代理商甲信息技术有限公司"
    assert row.product_name == "智核ZClass5专业版系统"
    assert row.model == "V5.0"
    assert row.quantity == 1
    assert row.unit_price == 2500.0
    assert row.amount == 2500.0
    assert row.royalty == 750.0


def test_parse_module_table_repairs_ocr_contract_number():
    extraction = _module_extraction()
    repaired = [
        tok if tok.text != "ZHDEMO-20251124-01" else OcrToken("ZDEMO-20251124-01", 0.7, tok.x, tok.y)
        for tok in extraction.tokens
    ]
    rows = parse_module_table(Extraction(text="", tokens=repaired), Path("module.png"))

    assert rows[0].contract_number == "ZDEMO-20251124-01"


def test_parse_module_table_tolerates_column_offset():
    """Tokens offset >70px from their header column must still parse correctly.

    Columns are spaced 200px apart so an 80px offset keeps every data token
    clearly nearest its own header column (80 < 100 = half-gap).  The old
    fixed-threshold (70px) would have rejected all of them.
    """
    # Header columns spaced 200px apart — large enough that an 80px offset
    # still leaves each data token closest to its own column.
    header = [
        OcrToken("合同单号", 0.9, x=0, y=0),
        OcrToken("采购公司名称", 0.9, x=200, y=0),
        OcrToken("产品名称", 0.9, x=400, y=0),
        OcrToken("型号", 0.9, x=600, y=0),
        OcrToken("单位", 0.9, x=800, y=0),
        OcrToken("数量", 0.9, x=1000, y=0),
        OcrToken("单价", 0.9, x=1200, y=0),
        OcrToken("金额", 0.9, x=1400, y=0),
        OcrToken("权益金", 0.9, x=1600, y=0),
    ]
    # Data tokens each shifted +80px from their header column x.
    # 80px < half-gap (100px) → each token is still nearest its own column.
    # But 80px > old 70px hard threshold → the old code would drop them all.
    OFFSET = 80
    row = [
        OcrToken("ZHDEMO-20251124-01", 0.8, x=0 + OFFSET, y=40),
        OcrToken("四川代理商甲信息技术有限公司", 0.8, x=200 + OFFSET, y=40),
        OcrToken("智核ZClass5专业版系统", 0.8, x=400 + OFFSET, y=40),
        OcrToken("V5.0", 0.8, x=600 + OFFSET, y=40),
        OcrToken("套", 0.8, x=800 + OFFSET, y=40),
        OcrToken("1", 0.8, x=1000 + OFFSET, y=40),
        OcrToken("2500", 0.8, x=1200 + OFFSET, y=40),
        OcrToken("2500", 0.8, x=1400 + OFFSET, y=40),
        OcrToken("750", 0.8, x=1600 + OFFSET, y=40),
    ]
    extraction = Extraction(text="", tokens=header + row)
    rows = parse_module_table(extraction, Path("module.png"))

    assert len(rows) == 1
    r = rows[0]
    assert r.contract_number == "ZHDEMO-20251124-01"
    assert r.product_name == "智核ZClass5专业版系统"
    assert r.unit_price == 2500.0


def test_parse_approval_items_from_chuhuoneirong_format():
    text = (
        "出货内容： C5-2-1，2年智核启思云平台服务（管理权限+100G空间）\n"
        "T5-3-1，1套AI服务（授权序列号为：SNDEMO01-6M83）\n"
        "收货地址： 自提\n"
    )
    ap = parse_approval_text(text, Path("a.pdf"))
    assert len(ap.actual_items) == 2
    assert any("启思云平台服务" in (i.name or "") for i in ap.actual_items)


def test_parse_approval_items_numbered_chuhuoneirong():
    text = (
        "出货内容：\n"
        "1、C5-2-1，智核启思云平台管理服务（含100G空间） 1年\n"
        "2、C5-1，智核云服务（启思云平台） 1.5T空间 1年\n"
        "3、C5-5-1，智核智慧学校云平台（基础版） 1年\n"
        "收货地址：\n"
    )
    ap = parse_approval_text(text, Path("a.pdf"))
    assert len(ap.actual_items) == 3


def test_parse_approval_school_name_label_variants():
    cases = [
        ("备注 1、学校全称：示范乙校 代码：2151005439", "示范乙校"),
        ("1、学校完整名称：北京市东城区示范丙校；教育部-学校代码：2111000810", "北京市东城区示范丙校"),
        ("2、学校名称：示范庚校，教育部学校代码：2151005180", "示范庚校"),
        ("一、学校名称：中国移动示范戊校分公司，代码：无，简码：无。", "中国移动示范戊校分公司"),
        ("1、学校名称：示范丁校 ；教育部学校代码", "示范丁校"),
    ]
    for line, expected in cases:
        assert parse_approval_text(line, Path("a.pdf")).school_name == expected


def test_module_table_with_region_and_sales_columns_keeps_company_clean():
    header = [
        OcrToken("合同单号", 0.9, x=207, y=0),
        OcrToken("区域", 0.9, x=564, y=0),
        OcrToken("销售经理", 0.9, x=743, y=0),
        OcrToken("采购公司名称", 0.9, x=1131, y=0),
        OcrToken("产品名称", 0.9, x=1791, y=0),
        OcrToken("型号", 0.9, x=2245, y=0),
        OcrToken("单价", 0.9, x=2894, y=0),
        OcrToken("金额", 0.9, x=3109, y=0),
        OcrToken("权益金", 0.9, x=3310, y=0),
    ]
    row = [
        OcrToken("ZHDEMO-20251223-01", 0.9, x=95, y=40),
        OcrToken("销售3部", 0.9, x=538, y=40),
        OcrToken("徐珺", 0.9, x=779, y=40),
        OcrToken("示范丁校", 0.9, x=1031, y=40),
        OcrToken("智核A教研中心智能终端系统", 0.9, x=1601, y=40),
        OcrToken("V1.0", 0.9, x=2249, y=40),
        OcrToken("91850", 0.9, x=2882, y=40),
        OcrToken("91850", 0.9, x=3098, y=40),
        OcrToken("13500", 0.9, x=3314, y=40),
    ]
    rows = parse_module_table(Extraction(text="", tokens=header + row), Path("m.png"))
    assert len(rows) == 1
    assert rows[0].purchasing_company == "示范丁校"
    assert "徐珺" not in (rows[0].purchasing_company or "")
