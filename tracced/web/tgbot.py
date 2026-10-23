"""Telegram /early (owner, 20.10): a token's early wallets and its launch facts, in a chat or a group.

Only the pure parts live here (what a message asks for, which window to analyse, what the answer reads, which buttons it
has), so they are tested without Telegram. The network side is in app.py, next to the bot loop. The bot never calls a
launch "clean": it lists the facts it found with a link to each proof, or says what it checked and found nothing.
"""
import html
import re
import time

MIN, HOUR = 60_000, 3_600_000
ADDR = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
TOP = 5
SHOWN_TAGS = ("bundle", "sniper", "fresh")
SKIP_TAGS = {"bot-like", "dev", "launch-bundle", "own-bundle"}
HELP = ("Send <code>/early &lt;token address&gt;</code> and I show the wallets that bought before its pump: entry and "
        "exit market cap, realized profit, and what the launch looked like on chain, each fact with its proof link.\n"
        "Add me to a group and the same command works there.")
COMMANDS = [{"command": "early", "description": "Early wallets and launch facts of a Solana token"}]


def parse_early(text, bot_name="", private=False):
    """What a message asks for. '/early <mint>' and '/early@bot <mint>' anywhere; a bare pasted address only in a
    private chat (in a group people paste addresses for other bots too). → the mint, "" for the command without a
    valid address, None when the message is not for /early (another bot's command included)."""
    t = str(text or "").strip()
    if not t:
        return None
    parts = t.split()                                       # пробіл чи новий рядок: адреса часто вставляється з нового
    cmd, _, to = parts[0].partition("@")
    if cmd.lower() == "/early":
        if to and bot_name and to.lower() != bot_name.lower():
            return None
        arg = parts[1] if len(parts) > 1 else ""
        return arg if ADDR.match(arg) else ""
    if private and not t.startswith("/") and ADDR.match(t):
        return t
    return None


ZONE_X, PUMP_X, NEW_HIGH_X = 1.5, 3.0, 2.0   # a range: highest close within 1.5x the lowest; a pump: 3x its low,
                                         # or 2x to a new high since the migration (LILLY, 21.10: a 2x bounce inside
                                         # the range it had kept for two days is not a pump)
ZONE_MAX, ZONE_MIN = HOUR, 8 * MIN       # the range before a breakout: at most an hour back, at least 8 minutes
TOP_SPAN = 3 * HOUR                      # a pump's size: what the cap gained in its first 3 hours
# a slow pump (Macca, 21.10: out of a 17-hour range over two hours, then on to a new high a day later) only shows on hourly
# candles: the range up to a day back and at least 3 h, its size over 12 h; its window up to 3 h before the climb
SLOW = {"zone_max": 24 * HOUR, "zone_min": 3 * HOUR, "top_span": 12 * HOUR}
HOLD_X = 1.45                            # ... back under 1.45x its range's low (a touch of 1.48x on Gato is not a fall)
SLOW_WINDOW, SLOW_FLAT, LATER = 3 * HOUR, 1.05, 6 * HOUR   # the climb begins past 1.05x the range's low; a slow pump
                                         # wins only 6 h+ after the fast one (on «1» a continuation came 2 h later)


def caps(candles, supply):
    """Price candles → [(t_ms, cap at the close, cap at the high)] by time."""
    return sorted((int(c["time"]), float(c["close"]) * supply, float(c.get("high") or c["close"]) * supply)
                  for c in candles or [] if c.get("close") and c.get("time") is not None and supply)


def _range_before(pts, e, zone_max=None, floor=0):
    """The trading range right before candle e: back while the highest close stays within ZONE_X of the lowest, no
    further than zone_max (ZONE_MAX) and not into the previous breakout (index floor).
    → (index of its first candle, its lowest cap)."""
    zone_max = zone_max or ZONE_MAX
    s, hi, lo = e - 1, pts[e - 1][1], pts[e - 1][1]
    while s > floor and pts[e][0] - pts[s - 1][0] <= zone_max:
        m = pts[s - 1][1]
        if max(hi, m) > ZONE_X * min(lo, m):
            break
        s, hi, lo = s - 1, max(hi, m), min(lo, m)
    return s, lo


def pumps(pts, zone_max=None, zone_min=None, top_span=None):
    """Pumps and the window before each (owner's markup of 21.10 on six charts: the window is the trading range right
    before the breakout; the end matched within minutes, the start within ~20). A breakout: the close crosses ZONE_X x
    the range's low; a pump: before the cap falls below that low it reaches PUMP_X x the low, or NEW_HIGH_X x the low
    and above everything since the migration. `top`: the highest cap in the first
    TOP_SPAN after the breakout, while it stays above the range's low; `gain` = top - low, in dollars.
    → [{start, end, low, top, gain}] by time."""
    zone_min, top_span = zone_min or ZONE_MIN, top_span or TOP_SPAN
    out, last, high = [], -1, 0.0
    for e in range(1, len(pts)):
        high = max(high, pts[e - 1][-1])                        # the highest cap before this candle (its wick: a launch
                                                                # spike to $566K lives in the highs, not the closes)
        if e - 1 <= last:
            continue                                            # right after a breakout: no range yet
        s, lo = _range_before(pts, e, zone_max, last + 1)       # PHP, 21.10: the range before the second wave starts
                                                                # after the first one's breakout, it is not a repeat
        if lo <= 0 or pts[e][0] - pts[s][0] < zone_min or pts[e][1] <= ZONE_X * lo:
            continue
        peak = top = pts[e][1]
        held = True
        for t, m, *_ in pts[e:]:
            if m < lo:
                break                                           # fell out of the range: the pump is over
            peak = max(peak, m)
            held = held and m > HOLD_X * lo                     # a wave that fell back under its breakout level is over:
            if held and t - pts[e][0] <= top_span:              # what came later is the next wave's (PHP's first wave)
                top = max(top, m)
        if peak >= PUMP_X * lo or (peak >= NEW_HIGH_X * lo and peak > high):
            out.append({"start": pts[s][0], "end": pts[e][0], "low": lo, "top": top, "gain": top - lo,
                        "new_high": peak > high})                   # over the whole run: Macca's came a day later
            last = e
    return out


def pick(found):
    """The pump to answer about: the biggest, by the dollars of market cap it added in its first TOP_SPAN. A multiple
    would crown the launch spike from $20K; dollars pick the owner's pump on four of five charts of 21.10 (hi four days
    after the launch, GLITCH the next evening, «1», COLLECTOOOR) and his second range on Gato. One answer, no buttons for
    the others (owner, 21.10: «зайве»): another range is marked on the site. → the pump or None."""
    return min(found or [], key=lambda p: (-p["gain"], p["end"]), default=None)


def hourly(pts):
    """5-minute caps → hourly: the last close of each hour and its highest high."""
    out = {}
    for t, c, *h in pts:
        k = t - t % HOUR
        o = out.get(k)
        out[k] = (k, c, max(h[0] if h else c, o[2] if o else 0))
    return [out[k] for k in sorted(out)]


def slow_pumps(pts):
    """Pumps over hours, on hourly candles, mapped back to the 5-minute caps: the window ends where the climb began (the
    last 5-minute close still within SLOW_FLAT x the lowest close of the 6 hours before the hourly breakout) and reaches
    up to SLOW_WINDOW back into the range."""
    out = []
    for p in pumps(hourly(pts), **SLOW):
        ref = min((q[1] for q in pts if p["end"] - 6 * HOUR <= q[0] < p["end"] + HOUR), default=p["low"])
        flat = [i for i, q in enumerate(pts) if q[0] < p["end"] + HOUR and q[1] <= SLOW_FLAT * ref]
        if not flat or flat[-1] + 1 >= len(pts):
            continue
        e = flat[-1] + 1
        s, _ = _range_before(pts, e, SLOW_WINDOW)
        out.append(dict(p, start=pts[s][0], end=pts[e][0], slow=True))
    return out


def choose(pts):
    """The pump to answer about: the biggest fast pump (pick); but when a slow pump to a new high came later and started
    a new run — the cap had fallen back under the first one's breakout level in between — that one: a token that has
    traded for days and pumped again is asked about for its latest pump (owner on Macca, 21.10). GLITCH's climb the next
    morning only went on from its evening pump, which stays."""
    best = pick(pumps(pts))

    def new_run(p):
        if best is None:
            return True
        between = [q[1] for q in pts if best["end"] < q[0] < p["start"]]
        return p["end"] > best["end"] + LATER and bool(between) and min(between) < ZONE_X * best["low"]
    later = [p for p in slow_pumps(pts) if p["new_high"] and new_run(p)]
    return later[-1] if later else best


def refine(coarse, fine):
    """The same pump on minute candles: the minute pump whose breakout is nearest (within 15 min); else the coarse one."""
    near = [p for p in pumps(fine) if abs(p["end"] - coarse["end"]) <= 15 * MIN]
    return min(near, key=lambda p: abs(p["end"] - coarse["end"])) if near else coarse


def launch_state(info):
    """Where the window may start (owner, 21.10: «до міграції нас не цікавить»): → ("migrated", ms), ("curve", None)
    for a pump.fun token whose curve is not finished, or ("dex", created) for a token launched straight on an exchange."""
    mig = (info.get("migration") or {}).get("ms")
    if mig:
        return "migrated", int(mig)
    curves = [p.get("curve") for p in info.get("pools") or [] if p.get("curve") is not None]
    if "pump.fun" in str(info.get("launchpad") or "") and (not info.get("pools") or any(c < 100 for c in curves)):
        return "curve", None
    return "dex", info.get("created_time")


def top_rows(rows, n=TOP, min_profit=0, min_mult=0, creator=None):
    """The wallets worth a look (owner, 20.10: «чи відфільтровується сміття?»): most realized profit first, among those
    that sold at min_mult x their entry on average and took at least min_profit dollars; never a bot-like wallet, the
    token's creator, or a wallet of the launch's own bundles (those are the launch's facts, not someone to follow)."""
    ok = [r for r in rows or [] if (r.get("realized_usd") or 0) > 0 and (r.get("realized_usd") or 0) >= min_profit
          and (r.get("multiple") or 0) >= min_mult and not set(r.get("tag_list") or ()) & SKIP_TAGS
          and r.get("wallet") != creator]
    return sorted(ok, key=lambda r: -r["realized_usd"])[:n]


X_HANDLE = re.compile(r"^@?([A-Za-z0-9_]{1,15})$")


def _who(idn):
    """Who the wallet is, as HTML: an X handle links to x.com (owner, 21.10: a bare @name opened a stranger's Telegram —
    Telegram links every @word to its own users); any other name has no @ for Telegram to pick up."""
    idn = idn if isinstance(idn, dict) else {}
    m = X_HANDLE.match(str(idn.get("twitter") or ""))
    if m:
        return f'<a href="https://x.com/{m.group(1)}">@{m.group(1)}</a>'
    name = str(idn.get("name") or "").lstrip("@").replace("@", "\uff20")[:14]
    return html.escape(name) if name else ""


def short(w):
    """«5sQ…9sv»: власник, 20.10 — у чаті не повні адреси, а перші й останні три знаки (посилання веде на повну)."""
    w = str(w or "")
    return f"{w[:3]}…{w[-3:]}" if len(w) > 8 else w


def money(v):
    """$619K, $1.2M, $9.5K, $37: у чаті без зайвих знаків після крапки."""
    v = float(v or 0)
    a = abs(v)
    s = (f"{a / 1e9:.1f}B" if a >= 1e9 else f"{a / 1e6:.1f}M" if a >= 1e6 else f"{a / 1e3:.0f}K" if a >= 1e5
         else f"{a / 1e3:.1f}K" if a >= 1e3 else f"{a:.0f}")
    return ("-$" if v < 0 else "$") + s.replace(".0B", "B").replace(".0M", "M").replace(".0K", "K")


def link(w, url="https://solscan.io/account/"):
    return f'<a href="{url}{html.escape(w)}">{html.escape(short(w))}</a>'


def wallet_line(r, names):
    w = r["wallet"]
    out = link(w)
    who = _who((names or {}).get(w))
    if who:
        out += " " + who
    entry, exit_ = r.get("entry_range_mcap") or r.get("entry_mcap_avg"), r.get("exit_mcap_avg")
    out += f" · {money(entry)} → {money(exit_) if exit_ else 'holding'}"
    if entry and exit_:                                 # owner, 23.10: how many x, what went in, what came out
        out += f" · <b>×{exit_ / entry:.1f}</b>"
    out += f" · {money(r.get('invested_usd'))} in"
    if r.get("proceeds_usd"):
        out += f", {money(r.get('proceeds_usd'))} out"
    sold = r.get("sold_share_pct")
    if sold is not None and float(sold) < 99.5:
        out += f" · holds {round(100 - float(sold)):g}%"
    tags = [t for t in SHOWN_TAGS if t in (r.get("tag_list") or [])]
    if tags:
        out += " · " + ", ".join(tags)
    return out


def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def launch_lines(r, creator=None, waiting=True):
    """What the launch check found: only facts, each with its proof link; or one line that it found nothing and how much
    it checked (never «clean»); or that it is still running. Nothing when it did not run for this analysis."""
    lc = r.get("launch")
    if lc is None:
        return ["Launch check: running…"] if waiting else []
    if lc.get("failed"):
        return ["Launch check: did not finish."]
    jito = "https://explorer.jito.wtf/bundle/"
    out = []
    launch = lc.get("launch") or {}
    if launch.get("wallets"):
        out.append(f'creator launched in one bundle with {plural(len(launch["wallets"]), "wallet")} '
                   f'(<a href="{jito}{html.escape(launch["bundle"])}">proof</a>)')
    pairs = lc.get("pairs") or []
    if pairs:
        out.append(f'{plural(len(pairs), "early sale")} bought back in the same bundle '
                   f'(<a href="{jito}{html.escape(pairs[0]["bundle"])}">proof</a>)')
    fee = lc.get("fee") or {}
    to = [x[0] for x in fee.get("to") or [] if x and x[0] != creator]
    if to:
        paid = (fee.get("paid") or {}).get("sol")
        out.append(f"creator fee goes to {link(to[0])}" + (f", {paid:g} SOL paid" if paid else ""))
    if out:
        return ["<b>Organised launch:</b>"] + ["• " + x for x in out]
    if lc.get("no_tx"):
        return []
    checked = int(lc.get("checked", lc.get("sells") or 0) or 0)
    return ["Launch: nothing organised found" + (f" · {plural(checked, 'early sale')} checked" if checked else "")]


def early_text(symbol, mint, t_from, t_to, rows, names, result, creator=None, waiting=True, min_profit=0, min_mult=0):
    """The whole answer, short (owner, 20.10: «забагато тексту»): the token and its pump, the wallets worth a look, the
    launch. rows: the analysis rows; names: identities by wallet. Stays under Telegram's 4096."""
    sym = html.escape(str(symbol or short(mint))[:16])
    lines = [f"<b>${sym}</b> · pump {span(t_from, t_to)} UTC", ""]
    top = top_rows(rows, min_profit=min_profit, min_mult=min_mult, creator=creator)
    if top:                                             # no «5 of 615 early wallets» line (owner, 21.10: says little)
        lines += [wallet_line(r, names) for r in top]
    else:
        bar = f"{min_mult:g}x+ and {money(min_profit)}+ profit" if min_profit or min_mult else "in profit"
        lines.append(f"{plural(len(rows or []), 'early wallet')}, none {bar}.")
    launch = launch_lines(result or {}, creator, waiting)
    return "\n".join(lines + ([""] + launch if launch else []))[:4000]


def keyboard(job_id, site):
    """One button: the whole analysis on the site. No «follow all five» (owner, 20.10): one tap would add wallets nobody
    picked; a single wallet is followed from its row there. No other pumps either (owner, 21.10: «зайве»)."""
    return {"inline_keyboard": [[{"text": "Open on tracced", "url": f"{site}/job/{job_id}"}]]}


def utc(ms, short=False):
    return time.strftime("%H:%M" if short else "%d %b %H:%M", time.gmtime(int(ms) / 1000))


def span(a, b):
    """«15 Oct 20:16–20:50», з датою й у кінці, коли вікно переходить через північ UTC."""
    same = time.gmtime(int(a) / 1000)[:3] == time.gmtime(int(b) / 1000)[:3]
    return f"{utc(a)}–{utc(b, short=same)}"
