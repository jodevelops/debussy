# Debussy Re-Check Report (aktualisiert): CSV-Upload & Tabs

## Status (aktuell)

Die ursprünglichen Hauptprobleme wurden **größtenteils behoben**:

- Tabs sind nicht mehr starr an `bindTabs('dt')` gekoppelt, sondern werden generisch über `.tabs` initialisiert.
- Die Initialisierung ist in abgesicherte Schritte geteilt (mit `try/catch`), wodurch ein Teilfehler nicht mehr alles blockiert.
- Der Field-Mapping-Vertrag ist auf `mappings[]` vereinheitlicht (Frontend ↔ Backend).

Zusätzlich wurde jetzt die Upload-Robustheit weiter verbessert:

- Upload-Namen werden bei Kollisionen eindeutig gemacht (z. B. `datei (2).csv`).
- CSV-Dateien mit gleichem Originalnamen überschreiben sich im Upload-Flow nicht mehr.
- Der Datei-Input wird nach Verarbeitung zurückgesetzt.

---

## Verbleibende Restpunkte

- Die interne Dateiverwaltung bleibt in-memory (kein Persistenzlayer über Browser-Reload hinaus) – erwartbar für die aktuelle Architektur.
- Für langfristige Stabilität wären UI-E2E-Tests für Upload + Tab-Navigation sinnvoll.

---

## Kurzfazit

Der zuvor gemeldete „alles blockiert“-Zustand ist im aktuellen Stand nicht mehr der erwartete Normalfall. Die Kernursachen (Init-Fragilität + Mapping-Drift) sind adressiert; Dateinamenskollisionen im Upload wurden nachgezogen.
