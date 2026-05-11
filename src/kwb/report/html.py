"""
HTML Report (F42) — Interactive curation overview.

Generates a self-contained HTML document with embedded CSS and JS that
summarizes the entire workspace: dataset profiles, NER entities, EDTF
dates, dictionary entries with authority links, image analyses, and
field mappings.

The output is a single HTML file with no external dependencies — suitable
for archiving, sharing, and offline review.
"""
from __future__ import annotations

import html
from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kwb.core.workspace import Workspace


# Entity type display labels (matches NER taxonomy)
_ENTITY_LABELS = {
    "PER": "Person",
    "ORG": "Organisation",
    "LOC": "Ort",
    "GPE": "Geo-politische Einheit",
    "FAC": "Bauwerk",
    "EVT": "Ereignis",
    "WRK": "Werk",
    "DAT": "Datum",
    "ETH": "Ethnie",
    "CON": "Konzept",
}

# Status color mapping
_STATUS_COLORS = {
    "accepted": "#2ecc71",
    "rejected": "#e74c3c",
    "pending": "#95a5a6",
    "needs_review": "#f39c12",
}

_MUTED_DASH = '<span class="muted">—</span>'


def _esc(value) -> str:
    """HTML-escape a value, handling None gracefully."""
    if value is None:
        return ""
    return html.escape(str(value))


def _authority_link(entry) -> str:
    """Render authority links (GND, Wikidata, GeoNames) as HTML."""
    links = []
    if entry.gnd_id:
        links.append(
            f'<a href="https://d-nb.info/gnd/{_esc(entry.gnd_id)}" '
            f'target="_blank" rel="noopener" class="auth-link gnd">'
            f'GND:{_esc(entry.gnd_id)}</a>'
        )
    if entry.wikidata_id:
        links.append(
            f'<a href="https://www.wikidata.org/wiki/{_esc(entry.wikidata_id)}" '
            f'target="_blank" rel="noopener" class="auth-link wd">'
            f'WD:{_esc(entry.wikidata_id)}</a>'
        )
    if entry.geonames_id:
        links.append(
            f'<a href="https://www.geonames.org/{_esc(entry.geonames_id)}" '
            f'target="_blank" rel="noopener" class="auth-link gn">'
            f'GN:{_esc(entry.geonames_id)}</a>'
        )
    return " ".join(links) if links else '<span class="muted">—</span>'


def _section_overview(workspace: "Workspace") -> str:
    """Render summary statistics section."""
    n_mappings = len(workspace.field_mapping)
    n_dict = len(workspace.dictionary)
    n_entities = len(workspace.entity_reviews)
    n_dates = len(workspace.dates)
    n_images = len(workspace.image_analyses)

    accepted_entities = sum(1 for e in workspace.entity_reviews if e.status.value == "accepted")
    accepted_images = sum(1 for i in workspace.image_analyses if i.review_status.value == "accepted")

    n_with_gnd = sum(1 for e in workspace.dictionary if e.gnd_id)
    n_with_wd = sum(1 for e in workspace.dictionary if e.wikidata_id)

    return f"""
    <section id="overview" class="tab-content active">
        <h2>Übersicht</h2>
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-value">{n_mappings}</div>
                <div class="stat-label">Field-Mappings</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{n_dict}</div>
                <div class="stat-label">Wörterbuch-Einträge</div>
                <div class="stat-sub">{n_with_gnd} mit GND · {n_with_wd} mit Wikidata</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{n_entities}</div>
                <div class="stat-label">NER-Entitäten</div>
                <div class="stat-sub">{accepted_entities} akzeptiert</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{n_dates}</div>
                <div class="stat-label">EDTF-Daten</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{n_images}</div>
                <div class="stat-label">Bildanalysen</div>
                <div class="stat-sub">{accepted_images} akzeptiert</div>
            </div>
        </div>
        <p class="meta">Workspace: <code>{_esc(workspace.name)}</code> ·
        Erstellt: <code>{_esc(workspace.created_at)}</code> ·
        Aktualisiert: <code>{_esc(workspace.updated_at)}</code></p>
    </section>
    """


def _section_entities(workspace: "Workspace") -> str:
    """Render NER entities section with type breakdown."""
    if not workspace.entity_reviews:
        return """
        <section id="entities" class="tab-content">
            <h2>NER-Entitäten</h2>
            <p class="empty">Keine Entitäten erfasst.</p>
        </section>
        """

    # Type breakdown
    type_counts = Counter(e.entity_type for e in workspace.entity_reviews)
    type_bars_html = "".join(
        f'<div class="bar-row">'
        f'<span class="bar-label">{_esc(_ENTITY_LABELS.get(t, t))} ({t})</span>'
        f'<div class="bar"><div class="bar-fill" style="width:{count * 100 // max(type_counts.values())}%"></div></div>'
        f'<span class="bar-count">{count}</span>'
        f'</div>'
        for t, count in type_counts.most_common()
    )

    # Entity rows table
    rows = []
    for er in workspace.entity_reviews:
        status_color = _STATUS_COLORS.get(er.status.value, "#999")
        gnd_html = (
            f'<a href="https://d-nb.info/gnd/{_esc(er.gnd_id)}" '
            f'target="_blank" rel="noopener" class="auth-link gnd">GND:{_esc(er.gnd_id)}</a>'
            if er.gnd_id else '<span class="muted">—</span>'
        )
        rows.append(
            f'<tr data-status="{_esc(er.status.value)}" data-type="{_esc(er.entity_type)}">'
            f'<td><code>{_esc(er.entity_type)}</code></td>'
            f'<td>{_esc(er.text)}</td>'
            f'<td>{_esc(er.gnd_preferred or "")}</td>'
            f'<td>{gnd_html}</td>'
            f'<td><span class="status-badge" style="background:{status_color}">{_esc(er.status.value)}</span></td>'
            f'<td><code class="muted">{_esc(er.record_id or "—")}</code></td>'
            f'<td>{er.confidence:.2f}</td>'
            f'</tr>'
        )

    return f"""
    <section id="entities" class="tab-content">
        <h2>NER-Entitäten</h2>
        <div class="subsection">
            <h3>Verteilung nach Typ</h3>
            <div class="bars">{type_bars_html}</div>
        </div>
        <div class="subsection">
            <h3>Entitäten ({len(workspace.entity_reviews)})</h3>
            <div class="filter-row">
                <label>Status:
                    <select id="entity-status-filter">
                        <option value="">Alle</option>
                        <option value="accepted">Akzeptiert</option>
                        <option value="pending">Offen</option>
                        <option value="rejected">Abgelehnt</option>
                    </select>
                </label>
            </div>
            <table class="data-table" id="entity-table">
                <thead>
                    <tr><th>Typ</th><th>Text</th><th>GND-Bevorzugt</th><th>GND-ID</th><th>Status</th><th>Record</th><th>Konfidenz</th></tr>
                </thead>
                <tbody>{''.join(rows)}</tbody>
            </table>
        </div>
    </section>
    """


def _section_dates(workspace: "Workspace") -> str:
    """Render EDTF dates section."""
    if not workspace.dates:
        return """
        <section id="dates" class="tab-content">
            <h2>EDTF-Daten</h2>
            <p class="empty">Keine Datierungen erfasst.</p>
        </section>
        """

    method_counts = Counter(d.method or d.source or "—" for d in workspace.dates)
    method_summary = ", ".join(f"{m}: {c}" for m, c in method_counts.most_common())

    rows = []
    for cd in workspace.dates:
        rows.append(
            f'<tr>'
            f'<td>{_esc(cd.original)}</td>'
            f'<td><code>{_esc(cd.edtf or "—")}</code></td>'
            f'<td>{cd.confidence:.2f}</td>'
            f'<td><span class="badge">{_esc(cd.method or cd.source or "—")}</span></td>'
            f'<td><code class="muted">{_esc(cd.record_id or "—")}</code></td>'
            f'<td><code class="muted">{_esc(cd.column or "—")}</code></td>'
            f'</tr>'
        )

    return f"""
    <section id="dates" class="tab-content">
        <h2>EDTF-Daten</h2>
        <p class="meta">{_esc(method_summary)}</p>
        <table class="data-table">
            <thead>
                <tr><th>Original</th><th>EDTF</th><th>Konfidenz</th><th>Methode</th><th>Record</th><th>Spalte</th></tr>
            </thead>
            <tbody>{''.join(rows)}</tbody>
        </table>
    </section>
    """


def _section_dictionary(workspace: "Workspace") -> str:
    """Render dictionary entries with authority links."""
    if not workspace.dictionary:
        return """
        <section id="dictionary" class="tab-content">
            <h2>Wörterbuch</h2>
            <p class="empty">Wörterbuch ist leer.</p>
        </section>
        """

    type_counts = Counter(e.entity_type or "—" for e in workspace.dictionary)
    type_summary = ", ".join(f"{t}: {c}" for t, c in type_counts.most_common())

    rows = []
    for entry in workspace.dictionary:
        rows.append(
            f'<tr data-type="{_esc(entry.entity_type or "")}">'
            f'<td>{_esc(entry.term)}</td>'
            f'<td>{_esc(entry.gnd_preferred or entry.preferred_name or "")}</td>'
            f'<td><code>{_esc(entry.entity_type or "—")}</code></td>'
            f'<td>{_authority_link(entry)}</td>'
            f'<td>{len(entry.record_ids)}</td>'
            f'<td><span class="badge">{_esc(entry.source)}</span></td>'
            f'</tr>'
        )

    return f"""
    <section id="dictionary" class="tab-content">
        <h2>Wörterbuch ({len(workspace.dictionary)})</h2>
        <p class="meta">{_esc(type_summary)}</p>
        <table class="data-table">
            <thead>
                <tr><th>Term</th><th>Bevorzugt</th><th>Typ</th><th>Authority</th><th>Records</th><th>Quelle</th></tr>
            </thead>
            <tbody>{''.join(rows)}</tbody>
        </table>
    </section>
    """


def _section_images(workspace: "Workspace") -> str:
    """Render image analyses section."""
    if not workspace.image_analyses:
        return """
        <section id="images" class="tab-content">
            <h2>Bildanalysen</h2>
            <p class="empty">Keine Bilder analysiert.</p>
        </section>
        """

    status_counts = Counter(i.review_status.value for i in workspace.image_analyses)
    status_summary = ", ".join(f"{s}: {c}" for s, c in status_counts.most_common())

    rows = []
    for img in workspace.image_analyses:
        payload = img.result if isinstance(img.result, dict) else {}
        description = payload.get("description", "")
        if len(description) > 200:
            description = description[:197] + "…"
        status_color = _STATUS_COLORS.get(img.review_status.value, "#999")
        rows.append(
            f'<tr data-status="{_esc(img.review_status.value)}">'
            f'<td><code class="muted">{_esc(img.image_id[:12])}</code></td>'
            f'<td>{_esc(img.filename)}</td>'
            f'<td>{_esc(description) or _MUTED_DASH}</td>'
            f'<td><span class="status-badge" style="background:{status_color}">{_esc(img.review_status.value)}</span></td>'
            f'<td>{img.confidence:.2f}</td>'
            f'<td><code class="muted">{_esc(img.record_id or "—")}</code></td>'
            f'</tr>'
        )

    return f"""
    <section id="images" class="tab-content">
        <h2>Bildanalysen ({len(workspace.image_analyses)})</h2>
        <p class="meta">{_esc(status_summary)}</p>
        <table class="data-table">
            <thead>
                <tr><th>ID</th><th>Datei</th><th>Beschreibung</th><th>Status</th><th>Konfidenz</th><th>Record</th></tr>
            </thead>
            <tbody>{''.join(rows)}</tbody>
        </table>
    </section>
    """


def _section_mappings(workspace: "Workspace") -> str:
    """Render field mappings section."""
    if not workspace.field_mapping:
        return """
        <section id="mappings" class="tab-content">
            <h2>Field-Mappings</h2>
            <p class="empty">Keine Mappings konfiguriert.</p>
        </section>
        """

    rows = []
    for fm in workspace.field_mapping:
        enabled = "✓" if not fm.is_ignored else "—"
        rows.append(
            f'<tr>'
            f'<td><code>{_esc(fm.csv_column)}</code></td>'
            f'<td><code>{_esc(fm.goobi_type)}</code></td>'
            f'<td>{_esc(fm.label or "")}</td>'
            f'<td>{"Ja" if fm.repeatable else "Nein"}</td>'
            f'<td>{enabled}</td>'
            f'<td><span class="muted">{_esc(fm.note or "")}</span></td>'
            f'</tr>'
        )

    return f"""
    <section id="mappings" class="tab-content">
        <h2>Field-Mappings ({len(workspace.field_mapping)})</h2>
        <table class="data-table">
            <thead>
                <tr><th>CSV-Spalte</th><th>Goobi-Typ</th><th>Label</th><th>Wiederholbar</th><th>Aktiv</th><th>Notiz</th></tr>
            </thead>
            <tbody>{''.join(rows)}</tbody>
        </table>
    </section>
    """


_STYLES = """
* { box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    margin: 0; padding: 0; color: #222; background: #f6f7f9; line-height: 1.5;
}
header {
    background: linear-gradient(135deg, #2c3e50, #34495e);
    color: #fff; padding: 24px 40px;
}
header h1 { margin: 0 0 4px 0; font-size: 24px; font-weight: 600; }
header .meta { color: #bdc3c7; font-size: 13px; }
.tabs {
    display: flex; gap: 0; padding: 0 40px; background: #fff;
    border-bottom: 1px solid #e1e4e8; position: sticky; top: 0; z-index: 10;
}
.tab-button {
    padding: 14px 20px; cursor: pointer; border: none; background: transparent;
    font-size: 14px; color: #555; border-bottom: 2px solid transparent;
}
.tab-button:hover { color: #2c3e50; }
.tab-button.active { color: #2c3e50; border-bottom-color: #2c3e50; font-weight: 600; }
main { padding: 24px 40px 48px; max-width: 1400px; margin: 0 auto; }
.tab-content { display: none; }
.tab-content.active { display: block; }
h2 { margin: 0 0 16px 0; color: #2c3e50; font-size: 20px; }
h3 { margin: 16px 0 8px 0; color: #34495e; font-size: 16px; }
.subsection { margin-bottom: 32px; }
.stats-grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 16px; margin-bottom: 24px;
}
.stat-card {
    background: #fff; padding: 20px; border-radius: 8px;
    border: 1px solid #e1e4e8; box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}
.stat-value { font-size: 32px; font-weight: 700; color: #2c3e50; }
.stat-label { font-size: 13px; color: #6a737d; text-transform: uppercase; letter-spacing: 0.5px; }
.stat-sub { font-size: 11px; color: #95a5a6; margin-top: 4px; }
.data-table {
    width: 100%; border-collapse: collapse; background: #fff;
    border-radius: 6px; overflow: hidden; box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}
.data-table th {
    background: #f1f3f5; padding: 10px 12px; text-align: left;
    font-size: 12px; text-transform: uppercase; color: #555;
    border-bottom: 1px solid #e1e4e8;
}
.data-table td {
    padding: 8px 12px; border-bottom: 1px solid #f1f3f5; font-size: 13px;
}
.data-table tbody tr:hover { background: #fafbfc; }
.data-table tr.hidden { display: none; }
code { background: #f1f3f5; padding: 2px 6px; border-radius: 3px;
       font-family: SFMono-Regular, Consolas, monospace; font-size: 12px; }
.muted { color: #95a5a6; }
.badge {
    display: inline-block; padding: 2px 8px; border-radius: 10px;
    background: #ecf0f1; font-size: 11px; color: #34495e;
}
.status-badge {
    display: inline-block; padding: 2px 8px; border-radius: 10px;
    color: #fff; font-size: 11px; font-weight: 500;
}
.auth-link {
    text-decoration: none; padding: 2px 6px; border-radius: 3px;
    font-size: 11px; font-family: monospace; display: inline-block; margin-right: 4px;
}
.auth-link.gnd { background: #e8f5e8; color: #1a6e1a; }
.auth-link.wd  { background: #e8f0ff; color: #0d47a1; }
.auth-link.gn  { background: #fff3e0; color: #c66200; }
.auth-link:hover { text-decoration: underline; }
.bars { display: flex; flex-direction: column; gap: 4px; max-width: 600px; }
.bar-row { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.bar-label { flex: 0 0 220px; }
.bar { flex: 1; background: #ecf0f1; height: 16px; border-radius: 3px; overflow: hidden; }
.bar-fill { background: #3498db; height: 100%; }
.bar-count { flex: 0 0 40px; text-align: right; color: #555; font-variant-numeric: tabular-nums; }
.filter-row { margin-bottom: 12px; font-size: 13px; color: #555; }
.filter-row select { padding: 4px 8px; border: 1px solid #ccd0d4; border-radius: 4px; }
.empty { color: #95a5a6; font-style: italic; padding: 16px 0; }
.meta { font-size: 12px; color: #6a737d; margin: 0 0 16px 0; }
"""


_SCRIPT = """
(function() {
    const buttons = document.querySelectorAll('.tab-button');
    const sections = document.querySelectorAll('.tab-content');
    buttons.forEach(btn => {
        btn.addEventListener('click', () => {
            const target = btn.dataset.tab;
            buttons.forEach(b => b.classList.remove('active'));
            sections.forEach(s => s.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById(target).classList.add('active');
        });
    });

    // Entity status filter
    const filter = document.getElementById('entity-status-filter');
    if (filter) {
        filter.addEventListener('change', () => {
            const val = filter.value;
            document.querySelectorAll('#entity-table tbody tr').forEach(row => {
                row.classList.toggle('hidden', val && row.dataset.status !== val);
            });
        });
    }
})();
"""


def render_html_report(
    workspace: "Workspace",
    *,
    title: str = "Debussy Kuratierungsbericht",
) -> str:
    """
    Render a complete HTML report from the workspace.

    Returns a self-contained HTML document with embedded CSS and JS.
    No external dependencies — can be archived or shared as a single file.
    """
    sections = [
        _section_overview(workspace),
        _section_entities(workspace),
        _section_dates(workspace),
        _section_dictionary(workspace),
        _section_images(workspace),
        _section_mappings(workspace),
    ]

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="utf-8">
    <title>{_esc(title)}</title>
    <style>{_STYLES}</style>
</head>
<body>
    <header>
        <h1>{_esc(title)}</h1>
        <div class="meta">Workspace: {_esc(workspace.name)} · Stand: {_esc(workspace.updated_at)}</div>
    </header>
    <nav class="tabs">
        <button class="tab-button active" data-tab="overview">Übersicht</button>
        <button class="tab-button" data-tab="entities">NER ({len(workspace.entity_reviews)})</button>
        <button class="tab-button" data-tab="dates">Daten ({len(workspace.dates)})</button>
        <button class="tab-button" data-tab="dictionary">Wörterbuch ({len(workspace.dictionary)})</button>
        <button class="tab-button" data-tab="images">Bilder ({len(workspace.image_analyses)})</button>
        <button class="tab-button" data-tab="mappings">Mappings ({len(workspace.field_mapping)})</button>
    </nav>
    <main>
        {''.join(sections)}
    </main>
    <script>{_SCRIPT}</script>
</body>
</html>"""


def render_html_report_bytes(workspace: "Workspace", **kwargs) -> bytes:
    """Return HTML report as UTF-8 bytes."""
    return render_html_report(workspace, **kwargs).encode("utf-8")
