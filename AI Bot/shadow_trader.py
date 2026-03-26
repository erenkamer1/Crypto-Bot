"""
Shadow trading: track rejected signals virtually and record outcomes.
"""

import json
import os
import time
from datetime import datetime, timezone
from threading import Thread, Lock
import config
import order_executor
import trade_manager
import path_utils

_BASE_DIR = path_utils.get_base_dir()
PREDICTIONS_FILE = os.path.join(_BASE_DIR, getattr(config, 'ML_PREDICTIONS_FILE', 'ml_predictions.jsonl'))


class ShadowTrader:
    """Track rejected signals as virtual trades."""

    def __init__(self):
        self.shadow_trades = {}
        self.lock = Lock()
        self._running = False

    def add_shadow_trade(self, symbol, signal_type, entry_price, trade_setup, timestamp):
        """
        Add a rejected signal as a shadow trade.

        Args:
            symbol: Trading pair
            signal_type: LONG or SHORT
            entry_price: Entry price
            trade_setup: {"sl", "tp1", "tp2"}
            timestamp: Signal timestamp
        """
        with self.lock:
            key = f"{symbol}_{timestamp}"
            self.shadow_trades[key] = {
                "symbol": symbol,
                "signal_type": signal_type,
                "entry_price": entry_price,
                "sl": trade_setup.get("sl"),
                "tp1": trade_setup.get("tp1"),
                "tp2": trade_setup.get("tp2"),
                "timestamp": timestamp,
                "start_time": datetime.now(timezone.utc).isoformat(),
                "status": "open"
            }
            print(f"Shadow trade added: {symbol} {signal_type} @ {entry_price}")

    def check_shadow_trades(self, symbol, current_price, high=None, low=None):
        """
        Update shadow trades with latest price.
        After TP1, trade stays open until TP2 or SL (partial path simulation).

        Args:
            symbol: Pair
            current_price: Last price
            high: Bar high (optional)
            low: Bar low (optional)

        Returns:
            List of completed shadow trades
        """
        completed = []
        high = high or current_price
        low = low or current_price
        
        with self.lock:
            keys_to_remove = []
            
            for key, trade in self.shadow_trades.items():
                if trade["symbol"] != symbol or trade["status"] != "open":
                    continue
                
                entry = trade["entry_price"]
                sl = trade["sl"]
                tp1 = trade["tp1"]
                tp2 = trade["tp2"]
                signal_type = trade["signal_type"]
                tp1_hit = trade.get("tp1_hit", False)
                
                outcome = None
                close_price = None
                close_reason = None
                
                if signal_type == "LONG":
                    if not tp1_hit and current_price >= tp1:
                        trade["tp1_hit"] = True
                        trade["tp1_hit_time"] = datetime.now(timezone.utc).isoformat()
                        trade["tp1_price"] = tp1
                        print(f"Shadow TP1 hit: {symbol} @ {tp1} — waiting for TP2/SL...")

                    if trade.get("tp1_hit"):
                        if current_price <= sl:
                            outcome = "tp1_then_sl"
                            close_price = sl
                            close_reason = "TP1_HIT_THEN_SL"
                        elif current_price >= tp2:
                            outcome = "tp1_then_tp2"
                            close_price = tp2
                            close_reason = "TP1_THEN_TP2"
                    else:
                        if current_price <= sl:
                            outcome = "would_lose"
                            close_price = sl
                            close_reason = "SL_HIT"
                        elif current_price >= tp2:
                            outcome = "would_full_win"
                            close_price = tp2
                            close_reason = "TP2_HIT"

                else:  # SHORT
                    if not tp1_hit and current_price <= tp1:
                        trade["tp1_hit"] = True
                        trade["tp1_hit_time"] = datetime.now(timezone.utc).isoformat()
                        trade["tp1_price"] = tp1
                        print(f"Shadow TP1 hit: {symbol} @ {tp1} — waiting for TP2/SL...")

                    if trade.get("tp1_hit"):
                        if current_price >= sl:
                            outcome = "tp1_then_sl"
                            close_price = sl
                            close_reason = "TP1_HIT_THEN_SL"
                        elif current_price <= tp2:
                            outcome = "tp1_then_tp2"
                            close_price = tp2
                            close_reason = "TP1_THEN_TP2"
                    else:
                        if current_price >= sl:
                            outcome = "would_lose"
                            close_price = sl
                            close_reason = "SL_HIT"
                        elif current_price <= tp2:
                            outcome = "would_full_win"
                            close_price = tp2
                            close_reason = "TP2_HIT"

                if outcome:
                    # P&L: after TP1, SL moves to breakeven in live bot
                    if outcome == "tp1_then_tp2":
                        if signal_type == "LONG":
                            profit_pct = (tp2 - entry) / entry * 100
                        else:
                            profit_pct = (entry - tp2) / entry * 100
                            
                    elif outcome == "tp1_then_sl":
                        profit_pct = 0.0

                    else:
                        if signal_type == "LONG":
                            profit_pct = (close_price - entry) / entry * 100
                        else:
                            profit_pct = (entry - close_price) / entry * 100
                    
                    trade["status"] = "closed"
                    trade["outcome"] = outcome
                    trade["close_price"] = close_price
                    trade["close_reason"] = close_reason
                    trade["profit_pct"] = round(profit_pct, 2)
                    trade["close_time"] = datetime.now(timezone.utc).isoformat()
                    
                    self._update_prediction_outcome(trade)

                    completed.append(trade)
                    keys_to_remove.append(key)

                    if "win" in outcome or "tp2" in outcome:
                        status_emoji = "OK"
                    elif outcome == "tp1_then_sl":
                        status_emoji = "BE"
                    else:
                        status_emoji = "LOSS"

                    print(f"Shadow closed: {symbol} {outcome} ({profit_pct:+.2f}%) [{status_emoji}]")

            for key in keys_to_remove:
                del self.shadow_trades[key]

        return completed

    def check_active_trades(self, exchange):
        """Poll open shadow trades using exchange tickers."""
        with self.lock:
            active_symbols = set(t["symbol"] for t in self.shadow_trades.values() if t["status"] == "open")

        if not active_symbols:
            return

        prices = {}
        for symbol in active_symbols:
            try:
                ticker = order_executor.fetch_ticker_with_retry(exchange, symbol)
                prices[symbol] = float(ticker['last'])
            except Exception as e:
                print(f"Shadow price fetch error ({symbol}): {e}")
        
        for symbol, price in prices.items():
            self.check_shadow_trades(symbol, price, price, price)

    def _update_prediction_outcome(self, trade):
        """Update ml_predictions.jsonl line and append shadow row to signal_history."""
        if os.path.exists(PREDICTIONS_FILE):
            updated_records = []
            found = False
            
            try:
                with open(PREDICTIONS_FILE, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        record = json.loads(line)
                        
                        if (record.get('symbol') == trade['symbol'] and
                            record.get('timestamp') == trade['timestamp'] and
                            record.get('accepted') == False):
                            
                            record['outcome'] = trade['outcome']
                            record['outcome_source'] = 'shadow'
                            record['profit_pct'] = trade['profit_pct']
                            record['close_reason'] = trade['close_reason']
                            record['close_time'] = trade['close_time']
                            found = True
                        
                        updated_records.append(record)
                
                if found:
                    with open(PREDICTIONS_FILE, 'w', encoding='utf-8') as f:
                        for record in updated_records:
                            f.write(json.dumps(record, ensure_ascii=False) + '\n')
                            
            except Exception as e:
                print(f"Shadow prediction update error: {e}")
        try:
            history = trade_manager.load_history()
            history["signals"].append({
                "signal_id": f"shadow_{trade.get('timestamp', '')[:19].replace(':', '').replace('-', '')}",
                "symbol": trade["symbol"],
                "signal": f"{trade['signal_type']} (Shadow)",
                "entry": trade["entry_price"],
                "sl": trade["sl"],
                "tp1": trade["tp1"],
                "tp2": trade["tp2"],
                "start_time": trade.get("start_time", trade.get("timestamp", ""))[:19].replace("T", " "),
                "status": "CLOSED",
                "close_reason": trade["close_reason"],
                "close_time": trade.get("close_time", "")[:19].replace("T", " "),
                "close_price": trade.get("close_price"),
                "profit_pct": trade["profit_pct"],
                "trade_source": "shadow"
            })
            trade_manager.save_history(history)
        except Exception as e:
            print(f"Shadow history save error: {e}")

    def get_open_count(self):
        """Count of open shadow trades."""
        with self.lock:
            return sum(1 for t in self.shadow_trades.values() if t["status"] == "open")
    
    def get_stats(self):
        """Aggregate shadow stats (multiple outcome types)."""
        if not os.path.exists(PREDICTIONS_FILE):
            return None
        
        shadow_completed = []
        
        with open(PREDICTIONS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    if record.get('outcome_source') == 'shadow' and record.get('outcome'):
                        shadow_completed.append(record)
                except:
                    continue
        
        if not shadow_completed:
            return {"total": 0, "message": "No completed shadow trades yet."}

        total = len(shadow_completed)

        full_wins = sum(1 for r in shadow_completed if r.get('outcome') == 'would_full_win')
        tp1_then_tp2 = sum(1 for r in shadow_completed if r.get('outcome') == 'tp1_then_tp2')
        tp1_then_sl = sum(1 for r in shadow_completed if r.get('outcome') == 'tp1_then_sl')
        full_losses = sum(1 for r in shadow_completed if r.get('outcome') == 'would_lose')

        only_tp1 = sum(1 for r in shadow_completed if r.get('outcome') == 'would_win')

        total_profit = sum(r.get('profit_pct', 0) for r in shadow_completed)

        positive = full_wins + tp1_then_tp2 + tp1_then_sl + only_tp1
        negative = full_losses

        return {
            "total": total,
            "full_wins": full_wins,
            "tp1_then_tp2": tp1_then_tp2,
            "tp1_then_sl": tp1_then_sl,
            "only_tp1": only_tp1,
            "full_losses": full_losses,
            "total_profit_pct": round(total_profit, 2),
            "avg_profit_pct": round(total_profit / total, 2) if total > 0 else 0,
            "positive_rate": positive / total * 100 if total > 0 else 0,
            "message": (
                f"Shadow: {total} trades | +{positive} positive, -{negative} SL | "
                f"sum P&L: {total_profit:+.2f}%"
            ),
        }


# Global instance
_shadow_trader = None

def get_shadow_trader():
    """Return singleton ShadowTrader."""
    global _shadow_trader
    if _shadow_trader is None:
        _shadow_trader = ShadowTrader()
    return _shadow_trader

def add_shadow_trade(symbol, signal_type, entry_price, trade_setup, timestamp):
    """Convenience function."""
    return get_shadow_trader().add_shadow_trade(symbol, signal_type, entry_price, trade_setup, timestamp)

def check_shadow_trades(symbol, current_price, high=None, low=None):
    """Convenience function."""
    return get_shadow_trader().check_shadow_trades(symbol, current_price, high, low)

def get_stats():
    """Convenience function."""
    return get_shadow_trader().get_stats()

def check_active_trades(exchange):
    """Convenience function."""
    return get_shadow_trader().check_active_trades(exchange)

def print_stats():
    """Print shadow trading summary."""
    stats = get_stats()
    if stats:
        print("\nSHADOW TRADING")
        print(f"   {stats['message']}")
        if stats.get("total", 0) > 0:
            fl = stats.get("full_losses", 0)
            t = stats["total"]
            print(f"   Direct SL share: {fl / t * 100:.1f}%")
