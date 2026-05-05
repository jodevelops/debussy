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
- **Sicherheit** — sicherheitsrelevante Korrekturen

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
- Bare `except:` in `_get_affected_ids()` konnte legitime Exceptions
  wie pandas.errors.IndexingError verschlucken; now catches spezifisch
  (IndexError, KeyError, ValueError, pandas.errors.IndexingError). (#118)
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

## [0.6.1] — 2026-05 (Phase 1a — Core Stabilization)

### Hinzugefügt
- **`kwb.core.utils.utc_now_iso()`** — zentraler Helper für UTC-Zeitstempel
  mit Timezone-Offset. Single source of truth für alle persistierten
  Timestamps. Ersetzt das deprecated `datetime.utcnow()` projektweit.
- **`UserStore.load_ok`** — Property, die signalisiert, ob `users.json`
  erfolgreich geladen wurde. Erlaubt der API, beim Start zu prüfen, ob
  der Account-Speicher gesund ist.
- **`UserStoreCorruptError`** — Exception-Typ für korrupte User-Stores.
- **Regression-Test-Suite `tests/test_phase1_stabilization.py`** — jeder
  Audit-Issue ist mit einem dedizierten Test abgedeckt; die Audit-ID
  steht im Docstring.

### Geändert
- **`Workspace.image_review_stats()`** — gibt jetzt einen Dict zurück,
  dessen Schlüssel exakt mit den `ImageReviewStatus`-Werten
  (`pending` / `accepted` / `rejected`) plus `total` übereinstimmen.
  Vorher gab es zwei Methoden mit identischem Namen, die zweite hatte
  den Tippfehler `"approved"`. (CORE-BUG-01, Issue #101)
- **`ReviewStatus`** — wird jetzt zentral in `kwb.core.models` definiert
  und von `kwb.core.workspace` re-exportiert. Vorher existierten zwei
  Enums mit identischem Namen aber unterschiedlichen Member-Sets, die
  über Modulgrenzen hinweg nie gleich verglichen wurden. Der nicht
  genutzte Wert `MERGED` wurde entfernt. (CORE-BUG-02, Issue #102)
- **`KWBConfig.save_to_dotenv()`** — persistiert jetzt **alle 13**
  Konfigurations-Keys (vorher nur 4 GPUStack-Felder). Damit
  round-trippt `load_config → save_to_dotenv → load_config` ohne
  Datenverlust. (CORE-BUG-06, Issue #106)
- **`UserStore._load()`** — fängt jetzt nur `OSError` und
  `json.JSONDecodeError` (statt bare `except: pass`). Korrupte
  `users.json` wird automatisch in `users.json.corrupt-<timestamp>`
  umbenannt, sodass Operatoren manuell wiederherstellen können.
  (CORE-BUG-04, Issue #104)
- **`UserStore.ensure_default_admin()`** — verweigert die Erstellung
  des Default-Admins, wenn der Store nicht geladen werden konnte.
  Vorher konnten korrupte Dateien zu stiller Account-Wiederherstellung
  mit dem Default-Passwort führen. (CORE-BUG-04, Issue #104)
- **Alle Timestamps** in `core/workspace.py`, `core/tasks.py`,
  `api/routes/ai.py`, `api/routes/mds_tasks.py` nutzen jetzt
  `utc_now_iso()` statt `datetime.utcnow().isoformat()`. ISO-Strings
  enthalten den Timezone-Offset `+00:00`. (CORE-BUG-07, Issue #107)

### Behoben
- Bilder mit `review_status = ACCEPTED` wurden in `image_review_stats()`
  unter dem falschen Key `"approved"` gezählt; tatsächliche Curator-
  Zahlen waren systematisch auf 0. (#101)
- Cross-Modul-Vergleiche von `ReviewStatus` gaben silently `False`
  zurück, weil zwei verschiedene Enum-Klassen verglichen wurden. (#102)
- Korruption in `users.json` führte zur stillen Wiederherstellung
  des Default-Admins mit Passwort `"debussy"`. Jetzt: kein Account
  wird angefasst, der Operator wird informiert. (#104)
- Konfigurations-Änderungen an Goobi- oder GeoNames-Feldern in der
  UI gingen beim Neustart verloren. (#106)
- `DeprecationWarning` aus `datetime.utcnow()` (Python 3.12+) ist
  beseitigt; alle Timestamps sind timezone-aware. (#107)

### Architektur-Hinweis
Phase 1 (Stabilize) der Core-Audit-Empfehlungen ist abgeschlossen. Die
nächsten Phasen sind:
- **Phase 2** — Collection-Agnosticism (Issues #103, #110, #120, #121, #136)
- **Phase 3** — Confidence-Semantics (Issues #123, #129, #133)
- **Phase 4** — User-Centered UX-Redesign (Issues #125, #126, #127, #132)

Siehe `debussy-core-audit-issues.md` für die vollständige Sequenzierung.

---

## [0.6.0] — 2026-04 (Stand vor Audit-Phase)

Initiale Version vor systematischem Audit. Siehe Git-History für Details.
