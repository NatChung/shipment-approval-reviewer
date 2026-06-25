"""Machine-readable JSON of a ReportData, for an orchestration layer to consume."""
from __future__ import annotations

from shipment_review.models import Issue
from shipment_review.report import ReportData


def _issue(issue: Issue) -> dict:
    return {"severity": issue.severity.value, "message": issue.message, "unverified": issue.unverified}


def verdict_json(report: ReportData) -> dict:
    return {
        "status": report.result.title,
        "violations": [_issue(i) for i in report.violations],
        "needs_review": [_issue(i) for i in report.unverified],
        "confirmed_checks": list(report.confirmed),
        "ai_unconfirmed_contracts": list(report.ai_unconfirmed_contracts),
    }
