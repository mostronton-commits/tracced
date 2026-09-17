import os
import time
import tempfile
import unittest

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

    def test_ttl_expiry(self):
        c = JsonCache(self.path, ttl_hours=1, flush_every=1)
        c.data["W"] = {"value": 1, "ts": time.time() - 7200}  # 2ч назад, TTL 1ч
        self.assertIsNone(c.get("W"))

    def test_persist_across_instances(self):
        c1 = JsonCache(self.path, flush_every=1)
        c1.put("W", 42)
        c2 = JsonCache(self.path)          # новый инстанс читает с диска
        self.assertEqual(c2.get("W"), 42)


if __name__ == "__main__":
    unittest.main()
