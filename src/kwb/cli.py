"""
CLI entry point for the Kuratierwerkbank.

Usage:
    python -m kwb.cli analyze data/file1.csv data/file2.csv --output report.md
    kwb analyze data/file1.csv data/file2.csv --output report.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kwb.ingest.csv_loader import ingest_csv
from kwb.analyze.structural import analyze_datasets
from kwb.report.markdown import render_report


def cmd_analyze(args: argparse.Namespace) -> int:
    """Run structural analysis on one or more CSV files."""
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

    # Generate report
    md = render_report(report)

    if args.output:
        out_path = Path(args.output)
        out_path.write_text(md, encoding="utf-8")
        print(f"\n✅ Report written to: {out_path}")
    else:
        print("\n" + "=" * 60)
        print(md)

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kwb",
        description="Kuratierwerkbank — AI-assisted curation workbench for GLAM data",
    )
    subparsers = parser.add_subparsers(dest="command")

    # analyze subcommand
    p_analyze = subparsers.add_parser("analyze", help="Run structural quality analysis")
    p_analyze.add_argument("files", nargs="+", help="CSV files to analyze")
    p_analyze.add_argument("-o", "--output", help="Output path for Markdown report")
    p_analyze.set_defaults(func=cmd_analyze)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
