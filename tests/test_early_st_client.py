"""Клієнт early поверх кешів: живий край графіка, свіжі угоди для прогону, запис кешів без спільного замка. Без мережі."""
import threading
import time
import unittest

from tracced.cache import JsonCache
from tracced.early.st_client import EarlyST

H = 3_600_000
MINT = "M" * 40


def client(**caches):
    st = EarlyST("k", pause=0, **caches)
    st.paths = []

    def fake(path, body=None):
        st.paths.append(path)
        if body is not None:
            return {"wallets": [], "notFound": body["wallets"]}
        if path.startswith("/chart/"):
            return {"oclhv": [{"time": 1_790_000_000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}]}
        return {"trades": list(st.feed), "hasNextPage": False}
    st._get = fake
    st.feed = []
    return st


class TestChartLiveEdge(unittest.TestCase):
    """Шматок, що доходить до «зараз», ще росте: з кешу він віддав би графік, застиглий на першому перегляді."""

    def test_a_past_chunk_is_cached_and_free(self):
        st = client(chart_cache=JsonCache(None))
        a = int(time.time() * 1000) - 48 * H
        st.chart(MINT, "1m", a, a + 12 * H)
        self.assertTrue(st.chart_cached(MINT, "1m", a, a + 12 * H))
        st.chart(MINT, "1m", a, a + 12 * H)
        self.assertEqual(len(st.paths), 1)

    def test_the_live_chunk_is_shared_for_a_minute_then_fetched_again(self):
        from unittest import mock
        from tracced.early import st_client
        st = client(chart_cache=JsonCache(None))
        now = int(time.time() * 1000)
        for b in (now + H, now - 60_000):                            # у майбутньому і хвилину тому — обидва живі
            st.paths.clear()
            self.assertFalse(st.chart_cached(MINT, "1m", b - 12 * H, b))
            st.chart(MINT, "1m", b - 12 * H, b)
            self.assertTrue(st.chart_cached(MINT, "1m", b - 12 * H, b))   # хвилину його ділять усі глядачі
            st.chart(MINT, "1m", b - 12 * H, b)
            self.assertEqual(len(st.paths), 1)
            self.assertEqual(st.chart_cache.get(st._chart_key(MINT, "1m", b - 12 * H, b)), None)   # у файл не йде
            with mock.patch.object(st_client.time, "time", return_value=time.time() + st_client.LIVE_TTL_S + 1):
                self.assertFalse(st.chart_cached(MINT, "1m", b - 12 * H, b))   # за хвилину — знову з джерела
                st.chart(MINT, "1m", b - 12 * H, b)
            self.assertEqual(len(st.paths), 2)

    def test_an_old_cached_copy_of_the_live_chunk_is_not_served(self):
        cache = JsonCache(None)
        st = client(chart_cache=cache)
        now = int(time.time() * 1000)
        cache.put(st._chart_key(MINT, "1m", now - 12 * H, now + H), [{"time": 1, "close": 9}])   # з часів до цього виправлення
        self.assertNotEqual(st.chart(MINT, "1m", now - 12 * H, now + H)[0]["close"], 9)


class TestWalletTradesFreshness(unittest.TestCase):
    def raw(self, typ, minute):
        return {"wallet": "W1", "type": typ, "time": 1_790_000_000_000 + minute * 60_000, "amount": 100,
                "volume": 100.0, "priceUsd": 1.0, "tx": f"{typ}{minute}"}

    def test_fresh_skips_the_cached_copy_and_stores_the_new_one(self):
        st = client(stats_cache=JsonCache(None, ttl_hours=24))
        st.feed = [self.raw("buy", 1)]
        self.assertEqual([t["type"] for t in st.wallet_token_trades("W1", MINT)], ["buy"])
        st.feed.append(self.raw("sell", 30))                         # вийшов після того, як його закешували
        self.assertEqual([t["type"] for t in st.wallet_token_trades("W1", MINT)], ["buy"])   # картка: кеш як був
        self.assertEqual([t["type"] for t in st.wallet_token_trades("W1", MINT, fresh=True)], ["buy", "sell"])
        self.assertEqual([t["type"] for t in st.wallet_token_trades("W1", MINT)], ["buy", "sell"])


class Gate:
    """Кеш, чий запис файлу стоїть, доки тест не відпустить."""

    def __init__(self):
        self.data, self.entered, self.release = {}, threading.Event(), threading.Event()

    def get(self, k):
        return self.data.get(k)

    def put(self, k, v):
        self.data[k] = v

    def put_many(self, items):
        self.data.update(items)

    def flush(self):
        self.entered.set()
        self.release.wait(5)


class TestNoSharedLock(unittest.TestCase):
    """Цикл подій питає chart_cached(): він не має чекати, поки інший потік переписує файл імен чи угод."""

    def check(self, st, gate, work):
        t = threading.Thread(target=work)
        t.start()
        try:
            self.assertTrue(gate.entered.wait(5))
            got = []
            probe = threading.Thread(target=lambda: got.append(st.chart_cached(MINT, "1m", 0, 60_000)))
            probe.start()
            probe.join(2)
            self.assertEqual(got, [False])
        finally:
            gate.release.set()
            t.join(5)

    def test_naming_a_run_does_not_hold_up_the_chart(self):
        gate = Gate()
        st = client(identity_cache=gate, chart_cache=JsonCache(None))
        self.check(st, gate, lambda: st.identities([f"W{i}" for i in range(250)]))
        self.assertEqual(len(gate.data), 250)                        # усі імена записані одним кроком

    def test_flushing_the_caches_does_not_hold_up_the_chart(self):
        gate = Gate()
        gate.data["x"] = 1
        st = client(stats_cache=gate, chart_cache=JsonCache(None))
        self.check(st, gate, st.flush)

    def test_names_reach_the_file_in_one_write(self):
        import os
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "identity.json")
            st = client(identity_cache=JsonCache(path, ttl_hours=720))
            writes, real = [], os.replace

            def counted(src, dst):
                if dst == path:
                    writes.append(dst)
                return real(src, dst)
            with mock.patch("tracced.cache.os.replace", side_effect=counted):
                st.identities([f"W{i}" for i in range(250)])
            self.assertEqual(len(writes), 1)                              # було: файл заново кожні 25 гаманців
            self.assertEqual(len(JsonCache(path, ttl_hours=720).data), 250)   # і переживають перезапуск


if __name__ == "__main__":
    unittest.main()
