"""Roadmap parsing and proposal generation from FUNKTIONSKATALOG.md."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FeatureEntry:
    category: str; feature_id: str; title: str; status: str
    tests_done: int; tests_total: int; module: str; note: str


@dataclass(frozen=True)
class ImprovementProposal:
    feature_id: str; title: str; priority: int
    rationale: str; actions: list[str]; acceptance_criteria: list[str]


def _parse_tests(cell):
    text = cell.strip()
    if not text or text == "—" or "/" not in text: return 0, 0
    done, total = text.split("/", 1)
    try: return int(done.strip()), int(total.strip())
    except: return 0, 0

def _clean_status(s):
    return s.replace("✅","").replace("🟡","").replace("🔴","").strip()


def parse_function_catalog(path):
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    current_category, entries = "", []
    header_to_index = None

    def _is_separator_row(row_cells):
        return all(set(cell.replace(":", "")) <= {"-"} for cell in row_cells if cell)

    def _build_header_map(row_cells):
        normalized = [cell.strip().lower() for cell in row_cells]
        required = {"id", "funktion", "status", "tests"}
        if not required.issubset(set(normalized)):
            return None
        return {name: idx for idx, name in enumerate(normalized)}

    for line in lines:
        if line.startswith("## "):
            heading = line.lstrip("# ").strip()
            current_category = heading.split("—", 1)[1].strip() if "—" in heading else heading.split(".", 1)[-1].strip()
            header_to_index = None
            continue

        if not line.startswith("|"):
            header_to_index = None
            continue

        cells = [c.strip() for c in line.strip().split("|")[1:-1]]

        maybe_header = _build_header_map(cells)
        if maybe_header is not None:
            header_to_index = maybe_header
            continue

        if _is_separator_row(cells) or not header_to_index:
            continue

        def _cell(name):
            idx = header_to_index.get(name)
            return cells[idx] if idx is not None and idx < len(cells) else ""

        feature_id = _cell("id")
        if not feature_id:
            continue

        tests_done, tests_total = _parse_tests(_cell("tests"))
        entries.append(FeatureEntry(
            category=current_category,
            feature_id=feature_id,
            title=_cell("funktion"),
            status=_clean_status(_cell("status")),
            tests_done=tests_done,
            tests_total=tests_total,
            module=_cell("modul"),
            note=_cell("hinweis"),
        ))
    return entries


def _priority(e):
    score = 0
    if e.status.lower().startswith("geplant"): score += 100
    elif e.status.lower().startswith("teilweise"): score += 60
    if e.tests_total == 0: score += 30
    elif e.tests_done < e.tests_total: score += 15
    if any(d in e.category.lower() for d in ("ingest","export","enrichment","infrastruktur")): score += 10
    return score


def build_improvement_proposals(entries, top_n=6):
    candidates = [e for e in entries if e.status != "Umgesetzt"]
    ranked = sorted(candidates, key=lambda e: (_priority(e), e.feature_id), reverse=True)
    proposals = []
    for entry in ranked[:top_n]:
        proposals.append(ImprovementProposal(
            feature_id=entry.feature_id, title=entry.title, priority=_priority(entry),
            rationale=f"Status '{entry.status}' bei {entry.tests_done}/{entry.tests_total} Tests. Diese Lücke blockiert Reifegrad und produktiven Einsatz in '{entry.category}'.",
            actions=[
                f"Implementiere Kernfunktion für {entry.title} im Modul {entry.module}.",
                "Ergänze API/CLI-Zugriff mit klaren Parametern und validierten Fehlerfällen.",
                "Dokumentiere Datenflüsse, Limits und Beispiel-Workflows im Funktionskatalog.",
            ],
            acceptance_criteria=[
                "Mindestens ein End-to-End-Test deckt den Standardpfad ab.",
                "Fehlerfälle (leere Inputs, Zeitüberschreitung, fehlerhafte Datensätze) sind getestet.",
                "Feature ist im Dashboard oder in der CLI ausführbar und dokumentiert.",
            ],
        ))
    return proposals


def render_proposals_markdown(proposals):
    lines = ["# Konkrete Entwicklungsvorschläge", ""]
    for idx, p in enumerate(proposals, 1):
        lines.append(f"## {idx}. {p.feature_id} — {p.title} (Priorität {p.priority})")
        lines.append(f"**Begründung:** {p.rationale}")
        lines.append("")
        lines.append("**Nächste Schritte:**")
        for a in p.actions: lines.append(f"- {a}")
        lines.append("")
        lines.append("**Akzeptanzkriterien:**")
        for c in p.acceptance_criteria: lines.append(f"- {c}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"
