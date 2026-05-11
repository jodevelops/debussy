# Debussy — Technical Debt Report

**Stand:** Post Phase 3 Wave 3 (nach PR #205–#208)
**Erstellt:** Analyse auf Basis aller bisherigen PR-Runden

---

## Methodik

Dieser Report basiert auf technischen Beobachtungen aus 8 Codex-Review-Runden (PR #205) und den drei Wave-3-PRs (#206–#208). Jeder Schulden-Eintrag enthält Schweregrad, Herkunft und empfohlene Maßnahme.

---

## Kategorie 1: Datenmodell-Schulden

### TD-01: Inkonsistente Authority-Felder in `DictionaryEntry` ⚠️ MITTEL

**Problem:** GND hat 4 persistierte Felder (`gnd_id`, `gnd_preferred`, `gnd_type`, `gnd_uri`), Wikidata hat 1 (`wikidata_id`), GeoNames hatte bis Wave 3C nur 1 (`geonames_id`). Nach jedem GeoNames-Commit wurden Name, Typ und URI silently verworfen.

**Wo:** `src/kwb/core/workspace.py`, Klasse `DictionaryEntry`

**Status:** Teilweise behoben (Wave 3C — `geonames_preferred`, `geonames_type`, `geonames_uri` hinzugefügt). Wikidata fehlt noch `wikidata_preferred`, `wikidata_type`, `wikidata_uri`.

**Empfehlung:** Wikidata-Commit-Logik in `enrich.py` um die drei fehlenden Felder erweitern, Parität zu GND/GeoNames herstellen.

---

### TD-02: Ungenutzte `added_sections`-Variable in METS/MODS-Export ℹ️ GERING

**Problem:** In `_make_mods_record()` wird `added_sections: set[str] = set()` initialisiert, aber nach dem Refactoring zur universellen Repeatable-Schleife nie befüllt oder geprüft.

**Wo:** `src/kwb/export/mets_mods.py`, ca. Zeile 115

**Empfehlung:** Variable entfernen — toter Code, verwirrt Leser.

---

## Kategorie 2: API- und Validierungs-Schulden

### TD-03: Hardcoded GeoNames-Demo-Account 🔴 HOCH

**Problem:** Wenn `cfg.geonames_username` nicht gesetzt ist, fällt das System auf `"demo"` zurück. Das Demo-Konto hat Rate Limits von 2000 req/Tag und ist für Produktivnutzung ungeeignet. Fehler erscheinen erst zur Laufzeit im Curator-Workflow.

**Wo:** `src/kwb/api/routes/enrich.py`, `geonames_batch_api()`

**Empfehlung:** Beim Startup auf Log-Level WARNING hinweisen; im Endpoint einen 503 mit klarer Fehlermeldung zurückgeben wenn kein Username konfiguriert.

---

### TD-04: Hardcoded Confidence-Score 0.8 für alle GeoNames-Treffer ⚠️ MITTEL

**Problem:** Jeder GeoNames-Kandidat bekommt `score=0.8` unabhängig davon, wie gut der Treffer ist. GND berechnet einen rang-basierten Score. GeoNames könnte Population, `feature_code`-Spezifität und Name-Ähnlichkeit einbeziehen.

**Wo:** `src/kwb/api/routes/enrich.py`, `geonames_batch_api()`, `score=0.8`

**Empfehlung:** Einfache Heuristik: `score = 1.0 if position == 0 else max(0.3, 1.0 - position * 0.15)`.

---

### TD-05: `limit`-Typ-Validierung nur im METS/MODS-Endpoint ⚠️ MITTEL

**Problem:** Der METS/MODS-Endpoint prüft `isinstance(limit, int)` vor `limit < 0`. Andere Batch-Endpoints (GND, Wikidata, GeoNames) tun das nicht — ein `{"limit": null}` würde `TypeError` oder unerwartetes Verhalten auslösen.

**Wo:** `src/kwb/api/routes/enrich.py`, alle `*_batch_api()`-Funktionen

**Empfehlung:** Gemeinsamen Validator `_validate_limit(request, default, max_val)` extrahieren und in allen Batch-Endpunkten einsetzen.

---

## Kategorie 3: XML-/Ingest-Schulden

### TD-06: `_lido_findall()` Fallback ist semantisch ungenau 🔴 HOCH

**Problem:** Die Fallback-Implementierung matcht ausschließlich nach dem **terminalen Tag-Namen** — d.h. `_lido_findall(root, "a/b/c")` gibt alle `<c>`-Elemente auf beliebiger Tiefe zurück, nicht nur im Pfad `a/b/c`. In LIDO-Dokumenten mit mehreren Events können so falsche Elemente zurückgegeben werden.

```python
# Aktuell: iteriert ALLE Nachkommen, matched nur Terminal-Tag
terminal = path.split("/")[-1].split(":")[-1]
for el in parent.iter():
    tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
    if tag == terminal:
        out.append(el)
```

**Wo:** `src/kwb/ingest/xml_loader.py`, `_lido_findall()`

**Empfehlung:** Den lokalnamen-basierten Pfad schrittweise traversieren, analog zu `_lido_find()`.

---

### TD-07: EAD-Format fehlt in F31 🔴 HOCH (bekannt, geplant)

**Problem:** F31 ist `🟡 Teilweise` — METS/MODS und LIDO funktionieren, EAD (Encoded Archival Description) fehlt. EAD ist Standardformat für Findbücher in Archiven. Das hierarchische Modell (`<c01>` → `<c02>` → Blatt) ist noch nicht gelöst.

**Wo:** Kein Code vorhanden

**Empfehlung:** Designentscheidung: Row pro Blattknoten vs. Row pro Ebene mit `parent_id`-Spalte — dann Wave 4a-PR.

---

### TD-08: Kein ZIP/Verzeichnis-Batch-Ingest ⚠️ MITTEL

**Problem:** Goobi-Exports liefern oft **ein METS/MODS-XML pro Record** in einem Verzeichnis. Der aktuelle `ingest_xml()` lädt eine Datei — ein Verzeichnis müsste manuell durch Mehrfach-Upload abgebildet werden.

**Wo:** `src/kwb/ingest/xml_loader.py`, `src/kwb/api/routes/analyze.py`

**Empfehlung:** ZIP-Dateien entpacken und alle enthaltenen `.xml`-Dateien laden und konkatenieren.

---

## Kategorie 4: Test-Schulden

### TD-09: `test_roadmap.py` prüft hardcodierten Feature-Status ℹ️ GERING

**Problem:** `test_parse_function_catalog_reads_known_feature` prüfte `F31.status == "Geplant"`. Als F31 auf `🟡 Teilweise` gehoben wurde, brach der Test sofort. Wir haben ihn auf F37 umgestellt — das gleiche Problem tritt wieder auf, wenn F37 implementiert wird.

**Wo:** `tests/test_roadmap.py`

**Empfehlung:** Test auf strukturelle Korrektheit umstellen: `status in {"Umgesetzt", "Teilweise", "Geplant"}` für alle Einträge prüfen, oder ausschließlich die Fixture-Katalogdatei (`tests/fixtures/roadmap_small_catalog.md`) verwenden.

---

### TD-10: Kein GeoNames E2E-API-Test ⚠️ MITTEL

**Problem:** Es gibt Tests für den Batch-Endpoint und den DictionaryEntry-Roundtrip, aber **keinen End-to-End-Test** der den vollen Workflow abdeckt: Batch → Candidate → Commit → DictionaryEntry-Prüfung.

**Wo:** `tests/test_api.py`, `tests/test_authority_review.py`

**Empfehlung:** `test_full_geonames_workflow_via_api()` hinzufügen — analog zum bestehenden GND-Workflow-Test.

---

### TD-11: Dashboard-JavaScript hat nur Syntax-Test ⚠️ MITTEL

**Problem:** Das gesamte Frontend-JavaScript (>2000 Zeilen) wird nur via `node --check` auf Syntaxfehler geprüft. Funktionen wie `renderGeoNamesResults()`, `renderGNDResults()`, `updWS()` sind komplett ungetestet.

**Wo:** `src/kwb/api/parts/dashboard.js`

**Empfehlung:** DOM-Testing mit jsdom oder Playwright für kritische Render-Funktionen. Mindestens Unit-Tests für `renderGeoNamesResults` mit Mock-Input.

---

## Kategorie 5: Performance-/Produktionsschulden

### TD-12: Kein Caching in Enrichment-APIs ⚠️ MITTEL

**Problem:** Jede GND-, Wikidata- und GeoNames-Suche trifft die externe API ohne Caching. Bei Batch-Läufen mit redundanten Termen (gleicher Ort in 1000 Records) wird der Term 1000-mal abgefragt.

**Wo:** `src/kwb/enrich/gnd.py`, `src/kwb/enrich/wikidata.py`, `src/kwb/enrich/geonames.py`

**Empfehlung:** `functools.lru_cache` auf der Search-Funktion. Für Produktivbetrieb: SQLite-basierter Disk-Cache.

---

### TD-13: XML-Loader liest ganzes Dokument in DOM ℹ️ GERING

**Problem:** `load_mets_mods()` und `load_lido()` nutzen `ET.parse()` (vollständiger DOM-Parse). Bei sehr großen Dateien kann dies zu hohem Speicherverbrauch führen — der DOM wird vollständig geladen, bevor `MAX_ROWS` geprüft wird.

**Wo:** `src/kwb/ingest/xml_loader.py`

**Empfehlung:** `ET.iterparse()` für Streaming einsetzen. `detect_xml_format()` nutzt es bereits korrekt als Vorbild.

---

## Zusammenfassung nach Priorität

| ID | Titel | Schwere | Aufwand |
|----|-------|---------|---------|
| TD-03 | GeoNames Demo-Account | 🔴 HOCH | Klein |
| TD-06 | `_lido_findall()` Fallback ungenau | 🔴 HOCH | Klein |
| TD-07 | EAD fehlt (bekannt) | 🔴 HOCH | Groß |
| TD-01 | Wikidata-Felder unvollständig | ⚠️ MITTEL | Klein |
| TD-04 | GeoNames Confidence hardcoded | ⚠️ MITTEL | Klein |
| TD-05 | Limit-Validierung inkonsistent | ⚠️ MITTEL | Klein |
| TD-08 | Kein ZIP/Verzeichnis-Batch-Ingest | ⚠️ MITTEL | Mittel |
| TD-10 | Kein GeoNames E2E-API-Test | ⚠️ MITTEL | Klein |
| TD-11 | JS ohne Unit-Tests | ⚠️ MITTEL | Groß |
| TD-12 | Kein Enrichment-Caching | ⚠️ MITTEL | Mittel |
| TD-02 | Tote `added_sections`-Variable | ℹ️ GERING | Trivial |
| TD-09 | Hardcodierter Feature-Status im Test | ℹ️ GERING | Klein |
| TD-13 | XML DOM statt Streaming | ℹ️ GERING | Mittel |

---

## Empfohlene Quick-Wins (< 1 Tag)

1. **TD-02:** `added_sections` entfernen — 1 Zeile löschen
2. **TD-03:** GeoNames-Demo-Warning + 503 — ~5 Zeilen
3. **TD-05:** `_validate_limit()` Helper extrahieren — ~20 Zeilen
4. **TD-06:** `_lido_findall()` Fallback verschärfen — ~15 Zeilen
5. **TD-09:** `test_roadmap.py` auf strukturellen Test umstellen — ~5 Zeilen
