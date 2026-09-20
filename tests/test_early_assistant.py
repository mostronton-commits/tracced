import json
import unittest
import urllib.error

from tracced.early import assistant
from tracced.early.assistant import Assistant, AssistantError, build_prompt, compact, parse_reply

ROWS = [
    {"wallet": "W1", "entry_range_mcap": 395140.29, "invested_in_range_usd": 954.75, "realized_usd": 822.03,
     "multiple": 1.86, "hold_minutes": 147.3, "buys": 7, "sells": 7, "tags": "fresh", "sold_share_pct": 100.0,
     "unrealized_usd": 0.0, "first_sell_utc": "2026-09-16 20:53"},
    {"wallet": "W2", "entry_range_mcap": 398597.32, "invested_in_range_usd": 784.78, "realized_usd": 10.97,
     "multiple": 1.01, "hold_minutes": 0.0, "buys": 27, "sells": 27, "tags": "bot-like"},
]


class FakePost:
    def __init__(self, answers):
        self.answers, self.payloads = list(answers), []

    def __call__(self, payload):
        self.payloads.append(payload)
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return {"choices": [{"message": {"content": a}}]}


class TestAssistant(unittest.TestCase):
    def test_compact_and_prompt_contain_only_facts(self):
        c = compact(ROWS)
        self.assertEqual(c[0]["wallet"], "W1")
        self.assertEqual(c[0]["realized_usd"], 822.0)
        self.assertNotIn("unrealized_usd", c[0])                      # нулі й порожнє не шлемо
        system, user = build_prompt(ROWS, "my method: only profitable")
        self.assertIn("JSON only", system)
        self.assertIn("my method: only profitable", user)
        self.assertIn('"wallet": "W2"', user)
        self.assertNotIn("solscan", user.lower())                      # лише факти з FIELDS

    def test_default_method_when_empty(self):
        _, user = build_prompt(ROWS, "")
        self.assertIn("Pick wallets worth watching", user)

    def test_parse_reply_tolerates_text_and_unknown_wallets(self):
        text = 'Sure! Here you go:\n{"picks": [{"wallet": "W1", "reason": "+$822, held 147 min"}, {"wallet": "ZZZ", "reason": "x"}, {"wallet": "W1", "reason": "dup"}], "note": "W2 looks like a bot"}\nHope this helps.'
        picks, note = parse_reply(text, known={"W1", "W2"})
        self.assertEqual(picks, [{"wallet": "W1", "reason": "+$822, held 147 min"}])
        self.assertEqual(note, "W2 looks like a bot")
        self.assertEqual(parse_reply("no json here", {"W1"}), ([], ""))
        self.assertEqual(parse_reply("", {"W1"}), ([], ""))

    def test_ask_retries_once_then_returns(self):
        post = FakePost(["not json at all", json.dumps({"picks": [{"wallet": "W1", "reason": "profit"}], "note": ""})])
        a = Assistant("k", post=post, model="m")
        out = a.ask(ROWS, "")
        self.assertEqual(out["picks"][0]["wallet"], "W1")
        self.assertEqual(a.calls, 2)
        self.assertIn("not valid JSON", post.payloads[1]["messages"][1]["content"])
        self.assertEqual(post.payloads[0]["model"], "m")

    def test_ask_errors_are_human(self):
        err = urllib.error.HTTPError("u", 401, "x", {}, None)
        with self.assertRaises(AssistantError) as cm:
            Assistant("k", post=FakePost([err])).ask(ROWS, "")
        self.assertIn("HTTP 401", str(cm.exception))
        with self.assertRaises(AssistantError):
            Assistant("k", post=FakePost(["nope", "still nope"])).ask(ROWS, "")

    def test_defaults(self):
        a = Assistant("k")
        self.assertEqual((a.url, a.model), (assistant.DEFAULT_URL, assistant.DEFAULT_MODEL))
        self.assertIn("openrouter.ai", a.url)

    def test_payload_for_openrouter(self):
        post = FakePost([json.dumps({"picks": [{"wallet": "W1", "reason": "ok"}]})])
        a = Assistant("k", post=post, model="m", fallbacks="f1, f2, m")
        a.ask(ROWS, "")
        p = post.payloads[0]
        self.assertEqual((p["max_tokens"], p["response_format"], p["models"]), (assistant.MAX_TOKENS, {"type": "json_object"}, ["m", "f1", "f2"]))
        self.assertNotIn("reasoning", p)
        self.assertEqual(a.calls, 1)

    def test_empty_answer_retries_without_reasoning(self):
        post = FakePost(["", json.dumps({"picks": [{"wallet": "W2", "reason": "bot"}]})])
        a = Assistant("k", post=post)
        out = a.ask(ROWS, "")
        self.assertEqual(out["picks"][0]["wallet"], "W2")
        self.assertEqual(post.payloads[1]["reasoning"], {"enabled": False})
        self.assertEqual(a.calls, 2)

    def test_http_400_retries_without_response_format(self):
        err = urllib.error.HTTPError("u", 400, "x", {}, None)
        post = FakePost([err, json.dumps({"picks": [{"wallet": "W1", "reason": "ok"}]})])
        a = Assistant("k", post=post)
        a.ask(ROWS, "")
        self.assertIn("response_format", post.payloads[0])
        self.assertNotIn("response_format", post.payloads[1])

    def test_rate_limit_is_explained(self):
        err = urllib.error.HTTPError("u", 429, "x", {}, None)
        with self.assertRaises(AssistantError) as cm:
            Assistant("k", post=FakePost([err])).ask(ROWS, "")
        self.assertIn("rate-limited", str(cm.exception))

    def test_at_most_three_calls(self):
        post = FakePost(["", "nope", "still nope", "never asked"])
        with self.assertRaises(AssistantError):
            Assistant("k", post=post).ask(ROWS, "")
        self.assertEqual(len(post.payloads), 3)


if __name__ == "__main__":
    unittest.main()
