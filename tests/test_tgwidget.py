"""Telegram widgets (/prism, 09.11): the owner's hidden command, the cards under Telegram's limits, the chart's even
grid that turns a tap into a time, the requests a card sends; then the bot's flow on a fake Telegram — only the owner
gets cards, a tap follows a wallet or analyses a marked range, everyone else sees the bot as before."""
import asyncio
import json
import tempfile
import time
import unittest

from tracced.web import tgbot, tgwidget

MINT = "So1aNaTokenMint1111111111111111111111pump"
W = "9yYya3F5EJoLnBNKW6z4bZvyQytMXzDcpU5D6yYr4jqL"
MIN = 60_000
T = 1_790_000_000_000 // MIN * MIN            # a whole minute, as analysis windows are


def row(wallet, realized, **kw):
    r = {"wallet": wallet, "realized_usd": realized, "entry_range_mcap": 20_000, "exit_mcap_avg": 400_000,
         "sold_share_pct": 100.0, "multiple": 3.0, "tag_list": ["fresh"], "invested_usd": 1000.0,
         "proceeds_usd": 1000.0 + realized, "buys": 3, "sells": 2, "first_buy_ms": T}
    r.update(kw)
    return r


class TestParse(unittest.TestCase):
    def test_the_hidden_command(self):
        self.assertEqual(tgbot.parse_prism("/prism", "tracced_bot"), "")
        self.assertEqual(tgbot.parse_prism(f"/prism {MINT}", "tracced_bot"), MINT)
        self.assertEqual(tgbot.parse_prism(f"/prism@tracced_bot {MINT}", "tracced_bot"), MINT)
        self.assertIsNone(tgbot.parse_prism(f"/prism@other_bot {MINT}", "tracced_bot"))
        self.assertIsNone(tgbot.parse_prism("/prism not-an-address", "tracced_bot"))
        self.assertIsNone(tgbot.parse_prism(f"/early {MINT}", "tracced_bot"))
        self.assertNotIn("prism", json.dumps(tgbot.COMMANDS))                  # never in the bot's menu

    def test_what_a_card_may_ask(self):
        self.assertEqual(tgwidget.parse_query("s"), ("stats",))
        self.assertEqual(tgwidget.parse_query("f:" + W), ("follow", W))
        a, b = T // MIN, T // MIN + 30
        self.assertEqual(tgwidget.parse_query(f"r:{MINT}:{tgwidget_b36(a)}:{tgwidget_b36(b)}"), ("range", MINT, a * MIN, b * MIN))
        self.assertLessEqual(len(f"r:{MINT}:{tgwidget_b36(a)}:{tgwidget_b36(b)}".encode()), 64)   # Telegram's 64 bytes
        for bad in ("", "f:nope", f"r:{MINT}:zz:1", f"r:{MINT}:x!:y", "follow"):
            self.assertIsNone(tgwidget.parse_query(bad), bad)


def tgwidget_b36(n):
    s = ""
    while n:
        n, d = divmod(n, 36)
        s = "0123456789abcdefghijklmnopqrstuvwxyz"[d] + s
    return s or "0"


class TestCards(unittest.TestCase):
    def test_the_chart_is_an_even_grid_of_candles(self):
        raw = [{"time": T + i * MIN, "open": 1 + i, "high": 2 + i, "low": 0.5 + i, "close": 1.5 + i} for i in range(10)]
        c, t0, dt, lo, hi = tgwidget.candles(raw, 1000, T, T + 10 * MIN, n=5)
        self.assertEqual((t0, dt, len(c)), (T // MIN, 2, 5 * 8))              # two minutes a candle
        dec = lambda k: tgwidget.B64.index(c[k]) * 64 + tgwidget.B64.index(c[k + 1])
        o, h, l, cl = (dec(k) for k in (0, 2, 4, 6))
        self.assertLess(o, cl)                                                 # it rose: 1 → 2.5
        self.assertGreaterEqual(h, cl)
        self.assertLessEqual(l, o)
        c2, *_ = tgwidget.candles(raw[:2], 1000, T, T + 10 * MIN, n=5)         # no trades later: the last close repeats
        self.assertEqual(c2[16:24], c2[24:32])
        self.assertEqual(tgwidget.candles([], 1000, T, T + MIN)[0], "")

    def test_a_broken_wick_does_not_flatten_the_chart(self):
        raw = [{"time": T + i * MIN, "open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1} for i in range(10)]
        raw[4]["low"] = 1e-9                                                    # a source's shifted decimal
        raw[6]["close"] = 1e-6                                                  # and a whole candle off by decimals
        _, _, _, lo, hi = tgwidget.candles(raw, 1000, T, T + 10 * MIN, n=10)
        self.assertGreater(lo, 800)                                             # the scale follows opens and closes
        _, t0, *_ = tgwidget.candles(raw, 1000, T - 60 * MIN, T + 10 * MIN, n=10)
        self.assertEqual(t0, T // MIN)                                          # nothing to draw before the first trade

    def test_the_card_fits_telegrams_limits(self):
        rows = [row(W[:-1] + str(i), 10_000 * (i + 1), tag_list=["bundle", "sniper", "fresh"]) for i in range(9)]
        names = {r["wallet"]: {"twitter": "a_long_handle_x"} for r in rows}
        cs = [{"time": T + i * MIN, "open": 1 + (i % 17) / 3, "high": 2 + (i % 13) / 3, "low": 0.5 + (i % 7) / 9,
                "close": 1 + (i % 11) / 3} for i in range(400)]
        page = tgwidget.early_card("SYMBOLSYMBOLSYM", MINT, T + 60 * MIN, T + 90 * MIN, rows, names, {}, cs, 1e9, "job1",
                                   "https://tracced.xyz", around=(T, T + 400 * MIN))
        raw, z = tgwidget.sizes(page)
        self.assertTrue(tgwidget.fits(page), (raw, z))
        self.assertLess(z, tgwidget.MAX_Z - 400)                              # room for a longer launch section
        d = json.loads(page.split("id=d>")[1].split("</script>")[0])
        self.assertEqual(len(d["r"]), tgbot.TOP)                              # the same five as the text answer
        self.assertEqual((d["a"], d["b"], d["m"]), (60 // d["dt"], (90 * MIN - 1) // MIN // d["dt"], MINT))
        self.assertEqual(len(d["c"]), tgwidget.CANDLES * 8)
        self.assertTrue(tgwidget.fits(tgwidget.panel_card(None)))
        busy = {"launch": {"launch": {"wallets": [W] * 40, "bundle": "b" * 88},
                           "pairs": [{"bundle": "c" * 88}] * 30, "fee": {"to": [[W]], "paid": {"sol": 12.5}}}}
        noisy = [dict(x, open=x["open"] * (1 + i % 5 / 7), close=x["close"] * (1 + i % 3 / 5)) for i, x in enumerate(cs)]
        page = tgwidget.early_card("SYM", MINT, T + 60 * MIN, T + 90 * MIN, rows, names, busy, noisy, 1e9, "job1",
                                   "https://tracced.xyz", around=(T, T + 400 * MIN))
        self.assertTrue(tgwidget.fits(page), tgwidget.sizes(page))                # fewer candles before a missing card

    def test_a_wallets_trades_are_markers_on_the_chart(self):
        dec = lambda s: [((tgwidget.B64.index(s[j]) * 64 + tgwidget.B64.index(s[j + 1])) >> 1,
                          (tgwidget.B64.index(s[j]) * 64 + tgwidget.B64.index(s[j + 1])) & 1, tgwidget.B64.index(s[j + 2]))
                         for j in range(0, len(s), 3)]
        trades = [[T + 30_000, "buy", 1, 100, 1.0], [T + 40_000, "buy", 1, 300, 2.0],   # one candle, one side: one marker
                  [T + 3 * MIN, "sell", 1, 500, 3.0], [T + 3 * MIN, "transfer", 1, 9, 3.0],
                  [T + 99 * MIN, "sell", 1, 900, 3.0], [T - MIN, "buy", 1, 50, 1.0]]   # outside the chart: not drawn
        got = dec(tgwidget.marks(trades, 1000, T // MIN, 1, 10, 0, 3000))
        self.assertEqual([(x, s) for x, s, _ in got], [(0, 0), (3, 1)])
        self.assertEqual(got[0][2], round(1750 / 3000 * 63))                     # the dollar-weighted cap: $1.75K
        self.assertEqual(got[1][2], 63)
        many = [[T + i * MIN, "sell", 1, i + 1, 1.0] for i in range(40)]
        kept = dec(tgwidget.marks(many, 1000, T // MIN, 1, 40, 0, 3000))
        self.assertEqual([x for x, *_ in kept], list(range(26, 40)))            # the 14 biggest, in time order

    def test_the_card_shows_trades_and_how_long_it_held(self):
        rows = [row(W[:-1] + str(i), 10_000 * (i + 1), hold_minutes=95) for i in range(5)]
        wt = {r["wallet"]: {"trades": [[T + 60 * MIN + j * MIN, "buy" if j < 20 else "sell", 1, 100 + j, 1.0 + j / 9]
                                       for j in range(40)]} for r in rows}
        cs = [{"time": T + i * MIN, "open": 1 + (i % 17) / 3, "high": 2 + (i % 13) / 3, "low": 0.5 + (i % 7) / 9,
               "close": 1 + (i % 11) / 3} for i in range(400)]
        names = {r["wallet"]: {"twitter": "a_long_handle_x"} for r in rows}
        page = tgwidget.early_card("SYM", MINT, T + 60 * MIN, T + 90 * MIN, rows, names, {"wallet_trades": wt}, cs, 1e9,
                                   "job1", "https://tracced.xyz", around=(T, T + 400 * MIN))
        self.assertTrue(tgwidget.fits(page), tgwidget.sizes(page))
        d = json.loads(page.split("id=d>")[1].split("</script>")[0])
        self.assertTrue(all(6 <= len(r[11]) <= tgwidget.MARKS * 3 for r in d["r"]), [r[11] for r in d["r"]])
        self.assertEqual({r[12] for r in d["r"]}, {"2h"})
        self.assertGreater(d["lo"], 0)                                           # the label is the lowest candle, not $0

    def test_a_symbol_cannot_break_out_of_the_data(self):
        page = tgwidget.early_card('</script><script>alert(1)</script>', MINT, T, T + MIN, [], {}, {}, [], 1, "j", "https://x")
        self.assertNotIn("<script>alert", page)
        self.assertEqual(page.count("<script"), 2)

    def test_the_panel_numbers_fit_an_answer(self):
        meters = [{"key": k, "name": n, "left": 123_456_789, "of": 999_999_999, "pct": 12.3456, "level": "warn"}
                  for k, n in (("st", "Solana Tracker"), ("rpc", "Helius"), ("de", "Digital Energy"), ("ai", "AI agent"))]
        pulse = {k: 10 ** 9 for k in ("dau", "new_today", "runs_today", "runs_today_failed", "st_today", "rpc_today")}
        x = tgwidget.panel_stats(pulse, meters, 3, {"sent": 10 ** 6, "errors": 2})
        self.assertLessEqual(len(json.dumps(x, separators=(",", ":"))), 1024)
        self.assertEqual(x["m"][3][0], "AI agent $")


try:
    from aiohttp.test_utils import AioHTTPTestCase
except ImportError:
    AioHTTPTestCase = None

if AioHTTPTestCase:
    from unittest import mock

    from tracced.early import settings
    from tracced.web import app as app_mod
    from tracced.web.app import create_app
    try:
        from tests.test_early_pipeline import TRADES
        from tests.test_tgbot import FakeTelegram
        from tests.test_web import FakeWebST, TEST_PK, W1, OTHER_MINT, OTHER_JID, DEMO_A, DEMO_B, _result, _job_file
    except ImportError:
        from test_early_pipeline import TRADES
        from test_tgbot import FakeTelegram
        from test_web import FakeWebST, TEST_PK, W1, OTHER_MINT, OTHER_JID, DEMO_A, DEMO_B, _result, _job_file

    OWNER_TG = 555

    class TestPrism(AioHTTPTestCase):
        async def get_application(self):
            self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
            self.st = FakeWebST(TRADES)
            app = create_app(self.st, settings.load(), {}, out_dir=self.tmp.name + "/web", store_dir=self.tmp.name + "/cache")
            app["admins"] = {TEST_PK}
            app["tg"].update(token="test-token", name="tracced_bot", on=True, checked=True)
            app["accounts"].set_telegram(TEST_PK, OWNER_TG, "@owner")
            return app

        async def tearDownAsync(self):
            await asyncio.to_thread(self.app["jobs"].q.join)
            await self.client.close()
            self.tmp.cleanup()

        def msg(self, text, user=OWNER_TG):
            return {"message_id": 5, "chat": {"id": user, "type": "private"}, "from": {"id": user}, "text": text}

        async def test_only_the_owner_gets_cards(self):
            tg = FakeTelegram()
            with mock.patch.object(app_mod, "_tg_call", tg):
                await app_mod._tg_prism(self.app, None, self.msg("/prism", user=777), "")
                self.assertEqual(tg.of("sendWidget"), [])
                self.assertIn("/early", tg.of("sendMessage")[-1]["text"])          # the usual answer, nothing hints
                await app_mod._tg_prism(self.app, None, self.msg("/prism"), "")
            w = tg.of("sendWidget")[-1]
            self.assertEqual((w["chat_id"], w["allow_queries"]), (OWNER_TG, True))
            self.assertTrue(tgwidget.fits(w["html"]))
            self.assertIn("tracced · today", w["html"])

        async def test_the_early_card_replaces_the_text(self):
            _job_file(self.tmp.name + "/web", OTHER_JID, OTHER_MINT, DEMO_A, DEMO_B, _result(OTHER_MINT, DEMO_A, DEMO_B, W1))
            self.app["jobs"]._load()
            self.app["s"]["tg_top_min_profit_usd"] = 50
            tg = FakeTelegram()
            with mock.patch.object(app_mod, "_tg_call", tg):
                await app_mod._tg_prism(self.app, None, self.msg(f"/prism {OTHER_MINT}"), OTHER_MINT)
            w = tg.of("sendWidget")[-1]
            self.assertIn("$TST", w["html"])
            self.assertIn(W1, w["html"])                                         # the full address: Copy and Solscan
            self.assertEqual(w["reply_markup"]["inline_keyboard"][0][0]["url"], "https://tracced.xyz/job/" + OTHER_JID)
            self.assertNotIn("caption", w)                                       # no line repeating the card's title
            self.assertEqual(tg.of("deleteMessage")[-1]["message_id"], 77)      # the «Looking at…» text goes
            self.assertEqual(self.app["tg_pending"], {})

        async def test_a_tap_follows_a_wallet_for_whoever_linked_telegram(self):
            other_pk, linked, stranger = "8" * 43 + "A", 666, 777
            self.app["accounts"].set_telegram(other_pk, linked, "@someone")
            tg = FakeTelegram()
            q = {"id": "q1", "from": {"id": OWNER_TG}, "chat": {"id": OWNER_TG, "type": "private"}, "message_id": 9,
                 "data": "f:" + W1}
            with mock.patch.object(app_mod, "_tg_call", tg):
                await app_mod._tg_widget_query(self.app, None, q)
                await app_mod._tg_widget_query(self.app, None, dict(q, id="q2", **{"from": {"id": linked}}))
                await app_mod._tg_widget_query(self.app, None, dict(q, id="q3", **{"from": {"id": stranger}}))
            got = [(a["widget_query_id"], a["data"]) for a in tg.of("answerWidgetQuery")]
            self.assertEqual(got[:2], [("q1", "ok"), ("q2", "ok")])
            self.assertIn("tracced.xyz/me", got[2][1])                           # not linked: where to connect
            self.assertLess(len(got[2][1]), 30)                                  # it becomes the button's label
            self.assertIn(W1, self.app["accounts"].load(TEST_PK)["wallets"])
            self.assertIn(W1, self.app["accounts"].load(other_pk)["wallets"])

        async def test_everyone_gets_the_card_in_a_private_chat_and_text_in_a_group(self):
            self.assertTrue(app_mod._tg_wants_card(self.app, {"id": 777, "type": "private"}))
            self.assertFalse(app_mod._tg_wants_card(self.app, {"id": -100, "type": "supergroup"}))
            self.app["s"]["tg_cards"] = False
            self.assertFalse(app_mod._tg_wants_card(self.app, {"id": 777, "type": "private"}))
            self.app["s"]["tg_cards"] = True
            _job_file(self.tmp.name + "/web", OTHER_JID, OTHER_MINT, DEMO_A, DEMO_B, _result(OTHER_MINT, DEMO_A, DEMO_B, W1))
            self.app["jobs"]._load()
            self.app["s"]["tg_top_min_profit_usd"] = 50
            tg = FakeTelegram()
            with mock.patch.object(app_mod, "_tg_call", tg):                    # a stranger, not the owner
                await app_mod._tg_early(self.app, None, self.msg(f"/early {OTHER_MINT}", user=777), OTHER_MINT, widget=True)
            self.assertEqual(tg.of("sendWidget")[-1]["chat_id"], 777)

        async def test_only_the_owner_gets_the_panels_numbers(self):
            tg = FakeTelegram()
            q = {"id": "q1", "from": {"id": 777}, "chat": {"id": 777}, "message_id": 9, "data": "s"}
            with mock.patch.object(app_mod, "_tg_call", tg):
                await app_mod._tg_widget_query(self.app, None, q)
            self.assertEqual(tg.of("answerWidgetQuery")[-1]["data"], "no")

        async def test_a_marked_range_starts_its_analysis(self):
            tg, mint2 = FakeTelegram(), "C" * 40
            created = FakeWebST(TRADES).token_info(mint2)["created_time"]
            a, b = created // MIN + 5, created // MIN + 35
            q = {"id": "q1", "from": {"id": OWNER_TG}, "chat": {"id": OWNER_TG, "type": "private"}, "message_id": 9,
                 "data": f"r:{mint2}:{tgwidget_b36(a)}:{tgwidget_b36(b)}"}
            with mock.patch.object(app_mod, "_tg_call", tg), mock.patch.object(app_mod, "_tg_watch", mock.AsyncMock()) as watch:
                await app_mod._tg_widget_query(self.app, None, q)
                await asyncio.gather(*list(self.app["tg_tasks"]))
            self.assertEqual(tg.of("answerWidgetQuery")[-1]["data"], "ok")
            entry = watch.call_args[0][2]
            job = self.app["jobs"].get(entry["job"])
            self.assertEqual((job.mint, job.t_from, job.t_to, entry.get("w")), (mint2, a * MIN, b * MIN, 1))
            await asyncio.to_thread(self.app["jobs"].q.join)

        async def test_the_panel_answers_every_five_seconds(self):
            tg = FakeTelegram()
            q = {"id": "q1", "from": {"id": OWNER_TG}, "chat": {"id": OWNER_TG}, "message_id": 9, "data": "s"}
            with mock.patch.object(app_mod, "_tg_call", tg):
                await app_mod._tg_widget_query(self.app, None, q)
            d = json.loads(tg.of("answerWidgetQuery")[-1]["data"])
            self.assertEqual(set(d), {"p", "m", "j", "b", "e"})
            self.assertIn("runs_today", d["p"])


if __name__ == "__main__":
    unittest.main()
