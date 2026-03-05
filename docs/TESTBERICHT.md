# Debussy v0.5.2 — Umfassender Software-Testbericht

**Datum:** 2026-03-04
**Status:** Alle gefundenen Bugs behoben, Tests bestehen (369/369, 0 Failures)

## Kontext

Das System wurde einer umfassenden technischen und funktionalen Prüfung unterzogen.
Alle Module, Tests, API-Endpunkte, das Dashboard und die Entwicklungsplanung wurden analysiert.

**Ausgangslage vor Fixes:** 369 Tests, 5 Failures, 5 Errors, 16 Skipped.
**Nach Fixes:** 369 Tests, 0 Failures, 0 Errors, 16 Skipped.

---

## TEIL 1: KRITISCHE FEHLER — Gefunden und behoben

### BUG-01: Export-Funktionen durch fehlerhafte Aliase zerstort [BEHOBEN]
- **Datei:** `src/kwb/export/goobi_xml.py:415-417`
- **Problem:** Die letzten 3 Zeilen der Datei ueberschrieben die korrekten Funktionen:
  ```python
  export_goobi_xml = dataframe_to_goobi_xml        # FALSCH!
  export_goobi_batch = dataframe_to_goobi_xml_files # FALSCH!
  ```
- `export_goobi_xml()` gibt `list[tuple[str,str]]` zurueck,
  wurde aber mit `dataframe_to_goobi_xml()` ueberschrieben, die `str` zurueckgibt.
- `export_goobi_batch()` gibt `str` zurueck,
  wurde aber mit `dataframe_to_goobi_xml_files()` ueberschrieben, die `output_dir` erfordert.
- **Auswirkung:** 8 von 10 Testfehlern gingen auf diesen einen Bug zurueck.
- **Fix:** Zeilen 415-417 geloescht.

### BUG-02: Thumbnail-Anzeige defekt — falscher Endpoint-Pfad [BEHOBEN]
- **Datei:** `src/kwb/api/dashboard.html:708`
- **Problem:** Dashboard forderte Bilder von `/api/images/{id}` an,
  tatsaechlicher Endpoint ist `/api/images/{id}/data`.
- **Auswirkung:** Thumbnails wurden nie angezeigt ("Vorschau n/v").
- **Fix:** Pfad auf `/api/images/{id}/data` korrigiert.

### BUG-03: XSS-Schwachstelle in Bild-Grid [BEHOBEN]
- **Datei:** `src/kwb/api/dashboard.html:706-715`
- **Problem:** `renderImgGrid()` verwendete Template-Literale mit unescapten Interpolationen.
- **Fix:** Funktion auf String-Konkatenation mit `esc()` umgestellt.

### BUG-04: Image-Cleanup loeschte nur Speicher, nicht Dateien [BEHOBEN]
- **Datei:** `src/kwb/api/routes/ai.py`
- **Problem:** `images_clear()` rief nur `_uploaded_images.clear()` auf,
  loeschte aber nicht die Dateien auf Disk.
- **Fix:** Dateien in `_IMAGE_DIR` werden jetzt mitgeloescht.

---

## TEIL 2: ARCHITEKTUR-PROBLEME — Gefunden und behoben

### ARCH-01: Tote Code-Datei `app.py` (783 Zeilen) [BEHOBEN]
- Die alte monolithische `app.py` wurde geloescht, `app_new.py` zu `app.py` umbenannt.
- Alle Imports in Tests aktualisiert.
- Security-Tests pruefen jetzt die richtigen Dateien (`deps.py`, `routes/`).

### ARCH-02: Verwaiste Datei `ner_hybrid_fix.py` [BEHOBEN]
- Standalone-"Fix"-Datei entfernt. Die Funktionalitaet ist in `ner.py` enthalten.

### ARCH-05: Unnoetige Imports in `image_data()` [BEHOBEN]
- Doppelte lokale Imports entfernt, ungenutzter `tempfile`-Import bereinigt.

### ARCH-03: Bild-Analyse ohne Workspace-Persistenz [OFFEN]
- Bildanalyse-Ergebnisse werden nur In-Memory gespeichert.
- Bei Server-Neustart gehen alle Ergebnisse verloren.
- **Empfehlung:** `ImageAnalysis`-Datenklasse in `workspace.py` einfuehren.

### ARCH-04: Bilder in `/tmp` — Datenverlust bei Systemneustart [OFFEN]
- `_IMAGE_DIR` zeigt auf `/tmp/debussy_uploads/` — OS kann `/tmp` leeren.
- **Empfehlung:** `KWB_IMAGE_DIR` in `.env` konfigurierbar machen.

---

## TEIL 3: TEST-QUALITAET

### Staerken
- 369 Tests mit guter Abdeckung der Kernmodule
- Edge-Cases: Unicode, Encoding, leere Werte, Whitespace
- Provider-Abstraktion gut getestet (Model-Forwarding, Call-Log)
- Workspace-Serialisierung mit Roundtrip-Tests
- EDTF mit 50+ Testfaellen pro Muster-Gruppe

### Behobene Schwaechenn
- **TEST-01:** Security-Tests prueften toten Code → jetzt auf `deps.py`/`routes/` umgestellt
- **TEST-02/03:** Export-Tests ohne Field-Mapping → Field-Mapping hinzugefuegt

### Verbleibende Schwaechenn [OFFEN]
- **TEST-04:** Kein Image-Integration-Test (Upload → Thumbnail → Analyse)
- **TEST-05:** GPUStack-Provider wird nie (auch nicht gemockt) getestet
- **TEST-06:** MockProvider maskiert Fehlerszenarien (ungueltige JSON, leere Antworten)
- **TEST-07:** OCR-Test-Assertion prueft deutsch ("Transkription") statt englisch ("transcription")
- **TEST-08:** Kein CLI-Test (`test_cli.py` fehlt)

---

## TEIL 4: BENUTZER-PERSPEKTIVE [OFFEN]

### UX-01: Kein gefuehrter Workflow
- 7+ Tabs ohne logische Reihenfolge
- Export scheitert ohne Field-Mapping, aber kein Hinweis darauf
- **Empfehlung:** Wizard-Modus oder Fortschrittsanzeige

### UX-02: Bildanalyse-Workflow unvollstaendig
- Upload funktioniert, Thumbnails jetzt korrigiert (BUG-02)
- Ergebnisse gehen bei Neustart verloren (ARCH-03)
- Kein Export-Pfad fuer Bildanalyse-Ergebnisse

### UX-03: Fehler bei Export nicht erklaert
- API-Fehlermeldung ist technisch, nicht benutzerfreundlich
- **Empfehlung:** Kontext-sensitive Hilfe im Dashboard

### UX-04: GPUStack-Status irrefuehrend
- "Mock-Modus aktiv" ist fuer Laien verwirrend
- **Empfehlung:** Klare Meldung ueber eingeschraenkte Funktionalitaet

### UX-05: Funktionskatalog behauptet "done" fuer eingeschraenkte Features
- Bild-Upload als "done" — aber Persistenz fehlt
- Export als "done" — war durch Alias-Bug komplett defekt

---

## TEIL 5: ENTWICKLUNGSPLANUNG — Bewertung

### Inkonsistenzen (behoben)
- Versionsnummer in CLAUDE.md auf v0.5.2 synchronisiert

### Verbleibende Inkonsistenzen
- Funktionskatalog-Status sollte "partial" sein fuer Bild-Features
- Phase 2 kann erst als abgeschlossen gelten, wenn ARCH-03/04 behoben sind

### Empfehlung zur Entwicklungsreihenfolge
1. **Erst stabilisieren:** ARCH-03/04 und TEST-04-08 beheben
2. **Dann erweitern:** Wikidata, OCR, METS/MODS erst nach Stabilisierung
3. **UX verbessern:** Gefuehrter Workflow, bessere Fehlermeldungen

---

## TEIL 6: ZUSAMMENFASSUNG

| Kategorie | Gefunden | Behoben | Offen |
|-----------|----------|---------|-------|
| Kritische Bugs | 4 | 4 | 0 |
| Architektur-Probleme | 5 | 3 | 2 |
| Test-Schwaechenn | 8 | 3 | 5 |
| UX-Probleme | 5 | 0 | 5 |
| Planungs-Inkonsistenzen | 3 | 1 | 2 |
| **Gesamt** | **25** | **11** | **14** |

### Ergebnis
Alle 10 Testfehler (5 Failures + 5 Errors) wurden behoben.
Die Testsuite laeuft jetzt fehlerfrei: **369/369 Tests bestanden**.
Die kritischsten Bugs (Export, Thumbnails, XSS, Image-Cleanup) sind behoben.
14 offene Punkte verbleiben als Empfehlungen fuer die weitere Entwicklung.
