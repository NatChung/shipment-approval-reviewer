from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping, Sequence


class ReviewStatus(Enum):
    APPROVED = "可出貨"
    BLOCKED = "不可出貨"
    MANUAL_REVIEW = "需人工確認"


class IssueSeverity(Enum):
    HARD_BLOCK = "hard_block"
    MANUAL_REVIEW = "manual_review"


class UnverifiedPolicy(Enum):
    """How the ⚠️ "could-not-verify" tier maps to the final verdict.

    MANUAL (default, focused-manual): unverified-only → 需人工確認 — the reviewer is
    handed only the items that genuinely could not be confirmed.
    BLOCK (fail-closed): unverified-only → 不可出貨, overridden manually.
    """

    MANUAL = "manual"
    BLOCK = "block"


class FrozenDict(dict[str, str]):
    def __init__(self, values: Mapping[str, str] | Iterable[tuple[str, str]] = ()) -> None:
        dict.__init__(self, values)

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> "FrozenDict":
        return cls(dict(values))

    def __copy__(self) -> "FrozenDict":
        return FrozenDict(self)

    def __deepcopy__(self, memo: dict[int, object]) -> "FrozenDict":
        copied = FrozenDict(self)
        memo[id(self)] = copied
        return copied

    def __setitem__(self, key: str, value: str) -> None:
        raise TypeError("FrozenDict is immutable")

    def __delitem__(self, key: str) -> None:
        raise TypeError("FrozenDict is immutable")

    def clear(self) -> None:
        raise TypeError("FrozenDict is immutable")

    def pop(self, key: str, default: object = None) -> str:
        raise TypeError("FrozenDict is immutable")

    def popitem(self) -> tuple[str, str]:
        raise TypeError("FrozenDict is immutable")

    def setdefault(self, key: str, default: str = "") -> str:
        raise TypeError("FrozenDict is immutable")

    def update(self, *args: object, **kwargs: str) -> None:
        raise TypeError("FrozenDict is immutable")

    def __ior__(self, other: object) -> "FrozenDict":
        raise TypeError("FrozenDict is immutable")


@dataclass(frozen=True)
class Issue:
    severity: IssueSeverity
    message: str
    # ⚠️ "could-not-verify" (missing/unreadable input) rather than a proven ❌ violation.
    # MANUAL_REVIEW issues are always ⚠️; a HARD_BLOCK is ⚠️ only when this is set
    # (e.g. a missing module table) — otherwise a HARD_BLOCK is a ❌ violation.
    unverified: bool = False


@dataclass(frozen=True)
class ShipmentItem:
    code: str | None
    name: str
    model: str | None
    unit: str | None
    quantity: float | None
    source: str


@dataclass(frozen=True)
class Approval:
    source_file: str
    approval_code: str | None
    contract_numbers: Sequence[str]
    shipment_companies: Sequence[str]
    school_name: str | None
    actual_items: Sequence[ShipmentItem]
    approver_statuses: Mapping[str, str]
    shipment_amount: float | None = None
    attached_contract_files: Sequence[str] = field(default_factory=tuple)
    original_field_items: Sequence[ShipmentItem] = field(default_factory=tuple)
    comment_items: Sequence[ShipmentItem] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "contract_numbers", tuple(self.contract_numbers))
        object.__setattr__(self, "shipment_companies", tuple(self.shipment_companies))
        object.__setattr__(self, "actual_items", tuple(self.actual_items))
        object.__setattr__(self, "approver_statuses", FrozenDict.from_mapping(self.approver_statuses))
        object.__setattr__(self, "attached_contract_files", tuple(self.attached_contract_files))
        object.__setattr__(self, "original_field_items", tuple(self.original_field_items))
        object.__setattr__(self, "comment_items", tuple(self.comment_items))


@dataclass(frozen=True)
class ContractItem:
    name: str
    model: str | None
    unit: str | None
    quantity: float | None
    unit_price: float | None
    code: str | None = None
    amount: float | None = None


@dataclass(frozen=True)
class Contract:
    source_file: str
    contract_number: str | None
    buyer_name: str | None
    seller_name: str | None
    school_name: str | None
    items: Sequence[ContractItem]
    readable: bool
    school_names: list[str] = field(default_factory=list)
    ocr_extracted: bool = False
    ai_unconfirmed: bool = False
    number_inferred: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))
        object.__setattr__(self, "school_names", tuple(self.school_names))


@dataclass(frozen=True)
class ModuleRow:
    source_file: str
    contract_number: str | None
    purchasing_company: str | None
    product_name: str
    model: str | None
    unit: str | None
    quantity: float | None
    unit_price: float | None
    amount: float | None
    royalty: float | None
    code: str | None = None


@dataclass(frozen=True)
class CaseData:
    approval: Approval | None
    contracts: Sequence[Contract]
    module_rows: Sequence[ModuleRow]
    expected_contract_files: Sequence[str] = field(default_factory=tuple)
    extraction_issues: Sequence[Issue] = field(default_factory=tuple)
    module_table_present: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "contracts", tuple(self.contracts))
        object.__setattr__(self, "module_rows", tuple(self.module_rows))
        object.__setattr__(self, "expected_contract_files", tuple(self.expected_contract_files))
        object.__setattr__(self, "extraction_issues", tuple(self.extraction_issues))


@dataclass(frozen=True)
class ReviewResult:
    status: ReviewStatus
    issues: Sequence[Issue]
    checks: Sequence[str] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "issues", tuple(self.issues))
        object.__setattr__(self, "checks", tuple(self.checks))

    @property
    def title(self) -> str:
        return self.status.value

    @staticmethod
    def is_violation(issue: "Issue") -> bool:
        """❌ — a proven violation (a HARD_BLOCK not flagged unverified)."""
        return issue.severity is IssueSeverity.HARD_BLOCK and not issue.unverified

    @classmethod
    def from_issues(
        cls,
        issues: Sequence[Issue],
        checks: Sequence[str] | None = None,
        unverified_policy: "UnverifiedPolicy" = UnverifiedPolicy.MANUAL,
    ) -> "ReviewResult":
        copied_issues = tuple(issues)
        has_violation = any(cls.is_violation(issue) for issue in copied_issues)
        if has_violation:
            status = ReviewStatus.BLOCKED  # any ❌ violation blocks regardless of policy
        elif copied_issues:
            # only ⚠️ could-not-verify items remain → policy decides
            status = (
                ReviewStatus.BLOCKED
                if unverified_policy is UnverifiedPolicy.BLOCK
                else ReviewStatus.MANUAL_REVIEW
            )
        else:
            status = ReviewStatus.APPROVED
        return cls(status=status, issues=copied_issues, checks=tuple(checks or ()))
