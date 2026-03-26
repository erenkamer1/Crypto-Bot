"""
Runtime configuration module.
Thread-safe settings shared between GUI and bot process.
"""

import threading
import json
import os
from typing import Optional, Callable, List
from datetime import datetime

import path_utils

CONFIG_FILE = os.path.join(path_utils.get_base_dir(), "runtime_settings.json")


class RuntimeConfig:
    """
    Thread-safe runtime settings (singleton).
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self._settings_lock = threading.RLock()
        self._callbacks: List[Callable] = []

        # Defaults
        self._api_key: str = ""
        self._api_secret: str = ""
        self._initial_balance: float = 0.0
        self._trade_percent: float = 0.05
        self._use_fixed_trade_amount: bool = False
        self._fixed_trade_amount_usdt: float = 10.0
        self._allow_new_trades: bool = True
        self._auto_trade: bool = False  # Live Binance trading

        self._use_custom_ml_threshold: bool = False
        self._ml_threshold: float = 0.52

        # TP/SL (%)
        self._sl_pct: float = 4.0
        self._tp1_pct: float = 1.5
        self._tp2_pct: float = 3.0

        # Slippage buffers (%)
        self._sl_buffer_pct: float = 0.03
        self._be_buffer_pct: float = 0.08

        self._show_balance_info: bool = True

        self._max_trades_per_coin: int = 3

        # Simulation
        self._simulation_mode: bool = False
        self._simulation_balance: float = 10000.0
        self._simulation_use_fixed_amount: bool = True
        self._simulation_fixed_amount: float = 100.0
        self._simulation_trade_percent: float = 0.05
        self._simulation_current_balance: float = 10000.0

        self._current_balance: float = 0.0
        self._last_balance_update: Optional[datetime] = None

        self._load_from_file()

    def _load_from_file(self):
        """Load settings from JSON file if present."""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._api_key = data.get('api_key', '')
                    self._api_secret = data.get('api_secret', '')
                    self._initial_balance = data.get('initial_balance', 0.0)
                    self._trade_percent = data.get('trade_percent', 0.05)
                    self._use_fixed_trade_amount = data.get('use_fixed_trade_amount', False)
                    self._fixed_trade_amount_usdt = data.get('fixed_trade_amount_usdt', 10.0)
                    self._allow_new_trades = data.get('allow_new_trades', True)
                    self._auto_trade = data.get('auto_trade', False)
                    self._use_custom_ml_threshold = data.get('use_custom_ml_threshold', False)
                    self._ml_threshold = data.get('ml_threshold', 0.52)
                    self._sl_pct = data.get('sl_pct', 4.0)
                    self._tp1_pct = data.get('tp1_pct', 1.5)
                    self._tp2_pct = data.get('tp2_pct', 3.0)
                    self._sl_buffer_pct = data.get('sl_buffer_pct', 0.03)
                    self._be_buffer_pct = data.get('be_buffer_pct', 0.08)
                    self._show_balance_info = data.get('show_balance_info', True)
                    self._max_trades_per_coin = data.get('max_trades_per_coin', 3)
                    self._simulation_mode = data.get('simulation_mode', False)
                    self._simulation_balance = data.get('simulation_balance', 10000.0)
                    self._simulation_use_fixed_amount = data.get('simulation_use_fixed_amount', True)
                    self._simulation_fixed_amount = data.get('simulation_fixed_amount', 100.0)
                    self._simulation_trade_percent = data.get('simulation_trade_percent', 0.05)
            except Exception as e:
                print(f"Failed to load settings file: {e}")

    def save_to_file(self):
        """Persist settings to JSON."""
        try:
            with self._settings_lock:
                data = {
                    'api_key': self._api_key,
                    'api_secret': self._api_secret,
                    'initial_balance': self._initial_balance,
                    'trade_percent': self._trade_percent,
                    'use_fixed_trade_amount': self._use_fixed_trade_amount,
                    'fixed_trade_amount_usdt': self._fixed_trade_amount_usdt,
                    'allow_new_trades': self._allow_new_trades,
                    'auto_trade': self._auto_trade,
                    'use_custom_ml_threshold': self._use_custom_ml_threshold,
                    'ml_threshold': self._ml_threshold,
                    'sl_pct': self._sl_pct,
                    'tp1_pct': self._tp1_pct,
                    'tp2_pct': self._tp2_pct,
                    'sl_buffer_pct': self._sl_buffer_pct,
                    'be_buffer_pct': self._be_buffer_pct,
                    'show_balance_info': self._show_balance_info,
                    'max_trades_per_coin': self._max_trades_per_coin,
                    'simulation_mode': self._simulation_mode,
                    'simulation_balance': self._simulation_balance,
                    'simulation_use_fixed_amount': self._simulation_use_fixed_amount,
                    'simulation_fixed_amount': self._simulation_fixed_amount,
                    'simulation_trade_percent': self._simulation_trade_percent,
                }
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Failed to save settings file: {e}")

    @property
    def api_key(self) -> str:
        with self._settings_lock:
            return self._api_key

    @api_key.setter
    def api_key(self, value: str):
        with self._settings_lock:
            self._api_key = value
            self._notify_change('api_key')

    @property
    def api_secret(self) -> str:
        with self._settings_lock:
            return self._api_secret

    @api_secret.setter
    def api_secret(self, value: str):
        with self._settings_lock:
            self._api_secret = value
            self._notify_change('api_secret')

    @property
    def initial_balance(self) -> float:
        with self._settings_lock:
            return self._initial_balance

    @initial_balance.setter
    def initial_balance(self, value: float):
        with self._settings_lock:
            self._initial_balance = max(0.0, value)
            self._notify_change('initial_balance')

    @property
    def trade_percent(self) -> float:
        with self._settings_lock:
            return self._trade_percent

    @trade_percent.setter
    def trade_percent(self, value: float):
        with self._settings_lock:
            self._trade_percent = max(0.001, min(1.0, value))
            self._notify_change('trade_percent')

    @property
    def use_fixed_trade_amount(self) -> bool:
        with self._settings_lock:
            return self._use_fixed_trade_amount

    @use_fixed_trade_amount.setter
    def use_fixed_trade_amount(self, value: bool):
        with self._settings_lock:
            self._use_fixed_trade_amount = value
            self._notify_change('use_fixed_trade_amount')

    @property
    def fixed_trade_amount_usdt(self) -> float:
        with self._settings_lock:
            return self._fixed_trade_amount_usdt

    @fixed_trade_amount_usdt.setter
    def fixed_trade_amount_usdt(self, value: float):
        with self._settings_lock:
            self._fixed_trade_amount_usdt = max(1.0, min(100000.0, value))
            self._notify_change('fixed_trade_amount_usdt')

    @property
    def allow_new_trades(self) -> bool:
        with self._settings_lock:
            return self._allow_new_trades

    @allow_new_trades.setter
    def allow_new_trades(self, value: bool):
        with self._settings_lock:
            self._allow_new_trades = value
            self._notify_change('allow_new_trades')

    @property
    def auto_trade(self) -> bool:
        with self._settings_lock:
            return self._auto_trade

    @auto_trade.setter
    def auto_trade(self, value: bool):
        with self._settings_lock:
            self._auto_trade = value
            if value:
                self._simulation_mode = False
            self._notify_change('auto_trade')

    @property
    def current_balance(self) -> float:
        with self._settings_lock:
            return self._current_balance

    @current_balance.setter
    def current_balance(self, value: float):
        with self._settings_lock:
            self._current_balance = value
            self._last_balance_update = datetime.now()
            self._notify_change('current_balance')

    @property
    def use_custom_ml_threshold(self) -> bool:
        with self._settings_lock:
            return getattr(self, '_use_custom_ml_threshold', False)

    @use_custom_ml_threshold.setter
    def use_custom_ml_threshold(self, value: bool):
        with self._settings_lock:
            self._use_custom_ml_threshold = value
            self._notify_change('use_custom_ml_threshold')

    @property
    def ml_threshold(self) -> float:
        with self._settings_lock:
            return getattr(self, '_ml_threshold', 0.52)

    @ml_threshold.setter
    def ml_threshold(self, value: float):
        with self._settings_lock:
            self._ml_threshold = max(0.0, min(1.0, value))
            self._notify_change('ml_threshold')

    @property
    def sl_pct(self) -> float:
        with self._settings_lock:
            return self._sl_pct

    @sl_pct.setter
    def sl_pct(self, value: float):
        with self._settings_lock:
            self._sl_pct = max(0.1, min(50.0, value))
            self._notify_change('sl_pct')

    @property
    def tp1_pct(self) -> float:
        with self._settings_lock:
            return self._tp1_pct

    @tp1_pct.setter
    def tp1_pct(self, value: float):
        with self._settings_lock:
            self._tp1_pct = max(0.1, min(50.0, value))
            self._notify_change('tp1_pct')

    @property
    def tp2_pct(self) -> float:
        with self._settings_lock:
            return self._tp2_pct

    @tp2_pct.setter
    def tp2_pct(self, value: float):
        with self._settings_lock:
            self._tp2_pct = max(0.1, min(50.0, value))
            self._notify_change('tp2_pct')

    @property
    def sl_buffer_pct(self) -> float:
        with self._settings_lock:
            return self._sl_buffer_pct

    @sl_buffer_pct.setter
    def sl_buffer_pct(self, value: float):
        with self._settings_lock:
            self._sl_buffer_pct = max(0.0, min(1.0, value))
            self._notify_change('sl_buffer_pct')

    @property
    def be_buffer_pct(self) -> float:
        with self._settings_lock:
            return self._be_buffer_pct

    @be_buffer_pct.setter
    def be_buffer_pct(self, value: float):
        with self._settings_lock:
            self._be_buffer_pct = max(0.0, min(1.0, value))
            self._notify_change('be_buffer_pct')

    @property
    def show_balance_info(self) -> bool:
        with self._settings_lock:
            return self._show_balance_info

    @show_balance_info.setter
    def show_balance_info(self, value: bool):
        with self._settings_lock:
            self._show_balance_info = value
            self._notify_change('show_balance_info')

    @property
    def max_trades_per_coin(self) -> int:
        with self._settings_lock:
            return self._max_trades_per_coin

    @max_trades_per_coin.setter
    def max_trades_per_coin(self, value: int):
        with self._settings_lock:
            self._max_trades_per_coin = max(1, min(10, int(value)))
            self._notify_change('max_trades_per_coin')

    @property
    def simulation_mode(self) -> bool:
        with self._settings_lock:
            return self._simulation_mode

    @simulation_mode.setter
    def simulation_mode(self, value: bool):
        with self._settings_lock:
            self._simulation_mode = value
            if value:
                self._auto_trade = False
            self._notify_change('simulation_mode')

    @property
    def simulation_balance(self) -> float:
        with self._settings_lock:
            return self._simulation_balance

    @simulation_balance.setter
    def simulation_balance(self, value: float):
        with self._settings_lock:
            self._simulation_balance = max(1.0, value)
            self._notify_change('simulation_balance')

    @property
    def simulation_use_fixed_amount(self) -> bool:
        with self._settings_lock:
            return self._simulation_use_fixed_amount

    @simulation_use_fixed_amount.setter
    def simulation_use_fixed_amount(self, value: bool):
        with self._settings_lock:
            self._simulation_use_fixed_amount = value
            self._notify_change('simulation_use_fixed_amount')

    @property
    def simulation_fixed_amount(self) -> float:
        with self._settings_lock:
            return self._simulation_fixed_amount

    @simulation_fixed_amount.setter
    def simulation_fixed_amount(self, value: float):
        with self._settings_lock:
            self._simulation_fixed_amount = max(1.0, min(100000.0, value))
            self._notify_change('simulation_fixed_amount')

    @property
    def simulation_trade_percent(self) -> float:
        with self._settings_lock:
            return self._simulation_trade_percent

    @simulation_trade_percent.setter
    def simulation_trade_percent(self, value: float):
        with self._settings_lock:
            self._simulation_trade_percent = max(0.001, min(1.0, value))
            self._notify_change('simulation_trade_percent')

    @property
    def simulation_current_balance(self) -> float:
        with self._settings_lock:
            return self._simulation_current_balance

    @simulation_current_balance.setter
    def simulation_current_balance(self, value: float):
        with self._settings_lock:
            self._simulation_current_balance = value
            self._notify_change('simulation_current_balance')

    def get_simulation_trade_amount(self) -> float:
        """USDT size for the next simulated trade."""
        with self._settings_lock:
            if self._simulation_use_fixed_amount:
                return self._simulation_fixed_amount
            return self._simulation_current_balance * self._simulation_trade_percent

    def reset_simulation(self):
        """Reset simulation balance to starting value."""
        with self._settings_lock:
            self._simulation_current_balance = self._simulation_balance
            self._notify_change('simulation_reset')

    def get_trade_amount(self) -> float:
        """USDT size for the next live trade."""
        with self._settings_lock:
            if self._use_fixed_trade_amount:
                return self._fixed_trade_amount_usdt
            balance = self._current_balance if self._current_balance > 0 else self._initial_balance
            return balance * self._trade_percent

    def get_pnl(self) -> tuple:
        """Returns (pnl_usdt, pnl_percent)."""
        with self._settings_lock:
            if self._initial_balance <= 0 or self._current_balance <= 0:
                return 0.0, 0.0
            pnl = self._current_balance - self._initial_balance
            pnl_pct = (pnl / self._initial_balance) * 100
            return pnl, pnl_pct

    def can_open_new_trade(self) -> bool:
        """Whether new trades are allowed."""
        with self._settings_lock:
            return self._auto_trade and self._allow_new_trades

    def get_settings_summary(self) -> dict:
        """User-visible settings (no API secrets)."""
        with self._settings_lock:
            return {
                'ml_threshold': self._ml_threshold,
                'use_custom_ml_threshold': self._use_custom_ml_threshold,
                'tp1_pct': self._tp1_pct,
                'tp2_pct': self._tp2_pct,
                'sl_pct': self._sl_pct,
                'sl_buffer_pct': self._sl_buffer_pct,
                'be_buffer_pct': self._be_buffer_pct,
                'fixed_trade_amount_usdt': self._fixed_trade_amount_usdt,
                'use_fixed_trade_amount': self._use_fixed_trade_amount,
                'trade_percent': self._trade_percent,
                'allow_new_trades': self._allow_new_trades,
                'show_balance_info': self._show_balance_info,
                'max_trades_per_coin': self._max_trades_per_coin,
                'simulation_mode': self._simulation_mode,
                'simulation_balance': self._simulation_balance,
                'simulation_use_fixed_amount': self._simulation_use_fixed_amount,
                'simulation_fixed_amount': self._simulation_fixed_amount,
                'simulation_trade_percent': self._simulation_trade_percent,
            }

    def add_change_callback(self, callback: Callable):
        """Register a callback when a setting changes."""
        self._callbacks.append(callback)

    def _notify_change(self, setting_name: str):
        for callback in self._callbacks:
            try:
                callback(setting_name)
            except Exception as e:
                print(f"Callback error: {e}")


_runtime_config: Optional[RuntimeConfig] = None


def get_config() -> RuntimeConfig:
    """Singleton accessor."""
    global _runtime_config
    if _runtime_config is None:
        _runtime_config = RuntimeConfig()
    return _runtime_config


def can_open_new_trade() -> bool:
    return get_config().can_open_new_trade()


def get_trade_amount() -> float:
    return get_config().get_trade_amount()
