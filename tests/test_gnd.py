"""
GND module tests with mocked network calls.

Tests gnd_search, gnd_lookup, and gnd_batch_search without hitting lobid.org.
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch, MagicMock

from kwb.enrich.gnd import gnd_search, gnd_lookup, gnd_batch_search, GNDResult


def _lobid_search_response(members: list[dict] | None = None) -> bytes:
    """Build a fake lobid.org search JSON response."""
    if members is None:
        members = [{
            "gndIdentifier": "118540238",
            "preferredName": "Johann Wolfgang von Goethe",
            "type": ["AuthorityResource", "Person"],
            "variantName": ["Goethe, J.W.", "Goethe"],
            "biographicalOrHistoricalInformation": ["Dichter und Naturforscher"],
        }]
    return json.dumps({"member": members, "totalItems": len(members)}).encode("utf-8")


def _lobid_entity_response() -> bytes:
    """Build a fake lobid.org entity JSON response."""
    return json.dumps({
        "gndIdentifier": "118540238",
        "preferredName": "Johann Wolfgang von Goethe",
        "type": ["AuthorityResource", "Person"],
        "variantName": ["Goethe, J.W."],
        "biographicalOrHistoricalInformation": ["Dichter und Naturforscher"],
    }).encode("utf-8")


def _make_mock_urlopen(data: bytes) -> MagicMock:
    """Create a mock for urllib.request.urlopen returning given data."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = data
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


class TestGNDSearch(unittest.TestCase):

    @patch("kwb.enrich.gnd.urlopen")
    def test_search_returns_results(self, mock_urlopen):
        mock_urlopen.return_value = _make_mock_urlopen(_lobid_search_response())
        results = gnd_search("Goethe", entity_type="PER")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].gnd_id, "118540238")
        self.assertEqual(results[0].preferred_name, "Johann Wolfgang von Goethe")
        self.assertEqual(results[0].gnd_type, "Person")
        self.assertIn("Goethe, J.W.", results[0].alternative_names)

    @patch("kwb.enrich.gnd.urlopen")
    def test_search_with_type_filter(self, mock_urlopen):
        mock_urlopen.return_value = _make_mock_urlopen(_lobid_search_response())
        gnd_search("Bern", entity_type="GPE")
        # Verify the URL contains type filter
        call_args = mock_urlopen.call_args
        url = call_args[0][0].full_url if hasattr(call_args[0][0], "full_url") else str(call_args[0][0])
        self.assertIn("filter=type", url)
        self.assertIn("PlaceOrGeographicName", url)

    def test_search_empty_query(self):
        results = gnd_search("")
        self.assertEqual(results, [])

    def test_search_whitespace_query(self):
        results = gnd_search("   ")
        self.assertEqual(results, [])

    @patch("kwb.enrich.gnd.urlopen")
    def test_search_no_results(self, mock_urlopen):
        mock_urlopen.return_value = _make_mock_urlopen(_lobid_search_response([]))
        results = gnd_search("xyznonexistent")
        self.assertEqual(results, [])

    @patch("kwb.enrich.gnd.urlopen")
    def test_search_network_error(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Network error")
        results = gnd_search("Goethe")
        self.assertEqual(results, [])

    @patch("kwb.enrich.gnd.urlopen")
    def test_search_uri_generated(self, mock_urlopen):
        mock_urlopen.return_value = _make_mock_urlopen(_lobid_search_response())
        results = gnd_search("Goethe")
        self.assertEqual(results[0].uri, "https://d-nb.info/gnd/118540238")


class TestGNDLookup(unittest.TestCase):

    @patch("kwb.enrich.gnd.urlopen")
    def test_lookup_by_id(self, mock_urlopen):
        mock_urlopen.return_value = _make_mock_urlopen(_lobid_entity_response())
        result = gnd_lookup("118540238")
        self.assertIsNotNone(result)
        self.assertEqual(result.gnd_id, "118540238")
        self.assertEqual(result.preferred_name, "Johann Wolfgang von Goethe")

    @patch("kwb.enrich.gnd.urlopen")
    def test_lookup_network_error(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("404 Not Found")
        result = gnd_lookup("000000000")
        self.assertIsNone(result)


class TestGNDBatchSearch(unittest.TestCase):

    @patch("kwb.enrich.gnd.urlopen")
    def test_batch_search(self, mock_urlopen):
        mock_urlopen.return_value = _make_mock_urlopen(_lobid_search_response())
        terms = [
            {"text": "Goethe", "type": "PER", "record_id": "R001"},
            {"text": "Schiller", "type": "PER", "record_id": "R002"},
        ]
        results = gnd_batch_search(terms, delay=0)
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertIn("text", r)
            self.assertIn("results", r)
            self.assertIn("top_match", r)
            self.assertIsNotNone(r["top_match"])

    @patch("kwb.enrich.gnd.urlopen")
    def test_batch_empty_input(self, mock_urlopen):
        results = gnd_batch_search([], delay=0)
        self.assertEqual(results, [])
        mock_urlopen.assert_not_called()

    @patch("kwb.enrich.gnd.urlopen")
    def test_batch_partial_failure(self, mock_urlopen):
        """First call succeeds, second fails."""
        good = _make_mock_urlopen(_lobid_search_response())
        mock_urlopen.side_effect = [good, Exception("timeout")]
        terms = [
            {"text": "Goethe", "type": "PER", "record_id": "R001"},
            {"text": "Fail", "type": "PER", "record_id": "R002"},
        ]
        results = gnd_batch_search(terms, delay=0)
        self.assertEqual(len(results), 2)
        # First succeeded
        self.assertIsNotNone(results[0]["top_match"])
        # Second failed gracefully
        self.assertIsNone(results[1]["top_match"])


class TestGNDResult(unittest.TestCase):

    def test_to_dict(self):
        r = GNDResult(
            gnd_id="118540238",
            preferred_name="Goethe",
            gnd_type="Person",
        )
        d = r.to_dict()
        self.assertEqual(d["gnd_id"], "118540238")
        self.assertEqual(d["preferred_name"], "Goethe")
        self.assertEqual(d["uri"], "https://d-nb.info/gnd/118540238")

    def test_auto_uri(self):
        r = GNDResult(gnd_id="12345", preferred_name="Test")
        self.assertEqual(r.uri, "https://d-nb.info/gnd/12345")


if __name__ == "__main__":
    unittest.main()
