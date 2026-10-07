"""Ready lists: wallets worth following that a person can take in one click (owner, 07.10).

Rankings come from Solana Tracker (the owner trusts its PnL), and we only choose and shape them; no network here.

- KOLs · 30 days: Solana Tracker's KOL roster, named wallets with an X account, by realized profit in 30 days.
- Top traders · 30 days: its leaderboard of all wallets, by realized profit, kept only when a person could be
  behind it. Measured on 07.10: the top of that board is bots and market makers (hundreds of thousands of trades a
  month, 98 % win rates) and wallets that «made» millions selling tokens they never bought ($61 in, $23M out). So a
  wallet stays when it trades at a human pace, its profit is not conjured from nothing, and its win rate is a
  trader's, not a bot's. Of the first 800 wallets on the board, 25 passed.

Every list is ten wallets: ten is also the number of alert bells one account has, so following a list turns on
alerts for all of it.
"""

SIZE = 10
LISTS = {
    "kols-30d": {"title": "KOLs · 30 days", "kind": "kols",
                 "rule": "Known traders with a public X account, by profit they realized in the last 30 days."},
    "top-traders-30d": {"title": "Top traders · 30 days", "kind": "top",
                        "rule": "The most profitable wallets of the last 30 days that trade at a human pace: up to 1,500 "
                                "trades a month, 10+ active days, a win rate between 30 and 90 %, no profit out of tokens "
                                "they never bought."},
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


def kols(raw):
    """/v2/pnl/leaderboard/kols/period rows → our rows, best first, at most SIZE."""
    out = []
    for t in raw or []:
        w, p, i = t.get("wallet"), t.get("period") or {}, t.get("identity") or {}
        if not w or not isinstance(p.get("realized"), (int, float)):
            continue
        out.append({"wallet": w, "name": _text(i.get("name"), 32), "x": _handle(i.get("twitter")),
                    "avatar": _avatar(i.get("avatar")), "realized": float(p["realized"]),
                    "volume": float(p.get("volume") or 0), "days": p.get("tradingDays")})
    out.sort(key=lambda r: -r["realized"])
    return out[:SIZE]


def is_person(t):
    """One row of /v2/pnl/leaderboard/top: could a person be trading this wallet?"""
    p, c, i = t.get("period") or {}, t.get("counts") or {}, t.get("identity") or {}
    invested, realized = float(t.get("invested") or 0), float(p.get("realized") or 0)
    trades, win = int(c.get("trades") or 0), float(t.get("winRate") or 0)
    return (0 < trades <= MAX_TRADES and invested > 0 and realized > 0 and realized / invested <= MAX_PROFIT_X
            and WIN_RATE[0] <= win <= WIN_RATE[1] and i.get("type") not in NOT_PEOPLE)


def traders(raw):
    """/v2/pnl/leaderboard/top rows (several pages) → the first SIZE that pass is_person, best first, no repeats."""
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
        if len(out) >= SIZE:
            break
    return out


def summary(rows):
    """What a list's card says at a glance: how many, how much they realized together, the best of them."""
    rows = rows or []
    return {"n": len(rows), "realized": sum(r["realized"] for r in rows),
            "best": max((r["realized"] for r in rows), default=0.0)}
