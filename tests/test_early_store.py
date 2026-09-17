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


if __name__ == "__main__":
    unittest.main()
