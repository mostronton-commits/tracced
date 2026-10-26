"""Design v2 of a ready list (/lists/<slug>) and of the watchlist (/me), canvas «Lists» and «Me» (26.10): with the cookie
design=v2 both pages come from templates/v2 with the canvas's parts and every control of the old page; without it, the
old markup, unchanged. No network."""
import asyncio
import re
import tempfile
import time
import unittest
from pathlib import Path

try:
    from aiohttp.test_utils import AioHTTPTestCase
except ImportError:  # a host without aiohttp: the page tests are skipped
    AioHTTPTestCase = None

from tracced.early import settings

CSS = Path(__file__).resolve().parent.parent / "tracced" / "web" / "static" / "v2" / "lists.css"


class TestV2ListsSheet(unittest.TestCase):
    """lists.css is loaded on every v2 page: each rule stays inside the two pages, and colours come from the tokens."""

    def test_every_rule_is_scoped_to_the_two_pages(self):
        css = re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.S)
        selectors, buf, depth = [], "", 0
        for ch in css:
            if ch == "{":
                head = buf.strip()
                if not head.startswith("@"):
                    selectors.append(head)
                buf, depth = "", depth + 1
            elif ch == "}":
                buf, depth = "", depth - 1
            elif ch == ";":
                buf = ""
            else:
                buf += ch
        self.assertGreater(len(selectors), 50)
        for sel in selectors:
            for part in sel.split(","):
                self.assertRegex(part, r"\.v2lists\b|\.v2me\b", f"unscoped selector: {part.strip()}")

    def test_no_new_colours(self):
        css = re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.S)
        self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b", css))
        self.assertIsNone(re.search(r"rgba?\(", css))
        self.assertNotIn("transition: all", css)


if AioHTTPTestCase:
    try:
        from tests.test_web import TEST_PK, wallet_cookie, CYRILLIC
        from tests.test_ready import ReadyST, SLUG, addr
        from tests.test_early_pipeline import TRADES
    except ImportError:
        from test_web import TEST_PK, wallet_cookie, CYRILLIC
        from test_ready import ReadyST, SLUG, addr
        from test_early_pipeline import TRADES
    from tracced.web import accounts as acct_mod
    from tracced.web.app import create_app, _ready_refresh

    V2 = "design=v2"
    GUEST_V2 = {"Cookie": V2}
    W = [acct_mod.b58encode(bytes([i + 40]) * 32) for i in range(4)]

    class TestV2ListsPages(AioHTTPTestCase):
        async def get_application(self):
            self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
            s = settings.load()
            s["ready_lists_on"], s["ready_top_pages"], s["ready_min_pnl"] = True, 4, 0
            s["ready_human"] = dict(s["ready_human"], min_closed=1, win_rate=[0, 100])
            s["ready_roi_pages"], s["ready_roi_min_invested"], s["ready_roi_min_pnl"] = 2, 0, 0
            app = create_app(ReadyST(TRADES), s, {}, out_dir=self.tmp.name + "/web", store_dir=self.tmp.name + "/cache")
            app["admins"] = {TEST_PK}
            app["tg"]["token"], app["tg"]["name"], app["tg"]["on"] = "test-token", "tracced_bot", True   # alerts run here
            app["tg"]["checked"] = True
            return app

        async def tearDownAsync(self):
            await asyncio.to_thread(self.app["jobs"].q.join)
            await asyncio.to_thread(self.app["jobs"].rq.join)
            await self.client.close()
            self.tmp.cleanup()

        def me(self, v2=True):
            return {"Cookie": wallet_cookie(TEST_PK) + ("; " + V2 if v2 else "")}

        @property
        def origin(self):
            return {"Origin": f"http://{self.client.host}:{self.client.port}"}

        async def page(self, path, headers):
            r = await self.client.get(path, headers=headers)
            self.assertEqual(r.status, 200, path)
            return await r.text()

        def seed(self):
            acc, now = self.app["accounts"], int(time.time() * 1000)
            acc.load(TEST_PK)
            acc.create_list(TEST_PK, "Second")
            acc.add_wallets(TEST_PK, [{"wallet": w} for w in W])
            acc.set_my_tags(TEST_PK, W[0], ["fast flipper", "sold the top"])
            acc.set_wallet_alert(TEST_PK, W[0], True)
            acc.add_analysis(TEST_PK, "JOBV2", {"mint": "M" * 40, "symbol": "CLAUDIA", "t_from": now - 7_200_000, "t_to": now - 3_600_000, "n": 755, "best": 10.2})

        # ───────────── a ready list ─────────────
        async def test_the_ready_list_in_v2_and_as_before(self):
            await _ready_refresh(self.app)
            html = await self.page("/lists/top-traders", self.me())
            self.assertIn('data-design="v2"', html)
            self.assertIn("/static/v2/lists.css", html)
            self.assertIn('<main class="withcard v2lists">', html)
            self.assertIn('class="lv-tally"', html)
            for label in ("Profit", "Best", "Wallets", "Next update"):
                self.assertIn(f"<span>{label}</span>", html)
            self.assertIn('class="lv-rows"', html)
            self.assertIn(addr("K", 1), html)                                              # a row is a real wallet of the list
            self.assertIn('<svg class="fp"', html)                                         # its fingerprint, not a made-up face
            self.assertIn("100% win rate", html)
            self.assertIn('data-follow="top-traders"', html)                               # the one key: Follow 10 wallets
            self.assertIn("Follow 10 wallets", html)
            self.assertIn('href="/lists/top-roi"', html)                                   # the other list, for comparison
            self.assertIn('id="drawer"', html)                                             # the card, the same as on a result
            self.assertIn('<button type="button" data-p="7">7D</button><button type="button" data-p="30" class="on">30D</button>', html)
            self.assertIn("document.querySelector('.lv-rows')", html)
            self.assertNotIn('class="lp-rows"', html)
            self.assertIsNone(CYRILLIC.search(html))
            old = await self.page("/lists/top-traders", self.me(v2=False))                 # no cookie: the page as it was
            self.assertIn('class="lp-rows"', old)
            self.assertNotIn("lv-rows", old)
            self.assertNotIn('data-design="v2"', old)
            roi = await self.page("/lists/top-roi", self.me())
            self.assertIn("<span>Best ROI</span>", roi)
            self.assertIn("+50%</b>", roi)                                                 # ROI is the main number there

        async def test_a_guest_sees_the_title_a_line_and_connect(self):
            await _ready_refresh(self.app)
            html = await self.page("/lists/top-traders", GUEST_V2)
            self.assertIn('class="lv-gate"', html)
            self.assertIn("Connect a wallet to see the 10 traders of this list and follow them.", html)
            self.assertIn("data-wallet-signin", html)
            self.assertNotIn(addr("K", 1), html)
            self.assertNotIn("lv-rows", html)
            self.assertNotIn('id="drawer"', html)

        async def test_after_follow_the_key_opens_the_watchlist(self):
            await _ready_refresh(self.app)
            r = await self.client.post("/me/ready/follow", json={"slug": SLUG}, headers=self.me() | self.origin)
            self.assertEqual(r.status, 200)
            html = await self.page("/lists/top-traders", self.me())
            self.assertIn("Open in your watchlist", html)
            self.assertIn("data-open-list=", html)
            self.assertNotIn('data-follow="top-traders"', html)

        # ───────────── the watchlist ─────────────
        async def test_the_watchlist_in_v2_keeps_every_control(self):
            self.seed()
            html = await self.page("/me", self.me())
            self.assertIn('<main class="withcard v2me">', html)
            # Telegram alerts: a head and three tiles (switches, the sum with quick picks, today's use)
            self.assertIn('id="tgbar"', html)
            self.assertIn('id="tgbuys" role="switch" aria-checked="true"', html)
            self.assertIn('id="tgsells" role="switch"', html)
            self.assertIn('id="tgmin"', html)
            for v in (0, 100, 1000, 10000):
                self.assertIn(f'data-min="{v}"', html)
            self.assertIn('<b id="tgn" data-cap="20">1</b>', html)                         # one bell of twenty
            self.assertIn("Connect Telegram", html)                                        # not linked yet
            self.assertIn('id="tgunlink" hidden', html)
            # the lists as tabs, a new list, the open list's bar with its switch, Rename and Delete
            self.assertIn('class="mv-tab on" data-list=""', html)
            self.assertIn(">Second <b>0</b>", html)
            self.assertIn('id="lnew"', html)
            for el in ('id="lalert" role="switch"', 'id="lrename"', 'id="ldelete"', 'id="xcsv"', 'id="xtxt"'):
                self.assertIn(el, html)
            # a row: its fingerprint, its short address, your tags with their × and +, the bell and ×
            self.assertEqual(html.count('class="mv-row"'), 4)
            self.assertIn(W[0][:4] + "…" + W[0][-4:], html)
            self.assertIn("<span>fast flipper</span>", html)
            self.assertIn('class="tagx" data-tag="sold the top"', html)
            self.assertIn('class="tagadd"', html)
            self.assertIn('class="mv-bell on" data-bell aria-pressed="true"', html)
            self.assertEqual(html.count('data-rm-wallet title="Remove from this list"'), 4)
            self.assertIn('id="drawer"', html)
            self.assertIn('id="mewmeta"', html)
            # My analyses: the token, its range, wallets, best, Open and ×
            self.assertIn('class="mv-arow" data-j="JOBV2"', html)
            self.assertIn('href="/job/JOBV2">Open</a>', html)
            self.assertIn("data-rm-job", html)
            self.assertIsNone(CYRILLIC.search(html))
            old = await self.page("/me", self.me(v2=False))                               # no cookie: the page as it was
            self.assertIn('class="facts melist mewl"', old)
            self.assertIn('class="card tgcard', old)
            self.assertNotIn("mv-row", old)

        async def test_a_linked_telegram_and_the_drafts_preview(self):
            self.seed()
            self.app["accounts"].set_telegram(TEST_PK, 4242, "@owner")
            html = await self.page("/me", self.me())
            self.assertIn("Connected as <b>@owner</b>", html)
            self.assertIn('id="tgconnect" hidden', html)
            self.assertNotIn('id="tgunlink" hidden', html)
            self.assertNotIn('id="after"', html)                                           # After the alerts: the draft only
            self.app["tg"]["on"] = False                                                   # the draft: no bot runs there
            self.app["s"]["private_hosts"] = [self.client.host]
            self.app["accounts"].clear_telegram(TEST_PK)
            html = await self.page("/me", self.me())
            self.assertIn('id="tgpill"', html)
            self.assertIn(">Preview</span>", html)
            self.assertNotIn('id="tgconnect"', html)                                       # nothing to connect on the draft
            self.assertIn('id="after"', html)
            self.assertIn('id="aftrows"', html)

        async def test_a_guest_and_an_empty_watchlist(self):
            html = await self.page("/me", GUEST_V2)
            self.assertIn('class="mv-card mv-guest"', html)
            self.assertIn("data-wallet-signin", html)
            self.assertNotIn('id="list"', html)
            html = await self.page("/me", self.me())
            self.assertIn("Nothing here yet. On a result, click the", html)
            self.assertNotIn('class="mv-row"', html)
            self.assertNotIn('id="drawer"', html)


if __name__ == "__main__":
    unittest.main()
