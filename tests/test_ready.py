"""Готові списки (власник, 07.10): відбір із рейтингів Solana Tracker, головна, сторінка списку, «Follow» одним кліком і
картка гаманця зі списку. Без мережі."""
import asyncio
import json
import tempfile
import time
import unittest

try:
    from aiohttp.test_utils import AioHTTPTestCase
except ImportError:  # хост без aiohttp: тести сторінок пропускаються
    AioHTTPTestCase = None

from tracced.early import ready, settings
from tracced.early.st_client import EarlyST

try:
    from tests.test_early_pipeline import TRADES
except ImportError:
    from test_early_pipeline import TRADES


B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def addr(c, i):
    """Адреса, яку сайт приймає за гаманець: лише base58, без нулів."""
    return c + B58[i // 58] + B58[i % 58] + c.lower() * 40


def kol(i, realized, name=None, twitter=None, avatar=None):
    return {"wallet": addr("K", i), "period": {"realized": realized, "volume": realized * 3, "tradingDays": 12},
            "identity": {"name": name or f"Kol {i}", "twitter": twitter or f"@kol{i}", "avatar": avatar, "type": "kol"}}


def top(i, realized, invested=50_000.0, trades=300, win=60.0, kind=None):
    return {"wallet": addr("T", i), "period": {"realized": realized, "tradingDays": 20}, "invested": invested,
            "counts": {"trades": trades, "buys": trades // 2, "sells": trades // 2, "tokensTraded": 40}, "winRate": win,
            "identity": {"type": kind, "platforms": ["axiom", "photon"]}}


class TestKols(unittest.TestCase):
    def test_best_first_ten_at_most_and_only_safe_avatars(self):
        raw = [kol(i, 1000.0 * i) for i in range(1, 15)]
        raw[0]["identity"]["avatar"] = "https://pbs.example/a.jpg"
        raw[1]["identity"]["avatar"] = "javascript:alert(1)"
        raw[2]["identity"]["avatar"] = 'https://x.example/a.jpg" onerror="x'
        raw.append({"wallet": "", "period": {"realized": 9e9}})                  # без адреси
        raw.append({"wallet": "Z" * 44, "period": {"realized": "lots"}})         # сума не число
        rows = ready.kols(raw)
        self.assertEqual(len(rows), ready.SIZE)
        self.assertEqual([r["realized"] for r in rows], sorted((r["realized"] for r in rows), reverse=True))
        self.assertEqual(rows[0]["wallet"], raw[13]["wallet"])
        self.assertEqual(rows[0]["x"], "kol14")                                 # без @
        by = {r["wallet"]: r for r in ready.kols(raw[:3])}
        self.assertEqual(by[raw[0]["wallet"]]["avatar"], "https://pbs.example/a.jpg")
        self.assertIsNone(by[raw[1]["wallet"]]["avatar"])
        self.assertIsNone(by[raw[2]["wallet"]]["avatar"])

    def test_a_name_is_cut_to_fit_a_row(self):
        self.assertEqual(len(ready.kols([kol(1, 10.0, name="N" * 100)])[0]["name"]), 32)


class TestTopTraders(unittest.TestCase):
    """Вгорі загальної дошки — боти й «прибуток» з токенів, що прийшли задарма (замір 07.10). Лишається лише людський темп."""

    def test_the_bounds_of_a_person(self):
        self.assertTrue(ready.is_person(top(1, 100_000.0)))
        self.assertFalse(ready.is_person(top(1, 100_000.0, trades=ready.MAX_TRADES + 1)))   # сотні тисяч угод — машина
        self.assertTrue(ready.is_person(top(1, 100_000.0, trades=ready.MAX_TRADES)))
        self.assertFalse(ready.is_person(top(1, 23e6, invested=61.0)))                     # $61 у вхід, $23M на виході
        self.assertTrue(ready.is_person(top(1, 20 * 5000.0, invested=5000.0)))             # рівно 20× — ще людина
        self.assertFalse(ready.is_person(top(1, 100_000.0, win=98.0)))                     # бот або wash
        self.assertFalse(ready.is_person(top(1, 100_000.0, win=29.9)))
        self.assertTrue(ready.is_person(top(1, 100_000.0, win=30.0)))
        self.assertTrue(ready.is_person(top(1, 100_000.0, win=90.0)))
        self.assertFalse(ready.is_person(top(1, 100_000.0, kind="bot")))
        self.assertFalse(ready.is_person(top(1, 100_000.0, kind="exchange")))
        self.assertFalse(ready.is_person(top(1, 100_000.0, trades=0)))
        self.assertFalse(ready.is_person(top(1, -5.0)))
        self.assertFalse(ready.is_person(top(1, 100.0, invested=0)))

    def test_ten_people_best_first_without_repeats(self):
        raw = [top(i, 1e6 - i * 1000, win=99.0) for i in range(30)]                 # боти зверху
        raw += [top(100 + i, 5e5 - i * 1000) for i in range(15)]
        raw.append(dict(raw[30]))                                                     # той самий гаманець з другої сторінки
        rows = ready.traders(raw)
        self.assertEqual(len(rows), ready.SIZE)
        self.assertEqual(len({r["wallet"] for r in rows}), ready.SIZE)
        self.assertTrue(all(r["wallet"] in {addr("T", 100 + i) for i in range(15)} for r in rows))   # жодного бота
        self.assertEqual(rows[0]["realized"], 5e5)
        self.assertEqual(rows[0]["apps"], ["axiom", "photon"])
        self.assertEqual((rows[0]["trades"], rows[0]["win_rate"]), (300, 60.0))

    def test_summary(self):
        self.assertEqual(ready.summary([{"realized": 3.0}, {"realized": 5.0}]), {"n": 2, "realized": 8.0, "best": 5.0})
        self.assertEqual(ready.summary([]), {"n": 0, "realized": 0, "best": 0.0})


class TestClientPaging(unittest.TestCase):
    def test_the_board_is_read_by_cursor_and_stops_where_it_ends(self):
        st = EarlyST("k", pause=0)
        st.paths = []

        def fake(path, body=None):
            st.paths.append(path)
            n = len(st.paths)
            return {"traders": [top(n, 1.0)], "pagination": {"nextCursor": f"c{n}", "hasMore": n < 3}}
        st._get = fake
        self.assertEqual(len(st.top_traders(30, pages=10)), 3)
        self.assertEqual(len(st.paths), 3)
        self.assertNotIn("cursor=", st.paths[0])
        self.assertIn("&cursor=c1", st.paths[1])
        self.assertIn("days=30", st.paths[0])
        st.paths.clear()
        self.assertEqual(len(st.top_traders(30, pages=2)), 2)                            # стеля сторінок тримає
        st.paths.clear()

        def kfake(path, body=None):
            st.paths.append(path)
            return {"traders": [kol(1, 5.0)]}
        st._get = kfake
        self.assertEqual(len(st.kol_leaderboard(30, 20)), 1)
        self.assertIn("/v2/pnl/leaderboard/kols/period?period=30d&sort=realized&direction=desc&limit=20", st.paths[0])


if AioHTTPTestCase:
    try:
        from tests.test_web import FakeWebST, TEST_PK, wallet_cookie, CYRILLIC, seed_demo, OTHER_JID, OTHER_MINT
    except ImportError:
        from test_web import FakeWebST, TEST_PK, wallet_cookie, CYRILLIC, seed_demo, OTHER_JID, OTHER_MINT
    from tracced.web import accounts as acct_mod
    from tracced.web.app import create_app, _ready_refresh

    GUEST = {"Cookie": ""}
    OTHER = acct_mod.b58encode(b"\x09" * 32)                      # звичайний гаманець, не власник

    class ReadyST(FakeWebST):
        def kol_leaderboard(self, days=30, limit=10):
            self.requests += 1
            return [kol(i, 1e6 / i, name=f"Kol {i}", avatar="https://pbs.example/%d.jpg" % i) for i in range(1, 13)]

        def top_traders(self, days=30, pages=10, per_page=100):
            self.requests += pages
            return [top(i, 9e5 - i * 1000) for i in range(12)]

    class TestReadyWeb(AioHTTPTestCase):
        async def get_application(self):
            self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
            self.st = ReadyST(TRADES)
            s = settings.load()
            s["ready_lists_on"], s["ready_top_pages"] = True, 4
            app = create_app(self.st, s, {}, out_dir=self.tmp.name + "/web", store_dir=self.tmp.name + "/cache")
            app["admins"] = {TEST_PK}
            return app

        async def setUpAsync(self):
            await super().setUpAsync()
            self.client.session.headers["Cookie"] = wallet_cookie(TEST_PK)

        async def tearDownAsync(self):
            await asyncio.to_thread(self.app["jobs"].q.join)
            await asyncio.to_thread(self.app["jobs"].rq.join)
            await self.client.close()
            self.tmp.cleanup()

        @property
        def origin(self):
            return {"Origin": f"http://{self.client.host}:{self.client.port}"}

        async def refresh(self):
            await _ready_refresh(self.app)
            return self.app["ready"]["lists"]

        async def test_the_lists_are_read_twice_a_day_and_kept_in_a_file(self):
            self.app["s"]["ready_lists_on"] = False
            self.assertNotIn('id="ready"', await (await self.client.get("/")).text())     # вимкнено — ні блоку, ні запитів
            self.assertEqual(self.st.requests, 0)
            self.app["s"]["ready_lists_on"] = True
            lists = await self.refresh()
            self.assertEqual(self.st.requests, 1 + 4)                                      # KOL — один запит, дошка — 4 сторінки
            self.assertEqual(set(lists), {"kols-30d", "top-traders-30d"})
            self.assertEqual(len(lists["kols-30d"]["rows"]), 10)
            self.assertEqual(lists["kols-30d"]["rows"][0]["name"], "Kol 1")
            self.assertEqual(lists["top-traders-30d"]["summary"]["n"], 10)
            await self.refresh()
            self.assertEqual(self.st.requests, 5)                                          # за 12 годин — не раніше
            with open(self.tmp.name + "/ready_lists.json") as f:
                self.assertEqual(set(json.load(f)["lists"]), set(lists))                    # після перезапуску — з файлу

        async def test_a_failed_list_keeps_its_last_version(self):
            await self.refresh()
            was = self.app["ready"]["lists"]["kols-30d"]["rows"]

            def down(*a, **k):
                raise RuntimeError("board down")
            self.st.kol_leaderboard = down
            self.app["ready"]["at"] = 0
            lists = await self.refresh()
            self.assertEqual(lists["kols-30d"]["rows"], was)
            self.assertFalse(self.app["ready"]["busy"])

        async def test_home_shows_two_cards_with_a_podium_and_one_key_each(self):
            await self.refresh()
            html = await (await self.client.get("/", headers=GUEST)).text()
            self.assertIn('id="ready"', html)
            self.assertIn("KOLs · 30 days", html)
            self.assertIn("Top traders · 30 days", html)
            self.assertIn('data-follow="kols-30d"', html)
            self.assertIn("Follow 10 wallets", html)
            self.assertIn("and 7 more", html)                                               # троє рядками, решта обличчями
            self.assertIn('src="https://pbs.example/1.jpg"', html)
            self.assertIn("@kol1", html)
            self.assertIn("Past results, not advice.", html)
            self.assertLess(html.index('id="ready"'), html.index('class="freebar"'))          # «Free while we build it» — нижче, окремо
            self.assertNotIn("herofree", html)
            self.assertIsNone(CYRILLIC.search(html))

        async def test_the_list_page_is_open_to_anyone_and_unknown_lists_are_404(self):
            await self.refresh()
            r = await self.client.get("/lists/top-traders-30d", headers=GUEST)
            self.assertEqual(r.status, 200)
            html = await r.text()
            self.assertIn("human pace", html)                                              # правило відбору на сторінці
            self.assertIn("% win rate", html)
            self.assertIn('href="/lists/kols-30d"', html)                                   # інший список
            self.assertIn('id="dlist"', html)                                              # у картці — цифри списку, і гостю
            self.assertIn('data-follow="top-traders-30d"', html)
            self.assertIsNone(CYRILLIC.search(html))
            self.assertEqual((await self.client.get("/lists/nope", headers=GUEST)).status, 404)

        async def test_follow_takes_the_list_with_its_bells_once(self):
            await self.refresh()
            r = await self.client.post("/me/ready/follow", json={"slug": "kols-30d"}, headers=GUEST | self.origin)
            self.assertEqual(r.status, 401)                                                # гість спершу підключається
            r = await self.client.post("/me/ready/follow", json={"slug": "kols-30d"})
            self.assertEqual(r.status, 403)                                                # лише з цього сайту
            r = await self.client.post("/me/ready/follow", json={"slug": "kols-30d"}, headers=self.origin)
            d = await r.json()
            self.assertEqual(r.status, 200, d)
            self.assertEqual((d["name"], d["added"], d["alerts_on"], d["alerts_ok"], d["telegram"]), ("KOLs · 30 days", 10, 10, True, False))
            a = self.app["accounts"].load(TEST_PK)
            self.assertEqual(a["lists"][d["list"]]["name"], "KOLs · 30 days")
            rows = self.app["ready"]["lists"]["kols-30d"]["rows"]
            self.assertTrue(all(d["list"] in a["wallets"][x["wallet"]]["lists"] and a["wallets"][x["wallet"]]["alert"] for x in rows))
            again = await (await self.client.post("/me/ready/follow", json={"slug": "kols-30d"}, headers=self.origin)).json()
            self.assertEqual((again["list"], again["added"]), (d["list"], 0))              # той самий список, без дублів
            html = await (await self.client.get("/lists/kols-30d")).text()
            self.assertIn("In your watchlist", html)
            self.assertNotIn('data-follow="kols-30d"', html)
            r = await self.client.post("/me/ready/follow", json={"slug": "nope"}, headers=self.origin)
            self.assertEqual(r.status, 404)
            tail = [e["event"] for e in self.app["events"].tail(10)]
            self.assertIn("list_follow", tail)

        async def test_a_second_list_rings_only_while_bells_are_left(self):
            await self.refresh()
            await self.client.post("/me/ready/follow", json={"slug": "kols-30d"}, headers=self.origin)
            d = await (await self.client.post("/me/ready/follow", json={"slug": "top-traders-30d"}, headers=self.origin)).json()
            self.assertEqual((d["added"], d["alerts_on"], d["cap"]), (10, 0, 10))         # усі 10 дзвіночків уже зайняті

        async def test_the_result_head_shows_the_tokens_picture_and_each_row_its_phone_line(self):
            seed_demo(self.tmp.name, self.app)
            html = await (await self.client.get(f"/job/{OTHER_JID}")).text()
            self.assertIn('class="limg h-img" data-l="', html)                             # літера, поки картинки нема
            self.assertNotIn("https://img.example/t.png", html)
            self.app["token_images"].put(OTHER_MINT, "https://img.example/t.png")
            html = await (await self.client.get(f"/job/{OTHER_JID}")).text()
            self.assertIn('<img src="https://img.example/t.png"', html)
            self.assertIn('class="msub"', html)                                            # рядок гаманця на телефоні (власник, 07.10)
            self.assertIn('class="wface"', html)
            self.assertIn('aria-label="Save analysis"', html)                              # на телефоні кнопка — лише зірка
            self.assertIsNone(CYRILLIC.search(html))

        async def test_a_ready_wallets_card_opens_without_a_watchlist(self):
            await self.refresh()
            w = self.app["ready"]["lists"]["kols-30d"]["rows"][0]["wallet"]
            r = await self.client.get(f"/wallet_profile.json?wallet={w}", headers=GUEST)
            self.assertEqual(r.status, 401)                                                # новий профіль — лише з гаманцем
            self.client.session.headers["Cookie"] = wallet_cookie(OTHER)
            r = await self.client.get(f"/wallet_profile.json?wallet={w}")
            self.assertEqual(r.status, 200, await r.text())                                # не у вотчлісті — і все одно відкривається
            r = await self.client.get(f"/wallet_profile.json?wallet={w}", headers=GUEST)
            self.assertEqual(r.status, 200)                                                # з кешу — і гостю
            stranger = acct_mod.b58encode(b"\x0b" * 32)
            r = await self.client.get(f"/wallet_profile.json?wallet={stranger}")
            self.assertEqual(r.status, 404)                                                # чужа адреса — ні


if __name__ == "__main__":
    unittest.main()
