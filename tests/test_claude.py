"""Claude як модель агента (власник, 18.10): той самий json_chat, що в Assistant, ціна в журнал, відмова й збій →
запасна модель. Мережі немає: клієнт підмінено, а форму запиту справжнього SDK перевіряє підставний транспорт."""
import json
import unittest
from types import SimpleNamespace as NS

from tracced.early import claude
from tracced.early.assistant import AssistantError


def reply(text, inp=4000, out=500, stop="end_turn", model="claude-sonnet-5-5"):
    return NS(content=[NS(type="thinking", thinking=""), NS(type="text", text=text)], stop_reason=stop, model=model,
              usage=NS(input_tokens=inp, output_tokens=out))


class FakeClient:
    def __init__(self, *replies):
        self.replies, self.sent = list(replies), []
        self.beta = NS(messages=NS(create=self.create))

    def create(self, **kw):
        self.sent.append(kw)
        return self.replies.pop(0)


class TestClaude(unittest.TestCase):
    def test_json_answer_and_its_price(self):
        fc = FakeClient(reply('Here: {"story": ["1 wallet bought."]}'))
        out, usage = claude.Claude("k", model="claude-sonnet-5-5", client=fc).json_chat("rules", "digest")
        self.assertEqual(out, {"story": ["1 wallet bought."]})
        self.assertAlmostEqual(usage["cost"], (4000 * 2 + 500 * 10) / 1e6)        # Sonnet 5.5: $2 / $10 за мільйон
        kw = fc.sent[0]
        self.assertEqual((kw["model"], kw["system"], kw["output_config"], kw["fallbacks"]),
                         ("claude-sonnet-5-5", "rules", {"effort": "low"}, "default"))
        self.assertIn(claude.FALLBACK_BETA, kw["betas"])

    def test_haiku_is_the_default_and_is_sent_without_a_server_fallback(self):
        fc = FakeClient(reply('{"a": 1}', model="claude-haiku-5-5"))
        out, usage = claude.Claude("k", client=fc).json_chat("s", "u")
        self.assertEqual(fc.sent[0]["model"], "claude-haiku-5-5")
        self.assertNotIn("fallbacks", fc.sent[0])                                    # Haiku його не має: «default» нічого не дає
        self.assertAlmostEqual(usage["cost"], (4000 * 0.10 + 500 * 0.50) / 1e6)

    def test_a_broken_answer_is_asked_once_more_and_both_are_paid(self):
        fc = FakeClient(reply("no json here"), reply('{"answer": ["ok"]}'))
        out, usage = claude.Claude("k", client=fc).json_chat("s", "u")
        self.assertEqual((out, len(fc.sent)), ({"answer": ["ok"]}, 2))
        self.assertAlmostEqual(usage["cost"], 2 * (4000 * 2 + 500 * 10) / 1e6)       # ціна — тієї моделі, що відповіла

    def test_a_refusal_is_a_readable_error_that_carries_its_cost(self):
        fc = FakeClient(reply("", out=0, stop="refusal"))
        with self.assertRaises(AssistantError) as e:
            claude.Claude("k", client=fc).json_chat("s", "u")
        self.assertIn("could not answer", str(e.exception))
        self.assertAlmostEqual(e.exception.usage["cost"], 4000 * 2 / 1e6)


class FakeChat:
    def __init__(self, model, out=None, err=None):
        self.model, self.out, self.err, self.calls = model, out, err, 0

    def json_chat(self, system, user):
        self.calls += 1
        if self.err:
            raise AssistantError(self.err, {"prompt_tokens": 10, "completion_tokens": 0, "cost": 0.01})
        return self.out, {"prompt_tokens": 5, "completion_tokens": 5, "cost": 0.001}

    def balance(self):
        return {"account_left": 3.0}


class TestChain(unittest.TestCase):
    def test_the_backup_answers_when_claude_cannot_and_the_costs_add_up(self):
        main, backup = FakeChat("claude", err="The agent's budget for its model is used up."), FakeChat("deepseek", out={"a": 1})
        out, usage = claude.Chain(main, backup).json_chat("s", "u")
        self.assertEqual((out, main.calls, backup.calls), ({"a": 1}, 1, 1))
        self.assertAlmostEqual(usage["cost"], 0.011)
        self.assertEqual(claude.Chain(main, backup).balance(), {"account_left": 3.0})

    def test_claude_answers_and_the_backup_is_not_called(self):
        main, backup = FakeChat("claude", out={"a": 2}), FakeChat("deepseek", out={"a": 1})
        self.assertEqual(claude.Chain(main, backup).json_chat("s", "u")[0], {"a": 2})
        self.assertEqual(backup.calls, 0)

    def test_both_down_is_one_readable_error(self):
        main, backup = FakeChat("claude", err="busy"), FakeChat("deepseek", err="also busy")
        with self.assertRaises(AssistantError) as e:
            claude.Chain(main, backup).json_chat("s", "u")
        self.assertEqual(str(e.exception), "also busy")
        self.assertAlmostEqual(e.exception.usage["cost"], 0.02)


try:
    import anthropic
    import httpx2
except ImportError:                       # пакета нема на хості — перевіряється в образі
    anthropic = None


@unittest.skipIf(anthropic is None, "anthropic SDK not installed")
class TestRealSdkRequest(unittest.TestCase):
    def test_the_sdk_sends_what_the_api_expects(self):
        seen = {}

        def handler(request):
            seen["url"], seen["beta"] = str(request.url), request.headers.get("anthropic-beta", "")
            seen["body"] = json.loads(request.content)
            return httpx2.Response(200, json={
                "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
                "content": [{"type": "text", "text": '{"story": ["ok"]}'}], "stop_reason": "end_turn", "stop_sequence": None,
                "usage": {"input_tokens": 100, "output_tokens": 20}})
        client = anthropic.Anthropic(api_key="test", max_retries=0,
                                     http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)))
        out, usage = claude.Claude("test", model="claude-sonnet-5-5", client=client).json_chat("rules", "digest")
        self.assertEqual(out, {"story": ["ok"]})
        self.assertTrue(seen["url"].endswith("/v1/messages?beta=true") or seen["url"].endswith("/v1/messages"))
        self.assertIn("server-side-fallback-2026-07-01", seen["beta"])
        b = seen["body"]
        self.assertEqual((b["model"], b["fallbacks"], b["output_config"], b["system"]), ("claude-sonnet-5-5", "default", {"effort": "low"}, "rules"))
        self.assertAlmostEqual(usage["cost"], (100 * 2 + 20 * 10) / 1e6)


if __name__ == "__main__":
    unittest.main()
