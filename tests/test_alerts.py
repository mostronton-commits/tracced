"""Сповіщення в Telegram, чиста логіка: розбір транзакції, коди прив'язки, хто на що підписаний, текст. Без мережі."""
import unittest

from tracced.web import alerts as A

W, OTHER, POOL = "W" * 44, "Q" * 44, "P" * 44
TOKEN, USDC = "T" * 44, "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
PX = 150.0


def tb(mint, amount, owner=W):
    return {"mint": mint, "owner": owner, "uiTokenAmount": {"uiAmount": amount}}


def tx(sol=(10.0, 10.0), pre=(), post=(), signer=W, fee=5000, err=None):
    """Транзакція, яку підписав signer; sol — SOL гаманця до і після (у SOL), pre/post — його токен-баланси."""
    keys = [{"pubkey": signer, "signer": True}] + ([{"pubkey": W, "signer": False}] if signer != W else []) + [{"pubkey": POOL, "signer": False}]
    i = [k["pubkey"] for k in keys].index(W)
    pre_b, post_b = [0] * len(keys), [0] * len(keys)
    pre_b[i], post_b[i] = int(sol[0] * 1e9), int(sol[1] * 1e9)
    return {"blockTime": 1_790_000_000, "transaction": {"signatures": ["SIG1"], "message": {"accountKeys": keys}},
            "meta": {"err": err, "fee": fee, "preBalances": pre_b, "postBalances": post_b,
                     "preTokenBalances": list(pre), "postTokenBalances": list(post)}}


class TestClassify(unittest.TestCase):
    def test_a_buy_with_sol_leaves_the_fee_out(self):
        ev, = A.classify(tx(sol=(10.0, 10.0 - 1.0 - 5000 / 1e9), post=[tb(TOKEN, 1000)]), W, PX)
        self.assertEqual((ev["side"], ev["mint"], ev["amount"], ev["sig"]), ("buy", TOKEN, 1000, "SIG1"))
        self.assertAlmostEqual(ev["usd"], 150.0, places=2)

    def test_a_sell_for_sol(self):
        ev, = A.classify(tx(sol=(8.0, 9.5 - 5000 / 1e9), pre=[tb(TOKEN, 1000)], post=[tb(TOKEN, 0)]), W, PX)
        self.assertEqual((ev["side"], ev["amount"]), ("sell", 1000))
        self.assertAlmostEqual(ev["usd"], 225.0, places=2)

    def test_stablecoins_and_wrapped_sol_pay_too(self):
        ev, = A.classify(tx(pre=[tb(USDC, 200)], post=[tb(USDC, 0), tb(TOKEN, 50)]), W, PX)
        self.assertEqual((ev["side"], round(ev["usd"])), ("buy", 200))
        ev, = A.classify(tx(pre=[tb(A.WSOL, 2)], post=[tb(A.WSOL, 0), tb(TOKEN, 50)]), W, PX)
        self.assertEqual((ev["side"], round(ev["usd"])), ("buy", 300))

    def test_what_is_not_a_trade(self):
        fee = 5000 / 1e9
        self.assertEqual(A.classify(tx(sol=(1, 1 - fee), pre=[tb(TOKEN, 1000)], post=[tb(TOKEN, 400)]), W, PX), [])   # sent to someone
        self.assertEqual(A.classify(tx(sol=(1, 1 - 0.002 - fee), post=[tb(TOKEN, 5)]), W, PX), [])                   # an airdrop claim: rent only
        self.assertEqual(A.classify(tx(sol=(1, 2), signer=OTHER), W, PX), [])                                         # SOL sent to it
        self.assertEqual(A.classify(tx(sol=(1, 0), post=[tb(TOKEN, 5)], signer=OTHER), W, PX), [])                   # not its signature
        two = tx(pre=[tb(TOKEN, 10)], post=[tb(TOKEN, 0), tb("U" * 44, 3)])
        self.assertEqual(A.classify(two, W, PX), [])                                                                  # token for token
        self.assertEqual(A.classify(tx(sol=(10, 9), post=[tb(TOKEN, 1)], err={"x": 1}), W, PX), [])                  # failed
        self.assertEqual(A.classify(None, W, PX), [])


class TestPrefsAndWatch(unittest.TestCase):
    def test_prefs_have_bounds(self):
        self.assertEqual(A.prefs_of(None, 100), {"buys": True, "sells": True, "min_usd": 100.0})
        self.assertEqual(A.prefs_of({"buys": "yes", "sells": False, "min_usd": -5}), {"buys": True, "sells": False, "min_usd": 0.0})
        self.assertEqual(A.prefs_of({"min_usd": "abc"}, 50)["min_usd"], 50.0)
        p = A.prefs_of({"sells": False, "min_usd": 100})
        self.assertTrue(A.wants({"side": "buy", "usd": 150}, p))
        self.assertFalse(A.wants({"side": "buy", "usd": 99}, p))
        self.assertFalse(A.wants({"side": "sell", "usd": 1e6}, p))

    def test_who_watches_what(self):
        admin, user = "A" * 44, "B" * 44
        acc = [{"pubkey": admin, "telegram": {"chat": 1}, "alerts": {"min_usd": 500},
                "lists": {"main": {"name": "Main", "alerts": True}, "x": {"name": "Off"}},
                "wallets": {W: {"lists": ["main"], "added_ms": 2}, OTHER: {"lists": ["x"], "added_ms": 3}}},
               {"pubkey": user, "telegram": {"chat": 2}, "lists": {"main": {"name": "Main", "alerts": True}},
                "wallets": {W: {"lists": ["main"]}}},
               {"pubkey": "C" * 44, "lists": {"main": {"name": "Main", "alerts": True}}, "wallets": {W: {"lists": ["main"]}}}]
        wm = A.watch_map(acc, admins={admin})
        self.assertEqual(list(wm), [W])                                             # the list without the bell stays silent
        self.assertEqual([(s["chat"], s["lists"], s["prefs"]["min_usd"]) for s in wm[W]], [(1, ["Main"], 500.0)])
        wm = A.watch_map(acc, admins={admin}, open_to_all=True, default_min=100)
        self.assertEqual(sorted(s["chat"] for s in wm[W]), [1, 2])                  # no Telegram, no alerts
        acc[0]["lists"]["x"]["alerts"] = True
        self.assertEqual(list(A.watch_map(acc, admins={admin}, max_wallets=1)), [OTHER])   # the newest first, up to the cap


class TestCodesAndText(unittest.TestCase):
    def test_a_code_works_once_and_not_for_long(self):
        c = A.LinkCodes(ttl_s=600)
        code = c.issue("A" * 44, now=100)
        self.assertRegex(code, r"^[0-9a-f]{24}$")
        self.assertEqual(c.consume(code, now=200), "A" * 44)
        self.assertIsNone(c.consume(code, now=200))
        self.assertIsNone(c.consume(c.issue("A" * 44, now=100), now=800))

    def test_the_message_escapes_what_others_wrote(self):
        ev = {"side": "buy", "mint": TOKEN, "usd": 1234.5, "sig": "SIG9"}
        text = A.message(ev, W, {"lists": ["<b>Main</b>"]}, {"symbol": "<i>X</i>", "mcap": 250_000}, "https://dev.tracced.xyz")
        self.assertIn("🟢 <b>Buy · &lt;i&gt;X&lt;/i&gt;</b>", text)
        self.assertIn("&lt;b&gt;Main&lt;/b&gt;", text)
        self.assertIn("bought <b>$1.2K</b> at <b>$250K</b> cap", text)
        self.assertIn('href="https://dev.tracced.xyz/token?mint=' + TOKEN, text)
        self.assertIn("solscan.io/tx/SIG9", text)
        self.assertIn("🔴 <b>Sell", A.message(dict(ev, side="sell"), W, {}, {}))

    def test_token_facts_take_the_largest_pool(self):
        rep = {"token": {"symbol": "PAID"}, "pools": [{"liquidity": {"usd": 5}, "marketCap": {"usd": 1}},
                                                       {"liquidity": {"usd": 50}, "marketCap": {"usd": 250000}}]}
        self.assertEqual(A.token_facts(rep), {"symbol": "PAID", "mcap": 250000})
        self.assertEqual(A.token_facts(None), {"symbol": None, "mcap": None})


if __name__ == "__main__":
    unittest.main()
