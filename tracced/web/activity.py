"""Скільки купівель і продажів потік сповіщень побачив у кожного гаманця, за яким стежить (власник, 01.10: «лічильники
алертів для кожного гаманця, щоб бачити, хто наскільки активний»).

Рахуємо кожну угоду, яку розбір визнав купівлею чи продажем, — незалежно від налаштувань людини (мінімальна сума, лише
купівлі) і годинної стелі: це активність гаманця, а не кількість повідомлень. Угоди — факт ланцюга, тож лічильник один на
гаманець, хоч би скільки людей за ним стежило. Рахунок іде відтоді, як потік почав стежити за гаманцем (`since`); коли
стежити перестав (дзвіночок вимкнули, гаманець прибрали, Telegram відв'язали) — запис забуваємо, і наступного разу рахунок
почнеться заново. Тому «0 угод» на сторінці завжди означає «стежили, а угод не було».

Вікно ковзне: години за UTC, сума за останні 168 годин; тримаємо 8 діб. Усі зміни — з циклу подій сервера (один потік),
на диск пишемо знімок у фоновому потоці з кожною перевіркою потоку (alerts_check_s) і при зупинці. Тут же закладка
опитування-страховки і підписи, оброблені за останні 15 хвилин (після перезапуску не надсилаються вдруге). Файл:
{гаманець: {"h": {"YYYY-MM-DDTHH": [купівлі, продажі]}, "last": ms, "since": ms, "sig": закладка, "done": [[підпис, ms]]}}."""
import datetime
import json
import os
import tempfile
import threading
import time

HOUR_MS = 3_600_000
WINDOW_H = 168               # сім діб
KEEP_H = 192                 # вісім діб: вікно і запас на перезапуск
DONE_MS = 15 * 60_000        # оброблені підписи пам'ятаємо 15 хв: більше за горизонт страховки (10 хв)
DONE_MAX = 64


def _hour(ms):
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).strftime("%Y-%m-%dT%H")


def _hour_ms(key):
    try:
        return int(datetime.datetime.strptime(key, "%Y-%m-%dT%H").replace(tzinfo=datetime.timezone.utc).timestamp() * 1000)
    except (TypeError, ValueError):
        return 0


def _now():
    return int(time.time() * 1000)


def _int(x):
    return isinstance(x, int) and not isinstance(x, bool)


class Activity:
    def __init__(self, path):
        self.path, self.write_lock, self.dirty = path, threading.Lock(), False
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
        for w, rec in (raw.items() if isinstance(raw, dict) else []):
            if not isinstance(rec, dict) or not _int(rec.get("since")) or not isinstance(rec.get("h", {}), dict):
                continue
            hours = {h: [v[0], v[1]] for h, v in rec.get("h", {}).items()
                     if _hour_ms(h) and isinstance(v, list) and len(v) == 2 and all(_int(x) for x in v)}
            done = [[x[0], x[1]] for x in rec.get("done") or [] if isinstance(x, list) and len(x) == 2 and isinstance(x[0], str) and _int(x[1])]
            out[str(w)] = {"h": hours, "last": rec["last"] if _int(rec.get("last")) else 0, "since": rec["since"],
                           "sig": rec["sig"] if isinstance(rec.get("sig"), str) else "", "done": done[-DONE_MAX:]}
        return out

    def watch(self, wallets, now_ms=None):
        """Потік стежить за цими гаманцями: новим ставимо початок рахунку, тих, кого більше нема, забуваємо."""
        now_ms = now_ms or _now()
        wallets = set(wallets)
        for w in [w for w in self.data if w not in wallets]:
            del self.data[w]
            self.dirty = True
        for w in wallets - set(self.data):
            self.data[w] = {"h": {}, "last": 0, "since": now_ms, "sig": "", "done": []}
            self.dirty = True

    def bump(self, wallet, side, ms=None):
        """Одна угода гаманця, за яким стежить потік."""
        rec = self.data.get(wallet)
        if rec is None or side not in ("buy", "sell"):
            return
        ms = int(ms or _now())
        h = rec["h"].setdefault(_hour(ms), [0, 0])
        h[0 if side == "buy" else 1] += 1
        rec["last"] = max(rec["last"], ms)
        self.dirty = True

    def seen(self, wallet, sig):
        """Закладка опитування-страховки: найновіший підпис, який воно вже розібрало. Переживає перезапуск сервера, тож
        угоди за час простою теж знайдуться."""
        rec = self.data.get(wallet)
        if rec is not None and sig and rec.get("sig") != sig:
            rec["sig"] = sig
            self.dirty = True

    def done(self, wallet, sig, ms=None):
        """Підпис оброблено (потоком чи страховкою): переживе перезапуск, щоб страховка не надіслала його вдруге.
        True — уперше; False — його вже рахували."""
        rec = self.data.get(wallet)
        if rec is None or not sig:
            return True
        d = rec.setdefault("done", [])
        if any(x[0] == sig for x in d):
            return False                              # уже рахували: повтор після невдалої відправки не додає угоду вдруге
        d.append([sig, int(ms or _now())])
        del d[:-DONE_MAX]
        self.dirty = True
        return True

    def recent_done(self, now_ms=None):
        """Ключі «підпис:гаманець», оброблені за останні 15 хв — для пам'яті сповіщень після перезапуску."""
        edge = (now_ms or _now()) - DONE_MS
        return [sig + ":" + w for w, rec in self.data.items() for sig, ms in rec.get("done") or [] if ms >= edge]

    def last_sig(self, wallet):
        return (self.data.get(wallet) or {}).get("sig") or ""

    def of(self, wallets, now_ms=None):
        """{гаманець: {"buys", "sells", "last", "since"}} за останні 168 годин — лише для тих, за ким потік стежить."""
        now_ms = now_ms or _now()
        start = now_ms - WINDOW_H * HOUR_MS
        out = {}
        for w in wallets:
            rec = self.data.get(w)
            if rec is None:
                continue
            got = [v for h, v in rec["h"].items() if _hour_ms(h) + HOUR_MS > start]
            out[w] = {"buys": sum(v[0] for v in got), "sells": sum(v[1] for v in got), "last": rec["last"], "since": rec["since"]}
        return out

    def snapshot(self, now_ms=None):
        """Знімок для запису (з циклу подій): години старші за 8 діб — геть. None — записувати нічого."""
        if not self.dirty:
            return None
        edge = (now_ms or _now()) - KEEP_H * HOUR_MS
        recent = (now_ms or _now()) - DONE_MS
        for rec in self.data.values():
            rec["h"] = {h: v for h, v in rec["h"].items() if _hour_ms(h) + HOUR_MS > edge}
            rec["done"] = [x for x in rec.get("done") or [] if x[1] >= recent]
        self.dirty = False
        return json.dumps(self.data, ensure_ascii=False, separators=(",", ":"))

    def write(self, snap):
        """Записати знімок (у фоновому потоці): власний тимчасовий файл і заміна, по одному записувачу за раз."""
        if snap is None:
            return False
        with self.write_lock:
            d = os.path.dirname(str(self.path)) or "."
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=d, prefix=".activity-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(snap)
                os.replace(tmp, self.path)
            except OSError:
                self.dirty = True                     # не записалось: наступна перевірка спробує знову
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        return True

    def save(self):
        """Знімок і запис разом — для тестів і зупинки сервера."""
        return self.write(self.snapshot())
