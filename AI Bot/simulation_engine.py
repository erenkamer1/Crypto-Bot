"""
Simulation Engine
Gercek Binance islemlerini simule eden motor.
Komisyon, slippage, bakiye yonetimi, ayri dosya sistemi.
Data semalari gercek dosyalarla BIREBIR AYNI.
"""

import json
import os
import uuid
import random
import threading
from datetime import datetime, timezone
from typing import Optional, Tuple, Dict, List

import path_utils

try:
    import runtime_config
    _RC_AVAILABLE = True
except ImportError:
    _RC_AVAILABLE = False

try:
    import config
except ImportError:
    config = None

_BASE_DIR = path_utils.get_base_dir()

SIM_TRADES_FILE = os.path.join(_BASE_DIR, "simulation_trades.json")
SIM_HISTORY_FILE = os.path.join(_BASE_DIR, "simulation_signal_history.json")
SIM_ML_PREDICTIONS_FILE = os.path.join(_BASE_DIR, "simulation_ml_predictions.jsonl")
SIM_ML_PREDICTIONS_LOG = os.path.join(_BASE_DIR, "simulation_ml_predictions.log")
SIM_ML_TRAINING_DATA_FILE = os.path.join(_BASE_DIR, "simulation_ml_training_data.jsonl")

TAKER_FEE_PCT = 0.0004  # %0.04
SLIPPAGE_MIN_PCT = 0.0001  # %0.01
SLIPPAGE_MAX_PCT = 0.0005  # %0.05

# Breakeven bandi: -0.5 ile +0.5 arasi BL sayilir (kayma/tam kapanma nedeniyle)
BREAKEVEN_BAND_PCT = 0.5


def _generate_id():
    return str(uuid.uuid4())[:8]


class SimulationEngine:
    """Binance Futures islemlerini simule eder."""

    def __init__(self):
        self._lock = threading.RLock()
        self._trades: Dict = {}
        self._history: Dict = {"signals": []}
        self._load_trades()
        self._load_history()

    # ======================== PERSISTENCE ========================

    def _load_trades(self):
        if os.path.exists(SIM_TRADES_FILE):
            try:
                with open(SIM_TRADES_FILE, 'r', encoding='utf-8') as f:
                    self._trades = json.load(f)
            except Exception:
                self._trades = {}
        else:
            self._trades = {}

    def _save_trades(self):
        try:
            with open(SIM_TRADES_FILE, 'w', encoding='utf-8') as f:
                json.dump(self._trades, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[SIM] Trade dosyasi kaydedilemedi: {e}")

    def _load_history(self):
        if os.path.exists(SIM_HISTORY_FILE):
            try:
                with open(SIM_HISTORY_FILE, 'r', encoding='utf-8') as f:
                    self._history = json.load(f)
            except Exception:
                self._history = {"signals": []}
        else:
            self._history = {"signals": []}

    def _save_history(self):
        try:
            with open(SIM_HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(self._history, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[SIM] History dosyasi kaydedilemedi: {e}")

    # ======================== BALANCE ========================

    def _get_rc(self):
        if _RC_AVAILABLE:
            return runtime_config.get_config()
        return None

    def get_available_balance(self) -> float:
        """Kullanilabilir simulasyon bakiyesi (toplam - acik islemlerde kullanilan)."""
        rc = self._get_rc()
        if not rc:
            return 0.0
        total = rc.simulation_current_balance
        allocated = self._get_allocated_amount()
        return max(0.0, total - allocated)

    def _get_allocated_amount(self) -> float:
        """Acik islemlerde kullanilan toplam USDT miktari."""
        total = 0.0
        with self._lock:
            for symbol, trade_list in self._trades.items():
                for t in trade_list:
                    if t.get("status") == "OPEN":
                        total += t.get("notional_usdt", 0.0)
        return total

    def _get_trade_amount(self) -> float:
        rc = self._get_rc()
        if not rc:
            return 0.0
        return rc.get_simulation_trade_amount()

    def _deduct_balance(self, amount: float):
        rc = self._get_rc()
        if rc:
            rc.simulation_current_balance -= amount

    def _add_balance(self, amount: float):
        rc = self._get_rc()
        if rc:
            rc.simulation_current_balance += amount

    # ======================== SLIPPAGE & COMMISSION ========================

    def _apply_slippage(self, price: float, direction: str) -> float:
        """Simule slippage uygular. Market order oldugundan girisin biraz kotu olur."""
        slip_pct = random.uniform(SLIPPAGE_MIN_PCT, SLIPPAGE_MAX_PCT)
        if "LONG" in direction:
            return price * (1 + slip_pct)
        else:
            return price * (1 - slip_pct)

    def _calc_commission(self, notional: float) -> float:
        """Taker komisyon hesaplar."""
        return notional * TAKER_FEE_PCT

    # ======================== TRADE EXECUTION ========================

    def can_add_trade(self, symbol: str, direction: str) -> Tuple[bool, str]:
        """Simulasyon trade eklenebilir mi kontrol eder."""
        rc = self._get_rc()
        if not rc:
            return False, "RuntimeConfig yok"

        trade_amount = self._get_trade_amount()
        available = self.get_available_balance()

        if trade_amount > available:
            return False, f"Yetersiz bakiye ({available:.2f} < {trade_amount:.2f})"

        with self._lock:
            open_trades = [t for t in self._trades.get(symbol, []) if t.get("status") == "OPEN"]

        if not open_trades:
            return True, ""

        max_allowed = rc.max_trades_per_coin
        if len(open_trades) >= max_allowed:
            return False, f"Maks limit ({len(open_trades)}/{max_allowed})"

        existing_dir = open_trades[0].get("signal", "")
        if "LONG" in direction and "SHORT" in existing_dir:
            return False, "Ters yon: mevcut SHORT, yeni LONG"
        if "SHORT" in direction and "LONG" in existing_dir:
            return False, "Ters yon: mevcut LONG, yeni SHORT"

        return True, ""

    def open_trade(self, symbol: str, signal_type: str, market_price: float,
                   sl: float, tp1: float, tp2: float,
                   ml_confidence: Optional[float] = None) -> Optional[dict]:
        """
        Simulasyon islemi acar. Slippage + komisyon uygulanir.
        Returns: trade objesi veya None.
        """
        rc = self._get_rc()
        if not rc:
            return None

        trade_amount_usdt = self._get_trade_amount()
        available = self.get_available_balance()
        if trade_amount_usdt > available:
            print(f"[SIM] Yetersiz bakiye: {available:.2f} < {trade_amount_usdt:.2f}")
            return None

        direction = "LONG" if "LONG" in signal_type else "SHORT"
        sim_entry = self._apply_slippage(market_price, direction)

        entry_commission = self._calc_commission(trade_amount_usdt)

        sl_pct_val = rc.sl_pct / 100.0
        tp1_pct_val = rc.tp1_pct / 100.0
        tp2_pct_val = rc.tp2_pct / 100.0

        if "LONG" in signal_type:
            sim_sl = sim_entry * (1 - sl_pct_val)
            sim_tp1 = sim_entry * (1 + tp1_pct_val)
            sim_tp2 = sim_entry * (1 + tp2_pct_val)
        else:
            sim_sl = sim_entry * (1 + sl_pct_val)
            sim_tp1 = sim_entry * (1 - tp1_pct_val)
            sim_tp2 = sim_entry * (1 - tp2_pct_val)

        amount_coin = trade_amount_usdt / sim_entry

        trade_id = _generate_id()
        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        trade_obj = {
            "trade_id": trade_id,
            "signal_id": trade_id,
            "signal": signal_type,
            "entry": round(sim_entry, 6),
            "original_market_price": round(market_price, 6),
            "amount": round(amount_coin, 6),
            "notional_usdt": round(trade_amount_usdt, 2),
            "sl": round(sim_sl, 6),
            "tp1": round(sim_tp1, 6),
            "tp2": round(sim_tp2, 6),
            "tp1_hit": False,
            "sl_order_id": None,
            "tp_order_id": None,
            "start_time": start_time,
            "status": "OPEN",
            "entry_commission": round(entry_commission, 6),
            "slippage_pct": round(abs(sim_entry - market_price) / market_price * 100, 4),
        }

        with self._lock:
            if symbol not in self._trades:
                self._trades[symbol] = []
            self._trades[symbol].append(trade_obj)
            self._save_trades()

        self._deduct_balance(trade_amount_usdt)

        history_entry = {
            "signal_id": trade_id,
            "symbol": symbol,
            "signal": signal_type,
            "entry": round(sim_entry, 6),
            "sl": round(sim_sl, 6),
            "tp1": round(sim_tp1, 6),
            "tp2": round(sim_tp2, 6),
            "start_time": start_time,
            "status": "OPEN",
            "close_reason": None,
            "close_time": None,
            "close_price": None,
            "profit_pct": None,
            "notional_usdt": round(trade_amount_usdt, 2),
            "trade_source": "simulation",
            "binance_order_id": f"sim_{trade_id}",
            "ml_confidence": ml_confidence if ml_confidence is not None else "-"
        }
        with self._lock:
            self._history["signals"].append(history_entry)
            self._save_history()

        print(f"[SIM] Islem Acildi: {symbol} {signal_type} @ {sim_entry:.6f} "
              f"(Market: {market_price:.6f}, Slippage: {trade_obj['slippage_pct']:.3f}%, "
              f"Komisyon: {entry_commission:.4f} USDT)")

        return trade_obj

    # ======================== TRADE STATUS CHECK ========================

    def check_trade_status(self, symbol: str, trade: dict, current_price: float):
        """
        Simulasyon trade'i icin fiyat kontrolu.
        Donus: (event_type, profit_pct, is_closed)
        """
        if trade.get("status") != "OPEN":
            return None, None, False

        signal = trade["signal"]
        entry = trade["entry"]
        sl = trade["sl"]
        tp1 = trade["tp1"]
        tp2 = trade["tp2"]

        event_type = None
        is_closed = False
        close_price = None
        profit_pct = 0.0

        if "LONG" in signal:
            profit_pct = (current_price - entry) / entry

            if current_price <= sl:
                event_type = "SL"
                is_closed = True
                close_price = sl
                profit_pct = (sl - entry) / entry
            elif current_price >= tp2:
                event_type = "TP2"
                is_closed = True
                close_price = tp2
                profit_pct = (tp2 - entry) / entry
            elif current_price >= tp1 and not trade.get("tp1_hit"):
                event_type = "TP1"
                profit_pct = (tp1 - entry) / entry

        elif "SHORT" in signal:
            profit_pct = (entry - current_price) / entry

            if current_price >= sl:
                event_type = "SL"
                is_closed = True
                close_price = sl
                profit_pct = (entry - sl) / entry
            elif current_price <= tp2:
                event_type = "TP2"
                is_closed = True
                close_price = tp2
                profit_pct = (entry - tp2) / entry
            elif current_price <= tp1 and not trade.get("tp1_hit"):
                event_type = "TP1"
                profit_pct = (entry - tp1) / entry

        if event_type == "TP1" and not is_closed:
            with self._lock:
                trade["tp1_hit"] = True
                trade["sl"] = entry
                self._update_trade_in_file(trade["trade_id"], {"tp1_hit": True, "sl": entry})

        if is_closed:
            exit_commission_pct = TAKER_FEE_PCT
            net_profit_pct = profit_pct - (TAKER_FEE_PCT * 2)
            self._close_trade(trade["trade_id"], event_type, close_price, net_profit_pct)

        return event_type, profit_pct, is_closed

    def _close_trade(self, trade_id: str, close_reason: str, close_price: float, net_profit_pct: float):
        """Simulasyon trade'ini kapatir, bakiyeyi gunceller."""
        close_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with self._lock:
            for symbol, trade_list in self._trades.items():
                for i, trade in enumerate(trade_list):
                    if trade.get("trade_id") == trade_id:
                        notional = trade.get("notional_usdt", 0)
                        exit_commission = self._calc_commission(notional)

                        pnl_usdt = notional * net_profit_pct
                        returned = notional + pnl_usdt - exit_commission

                        self._add_balance(returned)

                        trade_list.pop(i)
                        if not trade_list:
                            del self._trades[symbol]
                        self._save_trades()

                        for hist in self._history["signals"]:
                            if hist.get("signal_id") == trade_id:
                                hist["status"] = "CLOSED"
                                hist["close_reason"] = close_reason
                                hist["close_time"] = close_time
                                hist["close_price"] = close_price
                                hist["profit_pct"] = round(net_profit_pct * 100, 2)
                                hist["notional_usdt"] = round(notional, 2)
                                break
                        self._save_history()

                        self._update_ml_training_label(trade_id, close_reason,
                                                       round(net_profit_pct * 100, 2),
                                                       trade.get("tp1_hit", False))

                        self._update_ml_prediction_outcome(
                            symbol, close_reason,
                            round(net_profit_pct * 100, 2),
                            trade.get("tp1_hit", False)
                        )

                        print(f"[SIM] Islem Kapandi: {symbol} ({trade_id}) -> {close_reason} "
                              f"({net_profit_pct*100:+.2f}%) | PnL: {pnl_usdt:+.2f} USDT")
                        return True
        return False

    def _update_trade_in_file(self, trade_id: str, updates: dict):
        """Trade dosyasindaki belirli trade'i gunceller."""
        with self._lock:
            for symbol, trade_list in self._trades.items():
                for trade in trade_list:
                    if trade.get("trade_id") == trade_id:
                        trade.update(updates)
                        self._save_trades()
                        return

    # ======================== POSITION SUMMARY ========================

    def get_open_trades(self, symbol: Optional[str] = None) -> Dict[str, list]:
        """Acik simulasyon trade'lerini dondurur."""
        with self._lock:
            if symbol:
                trades = [t for t in self._trades.get(symbol, []) if t.get("status") == "OPEN"]
                return {symbol: trades} if trades else {}

            result = {}
            for sym, trade_list in self._trades.items():
                open_trades = [t for t in trade_list if t.get("status") == "OPEN"]
                if open_trades:
                    result[sym] = open_trades
            return result

    def get_all_open_trades_flat(self) -> List[dict]:
        """Tum acik trade'leri duz liste olarak dondurur (symbol eklenmis)."""
        result = []
        with self._lock:
            for symbol, trade_list in self._trades.items():
                for t in trade_list:
                    if t.get("status") == "OPEN":
                        t_copy = dict(t)
                        t_copy["symbol"] = symbol
                        result.append(t_copy)
        return result

    def calculate_unrealized_pnl(self, symbol: str, current_price: float) -> dict:
        """
        Belirli coin icin acik pozisyonlarin anlik PnL hesabi.
        Binance'in gosterdigi gibi: avg_entry, total_amount, unrealized_pnl
        """
        with self._lock:
            open_trades = [t for t in self._trades.get(symbol, []) if t.get("status") == "OPEN"]

        if not open_trades:
            return {"symbol": symbol, "count": 0}

        total_notional = 0.0
        total_amount = 0.0
        weighted_entry_sum = 0.0

        for t in open_trades:
            amt = t.get("amount", 0)
            entry = t.get("entry", 0)
            total_amount += amt
            total_notional += t.get("notional_usdt", 0)
            weighted_entry_sum += amt * entry

        avg_entry = weighted_entry_sum / total_amount if total_amount > 0 else 0

        direction = open_trades[0].get("signal", "LONG")
        if "LONG" in direction:
            pnl_pct = (current_price - avg_entry) / avg_entry * 100 if avg_entry > 0 else 0
        else:
            pnl_pct = (avg_entry - current_price) / avg_entry * 100 if avg_entry > 0 else 0

        pnl_usdt = total_notional * (pnl_pct / 100)

        return {
            "symbol": symbol,
            "direction": direction,
            "count": len(open_trades),
            "avg_entry": round(avg_entry, 6),
            "total_amount": round(total_amount, 6),
            "total_notional": round(total_notional, 2),
            "current_price": round(current_price, 6),
            "unrealized_pnl_pct": round(pnl_pct, 2),
            "unrealized_pnl_usdt": round(pnl_usdt, 2),
        }

    # ======================== ML DATA LOGGING ========================
    # Semalar gercek dosyalardakiyle BIREBIR AYNI

    def log_ml_prediction(self, symbol, signal_type, confidence, threshold,
                          accepted, entry_price, reason=None,
                          features=None, trade_setup=None, timeframe=None):
        """ml_predictions.jsonl semasinda simulasyon tahmini loglar."""
        timestamp = datetime.now(timezone.utc).isoformat()

        record = {
            "timestamp": timestamp,
            "symbol": symbol,
            "signal_type": signal_type,
            "timeframe": timeframe or "4h",
            "confidence": round(confidence, 4),
            "threshold": threshold,
            "accepted": accepted,
            "entry_price": entry_price,
            "reason": reason,
            "trade_setup": trade_setup or {},
            "features": features or {},
            "outcome": None,
            "profit_pct": None,
            "close_reason": None,
            "duration_minutes": None,
        }

        status = "KABUL" if accepted else "RED"
        log_line = f"[{timestamp}] {symbol} | {signal_type} | Guven: {confidence:.2f} | {status}"
        if reason:
            log_line += f" | Sebep: {reason}"

        try:
            with open(SIM_ML_PREDICTIONS_LOG, 'a', encoding='utf-8') as f:
                f.write(log_line + '\n')
        except Exception:
            pass

        try:
            with open(SIM_ML_PREDICTIONS_FILE, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
        except Exception:
            pass

        return record

    def _update_ml_prediction_outcome(self, symbol, close_reason, profit_pct, tp1_hit=False):
        """Simulasyon ml_predictions dosyasinda sonuc gunceller."""
        if close_reason == "SL":
            outcome = "breakeven" if tp1_hit else "loss"
        elif close_reason == "TP1":
            outcome = "tp1_hit"
        elif close_reason == "TP2":
            outcome = "full_win"
        else:
            outcome = close_reason.lower() if close_reason else "unknown"

        if not os.path.exists(SIM_ML_PREDICTIONS_FILE):
            return

        updated_records = []
        found_index = -1

        try:
            with open(SIM_ML_PREDICTIONS_FILE, 'r', encoding='utf-8') as f:
                for i, line in enumerate(f):
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    updated_records.append(record)
                    if (record.get('symbol') == symbol and
                            record.get('accepted') is True and
                            record.get('outcome') is None):
                        found_index = i
        except Exception:
            return

        if found_index >= 0 and found_index < len(updated_records):
            updated_records[found_index]['outcome'] = outcome
            updated_records[found_index]['outcome_source'] = 'simulation'
            updated_records[found_index]['profit_pct'] = profit_pct
            updated_records[found_index]['close_reason'] = close_reason
            updated_records[found_index]['close_time'] = datetime.now(timezone.utc).isoformat()
            updated_records[found_index]['tp1_hit_before_close'] = tp1_hit

            try:
                with open(SIM_ML_PREDICTIONS_FILE, 'w', encoding='utf-8') as f:
                    for record in updated_records:
                        f.write(json.dumps(record, ensure_ascii=False) + '\n')
            except Exception:
                pass

    def log_ml_training_data(self, signal_id, symbol, signal_type, df, entry_price,
                             sl, tp1, tp2, timeframe, btc_df=None, spread_pct=0.05):
        """
        ml_training_data.jsonl semasinda simulasyon egitim datasi loglar.
        Gercek ml_data_logger.log_signal ile AYNI sema.
        """
        try:
            import ml_data_logger
            from datetime import timezone as tz
            import pandas as pd

            now = datetime.now(tz.utc)
            last_candle = df.iloc[-1]

            candle_close_time = last_candle['timestamp']
            if isinstance(candle_close_time, pd.Timestamp):
                candle_close_time = candle_close_time.isoformat()

            technical = ml_data_logger.collect_technical_features(df, entry_price)
            context = ml_data_logger.collect_context_features(btc_df)

            record = {
                'signal_id': signal_id,
                'timestamp': now.isoformat(),
                'candle_close_time': candle_close_time,
                'is_candle_closed': True,
                'symbol': symbol,
                'symbol_category': ml_data_logger.get_symbol_category(symbol),
                'signal_type': 'LONG' if 'LONG' in signal_type else 'SHORT',
                'timeframe': timeframe,
                'technical': technical,
                'context': context,
                'trade': {
                    'entry_price': round(entry_price, 6),
                    'sl': round(sl, 6),
                    'tp1': round(tp1, 6),
                    'tp2': round(tp2, 6),
                },
                'execution': {
                    'spread_pct': spread_pct,
                    'order_type': 'market',
                    'mode': 'simulation',
                },
                'label': None,
                'close_reason': None,
                'profit_pct': None,
                'final_rr': None,
                'duration_minutes': None,
                'meta': {
                    'strategy_version': ml_data_logger.STRATEGY_VERSION,
                    'feature_version': ml_data_logger.FEATURE_VERSION,
                }
            }

            with open(SIM_ML_TRAINING_DATA_FILE, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False,
                                   default=ml_data_logger.json_serializer) + '\n')

            print(f"[SIM-ML] Egitim datasi kaydedildi: {signal_id}")
            return record

        except Exception as e:
            print(f"[SIM-ML] Egitim datasi kayit hatasi: {e}")
            return None

    def _update_ml_training_label(self, signal_id, close_reason, profit_pct, tp1_hit=False):
        """Simulasyon ml_training_data dosyasinda label gunceller."""
        if not os.path.exists(SIM_ML_TRAINING_DATA_FILE):
            return

        try:
            import ml_data_logger

            if close_reason == 'TP2' or (close_reason == 'TP1' and profit_pct > 0):
                label = 'full_win'
            elif tp1_hit and close_reason == 'SL':
                label = 'breakeven'
            elif close_reason == 'SL':
                label = 'loss'
            else:
                label = 'partial_win'

            final_rr = round(profit_pct / 4, 2) if profit_pct != 0 else 0

            lines = []
            updated = False

            with open(SIM_ML_TRAINING_DATA_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    record = json.loads(line.strip())
                    if record.get('signal_id') == signal_id and not updated:
                        start_time = datetime.fromisoformat(
                            record['timestamp'].replace('Z', '+00:00'))
                        duration = (datetime.now(timezone.utc) - start_time).total_seconds() / 60

                        record['label'] = label
                        record['close_reason'] = close_reason
                        record['profit_pct'] = round(profit_pct, 2)
                        record['final_rr'] = final_rr
                        record['duration_minutes'] = round(duration, 1)
                        updated = True
                    lines.append(json.dumps(record, ensure_ascii=False,
                                            default=ml_data_logger.json_serializer))

            if updated:
                with open(SIM_ML_TRAINING_DATA_FILE, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(lines) + '\n')

        except Exception as e:
            print(f"[SIM-ML] Label guncelleme hatasi: {e}")

    # ======================== BALANCE SYNC ========================

    def sync_balance_from_history(self) -> bool:
        """
        Guncel bakiyeyi simulation_signal_history.json'dan yeniden hesaplar ve
        runtime_config'e yazar. Boylece Bakiye P&L her zaman dogru gosterilir.
        """
        rc = self._get_rc()
        if not rc:
            return False
        starting = rc.simulation_balance
        with self._lock:
            all_signals = self._history.get("signals", [])
            closed = [s for s in all_signals if s.get("status") == "CLOSED"]
        total_pnl_usdt = 0.0
        for s in closed:
            pct = s.get("profit_pct")
            if pct is None:
                continue
            notional = s.get("notional_usdt")
            if isinstance(notional, (int, float)) and notional > 0:
                total_pnl_usdt += notional * (pct / 100.0)
            else:
                # Eski kayitlar: sim ayarina gore notional tahmin et
                if rc.simulation_use_fixed_amount:
                    est_notional = rc.simulation_fixed_amount
                else:
                    est_notional = (starting / len(closed)) if closed else 0.0
                total_pnl_usdt += est_notional * (pct / 100.0)
        new_balance = max(0.0, starting + total_pnl_usdt)
        rc.simulation_current_balance = round(new_balance, 2)
        return True

    # ======================== STATISTICS ========================

    def get_stats(self) -> dict:
        """Simulasyon istatistiklerini dondurur."""
        self.sync_balance_from_history()
        rc = self._get_rc()
        starting_balance = rc.simulation_balance if rc else 0
        current_balance = rc.simulation_current_balance if rc else 0

        with self._lock:
            all_signals = self._history.get("signals", [])
            closed = [s for s in all_signals if s.get("status") == "CLOSED"]
            open_trades = [s for s in all_signals if s.get("status") == "OPEN"]

        # -0.5% ile +0.5% arasi breakeven (kaymalar nedeniyle tam 0 olmuyor)
        def _pnl(p):
            return p.get('profit_pct') if p.get('profit_pct') is not None else None
        wins = len([s for s in closed if (_pnl(s) or 0) > BREAKEVEN_BAND_PCT])
        losses = len([s for s in closed if (_pnl(s) or 0) < -BREAKEVEN_BAND_PCT])
        breakeven = len([s for s in closed if _pnl(s) is not None and -BREAKEVEN_BAND_PCT <= (_pnl(s) or 0) <= BREAKEVEN_BAND_PCT])
        total_pnl = sum(s.get('profit_pct', 0) or 0 for s in closed)
        avg_pnl = total_pnl / len(closed) if closed else 0
        # Win+BE orani (kazanan + breakeven) / toplam
        win_rate = ((wins + breakeven) / len(closed) * 100) if closed else 0

        return {
            "starting_balance": starting_balance,
            "current_balance": current_balance,
            "balance_pnl": round(current_balance - starting_balance, 2),
            "balance_pnl_pct": round((current_balance - starting_balance) / starting_balance * 100, 2) if starting_balance > 0 else 0,
            "total_trades": len(all_signals),
            "open_trades": len(open_trades),
            "closed_trades": len(closed),
            "wins": wins,
            "losses": losses,
            "breakeven": breakeven,
            "win_rate": round(win_rate, 1),
            "total_pnl_pct": round(total_pnl, 2),
            "avg_pnl_pct": round(avg_pnl, 2),
        }


# ======================== SINGLETON ========================

_engine: Optional[SimulationEngine] = None


def get_engine() -> SimulationEngine:
    global _engine
    if _engine is None:
        _engine = SimulationEngine()
    return _engine
