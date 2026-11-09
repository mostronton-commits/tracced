"""Telegram HTML widgets (Bot API 10.4, 09.11): cards drawn inside the chat, for now only the owner's (/prism, owner 09.11).

Only the pure part: each widget's HTML with its data baked in. A widget is one document with inline style and script, at
most 32 KB and 4 KB after zlib -9, offline: what it shows travels inside it, and what it asks the bot goes through
TelegramWidget.request (64 bytes out, 1 KB back). Production sends widgets to private chats only, so groups keep the
text answer of tgbot.early_text.

Two cards:
- the /early answer: the chart around the pump with its window, the wallets (tap one for its numbers, Copy, Solscan,
  Follow), the launch facts. Two taps on the chart mark another range, and its button asks the bot to analyse it;
- the owner's live panel: what the site did today and what is left of each paid budget, asked for every 5 s while it is
  on screen.
Requests: "f:<wallet>" follow, "r:<mint>:<from>:<to>" (unix minutes, base 36) analyse a range, "s" the panel's numbers.
"""
import html
import json
import re
import zlib

from . import tgbot

MAX_HTML, MAX_Z = 32768, 4096
POINTS = 120                     # the chart's points: a pump's shape, and 4 KB with room for the wallets
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

EARLY_CSS = """#c{background:#090D16;border-radius:10px;margin:8px 0 2px;height:104px;position:relative;touch-action:pan-y}svg{display:block;width:100%;height:100%}
#c i{position:absolute;top:6px;font:11px ui-monospace,monospace;color:#94A3B8;font-style:normal}#h{min-height:16px}
.r{display:flex;gap:8px;align-items:center;padding:7px 0;border-top:1px solid var(--ln)}
.r b{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-weight:600}
.d{display:none;padding:0 0 8px;font-size:13px}.o .d{display:block}.t{color:light-dark(#92400E,#FBBF24);font-size:12px}#L{margin-top:6px}"""

EARLY_JS = """const S=v=>(v<0?'−':'+')+M(Math.abs(v)),n=D.c.length,hm=m=>new Date(m*6e4).toISOString().slice(11,16);let A=-1,B=-1;
function chart(){const x=i=>(i/(n-1)*100).toFixed(2),y=v=>(98-v/999*84).toFixed(1);let p='';D.c.forEach((v,i)=>p+=(i?'L':'M')+x(i)+' '+y(v));
const band=(a,b,o)=>'<rect x="'+x(a)+'" width="'+(x(b)-x(a)).toFixed(2)+'" height="104" fill="#A7F3D0" opacity="'+o+'"/>';
const sel=A<0?'':B<0?band(A,Math.min(n-1,A+1),.6):band(A,B,.32);
$('#c').innerHTML='<svg viewBox="0 0 100 104" preserveAspectRatio="none">'+band(D.a,D.b,.16)+sel+'<path d="'+p+'" fill="none" stroke="#A7F3D0" stroke-width="1.6" vector-effect="non-scaling-stroke"/></svg><i style="left:8px">'+M(D.lo)+'</i><i style="right:8px">'+M(D.hi)+'</i>';
const t=i=>D.t0+i*D.dt;$('#h').innerHTML=A<0?'<span class=s>Tap the chart twice to mark another range</span>':B<0?'<span class=s>From '+hm(t(A))+' UTC… tap where it ends</span>':'<div class=k><button class=a id=g>Get wallets '+hm(t(A))+'–'+hm(t(B))+' UTC</button></div>'}
function rows(){let h='';D.r.forEach((r,i)=>{const[w,s,who,tg,e,x,pnl,roi,b,tk,l,nb,ns,fb]=r;
h+='<div class=i><div class=r><b>'+s+(who?' · '+who:'')+'</b><span class="n s">'+M(e)+' → '+(x?M(x):'holding')+'</span><span class="n '+(pnl<0?'q':'p')+'">'+(roi<0?'−':'+')+Math.abs(roi)+'%</span></div>'
+'<div class=d>'+(tg?'<div class=t>'+tg+'</div>':'')+'<div class=n>PnL '+S(pnl)+' · in '+M(b)+' · took '+M(tk)+(l!=null?' · left '+M(l):'')+'</div><div class=s>'+nb+' buys · '+ns+' sells · first buy '+fb+' UTC</div>'
+'<div class=k><button data-c='+i+'>Copy</button><button data-x='+i+'>Solscan</button><button class=a data-f='+i+'>☆ Follow</button></div></div></div>'});
$('#w').innerHTML=h||'<p class=s>'+D.e+'</p>'}
function ask(g,q,ok){if(!T)return;g.textContent='…';T.request(q).then(r=>{g.textContent=r.result=='ok'?ok:(r.result||'No answer')},e=>{g.textContent=e.code=='RATE_LIMITED'?'Too fast: tap again':'Not now'})}
chart();rows();$('#L').innerHTML=D.L.map(x=>'<div class=s>'+x+'</div>').join('');
$('#c').addEventListener('click',e=>{const r=$('#c').getBoundingClientRect(),i=Math.max(0,Math.min(n-1,Math.round((e.clientX-r.left)/r.width*(n-1))));
if(A<0||B>=0){A=i;B=-1}else if(i==A)return;else{B=Math.max(A,i);A=Math.min(A,i)}T&&T.HapticFeedback.selectionChanged();chart()});
document.addEventListener('click',e=>{const g=e.target,a=g.dataset;
if(g.id=='g')return ask(g,'r:'+D.m+':'+(D.t0+A*D.dt).toString(36)+':'+(D.t0+B*D.dt).toString(36),'Running: the card comes here');
if(a.c!=null)return T&&T.copyText(D.r[a.c][0]);if(a.x!=null)return T&&T.openLink('https://solscan.io/account/'+D.r[a.x][0]);
if(a.f!=null)return ask(g,'f:'+D.r[a.f][0],'★ In your watchlist');if(g.id=='o')return T&&T.openLink(D.u);
const it=g.closest('.i');if(it&&!g.closest('.d')){T&&T.HapticFeedback.selectionChanged();it.classList.toggle('o')}});"""

EARLY_BODY = ('<h1>{sym}</h1><div class=s>pump {span} UTC · early wallets, best first</div><div id=c></div><div id=h></div>'
              '<div id=w></div><div id=L></div><div class=k><button id=o class=a>Open on tracced</button></div>')

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


def series(pts, a, b, n=POINTS):
    """Caps [(t_ms, cap, …)] → (n caps on an even grid from a to b, scaled 0..999; first minute; minutes per point; the
    lowest and highest cap). Even steps let a tap on the chart turn into a time; each point is the last close at or
    before its moment (the first close before the first candle)."""
    pts = sorted(p for p in pts if p[1])
    if not pts:
        return [], a // MINUTE, 1, 0, 0
    t0, dt = a // MINUTE, max(1, -(-(b - a) // MINUTE) // (n - 1))
    out, j = [], 0
    for i in range(n):
        t = (t0 + i * dt) * MINUTE
        while j + 1 < len(pts) and pts[j + 1][0] <= t:
            j += 1
        out.append(pts[j][1])
    lo, hi = min(out), max(out)
    return [round((c - lo) / ((hi - lo) or 1) * 999) for c in out], t0, dt, lo, hi


def early_card(symbol, mint, t_from, t_to, rows, names, result, pts, job_id, site, creator=None, min_profit=0,
               min_mult=0, price_ratio=1.0, around=None):
    """The /early answer as a widget. pts: caps over `around` (from, to), the chart's span; the window is shaded on it.
    Same wallets and facts as tgbot.early_text."""
    out = []
    for r in tgbot.top_rows(rows, min_profit=min_profit, min_mult=min_mult, creator=creator):
        w, idn = r["wallet"], (names or {}).get(r["wallet"]) or {}
        took, size, left = r.get("proceeds_usd") or 0, r.get("invested_usd") or 0, tgbot.unsold_now(r, price_ratio)
        pnl = took + (left or 0) - size
        who = re.sub(r"[<>&\"']", "", str(idn.get("twitter") or idn.get("name") or ""))[:16]
        out.append([w, tgbot.short(w), who, ", ".join(t for t in tgbot.SHOWN_TAGS if t in (r.get("tag_list") or [])),
                    round(r.get("entry_mcap_avg") or r.get("entry_range_mcap") or 0),
                    round((r.get("exit_mcap_avg") or 0) if took else 0), round(pnl),
                    round(pnl / size * 100) if size else 0, round(size), round(took), None if left is None else round(left),
                    r.get("buys") or 0, r.get("sells") or 0, tgbot.utc(r.get("first_buy_ms") or t_from, short=True)])
    a, b = around or (t_from - 60 * MINUTE, t_to + 120 * MINUTE)
    c, t0, dt, lo, hi = series(pts, a, b)
    idx = lambda t: max(0, min(len(c) - 1, round((t // MINUTE - t0) / dt)))
    launch = [html.unescape(re.sub(r"<[^>]+>", "", x)) for x in tgbot.launch_lines(result or {}, creator, waiting=False)]
    data = {"c": c, "t0": t0, "dt": dt, "lo": round(lo), "hi": round(hi), "a": idx(t_from), "b": idx(t_to), "m": mint,
            "r": out, "u": f"{site}/job/{job_id}", "L": launch,
            "e": f"{tgbot.plural(len(rows or []), 'early wallet')}, none in profit."}
    sym = "$" + html.escape(str(symbol or tgbot.short(mint))[:16])
    return page(EARLY_CSS, EARLY_BODY.format(sym=sym, span=tgbot.span(t_from, t_to)), data, EARLY_JS)


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
