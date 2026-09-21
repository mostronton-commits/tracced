"""AI-асистент v1: «які з цих гаманців варті спостереження — і чому».

Асистент бачить ЛИШЕ факти з таблиці (компактні рядки) і методику користувача. Він не має доступу до
мережі, не бачить інших токенів і нічого не прогнозує; його відповідь — відбір рядків із поясненням у
фактах, який людина перевіряє сама. Промт і розбір відповіді — чисті функції; виклик моделі — через
OpenAI-сумісний чат-ендпоінт (за замовчуванням OpenRouter і безкоштовна модель), транспорт підмінюваний
для тестів.

Особливості безкоштовних моделей OpenRouter, які тут враховано: reasoning-моделі можуть віддати порожній
`content` (думки лежать окремо) — повторюємо з вимкненим reasoning; `response_format` не всі приймають —
при 400 повторюємо без нього; поле `models` дає автоматичну запасну модель; 429 — денний ліміт.
"""
import json
import re
import urllib.error
import urllib.request

DEFAULT_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "meta-llama/llama-3.3-70b-instruct:free"
MAX_ROWS = 200
MAX_TOKENS = 1200
MAX_CALLS = 3

DEFAULT_METHOD = (
    "Pick wallets worth watching for future pumps. Prefer: realized profit above zero and multiple of 1.3 or more; "
    "held at least 10 minutes before the first sell; not bot-like; not part of a bundle; bought at least $100 in the "
    "range; sold in more than one step or still holding a part. Avoid: wallets that dumped everything within minutes, "
    "bots, bundles, and wallets with a realized loss. Return 5 to 15 wallets, best first."
)

PRESETS = {
    "Early and still holding": "Pick wallets that bought early in the range (lowest entry_range_mcap) and still hold most of their "
                               "tokens (sold_share_pct under 50). Skip bots and bundles. Return 5 to 15 wallets, best first.",
    "Took profit, no bot signs": "Pick wallets with realized profit above zero and a multiple of 1.5 or more, that held at least 10 minutes "
                                 "before the first sell and sold in more than one step. Skip bot-like and bundle wallets. Return 5 to 15, best first.",
    "Big early buyers": "Pick the wallets that spent the most inside the range (invested_in_range_usd), whatever they did next, "
                        "but skip bundles. Return 5 to 15 wallets, largest first, and say what each one did after buying.",
}

FIELDS = ("wallet", "entry_range_mcap", "first_range_buy_utc", "invested_in_range_usd", "invested_usd",
          "exit_mcap_avg", "first_sell_utc", "proceeds_usd", "sold_share_pct", "realized_usd", "unrealized_usd",
          "multiple", "hold_minutes", "buys", "sells", "tags")

SYSTEM = (
    "You are an analyst's assistant. You receive a table of wallets that bought a Solana token inside a marked "
    "range, with facts computed from raw on-chain swaps, and the user's method for choosing wallets to watch. "
    "Apply the method to the facts only. Do not invent facts, do not predict prices, do not rate wallets on "
    "anything outside the table. Answer with JSON only: {\"picks\": [{\"wallet\": \"<wallet exactly as given>\", "
    "\"reason\": \"<one sentence citing the facts>\"}], \"note\": \"<one sentence on what you could not judge>\"}."
)


def compact(rows, cap=MAX_ROWS):
    """Стислі рядки для промту: лише поля з FIELDS, числа округлені."""
    out = []
    for r in rows[:cap]:
        c = {}
        for k in FIELDS:
            v = r.get(k)
            if isinstance(v, float):
                v = round(v, 1)
            if v not in (None, "", [], 0.0):
                c[k] = v
        out.append(c)
    return out


def build_prompt(rows, method):
    """(system, user) для чат-моделі."""
    method = (method or DEFAULT_METHOD).strip()[:2000]
    table = compact(rows)
    user = (f"Method:\n{method}\n\nWallets ({len(table)} rows, JSON lines; entry_range_mcap and exit_mcap_avg are "
            f"market caps in USD, hold_minutes is minutes from the entry to the first sell after it, tags are facts "
            f"with fixed definitions):\n" + "\n".join(json.dumps(t, ensure_ascii=False) for t in table)
            + "\n\nReturn JSON only.")
    return SYSTEM, user


def parse_reply(text, known=None):
    """Список {wallet, reason} з відповіді моделі; терпимо до тексту навколо JSON. Невідомі гаманці відкидаються."""
    if not text:
        return [], ""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return [], ""
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return [], ""
    picks, seen = [], set()
    for p in d.get("picks") or []:
        if not isinstance(p, dict):
            continue
        w = str(p.get("wallet") or "").strip()
        if not w or w in seen or (known is not None and w not in known):
            continue
        seen.add(w)
        picks.append({"wallet": w, "reason": str(p.get("reason") or "").strip()[:300]})
    return picks, str(d.get("note") or "").strip()[:300]


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
        p = {"model": self.model, "temperature": 0.2, "max_tokens": MAX_TOKENS,
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
        return (msg.get("content") or ""), bool(msg.get("reasoning"))

    def ask(self, rows, method):
        """{"picks": [...], "note": str, "model": str}; кидає AssistantError з людським текстом."""
        system, user = build_prompt(rows, method)
        known = {r["wallet"] for r in rows}
        picks, note, json_mode = [], "", True
        calls = [0]                                              # ліміт спроб — на одне запитання, не на життя процесу

        def chat(u=None, **opts):
            calls[0] += 1
            return self._chat(system, u or user, **opts)
        try:
            try:
                text, reasoned = chat()
            except urllib.error.HTTPError as e:
                if e.code != 400:
                    raise
                json_mode = False                                # ця модель не знає response_format — без нього
                text, reasoned = chat(json_mode=False)
            picks, note = parse_reply(text, known)
            if not picks and not text.strip() and calls[0] < MAX_CALLS:   # порожня відповідь: думки з'їли ліміт токенів
                text, _ = chat(json_mode=json_mode, reasoning=False)
                picks, note = parse_reply(text, known)
            if not picks and calls[0] < MAX_CALLS:
                text, _ = chat(user + "\nYour previous answer was not valid JSON. Return only the JSON object.",
                               json_mode=json_mode, reasoning=False)
                picks, note = parse_reply(text, known)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                raise AssistantError("The free model is rate-limited right now. Try again in a minute.") from e
            raise AssistantError(f"The assistant's model answered HTTP {e.code}. Check ASSISTANT_KEY / ASSISTANT_MODEL.") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise AssistantError("The assistant's model did not answer in time. Try again in a minute.") from e
        if not picks:
            raise AssistantError("The assistant did not return a usable list. Try again or simplify the method.")
        return {"picks": picks, "note": note, "model": self.model}


class AssistantError(Exception):
    """A reason a person can read."""
