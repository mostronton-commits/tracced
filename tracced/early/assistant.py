"""AI-асистент v1: «які з цих гаманців варті спостереження — і чому».

Асистент бачить ЛИШЕ факти з таблиці (компактні рядки) і методику користувача. Він не має доступу до
мережі, не бачить інших токенів і нічого не прогнозує; його відповідь — відбір рядків із поясненням у
фактах, який людина перевіряє сама. Промт і розбір відповіді — чисті функції; виклик моделі — через
OpenAI-сумісний чат-ендпоінт (за замовчуванням Ollama Cloud), транспорт підмінюваний для тестів.
"""
import json
import re
import urllib.error
import urllib.request

DEFAULT_URL = "https://ollama.com/v1"
DEFAULT_MODEL = "kimi-k2.6:cloud"
MAX_ROWS = 200

DEFAULT_METHOD = (
    "Pick wallets worth watching for future pumps. Prefer: realized profit above zero and multiple of 1.3 or more; "
    "held at least 10 minutes before the first sell; not bot-like; not part of a bundle; bought at least $100 in the "
    "range; sold in more than one step or still holding a part. Avoid: wallets that dumped everything within minutes, "
    "bots, bundles, and wallets with a realized loss. Return 5 to 15 wallets, best first."
)

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
    def __init__(self, key, url=None, model=None, post=None, timeout=60):
        self.key = key
        self.url = (url or DEFAULT_URL).rstrip("/")
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout
        self._post = post or self._http
        self.calls = 0

    def _http(self, payload):
        req = urllib.request.Request(self.url + "/chat/completions", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.key}",
                                              "User-Agent": "early-wallets/1.0"}, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode())

    def _chat(self, system, user):
        self.calls += 1
        d = self._post({"model": self.model, "temperature": 0.2,
                        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        return (((d.get("choices") or [{}])[0].get("message") or {}).get("content") or "")

    def ask(self, rows, method):
        """{"picks": [...], "note": str, "model": str}; кидає AssistantError з людським текстом."""
        system, user = build_prompt(rows, method)
        known = {r["wallet"] for r in rows}
        try:
            text = self._chat(system, user)
            picks, note = parse_reply(text, known)
            if not picks:
                text = self._chat(system, user + "\nYour previous answer was not valid JSON. Return only the JSON object.")
                picks, note = parse_reply(text, known)
        except urllib.error.HTTPError as e:
            raise AssistantError(f"The assistant's model answered HTTP {e.code}. Check ASSISTANT_KEY / ASSISTANT_MODEL.") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise AssistantError("The assistant's model did not answer in time. Try again in a minute.") from e
        if not picks:
            raise AssistantError("The assistant did not return a usable list. Try again or simplify the method.")
        return {"picks": picks, "note": note, "model": self.model}


class AssistantError(Exception):
    """A reason a person can read."""
