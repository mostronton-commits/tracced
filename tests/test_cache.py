import json
import os
import threading
import time
import tempfile
import unittest
from unittest import mock

from tracced.cache import JsonCache


class TestCache(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "c.json")

    def test_put_get(self):
        c = JsonCache(self.path, ttl_hours=1, flush_every=1)
        c.put("W", {"pnl": 100})
        self.assertEqual(c.get("W"), {"pnl": 100})

    def test_miss(self):
        c = JsonCache(self.path)
        self.assertIsNone(c.get("nope"))

    def test_a_record_older_than_since_counts_as_missing(self):
        c = JsonCache(self.path, ttl_hours=0)
        c.data["OLD"] = {"value": 1, "ts": 1000.0}
        c.data["NEW"] = {"value": 2, "ts": 3000.0}
        self.assertEqual((c.get("OLD"), c.get("OLD", since=2000), c.get("NEW", since=2000)), (1, None, 2))

    def test_ttl_expiry(self):
        c = JsonCache(self.path, ttl_hours=1, flush_every=1)
        c.data["W"] = {"value": 1, "ts": time.time() - 7200}  # 2ч назад, TTL 1ч
        self.assertIsNone(c.get("W"))

    def test_persist_across_instances(self):
        c1 = JsonCache(self.path, flush_every=1)
        c1.put("W", 42)
        c2 = JsonCache(self.path)          # новый инстанс читает с диска
        self.assertEqual(c2.get("W"), 42)

    def test_expired_entries_leave_on_load_and_on_flush(self):
        now = time.time()
        with open(self.path, "w") as f:
            json.dump({"old": {"value": 1, "ts": now - 7200}, "new": {"value": 2, "ts": now}}, f)
        c = JsonCache(self.path, ttl_hours=1, flush_every=1)
        self.assertEqual(set(c.data), {"new"})                 # протухшее не грузим в память
        c.data["stale"] = {"value": 3, "ts": now - 7200}
        c.put("more", 4)
        with open(self.path) as f:
            self.assertEqual(set(json.load(f)), {"new", "more"})   # и не пишем обратно в файл

    def test_no_ttl_keeps_everything(self):
        with open(self.path, "w") as f:
            json.dump({"old": {"value": 1, "ts": 1}}, f)
        c = JsonCache(self.path, ttl_hours=0, flush_every=1)
        c.put("new", 2)
        self.assertEqual(c.get("old"), 1)
        with open(self.path) as f:
            self.assertEqual(set(json.load(f)), {"old", "new"})

    def test_put_many_is_one_step_towards_a_flush(self):
        c = JsonCache(self.path, ttl_hours=1, flush_every=2)
        c.put_many({f"W{i}": i for i in range(100)})
        self.assertFalse(os.path.exists(self.path))            # сто записей — один шаг, а не четыре дампа
        c.put_many({f"V{i}": i for i in range(100)})
        with open(self.path) as f:
            self.assertEqual(len(json.load(f)), 200)
        self.assertEqual(c.get("V7"), 7)

    def test_a_slow_write_blocks_neither_readers_nor_writers(self):
        """Файл пишется без замка данных: get() и put() не ждут дамп, а второй flush ждёт первый."""
        c = JsonCache(self.path, ttl_hours=1, flush_every=1000)
        c.put("a", 1)
        entered, release = threading.Event(), threading.Event()
        real = os.replace

        def slow_replace(src, dst):
            if dst == self.path and not release.is_set():
                entered.set()
                release.wait(5)
            return real(src, dst)
        with mock.patch("tracced.cache.os.replace", side_effect=slow_replace):
            first = threading.Thread(target=c.flush)
            first.start()
            self.assertTrue(entered.wait(5))
            got = []
            reader = threading.Thread(target=lambda: (c.put("b", 2), got.append(c.get("a"))))
            reader.start()
            reader.join(2)
            self.assertEqual(got, [1])                         # не ждали запись файла
            second = threading.Thread(target=c.flush)
            second.start()
            second.join(0.3)
            self.assertTrue(second.is_alive())                 # второй flush ждёт первый, а не пишет в тот же .tmp
            release.set()
            first.join(5)
            second.join(5)
        with open(self.path) as f:
            self.assertEqual(set(json.load(f)), {"a", "b"})


if __name__ == "__main__":
    unittest.main()
