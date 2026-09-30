"""Закрита копія сайту (dev): лише гаманці власника; решта — закриті двері, без даних; пошуковикам — noindex."""
import tempfile
import unittest

try:
    from aiohttp.test_utils import AioHTTPTestCase
except ImportError:  # хост без aiohttp: тести сторінок пропускаються
    AioHTTPTestCase = None

from tracced.early import settings

try:
    from tests.test_early_pipeline import TRADES
except ImportError:
    from test_early_pipeline import TRADES

if AioHTTPTestCase:
    try:
        from tests.test_web import FakeWebST, TEST_PK, wallet_cookie
    except ImportError:
        from test_web import FakeWebST, TEST_PK, wallet_cookie
    from tracced.web import accounts as acct_mod
    from tracced.web.app import create_app

    DEV = {"Host": "dev.example"}
    STRANGER = acct_mod.b58encode(b"\x09" * 32)

    class TestPrivateCopy(AioHTTPTestCase):
        async def get_application(self):
            self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
            s = settings.load()
            s["private_hosts"] = ["dev.example"]
            app = create_app(FakeWebST(TRADES), s, {}, out_dir=self.tmp.name + "/web", store_dir=self.tmp.name + "/cache")
            app["admins"] = {TEST_PK}
            return app

        async def tearDownAsync(self):
            await self.client.close()
            self.tmp.cleanup()

        async def test_only_the_owner_gets_in(self):
            for path in ("/", "/docs/api", "/token?mint=" + "M" * 44, "/me"):
                r = await self.client.get(path, headers=DEV)
                html = await r.text()
                self.assertEqual(r.status, 403, path)
                self.assertIn("This copy of tracced is private", html, path)
                self.assertNotIn("Recently analyzed", html, path)
                self.assertEqual(r.headers.get("X-Robots-Tag"), "noindex, nofollow", path)
            r = await self.client.get("/", headers=dict(DEV, Cookie=wallet_cookie(STRANGER)))
            self.assertIn("has no access here", await r.text())                     # another wallet: still closed
            for path in ("/job/x.state.json", "/me/wallets.csv", "/api/v1/check?mint=" + "M" * 44):
                r = await self.client.get(path, headers=DEV)
                self.assertEqual((r.status, (await r.json())["error"]), (403, "This copy of tracced is private."), path)
            r = await self.client.get("/", headers=dict(DEV, Cookie=wallet_cookie(TEST_PK)))
            self.assertEqual(r.status, 200)                                           # the owner's wallet
            self.assertEqual(r.headers.get("X-Robots-Tag"), "noindex, nofollow")

        async def test_what_sign_in_needs_stays_open(self):
            self.assertEqual((await self.client.get("/health", headers=DEV)).status, 200)
            self.assertEqual((await self.client.get("/static/style.css", headers=DEV)).status, 200)
            r = await self.client.post("/auth/nonce", headers=dict(DEV, Origin="http://dev.example"))
            self.assertNotEqual(r.status, 403)
            self.assertEqual(await (await self.client.get("/robots.txt", headers=DEV)).text(), "User-agent: *\nDisallow: /\n")

        async def test_the_public_site_is_untouched(self):
            r = await self.client.get("/")
            self.assertEqual(r.status, 200)
            self.assertIsNone(r.headers.get("X-Robots-Tag"))
            self.assertIn("Disallow: /admin", await (await self.client.get("/robots.txt")).text())


if __name__ == "__main__":
    unittest.main()
