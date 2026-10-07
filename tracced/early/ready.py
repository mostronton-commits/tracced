"""Ready lists: wallets worth following that a person can take in one click (owner, 07.10).

Solana Tracker only says who could be in a list; how much each one made is counted by tracced, from the wallet's own
swaps, the same way its card counts it (owner, 08.10: the list said +$2.31M where the card said $463K). Its boards
count as profit tokens that came with no purchase (transfers, airdrops) and token-for-token swaps at the new token's
paper price: Dolo's $2.31M was one swap of RARI into RACE, worth $2.4K a week later, and of the ten «top traders» seven
were at a loss by their own swaps. So:

- KOLs · 30 days: Solana Tracker's KOL roster, named wallets with an X account;
- Top traders · 30 days: its board of all wallets, kept to where a person could be behind it (a human pace, a trader's
  win rate, no bots or exchanges);
- then each candidate's last 30 days are read in full and counted by tracced's ledger; a list keeps the ones that made
  more than a floor, best first. A wallet whose 30 days do not fit the pages read is left out: its number would be a
  part of the month.

Swaps of a memecoin into a tokenized stock (RACE, SKHY, SPCX) are real exits and count at the stock's price, the way the
card counts them. What the boards add on top is tokens that came from another wallet with no purchase here.

Every list is ten wallets at most.
"""

SIZE = 10
LISTS = {
    "kols-30d": {"title": "KOLs · 30 days", "kind": "kols",
                 "rule": "Known traders with a public X account, ranked by the profit on what they sold in the last 30 "
                         "days. tracced counts it from each wallet's own swaps, the same way as its card."},
    "top-traders-30d": {"title": "Top traders · 30 days", "kind": "top",
                        "rule": "The most profitable wallets of the last 30 days that trade at a human pace, ranked by the "
                                "profit on what they sold. tracced counts it from each wallet's own swaps, the same way as "
                                "its card."},
}
# a person, not a machine: these bounds are what the 07.10 scan of the board needed to drop the bots
MAX_TRADES = 1500             # a month: about fifty a day
MAX_PROFIT_X = 20             # realized ÷ invested: above it, the «profit» is mostly tokens that came for free
WIN_RATE = (30.0, 90.0)       # below: noise; above: a bot or a wash trader
NOT_PEOPLE = {"bot", "exchange", "pool", "hacker", "spam_dusting"}


def _avatar(v):
    """An avatar URL from Solana Tracker goes into the page only as a plain https address."""
    if not isinstance(v, str) or not v.startswith("https://") or len(v) > 600 or any(c in v for c in "\"'<> \t\n"):
        return None
    return v


def _text(v, n):
    return None if v is None else str(v).strip()[:n] or None


def _handle(v):
    v = _text(v, 40)
    return v.lstrip("@") if v else None


def kols(raw, n=SIZE):
    """/v2/pnl/leaderboard/kols/period rows → candidates, in the board's order, at most n."""
    out = []
    for t in raw or []:
        w, p, i = t.get("wallet"), t.get("period") or {}, t.get("identity") or {}
        if not w or not isinstance(p.get("realized"), (int, float)):
            continue
        out.append({"wallet": w, "name": _text(i.get("name"), 32), "x": _handle(i.get("twitter")),
                    "avatar": _avatar(i.get("avatar")), "realized": float(p["realized"]),
                    "volume": float(p.get("volume") or 0), "days": p.get("tradingDays")})
    out.sort(key=lambda r: -r["realized"])
    return out[:n]


def is_person(t):
    """One row of /v2/pnl/leaderboard/top: could a person be trading this wallet?"""
    p, c, i = t.get("period") or {}, t.get("counts") or {}, t.get("identity") or {}
    invested, realized = float(t.get("invested") or 0), float(p.get("realized") or 0)
    trades, win = int(c.get("trades") or 0), float(t.get("winRate") or 0)
    return (0 < trades <= MAX_TRADES and invested > 0 and realized > 0 and realized / invested <= MAX_PROFIT_X
            and WIN_RATE[0] <= win <= WIN_RATE[1] and i.get("type") not in NOT_PEOPLE)


def traders(raw, n=SIZE):
    """/v2/pnl/leaderboard/top rows (several pages) → the first n that pass is_person, in the board's order, no repeats."""
    out, seen = [], set()
    for t in sorted(raw or [], key=lambda x: -float((x.get("period") or {}).get("realized") or 0)):
        w = t.get("wallet")
        if not w or w in seen or not is_person(t):
            continue
        seen.add(w)
        p, c, i = t.get("period") or {}, t.get("counts") or {}, t.get("identity") or {}
        out.append({"wallet": w, "name": _text(i.get("name"), 32), "x": _handle(i.get("twitter")),
                    "avatar": _avatar(i.get("avatar")), "realized": float(p.get("realized") or 0),
                    "invested": float(t.get("invested") or 0), "trades": int(c.get("trades") or 0),
                    "win_rate": float(t.get("winRate") or 0), "days": p.get("tradingDays"),
                    "apps": [str(x)[:20] for x in (i.get("platforms") or [])][:3]})
        if len(out) >= n:
            break
    return out


def counted(row, card):
    """A candidate with tracced's own 30 days (profile.card): profit on what it sold, win rate, positions, tokens."""
    p = ((card or {}).get("periods") or {}).get("30") or card or {}
    wr = p.get("win_rate")
    who = {k: row.get(k) for k in ("wallet", "name", "x", "avatar")}       # the board's own sums stay out of sight
    return dict(who, pnl=float(p.get("pnl_usd") or 0.0), win_rate=None if wr is None else round(float(wr) * 100, 1),
                wins=int(p.get("wins") or 0), losses=int(p.get("losses") or 0), tokens=int(p.get("tokens") or 0),
                swaps=int(p.get("swaps") or 0), partial=bool((card or {}).get("partial")))


def rank(rows, n=SIZE, min_pnl=0.0):
    """The list itself: wallets whose whole 30 days were read and that made more than min_pnl by them, best first, at
    most n. A «top» of +$2.7K is not one (08.10: the tail of the first count)."""
    keep = [r for r in rows or [] if not r.get("partial") and (r.get("pnl") or 0) > max(0.0, float(min_pnl or 0))]
    keep.sort(key=lambda r: -r["pnl"])
    return keep[:n]


def summary(rows):
    """What a list's card says at a glance: how many, how much they made together, the best of them."""
    rows = rows or []
    return {"n": len(rows), "pnl": sum(r["pnl"] for r in rows), "best": max((r["pnl"] for r in rows), default=0.0)}
