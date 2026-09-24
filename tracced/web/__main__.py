"""python -m tracced.web — запуск сторінки (у Docker: порт лише на 127.0.0.1 хоста)."""
import logging
import os
import sys

from aiohttp import web

from ..cache import JsonCache
from ..util import get_key
from ..config import load_config
from ..early import settings
from ..early.st_client import EarlyST
from ..early.assistant import Assistant
from ..early.wallet_age import WalletAge
from .app import create_app


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    key = get_key()
    if not key:
        print("SOLANATRACKER_API_KEY is missing (environment or .env).", file=sys.stderr)
        return 1
    cfg = load_config(os.getenv("EARLY_CONFIG", "config.yaml"))
    s = settings.load(cfg)
    identity = JsonCache("cache/early/identity.json", ttl_hours=s["identity_ttl_hours"]) if s.get("st_identity") else None
    st = EarlyST(key, pause=float(s.get("pause_s", 0.35)), chart_cache=JsonCache("cache/early/chart.json", ttl_hours=72),
                 identity_cache=identity,
                 stats_cache=JsonCache("cache/early/wallet_token.json", ttl_hours=s["wallet_stats_ttl_hours"],
                                       flush_every=200))   # великий файл: при паралельних гаманцях дамп кожні 25 записів гальмує всіх
    ages = None
    if s.get("age_lookups_max", 0) > 0:
        ages = WalletAge(cache=JsonCache("cache/early/wallet_age.json", ttl_hours=s["wallet_age_ttl_hours"]),
                         pace_s=float(s.get("rpc_pace_s", 0.5)))
    assistant = None
    if os.getenv("ASSISTANT_KEY"):
        assistant = Assistant(os.getenv("ASSISTANT_KEY"), url=os.getenv("ASSISTANT_URL"), model=os.getenv("ASSISTANT_MODEL"),
                              fallbacks=os.getenv("ASSISTANT_FALLBACKS"))
        logging.getLogger("early.web").info("assistant: %s @ %s", assistant.model, assistant.url)
    app = create_app(st, s, cfg, ages=ages, assistant=assistant)
    port = int(os.getenv("WEB_PORT", "8095"))
    web.run_app(app, host=os.getenv("WEB_HOST", "0.0.0.0"), port=port, print=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
