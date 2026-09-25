"""Методика агента, яку пише власник, її версії і журнал усіх питань до агента — у output/early/agent/.

config.json — чинна методика (v росте з кожним збереженням), history.jsonl — кожна збережена версія (до неї можна
повернутись), log.jsonl — хто що питав, чи було питання про аналіз, що перевірка відкинула і скільки це коштувало.
"""
import json
import os
import threading
import time

from ..early import agent as agent_mod

LOG_KEEP = 5000          # журнал читається з кінця; довше за це файл обрізається при записі


class AgentStore:
    def __init__(self, path):
        self.dir = str(path)
        self._lock = threading.Lock()
        os.makedirs(self.dir, exist_ok=True)
        self._config = None

    def _p(self, name):
        return os.path.join(self.dir, name)

    def config(self):
        with self._lock:
            if self._config is None:
                try:
                    with open(self._p("config.json"), encoding="utf-8") as f:
                        raw = json.load(f)
                except (OSError, ValueError):
                    raw = {"v": 0}
                self._config = agent_mod.normalize_config(raw)
                self._config.setdefault("v", 0)
            return dict(self._config)

    def save(self, raw, by):
        """Нова версія методики; повертає її. Попередні лишаються в history.jsonl."""
        cfg = agent_mod.normalize_config(raw)
        with self._lock:
            prev = self._config["v"] if self._config else self._read_v()
            cfg.update(v=prev + 1, saved_ms=int(time.time() * 1000), by=by)
            tmp = self._p("config.json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self._p("config.json"))
            with open(self._p("history.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(cfg, ensure_ascii=False) + "\n")
            self._config = cfg
        return dict(cfg)

    def _read_v(self):
        try:
            with open(self._p("config.json"), encoding="utf-8") as f:
                return int(json.load(f).get("v") or 0)
        except (OSError, ValueError, TypeError):
            return 0

    def history(self, n=20):
        return list(reversed(self._tail("history.jsonl", n)))

    def version(self, v):
        for c in self._tail("history.jsonl", 10_000):
            if c.get("v") == v:
                return c
        return None

    def log(self, entry):
        entry = dict(entry, ts_ms=int(time.time() * 1000))
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with self._lock:
            with open(self._p("log.jsonl"), "a", encoding="utf-8") as f:
                f.write(line)
            try:
                if os.path.getsize(self._p("log.jsonl")) > LOG_KEEP * 2_000:
                    keep = self._tail_unlocked("log.jsonl", LOG_KEEP)
                    tmp = self._p("log.jsonl.tmp")
                    with open(tmp, "w", encoding="utf-8") as f:
                        f.writelines(json.dumps(e, ensure_ascii=False) + "\n" for e in keep)
                    os.replace(tmp, self._p("log.jsonl"))
            except OSError:
                pass

    def recent(self, n=50):
        return list(reversed(self._tail("log.jsonl", n)))

    def _tail(self, name, n):
        with self._lock:
            return self._tail_unlocked(name, n)

    def _tail_unlocked(self, name, n):
        try:
            with open(self._p(name), encoding="utf-8") as f:
                lines = f.readlines()[-n:]
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out
