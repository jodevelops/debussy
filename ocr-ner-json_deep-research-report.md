# NER‑zu‑Normdaten‑Dictionary‑Editor in einer FastAPI‑Browser‑App: Stand der Technik und wiederverwendbare Vorarbeiten

## Problemstellung und Zielbild

Ihr Vorhaben kombiniert drei Aufgaben, die in vielen Digital‑Humanities‑/GLAM‑Workflows getrennt behandelt werden, aber in der Praxis eng zusammenhängen: (a) automatische Erkennung von Entitäten (NER) aus Metadaten und OCR‑Text, (b) kuratorische Normalisierung/Deduplizierung zu stabilen „Dictionary‑Einträgen“, und (c) Verlinkung dieser Einträge auf Normdaten (z. B. externe Identifikatoren und URIs). Genau diese „Human‑in‑the‑Loop“-Schicht entscheidet später darüber, ob aus NER‑Treffern tatsächlich belastbare, durchsuchbare und referenzierbare Daten werden.

Ihr gewünschtes JSON‑Dictionary‑Format (pro Entry mindestens: interne ID, Kategorie nach spaCy‑ähnlicher Typologie, Schreibweise in der Quelle, normalisierte Schreibweise, Provenienz/Quelle, sowie `record_ID` zur Rückverbindung in Quell‑Datensätze) entspricht fachlich einer Trennung zwischen:

* **Mention/Occurrence‑Ebene**: „Was wurde wo (in welchem Record) so geschrieben?“ (Quelle‑Schreibweise + `record_ID` + ggf. Kontext/Offsets)  
* **Entity/Entry‑Ebene**: „Welcher kanonische Eintrag ist das?“ (Normalform + Typ + Normdatenlinks + interne ID)

`record_ID` ist dabei nicht nur ein „nice to have“, sondern Kern der Nachvollziehbarkeit: Ohne explizite Occurrence‑Referenzen verlieren Sie die Möglichkeit, automatisierte Vorschläge zu auditieren, Korrekturen zu propagieren (z. B. Merge/Split), oder in der UI vom Dictionary‑Entry zurück in die betroffenen Records zu springen (und dort Korrektur/Highlighting zu zeigen).

Wichtig für die Einordnung: Das GitHub‑Repository `jodevelops/debussy` ist über das Web‑Fetching hier nicht öffentlich erreichbar (HTTP 404), daher kann ich die konkrete Architektur/Ordnerstruktur Ihrer App nicht verifizieren; die folgenden Aussagen sind deshalb „repo‑agnostisch“ formuliert, aber bewusst so gewählt, dass sie sich unmittelbar in eine typische FastAPI‑gestützte Browser‑App integrieren lassen. citeturn2view0

## Was es bereits gibt und wie nah es an Ihrem Ziel ist

### Ein sehr naher Treffer: entity["organization","neat","named entity annotation tool"]

Für Ihr konkretes Profil („OCR‑/Token‑Korrektur + NER‑Tags + optionale Authority‑ID + browserbasiert“) ist **neat** auffallend nah am Zielbild:

* **Reines HTML+JavaScript**, läuft lokal im Browser ohne Server‑Komponente (damit extrem leicht in bestehende Web‑Apps einzubetten, z. B. als statische Route oder „micro‑frontend“). citeturn5view0  
* Datenformat ist **tabellarisch/TSV** in IOB2‑Logik; neat erweitert dieses Format optional um eine **„ID“-Spalte für Authority‑IDs** und dokumentiert explizit, dass dafür u. a. **Wikidata‑IDs** vorgesehen sind. citeturn8view0turn5view0  
* neat ist auf OCR‑Realität ausgerichtet: Es kann Token‑Text/Tokenisierung korrigieren (z. B. OCR‑Fehler) und bezieht sich als Ausgangsdaten auf **PAGE‑XML**; außerdem unterstützt es das Einblenden von Bildausschnitten über **IIIF** (wenn Bounding Boxes vorhanden sind). citeturn5view0  
* Lizenzierung ist **Apache‑2.0**, in vielen Projekten gut kompatibel. citeturn5view0  

Was neat (in der dokumentierten Standardform) **nicht** direkt löst, aber als sehr guter Startpunkt dienen kann:

* Es erzeugt nicht Ihr gewünschtes **JSON‑Dictionary** out‑of‑the‑box, sondern speichert tabellarisch. citeturn5view0  
* Es ist eher ein **Annotation/Editing‑UI** pro Dokument/Tokenstrom als ein systematischer „Entity‑Katalog“ mit globaler Deduplizierung/Referenzen über viele Records hinweg (genau das wäre Ihre zusätzliche Schicht).  

Trotzdem: Wenn Sie „unmittelbar nutzbare Vorarbeit in einer Browser‑App“ suchen, ist neat wahrscheinlich die **schnellste funktionierende Grundlage**, die Sie in eine FastAPI‑Route übernehmen und schrittweise auf Ihr JSON‑/Entity‑Modell umbauen können. citeturn5view0turn8view0  

### Klassische Web‑Annotation für NER: entity["organization","doccano","text annotation tool"]

**doccano** ist ein verbreitetes Open‑Source‑Tool für Textannotation (u. a. Sequenzlabeling/NER) mit UI und API‑Ansatz. citeturn10search0turn10search28  
Für Ihr Ziel ist doccano vor allem dann interessant, wenn Sie bereits eine solide „Annotation‑Projekt‑/Task‑/User“-Logik brauchen.

Aber: doccano ist primär auf **Labels/Spans** ausgerichtet („Entity‑Typ“ + Positionen), nicht auf „Entity‑Katalogeinträge mit Normdaten pro Entry“ als first‑class concept. Es gibt im Standardmodell typischerweise keine dedizierte „Authority‑ID‑pro‑Entity‑Span“-UX, die sofort Ihren Minimalsatz (inkl. Normdaten + Normalform + `record_ID`‑Rückbindung) abbildet; so etwas wäre eher ein **Customizing/Erweiterung**. (Diese Aussage ist eine Design‑Einordnung; die belastbaren Fakten sind: Aufgabenfokus und Featurebeschreibung von doccano.) citeturn10search0turn10search28  

### Multimodal/ OCR‑Workflow‑UI: entity["organization","Label Studio","data labeling tool"]

**Label Studio** ist Open Source und deckt viele Datentypen ab (Text, Bilder, Video, Audio etc.). citeturn10search1  
Für OCR‑Zentrierung ist relevant, dass es explizite OCR‑Templates anbietet (Regionen markieren + Transkription). citeturn10search17  

Für Ihr Vorhaben ist Label Studio attraktiv, wenn:

* Sie OCR‑Bounding‑Boxes/Regionen **interaktiv** bearbeiten/validieren wollen und NER eher als nachgelagerte Schicht betrachten.

Weniger „sofort passend“ ist es, wenn:

* Ihr Hauptartefakt ein **konsolidiertes, normdatenverlinktes Dictionary** ist (Label Studio erzeugt primär Annotation‑Outputs pro Task/Item; die Entity‑Katalogisierung wäre wieder zusätzliche Logik). citeturn10search1turn10search17  

### Semantische Annotation mit Knowledge‑Base‑Linking: entity["organization","INCEpTION","semantic annotation platform"]

**INCEpTION** ist eine ausgereifte semantische Annotationsplattform (Apache‑2.0), die explizit Knowledge‑Base‑Anbindung und Entity‑Linking unterstützt. citeturn10search10turn10search26turn10search2  
Besonders relevant:

* Das Knowledge‑Base‑Modul kann lokale KBs verwalten oder an **remote KBs via SPARQL** anbinden (inkl. vorkonfigurierter KB‑Beispiele wie Wikidata), und diese KBs können für **Entity Linking** in der Annotation genutzt werden. citeturn10search2  

Für Ihr Ziel ist INCEpTION inhaltlich sehr passend (weil es genau „Annotation + Linking + Knowledge Management“ ernst nimmt). Für die von Ihnen gewünschte „unmittelbar nutzbare“ Integration in eine FastAPI‑Browser‑App ist es aber häufig **eher ein Sidecar‑System** als ein „einfach einbettbares Modul“, weil es eine eigene Plattform ist (Deployment/SSO/DB/Projektverwaltung etc.). (Auch das ist eine Architektur‑Einordnung; die belastbaren Fakten sind KB‑Linking/Remote‑SPARQL und Lizenz.) citeturn10search2turn10search26  

### Geo‑ und Semantic Annotation: entity["organization","Recogito","semantic annotation platform"]

**Recogito** ist eine geisteswissenschaftlich/digital‑humanities‑nahe Plattform für semantische Annotation von Texten und Bildern („identify and mark named entities“). citeturn10search27  
Spannend für Ihren Normdaten‑Fokus ist insbesondere die Geo‑Ausrichtung: Es existiert z. B. ein Utility‑Projekt, das aus GeoNames‑Daten **eigene Gazetteer‑Pakete** für Recogito baut. citeturn10search3  

Auch hier gilt: Sehr wertvolle Vorarbeit als Referenz/Workflow‑Blueprint, aber als „in eine FastAPI‑App reinziehen“ meist eher über Export/Import/API oder als separater Dienst als über „Code direkt in die bestehende App integrieren“. citeturn10search27turn10search3  

image_group{"layout":"carousel","aspect_ratio":"16:9","query":["qurator-spk neat named entity annotation tool screenshot","doccano named entity recognition annotation interface screenshot","INCEpTION knowledge base entity linking screenshot","Recogito annotation interface screenshot"],"num_per_query":1}

## Normdaten‑Anreicherung: praktikable Zugriffsmuster und „Reconciliation“ als Hebel

### GND‑Lookup über lobid‑gnd statt „direkt DNB parsen“

Für GND‑Verlinkung ist **lobid‑gnd** als „human and machine interface“ besonders praktisch, weil es eine klar dokumentierte Web‑API liefert und als Antwortformat **JSON‑LD** anbietet. citeturn7search0turn7search8turn7search36  
Für die unmittelbare Integration in eine Web‑App sind zwei Dinge wertvoll:

* Sie bekommen **Such‑/Autocomplete‑fähige Responses** (JSON‑LD), die sich in einem Typeahead‑Widget sehr gut nutzen lassen. citeturn7search0turn7search12  
* lobid‑gnd ist explizit in **OpenRefine‑Workflows integrierbar** (siehe die gnd.network‑Einordnung und die lobid‑Dokumentation). citeturn7search36turn7search8  

Ein naheliegendes Design ist deshalb: Ihr Editor ruft **nicht** direkt verschiedenste Authority‑APIs unterschiedlich an, sondern kapselt GND‑Lookup serverseitig als `GET /authority/gnd?q=...` und nutzt intern lobid‑gnd.

### GeoNames: JSON‑Services, Username‑Pflicht und Lizenz/Attribution

GeoNames bietet eine Reihe von REST‑Services; für Javascript‑Nutzung wird explizit empfohlen, die **JSON‑Services** zu verwenden. citeturn7search1  
Praktisch wichtig für Ihre App:

* Für die freien Webservices ist der Parameter `username=<geonames username>` verpflichtend (auch dokumentiert im GeoNames‑Blog zur Domain `api.geonames.org`). citeturn7search33turn7search1  
* GeoNames stellt die Daten als **CC‑BY** bereit, fordert also Attribution und weist auf „as is“/keine Gewährleistung hin; kommerzielle Nutzung ist laut Selbstdokumentation erlaubt. citeturn7search9turn7search5  

Für Ihre Architektur heißt das fast immer: GeoNames‑Requests lieber **serverseitig** proxyen (API‑Key/Username nicht im Frontend), Caching einziehen, und in den exportierten JSON‑Artefakten/Impressum Attribution sauber abbilden. citeturn7search9turn7search33  

### Wikidata für Kandidatenfindung und als „Identifier‑Hub“

Wikidata stellt mehrere Zugriffswege bereit (Übersicht über „Data access“). citeturn7search2  
Für einen UI‑Editor ist besonders wichtig, dass es ein Such‑/Autocomplete‑fähiges API‑Modul gibt: `wbsearchentities` ist genau das Endpoint‑Prinzip, das auch in Wikibase‑GUIs für Suchleisten/Autocomplete genutzt wird (Beispiel‑URL dokumentiert in der Wikibase‑SDK‑Doku). citeturn7search26turn7search6  

Für Ihre Normdaten‑Ziele ist Wikidata außerdem ein sehr nützlicher **„Identifier‑Hub“**, weil Wikidata für viele Normdateien eigene „external identifier“-Properties pflegt. Allgemein erläutert Wikidata, dass viele Properties den Datentyp „external identifier“ haben und dafür Listen/Übersichten existieren. citeturn9search18  
Konkrete Brücken, die für Sie zentral sind:

* **GND‑ID** in Wikidata ist Property **P227** (Property‑Seite). citeturn9search0  
* **GeoNames‑ID** in Wikidata ist Property **P1566** (Property‑Seite). citeturn9search1  

Das eröffnet eine pragmatische Wahlmöglichkeit im Editor:

* Entweder Sie erfassen **direkt** GND/GeoNames/QID in Ihren JSON‑Entries, oder  
* Sie priorisieren die **QID** als primäre Normreferenz und „synchronisieren/ergänzen“ (wo vorhanden) die korrespondierenden IDs über P227/P1566.

In der Praxis ist es sinnvoll, beides zu unterstützen, weil nicht jeder Wikidata‑Eintrag die gewünschten externen IDs vollständig trägt (und weil Sie für Auditing/Provenienz manchmal direkt auf die Authority‑Quelle zeigen wollen, nicht nur indirekt über Wikidata). (Diese Schlussfolgerung ist eine Implementations‑Empfehlung; die Brücken‑Fakten sind P227/P1566.) citeturn9search0turn9search1  

### Reconciliation als UI‑Paradigma: entity["organization","OpenRefine","data wrangling tool"]

OpenRefine ist in diesem Kontext weniger als Tool, das Sie „einbetten“, sondern als **Paradigma** extrem hilfreich: „Reconciliation“ meint das Matching lokaler Strings gegen externe Wissensbasen und das Zurückschreiben stabiler IDs.

Zwei belastbare Punkte aus der aktuellen Doku:

* OpenRefine enthält **Wikidata‑Reconciliation** in der Standardinstallation. citeturn7search3turn7search7  
* Es existiert ein etablierter öffentlicher Wikidata‑Reconciliation‑Endpoint (`wikidata.reconci.link`), der explizit für OpenRefine gedacht ist. citeturn7search11  

Übertrag auf Ihre App: Wenn Sie für Ihren Editor ein „Reconciliation‑Widget“ bauen (String → Kandidatenliste → Score/Preview → Commit), ist OpenRefine eine sehr gute Referenz für UX‑Ablauf und API‑Shape – auch wenn Sie die Umsetzung viel schlanker halten.

## Datenmodell für Ihr JSON‑Dictionary und warum die Trennung Entry/Mention wichtig ist

Ein robustes Modell für Ihr Ziel („valide JSON dictionaries“ + Rückverbindung) entsteht meist nicht als „eine einzige Liste von flachen Entries“, sondern als zwei logisch unterschiedliche Strukturen:

* **DictionaryEntry**: stabiler Katalogeintrag (einmalig pro „konzeptuell gleicher“ Entität)  
* **Mention/Occurrence**: konkrete Vorkommen in Records (viele pro Entry)

Ein minimales, aber in der Praxis tragfähiges JSON pro Entry könnte so aussehen (Beispiel nur zur Illustration; Schema/Validierung würden Sie mit Pydantic/JSON‑Schema erzwingen):

```json
{
  "id": "term_000123",
  "category": "PER",
  "term_source": "Joh. Seb. Bach",
  "term_normalized": "Johann Sebastian Bach",
  "source": "Metadaten",
  "authority": {
    "wikidata_qid": "Q1339",
    "gnd_id": "11850529X",
    "geonames_id": null
  },
  "occurrences": [
    {"record_id": "meta_98765"},
    {"record_id": "ocr_45678"}
  ]
}
```

Warum meistens zusätzlich strukturierter als „nur“ `record_ID`:

* In OCR‑/Text‑Workflows ist `record_ID` allein oft nicht genug; Sie möchten häufig mindestens auch **Kontext** (Snippet) oder **Offsets/Bounding‑Boxes**, um im UI präzise zurückzuspringen. neat zeigt sehr deutlich, warum Bounding‑Boxes/IIIF‑Snippets für OCR‑QC wertvoll sind. citeturn5view0  
* Für Merge/Split‑Operationen brauchen Sie häufig eine Mention‑ID (oder zusammengesetzte Keys wie `record_id + start + end`), sonst wird es schwer, Korrekturen sauber zu versionieren.

Eine praxistaugliche Normalisierungskaskade (ohne „Semantik zu raten“) ist typischerweise:

* Unicode‑Normalisierung (NFC), Whitespace‑Kollaps, Trimmen  
* ggf. „Anzeigeform“ vs „Suchform“ trennen (z. B. Casefold)  
* Für Personen: heuristische Auflösung abgekürzter Vornamen/Initialen eher als „unsicherer Vorschlag“, nicht als automatische Normalform – und dann im Editor bestätigen lassen.

Diese Art von vorsichtiger Normalisierung ist besonders wichtig, weil Ihre Normdaten‑Links sonst „scheinpräzise“ werden (falsche QID/GND), was später schwerer zu reparieren ist als eine unvollständige Verlinkung.

## Integrationsarchitektur in einer FastAPI‑gestützten Browser‑App

### E2E‑Datenfluss vom NER/OCR‑Output zum Editor

Ein bewährter Anschluss‑Workflow sieht so aus:

1. **Ingestion** eines Records (Metadaten oder OCR‑Transkript) und Speicherung als „Quelle“ mit stabiler `record_id`.  
2. NER/OCR‑Pipeline schreibt **Mentions** (mit Typ, Textspanne, Confidence, Quelle).  
3. Editor zeigt „Inbox“ der neuen Mentions, gruppiert nach (a) Normalform‑Vorschlag oder (b) String‑Ähnlichkeit, und ermöglicht:
   * „Create new Entry“
   * „Link to existing Entry“
   * „Merge/Split“
4. Beim Commit triggert der Editor einen **Reconciliation‑Schritt**: Candidate‑Lookup gegen Authority‑Adapter (GND via lobid‑gnd, GeoNames via GeoNames‑JSON‑Service, Wikidata via `wbsearchentities`). citeturn7search0turn7search1turn7search26turn9search0turn9search1  
5. Speicherung (Entry + Occurrence‑Links), Export als JSON‑Dictionary oder als View.

### Authority‑Adapter als FastAPI‑Endpoints

Praktisch robuste Adapter‑Schicht (serverseitig, damit Sie Caching, Rate‑Limit, Credentials und konsistente Antwortformate kontrollieren):

* `GET /authority/wikidata?q=...&lang=de&type=...` (intern: `wbsearchentities`) citeturn7search26turn7search6  
* `GET /authority/gnd?q=...` (intern: lobid‑gnd JSON‑LD Search) citeturn7search0turn7search12turn7search36  
* `GET /authority/geonames?q=...` (intern: GeoNames JSON; Username serverseitig) citeturn7search1turn7search33turn7search9  

Wichtig ist dabei nicht nur das Abrufen von Kandidaten, sondern auch ein einheitliches „Candidate“-Contract für Ihr Frontend:

* `id` (z. B. QID oder URI)  
* `label` / `description`  
* `match_score` (heuristisch; auch „unscored“ möglich)  
* `source` (welcher Authority‑Adapter)  
* optional `extra` (z. B. Koordinaten/Typen)

### Entity Linking als Vorschlagsgenerator (optional, aber oft lohnend)

Neben „Typeahead gegen Authority“ gibt es zwei automatische Vorschlagsquellen, die Sie (auch später) ergänzen können:

* **spaCy EntityLinker**: spaCy beschreibt einen EntityLinker‑Baustein, der Mentions zu eindeutigen IDs disambiguiert, basierend auf KnowledgeBase + Kandidatengenerator + Modell. citeturn11search11  
* **Wikidata‑basierte Entity‑Linking‑Tools**:
  * entity["organization","OpenTapioca","entity linking tool"] ist ein „simple and fast Named Entity Linking system for Wikidata“ und kann lokal betrieben werden; es gibt Hinweise auf „synchronous with Wikidata“ und verfügbare pre‑trained models. citeturn11search0turn11search4  
  * entity["organization","entity-fishing","entity disambiguation tool"] positioniert sich als performanter Wikidata‑basierter Disambiguation‑Dienst. citeturn11search6turn11search14  
  * entity["organization","FALCON 2.0","entity linking tool"] ist ein Entity‑ und Relation‑Linker über Wikidata (inkl. Web‑API); die Methodik ist stark über englische Morphologie motiviert, was für deutschsprachige OCR/Metadaten evaluiert werden müsste. citeturn11search1turn11search13  

Für Ihren Editor‑Use‑Case sind solche Tools vor allem als „Vorschlagmaschine“ sinnvoll, nicht als automatische Wahrheit: UI‑seitig bleibt ein kuratorischer Bestätigungsschritt zentral.

## Konkrete, unmittelbar nutzbare Vorarbeiten für Debussy und eine pragmatische Empfehlung

### Was sich am ehesten „direkt“ in eine FastAPI‑Browser‑App integrieren lässt

**neat als UI‑Baseline (empfohlen, wenn Time‑to‑Value zählt)**  
Weil neat bereits als reines HTML/JS‑Tool konzipiert ist, OCR‑/Token‑Korrektur und NER‑Tagging kombiniert und eine Authority‑ID‑Spalte vorsieht, ist es ein sehr konkreter Startpunkt für Ihr Szenario. citeturn5view0turn8view0  
Der Transformationsschritt wäre dann:

* statt TSV‑Upload/Download → API‑basiertes Laden/Speichern (FastAPI)  
* statt „ID‑Spalte frei editieren“ → „ID‑Spalte als Reconciliation‑Widget“ (Kandidatensuche gegen Ihre Authority‑Adapter)  
* zusätzlicher „Dictionary‑Entry“-Layer (globales Dedupe + Occurrence‑Links)

**doccano/Label Studio (empfohlen, wenn Sie ein komplettes Annotation‑Backoffice brauchen)**  
Wenn Ihr Projekt ohnehin Projekt‑/User‑/Role‑/Dataset‑Management plus UI‑Workflows für Annotation in größerem Stil braucht, sind doccano oder Label Studio als eigenständige Systeme stark. citeturn10search0turn10search1turn10search17  
Sie müssten aber die „Dictionary‑Entity‑Management“-Schicht zusätzlich bauen.

**INCEpTION/Recogito (empfohlen, wenn Sie eine etablierte semantische Annotationsplattform akzeptieren)**  
Beide sind fachlich sehr nah am „Linking zu Knowledge Bases“ und „semantischer Annotation“, aber meist eher als Plattformintegration (separater Dienst) als als eingebettete Komponente. citeturn10search2turn10search27turn10search3  

### Eine belastbare Minimal‑Roadmap, die zu Ihrem JSON‑Ziel passt

1. **JSON‑Schema/Pydantic‑Modelle zuerst festziehen** (Entry + Occurrence getrennt modellieren; `record_id` als Pflichtfeld auf Occurrence‑Ebene).  
2. **Authority‑Adapter** (Wikidata‑Search via `wbsearchentities`, lobid‑gnd‑Search, GeoNames‑Search JSON) als FastAPI‑Endpoints implementieren; Caching/Rate‑Limit/Attribution berücksichtigen. citeturn7search26turn7search0turn7search1turn7search9turn7search33  
3. **Editor‑UI**:  
   * schnellster Start: neat‑Fork als eingebettetes Frontend, zunächst nur Mentions + ID‑Auswahl, später Entry‑Management. citeturn5view0turn8view0  
4. **Merging/Dedupe**: UI‑Funktion „merge two entries“ muss Occurrences umhängen; das ist der Punkt, an dem `record_id`/Mention‑IDs wirklich tragen.  
5. Optional: Entity‑Linking‑Vorschläge (OpenTapioca/spaCy‑EntityLinker/entity‑fishing) als „Suggestion“-Service zuschalten. citeturn11search0turn11search11turn11search6  

### Risiko‑/Qualitätsaspekte, die Sie früh adressieren sollten

* **Ambiguität und falsche Normdatenlinks** sind teurer als fehlende Links: Deshalb Kandidaten‑UI mit Preview/Context, nicht nur „ID‑Feld“. Das ist genau die Logik, die Reconciliation‑Workflows (OpenRefine) etabliert haben. citeturn7search7turn7search3  
* **OCR‑Kontext**: Wenn Sie Bildausschnitte/BBoxes nutzen können, steigt die Kurationsqualität deutlich; neat zeigt, wie man IIIF‑Snippets und Bounding‑Box‑Koordinaten in einen Editor einwebt. citeturn5view0  
* **Lizenz/Attribution/Keys**: GeoNames verlangt Username und Attribution (CC‑BY), daher serverseitig kapseln und in Ihren Exporten/Metadaten sauber ausweisen. citeturn7search33turn7search9  
* **Identifier‑Crosswalks**: Wenn Sie QIDs speichern, können P227/P1566 als sekundäre IDs helfen (wo gepflegt), aber nie als Garantie. citeturn9search0turn9search1turn9search18  

In Summe gibt es kein einzelnes „Drop‑in‑FastAPI‑Modul“, das exakt Ihr JSON‑Dictionary‑Ziel (inkl. Normdaten + globaler Entity‑Katalog + Record‑Rückbindung) komplett abdeckt. Es gibt aber sehr einschlägige Vorarbeiten, die große Teile bereits lösen: **neat** als leichtgewichtige browserbasierte Editing‑Basis für OCR/NER mit Authority‑ID‑Spalte, **lobid‑gnd** als GND‑Lookup‑API in JSON‑LD, **GeoNames** als gut dokumentierte JSON‑Webservices, **Wikidata** als Such‑/ID‑Hub über `wbsearchentities` und externe Identifier‑Properties, und **OpenRefine** als Blaupause für Reconciliation‑UX. citeturn5view0turn7search0turn7search1turn7search26turn7search3turn9search0turn9search1