"""Кеш угод токена на диску: покриття відрізків часу, а не сторінки за курсором.

Чому так: у липні непокешована пагінація /trades спалила квоту. Тут кожна завантажена
сторінка одразу дописується у JSONL, а мета-файл пам'ятає, які відрізки часу вже
покриті. Зсув меж вікна тягне лише незакриті шматки; повтор — нуль запитів.

Файли: cache/early/trades_<mint>.jsonl (append-only) + trades_<mint>.meta.json.

Курсор Solana Tracker — це час, тож довгий відрізок можна різати на шматки і тягнути їх одночасно
(`ensure(..., workers=K)`): кожен шматок — свій ланцюжок сторінок, густий шматок по дорозі ділиться навпіл.
Пише в сховище лише потік, що кличе ensure; робочі потоки тільки ходять по сторінки.
"""
import contextvars
import json
import os
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

SPLIT_MIN_PAGES = 4          # залишок шматка ділимо навпіл, лише коли в ньому ще стільки сторінок
SPLIT_MIN_MS = 60_000        # коротший відрізок на старті не ріжемо


class PageBudget(Exception):
    """Стеля сторінок за прогін досягнута; усе завантажене вже збережено."""

    def __init__(self, pages, covered_to):
        super().__init__(f"page cap reached: {pages}")
        self.pages = pages
        self.covered_to = covered_to


def _merge(intervals):
    out = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


class TradeStore:
    def __init__(self, dir_path, mint):
        self.dir = dir_path
        self.mint = mint
        self.path = os.path.join(dir_path, f"trades_{mint}.jsonl")
        self.meta_path = os.path.join(dir_path, f"trades_{mint}.meta.json")
        self._trades = []
        self._unsorted = False       # сортуємо, коли хтось читає, а не після кожної сторінки
        self._keys = set()
        self.covered = []
        self._load()

    # ── диск ──
    def _load(self):
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        tr = json.loads(line)
                    except ValueError:
                        continue                      # обірваний рядок після збою — пропуск
                    if self._key(tr) not in self._keys:
                        self._keys.add(self._key(tr))
                        self._trades.append(tr)
            self._trades.sort(key=lambda x: x["time"] or 0)
        if os.path.exists(self.meta_path):
            try:
                with open(self.meta_path, encoding="utf-8") as f:
                    self.covered = _merge([tuple(x) for x in json.load(f).get("covered", [])])
            except Exception:
                self.covered = []

    def _save_meta(self):
        os.makedirs(self.dir, exist_ok=True)
        tmp = self.meta_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"mint": self.mint, "covered": self.covered}, f)
        os.replace(tmp, self.meta_path)

    @staticmethod
    def _key(tr):
        return f"{tr.get('tx')}|{tr.get('wallet')}|{tr.get('type')}|{tr.get('time')}|{tr.get('qty')}"

    # ── дані ──
    @property
    def trades(self):
        """Усі угоди за часом. Сортування відкладене: сотні сторінок поспіль більше не сортують увесь список щоразу."""
        if self._unsorted:
            self._trades.sort(key=lambda x: x["time"] or 0)
            self._unsorted = False
        return self._trades

    def add(self, trades):
        """Додає нові угоди (дублі відкидає), одразу дописує на диск. Повертає число нових."""
        os.makedirs(self.dir, exist_ok=True)
        new = [tr for tr in trades if self._key(tr) not in self._keys]
        if not new:
            return 0
        with open(self.path, "a", encoding="utf-8") as f:
            for tr in new:
                self._keys.add(self._key(tr))
                f.write(json.dumps(tr, ensure_ascii=False) + "\n")
        self._trades.extend(new)
        self._unsorted = True
        return len(new)

    def mark_covered(self, a, b):
        if b > a:
            self.covered = _merge(self.covered + [[a, b]])
            self._save_meta()

    def gaps(self, a, b):
        """Незакриті шматки [a, b]."""
        out, cur = [], a
        for ca, cb in self.covered:
            if cb <= cur:
                continue
            if ca >= b:
                break
            if ca > cur:
                out.append((cur, min(ca, b)))
            cur = max(cur, cb)
            if cur >= b:
                break
        if cur < b:
            out.append((cur, b))
        return out

    def save_candles(self):
        """Хвилинні свічки (ціна в $) з усіх угод сховища — щоб графік заповнив місця, де джерело свічок мовчить.

        У частини токенів після міграції Solana Tracker не знає пулу, де йшла торгівля (у SI 24.09 — PumpSwap), і
        графік має діру якраз на пампі. Угоди ми вже купили під час аналізу, тож свічки з них нічого не коштують.
        Разом зі свічками зберігаємо покриття: заповнювати можна лише там, де угоди відомі повністю."""
        minutes = {}
        for tr in self.trades:                          # уже за часом
            t, pr = tr.get("time"), tr.get("price")
            if t is None or not pr or pr <= 0:
                continue
            minutes.setdefault(int(t // 60000) * 60, []).append((float(pr), float(tr.get("usd") or 0)))
        by = {}
        for m, xs in minutes.items():
            # окрема угода з битою ціною дала б тінь у тисячу разів вищу за ринок і сплющила б увесь графік:
            # ціни хвилини беремо лише в межах утричі від її медіани (джерело свічок так само прибирає викиди)
            med = sorted(p_ for p_, _ in xs)[len(xs) // 2]
            ok = [x for x in xs if med / 3 <= x[0] <= med * 3] or xs
            by[m] = [m, ok[0][0], max(x[0] for x in ok), min(x[0] for x in ok), ok[-1][0], sum(v for _, v in xs)]
        os.makedirs(self.dir, exist_ok=True)
        tmp = candles_path(self.dir, self.mint) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"covered": self.covered, "c": [by[k] for k in sorted(by)]}, f)
        os.replace(tmp, candles_path(self.dir, self.mint))
        return len(by)

    def between(self, a, b):
        return [tr for tr in self.trades if tr["time"] is not None and a <= tr["time"] <= b]

    # ── завантаження ──
    def ensure(self, a, b, fetch_page, max_pages, log=None, pages_done=0, on_page=None, workers=1):
        """Закриває всі прогалини [a, b] сторінками fetch_page(cursor_ms) →
        {"trades": [...], "hasNextPage": bool, "nextCursor": ms}. Повертає число сторінок.

        Курсор Solana Tracker ВИКЛЮЧНИЙ (`cursor=T` → угоди з часом > T), а час угод — цілі секунди,
        тож у одній секунді буває кілька угод. Якщо сторінка обривається посеред секунди і йти далі з
        `nextCursor` (= час останньої угоди), решта угод тієї секунди губиться (аудит 17.09.2026:
        1,1 % свопів PAIDDOGE). Тому: стартуємо з `ga - 1`, наступну сторінку беремо з `last_t - 1`
        (межова секунда перечитується, дублі відкидає add()), а покритим вважаємо до `last_t - 1`.

        workers > 1: ті самі правила для кожного шматка, шматки тягнуться одночасно (див. _ensure_parallel)."""
        if workers and workers > 1:
            return self._ensure_parallel(a, b, fetch_page, max_pages, log, pages_done, on_page, int(workers))
        pages = pages_done
        for ga, gb in self.gaps(a, b):
            cursor = ga - 1
            while True:
                if pages >= max_pages:
                    raise PageBudget(pages, cursor + 1)
                d = fetch_page(cursor)
                pages += 1
                trs = d.get("trades") or []
                n_new = self.add(trs)
                times = [tr["time"] for tr in trs if tr["time"] is not None]
                last_t = max(times, default=None)
                if log:
                    log(f"page {pages}: {len(trs)} trades (+{n_new} new)"
                        + (f", up to {_hhmm(last_t)}" if last_t else ""))
                if on_page:
                    on_page(pages, last_t)
                if not trs or not d.get("hasNextPage"):
                    self.mark_covered(ga, max(gb, last_t or ga))   # історія скінчилась
                    break
                if last_t - 1 > gb:
                    self.mark_covered(ga, gb)
                    break
                nxt = last_t - 1                                    # перечитати межову секунду
                if nxt > cursor:
                    self.mark_covered(ga, last_t - 1)
                    cursor = nxt
                elif n_new > 0:
                    self.mark_covered(ga, last_t - 1)               # ціла сторінка — одна секунда: ще раз
                else:
                    # перечитали, нового нема, а сторінка повна: у цій секунді угод більше за сторінку,
                    # курсор по часу далі не зрушить — приймаємо можливу втрату решти секунди, йдемо далі
                    if log:
                        log(f"  warning: a full page of trades within one second at {_hhmm(last_t)} — "
                            f"moving on; a few trades of that second may be missing")
                    self.mark_covered(ga, last_t)
                    cursor = last_t
        return pages

    def _ensure_parallel(self, a, b, fetch_page, max_pages, log, pages_done, on_page, workers):
        """Прогалини ріжуться на `workers` рівних за часом шматків; кожен шматок — ланцюжок сторінок від свого
        початку, як у послідовному шляху. Густина угод нерівна (памп — хвилини, решта — дні), тож шматок, у якому
        після першої сторінки лишається багато сторінок, ділиться навпіл, щойно якийсь потік простоює.

        Чому межі не губляться: перша половина йде, доки її сторінка не перескочить за середину (усе ≤ mid
        прочитано), друга стартує з курсора mid − 1 (усе ≥ mid). Спільна секунда читається двічі, дублі відкидає
        add(). Стеля сторінок рахується разом із тими, що в польоті, тож не перевищується."""
        pages = pages_done
        todo = deque()
        for ga, gb in self.gaps(a, b):
            n = workers if gb - ga > SPLIT_MIN_MS * workers else 1
            step = (gb - ga) / n
            for i in range(n):
                sa = int(ga + i * step)
                sb = int(ga + (i + 1) * step) if i < n - 1 else gb
                todo.append((sa, sb, sa - 1))                          # (початок, кінець, курсор)
        pending = {}
        pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="early-pages")
        clean = False
        try:
            while todo or pending:
                while todo and len(pending) < workers and pages + len(pending) < max_pages:
                    seg = todo.popleft()
                    pending[pool.submit(contextvars.copy_context().run, fetch_page, seg[2])] = seg
                if not pending:
                    break                                               # стеля: у черзі лишились шматки
                finished, _ = wait(pending, return_when=FIRST_COMPLETED)
                for f in finished:
                    sa, sb, cur = pending.pop(f)
                    d = f.result()
                    pages += 1
                    trs = d.get("trades") or []
                    n_new = self.add(trs)
                    times = [tr["time"] for tr in trs if tr["time"] is not None]
                    last_t, first_t = max(times, default=None), min(times, default=None)
                    if log:
                        log(f"page {pages}: {len(trs)} trades (+{n_new} new)"
                            + (f", up to {_hhmm(last_t)}" if last_t else ""))
                    if on_page:
                        on_page(pages, last_t)
                    if not trs or not d.get("hasNextPage"):
                        self.mark_covered(sa, max(sb, last_t or sa))    # далі угод нема взагалі
                        continue
                    if last_t - 1 > sb:
                        self.mark_covered(sa, sb)                       # шматок прочитано до кінця
                        continue
                    nxt = last_t - 1
                    if nxt > cur:
                        self.mark_covered(sa, nxt)
                        cur = nxt
                    elif n_new > 0:
                        self.mark_covered(sa, nxt)                      # ціла сторінка — одна секунда: ще раз
                    else:
                        if log:
                            log(f"  warning: a full page of trades within one second at {_hhmm(last_t)} — "
                                f"moving on; a few trades of that second may be missing")
                        self.mark_covered(sa, last_t)
                        cur = last_t
                    rest, span = sb - cur, (last_t - first_t) if (first_t is not None and last_t > first_t) else 0
                    if span and rest / span > SPLIT_MIN_PAGES and len(todo) + len(pending) < workers:
                        mid = int(cur + rest / 2)
                        todo.appendleft((sa, mid, cur))                 # ця половина — далі без черги
                        todo.append((mid, sb, mid - 1))                 # друга — вільному потоку
                    else:
                        todo.appendleft((sa, sb, cur))
            clean = True
        finally:
            pool.shutdown(wait=clean, cancel_futures=not clean)
        if todo:
            left = self.gaps(a, b)
            raise PageBudget(pages, left[0][0] if left else b)
        return pages


def candles_path(dir_path, mint):
    return os.path.join(dir_path, f"candles_{mint}.json")


def load_candles(dir_path, mint):
    """Хвилинні свічки з наших угод, збережені після аналізу: {"covered": [[a, b] мс], "c": [[t с, o, h, l, c, $]]}."""
    try:
        with open(candles_path(dir_path, mint), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _hhmm(ms):
    import datetime
    return datetime.datetime.utcfromtimestamp(ms / 1000).strftime("%m-%d %H:%M")
