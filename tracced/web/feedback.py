"""Листи власнику з сайту («Write to us»): помилка, ідея, питання. Один JSONL-файл, читає лише власник на /admin."""
import json
import os
import threading

KINDS = ("bug", "idea", "question", "other")
MAX_TEXT, MAX_CONTACT, MAX_PAGE = 2000, 120, 200


class FeedbackStore:
    def __init__(self, path):
        self.path = str(path)
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)

    def add(self, rec):
        with self._lock, open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def recent(self, n=200):
        """Останні n листів, новіші першими; битий рядок пропускається."""
        try:
            with self._lock, open(self.path, encoding="utf-8") as f:
                lines = f.readlines()[-n:]
        except OSError:
            return []
        out = []
        for line in reversed(lines):
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out
