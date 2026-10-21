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


class TestWindow(unittest.TestCase):
    def test_launch_to_the_first_3x_of_the_cap_at_ten_minutes(self):
        closes = [1.0] * 12 + [1.5, 2.0, 2.9, 3.1, 3.5]                    # 3x of +10 min is reached at minute 15 (high 2.93 < 3)
        a, b, how = tgbot.auto_window(candles(closes), T, 1_000_000, T + 6 * HOUR)
        self.assertEqual((a, b, how), (T, T + 16 * MIN, "launch → first 3x"))

    def test_no_3x_falls_back_to_the_first_half_hour(self):
        a, b, how = tgbot.auto_window(candles([1.0] * 120), T, 1_000_000, T + 6 * HOUR)
        self.assertEqual((a, b), (T, T + 30 * MIN))
        self.assertIn("no 3x", how)
        late = candles([1.0] * 11 + [1.0] * 400)                        # 3x only after six hours: not this rule's pump
        late[-1]["high"] = 10.0
        self.assertEqual(tgbot.auto_window(late, T, 1_000_000, T + 8 * HOUR)[1], T + 30 * MIN)

    def test_too_new_or_no_data(self):
        self.assertIsNone(tgbot.auto_window([], T, 1_000_000, T + MIN))     # a minute old: nothing to analyse yet
        self.assertIsNone(tgbot.auto_window(candles([1.0]), T, 0, T + HOUR))
        self.assertIsNone(tgbot.auto_window(candles([1.0]), None, 1_000_000, T + HOUR))
        self.assertEqual(tgbot.auto_window([], T, 1_000_000, T + 10 * MIN)[1], T + 10 * MIN)   # never past now

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

    def test_a_wallet_line_carries_facts_and_escapes_names(self):
        w = "CE44oKS3wpUerx8afyeii56u5oQjBLZknzm4Q2CYHUz9"
        line = tgbot.wallet_line(row(w, 22_600, entry_range_mcap=4_400, exit_mcap_avg=382_000, sold_share_pct=76.0,
                                     tag_list=["sniper", "my-own"]), {w: {"name": "<b>x</b>", "twitter": "ape"}})
        self.assertIn(f'<a href="https://solscan.io/account/{w}">CE4…Uz9</a>', line)
        self.assertNotIn(w + "<", line.replace(f'account/{w}"', ""))               # the full address only in the link
        self.assertIn("@ape", line)                                       # X handle first
        self.assertIn("$4.4K → $382K", line)
        self.assertIn("<b>+$22.6K</b>", line)
        self.assertIn("holds 24%", line)
        self.assertIn("sniper", line)
        self.assertNotIn("my-own", line)                                  # a person's own tags stay theirs
        line = tgbot.wallet_line(row(w, 5, exit_mcap_avg=None), {w: {"name": "<script>"}})
        self.assertIn("&lt;script&gt;", line)
        self.assertIn("→ holding", line)
        self.assertNotIn("holds", tgbot.wallet_line(row(w, 5, sold_share_pct=99.7), {}))

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
        self.assertIn("<b>5 of 6 early wallets</b> · in profit", text)
        tower = [row(f"{c}" * 44, p) for c, p in zip("ABCDE", (168, 37, 22, 12, 9))] + [row(f"Z{i}" * 22, -1) for i in range(13)]
        shown = re.sub(r"<[^>]+>", "", tgbot.early_text("TOWER", MINT, T, T + 25 * MIN, tower, {}, {"launch": {"pairs": [], "sells": 0}}))
        self.assertLess(len(shown), 330)                                   # what a person reads, links aside (was ~620)
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
                # the fake's chart: 1.0 for 40 min from creation, then 3x at minute 43; bounds in whole minutes
                created = FakeWebST(TRADES).token_info(mint2)["created_time"]
                self.assertEqual((job.t_from, job.t_to), (created // MIN * MIN, -(-(created + 44 * MIN) // MIN) * MIN))
                await asyncio.to_thread(self.app["jobs"].q.join)
                await app_mod._tg_early(self.app, None, self.msg(f"/early {mint2}"), mint2)   # the same token: reused
                self.assertEqual(watch.call_args[0][2]["job"], job.id)
                mint3 = "D" * 40
                await app_mod._tg_early(self.app, None, self.msg(f"/early {mint3}"), mint3)  # the chat's cap
            self.assertIn("used its 1 new analyses", tg.of("editMessageText")[-1]["text"])
            self.assertIsNone(next((j for j in self.app["jobs"].jobs.values() if j.mint == mint3), None))
            self.assertEqual(self.app["runs_daily"].left("tg:global", 20), 19)

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
