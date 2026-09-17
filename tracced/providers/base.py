"""Интерфейс источника данных. Движок зависит от него, а не от конкретного вендора."""


class PumpDataSource:
    def discover_tokens(self, scan_cfg):
        """Свежие токены под фильтры scan → список dict {mint,symbol,mcap,age_hours,link}."""
        raise NotImplementedError

    def token_info(self, mint):
        """dict {mint,symbol,created_time(ms),supply,price_usd,mcap,liquidity_usd}."""
        raise NotImplementedError

    def trades_iter(self, mint, max_pages=40):
        """Генератор сделок по возрастанию времени:
        dict {wallet,type('buy'/'sell'),time(ms),volume_usd,price_usd,program}."""
        raise NotImplementedError

    def trades_window(self, mint, t_from, t_to, max_pages=40):
        """Сделки в окне [t_from..t_to] (мс), старт с t_from (для дальних окон)."""
        raise NotImplementedError

    def price_series(self, mint, interval="5m", t_from=None, t_to=None):
        """Свечи графика → [(time_ms, close, volume)] по возрастанию времени."""
        raise NotImplementedError

    def wallet_stats(self, wallet):
        """dict {winrate(0..1),total_pnl_usd,positions,distinct_tokens}."""
        raise NotImplementedError
