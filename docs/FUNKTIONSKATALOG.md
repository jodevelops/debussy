# Debussy — Funktionskatalog & Testmatrix

**Version:** 0.6.0  
**Stand:** 2026-03-05  
**Gesamtstatus:** 532/548 Tests bestanden, 0 fehlgeschlagen, 16 übersprungen

---

## Legende

| Status | Bedeutung |
|--------|-----------|
| ✅ Umgesetzt | Funktion implementiert und getestet |
| 🟡 Teilweise | Modul vorhanden, GUI oder Tests unvollständig |
| 🔴 Geplant | Architektur definiert, noch nicht implementiert |

---

## 1. Daten-Ingest

| ID | Funktion | Status | Tests | Modul | Hinweis |
|----|----------|--------|-------|-------|---------|
| F01 | CSV/TSV Ingest | ✅ Umgesetzt | 5/5 | `ingest/csv_loader.py` | Automatische Encoding-Erkennung (UTF-8, Latin-1, BOM), Zeilenende-Erkennung, Profiling aller Spalten |
| F31 | XML-Import (METS/MODS, LIDO, EAD) | 🔴 Geplant | 0/0 | `ingest/` | Parsing mit lxml, Mapping auf internes Schema |
| F36 | Bild-Ingest (TIFF/JPEG/PNG) | ✅ Umgesetzt | 2/2 | `ingest/image_loader.py` | EXIF, Dimensionen, SHA-256, Base64 ohne Pillow |
| F37 | PDF-Import | 🔴 Geplant | 0/0 | `ingest/` | Text + Seitenbilder extrahieren |

### Testanleitung F01
```
1. Lade subjects_restructured_1.csv hoch
2. ✓ Erwartung: 8.308 Records, 18 Spalten erkannt
3. ✓ Erwartung: Encoding UTF-8 erkannt
4. ✓ Erwartung: record_id als ID-Spalte erkannt
5. Lade GIUBMaster_locations_gnd_merged.csv dazu
6. ✓ Erwartung: 8.312 Records, 96 Spalten erkannt
7. ✓ Erwartung: Beide Dateien mit Checkboxen angezeigt
8. ✓ Erwartung: Einzelne Dateien abwählbar
```

---

## 2. Strukturelle Analyse

| ID | Funktion | Status | Tests | Modul | Hinweis |
|----|----------|--------|-------|-------|---------|
| F02 | Fehlende Werte | ✅ Umgesetzt | 3/3 | `analyze/structural.py` | Severity nach Füllrate: >50% leer = critical, 20-50% = warning |
| F03 | Duplikate | ✅ Umgesetzt | 2/2 | `analyze/structural.py` | Erkennt doppelte Record-IDs |
| F04 | Encoding-Probleme | ✅ Umgesetzt | 2/2 | `analyze/structural.py` | UTF-8/Latin-1 Artefakte, Mojibake-Erkennung |
| F05 | Format-Inkonsistenzen | ✅ Umgesetzt | 2/2 | `analyze/structural.py` | Gemischte Trennzeichen (;/,), führende/folgende Whitespace |
| F06 | Term-Varianten | ✅ Umgesetzt | 2/2 | `analyze/structural.py` | Case-Varianten desselben Begriffs |
| F07 | Cross-File-Linkage | ✅ Umgesetzt | 2/2 | `analyze/structural.py` | Verwaiste Records zwischen verknüpften Dateien |
| F08 | GND-Abdeckung | ✅ Umgesetzt | 2/2 | `analyze/structural.py` | Matching-Quote, Konfidenzverteilung |

### Testanleitung F02-F08
```
1. Lade beide GIUB-CSVs hoch
2. Beide Dateien auswählen → "Strukturelle Analyse"
3. ✓ Erwartung: Summary zeigt Records, Spalten, Critical/Warning/Info
4. ✓ Erwartung: Findings nach Severity filterbar
5. ✓ Erwartung: Profile zeigen Füllraten pro Spalte
6. ✓ Erwartung: Spalten-Beschreibungen mit Beispielwerten
7. ✓ Erwartung: Markdown-Export kopierbar
```

---

## 3. Named Entity Recognition (NER)

| ID | Funktion | Status | Tests | Modul | Hinweis |
|----|----------|--------|-------|-------|---------|
| F10 | NER (LLM) | ✅ Umgesetzt | 4/4 | `analyze/ner.py` | 10 Entity-Typen, JSON-Output mit Konfidenz + Begründung |
| F11 | NER (SpaCy) | 🟡 Teilweise | 1/2 | `analyze/ner.py` | Funktioniert wenn `de_core_news_lg` installiert |
| F12 | NER (Hybrid) | ✅ Umgesetzt | 1/1 | `analyze/ner.py` | SpaCy-Baseline + LLM-Verfeinerung |
| F13 | Problematik-Scanner | ✅ Umgesetzt | 1/1 | `analyze/ner.py` | Ganzes Dataset, koloniale/veraltete Terminologie |
| F25 | Entity-Filter im GUI | ✅ Umgesetzt | — | `api/dashboard.html` | Filter nach Entity-Typ (PER, ORG, LOC, etc.) |
| F24 | NER-Export (CSV) | ✅ Umgesetzt | — | `api/dashboard.html` | Client-seitiger CSV-Download |

### Entity-Typen

| Typ | Bezeichnung | Beispiel |
|-----|-------------|---------|
| PER | Person | Johann Wolfgang von Goethe |
| ORG | Organisation | Universität Bern |
| LOC | Ort/Geografie | Alpen, Rhein, Sahara |
| GPE | Geo-politische Einheit | Schweiz, Berlin, Kanton Bern |
| FAC | Bauwerk/Einrichtung | Münster, Stadtmauer, Rathaus |
| EVT | Ereignis | Weltausstellung 1900 |
| WRK | Werk/Publikation | Zur Völkerkunde des Orients |
| DAT | Datum/Zeitangabe | ca. 1920, 19. Jahrhundert |
| ETH | Ethnie/Kulturgruppe | Berber, Tuareg |
| CON | Konzept/Thema | Kartographie, Landwirtschaft |

### Testanleitung F10-F13
```
1. Tab "NER & Entities" öffnen
2. Datensatz wählen: subjects_restructured_1.csv
3. Spalten wählen: subject_extract_original, NE_Place
4. Methode: LLM, Samples: 5
5. "NER starten" klicken
6. ✓ Erwartung: Entity-Tabelle mit Typ-Badges, Konfidenz-Balken
7. ✓ Erwartung: Filter nach Typ funktioniert (PER, LOC, etc.)
8. ✓ Erwartung: CSV-Export generiert valide Datei
9. "Problematische Begriffe suchen" → Datensatz wählen, Samples: 10
10. ✓ Erwartung: Ergebnis zeigt Issues oder "keine gefunden"
```

---

## 4. Datierung (EDTF)

| ID | Funktion | Status | Tests | Modul | Hinweis |
|----|----------|--------|-------|-------|---------|
| F14 | EDTF Regelbasiert | ✅ Umgesetzt | 24/24 | `normalize/edtf.py` | LOC EDTF Level 0+1, DE/EN Muster |
| F15 | EDTF LLM-Fallback | ✅ Umgesetzt | 0/1 | `normalize/edtf.py` | Für nicht-erkannte Muster |

### Unterstützte Muster

| Input | EDTF | Regel |
|-------|------|-------|
| `1920` | `1920` | ISO Jahr |
| `1920-03-15` | `1920-03-15` | ISO Datum |
| `ca. 1920` / `um 1920` | `1920~` | Approximation |
| `vor 1920` | `../1920` | Open start |
| `nach 1920` | `1920/..` | Open end |
| `1920-1930` | `1920/1930` | Range |
| `1920er` / `1920s` | `192X` | Dekade |
| `19. Jh.` / `19. Jahrhundert` | `18XX` | Jahrhundert (n-1) |
| `[1920]` / `1920?` | `1920?` | Unsicher |
| `o.D.` / `undatiert` | *(leer)* | Undatiert |

### Testanleitung F14
```
1. Tab "Datierung" öffnen
2. Datensatz wählen, Datums-Spalte wählen
3. Samples: 0 (alle) → "Konvertieren"
4. ✓ Erwartung: Tabelle mit Original → EDTF Mapping
5. ✓ Erwartung: Summary zeigt Konvertiert/Fehlgeschlagen/Undatiert
6. ✓ Erwartung: Konfidenz-Werte für jede Konvertierung
7. Test mit "LLM-Fallback": Ja → nicht-erkannte werden per LLM konvertiert
```

---

## 5. KI-Integration

| ID | Funktion | Status | Tests | Modul | Hinweis |
|----|----------|--------|-------|-------|---------|
| F09 | KI-Klassifikation | ✅ Umgesetzt | 3/3 | `analyze/semantic.py` | Batch via GPUStack/Mock |
| F16 | GPUStack Provider | ✅ Umgesetzt | 3/3 | `ai/gpustack.py` | OpenAI-kompatible API |
| F17 | Mock Provider | ✅ Umgesetzt | 3/3 | `ai/mock.py` | Deterministische Tests ohne GPU |
| F18 | Batch-Processing | ✅ Umgesetzt | 3/3 | `ai/batch.py` | Progress, Fehlertoleranz, Rate Limiting |
| F22 | Modell-Auswahl im GUI | ✅ Umgesetzt | — | `api/` | Alle GPUStack-Modelle als Dropdown |
| F23 | System-Prompt Editor | ✅ Umgesetzt | — | `api/` | 6 Vorlagen + eigene Instruktion |

### Testanleitung F16/F22/F23
```
1. Tab "KI-Konfiguration" öffnen
2. ✓ Erwartung: Text-Modell und Vision-Modell Dropdowns mit GPUStack-Modellen
3. ✓ Erwartung: System-Instruktionen mit Vorlagen-Auswahl
4. ✓ Erwartung: Vorlagen: Metadaten DE/EN, Vision, NER, EDTF, Scanner
5. "GPUStack testen" klicken
6. ✓ Erwartung: JSON mit success/models/test_response
```

---

## 6. Export

| ID | Funktion | Status | Tests | Modul | Hinweis |
|----|----------|--------|-------|-------|---------|
| F19 | Markdown-Report | ✅ Umgesetzt | 2/2 | `report/markdown.py` | Vollständiger Qualitätsbericht |
| F26 | Goobi XML Preview | ✅ Umgesetzt | 4/4 | `api/routes/export.py` | Vorschau, Record-basiert |
| F34 | CSV-Export bereinigt | ✅ Umgesetzt | 10/10 | `export/csv_export.py`, `/api/export/csv` | NER + EDTF + GND Anreicherungen, BOM für Excel |
| F35 | JSON-LD Export | ✅ Umgesetzt | 10/10 | `export/jsonld.py`, `/api/export/jsonld` | Schema.org, GND + Wikidata sameAs, EDTF Dates |

### Testanleitung F26
```
1. Tab "Export" öffnen
2. Datensatz wählen → Record auswählen
3. "XML-Vorschau" klicken
4. ✓ Erwartung: Goobi-Import XML mit Metadaten des Records
5. ✓ Erwartung: Format entspricht goobi-import Schema
```

---

## 7. Enrichment (geplant)

| ID | Funktion | Status | Tests | Modul | Hinweis |
|----|----------|--------|-------|-------|---------|
| F27 | GND-Enrichment | ✅ Umgesetzt | 2/2 | `enrich/gnd.py`, `api/routes/enrich.py` | lobid.org API Batch-Lookup via `/api/gnd/batch` |
| F28 | Wikidata-Enrichment | ✅ Umgesetzt | 9/9 | `enrich/wikidata.py`, `api/routes/enrich.py` | SPARQL via query.wikidata.org, offline-sicher |
| F33 | Normdaten-Wörterbuch | ✅ Umgesetzt | — | `core/workspace.py` | Im Workspace mit GND+Wikidata Verknüpfung |

---

## 8. Web-Dashboard

| ID | Funktion | Status | Tests | Hinweis |
|----|----------|--------|-------|---------|
| F20 | Web-Dashboard | ✅ Umgesetzt | — | FastAPI + HTML, kein Build-Schritt |
| F21 | Datei-Auswahl | ✅ Umgesetzt | — | Checkbox pro hochgeladener Datei |
| F38 | Tab-Navigation | ✅ Umgesetzt | — | 6 Tabs: Daten, NER, Datierung, KI-Konfig, Export, Katalog |

---

## 9. Infrastruktur

| ID | Funktion | Status | Tests | Hinweis |
|----|----------|--------|-------|---------|
| F39 | .env Konfiguration | ✅ Umgesetzt | — | Keine hardcodierten Secrets |
| F40 | Maskierte API-Keys | ✅ Umgesetzt | — | `display_safe()` für Logs |
| F41 | Modulares Design | ✅ Umgesetzt | — | Jedes Modul einzeln testbar |
| F29 | Bild-Analyse (Vision) | ✅ Umgesetzt | 10/10 | `api/routes/ai.py`, Dashboard | Upload, Analyse, Thumbnail, Workspace-Persistenz |
| F30 | OCR/HTR | ✅ Umgesetzt | 5/5 | `api/routes/ai.py` `/api/images/ocr`, Dashboard | Vision-LLM Texterkennung, JSON-Output |
| F32 | Goobi API Integration | ✅ Umgesetzt | 6/6 | `/api/goobi/status`, `/api/goobi/push-record`, `/api/goobi/push-batch` |

---

## Zusammenfassung

| Kategorie | Umgesetzt | Teilweise | Geplant | Gesamt |
|-----------|-----------|-----------|---------|--------|
| Daten-Ingest | 2 | 0 | 2 | 4 |
| Strukturelle Analyse | 7 | 0 | 0 | 7 |
| NER | 4 | 1 | 0 | 5 |
| Datierung | 2 | 0 | 0 | 2 |
| KI-Integration | 6 | 0 | 0 | 6 |
| Export | 5 | 0 | 0 | 5 |
| Enrichment | 2 | 0 | 1 | 3 |
| Dashboard | 3 | 0 | 0 | 3 |
| Infrastruktur | 6 | 0 | 0 | 6 |
| **Gesamt** | **39** | **0** | **2** | **41** |

### Automatische Tests

<!-- AUTO-TESTS-START -->
| Test-Suite | Bestanden | Fehlgeschlagen | Übersprungen | Status |
|------------|-----------|----------------|--------------|--------|
| test_ai.py | 19/19 | 0 | 0 | ✅ |
| test_api.py | 50/50 | 0 | 0 | ✅ |
| test_cli.py | 8/8 | 0 | 0 | ✅ |
| test_comprehensive.py | 22/22 | 0 | 0 | ✅ |
| test_core.py | 18/18 | 0 | 0 | ✅ |
| test_edtf.py | 82/82 | 0 | 0 | ✅ |
| test_gnd.py | 14/14 | 0 | 0 | ✅ |
| test_gnd_enrich.py | 24/40 | 0 | 16 | ✅ |
| test_goobi_api.py | 4/4 | 0 | 0 | ✅ |
| test_goobi_export.py | 32/32 | 0 | 0 | ✅ |
| test_image_fixtures.py | 10/10 | 0 | 0 | ✅ |
| test_image_upload.py | 31/31 | 0 | 0 | ✅ |
| test_ner.py | 29/29 | 0 | 0 | ✅ |
| test_ner_edtf.py | 31/31 | 0 | 0 | ✅ |
| test_new_features.py | 41/41 | 0 | 0 | ✅ |
| test_roadmap.py | 8/8 | 0 | 0 | ✅ |
| test_services.py | 20/20 | 0 | 0 | ✅ |
| test_utils.py | 30/30 | 0 | 0 | ✅ |
| test_workspace.py | 33/33 | 0 | 0 | ✅ |
| test_workspace_export.py | 26/26 | 0 | 0 | ✅ |
| **Gesamt** | **532/548** | **0** | **16** | **✅** |
<!-- AUTO-TESTS-END -->

---

## Empfohlene Entwicklungsreihenfolge

**Stand:** 2026-03-05 (v0.5.2)

### Priorität 1: Stabilisieren
Alle bestehenden Features müssen zuverlässig funktionieren, bevor neue hinzukommen:
1. Export-Pipeline (BUG-01 bis BUG-04 im Testbericht) — **erledigt in v0.5.2**
2. Thumbnail-Anzeige und XSS-Schutz im Dashboard — **erledigt in v0.5.2**
3. Image-Cleanup und Persistenz — **erledigt in v0.5.2**

### Priorität 2: Test-Abdeckung erweitern
4. Image-Integration-Tests (Upload → Thumbnail → Analyse → Workspace)
5. GPUStack-Provider mit gemocktem HTTP-Aufruf
6. MockProvider-Fehlerszenarien (ungültiges JSON, leere Antworten)
7. CLI-Tests für `analyze` und `plan`

### Priorität 3: Neue Features (Phase 3+)
8. Wikidata-Enrichment (SPARQL) — R-01
9. OCR/HTR-Integration — R-02
10. METS/MODS-Export — R-04
11. GeoNames-Lookup — R-05
12. Goobi Viewer API (REST Push) — R-03 — **erledigt in v0.6.0**
13. XML/PDF-Ingest — R-06

_Hinweis: Diese Zahlen werden mit `python scripts/update_test_catalog.py --update-doc` neu berechnet. Vor Releases lokal ausführen; in CI prüft der Workflow `test-catalog-consistency.yml` die Konsistenz via `--check-doc`._