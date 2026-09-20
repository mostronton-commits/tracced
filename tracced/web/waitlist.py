"""Лист очікування: e-mail (+ що людина торгує, + гаманець, якщо увійшла) → один JSONL на сервері.

Це перші цифри трекшну і ціль для підказки «аналізи в закритій беті». Дедуп по e-mail у нижньому
регістрі, нічого нікуди не надсилається; читає лише власник на /admin.
"""
import json
import logging
import os
import re
import threading
import time

log = logging.getLogger("early.waitlist")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[A-Za-z]{2,}$")
MAX_NOTE = 120


class Waitlist:
    def __init__(self, path):
        self.path = str(path)
        self.lock = threading.Lock()
        self.emails = set()
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        for rec in self._read():
            self.emails.add(rec.get("email", ""))

    def _read(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                lines = f.readlines()
        except FileNotFoundError:
            return []
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    def add(self, email, note="", pubkey=""):
        """True, якщо адреса нова; ValueError, якщо це не e-mail."""
        email = str(email or "").strip().lower()
        if not EMAIL_RE.match(email):
            raise ValueError("not an e-mail")
        rec = {"ts_ms": int(time.time() * 1000), "email": email,
               "note": " ".join(str(note or "").split())[:MAX_NOTE], "pubkey": str(pubkey or "")[:64]}
        with self.lock:
            if email in self.emails:
                return False
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self.emails.add(email)
        return True

    def count(self):
        return len(self.emails)

    def tail(self, n=50):
        """Найновіші першими."""
        return self._read()[-n:][::-1]
