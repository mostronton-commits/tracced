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
        self.assertTrue(ready.is_person(top(1, 23e6, invested=61.0)))                      # «прибуток з повітря» відсіє наш підрахунок
        self.assertTrue(ready.is_person(top(1, 100_000.0, win=98.0)))                      # і win rate — теж наш, за місяць
        self.assertFalse(ready.is_person(top(1, 100_000.0, kind="bot")))
        self.assertFalse(ready.is_person(top(1, 100_000.0, kind="exchange")))
        self.assertFalse(ready.is_person(top(1, 100_000.0, trades=0)))
        self.assertFalse(ready.is_person(top(1, -5.0)))
        self.assertFalse(ready.is_person(top(1, 100.0, invested=0)))

    def test_ten_people_best_first_without_repeats(self):
        raw = [top(i, 1e6 - i * 1000, trades=50_000) for i in range(30)]           # боти зверху
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
        self.assertEqual(ready.summary([{"pnl": 3.0}, {"pnl": 5.0}]), {"n": 2, "pnl": 8.0, "best": 5.0})
        self.assertEqual(ready.summary([]), {"n": 0, "pnl": 0, "best": 0.0})


class TestOwnCount(unittest.TestCase):
    """Власник, 08.10: список казав +$2.31M, картка $463K. Тепер у списку — той самий підрахунок, що в картці, за місяць."""

    def month(self, pnl, partial=False, wr=0.41, **kw):
        return dict({"pnl_usd": pnl, "win_rate": wr, "wins": 7, "losses": 10, "closed": 17, "tokens": 22, "swaps": 81,
                     "quick": 2, "avg_hold_min": 190.0, "partial": partial}, **kw)

    def test_the_count_gives_the_number_and_the_board_only_the_name(self):
        row = ready.counted(ready.kols([kol(1, 2_309_458.4, name="Dolo")])[0], self.month(463_143.0))
        self.assertEqual(row["pnl"], 463_143.0)
        self.assertEqual((row["win_rate"], row["wins"], row["losses"], row["tokens"], row["closed"]), (41.0, 7, 10, 22, 17))
        self.assertEqual((row["name"], row["x"], row["month"]["pnl_usd"]), ("Dolo", "kol1", 463_143.0))   # місяць — і для картки
        self.assertNotIn("realized", row)                                          # суми рейтингу не показуються ніде
        self.assertIsNone(ready.counted(ready.kols([kol(2, 1.0)])[0], self.month(5.0, wr=None))["win_rate"])

    def test_a_list_keeps_whole_months_in_profit_best_first(self):
        rows = [ready.counted(ready.kols([kol(i, 1.0)])[0], self.month(pnl, partial)) for i, (pnl, partial) in
                enumerate([(100.0, False), (-5.0, False), (900.0, True), (0.0, False), (300.0, False)], 1)]
        out = ready.rank(rows)
        self.assertEqual([r["pnl"] for r in out], [300.0, 100.0])                 # збиток, нуль і неповний місяць — поза
        self.assertEqual([r["pnl"] for r in ready.rank(rows, min_pnl=150)], [300.0])   # поріг «топу»
        self.assertEqual(len(ready.rank([dict(rows[0], wallet=str(i)) for i in range(15)])), ready.SIZE)


class TestOneList(unittest.TestCase):
    """Власник, 08.10: «просто одну картку топ трейдери за вересень» — KOL і рейтинг разом, і поруч — як її склали."""

    def test_both_boards_once_each_the_kol_name_first(self):
        k = ready.kols([kol(1, 5.0, name="Dolo")])
        t = ready.traders([dict(top(9, 1e5), wallet=k[0]["wallet"]), top(8, 9e4)])
        out = ready.merged(k, t)
        self.assertEqual([r["wallet"] for r in out], [k[0]["wallet"], addr("T", 8)])
        self.assertEqual(out[0]["name"], "Dolo")

    def test_how_the_list_was_made(self):
        f = ready.funnel(141, {"pace": 81, "fresh": 24, "bot": 2, "win rate": 9, "few": 6}, 19, 10)
        self.assertEqual(f["checked"], 141)
        self.assertEqual(f["reasons"][:3], [["trade at a machine's pace", 81], ["fresh wallets", 24], ["win rate outside 30–90 %", 9]])
        self.assertIn(["people who made less", 9], f["reasons"])                   # люди, що не ввійшли в десятку
        self.assertEqual(ready.funnel(5, {}, 3, 3)["reasons"], [])

    def test_roi_is_the_profit_on_what_went_in(self):
        row = ready.counted({"wallet": "W"}, {"pnl_usd": 30_000.0, "invested_usd": 10_000.0, "win_rate": 0.5})
        self.assertEqual((row["roi"], row["invested"]), (3.0, 10_000.0))
        self.assertIsNone(ready.counted({"wallet": "W"}, {"pnl_usd": 5.0, "invested_usd": 0})["roi"])


class TestMonth(unittest.TestCase):
    """Власник, 08.10: «топ трейдери за попередній місяць» — список змінюється раз на місяць і каже, за який."""

    def test_the_month_before_this_one(self):
        oct8 = 1_791_417_600_000                                                    # 2026-10-08 UTC
        m = ready.prev_month(oct8)
        self.assertEqual((m["key"], m["label"], m["short"], m["days"], m["next_label"]), ("2026-09", "September", "Sep 2026", 30, "Nov 1"))
        self.assertEqual(time.strftime("%Y-%m-%d %H:%M", time.gmtime(m["from"] / 1000)), "2026-09-01 00:00")
        self.assertEqual(time.strftime("%Y-%m-%d %H:%M", time.gmtime(m["to"] / 1000)), "2026-10-01 00:00")
        jan = ready.prev_month(1_799_000_000_000)                                  # 2027-01-03: грудень минулого року
        self.assertEqual((jan["key"], jan["label"], jan["days"], jan["next_label"]), ("2026-12", "December", 31, "Feb 1"))
        dec = ready.prev_month(1_796_000_000_000)                                  # 2026-11-29 → жовтень, наступний — 1 грудня
        self.assertEqual((dec["key"], dec["next_label"]), ("2026-10", "Dec 1"))
        self.assertEqual(ready.titled("top-traders", m)["title"], "Top traders · September")


class TestHuman(unittest.TestCase):
    """Власник, 08.10: боти, свіжі гаманці, снайпери й тисячі угод — поза списками; лише ті, хто торгує як людина."""
    SEP1 = 1_788_220_800_000                                                      # 2026-09-01 UTC

    def row(self, **kw):
        base = {"pnl_usd": 50_000.0, "win_rate": 0.55, "wins": 11, "losses": 9, "closed": 20, "tokens": 60, "swaps": 300,
                "quick": 2, "avg_hold_min": 45.0}
        return ready.counted({"wallet": "W"}, dict(base, **kw))

    def test_a_person(self):
        self.assertIsNone(ready.not_human(self.row(), self.SEP1, {"first_trade": self.SEP1 - 400 * ready.DAY}))
        self.assertIsNone(ready.not_human(self.row(), self.SEP1, {}))               # Solana Tracker не знає — не причина

    def test_what_is_not(self):
        cases = {
            "pace": [self.row(swaps=1501), self.row(tokens=301), self.row(partial=True)],
            "few": [self.row(closed=4)],
            "win rate": [self.row(win_rate=0.97), self.row(win_rate=0.29), self.row(win_rate=None)],
            "sniper": [self.row(avg_hold_min=1.5), self.row(quick=11)],          # півхвилини на позицію, більше половини — за хвилину
        }
        for why, rows in cases.items():
            for r in rows:
                self.assertEqual(ready.not_human(r, self.SEP1, {}), why, r)
        self.assertEqual(ready.not_human(self.row(), self.SEP1, {"first_trade": self.SEP1 - 10 * ready.DAY}), "fresh")
        self.assertEqual(ready.not_human(self.row(), self.SEP1, {"arbitrage": True}), "bot")
        self.assertEqual(ready.not_human(self.row(), self.SEP1, {"type": "exchange"}), "bot")
        self.assertIsNone(ready.not_human(self.row(swaps=1501), self.SEP1, {}, {"max_swaps": 2000}))   # межі — з налаштувань


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

    def test_first_trades_come_a_hundred_at_a_time(self):
        st = EarlyST("k", pause=0)
        st.bodies = []

        def fake(path, body=None):
            st.bodies.append((path, body))
            return {"wallets": [{"wallet": w, "summary": {"timing": {"firstTrade": 1_700_000_000_000}},
                                 "tags": {"isArbitrage": w.endswith("9")}, "identity": {"type": "trader"}} for w in body["wallets"]]}
        st._get = fake
        ws = [f"W{i:03d}" for i in range(150)]
        out = st.wallet_summaries(ws + ws[:5])                                       # повтори не питаються двічі
        self.assertEqual([len(b["wallets"]) for _, b in st.bodies], [100, 50])
        self.assertEqual(st.bodies[0][0], "/v2/pnl/wallets/batch")
        self.assertEqual(out["W000"], {"first_trade": 1_700_000_000_000, "arbitrage": False, "type": "trader"})
        self.assertTrue(out["W009"]["arbitrage"])


if AioHTTPTestCase:
    try:
        from tests.test_web import FakeWebST, TEST_PK, wallet_cookie, CYRILLIC, seed_demo, OTHER_JID, OTHER_MINT
    except ImportError:
        from test_web import FakeWebST, TEST_PK, wallet_cookie, CYRILLIC, seed_demo, OTHER_JID, OTHER_MINT
    from tracced.web import accounts as acct_mod
    from tracced.web.app import create_app, _ready_refresh

    GUEST = {"Cookie": ""}
    OTHER = acct_mod.b58encode(b"\x09" * 32)                      # звичайний гаманець, не власник
    SLUG = "top-traders"

    class ReadyST(FakeWebST):
        def kol_leaderboard(self, days=30, limit=10):
            self.requests += 1
            return [kol(i, 1e6 / i, name=f"Kol {i}", avatar="https://pbs.example/%d.jpg" % i) for i in range(1, 13)]

        def top_traders(self, days=30, pages=10, per_page=100):
            self.requests += pages
            return [top(i, 9e5 - i * 1000) for i in range(12)]

        def wallet_summaries(self, wallets):
            self.requests += 1
            now = int(time.time() * 1000)
            return {addr("K", 2): {"first_trade": now - ready.DAY, "arbitrage": False, "type": "kol"},     # свіжий
                    addr("T", 3): {"first_trade": now - 900 * ready.DAY, "arbitrage": True, "type": None}}  # арбітражний бот

        def wallet_swaps(self, owner, since_ms, max_pages=5):
            """Одна купівля і продаж з прибутком $50 — у минулому місяці, хоч би яке сьогодні число."""
            return super().wallet_swaps(owner, ready.prev_month(time.time() * 1000)["from"], max_pages)

    class TestReadyWeb(AioHTTPTestCase):
        async def get_application(self):
            self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
            self.st = ReadyST(TRADES)
            s = settings.load()
            s["ready_lists_on"], s["ready_top_pages"], s["ready_min_pnl"] = True, 4, 0   # у фейку кожен гаманець заробляє $50
            s["ready_human"] = {"min_closed": 1, "win_rate": [0, 100]}                     # одна закрита позиція на гаманець
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

        @property
        def month(self):
            return ready.prev_month(time.time() * 1000)

        async def refresh(self):
            await _ready_refresh(self.app)
            return self.app["ready"]["lists"]

        async def test_one_list_of_last_month_counted_once_and_kept_in_a_file(self):
            self.app["s"]["ready_lists_on"] = False
            self.assertNotIn('id="ready"', await (await self.client.get("/")).text())     # вимкнено — ні блоку, ні запитів
            await self.refresh()
            self.assertEqual(self.st.requests, 0)
            self.app["s"]["ready_lists_on"] = True
            lists = await self.refresh()
            # KOL — 1 запит, дошка — 4 сторінки, перші угоди — 1 на всіх, і кожен кандидат (24) своїми обмінами, крім
            # свіжого KOL і арбітражного бота: їх відсіяно до запиту
            self.assertEqual(self.st.requests, 1 + 4 + 1 + 22)
            self.assertEqual(set(lists), {SLUG})                                           # власник, 08.10: один список
            t = lists[SLUG]
            self.assertEqual((t["title"], t["month"], t["next_label"]), ("Top traders · " + self.month["label"], self.month["key"], self.month["next_label"]))
            self.assertEqual(t["funnel"], {"checked": 24, "listed": 10, "reasons": [["people who made less", 12], ["fresh wallets", 1], ["bots, exchanges, arbitrage", 1]]})
            self.assertEqual(len(t["pool"]), 22)                                           # усі люди — на випадок списку за ROI
            first = t["rows"][0]
            self.assertEqual((first["name"], first["pnl"], first["win_rate"], first["month"]["label"]), ("Kol 1", 50.0, 100.0, self.month["label"]))
            self.assertNotIn("realized", first)
            self.assertNotIn(addr("K", 2), [r["wallet"] for r in t["rows"]])
            self.app["ready"]["tried_at"] = 0
            await self.refresh()
            self.assertEqual(self.st.requests, 28)                                         # місяць уже пораховано: до 1-го — ні запиту
            with open(self.tmp.name + "/ready_lists.json") as f:
                saved = json.load(f)
            self.assertEqual((saved["v"], set(saved["lists"])), (4, {SLUG}))                 # після перезапуску — з файлу

        async def test_a_new_month_counts_again_but_not_after_every_failure(self):
            await self.refresh()
            self.app["ready"]["lists"][SLUG]["month"] = "2000-01"                          # минулий місяць змінився
            n = self.st.requests
            await self.refresh()
            self.assertEqual(self.st.requests, n)                                          # щойно пробували — чекає ready_retry_hours
            self.app["ready"]["tried_at"] = 0
            await self.refresh()
            self.assertGreater(self.st.requests, n)
            self.assertEqual(self.app["ready"]["lists"][SLUG]["month"], self.month["key"])

        async def test_a_file_of_an_older_kind_is_not_read(self):
            from tracced.web.app import _ready_load
            path = self.tmp.name + "/old.json"
            for v in (None, 2, 3):
                with open(path, "w") as f:
                    json.dump({"v": v, "lists": {"kols-30d": {"rows": [{"wallet": "W", "pnl": 1.0}]}}, "at": 1}, f)
                self.assertEqual(_ready_load(path)["lists"], {})                            # 07.10 рейтингові, «30 днів», два списки

        async def test_one_board_down_still_makes_the_list_both_down_keep_the_last_month(self):
            await self.refresh()
            was = self.app["ready"]["lists"][SLUG]["rows"]

            def down(*a, **k):
                raise RuntimeError("board down")
            self.st.kol_leaderboard = down
            self.app["ready"]["lists"][SLUG]["month"], self.app["ready"]["tried_at"] = "2000-01", 0
            lists = await self.refresh()
            self.assertEqual(lists[SLUG]["month"], self.month["key"])                        # з одного рейтингу
            self.assertTrue(all(r["wallet"].startswith("T") for r in lists[SLUG]["rows"]))
            self.st.top_traders = down
            self.app["ready"]["lists"][SLUG]["month"], self.app["ready"]["tried_at"] = "2000-01", 0
            kept = self.app["ready"]["lists"][SLUG]["rows"]
            lists = await self.refresh()
            self.assertEqual((lists[SLUG]["rows"], lists[SLUG]["month"]), (kept, "2000-01"))   # обидва впали — той, що був
            self.assertFalse(self.app["ready"]["busy"])
            self.assertNotEqual(was, [])

        async def test_home_shows_the_list_and_beside_it_how_it_is_made(self):
            await self.refresh()
            html = await (await self.client.get("/", headers=GUEST)).text()
            self.assertIn('id="ready"', html)
            self.assertIn("Top traders · " + self.month["label"], html)
            self.assertIn("profit together in " + self.month["label"], html)
            self.assertIn("next list " + self.month["next_label"], html)                       # змінюється раз на місяць
            self.assertEqual(html.count('class="rcard"'), 1)                                # один список (власник, 08.10)
            self.assertIn("How the list is made", html)                                    # і поруч — що це і навіщо
            self.assertIn("<b>24</b><span>wallets checked</span>", html)
            self.assertIn("<li><span>fresh wallets</span><b class=\"mono\">1</b></li>", html)
            self.assertIn("Hours of searching, done.", html)
            self.assertIn('data-follow="top-traders"', html)
            self.assertIn("Follow 10 wallets", html)
            self.assertIn('href="/lists/top-traders">See all 10</a>', html)
            self.assertIn('src="https://pbs.example/1.jpg"', html)
            self.assertIn("@kol1 · 100% win rate", html)
            self.assertIn("Their trades come to your Telegram.", html)
            for gone in ("and 7 more", "Past results", "Rankings by", "rc-stack", "KOLs · "):
                self.assertNotIn(gone, html)
            self.assertLess(html.index('id="ready"'), html.index('class="freebar"'))          # «Free while we build it» — нижче, окремо
            self.assertIsNone(CYRILLIC.search(html))

        async def test_the_list_page_is_open_to_anyone_and_unknown_lists_are_404(self):
            await self.refresh()
            r = await self.client.get("/lists/top-traders", headers=GUEST)
            self.assertEqual(r.status, 200)
            html = await r.text()
            self.assertIn("trade like people", html)                                       # правило відбору на сторінці
            self.assertIn("wallets checked for " + self.month["label"], html)
            self.assertIn("100% win rate · 1W 0L", html)
            self.assertIn('data-p="M" class="on">' + self.month["label"][:3], html)          # картка відкривається на місяці списку
            self.assertIn("Next list", html)
            self.assertIn('data-follow="top-traders"', html)
            self.assertIsNone(CYRILLIC.search(html))
            for gone in ("nope", "kols-30d", "top-traders-30d"):
                self.assertEqual((await self.client.get("/lists/" + gone, headers=GUEST)).status, 404)

        async def test_follow_takes_a_copy_of_the_list_with_its_bells_once(self):
            await self.refresh()
            r = await self.client.post("/me/ready/follow", json={"slug": SLUG}, headers=GUEST | self.origin)
            self.assertEqual(r.status, 401)                                                # гість спершу підключається
            r = await self.client.post("/me/ready/follow", json={"slug": SLUG})
            self.assertEqual(r.status, 403)                                                # лише з цього сайту
            r = await self.client.post("/me/ready/follow", json={"slug": SLUG}, headers=self.origin)
            d = await r.json()
            self.assertEqual(r.status, 200, d)
            name = "Top traders · " + self.month["label"]
            self.assertEqual((d["name"], d["added"], d["alerts_on"], d["cap"], d["alerts_ok"], d["telegram"]), (name, 10, 10, 20, True, False))
            a = self.app["accounts"].load(TEST_PK)
            self.assertEqual(a["lists"][d["list"]]["name"], name)
            rows = self.app["ready"]["lists"][SLUG]["rows"]
            self.assertTrue(all(d["list"] in a["wallets"][x["wallet"]]["lists"] and a["wallets"][x["wallet"]]["alert"] for x in rows))
            again = await (await self.client.post("/me/ready/follow", json={"slug": SLUG}, headers=self.origin)).json()
            self.assertEqual((again["list"], again["added"]), (d["list"], 0))              # той самий список, без дублів
            html = await (await self.client.get("/lists/top-traders")).text()
            self.assertIn("In your watchlist", html)
            self.assertNotIn('data-follow="top-traders"', html)
            r = await self.client.post("/me/ready/follow", json={"slug": "nope"}, headers=self.origin)
            self.assertEqual(r.status, 404)
            self.assertIn("list_follow", [e["event"] for e in self.app["events"].tail(10)])
            # наступного місяця — новий список з новою назвою; узятий раніше лишається як був (копія)
            self.app["ready"]["lists"][SLUG]["month"], self.app["ready"]["tried_at"] = "2000-01", 0
            self.app["ready"]["lists"][SLUG]["title"] = "Top traders · Old"
            await self.refresh()
            a = self.app["accounts"].load(TEST_PK)
            self.assertEqual(sorted(w for w, m in a["wallets"].items() if d["list"] in m["lists"]), sorted(x["wallet"] for x in rows))

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

        async def test_a_listed_wallets_card_opens_without_a_watchlist(self):
            await self.refresh()
            w = self.app["ready"]["lists"][SLUG]["rows"][0]["wallet"]
            before = self.st.requests
            r = await self.client.get(f"/wallet_profile.json?wallet={w}", headers=GUEST)
            self.assertEqual(r.status, 200)                                                # список уже порахував картку: і гостю
            self.assertEqual(self.st.requests, before)                                     # з кешу, 0 запитів
            from tracced.early import profile as profile_mod
            self.app["profile_cache"].put(f"v{profile_mod.VERSION}:{w}", None)
            r = await self.client.get(f"/wallet_profile.json?wallet={w}", headers=GUEST)
            self.assertEqual(r.status, 401)                                                # новий профіль — лише з гаманцем
            self.client.session.headers["Cookie"] = wallet_cookie(OTHER)
            r = await self.client.get(f"/wallet_profile.json?wallet={w}")
            self.assertEqual(r.status, 200, await r.text())                                # не у вотчлісті — і все одно відкривається
            stranger = acct_mod.b58encode(b"\x0b" * 32)
            r = await self.client.get(f"/wallet_profile.json?wallet={stranger}")
            self.assertEqual(r.status, 404)                                                # чужа адреса — ні


if __name__ == "__main__":
    unittest.main()
