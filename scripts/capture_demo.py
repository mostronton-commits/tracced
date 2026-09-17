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

from tracced.early.st_client import EarlyST          # noqa: E402
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
    for tf in TFS:
        candles[tf] = st.chart(mint, tf, created, end)
        print(f"  {tf}: {len(candles[tf])} candles")

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
