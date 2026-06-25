from pathlib import Path

from shipment_review.html_report import render_html
from shipment_review.models import ReviewStatus, UnverifiedPolicy
from shipment_review.report import build_report


def _write_case(tmp_path: Path, with_module: bool = True) -> Path:
    (tmp_path / "出货审批.txt").write_text(
        "出货审批\n审批编码 202606091044000425537\n合同编号 ZHDEMO-20251124-01\n"
        "出货金额（元） 2,500.00\n出货公司名称 四川代理商甲信息技术有限公司\n实际出货为：\n"
        "T5-3，1套智核ZClass5专业版系统V5.0\n收货人： 王钞\n"
        "【财务确认】 审批人甲 已同意\n",
        encoding="utf-8",
    )
    (tmp_path / "ZHDEMO-20251124-01.txt").write_text(
        "购销合同\n订单号码 ZHDEMO-20251124-01\n单位名称 四川代理商甲信息技术有限公司\n"
        "T5-3 智核ZClass5专业版系统 V5.0 套 1 2500 2500\n",
        encoding="utf-8",
    )
    if with_module:
        (tmp_path / "模組金核算表.txt").write_text(
            "合同单号 采购公司名称 产品名称 型号 单位 数量 单价 金额 权益金\n"
            "ZHDEMO-20251124-01 四川代理商甲信息技术有限公司 T5-3 智核ZClass5专业版系统 V5.0 套 1 2500 2500 750\n",
            encoding="utf-8",
        )
    return tmp_path


def test_build_report_tiers_and_materials(tmp_path):
    # No module table → ⚠️ 缺模組表 under default focused-manual.
    report = build_report(_write_case(tmp_path, with_module=False))

    assert report.result.status is ReviewStatus.MANUAL_REVIEW
    assert any("缺少模組金核算表" in i.message for i in report.unverified)
    assert not report.violations
    assert report.approval is not None and report.approval.contract_numbers == ("ZHDEMO-20251124-01",)
    assert any(c.contract_number == "ZHDEMO-20251124-01" for c in report.contracts)


def test_build_report_policy_passes_through(tmp_path):
    case = _write_case(tmp_path, with_module=False)
    assert build_report(case).result.status is ReviewStatus.MANUAL_REVIEW
    assert build_report(case, UnverifiedPolicy.BLOCK).result.status is ReviewStatus.BLOCKED


def test_render_html_marks_review_terms_in_extracted_text(tmp_path):
    # A product named in a ❌/⚠️ issue is wrapped in <mark> where it appears in the
    # extracted text, so a reviewer can find the spot to check.
    (tmp_path / "出货审批.txt").write_text(
        "出货审批\n审批编码 1\n合同编号 ZHDEMO-20251124-01\n实际出货为：\n智核ZClass5专业版系统V5.0\n",
        encoding="utf-8",
    )
    (tmp_path / "ZHDEMO-20251124-01.txt").write_text(
        "购销合同\n订单号码 ZHDEMO-20251124-01\n", encoding="utf-8"
    )
    html = render_html(build_report(tmp_path))

    assert "<mark>智核ZClass5专业版系统</mark>" in html


def test_render_html_has_verdict_tiers_controls_and_sources(tmp_path):
    html = render_html(build_report(_write_case(tmp_path, with_module=False)))

    assert html.startswith("<!doctype html>")
    assert "需人工確認" in html
    assert "待人工核實" in html  # ⚠️ tier header (semantic color/dot, no emoji)
    assert "缺少模組金核算表" in html
    assert "放行" in html and "駁回" in html
    assert "exportDecisions" in html
    # source materials present for comparison
    assert "出貨審批" in html and "ZHDEMO-20251124-01" in html
    assert "智核ZClass5专业版系统" in html


def test_render_html_escapes_angle_brackets(tmp_path):
    # A product name with < > must not break the markup.
    (tmp_path / "出货审批.txt").write_text(
        "出货审批\n审批编码 1\n合同编号 ZHDEMO-20251124-01\n实际出货为：\n智核<script>系统 V5.0\n",
        encoding="utf-8",
    )
    html = render_html(build_report(tmp_path))
    assert "<script>系统" not in html
    assert "&lt;script&gt;" in html


def test_build_report_lists_source_files_with_kind(tmp_path):
    from shipment_review.report import build_report
    case = _write_case(tmp_path, with_module=True)  # existing helper in this file
    report = build_report(case)
    roles = {sf.role: sf for sf in report.source_files}
    assert roles["approval"].kind == "text" and roles["approval"].path.endswith("出货审批.txt")
    assert roles["module"].kind == "text"
    contract = next(sf for sf in report.source_files if sf.role == "contract")
    assert contract.kind == "text" and contract.contract_number == "ZHDEMO-20251124-01"
    # paths are absolute (Windows-safe check)
    from pathlib import Path

    assert all(Path(sf.path).is_absolute() for sf in report.source_files)


def test_issue_anchor_targets_panel_by_prefix_and_row(tmp_path):
    from shipment_review.report import build_report, issue_anchor
    report = build_report(_write_case(tmp_path, with_module=True))
    # approval-side item (rule prefix 出貨項目, bracket is "name model")
    a = issue_anchor("出貨項目「智核ZClass5专业版系统 V5.0」未在任何合同中找到。", report)
    assert a.panel_id == "panel-approval" and a.row_index == 0
    # module-side item
    m = issue_anchor("模組表項目「智核ZClass5专业版系统 V5.0」未在出貨審批實際出貨項目中找到。", report)
    assert m.panel_id == "panel-module" and m.row_index == 0
    # contract chosen by number
    c = issue_anchor("模組表合同單號 ZHDEMO-20251124-01 的「智核ZClass5专业版系统」單價不一致：模組表 1，合同 2。", report)
    assert c.panel_id == "panel-module"  # 模組表… prefix → module panel, row matched
    # unanchorable structural issue → still returns a panel, row_index None
    u = issue_anchor("缺少模組金核算表。", report)
    assert u is None or u.row_index is None


def test_verdict_json_shape(tmp_path):
    import json as _json
    from shipment_review.report import build_report
    from shipment_review.json_report import verdict_json
    (tmp_path / "出货审批.txt").write_text(
        "出货审批\n审批编码 1\n合同编号 ZHDEMO-20251124-01\n实际出货为：\n智核ZClass5专业版系统V5.0\n",
        encoding="utf-8")
    (tmp_path / "ZHDEMO-20251124-01.txt").write_text("购销合同\n订单号码 ZHDEMO-20251124-01\n", encoding="utf-8")
    j = verdict_json(build_report(tmp_path))
    assert set(j) == {"status", "violations", "needs_review", "confirmed_checks", "ai_unconfirmed_contracts"}
    assert isinstance(j["status"], str)
    assert all(set(i) == {"severity", "message", "unverified"} for i in j["violations"] + j["needs_review"])
    _json.dumps(j)  # serialisable


def test_render_html_embeds_originals_and_links_issue_to_row(tmp_path):
    from PIL import Image
    # a real PNG module table so kind=image and a file:// img is emitted
    img = tmp_path / "模組金核算表.png"
    Image.new("RGB", (4, 4), "white").save(img)
    (tmp_path / "出货审批.txt").write_text(
        "出货审批\n审批编码 1\n合同编号 ZHDEMO-20251124-01\n实际出货为：\n"
        "T5-3，1套智核ZClass5专业版系统V5.0\n", encoding="utf-8")
    # Contract has the number but does NOT list the product → the approval item is unmatched,
    # raising 出貨項目「…」未在任何合同中找到 (a ❌ violation that anchors to the approval row).
    (tmp_path / "ZHDEMO-20251124-01.txt").write_text(
        "购销合同\n订单号码 ZHDEMO-20251124-01\n单位名称 四川代理商甲信息技术有限公司\n",
        encoding="utf-8")
    from shipment_review.report import build_report
    from shipment_review.html_report import render_html
    html = render_html(build_report(tmp_path))

    # The blank PNG module table parses to zero rows but its panel + <img file://> still render.
    assert 'src="file://' in html and ".png" in html         # embedded image
    assert 'id="panel-approval-row-0"' in html               # row carries an id
    assert "jumpTo('panel-approval','panel-approval-row-0')" in html  # clickable issue → row
    assert "請用 Chrome / Edge 開啟" in html                  # browser note
    assert "class='file'" in html and "出货审批.txt" in html  # issue carries a file-open link


def test_gather_case_backfills_numberless_contract(tmp_path):
    # An approval listing two numbers + two contract files (one filename carries its number,
    # one doesn't), and a module table tying the leftover number to a product → the numberless
    # contract is backfilled with number_inferred=True.
    from shipment_review.report import gather_case
    (tmp_path / "出货审批.txt").write_text(
        "出货审批\n审批编码 1\n合同编号 ZHDEMO-20251124-01、ZHDEMO-20231211-01\n"
        "附合同 ZHDEMO-20251124-01代理商甲.pdf\n代理商乙-智核1551637.5元.pdf\n实际出货为：\n",
        encoding="utf-8")
    (tmp_path / "ZHDEMO-20251124-01代理商甲.txt").write_text(
        "购销合同\n订单号码 ZHDEMO-20251124-01\n", encoding="utf-8")
    (tmp_path / "代理商乙-智核1551637.5元.txt").write_text(
        "购销合同\n合同编号：\n", encoding="utf-8")  # number field blank
    (tmp_path / "模組金核算表.txt").write_text(
        "合同单号 采购公司名称 产品名称 型号 单位 数量 单价 金额 权益金\n"
        "ZHDEMO-20231211-01 四川代理商乙昆吾信息产业有限公司 智核AI教研中心智能终端系统 V1.0 套 1 45000 45000 0\n",
        encoding="utf-8")
    contracts = {c.contract_number: c for c in gather_case(tmp_path).case.contracts}
    inferred = contracts.get("ZHDEMO-20231211-01")
    assert inferred is not None and inferred.number_inferred is True
    assert contracts["ZHDEMO-20251124-01"].number_inferred is False


def test_html_marks_inferred_contract_number(tmp_path):
    from dataclasses import replace
    from shipment_review.report import build_report
    from shipment_review.html_report import render_html
    (tmp_path / "出货审批.txt").write_text(
        "出货审批\n审批编码 1\n合同编号 ZHDEMO-20231211-01\n实际出货为：\n", encoding="utf-8")
    (tmp_path / "ZHDEMO-20231211-01.txt").write_text("购销合同\n订单号码 ZHDEMO-20231211-01\n", encoding="utf-8")
    report = build_report(tmp_path)
    report = replace(report, contracts=[replace(report.contracts[0], number_inferred=True)])
    html = render_html(report)
    assert "消去法推得" in html
