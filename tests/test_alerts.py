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

    def test_new_position_and_sold_all(self):
        fee = 5000 / 1e9
        ev, = A.classify(tx(sol=(10.0, 9.0 - fee), post=[tb(TOKEN, 1000)]), W, PX)
        self.assertTrue(ev["new"])
        ev, = A.classify(tx(sol=(10.0, 9.0 - fee), pre=[tb(TOKEN, 500)], post=[tb(TOKEN, 1500)]), W, PX)
        self.assertFalse(ev["new"])                                            # it held some: a top-up
        ev, = A.classify(tx(sol=(10.0, 9.0 - fee), pre=[tb(TOKEN, 5)], post=[tb(TOKEN, 1005)]), W, PX)
        self.assertTrue(ev["new"])                                             # dust before does not make it a top-up
        ev, = A.classify(tx(sol=(8.0, 9.0 - fee), pre=[tb(TOKEN, 1000)], post=[tb(TOKEN, 3)]), W, PX)
        self.assertTrue(ev["all"])                                             # dust left: sold out, as the site counts it
        ev, = A.classify(tx(sol=(8.0, 9.0 - fee), pre=[tb(TOKEN, 1000)], post=[tb(TOKEN, 400)]), W, PX)
        self.assertEqual((ev["all"], ev["pct"]), (False, 60))

    def test_a_crumb_of_another_token_does_not_hide_the_buy(self):
        # FOMO, 30.09: 100 USDC for 20M of a token, plus 0.0001 of another one — it was «token for token» and got lost
        ev, = A.classify(tx(pre=[tb(USDC, 100)], post=[tb(USDC, 0), tb(TOKEN, 20_005_184), tb("U" * 44, 0.0001)]), W, PX)
        self.assertEqual((ev["side"], ev["mint"], round(ev["usd"])), ("buy", TOKEN, 100))
        two = tx(pre=[tb(USDC, 100)], post=[tb(USDC, 0), tb(TOKEN, 50), tb("U" * 44, 3)])
        self.assertEqual(A.classify(two, W, PX), [])                                  # two real tokens: still not one trade

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

    def test_the_message_reads_like_a_trades_channel(self):
        ev = {"side": "buy", "mint": TOKEN, "usd": 1234.5, "sig": "SIG9", "new": True}
        sub = {"lists": ["Main"], "src": "W&F", "tags": ["<u>whale</u>", "kol"]}      # the pump it came from stays out
        text = A.message(ev, W, sub, {"symbol": "<i>X</i>", "mcap": 250_000}, "https://dev.tracced.xyz")
        self.assertEqual(text.split("\n"), [
            '🟡 <a href="https://dev.tracced.xyz/token?mint=' + TOKEN + '"><b>$&lt;i&gt;X&lt;/i&gt;</b></a> 🆕 · MC $250K · <a href="https://solscan.io/tx/SIG9">tx</a>',
            "<code>" + TOKEN + "</code>",
            '<a href="https://solscan.io/account/' + W + '">&lt;u&gt;whale&lt;/u&gt;, kol</a> · <b>$1.2K</b>'])
        self.assertNotIn(">" + A.short(W) + "<", text)                               # a tag stands for the wallet: no address
        self.assertNotIn("Main", text)
        again = A.message(ev, W, sub, {"symbol": "X"}, ca=False)
        self.assertNotIn(TOKEN + "</code>", again)                                   # the token's address only the first time
        self.assertEqual(len(again.split("\n")), 2)
        bare = A.message(dict(ev, new=False), W, {}, {})
        self.assertIn(">" + A.short(W) + "</a> · <b>$1.2K</b>", bare)              # no tag: the short address
        self.assertTrue(bare.startswith("🟡 <a href=\"https://tracced.xyz/token?mint=" + TOKEN + "\"><b>" + A.short(TOKEN) + "</b></a> · bought more · <a"), bare)
        self.assertIn("&amp;", A.message(ev, W, {}, {"symbol": "&" * 40}))              # cut before escaping: no half of an &amp;
        self.assertNotIn("&am<", A.message(ev, W, {}, {"symbol": "&" * 40}))

    def test_the_dot_is_the_size(self):
        self.assertEqual([A.size_dot(v) for v in (100, 999, 1000, 9999, 10000, 1e6)], ["🟢", "🟢", "🟡", "🟡", "🔴", "🔴"])
        self.assertEqual([A.size_dot(v, [500, 2000]) for v in (499, 500, 2000)], ["🟢", "🟡", "🔴"])     # from the settings
        self.assertEqual(A.size_dot(50, None), "🟢")
        ev = {"side": "sell", "mint": TOKEN, "usd": 25_000, "sig": "S", "all": True}
        self.assertTrue(A.message(ev, W, {}, {}).startswith("🔴 "))                  # a big sell is red, a big buy too

    def test_sold_from_the_start_of_the_position(self):
        tr = lambda kind, qty, tx, t=1: {"type": kind, "qty": qty, "tx": tx, "time": t * 1000}
        ev = {"side": "sell", "mint": TOKEN, "amount": 200, "sig": "B", "ts": 100, "usd": 50}
        self.assertEqual(A.sold_share([tr("buy", 1000, "a"), tr("sell", 400, "A", 2)], ev), (60, 20))     # 40% before, 20% now
        self.assertEqual(A.sold_share([tr("buy", 1000, "a")], dict(ev, amount=400)), (40, 40))            # the first sale
        self.assertEqual(A.sold_share([tr("buy", 1000, "a"), tr("sell", 400, "A", 2), tr("sell", 200, "B", 3)], ev), (60, 20))   # ST already has it
        self.assertEqual(A.sold_share([tr("buy", 1000, "a"), tr("sell", 1000, "x", 2), tr("buy", 500, "c", 3)], dict(ev, amount=250)), (50, 50))   # a new position
        self.assertEqual(A.sold_share([tr("buy", 1000, "a"), tr("sell", 300, "late", 500)], ev), (20, 20))   # a later trade is not this one's past
        self.assertIsNone(A.sold_share([tr("sell", 10, "s")], ev))                                          # no buys seen: unknown
        self.assertEqual(A.sold_text(dict(ev, total=60, step=20)), "sold 60% (+20%)")
        self.assertEqual(A.sold_text(dict(ev, total=40, step=40)), "sold 40%")
        self.assertEqual(A.sold_text(dict(ev, total=99, step=5)), "sold all")
        self.assertEqual(A.sold_text(dict(ev, all=True, total=70, step=10)), "sold all")
        self.assertEqual(A.sold_text(dict(ev, pct=35)), "sold 35%")                                        # no history: this sale's share
        self.assertIn("</a> · sold 60% (+20%) · <a", A.message(dict(ev, total=60, step=20), W, {}, {"symbol": "X"}))

    def test_a_sell_says_how_much_went(self):
        ev = {"side": "sell", "mint": TOKEN, "usd": 221, "sig": "S"}
        self.assertIn("</a> · sold all · <a", A.message(dict(ev, all=True, pct=100), W, {}, {"symbol": "X"}))
        self.assertIn("</a> · sold 40% · MC $3K · <a", A.message(dict(ev, all=False, pct=40), W, {}, {"symbol": "X", "mcap": 3000}))
        self.assertNotIn("sold", A.message(ev, W, {}, {}))                             # unknown share: no word
        self.assertNotIn("🆕", A.message(dict(ev, new=True), W, {}, {}))
        self.assertNotIn("bought", A.message(dict(ev, new=False), W, {}, {}))

    def test_token_facts_take_the_largest_pool(self):
        rep = {"token": {"symbol": "PAID"}, "pools": [{"liquidity": {"usd": 5}, "marketCap": {"usd": 1}},
                                                       {"liquidity": {"usd": 50}, "marketCap": {"usd": 250000}}]}
        self.assertEqual(A.token_facts(rep), {"symbol": "PAID", "mcap": 250000})
        self.assertEqual(A.token_facts(None), {"symbol": None, "mcap": None})


if __name__ == "__main__":
    unittest.main()
