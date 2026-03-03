"""Roadmap parsing and proposal generation based on the development catalog."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FeatureEntry:
    category: str
    feature_id: str
    title: str
    status: str
    tests_done: int
    tests_total: int
    module: str
    note: str


@dataclass(frozen=True)
class ImprovementProposal:
    feature_id: str
    title: str
    priority: int
    rationale: str
    actions: list[str]
    acceptance_criteria: list[str]


def _parse_tests(cell: str) -> tuple[int, int]:
    text = cell.strip()
    if not text or text == "—":
        return 0, 0
    if "/" not in text:
        return 0, 0
    done, total = text.split("/", 1)
    return int(done.strip()), int(total.strip())


def _clean_status(status_cell: str) -> str:
    return status_cell.replace("✅", "").replace("🟡", "").replace("🔴", "").strip()


def parse_function_catalog(path: str | Path) -> list[FeatureEntry]:
    """Parse docs/FUNKTIONSKATALOG.md feature tables into FeatureEntry objects."""
    catalog_path = Path(path)
    lines = catalog_path.read_text(encoding="utf-8").splitlines()

    current_category = ""
    entries: list[FeatureEntry] = []

    for line in lines:
        if line.startswith("## "):
            heading = line.lstrip("# ").strip()
            if "—" in heading:
                current_category = heading.split("—", 1)[1].strip()
            else:
                current_category = heading.split(".", 1)[-1].strip()
            continue

        if not line.startswith("|"):
            continue

        cells = [c.strip() for c in line.strip().split("|")[1:-1]]
        if len(cells) < 6:
            continue
        if cells[0] == "ID" or cells[0].startswith("----"):
            continue

        tests_done, tests_total = _parse_tests(cells[3])
        note = cells[6] if len(cells) > 6 else ""

        entries.append(
            FeatureEntry(
                category=current_category,
                feature_id=cells[0],
                title=cells[1],
                status=_clean_status(cells[2]),
                tests_done=tests_done,
                tests_total=tests_total,
                module=cells[4],
                note=note,
            )
        )

    return entries


def _priority(entry: FeatureEntry) -> int:
    score = 0
    if entry.status.lower().startswith("geplant"):
        score += 100
    elif entry.status.lower().startswith("teilweise"):
        score += 60

    if entry.tests_total == 0:
        score += 30
    elif entry.tests_done < entry.tests_total:
        score += 15

    critical_domains = ("ingest", "export", "enrichment", "infrastruktur")
    if any(d in entry.category.lower() for d in critical_domains):
        score += 10

    return score


def build_improvement_proposals(entries: list[FeatureEntry], top_n: int = 6) -> list[ImprovementProposal]:
    """Build prioritized, concrete improvement proposals from catalog entries."""
    candidates = [e for e in entries if e.status != "Umgesetzt"]
    ranked = sorted(candidates, key=lambda e: (_priority(e), e.feature_id), reverse=True)

    proposals: list[ImprovementProposal] = []
    for entry in ranked[:top_n]:
        actions = [
            f"Implementiere Kernfunktion für {entry.title} im Modul {entry.module}.",
            "Ergänze API/CLI-Zugriff mit klaren Parametern und validierten Fehlerfällen.",
            "Dokumentiere Datenflüsse, Limits und Beispiel-Workflows im Funktionskatalog.",
        ]
        acceptance = [
            "Mindestens ein End-to-End-Test deckt den Standardpfad ab.",
            "Fehlerfälle (leere Inputs, Zeitüberschreitung, fehlerhafte Datensätze) sind getestet.",
            "Feature ist im Dashboard oder in der CLI ausführbar und dokumentiert.",
        ]
        rationale = (
            f"Status '{entry.status}' bei {entry.tests_done}/{entry.tests_total} Tests. "
            f"Diese Lücke blockiert Reifegrad und produktiven Einsatz in '{entry.category}'."
        )
        proposals.append(
            ImprovementProposal(
                feature_id=entry.feature_id,
                title=entry.title,
                priority=_priority(entry),
                rationale=rationale,
                actions=actions,
                acceptance_criteria=acceptance,
            )
        )

    return proposals


def render_proposals_markdown(proposals: list[ImprovementProposal]) -> str:
    """Render proposals in concise markdown for reporting/CLI output."""
    lines = ["# Konkrete Entwicklungsvorschläge", ""]
    for idx, proposal in enumerate(proposals, start=1):
        lines.append(f"## {idx}. {proposal.feature_id} — {proposal.title} (Priorität {proposal.priority})")
        lines.append(f"**Begründung:** {proposal.rationale}")
        lines.append("")
        lines.append("**Nächste Schritte:**")
        for action in proposal.actions:
            lines.append(f"- {action}")
        lines.append("")
        lines.append("**Akzeptanzkriterien:**")
        for criterion in proposal.acceptance_criteria:
            lines.append(f"- {criterion}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"
