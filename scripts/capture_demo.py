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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tracced.early import pipeline                      # noqa: E402
from tracced.early.st_client import EarlyST             # noqa: E402
from tracced.util import get_key                        # noqa: E402
from tracced.web import demo                            # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("jobs", nargs="+", metavar="analysis[=label]",
                   help="one or more finished analyses of the SAME token, in the order to show them; "
                        "add =label to name a range, e.g. 98kfF7_20260915-1930_1950='Pump 1'")
    p.add_argument("--jobs-dir", default="output/early/web")
    p.add_argument("--demo-dir", default="output/early/demo")
    p.add_argument("--span-hours", type=float, default=0, help="hours of chart after the first range (default: up to now)")
    p.add_argument("--set", action="store_true", help="also make it the demo now (writes current.json; no config change)")
    a = p.parse_args()
    jobs, labels = [], {}
    for spec in a.jobs:
        jid, _, label = spec.partition("=")
        with open(os.path.join(a.jobs_dir, jid + ".json"), encoding="utf-8") as f:
            jobs.append(json.load(f))
        if label:
            labels[jid] = label
    try:
        path, first = demo.capture(EarlyST(get_key()), jobs, a.demo_dir, chart_fn=pipeline._chart, labels=labels, span_hours=a.span_hours)
    except ValueError as e:
        sys.exit(str(e))
    if a.set:
        demo.write_override(a.demo_dir, first)
        print(f"The demo is now {first}.")
    else:
        print(f"Make it the demo from the result page (admin), or run again with --set.")


if __name__ == "__main__":
    main()
