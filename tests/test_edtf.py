"""
Rigorous tests for kwb.normalize.edtf (canonical EDTF implementation).

These tests cover the PRODUCTION code path used by app.py via enrich/edtf.py.
Previous tests covered normalize/edtf.py (old path) but NOT enrich/edtf.py.
This test file directly tests the canonical module.

Test strategy:
- Parameterised cases for each pattern group.
- Edge cases: empty, None, whitespace, mixed case.
- Approximation combos: ca. + range, ca. + century.
- Roundtrip: EDTFResult.original always matches input.
- Batch + hybrid integration tests.
- Model forwarding: LLM path uses the model we pass.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import unittest

from kwb.normalize.edtf import (
    normalize_edtf,
    normalize_edtf_batch,
    normalize_edtf_hybrid,
)
from kwb.enrich.edtf import normalize_date_rules, normalize_dates
from kwb.ai.mock import MockProvider


# ---------------------------------------------------------------------------
# normalize_edtf: unit tests per pattern group
# ---------------------------------------------------------------------------

class TestNormalizeEdtfEmpty(unittest.TestCase):

    def test_empty_string(self):
        r = normalize_edtf("")
        self.assertEqual(r.edtf, "")
        self.assertEqual(r.note, "leer")
        self.assertTrue(r.valid)

    def test_whitespace_only(self):
        r = normalize_edtf("   ")
        self.assertEqual(r.note, "leer")

    def test_undated_german(self):
        for term in ["undatiert", "o.d.", "o. d.", "ohne datum", "s.d.", "k.a."]:
            with self.subTest(term=term):
                r = normalize_edtf(term)
                self.assertEqual(r.edtf, "", msg=f"Expected empty EDTF for {term!r}")
                self.assertIn("undatiert", r.note)

    def test_undated_english(self):
        r = normalize_edtf("undated")
        self.assertEqual(r.edtf, "")
        self.assertIn("undatiert", r.note)


class TestNormalizeEdtfPlainYear(unittest.TestCase):

    def test_four_digit_year(self):
        self.assertEqual(normalize_edtf("1920").edtf, "1920")

    def test_early_year(self):
        self.assertEqual(normalize_edtf("0842").edtf, "0842")

    def test_modern_year(self):
        self.assertEqual(normalize_edtf("2024").edtf, "2024")

    def test_year_with_leading_spaces(self):
        self.assertEqual(normalize_edtf("  1950  ").edtf, "1950")

    def test_plain_year_confidence(self):
        r = normalize_edtf("1920")
        self.assertEqual(r.confidence, 1.0)
        self.assertEqual(r.method, "rule")


class TestNormalizeEdtfMonthYear(unittest.TestCase):

    def test_month_year_german(self):
        self.assertEqual(normalize_edtf("Januar 1920").edtf, "1920-01")

    def test_month_abbrev(self):
        self.assertEqual(normalize_edtf("Dez 1945").edtf, "1945-12")

    def test_month_year_reversed(self):
        self.assertEqual(normalize_edtf("1920 März").edtf, "1920-03")

    def test_december_case_insensitive(self):
        self.assertEqual(normalize_edtf("dezember 1900").edtf, "1900-12")

    def test_all_months(self):
        expected = {
            "Januar": "01", "Februar": "02", "März": "03",
            "April": "04", "Mai": "05", "Juni": "06",
            "Juli": "07", "August": "08", "September": "09",
            "Oktober": "10", "November": "11", "Dezember": "12",
        }
        for month, num in expected.items():
            with self.subTest(month=month):
                r = normalize_edtf(f"{month} 1920")
                self.assertEqual(r.edtf, f"1920-{num}", f"Failed for {month}")


class TestNormalizeEdtfDates(unittest.TestCase):

    def test_german_date_format(self):
        self.assertEqual(normalize_edtf("15.03.1920").edtf, "1920-03-15")

    def test_single_digit_day_month(self):
        self.assertEqual(normalize_edtf("1.1.1900").edtf, "1900-01-01")

    def test_iso_date(self):
        self.assertEqual(normalize_edtf("1920-03-15").edtf, "1920-03-15")

    def test_iso_slash_separator(self):
        self.assertEqual(normalize_edtf("1920/03/15").edtf, "1920-03-15")

    def test_iso_dot_separator(self):
        self.assertEqual(normalize_edtf("1920.03.15").edtf, "1920-03-15")

    def test_iso_month_only(self):
        self.assertEqual(normalize_edtf("1920-03").edtf, "1920-03")


class TestNormalizeEdtfRanges(unittest.TestCase):

    def test_dash_range(self):
        self.assertEqual(normalize_edtf("1920-1930").edtf, "1920/1930")

    def test_endash_range(self):
        self.assertEqual(normalize_edtf("1920–1930").edtf, "1920/1930")

    def test_slash_range(self):
        self.assertEqual(normalize_edtf("1920/1930").edtf, "1920/1930")

    def test_bis_range(self):
        self.assertEqual(normalize_edtf("1920 bis 1930").edtf, "1920/1930")

    def test_to_range(self):
        self.assertEqual(normalize_edtf("1920 to 1930").edtf, "1920/1930")

    def test_range_confidence(self):
        r = normalize_edtf("1920-1930")
        self.assertGreaterEqual(r.confidence, 0.9)


class TestNormalizeEdtfApproximation(unittest.TestCase):

    def test_ca_year(self):
        self.assertEqual(normalize_edtf("ca. 1920").edtf, "1920~")

    def test_um_year(self):
        self.assertEqual(normalize_edtf("um 1920").edtf, "1920~")

    def test_circa_year(self):
        self.assertEqual(normalize_edtf("circa 1920").edtf, "1920~")

    def test_etwa_year(self):
        self.assertEqual(normalize_edtf("etwa 1920").edtf, "1920~")

    def test_approx_range(self):
        self.assertEqual(normalize_edtf("ca. 1920-1930").edtf, "1920~/1930~")

    def test_approx_decade(self):
        self.assertEqual(normalize_edtf("ca. 1920er").edtf, "192X~")


class TestNormalizeEdtfDecadeCentury(unittest.TestCase):

    def test_decade_er(self):
        self.assertEqual(normalize_edtf("1920er").edtf, "192X")

    def test_decade_er_jahre(self):
        self.assertEqual(normalize_edtf("1920er Jahre").edtf, "192X")

    def test_century_19(self):
        self.assertEqual(normalize_edtf("19. Jahrhundert").edtf, "18XX")

    def test_century_20(self):
        self.assertEqual(normalize_edtf("20. Jahrhundert").edtf, "19XX")

    def test_century_jh_abbrev(self):
        self.assertEqual(normalize_edtf("19. Jh.").edtf, "18XX")

    def test_century_anfang(self):
        r = normalize_edtf("Anfang 19. Jahrhundert")
        self.assertEqual(r.edtf, "18XX")

    def test_century_confidence_lower(self):
        r = normalize_edtf("19. Jahrhundert")
        self.assertLessEqual(r.confidence, 0.9)


class TestNormalizeEdtfUncertain(unittest.TestCase):

    def test_question_mark(self):
        self.assertEqual(normalize_edtf("1920?").edtf, "1920?")

    def test_bracket_uncertain(self):
        self.assertEqual(normalize_edtf("[1920]").edtf, "1920?")


class TestNormalizeEdtfBeforeAfter(unittest.TestCase):

    def test_vor(self):
        self.assertEqual(normalize_edtf("vor 1920").edtf, "../1920")

    def test_before(self):
        self.assertEqual(normalize_edtf("before 1920").edtf, "../1920")

    def test_nach(self):
        self.assertEqual(normalize_edtf("nach 1920").edtf, "1920/..")

    def test_after(self):
        self.assertEqual(normalize_edtf("after 1920").edtf, "1920/..")

    def test_ab_year(self):
        self.assertEqual(normalize_edtf("ab 1920").edtf, "1920/..")


class TestNormalizeEdtfSeasons(unittest.TestCase):

    def test_sommer(self):
        self.assertEqual(normalize_edtf("Sommer 1945").edtf, "1945-22")

    def test_winter(self):
        self.assertEqual(normalize_edtf("Winter 1945").edtf, "1945-24")

    def test_herbst(self):
        self.assertEqual(normalize_edtf("Herbst 1945").edtf, "1945-23")

    def test_fruehling(self):
        self.assertEqual(normalize_edtf("Frühling 1920").edtf, "1920-21")


class TestNormalizeEdtfOriginalPreserved(unittest.TestCase):
    """The original field must always exactly match the input."""

    def test_original_preserved_whitespace(self):
        r = normalize_edtf("  1920  ")
        self.assertEqual(r.original, "1920")  # stripped

    def test_original_preserved_complex(self):
        r = normalize_edtf("ca. 1920-1930")
        self.assertEqual(r.original, "ca. 1920-1930")

    def test_original_preserved_unmatched(self):
        r = normalize_edtf("XYZZY not a date")
        self.assertEqual(r.original, "XYZZY not a date")
        self.assertFalse(r.valid)


class TestNormalizeEdtfUnmatched(unittest.TestCase):

    def test_random_text_not_valid(self):
        r = normalize_edtf("keine Ahnung")
        self.assertFalse(r.valid)
        self.assertEqual(r.edtf, "")
        self.assertEqual(r.confidence, 0.0)
        self.assertIn("LLM", r.note)


# ---------------------------------------------------------------------------
# Batch tests
# ---------------------------------------------------------------------------

class TestNormalizeEdtfBatch(unittest.TestCase):

    def _items(self, dates: list[str]) -> list[dict]:
        return [{"text": d, "record_id": f"r{i}"} for i, d in enumerate(dates)]

    def test_batch_all_matched(self):
        items = self._items(["1920", "1930", "1945"])
        report = normalize_edtf_batch(items)
        self.assertEqual(report.total, 3)
        self.assertEqual(report.converted, 3)
        self.assertEqual(report.failed, 0)

    def test_batch_mixed(self):
        items = self._items(["1920", "undatiert", "nicht datiert xyz"])
        report = normalize_edtf_batch(items)
        self.assertEqual(report.total, 3)
        self.assertEqual(report.converted, 1)
        self.assertEqual(report.undated, 1)
        self.assertEqual(report.failed, 1)

    def test_batch_record_ids(self):
        items = [{"text": "1920", "record_id": "obj-001"}]
        report = normalize_edtf_batch(items)
        self.assertEqual(report.results[0].record_id, "obj-001")


# ---------------------------------------------------------------------------
# Hybrid tests: LLM path + model forwarding
# ---------------------------------------------------------------------------

class TestNormalizeEdtfHybrid(unittest.TestCase):

    def test_hybrid_rules_only_no_provider(self):
        """When provider=None, unmatched dates get a note but no crash."""
        items = [
            {"text": "1920", "record_id": "r1"},
            {"text": "unclear date text xyz", "record_id": "r2"},
        ]
        results, batch = normalize_edtf_hybrid(items, provider=None)
        self.assertEqual(len(results), 2)
        self.assertIsNone(batch)
        # First is resolved by rule
        self.assertTrue(results[0].valid)
        self.assertEqual(results[0].edtf, "1920")
        # Second fails without provider
        self.assertFalse(results[1].valid)

    def test_hybrid_llm_called_for_unmatched(self):
        """LLM provider is invoked only for items that rules could not handle."""
        mock = MockProvider.with_edtf_response("unclear text", "1920~", 0.7)
        items = [
            {"text": "1920", "record_id": "r1"},
            {"text": "unclear text", "record_id": "r2"},
        ]
        results, batch = normalize_edtf_hybrid(items, provider=mock)
        # Only 1 item should have triggered an LLM call (r2)
        self.assertEqual(len(mock.call_log), 1)
        # r1 was resolved by rule
        self.assertEqual(results[0].edtf, "1920")
        self.assertEqual(results[0].method, "rule")

    def test_hybrid_model_forwarded_to_llm(self):
        """The model parameter must reach MockProvider.call_log."""
        mock = MockProvider.with_edtf_response("xyz", "1920", 0.8)
        items = [{"text": "xyz date unclear", "record_id": "r1"}]
        normalize_edtf_hybrid(items, provider=mock, model="gpt-oss-120b")
        self.assertEqual(len(mock.call_log), 1)
        self.assertEqual(mock.call_log[0]["model"], "gpt-oss-120b")

    def test_hybrid_result_order_preserved(self):
        """Results must be returned in the same order as input items."""
        mock = MockProvider.with_edtf_response("unk", "1899", 0.6)
        items = [
            {"text": "1920", "record_id": "A"},
            {"text": "unk date xyz", "record_id": "B"},
            {"text": "1930", "record_id": "C"},
        ]
        results, _ = normalize_edtf_hybrid(items, provider=mock)
        self.assertEqual([r.record_id for r in results], ["A", "B", "C"])


# ---------------------------------------------------------------------------
# enrich/edtf adapter tests (ensures the adapter is a true pass-through)
# ---------------------------------------------------------------------------

class TestEnrichEdtfAdapter(unittest.TestCase):

    def test_normalize_date_rules_returns_result(self):
        r = normalize_date_rules("1920")
        self.assertIsNotNone(r)
        self.assertEqual(r.edtf, "1920")

    def test_normalize_date_rules_returns_none_for_unmatched(self):
        r = normalize_date_rules("something unrecognisable xyz abc")
        self.assertIsNone(r)

    def test_normalize_dates_hybrid(self):
        mock = MockProvider.with_edtf_response("unk", "1900~", 0.6)
        items = [
            {"text": "1920", "record_id": "r1"},
            {"text": "unbekannte Zeit xyz", "record_id": "r2"},
        ]
        results, batch = normalize_dates(items, provider=mock)
        self.assertEqual(len(results), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
