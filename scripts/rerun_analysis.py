"""Run finished analyses again under the same ids: fresh trades, the current pipeline, a new background check.

A range that already has a result opens that result instead of running again, for everyone including the admin, so
this is how an older analysis is brought up to date — the demo's, for one. The web app reads result files when it
starts: restart it afterwards, and it checks the new results' wallets in the background.

    docker compose run --rm --no-deps -v "$PWD/scripts:/app/scripts" web \
        python scripts/rerun_analysis.py <analysis id>... [--every-wallet] [--check-only]
    docker compose restart web

--every-wallet gives every wallet of the result the full age and funder check, not only the first `age_full_top` by
PnL. That is for the demo: its visitors cannot open a check from a card, so what the demo shows is what it holds. It
costs about 8 RPC credits a wallet instead of 2.

--check-only keeps the analysis and forgets only its age and funder check (ages, funders, `fresh` and `bundle`), so the
app checks the wallets again after the restart: for results checked from a cache that could not be trusted.

The script keeps no caches of its own and writes none of the app's, so the running app is not raced for them.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tracced.config import load_config                  # noqa: E402
from tracced.early import pipeline, settings            # noqa: E402
from tracced.early.st_client import EarlyST             # noqa: E402
from tracced.util import get_key                        # noqa: E402
from tracced.web.app import ROWS_REV                    # noqa: E402
from tracced.web.jobs import Job                        # noqa: E402


def forget_check(r, every=False):
    """Результат без перевірки віку і спонсора: наступний запуск застосунку перевірить його гаманці заново."""
    for k in ("enrich", "ages", "funders", "funder_checked", "bundle"):
        r.pop(k, None)
    r["fresh_wallets"] = []
    for row in r.get("rows") or []:
        tl = [t for t in (row.get("tag_list") or []) if t not in ("fresh", "bundle")]
        row["tag_list"], row["tags"] = tl, "|".join(tl)
    if every:
        r["age_full_top"] = len(r.get("rows") or [])


def write(job, path):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(job.to_dict(), ensure_ascii=False, default=str))
    os.replace(tmp, path)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("jobs", nargs="+", metavar="analysis", help="ids of finished analyses, e.g. 98kfF7_20260915-1930_1950")
    p.add_argument("--every-wallet", action="store_true", help="the full age and funder check for every wallet (the demo)")
    p.add_argument("--check-only", action="store_true", help="do not run the analysis again, only forget its age check")
    p.add_argument("--jobs-dir", default="output/early/web")
    a = p.parse_args()
    s = settings.load(load_config(os.getenv("EARLY_CONFIG", "config.yaml")))
    st = EarlyST(get_key(), pause=float(s.get("pause_s", 0.35)))
    for jid in a.jobs:
        path = os.path.join(a.jobs_dir, jid + ".json")
        with open(path, encoding="utf-8") as f:
            old = Job.from_dict(json.load(f))
        if old.status != "done":
            sys.exit(f"{jid} is {old.status}: only a finished analysis is run again")
        if a.check_only:
            forget_check(old.result, every=a.every_wallet)
            write(old, path)
            print(f"── {jid}: its age and funder check starts over after the restart")
            continue
        job = Job(old.id, old.mint, old.t_from, old.t_to)
        job.owner, job.created_ms, job.symbol_hint = old.owner, old.created_ms, old.symbol_hint
        job.started_ms, job.status = int(time.time() * 1000), "running"
        print(f"── {jid}")
        before = st.requests

        def log(m):
            job.log.append(m)
            print("  " + m, flush=True)
        res = pipeline.run(st, job.mint, job.t_from, job.t_to, dict(s, budget_guard_pct=0, run_cap_requests=0),
                           log=log, progress=job.set_progress, store_dir="cache/early")
        res["rows_rev"] = ROWS_REV
        if a.every_wallet:
            res["age_full_top"] = len(res["rows"])
        job.result, job.status, job.finished_ms = res, "done", int(time.time() * 1000)
        job.set_progress("done", 1, 1)
        write(job, path)
        print(f"  {len(res['rows']):,} wallets (was {len((old.result or {}).get('rows') or []):,}), "
              f"{st.requests - before:,} requests")
    print("Restart the web app so it loads the new results and checks their wallets.")


if __name__ == "__main__":
    main()
