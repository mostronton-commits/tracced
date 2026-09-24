import tempfile
import unittest

from tracced.early.store import PageBudget, TradeStore

T0 = 1_000_000_000_000
MIN = 60_000
MINT = "TESTMINT"


def make_fetch(n_total=1000, page=100, calls=None):
    """Одна угода на хвилину від T0; сторінка = page угод ПІСЛЯ курсора (як у ST: виключний)."""
    trades = [{"wallet": f"w{i % 7}", "type": "buy" if i % 3 else "sell", "time": T0 + i * MIN,
               "qty": 1.0, "usd": 1.0, "price": 1.0, "tx": f"tx{i}", "program": "p"}
              for i in range(n_total)]

    def fetch(cursor):
        if calls is not None:
            calls.append(cursor)
        chunk = [t for t in trades if t["time"] > cursor][:page]
        has_next = bool(chunk) and chunk[-1]["time"] < trades[-1]["time"]
        return {"trades": chunk, "hasNextPage": has_next,
                "nextCursor": chunk[-1]["time"] if chunk else None}
    return fetch


def make_fetch_same_second(page=3, same=3):
    """Секунда T0+MIN має `same` угод; сторінка з `page` обривається посеред неї (кейс аудиту 17.09)."""
    trades = [{"wallet": "a", "type": "buy", "time": T0, "qty": 1.0, "usd": 1.0, "price": 1.0, "tx": "t0", "program": "p"}]
    trades += [{"wallet": f"w{i}", "type": "buy", "time": T0 + MIN, "qty": 1.0, "usd": 1.0, "price": 1.0, "tx": f"s{i}", "program": "p"} for i in range(same)]
    trades += [{"wallet": "z", "type": "sell", "time": T0 + 2 * MIN, "qty": 1.0, "usd": 1.0, "price": 1.0, "tx": "t9", "program": "p"}]

    def fetch(cursor):
        chunk = [t for t in trades if t["time"] > cursor][:page]
        has_next = bool(chunk) and chunk[-1]["time"] < trades[-1]["time"]
        return {"trades": chunk, "hasNextPage": has_next, "nextCursor": chunk[-1]["time"] if chunk else None}
    return fetch, trades


class TestTradeStore(unittest.TestCase):
    def test_boundary_second_is_not_lost(self):
        # сторінка з 3 обривається посеред секунди з 3 угодами (взяла 2) → усі 3 мають потрапити
        with tempfile.TemporaryDirectory() as d:
            fetch, trades = make_fetch_same_second(page=3, same=3)
            store = TradeStore(d, MINT)
            pages = store.ensure(T0, T0 + 2 * MIN, fetch, max_pages=20)
            self.assertEqual({t["tx"] for t in store.trades}, {t["tx"] for t in trades})
            self.assertLessEqual(pages, 4)
            self.assertEqual(store.gaps(T0, T0 + 2 * MIN), [])
        # звичайний випадок: секунда з 2 угодами на межі сторінки з 3 — без зайвих сторінок і попереджень
        with tempfile.TemporaryDirectory() as d:
            fetch, trades = make_fetch_same_second(page=3, same=2)
            store = TradeStore(d, MINT)
            logs = []
            pages = store.ensure(T0, T0 + 2 * MIN, fetch, max_pages=20, log=logs.append)
            self.assertEqual({t["tx"] for t in store.trades}, {t["tx"] for t in trades})
            self.assertFalse(any("warning" in m for m in logs))

    def test_second_wider_than_a_page_moves_on(self):
        # 5 угод в одній секунді, сторінка 2 → далі не зрушити; приймаємо втрату, не зациклюємось
        with tempfile.TemporaryDirectory() as d:
            fetch, trades = make_fetch_same_second(page=2, same=5)
            store = TradeStore(d, MINT)
            logs = []
            pages = store.ensure(T0, T0 + 2 * MIN, fetch, max_pages=20, log=logs.append)
            self.assertLess(pages, 20)
            self.assertTrue(any("warning" in m for m in logs))
            self.assertIn("t9", {t["tx"] for t in store.trades})            # історія за секундою дійшла
            self.assertEqual(store.gaps(T0, T0 + 2 * MIN), [])

    def test_start_of_gap_is_inclusive(self):
        # угода рівно в момент «від» має потрапити (курсор виключний → старт з ga-1)
        with tempfile.TemporaryDirectory() as d:
            calls = []
            store = TradeStore(d, MINT)
            store.ensure(T0, T0 + 5 * MIN, make_fetch(n_total=10, page=100, calls=calls), max_pages=5)
            self.assertEqual(calls[0], T0 - 1)
            self.assertIn("tx0", {t["tx"] for t in store.trades})

    def test_ensure_then_extend_then_reload(self):
        with tempfile.TemporaryDirectory() as d:
            calls = []
            st = TradeStore(d, MINT)
            pages = st.ensure(T0, T0 + 250 * MIN, make_fetch(calls=calls), max_pages=50)
            self.assertEqual(pages, 3)                                  # 0-99, 99-198, 198-297
            self.assertEqual(len(st.between(T0, T0 + 250 * MIN)), 251)
            self.assertEqual(st.gaps(T0, T0 + 250 * MIN), [])

            pages = st.ensure(T0 + 100 * MIN, T0 + 400 * MIN, make_fetch(calls=calls), max_pages=50)
            self.assertEqual(pages, 2)                                  # лише прогалина після 297
            self.assertEqual(st.gaps(T0, T0 + 400 * MIN), [])

            st2 = TradeStore(d, MINT)                                   # перечитали з диска
            self.assertEqual(len(st2.trades), len(st.trades))
            self.assertEqual(st2.gaps(T0, T0 + 400 * MIN), [])
            self.assertEqual(st2.ensure(T0, T0 + 400 * MIN, make_fetch(calls=calls), 50), 0)

    def test_budget_keeps_data(self):
        with tempfile.TemporaryDirectory() as d:
            st = TradeStore(d, MINT)
            with self.assertRaises(PageBudget) as cm:
                st.ensure(T0, T0 + 900 * MIN, make_fetch(), max_pages=2)
            self.assertEqual(cm.exception.pages, 2)
            self.assertGreaterEqual(len(st.trades), 199)
            st2 = TradeStore(d, MINT)
            self.assertTrue(st2.gaps(T0, T0 + 900 * MIN))               # прогалина лишилась
            self.assertLess(st2.gaps(T0, T0 + 900 * MIN)[0][0], T0 + 900 * MIN)

    def test_dedup(self):
        with tempfile.TemporaryDirectory() as d:
            st = TradeStore(d, MINT)
            page = make_fetch()(T0)["trades"]
            self.assertEqual(st.add(page), 100)
            self.assertEqual(st.add(page), 0)
            self.assertEqual(len(st.trades), 100)

    def test_history_end_marks_covered(self):
        with tempfile.TemporaryDirectory() as d:
            st = TradeStore(d, MINT)
            st.ensure(T0, T0 + 5000 * MIN, make_fetch(n_total=150), max_pages=50)
            self.assertEqual(st.gaps(T0, T0 + 5000 * MIN), [])         # історія скінчилась → закрито
            self.assertEqual(len(st.trades), 150)


def uneven_feed(delay=0.0):
    """Памп і тиша: 1 800 угод за перші пів години (по три в секунду, щоб межі шматків різали секунди),
    потім 300 угод на три доби. Той самий виключний курсор, що в ST; рахує одночасні виклики."""
    import threading
    import time as _t
    trades = []
    for i in range(1800):
        trades.append({"wallet": f"p{i % 50}", "type": "buy", "time": T0 + (i // 3) * 1000, "qty": 1.0, "usd": 1.0,
                       "price": 1.0, "tx": f"p{i}", "program": "p"})
    for i in range(300):
        trades.append({"wallet": f"q{i % 9}", "type": "sell", "time": T0 + 1_800_000 + i * 864_000, "qty": 1.0,
                       "usd": 1.0, "price": 1.0, "tx": f"q{i}", "program": "p"})
    lock, state = threading.Lock(), {"now": 0, "max": 0, "calls": 0}

    def fetch(cursor, page=50):
        with lock:
            state["now"] += 1; state["calls"] += 1
            state["max"] = max(state["max"], state["now"])
        try:
            if delay:
                _t.sleep(delay)
            chunk = [t for t in trades if t["time"] > cursor][:page]
            has_next = bool(chunk) and chunk[-1]["time"] < trades[-1]["time"]
            return {"trades": chunk, "hasNextPage": has_next, "nextCursor": chunk[-1]["time"] if chunk else None}
        finally:
            with lock:
                state["now"] -= 1
    return fetch, trades, state


class TestParallelEnsure(unittest.TestCase):
    """Курсор — час, тож історію ріжемо на шматки і тягнемо одночасно; жодна угода не має загубитись."""

    END = T0 + 1_800_000 + 300 * 864_000

    def test_every_trade_arrives_once_whatever_the_split(self):
        for workers in (2, 4, 8):
            with self.subTest(workers=workers), tempfile.TemporaryDirectory() as d:
                fetch, trades, state = uneven_feed(delay=0.005)
                store = TradeStore(d, MINT)
                pages = store.ensure(T0, self.END, fetch, max_pages=500, workers=workers)
                self.assertEqual(sorted(t["tx"] for t in store.trades), sorted(t["tx"] for t in trades))
                self.assertEqual(store.gaps(T0, self.END), [])
                self.assertEqual(pages, state["calls"])
                self.assertLessEqual(state["max"], workers)
                self.assertGreaterEqual(state["max"], 2)                 # справді одночасно
                seq_pages = -(-len(trades) // 50)
                self.assertLess(pages, seq_pages * 2)                     # перекриття на межах — кілька сторінок, не вдвічі

    def test_the_result_matches_the_sequential_path(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            fetch, _, _ = uneven_feed()
            one, many = TradeStore(d1, MINT), TradeStore(d2, MINT)
            one.ensure(T0, self.END, fetch, max_pages=500)
            many.ensure(T0, self.END, fetch, max_pages=500, workers=6)
            self.assertEqual([t["tx"] for t in one.trades], [t["tx"] for t in many.trades])   # і порядок за часом

    def test_the_page_cap_holds_with_pages_in_flight(self):
        with tempfile.TemporaryDirectory() as d:
            fetch, _, state = uneven_feed(delay=0.002)
            store = TradeStore(d, MINT)
            with self.assertRaises(PageBudget) as cm:
                store.ensure(T0, self.END, fetch, max_pages=12, workers=8)
            self.assertLessEqual(state["calls"], 12)
            self.assertEqual(cm.exception.pages, state["calls"])
            again = TradeStore(d, MINT)                                   # усе завантажене лишилось на диску
            self.assertGreater(len(again.trades), 0)

    def test_a_short_gap_is_not_split(self):
        with tempfile.TemporaryDirectory() as d:
            fetch, _, state = uneven_feed()
            store = TradeStore(d, MINT)
            store.ensure(T0, T0 + 5_000, fetch, max_pages=50, workers=8)
            self.assertEqual(state["calls"], 1)

    def test_a_quiet_history_costs_what_the_sequential_path_does(self):
        """400 угод за дві доби, діапазон входу вже в кеші: кожна сторінка — кредит, тож тиха історія не має
        коштувати по сторінці на кожен потік (було щонайменше 8 на кожну з двох прогалин замість 5 разом)."""
        trades = [{"wallet": f"q{i % 9}", "type": "buy", "time": T0 + i * 432_000, "qty": 1.0, "usd": 1.0,
                   "price": 1.0, "tx": f"q{i}", "program": "p"} for i in range(400)]
        end = trades[-1]["time"]

        def fetch(cursor, page=100):
            chunk = [t for t in trades if t["time"] > cursor][:page]
            return {"trades": chunk, "hasNextPage": bool(chunk) and chunk[-1]["time"] < end}
        pages = {}
        for workers in (1, 8):
            with tempfile.TemporaryDirectory() as d:
                store = TradeStore(d, MINT)
                store.mark_covered(T0 + 23 * 3_600_000, T0 + 24 * 3_600_000)   # діапазон входу вже купили
                pages[workers] = store.ensure(T0, end, fetch, max_pages=100, workers=workers)
                self.assertEqual(store.gaps(T0, end), [])
                outside = {t["tx"] for t in trades if not T0 + 23 * 3_600_000 <= t["time"] <= T0 + 24 * 3_600_000}
                self.assertLessEqual(outside, {t["tx"] for t in store.trades})
        self.assertEqual(pages, {1: 5, 8: 5})


class TestTradeCandles(unittest.TestCase):
    """Де джерело свічок мовчить, графік бере свічки з угод, які аналіз уже купив."""

    def test_minute_candles_from_trades_and_filling_only_the_holes(self):
        from tracced.early.store import load_candles
        from tracced.web.chart import fill_gaps
        B = (T0 // 60000 + 1) * 60000                                              # початок хвилини
        trades = [{"wallet": "a", "type": "buy", "time": B + s_ * 1000, "qty": 1.0, "usd": 10.0, "price": p, "tx": f"t{s_}", "program": "p"}
                  for s_, p in ((0, 1.0), (20, 3.0), (40, 2.0), (60, 5.0), (125, 4.0))]
        with tempfile.TemporaryDirectory() as d:
            st = TradeStore(d, MINT)
            st.add(trades)
            st.mark_covered(B, B + 180_000)
            self.assertEqual(st.save_candles(), 3)
            ours = load_candles(d, MINT)
            m0 = B // 1000
            self.assertEqual(ours["c"][0], [m0, 1.0, 3.0, 1.0, 2.0, 30.0])      # open, high, low, close, $ за хвилину
            source = [{"time": m0 + 60, "open": 9, "high": 9, "low": 9, "close": 9, "volume": 1}]   # джерело має лише 2-гу хвилину
            out = fill_gaps(source, ours, m0, m0 + 300, "1m", 1000)
            self.assertEqual([c["time"] for c in out], [m0, m0 + 60, m0 + 120])
            self.assertEqual(out[1]["close"], 9)                                    # свічка джерела лишається своєю
            self.assertEqual((out[0]["close"], out[0]["src"]), (2000.0, "trades"))  # ціна × supply
            st.add([{"wallet": "b", "type": "buy", "time": B + 30_000, "qty": 1e-9, "usd": 10.0, "price": 1e10, "tx": "broken", "program": "p"}])
            st.save_candles()
            self.assertEqual(load_candles(d, MINT)["c"][0][2], 3.0)                 # бита ціна не стає тінню свічки
            st.covered = []
            st.mark_covered(B, B + 60_000)                                          # покрита лише перша хвилина
            st.save_candles()
            self.assertEqual(len(fill_gaps(source, load_candles(d, MINT), m0, m0 + 300, "1m", 1000)), 2)


if __name__ == "__main__":
    unittest.main()
