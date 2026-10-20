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
FALLBACK_MIN = 30
SHOWN_TAGS = ("launch-bundle", "own-bundle", "bundle", "sniper", "fresh", "bot-like")
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


def auto_window(candles, created, supply, now, max_hours=6):
    """The pump window when nobody marked one (spike of 18.10, rule A matched by eye on 3 of 3 tokens): from the
    token's creation to the first minute its market cap reached 3x its value at +10 min, within the first `max_hours`.
    Never reached → the first 30 minutes. `candles`: 1m price candles with time (ms), close and high.
    → (from, to, how) or None without data."""
    if not created or not supply:
        return None
    mc = sorted((int(c["time"]), float(c["close"]) * supply, float(c.get("high") or c["close"]) * supply)
                for c in candles or [] if c.get("close") and c.get("time") is not None)
    ref = created + 10 * MIN
    before = [x for x in mc if x[0] <= ref - MIN] or mc[:1]
    end_cap = min(now, created + max_hours * HOUR)
    if before and before[-1][1] > 0:
        base = before[-1][1]
        for t, _, hi in mc:
            if ref <= t <= end_cap and hi >= 3 * base:
                return created, min(t + MIN, end_cap), "launch → first 3x"
    to = min(created + FALLBACK_MIN * MIN, now)
    return (created, to, f"first {FALLBACK_MIN} min, no 3x in {max_hours} h") if to - created >= 2 * MIN else None


def how_of(job_owner, t_from, t_to, created):
    """How the window of an analysis the bot reuses was chosen: by the bot (from the token's creation) or by a person."""
    if job_owner == "system" and created and abs(t_from - created) < MIN:
        return (f"first {FALLBACK_MIN} min after launch" if abs(t_to - t_from - FALLBACK_MIN * MIN) < MIN
                else "launch → first 3x")
    return "range marked on tracced"


def top_rows(rows, n=TOP):
    """The wallets the message shows and Follow saves: most realized profit first, profitable ones only."""
    win = [r for r in rows or [] if (r.get("realized_usd") or 0) > 0]
    return sorted(win, key=lambda r: -r["realized_usd"])[:n]


def _who(idn):
    idn = idn if isinstance(idn, dict) else {}
    if idn.get("twitter"):
        return "@" + str(idn["twitter"]).lstrip("@")[:24]
    return str(idn.get("name") or "")[:24]


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
        out += " " + html.escape(who[:14])
    entry, exit_ = r.get("entry_range_mcap") or r.get("entry_mcap_avg"), r.get("exit_mcap_avg")
    out += f" · {money(entry)} → {money(exit_) if exit_ else 'holding'} · <b>+{money(r.get('realized_usd'))}</b>"
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


def early_text(symbol, mint, t_from, t_to, rows, names, result, creator=None, waiting=True):
    """The whole answer, short (owner, 20.10: «забагато тексту»): the token and its pump, the top wallets, the launch.
    rows: the analysis rows; names: identities by wallet. Stays under Telegram's 4096."""
    sym = html.escape(str(symbol or short(mint))[:16])
    lines = [f"<b>${sym}</b> · pump {span(t_from, t_to)} UTC", ""]
    top = top_rows(rows)
    if top:
        lines.append(f"<b>Top {len(top)} of {len(rows):,} early wallets</b>")
        lines += [wallet_line(r, names) for r in top]
    else:
        lines.append(f"{plural(len(rows or []), 'early wallet')}, none in profit yet.")
    launch = launch_lines(result or {}, creator, waiting)
    return "\n".join(lines + ([""] + launch if launch else []))[:4000]


def keyboard(job_id, site, follow=True):
    row = [{"text": "Open on tracced", "url": f"{site}/job/{job_id}"}]
    if follow:
        row.insert(0, {"text": "Follow these wallets", "callback_data": f"f:{job_id}"[:64]})
    return {"inline_keyboard": [row]}


def follow_job(data):
    """The analysis id a Follow button carries, or None."""
    d = str(data or "")
    return d[2:] if d.startswith("f:") and re.fullmatch(r"[A-Za-z0-9_-]{1,62}", d[2:]) else None


def list_name(symbol, mint):
    return f"{str(symbol or mint[:6])[:20]} early (Telegram)"[:32]


def utc(ms, short=False):
    return time.strftime("%H:%M" if short else "%d %b %H:%M", time.gmtime(int(ms) / 1000))


def span(a, b):
    """«15 Oct 20:16–20:50», з датою й у кінці, коли вікно переходить через північ UTC."""
    same = time.gmtime(int(a) / 1000)[:3] == time.gmtime(int(b) / 1000)[:3]
    return f"{utc(a)}–{utc(b, short=same)}"
