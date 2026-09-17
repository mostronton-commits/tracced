"""CLI: python -m tracced.early <mint> --from --to [--scope all|24h|48h] [--tz] [--probe]."""
import argparse
import os
import sys
import time

from ..cache import JsonCache
from ..util import get_key
from ..config import load_config
from ..util import iso_ms, parse_time_to_ms
from . import pipeline, report, settings
from .st_client import EarlyST


def build_parser():
    ap = argparse.ArgumentParser(
        prog="python -m tracced.early",
        description="Ранні гаманці токена за фактами з його угод (Solana). Тільки читання.")
    ap.add_argument("mint")
    ap.add_argument("--from", dest="from_t", help="початок вікна входу (unix або 'YYYY-MM-DD HH:MM')")
    ap.add_argument("--to", dest="to_t", help="кінець вікна входу")
    ap.add_argument("--scope", default="all", help="масштаб цифр: all (уся історія) | 24h | 48h після діапазону")
    ap.add_argument("--tz", type=float, default=0.0, help="зсув введених часів (2 = UTC+2)")
    ap.add_argument("--max-pages", type=int, default=None)
    ap.add_argument("--probe", action="store_true", help="лише токен + графік + підказки меж (2 запити)")
    ap.add_argument("--dry-run", action="store_true", help="показати план, у мережу не ходити")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--out", default="output/early")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config)
    s = settings.load(cfg)
    off = int(args.tz * 3_600_000)
    t_from = parse_time_to_ms(args.from_t) - off if args.from_t else None
    t_to = parse_time_to_ms(args.to_t) - off if args.to_t else None
    t_exit = None

    if args.dry_run:
        print(f"DRY-RUN: {args.mint} діапазон {iso_ms(t_from)}…{iso_ms(t_to)} UTC, історія до зараз. "
              f"Стеля {args.max_pages or s['max_trade_pages']} сторінок. У мережу не ходжу.")
        return 0
    key = get_key()
    if not key:
        print("SOLANATRACKER_API_KEY is missing (environment or .env).", file=sys.stderr)
        return 1
    st = EarlyST(key, pause=float(s.get("pause_s", 0.35)), chart_cache=JsonCache("cache/early/chart.json", ttl_hours=72),
                 stats_cache=JsonCache("cache/early/wallet_token.json", ttl_hours=s["wallet_stats_ttl_hours"]))

    if args.probe:
        info = pipeline.token(st, args.mint)
        ov = pipeline.overview(st, args.mint, info, s)
        print(f"{info.get('symbol')}  створено {iso_ms(info.get('created_time'))} UTC  "
              f"supply {info['supply']:,.0f}  капа {report.money(info.get('mcap'))}")
        print(f"свічок {ov['interval']}: {len(ov['candles'])}; підказок меж: {len(ov['hints'])}")
        for i, h in enumerate(ov["hints"], 1):
            print(f"  [{i}] накопичення {iso_ms(h['acc_start'])} → старт {iso_ms(h['pump_start'])} "
                  f"→ пік {iso_ms(h['peak_time'])}  {report.money(h['base_mcap'])}→{report.money(h['peak_mcap'])} (x{h['magnitude']})")
        st.flush()
        print(f"запитів: {st.requests} | кредитів лишилось: {st.credits()}")
        return 0

    if not (t_from and t_to):
        print("Потрібні --from і --to (або --probe для підказок меж).", file=sys.stderr)
        return 1
    try:
        res = pipeline.run(st, args.mint, t_from, t_to, s, log=lambda m: print("  ·", m),
                           max_pages=args.max_pages)
    except pipeline.EarlyError as e:
        print(f"⛔ {e}", file=sys.stderr)
        return 2
    res["credits"] = st.credits()
    sym = res["info"].get("symbol") or args.mint[:8]
    stem = f"{sym}_{time.strftime('%Y%m%d', time.gmtime(t_from / 1000))}_{time.strftime('%H%M', time.gmtime(t_from / 1000))}-{time.strftime('%H%M', time.gmtime(t_to / 1000))}"
    os.makedirs(args.out, exist_ok=True)
    report.write_csv(res["rows"], f"{args.out}/{stem}.csv")
    report.write_json(res, f"{args.out}/{stem}.json")
    md = report.markdown(res)
    with open(f"{args.out}/{stem}.md", "w", encoding="utf-8") as f:
        f.write(md)
    print(md)
    print(f"файли: {args.out}/{stem}.{{csv,md,json}}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
