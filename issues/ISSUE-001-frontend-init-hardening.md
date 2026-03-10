# ISSUE-001 — Frontend-Init härten (P0)

## Typ
Bug / Stabilität

## Priorität
P0 (kritisch)

## Problem
Die Dashboard-Interaktion ist fragil, weil zentrale Event-Bindings im Top-Level ohne defensive Guards initialisiert werden. Ein früher JS-Fehler kann Upload und Tab-Interaktionen gleichzeitig ausfallen lassen.

## Betroffene Bereiche
- `src/kwb/api/parts/dashboard.js`
- Upload-Bindings (`fi`, `uz`)
- Navigation und Tab-Initialisierung

## Reproduktion (typisch)
1. Dashboard öffnen.
2. CSV auswählen oder Dropzone verwenden.
3. Tabs wechseln.
4. Beobachtung: UI wirkt teilweise „sichtbar aber inaktiv“ (je nach Fehlerpfad).

## Zielzustand
Ein Teilfehler in der Initialisierung darf nicht mehr die gesamte UI blockieren.

## Umsetzung
- Initialisierung in Funktionen aufteilen:
  - `initNav()`
  - `initTabs()`
  - `initUpload()`
  - `initAsyncPanels()`
- Pro Init-Funktion `try/catch` + `console.error('[initX]', err)`.
- Vor DOM-Bindings Existenzchecks einbauen.
- Optional: kleines Dev-Diagnostic-Banner bei Init-Fehlern.

## Akzeptanzkriterien
- Upload bleibt funktionsfähig, selbst wenn ein nicht-kritisches Panel-Init fehlschlägt.
- Tabs bleiben klickbar bei Teilfehlern.
- Fehler sind in Konsole klar den Init-Modulen zugeordnet.

## Testhinweise
- Manueller Smoke-Test: Upload (Click + DnD), Tabwechsel, wiederholtes Laden.
- Optional UI-E2E-Test für „Init-Teilfehler blockiert Kernfunktionen nicht“.
