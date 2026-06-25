from __future__ import annotations

from shipment_review.models import Issue, ReviewResult


def violation_issues(result: ReviewResult) -> list[Issue]:
    """❌ tier — proven violations."""
    return [issue for issue in result.issues if ReviewResult.is_violation(issue)]


def unverified_issues(result: ReviewResult) -> list[Issue]:
    """⚠️ tier — could-not-verify items the reviewer must confirm."""
    return [issue for issue in result.issues if not ReviewResult.is_violation(issue)]


def confirmed_checks(result: ReviewResult) -> list[str]:
    """✅ tier — standing checks that no issue contradicts."""
    return [check for check in result.checks if not _check_contradicted(check, result.issues)]


def format_result(result: ReviewResult) -> str:
    """Render the verdict in three tiers: ❌ 違規 / ⚠️ 待人工核實 / ✅ 已確認.

    A proven violation (❌) blocks; could-not-verify items (⚠️) are what the reviewer
    must confirm; ✅ lists the standing checks no issue contradicts.
    """
    lines = [f"審核結果：{result.title}", ""]

    violations = violation_issues(result)
    unverified = unverified_issues(result)
    confirmed = confirmed_checks(result)

    if violations:
        lines.append("❌ 違規事項：")
        lines.extend(f"{i}. {issue.message}" for i, issue in enumerate(violations, start=1))
        lines.append("")
    if unverified:
        lines.append("⚠️ 待人工核實：")
        lines.extend(f"{i}. {issue.message}" for i, issue in enumerate(unverified, start=1))
        lines.append("")
    if confirmed:
        lines.append("✅ 已確認：")
        lines.extend(f"- {check}" for check in confirmed)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _check_contradicted(check: str, issues: list[Issue]) -> bool:
    """A standing check is contradicted (so NOT shown as ✅) when an issue covers its area."""
    messages = [issue.message for issue in issues]
    if check == "模組表合同單號均可對應合同":
        markers = ("找不到", "未能", "無法", "未出現", "對應多份", "未在對應")
        return any(("合同單號" in m or "對應合同" in m) and any(k in m for k in markers) for m in messages)
    if check == "出貨項目均可在合同中找到":
        return any("出貨項目" in m and ("未在" in m or "無法在" in m) for m in messages)
    if check == "模組表單價與合同單價一致":
        return any("單價不一致" in m for m in messages)
    return False
