import unittest
from unittest import mock

from tracced.early import exchanges as exch_mod
from tracced.web import insights


def row(i, real=0.0, sold=100.0, inv=100.0, tags=()):
    return {"wallet": f"W{i:03d}", "realized_usd": real, "sold_share_pct": sold, "invested_in_range_usd": inv, "tag_list": list(tags)}


class TestInsights(unittest.TestCase):
    def test_conclusions_in_percent_in_order_of_weight(self):
        # 40 wallets: 30 in profit (top 10 hold most of it), 32 sold out, 12 fresh, 6 bundled with a quarter of the buying
        rows = [row(i, real=(10_000 if i < 10 else 100 if i < 30 else -50), sold=(100 if i < 32 else 20),
                    inv=(500 if i < 6 else 100), tags=(["bundle"] if i < 6 else []) + (["fresh"] if 10 <= i < 22 else []))
                for i in range(40)]
        out = insights.of_result({"rows": rows}, checked=40)
        self.assertEqual([x["k"] for x in out], ["bundle", "fresh", "top", "sold", "won"])
        self.assertEqual(out[0]["text"], "47% bought through bundles")       # 3,000 of 6,400
        self.assertEqual(out[1]["text"], "30% fresh wallets")
        self.assertEqual(out[2]["text"], "Top 10 took 98% of the profit")
        self.assertEqual(out[3]["text"], "80% already sold out")
        self.assertEqual(out[4]["text"], "75% took a profit")
        self.assertEqual(insights.headline({"rows": rows}, 40), "47% bought through bundles · 30% fresh wallets")

    def test_quiet_facts_stay_out(self):
        rows = [row(i, real=10, sold=(10 if i < 25 else 100)) for i in range(30)]   # an even spread, most still hold
        out = insights.of_result({"rows": rows})
        self.assertEqual([x["k"] for x in out], ["hold", "won"])               # no bundles, no fresh, profit not concentrated
        self.assertEqual(out[0]["text"], "83% still holding")
        self.assertEqual(insights.of_result({"rows": rows[:5]}), [])         # too few wallets for shares to mean anything
        self.assertEqual(insights.of_result({}), [])
        fresh = [row(i, tags=["fresh"] if i < 30 else []) for i in range(40)]           # an older result: all 40 checked
        out = insights.of_result({"rows": fresh, "ages": {f"W{i:03d}": {"ms": 1} for i in range(40)}}, checked=20)
        self.assertIn("75% fresh wallets", [x["text"] for x in out])                  # 30 of the 40 checked, never over 100%
        self.assertIn("100% fresh wallets", [x["text"] for x in insights.of_result({"rows": fresh}, checked=20)])   # all 30 known fresh
        almost = {"rows": fresh, "enrich": {"done": 31}}                                 # 30 fresh of 31 checked
        self.assertIn("97% fresh wallets", [x["text"] for x in insights.of_result(almost, checked=20)])
        self.assertEqual(insights._pct(299, 300), 99)                                   # never "100%" unless all
        self.assertEqual(insights.headline(None), "")

    def test_the_creator_and_the_exchanges(self):
        rows = [row(i, tags=["dev"] if i == 0 else []) for i in range(30)]
        funders = {f"W{i:03d}": ("EXCH" if i < 12 else f"F{i}") for i in range(30)}
        with mock.patch.dict(exch_mod.KNOWN, {"EXCH": ["Binance", "Binance hot wallet"]}):
            out = insights.of_result({"rows": rows, "funders": funders})
        self.assertEqual(out[0]["text"], "Creator bought in the range")
        self.assertIn({"k": "cex", "sev": "info", "pct": 40, "text": "40% funded from exchanges"}, out)
        rows[0]["tag_list"], rows[0]["tags"] = None, "dev|sniper"             # an old result keeps its tags as a string
        self.assertEqual(insights.of_result({"rows": rows})[0]["k"], "dev")


if __name__ == "__main__":
    unittest.main()
