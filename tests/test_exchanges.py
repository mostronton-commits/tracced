"""Назви бірж серед спонсорів: список з файлу поза репозиторієм; без файлу — жодної назви."""
import json
import os
import tempfile
import unittest

from tracced.early import exchanges

BINANCE_1 = "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9"


class TestExchanges(unittest.TestCase):
    def test_a_list_from_a_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "cex.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"addresses": {BINANCE_1: ["Binance", "Binance 1"], "bad": "x"}}, f)
            known = exchanges.load(p)
        self.assertEqual(known, {BINANCE_1: ["Binance", "Binance 1"]})

    def test_no_file_no_names(self):
        self.assertEqual(exchanges.load(""), {})
        self.assertEqual(exchanges.load("/nonexistent.json"), {})
        if not os.getenv("EXCHANGE_LABELS_FILE"):
            self.assertIsNone(exchanges.name_of(BINANCE_1))            # the repo ships no list (the Dune snapshot's licence)


if __name__ == "__main__":
    unittest.main()
