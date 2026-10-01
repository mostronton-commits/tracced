"""Скільки купівель і продажів потік сповіщень побачив у кожного гаманця зі списків людини (власник, 01.10: «лічильники
алертів для кожного гаманця, щоб бачити, хто наскільки активний»).

Рахуємо кожну угоду, яку розбір визнав купівлею чи продажем, для кожного, хто за гаманцем стежить, — незалежно від його
налаштувань (мінімальна сума, лише купівлі) і годинної стелі: це активність гаманця, а не кількість повідомлень. Бачимо
лише гаманці зі списків з увімкненим дзвіночком і лише відтоді, як за ними стежать.

Файл — один на сервер: {акаунт: {гаманець: {"d": {"YYYY-MM-DD": [купівлі, продажі]}, "last": ms, "side": "buy"|"sell"}}}.
Дні — за UTC, тримаємо 30; запис гаманця без угод за 30 днів забуваємо. Пишемо не на кожну угоду, а коли потік
перевіряє список гаманців (раз на 30 с) і при зупинці сервера."""
import datetime
import json
import os
import threading
import time

KEEP_DAYS = 30
DAY_MS = 86_400_000


def _day(ms):
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).strftime("%Y-%m-%d")


class Activity:
    def __init__(self, path, keep_days=KEEP_DAYS):
        self.path, self.keep, self.lock, self.dirty = path, keep_days, threading.Lock(), False
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            raw = {}
        self.data = self._clean(raw)

    @staticmethod
    def _clean(raw):
        """Файл свій, але зіпсований не має валити сторінку списків: лише числа в очікуваних місцях."""
        out = {}
        for pk, ws in (raw.items() if isinstance(raw, dict) else []):
            for w, rec in (ws.items() if isinstance(ws, dict) else []):
                if not isinstance(rec, dict) or not isinstance(rec.get("d"), dict):
                    continue
                days = {d: [int(v[0]), int(v[1])] for d, v in rec["d"].items()
                        if isinstance(d, str) and isinstance(v, list) and len(v) == 2 and all(isinstance(x, int) for x in v)}
                last = rec.get("last") if isinstance(rec.get("last"), int) else 0
                if days:
                    out.setdefault(str(pk), {})[str(w)] = {"d": days, "last": last,
                                                           "side": rec.get("side") if rec.get("side") in ("buy", "sell") else None}
        return out

    def bump(self, pk, wallet, side, ms=None):
        """Одна угода гаманця, яку бачить той, хто за ним стежить."""
        if side not in ("buy", "sell") or not pk or not wallet:
            return
        ms = int(ms or time.time() * 1000)
        with self.lock:
            rec = self.data.setdefault(pk, {}).setdefault(wallet, {"d": {}, "last": 0, "side": side})
            day = rec["d"].setdefault(_day(ms), [0, 0])
            day[0 if side == "buy" else 1] += 1
            if ms >= rec.get("last", 0):
                rec["last"], rec["side"] = ms, side
            self.dirty = True

    def of(self, pk, now_ms=None, days=7):
        """{гаманець: {"buys": n, "sells": n, "last": ms, "side": …}} за останні `days` днів, сьогодні включно."""
        now_ms = int(now_ms or time.time() * 1000)
        since = {_day(now_ms - i * DAY_MS) for i in range(days)}
        out = {}
        with self.lock:
            for w, rec in (self.data.get(pk) or {}).items():
                b = sum(v[0] for d, v in rec.get("d", {}).items() if d in since)
                s = sum(v[1] for d, v in rec.get("d", {}).items() if d in since)
                out[w] = {"buys": b, "sells": s, "last": int(rec.get("last") or 0), "side": rec.get("side")}
        return out

    def forget(self, pk, wallet=None):
        """Видалення акаунта чи гаманця на прохання людини."""
        with self.lock:
            if wallet is None:
                self.dirty = self.data.pop(pk, None) is not None or self.dirty
            elif (self.data.get(pk) or {}).pop(wallet, None) is not None:
                self.dirty = True

    def save(self, now_ms=None):
        """Записати, якщо щось змінилось; дні старші за keep — прибрати, а гаманці без жодного дня — забути."""
        if not self.dirty:
            return False
        now_ms = int(now_ms or time.time() * 1000)
        keep = {_day(now_ms - i * DAY_MS) for i in range(self.keep)}
        with self.lock:
            for pk in list(self.data):
                for w in list(self.data[pk]):
                    rec = self.data[pk][w]
                    rec["d"] = {d: v for d, v in rec.get("d", {}).items() if d in keep}
                    if not rec["d"]:
                        del self.data[pk][w]
                if not self.data[pk]:
                    del self.data[pk]
            snap = json.dumps(self.data, ensure_ascii=False, separators=(",", ":"))
            self.dirty = False
        try:
            os.makedirs(os.path.dirname(str(self.path)) or ".", exist_ok=True)
            tmp = str(self.path) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(snap)
            os.replace(tmp, self.path)
        except OSError:
            self.dirty = True                         # не записалось: спробуємо з наступною перевіркою
            raise
        return True
