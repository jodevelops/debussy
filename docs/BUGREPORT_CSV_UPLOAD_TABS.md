# Debussy Bug Report: CSV-Upload wird nicht geladen & Tabs reagieren nicht

## 1. Zusammenfassung

In der aktuellen Dashboard-UI wurden zwei zusammenhängende Fehlersymptome gemeldet:

1. **CSV-Upload scheint visuell aktiv**, aber die Datei wird nicht effektiv in den Workflow übernommen.
2. **Tabs sind nicht aktiv / nicht klickbar** (Navigation reagiert nicht wie erwartet).

Die statische Codeanalyse zeigt mehrere plausible Fehlerursachen. Die höchste Priorität hat eine fragile Frontend-Initialisierung: Bereits ein früher JavaScript-Fehler kann Upload- und Tab-Interaktionen gleichzeitig „still“ ausfallen lassen.

---

## 2. Beobachtete Symptome (aus Nutzersicht)

- Datei-Dialog lässt sich öffnen.
- Dropzone ist sichtbar und wirkt aktiv.
- Nach Auswahl/Drop erfolgt aber keine verwertbare Datenaufnahme (kein funktionsfähiger weiterer Ablauf).
- Tabs lassen sich nicht öffnen bzw. reagieren nicht.

Diese Kombination ist typisch für ein **JS-Initialisierungs-/Runtime-Problem im Frontend** (HTML/CSS laden, Interaktionslogik fällt jedoch teilweise oder vollständig aus).

---

## 3. Untersuchungsumfang

Analysierte Hauptdateien:

- `src/kwb/api/parts/dashboard.js`
- `src/kwb/api/dashboard.html`
- `src/kwb/api/parts/dashboard.css`
- `src/kwb/api/routes/analyze.py`
- `src/kwb/api/routes/workspace.py`
- `src/kwb/api/app.py`

Methodik:

- Statische Codeanalyse von Upload-, Tab-, Init- und API-Datenfluss.
- Plausibilitätsprüfung zwischen Frontend-Requestformaten und Backend-Responseformaten.
- Sichtung von Selektoren/Event-Bindings auf Robustheit gegenüber Teilfehlern.

---

## 4. Technische Befunde (Root-Cause-Hypothesen)

## 4.1 Inkonsistenz im Field-Mapping-API-Vertrag (klarer Funktionsbug)

### Befund

Frontend und Backend verwenden bei `/api/workspace/field-mapping` unterschiedliche Datenstrukturen:

- Frontend sendet aktuell `{"mapping": {...}}` (Dictionary), liest `ex.mapping`.
- Backend erwartet `{"mappings": [...]}` (Liste von `FieldMapping`-Objekten), liefert `{"mappings": [...]}`.

### Wirkung

- Mapping-Daten werden nicht korrekt gespeichert/zurückgeladen.
- Folgefehler in Mapping-abhängigen Schritten (insb. Export) sind wahrscheinlich.
- Führt zu „UI wirkt kaputt“, obwohl Ursache ein stiller Datenvertragsfehler ist.

### Priorität

**Hoch** (P1) – direkter Functional Break.

---

## 4.2 Fragile globale Frontend-Initialisierung (sehr wahrscheinlich für Upload+Tabs gemeinsam)

### Befund

Mehrere Event-Bindings erfolgen unmittelbar und ohne Schutzlogik. Wenn im Startup-Pfad ein Fehler auftritt, kann die Initialisierung nachfolgender Features abbrechen.

Typische Muster:

- Direkte Zuweisung ohne Null-Guard (`fi.onchange = ...`, `$('exp-ds').onchange = ...`).
- Große IIFE-Initialisierung mit vielen Aufrufen hintereinander, ohne zentrale Fehlerisolation.

### Wirkung

- Bei einem frühen JS-Error können Tabs nicht mehr reagieren.
- Upload-Handler kann ebenfalls nicht mehr sauber greifen.
- Für User sichtbar als „Dropzone/Buttons sind da, aber nichts funktioniert richtig“.

### Priorität

**Kritisch** (P0) – passt exakt zur Symptomkombination.

---

## 4.3 Tab-Bindung nur auf einen festen Container (`bindTabs('dt')`)

### Befund

Der Tab-Mechanismus wird explizit nur für den Daten-Subtab mit ID `dt` gebunden.

### Wirkung

- Erweiterungen/Refactorings sind fehleranfällig.
- Bereits kleine DOM-Änderungen können Tab-Klickbarkeit unbeabsichtigt brechen.
- Wartbarkeit und Fehlertoleranz sinken.

### Priorität

**Mittel** (P2) – Stabilitäts- und Architekturthema mit UX-Auswirkung.

---

## 4.4 Upload-Dateiverwaltung per Dateiname (Kollisionen) + fehlender Input-Reset

### Befund

`ufiles` wird nach `f.name` indiziert. Gleichnamige Dateien überschreiben sich. Zusätzlich wird der Datei-Input nach Verarbeitung nicht zurückgesetzt.

### Wirkung

- Upload wirkt inkonsistent (insb. bei gleichen Dateinamen aus unterschiedlichen Ordnern).
- Erneute Auswahl derselben Datei triggert unter Umständen keinen `change`.
- Kann als „CSV wird nicht geladen“ wahrgenommen werden.

### Priorität

**Mittel** (P2) – Edge Cases, aber realistisch im Alltag.

---

## 5. Risikoanalyse

## 5.1 Produktionsrisiken

- Funktionsketten brechen ohne klare Fehlermeldung (schlechte Diagnosefähigkeit).
- Nutzer verlieren Vertrauen in Upload-/Tab-Workflow.
- Mehr Supportaufwand wegen schwer reproduzierbarer „UI reagiert nicht“-Meldungen.

## 5.2 Entwicklungsrisiken

- API-Vertrag driftet weiter auseinander (Frontend/Backend).
- Regressionen bei künftigen UI-Änderungen durch fehlende Init-Härtung.
- Höhere Kosten für spätere Stabilisierung.

---

## 6. Konkrete Entwicklungsempfehlungen / Bugfix-Plan

## 6.1 P0: Frontend-Init robust machen (Upload/Tabs absichern)

1. Initialisierung in Teilfunktionen aufteilen:
   - `initNav()`
   - `initTabs()`
   - `initUpload()`
   - `initPanels()`
2. Jede Funktion mit lokaler Fehlerisolierung (`try/catch`) versehen.
3. Elementzugriffe konsequent mit Existenzprüfung absichern.
4. Bei Init-Fehlern sichtbaren Banner anzeigen + `console.error` mit Kontext.

**Akzeptanzkriterium:** Ein Fehler in einem Teilmodul darf nicht mehr das gesamte UI lahmlegen.

---

## 6.2 P1: Mapping-API-Vertrag vereinheitlichen

1. Einheitliches Payloadformat definieren (empfohlen: `mappings[]`).
2. Frontend-Funktionen `saveFM()` und `loadFMCols()` auf dieses Format umstellen.
3. Interne UI-Struktur `fmMapping` sauber in/aus `mappings[]` konvertieren.
4. Kurz-Dokumentation im Code ergänzen.

**Akzeptanzkriterium:** Mapping speichern/laden ist deterministisch und roundtrip-sicher.

---

## 6.3 P2: Tabs generisch und lokal binden

1. Tab-Binding über alle `.tabs`-Container iterieren.
2. `bindTabs()` auf Element- statt ID-Basis umbauen.
3. Panel-Toggle strikt auf den zugehörigen Container scopen.

**Akzeptanzkriterium:** Tabverhalten bleibt stabil bei DOM-Erweiterungen.

---

## 6.4 P2: Upload-Datenmodell verbessern

1. Dateischlüssel nicht nur über Namen bilden (ID aus Name+Size+mtime o.ä.).
2. UI soll Kollisionen transparent machen.
3. Nach Verarbeitung `fi.value = ''` setzen.

**Akzeptanzkriterium:** Wiederholte Uploads + gleichnamige Dateien verhalten sich erwartbar.

---

## 7. Teststrategie (empfohlen)

## 7.1 Frontend-Interaktions-Checks

- Upload per Click und per Drag&Drop.
- Re-Upload derselben Datei.
- Zwei gleichnamige Dateien aus verschiedenen Ordnern.
- Tabwechsel vor/nach Upload, inklusive Fehlerfällen.

## 7.2 API-Vertrags-Tests

- POST `/api/workspace/field-mapping` mit `mappings[]`.
- GET `/api/workspace/field-mapping` und Roundtrip-Vergleich.
- Negativtests bei unvollständigen Mapping-Objekten.

## 7.3 Regressionstests

- Exportpfade nach Mapping (XML/CSV/JSON-LD) verifizieren.
- Smoke-Test des Dashboards nach Init-Refactor.

---

## 8. Kurzfristige Hotfix-Reihenfolge

1. **P0:** Init-Härtung + defensives Binding.
2. **P1:** Mapping-Vertrag reparieren.
3. **P2:** Tabs generisch binden.
4. **P2:** Upload-Kollisionen + Input-Reset.

---

## 9. Erwarteter Nutzen nach Fix

- CSV-Upload wird zuverlässig verarbeitet.
- Tabs reagieren konsistent.
- Fehler werden sichtbar statt „still“.
- Geringere Regressionen bei UI-Weiterentwicklung.
- Deutlich bessere Wartbarkeit durch klaren API-Vertrag.

---

## 10. Abschluss

Die gemeldeten Symptome sind mit hoher Wahrscheinlichkeit kein einzelner „Mini-Bug“, sondern ein **Cluster aus Frontend-Robustheitslücken plus mindestens einem klaren API-Vertragsfehler**. Die empfohlenen Maßnahmen sind überschaubar, priorisierbar und liefern schnell stabilere UX.
