"""Дашборд власника: хто з підключених гаманців що робить на сайті і скільки кредитів це коштує.

Сировина — журнал подій (accounts.EventLog, output/early/usage/YYYY-MM.jsonl), акаунти і результати аналізів. Тут лише
чиста логіка, без aiohttp і без мережі: її можна тестувати на вигаданих подіях.
"""
import datetime
import zoneinfo


def zone(name):
    """Часовий пояс доби дашборда; невідомий (чи образ без бази поясів) — UTC."""
    try:
        return zoneinfo.ZoneInfo(str(name or "UTC"))
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return datetime.timezone.utc
