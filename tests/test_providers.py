"""Що ми дістаємо з чужих відповідей: творець токена, момент переїзду з лаунчпада, оплати DexScreener."""
import http.client
import json
import unittest
import urllib.error
from unittest import mock

from tracced.providers import dexscreener, solana_tracker
from tracced.providers.solana_tracker import SolanaTracker, _launch_pool, _migration

BORN = 1789500020749


def pool(market, created, curve=None):
    p = {"market": market, "createdAt": created, "deployer": market + "-deployer"}
    if curve is not None:
        p["curve"] = "Curve111"
        p["curvePercentage"] = curve
    return p


class TestMigration(unittest.TestCase):
    """Пулів у токена буває шість, і перший у відповіді — не той, з якого все почалось."""

    def test_first_pool_after_the_curve_is_the_migration(self):
        pools = [pool("raydium-clmm", BORN + 11_428_000),        # так відповідь і приходить: не за часом
                 pool("meteora-dlmm", BORN + 680_000),
                 pool("meteora-dlmm", BORN + 348_545),
                 pool("pumpfun", BORN, curve=100)]
        m = _migration(pools)
        self.assertEqual(m["ms"], BORN + 348_545)
        self.assertEqual((m["from"], m["market"]), ("pumpfun", "meteora-dlmm"))

    def test_an_unfinished_curve_never_migrated(self):
        self.assertIsNone(_migration([pool("pumpfun", BORN, curve=64)]))

    def test_a_token_launched_straight_on_a_dex_has_no_migration(self):
        self.assertIsNone(_migration([pool("raydium-clmm", BORN), pool("meteora-dlmm", BORN + 5000)]))

    def test_the_launch_pool_is_the_one_with_the_curve(self):
        pools = [pool("raydium-clmm", BORN - 999), pool("pumpfun", BORN, curve=100)]
        self.assertEqual(_launch_pool(pools)["market"], "pumpfun")   # не найстаріший, а саме з кривою


class TestDexscreenerOrders(unittest.TestCase):
    """Чужий сервіс: мовчить або відповідає сміттям — графік просто лишається без цих міток."""

    def fake(self, payload):
        import io
        import json as js

        class R(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return lambda req, timeout=0: R(js.dumps(payload).encode())

    def test_approved_orders_come_back_sorted(self):
        import urllib.request
        real = urllib.request.urlopen
        urllib.request.urlopen = self.fake({"orders": [
            {"type": "tokenProfile", "status": "approved", "paymentTimestamp": 1789500329864},
            {"type": "tokenAd", "status": "processing", "paymentTimestamp": 1789500000000},
            {"type": "tokenProfile", "status": "approved", "paymentTimestamp": 1789500257012}]})
        try:
            got = dexscreener.orders("M" * 40)
        finally:
            urllib.request.urlopen = real
        self.assertEqual([x["ms"] for x in got], [1789500257012, 1789500329864])   # неоплачене не рахуємо
        self.assertEqual(got[0]["kind"], "profile")

    def test_a_dead_service_is_an_empty_list_not_an_error(self):
        import urllib.request
        real = urllib.request.urlopen

        def boom(req, timeout=0):
            raise OSError("down")
        urllib.request.urlopen = boom
        try:
            self.assertEqual(dexscreener.orders("M" * 40), [])
        finally:
            urllib.request.urlopen = real

    def test_a_failure_is_remembered_for_ten_minutes(self):
        """Лежачий сервіс не питаємо на кожен перегляд: кожен запит тримав спільний потік сторінок до тайм-ауту."""
        import time
        import urllib.request

        class Cache(dict):
            def put(self, k, v): self[k] = v
        calls, real = [], urllib.request.urlopen

        def boom(req, timeout=0):
            calls.append(timeout)
            raise TimeoutError("slow")
        urllib.request.urlopen = boom
        cache = Cache()
        try:
            self.assertEqual(dexscreener.orders("M" * 40, cache), [])
            self.assertEqual(dexscreener.orders("M" * 40, cache), [])
            self.assertEqual(calls, [3])                              # другий раз без запиту; тайм-аут 3 с
            cache["M" * 40]["failed"] = time.time() - 11 * 60           # минуло десять хвилин — питаємо знову
            urllib.request.urlopen = self.fake({"orders": [{"type": "tokenAd", "paymentTimestamp": 5}]})
            self.assertEqual(dexscreener.orders("M" * 40, cache), [{"ms": 5, "kind": "ad"}])
            self.assertEqual(cache["M" * 40], [{"ms": 5, "kind": "ad"}])   # вдала відповідь перезаписала збій
        finally:
            urllib.request.urlopen = real


class TestSolanaTrackerRetries(unittest.TestCase):
    """Збій посеред тіла відповіді (тайм-аут читання, обрив, битий JSON) — такий самий повтор, як збій з'єднання."""

    def run_get(self, answers, retries=3):
        calls, slept = [], []

        def fake(url, headers):
            calls.append(url)
            a = answers.pop(0)
            if isinstance(a, BaseException):
                raise a
            return a
        st = SolanaTracker("k", pause=0, retries=retries)
        with mock.patch.object(solana_tracker, "http_get_json", side_effect=fake), \
                mock.patch.object(solana_tracker.time, "sleep", side_effect=slept.append):
            try:
                return st._get("/x"), calls, slept
            except Exception as e:  # noqa: BLE001
                return e, calls, slept

    def test_errors_after_the_headers_are_retried(self):
        for err in (TimeoutError("read timed out"), ConnectionResetError(104, "reset"),
                    http.client.RemoteDisconnected("closed"), http.client.IncompleteRead(b"{"),
                    json.JSONDecodeError("bad", "<html>", 0)):
            with self.subTest(err=type(err).__name__):
                got, calls, slept = self.run_get([err, {"ok": 1}])
                self.assertEqual(got, {"ok": 1})
                self.assertEqual((len(calls), slept), (2, [1.0]))

    def test_the_last_error_comes_out_after_every_attempt(self):
        got, calls, _ = self.run_get([TimeoutError("a"), ValueError("b"), ConnectionResetError("c")])
        self.assertIsInstance(got, ConnectionResetError)
        self.assertEqual(len(calls), 3)

    def test_a_client_error_is_not_retried(self):
        err = urllib.error.HTTPError("u", 400, "bad", {}, None)
        got, calls, _ = self.run_get([err, {"ok": 1}])
        self.assertIs(got, err)
        self.assertEqual(len(calls), 1)


class TestTokenInfoText(unittest.TestCase):
    def test_symbol_and_name_are_short_plain_text(self):
        """Символ і назву пише творець токена, а вони йдуть у сторінки: обрізаємо ще до шаблонів."""
        st = SolanaTracker("k", pause=0)
        st._get = lambda path: {"token": {"symbol": "<img src=x onerror=alert(1)>" * 3, "name": "N" * 500}, "pools": []}
        info = st.token_info("M" * 40)
        self.assertEqual((len(info["symbol"]), len(info["name"])), (24, 64))
        st._get = lambda path: {"token": {"symbol": 420, "name": None}, "pools": []}
        info = st.token_info("M" * 40)
        self.assertEqual((info["symbol"], info["name"]), ("420", None))


if __name__ == "__main__":
    unittest.main()
