"""What search engines and AI assistants are given: one address per page, a sitemap, llms.txt, and nothing that is
somebody's cabinet or costs a provider request."""
import json
import os
import struct
import tempfile
import unittest

try:
    from aiohttp.test_utils import AioHTTPTestCase
except ImportError:  # хост без aiohttp: тести сторінок пропускаються
    AioHTTPTestCase = None

from tracced.early import settings
from tracced.web import seo

try:
    from tests.test_early_pipeline import TRADES
except ImportError:
    from test_early_pipeline import TRADES

SITE = "https://tracced.xyz"


class TestSeoText(unittest.TestCase):
    def test_robots_names_the_sitemap_and_keeps_cabinets_and_raw_data_out(self):
        text = seo.robots(SITE)
        for line in ("User-agent: *", "Disallow: /admin", "Disallow: /me", "Disallow: /api/", "Disallow: /*.json",
                     "Disallow: /*src=fresh", "Sitemap: https://tracced.xyz/sitemap.xml"):
            self.assertIn(line + "\n", text)
        self.assertNotIn("Disallow: /\n", text)
        self.assertEqual(seo.robots(SITE, private=True), "User-agent: *\nDisallow: /\n")

    def test_sitemap_lists_pages_tokens_and_analyses_once_each(self):
        day = 1_795_000_000_000                                           # 2026-11-18
        xml = seo.sitemap(SITE, ["index", "how-it-works"], ["top-traders"],
                          [("aaa_1", "MINTA", day), ("aaa_2", "MINTA", day + 86_400_000), ("bbb_1", "MINT&B", None)])
        self.assertTrue(xml.startswith('<?xml version="1.0" encoding="UTF-8"?>'))
        for loc in (SITE + "/", SITE + "/docs", SITE + "/docs/how-it-works", SITE + "/lists/top-traders",
                    SITE + "/job/aaa_1", SITE + "/job/aaa_2", SITE + "/job/bbb_1"):
            self.assertEqual(xml.count(f"<loc>{loc}</loc>"), 1, loc)
        self.assertNotIn("/docs/index", xml)                              # the overview has one address: /docs
        self.assertEqual(xml.count("/token?mint=MINTA<"), 1)              # two analyses, one token page
        self.assertIn("<loc>https://tracced.xyz/token?mint=MINTA</loc><lastmod>2026-11-19</lastmod>", xml)   # its newest
        self.assertIn("/token?mint=MINT&amp;B</loc></url>", xml)          # escaped, and no date when none is known
        self.assertEqual(xml.count("<url>"), 9)

    def test_sitemap_is_well_formed_xml(self):
        from xml.dom import minidom
        doc = minidom.parseString(seo.sitemap(SITE, ["index"], [], [("a<b", "M\"1", 5)]))
        self.assertEqual(len(doc.getElementsByTagName("url")), 4)

    def test_llms_txt_links_the_plain_text_docs_and_recent_analyses(self):
        text = seo.llms(SITE, [{"slug": "index", "label": "Overview", "blurb": "What tracced answers"},
                               {"slug": "tags", "label": "Tags", "blurb": "Nine rules"}],
                        [{"slug": "top-traders", "title": "Top traders · October"}],
                        [{"id": "aaa_1", "symbol": "TST", "wallets": 1280, "fact": "Organised launch"},
                         {"id": "bbb_1", "symbol": "NOP", "wallets": None, "fact": None}])
        self.assertTrue(text.startswith("# tracced\n\n> tracced shows who bought a Solana token before it pumped"))
        self.assertIn("- [Overview](https://tracced.xyz/docs.md): What tracced answers\n", text)
        self.assertIn("- [Tags](https://tracced.xyz/docs/tags.md): Nine rules\n", text)
        self.assertIn("- [Top traders · October](https://tracced.xyz/lists/top-traders)", text)
        self.assertIn("- [TST](https://tracced.xyz/job/aaa_1): 1,280 wallets bought in the marked range; Organised launch\n", text)
        self.assertIn("- [NOP](https://tracced.xyz/job/bbb_1)\n", text)
        self.assertNotIn("Recent analyses", seo.llms(SITE, [], [], []))

    def test_structured_data_is_json_that_cannot_close_its_script_tag(self):
        home = json.loads(seo.home_ld(SITE))
        self.assertEqual([x["@type"] for x in home["@graph"]], ["Organization", "WebSite", "WebApplication"])
        self.assertEqual(home["@graph"][2]["offers"]["price"], "0")
        raw = seo.docs_ld(SITE, "tags", "Tags </script><b>", "Nine rules")
        self.assertNotIn("<", raw)
        doc = json.loads(raw)
        self.assertEqual(doc["@graph"][0]["headline"], "Tags </script><b>")
        self.assertEqual([c["item"] for c in doc["@graph"][1]["itemListElement"]],
                         [SITE + "/", SITE + "/docs", SITE + "/docs/tags"])
        self.assertEqual(len(json.loads(seo.docs_ld(SITE, "index", "Overview", None))["@graph"][1]["itemListElement"]), 2)

    def test_indexnow_body_names_our_host_and_the_key_file(self):
        body = seo.indexnow_body(SITE, "k" * 32, [SITE + "/job/a", SITE + "/"])
        self.assertEqual(body, {"host": "tracced.xyz", "key": "k" * 32, "keyLocation": "https://tracced.xyz/indexnow.txt",
                                "urlList": ["https://tracced.xyz/job/a", "https://tracced.xyz/"]})
        self.assertEqual(len(seo.indexnow_body(SITE, "k", [str(i) for i in range(12_000)])["urlList"]), 10_000)

    def test_ico_wraps_the_png_whole(self):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 32, 32) + b"rest-of-the-picture"
        ico = seo.ico(png)
        self.assertEqual(struct.unpack("<HHH", ico[:6]), (0, 1, 1))
        w, h, _c, _r, _planes, _bpp, size, offset = struct.unpack("<BBBBHHII", ico[6:22])
        self.assertEqual((w, h, size, offset), (32, 32, len(png), 22))
        self.assertEqual(ico[22:], png)


if AioHTTPTestCase:
    try:
        from tests.test_web import FakeWebST, MINT, TEST_PK, wallet_cookie
    except ImportError:
        from test_web import FakeWebST, MINT, TEST_PK, wallet_cookie
    from tracced.web.app import create_app

    JID = "AAAAAA_20010909-0146_0206"

    def stored_job():
        return {"id": JID, "mint": MINT, "t_from": 999999960000, "t_to": 1000001160000, "t_exit": None, "status": "done",
                "error": None, "created_ms": 1_795_000_000_000, "started_ms": 1_795_000_000_000, "finished_ms": 1_795_000_000_000,
                "symbol_hint": "TST", "progress": {"phase": "done", "done": 1, "total": 1}, "log": ["done"],
                "result": {"info": {"mint": MINT, "symbol": "TST", "supply": 1000000, "created_time": 999996400000},
                           "window": {"from": 999999960000, "to": 1000001160000, "end": 1000003560000}, "mode": "wallet-trades",
                           "counts": {"n_wallets": 1, "n_trades": 3, "n_early": 1, "dust": 0, "late": 0, "pre_range_only": 0, "lookups": 1, "entry_only": 0},
                           "coverage": {"exits_known": 1, "total": 1, "mode": "wallet-trades", "cost_full": 5, "lookup_cap": 500, "plan": "free"},
                           "wallet_trades": {"A": {"trades": [[1000000060000, "buy", 100.0, 100.0, 1.0]], "source": "wallet"}},
                           "price_at_end": 3.0, "fresh_wallets": [], "scope": "all", "rows": [], "summary": {}, "requests": 0, "pages_fetched": 0,
                           "enrich": {"done": 0, "total": 0, "fresh": 0, "failed": 0, "funders_done": 0}}}

    class TestSeoPages(AioHTTPTestCase):
        async def get_application(self):
            self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
            os.makedirs(self.tmp.name + "/web")
            with open(f"{self.tmp.name}/web/{JID}.json", "w") as f:
                json.dump(stored_job(), f)
            self.st = FakeWebST(TRADES)
            s = settings.load()
            s["private_hosts"] = ["dev.example"]
            s["design_v2"] = "all"                                       # the look everyone gets since 0.8.0
            app = create_app(self.st, s, {}, out_dir=self.tmp.name + "/web", store_dir=self.tmp.name + "/cache")
            app["admins"] = {TEST_PK}
            return app

        async def tearDownAsync(self):
            await self.client.close()
            self.tmp.cleanup()

        async def test_home_has_a_title_one_address_and_says_what_it_is(self):
            html = await (await self.client.get("/")).text()
            self.assertIn("<title>tracced · see who bought a Solana token before the pump</title>", html)
            self.assertIn('<link rel="canonical" href="https://tracced.xyz/">', html)
            self.assertNotIn('name="robots"', html)
            ld = json.loads(html.split('<script type="application/ld+json">')[1].split("</script>")[0])
            self.assertEqual(ld["@graph"][0]["name"], "tracced")
            self.assertNotIn("google-site-verification", html)             # no code set: no tag
            self.app["s"]["google_site_verification"] = "g-code"
            self.app["s"]["bing_site_verification"] = "b-code"
            html = await (await self.client.get("/")).text()
            self.assertIn('<meta name="google-site-verification" content="g-code">', html)
            self.assertIn('<meta name="msvalidate.01" content="b-code">', html)

        async def test_docs_have_their_own_description_address_and_a_plain_text_twin(self):
            html = await (await self.client.get("/docs/tags")).text()
            self.assertIn('<link rel="canonical" href="https://tracced.xyz/docs/tags">', html)
            self.assertIn('<meta name="description" content="Nine rules, each one checkable on chain. tracced documentation.">', html)
            self.assertIn('"@type":"BreadcrumbList"', html)
            html = await (await self.client.get("/docs")).text()
            self.assertIn('<link rel="canonical" href="https://tracced.xyz/docs">', html)
            for path, canon in (("/docs/tags.md", "/docs/tags"), ("/docs.md", "/docs")):
                r = await self.client.get(path)
                text = await r.text()
                self.assertEqual((r.status, r.content_type), (200, "text/markdown"), path)
                self.assertTrue(text.startswith("# "), path)
                self.assertNotIn("{{", text, path)                         # numbers are filled in, as on the site
                self.assertEqual(r.headers["X-Robots-Tag"], "noindex", path)
                self.assertEqual(r.headers["Link"], f'<https://tracced.xyz{canon}>; rel="canonical"', path)
            self.assertEqual((await self.client.get("/docs/nope.md")).status, 404)

        async def test_an_analysis_and_its_token_are_pages_a_bare_chart_is_not(self):
            html = await (await self.client.get("/job/" + JID)).text()
            self.assertIn("<title>Who bought TST before the pump · tracced</title>", html)
            self.assertIn(f'<link rel="canonical" href="https://tracced.xyz/job/{JID}">', html)
            self.assertIn('content="1 wallet bought TST in the marked range before the pump', html)
            html = await (await self.client.get(f"/token?mint={MINT}&src=live")).text()
            self.assertIn("<title>TST · who bought before the pump · tracced</title>", html)
            self.assertIn(f'<link rel="canonical" href="https://tracced.xyz/token?mint={MINT}">', html)   # no src in it
            other = "B" * 44
            html = await (await self.client.get(f"/token?mint={other}")).text()
            self.assertNotIn('rel="canonical"', html)
            self.assertIn('<meta name="robots" content="noindex">', html)

        async def test_guides_are_pages_with_their_own_menu_and_plain_text(self):
            import re
            from tracced.web import docs as docs_mod
            for g in docs_mod.GUIDES:
                path = "/guides" if g[0] == "index" else "/guides/" + g[0]
                r = await self.client.get(path)
                html = await r.text()
                self.assertEqual(r.status, 200, path)
                self.assertIn(f'<link rel="canonical" href="https://tracced.xyz{path}">', html, path)
                self.assertIn('<span class="dn-h">Guides</span>', html, path)
                body = html.split('<article class="docs-body')[1].split("</article>")[0]
                self.assertIsNone(re.search(r"[\u0400-\u04FF]", body), path)          # no Cyrillic on the site's pages
                for href in re.findall(r'href="(/[^"#?]*)', body):                  # every link inside a guide leads somewhere
                    if href.startswith(("/lists/", "/job/")):
                        continue                                                    # a ready list and a real analysis live only on the site
                    self.assertEqual((await self.client.get(href)).status, 200, (path, href))
                r = await self.client.get(path + ".md" if g[0] != "index" else "/guides.md")
                self.assertEqual((r.status, r.content_type), (200, "text/markdown"), path)
            html = await (await self.client.get("/guides/dev-sold")).text()
            self.assertIn("<title>Dev sold: what it means and how to check it · tracced</title>", html)
            xml = await (await self.client.get("/sitemap.xml")).text()
            self.assertIn("<loc>https://tracced.xyz/guides</loc>", xml)
            self.assertIn("<loc>https://tracced.xyz/guides/check-if-a-coin-is-bundled</loc>", xml)
            self.assertIn("(https://tracced.xyz/guides/dev-sold.md)", await (await self.client.get("/llms.txt")).text())
            self.assertEqual((await self.client.get("/guides/nope")).status, 404)

        async def test_cabinets_forms_and_errors_stay_out_of_search(self):
            for path in ("/me", "/feedback", "/no-such-page"):
                html = await (await self.client.get(path)).text()
                self.assertIn('<meta name="robots" content="noindex">', html, path)
                self.assertNotIn('rel="canonical"', html, path)

        async def test_sitemap_llms_and_favicon_answer_without_a_provider_request(self):
            before = self.st.requests
            r = await self.client.get("/sitemap.xml")
            xml = await r.text()
            self.assertEqual((r.status, r.content_type), (200, "application/xml"))
            for loc in ("https://tracced.xyz/", "https://tracced.xyz/docs/how-it-works", f"https://tracced.xyz/job/{JID}",
                        f"https://tracced.xyz/token?mint={MINT}"):
                self.assertIn(f"<loc>{loc}</loc>", xml)
            self.assertIn("<lastmod>2026-11-18</lastmod>", xml)
            for private in ("/me", "/admin", "/feedback"):
                self.assertNotIn(f"tracced.xyz{private}<", xml)
            r = await self.client.get("/llms.txt")
            text = await r.text()
            self.assertEqual((r.status, r.content_type), (200, "text/plain"))
            self.assertIn(f"- [TST](https://tracced.xyz/job/{JID}): 1 wallet bought in the marked range", text)
            self.assertIn("(https://tracced.xyz/docs/how-it-works.md)", text)
            r = await self.client.get("/favicon.ico")
            body = await r.read()
            self.assertEqual((r.status, r.content_type, body[:4]), (200, "image/x-icon", b"\x00\x00\x01\x00"))
            self.assertIn("Sitemap: https://tracced.xyz/sitemap.xml", await (await self.client.get("/robots.txt")).text())
            self.assertEqual(self.st.requests, before)

        async def test_indexnow_key_file_and_a_finished_analysis_waits_to_be_told(self):
            self.assertEqual((await self.client.get("/indexnow.txt")).status, 404)      # no key: no file
            self.app["s"]["indexnow_key"] = "abc123"
            r = await self.client.get("/indexnow.txt")
            self.assertEqual((r.status, await r.text()), (200, "abc123"))
            self.assertEqual((await self.client.get("/indexnow.txt", headers={"Host": "dev.example"})).status, 403)
            r = await self.client.post("/analyze", data={"mint": MINT, "from": "2001-09-09T02:30", "to": "2001-09-09T02:50"},
                                       headers={"Cookie": wallet_cookie(TEST_PK), "Origin": f"http://{self.client.host}:{self.client.port}"},
                                       allow_redirects=False)
            self.assertIn(r.status, (302, 303))
            import asyncio
            await asyncio.to_thread(self.app["jobs"].q.join)
            jid = r.headers["Location"].split("/job/")[1].split("?")[0]
            self.assertEqual(self.app["indexnow"], {f"/job/{jid}", f"/token?mint={MINT}"})

        async def test_www_moves_to_the_bare_name_for_pages_only(self):
            www = {"Host": "www.tracced.xyz"}
            r = await self.client.get("/docs/tags?x=1", headers=www, allow_redirects=False)
            self.assertEqual((r.status, r.headers["Location"]), (301, "https://tracced.xyz/docs/tags?x=1"))
            r = await self.client.post("/auth/nonce", headers=dict(www, Origin="https://www.tracced.xyz"), allow_redirects=False)
            self.assertNotEqual(r.status, 301)
            r = await self.client.get("/", headers={"Host": "www.elsewhere.example"}, allow_redirects=False)
            self.assertEqual(r.status, 200)                                # only our own www

        async def test_the_closed_copy_offers_nothing(self):
            dev = {"Host": "dev.example"}
            for path in ("/sitemap.xml", "/llms.txt", "/favicon.ico", "/docs/tags.md"):
                r = await self.client.get(path, headers=dev)
                self.assertEqual(r.status, 403, path)
                self.assertEqual(r.headers.get("X-Robots-Tag"), "noindex, nofollow", path)
            html = await (await self.client.get("/", headers=dict(dev, Cookie=wallet_cookie(TEST_PK)))).text()
            self.assertNotIn('rel="canonical"', html)                      # the owner's view of the closed copy
            self.assertIn('<meta name="robots" content="noindex">', html)


if __name__ == "__main__":
    unittest.main()
