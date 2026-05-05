# Changelog

Alle wesentlichen Änderungen an Debussy werden in dieser Datei dokumentiert.

Das Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
und das Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

Sektionen:
- **Hinzugefügt** — neue Features
- **Geändert** — Änderungen an bestehender Funktionalität
- **Veraltet** — wird in einer zukünftigen Version entfernt
- **Entfernt** — bereits entfernte Funktionalität
- **Behoben** — Bugfixes
- **Sicherheit** — sicherheitsrelevante Korrektionen

---

## [Unreleased]

### Hinzugefügt
- **`NERResult.completion_summary`** — Dict mit Batch-Verarbeitungsstatistiken
  (total_items, successful_parses, failed_parses, success_rate). Ermöglicht es
  der API und Callers, Ausfallquoten bei LLM-basierter NER zu tracking.
- **Regression-Test-Suite `tests/test_phase1b_stabilization.py`** — alle
  Analyze/Enrich-Audit-Issues sind mit dedizierten Tests abgedeckt; die Audit-ID
  steht im Docstring.

### Geändert
- **`LobidGNDClient.search()`** — gibt jetzt **rank-basierte** Konfidenzwerte
  zurück statt hardcoded 0.8. 1. Treffer = 1.0, 2. = 0.8, 3. = 0.6, minimum 0.2.
  Das ermöglicht es der UI, Ergebnisse besser zu sortieren. (#122)
- **`_normalize_dates_llm()`** — ersetzt O(n²) `next()`-Suche durch
  pre-built `items_by_id` Dict für O(1) Lookup bei fehlgeschlagenen Ergebnissen.
  Performance auf großen Batches verbessert. (#124)

### Behoben
- NER-LLM-Batch-Ausfallquoten waren nicht sichtbar; nun werden sie in
  `completion_summary` surfaced für Monitoring und Debugging. (#116)
- Bare `except: pass` in `_get_affected_ids()` konnte legitime Exceptions
  wie IndexError/KeyError verschlucken; now catches nur (IndexError, KeyError,
  ValueError). (#118)
- LobidGND-Matches wurden alle mit 0.8 Konfidenz gerankt, egal ob 1. oder
  5. Treffer — ist jetzt rank-sensitiv (1.0 für 1., 0.8 für 2., etc.). (#122)
- `_normalize_dates_llm()` hatte O(n²)-Komplexität beim Lookup von Input-Texts
  für fehlgeschlagene Records; jetzt O(1) mit pre-built Dict. (#124)

### Architektur-Hinweis
Phase 1b (Analyze/Enrich Stabilization) der Core-Audit-Empfehlungen ist abgeschlossen.
Die Audit-Arbeit folgt der etablierten Struktur:
- Gezielte Fixes für vier Audit-Issues (EXT-BUG-02, 04, 08, 10)
- Regression-Tests für alle Fixes
- Dokumentation in CHANGELOG und Docstrings
- Keine großen Umstrukturierungen, nur Stabilisierung

Siehe `debussy-core-audit-issues.md` für die vollständige Sequenzierung.

---

## [0.6.0] — 2026-04 (Stand vor Audit-Phase)

Initiale Version vor systematischem Audit. Siehe Git-History für Details.
