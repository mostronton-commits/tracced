import csv
import os
import tempfile
import unittest

from tracced.early import report

T0 = 1_000_000_000_000


def fact(wallet, realized, unrealized=0.0):
    return {"wallet": wallet, "first_buy_ms": T0, "entry_mcap_first": 100000.123,
            "entry_mcap_avg": 120000.0, "buys_in_range": 1, "invested_in_range_usd": 100.0,
            "buys": 1, "invested_usd": 100.0, "first_sell_ms": None,
            "last_sell_ms": None, "exit_mcap_avg": None, "sells": 0, "proceeds_usd": 0.0,
            "sold_share_pct": 0.0, "holding_share_pct": 100.0, "realized_usd": realized,
            "unrealized_usd": unrealized, "multiple": None, "hold_minutes": None,
            "bought_after_range": False, "partial_history": False}


class TestReport(unittest.TestCase):
    def test_csv_header_and_sort(self):
        rows = report.sort_rows([report.to_row(fact("A" * 44, 10)), report.to_row(fact("B" * 44, 50)),
                                 report.to_row(fact("C" * 44, 0, 70))])
        self.assertEqual([r["wallet"][0] for r in rows], ["C", "B", "A"])
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.csv")
            report.write_csv(rows, p)
            with open(p, newline="") as f:
                rd = csv.reader(f)
                self.assertEqual(next(rd), report.COLUMNS)
                self.assertEqual(len(list(rd)), 3)

    def test_to_row_formats(self):
        r = report.to_row(fact("W" * 44, 1.2345))
        self.assertEqual(r["first_buy_utc"], "2001-09-09 01:46")
        self.assertEqual(r["first_sell_utc"], "")
        self.assertEqual(r["entry_mcap_first"], 100000.12)
        self.assertTrue(r["solscan_url"].endswith("W" * 44))

    def test_markdown(self):
        res = {"info": {"mint": "M", "symbol": "TST", "created_time": T0, "supply": 1e6, "mcap": 2.5e6},
               "window": {"from": T0, "to": T0 + 1, "exit": T0 + 2},
               "counts": {"n_trades": 5, "n_early": 1, "late": 0, "pre_range_only": 0, "dust": 0},
               "requests": 3, "pages_fetched": 1, "rows": [report.to_row(fact("Q" * 44, 5))]}
        md = report.markdown(res)
        self.assertIn("QQQQQQ…QQQQ", md)
        self.assertIn("$2.50M", md)
        self.assertEqual(report.money(27_100_000), "$27.1M")
        self.assertEqual(report.money(950), "$950")


if __name__ == "__main__":
    unittest.main()


class TestUpgrade(unittest.TestCase):
    def test_upgrade_old_result(self):
        old = {"rows": [{"wallet": "A", "buys_in_window": 2, "invested_in_window_usd": 5.0, "bought_after_window": True,
                         "tags": "pre-window|re-bought", "tag_list": ["pre-window", "re-bought"]}],
               "counts": {"pre_window_only": 3}, "summary": {"invested_window": 5.0}}
        report.upgrade_result(old)
        r = old["rows"][0]
        self.assertEqual((r["buys_in_range"], r["invested_in_range_usd"], r["bought_after_range"]), (2, 5.0, True))
        self.assertNotIn("buys_in_window", r)
        self.assertEqual(r["tag_list"], ["pre-range", "re-bought"])
        self.assertEqual(old["counts"]["pre_range_only"], 3)
        self.assertEqual(old["summary"]["invested_range"], 5.0)
        report.upgrade_result(old)                                    # ідемпотентно
        self.assertEqual(old["rows"][0]["buys_in_range"], 2)

    def test_coverage_text(self):
        self.assertEqual(report.coverage_text({"exits_known": 5, "total": 5, "mode": "trades", "cost_full": 243}),
                         "Exits known for all 5 wallets · full trade history")
        self.assertIn("from cache", report.coverage_text({"exits_known": 5, "total": 5, "mode": "trades", "cost_full": 0}))
        self.assertEqual(report.coverage_text({"exits_known": 9, "total": 9, "mode": "wallet-trades", "cost_full": 50}),
                         "Exits known for all 9 wallets · each wallet's trades fetched")
        t = report.coverage_text({"exits_known": 250, "total": 1544, "mode": "wallet-trades", "cost_full": 243, "lookup_cap": 250, "plan": "free"})
        self.assertEqual(t, "Exits known for 250 of 1,544 wallets · the rest tagged no-exits (cap 250 wallets per analysis)")
        self.assertEqual(report.coverage_text(None), "")
