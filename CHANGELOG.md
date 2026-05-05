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
- **Regression-Test-Suite `tests/test_phase2_collection_agnosticism.py`** —
  15 dedizierte Tests für Phase 2 (Collection-Agnosticism) Issues #103,
  #110, #120, #121, #136. Validiert field_mapping Konsolidierung,
  Migrationen, Round-trip Serialisierung.

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
- **`Workspace.field_mapping`** — konsolidiert zu `list[FieldMapping]`
  (kanonisches Format). Entfernt `_field_mapping_raw` dual-storage
  anti-pattern. Legacy dict-Format (`{"col": (label, type)}`) wird
  automatisch zu list-Format migriert. Alle Serialisierung nutzt jetzt
  konsistent das list-Format. (CORE-BUG-03, Issue #103)

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
Phase 1 (Stabilize) der Core-Audit-Empfehlungen ist **abgeschlossen**.
Phase 2 (Collection-Agnosticism) hat **begonnen**:

**Phase 1** (✅ abgeschlossen):
- CORE-BUG-01 bis CORE-BUG-07 — Kern-Stabilisierung

**Phase 2** (🟡 in Arbeit):
- CORE-BUG-03 (#103) ✅ — field_mapping Konsolidierung **fertiggestellt**
- CORE-ENH-03 (#110) — provenance Konsistenz (ausstehend)
- CORE-ENH-04 (#120) — subject_extract_original Hardcodierung (ausstehend)
- CORE-ENH-05 (#121) — named_entity schema Konfigurierbarkeit (ausstehend)
- CORE-ENH-06 (#136) — Multilingual Wikidata (ausstehend)

**Phase 3** (geplant): Confidence-Semantics (Issues #123, #129, #133)
**Phase 4** (geplant): User-Centered UX-Redesign (Issues #125, #126, #127, #132)

Siehe `debussy-core-audit-issues.md` für die vollständige Sequenzierung.

---

## [0.6.0] — 2026-04 (Stand vor Audit-Phase)

Initiale Version vor systematischem Audit. Siehe Git-History für Details.
