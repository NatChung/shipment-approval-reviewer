from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from shipment_review.extractors.files import APPROVAL_EXCLUDE_MARKER, GENERAL_APPROVAL_MARKER
from shipment_review.models import (
    Approval,
    CaseData,
    Contract,
    ContractItem,
    Issue,
    IssueSeverity,
    ModuleRow,
    ReviewResult,
    ShipmentItem,
    UnverifiedPolicy,
)
from shipment_review.normalization import (
    contract_numbers_match,
    extract_contract_numbers,
    normalize_company,
    normalize_contract_number,
    normalize_money,
    normalize_text,
    product_key,
    products_match,
    units_compatible,
)


def review_case(
    case: CaseData, unverified_policy: UnverifiedPolicy = UnverifiedPolicy.MANUAL
) -> ReviewResult:
    issues: list[Issue] = list(case.extraction_issues)
    checks: list[str] = []

    if case.approval is None:
        issues.append(Issue(IssueSeverity.HARD_BLOCK, "缺少出貨審批文件。"))
    if not case.module_rows:
        if case.module_table_present:
            issues.append(Issue(IssueSeverity.MANUAL_REVIEW, "模組金核算表已偵測到但無法自動解析（可能為 Excel 檔或掃描品質不足），請人工核對模組金。"))
        else:
            # Missing supporting input, not a proven violation → ⚠️ (policy decides verdict).
            issues.append(Issue(IssueSeverity.HARD_BLOCK, "缺少模組金核算表。", unverified=True))

    readable_contracts = [contract for contract in case.contracts if contract.readable]
    if not readable_contracts:
        issues.append(Issue(IssueSeverity.HARD_BLOCK, "沒有可讀合同，無法核對出貨項目與單價。", unverified=True))
    else:
        affected = _unreadable_expected_contracts(case.expected_contract_files, readable_contracts)
        if affected:
            issues.append(
                Issue(
                    IssueSeverity.MANUAL_REVIEW,
                    f"部分預期合同無法讀取，請確認缺少或不可讀的合同檔案：{'、'.join(affected)}。",
                )
            )

    if case.approval is not None:
        issues.extend(_check_item_source_disagreement(case.approval))
        issues.extend(_check_approval_amount_total(case.approval, case.module_rows))

    if case.approval is not None and readable_contracts:
        has_general_approval = any(
            GENERAL_APPROVAL_MARKER in name for name in case.approval.attached_contract_files
        )
        issues.extend(_check_approval_contract_numbers(case.approval.contract_numbers, readable_contracts, case.module_rows))
        issues.extend(
            _check_shipment_items_in_contracts(
                case.approval.actual_items, readable_contracts, case.module_rows, has_general_approval
            )
        )
        issues.extend(_check_module_rows_in_approval(case.module_rows, case.approval.actual_items))

    if readable_contracts and case.module_rows:
        for row in case.module_rows:
            issues.extend(_check_module_row(row, readable_contracts))

    # The three standing checks are always offered; the formatter shows each ✅ only when
    # no issue contradicts it, so confirmations appear alongside ⚠️/❌ items too.
    checks.extend(
        [
            "模組表合同單號均可對應合同",
            "出貨項目均可在合同中找到",
            "模組表單價與合同單價一致",
        ]
    )

    return ReviewResult.from_issues(issues, checks, unverified_policy)


def _check_item_source_disagreement(approval: Approval) -> list[Issue]:
    if not approval.original_field_items or not approval.comment_items:
        return []

    original = {_item_signature(item) for item in approval.original_field_items}
    comment = {_item_signature(item) for item in approval.comment_items}
    if original != comment:
        return [
            Issue(
                IssueSeverity.MANUAL_REVIEW,
                "出貨內容欄位與審批流程評論中的實際出貨內容不同，已優先採用評論內容，請人工確認差異。",
            )
        ]
    return []


def _item_signature(item: ShipmentItem) -> tuple[str, str, float | None]:
    return (
        product_key(item.code, item.name, item.model),
        normalize_text(item.unit),
        item.quantity,
    )


def _has_reliable_contract(contracts: Sequence[Contract]) -> bool:
    return any(c.readable and not c.ocr_extracted and not c.ai_unconfirmed for c in contracts)


def _unreadable_expected_contracts(
    expected_files: Sequence[str], readable_contracts: Sequence[Contract]
) -> list[str]:
    """Attached contract files the approval expects but whose contract NUMBER has no
    readable contract. Filenames are unreliable — copy suffixes like "(1)(1)(1)" or
    " - 複製" differ from the on-disk name for the same contract — so we match by contract
    number, never by basename. 审批 docs are not contracts; a file with no extractable
    number can't be checked this way and is skipped."""
    affected: list[str] = []
    for name in expected_files:
        if APPROVAL_EXCLUDE_MARKER in name:
            continue
        file_numbers = extract_contract_numbers(name)
        if not file_numbers:
            continue
        if not any(
            contract_numbers_match(number, contract.contract_number)
            for number in file_numbers
            for contract in readable_contracts
        ):
            affected.append(name)
    return affected


def _check_approval_contract_numbers(
    approval_contract_numbers: Sequence[str],
    contracts: Sequence[Contract],
    module_rows: Sequence[ModuleRow],
) -> list[Issue]:
    issues: list[Issue] = []
    approval_numbers = {number for value in approval_contract_numbers if (number := normalize_contract_number(value))}
    if not approval_numbers:
        return [Issue(IssueSeverity.MANUAL_REVIEW, "出貨審批缺少合同單號，請人工確認合同對應關係。")]

    contract_numbers = {number for contract in contracts if (number := normalize_contract_number(contract.contract_number))}
    module_numbers = {number for row in module_rows if (number := normalize_contract_number(row.contract_number))}

    missing_contracts = _unmatched(approval_numbers, contract_numbers)
    if missing_contracts:
        if _has_reliable_contract(contracts):
            issues.append(
                Issue(
                    IssueSeverity.HARD_BLOCK,
                    f"出貨審批合同單號未找到對應合同：{'、'.join(missing_contracts)}。",
                )
            )
        else:
            issues.append(
                Issue(
                    IssueSeverity.MANUAL_REVIEW,
                    f"出貨審批合同單號 {'、'.join(missing_contracts)} 未能在合同中確認(合同為掃描件,OCR 可能讀取不全),請人工核對。",
                )
            )

    unexpected_contracts = _unmatched(contract_numbers, approval_numbers)
    if unexpected_contracts:
        issues.append(
            Issue(
                IssueSeverity.HARD_BLOCK,
                f"合同單號未出現在出貨審批中：{'、'.join(unexpected_contracts)}。",
            )
        )

    missing_module_numbers = _unmatched(approval_numbers, module_numbers)
    if module_rows and missing_module_numbers:
        issues.append(
            Issue(
                IssueSeverity.MANUAL_REVIEW,
                f"審批合同單號未出現在模組表：{'、'.join(missing_module_numbers)}，請確認模組表是否缺列。",
            )
        )

    unexpected_module_numbers = _unmatched(module_numbers, approval_numbers)
    if unexpected_module_numbers:
        issues.append(
            Issue(
                IssueSeverity.HARD_BLOCK,
                f"模組表合同單號未出現在出貨審批中：{'、'.join(unexpected_module_numbers)}。",
            )
        )
    return issues


def _check_shipment_items_in_contracts(
    items: Sequence[ShipmentItem],
    contracts: Sequence[Contract],
    module_rows: Sequence[ModuleRow],
    has_general_approval: bool,
) -> list[Issue]:
    issues: list[Issue] = []
    # number_inferred contracts are unread OCR scans whose identity was guessed by elimination;
    # their (possibly garbled) items must not silently cover a shipment item (identity, not trust).
    trusted_items = [ci for c in contracts if not c.ai_unconfirmed and not c.number_inferred for ci in c.items]
    ai_items = [ci for c in contracts if c.ai_unconfirmed for ci in c.items]

    for item in items:
        found_in_trusted = any(
            products_match(item.code, item.name, item.model, ci.code, ci.name, ci.model)
            for ci in trusted_items
        )
        found_in_ai = any(
            products_match(item.code, item.name, item.model, ci.code, ci.name, ci.model)
            for ci in ai_items
        )
        found_in_module = any(
            products_match(item.code, item.name, item.model, row.code, row.product_name, row.model)
            and _module_row_ties_to_reliable_contract(row, contracts)
            for row in module_rows
        )
        if found_in_trusted:
            continue
        if found_in_ai:
            # Only an AI-unconfirmed contract lists it. Trust it only if an independent
            # module row corroborates (the 模組表↔合同 value check guards the numbers
            # separately); otherwise escalate — never a silent pass on AI's word alone.
            if found_in_module:
                continue
            issues.append(
                Issue(
                    IssueSeverity.MANUAL_REVIEW,
                    f"出貨項目「{item.name} {item.model or ''}」僅見於 AI 補讀且未經佐證的合同，請覆核原檔。",
                    unverified=True,
                )
            )
            continue
        if found_in_module and _has_reliable_contract(contracts):
            continue
        if has_general_approval:
            # The approval attaches a 通用审批, which can authorize 0元 services (e.g. an
            # IES platform activation) that appear in no contract or 模組表. The engine
            # cannot structurally verify the narrative authorization, so escalate to
            # 需人工確認 (human/AI review) rather than hard-blocking the shipment.
            issues.append(
                Issue(
                    IssueSeverity.MANUAL_REVIEW,
                    f"出貨項目「{item.name} {item.model or ''}」不在合同或模組表中，疑為通用審批授權項目，請人工複核授權範圍。",
                )
            )
        elif _has_reliable_contract(contracts):
            issues.append(Issue(IssueSeverity.HARD_BLOCK, f"出貨項目「{item.name} {item.model or ''}」未在任何合同中找到。"))
        else:
            issues.append(Issue(IssueSeverity.MANUAL_REVIEW, f"出貨項目「{item.name} {item.model or ''}」無法在合同中核對(合同為掃描件,OCR 可能不完整),請人工複核合同。"))
    return issues


def _module_row_ties_to_reliable_contract(row: ModuleRow, contracts: Sequence[Contract]) -> bool:
    """True when a module row's contract number matches a contract whose content was actually
    read (not an OCR scan, and so never a number_inferred one). Module coverage that leans on an
    unread scan is not real coverage."""
    return any(
        contract_numbers_match(row.contract_number, c.contract_number) and not c.ocr_extracted
        for c in contracts
    )


def _corroborated(number: str | None, module_rows: Sequence[ModuleRow]) -> bool:
    """A candidate contract number is corroborated when the module table carries at least one
    NAMED product row under that number — evidence the number is a real one used in this case,
    not a stray. Weak guard: it does NOT prove the number belongs to a specific file; the
    exactly-one ↔ one elimination does that."""
    target = normalize_contract_number(number)
    if not target:
        return False
    return any(
        normalize_contract_number(row.contract_number) == target and row.product_name
        for row in module_rows
    )


def backfill_inferred_contract_numbers(
    contracts: list[Contract],
    approval_numbers: Sequence[str],
    module_rows: Sequence[ModuleRow],
) -> list[Contract]:
    """Recover ONE contract's blank number by elimination: when exactly one approval number is
    unclaimed and exactly one contract has no number, assign it — but only if a module row
    corroborates. Returns a new list; the backfilled contract gets number_inferred=True. The
    contract stays an OCR gap (ocr_extracted untouched) — identity only, never trust.
    leftover = approval − assigned excludes already-held numbers by construction, so no clash."""
    assigned = {n for c in contracts if (n := normalize_contract_number(c.contract_number))}
    approval_set = {n for v in approval_numbers if (n := normalize_contract_number(v))}
    leftover = approval_set - assigned
    numberless = [i for i, c in enumerate(contracts) if not c.contract_number]
    if len(leftover) != 1 or len(numberless) != 1:
        return contracts
    candidate = next(iter(leftover))
    if not _corroborated(candidate, module_rows):
        return contracts
    result = list(contracts)
    i = numberless[0]
    result[i] = replace(result[i], contract_number=candidate, number_inferred=True)
    return result


def _check_approval_amount_total(approval: Approval, module_rows: Sequence[ModuleRow]) -> list[Issue]:
    """The approval's 出貨金額 is the figure a salesperson typed; the module table's
    单价 and 数量 are the trusted reference. Reconcile the approval total against the
    recomputed 单价×数量 sum (not the OCR-fragile printed 金额 column). Skip silently
    when either side is incomplete so we never raise a false mismatch on missing data."""
    expected = approval.shipment_amount
    if expected is None or not module_rows:
        return []
    # The module table lists only 权益金-bearing (software) items; shipped hardware
    # such as 接收终端 never appears there. If the approval ships anything absent from
    # the module table, its total legitimately exceeds the module sum by a value we
    # cannot recompute, so the totals are not comparable — skip rather than false-flag.
    for item in approval.actual_items:
        if not any(
            products_match(row.code, row.product_name, row.model, item.code, item.name, item.model)
            for row in module_rows
        ):
            return []
    computed = 0.0
    for row in module_rows:
        if row.unit_price is None or row.quantity is None:
            return []
        computed += row.unit_price * row.quantity
    if round(computed, 2) == round(expected, 2):
        return []
    return [
        Issue(
            IssueSeverity.MANUAL_REVIEW,
            f"出貨審批出貨金額與模組表單價×數量加總不一致：審批 {expected:g}，模組表合計 {computed:g}，請確認審批金額是否填錯。",
        )
    ]


def _check_module_rows_in_approval(module_rows: Sequence[ModuleRow], approval_items: Sequence[ShipmentItem]) -> list[Issue]:
    return _check_product_totals_between_module_rows_and_approval(module_rows, approval_items)


def _check_product_totals_between_module_rows_and_approval(
    module_rows: Sequence[ModuleRow],
    approval_items: Sequence[ShipmentItem],
) -> list[Issue]:
    module_by_key: dict[str, list[ModuleRow]] = {}
    for row in module_rows:
        module_by_key.setdefault(product_key(row.code, row.product_name, row.model), []).append(row)

    issues: list[Issue] = []

    for _row_key, rows in module_by_key.items():
        first_row = rows[0]
        approval_matches = [
            item for item in approval_items
            if any(
                products_match(row.code, row.product_name, row.model, item.code, item.name, item.model)
                for row in rows
            )
        ]
        if not approval_matches:
            issues.append(
                Issue(
                    IssueSeverity.MANUAL_REVIEW,
                    f"模組表項目「{first_row.product_name} {first_row.model or ''}」未在出貨審批實際出貨項目中找到。",
                )
            )
            continue
        issues.extend(_compare_module_group_to_shipment_items(rows, approval_matches))
    return issues


def _check_module_row(row: ModuleRow, contracts: Sequence[Contract]) -> list[Issue]:
    issues: list[Issue] = []
    row_contract_number = normalize_contract_number(row.contract_number)
    if not row_contract_number:
        return [Issue(IssueSeverity.MANUAL_REVIEW, f"模組表項目「{row.product_name}」缺少合同單號，請人工確認。")]

    matching_contracts = [
        contract
        for contract in contracts
        if contract_numbers_match(contract.contract_number, row.contract_number)
    ]
    if not matching_contracts:
        if _has_reliable_contract(contracts):
            issues.append(Issue(IssueSeverity.HARD_BLOCK, f"模組表合同單號 {row.contract_number} 找不到對應合同。"))
        else:
            issues.append(Issue(IssueSeverity.MANUAL_REVIEW, f"模組表合同單號 {row.contract_number} 無法在合同中確認(合同為掃描件,OCR 可能讀取不全),請人工核對。"))
        return issues
    if len(matching_contracts) > 1:
        issues.append(Issue(IssueSeverity.MANUAL_REVIEW, f"合同單號 {row.contract_number} 對應多份合同，請人工確認應使用哪一份。"))
        return issues

    contract = matching_contracts[0]
    if contract.number_inferred:
        # Identity was inferred by elimination; the contract itself is an unread OCR scan.
        # Comparing its garbled buyer/items/prices would conjure false issues — defer to a
        # transcript instead of comparing.
        return [
            Issue(
                IssueSeverity.MANUAL_REVIEW,
                f"模組表合同單號 {row.contract_number} 對應的合同為掃描件(合同號由消去法推得，內容待 transcribe)，無法逐項核對。",
            )
        ]
    if not normalize_company(row.purchasing_company):
        issues.append(Issue(IssueSeverity.MANUAL_REVIEW, f"模組表合同單號 {row.contract_number} 缺少採購公司，請人工確認。"))
    elif not normalize_company(contract.buyer_name):
        issues.append(Issue(IssueSeverity.MANUAL_REVIEW, f"合同 {contract.source_file} 缺少買方名稱，請人工確認。"))
    elif normalize_company(row.purchasing_company) != normalize_company(contract.buyer_name):
        issues.append(Issue(IssueSeverity.HARD_BLOCK, f"模組表合同單號 {row.contract_number} 的採購公司與合同買方不一致。"))

    same_contract_items = [
        item for item in contract.items
        if products_match(row.code, row.product_name, row.model, item.code, item.name, item.model)
    ]
    if not same_contract_items:
        other_contract = _find_product_in_other_contract(row, contracts, contract.contract_number)
        if other_contract:
            issues.append(
                Issue(
                    IssueSeverity.MANUAL_REVIEW,
                    f"模組表合同單號 {row.contract_number} 的「{row.product_name}」未在對應合同中找到，但出現在其他合同 {other_contract.contract_number}，請確認合同單號是否填錯。",
                )
            )
        else:
            issues.append(
                Issue(IssueSeverity.MANUAL_REVIEW, f"模組表合同單號 {row.contract_number} 的「{row.product_name}」未在對應合同中找到。")
            )
        return issues

    if len(same_contract_items) > 1:
        # The same product may be listed at several pricing tiers; the module row's
        # unit price disambiguates. Only fall back to manual review when the price
        # doesn't single out exactly one line.
        row_price = normalize_money(row.unit_price)
        price_matches = [
            item for item in same_contract_items
            if row_price is not None and normalize_money(item.unit_price) == row_price
        ]
        if len(price_matches) == 1:
            same_contract_items = price_matches
        else:
            issues.append(
                Issue(
                    IssueSeverity.MANUAL_REVIEW,
                    f"合同 {contract.contract_number} 中「{row.product_name}」有多筆相同產品，請人工確認應對應哪一筆單價。",
                )
            )
            return issues

    contract_item = same_contract_items[0]
    issues.extend(_compare_module_row_to_contract_item(row, contract_item))
    if normalize_money(row.unit_price) != normalize_money(contract_item.unit_price):
        issues.append(
            Issue(
                IssueSeverity.MANUAL_REVIEW,
                f"模組表合同單號 {row.contract_number} 的「{row.product_name}」單價不一致：模組表 {row.unit_price}，合同 {contract_item.unit_price}。",
            )
        )

    return issues


def _compare_module_group_to_shipment_items(rows: Sequence[ModuleRow], items: Sequence[ShipmentItem]) -> list[Issue]:
    issues: list[Issue] = []
    first_row = rows[0]
    row_units = {normalize_text(row.unit) for row in rows if normalize_text(row.unit)}
    item_units = {normalize_text(item.unit) for item in items if normalize_text(item.unit)}
    if len(row_units) > 1:
        issues.append(
            Issue(
                IssueSeverity.MANUAL_REVIEW,
                f"模組表項目「{first_row.product_name}」有多種單位，請人工確認。",
            )
        )
    if len(item_units) > 1:
        issues.append(
            Issue(
                IssueSeverity.MANUAL_REVIEW,
                f"出貨審批項目「{first_row.product_name}」有多種單位，請人工確認。",
            )
        )
    if row_units and item_units and not _unit_sets_compatible(row_units, item_units):
        issues.append(
            Issue(
                IssueSeverity.MANUAL_REVIEW,
                f"模組表項目「{first_row.product_name}」與出貨審批單位不一致：模組表 {_join_units(row_units)}，出貨審批 {_join_units(item_units)}。",
            )
        )

    row_quantity = _sum_known_quantities(row.quantity for row in rows)
    item_quantity = _sum_known_quantities(item.quantity for item in items)
    if row_quantity is not None and item_quantity is not None and row_quantity != item_quantity:
        issues.append(
            Issue(
                IssueSeverity.MANUAL_REVIEW,
                f"模組表項目「{first_row.product_name}」與出貨審批數量不一致：模組表 {row_quantity}，出貨審批 {item_quantity}。",
            )
        )
    return issues


def _compare_module_row_to_contract_item(row: ModuleRow, item: ContractItem) -> list[Issue]:
    issues: list[Issue] = []
    # The contract quantity is the master-order ceiling; this shipment may deliver a
    # part of it. Only an over-shipment (more than contracted) is a real problem.
    if row.quantity is not None and item.quantity is not None and row.quantity > item.quantity:
        issues.append(
            Issue(
                IssueSeverity.MANUAL_REVIEW,
                f"模組表合同單號 {row.contract_number} 的「{row.product_name}」出貨數量 {row.quantity} 超過合同數量 {item.quantity}，請人工確認。",
            )
        )
    if not units_compatible(row.unit, item.unit):
        issues.append(
            Issue(
                IssueSeverity.MANUAL_REVIEW,
                f"模組表合同單號 {row.contract_number} 的「{row.product_name}」單位不一致：模組表 {row.unit}，合同 {item.unit}。",
            )
        )
    return issues


def _sum_known_quantities(values) -> float | None:
    total = 0.0
    for value in values:
        if value is None:
            return None
        total += value
    return total


def _unit_sets_compatible(row_units: set[str], item_units: set[str]) -> bool:
    """Each unit on each side must be compatible with some unit on the other —
    tolerant of OCR-merged/dropped units but strict on a genuine mismatch."""
    return all(any(units_compatible(r, i) for i in item_units) for r in row_units) and all(
        any(units_compatible(r, i) for r in row_units) for i in item_units
    )


def _join_units(units: set[str]) -> str:
    return "、".join(sorted(units))


def _find_product_in_other_contract(
    row: ModuleRow,
    contracts: Sequence[Contract],
    stated_contract_number: str | None,
) -> Contract | None:
    for contract in contracts:
        if contract.contract_number == stated_contract_number:
            continue
        if any(products_match(row.code, row.product_name, row.model, item.code, item.name, item.model) for item in contract.items):
            return contract
    return None


def _unmatched(numbers: set[str], others: set[str]) -> list[str]:
    return sorted(
        number
        for number in numbers
        if not any(contract_numbers_match(number, other) for other in others)
    )


def module_rows_matching_nothing(case: CaseData) -> list[ModuleRow]:
    """Module rows whose product matches NOTHING real — not in any contract's items and not
    in the approval's actual_items. The signature of a name-OCR garble (e.g. AI教研中心→A教研
    中心). Detector-only (feeds --ocr-gaps), deliberately NARROWER than the engine's
    per-contract-number 查無此項, and never wired into the verdict path."""
    contract_items = [it for c in case.contracts for it in c.items]
    approval_items = list(case.approval.actual_items) if case.approval else []
    unmatched: list[ModuleRow] = []
    for row in case.module_rows:
        in_contract = any(
            products_match(row.code, row.product_name, row.model, it.code, it.name, it.model)
            for it in contract_items
        )
        in_approval = any(
            products_match(row.code, row.product_name, row.model, it.code, it.name, it.model)
            for it in approval_items
        )
        if not in_contract and not in_approval:
            unmatched.append(row)
    return unmatched
