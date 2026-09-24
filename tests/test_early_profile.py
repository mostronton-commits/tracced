"""Картка гаманця: обміни по всіх токенах → наш 30-денний підсумок. Без мережі."""
import unittest

from tracced.early import profile
from tracced.early.st_client import EarlyST

NOW = 1_790_000_000_000
DAY = profile.DAY
W = "Wa11et1111111111111111111111111111111111"
SOL, USDC = profile.WSOL, "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def swap(days_ago, give, give_amt, get, get_amt, usd, sol=None, give_px=None, get_px=None, tx=None):
    """Один запис /wallet/{owner}/trades: нога from — віддав, to — отримав."""
    return {"tx": tx or f"tx-{days_ago}-{give[:3]}-{get[:3]}", "wallet": W, "program": "pumpfun-amm",
            "time": NOW - int(days_ago * DAY),
            "from": {"address": give, "amount": give_amt, "token": {"symbol": give[:4]}, "priceUsd": give_px},
            "to": {"address": get, "amount": get_amt, "token": {"symbol": get[:4]}, "priceUsd": get_px},
            "volume": {"usd": usd, "sol": sol if sol is not None else usd / 100}, "price": {"usd": 1.0, "sol": "0.01"}}


def events(raws):
    return [e for r in raws for e in profile.normalize_wallet_swap(r, W)]


class TestNormalize(unittest.TestCase):
    def test_sol_for_a_token_is_a_buy_of_that_token(self):
        [e] = events([swap(1, SOL, 1.0, "TOKA", 1000, 100.0)])
        self.assertEqual((e["type"], e["mint"], e["qty"], e["usd"], e["sol"]), ("buy", "TOKA", 1000, 100.0, 1.0))

    def test_a_token_for_usdc_is_a_sell(self):
        [e] = events([swap(1, "TOKA", 1000, USDC, 150.0, 150.0)])
        self.assertEqual((e["type"], e["mint"], e["usd"]), ("sell", "TOKA", 150.0))

    def test_token_for_token_is_a_sell_and_a_buy_each_at_its_own_price(self):
        sell, buy = events([swap(1, "TOKA", 1000, "TOKB", 50, 90.0, give_px=0.1, get_px=2.0)])
        self.assertEqual((sell["type"], sell["mint"], sell["usd"]), ("sell", "TOKA", 100.0))
        self.assertEqual((buy["type"], buy["mint"], buy["usd"]), ("buy", "TOKB", 100.0))

    def test_money_for_money_is_not_a_position(self):
        self.assertEqual(events([swap(1, SOL, 1.0, USDC, 150.0, 150.0)]), [])

    def test_broken_rows_are_skipped(self):
        self.assertEqual(events([{"tx": "x", "wallet": W}]), [])
        self.assertEqual(events([swap(1, SOL, 1.0, "TOKA", 0, 100.0)]), [])


class TestSummary(unittest.TestCase):
    RAWS = [
        swap(10, SOL, 1.0, "TOKA", 1000, 100.0), swap(9, "TOKA", 1000, SOL, 1.5, 150.0),      # закрита: +50
        swap(8, SOL, 2.0, "TOKB", 500, 200.0), swap(7, "TOKB", 500, SOL, 1.2, 120.0),         # закрита: -80
        swap(2, SOL, 0.5, "TOKC", 100, 50.0),                                                  # відкрита
        swap(5, "TOKD", 100, SOL, 0.3, 30.0),                                                  # продаж без купівлі
        swap(40, SOL, 9.0, "TOKA", 9000, 900.0),                                               # старше 30 днів
        swap(3, SOL, 1.0, USDC, 150.0, 150.0),                                                 # гроші на гроші
    ]

    def test_thirty_days_counted_by_our_ledger(self):
        s = profile.summary(events(self.RAWS), W, NOW, days=30)
        self.assertAlmostEqual(s["pnl_usd"], -30.0)
        self.assertAlmostEqual(s["pnl_sol"], (1.5 - 1.0) + (1.2 - 2.0))
        self.assertEqual((s["closed"], s["wins"], s["open"], s["tokens"]), (2, 1, 1, 3))
        self.assertAlmostEqual(s["win_rate"], 0.5)
        self.assertEqual(s["unbacked_tokens"], 1)                 # TOKD продано без купівлі: не заробіток
        self.assertEqual(s["swaps"], 6)                           # старший за 30 днів не рахується
        self.assertAlmostEqual(s["avg_hold_min"], 24 * 60)        # обидві закриті тримали добу
        self.assertEqual([b["mint"] for b in s["best"]], ["TOKA"])
        self.assertFalse(s["partial"])

    def test_no_closed_positions_means_no_win_rate(self):
        s = profile.summary(events([swap(2, SOL, 0.5, "TOKC", 100, 50.0)]), W, NOW)
        self.assertIsNone(s["win_rate"])
        self.assertEqual(s["open"], 1)

    def test_a_missing_sol_amount_hides_the_sol_total(self):
        raws = [swap(10, SOL, 1.0, "TOKA", 1000, 100.0), swap(9, "TOKA", 1000, SOL, 1.5, 150.0)]
        raws[1]["volume"] = {"usd": 150.0}
        self.assertIsNone(profile.summary(events(raws), W, NOW)["pnl_sol"])


class TestIdentity(unittest.TestCase):
    def test_only_what_we_show_survives(self):
        idn = profile.compact_identity({"name": "Cented", "twitter": "@Cented7", "avatar": "https://x/y.png", "type": "kol",
                                        "tags": ["kol", "axiom"], "platforms": ["axiom"], "sns": {"domain": "cented.sol"}})
        self.assertEqual(idn, {"name": "Cented", "twitter": "@Cented7", "type": "kol", "tags": ["kol", "axiom"],
                               "platforms": ["axiom"], "sns": "cented.sol"})

    def test_unknown_wallet_is_none(self):
        self.assertIsNone(profile.compact_identity(None))
        self.assertIsNone(profile.compact_identity({}))


class FakeCache(dict):
    def put(self, k, v):
        self[k] = v

    def flush(self):
        pass


class TestClient(unittest.TestCase):
    """Сторінки угод гаманця і збір ідентичності: відповіді ST підставлені, мережі нема."""

    def client(self, pages, identity=True):
        st = EarlyST("k", pause=0, identity_cache=FakeCache() if identity else None)
        st.paths = []

        def fake(path):
            st.paths.append(path)
            return pages.pop(0)
        st._get = fake
        return st

    def test_pages_stop_at_the_date_and_drop_the_repeated_boundary(self):
        a = swap(1, SOL, 1.0, "TOKA", 1000, 100.0, tx="a")
        b = swap(20, SOL, 1.0, "TOKB", 1000, 100.0, tx="b")
        c = swap(35, SOL, 1.0, "TOKC", 1000, 100.0, tx="c")
        st = self.client([{"trades": [a, b], "hasNextPage": True, "nextCursor": b["time"]},
                          {"trades": [b, c], "hasNextPage": True, "nextCursor": c["time"]}])
        raw, partial = st.wallet_swaps(W, NOW - 30 * DAY, max_pages=5)
        self.assertEqual([r["tx"] for r in raw], ["a", "b", "c"])
        self.assertFalse(partial)                                 # дійшли до дати старше 30 днів
        self.assertEqual(len(st.paths), 2)
        self.assertIn(f"cursor={b['time']}", st.paths[1])

    def test_running_out_of_pages_is_partial(self):
        pages = [{"trades": [swap(1 + i, SOL, 1.0, "TOKA", 1, 1.0, tx=f"t{i}")], "hasNextPage": True, "nextCursor": i + 1}
                 for i in range(3)]
        st = self.client(pages)
        raw, partial = st.wallet_swaps(W, NOW - 30 * DAY, max_pages=3)
        self.assertTrue(partial)
        self.assertEqual(len(raw), 3)

    def test_identity_rides_along_with_the_trade_pages(self):
        page = {"trades": [{"wallet": "K1", "type": "buy", "time": NOW, "amount": 1, "volume": 1, "priceUsd": 1, "tx": "t1",
                            "identity": {"name": "Cented", "twitter": "@Cented7", "type": "kol"}},
                           {"wallet": "U1", "type": "buy", "time": NOW, "amount": 1, "volume": 1, "priceUsd": 1, "tx": "t2",
                            "identity": None}], "hasNextPage": False}
        st = self.client([page])
        st.trades_page("MINT", NOW - 1)
        self.assertIn("enrich=identity", st.paths[0])
        self.assertEqual(st.identity("K1"), {"name": "Cented", "twitter": "@Cented7", "type": "kol"})
        self.assertIsNone(st.identity("U1"))

    def test_a_refused_identity_parameter_does_not_sink_the_analysis(self):
        import io
        import urllib.error
        st = EarlyST("k", pause=0, identity_cache=FakeCache())
        st.paths = []

        def fake(path):
            st.paths.append(path)
            if "enrich" in path:
                raise urllib.error.HTTPError(path, 400, "bad param", {}, io.BytesIO(b""))
            return {"trades": [], "hasNextPage": False}
        st._get = fake
        self.assertEqual(st.trades_page("MINT", NOW - 1)["trades"], [])
        st.trades_page("MINT", NOW)
        self.assertEqual(len(st.paths), 3)                        # відмова, повтор без параметра, далі одразу без нього
        self.assertNotIn("enrich", st.paths[2])

    def test_history_pages_do_not_ask_who_the_wallets_are(self):
        st = self.client([{"trades": [], "hasNextPage": False}])
        st.trades_page("MINT", NOW - 1, identity=False)
        self.assertNotIn("enrich", st.paths[0])

    def test_without_the_cache_nothing_is_asked(self):
        st = self.client([{"trades": [], "hasNextPage": False}], identity=False)
        st.trades_page("MINT", NOW - 1)
        self.assertNotIn("enrich", st.paths[0])
        self.assertIn("limit=500", st.paths[0])


if __name__ == "__main__":
    unittest.main()
