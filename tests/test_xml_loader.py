"""Tests for METS/MODS XML loader."""
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from kwb.ingest.xml_loader import load_mets_mods, ingest_xml, XMLLoadError


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


if __name__ == "__main__":
    unittest.main()
