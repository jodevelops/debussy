# ISSUE-004 — Upload-Keying und Datei-Input-Reset verbessern (P2)

## Typ
Bug / UX-Robustheit

## Priorität
P2 (mittel)

## Problem
Dateien werden per Dateiname als Key gespeichert (`ufiles[f.name] = f`). Gleichnamige Dateien können sich überschreiben. Zudem kann Wieder-Auswahl derselben Datei je nach Browser nicht erneut triggern.

## Betroffene Bereiche
- `src/kwb/api/parts/dashboard.js`

## Zielzustand
Upload verhält sich deterministisch bei gleichnamigen Dateien und wiederholter Auswahl.

## Umsetzung
- Stabilen internen Key verwenden (z. B. Name+Size+LastModified oder UUID).
- Anzeige von internem Key entkoppeln (UI zeigt lesbaren Dateinamen).
- Nach Verarbeitung `fi.value=''` setzen.
- Optional: Hinweis bei Kollisionen.

## Akzeptanzkriterien
- Zwei gleichnamige Dateien können gleichzeitig ausgewählt/verwaltet werden.
- Gleiches File kann direkt erneut ausgewählt werden.
- Dateiliste bleibt konsistent und nachvollziehbar.

## Testhinweise
- Upload von zwei gleichnamigen Dateien aus unterschiedlichen Ordnern.
- Re-Upload derselben Datei ohne Seitenreload.
