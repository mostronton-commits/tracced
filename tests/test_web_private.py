"""Закрита копія сайту (dev): лише гаманці власника; решта — закриті двері, без даних; пошуковикам — noindex."""
import os
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

        async def test_the_copy_is_closed_under_any_name_and_health_says_only_ok(self):
            os.environ["SITE_URL"] = "https://dev.example"                              # the copy's own address is private
            try:
                r = await self.client.get("/")                                            # reached under another name (127.0.0.1)
                self.assertEqual(r.status, 403)
                self.assertIn("This copy of tracced is private", await r.text())
                d = await (await self.client.get("/health")).json()
                self.assertIn("running", d)                                               # the deploy script asks from inside
            finally:
                os.environ.pop("SITE_URL", None)

        async def test_health_outside_says_only_ok(self):
            from unittest import mock
            with mock.patch("aiohttp.web_request.BaseRequest.remote", new_callable=mock.PropertyMock, return_value="203.0.113.9"):
                d = await (await self.client.get("/health", headers=DEV)).json()
                pub = await (await self.client.get("/health")).json()                   # the public site too (review 01.10)
            self.assertEqual((d, pub), ({"ok": True}, {"ok": True}))

        async def test_a_trailing_dot_is_the_same_private_name(self):
            self.assertEqual((await self.client.get("/", headers={"Host": "dev.example."})).status, 403)
            self.assertEqual((await self.client.get("/", headers={"Host": "dev.example.:443"})).status, 403)

        async def test_the_draft_shows_the_alerts_as_a_preview(self):
            # owner, 04.10: «why are there no alerts?» The draft runs no bot (Telegram gives a bot's updates to one listener
            # only), so there the bells and the list switch save and the card says that nothing is sent
            self.app["accounts"].add_wallets(TEST_PK, [{"wallet": STRANGER}])
            me = dict(DEV, Cookie=wallet_cookie(TEST_PK))
            r = await self.client.get("/me", headers=me)
            html = await r.text()
            self.assertEqual(r.status, 200)
            for bit in ('id="tgbar"', "Preview on the draft", 'id="lalert"', "data-bell", "const PREVIEW = true"):
                self.assertIn(bit, html)
            self.assertNotIn('id="tgconnect"', html)                                        # nothing to connect: no bot here
            r = await self.client.post("/me/wallets/alert", json={"wallet": STRANGER, "on": True}, headers=dict(me, Origin="http://dev.example"))
            self.assertEqual((r.status, (await r.json())["on"]), (200, True))               # the bell saves
            pub = await (await self.client.get("/me", headers={"Cookie": wallet_cookie(TEST_PK)})).text()
            self.assertNotIn('id="tgbar"', pub)                                              # the public site without a bot: no card

        async def test_the_public_site_is_untouched(self):
            r = await self.client.get("/")
            self.assertEqual(r.status, 200)
            self.assertIsNone(r.headers.get("X-Robots-Tag"))
            self.assertIn("Disallow: /admin", await (await self.client.get("/robots.txt")).text())


if __name__ == "__main__":
    unittest.main()
