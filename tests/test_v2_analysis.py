"""Design v2's analysis page (canvas Analysis4, AnalysisMark, AnalysisRun; DESIGN-v2.md phase 3) beside the old one: the
`design=v2` cookie picks templates/v2/token.html and v2/_result.html, no cookie keeps the old token page and result. On a
fake client, no network. Needs aiohttp (present in Docker)."""
import asyncio
import tempfile
import unittest

try:
    from aiohttp.test_utils import AioHTTPTestCase
except ImportError:  # host without aiohttp: page tests are skipped
    AioHTTPTestCase = None

from tracced.early import settings

try:
    from tests.test_web import FakeWebST, CYRILLIC, MINT, static_js
    from tests.test_early_pipeline import TRADES
except ImportError:                       # discover -s tests without -t: modules without package prefix
    from test_web import FakeWebST, CYRILLIC, MINT, static_js
    from test_early_pipeline import TRADES


if AioHTTPTestCase:
    from tracced.web.app import create_app
    try:
        from tests.test_web import TEST_PK, wallet_cookie
    except ImportError:
        from test_web import TEST_PK, wallet_cookie

    RANGE = {"mint": MINT, "from": "2001-09-09T01:46", "to": "2001-09-09T02:06"}

    class TestV2Analysis(AioHTTPTestCase):
        async def get_application(self):
            self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
            self.st = FakeWebST(TRADES)
            s = settings.load()
            s["replay_s"] = 0.6
            s["ranges_per_token"] = 50
            app = create_app(self.st, s, {}, out_dir=self.tmp.name + "/web", store_dir=self.tmp.name + "/cache")
            app["admins"] = {TEST_PK}                                    # no daily cap, as for the owner
            return app

        async def setUpAsync(self):
            await super().setUpAsync()
            self.acct = wallet_cookie(TEST_PK)
            self.client.session.headers["Cookie"] = self.acct

        async def tearDownAsync(self):
            await asyncio.to_thread(self.app["jobs"].q.join)
            await asyncio.to_thread(self.app["jobs"].rq.join)
            await self.client.close()
            self.tmp.cleanup()

        def v2(self):
            return {"Cookie": self.acct + "; design=v2"}

        async def finished_job(self):
            r = await self.client.post("/analyze.json", data=RANGE)
            d = await r.json()
            self.assertEqual(r.status, 200, d)
            await asyncio.to_thread(self.app["jobs"].q.join)
            return d["id"]

        async def test_token_page_v2_has_the_head_the_chart_toolbar_and_the_range_bar(self):
            html = await (await self.client.get(f"/token?mint={MINT}", headers=self.v2())).text()
            self.assertIn('data-design="v2"', html)
            self.assertIn('class="token ana"', html)                     # templates/v2/token.html
            self.assertIn('href="/static/v2/analysis.css', html)
            for part in ('id="ctools"', 'id="ctl"', 'id="ctw"', 'id="ctr"', 'id="cur"',       # the chart's toolbar, USD/SOL on it
                         'id="chart"', 'id="pick"', 'id="getw"', 'id="pickt"', 'id="picknote"',  # the bar on the chart
                         'id="tabs"', 'id="tabsum"', 'id="tabsres"',                         # the tabs and the range at their end
                         'id="run"', 'class="run-skel"', 'id="runsteps"', 'id="result"',      # the run's line and the rows it holds
                         'data-mcap=', 'data-supply=', 'class="tline"'):
                self.assertIn(part, html, part)
            self.assertIn('<button type="button" class="primary" id="getw">Get wallets</button>', html)
            self.assertNotIn('class="tchips"', html)                     # the old chips under the title went into one line
            self.assertIsNone(CYRILLIC.search(html))
            old = await (await self.client.get(f"/token?mint={MINT}")).text()
            self.assertIn('class="card token"', old)                     # without the cookie: the page as it was
            self.assertNotIn('class="token ana"', old)
            self.assertNotIn('id="ctools"', old)
            self.assertIn('class="tchips"', old)
            self.assertNotIn("/static/v2/", old)

        async def test_result_v2_has_the_tally_the_toolbar_the_table_and_the_card(self):
            jid = await self.finished_job()
            page = await (await self.client.get(f"/job/{jid}", headers=self.v2())).text()
            self.assertIn('class="token ana"', page)
            self.assertIn('id="resultroot"', page)
            for part in ('id="tally"', 'class="tbig"', 'id="tprofit"', 'data-act="sold"', 'data-act="holding"', 'data-act="best"', 'id="finds"',
                         'id="msort"', 'Sorted by', 'id="tfind"', 'id="hidebots"', 'id="ftoggle"', 'id="freset"', 'id="fpanel"',
                         'id="colsbtn"', 'id="colpanel"', 'id="askbtn"', 'Ask AI', 'id="xbtn"', 'id="xpanel"',
                         'data-x="csv"', 'data-x="txt"', 'data-x="json"',               # ⋯ holds Export
                         '<th class="wh">Wallet</th>', 'data-fil="real"', 'data-fil="hold"', 'id="shown"', 'id="more100"', 'id="moreall"',
                         'id="drawer"', 'id="dshare"', 'id="dpos"', 'id="dgroups"', 'id="dstar"', 'id="dprof"', 'id="dper"',
                         'id="apanel"', 'id="aform"', 'Reads this analysis only', 'id="savejob"', 'trades up to', 'id="rcfg"', 'id="rowsdata"'):
                self.assertIn(part, page, part)
            self.assertNotIn('data-menu title="Export', page)            # ⋯ opens by result.js, not by the header's menus
            self.assertNotIn('<span aria-hidden="true">→</span>', page)  # no arrows inside buttons
            self.assertNotIn("Wallet 1 of", page)                         # the card has no «Wallet N of M» and no key hints
            self.assertNotIn("<kbd", page.split('id="resultroot"', 1)[1])
            self.assertIsNone(CYRILLIC.search(page))
            old = await (await self.client.get(f"/job/{jid}")).text()
            self.assertIn('class="button holo"', old)                    # the old result is untouched
            self.assertIn('aria-label="Export"', old)
            self.assertNotIn('id="tfind"', old)
            self.assertNotIn('id="colsbtn"', old)
            self.assertNotIn('class="token ana"', old)

        async def test_result_part_alone_follows_the_cookie(self):
            jid = await self.finished_job()
            r = await self.client.get(f"/job/{jid}/view", headers=self.v2())
            frag = await r.text()
            self.assertEqual(r.status, 200)
            self.assertNotIn("<html", frag)                              # a part of the page, not a page
            self.assertIn('id="colsbtn"', frag)                           # templates/v2/_result.html
            self.assertIn('id="facts"', frag)
            self.assertIsNone(CYRILLIC.search(frag))
            old = await (await self.client.get(f"/job/{jid}/view")).text()
            self.assertNotIn('id="colsbtn"', old)
            self.assertIn('id="facts"', old)

        def test_scripts_change_only_under_the_v2_flag(self):
            flag = "document.documentElement.dataset.design === 'v2'"
            for name in ("result.js", "tokenpage.js", "chart.js", "card.js"):
                self.assertIn(flag, static_js(name), name)
            res = static_js("result.js")
            self.assertIn("if (V2) return rowHtmlV2(o, n, i);", res)      # the old rows stay the old rows
            self.assertIn("return function unmount()", res)
            self.assertIn("rheadEl.remove()", res)                       # what v2 moved out of the result goes back with it
            self.assertIn("early:cols", res)                             # Columns kept in this browser
            card = static_js("card.js")
            self.assertIn("if (V2) return fingerprint(w);", card)        # one picture per address, as the server draws it
            chart = static_js("chart.js")
            self.assertIn("V2 && opts.tools", chart)                     # the toolbar above the chart only in v2


if __name__ == "__main__":
    unittest.main()
