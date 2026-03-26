"""
ML training data logger — append full feature rows to JSONL per signal.
"""

import json
import os
from datetime import datetime, timezone
import pandas as pd
import numpy as np
import path_utils

_BASE_DIR = path_utils.get_base_dir()
ML_DATA_FILE = os.path.join(_BASE_DIR, "ml_training_data.jsonl")
STRATEGY_VERSION = "wavetrend_divergence_v1"
FEATURE_VERSION = "1.0"


def json_serializer(obj):
    """Serialize numpy/pandas types for JSON."""
    if isinstance(obj, (np.integer, np.floating)):
        return float(obj) if isinstance(obj, np.floating) else int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

# Symbol kategorileri
SYMBOL_CATEGORIES = {
    'major': ['BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 'XRP/USDT'],
    'meme': ['DOGE/USDT', 'SHIB/USDT', 'PEPE/USDT', 'WIF/USDT', 'FLOKI/USDT', 'BONK/USDT', 'BOME/USDT', 'MEME/USDT', 'TURBO/USDT'],
    'low_liquidity': ['AI/USDT', 'LOOM/USDT', 'SCRT/USDT']
}


def get_symbol_category(symbol):
    """Return symbol bucket (major/meme/alt)."""
    for category, symbols in SYMBOL_CATEGORIES.items():
        if symbol in symbols:
            return category
    return 'alt'


def get_session(timestamp=None):
    """UTC session bucket: Asia / EU / US."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    elif isinstance(timestamp, str):
        timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    
    hour = timestamp.hour
    if 0 <= hour < 8:
        return 'Asia'
    elif 8 <= hour < 16:
        return 'EU'
    else:
        return 'US'


def calculate_market_regime(df):
    """Regime name and score from ADX/ATR/EMA slope."""
    if len(df) < 30:
        return 'unknown', 0.5
    
    last = df.iloc[-1]
    
    # ADX bazlı trend gücü
    adx = last.get('ADX', 25)
    
    # ATR bazlı volatilite (son 14 günün ortalamasına göre)
    atr_pct = last.get('ATR', 0) / last['close'] * 100 if last['close'] > 0 else 0
    avg_atr_pct = df['ATR'].iloc[-14:].mean() / df['close'].iloc[-14:].mean() * 100 if len(df) >= 14 else atr_pct
    
    # EMA slope (trend yönü)
    ema_20 = last.get('EMA_20', last['close'])
    ema_20_prev = df['EMA_20'].iloc[-5] if 'EMA_20' in df.columns and len(df) >= 5 else ema_20
    ema_slope = (ema_20 - ema_20_prev) / ema_20_prev * 100 if ema_20_prev > 0 else 0
    
    # Regime scoring (0-1 arası)
    # 0 = ranging/low_vol, 1 = trending/high_vol
    trend_score = min(adx / 50, 1.0)  # ADX 50'de max
    vol_score = min(atr_pct / avg_atr_pct, 2.0) / 2 if avg_atr_pct > 0 else 0.5
    
    regime_score = (trend_score * 0.6 + vol_score * 0.4)
    
    # Regime name
    if adx > 30:
        regime = 'trending'
    elif adx < 20:
        if vol_score > 0.7:
            regime = 'high_vol'
        else:
            regime = 'ranging'
    else:
        if vol_score < 0.3:
            regime = 'low_vol'
        else:
            regime = 'ranging'
    
    return regime, round(regime_score, 3)


def calculate_volume_zscore(df, window=20):
    """Volume z-score hesaplar."""
    if len(df) < window:
        return 0, False
    
    volumes = df['volume'].iloc[-window:]
    mean_vol = volumes.mean()
    std_vol = volumes.std()
    
    if std_vol == 0:
        return 0, False
    
    current_vol = df['volume'].iloc[-1]
    zscore = (current_vol - mean_vol) / std_vol
    spike = bool(zscore > 2.0)  # numpy.bool_ -> Python bool
    
    return round(float(zscore), 3), spike


def get_rolling_features(df, col_name, lookback=2):
    """Belirtilen sütun için rolling (önceki) değerleri döndürür."""
    result = {}
    for i in range(1, lookback + 1):
        idx = -(i + 1)
        if len(df) > abs(idx) and col_name in df.columns:
            result[f'{col_name}_prev_{i}'] = round(float(df[col_name].iloc[idx]), 4)
        else:
            result[f'{col_name}_prev_{i}'] = None
    return result


def get_entry_candle_position(entry_price, candle_high, candle_low):
    """Entry fiyatının candle içindeki pozisyonunu hesaplar."""
    candle_range = candle_high - candle_low
    if candle_range == 0:
        return 0, 0
    
    high_pct = round((candle_high - entry_price) / candle_range * 100, 2)
    low_pct = round((entry_price - candle_low) / candle_range * 100, 2)
    
    return high_pct, low_pct


def calculate_bb_width_pct(df):
    """Bollinger Band width yüzdesi hesaplar."""
    if 'BB_UPPER' not in df.columns or 'BB_LOWER' not in df.columns:
        return None
    
    last = df.iloc[-1]
    bb_width = last['BB_UPPER'] - last['BB_LOWER']
    bb_middle = last.get('BB_MIDDLE', last['close'])
    
    if bb_middle == 0:
        return None
    
    return round(bb_width / bb_middle * 100, 3)


def calculate_atr_zscore(df, window=14):
    """ATR z-score hesaplar (volatility compression tespiti için)."""
    if 'ATR' not in df.columns or len(df) < window * 2:
        return None
    
    atrs = df['ATR'].iloc[-window * 2:-1]
    current_atr = df['ATR'].iloc[-1]
    
    mean_atr = atrs.mean()
    std_atr = atrs.std()
    
    if std_atr == 0:
        return 0
    
    return round((current_atr - mean_atr) / std_atr, 3)


def collect_technical_features(df, entry_price):
    """Tüm teknik feature'ları toplar."""
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else last
    
    # Volume z-score
    vol_zscore, vol_spike = calculate_volume_zscore(df)
    
    # Entry candle position
    entry_vs_high, entry_vs_low = get_entry_candle_position(
        entry_price, last['high'], last['low']
    )
    
    features = {
        # RSI
        'rsi_14': round(float(last.get('RSI', 50)), 2),
        'rsi_21': round(float(last.get('RSI_21', 50)), 2),
        
        # MACD (precision artırıldı - floating point loss önleme)
        'macd': round(float(last.get('MACD', 0)), 6),
        'macd_signal': round(float(last.get('MACD_SIGNAL', 0)), 6),
        'macd_histogram': round(float(last.get('MACD_HIST', 0)), 6),
        
        # EMA
        'ema_20': round(float(last.get('EMA_20', last['close'])), 4),
        'ema_50': round(float(last.get('EMA_50', last['close'])), 4),
        'ema_200': round(float(last.get('EMA_200', last['close'])), 4),
        
        # EMA differences
        'ema_20_50_diff': round((last.get('EMA_20', last['close']) - last.get('EMA_50', last['close'])) / last.get('EMA_50', last['close']) * 100, 3) if last.get('EMA_50', 0) > 0 else 0,
        'ema_50_200_diff': round((last.get('EMA_50', last['close']) - last.get('EMA_200', last['close'])) / last.get('EMA_200', last['close']) * 100, 3) if last.get('EMA_200', 0) > 0 else 0,
        'price_vs_ema_200': round((last['close'] - last.get('EMA_200', last['close'])) / last.get('EMA_200', last['close']) * 100, 3) if last.get('EMA_200', 0) > 0 else 0,
        
        # Entry quality
        'entry_distance_to_ema20_pct': round((entry_price - last.get('EMA_20', entry_price)) / last.get('EMA_20', entry_price) * 100, 3) if last.get('EMA_20', 0) > 0 else 0,
        'entry_distance_to_ema50_pct': round((entry_price - last.get('EMA_50', entry_price)) / last.get('EMA_50', entry_price) * 100, 3) if last.get('EMA_50', 0) > 0 else 0,
        'entry_vs_candle_high_pct': entry_vs_high,
        'entry_vs_candle_low_pct': entry_vs_low,
        
        # Volume
        'volume_zscore': vol_zscore,
        'volume_spike': vol_spike,
        
        # Volatility
        'atr': round(float(last.get('ATR', 0)), 4),
        'atr_pct': round(float(last.get('ATR', 0)) / last['close'] * 100, 3) if last['close'] > 0 else 0,
        'atr_valid': bool(last.get('ATR', 0) > 0),  # ATR validation - ML için önemli
        'atr_zscore': calculate_atr_zscore(df),
        'bb_width_pct': calculate_bb_width_pct(df),
        
        # WaveTrend
        'wt_1': round(float(last.get('WT_1', 0)), 2),
        'wt_2': round(float(last.get('WT_2', 0)), 2),
        
        # ADX
        'adx': round(float(last.get('ADX', 25)), 2),
    }
    
    # Rolling features (standardize naming: rsi_14_prev_X formatı)
    for i in range(1, 3):
        idx = -(i + 1)
        if len(df) > abs(idx) and 'RSI' in df.columns:
            features[f'rsi_14_prev_{i}'] = round(float(df['RSI'].iloc[idx]), 4)
        else:
            features[f'rsi_14_prev_{i}'] = None
    
    features.update(get_rolling_features(df, 'MACD_HIST', 1))
    features.update(get_rolling_features(df, 'volume', 1))
    
    return features


def collect_context_features(btc_df=None):
    """BTC ve piyasa context feature'larını toplar."""
    now = datetime.now(timezone.utc)
    
    context = {
        'session': get_session(now),
        'hour': now.hour,
        'day_of_week': now.weekday(),
        'is_weekend': bool(now.weekday() >= 5),  # Python bool
    }
    
    if btc_df is not None and len(btc_df) > 0:
        last = btc_df.iloc[-1]
        prev_24h = btc_df.iloc[-6] if len(btc_df) >= 6 else last  # 4h candle, 6 tane = 24h
        
        # BTC price and RSI
        context['btc_price'] = round(float(last['close']), 2)
        context['btc_rsi'] = round(float(last.get('RSI', 50)), 2)
        
        # BTC 24h change
        if prev_24h['close'] > 0:
            context['btc_change_24h'] = round((last['close'] - prev_24h['close']) / prev_24h['close'] * 100, 2)
        else:
            context['btc_change_24h'] = 0
        
        # BTC trend (basit: son 5 candle EMA slope)
        if 'EMA_20' in btc_df.columns and len(btc_df) >= 5:
            ema_now = last.get('EMA_20', last['close'])
            ema_prev = btc_df['EMA_20'].iloc[-5]
            change = (ema_now - ema_prev) / ema_prev * 100 if ema_prev > 0 else 0
            
            if change > 1:
                context['btc_trend'] = 'up'
            elif change < -1:
                context['btc_trend'] = 'down'
            else:
                context['btc_trend'] = 'range'
        else:
            context['btc_trend'] = 'unknown'
        
        # Market regime
        regime, regime_score = calculate_market_regime(btc_df)
        context['market_regime'] = regime
        context['market_regime_score'] = regime_score
    else:
        context['btc_price'] = None
        context['btc_rsi'] = None
        context['btc_change_24h'] = None
        context['btc_trend'] = 'unknown'
        context['market_regime'] = 'unknown'
        context['market_regime_score'] = 0.5
    
    return context


def log_signal(signal_id, symbol, signal_type, df, entry_price, sl, tp1, tp2, 
               timeframe, btc_df=None, spread_pct=0.05):
    """
    Yeni sinyal için tüm feature'ları JSONL dosyasına kaydeder.
    """
    now = datetime.now(timezone.utc)
    last_candle = df.iloc[-1]
    
    # Candle close time (timestamp sütunundan)
    candle_close_time = last_candle['timestamp']
    if isinstance(candle_close_time, pd.Timestamp):
        candle_close_time = candle_close_time.isoformat()
    
    # Technical features
    technical = collect_technical_features(df, entry_price)
    
    # Context features
    context = collect_context_features(btc_df)
    
    # Data validation (assert'ler)
    assert candle_close_time is not None, "candle_close_time cannot be None"
    
    record = {
        # Identification
        'signal_id': signal_id,
        'timestamp': now.isoformat(),
        'candle_close_time': candle_close_time,
        'is_candle_closed': True,
        
        # Symbol info
        'symbol': symbol,
        'symbol_category': get_symbol_category(symbol),
        'signal_type': 'LONG' if 'LONG' in signal_type else 'SHORT',
        'timeframe': timeframe,
        
        # Features
        'technical': technical,
        'context': context,
        
        # Trade info
        'trade': {
            'entry_price': round(entry_price, 6),
            'sl': round(sl, 6),
            'tp1': round(tp1, 6),
            'tp2': round(tp2, 6),
        },
        
        # Execution
        'execution': {
            'spread_pct': spread_pct,
            'order_type': 'market',
        },
        
        # Label (trade kapanınca güncellenecek)
        'label': None,
        'close_reason': None,
        'profit_pct': None,
        'final_rr': None,
        'duration_minutes': None,
        
        # Meta
        'meta': {
            'strategy_version': STRATEGY_VERSION,
            'feature_version': FEATURE_VERSION,
        }
    }
    
    # JSONL'e append et
    with open(ML_DATA_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False, default=json_serializer) + '\n')
    
    print(f"[ML] Signal saved: {signal_id}")
    return record


def update_label(signal_id, close_reason, profit_pct, tp1_hit=False):
    """
    Trade kapandığında label ve sonuç bilgilerini günceller.
    
    Label mantığı:
    - full_win: TP2 hit
    - breakeven: TP1 hit + SL (SL entry'de)
    - loss: Direkt SL hit
    """
    if not os.path.exists(ML_DATA_FILE):
        print(f"[ML] Warning: {ML_DATA_FILE} not found")
        return
    
    # Validation
    assert profit_pct is not None, "profit_pct cannot be None when updating label"
    
    # Label belirleme
    if close_reason == 'TP2' or (close_reason == 'TP1' and profit_pct > 0):
        label = 'full_win'
    elif tp1_hit and close_reason == 'SL':
        label = 'breakeven'
    elif close_reason == 'SL':
        label = 'loss'
    else:
        label = 'partial_win'
    
    # Final RR hesapla (basit: profit / stop distance)
    # profit_pct / 4 (çünkü SL %4)
    final_rr = round(profit_pct / 4, 2) if profit_pct != 0 else 0
    
    # Dosyayı oku ve güncelle
    lines = []
    updated = False
    
    with open(ML_DATA_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            record = json.loads(line.strip())
            if record['signal_id'] == signal_id:
                # Süre hesapla
                start_time = datetime.fromisoformat(record['timestamp'].replace('Z', '+00:00'))
                duration = (datetime.now(timezone.utc) - start_time).total_seconds() / 60
                
                record['label'] = label
                record['close_reason'] = close_reason
                record['profit_pct'] = round(profit_pct, 2)
                record['final_rr'] = final_rr
                record['duration_minutes'] = round(duration, 1)
                updated = True
            lines.append(json.dumps(record, ensure_ascii=False, default=json_serializer))
    
    if updated:
        with open(ML_DATA_FILE, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
        print(f"[ML] Label updated: {signal_id} -> {label}")
    else:
        print(f"[ML] Warning: signal_id {signal_id} not found")
