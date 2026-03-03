"""CLI entry point for the Kuratierwerkbank."""
from __future__ import annotations
import argparse, sys
from pathlib import Path

from kwb.ingest.csv_loader import ingest_csv
from kwb.analyze.structural import analyze_datasets
from kwb.report.markdown import render_report
from kwb.core.roadmap import (
    build_improvement_proposals,
    parse_function_catalog,
    render_proposals_markdown,
)


def cmd_analyze(args):
    datasets = []
    for csv_path in args.files:
        path = Path(csv_path)
        if not path.exists():
            print(f"ERROR: File not found: {path}", file=sys.stderr)
            return 1
        print(f"📂 Ingesting: {path.name} …")
        df, profile = ingest_csv(path)
        print(f"   → {profile.row_count:,} rows, {profile.column_count} columns, ID: {profile.id_column}")
        datasets.append((df, profile))
    print(f"\n🔍 Running {len(datasets)} dataset(s) through structural analysis …")
    report = analyze_datasets(datasets)
    s = report.summary
    print(f"\n📊 Results: {s['critical']} critical, {s['warnings']} warnings, {s['info']} info")
    md = render_report(report)
    if args.output:
        out_path = Path(args.output)
        out_path.write_text(md, encoding="utf-8")
        print(f"\n✅ Report written to: {out_path}")
    else:
        print("\n" + "=" * 60)
        print(md)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="kwb",
        description="Kuratierwerkbank — AI-assisted curation workbench for GLAM data")
    subparsers = parser.add_subparsers(dest="command")

    p_analyze = subparsers.add_parser("analyze", help="Run structural quality analysis")
    p_analyze.add_argument("files", nargs="+", help="CSV files to analyze")
    p_analyze.add_argument("-o", "--output", help="Output path for Markdown report")
    p_analyze.set_defaults(func=cmd_analyze)

    p_plan = subparsers.add_parser(
        "plan",
        help="Generate prioritized development proposals from FUNKTIONSKATALOG",
    )
    p_plan.add_argument(
        "--catalog",
        default="docs/FUNKTIONSKATALOG.md",
        help="Path to FUNKTIONSKATALOG markdown file",
    )
    p_plan.add_argument("--top", type=int, default=6, help="Number of proposals")

    def _cmd_plan(args: argparse.Namespace) -> int:
        entries = parse_function_catalog(args.catalog)
        proposals = build_improvement_proposals(entries, top_n=args.top)
        output = render_proposals_markdown(proposals)
        print(output)
        return 0

    p_plan.set_defaults(func=_cmd_plan)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
