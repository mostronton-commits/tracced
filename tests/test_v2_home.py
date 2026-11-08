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
    from tests.test_web import FakeWebST, CYRILLIC, static_js
    from tests.test_early_pipeline import TRADES
except ImportError:                       # discover -s tests without -t: modules without package prefix
    from test_web import FakeWebST, CYRILLIC, static_js
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
            s["design_v2"] = "cookie"                                    # a guest's cookie counts
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
                         'placeholder="Paste a Solana token address"', ">Analyze</button>", "<span>wallets</span>", "<span>tokens</span>",
                         "<span>trades</span>", 'title="Wallets on the record"', 'class="hm-call"', "Someone always<br>buys first.", "Free during beta.", "data-focus-mint",
                         "x.com/intent/follow?screen_name=tracced_xyz", 'data-umami-event="home-follow"', '<footer class="foot">',
                         'href="/static/v2/home.css', "data-type-address", 'src="/static/v2/home.js'):   # owner, 06.11: the field types again; the blocks move
                self.assertIn(part, html, part)
            self.assertIn("data-wallet-signin", html)                                  # a guest sees Connect in the hero's corner
            for gone in ('class="hero-dark"', 'class="steps3"', "Paste address", 'class="top"', "early:theme"):
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
            self.assertIn(TEST_PK[:4] + "…" + TEST_PK[-4:], top)
            self.assertNotIn('class="fp"', top)                                          # owner, 26.10: no wallet pictures
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
            self.assertEqual(row.count('<li'), 6)                                       # five leaders and the sixth blurred
            self.assertEqual(row.count('class="hm-peek"'), 1)
            self.assertNotIn('class="fp"', row)                                         # owner, 26.10: no wallet pictures
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
            rows = self.app["ready"]["lists"]["top-traders"]["rows"]
            self.assertEqual(orbit.count('class="hm-sat'), 5)                          # only the five the page shows anyway
            for r in rows[:5]:
                self.assertIn(str(_fingerprint(r["wallet"], 21)), orbit)
                self.assertNotIn(r["wallet"], orbit)                                  # pictures only, never the address
            for r in rows[5:]:
                self.assertNotIn(str(_fingerprint(r["wallet"], 21)), orbit)            # the closed list's rest stays closed
            self.assertNotIn("first", re.findall(r'class="hm-sat([^"]*)"', orbit)[0])  # no analysis: nobody bought first here

        def test_the_page_moves_only_what_is_seen(self):
            css, js = static_js("v2/home.css"), static_js("v2/home.js")
            self.assertNotIn("hm-drift", css)                            # the stars are one canvas, drawn five times a second
            self.assertNotIn("hm-breathe", css)                          # the dawn and the dot stand still
            self.assertNotIn("hm-peek {", css.replace(".hm-rank li.hm-peek { filter", ""))
            self.assertIn("infinite paused", css)                        # the feed and the orbits wait until they are in view
            self.assertIn("hm-seen", js)
            self.assertNotIn("perspective", css.split(".hm-card.hm-lean")[0])   # a card is no layer of its own until the pointer is on it

        async def test_live_on_tracced_keeps_its_feed(self):
            self.assertNotIn('id="live"', await self.page())                         # no analyses yet: no block
            from unittest import mock
            import tracced.web.app as app_mod
            now = int(time.time() * 1000)
            rows = [{"id": f"J{i}", "mint": f"M{i}" * 22, "symbol": f"SYM{i}", "letter": "S", "image": "", "hue": 10, "running": i == 0, "wallets": 5,
                     "cap": None, "made2x": 0, "saved": 3 if i == 1 else 0, "at": now - i * 60_000, "ago": f"{i} min ago",
                     "fact": {"text": "Staged launch", "sev": "bad", "tip": "one hand"} if i == 2 else {"text": "43% fresh wallets", "sev": "warn", "tip": "43 of 100"} if i == 3 else None}
                    for i in range(11)]
            with mock.patch.object(app_mod, "_live_feed", return_value={"rows": rows, "day": 9}):
                html = await self.page()
            feed = html[html.index('id="lfeed"'):html.index('</article>', html.index('id="lfeed"'))]
            self.assertEqual(feed.count('class="hm-lrow"'), 11)                       # all of them, newest first: they roll
            self.assertLess(feed.index('data-id="J0"'), feed.index('data-id="J1"'))
            self.assertNotIn('id="liveq"', feed)
            self.assertIn("analyzing now", feed)
            self.assertIn("saved 3 wallets", feed)
            self.assertIn("/live.json", html)
            self.assertIn("Live on tracced", html)
            # owner, 08.11: a row opens the token's chart for one's own range (not that analysis), with one fact beside the name
            self.assertIn('<a class="hm-lrow" href="/token?mint=' + "M2" * 22 + '&amp;src=live"', feed)
            self.assertNotIn('href="/job/', feed)
            self.assertIn('<span class="hm-flag bad" title="one hand">Staged launch</span>', feed)
            self.assertIn('<span class="hm-flag warn" title="43 of 100">43% fresh wallets</span>', feed)
            self.assertEqual(feed.count("hm-flag"), 2)                               # no fact, no word

        def test_a_feed_row_says_what_the_result_would_lead_with(self):
            from tracced.web.app import _feed_fact
            s = {"age_lookups_max": 200, "verdict_organised_pct": 90, "feed_fact_min_pct": 30}
            row = lambda i, tags=(), inv=100: {"wallet": f"W{i}", "tag_list": list(tags), "invested_in_range_usd": inv}
            done = lambda n: {"done": n, "total": n}
            self.assertIsNone(_feed_fact({"rows": [row(i) for i in range(30)]}, s))                       # nothing to say
            staged = {"rows": [row(i, ["fresh"]) for i in range(30)], "enrich": done(30)}
            self.assertEqual({k: v for k, v in _feed_fact(staged, s).items() if k != "tip"}, {"text": "Staged launch", "sev": "bad"})
            self.assertIn("30 of the top 30 by PnL", _feed_fact(staged, s)["tip"])
            staged["enrich"]["done"] = 10                                                                  # ages still coming: no verdict yet
            self.assertEqual(_feed_fact(staged, s)["text"], "100% fresh wallets")
            rigged = {"rows": [row(0, ["dev", "fresh"])] + [row(i, ["fresh"]) for i in range(1, 30)], "enrich": done(30)}
            self.assertEqual(_feed_fact(rigged, s)["text"], "Rigged launch")
            self.assertEqual(_feed_fact({"rows": [row(0, ["dev"])] + [row(i) for i in range(1, 30)]}, s)["text"], "Creator bought")
            launch = {"rows": [row(i) for i in range(30)], "launch": {"rev": 2, "pairs": [], "launch": {"wallets": ["W1"]}}, "info": {"supply": 1e9}}
            self.assertEqual(_feed_fact(launch, s)["text"], "Organised launch")
            self.assertEqual(_feed_fact(launch, s)["tip"], "1 wallet in the creator's own launch bundle")
            bundled = {"rows": [row(i, inv=700 if i < 3 else 100) for i in range(30)], "bundle": {f"W{i}": {"funder": "F", "n": 3} for i in range(3)}}
            self.assertEqual(_feed_fact(bundled, s)["text"], "44% bundled buys")                     # 2,100 of 4,800 dollars in the range
            self.assertEqual(_feed_fact(bundled, s)["tip"], "3 wallets that share a funder bought 44% of this range")
            fresh = {"rows": [row(i, ["fresh"] if 50 <= i < 90 else []) for i in range(100)], "enrich": done(100)}
            self.assertEqual(_feed_fact(fresh, s)["text"], "40% fresh wallets")
            self.assertEqual(_feed_fact(fresh, s)["tip"], "40 of the 100 wallets checked were under a day old when they bought")
            usual = {"rows": [row(i, ["fresh"] if 50 <= i < 64 else []) for i in range(100)], "enrich": done(100)}
            self.assertIsNone(_feed_fact(usual, s))                                                     # 14% is usual: the feed stays quiet
            bundled["rows"][0]["invested_in_range_usd"] = bundled["rows"][1]["invested_in_range_usd"] = bundled["rows"][2]["invested_in_range_usd"] = 200
            self.assertIsNone(_feed_fact(bundled, s))                                                   # 600 of 3,300: 18%, under the bar

if __name__ == "__main__":
    unittest.main()
