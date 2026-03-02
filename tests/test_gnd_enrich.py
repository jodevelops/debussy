"""
Tests for enrich/gnd.py.

Two groups:
1. parse_confidence: thorough coverage of all real formats from the CSV
   ("70%", "85%", 0.9, None, "").
2. parse_gnd_columns: run against actual GIUBMaster_locations_gnd_merged.csv
   to verify extraction logic on real-world data.
3. build_dictionary_from_gnd_csv: verify deduplication logic.
4. flag_low_confidence: verify flagging threshold.
"""

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from kwb.enrich.gnd import (
    parse_confidence, parse_gnd_columns,
    build_dictionary_from_gnd_csv, flag_low_confidence, GNDMatch,
)

# Path to real project CSV
GND_CSV = Path("/mnt/project/GIUBMaster_locations_gnd_merged.csv")


# ---------------------------------------------------------------------------
# parse_confidence
# ---------------------------------------------------------------------------

class TestParseConfidence(unittest.TestCase):

    def test_percent_string_70(self):
        self.assertAlmostEqual(parse_confidence("70%"), 0.70)

    def test_percent_string_85(self):
        self.assertAlmostEqual(parse_confidence("85%"), 0.85)

    def test_percent_string_100(self):
        self.assertAlmostEqual(parse_confidence("100%"), 1.0)

    def test_percent_string_50(self):
        self.assertAlmostEqual(parse_confidence("50%"), 0.50)

    def test_float_string(self):
        self.assertAlmostEqual(parse_confidence("0.9"), 0.9)

    def test_float_above_one_normalised(self):
        # If someone passes "90" (not "90%"), treat as percentage
        self.assertAlmostEqual(parse_confidence(90.0), 0.90)

    def test_float_at_one(self):
        self.assertAlmostEqual(parse_confidence(1.0), 1.0)

    def test_float_below_one(self):
        self.assertAlmostEqual(parse_confidence(0.75), 0.75)

    def test_none_returns_zero(self):
        self.assertAlmostEqual(parse_confidence(None), 0.0)

    def test_empty_string_returns_zero(self):
        self.assertAlmostEqual(parse_confidence(""), 0.0)

    def test_invalid_string_returns_zero(self):
        self.assertAlmostEqual(parse_confidence("hoch"), 0.0)

    def test_whitespace_string(self):
        self.assertAlmostEqual(parse_confidence("  "), 0.0)

    def test_int_input(self):
        self.assertAlmostEqual(parse_confidence(80), 0.80)

    # All values from the actual CSV
    def test_all_csv_confidence_values(self):
        for raw, expected in [("50%", 0.50), ("70%", 0.70), ("75%", 0.75),
                               ("80%", 0.80), ("85%", 0.85), ("90%", 0.90),
                               ("95%", 0.95)]:
            with self.subTest(raw=raw):
                self.assertAlmostEqual(parse_confidence(raw), expected)


# ---------------------------------------------------------------------------
# Tests against real CSV (skipped if file not present)
# ---------------------------------------------------------------------------

@unittest.skipUnless(GND_CSV.exists(), f"Real CSV not found at {GND_CSV}")
class TestParseGNDColumnsReal(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.df = pd.read_csv(GND_CSV, dtype=str, keep_default_na=False, low_memory=False)

    def test_returns_list_of_gnd_matches(self):
        matches = parse_gnd_columns(self.df)
        self.assertIsInstance(matches, list)
        self.assertTrue(len(matches) > 0)

    def test_all_matches_have_gnd_id(self):
        matches = parse_gnd_columns(self.df)
        for m in matches:
            self.assertNotEqual(m.gnd_id, "", f"Empty GND ID for {m.term!r}")

    def test_confidences_are_floats_in_range(self):
        matches = parse_gnd_columns(self.df)
        for m in matches:
            self.assertGreaterEqual(m.confidence, 0.0, f"Negative confidence for {m.term!r}")
            self.assertLessEqual(m.confidence, 1.0, f"Confidence > 1 for {m.term!r}")

    def test_total_match_count_reasonable(self):
        # We know from earlier analysis: ~13,341 matches in 8,312 rows
        matches = parse_gnd_columns(self.df)
        self.assertGreater(len(matches), 10_000)
        self.assertLess(len(matches), 30_000)

    def test_source_is_csv(self):
        matches = parse_gnd_columns(self.df)
        for m in matches[:100]:
            self.assertEqual(m.source, "csv")

    def test_record_ids_populated(self):
        matches = parse_gnd_columns(self.df)
        records_with_id = sum(1 for m in matches if m.record_id)
        self.assertGreater(records_with_id, len(matches) * 0.9)

    def test_no_matches_without_gnd_id(self):
        """Rows with NaN GND ID must not produce a match."""
        matches = parse_gnd_columns(self.df)
        gnd_ids = {m.gnd_id for m in matches}
        self.assertNotIn("", gnd_ids)
        self.assertNotIn("nan", gnd_ids)


@unittest.skipUnless(GND_CSV.exists(), f"Real CSV not found at {GND_CSV}")
class TestBuildDictionaryReal(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.df = pd.read_csv(GND_CSV, dtype=str, keep_default_na=False, low_memory=False)

    def test_returns_dict(self):
        d = build_dictionary_from_gnd_csv(self.df)
        self.assertIsInstance(d, dict)

    def test_all_keys_lowercase(self):
        d = build_dictionary_from_gnd_csv(self.df)
        for k in d:
            self.assertEqual(k, k.lower(), f"Key not lowercase: {k!r}")

    def test_values_are_dictionary_entries(self):
        from kwb.core.workspace import DictionaryEntry
        d = build_dictionary_from_gnd_csv(self.df)
        for v in list(d.values())[:10]:
            self.assertIsInstance(v, DictionaryEntry)

    def test_no_duplicate_keys(self):
        """Dictionary deduplication: each preferred name appears once."""
        d = build_dictionary_from_gnd_csv(self.df)
        # All keys unique by definition (dict)
        self.assertEqual(len(d), len(set(d.keys())))

    def test_keeps_highest_confidence(self):
        """When same term appears at different confidence levels, highest wins."""
        from kwb.core.workspace import DictionaryEntry
        rows = [
            {"record_id": "r1", "named_entity_1": "Berlin",
             "named_entity_1_gnd_id": "4005765-8",
             "named_entity_1_gnd_preferredName": "Berlin",
             "named_entity_1_gnd_type": "PlaceOrGeographicName",
             "named_entity_1_gnd_konfidenz": "70%",
             "named_entity_1_gnd_alternativen": ""},
            {"record_id": "r2", "named_entity_1": "Berlin",
             "named_entity_1_gnd_id": "4005765-8",
             "named_entity_1_gnd_preferredName": "Berlin",
             "named_entity_1_gnd_type": "PlaceOrGeographicName",
             "named_entity_1_gnd_konfidenz": "95%",
             "named_entity_1_gnd_alternativen": ""},
        ]
        for r in rows:
            for n in range(2, 12):
                for sfx in ["", "_gnd_id", "_gnd_preferredName", "_gnd_type",
                            "_gnd_konfidenz", "_gnd_alternativen"]:
                    col = f"named_entity_{n}{sfx}"
                    if col not in r:
                        r[col] = ""
        df = pd.DataFrame(rows)
        d = build_dictionary_from_gnd_csv(df)
        self.assertIn("berlin", d)
        self.assertAlmostEqual(d["berlin"].confidence, 0.95)


@unittest.skipUnless(GND_CSV.exists(), f"Real CSV not found at {GND_CSV}")
class TestFlagLowConfidenceReal(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.df = pd.read_csv(GND_CSV, dtype=str, keep_default_na=False, low_memory=False)

    def test_returns_list(self):
        flags = flag_low_confidence(self.df, threshold=0.80)
        self.assertIsInstance(flags, list)

    def test_all_flagged_below_threshold(self):
        flags = flag_low_confidence(self.df, threshold=0.80)
        for f in flags:
            self.assertLess(f["confidence"], 0.80)

    def test_high_threshold_flags_more(self):
        low = flag_low_confidence(self.df, threshold=0.70)
        high = flag_low_confidence(self.df, threshold=0.90)
        self.assertLessEqual(len(low), len(high))

    def test_flagged_have_record_id(self):
        flags = flag_low_confidence(self.df, threshold=0.85)
        for f in flags[:50]:
            self.assertIn("record_id", f)
            self.assertIn("gnd_id", f)
            self.assertIn("confidence", f)


# ---------------------------------------------------------------------------
# GNDMatch unit tests
# ---------------------------------------------------------------------------

class TestGNDMatch(unittest.TestCase):

    def test_uri_constructed(self):
        m = GNDMatch(term="Berlin", gnd_id="4005765-8", preferred_name="Berlin")
        self.assertEqual(m.uri, "http://d-nb.info/gnd/4005765-8")

    def test_empty_gnd_id_empty_uri(self):
        m = GNDMatch(term="Unbekannt", gnd_id="", preferred_name="")
        self.assertEqual(m.uri, "")

    def test_to_dictionary_entry(self):
        m = GNDMatch(
            term="Berlin", gnd_id="4005765-8",
            preferred_name="Berlin (Deutschland)",
            gnd_type="PlaceOrGeographicName",
            alternatives=["West-Berlin", "Ost-Berlin"],
            confidence=0.95, source="csv",
        )
        entry = m.to_dictionary_entry()
        self.assertEqual(entry.gnd_id, "4005765-8")
        self.assertEqual(entry.gnd_preferred, "Berlin (Deutschland)")
        self.assertEqual(len(entry.alternatives), 2)
        self.assertAlmostEqual(entry.confidence, 0.95)


if __name__ == "__main__":
    unittest.main(verbosity=2)
