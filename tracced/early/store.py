"""Кеш угод токена на диску: покриття відрізків часу, а не сторінки за курсором.

Чому так: у липні непокешована пагінація /trades спалила квоту. Тут кожна завантажена
сторінка одразу дописується у JSONL, а мета-файл пам'ятає, які відрізки часу вже
покриті. Зсув меж вікна тягне лише незакриті шматки; повтор — нуль запитів.

Файли: cache/early/trades_<mint>.jsonl (append-only) + trades_<mint>.meta.json.
"""
import json
import os


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
        self.trades = []
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
                        self.trades.append(tr)
            self.trades.sort(key=lambda x: x["time"] or 0)
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
        self.trades.extend(new)
        self.trades.sort(key=lambda x: x["time"] or 0)
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

    def between(self, a, b):
        return [tr for tr in self.trades if tr["time"] is not None and a <= tr["time"] <= b]

    # ── завантаження ──
    def ensure(self, a, b, fetch_page, max_pages, log=None, pages_done=0, on_page=None):
        """Закриває всі прогалини [a, b] сторінками fetch_page(cursor_ms) →
        {"trades": [...], "hasNextPage": bool, "nextCursor": ms}. Повертає число сторінок.

        Курсор Solana Tracker ВИКЛЮЧНИЙ (`cursor=T` → угоди з часом > T), а час угод — цілі секунди,
        тож у одній секунді буває кілька угод. Якщо сторінка обривається посеред секунди і йти далі з
        `nextCursor` (= час останньої угоди), решта угод тієї секунди губиться (аудит 17.09.2026:
        1,1 % свопів PAIDDOGE). Тому: стартуємо з `ga - 1`, наступну сторінку беремо з `last_t - 1`
        (межова секунда перечитується, дублі відкидає add()), а покритим вважаємо до `last_t - 1`."""
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


def _hhmm(ms):
    import datetime
    return datetime.datetime.utcfromtimestamp(ms / 1000).strftime("%m-%d %H:%M")
