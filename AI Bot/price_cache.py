"""
Thread-safe price cache for latest tickers.
Used by order_tracker so the GUI can read live prices.
"""

import threading
from typing import Dict, Optional


class PriceCache:
    """Symbol -> last price. Thread-safe."""

    def __init__(self):
        self._lock = threading.RLock()
        self._prices: Dict[str, float] = {}

    def set_price(self, symbol: str, price: float) -> None:
        with self._lock:
            self._prices[symbol] = float(price)

    def get_price(self, symbol: str) -> Optional[float]:
        with self._lock:
            return self._prices.get(symbol)

    def get_all_prices(self) -> Dict[str, float]:
        with self._lock:
            return dict(self._prices)

    def clear(self) -> None:
        with self._lock:
            self._prices.clear()


_cache: Optional[PriceCache] = None
_cache_lock = threading.Lock()


def get_cache() -> PriceCache:
    global _cache
    with _cache_lock:
        if _cache is None:
            _cache = PriceCache()
        return _cache


def set_price(symbol: str, price: float) -> None:
    get_cache().set_price(symbol, price)


def get_price(symbol: str) -> Optional[float]:
    return get_cache().get_price(symbol)


def get_all_prices() -> Dict[str, float]:
    return get_cache().get_all_prices()
