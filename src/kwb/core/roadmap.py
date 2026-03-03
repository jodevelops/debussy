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
    for line in lines:
        if line.startswith("## "):
            heading = line.lstrip("# ").strip()
            current_category = heading.split("—", 1)[1].strip() if "—" in heading else heading.split(".", 1)[-1].strip()
            continue
        if not line.startswith("|"): continue
        cells = [c.strip() for c in line.strip().split("|")[1:-1]]
        if len(cells) < 5: continue
        if cells[0] in ("ID","") or cells[0].startswith("----"): continue
        tests_done, tests_total = _parse_tests(cells[3])
        note = cells[6] if len(cells) > 6 else ""
        entries.append(FeatureEntry(
            category=current_category, feature_id=cells[0], title=cells[1],
            status=_clean_status(cells[2]), tests_done=tests_done, tests_total=tests_total,
            module=cells[4], note=note,
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
