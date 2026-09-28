"""Партнерське API: правила перевірки токена і ключі. Без сервера і без мережі."""
import json
import os
import tempfile
import unittest

from tracced.web import partner_api as api


def st_report(dev=3.4, bundle=27.7, launch=96.0, top10=24.6, snipers=12.0, insiders=0.0, mint=None, freeze=None,
              market="pumpfun-amm", lp_burn=100, liq=25_000.0, created=1_000_000, rugged=False, risk=True):
    """Відповідь Solana Tracker `/tokens/{mint}` у потрібній формі (значення — як у справжнього «AI6» 28.09)."""
    d = {"token": {"creation": {"created_time": created}},
         "pools": [{"market": market, "lpBurn": lp_burn, "liquidity": {"usd": liq},
                    "security": {"mintAuthority": mint, "freezeAuthority": freeze}}]}
    if risk:
        d["risk"] = {"dev": {"percentage": dev}, "top10": top10, "rugged": rugged,
                     "bundlers": {"totalPercentage": bundle, "totalInitialPercentage": launch},
                     "snipers": {"totalPercentage": snipers}, "insiders": {"totalPercentage": insiders}}
    return d


class TestRules(unittest.TestCase):
    def test_a_bundled_launch_fails_the_default_thresholds_and_shows_its_levels(self):
        out = api.evaluate(st_report(), api.DEFAULT_THRESHOLDS, now_s=1_000_000 + 120)
        self.assertEqual((out["passes"], out["failed"]), (False, ["bundle", "top10"]))
        self.assertEqual((out["high"], out["flags"], out["age_minutes"]), (["bundle", "bundled_launch"], "2 of 9", 2))
        self.assertEqual(out["levels"], {"dev": "low", "bundle": "high", "top10": "medium", "snipers": "medium", "insiders": "low",
                                         "bundled_launch": "high", "mint": "low", "freeze": "low", "liquidity": "low"})
        self.assertNotIn("27.7", json.dumps(out))                          # сирі частки назовні не йдуть

    def test_the_keys_thresholds_decide_passes(self):
        loose = {"dev": 30, "bundle": 30, "top10": 30}
        self.assertTrue(api.evaluate(st_report(), loose)["passes"])
        self.assertEqual(api.evaluate(st_report(dev=79.3, bundle=79.3, top10=92.4), loose)["failed"], ["dev", "bundle", "top10"])

    def test_a_clean_token_passes_with_every_rule_low(self):
        out = api.evaluate(st_report(dev=0, bundle=0, launch=0, top10=5, snipers=0), api.DEFAULT_THRESHOLDS)
        self.assertEqual((out["passes"], out["high"], out["flags"]), (True, [], "0 of 9"))
        self.assertEqual(set(out["levels"].values()), {"low"})

    def test_unknown_data_closes_the_check(self):
        out = api.evaluate(st_report(risk=False), api.DEFAULT_THRESHOLDS)
        self.assertEqual((out["passes"], out["failed"]), (False, ["no_data"]))   # фільтр скаму не пропускає те, чого не знає
        self.assertEqual(out["levels"]["dev"], "unknown")
        self.assertEqual(api.evaluate(st_report(rugged=True, dev=0, bundle=0, top10=1), api.DEFAULT_THRESHOLDS)["failed"], ["rugged"])

    def test_a_share_over_a_hundred_is_a_source_glitch_and_is_clipped(self):
        self.assertEqual(api.facts(st_report(launch=158.62))["bundled_launch"], 100.0)
        self.assertIsNone(api.facts(st_report(launch=float("nan")))["bundled_launch"])

    def test_liquidity_mint_and_freeze(self):
        lvl = lambda **kw: api.evaluate(st_report(**kw), {})["levels"]   # noqa: E731
        self.assertEqual(lvl(market="pumpfun", liq=3_000)["liquidity"], "low")          # крива лаунчпада: вивести не можна
        self.assertEqual(lvl(market="raydium-cpmm", lp_burn=0, liq=900_000)["liquidity"], "high")   # пул не спалено
        self.assertEqual(lvl(market="raydium-cpmm", liq=10_000)["liquidity"], "medium")
        self.assertEqual(lvl(market="raydium-cpmm", liq=3_000)["liquidity"], "high")
        self.assertEqual((lvl(mint="X")["mint"], lvl(freeze="Y")["freeze"]), ("high", "high"))
        # 28.09: pumpfun-amm спалено на 99 %, meteora-dyn на 97 % — це «не забрати», не ризик
        self.assertEqual(lvl(market="pumpfun-amm", lp_burn=99, liq=266_509)["liquidity"], "low")
        self.assertEqual(lvl(market="meteora-dyn-v2", lp_burn=97.08, liq=97_973)["liquidity"], "low")
        # DLMM/CLMM не мають LP-токенів: 0 % «спалено» там нічого не означає, лишається розмір
        self.assertEqual(lvl(market="meteora-dlmm", lp_burn=0, liq=227_557)["liquidity"], "low")
        self.assertEqual(lvl(market="raydium-clmm", lp_burn=0, liq=3_000)["liquidity"], "high")


class TestKeys(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = api.KeyStore(os.path.join(self.tmp.name, "api", "keys.json"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_key_is_kept_only_as_its_fingerprint(self):
        kid, key = self.store.create("pumpling")
        self.assertTrue(key.startswith("tr_") and len(key) > 30)
        with open(self.store.path) as f:
            self.assertNotIn(key, f.read())                                   # сам ключ на диск не потрапляє
        rec = self.store.find(key)
        self.assertEqual((rec["id"], rec["name"], rec["enabled"], rec["daily_cap"]), (kid, "pumpling", True, 1000))
        self.assertNotIn("hash", rec)
        self.assertEqual([k["id"] for k in self.store.all()], [kid])

    def test_regenerate_switch_off_and_delete(self):
        kid, old = self.store.create("p")
        new = self.store.rotate(kid)
        self.assertIsNone(self.store.find(old))                              # старий ключ одразу не діє
        self.assertEqual(self.store.find(new)["id"], kid)
        self.assertTrue(self.store.update(kid, enabled=False, daily_cap=5, thresholds={"dev": 10, "bundle": 10, "top10": 30}))
        rec = self.store.find(new)
        self.assertEqual((rec["enabled"], rec["daily_cap"], rec["thresholds"]["top10"]), (False, 5, 30))
        self.assertIsNone(self.store.rotate("nope"))
        self.assertFalse(self.store.update("nope", enabled=True))
        self.assertTrue(self.store.delete(kid))
        self.assertIsNone(self.store.find(new))
        for bad in ("", "tr_" + "é" * 10, "tr_" + "a" * 200, "nope", None):
            self.assertIsNone(self.store.find(bad))


if __name__ == "__main__":
    unittest.main()
