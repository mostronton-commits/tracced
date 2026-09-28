"""Листи власнику з сайту («Contact»): помилка, ідея, питання. Один JSONL-файл, читає лише власник на /admin.

Поруч `state.json`: які листи власник уже прочитав. Видалення переписує файл без листа (атомарно), тож видалене
справді зникає, а не лише ховається."""
import json
import os
import re
import secrets
import threading
import time

KINDS = ("bug", "idea", "question", "other")
MAX_TEXT, MAX_CONTACT, MAX_PAGE = 2000, 120, 200
URL_RE = re.compile(r"(https?://|www\.|t\.me/|\b[a-z0-9-]+\.(?:com|io|xyz|ru|net|org|app|me|site|online|top|click)\b)", re.I)


def key_of(rec):
    """Стабільний id листа: новим — свій, старим (записаним до id) — час у мс."""
    return str(rec.get("id") or rec.get("ts_ms") or "")


def _key_line(line):
    try:
        rec = json.loads(line)
    except ValueError:
        return None
    return key_of(rec) if isinstance(rec, dict) else None


def links(text):
    """Скільки посилань у тексті: спам майже завжди несе їх пачкою, людина — одне-два."""
    return len(URL_RE.findall(text or ""))


def _norm(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())


class FeedbackStore:
    def __init__(self, path):
        self.path = str(path)
        self.state_path = os.path.join(os.path.dirname(self.path) or ".", "state.json")
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)

    def add(self, rec):
        rec = dict(rec, id=rec.get("id") or secrets.token_hex(6))
        with self._lock, open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec["id"]

    def _lines(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                return f.readlines()
        except OSError:
            return []

    def _tail(self, n):
        """Останні n рядків, не читаючи весь файл: скринька росте, а форма шукає повтор на кожен лист."""
        try:
            with open(self.path, "rb") as f:
                f.seek(0, os.SEEK_END)
                pos, data = f.tell(), b""
                while pos > 0 and data.count(b"\n") <= n:
                    step = min(65536, pos)
                    pos -= step
                    f.seek(pos)
                    data = f.read(step) + data
        except OSError:
            return []
        return data.decode("utf-8", errors="replace").splitlines(keepends=True)[-n:]   # перший, обрізаний, лишається за межею

    def _state(self):
        try:
            with open(self.state_path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        return {"read": dict(d.get("read") or {})}

    def _save_state(self, st):
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f)
        os.replace(tmp, self.state_path)

    def recent(self, n=200):
        """Останні n листів, новіші першими, кожен з `id` і `read`; битий рядок пропускається."""
        with self._lock:
            lines, read = self._tail(n), self._state()["read"]
        out = []
        for line in reversed(lines):
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict):
                continue
            rec["id"] = key_of(rec)
            rec["read"] = rec["id"] in read
            out.append(rec)
        return out

    def seen(self, text, now_ms, window_ms=86_400_000, n=300):
        """Такий самий текст уже приходив за останню добу: повтор не пишемо вдруге."""
        want = _norm(text)
        for rec in self.recent(n):
            if now_ms - int(rec.get("ts_ms") or 0) > window_ms:
                break
            if _norm(rec.get("text")) == want:
                return True
        return False

    def mark(self, fid, read=True):
        """Прочитано / знову нове. False — такого листа нема."""
        with self._lock:
            if not any(_key_line(x) == fid for x in self._lines()):
                return False
            st = self._state()
            if read:
                st["read"][fid] = int(time.time() * 1000)
            else:
                st["read"].pop(fid, None)
            self._save_state(st)
        return True

    def delete(self, fid):
        """Прибрати лист з файлу назовсім. False — такого листа нема."""
        with self._lock:
            lines, keep, found = self._lines(), [], False
            for line in lines:
                if _key_line(line) == fid:
                    found = True
                else:
                    keep.append(line)
            if not found:
                return False
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.writelines(keep)
            os.replace(tmp, self.path)
            st = self._state()
            if st["read"].pop(fid, None) is not None:
                self._save_state(st)
        return True
