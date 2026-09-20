"""Демо-реплей: правдиві рядки зі справжніх чисел, фази по порядку, час у бюджеті."""
import re
import unittest

from tracced.web import replay

CYRILLIC = re.compile("[Ѐ-ӿ]")
A, B = 999999960000, 1000001160000


def result(n_trades, n_early, mode="trades", requests=None, tags=()):
    r = {"info": {"symbol": "TST", "supply": 1000000}, "window": {"from": A, "to": B, "end": B + 3600000}, "mode": mode,
         "counts": {"n_wallets": n_early + 5, "n_trades": n_trades, "n_early": n_early},
         "coverage": {"exits_known": n_early, "total": n_early, "mode": mode, "cost_full": 5, "lookup_cap": 500, "plan": "free"},
         "rows": [{"wallet": f"w{i}", "tag_list": list(t)} for i, t in enumerate(tags)]}
    if requests is not None:
        r["requests"] = requests
    return r


class TestReplayLines(unittest.TestCase):
    def phases(self, seq):
        return [p for _, p, _, _, _ in seq]

    def test_numbers_add_up_and_phases_are_ordered(self):
        seq = replay.replay_lines(result(14414, 765, tags=[("sniper",), ("sniper", "bundle"), ()]), A, B)
        lines = [l for l, *_ in seq if l]
        self.assertTrue(all(isinstance(l, str) and l for l in lines))
        self.assertFalse(any(CYRILLIC.search(l) for l in lines))
        new = [int(m.group(1).replace(",", "")) for l in lines for m in [re.search(r"\(\+([\d,]+) new\)", l)] if m]
        self.assertEqual(sum(new), 14414)                                # сторінки разом = усі угоди
        self.assertEqual(len(new), 12)                                   # не більше 12 рядків сторінок
        order = [replay.PHASES.index(p) for p in self.phases(seq)]
        self.assertEqual(order, sorted(order))                           # token → trades → wallets → tags → done
        self.assertEqual(self.phases(seq)[-1], "done")
        self.assertIn("entry range: 14,414 trades · 770 buyers · 765 bought in the range", lines)
        self.assertIn("tags: sniper 2 · bundle 1", lines)
        self.assertTrue(lines[-1].startswith("done (trades): 765 wallets bought in the range; Exits known for all 765 wallets"))
        self.assertTrue(lines[-1].endswith("; cached"))                  # запитів у результаті нема → так і кажемо
        self.assertIn("cheapest complete path: whole token history — cached", lines)
        ups = [l.split("up to ")[1] for l in lines if " up to " in l]
        self.assertEqual(ups, sorted(ups))                               # час на сторінках не йде назад
        dones = [d for _, p, d, t, _ in seq if p == "trades" and t]
        self.assertEqual(dones, sorted(dones))

    def test_budget_and_small_result(self):
        for n in (3, 14414):
            seq = replay.replay_lines(result(n, 1 if n == 3 else 765, mode="wallet-trades", requests=3), A, B, budget_s=12.0)
            self.assertAlmostEqual(sum(s for *_, s in seq), 12.0, delta=0.5)
            self.assertTrue(all(s > 0 for *_, s in seq))
        seq = replay.replay_lines(result(3, 1, mode="wallet-trades", requests=3), A, B)
        lines = [l for l, *_ in seq if l]
        self.assertIn("page 1: 3 trades (+3 new), up to 09-09 02:06", lines)
        self.assertIn("  exits: 1/1", lines)                             # режим per-wallet пише як конвеєр
        self.assertTrue(lines[-1].endswith("requests 3"))
        self.assertIn("tags: none", lines)

    def test_play_drives_a_job(self):
        class Job:
            def __init__(self):
                self.log, self.progress = [], []
            def set_progress(self, phase, done=0, total=None):
                self.progress.append((phase, done, total))
        j, slept = Job(), []
        out = replay.play(j, result(500, 20, requests=3), A, B, sleep=slept.append)
        self.assertEqual(out["counts"]["n_early"], 20)
        self.assertEqual(j.progress[-1], ("done", 1, 1))
        self.assertEqual(len(slept), len(j.progress))
        self.assertTrue(len(j.log) >= 8)


if __name__ == "__main__":
    unittest.main()
