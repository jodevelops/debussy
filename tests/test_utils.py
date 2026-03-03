"""Tests for core/utils — shared utilities."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import unittest
from kwb.core.utils import try_parse_json, truncate_string, safe_float, safe_int


class TestTryParseJson(unittest.TestCase):

    # --- Valid JSON ---
    def test_plain_dict(self):
        self.assertEqual(try_parse_json('{"key": "value"}'), {"key": "value"})

    def test_plain_list(self):
        self.assertEqual(try_parse_json('[1, 2, 3]'), [1, 2, 3])

    def test_nested(self):
        r = try_parse_json('{"entities": [{"text": "Berlin", "type": "GPE"}]}')
        self.assertEqual(r["entities"][0]["text"], "Berlin")

    # --- Markdown fences ---
    def test_json_fence(self):
        s = '```json\n{"key": "value"}\n```'
        self.assertEqual(try_parse_json(s), {"key": "value"})

    def test_plain_fence(self):
        s = '```\n{"key": "value"}\n```'
        self.assertEqual(try_parse_json(s), {"key": "value"})

    def test_fence_no_trailing_newline(self):
        s = '```json\n{"k":"v"}```'
        self.assertEqual(try_parse_json(s), {"k": "v"})

    # --- Whitespace and BOM ---
    def test_leading_whitespace(self):
        self.assertEqual(try_parse_json('  {"k": 1}  '), {"k": 1})

    def test_bom(self):
        self.assertEqual(try_parse_json('\ufeff{"k": 1}'), {"k": 1})

    # --- Failure cases → None ---
    def test_empty_string(self):
        self.assertIsNone(try_parse_json(""))

    def test_none_input(self):
        self.assertIsNone(try_parse_json(None))  # type: ignore

    def test_plain_text(self):
        self.assertIsNone(try_parse_json("not json at all"))

    def test_scalar_json(self):
        # JSON scalars are valid JSON but we return None (not dict/list)
        self.assertIsNone(try_parse_json("42"))
        self.assertIsNone(try_parse_json('"hello"'))

    def test_truncated_json(self):
        self.assertIsNone(try_parse_json('{"key": "val'))

    def test_markdown_wrapping_invalid_json(self):
        self.assertIsNone(try_parse_json('```json\nnot json\n```'))

    # --- Robustness ---
    def test_deeply_nested(self):
        import json
        deep = {"a": {"b": {"c": {"d": "value"}}}}
        self.assertEqual(try_parse_json(json.dumps(deep)), deep)

    def test_unicode_values(self):
        r = try_parse_json('{"city": "Zürich", "country": "Schweiz"}')
        self.assertEqual(r["city"], "Zürich")


class TestTruncateString(unittest.TestCase):
    def test_short_string_unchanged(self):
        self.assertEqual(truncate_string("hello", max_len=10), "hello")

    def test_exact_length_unchanged(self):
        self.assertEqual(truncate_string("hello", max_len=5), "hello")

    def test_long_string_truncated(self):
        r = truncate_string("a" * 100, max_len=10)
        self.assertEqual(len(r), 10)
        self.assertTrue(r.endswith("…"))

    def test_empty_string(self):
        self.assertEqual(truncate_string(""), "")

    def test_none_like(self):
        # Should not crash
        self.assertEqual(truncate_string("", 50), "")


class TestSafeFloat(unittest.TestCase):
    def test_float_string(self):
        self.assertAlmostEqual(safe_float("0.85"), 0.85)

    def test_int_string(self):
        self.assertAlmostEqual(safe_float("1"), 1.0)

    def test_none_returns_default(self):
        self.assertAlmostEqual(safe_float(None), 0.0)

    def test_bad_string_returns_default(self):
        self.assertAlmostEqual(safe_float("nope", default=99.0), 99.0)

    def test_already_float(self):
        self.assertAlmostEqual(safe_float(3.14), 3.14)


class TestSafeInt(unittest.TestCase):
    def test_int_string(self):
        self.assertEqual(safe_int("42"), 42)

    def test_float_string_truncates(self):
        self.assertEqual(safe_int("3.9"), 3)

    def test_none_returns_default(self):
        self.assertEqual(safe_int(None, default=-1), -1)

    def test_bad_string_returns_default(self):
        self.assertEqual(safe_int("nope"), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
