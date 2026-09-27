"""Журнал подій і підрахунки дашборда власника: без сервера і без мережі."""
import datetime
import json
import os
import tempfile
import unittest

from tracced.web import usage
from tracced.web.accounts import EventLog

SEP_2026 = 1_789_000_000_000          # 2026-09-10 UTC
AUG_2026 = SEP_2026 - 31 * 86_400_000


class TestEventLog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.legacy = os.path.join(self.tmp.name, "_events.jsonl")
        self.log = EventLog(os.path.join(self.tmp.name, "usage"), legacy=self.legacy)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_line_lands_in_the_file_of_its_month(self):
        self.log.add("P", "signin", ts_ms=AUG_2026, wallet="Phantom", n=None)
        self.log.add_many([{"ts_ms": SEP_2026, "pubkey": "P", "event": "view", "page": "job"}])
        files = sorted(os.listdir(os.path.join(self.tmp.name, "usage")))
        self.assertEqual(files, ["2026-08.jsonl", "2026-09.jsonl"])
        with open(os.path.join(self.tmp.name, "usage", "2026-08.jsonl")) as f:
            rec = json.loads(f.readline())
        self.assertEqual(rec, {"ts_ms": AUG_2026, "pubkey": "P", "event": "signin", "wallet": "Phantom"})   # None не пишеться

    def test_read_merges_the_old_file_and_keeps_time_order(self):
        with open(self.legacy, "w") as f:
            f.write(json.dumps({"ts_ms": AUG_2026 - 5, "pubkey": "P", "event": "signin"}) + "\nnot json\n")
        self.log.add("P", "view", ts_ms=SEP_2026 + 2)
        self.log.add("P", "analyze", ts_ms=SEP_2026 + 1)                  # пачка кліків могла прийти пізніше за подію
        self.assertEqual([e["event"] for e in self.log.read()], ["signin", "analyze", "view"])
        self.assertEqual([e["event"] for e in self.log.read(since_ms=SEP_2026)], ["analyze", "view"])
        self.assertEqual([e["event"] for e in self.log.read(until_ms=AUG_2026)], ["signin"])

    def test_tail_holds_only_actions_newest_first_across_months(self):
        with open(self.legacy, "w") as f:
            f.write(json.dumps({"ts_ms": 1, "pubkey": "guest", "event": "waitlist"}) + "\n")
        self.log.add("P", "save_wallets", ts_ms=AUG_2026, n=1)
        self.log.add("P", "view", ts_ms=SEP_2026, page="job")
        self.log.add("P", "spend", ts_ms=SEP_2026 + 1, st=3)
        self.log.add("P", "analyze", ts_ms=SEP_2026 + 2)
        self.assertEqual([e["event"] for e in self.log.tail()], ["analyze", "save_wallets", "waitlist"])
        self.assertEqual([e["event"] for e in self.log.tail(2, kinds=None)], ["analyze", "spend"])

    def test_prune_keeps_the_last_months(self):
        d = os.path.join(self.tmp.name, "usage")
        for m in ("2025-08", "2025-09", "2026-08", "2026-09"):
            open(os.path.join(d, m + ".jsonl"), "w").close()
        self.assertEqual(self.log.prune(13, now_ms=SEP_2026), 1)         # вересень 2025 — тринадцятий місяць, лишається
        self.assertEqual(sorted(os.listdir(d)), ["2025-09.jsonl", "2026-08.jsonl", "2026-09.jsonl"])


class TestBeaconBatch(unittest.TestCase):
    NOW = 1_790_000_000_000

    def test_only_named_clicks_with_short_values_pass(self):
        addr = "9ALkCa" + "x" * 38
        body = {"e": [["sort", {"key": "real", "dir": "desc", "via": "head", "extra": "no"}, 5_000],
                      ["copy", {"what": addr}, 5_000],                            # адреса не проходить
                      ["filter", {"k": "hello world, I typed this"}, 5_000],    # набраний текст — теж
                      ["select", {"count": float("nan")}, 5_000],
                      ["leave", {"secs": 1e12}, 5_000],
                      ["pin", {"on": True}, 5_000],
                      ["rm -rf", {}, 5_000], "junk", ["card-open", "not a dict", 1]]}
        out = usage.clean_batch(body, self.NOW)
        self.assertEqual([(e["name"], e["p"]) for e in out],
                         [("sort", {"key": "real", "dir": "desc", "via": "head"}), ("copy", {}), ("filter", {}),
                          ("select", {}), ("leave", {"secs": 1_000_000_000}), ("pin", {"on": True})])

    def test_the_easter_egg_is_a_named_click(self):
        out = usage.clean_batch({"e": [["egg", {"what": "candles", "who": "wick"}, 5_000]]}, self.NOW)
        self.assertEqual([(e["name"], e["p"]) for e in out], [("egg", {"what": "candles"})])
        self.assertEqual(usage.CLICKS["egg"], "Found an easter egg")

    def test_the_browser_clock_only_orders_a_batch(self):
        out = usage.clean_batch({"e": [["tf", {"tf": "1m"}, 1_000], ["tf", {"tf": "5m"}, 61_000], ["tf", {"tf": "1h"}, 10**15]]}, self.NOW)
        self.assertEqual([e["ts"] for e in out], [self.NOW - usage.LAG_MAX_MS, self.NOW - usage.LAG_MAX_MS, self.NOW])
        out = usage.clean_batch({"e": [["tf", {}, 1_000], ["tf", {}, 61_000]]}, self.NOW)
        self.assertEqual([e["ts"] for e in out], [self.NOW - 60_000, self.NOW])

    def test_at_most_thirty_and_junk_bodies(self):
        self.assertEqual(len(usage.clean_batch({"e": [["tf", {}, 1]] * 100}, self.NOW)), 30)
        for body in (None, [], {"e": "x"}, {"e": {}}, {}):
            self.assertEqual(usage.clean_batch(body, self.NOW), [])

    def test_the_page_comes_from_the_referer_of_this_site(self):
        h = "tracced.xyz"
        mint = "8" * 44
        cases = {"https://tracced.xyz/": ("home", None), f"https://tracced.xyz/token?mint={mint}&from=x": ("token", mint),
                 "https://tracced.xyz/job/98kfF7_20260915-1930_1950": ("job", "98kfF7_20260915-1930_1950"),
                 "https://tracced.xyz/me": ("me", None), "https://tracced.xyz/docs": ("docs", "index"),
                 "https://tracced.xyz/docs/limits": ("docs", "limits"), "https://tracced.xyz/token?mint=<script>": ("token", None),
                 "https://tracced.xyz/connect": ("other", None)}
        for ref, want in cases.items():
            self.assertEqual(usage.page_of(ref, h), want, ref)
        for ref in ("https://tracced.xyz/admin", "https://tracced.xyz/admin/w/x", "https://evil.example/job/x", "", "not a url"):
            self.assertIsNone(usage.page_of(ref, h), ref)


UTC = datetime.timezone.utc
NOW = int(datetime.datetime(2026, 9, 25, 12, 0, tzinfo=UTC).timestamp() * 1000)
H, D = 3_600_000, 86_400_000
A, B, C, T = "A" * 44, "B" * 44, "C" * 44, "T" * 44          # два гаманці, третій з ночі за Варшавою, і власник


def ev(ts, pk, event, **kw):
    return dict({"ts_ms": ts, "pubkey": pk, "event": event}, **kw)


def job(jid, owner, finished, requests, **kw):
    from types import SimpleNamespace
    return SimpleNamespace(id=jid, mint="M" * 40, owner=owner, replay=None, status="done", error=None, spent=None,
                           t_from=finished - 3 * H, t_to=finished - 2 * H, created_ms=finished - 60_000, started_ms=finished - 50_000,
                           finished_ms=finished, symbol="OLD", result={"requests": requests, "rows": [{}] * 5, "info": {"created_time": finished - 5 * H}}, **kw)


class TestSummary(unittest.TestCase):
    def setUp(self):
        a0, b0 = NOW - 10 * D, NOW - 2 * D
        self.accounts = [{"pubkey": A, "created_ms": a0, "wallet_app": "Phantom"}, {"pubkey": B, "created_ms": b0},
                         {"pubkey": T, "created_ms": NOW - 20 * D}]
        self.events = [
            ev(a0, A, "signin"), ev(a0 + 60_000, A, "analyze", job="J1"),
            ev(a0 + 120_000, A, "run", job="J1", mint="M1", symbol="ONE", ok=1, st=100, rows=50, age_h=2.0, after_h=0.5, mcap=400_000, pad="pump.fun"),
            ev(a0 + 130_000, A, "spend", what="names", st=3, job="J1", bg=1),
            ev(a0 + 140_000, A, "spend", what="enrich", rpc=50, job="J1", bg=1),
            ev(a0 + 150_000, A, "spend", what="card-profile", st=2, job="J1"),
            ev(a0 + 160_000, A, "spend", what="card-age", rpc=5, job="J1"),
            ev(b0, B, "signin"), ev(b0 + 1000, B, "view", page="token", ref="M1", dev="m"),
            ev(b0 + 2000, B, "ui", name="card-open", page="job", ref="J1", src="row"),
            ev(b0 + 3000, B, "ui", name="export", page="job", format="csv"),
            ev(b0 + 4000, B, "agent", kind="cards", ok=1, cached=0, ai_usd=0.001, ai_in=100, ai_out=20, ms=2000),
            ev(b0 + 5000, B, "agent", kind="cards", ok=1, cached=1, ms=5),
            ev(NOW - 3 * H, A, "view", page="job", ref="J1", state="done", dev="d"),
            ev(NOW - 3 * H + 60_000, A, "analyze", job="J1"),
            ev(NOW - 3 * H + 120_000, A, "run", job="J1", mint="M1", symbol="ONE", ok=1, st=40, rows=52),
            ev(NOW - 3 * H + 180_000, A, "spend", what="card-profile", st=1, job="J1"),     # належить повторному прогону
            ev(NOW - 3 * H + 240_000, A, "ui", name="sort", page="job", key="real", dir="desc"),
            ev(NOW - 3 * H + 250_000, A, "ui", name="sort", page="job", key="real", dir="desc"),
            ev(NOW - 3 * H + 260_000, A, "ui", name="sort", page="job", key="real", dir="desc"),
            ev(NOW - 3 * H + 300_000, A, "agent", kind="ask", ok=1, chip="Was this a bundled launch?", ai_usd=0.0002, ms=1500),
            ev(NOW - 2 * H, T, "view", page="home"), ev(NOW - 2 * H + 1000, T, "run", job="J2", mint="M2", ok=0, st=500, err="feed down"),
            ev(NOW - H, "guest", "spend", what="chart", st=7, mint="M3"),
            ev(NOW - H, "system", "spend", what="credits", st=1, bg=1),
            ev(NOW - 13 * H - 30 * 60_000, C, "view", page="home"),                        # 24.09 22:30 UTC = 25.09 у Варшаві
        ]
        self.accounts.append({"pubkey": C, "created_ms": NOW - 13 * H - 40 * 60_000})

    def summ(self, **kw):
        kw.setdefault("team", {T})
        return usage.summarize(self.events, accounts=self.accounts, now_ms=NOW, **kw)

    def test_active_wallets_leave_out_the_team_guests_and_the_server(self):
        u = self.summ(period="7d")
        self.assertEqual((u["pulse"]["dau"], u["pulse"]["wau"], u["pulse"]["mau"]), (1, 3, 3))   # C — учора за UTC
        self.assertEqual((u["pulse"]["new"], u["pulse"]["accounts_all"]), (2, 4))
        self.assertEqual({w["pubkey"] for w in u["users"]}, {A, B, C})
        with_team = self.summ(period="7d", include_team=True)
        self.assertEqual(with_team["pulse"]["dau"], 2)
        self.assertEqual({w["pubkey"] for w in with_team["users"]}, {A, B, C, T})

    def test_a_day_ends_at_midnight_in_warsaw(self):
        warsaw = usage.zone("Europe/Warsaw")
        self.assertEqual(self.summ(period="today", tz=warsaw)["pulse"]["dau"], 2)        # A і нічний C
        self.assertEqual(self.summ(period="today")["pulse"]["dau"], 1)

    def test_funnel_visits_and_coming_back(self):
        u = self.summ(period="7d")
        self.assertEqual(u["funnel_base"], 3)
        self.assertEqual({f["key"]: f["n"] for f in u["funnel"]}, {"result": 2, "card": 2, "run": 1, "keep": 1, "agent": 1})
        self.assertEqual((u["sessions"]["n"], u["returning"]), (3, 0))
        self.assertEqual([(c["days"], c["n"], c["of"]) for c in u["came_back"]], [(1, 1, 2), (7, 1, 1), (30, 0, 0)])
        self.assertEqual(u["activation"], {"n": 1, "of": 2})                          # B відкрив картку, C бачив лише головну

    def test_each_analysis_carries_its_names_age_checks_and_cards(self):
        u = self.summ(period="30d")
        runs = {(r["job"], r["st_run"]): r for r in u["runs"]}
        first, again = runs[("J1", 100)], runs[("J1", 40)]
        self.assertEqual((first["st_total"], first["rpc_total"], first["st_names"]), (105, 55, 3))
        self.assertEqual((again["st_total"], again["rpc_total"]), (41, 0))              # картка після повтору — його
        self.assertEqual(u["run_stats"]["st"]["max"], 105)
        self.assertNotIn("J2", {r["job"] for r in u["runs"]})                          # прогін власника — лише з командою

    def test_costs_count_everyone_who_spent(self):
        u = self.summ(period="30d")
        who = {w["who"]: w for w in u["costs"]["by_who"]}
        self.assertEqual((who["wallets"]["st"], who["wallets"]["rpc"], who["team"]["st"], who["guests"]["st"], who["system"]["st"]),
                         (146, 55, 500, 7, 1))
        self.assertAlmostEqual(who["wallets"]["ai_usd"], 0.0012)
        feat = {f["what"]: f for f in u["costs"]["by_feature"]}
        self.assertEqual((feat["run"]["st"], feat["names"]["st"], feat["enrich"]["rpc"], feat["chart"]["st"]), (640, 3, 50, 7))
        self.assertEqual(self.summ(period="30d", budgets={"rpc": {"spent": 80}})["costs"]["month"]["rpc_unlogged"], 25)

    def test_the_agent_in_numbers(self):
        ai = self.summ(period="30d")["ai"]
        self.assertEqual((ai["wallets"], ai["cards_fresh"], ai["cards_ready"], ai["asks"], ai["asks_chip"]), (2, 1, 1, 1, 1))
        self.assertEqual(ai["chips"], [{"q": "Was this a bundled launch?", "n": 1}])
        self.assertAlmostEqual(ai["usd_per_cards"], 0.001)

    def test_old_analyses_come_from_their_files_once(self):
        jobs = [job("OLD1", A, NOW - 12 * D, 321), job("J1", A, NOW - 3 * H + 120_000, 40)]   # другий уже має рядок run
        u = usage.summarize(self.events, accounts=self.accounts, jobs=jobs, now_ms=NOW, period="30d", team={T})
        old = [r for r in u["runs"] if r["backfill"]]
        self.assertEqual([(r["job"], r["st_total"], r["pubkey"]) for r in old], [("OLD1", 321, A)])
        self.assertEqual(sum(1 for r in u["runs"] if r["job"] == "J1"), 2)

    def test_what_they_analyze(self):
        t = self.summ(period="30d", include_team=True)["tokens"]
        self.assertEqual([(x["mint"], x["runs"]) for x in t["top"][:2]], [("M1", 2), ("M2", 1)])
        self.assertEqual({b["label"]: b["n"] for b in t["age"]}["1–6 h"], 1)
        self.assertEqual(t["pads"], [{"pad": "pump.fun", "n": 1}])

    def test_ranges_failures_errors_and_devices(self):
        self.events += [ev(NOW - H, A, "error", where="job", status=502, msg="The chain node did not answer."),
                        ev(NOW - H + 1, B, "error", where="job", status=502, msg="The chain node did not answer.")]
        u = self.summ(period="30d", include_team=True)
        self.assertEqual({b["label"]: b["n"] for b in u["tokens"]["range"]}["> 6 h"], 0)
        self.assertEqual(u["fails"], [{"err": "feed down", "n": 1}])               # прогін власника, з командою
        self.assertEqual([(e["where"], e["status"], e["times"], e["wallets"]) for e in u["errors"]], [("job", 502, 2, 2)])
        self.assertEqual(u["devices"], {"phone": 1, "computer": 1})
        self.assertEqual(u["questions"], 1)

    def test_one_wallet_step_by_step(self):
        d = usage.wallet_detail(self.events, A, account=self.accounts[0], now_ms=NOW, team={T})
        items = [x for day in d["timeline"] for x in day["steps"]]
        sort = [x for x in items if x["text"].startswith("Sorted the table")]
        self.assertEqual((len(sort), sort[0]["n"], sort[0]["text"]), (1, 3, "Sorted the table · real desc"))   # три підряд — один рядок
        self.assertEqual([r["st_total"] for r in d["runs"]], [41, 105])
        self.assertEqual((d["totals"]["st"], d["totals"]["rpc"]), (146, 55))
        self.assertFalse(any(x["text"].startswith("Wallet names") for x in items))    # фонові витрати — у таблиці аналізів

    def test_labels_read_like_the_old_page(self):
        self.assertEqual(usage.label(ev(1, A, "save_wallets", n=1, job="J1", symbol="ONE")),
                         {"text": "saved 1 wallet from", "href": "/job/J1", "link": "ONE"})
        self.assertEqual(usage.label(ev(1, A, "limit", what="run", kind="wallet"))["text"], "hit the daily limit: run (wallet)")
        self.assertIn("off topic", usage.label(ev(1, A, "agent", kind="ask", ok=1, off=1, job="J1"))["text"])


class TestOnchainHelpers(unittest.TestCase):
    def test_who_is_due_for_fresh_facts(self):
        evs = [ev(NOW - 5 * H, A, "view"), ev(NOW - H, B, "view"), ev(NOW - 2 * H, C, "view"), ev(NOW - H, "guest", "spend", st=1),
               ev(NOW - H, T, "spend", what="enrich", rpc=5, bg=1)]
        onchain = {C: {"at": NOW - 3 * H}, A: {"at": NOW - 30 * H}}
        self.assertEqual(usage.due_wallets(evs, onchain, NOW), [B, A])        # C оновлено 3 год тому, T лише платив у фоні
        self.assertEqual(usage.due_wallets(evs, onchain, NOW, cap=1), [B])

    def test_the_dashboard_keeps_a_few_numbers_of_the_card(self):
        card = {"pnl_usd": 1234.567, "win_rate": 0.4567, "closed": 9, "swaps": 120, "tokens": 14, "volume_usd": 9999.991,
                "partial": False, "computed_ms": 5, "heat": [[0] * 24] * 7, "periods": {}}
        self.assertEqual(usage.compact_profile(card), {"pnl_usd": 1234.57, "win_rate": 0.457, "closed": 9, "swaps": 120, "tokens": 14,
                                                       "volume_usd": 9999.99, "partial": False, "at": 5})
        self.assertIsNone(usage.compact_profile(None))


class TestZone(unittest.TestCase):
    def test_warsaw_resolves_in_the_image(self):
        tz = usage.zone("Europe/Warsaw")                                 # pip tzdata: у slim-образі системної бази нема
        self.assertEqual(datetime.datetime(2026, 9, 25, 22, 30, tzinfo=datetime.timezone.utc).astimezone(tz).day, 26)

    def test_an_unknown_zone_is_utc(self):
        self.assertIs(usage.zone("Mars/Olympus"), datetime.timezone.utc)
        noon = datetime.datetime(2026, 9, 25, 12, tzinfo=datetime.timezone.utc)
        self.assertEqual(noon.astimezone(usage.zone("")).hour, 12)      # не задано — UTC


if __name__ == "__main__":
    unittest.main()
