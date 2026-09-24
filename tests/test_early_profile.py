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

    def test_a_buy_through_usd1_is_a_buy_not_a_sale_of_usd1(self):
        usd1 = "USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB"
        [e] = events([swap(1, usd1, 100.0, "TOKA", 1000, 100.0)])
        self.assertEqual((e["type"], e["mint"]), ("buy", "TOKA"))

    def test_token_for_token_counts_as_one_swap(self):
        raws = [swap(3, SOL, 1.0, "TOKA", 1000, 100.0), swap(2, "TOKA", 1000, "TOKB", 50, 120.0, give_px=0.12, get_px=2.4)]
        self.assertEqual(profile.summary(events(raws), W, NOW)["swaps"], 2)

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


class TestCardExtras(unittest.TestCase):
    """Те, що картка показує понад PnL і win rate: розподіл, дні, серії, мапа активності, останні токени."""
    RAWS = TestSummary.RAWS

    def test_same_arithmetic_as_the_table(self):
        from tracced.early import ledger
        evs = events(self.RAWS)
        books, _ = profile._replay(evs)
        for mint in {e["mint"] for e in evs}:
            L, _ = ledger.build([e for e in evs if e["mint"] == mint], 0, NOW, NOW)
            self.assertAlmostEqual(books[mint].realized, L[W].realized, places=6)   # таблиця і картка — одне число
            self.assertAlmostEqual(books[mint].invested, L[W].invested, places=6)

    def test_distribution_days_streaks_and_drawdown(self):
        s = profile.summary(events(self.RAWS), W, NOW, days=30)
        self.assertEqual((s["buys"], s["sells"], s["losses"]), (3, 3, 1))
        self.assertAlmostEqual(s["volume_usd"], 100 + 150 + 200 + 120 + 50 + 30)
        self.assertEqual(s["dist"]["50-200"], 1)                  # TOKA: +50 на 100
        self.assertEqual(s["dist"]["-50-0"], 1)                   # TOKB: −80 на 200 = −40 %
        self.assertEqual([round(v) for _, v in s["daily"]], [50, -80])
        self.assertEqual((s["best_day"]["usd"], s["worst_day"]["usd"]), (50, -80))
        self.assertEqual((s["win_streak"], s["loss_streak"]), (1, 1))
        self.assertAlmostEqual(s["max_drawdown_usd"], 80)         # з +50 до −30

    def test_seven_days_is_its_own_window(self):
        c = profile.card(events(self.RAWS), W, NOW)
        self.assertAlmostEqual(c["pnl_usd"], -30)                  # верхній рівень = 30 днів, як і раніше
        seven = c["periods"]["7"]
        self.assertEqual(seven["closed"], 0)                       # купівлі TOKB і TOKA старші за тиждень
        self.assertEqual(seven["unbacked_tokens"], 2)              # TOKB (продаж рівно на межі тижня) і TOKD
        self.assertEqual(seven["open"], 1)                         # TOKC

    def test_heatmap_and_recent_tokens(self):
        c = profile.card(events(self.RAWS), W, NOW)
        self.assertEqual(sum(map(sum, c["heat"])), 6)              # шість обмінів з позицією за 30 днів
        self.assertEqual(len(c["heat"]), 7)
        recent = {r["symbol"]: r for r in c["recent"]}
        self.assertEqual(recent["TOKC"]["state"], "open")
        self.assertEqual(recent["TOKD"]["state"], "sold only")
        self.assertAlmostEqual(recent["TOKA"]["roi"], 50)
        self.assertEqual(c["recent"][0]["symbol"], "TOKC")          # найсвіжіший угорі


class TestIdentity(unittest.TestCase):
    def test_only_what_we_show_survives(self):
        idn = profile.compact_identity({"name": "Cented", "twitter": "@Cented7", "avatar": "https://x/y.png", "type": "kol",
                                        "tags": ["kol", "axiom"], "platforms": ["axiom"], "sns": {"domain": "cented.sol"}})
        self.assertEqual(idn, {"name": "Cented", "twitter": "@Cented7", "type": "kol", "tags": ["kol", "axiom"],
                               "platforms": ["axiom"], "sns": "cented.sol", "avatar": "https://x/y.png"})

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

    def test_trade_pages_never_ask_who_the_wallets_are(self):
        st = self.client([{"trades": [], "hasNextPage": False}])
        st.trades_page("MINT", NOW - 1)
        self.assertNotIn("enrich", st.paths[0])                   # 11 s a page with it on 24.09, 0.2 s without
        self.assertIn("limit=500", st.paths[0])


class TestIdentityBatch(unittest.TestCase):
    """Хто стоїть за гаманцем: пакетами по 100, кешуючи і відомих, і невідомих."""

    def client(self, answer):
        import threading
        st = EarlyST("k", pause=0, identity_cache=FakeCache())
        st.calls, lock = [], threading.Lock()

        def fake(path, body=None):
            with lock:
                st.calls.append((path, list((body or {}).get("wallets") or [])))
            return answer(body["wallets"])
        st._get = fake
        return st

    def test_batches_of_a_hundred_and_only_known_wallets_come_back(self):
        ws = [f"W{i:03d}" for i in range(250)]

        def answer(chunk):
            return {"wallets": [{"wallet": w, "identity": {"name": "Cented", "twitter": "@Cented7", "type": "kol"}}
                                for w in chunk if w == "W007"],
                    "notFound": [w for w in chunk if w != "W007"]}
        st = self.client(answer)
        got = st.identities(ws)
        self.assertEqual(sorted(len(c[1]) for c in st.calls), [50, 100, 100])
        self.assertTrue(all(c[0] == "/v2/pnl/wallets/batch" for c in st.calls))
        self.assertEqual(got, {"W007": {"name": "Cented", "twitter": "@Cented7", "type": "kol"}})
        st.calls.clear()
        self.assertEqual(st.identities(ws), got)                  # другий раз — з кешу, і невідомі теж
        self.assertEqual(st.calls, [])
        self.assertIsNone(st.identity("W008"))

    def test_a_failed_batch_leaves_those_wallets_unasked_not_unknown(self):
        def answer(chunk):
            if "W000" in chunk:
                raise RuntimeError("down")
            return {"wallets": [], "notFound": chunk}
        st = self.client(answer)
        self.assertEqual(st.identities([f"W{i:03d}" for i in range(150)]), {})
        st.calls.clear()
        st.identities([f"W{i:03d}" for i in range(150)])
        self.assertEqual([len(c[1]) for c in st.calls], [100])    # збій не записався як «невідомий»: спитаємо ще


class TestNamer(unittest.TestCase):
    def test_names_come_in_one_pass_and_are_not_asked_twice(self):
        from types import SimpleNamespace
        from tracced.web.app import make_namer
        rows = [{"wallet": "W1"}, {"wallet": "W2"}]
        job = SimpleNamespace(result={"rows": rows}, log=[])
        saved, asked = [], []
        namer = make_namer(lambda ws: (asked.append(ws), {"W2": {"name": "Cented", "type": "kol"}})[1])
        namer(job, saved.append)
        self.assertEqual(job.result["identities"], {"W2": {"name": "Cented", "type": "kol"}})
        self.assertTrue(job.result["identities_done"])
        namer(job, saved.append)
        self.assertEqual((len(asked), len(saved)), (1, 1))


if __name__ == "__main__":
    unittest.main()
