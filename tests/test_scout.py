"""Offline tests: no network, no live markup.

Run with ``python -m unittest discover tests`` or ``python tests/test_scout.py``.
"""
from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from gravelscout.config import Config
from gravelscout.geometry import FitWindow, Geometry, GeometryDB, check_fit
from gravelscout.models import Listing
from gravelscout.normalize import norm, parse_price
from gravelscout.scoring import assess
from gravelscout.sizing import SizeWindow, parse_size
from gravelscout.sources.base import HttpClient
from gravelscout.sources.dvabike import DvaBike
from gravelscout.sources.kupujemprodajem import KupujemProdajem
from gravelscout.specs import (detect_bar, detect_brakes, detect_groupset,
                               detect_type_with_model)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


class TestNormalize(unittest.TestCase):
    def test_cyrillic_and_diacritics(self):
        self.assertEqual(norm("Шимано ГРX"), "simano grx")
        self.assertEqual(norm("Šimano več đir"), "simano vec djir")

    def test_prices(self):
        self.assertEqual(parse_price("1.450 €")[0], 1450.0)
        self.assertEqual(parse_price("1200 eur")[0], 1200.0)
        self.assertAlmostEqual(parse_price("140.000 din")[0], 1196.58, places=1)
        self.assertIsNone(parse_price("kao nov, bez cene")[0])


class TestSpecs(unittest.TestCase):
    def test_gravel_beats_road_label(self):
        d = detect_type_with_model("Drumski bicikl Specialized Diverge, 52cm")
        self.assertEqual(d.value, "gravel")

    def test_mtb_rejected(self):
        self.assertEqual(detect_type_with_model("Brdski MTB bicikl").value, "mtb")

    def test_grx_codes(self):
        g = detect_groupset("Shimano GRX RX810 2x11")
        self.assertEqual((g.family, g.model_code, g.speeds, g.chainrings), ("grx", "rx810", 11, 2))
        self.assertEqual(g.tier, 5)

    def test_tiagra_total_gear_count(self):
        g = detect_groupset("Tiagra, 20 brzina")
        self.assertEqual((g.family, g.chainrings, g.speeds), ("tiagra", 2, 10))

    def test_brakes(self):
        self.assertEqual(detect_brakes("hidraulicne disk kocnice").value, "hydraulic_disc")
        self.assertEqual(detect_brakes("mehanicke disk kocnice").value, "mechanical_disc")
        self.assertEqual(detect_brakes("felnaste kocnice").value, "rim")
        self.assertEqual(detect_brakes("disk kocnice").value, "disc_unknown_actuation")

    def test_bar(self):
        self.assertEqual(detect_bar("spusteni volan").value, "drop")
        self.assertEqual(detect_bar("ravan volan").value, "flat")


class TestSizing(unittest.TestCase):
    def test_wheel_size_is_not_frame_size(self):
        self.assertIsNone(parse_size("bicikl 28 inca, kao nov").cm)

    def test_letter_and_cm(self):
        s = parse_size("Giant Revolt vel. S/52, 700c")
        self.assertEqual((s.letter, s.cm), ("s", 52.0))

    def test_window(self):
        w = SizeWindow()
        self.assertEqual(w.check(parse_size("vel. 58"))[0], "out")
        self.assertEqual(w.check(parse_size("vel. 52"))[0], "ok")
        self.assertEqual(w.check(parse_size("bicikl povoljno"))[0], "unknown")


class TestFit(unittest.TestCase):
    def setUp(self):
        self.db = GeometryDB()
        self.window = Config.load().fit_window(self.db)

    def test_anchor_fits_itself(self):
        rows = self.db.lookup("liv", "devote", size="S")
        self.assertTrue(rows)
        self.assertEqual(check_fit(rows[0], self.window).verdict, "fit")

    def test_too_tall_frame_fails(self):
        g = Geometry(brand="x", model="y", size="L", stack=640, reach=390)
        self.assertEqual(check_fit(g, self.window).verdict, "no-fit")

    def test_stem_swap_is_close_not_fail(self):
        g = Geometry(brand="x", model="y", size="M", stack=560, reach=404)
        self.assertEqual(check_fit(g, self.window).verdict, "close")

    def test_standover_blocks(self):
        w = FitWindow(500, 600, 350, 400, standover_max=780)
        g = Geometry(brand="x", model="y", size="M", stack=560, reach=380, standover=800)
        self.assertEqual(check_fit(g, w).verdict, "no-fit")


class TestAssess(unittest.TestCase):
    def setUp(self):
        self.cfg, self.db = Config.load(), GeometryDB()

    def _a(self, title, desc="", price=None):
        return assess(Listing(source="t", source_id="1", url="u", title=title,
                              description=desc, price_eur=price), self.cfg, self.db)

    def test_ideal_listing_matches(self):
        a = self._a("Liv Devote Advanced 2 vel. S",
                    "zenski gravel, Shimano GRX 600 2x11, hidraulicne disk kocnice", 1500)
        self.assertEqual(a.verdict, "match")
        self.assertEqual(a.fit["verdict"], "fit")

    def test_rim_brakes_rejected(self):
        a = self._a("Gravel 52", "GRX 600, felnaste kocnice")
        self.assertEqual(a.verdict, "reject")
        self.assertTrue(any("rim" in b for b in a.blockers))

    def test_sora_rejected(self):
        a = self._a("Gravel bicikl 52", "Shimano Sora 2x9, hidraulicne disk kocnice")
        self.assertEqual(a.verdict, "reject")

    def test_big_frame_rejected(self):
        a = self._a("Canyon Grizl 58cm", "GRX RX810, hidraulika, gravel")
        self.assertEqual(a.verdict, "reject")

    def test_thin_ad_is_maybe_not_reject(self):
        a = self._a("Gravel bicikl povoljno", "malo koriscen, vel 52")
        self.assertEqual(a.verdict, "maybe")
        self.assertTrue(a.unknowns)

    def test_mtb_rejected(self):
        self.assertEqual(self._a("MTB Scott", "Deore, hidraulicne disk").verdict, "reject")


class TestParsers(unittest.TestCase):
    def _http(self):
        return HttpClient(user_agent="test", delay_seconds=0)

    def test_kupujemprodajem_json_strategy(self):
        html = (FIXTURES / "kupujemprodajem_list.html").read_text(encoding="utf-8")
        src = KupujemProdajem({}, self._http())
        found = src.parse_page(html, "https://www.kupujemprodajem.com/bicikli")
        self.assertEqual(len(found), 2)
        gravel = next(l for l in found if "Revolt" in l.title)
        self.assertEqual(gravel.price_eur, 1450.0)
        self.assertEqual(gravel.location, "Beograd")
        self.assertTrue(gravel.url.endswith("/oglas/191861429"))
        self.assertTrue(gravel.images)

    def test_2bike_html_strategy_skips_categories(self):
        html = (FIXTURES / "2bike_list.html").read_text(encoding="utf-8")
        src = DvaBike({}, self._http())
        found = src.parse_page(html, "https://www.2bike.rs/cikloberza")
        titles = sorted(l.title for l in found)
        self.assertEqual(len(found), 2, f"got {titles}")
        grizl = next(l for l in found if "Grizl" in l.title)
        self.assertEqual(grizl.price_eur, 1850.0)
        self.assertEqual(grizl.source_id, "44231")
        bianchi = next(l for l in found if "Bianchi" in l.title)
        self.assertAlmostEqual(bianchi.price_eur, 1025.64, places=1)

    def test_end_to_end_filtering_over_fixture(self):
        cfg, db = Config.load(), GeometryDB()
        html = (FIXTURES / "2bike_list.html").read_text(encoding="utf-8")
        found = DvaBike({}, self._http()).parse_page(html, "https://www.2bike.rs/cikloberza")
        verdicts = {l.title.split(",")[0]: assess(l, cfg, db).verdict for l in found}
        self.assertEqual(verdicts["Canyon Grizl 7 GRX RX810"], "match")
        self.assertEqual(verdicts["Bianchi Via Nirone 7 Sora"], "reject")


if __name__ == "__main__":
    unittest.main(verbosity=2)
