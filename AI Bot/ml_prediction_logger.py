"""
ML prediction logger — logs all ML decisions for paper trading / analysis.
"""

import json
import os
from datetime import datetime, timezone
import config
import path_utils


class MLPredictionLogger:
    """Log and track ML predictions."""
    
    def __init__(self, log_file=None, jsonl_file=None):
        _base_dir = path_utils.get_base_dir()
        _default_log = os.path.join(_base_dir, getattr(config, 'ML_LOG_FILE', 'ml_predictions.log'))
        _default_jsonl = os.path.join(_base_dir, getattr(config, 'ML_PREDICTIONS_FILE', 'ml_predictions.jsonl'))
        self.log_file = log_file or _default_log
        self.jsonl_file = jsonl_file or _default_jsonl
        self.predictions = []
        self._counter = 0
    
    def log_prediction(self, symbol, signal_type, confidence, threshold, 
                       accepted, entry_price, reason=None,
                       features=None, trade_setup=None, timeframe=None):
        """
        Log one prediction with full detail.

        Args:
            symbol: Pair
            signal_type: LONG or SHORT
            confidence: ML score 0–1
            threshold: Threshold used
            accepted: Whether signal was taken
            entry_price: Entry price
            reason: Rejection reason if any
            features: Feature dict
            trade_setup: {"sl", "tp1", "tp2"}
            timeframe: e.g. 4h, 15m
        """
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

            # Filled when trade closes
            "outcome": None,
            "profit_pct": None,
            "close_reason": None,
            "duration_minutes": None
        }
        
        self.predictions.append(record)
        self._counter += 1
        
        status = "ACCEPT" if accepted else "REJECT"
        log_line = f"[{timestamp}] {symbol} | {signal_type} | conf: {confidence:.2f} | {status}"
        if reason:
            log_line += f" | reason: {reason}"
        
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(log_line + '\n')
        
        # JSONL log
        if getattr(config, 'ML_SAVE_PREDICTIONS_JSONL', True):
            with open(self.jsonl_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
        
        return record
    
    def update_outcome(self, symbol, timestamp, outcome, profit_pct):
        """
        Update outcome for a prediction line.

        Args:
            symbol: Pair
            timestamp: Prediction timestamp
            outcome: 'win', 'loss', 'breakeven'
            profit_pct: P&L %
        """
        updated_records = []
        found = False
        
        if os.path.exists(self.jsonl_file):
            with open(self.jsonl_file, 'r', encoding='utf-8') as f:
                for line in f:
                    record = json.loads(line.strip())
                    if record['symbol'] == symbol and record['timestamp'] == timestamp:
                        record['outcome'] = outcome
                        record['profit_pct'] = profit_pct
                        found = True
                    updated_records.append(record)
            
            if found:
                with open(self.jsonl_file, 'w', encoding='utf-8') as f:
                    for record in updated_records:
                        f.write(json.dumps(record, ensure_ascii=False) + '\n')
        
        return found
    
    def update_real_trade_outcome(self, symbol, close_reason, profit_pct, tp1_hit=False):
        """
        Update the latest accepted=true row for symbol (live trade close).

        Args:
            symbol: Pair
            close_reason: 'SL', 'TP1', 'TP2'
            profit_pct: P&L %
            tp1_hit: Whether TP1 was hit before close
        """
        from datetime import datetime, timezone

        if close_reason == "SL":
            if tp1_hit:
                outcome = "breakeven"
            else:
                outcome = "loss"
        elif close_reason == "TP1":
            outcome = "tp1_hit"
        elif close_reason == "TP2":
            if tp1_hit:
                outcome = "full_win"
            else:
                outcome = "full_win"
        else:
            outcome = close_reason.lower()
        updated_records = []
        found_index = -1
        
        if not os.path.exists(self.jsonl_file):
            return False
        
        with open(self.jsonl_file, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                updated_records.append(record)
                
                if (record.get('symbol') == symbol and
                    record.get('accepted') == True and
                    record.get('outcome') is None):
                    found_index = i

        if found_index >= 0:
            updated_records[found_index]['outcome'] = outcome
            updated_records[found_index]['outcome_source'] = 'real'
            updated_records[found_index]['profit_pct'] = profit_pct
            updated_records[found_index]['close_reason'] = close_reason
            updated_records[found_index]['close_time'] = datetime.now(timezone.utc).isoformat()
            updated_records[found_index]['tp1_hit_before_close'] = tp1_hit
            
            with open(self.jsonl_file, 'w', encoding='utf-8') as f:
                for record in updated_records:
                    f.write(json.dumps(record, ensure_ascii=False) + '\n')
            
            print(f"[ML] Live trade outcome saved: {symbol} -> {outcome} ({profit_pct:+.2f}%)")
            return True
        
        return False
    
    def get_stats(self):
        """Return aggregate ML stats from JSONL."""
        if not os.path.exists(self.jsonl_file):
            return None
        
        records = []
        with open(self.jsonl_file, 'r', encoding='utf-8') as f:
            for line in f:
                records.append(json.loads(line.strip()))
        
        total = len(records)
        accepted = sum(1 for r in records if r['accepted'])
        rejected = total - accepted
        
        completed = [r for r in records if r['outcome'] is not None]
        wins = sum(1 for r in completed if r['outcome'] == 'win')
        losses = sum(1 for r in completed if r['outcome'] == 'loss')
        
        stats = {
            "total_predictions": total,
            "accepted": accepted,
            "rejected": rejected,
            "completed_trades": len(completed),
            "wins": wins,
            "losses": losses,
            "win_rate": wins / len(completed) * 100 if completed else 0,
            "avg_confidence_accepted": sum(r['confidence'] for r in records if r['accepted']) / accepted if accepted else 0,
            "avg_confidence_rejected": sum(r['confidence'] for r in records if not r['accepted']) / rejected if rejected else 0
        }
        
        return stats
    
    def print_report(self):
        """Print performance summary."""
        stats = self.get_stats()
        if not stats:
            print("No prediction data yet.")
            return

        print("\n" + "="*50)
        print("ML PREDICTION PERFORMANCE")
        print("="*50)
        print(f"Total predictions: {stats['total_predictions']}")
        print(f"Accepted: {stats['accepted']} ({stats['accepted']/stats['total_predictions']*100:.1f}%)")
        print(f"Rejected: {stats['rejected']} ({stats['rejected']/stats['total_predictions']*100:.1f}%)")
        print(f"Completed (outcome set): {stats['completed_trades']}")
        if stats['completed_trades'] > 0:
            print(f"Win rate: {stats['win_rate']:.1f}%")
            print(f"Wins: {stats['wins']} | Losses: {stats['losses']}")
        print(f"Avg confidence (accepted): {stats['avg_confidence_accepted']:.3f}")
        print(f"Avg confidence (rejected): {stats['avg_confidence_rejected']:.3f}")
        print("="*50 + "\n")


# Global instance
_logger = None

def get_logger():
    """Singleton MLPredictionLogger."""
    global _logger
    if _logger is None:
        _logger = MLPredictionLogger()
    return _logger

def log_prediction(symbol, signal_type, confidence, threshold, accepted, entry_price, 
                   reason=None, features=None, trade_setup=None, timeframe=None):
    """Log one prediction (convenience)."""
    return get_logger().log_prediction(
        symbol, signal_type, confidence, threshold, accepted, entry_price, 
        reason, features, trade_setup, timeframe
    )

def print_report():
    """Convenience function."""
    get_logger().print_report()

def update_real_trade_outcome(symbol, close_reason, profit_pct, tp1_hit=False):
    """Update live trade outcome (convenience)."""
    return get_logger().update_real_trade_outcome(symbol, close_reason, profit_pct, tp1_hit)
