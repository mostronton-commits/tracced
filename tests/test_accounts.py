"""Акаунт гаманця без сервера: base58, текст для підпису, підпис ed25519, nonce, кука, сховище."""
import base64
import os
import tempfile
import unittest

from tracced.web import accounts as A

try:
    from nacl.signing import SigningKey
except ImportError:                      # хост без PyNaCl: підпис перевіряється лише в Docker
    SigningKey = None

ZERO = "1" * 32                          # 32 нульові байти — адреса системної програми Solana
def addr(seed):
    return A.b58encode(bytes([seed]) * 32)


class TestBase58(unittest.TestCase):
    def test_roundtrip_and_vectors(self):
        self.assertEqual(A.b58encode(b"hello"), "Cn8eVZg")
        self.assertEqual(A.b58decode("Cn8eVZg"), b"hello")
        self.assertEqual(A.b58decode("1111"), b"\x00" * 4)
        self.assertEqual(A.b58encode(b""), "")
        for b in (b"\x00", b"\x00\x01", b"\xff" * 20, os.urandom(32), os.urandom(64)):
            self.assertEqual(A.b58decode(A.b58encode(b)), b)
        for bad in ("0", "O", "l", "I", "a b", ""):
            with self.assertRaises(ValueError):
                A.b58decode(bad)

    def test_valid_pubkey(self):
        self.assertTrue(A.valid_pubkey(ZERO))
        self.assertTrue(A.valid_pubkey(addr(7)))
        self.assertFalse(A.valid_pubkey(A.b58encode(b"\x07" * 31)))      # 31 байт
        self.assertFalse(A.valid_pubkey(A.b58encode(b"\x07" * 33)))      # 33 байти
        for bad in ("../x", "0OIl" * 9, "", None, 42, "A" * 40):         # "A"*40 — base58, але 29 байт
            self.assertFalse(A.valid_pubkey(bad))


class TestMessage(unittest.TestCase):
    def test_build_and_parse(self):
        pk = addr(1)
        msg = A.build_message("tracced.xyz", pk, "n0nce_x-1", "2026-09-20T10:00:00Z")
        self.assertEqual(A.parse_message(msg), {"domain": "tracced.xyz", "pubkey": pk, "nonce": "n0nce_x-1",
                                                 "issued_at": "2026-09-20T10:00:00Z"})
        self.assertIn("No transaction, no fees.", msg)
        self.assertEqual(msg.count("\n"), 6)

    def test_rejects_anything_else(self):
        pk = addr(1)
        good = A.build_message("tracced.xyz", pk, "n0nce_x-1", "2026-09-20T10:00:00Z")
        for bad in (good + "\n", good + " ", good.replace("Nonce: ", "nonce: "), good.replace("\n\n", "\n", 1),
                    good.replace("No transaction", "A transaction"), "", None, "x" * 3000, good.replace("tracced.xyz", "")):
            with self.assertRaises(ValueError, msg=repr(bad)[:60]):
                A.parse_message(bad)

    def test_issued_at(self):
        self.assertEqual(A.issued_at(0), "1970-01-01T00:00:00Z")
        self.assertEqual(A.parse_issued_at("1970-01-01T00:01:40Z"), 100.0)
        self.assertIsNone(A.parse_issued_at("yesterday"))
        self.assertIsNone(A.parse_issued_at(None))


@unittest.skipIf(SigningKey is None, "PyNaCl not installed")
class TestSignature(unittest.TestCase):
    def test_verify(self):
        sk = SigningKey.generate()
        pk = A.b58encode(bytes(sk.verify_key))
        msg = A.build_message("tracced.xyz", pk, "n0nce_x-1", A.issued_at())
        sig = sk.sign(msg.encode()).signature
        self.assertTrue(A.verify_signature(pk, msg, A.b58encode(sig)))
        self.assertTrue(A.verify_signature(pk, msg, base64.b64encode(sig).decode()))
        self.assertFalse(A.verify_signature(pk, msg + "x", A.b58encode(sig)))
        self.assertFalse(A.verify_signature(A.b58encode(bytes(SigningKey.generate().verify_key)), msg, A.b58encode(sig)))
        self.assertFalse(A.verify_signature(pk, msg, "garbage"))
        self.assertFalse(A.verify_signature(pk, msg, A.b58encode(sig[:63])))
        self.assertFalse(A.verify_signature("not-a-key", msg, A.b58encode(sig)))


class TestNonce(unittest.TestCase):
    def test_single_use_and_ttl(self):
        ns = A.NonceStore(ttl_s=300)
        n = ns.issue(now=100)
        self.assertTrue(ns.consume(n, now=200))
        self.assertFalse(ns.consume(n, now=200))                          # вдруге — ні
        n = ns.issue(now=100)
        self.assertFalse(ns.consume(n, now=500))                          # прострочений
        self.assertFalse(ns.consume("never-issued", now=100))

    def test_cap(self):
        ns = A.NonceStore(cap=3)
        for i in range(10):
            ns.issue(now=100 + i)
        self.assertLessEqual(len(ns.live), 3)


class TestCookie(unittest.TestCase):
    def test_sign_and_read(self):
        pk = addr(3)
        tok = A.sign_acct("s3cret", pk, 2_000_000_000)
        self.assertEqual(A.read_acct("s3cret", tok, now=1_000), pk)
        self.assertIsNone(A.read_acct("other", tok, now=1_000))            # інший ключ
        self.assertIsNone(A.read_acct("s3cret", tok, now=3_000_000_000))   # прострочена
        self.assertIsNone(A.read_acct("s3cret", tok[:-1] + "0", now=1_000))
        self.assertIsNone(A.read_acct("s3cret", tok.replace(pk, addr(4)), now=1_000))
        self.assertIsNone(A.read_acct("s3cret", None))
        self.assertIsNone(A.read_acct("s3cret", "a.b"))


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = A.AccountStore(self.tmp.name + "/accounts")
        self.pk = addr(9)

    def tearDown(self):
        self.tmp.cleanup()

    def test_path_is_gated(self):
        for bad in ("../x", "x", "A" * 40):
            with self.assertRaises(ValueError):
                self.st.path(bad)
        self.assertTrue(self.st.path(self.pk).endswith(self.pk + ".json"))

    def test_touch_creates_and_load_is_lenient(self):
        self.assertFalse(self.st.exists(self.pk))
        self.st.touch(self.pk)
        self.assertTrue(self.st.exists(self.pk))
        a = self.st.load(self.pk)
        self.assertEqual((a["pubkey"], a["wallets"], a["analyses"]), (self.pk, {}, {}))
        with open(self.st.path(self.pk), "w") as f:
            f.write("{broken")
        self.assertEqual(self.st.load(self.pk)["wallets"], {})           # битий файл → порожній акаунт

    def test_wallets(self):
        w1, w2 = addr(10), addr(11)
        items = [{"wallet": w1, "symbol": "TST", "entry_mcap": 1e6, "tags": ["sniper"]},
                 {"wallet": w2, "symbol": "TST"}, {"wallet": "not-an-address"}, {"wallet": w1}]
        self.assertEqual(self.st.add_wallets(self.pk, items), (2, 2))
        self.assertEqual(self.st.add_wallets(self.pk, items), (0, 2))      # уже є
        a = self.st.load(self.pk)
        self.assertEqual(a["wallets"][w1]["tags"], ["sniper"])
        self.assertEqual(a["wallets"][w1]["note"], "")
        self.assertTrue(self.st.set_note(self.pk, w1, "  watch\nthis " + "x" * 300))
        self.assertEqual(len(self.st.load(self.pk)["wallets"][w1]["note"]), A.MAX_NOTE)
        self.assertFalse(self.st.set_note(self.pk, addr(12), "nope"))
        self.assertTrue(self.st.remove_wallet(self.pk, w2))
        self.assertFalse(self.st.remove_wallet(self.pk, w2))
        self.assertEqual(list(self.st.load(self.pk)["wallets"]), [w1])

    def test_several_lists(self):
        w1, w2 = A.b58encode(b"\x21" * 32), A.b58encode(b"\x22" * 32)
        items = [{"wallet": w1, "symbol": "A"}, {"wallet": w2, "symbol": "B"}]
        self.assertEqual(self.st.add_wallets(self.pk, items), (2, 2))                  # у перший список, як завжди
        lid, name = self.st.create_list(self.pk, "  Insiders  ")
        self.assertEqual(name, "Insiders")
        with self.assertRaises(A.AccountError):
            self.st.create_list(self.pk, "insiders")                                     # та сама назва
        self.assertEqual(self.st.add_wallets(self.pk, items[:1], lid), (1, 2))          # той самий гаманець — ще в один список
        a = self.st.load(self.pk)
        self.assertEqual(a["wallets"][w1]["lists"], [A.MAIN_LIST, lid])
        self.assertTrue(self.st.remove_wallet(self.pk, w2, A.MAIN_LIST))              # w2 був лише в першому — зникає
        self.assertNotIn(w2, self.st.load(self.pk)["wallets"])
        self.assertEqual(self.st.delete_list(self.pk, lid), 0)                           # w1 лишається в першому
        self.assertEqual(self.st.load(self.pk)["wallets"][w1]["lists"], [A.MAIN_LIST])
        with self.assertRaises(A.AccountError):
            self.st.delete_list(self.pk, A.MAIN_LIST)

    def test_old_accounts_get_their_list_named(self):
        w = A.b58encode(b"\x23" * 32)
        a = self.st.load(self.pk)
        a["wallets"][w] = {"added_ms": 1, "my_tags": []}                                 # запис з часів одного списку
        a.pop("lists", None)
        self.st.save(a)
        a = self.st.load(self.pk)
        self.assertEqual(a["lists"][A.MAIN_LIST]["name"], "Watchlist")
        self.assertEqual(a["wallets"][w]["lists"], [A.MAIN_LIST])

    def test_wallet_cap(self):
        old = A.MAX_WALLETS
        A.MAX_WALLETS = 2
        try:
            with self.assertRaises(A.AccountError):
                self.st.add_wallets(self.pk, [{"wallet": addr(i)} for i in (20, 21, 22)])
        finally:
            A.MAX_WALLETS = old

    def test_analyses(self):
        summ = {"mint": "M", "symbol": "TST", "t_from": 1, "t_to": 2, "n": 3, "best": 2.5}
        self.assertEqual(self.st.add_analysis(self.pk, "AAAAAA_20010909-0146_0206", summ), (True, 1))
        self.assertEqual(self.st.add_analysis(self.pk, "AAAAAA_20010909-0146_0206", summ), (False, 1))
        with self.assertRaises(A.AccountError):
            self.st.add_analysis(self.pk, "../evil", summ)
        old = A.MAX_ANALYSES
        A.MAX_ANALYSES = 1
        try:
            with self.assertRaises(A.AccountError):
                self.st.add_analysis(self.pk, "BBBBBB_20010909-0146_0206", summ)
        finally:
            A.MAX_ANALYSES = old
        self.assertTrue(self.st.remove_analysis(self.pk, "AAAAAA_20010909-0146_0206"))
        self.assertFalse(self.st.remove_analysis(self.pk, "AAAAAA_20010909-0146_0206"))


if __name__ == "__main__":
    unittest.main()
