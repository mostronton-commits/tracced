"""Черга аналізів: один робочий потік, стан у пам'яті, результати на диску.

Аналізи йдуть по одному. Паралельність живе всередині аналізу (угоди гаманців тягнуться кількома потоками), а
слоти запитів до Solana Tracker спільні: два аналізи поруч ділили б ті самі слоти і обидва йшли б повільніше.
Програвання демо запитів не робить, тож має свої два потоки і не стоїть у черзі перед платним прогоном.
Файл output/early/web/<id>.json пишеться після завершення; при старті список минулих
аналізів читається з диска, тож перезапуск контейнера їх не втрачає.
"""
import datetime
import json
import os
import queue
import re
import secrets
import threading
import time

from ..early.tags import BUNDLE_REV


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
        self.owner = None                 # гаманець, який запустив аналіз (демо і старі — None)
        self.canon = None                 # програвання демо: id збереженого аналізу, який воно показує
        self.s_over = None                # стелі саме цього прогону (адмін — без стель), не зберігаються
        self.charged = []                 # добові лічильники, з яких узято цей прогін (браузер, мережа)
        self.spent = None                 # скільки запитів прогін справді зробив; None — невідомо (рестарт)
        self.progress = {"phase": "queued", "done": 0, "total": None}

    def set_progress(self, phase, done=0, total=None):
        """Замінює словник цілком (а не мутує): сторінка читає його з іншого потоку."""
        self.progress = {"phase": phase, "done": int(done or 0), "total": (int(total) if total else None),
                         "updated_ms": int(time.time() * 1000)}

    def to_dict(self, with_result=True):
        d = {"id": self.id, "mint": self.mint, "t_from": self.t_from, "t_to": self.t_to,
             "t_exit": self.t_exit, "status": self.status, "error": self.error,
             "created_ms": self.created_ms, "started_ms": self.started_ms, "finished_ms": self.finished_ms,
             "symbol_hint": self.symbol_hint, "progress": self.progress, "owner": self.owner,
             "charged": self.charged, "log": self.log[-200:]}
        if with_result:
            d["result"] = self.result
        return d

    @classmethod
    def from_dict(cls, d):
        j = cls(d["id"], d["mint"], d["t_from"], d["t_to"], d.get("t_exit"))
        j.status, j.error = d.get("status", "done"), d.get("error")
        j.created_ms, j.finished_ms = d.get("created_ms"), d.get("finished_ms")
        j.started_ms, j.symbol_hint = d.get("started_ms"), d.get("symbol_hint")
        j.owner = d.get("owner")
        j.charged = list(d.get("charged") or [])   # рестарт посеред прогону повертає і браузер, і мережу
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


def unnamed(result):
    """Позначений названим, але без жодного імені на 20+ гаманців: так виглядав результат, чиї імена джерело відмовилось
    віддати (24.09, ключ без кредитів). Серед двадцяти гаманців завжди є відомі хоча б за застосунком."""
    return bool(result.get("identities_done")) and not result.get("identities") and len(result.get("rows") or []) >= 20


REPLAY_THREADS = 2                        # демо лише спить між рядками журналу: двох потоків досить і на натовп


class JobQueue:
    def __init__(self, runner, persist_dir, enricher=None, on_error=None, namer=None, enrich_upto=0, on_finish=None):
        self.runner = runner
        self.enricher = enricher              # enricher(job, save) — повільне збагачення після done
        self.namer = namer                    # namer(job, save) — імена гаманців: секунди, окремий потік, без черги за віком
        self.on_error = on_error              # on_error(job) — прогін упав: повернути власнику день
        self.on_finish = on_finish            # on_finish(job) — живий прогін закінчився (як завгодно): рядок журналу
        self.dir = persist_dir
        self.jobs = {}
        self.load_errors = []                 # файли аналізів, які не вдалось прочитати при старті: видно в /health
        self.q = queue.Queue()
        self.rq = queue.Queue()               # програвання демо: окремо від платної черги
        self.eq = queue.Queue()
        self.nq = queue.Queue()
        self.lock = threading.Lock()
        self._save_lock = threading.Lock()
        self._resumed = set()                 # аналізи, чиє збагачення після паузи бюджету вже знову в черзі
        os.makedirs(persist_dir, exist_ok=True)
        self._load()                          # прогони, перервані рестартом, стають помилкою і повертають день
        self.thread = threading.Thread(target=self._worker, name="early-worker", daemon=True)
        self.thread.start()
        for i in range(REPLAY_THREADS):
            threading.Thread(target=self._replay_worker, name=f"early-replay-{i}", daemon=True).start()
        # недороблене до перезапуску — найсвіжіші першими: саме їх зараз і відкривають
        done = sorted((j for j in self.jobs.values() if j.status == "done" and j.result and not j.replay),
                      key=lambda j: j.created_ms or 0, reverse=True)
        if namer:
            self.nthread = threading.Thread(target=self._name_worker, name="early-names", daemon=True)
            self.nthread.start()
            for j in done:                    # імен не питали (результат до v0.4 або рестарт): пакет на 100 гаманців, раз
                if not j.result.get("identities_done") or unnamed(j.result):
                    self.nq.put(j)
        if enricher:
            self.ethread = threading.Thread(target=self._enrich_worker, name="early-enrich", daemon=True)
            self.ethread.start()
            for j in done:
                e = j.result.get("enrich") or {}
                # стелю збагачення підняли (ключ ноди з'явився, чи перевіряємо вже всіх): старі результати
                # дозаповнюються у фоні, з того місця, де зупинились. enrich_upto(result) каже, скільки рядків
                # саме цьому результату належить перевірити (у старших, без підпису покупки, — лише перші за PnL)
                upto = (enrich_upto(j.result) if callable(enrich_upto)
                        else min(len(j.result.get("rows") or []), int(enrich_upto or 0)))
                if (not e or e.get("done", 0) < e.get("total", 0) or e.get("failed") or e.get("funders_failed")
                        or e.get("funders_done", 0) < e.get("total", 0) or e.get("total", 0) < upto
                        or (j.result.get("funders") and j.result.get("bundle_rev") != BUNDLE_REV)):   # бандли за старим правилом
                    self.eq.put(j)

    def _load(self):
        for name in os.listdir(self.dir):
            if name.endswith(".json"):
                try:
                    with open(os.path.join(self.dir, name), encoding="utf-8") as f:
                        j = Job.from_dict(json.load(f))
                    if j.status in ("queued", "running"):
                        j.status, j.error = "error", "interrupted by a server restart — run it again, your day is not spent"
                        j.finished_ms = int(time.time() * 1000)
                        if self.on_error:
                            try:
                                self.on_error(j)
                            except Exception:  # noqa: BLE001
                                pass
                        try:
                            self._save(j)
                        except OSError:
                            pass
                        self._finished(j)
                    if j.result:
                        from ..early.report import upgrade_result
                        upgrade_result(j.result)              # файли до перейменування window → range
                    self.jobs[j.id] = j
                except Exception as e:  # noqa: BLE001 — битий файл не валить сторінку, але й не зникає мовчки
                    self.load_errors.append(f"{name}: {type(e).__name__}: {str(e)[:120]}")
                    continue

    def _save(self, job, only_current=False):
        """Робочий потік і збагачення пишуть той самий <id>.json через той самий .tmp: по одному. Збагачення
        старого аналізу, який уже перезапустили, пише лише поки він ще поточний, і перевірка йде під тим самим
        замком, що й запис, інакше старий результат міг би лягти поверх нового.

        Текст збирає json.dumps одним викликом: C-кодувальник не віддає GIL посеред словника, а json.dump віддавав,
        і потік імен чи збагачення, що саме дописував ключ, валив запис («dictionary changed size during iteration»)."""
        if job.replay:
            return False                      # програвання демо — лише показ знімка: на диск не лягає ніколи
        with self._save_lock:
            if only_current and not self._current(job):
                return False                  # аналіз видалили або перезапустили: хто зберігав, хай зупиниться
            text = json.dumps(job.to_dict(), ensure_ascii=False, default=str)
            path = os.path.join(self.dir, job.id + ".json")
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, path)
            return True

    def submit(self, mint, t_from, t_to, symbol=None, replay=None, owner=None, s_over=None, charged=None):
        """Живий прогін живе під id діапазону. Програвання демо отримує свій id (…_r + 6 hex), щоб не витісняти
        збережений аналіз, який у цей час читають інші; старі програвання прибираються з пам'яті."""
        canon = make_id(mint, t_from, t_to)
        id = f"{canon}_r{secrets.token_hex(3)}" if replay else canon
        with self.lock:
            cur = self.jobs.get(id)
            if cur and cur.status in ("queued", "running"):
                return cur                            # той самий аналіз уже йде
            if replay:
                stale = int(time.time() * 1000) - 600_000
                for k in [k for k, j in self.jobs.items() if j.replay and j.finished_ms and j.finished_ms < stale]:
                    self.jobs.pop(k, None)
            job = Job(id, mint, t_from, t_to)
            job.symbol_hint = symbol
            job.replay = replay
            job.canon = canon if replay else None
            job.owner, job.s_over, job.charged = owner, s_over, list(charged or [])
            self.jobs[id] = job
        if replay:
            self.rq.put(job)                  # демо не чекає за платним прогоном, а прогін — за натовпом у демо
            return job
        try:
            self._save(job)                   # у черзі — уже на диску: рестарт побачить його і поверне день
        except OSError:
            pass
        self.q.put(job)
        return job

    def get(self, id):
        return self.jobs.get(id)

    def remove(self, id):
        """Забрати аналіз з пам'яті і з диска; збагачення, що ще йде, помітить це через _current. Під замком запису:
        інакше збереження, що вже пройшло перевірку _current, повернуло б файл, і аналіз ожив би після рестарту."""
        with self._save_lock:
            with self.lock:
                job = self.jobs.pop(id, None)
            if job is None:
                return False
            try:
                os.remove(os.path.join(self.dir, id + ".json"))
            except FileNotFoundError:
                pass
        return True

    def resume_enrich(self, job):
        """Пауза бюджету RPC минула (новий місяць): збагачення доробляється без рестарту, раз на аналіз."""
        if not self.enricher:
            return
        with self.lock:
            if job.id in self._resumed:
                return
            self._resumed.add(job.id)
        self.eq.put(job)

    def recent(self, n=30):
        return sorted((j for j in self.jobs.values() if not j.replay), key=lambda j: j.created_ms or 0, reverse=True)[:n]

    def _worker(self):
        while True:
            job = self.q.get()
            self._run(job)
            self.q.task_done()

    def _replay_worker(self):
        while True:
            job = self.rq.get()
            self._run(job)
            self.rq.task_done()

    def _run(self, job):
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
            if self.on_error:
                try:
                    self.on_error(job)
                except Exception as e2:  # noqa: BLE001
                    job.log.append(f"could not give the run back: {e2}")
        job.finished_ms = int(time.time() * 1000)
        try:
            if not job.replay:                # програвання демо не чіпає збережений аналіз на диску
                self._save(job)
        except Exception as e:  # noqa: BLE001
            job.log.append(f"could not save the result: {e}")
            self.load_errors.append(f"{job.id}.json not saved: {type(e).__name__}: {str(e)[:120]}")
        self._finished(job)
        if job.status == "done" and job.result and not job.replay:   # демо вже збагачене
            if self.namer:
                self.nq.put(job)
            if self.enricher:
                self.eq.put(job)

    def _finished(self, job):
        """Живий прогін закінчився — успіхом, помилкою чи рестартом посеред роботи. Програвання демо — лише показ."""
        if self.on_finish and not job.replay:
            try:
                self.on_finish(job)
            except Exception:  # noqa: BLE001 — журнал не має валити чергу
                pass

    def _current(self, job):
        """Чи це ще той самий аналіз? Повторний запуск того ж діапазону кладе на його місце новий."""
        return self.jobs.get(job.id) is job

    def _name_worker(self):
        while True:
            job = self.nq.get()
            try:
                if self._current(job):
                    self.namer(job, lambda j: self._save(j, only_current=True))
            except Exception as e:  # noqa: BLE001 — імена не мають валити результат
                job.log.append(f"wallet names unavailable: {str(e)[:60]}")
            self.nq.task_done()

    def _enrich_worker(self):
        while True:
            job = self.eq.get()
            try:
                if self._current(job):           # аналіз перезапустили: старе збагачення не чіпає новий результат
                    self.enricher(job, lambda j: self._save(j, only_current=True))
            except Exception as e:  # noqa: BLE001 — збагачення не має валити результат
                job.log.append(f"enrichment stopped: {e}")
            with self.lock:
                self._resumed.discard(job.id)
            self.eq.task_done()
