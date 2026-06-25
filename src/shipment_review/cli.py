from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from shipment_review.extractors.ocr_gaps import collect_ocr_gaps
from shipment_review.html_report import render_html
from shipment_review.json_report import verdict_json
from shipment_review.models import UnverifiedPolicy
from shipment_review.report import build_report
from shipment_review.text_report import format_report_text


def run(case_dir: Path | str, unverified_policy: UnverifiedPolicy = UnverifiedPolicy.MANUAL) -> str:
    return format_report_text(build_report(case_dir, unverified_policy))


def run_html(
    case_dir: Path | str,
    out_path: Path,
    unverified_policy: UnverifiedPolicy = UnverifiedPolicy.MANUAL,
) -> str:
    """Write an offline HTML review page for the case; return a one-line confirmation."""
    report = build_report(case_dir, unverified_policy)
    out_path.write_text(render_html(report), encoding="utf-8")
    return f"已輸出審核頁：{out_path}（{report.result.title}）\n"


def run_ocr_gaps(case_dir: Path | str, as_json: bool = False) -> str:
    """List contracts that need an authored transcript because OCR could not read them.
    One ``path<TAB>reason`` line per gap, so an agent can act on it directly."""
    gaps = collect_ocr_gaps(case_dir)
    if as_json:
        return json.dumps(
            [{"file": g.file, "reason": g.reason, "sha256": g.sha256, "kind": g.kind} for g in gaps],
            ensure_ascii=False,
        ) + "\n"
    if not gaps:
        return "無 OCR 缺口：所有合同均可讀，或已有 transcript。\n"
    return "\n".join(f"{gap.file}\t{gap.reason}" for gap in gaps) + "\n"


def main(argv: list[str] | None = None) -> int:
    # The verdict mixes Traditional and Simplified Chinese; on Windows a console
    # or redirected stdout defaults to the legacy code page (cp1252/cp950/cp936)
    # and would raise UnicodeEncodeError. Force UTF-8 so output is portable.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Review a shipment approval case folder.")
    parser.add_argument("case_dir", type=Path)
    parser.add_argument(
        "--ocr-gaps",
        action="store_true",
        help="List contracts whose OCR is too weak to review (need a transcript) instead of judging.",
    )
    parser.add_argument(
        "--unverified",
        choices=("manual", "block"),
        default="manual",
        help="How ⚠️ could-not-verify items map to the verdict: manual=需人工確認 (default, "
        "focused-manual), block=不可出貨 (fail-closed).",
    )
    parser.add_argument(
        "--html",
        type=Path,
        metavar="PATH",
        help="Write an offline HTML review page (❌/⚠️/✅ + 放行/駁回 + 原文) to PATH instead of text.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON instead of text.")
    args = parser.parse_args(argv)
    policy = UnverifiedPolicy.BLOCK if args.unverified == "block" else UnverifiedPolicy.MANUAL
    if args.ocr_gaps:
        output = run_ocr_gaps(args.case_dir, as_json=args.json)
    elif args.json:
        output = json.dumps(verdict_json(build_report(args.case_dir, policy)), ensure_ascii=False, indent=2) + "\n"
    elif args.html is not None:
        output = run_html(args.case_dir, args.html, policy)
    else:
        output = run(args.case_dir, policy)
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
