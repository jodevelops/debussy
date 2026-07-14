# Bildbetrachter für Digitalisate

Ein eigenständiges HTML-Werkzeug zum Ansehen von Bildern zusammen mit ihren
CSV-Metadaten – läuft **lokal im Browser, ganz ohne Installation**.

## Weitergabe an Kolleg:innen

Es genügt, die eine Datei `bildbetrachter.html` weiterzugeben (z. B. per
E-Mail oder USB-Stick). Doppelklick öffnet sie im Standardbrowser
(Chrome, Edge oder Firefox empfohlen). Es wird nichts hochgeladen – alle
Daten bleiben auf dem eigenen Rechner.

## Bedienung

1. **CSV-Datei wählen** – die Tabelle mit den Metadaten. Trennzeichen
   (Komma, Semikolon, Tab) und ein evtl. BOM werden automatisch erkannt.
2. **Bilderordner wählen** – der Ordner mit den Digitalisaten. Unterordner
   werden automatisch mit durchsucht. Unterstützte Formate: JPEG, PNG,
   **TIFF**, GIF, BMP, WebP.
3. **Dateinamen-Spalte** – wird meist automatisch erkannt (z. B.
   `dias_jpg-file-name2048`), lässt sich aber umstellen. Direkt darunter
   wird angezeigt, wie viele CSV-Zeilen einem Bild zugeordnet werden konnten.
4. **Betrachter öffnen** anklicken.

Die Zuordnung Bild ↔ Metadaten läuft über den Dateinamen in der gewählten
Spalte (z. B. `Bild008-2048.jpg`). Groß-/Kleinschreibung und
Pfad-Vorsätze werden dabei ignoriert.

## In der Ansicht

- **Großes Bild** in der Mitte, **alle** CSV-Felder rechts daneben.
- **Facetten/Filter** links: Spalten mit wenigen verschiedenen Werten
  erscheinen als anklickbare Auswahllisten (mit Trefferzahlen), Spalten mit
  vielen Werten als Text-Suchfeld. Oben durchsucht ein Suchfeld alle Felder.
- Werte im Metadaten-Panel sind teils **anklickbar**, um direkt danach zu
  filtern.
- **Navigation**: Pfeile links/rechts am Bild, die Miniaturen-Leiste unten
  oder die Tasten `←` / `→`.
- Fehlt zu einem Datensatz das Bild im Ordner, wird das deutlich angezeigt;
  die Metadaten erscheinen trotzdem.

Über **„Andere Daten laden“** oben rechts lässt sich jederzeit eine neue
CSV bzw. ein neuer Ordner wählen.

## TIFF-Dateien

TIFF-Bilder können Browser nicht von sich aus anzeigen. Das Tool bringt
dafür einen eingebauten TIFF-Decoder mit (UTIF.js, MIT-Lizenz, direkt in
die HTML-Datei eingebettet) und wandelt TIFFs beim Anzeigen automatisch um –
weiterhin ganz ohne Internet oder Installation. Das Dekodieren großer TIFFs
kann einen kurzen Moment dauern; solange erscheint „Bild wird geladen …“.
Bei mehrseitigen TIFFs wird die erste Seite angezeigt.

## Browser-Hinweis

Die Ordnerauswahl nutzt eine Standard-Browserfunktion
(`webkitdirectory`), die von aktuellen Versionen von Chrome, Edge und
Firefox unterstützt wird.
