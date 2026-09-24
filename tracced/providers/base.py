"""Интерфейс источника данных. Приложение зависит от него, а не от конкретного вендора."""


class PumpDataSource:
    def token_info(self, mint):
        """dict {mint,symbol,created_time(ms),supply,price_usd,mcap,liquidity_usd,creator,migration,...}."""
        raise NotImplementedError
