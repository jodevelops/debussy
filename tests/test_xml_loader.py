"""Tests for METS/MODS and LIDO XML loaders."""
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from kwb.ingest.xml_loader import (
    load_mets_mods,
    load_lido,
    ingest_xml,
    detect_xml_format,
    XMLLoadError,
)


SAMPLE_MODS = """\
<?xml version="1.0" encoding="UTF-8"?>
<mods:modsCollection xmlns:mods="http://www.loc.gov/mods/v3">
  <mods:mods>
    <mods:titleInfo>
      <mods:title>Ansicht von Berlin</mods:title>
    </mods:titleInfo>
    <mods:name type="personal">
      <mods:namePart>Müller, Friedrich</mods:namePart>
      <mods:role>
        <mods:roleTerm type="text">Künstler</mods:roleTerm>
      </mods:role>
    </mods:name>
    <mods:originInfo>
      <mods:dateIssued>1850</mods:dateIssued>
      <mods:place>
        <mods:placeTerm type="text">Berlin</mods:placeTerm>
      </mods:place>
    </mods:originInfo>
    <mods:subject>
      <mods:topic>Stadtansicht</mods:topic>
      <mods:geographic>Berlin</mods:geographic>
    </mods:subject>
    <mods:identifier type="local">rec_001</mods:identifier>
    <mods:genre>Druckgrafik</mods:genre>
    <mods:abstract>Eine Ansicht der Stadt Berlin um 1850.</mods:abstract>
  </mods:mods>
  <mods:mods>
    <mods:titleInfo>
      <mods:title>Porträt eines Unbekannten</mods:title>
    </mods:titleInfo>
    <mods:name type="personal">
      <mods:namePart>Schmidt, Anna</mods:namePart>
    </mods:name>
    <mods:originInfo>
      <mods:dateCreated>ca. 1900</mods:dateCreated>
    </mods:originInfo>
    <mods:identifier type="local">rec_002</mods:identifier>
  </mods:mods>
</mods:modsCollection>
"""

SAMPLE_METS_MODS = """\
<?xml version="1.0" encoding="UTF-8"?>
<mets:mets xmlns:mets="http://www.loc.gov/METS/"
           xmlns:mods="http://www.loc.gov/mods/v3">
  <mets:dmdSec ID="dmd1">
    <mets:mdWrap MDTYPE="MODS">
      <mets:xmlData>
        <mods:mods>
          <mods:titleInfo>
            <mods:title>Testdokument</mods:title>
          </mods:titleInfo>
          <mods:identifier type="local">test_001</mods:identifier>
        </mods:mods>
      </mets:xmlData>
    </mets:mdWrap>
  </mets:dmdSec>
</mets:mets>
"""


class TestXMLLoader(unittest.TestCase):
    """Test METS/MODS XML ingestion."""

    def _write_xml(self, content: str, filename: str = "test.xml") -> Path:
        path = Path(tempfile.mkdtemp()) / filename
        path.write_text(content, encoding="utf-8")
        return path

    def test_load_mods_collection(self):
        path = self._write_xml(SAMPLE_MODS)
        df = load_mets_mods(path)
        self.assertEqual(len(df), 2)
        self.assertEqual(df.loc[0, "title"], "Ansicht von Berlin")
        self.assertEqual(df.loc[0, "name"], "Müller, Friedrich")
        self.assertEqual(df.loc[0, "identifier"], "rec_001")

    def test_load_mets_mods(self):
        path = self._write_xml(SAMPLE_METS_MODS)
        df = load_mets_mods(path)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.loc[0, "title"], "Testdokument")

    def test_subjects_joined(self):
        path = self._write_xml(SAMPLE_MODS)
        df = load_mets_mods(path)
        self.assertIn("Stadtansicht", df.loc[0, "subjects"])
        self.assertIn("Berlin", df.loc[0, "subjects"])

    def test_empty_fields_are_na(self):
        path = self._write_xml(SAMPLE_MODS)
        df = load_mets_mods(path)
        # Second record has no abstract
        self.assertTrue(pd.isna(df.loc[1, "abstract"]))

    def test_ingest_xml_returns_profile(self):
        path = self._write_xml(SAMPLE_MODS)
        df, profile = ingest_xml(path)
        self.assertEqual(profile.row_count, 2)
        self.assertGreater(profile.column_count, 0)

    def test_no_mods_raises(self):
        path = self._write_xml(
            '<?xml version="1.0"?><root><item>test</item></root>'
        )
        with self.assertRaises(XMLLoadError):
            load_mets_mods(path)

    def test_file_not_found(self):
        with self.assertRaises(XMLLoadError):
            load_mets_mods("/nonexistent/file.xml")

    def test_invalid_xml(self):
        path = self._write_xml("not valid xml <>><<")
        with self.assertRaises(XMLLoadError):
            load_mets_mods(path)


# ---------------------------------------------------------------------------
# LIDO loader tests (F31)
# ---------------------------------------------------------------------------


SAMPLE_LIDO_MINIMAL = """\
<?xml version="1.0" encoding="UTF-8"?>
<lido:lido xmlns:lido="http://www.lido-schema.org">
  <lido:descriptiveMetadata>
    <lido:objectIdentificationWrap>
      <lido:titleWrap>
        <lido:titleSet>
          <lido:appellationValue>Bronzefigur Athena</lido:appellationValue>
        </lido:titleSet>
      </lido:titleWrap>
    </lido:objectIdentificationWrap>
  </lido:descriptiveMetadata>
  <lido:administrativeMetadata>
    <lido:recordWrap>
      <lido:recordID>inv-2024-001</lido:recordID>
    </lido:recordWrap>
  </lido:administrativeMetadata>
</lido:lido>
"""


SAMPLE_LIDO_FULL = """\
<?xml version="1.0" encoding="UTF-8"?>
<lido:lidoWrap xmlns:lido="http://www.lido-schema.org">
  <lido:lido>
    <lido:descriptiveMetadata>
      <lido:objectClassificationWrap>
        <lido:objectWorkTypeWrap>
          <lido:objectWorkType><lido:term>Gemälde</lido:term></lido:objectWorkType>
        </lido:objectWorkTypeWrap>
      </lido:objectClassificationWrap>
      <lido:objectIdentificationWrap>
        <lido:titleWrap>
          <lido:titleSet>
            <lido:appellationValue>Stillleben mit Blumen</lido:appellationValue>
          </lido:titleSet>
        </lido:titleWrap>
        <lido:objectDescriptionWrap>
          <lido:objectDescriptionSet>
            <lido:descriptiveNoteValue>Öl auf Leinwand, signiert.</lido:descriptiveNoteValue>
          </lido:objectDescriptionSet>
        </lido:objectDescriptionWrap>
        <lido:objectMeasurementsWrap>
          <lido:objectMeasurementsSet>
            <lido:displayObjectMeasurements>50 x 40 cm</lido:displayObjectMeasurements>
          </lido:objectMeasurementsSet>
        </lido:objectMeasurementsWrap>
      </lido:objectIdentificationWrap>
      <lido:eventWrap>
        <lido:eventSet>
          <lido:event>
            <lido:eventType><lido:term>production</lido:term></lido:eventType>
            <lido:eventActor>
              <lido:actorInRole>
                <lido:actor>
                  <lido:nameActorSet>
                    <lido:appellationValue>Schmidt, Anna</lido:appellationValue>
                  </lido:nameActorSet>
                </lido:actor>
                <lido:roleActor><lido:term>Malerin</lido:term></lido:roleActor>
              </lido:actorInRole>
            </lido:eventActor>
            <lido:eventDate><lido:displayDate>ca. 1900</lido:displayDate></lido:eventDate>
            <lido:eventPlace><lido:displayPlace>München</lido:displayPlace></lido:eventPlace>
          </lido:event>
        </lido:eventSet>
      </lido:eventWrap>
      <lido:objectRelationWrap>
        <lido:subjectWrap>
          <lido:subjectSet>
            <lido:subject>
              <lido:subjectConcept><lido:term>Stillleben</lido:term></lido:subjectConcept>
            </lido:subject>
            <lido:subject>
              <lido:subjectConcept><lido:term>Blumen</lido:term></lido:subjectConcept>
            </lido:subject>
          </lido:subjectSet>
        </lido:subjectWrap>
      </lido:objectRelationWrap>
    </lido:descriptiveMetadata>
    <lido:administrativeMetadata>
      <lido:recordWrap>
        <lido:recordID>obj-001</lido:recordID>
      </lido:recordWrap>
      <lido:rightsWorkWrap>
        <lido:rightsWorkSet>
          <lido:rightsType><lido:term>CC BY-SA 4.0</lido:term></lido:rightsType>
        </lido:rightsWorkSet>
      </lido:rightsWorkWrap>
    </lido:administrativeMetadata>
  </lido:lido>
  <lido:lido>
    <lido:descriptiveMetadata>
      <lido:objectIdentificationWrap>
        <lido:titleWrap>
          <lido:titleSet>
            <lido:appellationValue>Skulptur Diana</lido:appellationValue>
          </lido:titleSet>
        </lido:titleWrap>
      </lido:objectIdentificationWrap>
    </lido:descriptiveMetadata>
    <lido:administrativeMetadata>
      <lido:recordWrap>
        <lido:recordID>obj-002</lido:recordID>
      </lido:recordWrap>
    </lido:administrativeMetadata>
  </lido:lido>
</lido:lidoWrap>
"""


class TestLIDOLoader(unittest.TestCase):
    """Test LIDO XML ingestion (F31)."""

    def _write_xml(self, content: str, filename: str = "test.xml") -> Path:
        path = Path(tempfile.mkdtemp()) / filename
        path.write_text(content, encoding="utf-8")
        return path

    def test_load_lido_minimal(self):
        path = self._write_xml(SAMPLE_LIDO_MINIMAL)
        df = load_lido(path)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.loc[0, "title"], "Bronzefigur Athena")
        self.assertEqual(df.loc[0, "record_id"], "inv-2024-001")

    def test_load_lido_collection(self):
        path = self._write_xml(SAMPLE_LIDO_FULL)
        df = load_lido(path)
        self.assertEqual(len(df), 2)
        self.assertEqual(df.loc[0, "title"], "Stillleben mit Blumen")
        self.assertEqual(df.loc[1, "title"], "Skulptur Diana")
        self.assertEqual(df.loc[0, "record_id"], "obj-001")
        self.assertEqual(df.loc[1, "record_id"], "obj-002")

    def test_load_lido_actor_and_role(self):
        path = self._write_xml(SAMPLE_LIDO_FULL)
        df = load_lido(path)
        self.assertEqual(df.loc[0, "name"], "Schmidt, Anna")
        self.assertEqual(df.loc[0, "role"], "Malerin")
        self.assertEqual(df.loc[0, "date_created"], "ca. 1900")
        self.assertEqual(df.loc[0, "place_of_origin"], "München")

    def test_load_lido_multiple_subjects_joined(self):
        path = self._write_xml(SAMPLE_LIDO_FULL)
        df = load_lido(path)
        self.assertIn("Stillleben", df.loc[0, "subjects"])
        self.assertIn("Blumen", df.loc[0, "subjects"])
        self.assertIn(";", df.loc[0, "subjects"])

    def test_load_lido_genre_extent_rights(self):
        path = self._write_xml(SAMPLE_LIDO_FULL)
        df = load_lido(path)
        self.assertEqual(df.loc[0, "genre"], "Gemälde")
        self.assertEqual(df.loc[0, "extent"], "50 x 40 cm")
        self.assertEqual(df.loc[0, "access_condition"], "CC BY-SA 4.0")

    def test_load_lido_no_records_raises(self):
        path = self._write_xml(
            '<?xml version="1.0"?><root><item>x</item></root>'
        )
        with self.assertRaises(XMLLoadError):
            load_lido(path)


class TestXMLFormatDetection(unittest.TestCase):
    """Test format auto-detection and ingest_xml dispatch."""

    def _write_xml(self, content: str, filename: str = "test.xml") -> Path:
        path = Path(tempfile.mkdtemp()) / filename
        path.write_text(content, encoding="utf-8")
        return path

    def test_detect_mods_collection(self):
        path = self._write_xml(SAMPLE_MODS)
        self.assertEqual(detect_xml_format(path), "mods")

    def test_detect_mets_mods(self):
        path = self._write_xml(SAMPLE_METS_MODS)
        self.assertEqual(detect_xml_format(path), "mets_mods")

    def test_detect_lido(self):
        path = self._write_xml(SAMPLE_LIDO_FULL)
        self.assertEqual(detect_xml_format(path), "lido")

    def test_detect_unknown(self):
        path = self._write_xml(
            '<?xml version="1.0"?><other><foo/></other>'
        )
        self.assertEqual(detect_xml_format(path), "unknown")

    def test_ingest_xml_dispatches_lido(self):
        path = self._write_xml(SAMPLE_LIDO_FULL)
        df, profile = ingest_xml(path)
        self.assertEqual(profile.row_count, 2)
        self.assertGreater(profile.column_count, 0)
        self.assertEqual(df.loc[0, "title"], "Stillleben mit Blumen")

    def test_ingest_xml_dispatches_mods(self):
        path = self._write_xml(SAMPLE_MODS)
        df, profile = ingest_xml(path)
        self.assertEqual(profile.row_count, 2)
        self.assertEqual(df.loc[0, "title"], "Ansicht von Berlin")

    def test_ingest_xml_unknown_format_raises(self):
        path = self._write_xml(
            '<?xml version="1.0"?><foo><bar>x</bar></foo>'
        )
        with self.assertRaises(XMLLoadError):
            ingest_xml(path)


if __name__ == "__main__":
    unittest.main()
