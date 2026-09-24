"""Простой JSON-кэш ключ→значение с TTL. Экономит запросы к платным API.

Потокобезопасный: запись файла обходит словарь, который другой поток в этот момент дополняет, а два
одновременных flush() писали бы в один и тот же .tmp."""
import os
import json
import threading
import time


class JsonCache:
    def __init__(self, path, ttl_hours=72, flush_every=25):
        self.path = path
        self.ttl = ttl_hours * 3600
        self.flush_every = flush_every
        self._dirty = 0
        self._lock = threading.RLock()   # реентерабельный: put() сам вызывает flush()
        self.data = {}
        if path and os.path.exists(path):
            try:
                with open(path) as f:
                    self.data = json.load(f)
            except Exception:
                self.data = {}   # битый кэш не должен ронять прогон

    def get(self, key):
        with self._lock:
            e = self.data.get(key)
        if not e:
            return None
        if self.ttl and (time.time() - e.get("ts", 0)) > self.ttl:
            return None          # протух
        return e.get("value")

    def put(self, key, value):
        with self._lock:
            self.data[key] = {"value": value, "ts": time.time()}
            self._dirty += 1
            if self._dirty >= self.flush_every:
                self.flush()

    def flush(self):
        with self._lock:
            if not self.path or self._dirty == 0:
                return
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.data, f)
            os.replace(tmp, self.path)   # атомарно — не бьём кэш при сбое записи
            self._dirty = 0
