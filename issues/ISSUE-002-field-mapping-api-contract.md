# ISSUE-002 — Field-Mapping API-Vertrag vereinheitlichen (P1)

## Typ
Bug / API-Vertragsfehler

## Priorität
P1 (hoch)

## Problem
Frontend und Backend verwenden unterschiedliche Payload-/Response-Formate beim Field Mapping.

- Frontend verwendet `mapping` / `ex.mapping`
- Backend erwartet/liefert `mappings` (Liste)

Dadurch ist Speichern/Laden nicht roundtrip-sicher.

## Betroffene Bereiche
- `src/kwb/api/parts/dashboard.js`
- `src/kwb/api/routes/workspace.py`

## Zielzustand
Ein einheitlicher, stabiler Vertrag für GET/POST `/api/workspace/field-mapping`.

## Umsetzung
- Frontend auf `mappings[]` umstellen:
  - `saveFM()` sendet `{mappings:[...]}`
  - `loadFMCols()` liest `ex.mappings`
- UI-interne Datenstruktur sauber in/aus Liste konvertieren.
- API-Vertrag im Code kurz dokumentieren.

## Akzeptanzkriterien
- POST → GET Roundtrip liefert konsistente Daten.
- Mapping bleibt nach Reload erhalten und wird korrekt im UI angezeigt.
- Exportpfad nutzt korrekt gespeichertes Mapping.

## Testhinweise
- API-Test: POST/GET Roundtrip inkl. Negativfall.
- UI-Test: Mapping setzen, speichern, neu laden, Export-Vorschau prüfen.
