"""Design v2 (26.10) for the small pages: Docs, Contact, the 401 card and the connect sheet, the missing page and the
closed copy. With the `design=v2` cookie each renders its canvas board; without it the old markup stays as it was."""
import asyncio
import os
import re
import tempfile
import unittest

try:
    from aiohttp.test_utils import AioHTTPTestCase
except ImportError:  # host without aiohttp: page tests are skipped
    AioHTTPTestCase = None

from tracced.early import settings

try:
    from tests.test_early_pipeline import TRADES
except ImportError:
    from test_early_pipeline import TRADES

CYRILLIC = re.compile("[Ѐ-ӿ]")
DUMP = os.environ.get("V2_DUMP")          # a folder: the rendered pages land there to be looked at in a browser


def dump(name, html):
    if DUMP:
        with open(os.path.join(DUMP, name), "w", encoding="utf-8") as f:
            f.write(html)


if AioHTTPTestCase:
    try:
        from tests.test_web import FakeWebST, TEST_PK, wallet_cookie
    except ImportError:
        from test_web import FakeWebST, TEST_PK, wallet_cookie
    from tracced.web import accounts as acct_mod
    from tracced.web.app import create_app

    V2 = {"Cookie": wallet_cookie(TEST_PK) + "; design=v2"}
    GUEST_V2 = {"Cookie": "design=v2"}
    OLD = {"Cookie": wallet_cookie(TEST_PK)}

    class TestV2Pages(AioHTTPTestCase):
        async def get_application(self):
            self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
            s = settings.load()
            s["replay_s"] = 0.6
            s["ranges_per_token"] = 50
            app = create_app(FakeWebST(TRADES), s, {}, out_dir=self.tmp.name + "/web", store_dir=self.tmp.name + "/cache")
            app["admins"] = {TEST_PK}
            return app

        async def tearDownAsync(self):
            await asyncio.to_thread(self.app["jobs"].q.join)
            await asyncio.to_thread(self.app["jobs"].rq.join)
            await self.client.close()
            self.tmp.cleanup()

        async def page(self, path, headers, status=200, name=None):
            r = await self.client.get(path, headers=headers)
            html = await r.text()
            self.assertEqual(r.status, status, path)
            if name:
                dump(name, html)
            return html

        async def test_docs_in_v2(self):
            html = await self.page("/docs", V2, name="docs.html")
            self.assertIn('data-design="v2"', html)
            for part in ('class="docs-nav"', 'class="dn-h">Documentation', 'class="docs-crumb">Docs', 'class="docs-body p-index"',
                         'class="docs-toc"', 'id="dtoc"', 'class="pg next" href="/docs/compare"', '<svg class="dic"',
                         'class="on" aria-current="page"'):
                self.assertIn(part, html)
            self.assertNotIn("🧭", html[:html.index('class="docs-main"')])          # the menu wears our marks, not emoji
            self.assertNotIn('class="docs-body card', html)                        # no card around the text
            self.assertIsNone(CYRILLIC.search(html))
            html = await self.page("/docs/updates", V2, name="docs-updates.html")
            for part in ('class="docs-body p-updates"', 'class="ulog"', 'class="pg prev" href="/docs/roadmap"', "Previous",
                         'class="pg next" href="/docs/project"'):
                self.assertIn(part, html)
            html = await self.page("/docs/how-it-works", V2, name="docs-hiw.html")
            self.assertIn('href="/docs/how-it-works" class="on"', html)
            old = await self.page("/docs", OLD)                                    # the old look is untouched
            self.assertIn('<i aria-hidden="true">🧭</i>', old)
            self.assertIn('class="docs-body card p-index"', old)
            self.assertNotIn("docs-toc", old)
            self.assertNotIn('data-design="v2"', old)
            self.assertEqual((await self.client.get("/docs/no-such", headers=V2)).status, 404)

        async def test_contact_in_v2(self):
            html = await self.page("/feedback", GUEST_V2, name="feedback.html")
            for part in ('class="pcard fbc"', 'id="fbform"', 'name="text"', 'rows="7"', 'name="contact"', 'name="website" class="fbhp"',
                         'name="t" value="', 'type="submit" class="pk mint">Send', 'id="fbstat"', 'class="fbdone" hidden'):
                self.assertIn(part, html)
            for k in ("bug", "idea", "question", "other"):
                self.assertIn(f'value="{k}"', html)
            self.assertIn('value="idea" checked', html)
            self.assertNotIn("More analyses", html)                                # only when the limit window sent the person
            self.assertIsNone(CYRILLIC.search(html))
            html = await self.page("/feedback?kind=limits", GUEST_V2)
            self.assertIn('value="limits" checked', html)
            self.assertIn("More analyses", html)
            self.assertIn("how many analyses a day would you need", html)
            old = await self.page("/feedback", {"Cookie": ""})
            self.assertIn('class="card narrow fb"', old)
            self.assertNotIn("pcard", old)

        async def test_missing_page_and_other_errors_in_v2(self):
            r = await self.client.get("/nope-404", headers=GUEST_V2)
            html = await r.text()
            dump("missing.html", html)
            self.assertEqual(r.status, 404)
            for part in ('class="pcard pc-404"', 'class="rugline"', 'class="pc-code">404', "<h1>Page not found</h1>",
                         'class="pk ink" href="/">Back to tracced'):
                self.assertIn(part, html)
            for gone in ("Wick", 'class="wick"', "got rugged"):                    # the eyed candle was rejected
                self.assertNotIn(gone, html)
            self.assertIsNone(CYRILLIC.search(html))
            html = await self.page("/docs/no-such", GUEST_V2, status=404)
            self.assertIn("Page not found", html)
            r = await self.client.get("/token?mint=not-a-token", headers=GUEST_V2)  # another error keeps its reason
            html = await r.text()
            dump("error.html", html)
            self.assertEqual(r.status, 400)
            for part in ('class="pcard pc-err"', "That didn't work", "look like a Solana token address", 'href="/feedback?kind=bug">Report this'):
                self.assertIn(part, html)
            self.assertNotIn("rugline", html)
            old = await (await self.client.get("/nope-404", headers={"Cookie": ""})).text()
            self.assertIn("This page got rugged.", old)
            self.assertNotIn("pcard", old)

        async def test_connect_card_and_sheet_in_v2(self):
            r = await self.client.post("/analyze", allow_redirects=False, headers=GUEST_V2, data={
                "mint": "B" * 40, "from": "2001-09-09T01:46", "to": "2001-09-09T02:06"})
            html = await r.text()
            dump("connect.html", html)
            self.assertEqual(r.status, 401)
            for part in ('class="pcard cc"', "Connect a wallet to run this analysis", "A signature only: no transaction, no fees.",
                         'class="pk mint" data-wallet-signin data-wallet-note=', '<form id="again" method="post" action="/analyze" data-wallet-after hidden>',
                         'name="from" value="2001-09-09T01:46"', 'class="pk quiet" href="/token?mint=' + "B" * 40, "Back to the chart"):
                self.assertIn(part, html)
            for part in ('id="wsheet"', 'id="wtitle">Connect a wallet', 'data-wallet-close', 'id="wnote"', 'id="wlist"', 'id="wstate"', 'class="wsafe"'):
                self.assertIn(part, html)                                          # the sheet the key opens
            self.assertNotIn("Beta, free for now", html)                           # owner, 26.10: gone from the sheet
            self.assertNotIn("→", html[html.index('<main'):html.index('</main>')])  # no arrows in the keys or links
            self.assertIsNone(CYRILLIC.search(html))
            for f in ("phantom.svg", "backpack.svg", "solflare.png"):              # the wallet apps' own logos
                self.assertEqual((await self.client.get("/static/v2/wallets/" + f)).status, 200, f)
            js = await (await self.client.get("/static/wallet.js")).text()
            self.assertIn("dataset.design === 'v2'", js)
            self.assertIn("/static/v2/wallets/", js)
            for word in ("'Detected'", "'Install'", "'Open in the app'"):
                self.assertIn(word, js)
            old = await (await self.client.post("/analyze", allow_redirects=False, headers={"Cookie": ""}, data={
                "mint": "B" * 40, "from": "2001-09-09T01:46", "to": "2001-09-09T02:06"})).text()
            self.assertIn("<b>Beta, free for now.</b>", old)                       # the old card and sheet as they were
            self.assertIn('class="card narrow"', old)

    class TestV2Private(AioHTTPTestCase):
        """The closed copy reads like a missing page in v2, and its owner still has the way in."""
        DEV = {"Host": "dev.example"}
        STRANGER = acct_mod.b58encode(b"\x09" * 32)

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

        async def test_private_page_reads_like_a_missing_one_and_keeps_sign_in(self):
            for path in ("/", "/docs", "/me"):
                r = await self.client.get(path, headers=dict(self.DEV, Cookie="design=v2"))
                html = await r.text()
                self.assertEqual(r.status, 403, path)
                self.assertEqual(r.headers.get("X-Robots-Tag"), "noindex, nofollow", path)
                for part in ("<h1>Page not found</h1>", 'class="rugline"', 'href="https://tracced.xyz">Back to tracced'):
                    self.assertIn(part, html, path)
                self.assertNotIn("This copy of tracced is private", html, path)
                self.assertIn('class="acct-in" data-wallet-signin', html, path)   # the owner signs in from here: Connect…
                self.assertIn('id="wsheet"', html, path)                            # …opens the sheet on this page
                self.assertIn("/static/wallet.js", html, path)
                self.assertIsNone(CYRILLIC.search(html), path)
            dump("private.html", html)
            r = await self.client.get("/", headers=dict(self.DEV, Cookie=wallet_cookie(self.STRANGER) + "; design=v2"))
            html = await r.text()
            dump("private-signed.html", html)
            self.assertEqual(r.status, 403)
            self.assertIn("Page not found", html)
            self.assertIn("data-wallet-signout", html)                              # another wallet signs out from its menu
            r = await self.client.get("/docs", headers=dict(self.DEV, Cookie=wallet_cookie(TEST_PK) + "; design=v2"))
            self.assertEqual(r.status, 200)                                         # the owner's wallet is in
            self.assertIn('class="docs-nav"', await r.text())
            old = await (await self.client.get("/", headers=self.DEV)).text()
            self.assertIn("This copy of tracced is private", old)                   # the old look as it was
            self.assertIn('class="primary" data-wallet-signin', old)


if __name__ == "__main__":
    unittest.main()
