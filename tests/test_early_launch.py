"""Перевірка запуску (14.10): пакети Jito перших хвилин і комісія творця, без мережі."""
import struct
import unittest

from tracced.early import launch, ready, scope

T0 = 1_790_628_249_000
SUPPLY = 1_000_000_000


def tr(wallet, typ, sec, qty, tx):
    return {"wallet": wallet, "type": typ, "time": T0 + sec * 1000, "qty": qty, "tx": tx}


class FakeJito:
    """Пакети як у AI6: продаж D9v7 і покупка DVPS в одному пакеті; пакет творця з двома гаманцями."""
    def __init__(self, bundles):
        self.bundles, self.calls = bundles, 0

    def bundle_of(self, sig):
        self.calls += 1
        return next((b for b, v in self.bundles.items() if sig in v["txs"]), None)

    def bundle(self, bid):
        self.calls += 1
        return self.bundles[bid]


class TestDecode(unittest.TestCase):
    def test_update_fee_shares_names_the_wallet_and_its_share(self):
        pk = launch.b58decode("5MGjUr4SWqNRD8z2bae7Jo4TG73XqDeCqn62pJsosdJ4")
        data = launch.UPDATE_SHARES + struct.pack("<I", 1) + pk + struct.pack("<H", 10_000)
        self.assertEqual(launch.decode_shares(launch.b58encode(data)),
                         [("5MGjUr4SWqNRD8z2bae7Jo4TG73XqDeCqn62pJsosdJ4", 10_000)])

    def test_another_instruction_is_not_read_as_shares(self):
        self.assertIsNone(launch.decode_shares(launch.b58encode(bytes(8) + b"\x01\x00\x00\x00")))
        self.assertIsNone(launch.decode_shares(""))

    def test_base58_round_trip_keeps_leading_zeros(self):
        for raw in (b"\x00\x00\x01\x02", b"\xff" * 32, b""):
            self.assertEqual(launch.b58decode(launch.b58encode(raw)), raw)


class TestBundles(unittest.TestCase):
    def setUp(self):
        self.trades = [tr("CREATOR", "buy", 0, 30_000_000, "c1"), tr("A6u4", "buy", 0, 33_000_000, "c2"),
                       tr("D9v7", "buy", 0, 37_000_000, "c3"),
                       tr("D9v7", "sell", 2, 37_000_000, "s1"), tr("DVPS", "buy", 2, 36_700_000, "b1"),
                       tr("SNIPE", "sell", 3, 1_000_000, "s2"), tr("OTHER", "buy", 3, 900_000, "b2"),
                       tr("LATE", "sell", 900, 5_000_000, "s3")]
        self.jito = FakeJito({"LAUNCH": {"txs": ["c1", "c2", "c3"], "tippers": ["CREATOR"]},
                              "SELL1": {"txs": ["s1", "b1"], "tippers": ["D9v7"]},
                              "SNIPER": {"txs": ["s2"], "tippers": ["X"]}})

    def test_a_sell_and_a_buy_in_one_bundle_are_one_hand(self):
        f = launch.buybacks(self.trades, T0, 180_000, self.jito, creator="CREATOR")
        self.assertEqual([(p["seller"], [b[0] for b in p["buyers"]]) for p in f["pairs"]], [("D9v7", ["DVPS"])])
        self.assertEqual(f["launch"]["wallets"], ["A6u4", "D9v7"])          # the creator itself is not listed
        self.assertEqual(f["sells"], 2)                                      # the 15th minute is past the window

    def test_a_sniper_alone_in_its_bundle_is_no_pair(self):
        f = launch.buybacks(self.trades, T0, 180_000, self.jito)
        self.assertNotIn("SNIPE", [p["seller"] for p in f["pairs"]])
        self.assertIsNone(f["launch"])                                       # no creator given

    def test_biggest_sells_are_checked_first_under_the_cap(self):
        f = launch.buybacks(self.trades, T0, 180_000, self.jito, max_lookups=1)
        self.assertEqual([p["seller"] for p in f["pairs"]], ["D9v7"])
        self.assertTrue(f["capped"])

    def test_tags_and_summary(self):
        f = launch.buybacks(self.trades, T0, 180_000, self.jito, creator="CREATOR")
        f["fee"] = {"to": [["FEE", 10_000]], "paid": {"sol": 174.021}}
        self.assertEqual(launch.wallet_tags(f), {"D9v7": ["launch-bundle", "own-bundle"], "DVPS": ["own-bundle"],
                                                 "A6u4": ["launch-bundle"]})
        sm = launch.summary(f, SUPPLY)
        self.assertEqual((sm["pairs"], sm["bought_back_pct"], sm["launch_wallets"], sm["fee_sol"]), (1, 3.67, 2, 174.021))

    def test_buyers_outside_the_list_come_from_the_bundle_itself(self):
        jito = FakeJito({"SELL1": {"txs": ["s1", "zz"], "tippers": []}})

        def rpc(method, params):
            return {"meta": {"err": None,
                             "preTokenBalances": [{"mint": "M", "owner": "CURVE", "uiTokenAmount": {"uiAmount": 700_000_000}}],
                             "postTokenBalances": [{"mint": "M", "owner": "CURVE", "uiTokenAmount": {"uiAmount": 699_000_000}},
                                                   {"mint": "M", "owner": "SMALL", "uiTokenAmount": {"uiAmount": 1_000_000}}]}}
        f = launch.buybacks([tr("D9v7", "sell", 2, 37_000_000, "s1")], T0, 180_000, jito, rpc=rpc, mint="M", supply=SUPPLY)
        self.assertEqual(f["pairs"][0]["buyers"], [["SMALL", 1_000_000.0]])   # the curve holds most of the supply: not a buyer


class TestFee(unittest.TestCase):
    def test_the_last_update_names_the_wallet_and_the_paid_sol_is_summed(self):
        pk = launch.b58decode("5MGjUr4SWqNRD8z2bae7Jo4TG73XqDeCqn62pJsosdJ4")
        data = launch.b58encode(launch.UPDATE_SHARES + struct.pack("<I", 1) + pk + struct.pack("<H", 10_000))
        txs = {
            "setup": {"transaction": {"message": {"instructions": [
                {"programId": launch.FEE_PROGRAM, "accounts": ["G", "P", "CREATOR", "X", "MINT", "CONFIG"], "data": data}]}}},
            "d1": {"meta": {"logMessages": ["Program log: Instruction: DistributeCreatorFees"], "preBalances": [5, 0], "postBalances": [5, 40_970_000_000]},
                   "transaction": {"message": {"accountKeys": [{"pubkey": "PAYER"}, {"pubkey": "5MGjUr4SWqNRD8z2bae7Jo4TG73XqDeCqn62pJsosdJ4"}]}}},
            "other": {"meta": {"logMessages": ["Program log: Instruction: UpdateFeeShares"], "preBalances": [0, 0], "postBalances": [0, 9]},
                      "transaction": {"message": {"accountKeys": [{"pubkey": "PAYER"}, {"pubkey": "5MGjUr4SWqNRD8z2bae7Jo4TG73XqDeCqn62pJsosdJ4"}]}}},
        }

        def rpc(method, params):
            if method == "getSignaturesForAddress":
                if params[0] == "CREATOR":
                    return [{"signature": "setup", "blockTime": T0 // 1000 + 1, "slot": 2}]
                return [{"signature": "d1"}, {"signature": "other"}]
            return txs.get(params[0])
        fee = launch.fee_shares(rpc, "CREATOR", "MINT", T0)
        self.assertEqual((fee["to"], fee["config"]), ([["5MGjUr4SWqNRD8z2bae7Jo4TG73XqDeCqn62pJsosdJ4", 10_000]], "CONFIG"))
        paid = launch.fee_paid(rpc, "CONFIG", fee["to"][0][0])
        self.assertEqual((paid["sol"], paid["txs"]), (40.97, 1))


class TestRows(unittest.TestCase):
    def test_pack_keeps_the_signature_only_in_the_first_minutes(self):
        p = scope.pack([tr("W", "buy", 5, 1, "early"), tr("W", "sell", 600, 1, "later")], tx_until=T0 + 180_000)
        self.assertEqual([len(x) for x in p], [7, 6])
        self.assertEqual(scope.unpack("W", p)[0]["tx"], "early")
        self.assertIsNone(scope.unpack("W", p)[1]["tx"])

    def test_ready_lists_drop_the_launch_wallets(self):
        self.assertEqual(ready.by_facts({}, T0, wallet="DVPS", operators={"DVPS"}), "launch")
        self.assertIsNone(ready.by_facts({"first_trade": T0 - 400 * 86_400_000}, T0, wallet="HUMAN", operators={"DVPS"}))


if __name__ == "__main__":
    unittest.main()
