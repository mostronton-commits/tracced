"""Telegram HTML widgets (Bot API 10.4, 09.11): cards drawn inside the chat, for now only the owner's (/prism, owner 09.11).

Only the pure part: each widget's HTML with its data baked in. A widget is one document with inline style and script, at
most 32 KB and 4 KB after zlib -9, offline: what it shows travels inside it, and what it asks the bot goes through
TelegramWidget.request (64 bytes out, 1 KB back). Production sends widgets to private chats only, so groups keep the
text answer of tgbot.early_text.

Two cards:
- the /early answer: candles around the pump with its window shaded, the wallets (tap one, and only that one opens with
  its numbers — how long it held among them — Copy, Solscan, Follow, and its buys and sells show on the chart as B and
  S), the launch facts. Two taps on the chart mark another range, and its button asks
  the bot to analyse it. The link to the analysis is the message's own button, under the card;
- the owner's live panel: what the site did today and what is left of each paid budget, asked for every 5 s while it is
  on screen.
Requests: "f:<wallet>" follow, "r:<mint>:<from>:<to>" (unix minutes, base 36) analyse a range, "s" the panel's numbers.
"""
import html
import json
import re
import zlib

from . import tgbot
from ..early import agent

MAX_HTML, MAX_Z = 32768, 4096
MINUTE = 60_000

BASE_CSS = """:root{color-scheme:light dark;--g:light-dark(#059669,#34D399);--l:light-dark(#DC2626,#F87171);--m:var(--tg-theme-hint-color,#64748B);--ln:var(--tg-theme-section-separator-color,#E2E8F0)}
*{box-sizing:border-box;margin:0}body{font:14px/1.35 system-ui,sans-serif;color:var(--tg-theme-text-color,#0F172A);padding:10px 12px 12px}
.n{font-family:ui-monospace,monospace;font-variant-numeric:tabular-nums}h1{font-size:16px;font-weight:700}.s{color:var(--m);font-size:12px}
.p{color:var(--g)}.q{color:var(--l)}.k{display:flex;gap:6px;margin-top:6px}
button{flex:1;border:0;border-radius:8px;padding:7px 4px;font:600 13px system-ui;background:var(--tg-theme-secondary-bg-color,#F1F5F9);color:var(--tg-theme-text-color,#0F172A)}
.a{background:#A7F3D0;color:#0F172A}"""

BASE_JS = """const T=window.TelegramWidget,D=JSON.parse(document.getElementById('d').textContent),$=s=>document.querySelector(s);
if(T)document.documentElement.style.colorScheme=T.colorScheme;
const M=v=>{const a=Math.abs(v),s=a>=1e6?(a/1e6).toFixed(1)+'M':a>=1e5?(a/1e3).toFixed(0)+'K':a>=1e3?(a/1e3).toFixed(1)+'K':a.toFixed(0);return(v<0?'−$':'$')+s.replace('.0','')};"""

EARLY_CSS = """#c{background:#090D16;border-radius:10px;margin:8px 0 6px;height:132px;position:relative;touch-action:pan-y;overflow:hidden}svg{display:block;width:100%;height:100%}
#c i{position:absolute;font:11px ui-monospace,monospace;color:#94A3B8;font-style:normal;pointer-events:none}
#c u{position:absolute;width:13px;height:13px;margin:-7px 0 0 -7px;border-radius:50%;background:#4ADE80;color:#052E16;font:700 8px/13px system-ui;text-align:center;text-decoration:none;box-shadow:0 0 0 1.5px #090D16;pointer-events:none}
#c u.x{background:#FB7185;color:#fff}.f svg{opacity:.5}
.r{display:flex;gap:8px;align-items:center;padding:8px 0;border-top:1px solid var(--ln)}
.r b{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-weight:600}.r b em{font-style:normal;font-weight:400;color:var(--m)}
.d{display:none;padding:0 0 10px}.o .d{display:block}.v{display:grid;grid-template-columns:repeat(auto-fit,minmax(52px,1fr));gap:4px}.v span{display:block;font-size:11px;color:var(--m)}
.t{color:light-dark(#92400E,#FBBF24);font-size:12px;margin-bottom:4px}.k button{padding:6px 4px}#L{margin-top:2px}"""

EARLY_JS = """const n=D.c.length/8,Z='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_',hm=m=>new Date(m*6e4).toISOString().slice(11,16);
const C=[];for(let i=0;i<n;i++){const q=[];for(let k=0;k<4;k++){const j=i*8+k*2;q.push(Z.indexOf(D.c[j])*64+Z.indexOf(D.c[j+1]))}C.push(q)}let A=-1,B=-1,O=-1;
function mk(){const s=O<0?'':D.r[O][11];let h='';for(let j=0;j<s.length;j+=3){const v=Z.indexOf(s[j])*64+Z.indexOf(s[j+1]),x=v>>1,sl=v&1;
h+='<u class="'+(sl?'x':'')+'" style="left:'+((x+.5)/n*100).toFixed(2)+'%;top:'+(124-Z.indexOf(s[j+2])/63*112).toFixed(0)+'px">'+(sl?'S':'B')+'</u>'}return h}
function chart(){const y=v=>(124-v/4095*112).toFixed(1),band=(a,b,o)=>'<rect x="'+a+'" width="'+(b-a+1)+'" height="132" fill="#A7F3D0" opacity="'+o+'"/>';
let g=band(D.a,D.b,.13)+(A<0?'':B<0?band(A,A,.45):band(A,B,.28));
C.forEach(([o,h,l,c],i)=>{const u=c>=o,f=u?'#34D399':'#F87171',t=y(Math.max(o,c)),bt=y(Math.min(o,c));
g+='<rect x="'+(i+.44)+'" width=".12" y="'+y(h)+'" height="'+Math.max(.5,y(l)-y(h)).toFixed(1)+'" fill="'+f+'"/><rect x="'+(i+.15)+'" width=".7" y="'+t+'" height="'+Math.max(1,bt-t).toFixed(1)+'" fill="'+f+'"/>'});
$('#c').innerHTML='<svg viewBox="0 0 '+n+' 132" preserveAspectRatio="none">'+g+'</svg><i style="right:8px;top:6px">'+M(D.hi)+'</i><i style="right:8px;bottom:6px">'+M(D.lo)+'</i>'
+(A<0&&O<0?'<i style="left:8px;top:6px">tap 2 points: new range</i>':'')+mk();$('#c').classList.toggle('f',O>=0&&!!D.r[O][11]);
const t=i=>D.t0+i*D.dt;$('#h').innerHTML=B<0?'':'<div class=k style="margin:0 0 6px"><button class=a id=g>Get wallets '+hm(t(A))+'–'+hm(t(B+1))+' UTC</button></div>'}
function rows(){let h='';D.r.forEach((r,i)=>{const[w,s,who,tg,e,x,pnl,roi,b,tk,l,,hd]=r,V=(k,v)=>'<div><span>'+k+'</span><b class=n>'+v+'</b></div>';
h+='<div class=i data-i='+i+'><div class=r><b>'+s+(who?' <em>'+who+'</em>':'')+'</b><span class="n s">'+M(e)+' → '+(x?M(x):'hold')+'</span><span class="n '+(pnl<0?'q':'p')+'">'+(roi<0?'−':'+')+Math.abs(roi)+'%</span></div>'
+'<div class=d>'+(tg?'<div class=t>'+tg+'</div>':'')+'<div class=v>'+V('PnL',(pnl<0?'−':'+')+M(Math.abs(pnl)))+V('In',M(b))+V('Out',M(tk))+(hd?V('Held',hd):'')+(l!=null?V('Unsold',M(l)):'')+'</div>'
+'<div class=k><button data-c='+i+'>Copy</button><button data-x='+i+'>Solscan</button><button class=a data-f='+i+'>☆ Follow</button></div></div></div>'});
$('#w').innerHTML=h||'<p class=s>'+D.e+'</p>'}
function ask(g,q,ok){if(!T)return;g.textContent='…';T.request(q).then(r=>{g.textContent=r.result=='ok'?ok:(r.result||'No answer')},e=>{g.textContent=e.code=='RATE_LIMITED'?'Too fast: tap again':'Not now'})}
chart();rows();$('#L').innerHTML=D.L.length?'<div class=s>'+D.L.join(' · ')+'</div>':'';
$('#c').addEventListener('click',e=>{const r=$('#c').getBoundingClientRect(),i=Math.max(0,Math.min(n-1,Math.floor((e.clientX-r.left)/r.width*n)));
if(A<0||B>=0){A=i;B=-1}else{B=Math.max(A,i);A=Math.min(A,i)}T&&T.HapticFeedback.selectionChanged();chart()});
document.addEventListener('click',e=>{const g=e.target,a=g.dataset;
if(g.id=='g')return ask(g,'r:'+D.m+':'+(D.t0+A*D.dt).toString(36)+':'+(D.t0+(B+1)*D.dt).toString(36),'Running: a new card comes');
if(a.c!=null){T&&T.copyText(D.r[a.c][0]);g.textContent='Copied';return}if(a.x!=null)return T&&T.openLink('https://solscan.io/account/'+D.r[a.x][0]);
if(a.f!=null)return ask(g,'f:'+D.r[a.f][0],'★ Following');
const it=g.closest('.i');if(it&&!g.closest('.d')){const o=it.classList.contains('o');document.querySelectorAll('.o').forEach(x=>x.classList.remove('o'));if(!o)it.classList.add('o');O=o?-1:+it.dataset.i;chart();T&&T.HapticFeedback.selectionChanged()}});"""

EARLY_BODY = '<h1>{sym}</h1><div class=s>pump {span} UTC</div><div id=c></div><div id=h></div><div id=w></div><div id=L></div>'

PANEL_CSS = """.g{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin:8px 0}.g div{min-width:0;background:var(--tg-theme-secondary-bg-color,#F1F5F9);border-radius:8px;padding:6px 8px}
.g b{display:block;font:700 18px ui-monospace,monospace}.m{margin-top:7px}.m div{height:6px;border-radius:3px;background:var(--ln);overflow:hidden;margin-top:3px}
.m div span{display:block;height:100%;background:var(--g)}.warn div span{background:#D97706}.crit div span{background:var(--l)}"""

PANEL_JS = """let at=0;const N=v=>v==null?'–':v>=1e4?M(v).slice(1):String(v);
function draw(x){if(!x)return;at=Date.now();const p=x.p||{};
$('#g').innerHTML=[['Active today',p.dau],['New wallets',p.new_today],['Analyses'+(p.runs_today_failed?' · '+p.runs_today_failed+' failed':''),p.runs_today],
['ST today',p.st_today],['Helius today',p.rpc_today],['Running',x.j]].map(([k,v])=>'<div><span class=s>'+k+'</span><b>'+N(v)+'</b></div>').join('');
$('#m').innerHTML=(x.m||[]).map(([k,l,o,pc,lv])=>'<div class="m '+lv+'"><span class=s>'+k+': <span class=n>'+N(l)+(o?' of '+N(o):'')+'</span></span><div><span style="width:'+(pc==null?0:pc)+'%"></span></div></div>').join('')
+'<div class=s style="margin-top:8px">Bot: '+N(x.b)+' alerts sent · '+N(x.e)+' errors</div>'}
function pull(){if(!T||!T.isActive)return;T.request('s').then(r=>{try{draw(JSON.parse(r.result))}catch(e){}},()=>{})}
setInterval(()=>{$('#u').textContent=at?'updated '+Math.round((Date.now()-at)/1e3)+' s ago':'waiting for the bot…'},1e3);
draw(D.x);pull();setInterval(pull,5100);T&&T.onEvent('activated',pull);"""

PANEL_BODY = '<h1>tracced · today</h1><div class=s id=u></div><div class=g id=g></div><div id=m></div>'


B64 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"
CANDLES = 72                     # the chart's candles: 4 KB with room for the wallets


def candles(raw, supply, a, b, n=CANDLES):
    """Price candles → n candles on an even grid from a to b (market cap: open, high, low, close), packed 8 characters
    each (four values 0..4095, two base-64 digits each); first minute; minutes per candle; the lowest and highest cap
    on the chart. Even steps let a tap turn into a time. A step with no trade repeats the last close. A source's shifted
    decimal does not flatten the chart: a candle 50x off the median is left out, and the scale follows opens and closes,
    so a broken wick is cut at the chart's edge."""
    raw = sorted((int(c["time"]), c) for c in raw or [] if c.get("close") and c.get("time") is not None)
    if raw:                                             # a price a source shifted by a decimal (PAIDDOGE's first close at
        mid = sorted(float(c["close"]) for _, c in raw)[len(raw) // 2]     # 1/150 of the rest) is not a candle
        raw = [(t, c) for t, c in raw if mid / 50 <= float(c["close"]) <= mid * 50
               and mid / 50 <= float(c.get("open") or c["close"]) <= mid * 50]
    if raw:
        a = max(a, raw[0][0] // MINUTE * MINUTE)        # a young token: the chart starts at its first trade
    t0, dt = a // MINUTE, max(1, -(-(b - a) // MINUTE) // n)
    if not raw or not supply:
        return "", t0, dt, 0, 0
    out, j, last = [], 0, float(raw[0][1].get("open") or raw[0][1]["close"]) * supply
    for i in range(n):
        lo_t, hi_t, got = (t0 + i * dt) * MINUTE, (t0 + (i + 1) * dt) * MINUTE, []
        while j < len(raw) and raw[j][0] < hi_t:
            if raw[j][0] >= lo_t:
                got.append(raw[j][1])
            j += 1
        if got:
            o = float(got[0].get("open") or got[0]["close"]) * supply
            c = float(got[-1]["close"]) * supply
            h = max(float(x.get("high") or x["close"]) for x in got) * supply
            l = min(float(x.get("low") or x["close"]) for x in got) * supply
            out.append((o, max(h, o, c), min(l, o, c), c))
            last = c
        else:
            out.append((last, last, last, last))
    lo = min(min(o, c) for o, _, _, c in out)
    hi = max(max(o, c) for o, _, _, c in out)
    pad = (hi - lo) * 0.08 or hi * 0.05 or 1
    lo, hi = max(0.0, lo - pad), hi + pad
    q = lambda v: max(0, min(4095, round((v - lo) / ((hi - lo) or 1) * 4095)))
    packed = "".join(B64[q(v) // 64] + B64[q(v) % 64] for cnd in out for v in cnd)
    return packed, t0, dt, lo, hi


def extremes(packed, lo, hi):
    """The lowest and highest open or close drawn, for the chart's labels: the scale's padding would read «$0» under a
    launch that started near zero (owner's $PUSSY card, 10.11)."""
    v = [B64.index(packed[i]) * 64 + B64.index(packed[i + 1]) for i in range(0, len(packed), 8)
         for i in (i, i + 6)]
    if not v:
        return lo, hi
    f = lambda x: lo + x / 4095 * (hi - lo)
    return f(min(v)), f(max(v))


MARKS = 14                       # a wallet's markers on the chart: its biggest steps, so a bot's 60 sells stay one card


def marks(trades, supply, t0, dt, k, lo, hi, n=MARKS):
    """One wallet's buys and sells on the card's chart (owner, 10.11: tap a wallet, see its trades), packed 3 characters
    each: candle and side (two base-64 digits, candle × 2 + 1 for a sell), then the market cap on the chart's scale
    (one digit, 0..63). Trades in one candle on one side are one marker at their dollar-weighted cap; the n biggest are
    kept; a trade outside the chart's span is not drawn (its numbers are in the row)."""
    by = {}
    for t in trades or []:
        side, at, usd, price = t[1], int(t[0]) // MINUTE, float(t[3] or 0), float(t[4] or 0)
        x = (at - t0) // dt
        if side not in ("buy", "sell") or not price or not 0 <= x < k:
            continue
        m = by.setdefault((x, side == "sell"), [0.0, 0.0])
        m[0] += usd or 1e-9
        m[1] += (usd or 1e-9) * price * supply
    top = sorted(by.items(), key=lambda kv: -kv[1][0])[:n]
    out = ""
    for (x, sell), (usd, cap_usd) in sorted(top):
        y = max(0, min(63, round((cap_usd / usd - lo) / ((hi - lo) or 1) * 63)))
        v = x * 2 + sell
        out += B64[v // 64] + B64[v % 64] + B64[y]
    return out


def early_card(symbol, mint, t_from, t_to, rows, names, result, raw_candles, supply, job_id, site, creator=None,
               min_profit=0, min_mult=0, price_ratio=1.0, around=None):
    """The /early answer as a widget. raw_candles: price candles over `around` (from, to), the chart's span; the window
    is shaded on it. Same wallets and facts as tgbot.early_text; the link to the analysis is the message's own button."""
    out, top = [], tgbot.top_rows(rows, min_profit=min_profit, min_mult=min_mult, creator=creator)
    trades = (result or {}).get("wallet_trades") or {}
    for r in top:
        w, idn = r["wallet"], (names or {}).get(r["wallet"]) or {}
        took, size, left = r.get("proceeds_usd") or 0, r.get("invested_usd") or 0, tgbot.unsold_now(r, price_ratio)
        pnl = took + (left or 0) - size
        who = re.sub(r"[<>&\"']", "", str(idn.get("twitter") or idn.get("name") or ""))[:16]
        out.append([w, tgbot.short(w), who, ", ".join(t for t in tgbot.SHOWN_TAGS if t in (r.get("tag_list") or [])),
                    round(r.get("entry_mcap_avg") or r.get("entry_range_mcap") or 0),
                    round((r.get("exit_mcap_avg") or 0) if took else 0), round(pnl),
                    round(pnl / size * 100) if size else 0, round(size), round(took), None if left is None else round(left),
                    "", agent.held(r.get("hold_minutes")) or ""])
    a, b = around or (t_from - 60 * MINUTE, t_to + 120 * MINUTE)
    launch = [html.unescape(re.sub(r"<[^>]+>", "", x)).lstrip("• ").rstrip(":")
              for x in tgbot.launch_lines(result or {}, creator, waiting=False)]
    sym = "$" + html.escape(str(symbol or tgbot.short(mint))[:16])
    for n in (CANDLES, 60, 48, 36):                     # over Telegram's 4 KB: fewer candles, not a missing card
        c, t0, dt, lo, hi = candles(raw_candles, supply, a, b, n)
        k = len(c) // 8
        idx = lambda t: max(0, min(k - 1, (t // MINUTE - t0) // dt)) if k else 0
        for row_, r in zip(out, top):
            row_[11] = marks((trades.get(r["wallet"]) or {}).get("trades"), supply, t0, dt, k, lo, hi) if k else ""
        lab_lo, lab_hi = extremes(c, lo, hi)
        data = {"c": c, "t0": t0, "dt": dt, "lo": round(lab_lo), "hi": round(lab_hi), "a": idx(t_from), "b": idx(t_to - 1),
                "m": mint, "r": out, "L": launch, "e": f"{tgbot.plural(len(rows or []), 'early wallet')}, none in profit."}
        doc = page(EARLY_CSS, EARLY_BODY.format(sym=sym, span=tgbot.span(t_from, t_to)), data, EARLY_JS)
        if fits(doc):
            break
    return doc


def panel_card(stats=None):
    """The owner's live panel; stats (panel_stats) drawn at once, then fresh ones every 5 s from the bot."""
    return page(PANEL_CSS, PANEL_BODY, {"x": stats}, PANEL_JS)


def panel_stats(pulse, meters, running, alerts):
    """What the panel shows, under the 1 KB of a widget answer: today's numbers (usage.summarize's pulse), each paid
    budget's meter, analyses running, the bot's alerts sent and errors."""
    keys = ("dau", "new_today", "runs_today", "runs_today_failed", "st_today", "rpc_today")
    p = {k: round(pulse.get(k) or 0) for k in keys}
    m = [[str(x.get("name")) + (" $" if x.get("key") == "ai" else ""), x.get("left"), x.get("of"), None if x.get("pct") is None else round(x["pct"]), x.get("level")]
         for x in meters or []]
    return {"p": p, "m": m, "j": running, "b": (alerts or {}).get("sent"), "e": (alerts or {}).get("errors")}


def page(css, body, data, js):
    """One document: style, body, the data as JSON (never as script: a token's symbol cannot break out of it), the
    script."""
    blob = json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    return (f"<!doctype html><meta charset=utf-8><style>{BASE_CSS}{css}</style>{body}"
            f"<script type=application/json id=d>{blob}</script><script>{BASE_JS}{js}</script>")


def sizes(html_):
    """(bytes, bytes after zlib -9): Telegram takes at most MAX_HTML and MAX_Z."""
    raw = html_.encode()
    return len(raw), len(zlib.compress(raw, 9))


def fits(html_):
    raw, z = sizes(html_)
    return raw <= MAX_HTML and z <= MAX_Z


def parse_query(data):
    """A widget's request → ("follow", wallet) | ("range", mint, from_ms, to_ms) | ("stats",) | None."""
    d = str(data or "")
    if d == "s":
        return ("stats",)
    if d.startswith("f:") and tgbot.ADDR.match(d[2:]):
        return ("follow", d[2:])
    parts = d.split(":")
    if len(parts) == 4 and parts[0] == "r" and tgbot.ADDR.match(parts[1]):
        try:
            a, b = int(parts[2], 36) * MINUTE, int(parts[3], 36) * MINUTE
        except ValueError:
            return None
        return ("range", parts[1], a, b) if a < b else None
    return None
