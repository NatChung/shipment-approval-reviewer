from shipment_review.extractors.files import detect_case_files


def test_detect_by_filename_markers(tmp_path):
    approval = tmp_path / "申请人甲提交的出货审批202606091044000425537.pdf"
    module = tmp_path / "模組金核算表.png"
    contract = tmp_path / "ZHDEMO-20251124-01（双章）代理商甲-智核.pdf"
    for path in (approval, module, contract):
        path.write_bytes(b"x")

    detected = detect_case_files(tmp_path)

    assert detected.approval == approval
    assert detected.module_table == module
    assert detected.contracts == [contract]


def test_module_table_falls_back_to_lone_image(tmp_path):
    approval = tmp_path / "出货审批.txt"
    module = tmp_path / "c07ee594c3664042b05f0fea6d4e88e0.png"
    contract = tmp_path / "ZHDEMO-20251124-01.pdf"
    approval.write_text("出货审批", encoding="utf-8")
    module.write_bytes(b"x")
    contract.write_bytes(b"x")

    detected = detect_case_files(tmp_path)

    assert detected.module_table == module
    assert detected.contracts == [contract]


def test_approval_detected_by_content_when_name_is_generic(tmp_path):
    approval = tmp_path / "doc1.txt"
    contract = tmp_path / "doc2.txt"
    approval.write_text("出货审批 合同编号 ZHDEMO-20251124-01", encoding="utf-8")
    contract.write_text("购销合同", encoding="utf-8")
    (tmp_path / "table.png").write_bytes(b"x")

    detected = detect_case_files(tmp_path)

    assert detected.approval == approval
    assert detected.contracts == [contract]


def test_detect_xlsx_module_table(tmp_path):
    approval = tmp_path / "出货审批.txt"
    approval.write_text("出货审批", encoding="utf-8")
    xlsx = tmp_path / "示范辛校-模组金.xlsx"
    xlsx.write_bytes(b"x")
    contract = tmp_path / "ZHDEMO-20250625-01.pdf"
    contract.write_bytes(b"x")

    det = detect_case_files(tmp_path)

    assert det.module_table == xlsx


def test_module_table_prefers_readable_image_over_unreadable_xlsx(tmp_path):
    # 0512-shaped: the 模组金 export is an .xlsx the extractor cannot read, but a
    # readable module-table png sits alongside it. The png must win.
    approval = tmp_path / "出货审批.txt"
    approval.write_text("出货审批", encoding="utf-8")
    xlsx = tmp_path / "示范辛校200位教师授权-模组金.xlsx"
    xlsx.write_bytes(b"x")
    png = tmp_path / "lQLPmoduletable_1091_43.png"
    png.write_bytes(b"x")
    contract = tmp_path / "ZHDEMO-20250625-01.pdf"
    contract.write_bytes(b"x")

    det = detect_case_files(tmp_path)

    assert det.module_table == png


def test_second_approval_doc_is_not_a_contract(tmp_path):
    approval = tmp_path / "申请人甲提交的出货审批202605151649000507028.pdf"
    other_approval = tmp_path / "申请人乙提交的通用审批202605151455000368378.pdf"
    module = tmp_path / "模组金核算表.png"
    contract = tmp_path / "ZHDEMO-20260515-01（双章）代理商甲-智核.pdf"
    for p in (approval, other_approval, module, contract):
        p.write_bytes(b"x")
    det = detect_case_files(tmp_path)
    assert det.approval == approval
    assert det.contracts == [contract]            # the 通用审批 is excluded
    assert other_approval not in det.contracts
