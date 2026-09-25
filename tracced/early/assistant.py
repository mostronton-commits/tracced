"""Транспорт до моделі агента: OpenAI-сумісний чат-ендпоінт (OpenRouter), відповідь — JSON.

Що саме агент питає і як перевіряє відповідь, — у early/agent.py; тут лише надійна доставка. Особливості моделей
OpenRouter, які тут враховано: reasoning-моделі можуть віддати порожній `content` (думки лежать окремо) — повторюємо
з вимкненим reasoning; `response_format` приймають не всі — при 400 повторюємо без нього; поле `models` дає запасну
модель, якщо основна впала; 429 — ліміт. Не більше трьох викликів на одне питання.
"""
import json
import re
import urllib.error
import urllib.request

DEFAULT_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash"
MAX_TOKENS = 1500
MAX_CALLS = 3


def parse_json(text):
    """Перший JSON-об'єкт у тексті (модель інколи загортає його в пояснення чи ```); None — не вийшло."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return d if isinstance(d, dict) else None


class Assistant:
    def __init__(self, key, url=None, model=None, post=None, timeout=60, fallbacks=None):
        self.key = key
        self.url = (url or DEFAULT_URL).rstrip("/")
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout
        if isinstance(fallbacks, str):
            fallbacks = [m.strip() for m in fallbacks.split(",")]
        self.fallbacks = [m for m in (fallbacks or []) if m and m != self.model]
        self._post = post or self._http
        self.calls = 0

    def _http(self, payload):
        req = urllib.request.Request(self.url + "/chat/completions", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.key}",
                                              "User-Agent": "tracced/1.0", "HTTP-Referer": "https://tracced.xyz",
                                              "X-Title": "tracced"}, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode())

    def payload(self, system, user, json_mode=True, reasoning=True):
        p = {"model": self.model, "temperature": 0.2, "max_tokens": MAX_TOKENS, "usage": {"include": True},
             "provider": {"sort": "throughput"},                # OpenRouter: найшвидший постачальник цієї моделі (картки — сотні токенів)
             "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if self.fallbacks:
            p["models"] = [self.model] + self.fallbacks          # OpenRouter: запасні моделі, якщо основна впала чи перевантажена
        if json_mode:
            p["response_format"] = {"type": "json_object"}
        if not reasoning:
            p["reasoning"] = {"enabled": False}                 # reasoning-моделі: відповідь, а не роздуми
        return p

    def _chat(self, system, user, **opts):
        self.calls += 1
        d = self._post(self.payload(system, user, **opts))
        msg = ((d.get("choices") or [{}])[0].get("message") or {})
        u = d.get("usage") or {}
        return (msg.get("content") or ""), {"prompt_tokens": u.get("prompt_tokens") or 0,
                                            "completion_tokens": u.get("completion_tokens") or 0, "cost": u.get("cost") or 0}

    def json_chat(self, system, user):
        """(dict, usage) від моделі; кидає AssistantError з людським текстом."""
        calls, spent = [0], {"prompt_tokens": 0, "completion_tokens": 0, "cost": 0}

        def chat(u=None, **opts):
            calls[0] += 1
            text, usage = self._chat(system, u or user, **opts)
            for k in spent:
                spent[k] += usage.get(k) or 0
            return text
        json_mode, out = True, None
        try:
            try:
                text = chat(reasoning=False)
            except urllib.error.HTTPError as e:
                if e.code != 400:
                    raise
                json_mode = False                                # ця модель не знає response_format — без нього
                text = chat(json_mode=False, reasoning=False)
            out = parse_json(text)
            if out is None and calls[0] < MAX_CALLS:
                text = chat(user + "\n\nYour previous answer was not a valid JSON object. Return only the JSON object.",
                            json_mode=json_mode, reasoning=False)
                out = parse_json(text)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                raise AssistantError("The agent's model is busy right now. Try again in a minute.") from e
            if e.code == 402:
                raise AssistantError("The agent's budget for its model is used up. The owner has been told.") from e
            raise AssistantError(f"The agent's model answered HTTP {e.code}. Try again later.") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise AssistantError("The agent's model did not answer in time. Try again in a minute.") from e
        if out is None:
            raise AssistantError("The agent did not return a usable answer. Try again.")
        return out, spent


class AssistantError(Exception):
    """A reason a person can read."""
