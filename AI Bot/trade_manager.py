import json
import os
import uuid
from datetime import datetime
import config
import ml_data_logger
import path_utils

_BASE_DIR = path_utils.get_base_dir()
TRADES_FILE = os.path.join(_BASE_DIR, "trades.json")
HISTORY_FILE = os.path.join(_BASE_DIR, "signal_history.json")

try:
    import runtime_config
    _RC_AVAILABLE = True
except ImportError:
    _RC_AVAILABLE = False


def generate_signal_id():
    """Kisa benzersiz sinyal ID'si uretir."""
    return str(uuid.uuid4())[:8]


def load_history():
    """Sinyal gecmisini dosyadan okur."""
    if not os.path.exists(HISTORY_FILE):
        return {"signals": []}
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Gecmis dosyasi okunamadi: {e}")
        return {"signals": []}


def save_history(history):
    """Sinyal gecmisini dosyaya kaydeder."""
    try:
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Gecmis dosyasi kaydedilemedi: {e}")


def load_trades():
    """
    Yuklu islemleri dosyadan okur.
    Yeni sema: { "BTC/USDT": [ {trade1}, {trade2} ], ... }
    Eski sema otomatik migrate edilir.
    """
    if not os.path.exists(TRADES_FILE):
        return {}
    try:
        with open(TRADES_FILE, 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Trade dosyasi okunamadi: {e}")
        return {}

    migrated = False
    result = {}
    for symbol, value in data.items():
        if isinstance(value, list):
            result[symbol] = value
        elif isinstance(value, dict):
            if value.get("status") == "OPEN":
                if "trade_id" not in value:
                    value["trade_id"] = value.get("signal_id", generate_signal_id())
                if "amount" not in value:
                    value["amount"] = 0
                if "sl_order_id" not in value:
                    value["sl_order_id"] = None
                if "tp_order_id" not in value:
                    value["tp_order_id"] = None
                result[symbol] = [value]
            migrated = True
        else:
            result[symbol] = []
            migrated = True

    if migrated:
        save_trades(result)

    return result


def save_trades(trades):
    """Islemleri dosyaya kaydeder."""
    try:
        with open(TRADES_FILE, 'w') as f:
            json.dump(trades, f, indent=4)
    except Exception as e:
        print(f"Trade dosyasi kaydedilemedi: {e}")


def _get_max_trades_per_coin():
    """Runtime config'den veya config.py'den max_trades_per_coin degerini alir."""
    if _RC_AVAILABLE:
        return runtime_config.get_config().max_trades_per_coin
    return getattr(config, 'MAX_TRADES_PER_COIN', 3)


def get_open_trades(symbol):
    """Belirli coin icin acik trade listesini dondurur."""
    trades = load_trades()
    trade_list = trades.get(symbol, [])
    return [t for t in trade_list if t.get("status") == "OPEN"]


def get_all_open_trades():
    """Tum coinlerdeki acik trade'leri dondurur. {symbol: [trade_list]} formatinda."""
    trades = load_trades()
    result = {}
    for symbol, trade_list in trades.items():
        open_trades = [t for t in trade_list if t.get("status") == "OPEN"]
        if open_trades:
            result[symbol] = open_trades
    return result


def has_open_trade(symbol):
    """Belirtilen coin icin acik islem var mi kontrol eder (geriye uyumluluk)."""
    return len(get_open_trades(symbol)) > 0


def can_add_trade(symbol, direction):
    """
    Yeni trade eklenebilir mi kontrol eder.
    - max_trades_per_coin limitine bakar
    - Sadece ayni yon kontrol eder (ters yon engellenir)
    Returns: (bool, reason_str)
    """
    open_trades = get_open_trades(symbol)

    if not open_trades:
        return True, ""

    max_allowed = _get_max_trades_per_coin()
    if len(open_trades) >= max_allowed:
        return False, f"Maks limit asildi ({len(open_trades)}/{max_allowed})"

    existing_direction = open_trades[0].get("signal", "")
    if "LONG" in direction and "SHORT" in existing_direction:
        return False, "Ters yon: mevcut SHORT, yeni LONG"
    if "SHORT" in direction and "LONG" in existing_direction:
        return False, "Ters yon: mevcut LONG, yeni SHORT"

    return True, ""


def add_trade(symbol, signal_type, entry_price, sl, tp1, tp2,
              amount=0, binance_order_id=None, ml_confidence=None):
    """Yeni bir islem ekler ve gecmise kaydeder. Listeye append eder (ustune yazmaz)."""
    trades = load_trades()

    trade_id = generate_signal_id()
    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    trade_obj = {
        "trade_id": trade_id,
        "signal_id": trade_id,
        "signal": signal_type,
        "entry": entry_price,
        "amount": amount,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp1_hit": False,
        "sl_order_id": None,
        "tp_order_id": None,
        "start_time": start_time,
        "status": "OPEN"
    }

    if symbol not in trades:
        trades[symbol] = []
    trades[symbol].append(trade_obj)
    save_trades(trades)

    history = load_history()
    history["signals"].append({
        "signal_id": trade_id,
        "symbol": symbol,
        "signal": signal_type,
        "entry": entry_price,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "start_time": start_time,
        "status": "OPEN",
        "close_reason": None,
        "close_time": None,
        "close_price": None,
        "profit_pct": None,
        "trade_source": "binance",
        "binance_order_id": binance_order_id or "-",
        "ml_confidence": ml_confidence if ml_confidence is not None else "-"
    })
    save_history(history)

    print(f"Takip Baslatildi: {symbol} (ID: {trade_id})")
    return trade_id


def update_trade_orders(trade_id, sl_order_id=None, tp_order_id=None):
    """Trade'in Binance order ID'lerini gunceller."""
    trades = load_trades()
    for symbol, trade_list in trades.items():
        for trade in trade_list:
            if trade.get("trade_id") == trade_id:
                if sl_order_id is not None:
                    trade["sl_order_id"] = str(sl_order_id)
                if tp_order_id is not None:
                    trade["tp_order_id"] = str(tp_order_id)
                save_trades(trades)
                return True
    return False


def update_binance_order_id(symbol, signal_id, order_id):
    """Binance order ID'sini signal_history.json'a kaydeder."""
    if not order_id:
        return False
    history = load_history()
    for h in reversed(history["signals"]):
        if h.get("signal_id") == signal_id and h.get("status") == "OPEN":
            h["binance_order_id"] = str(order_id)
            break
    else:
        return False
    save_history(history)
    print(f"Binance Order ID kaydedildi: {order_id} (Sinyal: {signal_id})")
    return True


def update_trade_entry_to_fill(symbol, signal_id, real_entry, sl, tp1, tp2):
    """Gercek fill fiyatina gore entry/SL/TP1/TP2 gunceller."""
    trades = load_trades()
    trade_list = trades.get(symbol, [])
    found = False
    for trade in trade_list:
        if trade.get("trade_id") == signal_id or trade.get("signal_id") == signal_id:
            trade["entry"] = real_entry
            trade["sl"] = sl
            trade["tp1"] = tp1
            trade["tp2"] = tp2
            found = True
            break
    if found:
        save_trades(trades)

    history = load_history()
    for h in reversed(history["signals"]):
        if h.get("signal_id") == signal_id and h.get("status") == "OPEN":
            h["entry"] = real_entry
            h["sl"] = sl
            h["tp1"] = tp1
            h["tp2"] = tp2
            break
    save_history(history)
    return found


def get_trade_by_id(trade_id):
    """trade_id ile trade objesini ve sembolunu dondurur. (symbol, trade) veya (None, None)."""
    trades = load_trades()
    for symbol, trade_list in trades.items():
        for trade in trade_list:
            if trade.get("trade_id") == trade_id:
                return symbol, trade
    return None, None


def close_trade_by_id(trade_id, close_reason, close_price, profit_pct):
    """
    Belirli bir trade'i kapatir. Diger trade'lere dokunmaz.
    trade'i listeden cikarir ve history'yi gunceller.
    """
    trades = load_trades()
    close_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for symbol, trade_list in trades.items():
        for i, trade in enumerate(trade_list):
            if trade.get("trade_id") == trade_id:
                signal_id = trade.get("signal_id", trade_id)
                tp1_hit = trade.get("tp1_hit", False)

                trade_list.pop(i)

                if not trade_list:
                    del trades[symbol]
                save_trades(trades)

                history = load_history()
                for hist_signal in history["signals"]:
                    if hist_signal.get("signal_id") == signal_id:
                        hist_signal["status"] = "CLOSED"
                        hist_signal["close_reason"] = close_reason
                        hist_signal["close_time"] = close_time
                        hist_signal["close_price"] = close_price
                        hist_signal["profit_pct"] = round(profit_pct * 100, 2)
                        break
                save_history(history)

                ml_data_logger.update_label(
                    signal_id=signal_id,
                    close_reason=close_reason,
                    profit_pct=round(profit_pct * 100, 2),
                    tp1_hit=tp1_hit
                )

                try:
                    import ml_prediction_logger
                    ml_prediction_logger.update_real_trade_outcome(
                        symbol=symbol,
                        close_reason=close_reason,
                        profit_pct=round(profit_pct * 100, 2),
                        tp1_hit=tp1_hit
                    )
                except Exception as e:
                    print(f"ML Predictions guncelleme hatasi: {e}")

                print(f"Trade kapatildi: {symbol} ({trade_id}) -> {close_reason} ({profit_pct*100:+.2f}%)")
                return True

    return False


def check_trade_status(symbol, trade, current_price):
    """
    Tek bir trade objesi icin fiyat kontrolu yapar.
    Donus: (event_type, profit_pct, is_closed)
    Event Type: 'TP1', 'TP2', 'SL' veya None
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
        trade["tp1_hit"] = True
        trade["sl"] = entry
        trades = load_trades()
        trade_list = trades.get(symbol, [])
        for t in trade_list:
            if t.get("trade_id") == trade.get("trade_id"):
                t["tp1_hit"] = True
                t["sl"] = entry
                break
        save_trades(trades)

    if is_closed:
        close_trade_by_id(trade["trade_id"], event_type, close_price, profit_pct)

    return event_type, profit_pct, is_closed


def update_trade_sl(trade_id, new_sl, new_sl_order_id=None):
    """Belirli trade'in SL fiyatini ve order ID'sini gunceller (TP1 sonrasi BE icin)."""
    trades = load_trades()
    for symbol, trade_list in trades.items():
        for trade in trade_list:
            if trade.get("trade_id") == trade_id:
                trade["sl"] = new_sl
                if new_sl_order_id is not None:
                    trade["sl_order_id"] = str(new_sl_order_id)
                save_trades(trades)
                return True
    return False
