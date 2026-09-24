"""Спайк: наш PnL гаманця за 30 днів проти цифри Solana Tracker. Нічого не пише, лише друкує таблицю.

Навіщо. У картці гаманця показуємо лише власний порахунок із сирих обмінів (`tracced/early/profile.py`). Перед
тим як йому довіряти, звіряємо з `/v2/pnl/wallets/{w}/performance?period=30d` (`totals.realizedPnl`) на справжніх
гаманцях. Систематичне розходження треба пояснити: це наші перекази і токен→токен, чи їхня евристика «strict».

Ціна: на гаманець 1–5 запитів обмінів + 1 запит їхнього PnL. 20 гаманців ≈ 40–120 запитів.

    docker compose run --no-deps -v "$PWD/scripts:/app/scripts" web \\
        python scripts/compare_pnl.py output/early/web/<id>.json 20

Перший аргумент — файл аналізу (гаманці беруться з його рядків, спершу найбільші вкладення) або список адрес
через кому. Другий — скільки гаманців.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tracced.config import load_config          # noqa: E402
from tracced.early import profile, settings      # noqa: E402
from tracced.early.st_client import EarlyST      # noqa: E402
from tracced.util import get_key                 # noqa: E402


def wallets_from(arg, n):
    if os.path.exists(arg):
        job = json.load(open(arg, encoding="utf-8"))
        rows = (job.get("result") or job).get("rows") or []
        rows = sorted(rows, key=lambda r: -(r.get("invested_usd") or 0))
        return [r["wallet"] for r in rows][:n]
    return [w.strip() for w in arg.split(",") if w.strip()][:n]


def usd(v):
    return "—" if v is None else f"{v:>12,.0f}"


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    s = settings.load(load_config(os.getenv("EARLY_CONFIG", "config.yaml")))
    st = EarlyST(get_key(), pause=float(s.get("pause_s", 0.35)))
    days, pages = int(s.get("profile_days", 30)), int(s.get("profile_max_pages", 5))
    now = int(time.time() * 1000)
    rows = []
    print(f"{'wallet':<12} {'swaps':>5} {'tok':>4} {'unb':>4} {'ours $':>12} {'theirs $':>12} {'diff $':>12} "
          f"{'win':>5}  note")
    for w in wallets_from(sys.argv[1], n):
        try:
            raw, partial = st.wallet_swaps(w, now - days * profile.DAY, pages)
            evs = [e for r in raw for e in profile.normalize_wallet_swap(r, w)]
            ours = profile.summary(evs, w, now, days, partial)
        except Exception as e:  # noqa: BLE001
            print(f"{w[:10]}…  our side failed: {e}")
            continue
        try:
            perf = st._get(f"/v2/pnl/wallets/{w}/performance?period={days}d")
            theirs = ((perf or {}).get("totals") or {}).get("realizedPnl")
        except Exception as e:  # noqa: BLE001
            theirs, perf = None, {"error": str(e)[:60]}
        diff = (ours["pnl_usd"] - theirs) if theirs is not None else None
        note = []
        if partial:
            note.append(f"partial: {pages} pages end at {time.strftime('%d.%m', time.gmtime((ours['oldest_ms'] or now) / 1000))}")
        if ours["unbacked_tokens"]:
            note.append(f"{ours['unbacked_tokens']} tokens sold without a buy in {days}d")
        if isinstance(perf, dict) and perf.get("error"):
            note.append(perf["error"])
        win = f"{ours['win_rate'] * 100:.0f}%" if ours["win_rate"] is not None else "—"
        print(f"{w[:10]}… {ours['swaps']:>5} {ours['tokens']:>4} {ours['unbacked_tokens']:>4} {usd(ours['pnl_usd'])} "
              f"{usd(theirs)} {usd(diff)} {win:>5}  {'; '.join(note)}")
        rows.append({"wallet": w, "ours": ours, "theirs": theirs})
    both = [r for r in rows if r["theirs"] is not None]
    if both:
        close = sum(1 for r in both if abs(r["ours"]["pnl_usd"] - r["theirs"]) <= max(50, 0.1 * abs(r["theirs"])))
        print(f"\n{close} of {len(both)} within 10% (or $50) · requests spent: {st.requests}")
    json.dump(rows, open(os.getenv("OUT", "/tmp/compare_pnl.json"), "w"), default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
