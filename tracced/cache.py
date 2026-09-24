"""Простой JSON-кэш ключ→значение с TTL. Экономит запросы к платным API.

Потокобезопасный: данные под `_lock`, запись файла под отдельным `_write_lock`. Файл пишется из снимка, снятого
под замком данных, а сама запись идёт уже без него: get() на цикле событий не ждёт многомегабайтный дамп, а два
flush() никогда не пишут в один и тот же .tmp одновременно. Протухшие записи выбрасываются при загрузке и перед
каждой записью, иначе файл только растёт."""
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
        self._lock = threading.RLock()          # данные: get/put/снимок для записи
        self._write_lock = threading.Lock()     # файл: одна запись за раз
        self.data = {}
        if path and os.path.exists(path):
            try:
                with open(path) as f:
                    self.data = json.load(f)
            except Exception:
                self.data = {}   # битый кэш не должен ронять прогон
            self._prune(time.time())

    def _prune(self, now):
        """Выбросить протухшие записи (без TTL — хранить всё). Вызывать под `_lock`."""
        if self.ttl:
            self.data = {k: e for k, e in self.data.items()
                         if isinstance(e, dict) and now - e.get("ts", 0) <= self.ttl}

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
            due = self._dirty >= self.flush_every
        if due:
            self._flush(block=False)

    def put_many(self, items):
        """Много записей одним шагом: один замок и один шаг к очередной записи файла."""
        if not items:
            return
        with self._lock:
            now = time.time()
            for key, value in items.items():
                self.data[key] = {"value": value, "ts": now}
            self._dirty += 1
            due = self._dirty >= self.flush_every
        if due:
            self._flush(block=False)

    def flush(self):
        self._flush(block=True)

    def _flush(self, block):
        if not self.path:
            return
        # put() не ждёт чужую запись: если файл уже пишется, его данные уйдут со следующей
        if not self._write_lock.acquire(blocking=block):
            return
        try:
            with self._lock:
                if self._dirty == 0:
                    return
                self._prune(time.time())
                snap, dirty = dict(self.data), self._dirty
                self._dirty = 0
            try:
                text = json.dumps(snap)          # C-кодировщик, вне замка данных: записи заменяются, а не правятся
                os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
                tmp = self.path + ".tmp"
                with open(tmp, "w") as f:
                    f.write(text)
                os.replace(tmp, self.path)   # атомарно — не бьём кэш при сбое записи
            except BaseException:
                with self._lock:
                    self._dirty += dirty         # не записалось — следующий flush попробует снова
                raise
        finally:
            self._write_lock.release()
