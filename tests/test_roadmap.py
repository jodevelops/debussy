from pathlib import Path

from kwb.core.roadmap import (
    build_improvement_proposals,
    parse_function_catalog,
    render_proposals_markdown,
)
from kwb.cli import main


def test_parse_function_catalog_reads_known_feature():
    entries = parse_function_catalog("docs/FUNKTIONSKATALOG.md")
    feature_ids = {entry.feature_id for entry in entries}
    assert "F31" in feature_ids
    f31 = next(e for e in entries if e.feature_id == "F31")
    assert f31.status == "Geplant"
    assert f31.tests_done == 0
    assert f31.tests_total == 0


def test_proposals_prioritize_unimplemented_features():
    entries = parse_function_catalog("docs/FUNKTIONSKATALOG.md")
    proposals = build_improvement_proposals(entries, top_n=5)

    assert len(proposals) == 5
    assert all(p.priority >= 100 for p in proposals)
    assert all("Status" in p.rationale for p in proposals)


def test_render_proposals_markdown_contains_sections():
    entries = parse_function_catalog("docs/FUNKTIONSKATALOG.md")
    proposals = build_improvement_proposals(entries, top_n=2)
    md = render_proposals_markdown(proposals)

    assert md.startswith("# Konkrete Entwicklungsvorschläge")
    assert "**Nächste Schritte:**" in md
    assert "**Akzeptanzkriterien:**" in md


def test_cli_plan_command_outputs_recommendations(capsys):
    rc = main(["plan", "--catalog", "docs/FUNKTIONSKATALOG.md", "--top", "3"])
    captured = capsys.readouterr()

    assert rc == 0
    assert "Konkrete Entwicklungsvorschläge" in captured.out
    assert "Priorität" in captured.out


def test_parse_function_catalog_on_custom_file(tmp_path: Path):
    file = tmp_path / "catalog.md"
    file.write_text(
        "\n".join(
            [
                "## 1. Demo",
                "| ID | Funktion | Status | Tests | Modul | Hinweis |",
                "|----|----------|--------|-------|-------|---------|",
                "| F99 | Beispiel | 🟡 Teilweise | 1/2 | `demo.py` | Noch offen |",
            ]
        ),
        encoding="utf-8",
    )

    entries = parse_function_catalog(file)
    assert len(entries) == 1
    assert entries[0].feature_id == "F99"
    assert entries[0].tests_done == 1
    assert entries[0].tests_total == 2
