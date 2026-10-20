"""Telegram /early (20.10): the command, the pump window, the answer's text and buttons; then the bot's flow on a fake
Telegram and a fake data provider — an analysed token answers for free, a new one counts against the chat and the day,
Follow saves the wallets with their bells only for a linked Telegram."""
import asyncio
import json
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
         "sold_share_pct": 100.0, "tag_list": []}
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

    def test_how_a_reused_window_was_chosen(self):
        self.assertEqual(tgbot.how_of("system", T, T + 16 * MIN, T + 20_000), "launch → first 3x")
        self.assertEqual(tgbot.how_of("system", T, T + 30 * MIN, T), "first 30 min after launch")
        self.assertEqual(tgbot.how_of("Wallet111", T, T + 16 * MIN, T), "range marked on tracced")
        self.assertEqual(tgbot.how_of("system", T + HOUR, T + 2 * HOUR, T), "range marked on tracced")


class TestText(unittest.TestCase):
    def test_top_wallets_profitable_only_most_first(self):
        rows = [row("L", -50), row("A", 100), row("B", 900), row("Z", 0)] + [row(f"W{i}", 10 + i) for i in range(6)]
        self.assertEqual([r["wallet"] for r in tgbot.top_rows(rows)], ["B", "A", "W5", "W4", "W3"])
        self.assertEqual(tgbot.top_rows([row("L", -5)]), [])

    def test_a_wallet_line_carries_facts_and_escapes_names(self):
        w = "CE44oKS3wpUerx8afyeii56u5oQjBLZknzm4Q2CYHUz9"
        line = tgbot.wallet_line(1, row(w, 22_600, entry_range_mcap=4_400, exit_mcap_avg=382_000, sold_share_pct=91.0,
                                        tag_list=["sniper", "my-own"]), {w: {"name": "<b>x</b>", "twitter": "ape"}})
        self.assertIn(f'href="https://solscan.io/account/{w}"', line)
        self.assertIn("@ape", line)                                       # X handle first
        self.assertIn("$4.4K → $382K", line)
        self.assertIn("<b>+$22.6K</b>", line)
        self.assertIn("holds 9%", line)
        self.assertIn("sniper", line)
        self.assertNotIn("my-own", line)                                  # a person's own tags stay theirs
        line = tgbot.wallet_line(2, row(w, 5, exit_mcap_avg=None), {w: {"name": "<script>"}})
        self.assertIn("&lt;script&gt;", line)
        self.assertIn("→ holding", line)

    def test_launch_facts_only_with_proof_never_clean(self):
        self.assertIn("running", tgbot.launch_lines({})[0])
        self.assertIn("not run", tgbot.launch_lines({}, waiting=False)[0])
        self.assertIn("did not finish", tgbot.launch_lines({"launch": {"failed": "429"}})[0])
        found = {"launch": {"launch": {"bundle": "b0", "wallets": ["X", "Y"]},
                            "pairs": [{"bundle": f"b{i}", "seller": "S", "buyers": [["B", 1]]} for i in range(1, 5)],
                            "fee": {"to": [["FeeTaker111", 10000]], "paid": {"sol": 174.021}}, "sells": 113, "checked": 113}}
        text = "\n".join(tgbot.launch_lines(found, creator="Creator"))
        self.assertIn("explorer.jito.wtf/bundle/b0", text)
        self.assertIn("2 more wallets", text)
        self.assertIn("4 early sales", text)
        self.assertIn("explorer.jito.wtf/bundle/b3", text)
        self.assertNotIn("bundle/b4", text)                               # three links, then «…»
        self.assertIn("174.021 SOL", text)
        own_fee = {"launch": {"pairs": [], "launch": None, "fee": {"to": [["Creator", 10000]]}, "sells": 48, "checked": 48}}
        text = "\n".join(tgbot.launch_lines(own_fee, creator="Creator"))
        self.assertIn("no proof of an organised launch found (48 of 48 early sales checked", text)
        self.assertIn("not available", tgbot.launch_lines({"launch": {"no_tx": True, "pairs": []}})[0])
        for r in ({}, found, own_fee):
            self.assertNotIn("clean", " ".join(tgbot.launch_lines(r)).lower())

    def test_the_whole_answer_fits_telegram(self):
        rows = [row("W" * 44, 10 ** 6, tag_list=list(tgbot.SHOWN_TAGS)) for _ in range(6)]
        names = {"W" * 44: {"name": "<" * 200}}
        text = tgbot.early_text("<SYM>" * 10, MINT, T, T + 16 * MIN, "launch → first 3x", rows, names, {})
        self.assertLessEqual(len(text), 4000)
        self.assertIn("$&lt;SYM&gt;", text)
        self.assertIn(f"<code>{MINT}</code>", text)
        self.assertIn(tgbot.span(T, T + 16 * MIN) + " UTC", text)
        self.assertIn("top 5 by realized profit, of 6", text)
        empty = tgbot.early_text("TST", MINT, T, T + 30 * MIN, "x", [row("L", -1)], {}, {})
        self.assertIn("none has taken a profit yet", empty)

    def test_span_shows_the_date_again_past_midnight(self):
        a = 1_790_035_200_000 - 10 * MIN                                 # 23:50 UTC
        self.assertNotIn(" ", tgbot.span(a, a + 5 * MIN).split("–")[1])
        self.assertIn(" ", tgbot.span(a, a + 20 * MIN).split("–")[1])

    def test_buttons_and_follow_data(self):
        kb = tgbot.keyboard("2bCCHQ_20261015-2016_2050", "https://tracced.xyz")["inline_keyboard"][0]
        self.assertEqual(kb[0]["callback_data"], "f:2bCCHQ_20261015-2016_2050")
        self.assertEqual(kb[1]["url"], "https://tracced.xyz/job/2bCCHQ_20261015-2016_2050")
        self.assertEqual(len(tgbot.keyboard("j", "https://x", follow=False)["inline_keyboard"][0]), 1)
        self.assertEqual(tgbot.follow_job("f:2bCCHQ_20261015-2016_2050"), "2bCCHQ_20261015-2016_2050")
        for bad in ("f:../x", "f:", "g:abc", None, "f:" + "a" * 70):
            self.assertIsNone(tgbot.follow_job(bad))
        self.assertLessEqual(len(tgbot.list_name("A" * 40, MINT)), 32)


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
        from tests.test_web import FakeWebST, TEST_PK, W1, OTHER_MINT, OTHER_JID, DEMO_A, DEMO_B, _result, _job_file
    except ImportError:
        from test_early_pipeline import TRADES
        from test_web import FakeWebST, TEST_PK, W1, OTHER_MINT, OTHER_JID, DEMO_A, DEMO_B, _result, _job_file

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
            tg, before = FakeTelegram(), self.st.requests
            with mock.patch.object(app_mod, "_tg_call", tg):
                await app_mod._tg_early(self.app, None, self.msg(f"/early {OTHER_MINT}"), OTHER_MINT)
            self.assertEqual(self.st.requests, before)                         # nothing bought
            self.assertEqual(tg.of("sendMessage")[0]["reply_parameters"]["message_id"], 5)
            last = tg.of("editMessageText")[-1]
            self.assertIn("$TST", last["text"])
            self.assertIn(W1[:6], last["text"])
            self.assertIn("not run for this analysis", last["text"])         # an old result: no launch check is coming
            self.assertEqual(last["reply_markup"]["inline_keyboard"][0][0]["callback_data"], "f:" + OTHER_JID)
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
                self.assertEqual(entry["how"], "launch → first 3x")
                await asyncio.to_thread(self.app["jobs"].q.join)
                await app_mod._tg_early(self.app, None, self.msg(f"/early {mint2}"), mint2)   # the same token: reused
                self.assertEqual(watch.call_args[0][2]["job"], job.id)
                mint3 = "D" * 40
                await app_mod._tg_early(self.app, None, self.msg(f"/early {mint3}"), mint3)  # the chat's cap
            self.assertIn("used its 1 new analyses", tg.of("editMessageText")[-1]["text"])
            self.assertIsNone(next((j for j in self.app["jobs"].jobs.values() if j.mint == mint3), None))
            self.assertEqual(self.app["runs_daily"].left("tg:global", 20), 19)

        async def test_follow_needs_a_linked_telegram_then_saves_with_bells(self):
            self.seed()
            tg = FakeTelegram()
            cq = {"id": "q1", "from": {"id": 555}, "data": "f:" + OTHER_JID}
            with mock.patch.object(app_mod, "_tg_call", tg):
                await app_mod._tg_follow(self.app, None, cq)
                self.assertIn("Connect this Telegram", tg.of("answerCallbackQuery")[-1]["text"])
                self.app["accounts"].set_telegram(TEST_PK, 555, "@me")
                await app_mod._tg_follow(self.app, None, cq)
                await app_mod._tg_follow(self.app, None, dict(cq, data="f:nope"))
            done = tg.of("answerCallbackQuery")
            self.assertIn("Saved 1 wallet to your list", done[-2]["text"])
            self.assertIn("Alerts are on for 1", done[-2]["text"])
            self.assertIn("not ready", done[-1]["text"])
            a = self.app["accounts"].load(TEST_PK)
            lid = next(k for k, v in a["lists"].items() if v["name"] == "TST early (Telegram)")
            self.assertIn(lid, a["wallets"][W1]["lists"])
            self.assertTrue(a["wallets"][W1]["alert"])

        async def test_the_answer_survives_a_restart(self):
            self.seed()
            entry = {"chat": -100, "mid": 77, "job": OTHER_JID, "how": "range marked on tracced", "at": 0}
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
