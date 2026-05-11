from pathlib import Path

from kwb.core.roadmap import (
    FeatureEntry,
    build_improvement_proposals,
    parse_function_catalog,
    render_proposals_markdown,
)
from kwb.cli import main


FIXTURE_CATALOG = Path("tests/fixtures/roadmap_small_catalog.md")


def test_parse_function_catalog_reads_known_feature():
    entries = parse_function_catalog("docs/FUNKTIONSKATALOG.md")
    feature_ids = {entry.feature_id for entry in entries}
    # F37 PDF-Import remains a stable "Geplant" reference point
    assert "F37" in feature_ids
    f37 = next(e for e in entries if e.feature_id == "F37")
    assert f37.status == "Geplant"
    assert f37.tests_done == 0
    assert f37.tests_total == 0


def test_proposals_prioritize_unimplemented_features():
    entries = [
        e
        for e in parse_function_catalog(FIXTURE_CATALOG)
        if e.feature_id in {"F10", "F12", "F11", "F09", "F13"}
    ]
    proposals = build_improvement_proposals(entries, top_n=4)

    assert [p.feature_id for p in proposals] == ["F10", "F12", "F11", "F09"]
    assert [p.priority for p in proposals] == [140, 125, 100, 85]


def test_proposals_are_deterministic_for_equal_priorities():
    entries = [e for e in parse_function_catalog(FIXTURE_CATALOG) if e.feature_id in {"F20", "F21", "F22"}]

    first = build_improvement_proposals(entries, top_n=3)
    second = build_improvement_proposals(entries, top_n=3)

    assert [p.feature_id for p in first] == ["F22", "F21", "F20"]
    assert [p.feature_id for p in second] == ["F22", "F21", "F20"]


def test_parse_function_catalog_handles_invalid_tests_cell_as_zero_zero():
    entries = parse_function_catalog(FIXTURE_CATALOG)

    malformed = next(e for e in entries if e.feature_id == "F30")

    assert malformed.tests_done == 0
    assert malformed.tests_total == 0

    proposal = next(p for p in build_improvement_proposals(entries, top_n=8) if p.feature_id == "F30")
    assert "0/0 Tests" in proposal.rationale


def test_render_proposals_markdown_contains_sections():
    entries = parse_function_catalog(FIXTURE_CATALOG)
    proposals = build_improvement_proposals(entries, top_n=2)
    md = render_proposals_markdown(proposals)

    assert md.startswith("# Konkrete Entwicklungsvorschläge")
    assert "**Nächste Schritte:**" in md
    assert "**Akzeptanzkriterien:**" in md

    sections = [s for s in md.split("\n## ")[1:] if s.strip()]
    assert len(sections) == 2
    for section in sections:
        assert " — " in section
        assert "**Begründung:**" in section
        action_lines = section.split("**Nächste Schritte:**", 1)[1].split("**Akzeptanzkriterien:**", 1)[0]
        acceptance_lines = section.split("**Akzeptanzkriterien:**", 1)[1]
        assert action_lines.count("\n-") >= 3
        assert acceptance_lines.count("\n-") >= 3


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


def test_proposals_include_implemented_features_with_test_gaps():
    entries = [
        FeatureEntry(
            category="Core",
            feature_id="F01",
            title="Geplantes Feature",
            status="Geplant",
            tests_done=0,
            tests_total=0,
            module="core.py",
            note="",
        ),
        FeatureEntry(
            category="Core",
            feature_id="F02",
            title="Umgesetztes Feature mit Testlücke",
            status="Umgesetzt",
            tests_done=0,
            tests_total=1,
            module="core.py",
            note="",
        ),
    ]

    proposals = build_improvement_proposals(entries, top_n=5)

    proposal_ids = [p.feature_id for p in proposals]
    assert "F02" in proposal_ids

    planned = next(p for p in proposals if p.feature_id == "F01")
    implemented_gap = next(p for p in proposals if p.feature_id == "F02")

    assert planned.priority > implemented_gap.priority
    assert "Status 'Umgesetzt'" in implemented_gap.rationale
    assert "0/1 Tests" in implemented_gap.rationale
