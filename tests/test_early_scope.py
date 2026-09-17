import unittest

from tracced.early import scope

T0 = 1_000_000_000_000
MIN = 60_000
H = 3_600_000
SUPPLY = 1_000_000


def tr(minute, side, qty, price):
    return [T0 + minute * MIN, side, float(qty), float(qty) * price, price]


def result(trades, source="wallet-trades"):
    return {"info": {"supply": SUPPLY, "created_time": T0 - H},
            "window": {"from": T0, "to": T0 + 20 * MIN, "end": T0 + 72 * H},
            "wallet_trades": {"W": {"trades": trades, "source": source}},
            "price_at_end": 5.0, "fresh_wallets": ["W"], "bundle": {"W": {"funder": "F", "n": 3}}}


class TestScope(unittest.TestCase):
    def test_scopes_and_end(self):
        self.assertEqual(scope.scopes_for({"scopes": [24, 48]}), ["all", "24h", "48h"])
        self.assertEqual(scope.end_for("all", T0, T0 + 99 * H), T0 + 99 * H)
        self.assertEqual(scope.end_for("24h", T0, T0 + 99 * H), T0 + 24 * H)
        self.assertEqual(scope.end_for("48h", T0, T0 + 10 * H), T0 + 10 * H)     # не далі за «зараз»

    def test_same_wallet_different_scopes(self):
        # купив до діапазону, купив у діапазоні, продав через 30 год, докупив через 50 год
        trades = [tr(-30, "buy", 100, 1.0), tr(5, "buy", 100, 2.0), tr(30 * 60, "sell", 150, 4.0), tr(50 * 60, "buy", 10, 3.0)]
        r = result(trades)
        rows_all, sm_all = scope.rows_for(r, "all")
        rows_24, _ = scope.rows_for(r, "24h")
        a, b = rows_all[0], rows_24[0]
        self.assertEqual(a["first_range_buy_utc"][:16], "2001-09-09 01:51")           # вхід у діапазоні
        self.assertAlmostEqual(a["entry_range_mcap"], 2.0 * SUPPLY)
        self.assertTrue(a["bought_before_range"])
        self.assertAlmostEqual(a["invested_before_range_usd"], 100)
        self.assertAlmostEqual(a["invested_in_range_usd"], 200)
        self.assertAlmostEqual(a["invested_usd"], 330)                               # уся історія: 100 + 200 + 30
        self.assertAlmostEqual(a["proceeds_usd"], 600)
        self.assertAlmostEqual(a["realized_usd"], 600 - 150 * 1.5)                   # середня ціна 1.5
        self.assertAlmostEqual(a["hold_minutes"], 30 * 60 - 5)                       # від входу в діапазоні до продажу
        self.assertIn("pre-range", a["tag_list"]); self.assertIn("re-bought", a["tag_list"]); self.assertIn("fresh", a["tag_list"]); self.assertIn("bundle", a["tag_list"])
        self.assertFalse(b["first_sell_utc"])                                        # у 24 год продажу ще нема
        self.assertAlmostEqual(b["invested_usd"], 300)
        self.assertEqual(b["sold_share_pct"], 0)
        self.assertAlmostEqual(b["unrealized_usd"], 200 * 2.0 - 300)                 # остання відома ціна ≤ кінця масштабу (2.0)
        self.assertAlmostEqual(a["unrealized_usd"], (200 + 10 - 150) * 5.0 - (330 - 150 * 1.5))   # уся історія: ціна «зараз» 5.0
        self.assertEqual(sm_all["n"], 1)

    def test_entry_only_source(self):
        r = result([tr(5, "buy", 100, 2.0)], source="entry-only")
        rows, _ = scope.rows_for(r, "all")
        self.assertEqual(rows[0]["source"], "entry-only")
        self.assertIsNone(rows[0]["realized_usd"])
        self.assertIn("no-exits", rows[0]["tag_list"])

    def test_old_result_without_trades(self):
        self.assertIsNone(scope.rows_for({"rows": [{"wallet": "W"}], "window": {}}, "all"))


if __name__ == "__main__":
    unittest.main()
