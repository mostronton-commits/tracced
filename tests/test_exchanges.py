"""Відомі біржі серед спонсорів: назва замість адреси, без запитів і без бандлів."""
import unittest

from tracced.early import agent, exchanges
from tracced.web.app import _check_services

BINANCE_1 = "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9"
COINBASE_1 = "H8sMJSCQxfKiFTCfDR3DUMLPwcRbM61LGFJ8N4dK3WjS"


class TestExchanges(unittest.TestCase):
    def test_the_list_is_there_and_names_what_it_knows(self):
        self.assertGreaterEqual(len(exchanges.KNOWN), 150)
        self.assertEqual((exchanges.name_of(BINANCE_1), exchanges.name_of(COINBASE_1)), ("Binance", "Coinbase"))
        self.assertEqual(exchanges.KNOWN[BINANCE_1], ["Binance", "Binance 1"])
        self.assertIsNone(exchanges.name_of("A" * 44))

    def test_a_known_exchange_is_a_service_without_a_paid_check(self):
        asked = []

        class Ages:
            def is_service(self, f):
                asked.append(f)
                return False
        ws = [c * 44 for c in "BCDEFG"]
        r = {"funders": {ws[0]: BINANCE_1, ws[1]: BINANCE_1, ws[2]: BINANCE_1, ws[3]: "X" * 44, ws[4]: "X" * 44, ws[5]: "X" * 44}}
        _check_services(r, Ages())
        self.assertIn(BINANCE_1, r["services"])
        self.assertEqual(asked, ["X" * 44])                                      # біржу не питали: 1 кредит зекономлено

    def test_the_agent_says_the_exchange(self):
        w = "W" * 44
        res = {"info": {"symbol": "T"}, "window": {}, "summary": {},
               "rows": [{"wallet": w, "realized_usd": 100, "multiple": 2.0, "hold_minutes": 30, "tag_list": [], "invested_in_range_usd": 50}],
               "funders": {w: BINANCE_1}}
        d, _ = agent.digest(res)
        self.assertEqual(d["top_by_pnl"][0]["funded_by"], "Binance (exchange)")
        self.assertEqual(d["tags"]["funded_straight_from_exchanges"], {"Binance": 1})


if __name__ == "__main__":
    unittest.main()
