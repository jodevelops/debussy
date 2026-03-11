"""
Tests for enrich/geonames.py.

Uses mock HTTP responses to test GeoNames search and batch functions.
"""

import sys
import json
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from kwb.enrich.geonames import (
    GeoNamesResult, geonames_search, geonames_batch_search,
)


def _mock_geonames_response(geonames_list):
    """Create a mock urllib response with GeoNames JSON."""
    data = json.dumps({"geonames": geonames_list}).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = data
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


class TestGeoNamesResult(unittest.TestCase):

    def test_to_dict(self):
        r = GeoNamesResult(
            geonames_id="2950159",
            name="Berlin",
            country="Germany",
            country_code="DE",
            lat=52.52,
            lng=13.405,
            population=3748148,
        )
        d = r.to_dict()
        self.assertEqual(d["geonames_id"], "2950159")
        self.assertEqual(d["name"], "Berlin")
        self.assertEqual(d["country"], "Germany")
        self.assertIn("geonames.org", d["uri"])

    def test_uri(self):
        r = GeoNamesResult(geonames_id="12345", name="Test")
        self.assertEqual(r.uri, "https://www.geonames.org/12345")

    def test_empty_uri(self):
        r = GeoNamesResult(geonames_id="", name="Test")
        self.assertEqual(r.uri, "")


class TestGeoNamesSearch(unittest.TestCase):

    def test_empty_query(self):
        results = geonames_search("", username="test")
        self.assertEqual(results, [])

    def test_no_username(self):
        results = geonames_search("Berlin", username="")
        self.assertEqual(results, [])

    @patch("kwb.enrich.geonames.urlopen")
    def test_successful_search(self, mock_urlopen):
        mock_urlopen.return_value = _mock_geonames_response([
            {
                "geonameId": 2950159,
                "name": "Berlin",
                "countryName": "Germany",
                "countryCode": "DE",
                "fcl": "P",
                "fcode": "PPLC",
                "lat": "52.52437",
                "lng": "13.41053",
                "population": 3748148,
            },
        ])

        results = geonames_search("Berlin", username="test")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].geonames_id, "2950159")
        self.assertEqual(results[0].name, "Berlin")
        self.assertEqual(results[0].country, "Germany")

    @patch("kwb.enrich.geonames.urlopen")
    def test_network_error(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Connection refused")
        results = geonames_search("Berlin", username="test")
        self.assertEqual(results, [])


class TestGeoNamesBatchSearch(unittest.TestCase):

    def test_empty_terms(self):
        results = geonames_batch_search([])
        self.assertEqual(results, [])

    @patch("kwb.enrich.geonames.geonames_search")
    def test_batch(self, mock_search):
        mock_search.side_effect = [
            [GeoNamesResult(geonames_id="2950159", name="Berlin")],
            [],  # no results for second term
        ]

        terms = [
            {"text": "Berlin", "record_id": "r1"},
            {"text": "Atlantis", "record_id": "r2"},
        ]
        results = geonames_batch_search(terms, username="test", delay=0)

        self.assertEqual(len(results), 2)
        self.assertIsNotNone(results[0]["top_match"])
        self.assertEqual(results[0]["top_match"]["geonames_id"], "2950159")
        self.assertIsNone(results[1]["top_match"])


if __name__ == "__main__":
    unittest.main()
