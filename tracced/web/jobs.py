"""Черга аналізів: один робочий потік, стан у пам'яті, результати на диску.

Один потік — бо ліміт Solana Tracker спільний і два аналізи паралельно нічого не пришвидшать.
Файл output/early/web/<id>.json пишеться після завершення; при старті список минулих
аналізів читається з диска, тож перезапуск контейнера їх не втрачає.
"""
import datetime
import json
import os
import queue
import re
import threading
import time


class Job:
    def __init__(self, id, mint, t_from, t_to, t_exit=None):
        self.id, self.mint = id, mint
        self.t_from, self.t_to, self.t_exit = t_from, t_to, t_exit   # t_exit лише у старих результатах
        self.status = "queued"            # queued → running → done | error
        self.log = []
        self.result = None
        self.error = None
        self.created_ms = int(time.time() * 1000)
        self.started_ms = None
        self.finished_ms = None
        self.symbol_hint = None
        self.replay = None                # {"log": [...], "result": {...}} — демо: програти без запитів
        self.progress = {"phase": "queued", "done": 0, "total": None}

    def set_progress(self, phase, done=0, total=None):
        """Замінює словник цілком (а не мутує): сторінка читає його з іншого потоку."""
        self.progress = {"phase": phase, "done": int(done or 0), "total": (int(total) if total else None),
                         "updated_ms": int(time.time() * 1000)}

    def to_dict(self, with_result=True):
        d = {"id": self.id, "mint": self.mint, "t_from": self.t_from, "t_to": self.t_to,
             "t_exit": self.t_exit, "status": self.status, "error": self.error,
             "created_ms": self.created_ms, "started_ms": self.started_ms, "finished_ms": self.finished_ms,
             "symbol_hint": self.symbol_hint, "progress": self.progress,
             "log": self.log[-200:]}
        if with_result:
            d["result"] = self.result
        return d

    @classmethod
    def from_dict(cls, d):
        j = cls(d["id"], d["mint"], d["t_from"], d["t_to"], d.get("t_exit"))
        j.status, j.error = d.get("status", "done"), d.get("error")
        j.created_ms, j.finished_ms = d.get("created_ms"), d.get("finished_ms")
        j.started_ms, j.symbol_hint = d.get("started_ms"), d.get("symbol_hint")
        j.progress = d.get("progress") or {"phase": d.get("status", "done"), "done": 0, "total": None}
        j.log, j.result = d.get("log") or [], d.get("result")
        return j

    @property
    def symbol(self):
        return ((self.result or {}).get("info") or {}).get("symbol") or self.symbol_hint or self.mint[:6]


def make_id(mint, t_from, t_to):
    """Той самий діапазон = той самий аналіз: повторний запуск оновлює його (історія до «зараз»)."""
    f = datetime.datetime.utcfromtimestamp
    return re.sub(r"[^A-Za-z0-9_-]", "", f"{mint[:6]}_{f(t_from / 1000):%Y%m%d-%H%M}_{f(t_to / 1000):%H%M}")


class JobQueue:
    def __init__(self, runner, persist_dir, enricher=None):
        self.runner = runner
        self.enricher = enricher              # enricher(job, save) — повільне збагачення після done
        self.dir = persist_dir
        self.jobs = {}
        self.q = queue.Queue()
        self.eq = queue.Queue()
        self.lock = threading.Lock()
        os.makedirs(persist_dir, exist_ok=True)
        self._load()
        self.thread = threading.Thread(target=self._worker, name="early-worker", daemon=True)
        self.thread.start()
        if enricher:
            self.ethread = threading.Thread(target=self._enrich_worker, name="early-enrich", daemon=True)
            self.ethread.start()
            for j in self.jobs.values():      # недороблене збагачення після перезапуску
                e = (j.result or {}).get("enrich") or {}
                if j.status == "done" and j.result and (not e or e.get("done", 0) < e.get("total", 0) or e.get("failed")
                                                        or e.get("funders_done", 0) < e.get("total", 0)):
                    self.eq.put(j)

    def _load(self):
        for name in os.listdir(self.dir):
            if name.endswith(".json"):
                try:
                    with open(os.path.join(self.dir, name), encoding="utf-8") as f:
                        j = Job.from_dict(json.load(f))
                    if j.status in ("queued", "running"):
                        j.status, j.error = "error", "interrupted by a restart"
                    if j.result:
                        from ..early.report import upgrade_result
                        upgrade_result(j.result)              # файли до перейменування window → range
                    self.jobs[j.id] = j
                except Exception:
                    continue                          # битий файл не валить сторінку

    def _save(self, job):
        path = os.path.join(self.dir, job.id + ".json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(job.to_dict(), f, ensure_ascii=False, default=str)
        os.replace(tmp, path)

    def submit(self, mint, t_from, t_to, symbol=None, replay=None):
        id = make_id(mint, t_from, t_to)
        with self.lock:
            cur = self.jobs.get(id)
            if cur and cur.status in ("queued", "running"):
                return cur                            # той самий аналіз уже йде
            job = Job(id, mint, t_from, t_to)
            job.symbol_hint = symbol
            job.replay = replay
            self.jobs[id] = job
        self.q.put(job)
        return job

    def get(self, id):
        return self.jobs.get(id)

    def recent(self, n=30):
        return sorted(self.jobs.values(), key=lambda j: j.created_ms or 0, reverse=True)[:n]

    def _worker(self):
        while True:
            job = self.q.get()
            job.started_ms = int(time.time() * 1000)
            job.status = "running"
            job.set_progress("token")
            try:
                job.result = self.runner(job)
                job.status = "done"
                job.set_progress("done", 1, 1)
            except Exception as e:  # noqa: BLE001 — причина йде людині на сторінку
                job.status, job.error = "error", str(e)
                job.set_progress("error", 1, 1)
            job.finished_ms = int(time.time() * 1000)
            try:
                if not job.replay:                # програвання демо не чіпає збережений аналіз на диску
                    self._save(job)
            except Exception as e:  # noqa: BLE001
                job.log.append(f"could not save the result: {e}")
            if self.enricher and job.status == "done" and job.result:
                self.eq.put(job)
            self.q.task_done()

    def _current(self, job):
        """Чи це ще той самий аналіз? Повторний запуск того ж діапазону кладе на його місце новий."""
        return self.jobs.get(job.id) is job

    def _enrich_worker(self):
        while True:
            job = self.eq.get()
            try:
                if not self._current(job):
                    self.eq.task_done()          # аналіз перезапустили: старе збагачення не чіпає новий результат
                    continue
                self.enricher(job, lambda j: self._current(j) and self._save(j))
            except Exception as e:  # noqa: BLE001 — збагачення не має валити результат
                job.log.append(f"enrichment stopped: {e}")
            self.eq.task_done()
