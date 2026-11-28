"""What search engines and AI assistants read about the site: robots.txt, the sitemap, llms.txt, the page's
structured data and its favicon.

Pure functions: they take what the server already holds and return text. No network, no aiohttp. The rules:
only pages a guest can read without a wallet are offered for indexing; every address has one spelling (the site's own
name without www, no tracking parameters); nothing here costs a provider request.
"""
import json
import struct
import time
from xml.sax.saxutils import escape

# one line that says what the site is, in the owner's own words (the link card, 08.10 and 12.10)
SUMMARY = ("tracced shows who bought a Solana token before it pumped and what each wallet did next: what it paid, "
           "what it sold and what it earned. Paste a token address, mark the pump on the chart, and get every wallet "
           "that bought in that range. Raw on-chain swaps only, no scores or \"smart money\" labels; every trade can "
           "be checked on Solscan. Free in beta.")
HOME_TITLE = "tracced · see who bought a Solana token before the pump"
HOME_DESC = "Paste a Solana token, mark the pump — see who bought before it and what they did next."

# addresses that are someone's cabinet, an action or raw data: never offered to a crawler. The patterns are Google's
# and Bing's dialect of robots.txt (* inside a path). *.json also keeps a crawler that renders the page from pulling
# the chart's candles, which can cost a provider request each
DISALLOW = ("/admin", "/me", "/auth/", "/api/", "/analyze", "/design", "/*.json", "/*.csv",
            "/*src=fresh")                      # a fresh pump nobody analysed: an overview is ~2 paid requests


def robots(site, private=False):
    """robots.txt. The closed copy shuts everything; the public site names what stays out and where the sitemap is."""
    if private:
        return "User-agent: *\nDisallow: /\n"
    lines = ["User-agent: *"] + ["Disallow: " + p for p in DISALLOW]
    lines += ["", f"Sitemap: {site}/sitemap.xml", ""]
    return "\n".join(lines)


def _day(ms):
    return time.strftime("%Y-%m-%d", time.gmtime((ms or 0) / 1000)) if ms else None


def sitemap(site, docs, lists, jobs):
    """sitemap.xml: home, the documentation, the ready lists, every token that has a finished analysis and every such
    analysis. `docs` and `lists` are slugs; `jobs` are (id, mint, finished_ms) of finished analyses. A token's date is
    its newest analysis."""
    urls = [(site + "/", None), (site + "/docs", None)]
    urls += [(f"{site}/docs/{s}", None) for s in docs if s != "index"]
    urls += [(f"{site}/lists/{s}", None) for s in lists]
    tokens = {}
    for _id, mint, done in jobs:
        tokens[mint] = max(tokens.get(mint) or 0, done or 0)
    urls += [(f"{site}/token?mint={m}", _day(ms)) for m, ms in sorted(tokens.items(), key=lambda kv: -kv[1])]
    urls += [(f"{site}/job/{i}", _day(done)) for i, _m, done in sorted(jobs, key=lambda j: -(j[2] or 0))]
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, day in urls[:50_000]:                       # the format's own ceiling for one file
        out.append(f"<url><loc>{escape(loc)}</loc>" + (f"<lastmod>{day}</lastmod>" if day else "") + "</url>")
    out.append("</urlset>")
    return "\n".join(out) + "\n"


def llms(site, docs, lists, analyses):
    """llms.txt (llmstxt.org): what the site is and where its plain-text pages are, for an assistant that answers a
    question about it. `docs` are {slug, label, blurb}; `lists` are {slug, title}; `analyses` are
    {id, symbol, wallets, fact} of the newest finished analyses."""
    out = ["# tracced", "", "> " + SUMMARY, "",
           "Solana only. Sign-in is a wallet signature, never a transaction. Numbers are counted from each wallet's "
           "own swaps on the token; the documentation says how, rule by rule.", "", "## Documentation", ""]
    for d in docs:
        path = "/docs.md" if d["slug"] == "index" else f"/docs/{d['slug']}.md"
        out.append(f"- [{d['label']}]({site}{path}): {d['blurb']}")
    out += ["", "## The product", "", f"- [Home]({site}/): paste a token address and mark the pump on its chart"]
    out += [f"- [{x['title']}]({site}/lists/{x['slug']}): a ready list of wallets, counted once a month" for x in lists]
    if analyses:
        out += ["", "## Recent analyses", ""]
        for a in analyses:
            n = a.get("wallets")
            bits = [f"{n:,} wallet{'s' if n != 1 else ''} bought in the marked range" if n else None, a.get("fact")]
            tail = "; ".join(b for b in bits if b)
            out.append(f"- [{a['symbol']}]({site}/job/{a['id']})" + (": " + tail if tail else ""))
    return "\n".join(out) + "\n"


def _ld(obj):
    """JSON for a <script type="application/ld+json">: '<' never appears, so no text can close the tag."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def home_ld(site):
    """Who publishes the site and what it is, in schema.org's words."""
    org = {"@type": "Organization", "@id": site + "/#org", "name": "tracced", "url": site + "/",
           "logo": site + "/static/brand/icon-180.png",
           "sameAs": ["https://x.com/tracced_xyz", "https://t.me/tracced_xyz"]}
    web = {"@type": "WebSite", "@id": site + "/#site", "url": site + "/", "name": "tracced", "description": HOME_DESC,
           "inLanguage": "en", "publisher": {"@id": site + "/#org"}}
    app = {"@type": "WebApplication", "@id": site + "/#app", "name": "tracced", "url": site + "/",
           "applicationCategory": "FinanceApplication", "operatingSystem": "Any", "browserRequirements": "A modern browser",
           "description": SUMMARY, "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
           "publisher": {"@id": site + "/#org"}}
    return _ld({"@context": "https://schema.org", "@graph": [org, web, app]})


def docs_ld(site, slug, title, blurb):
    """A documentation page: where it sits and what it is about."""
    url = site + ("/docs" if slug == "index" else "/docs/" + slug)
    crumbs = [{"@type": "ListItem", "position": 1, "name": "tracced", "item": site + "/"},
              {"@type": "ListItem", "position": 2, "name": "Docs", "item": site + "/docs"}]
    if slug != "index":
        crumbs.append({"@type": "ListItem", "position": 3, "name": title, "item": url})
    page = {"@type": "TechArticle", "headline": title, "url": url, "inLanguage": "en",
            "isPartOf": {"@id": site + "/#site"}, "publisher": {"@id": site + "/#org"}}
    if blurb:
        page["description"] = blurb
    return _ld({"@context": "https://schema.org", "@graph": [page, {"@type": "BreadcrumbList", "itemListElement": crumbs}]})


def ico(png):
    """A one-picture .ico around a PNG (the format allows a PNG inside): /favicon.ico for whoever asks for it blindly."""
    w, h = struct.unpack(">II", png[16:24])
    head = struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", w % 256, h % 256, 0, 0, 1, 32, len(png), 22)
    return head + png
