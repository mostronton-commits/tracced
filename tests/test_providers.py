"""Що ми дістаємо з чужих відповідей: творець токена, момент переїзду з лаунчпада, оплати DexScreener."""
import unittest

from tracced.providers import dexscreener
from tracced.providers.solana_tracker import _launch_pool, _migration

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


if __name__ == "__main__":
    unittest.main()
