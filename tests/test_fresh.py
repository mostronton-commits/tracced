"""Свіжі пампи на головній: відбір, піки, пам'ять піків і сама сторінка. Без мережі."""
import unittest

from tracced.early import settings
from tracced.web import fresh as F

S = settings.DEFAULTS
NOW = 1_790_800_000_000
H = 3_600_000


def row(mint, cap, liq=100_000, vol=None, sym=None, age_h=5, image="", fees=500.0, buys=1000, sells=800):
    sym = sym or mint                                    # one name per token unless a test makes clones
    return {"mint": mint, "symbol": sym, "name": sym, "marketCapUsd": cap, "liquidityUsd": liq,
            "volume_24h": cap if vol is None else vol, "createdAt": NOW - age_h * H, "image": image,
            "fees": {"total": fees}, "buys": buys, "sells": sells}


class TestPick(unittest.TestCase):
    def test_turnover_drops_the_inflated_clones(self):
        # 30.09: UDR $3.45B with a day's volume of $465K (0.0001 of the cap) — a clone; SI $5M with $15.6M — a pump
        c = F.candidates([row("UDR", 3.45e9, 5.3e6, 4.65e5), row("SI", 5e6, 2.65e5, 1.56e7), row("SI", 5e6, 2.65e5, 1.56e7),
                          row("LOW", 2e5), row("DRY", 2e6, liq=2e4), {"bad": 1}, None], S)
        self.assertEqual([x["mint"] for x in c], ["SI"])                      # no clone, no double, nothing under the bars

    def test_an_always_rising_chart_stays_out(self):
        # JUMP, 30.09: $2.9M cap, a day's volume 12× the cap, no fees paid by anyone, 32,380 buys to 4,345 sells
        jump = row("JUMP", 2.9e6, 4.1e5, 3.5e7, fees=0.0, buys=32380, sells=4345)
        bandit = row("BANDIT", 1.3e6, 1.09e5, 1e6, fees=358.9, buys=2879, sells=1909)
        self.assertEqual([x["mint"] for x in F.candidates([jump, bandit], S)], ["BANDIT"])
        self.assertEqual(F.candidates([row("A", 2e6, fees=0.4)], S), [])                     # hardly any fees: no live trading
        self.assertEqual(F.candidates([row("B", 2e6, buys=1000, sells=100)], S), [])          # one sell to ten buys

    def test_the_peak_decides_and_sorts(self):
        c = F.candidates([row("A", 1.5e6), row("B", 3e6), row("C", 1.2e6)], S)
        out = F.pick(c, {"A": 2.5e6, "C": 1.9e6}, NOW, S)
        self.assertEqual([(x["mint"], x["peak"], x["drop"]) for x in out], [("B", 3e6, 0), ("A", 2.5e6, 40)])   # C never reached $2M
        self.assertEqual(round(out[0]["age_h"]), 5)
        self.assertEqual(F.pick(c, {"B": 1e6}, NOW, S)[0]["peak"], 3e6)                  # a stale peak never sits under the cap

    def test_only_the_trackers_own_image_host(self):
        c = F.candidates([row("A", 3e6, image="https://image.solanatracker.io/proxy?url=x"), row("B", 3e6, image="https://ipfs.io/ipfs/x")], S)
        self.assertEqual([x["image"][:30] for x in c], ["https://image.solanatracker.io", ""])

    def test_search_asks_for_the_owners_bars(self):
        q = F.search_path(NOW, S)
        for part in ("minCreatedAt=%d" % (NOW - 48 * H), "minMarketCap=250000", "minLiquidity=25000", "minHolders=500", "sortBy=marketCapUsd",
                     "minFeesTotal=5", "limit=500"):
            self.assertIn(part, q)


class FakeST:
    def __init__(self):
        self.calls = []

    def _get(self, path):
        self.calls.append(path)
        if path.startswith("/search"):
            return {"data": [row("A", 1.5e6), row("B", 3e6), row("Z", 4e9, vol=1e3)], "hasMore": False}
        return {"highest_market_cap": {"/tokens/A/ath": 2.2e6, "/tokens/B/ath": 7e6}.get(path, 0)}


class TestRefresh(unittest.TestCase):
    def test_a_peak_is_asked_once(self):
        st, peaks = FakeST(), {}
        out = F.refresh(st, S, peaks, NOW)
        self.assertEqual([(x["mint"], x["peak"]) for x in out], [("B", 7e6), ("A", 2.2e6)])
        self.assertEqual(sorted(c for c in st.calls if "/ath" in c), ["/tokens/A/ath", "/tokens/B/ath"])   # the clone costs nothing
        st.calls.clear()
        F.refresh(st, S, peaks, NOW + 5 * H)
        self.assertEqual([c for c in st.calls if "/ath" in c], [])                          # a peak only grows: never asked again
        F.refresh(st, S, peaks, NOW + 80 * H)
        self.assertEqual(peaks, {})                                                         # older than the 48 h window plus a day: forgotten

    def test_a_peak_the_tape_saw_itself_is_kept(self):
        # review 01.10: ATH asked at $1.2M said $1.5M, then the token ran to $4M and fell to $1.5M: it stays, with its $4M
        class ST:
            cap = 1.2e6
            def _get(self, path):
                if path.startswith("/search"):
                    return {"data": [row("R", self.cap)], "hasMore": False}
                return {"highest_market_cap": 1.5e6}
        st, peaks = ST(), {}
        need = dict(S, fresh_min_ath=2e6)
        self.assertEqual(F.refresh(st, need, peaks, NOW), [])                               # $1.5M peak: under the bar
        st.cap = 4e6
        self.assertEqual([x["peak"] for x in F.refresh(st, need, peaks, NOW + H)], [4e6])
        st.cap = 1.5e6
        out = F.refresh(st, need, peaks, NOW + 2 * H)
        self.assertEqual([(x["mint"], x["peak"], x["drop"]) for x in out], [("R", 4e6, 62)])   # not gone once it dumps

    def test_the_junk_the_server_cannot_see(self):
        rows = [row("WASH", 2.7e6, vol=2.72e6, fees=2.8), row("FAKE", 3e8, liq=1e6, vol=1e8), row("DEAD", 2e6, vol=1e6),
                row("OK", 2e6, vol=4e6, fees=300)]
        rows[2]["volume_1h"] = 1000
        self.assertEqual([x["mint"] for x in F.candidates(rows, dict(S, fresh_min_fees_sol=1))], ["OK"])   # wash, cap/liq 300, dead pool
        c = F.candidates([row("S1", 3e6, sym="SI"), row("S2", 5e6, sym="si")], S)
        self.assertEqual([x["mint"] for x in F.pick(c, {"S1": 9e6}, NOW, S)], ["S1"])            # one name, the bigger peak


if __name__ == "__main__":
    unittest.main()
