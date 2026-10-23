"""Telegram /early (20.10): the command, the pump window, the answer's text and buttons; then the bot's flow on a fake
Telegram and a fake data provider — an analysed token answers for free, a new one counts against the chat and the day,
one button opens the whole analysis."""
import asyncio
import json
import re
import tempfile
import time
import unittest

from tracced.web import tgbot

MINT = "So1aNaTokenMint1111111111111111111111pump"
T = 1_790_000_000_000
MIN, HOUR = 60_000, 3_600_000


def candles(closes, start=T):
    return [{"time": start + i * MIN, "close": c, "high": c * 1.01} for i, c in enumerate(closes)]


def row(wallet, realized, **kw):
    r = {"wallet": wallet, "realized_usd": realized, "entry_range_mcap": 20_000, "exit_mcap_avg": 400_000,
         "sold_share_pct": 100.0, "multiple": 3.0, "tag_list": []}
    r.update(kw)
    return r


class TestParse(unittest.TestCase):
    def test_the_command_in_every_form(self):
        self.assertEqual(tgbot.parse_early(f"/early {MINT}", "tracced_bot"), MINT)
        self.assertEqual(tgbot.parse_early(f"/early@tracced_bot  {MINT} please", "tracced_bot"), MINT)
        self.assertEqual(tgbot.parse_early(f"/EARLY@Tracced_Bot {MINT}", "tracced_bot"), MINT)
        self.assertEqual(tgbot.parse_early(f"/early\n{MINT}", "tracced_bot"), MINT)            # pasted on a new line
        self.assertIsNone(tgbot.parse_early(f"/early@other_bot {MINT}", "tracced_bot"))     # another bot's command
        self.assertEqual(tgbot.parse_early("/early", "tracced_bot"), "")                      # → how to use it
        self.assertEqual(tgbot.parse_early("/early not-an-address", "tracced_bot"), "")
        self.assertEqual(tgbot.parse_early("/early 0OIl" + "1" * 36, "tracced_bot"), "")       # not base58

    def test_a_bare_address_only_in_a_private_chat(self):
        self.assertEqual(tgbot.parse_early(MINT, "tracced_bot", private=True), MINT)
        self.assertIsNone(tgbot.parse_early(MINT, "tracced_bot", private=False))              # groups paste for other bots
        for text in ("/start", "/start abc", "hello", "", None, "/stop"):
            self.assertIsNone(tgbot.parse_early(text, "tracced_bot", private=True))


def series(*legs, start=T, step=MIN):
    """[(t, cap)]: each leg is (cap, minutes) — that cap held for that many minutes."""
    out, t = [], start
    for cap, n in legs:
        for _ in range(n):
            out.append((t, cap))
            t += step
    return out


class TestPumpWindow(unittest.TestCase):
    """Owner, 21.10: after the migration only; the window is the trading range right before the breakout."""

    def test_the_range_before_the_breakout(self):
        pts = series((300_000, 20), (100_000, 30), (120_000, 10), (400_000, 30))   # a drop, a range, a breakout
        (p,) = tgbot.pumps(pts)
        self.assertEqual((p["start"], p["end"]), (T + 20 * MIN, T + 60 * MIN))       # from where the range began
        self.assertEqual((p["low"], p["top"], p["gain"]), (100_000, 400_000, 300_000))

    def test_the_range_is_at_most_an_hour(self):
        (p,) = tgbot.pumps(series((100_000, 180), (300_000, 20)))
        self.assertEqual((p["start"], p["end"]), (T + 120 * MIN, T + 180 * MIN))

    def test_a_bounce_inside_an_old_range_is_not_a_pump(self):
        # LILLY, 21.10: launched at $566K, two days between $200K and $550K; a 2x bounce under the old high is no pump
        lilly = series((566_000, 10), (260_000, 60), (540_000, 30))
        self.assertEqual(tgbot.pumps(lilly), [])
        (p,) = tgbot.pumps(series((300_000, 10), (260_000, 60), (540_000, 30)))          # 2x to a new high is one
        self.assertEqual(p["top"], 540_000)
        (p,) = tgbot.pumps(series((900_000, 10), (100_000, 60), (320_000, 30)))          # 3x is one even under the old high
        self.assertEqual(p["top"], 320_000)

    def test_no_pump_without_doubling_or_after_falling_out_of_the_range(self):
        self.assertEqual(tgbot.pumps(series((100_000, 30), (180_000, 30))), [])        # +80%: not a pump
        self.assertEqual(tgbot.pumps(series((100_000, 30), (160_000, 2), (90_000, 5), (250_000, 5))), [])   # broke down first
        self.assertEqual(tgbot.pumps(series((100_000, 5), (400_000, 10))), [])         # no range to speak of (under 8 min)

    def test_the_biggest_pump_in_dollars(self):
        pts = series((20_000, 30), (100_000, 240), (120_000, 30), (350_000, 30))    # a launch spike, hours later the pump
        launch, later = tgbot.pumps(pts)
        self.assertGreater(launch["top"] / launch["low"], later["top"] / later["low"])   # ×5 against ×3.5 ...
        self.assertIs(tgbot.pick([launch, later]), later)                           # ... but +$250K against +$80K
        self.assertIsNone(tgbot.pick([]))

    def test_a_slow_pump_days_later_wins_over_the_launch(self):
        # Macca, 21.10: a launch pump that fell back, a day in a range, then a climb over hours to a new high
        five = 5 * MIN
        climb = [(36_000, 12), (43_000, 12), (52_000, 12), (62_000, 12), (75_000, 12), (90_000, 12), (108_000, 12),
                 (130_000, 24)]                                                       # +20% an hour: no fast breakout
        pts = [(t, c, c) for t, c in series((20_000, 6), (100_000, 60), (28_000, 60), (30_000, 288), *climb, step=five)]
        self.assertEqual(tgbot.pick(tgbot.pumps(pts))["end"], T + 6 * five)          # 5-minute candles see the launch only
        slow = tgbot.choose(pts)
        self.assertTrue(slow.get("slow"))
        self.assertEqual(slow["end"], T + (6 + 60 + 60 + 288) * five)                 # where the climb began
        self.assertEqual(slow["end"] - slow["start"], tgbot.SLOW_WINDOW)              # three hours of the range before it
        held = [(t, c, c) for t, c in series((20_000, 6), (100_000, 60), (95_000, 348), *climb, step=five)]
        self.assertFalse(tgbot.choose(held).get("slow"))                              # stayed above the launch breakout: same run

    def test_minute_candles_refine_the_bounds(self):
        coarse = {"start": T, "end": T + 60 * MIN, "low": 1, "top": 4, "gain": 3}
        fine = series((100_000, 46), (120_000, 12), (400_000, 20), start=T + 5 * MIN)
        self.assertEqual(tgbot.refine(coarse, fine)["end"], T + 63 * MIN)
        self.assertIs(tgbot.refine(coarse, series((100_000, 90))), coarse)

    def test_where_a_window_may_start(self):
        self.assertEqual(tgbot.launch_state({"migration": {"ms": T}, "launchpad": "pump.fun"}), ("migrated", T))
        on_curve = {"launchpad": "https://pump.fun", "pools": [{"market": "pumpfun", "curve": 64.0}], "created_time": T}
        self.assertEqual(tgbot.launch_state(on_curve), ("curve", None))
        dex = {"launchpad": None, "pools": [{"market": "raydium-cpmm", "curve": None}], "created_time": T}
        self.assertEqual(tgbot.launch_state(dex), ("dex", T))


class TestText(unittest.TestCase):
    def test_top_wallets_profitable_only_most_first(self):
        rows = [row("L", -50), row("A", 100), row("B", 900), row("Z", 0)] + [row(f"W{i}", 10 + i) for i in range(6)]
        self.assertEqual([r["wallet"] for r in tgbot.top_rows(rows)], ["B", "A", "W5", "W4", "W3"])
        self.assertEqual(tgbot.top_rows([row("L", -5)]), [])

    def test_no_junk_in_the_top(self):
        # owner, 20.10: «чи відфільтровується сміття?» — TOWER's top was +$9…$168 at 1.04–1.23x
        rows = [row("SMALL", 168, multiple=1.23), row("TINY", 60, multiple=4.0), row("GOOD", 900, multiple=2.5),
                row("BOT", 5000, tag_list=["bot-like"]), row("DEV", 4000, tag_list=["dev"]), row("CREATOR", 3000),
                row("LB", 2000, tag_list=["launch-bundle"]), row("OB", 1500, tag_list=["own-bundle"]),
                row("SNIPER", 700, tag_list=["sniper"])]
        top = tgbot.top_rows(rows, min_profit=250, min_mult=2, creator="CREATOR")
        self.assertEqual([r["wallet"] for r in top], ["GOOD", "SNIPER"])         # a sniper stays, tagged
        text = tgbot.early_text("TOWER", MINT, T, T + 25 * MIN, rows[:2], {}, {}, min_profit=250, min_mult=2)
        self.assertIn("2 early wallets, none 2x+ and $250+ profit.", text)

    def test_short_addresses_and_round_money(self):
        self.assertEqual(tgbot.short("5sQ7soAbCdEfGhJkx9sv"), "5sQ…9sv")              # owner, 20.10: three and three
        self.assertEqual([tgbot.money(v) for v in (618_600, 9_540, 37.4, 1_230_000, -2_000, 100_000)],
                         ["$619K", "$9.5K", "$37", "$1.2M", "-$2K", "$100K"])

    def test_a_wallet_says_what_it_put_in_and_took_out(self):
        w = "CE44oKS3wpUerx8afyeii56u5oQjBLZknzm4Q2CYHUz9"
        line = tgbot.wallet_line(row(w, 22_600, entry_mcap_avg=4_400, exit_mcap_avg=382_000, sold_share_pct=76.0,
                                     invested_usd=400, proceeds_usd=23_000, tag_list=["sniper", "my-own"]),
                                 {w: {"name": "<b>x</b>", "twitter": "ape"}})
        head, words = line.split("\n")
        self.assertIn(f'<a href="https://solscan.io/account/{w}">CE4…Uz9</a>', head)
        self.assertIn('<a href="https://x.com/ape">@ape</a>', head)       # X handle first, linked to X, not Telegram
        self.assertIn("sniper", head)
        self.assertNotIn("my-own", line)                                  # a person's own tags stay theirs
        self.assertEqual(words, "bought $400 at $4.4K mc, sold $23K at $382K mc (<b>×86.8</b>), holds 24%")
        held = tgbot.wallet_line(row(w, 5, entry_mcap_avg=20_000, exit_mcap_avg=None, invested_usd=300), {w: {"name": "<script>"}})
        self.assertIn("&lt;script&gt;", held)
        self.assertTrue(held.endswith("bought $300 at $20K mc, holds all"))
        self.assertNotIn("×", held)                                       # no exit, no x
        all_out = tgbot.wallet_line(row(w, 5, entry_mcap_avg=105_000, exit_mcap_avg=304_500, sold_share_pct=100.0,
                                        invested_usd=400, proceeds_usd=1_160), {})
        self.assertTrue(all_out.endswith("bought $400 at $105K mc, sold $1.2K at $304K mc (<b>×2.9</b>)"))
        line = tgbot.wallet_line(row(w, 5), {w: {"name": "@Dior100x", "twitter": "not a handle!"}})
        self.assertNotIn("@", line)                                       # a bare @word would open a Telegram stranger

    def test_launch_facts_only_with_proof_never_clean(self):
        self.assertEqual(tgbot.launch_lines({}), ["Launch check: running…"])
        self.assertEqual(tgbot.launch_lines({}, waiting=False), [])         # not run for an old analysis: no line
        self.assertIn("did not finish", tgbot.launch_lines({"launch": {"failed": "429"}})[0])
        found = {"launch": {"launch": {"bundle": "b0", "wallets": ["X", "Y"]},
                            "pairs": [{"bundle": f"b{i}", "seller": "S", "buyers": [["B", 1]]} for i in range(1, 5)],
                            "fee": {"to": [["FeeTaker111", 10000]], "paid": {"sol": 174.021}}, "sells": 113, "checked": 113}}
        lines = tgbot.launch_lines(found, creator="Creator")
        text = "\n".join(lines)
        self.assertEqual(len(lines), 4)
        self.assertIn("one bundle with 2 wallets", text)
        self.assertIn("explorer.jito.wtf/bundle/b0", text)
        self.assertIn("4 early sales bought back", text)
        self.assertIn("explorer.jito.wtf/bundle/b1", text)
        self.assertIn("Fee…111", text)
        self.assertIn("174.021 SOL", text)
        own_fee = {"launch": {"pairs": [], "launch": None, "fee": {"to": [["Creator", 10000]]}, "sells": 48, "checked": 48}}
        self.assertEqual(tgbot.launch_lines(own_fee, creator="Creator"), ["Launch: nothing organised found · 48 early sales checked"])
        self.assertEqual(tgbot.launch_lines({"launch": {"pairs": [], "sells": 0}}), ["Launch: nothing organised found"])
        self.assertEqual(tgbot.launch_lines({"launch": {"no_tx": True, "pairs": []}}), [])
        for r in ({}, found, own_fee):
            self.assertNotIn("clean", " ".join(tgbot.launch_lines(r)).lower())

    def test_the_whole_answer_is_short_and_fits_telegram(self):
        rows = [row("W" * 44, 10 ** 6, tag_list=list(tgbot.SHOWN_TAGS)) for _ in range(6)]
        names = {"W" * 44: {"name": "<" * 200}}
        text = tgbot.early_text("<SYM>" * 10, MINT, T, T + 16 * MIN, rows, names, {})
        self.assertLessEqual(len(text), 4000)
        self.assertIn("$&lt;SYM&gt;", text)
        self.assertNotIn(MINT, text)                                       # the token's address: the person just sent it
        self.assertIn("pump " + tgbot.span(T, T + 16 * MIN) + " UTC", text)
        self.assertNotIn("early wallets", text)                            # no «5 of 6» line: the wallets speak
        tower = [row(f"{c}" * 44, p) for c, p in zip("ABCDE", (168, 37, 22, 12, 9))] + [row(f"Z{i}" * 22, -1) for i in range(13)]
        shown = re.sub(r"<[^>]+>", "", tgbot.early_text("TOWER", MINT, T, T + 25 * MIN, tower, {}, {"launch": {"pairs": [], "sells": 0}}))
        self.assertLess(len(shown), 600)                                   # two lines a wallet, in words (owner, 23.10)
        empty = tgbot.early_text("TST", MINT, T, T + 30 * MIN, [row("L", -1)], {}, {})
        self.assertIn("1 early wallet, none in profit.", empty)

    def test_span_shows_the_date_again_past_midnight(self):
        a = 1_790_035_200_000 - 10 * MIN                                 # 23:50 UTC
        self.assertNotIn(" ", tgbot.span(a, a + 5 * MIN).split("–")[1])
        self.assertIn(" ", tgbot.span(a, a + 20 * MIN).split("–")[1])

    def test_one_button_the_whole_analysis(self):
        kb = tgbot.keyboard("2bCCHQ_20261015-2016_2050", "https://tracced.xyz")["inline_keyboard"]
        self.assertEqual(kb, [[{"text": "Open on tracced", "url": "https://tracced.xyz/job/2bCCHQ_20261015-2016_2050"}]])


class TestChatUsage(unittest.TestCase):
    def test_each_chat_its_asks_and_what_its_analyses_cost(self):
        from tracced.web import usage
        now = T + 5 * HOUR
        g = {"tg_chat": -100, "tg_kind": "group", "tg_name": "Pump club"}
        p = {"tg_chat": 555, "tg_kind": "private", "tg_name": "@ape"}
        ev = [dict(g, ts_ms=T, pubkey="system", event="spend", what="overview", st=2),
              dict(g, ts_ms=T, pubkey="system", event="spend", what="tg-window", st=1),
              dict(g, ts_ms=T, pubkey="system", event="analyze", job="J1", via="tg"),
              dict(g, ts_ms=T, pubkey="system", event="tg_early", job="J1", new=1),
              {"ts_ms": T + MIN, "pubkey": "system", "event": "run", "job": "J1", "st": 480},
              {"ts_ms": T + 2 * MIN, "pubkey": "system", "event": "spend", "what": "names", "job": "J1", "st": 3},
              {"ts_ms": T + 3 * MIN, "pubkey": "system", "event": "spend", "what": "enrich", "job": "J1", "rpc": 900},
              {"ts_ms": T + 4 * MIN, "pubkey": "Wallet1", "event": "run", "job": "J1", "st": 50},   # someone re-ran it on the site
              dict(p, ts_ms=T + HOUR, pubkey="system", event="tg_early", job="J1", new=0),
              dict(p, ts_ms=T + 2 * HOUR, pubkey="system", event="tg_early", mint="M", refused="limit")]
        u = usage.tg_usage(ev, now)
        club, ape = u["chats"]
        self.assertEqual((club["name"], club["asks"], club["new"], club["st"], club["rpc"]), ("Pump club", 1, 1, 486, 900))
        self.assertEqual((ape["name"], ape["kind"], ape["asks"], ape["refused"], ape["st"]), ("@ape", "private", 2, 1, 0))
        self.assertEqual((u["total"]["asks"], u["total"]["chats"], u["total"]["groups"], u["total"]["st"]), (3, 2, 1, 486))
        self.assertEqual(u["recent"][0]["refused"], "limit")


try:
    from aiohttp.test_utils import AioHTTPTestCase
except ImportError:
    AioHTTPTestCase = None

if AioHTTPTestCase:
    from unittest import mock

    from tracced.early import settings
    from tracced.web import app as app_mod
    from tracced.web.app import create_app, tg_reply
    try:
        from tests.test_early_pipeline import TRADES
        from tests.test_web import FakeWebST, TEST_PK, W1, OTHER_MINT, OTHER_JID, DEMO_A, DEMO_B, _result, _job_file, wallet_cookie
    except ImportError:
        from test_early_pipeline import TRADES
        from test_web import FakeWebST, TEST_PK, W1, OTHER_MINT, OTHER_JID, DEMO_A, DEMO_B, _result, _job_file, wallet_cookie

    class FakeTelegram:
        def __init__(self):
            self.calls = []

        async def __call__(self, http, token, method, **params):
            self.calls.append((method, params))
            return {"message_id": 77} if method == "sendMessage" else True

        def of(self, method):
            return [p for m, p in self.calls if m == method]

    class TestBotFlow(AioHTTPTestCase):
        async def get_application(self):
            self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
            self.st = FakeWebST(TRADES)
            app = create_app(self.st, settings.load(), {}, out_dir=self.tmp.name + "/web", store_dir=self.tmp.name + "/cache")
            app["admins"] = {TEST_PK}
            app["tg"].update(token="test-token", name="tracced_bot", on=True, checked=True)
            return app

        async def tearDownAsync(self):
            await asyncio.to_thread(self.app["jobs"].q.join)
            await self.client.close()
            self.tmp.cleanup()

        def seed(self):
            _job_file(self.tmp.name + "/web", OTHER_JID, OTHER_MINT, DEMO_A, DEMO_B, _result(OTHER_MINT, DEMO_A, DEMO_B, W1))
            self.app["jobs"]._load()

        def msg(self, text, chat=-100, kind="group"):
            return {"message_id": 5, "chat": {"id": chat, "type": kind}, "from": {"id": 555}, "text": text}

        async def test_start_without_a_code_says_what_the_bot_does(self):
            upd = {"update_id": 1, "message": {"chat": {"id": 9, "type": "private"}, "text": "/start"}}
            text = tg_reply(self.app, upd)[1]
            self.assertIn("/early", text)
            self.assertNotIn("expired", text)

        async def test_an_analysed_token_answers_for_free(self):
            self.seed()
            self.app["s"]["tg_top_min_profit_usd"] = 50                        # the seeded wallet made $100 at 3x
            tg, before = FakeTelegram(), self.st.requests
            with mock.patch.object(app_mod, "_tg_call", tg):
                await app_mod._tg_early(self.app, None, self.msg(f"/early {OTHER_MINT}"), OTHER_MINT)
            self.assertEqual(self.st.requests, before)                         # nothing bought
            self.assertEqual(tg.of("sendMessage")[0]["reply_parameters"]["message_id"], 5)
            last = tg.of("editMessageText")[-1]
            self.assertIn("$TST", last["text"])
            self.assertIn(W1[:3] + "…" + W1[-3:], last["text"])
            self.assertNotIn("Launch check", last["text"])                     # an old result: no launch check is coming
            self.assertEqual(last["reply_markup"]["inline_keyboard"][0][0]["url"], "https://tracced.xyz/job/" + OTHER_JID)
            self.assertEqual(self.app["runs_daily"].left("tg:-100", 5), 5)     # a ready answer takes no new analysis
            self.assertEqual(self.app["tg_pending"], {})                       # nothing left to update after a restart

        async def test_a_new_token_starts_one_analysis_within_the_chats_cap(self):
            tg = FakeTelegram()
            self.app["s"]["tg_runs_per_chat"] = 1
            mint2 = "C" * 40
            with mock.patch.object(app_mod, "_tg_call", tg), mock.patch.object(app_mod, "_tg_watch", mock.AsyncMock()) as watch:
                await app_mod._tg_early(self.app, None, self.msg(f"/early {mint2}"), mint2)
                entry = watch.call_args[0][2]
                job = self.app["jobs"].get(entry["job"])
                self.assertEqual((job.mint, job.owner), (mint2, "system"))
                self.assertEqual(job.s_over["run_cap_requests"], 1500)
                # the fake's chart: a flat 40 min from creation (no curve: launched on a DEX), then the breakout at
                # minute 41; bounds in whole minutes
                created = FakeWebST(TRADES).token_info(mint2)["created_time"]
                self.assertEqual((job.t_from, job.t_to), (created // MIN * MIN, -(-(created + 41 * MIN) // MIN) * MIN))
                await asyncio.to_thread(self.app["jobs"].q.join)
                await app_mod._tg_early(self.app, None, self.msg(f"/early {mint2}"), mint2)   # the same token: reused
                self.assertEqual(watch.call_args[0][2]["job"], job.id)                     # the rule gives the same window
                old = self.app["jobs"].submit(mint2, job.t_from - 60 * MIN, job.t_from - 30 * MIN, owner="system")
                await asyncio.to_thread(self.app["jobs"].q.join)
                await app_mod._tg_early(self.app, None, self.msg(f"/early {mint2}"), mint2)   # an old rule's window is not
                self.assertEqual(watch.call_args[0][2]["job"], job.id)                     # what the bot answers with
                self.assertNotEqual(old.id, job.id)
                mint3 = "D" * 40
                await app_mod._tg_early(self.app, None, self.msg(f"/early {mint3}"), mint3)  # the chat's cap
            self.assertIn("used its 1 new analyses", tg.of("editMessageText")[-1]["text"])
            self.assertIsNone(next((j for j in self.app["jobs"].jobs.values() if j.mint == mint3), None))
            self.assertEqual(self.app["runs_daily"].left("tg:global", 20), 19)
            self.app["accounts"].set_telegram(TEST_PK, 555, "@owner")                  # the owner's Telegram: no daily caps
            with mock.patch.object(app_mod, "_tg_call", tg), mock.patch.object(app_mod, "_tg_watch", mock.AsyncMock()) as watch:
                await app_mod._tg_early(self.app, None, self.msg(f"/early {mint3}"), mint3)
            self.assertEqual(self.app["jobs"].get(watch.call_args[0][2]["job"]).mint, mint3)
            self.assertEqual(self.app["runs_daily"].left("tg:global", 20), 19)              # and it takes none of the day
            await asyncio.to_thread(self.app["jobs"].q.join)

        async def test_each_chat_is_recorded_and_the_owner_sees_it(self):
            self.seed()
            tg = FakeTelegram()
            group = {"message_id": 5, "chat": {"id": -100, "type": "supergroup", "title": "Pump club"}, "text": "x"}
            private = {"message_id": 6, "chat": {"id": 555, "type": "private", "username": "ape", "first_name": "A"}, "text": "x"}
            self.app["s"]["tg_early_on"] = False                                  # a new token is refused, a ready one answers
            with mock.patch.object(app_mod, "_tg_call", tg):
                await app_mod._tg_early(self.app, None, group, OTHER_MINT)
                await app_mod._tg_early(self.app, None, private, OTHER_MINT)
                await app_mod._tg_early(self.app, None, private, "E" * 40)
            asks = [e for e in self.app["events"].read(0) if e.get("event") == "tg_early"]
            self.assertEqual([(e["tg_name"], e["tg_kind"], e.get("new"), bool(e.get("refused"))) for e in asks],
                             [("Pump club", "group", 0, False), ("@ape", "private", 0, False), ("@ape", "private", None, True)])
            r = await self.client.get("/admin?tab=tg", headers={"Cookie": wallet_cookie(TEST_PK)})
            html = await r.text()
            self.assertEqual(r.status, 200, html[:300])
            for want in ("Pump club", "@ape", "refused: New analyses from Telegram", "chats · 1 group<"):
                self.assertIn(want, html)
            r = await self.client.get("/admin?tab=tg", headers={"Cookie": wallet_cookie(W1)})
            self.assertEqual(r.status, 403)                                      # the owner's page only

        async def test_a_token_still_on_the_curve_is_not_analysed(self):
            tg, mint5 = FakeTelegram(), "G" * 40
            real = self.app["st"].token_info

            def on_curve(mint):
                return dict(real(mint), launchpad="https://pump.fun", pools=[{"market": "pumpfun", "curve": 40.0}])
            with mock.patch.object(self.app["st"], "token_info", on_curve), mock.patch.object(app_mod, "_tg_call", tg):
                await app_mod._tg_early(self.app, None, self.msg(f"/early {mint5}"), mint5)
            self.assertIn("still on pump.fun's curve", tg.of("editMessageText")[-1]["text"])
            self.assertIsNone(next((j for j in self.app["jobs"].jobs.values() if j.mint == mint5), None))

        async def test_the_answer_survives_a_restart(self):
            self.seed()
            entry = {"chat": -100, "mid": 77, "job": OTHER_JID, "at": 0}
            app_mod._tg_pending_set(self.app, "-100:77", entry)
            saved = json.load(open(self.app["tg_pending_file"]))
            self.assertEqual(saved["-100:77"]["job"], OTHER_JID)
            tg = FakeTelegram()
            with mock.patch.object(app_mod, "_tg_call", tg):
                await app_mod._tg_watch(self.app, None, dict(entry, at=time.time()))
            self.assertIn("$TST", tg.of("editMessageText")[-1]["text"])
            self.assertEqual(json.load(open(self.app["tg_pending_file"])), {})


if __name__ == "__main__":
    unittest.main()
