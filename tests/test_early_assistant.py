import json
import unittest
import urllib.error

from tracced.early import assistant
from tracced.early.assistant import Assistant, AssistantError, parse_json


class FakePost:
    def __init__(self, answers):
        self.answers, self.payloads = list(answers), []

    def __call__(self, payload):
        self.payloads.append(payload)
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return {"choices": [{"message": {"content": a}}], "usage": {"prompt_tokens": 100, "completion_tokens": 20, "cost": 0.0001}}


def http(code):
    return urllib.error.HTTPError("u", code, "x", {}, None)


class TestTransport(unittest.TestCase):
    def test_defaults(self):
        a = Assistant("k")
        self.assertEqual((a.url, a.model), ("https://openrouter.ai/api/v1", "deepseek/deepseek-v4.1-flash"))

    def test_payload_for_openrouter(self):
        a = Assistant("k", fallbacks="m2, m3")
        p = a.payload("sys", "usr")
        self.assertEqual(p["models"], ["deepseek/deepseek-v4.1-flash", "m2", "m3"])   # запасні моделі
        self.assertEqual(p["response_format"], {"type": "json_object"})
        self.assertEqual(p["usage"], {"include": True})                                 # ціна кожної відповіді — в журнал
        self.assertEqual([m["role"] for m in p["messages"]], ["system", "user"])

    def test_json_chat_returns_the_object_and_what_it_cost(self):
        post = FakePost(['Sure! {"story": ["a"]} hope it helps'])
        out, usage = Assistant("k", post=post).json_chat("s", "u")
        self.assertEqual(out, {"story": ["a"]})
        self.assertEqual(usage, {"prompt_tokens": 100, "completion_tokens": 20, "cost": 0.0001})
        self.assertEqual(post.payloads[0]["reasoning"], {"enabled": False})              # відповідь, а не роздуми

    def test_http_400_retries_without_response_format(self):
        post = FakePost([http(400), '{"ok": 1}'])
        out, _ = Assistant("k", post=post).json_chat("s", "u")
        self.assertEqual(out, {"ok": 1})
        self.assertNotIn("response_format", post.payloads[1])

    def test_not_json_is_asked_once_more_then_given_up(self):
        post = FakePost(["prose", '{"ok": 2}'])
        self.assertEqual(Assistant("k", post=post).json_chat("s", "u")[0], {"ok": 2})
        self.assertIn("not a valid JSON", post.payloads[1]["messages"][1]["content"])
        post = FakePost(["prose", "more prose"])
        with self.assertRaises(AssistantError):
            Assistant("k", post=post).json_chat("s", "u")
        self.assertEqual(len(post.payloads), 2)

    def test_errors_are_human(self):
        for code, words in ((429, "busy"), (402, "budget"), (500, "HTTP 500")):
            with self.assertRaises(AssistantError) as c:
                Assistant("k", post=FakePost([http(code)])).json_chat("s", "u")
            self.assertIn(words, str(c.exception))
        with self.assertRaises(AssistantError) as c:
            Assistant("k", post=FakePost([urllib.error.URLError("timed out")])).json_chat("s", "u")
        self.assertIn("did not answer in time", str(c.exception))

    def test_at_most_three_calls(self):
        post = FakePost([http(400), "prose", "prose", '{"never": 1}'])
        with self.assertRaises(AssistantError):
            Assistant("k", post=post).json_chat("s", "u")
        self.assertLessEqual(len(post.payloads), assistant.MAX_CALLS)

    def test_parse_json(self):
        self.assertEqual(parse_json('```json\n{"a": [1, 2]}\n```'), {"a": [1, 2]})
        self.assertIsNone(parse_json("no json"))
        self.assertIsNone(parse_json('["a list"]'))
        self.assertEqual(json.loads(json.dumps(parse_json('{"x": "y"}'))), {"x": "y"})


if __name__ == "__main__":
    unittest.main()
