# ISSUE-003 — Tab-Binding generisch und container-lokal machen (P2)

## Typ
Verbesserung / Robustheit

## Priorität
P2 (mittel)

## Problem
Tabs werden derzeit über festen Container (`bindTabs('dt')`) gebunden. Das ist bei DOM-Änderungen/Erweiterungen fragil.

## Betroffene Bereiche
- `src/kwb/api/parts/dashboard.js`

## Zielzustand
Tab-Binding funktioniert für alle Tab-Container robust und unabhängig von fester ID.

## Umsetzung
- `bindTabs` auf Elementbasis umstellen.
- Über alle `.tabs` iterieren und binden.
- Nur lokale zugehörige `.tp` Panels toggeln.

## Akzeptanzkriterien
- Bestehende Data-Tabs funktionieren unverändert.
- Neue `.tabs`-Container funktionieren ohne zusätzliche JS-Änderung.
- Keine Seiteneffekte auf andere Panelbereiche.

## Testhinweise
- Klicktests für alle vorhandenen Tabs.
- Regression bei zukünftigen zusätzlichen Tab-Containern.
