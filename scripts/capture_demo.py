"""Freeze one finished analysis as the demo token: page, chart and terminal replay with zero API requests.

The snapshot in output/early/demo/<mint>.json is self-contained — token facts, candles for every timeframe,
the range, the analysis log and its result. The app only reads it, so a demo can never turn into a live,
paid run. Point config.yaml at the analysis afterwards:

    early.demo_job:    <analysis id>     # replays on Analyze
    early.example_job: <analysis id>     # pinned as the example on the home page

Usage (inside the container, so it shares the app's key and paths):
    docker compose run --rm --no-deps -v "$PWD/scripts:/app/scripts" web \
        python scripts/capture_demo.py <analysis id> [--span-hours N]
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tracced.early.st_client import EarlyST
from tracced.web import chart as chart_mod          # noqa: E402
from tracced.util import get_key                      # noqa: E402

TFS = ("1m", "5m", "15m", "1h")
HOUR = 3600_000


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("jobs", nargs="+", metavar="analysis[=label]",
                   help="one or more finished analyses of the SAME token, in the order to show them; "
                        "add =label to name a range, e.g. 98kfF7_20260915-1930_1950='Pump 1'")
    p.add_argument("--jobs-dir", default="output/early/web")
    p.add_argument("--demo-dir", default="output/early/demo")
    p.add_argument("--span-hours", type=float, default=0,
                   help="hours of chart after the first range (default: up to now)")
    a = p.parse_args()

    ranges, info, created, mint = [], None, None, None
    for spec in a.jobs:
        jid, _, label = spec.partition("=")
        with open(os.path.join(a.jobs_dir, jid + ".json"), encoding="utf-8") as f:
            job = json.load(f)
        if job.get("status") != "done" or not job.get("result"):
            sys.exit(f"{jid} is {job.get('status')} — capture finished analyses only")
        res = job["result"]
        if mint and res["info"]["mint"] != mint:
            sys.exit("all analyses must be of the same token")
        info, mint = res["info"], res["info"]["mint"]
        created = info.get("created_time") or res["window"]["from"]
        ranges.append({"label": label or f"Range {len(ranges) + 1}", "from": res["window"]["from"],
                       "to": res["window"]["to"], "job": jid, "log": list(job.get("log") or []), "result": res})
        rows = (res.get("counts") or {}).get("n_early")
        cov = res.get("coverage") or {}
        print(f"  {jid}  {rows} wallets · exits known for {cov.get('exits_known')} of {cov.get('total')}")

    ranges.sort(key=lambda r: r["from"])
    end = ranges[0]["from"] + int(a.span_hours * HOUR) if a.span_hours else int(time.time() * 1000)

    st = EarlyST(get_key())
    candles = {}
    # Solana Tracker answers at most 2000 candles and silently drops the oldest ones, and for the coarser
    # timeframes it also stops a few days back. Measured 22.09.2026: one 1m call returns 2000 records (33 h),
    # one 5m call reached 3.3 days. So each timeframe is walked backwards in windows it can actually answer —
    # ask for the whole life at once and the snapshot starts hours after the token did.
    STEP_H = {"1m": 24, "5m": 48, "15m": 24 * 10, "1h": 24 * 45}
    for tf in TFS:
        step = int(STEP_H[tf] * HOUR)
        out, hi, calls = [], end, 0
        while hi > created and calls < 30:
            lo = max(created, hi - step)
            out.extend(st.chart(mint, tf, lo, hi))
            calls += 1
            hi = lo
        seen, merged = set(), []
        for c in sorted(out, key=lambda c: c["time"]):
            if c["time"] not in seen:
                seen.add(c["time"])
                merged.append(c)
        candles[tf] = merged
        first = time.strftime("%m-%d %H:%M", time.gmtime(merged[0]["time"] / 1000)) if merged else "—"
        print(f"  {tf}: {len(merged)} candles from {first} ({calls} calls)")

    snap = {"mint": mint, "info": info, "created": created, "captured_ms": int(time.time() * 1000),
            "candles": candles, "hints": [], "ranges": ranges}

    os.makedirs(a.demo_dir, exist_ok=True)
    out = os.path.join(a.demo_dir, f"{mint}.json")
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False)
    os.replace(tmp, out)
    print(f"\n{out}  {os.path.getsize(out) / 1e6:.1f} MB · {len(ranges)} range(s) · {len(TFS)} chart requests")
    print(f"Now set in config.yaml:\n  early:\n    demo_job: {ranges[0]['job']}\n    example_job: {ranges[0]['job']}")


if __name__ == "__main__":
    main()
