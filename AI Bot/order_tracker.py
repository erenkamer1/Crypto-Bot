import threading
import time
import traceback
from colorama import Fore, Style
import config
import runtime_config
import trade_manager
import price_cache
import shadow_trader
import order_executor
import simulation_engine
import telegram_bot
import app_logger

logger = app_logger.get_logger(__name__)


class OrderTracker(threading.Thread):
    def __init__(self, interval=5):
        super().__init__()
        self.interval = interval
        self.running = False
        self.exchange = None
        self.daemon = True

    def run(self):
        logger.info("Order Tracker Thread Baslatildi (Aralik: %ss)", self.interval)
        print(f"{Fore.CYAN}Order Tracker Thread Baslatildi (Aralik: {self.interval}s){Style.RESET_ALL}")
        self.running = True

        try:
            self.exchange = order_executor.get_exchange(use_runtime_config=True)
        except Exception as e:
            logger.exception("Order Tracker Exchange Hatasi")
            print(f"{Fore.RED}Order Tracker Exchange Hatasi: {e}{Style.RESET_ALL}")
            return

        while self.running:
            try:
                self._check_all_trades()
            except Exception as e:
                logger.exception("Order Tracker Dongu Hatasi")
                print(f"{Fore.RED}Order Tracker Dongu Hatasi: {e}{Style.RESET_ALL}")

            time.sleep(self.interval)

    def stop(self):
        self.running = False

    def _check_all_trades(self):
        rc = runtime_config.get_config()

        if rc.simulation_mode:
            self._check_simulation_trades()
        else:
            # 1. Binance order status kontrolu (once filled/cancelled kontrol)
            try:
                self._check_binance_order_status()
            except Exception as e:
                logger.error("Tracker Binance Order Status Error: %s", e)

            # 2. Fiyat bazli kontrol (tum acik trade'ler)
            try:
                all_open = trade_manager.get_all_open_trades()
                for symbol, trade_list in all_open.items():
                    for trade in trade_list:
                        self._check_single_trade(symbol, trade)
            except Exception as e:
                logger.error("Tracker Trade Check Error: %s", e)

        # 3. Shadow islemler (her iki modda da calisir)
        try:
            shadow_trader.check_active_trades(self.exchange)
        except Exception as e:
            logger.error("Tracker Shadow Error: %s", e)

    def _check_binance_order_status(self):
        """
        Binance'tan filled/cancelled order tespiti.
        Fiyat kontrolunden ONCE calisir - zamanlama riskini azaltir.
        """
        all_open = trade_manager.get_all_open_trades()
        if not all_open:
            return

        for symbol, trade_list in all_open.items():
            futures_symbol = order_executor._to_futures_symbol(symbol)

            try:
                open_orders = self.exchange.fetch_open_orders(futures_symbol)
            except Exception:
                continue

            open_order_ids = {str(o.get('id')) for o in open_orders}

            for trade in trade_list:
                sl_oid = trade.get("sl_order_id")
                tp_oid = trade.get("tp_order_id")

                if not sl_oid and not tp_oid:
                    continue

                sl_still_open = sl_oid and str(sl_oid) in open_order_ids
                tp_still_open = tp_oid and str(tp_oid) in open_order_ids

                if sl_oid and not sl_still_open and tp_still_open:
                    # SL tetiklendi (artik open degil), TP hala acik -> TP'yi iptal et
                    logger.info("Binance SL tetiklendi (trade %s), TP iptal ediliyor", trade.get("trade_id"))
                    order_executor.cancel_trade_orders(
                        symbol, None, tp_oid, exchange=self.exchange
                    )
                elif tp_oid and not tp_still_open and sl_still_open:
                    # TP tetiklendi, SL hala acik -> SL'yi iptal et
                    logger.info("Binance TP tetiklendi (trade %s), SL iptal ediliyor", trade.get("trade_id"))
                    order_executor.cancel_trade_orders(
                        symbol, sl_oid, None, exchange=self.exchange
                    )

    def _check_single_trade(self, symbol, trade):
        """Tek bir trade objesi icin fiyat bazli kontrol."""
        try:
            ticker = order_executor.fetch_ticker_with_retry(self.exchange, symbol)
            current_price = float(ticker['last'])

            event, profit, is_closed = trade_manager.check_trade_status(
                symbol, trade, current_price
            )

            if event:
                trade_id = trade.get("trade_id", "?")
                trade_signal = trade.get("signal", "")
                print(f"{Fore.RED}GERCEK BINANCE TRACKER UPDATE: {symbol} (trade:{trade_id}) -> {event} (Fiyat: {current_price}){Style.RESET_ALL}")
                telegram_bot.send_trade_update(symbol, event, current_price, profit, is_closed)

                if event == 'TP1' and not is_closed:
                    entry_price = trade.get('entry', 0)
                    tp2_price = trade.get('tp2', 0)
                    amount = trade.get('amount', 0)
                    old_sl_oid = trade.get('sl_order_id')
                    old_tp_oid = trade.get('tp_order_id')

                    if entry_price > 0 and amount > 0:
                        new_sl_oid, tp_oid = order_executor.update_sl_order_for_trade(
                            symbol, trade_signal, trade_id, amount, entry_price,
                            old_sl_order_id=old_sl_oid,
                            tp2_price=tp2_price if tp2_price else None,
                            old_tp_order_id=old_tp_oid,
                            exchange=self.exchange
                        )
                        if new_sl_oid:
                            trade_manager.update_trade_sl(
                                trade_id, entry_price, new_sl_order_id=new_sl_oid
                            )

                if is_closed:
                    sl_oid = trade.get('sl_order_id')
                    tp_oid = trade.get('tp_order_id')
                    order_executor.cancel_trade_orders(
                        symbol, sl_oid, tp_oid, exchange=self.exchange
                    )

        except Exception as e:
            logger.exception("Tracker Check Error (%s, trade:%s): %s",
                           symbol, trade.get("trade_id", "?"), e)
            print(f"Tracker Check Error ({symbol}): {e}")

    def _check_simulation_trades(self):
        """Simulasyon trade'lerini anlik fiyatla kontrol eder."""
        sim = simulation_engine.get_engine()
        all_open = sim.get_open_trades()

        if not all_open:
            return

        for symbol, trade_list in all_open.items():
            try:
                ticker = order_executor.fetch_ticker_with_retry(self.exchange, symbol)
                current_price = float(ticker['last'])
                price_cache.set_price(symbol, current_price)

                for trade in trade_list:
                    event, profit, is_closed = sim.check_trade_status(
                        symbol, trade, current_price
                    )

                    if event:
                        trade_id = trade.get("trade_id", "?")
                        print(f"{Fore.CYAN}[SIM] TRACKER UPDATE: {symbol} (trade:{trade_id}) "
                              f"-> {event} (Fiyat: {current_price}){Style.RESET_ALL}")
                        telegram_bot.send_trade_update(
                            symbol, f"SIM_{event}", current_price, profit, is_closed
                        )

            except Exception as e:
                logger.error("Sim Tracker Error (%s): %s", symbol, e)
