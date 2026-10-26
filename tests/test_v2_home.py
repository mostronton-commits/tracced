"""Design v2's home page (canvas Home6, DESIGN-v2.md phase 2) beside the old one: the `design=v2` cookie picks it, no
cookie keeps the old home. On a fake client, no network. Needs aiohttp (present in Docker)."""
import asyncio
import re
import tempfile
import time
import unittest

try:
    from aiohttp.test_utils import AioHTTPTestCase
except ImportError:  # host without aiohttp: page tests are skipped
    AioHTTPTestCase = None

from tracced.early import settings

try:
    from tests.test_web import FakeWebST, CYRILLIC
    from tests.test_early_pipeline import TRADES
except ImportError:                       # discover -s tests without -t: modules without package prefix
    from test_web import FakeWebST, CYRILLIC
    from test_early_pipeline import TRADES


def fresh_row(i, cap, peak, age_h=3.0, image=""):
    return {"mint": chr(ord("A") + i) * 44, "symbol": f"TK{i}", "name": f"Token {i}", "cap": cap, "liq": 1e5, "vol": 1e6,
            "created_ms": 0, "image": image, "peak": peak, "age_h": age_h, "drop": round((1 - cap / peak) * 100)}


def ready_list(n=10, example=True):
    rows = [{"wallet": f"{chr(ord('a') + i)}" * 43 + "W", "name": None if i % 2 == 0 else f"Trader{i}", "x": None if i % 3 else f"tr{i}",
             "avatar": None, "pnl": 1e6 / (i + 1), "roi": 0.5, "win_rate": 40.0 + i, "tokens": 20 + i} for i in range(n)]
    lst = {"title": "Top traders · September", "rule": "September's most profitable traders.", "kind": "top", "slug": "top-traders",
           "rows": rows, "summary": {"n": n, "pnl": sum(r["pnl"] for r in rows), "best": rows[0]["pnl"]}, "label": "September",
           "next_label": "Nov 1", "month": "2026-09"}
    if example:
        lst["example"] = {"msgs": [
            {"t": 1788646452000, "html": "🟡 <a><b>$USEFUL</b></a> 🆕 · MC $648.5K · <a>tx</a>\n\n<code>GWTP</code>\n\n<a>6HJetM…USX2</a> · <b>$4K</b>"},
            {"t": 1788970609000, "html": "🟡 <a><b>$USEFUL</b></a> · sold 74% (+8%) · MC $6.6M · <a>tx</a>\n\n<a>6HJetM…USX2</a> · <b>$3.3K</b>"}]}
    return lst


if AioHTTPTestCase:
    from tracced.web.app import create_app, _fingerprint
    try:
        from tests.test_web import TEST_PK, wallet_cookie
    except ImportError:
        from test_web import TEST_PK, wallet_cookie

    V2 = {"Cookie": "design=v2"}                         # a guest who switched to the new look

    class TestV2Home(AioHTTPTestCase):
        async def get_application(self):
            self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
            self.st = FakeWebST(TRADES)
            s = settings.load()
            app = create_app(self.st, s, {}, out_dir=self.tmp.name + "/web", store_dir=self.tmp.name + "/cache")
            app["admins"] = {TEST_PK}
            return app

        async def tearDownAsync(self):
            await asyncio.to_thread(self.app["jobs"].q.join)
            await asyncio.to_thread(self.app["jobs"].rq.join)
            await self.client.close()
            self.tmp.cleanup()

        async def page(self, headers=V2):
            r = await self.client.get("/", headers=headers)
            self.assertEqual(r.status, 200)
            return await r.text()

        def fresh(self, rows):
            self.app["s"]["fresh_on"] = True
            self.app["fresh"].update(rows=rows, at=int(time.time() * 1000), ok_at=int(time.time() * 1000), live=False)

        async def test_the_cookie_picks_the_new_home_and_without_it_the_old_one_stays(self):
            html = await self.page()
            self.assertIn('data-design="v2"', html)
            for part in ('class="hm-sky"', 'class="hm-world"', "Every wallet<br>on the record.", 'class="hm-ask"', 'action="/token"',
                         'placeholder="Paste a Solana token address"', ">Analyze</button>", "wallets on the record", "tokens analyzed",
                         "trades processed", 'class="hm-call"', "Someone always<br>buys first.", "Free during beta.", "data-focus-mint",
                         "x.com/intent/follow?screen_name=tracced_xyz", 'data-umami-event="home-follow"', '<footer class="foot">',
                         'href="/static/v2/home.css'):
                self.assertIn(part, html, part)
            self.assertIn("data-wallet-signin", html)                                  # a guest sees Connect in the hero's corner
            for gone in ('class="hero-dark"', 'class="steps3"', "Paste address", 'class="top"', "data-type-address", "early:theme"):
                self.assertNotIn(gone, html, gone)
            self.assertIsNone(CYRILLIC.search(html))
            old = await self.page(headers={"Cookie": ""})
            for part in ('class="hero-dark"', '<h1 class="brandline">tracced</h1>', "Paste address", "Get wallets", 'href="/static/style.css'):
                self.assertIn(part, old, part)
            for v2 in ("hm-sky", "hm-call", "/static/v2/", 'data-design="v2"'):
                self.assertNotIn(v2, old, v2)

        async def test_signed_in_the_hero_corner_carries_the_wallet_pill(self):
            html = await self.page(headers={"Cookie": wallet_cookie(TEST_PK) + "; design=v2"})
            top = html[html.index('<header class="hm-top">'):html.index('<section class="hm-hero">')]
            self.assertIn(str(_fingerprint(TEST_PK)), top)
            self.assertIn("Sign out", top)
            self.assertNotIn("data-wallet-signin", top)

        async def test_fresh_pumps_are_a_market_map_of_six_with_the_rest_in_a_menu(self):
            self.assertNotIn('id="fresh"', await self.page())                         # nothing fetched yet: no block at all
            caps = [5e6, 4e6, 3e6, 2e6, 1.5e6, 1.2e6, 1.1e6, 1e6]
            peaks = [5e6, 4.5e6, 4e6, 3.5e6, 2.5e6, 4e6, 1.2e6, 1.1e6]               # ratios 1, .89, .75, .57, .6, .3 …
            rows = [fresh_row(i, c, p) for i, (c, p) in enumerate(zip(caps, peaks))]
            self.fresh(list(reversed(rows)))                                           # the map sorts by cap itself
            html = await self.page()
            m = html[html.index('id="hmmap"'):html.index('class="hm-legend"')]
            tiles = re.findall(r'class="hm-tile (t\d)" data-cap="([\d.e+]+)"', m)
            self.assertEqual([t for t, _ in tiles], ["t1", "t2", "t3", "t4", "t4", "t5"])   # tint by how close it is to its peak
            self.assertEqual([float(c) for _, c in tiles], caps[:6])                       # biggest first, six at most
            self.assertIn('href="/token?mint=' + "A" * 44 + '&amp;src=fresh" rel="nofollow"', m)
            self.assertIn(">at peak<", m)
            self.assertIn("−11% from peak", m)                                            # a real minus
            self.assertIn("+2 more", html)                                                 # desktop: six drawn, two in the menu
            self.assertIn("+4 more", html)                                                 # phone: four drawn
            menu = html[html.index('class="menu-panel r"', html.index("hm-more")):]
            self.assertIn('href="/token?mint=' + "H" * 44 + '&amp;src=fresh"', menu)
            self.assertIn("Size is market cap", html)
            self.assertIn("Launched in the last 24 h", html)
            self.assertIsNone(CYRILLIC.search(html))

        async def test_a_quiet_day_says_so_and_a_stale_list_shows_nothing(self):
            self.fresh([])
            html = await self.page()
            self.assertIn('id="fresh"', html)
            self.assertIn("Quiet: no new pumps in 24 h", html)
            self.app["fresh"].update(ok_at=int(time.time() * 1000) - 10 * 3_600_000)      # hours old: not a fact any more
            self.assertNotIn('id="fresh"', await self.page())

        async def test_top_ten_and_its_alerts_from_the_real_list(self):
            self.assertNotIn('id="ready"', await self.page())                         # no list yet: no row
            self.app["ready"]["lists"]["top-traders"] = ready_list()
            html = await self.page()
            row = html[html.index('id="ready"'):html.index('class="hm-call"')]
            self.assertIn("September's top 10 traders", row)
            self.assertIn("next list Nov 1", row)
            self.assertIn("Real traders only", row)
            self.assertIn("total profit", row)
            lst = self.app["ready"]["lists"]["top-traders"]
            for r in lst["rows"][:6]:                                                  # five leaders and the sixth blurred
                self.assertIn(str(_fingerprint(r["wallet"], 22)), row)
            self.assertEqual(row.count('class="hm-peek"'), 1)
            self.assertNotIn(str(_fingerprint(lst["rows"][6]["wallet"], 22)), row)
            self.assertIn('href="/lists/top-traders" data-need-wallet', row)
            self.assertIn("Connect a wallet to see all ten.", row)
            self.assertIn("Turn on alerts", row)
            self.assertEqual(len(re.findall(r'class="hm-toast (?:front|back)"', row)), 2)
            self.assertLess(row.index("Sep 5"), row.index("Sep 9"))                    # the older behind, the newest in front
            self.assertIn('<span class="hm-new">NEW</span>', row)
            self.assertIn('<i class="hm-sd y"></i>', row)
            for emoji in ("🟡", "🆕", "<a>tx</a>", "GWTP"):                               # the first line only, no emoji
                self.assertNotIn(emoji, row)
            signed = await self.page(headers={"Cookie": wallet_cookie(TEST_PK) + "; design=v2"})
            self.assertNotIn("Connect a wallet to see all", signed)
            lst.pop("example")
            quiet = await self.page()
            self.assertIn('class="hm-stage hm-stage-q"', quiet)                       # no alert to show: the bell
            self.assertNotIn('class="hm-toasts', quiet)

        async def test_the_orbits_carry_real_wallets(self):
            html = await self.page()
            self.assertNotIn('class="hm-sat', html)                                    # no analysis and no list: empty rings
            self.app["ready"]["lists"]["top-traders"] = ready_list(example=False)
            html = await self.page()
            orbit = html[html.index('class="hm-orbits"'):html.index('class="hm-call-in"')]
            self.assertEqual(orbit.count('class="hm-sat'), 10)
            for r in self.app["ready"]["lists"]["top-traders"]["rows"]:
                self.assertIn(str(_fingerprint(r["wallet"], 21)), orbit)
                self.assertNotIn(r["wallet"], orbit)                                  # pictures only, never the address
            self.assertNotIn("first", re.findall(r'class="hm-sat([^"]*)"', orbit)[0])  # no analysis: nobody bought first here

        async def test_live_on_tracced_keeps_its_feed(self):
            self.assertNotIn('id="live"', await self.page())                         # no analyses yet: no block
            from unittest import mock
            import tracced.web.app as app_mod
            now = int(time.time() * 1000)
            rows = [{"id": f"J{i}", "symbol": f"SYM{i}", "letter": "S", "image": "", "hue": 10, "running": i == 0, "wallets": 5,
                     "cap": None, "made2x": 0, "saved": 3 if i == 1 else 0, "at": now - i * 60_000, "ago": f"{i} min ago"} for i in range(11)]
            with mock.patch.object(app_mod, "_live_feed", return_value={"rows": rows, "day": 9}):
                html = await self.page()
            feed = html[html.index('id="lfeed"'):html.index('</article>', html.index('id="lfeed"'))]
            shown, queued = feed.split('<template id="liveq">')
            self.assertEqual(shown.count('class="hm-lrow"'), 7)                       # seven on screen, the three newest queued
            self.assertEqual(queued.count('class="hm-lrow"'), 3)
            self.assertIn('data-id="J3"', feed)
            self.assertNotIn('data-id="J0"', shown)
            self.assertIn('data-id="J0"', queued)
            self.assertIn("analyzing now", queued)
            self.assertIn("saved 3 wallets", feed)
            self.assertIn("/live.json", html)
            self.assertIn("Live on tracced", html)

if __name__ == "__main__":
    unittest.main()
