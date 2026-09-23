"""Дописати в знімок демо-токена те, чого в ньому не було: творця токена і момент переїзду з лаунчпада.

Знімок важить два десятки мегабайт, і гнати його на сервери заново заради двох полів безглуздо. Скрипт
бере ті самі поля з відповіді про токен (1 запит) і вписує їх на місці, атомарно.

    docker compose -f compose.vps.yml run --rm --no-deps -v "$PWD/scripts:/app/scripts" web \
        python scripts/patch_demo_marks.py
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tracced.providers.solana_tracker import SolanaTracker    # noqa: E402
from tracced.util import get_key                              # noqa: E402


def main(demo_dir="output/early/demo"):
    st = SolanaTracker(get_key())
    files = sorted(glob.glob(os.path.join(demo_dir, "*.json")))
    if not files:
        print("знімків нема в", demo_dir)
        return 1
    for path in files:
        with open(path, encoding="utf-8") as f:
            snap = json.load(f)
        mint = snap.get("mint")
        fresh = st.token_info(mint)
        info = snap.setdefault("info", {})
        info["creator"] = fresh.get("creator")
        info["migration"] = fresh.get("migration")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snap, f)
        os.replace(tmp, path)
        print(f"{os.path.basename(path)}: creator={info['creator']} migration={info['migration']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
