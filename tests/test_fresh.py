"""Свіжі пампи на головній: відбір, піки, пам'ять піків і сама сторінка. Без мережі."""
import unittest

from tracced.early import settings
from tracced.web import fresh as F

S = settings.DEFAULTS
NOW = 1_790_800_000_000
H = 3_600_000


def row(mint, cap, liq=100_000, vol=None, sym="X", age_h=5, image=""):
    return {"mint": mint, "symbol": sym, "name": sym, "marketCapUsd": cap, "liquidityUsd": liq,
            "volume_24h": cap if vol is None else vol, "createdAt": NOW - age_h * H, "image": image}


class TestPick(unittest.TestCase):
    def test_turnover_drops_the_inflated_clones(self):
        # 30.09: UDR $3.45B with a day's volume of $465K (0.0001 of the cap) — a clone; SI $5M with $15.6M — a pump
        c = F.candidates([row("UDR", 3.45e9, 5.3e6, 4.65e5), row("SI", 5e6, 2.65e5, 1.56e7), row("SI", 5e6, 2.65e5, 1.56e7),
                          row("LOW", 9e5), row("DRY", 2e6, liq=5e4), {"bad": 1}, None], S)
        self.assertEqual([x["mint"] for x in c], ["SI"])                      # no clone, no double, nothing under the bars

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
        for part in ("minCreatedAt=%d" % (NOW - 24 * H), "minMarketCap=1000000", "minLiquidity=80000", "minHolders=500", "sortBy=marketCapUsd"):
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
    def test_peaks_are_remembered_for_an_hour(self):
        st, peaks = FakeST(), {}
        out = F.refresh(st, S, peaks, NOW)
        self.assertEqual([(x["mint"], x["peak"]) for x in out], [("B", 7e6), ("A", 2.2e6)])
        self.assertEqual(sorted(c for c in st.calls if "/ath" in c), ["/tokens/A/ath", "/tokens/B/ath"])   # the clone costs nothing
        st.calls.clear()
        F.refresh(st, S, peaks, NOW + 30 * 60_000)
        self.assertEqual([c for c in st.calls if "/ath" in c], [])                          # half an hour later: from memory
        F.refresh(st, S, peaks, NOW + 61 * 60_000)
        self.assertEqual(len([c for c in st.calls if "/ath" in c]), 2)


if __name__ == "__main__":
    unittest.main()
