"""Ready lists: wallets worth following that a person can take in one click (owner, 07.10).

Solana Tracker only says who could be in a list; how much each one made is counted by tracced, from the wallet's own
swaps, the same way its card counts it (owner, 08.10: the list said +$2.31M where the card said $463K). Its boards
count as profit the tokens that came from another wallet with no purchase: Dolo sold $2.31M of RARI, $1.85M of it
moved in from elsewhere. So:

- KOLs: Solana Tracker's KOL roster, named wallets with an X account;
- Top traders: its board of all wallets, kept to where a person could be behind it;
- each candidate's month is read in full and counted by tracced's ledger; a list keeps the people (below) that made more
  than a floor, best first.

A list is a calendar month, the one before this (owner, 08.10: «топ трейдери за попередній місяць»): it changes once a
month, on the 1st (UTC), and says which month it is.

A person, not a machine (owner, 08.10: «боти, фреші, снайпери і ті, що роблять тисячі угод — відсікаємо»): a month of up
to 1,500 swaps and 300 tokens, at least 5 closed positions with a win rate between 30 and 90 %, an average hold of two
minutes or more and no more than half of the positions closed within a minute (a sniper's or a bot's pace), a first
trade a month before the list's month began (a fresh wallet is out), and nothing Solana Tracker marks as a bot, an
exchange or an arbitrageur.

Swaps of a memecoin into a tokenized stock (RACE, SKHY, SPCX) are real exits and count at the stock's price, the way the
card counts them.
"""
import calendar
import time

SIZE = 10
DAY = 86_400_000
LISTS = {
    "kols-30d": {"title": "KOLs · {month}", "kind": "kols",
                 "rule": "Known traders with a public X account who trade like people, ranked by the profit on what they "
                         "sold in {month}. tracced counts it from each wallet's own swaps, the same way as its card."},
    "top-traders-30d": {"title": "Top traders · {month}", "kind": "top",
                        "rule": "The most profitable wallets of {month} that trade like people, ranked by the profit on "
                                "what they sold. tracced counts it from each wallet's own swaps, the same way as its card."},
}
MAX_TRADES = 1500             # the board's pace: a month of about fifty trades a day
NOT_PEOPLE = {"bot", "exchange", "pool", "hacker", "spam_dusting"}
HUMAN = {"max_swaps": 1500, "max_tokens": 300, "min_closed": 5, "win_rate": [30.0, 90.0], "min_hold_min": 2.0,
         "max_quick_share": 0.5, "min_age_days": 30}


def prev_month(now_ms):
    """The calendar month before the one now_ms falls in, UTC: its key, bounds, name and when the next list is due."""
    t = time.gmtime(now_ms / 1000)
    y, m = t.tm_year, t.tm_mon
    py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    start = calendar.timegm((py, pm, 1, 0, 0, 0)) * 1000
    end = calendar.timegm((y, m, 1, 0, 0, 0)) * 1000
    return {"key": f"{py:04d}-{pm:02d}", "from": start, "to": end, "days": round((end - start) / DAY),
            "label": calendar.month_name[pm], "short": f"{calendar.month_abbr[pm]} {py}",
            "next": calendar.timegm((ny, nm, 1, 0, 0, 0)) * 1000,
            "next_label": f"{calendar.month_abbr[nm]} 1"}


def titled(slug, month):
    """A list's title and rule for its month."""
    d = LISTS[slug]
    return {"title": d["title"].format(month=month["label"]), "rule": d["rule"].format(month=month["label"]), "kind": d["kind"]}


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
                    "volume": float(p.get("volume") or 0), "days": p.get("tradingDays"), "type": i.get("type")})
    out.sort(key=lambda r: -r["realized"])
    return out[:n]


def is_person(t):
    """One row of /v2/pnl/leaderboard/top: worth counting at all? The board's top is bots (08.10: 763 of its 802 rows
    traded over 1,500 times in 30 days), so the pace goes first; the win rate and where the profit came from are checked
    on tracced's own count of the month (not_human), not on the board's."""
    p, c, i = t.get("period") or {}, t.get("counts") or {}, t.get("identity") or {}
    invested, realized = float(t.get("invested") or 0), float(p.get("realized") or 0)
    trades = int(c.get("trades") or 0)
    return 0 < trades <= MAX_TRADES and invested > 0 and realized > 0 and i.get("type") not in NOT_PEOPLE


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
                    "win_rate": float(t.get("winRate") or 0), "days": p.get("tradingDays"), "type": i.get("type"),
                    "apps": [str(x)[:20] for x in (i.get("platforms") or [])][:3]})
        if len(out) >= n:
            break
    return out


def counted(row, month):
    """A candidate with tracced's own count of the month (profile.summary over it): profit on what it sold, win rate,
    positions, its pace. The board's own sums stay out of sight; the month's summary rides along for the card."""
    month = month or {}
    wr = month.get("win_rate")
    who = {k: row.get(k) for k in ("wallet", "name", "x", "avatar")}
    return dict(who, pnl=float(month.get("pnl_usd") or 0.0), win_rate=None if wr is None else round(float(wr) * 100, 1),
                wins=int(month.get("wins") or 0), losses=int(month.get("losses") or 0), closed=int(month.get("closed") or 0),
                tokens=int(month.get("tokens") or 0), swaps=int(month.get("swaps") or 0), quick=int(month.get("quick") or 0),
                avg_hold=month.get("avg_hold_min"), partial=bool(month.get("partial")),
                month=month if month.get("pnl_usd") is not None else None)


def by_facts(facts, month_from, rules=None):
    """What the batch of Solana Tracker already says, before a request is spent on the wallet: a bot or a fresh one."""
    r, f = dict(HUMAN, **(rules or {})), facts or {}
    if f.get("arbitrage") or f.get("type") in NOT_PEOPLE:
        return "bot"
    ft = f.get("first_trade")
    if ft and ft > month_from - int(r["min_age_days"]) * DAY:
        return "fresh"
    return None


def not_human(row, month_from, facts=None, rules=None):
    """Why a counted wallet is not a person's trading (a word for the log and the dashboard), or None when it is."""
    r = dict(HUMAN, **(rules or {}))
    why = by_facts(facts, month_from, r)
    if why:
        return why
    if row.get("partial"):
        return "pace"                         # more swaps in the month than the pages read: thousands of them
    if row["swaps"] > int(r["max_swaps"]) or row["tokens"] > int(r["max_tokens"]):
        return "pace"
    if row["closed"] < int(r["min_closed"]):
        return "few"
    lo, hi = r["win_rate"]
    if row["win_rate"] is None or not lo <= row["win_rate"] <= hi:
        return "win rate"
    if row["avg_hold"] is not None and row["avg_hold"] < float(r["min_hold_min"]):
        return "sniper"
    if row["closed"] and row["quick"] / row["closed"] > float(r["max_quick_share"]):
        return "sniper"
    return None


def rank(rows, n=SIZE, min_pnl=0.0):
    """The list itself: wallets whose month was read in full and that made more than min_pnl in it, best first, at most
    n. A «top» of +$2.7K is not one (08.10: the tail of the first count)."""
    keep = [r for r in rows or [] if not r.get("partial") and (r.get("pnl") or 0) > max(0.0, float(min_pnl or 0))]
    keep.sort(key=lambda r: -r["pnl"])
    return keep[:n]


def summary(rows):
    """What a list's card says at a glance: how many, how much they made together, the best of them."""
    rows = rows or []
    return {"n": len(rows), "pnl": sum(r["pnl"] for r in rows), "best": max((r["pnl"] for r in rows), default=0.0)}
