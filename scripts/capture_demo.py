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
    p.add_argument("job_id", help="id of a finished analysis, e.g. 98kfF7_20260915-1930_1933")
    p.add_argument("--jobs-dir", default="output/early/web")
    p.add_argument("--demo-dir", default="output/early/demo")
    p.add_argument("--span-hours", type=float, default=0,
                   help="hours of chart after the range (default: up to the analysis time)")
    a = p.parse_args()

    path = os.path.join(a.jobs_dir, a.job_id + ".json")
    with open(path, encoding="utf-8") as f:
        job = json.load(f)
    if job.get("status") != "done" or not job.get("result"):
        sys.exit(f"{a.job_id} is {job.get('status')} — capture a finished analysis")

    res = job["result"]
    info, win = res["info"], res["window"]
    mint = info["mint"]
    created = info.get("created_time") or win["from"]
    end = win["from"] + int(a.span_hours * HOUR) if a.span_hours else int(time.time() * 1000)

    st = EarlyST(get_key())
    candles, reqs = {}, 0
    for tf in TFS:
        cs = st.chart(mint, tf, created, end)
        candles[tf] = cs
        reqs += 1
        print(f"  {tf}: {len(cs)} candles")

    snap = {"mint": mint, "info": info, "created": created, "captured_ms": int(time.time() * 1000),
            "candles": candles, "hints": [], "job": a.job_id,
            "range": {"from": win["from"], "to": win["to"]},
            "log": list(job.get("log") or []), "result": res}

    os.makedirs(a.demo_dir, exist_ok=True)
    out = os.path.join(a.demo_dir, f"{mint}.json")
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False)
    os.replace(tmp, out)
    mb = os.path.getsize(out) / 1e6
    rows = len(res.get("rows") or []) or (res.get("counts") or {}).get("n_early")
    print(f"\n{out}  {mb:.1f} MB · {rows} wallets · {len(snap['log'])} log lines · {reqs} chart requests")
    print(f"Now set in config.yaml:\n  early:\n    demo_job: {a.job_id}\n    example_job: {a.job_id}")


if __name__ == "__main__":
    main()
