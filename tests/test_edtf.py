"""Tests for EDTF date normalization."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from kwb.normalize.edtf import normalize_edtf, normalize_edtf_batch, EDTFResult


class TestEDTFRules:
    """Rule-based EDTF conversion tests."""

    def test_empty(self):
        r = normalize_edtf("")
        assert r.edtf == ""
        assert r.confidence == 1.0

    def test_undated_od(self):
        for s in ["o.D.", "o. D.", "undatiert", "undated", "s.d.", "ohne Datum", "keine Angabe"]:
            r = normalize_edtf(s)
            assert r.edtf == "", f"Failed for '{s}': got '{r.edtf}'"
            assert "undatiert" in r.note

    def test_plain_year(self):
        r = normalize_edtf("1920")
        assert r.edtf == "1920"
        assert r.confidence == 1.0

    def test_iso_month(self):
        r = normalize_edtf("1920-03")
        assert r.edtf == "1920-03"

    def test_iso_day(self):
        r = normalize_edtf("1920-03-15")
        assert r.edtf == "1920-03-15"

    def test_approx_ca(self):
        for prefix in ["ca.", "ca", "Ca.", "circa", "um", "ungefähr", "etwa"]:
            r = normalize_edtf(f"{prefix} 1920")
            assert r.edtf == "1920~", f"Failed for '{prefix} 1920': got '{r.edtf}'"

    def test_approx_with_month(self):
        r = normalize_edtf("ca. 1920-03")
        assert r.edtf == "1920-03~"

    def test_before(self):
        for prefix in ["vor", "before", "bis"]:
            r = normalize_edtf(f"{prefix} 1920")
            assert r.edtf == "../1920", f"Failed for '{prefix}': got '{r.edtf}'"

    def test_after(self):
        for prefix in ["nach", "after", "ab", "seit"]:
            r = normalize_edtf(f"{prefix} 1920")
            assert r.edtf == "1920/..", f"Failed for '{prefix}': got '{r.edtf}'"

    def test_range_dash(self):
        r = normalize_edtf("1920-1930")
        assert r.edtf == "1920/1930"

    def test_range_endash(self):
        r = normalize_edtf("1920–1930")
        assert r.edtf == "1920/1930"

    def test_range_text(self):
        r = normalize_edtf("1920 bis 1930")
        assert r.edtf == "1920/1930"

    def test_decade_er(self):
        r = normalize_edtf("1920er")
        assert r.edtf == "192X"

    def test_decade_er_jahre(self):
        r = normalize_edtf("1920er Jahre")
        assert r.edtf == "192X"

    def test_decade_s(self):
        r = normalize_edtf("1920s")
        assert r.edtf == "192X"

    def test_century(self):
        r = normalize_edtf("19. Jh.")
        assert r.edtf == "18XX", f"Got: {r.edtf}"  # 19th century = 1800s

    def test_century_full(self):
        r = normalize_edtf("19. Jahrhundert")
        assert r.edtf == "18XX"

    def test_century_20(self):
        r = normalize_edtf("20. Jh.")
        assert r.edtf == "19XX"

    def test_century_anfang(self):
        r = normalize_edtf("Anfang 19. Jh.")
        assert r.edtf == "18XX"

    def test_uncertain_brackets(self):
        r = normalize_edtf("[1920]")
        assert r.edtf == "1920?"

    def test_uncertain_question(self):
        r = normalize_edtf("1920?")
        assert r.edtf == "1920?"

    def test_unresolved(self):
        r = normalize_edtf("irgendwann im Mittelalter")
        assert r.valid is False
        assert r.confidence == 0.0

    def test_approx_before(self):
        r = normalize_edtf("ca. vor 1920")
        # "ca." stripped, then "vor 1920" → "../1920~"
        assert "../1920" in r.edtf


class TestEDTFBatch:
    """Batch conversion tests."""

    def test_batch(self):
        items = [
            {"record_id": "r1", "date": "1920"},
            {"record_id": "r2", "date": "ca. 1850"},
            {"record_id": "r3", "date": "o.D."},
            {"record_id": "r4", "date": "Mittelalter"},
        ]
        report = normalize_edtf_batch(items)
        assert report.total == 4
        assert report.converted == 2  # 1920 + ca.1850
        assert report.undated == 1    # o.D.
        assert report.failed == 1     # Mittelalter


if __name__ == "__main__":
    total = passed = failed = 0
    for cls in [TestEDTFRules, TestEDTFBatch]:
        for name in sorted(m for m in dir(cls()) if m.startswith("test_")):
            total += 1
            try:
                getattr(cls(), name)()
                passed += 1
            except Exception as e:
                failed += 1
                print(f"FAIL {cls.__name__}.{name}: {e}")
    print(f"EDTF: {passed}/{total} passed, {failed} failed")
