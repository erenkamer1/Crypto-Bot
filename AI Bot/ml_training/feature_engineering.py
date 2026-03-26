"""
Feature engineering — AI Bot 4
Prepare JSONL training data for the classifier.

Merged bot1 + optional AI1/AI2/AI3 prediction sources; dedup by signal id.
"""

import json
import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
import os
import hashlib

LABEL_MAP = {
    'full_win': 2,
    'breakeven': 1,
    'loss': 0
}

BINARY_LABEL_MAP = {
    'full_win': 1,
    'breakeven': 1,
    'loss': 0
}

# Outcome strings from ml_predictions.jsonl -> training labels (accepted + rejected)
OUTCOME_TO_LABEL = {
    'would_win': 'full_win',
    'tp1_then_tp2': 'full_win',
    'full_win': 'full_win',
    'win': 'full_win',
    'breakeven': 'breakeven',
    'tp1_then_sl': 'breakeven',
    'would_lose': 'loss',
    'loss': 'loss',
}

SOURCE_WEIGHTS = {
    'real_trade': 1.0,
    'shadow_correct': 1.5,
    'shadow_wrong': 2.0,
    'shadow_other': 1.5,
}


def _load_jsonl(filepath):
    """Load JSON lines from a file."""
    data = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    data.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return data


def prediction_record_to_training_record(pred):
    """
    Map one ml_predictions.jsonl row to ml_training_data.jsonl-style record.
    Only rows with known outcome are used. Feature dict must match get_feature_columns().
    Sets _source_type for sample weights (shadow_wrong, shadow_correct, shadow_other, real_trade).
    """
    outcome = pred.get('outcome')
    if outcome is None:
        return None
    label = OUTCOME_TO_LABEL.get(outcome)
    if label is None:
        return None
    features = pred.get('features') or {}
    trade_setup = pred.get('trade_setup') or {}
    entry = pred.get('entry_price') or 0
    sl = trade_setup.get('sl', 0)
    tp1 = trade_setup.get('tp1', 0)
    tp2 = trade_setup.get('tp2', 0)
    # Numeric technical fields (non-ctx_*)
    technical = {k: v for k, v in features.items() if not k.startswith('ctx_') and isinstance(v, (int, float)) and not pd.isna(v)}
    # Strip ctx_ prefix into nested context dict
    context = {}
    for k, v in features.items():
        if not k.startswith('ctx_'):
            continue
        key = k.replace('ctx_', '')
        if key == 'btc_trend_down':
            context['btc_trend'] = 'down' if v == 1 else 'up'
        elif key == 'regime_trending':
            context['market_regime'] = 'trending' if v == 1 else 'ranging'
        elif key in ('hour', 'day_of_week', 'is_weekend', 'btc_rsi', 'btc_change_24h', 'market_regime_score'):
            context[key] = v
    if 'btc_trend' not in context:
        context['btc_trend'] = 'down' if context.get('btc_rsi', 50) < 50 else 'up'
    if 'market_regime' not in context:
        context['market_regime'] = 'trending' if context.get('market_regime_score', 0.5) > 0.5 else 'ranging'
    trade = {'entry_price': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2}
    
    accepted = pred.get('accepted', True)
    if not accepted:
        if outcome in ('would_win', 'tp1_then_tp2'):
            source_type = 'shadow_wrong'     # false negative: would have won
        elif outcome == 'would_lose':
            source_type = 'shadow_correct'   # true negative: would have lost
        else:
            source_type = 'shadow_other'
    else:
        source_type = 'real_trade'
    
    return {
        'signal_id': pred.get('signal_id') or f"pred_{pred.get('timestamp', '')}_{pred.get('symbol', '')}".replace(' ', '_'),
        'timestamp': pred.get('timestamp', ''),
        'symbol': pred.get('symbol', ''),
        'symbol_category': 'alt',
        'signal_type': pred.get('signal_type', 'LONG'),
        'timeframe': pred.get('timeframe', '4h'),
        'technical': technical,
        'context': context,
        'trade': trade,
        'label': label,
        'close_reason': pred.get('close_reason', ''),
        'profit_pct': pred.get('profit_pct') if pred.get('profit_pct') is not None else (1.5 if label == 'full_win' else (0.0 if label == 'breakeven' else -4.0)),
        'final_rr': 0.75 if label == 'full_win' else (0 if label == 'breakeven' else -1.0),
        'duration_minutes': pred.get('duration_minutes') or 0,
        '_source_type': source_type,
    }


# --- True Stacking: Meta confidence feature isimleri ---
META_CONF_COLUMNS = ['meta_ai1_conf', 'meta_ai2_conf', 'meta_ai3_conf']


def _normalize_ts_for_key(ts_str):
    """Build lookup key from timestamp (minute precision)."""
    if not ts_str or not isinstance(ts_str, str):
        return ''
    # e.g. 2026-02-11T20:55:37... -> 2026-02-11T20:55
    if 'T' in ts_str and len(ts_str) >= 16:
        return ts_str[:16]
    return str(ts_str)[:16]


def _build_meta_confidence_lookup(prediction_paths):
    """
    Build (symbol, ts_key, signal_type) -> {meta_ai1_conf, meta_ai2_conf, meta_ai3_conf} from prediction JSONLs.

    Args:
        prediction_paths: [AI1 path, AI2 path, AI3 path] in order
    """
    lookup = {}
    for idx, pred_path in enumerate(prediction_paths):
        path = pred_path if os.path.isabs(pred_path) else os.path.normpath(pred_path)
        if not os.path.exists(path):
            continue
        col_name = META_CONF_COLUMNS[idx] if idx < len(META_CONF_COLUMNS) else f'meta_ai{idx+1}_conf'
        preds = _load_jsonl(path)
        for p in preds:
            conf = p.get('confidence')
            if conf is None:
                continue
            symbol = p.get('symbol', '')
            ts = p.get('timestamp', '')
            sig = p.get('signal_type', 'LONG')
            key = (symbol, _normalize_ts_for_key(ts), sig)
            if key not in lookup:
                lookup[key] = {c: np.nan for c in META_CONF_COLUMNS}
            lookup[key][col_name] = float(conf)
    return lookup


def _enrich_record_with_meta(record, lookup):
    """Attach meta confidence columns from lookup to record."""
    symbol = record.get('symbol', '')
    ts = record.get('timestamp', '')
    sig = record.get('signal_type', 'LONG')
    key = (symbol, _normalize_ts_for_key(ts), sig)
    meta = lookup.get(key, {})
    for col in META_CONF_COLUMNS:
        val = meta.get(col, np.nan)
        record[col] = val


def _record_identity(record):
    """Dedup key: signal_id if present else hash of symbol|timestamp|signal_type|label."""
    signal_id = record.get('signal_id')
    if signal_id:
        return f"id:{signal_id}"
    raw = "|".join([
        str(record.get('symbol', '')),
        str(record.get('timestamp', '')),
        str(record.get('signal_type', '')),
        str(record.get('label', '')),
    ])
    return f"hash:{hashlib.md5(raw.encode('utf-8')).hexdigest()}"


def load_training_data(
    filepath='ml_training_data.jsonl',
    predictions_path=None,
    extra_training_paths=None,
    extra_predictions_paths=None
):
    """
    Load merged training rows: bot1-style JSONL + optional prediction JSONLs + meta stacking.

    Args:
        filepath: Primary training file (e.g. bot1/ml_training_data.jsonl)
        predictions_path: First ml_predictions.jsonl
        extra_training_paths: Additional training JSONLs
        extra_predictions_paths: Extra ml_predictions files

    Returns:
        List of records (deduped).
    """
    data = []
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # 1) Primary training file
    if not os.path.isabs(filepath):
        candidate = os.path.join(base_dir, filepath)
        if os.path.exists(candidate):
            filepath = candidate
    if not os.path.exists(filepath):
        filepath = os.path.join(base_dir, 'ml_training_data.jsonl')
    if os.path.exists(filepath):
        raw = _load_jsonl(filepath)
        for r in raw:
            if '_source_type' not in r:
                r['_source_type'] = 'real_trade'
        data = raw
        print(f"Loaded {len(data)} rows ({os.path.basename(filepath)}).")

    # 2) Extra training files
    for extra in (extra_training_paths or []):
        path = extra if os.path.isabs(extra) else os.path.normpath(os.path.join(base_dir, extra))
        if os.path.exists(path):
            extra_data = _load_jsonl(path)
            for r in extra_data:
                if '_source_type' not in r:
                    r['_source_type'] = 'real_trade'
            data.extend(extra_data)
            print(f"+{len(extra_data)} rows ({os.path.basename(path)}).")

    # 3) Append converted rows from all ml_predictions sources
    prediction_paths = []
    if predictions_path:
        prediction_paths.append(predictions_path)
    if extra_predictions_paths:
        prediction_paths.extend(extra_predictions_paths)
    if not prediction_paths:
        prediction_paths = [os.path.join(base_dir, 'ml_predictions.jsonl')]

    # 3b) True Stacking: Meta confidence lookup (AI1, AI2, AI3 confidence -> meta_ai1/2/3_conf)
    meta_lookup = _build_meta_confidence_lookup(prediction_paths)
    if meta_lookup:
        print(f"   Meta lookup: {len(meta_lookup)} keys for AI1/2/3 confidence")

    total_converted = 0
    shadow_stats_total = {'shadow_wrong': 0, 'shadow_correct': 0, 'shadow_other': 0, 'real_trade': 0}
    for pred_path in prediction_paths:
        path = pred_path if os.path.isabs(pred_path) else os.path.normpath(os.path.join(base_dir, pred_path))
        if not os.path.exists(path):
            continue
        preds = _load_jsonl(path)
        converted = 0
        shadow_stats = {'shadow_wrong': 0, 'shadow_correct': 0, 'shadow_other': 0, 'real_trade': 0}
        for p in preds:
            rec = prediction_record_to_training_record(p)
            if rec is None:
                continue
            data.append(rec)
            converted += 1
            src = rec.get('_source_type', 'real_trade')
            if src in shadow_stats:
                shadow_stats[src] += 1
        if converted:
            total_converted += converted
            for k in shadow_stats_total:
                shadow_stats_total[k] += shadow_stats[k]
            print(f"+{converted} rows ({os.path.basename(path)}).")

    if total_converted:
        print(f"   Shadow totals: wrong_reject={shadow_stats_total['shadow_wrong']}, "
              f"correct_reject={shadow_stats_total['shadow_correct']}, "
              f"other={shadow_stats_total['shadow_other']}, "
              f"real={shadow_stats_total['real_trade']}")

    # 4) Dedup
    if data:
        deduped = []
        seen = set()
        for rec in data:
            key = _record_identity(rec)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(rec)
        dropped = len(data) - len(deduped)
        data = deduped
        if dropped > 0:
            print(f"Dedup: removed {dropped} duplicate rows.")

    # 5) True Stacking: Her kayda meta confidence ekle
    if data and meta_lookup:
        for rec in data:
            _enrich_record_with_meta(rec, meta_lookup)
        matched = sum(1 for r in data if any(r.get(c) is not None and not (isinstance(r.get(c), float) and np.isnan(r.get(c))) for c in META_CONF_COLUMNS))
        print(f"   Meta enrichment: {matched}/{len(data)} rows matched")

    if not data:
        print("Warning: no training rows loaded.")
    return data


def flatten_record(record):
    """
    Flatten nested record to one dict for DataFrame rows.
    e.g. {'technical': {'rsi_14': 30}} -> {'rsi_14': 30}
    """
    flat = {}

    flat['signal_id'] = record.get('signal_id', '')
    flat['timestamp'] = record.get('timestamp', '')
    flat['symbol'] = record.get('symbol', '')
    flat['symbol_category'] = record.get('symbol_category', 'alt')
    flat['signal_type'] = record.get('signal_type', '')
    flat['timeframe'] = record.get('timeframe', '4h')
    flat['label'] = record.get('label', '')
    flat['profit_pct'] = record.get('profit_pct', 0)
    flat['final_rr'] = record.get('final_rr', 0)
    flat['duration_minutes'] = record.get('duration_minutes', 0)
    flat['_source_type'] = record.get('_source_type', 'real_trade')

    # True Stacking: Meta confidence features (AI1, AI2, AI3)
    for col in META_CONF_COLUMNS:
        val = record.get(col)
        if val is not None and isinstance(val, (int, float)) and not (isinstance(val, float) and np.isnan(val)):
            flat[col] = float(val)

    # Technical features
    technical = record.get('technical', {})
    for key, value in technical.items():
        if isinstance(value, (int, float)) and not pd.isna(value):
            flat[key] = value
    
    # Context features
    context = record.get('context', {})
    for key, value in context.items():
        if isinstance(value, (int, float, bool)):
            flat[f'ctx_{key}'] = value if not isinstance(value, bool) else int(value)
        elif key == 'btc_trend':
            flat['ctx_btc_trend_down'] = 1 if value == 'down' else 0
        elif key == 'market_regime':
            flat['ctx_regime_trending'] = 1 if value == 'trending' else 0
    
    # Trade features
    trade = record.get('trade', {})
    entry_price = trade.get('entry_price', 0)
    sl = trade.get('sl', 0)
    tp1 = trade.get('tp1', 0)
    tp2 = trade.get('tp2', 0)
    
    if entry_price > 0:
        flat['sl_distance_pct'] = abs(entry_price - sl) / entry_price * 100
        flat['tp1_distance_pct'] = abs(tp1 - entry_price) / entry_price * 100
        flat['tp2_distance_pct'] = abs(tp2 - entry_price) / entry_price * 100
        flat['risk_reward_ratio'] = flat['tp1_distance_pct'] / flat['sl_distance_pct'] if flat['sl_distance_pct'] > 0 else 0
    
    return flat


def get_feature_columns():
    """Ordered list of feature column names for training/inference."""
    return [
        # Technical indicators
        'rsi_14', 'rsi_21', 'macd_histogram', 
        'ema_20_50_diff', 'ema_50_200_diff', 'price_vs_ema_200',
        'entry_distance_to_ema20_pct', 'entry_distance_to_ema50_pct',
        'entry_vs_candle_high_pct', 'entry_vs_candle_low_pct',
        'volume_zscore', 'atr_pct', 'atr_zscore', 'bb_width_pct',
        'wt_1', 'wt_2', 'adx',
        
        # Context features
        'ctx_hour', 'ctx_day_of_week', 'ctx_is_weekend',
        'ctx_btc_rsi', 'ctx_btc_change_24h', 'ctx_btc_trend_down',
        'ctx_regime_trending', 'ctx_market_regime_score',
        
        # Trade setup
        'sl_distance_pct', 'tp1_distance_pct', 'risk_reward_ratio',

        # True Stacking: AI Bot 1/2/3 confidence meta-features
        'meta_ai1_conf', 'meta_ai2_conf', 'meta_ai3_conf',
    ]


def compute_sample_weights(df):
    """
    Per-row sample_weight from _source_type (shadow_wrong weighted highest).

    Args:
        df: DataFrame with _source_type column

    Returns:
        weights: 1d numpy array
    """
    weights = np.ones(len(df))
    
    for i, src in enumerate(df['_source_type'].values):
        weights[i] = SOURCE_WEIGHTS.get(src, 1.0)
    
    unique_sources = df['_source_type'].value_counts()
    print(f"\nSample weights:")
    for src, count in unique_sources.items():
        w = SOURCE_WEIGHTS.get(src, 1.0)
        print(f"   {src}: {count} rows x {w}")
    print(f"   Sum of weights: {weights.sum():.0f} (rows: {len(weights)})")
    
    return weights


def prepare_features(data, use_binary_labels=True):
    """
    Build X, y and feature name list from raw records.

    Args:
        data: list of dicts from JSONL
        use_binary_labels: True = binary win/loss, False = 3-class

    Returns:
        X, y, feature_names, df (includes timestamp, _source_type)
    """
    # Flatten all records
    flat_data = [flatten_record(r) for r in data]
    df = pd.DataFrame(flat_data)

    # Add missing meta columns as NaN
    for col in META_CONF_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan

    # Label encoding
    label_map = BINARY_LABEL_MAP if use_binary_labels else LABEL_MAP
    df['label_encoded'] = df['label'].map(label_map)
    
    # Drop rows with missing labels
    df = df.dropna(subset=['label_encoded'])
    
    if 'timestamp' in df.columns:
        df['_ts_parsed'] = pd.to_datetime(df['timestamp'], errors='coerce')
        df = df.sort_values('_ts_parsed').reset_index(drop=True)
        valid_ts = df['_ts_parsed'].notna().sum()
        print(f"Chronological sort: {valid_ts}/{len(df)} rows have parseable timestamps.")
    
    # Get feature columns
    feature_cols = get_feature_columns()
    available_cols = [c for c in feature_cols if c in df.columns]
    
    print(f"Available features: {len(available_cols)}/{len(feature_cols)}")

    # Impute: median; meta columns fallback to 0.5 if all-NaN
    X = df[available_cols].copy()
    for col in X.columns:
        if X[col].isna().any():
            med = X[col].median()
            fill_val = 0.5 if (col in META_CONF_COLUMNS and (pd.isna(med) or np.isnan(med))) else med
            X[col] = X[col].fillna(fill_val)
    
    y = df['label_encoded'].values
    
    print(f"Label distribution:")
    for label_name, label_val in label_map.items():
        count = (y == label_val).sum()
        pct = count / len(y) * 100
        print(f"   {label_name}: {count} ({pct:.1f}%)")
    
    return X.values, y, available_cols, df


def create_train_test_split(X, y, df=None, test_size=0.2, use_chronological=True):
    """
    Chronological split (last test_size fraction as test) to reduce look-ahead bias.

    Args:
        X, y: arrays
        df: optional, for printing time ranges (_ts_parsed)
        test_size: fraction for test set (default 20%)
        use_chronological: if False, stratified random split

    Returns:
        X_train, X_test, y_train, y_test
    """
    if use_chronological:
        split_idx = int(len(X) * (1 - test_size))
        X_train = X[:split_idx]
        X_test = X[split_idx:]
        y_train = y[:split_idx]
        y_test = y[split_idx:]
        
        print(f"\nSplit (chronological):")
        print(f"   Train: {len(X_train)} rows (first {int((1-test_size)*100)}%)")
        print(f"   Test:  {len(X_test)} rows (last {int(test_size*100)}%)")

        if df is not None and '_ts_parsed' in df.columns:
            ts = df['_ts_parsed']
            train_ts = ts.iloc[:split_idx]
            test_ts = ts.iloc[split_idx:]
            if train_ts.notna().any() and test_ts.notna().any():
                print(f"   Train time range: {train_ts.min()} -> {train_ts.max()}")
                print(f"   Test time range:  {test_ts.min()} -> {test_ts.max()}")
    else:
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=42, stratify=y
        )
        print(f"\nSplit (random stratified):")
        print(f"   Train: {len(X_train)} rows")
        print(f"   Test:  {len(X_test)} rows")

    train_pos = y_train.mean() * 100
    test_pos = y_test.mean() * 100
    print(f"   Train positive rate: {train_pos:.1f}%")
    print(f"   Test positive rate:  {test_pos:.1f}%")
    
    return X_train, X_test, y_train, y_test


def scale_features(X_train, X_test):
    """StandardScaler fit on train, transform both."""
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    return X_train_scaled, X_test_scaled, scaler


if __name__ == '__main__':
    print("Feature engineering self-test\n")
    
    data = load_training_data()
    X, y, feature_names, df = prepare_features(data)
    
    weights = compute_sample_weights(df)

    X_train, X_test, y_train, y_test = create_train_test_split(X, y, df=df, use_chronological=True)
    
    print(f"\nFeature matrix shape: {X.shape}")
    print(f"Feature names (first 5): {feature_names[:5]}...")
