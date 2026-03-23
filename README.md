# Debussy — KI-gestützte Kuratierungswerkbank

Debussy ist eine KI-gestützte Kuratierungswerkbank für GLAM-Sammlungsdaten.  
Die Anwendung unterstützt Daten-Ingest, strukturelle Analyse, Named Entity Recognition, EDTF-Normalisierung, Normdaten-Anreicherung, Bildanalyse, OCR sowie Export- und Pipeline-Workflows.

## Ziel

Debussy hilft dabei, Sammlungs- und Metadatensätze systematisch zu prüfen, anzureichern, kuratorisch zu überarbeiten und für nachgelagerte Systeme oder Exporte aufzubereiten.

## Kernfunktionen

- CSV-, XLSX-, XML- und PDF-Ingest
- Strukturelle Datenanalyse
- NER mit LLM, SpaCy und Hybrid-Ansatz
- EDTF-Normalisierung
- GND-, Wikidata- und GeoNames-bezogene Enrichment-Workflows
- Bildanalyse und OCR
- Workspace- und Dictionary-gestützte Review-Workflows
- Goobi-XML- und weitere Exportpfade
- Web-Dashboard für interaktive Arbeitsschritte

## Voraussetzungen

- Python 3.10 oder neuer
- Eine lokale virtuelle Umgebung wird empfohlen
- Für bestimmte KI-Workflows optional: GPUStack oder ein anderer konfigurierter Provider

## Installation

Virtuelle Umgebung anlegen und aktivieren, dann das Projekt mit allen Extras installieren:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -U pip
pip install -e .[all]
```

## Lokaler Start

Die Web-Anwendung lokal starten:

```bash
python -m kwb.api.app
```

Standardmäßig ist Debussy danach unter folgender Adresse erreichbar:

- http://localhost:8765

## Entwicklungsplanung per CLI

Debussy enthält eine CLI zur priorisierten Entwicklungsplanung auf Basis des Funktionskatalogs:

```bash
python -m kwb.cli plan --top 8
```

Das Kommando erzeugt priorisierte, konkrete Entwicklungsvorschläge aus `docs/FUNKTIONSKATALOG.md`, inklusive Begründung, nächster Schritte und Akzeptanzkriterien.

## Tests und Qualitätschecks

Vor Pull Requests sollten mindestens diese Checks lokal laufen:

```bash
ruff check .
pytest
```

## Konfiguration

Debussy unterstützt konfigurationsbasierte Provider- und Laufzeitparameter.  
Beispiele:

- `KWB_HOST`
- `KWB_PORT`
- `KWB_GPUSTACK_URL`
- `KWB_GPUSTACK_KEY`

Wenn keine externen KI-Dienste genutzt werden, sollten Tests möglichst mit Mock-Providern oder deterministischen Fixtures laufen.

## Dashboard-Tabs

| Tab | Funktion |
|-----|----------|
| Analyse | CSV laden, strukturelle Checks, Profile |
| KI-Werkzeuge | NER, Klassifikation, EDTF, Scans |
| KI-Konfiguration | Modelle, System-Prompts, Kategorien |
| Funktionen | Feature-Katalog mit Status |

## Entwicklungsworkflow

Empfohlener Ablauf für Änderungen:

1. Branch anlegen
2. Änderung lokal umsetzen
3. `ruff check .` und `pytest` ausführen
4. betroffene UI- oder API-Flows lokal prüfen
5. Pull Request mit dem PR-Template erstellen
6. CI grün abwarten
7. Review und Merge

## Hinweise für KI-gestützte Entwicklung

Im Repository gelten zusätzliche Arbeitsregeln für agentische Entwicklung über `AGENTS.md`.

Wichtige Grundsätze:

- keine direkten Änderungen auf `main`
- minimale, gezielte Änderungen
- Bugfixes nach Möglichkeit mit Test absichern
- bei UI- oder Workflow-Änderungen lokale Verifikation durchführen
- externe Abhängigkeiten in Tests möglichst mocken

## Projektstatus

Der detaillierte Umsetzungsstand, die Testabdeckung und die empfohlene Entwicklungsreihenfolge werden in `docs/FUNKTIONSKATALOG.md` dokumentiert.

## Lizenz

MIT