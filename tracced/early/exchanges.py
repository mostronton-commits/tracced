"""Відомі гарячі гаманці бірж на Solana: назва біржі там, де спонсор гаманця — біржа.

Solana Tracker біржових гаманців не знає (вони не торгують, 30.09 відповідь «notFound»). Тому знімок відкритого списку
Dune spellbook лежить у data/cex_solana.json: адреса → [біржа, мітка], напр. «Binance», «Binance 1». Це мітки з
названим джерелом, а не оцінка; невідома адреса лишається адресою. Список оновлюється вручну разом з кодом.
"""
import json
import pathlib

_PATH = pathlib.Path(__file__).parent / "data" / "cex_solana.json"


def _load():
    try:
        raw = json.loads(_PATH.read_text(encoding="utf-8")).get("addresses") or {}
    except (OSError, ValueError, AttributeError):
        return {}
    return {a: [str(v[0]), str(v[1] if len(v) > 1 else v[0])] for a, v in raw.items() if isinstance(v, list) and v}


KNOWN = _load()


def name_of(addr):
    """«Binance» для гарячого гаманця Binance, інакше None."""
    v = KNOWN.get(addr)
    return v[0] if v else None
