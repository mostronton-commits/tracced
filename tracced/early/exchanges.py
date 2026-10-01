"""Відомі гарячі гаманці бірж на Solana: назва біржі там, де спонсор гаманця — біржа.

Solana Tracker біржових гаманців не знає (вони не торгують, 30.09 відповідь «notFound»). Список — файл JSON
{"addresses": {адреса: [біржа, мітка]}} поза репозиторієм, шлях у EXCHANGE_LABELS_FILE; без нього назв бірж немає.

Знімок зі spellbook Dune тут був до 30.09 і прибраний: його ліцензія (Business Source License 1.1) до 03.03.2027
забороняє використання в аналітичній платформі для третіх осіб і вимагає показувати ліцензію з кожною копією (рев'ю
30.09). Потрібен власний список з джерел, які це дозволяють.
"""
import json
import os
import pathlib


def load(path):
    try:
        raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8")).get("addresses") or {}
    except (OSError, ValueError, AttributeError, TypeError):
        return {}
    if not isinstance(raw, dict):                     # чужий формат файла не валить сервер на старті (рев'ю 01.10)
        return {}
    return {a: [str(v[0]), str(v[1] if len(v) > 1 else v[0])] for a, v in raw.items() if isinstance(v, list) and v}


KNOWN = load(os.getenv("EXCHANGE_LABELS_FILE") or "")


def name_of(addr):
    """«Binance» для гарячого гаманця Binance, інакше None."""
    v = KNOWN.get(addr)
    return v[0] if v else None
