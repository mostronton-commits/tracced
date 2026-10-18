"""Модель агента від Anthropic (Claude) через офіційний SDK — той самий вхід і вихід, що в Assistant (early/assistant.py):
json_chat(system, user) → (dict, usage), кидає AssistantError з людським текстом.

Власник, 18.10: $100 кредитів Anthropic → Claude Sonnet як основна модель агента, OpenRouter лишається запасним (Chain):
скінчились кредити чи Anthropic не відповідає — відповідає запасна модель, людина помилки не бачить.
"""
from .assistant import MAX_CALLS, AssistantError, parse_json

DEFAULT_MODEL = "claude-sonnet-5-5"
# $ за мільйон токенів (вхід, вихід) — для журналу витрат у /admin; ціни Anthropic на 06.10.2026
PRICES = {"claude-sonnet-5-5": (2.0, 10.0), "claude-sonnet-5": (2.0, 10.0), "claude-opus-5-5": (4.0, 20.0),
          "claude-haiku-5-5": (0.10, 0.50)}
MAX_TOKENS = 4000          # разом із думками моделі: на низькому зусиллі їх мало, але 1500 могло б обрізати JSON
EFFORT = "low"             # зведення з готових фактів, не важка задача: менше думок — швидше і дешевше
FALLBACK_BETA = "server-side-fallback-2026-07-01"   # відмова класифікатора безпеки → Anthropic сам повторює на іншій моделі


class Claude:
    def __init__(self, key, model=None, client=None, timeout=60):
        self.model = model or DEFAULT_MODEL
        if client is None:
            import anthropic                                   # лише коли ключ є: без нього пакет не потрібен
            client = anthropic.Anthropic(api_key=key, timeout=timeout, max_retries=1)
        self.client = client
        self.calls = 0

    def balance(self):
        """Залишок кредитів Anthropic звичайним ключем не дізнатись — його видно в console.anthropic.com."""
        return None

    def _cost(self, model, usage):
        pin, pout = PRICES.get(model) or PRICES.get(self.model) or (0, 0)
        return (usage["prompt_tokens"] * pin + usage["completion_tokens"] * pout) / 1e6

    def _chat(self, system, user):
        import anthropic
        self.calls += 1
        try:
            r = self.client.beta.messages.create(
                model=self.model, max_tokens=MAX_TOKENS, system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": EFFORT}, betas=[FALLBACK_BETA], fallbacks="default")
        except anthropic.RateLimitError as e:
            raise AssistantError("The agent's model is busy right now. Try again in a minute.") from e
        except anthropic.BadRequestError as e:
            if "credit" in str(e).lower():
                raise AssistantError("The agent's budget for its model is used up. The owner has been told.") from e
            raise AssistantError("The agent's model answered HTTP 400. Try again later.") from e
        except anthropic.APIStatusError as e:
            raise AssistantError(f"The agent's model answered HTTP {e.status_code}. Try again later.") from e
        except anthropic.APIConnectionError as e:                  # сюди ж і тайм-аут
            raise AssistantError("The agent's model did not answer in time. Try again in a minute.") from e
        u = getattr(r, "usage", None)
        usage = {"prompt_tokens": int(getattr(u, "input_tokens", 0) or 0), "completion_tokens": int(getattr(u, "output_tokens", 0) or 0)}
        usage["cost"] = self._cost(getattr(r, "model", self.model), usage)
        if getattr(r, "stop_reason", None) == "refusal":
            raise AssistantError("The agent could not answer this one. Try asking it another way.", usage)
        text = "".join(getattr(b, "text", "") for b in (r.content or []) if getattr(b, "type", "") == "text")
        return text, usage

    def json_chat(self, system, user):
        """(dict, usage); не більше MAX_CALLS викликів на питання, як і в Assistant."""
        spent = {"prompt_tokens": 0, "completion_tokens": 0, "cost": 0}

        def chat(u):
            try:
                text, usage = self._chat(system, u)
            except AssistantError as e:
                for k in spent:
                    spent[k] += (e.usage or {}).get(k) or 0
                raise AssistantError(str(e), dict(spent)) from e
            for k in spent:
                spent[k] += usage.get(k) or 0
            return text
        out = parse_json(chat(user))
        if out is None and MAX_CALLS > 1:
            out = parse_json(chat(user + "\n\nYour previous answer was not a valid JSON object. Return only the JSON object."))
        if out is None:
            raise AssistantError("The agent did not return a usable answer. Try again.", spent)
        return out, spent


class Chain:
    """Основна модель, а якщо вона не змогла (кредити, збій, тайм-аут) — запасна. Витрати обох складаються."""

    def __init__(self, primary, backup):
        self.primary, self.backup = primary, backup
        self.model = primary.model
        self.calls = 0

    def balance(self):
        return self.backup.balance()                           # OpenRouter знає свій залишок; Anthropic — лише в консолі

    def json_chat(self, system, user):
        self.calls += 1
        try:
            return self.primary.json_chat(system, user)
        except AssistantError as e:
            spent = dict(e.usage or {})
            try:
                out, usage = self.backup.json_chat(system, user)
            except AssistantError as e2:
                raise AssistantError(str(e2), _add(spent, e2.usage)) from e2
            return out, _add(spent, usage)


def _add(a, b):
    out = {"prompt_tokens": 0, "completion_tokens": 0, "cost": 0}
    for d in (a or {}, b or {}):
        for k in out:
            out[k] += d.get(k) or 0
    return out
