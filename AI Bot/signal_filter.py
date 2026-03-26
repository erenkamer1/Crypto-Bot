"""
Signal filter: real-time ML scoring.

True stacking: optional AI1/AI2/AI3 confidence scores as meta-features.
"""

import sys
import os

# Avoid UnicodeEncodeError on Windows console with emoji in prints
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
import joblib
import json
import numpy as np
import pandas as pd
from datetime import datetime, timezone
import path_utils

META_CONF_COLUMNS = ['meta_ai1_conf', 'meta_ai2_conf', 'meta_ai3_conf']


class SignalFilter:
    """ML signal filter with optional true stacking."""

    def __init__(self, models_dir=None):
        self.model = None
        self.scaler = None
        self.feature_names = []
        # Bundled models (exe) or dev script dir
        if models_dir is None:
            self.models_dir = os.path.join(path_utils.get_resource_dir(), 'models')
        else:
            self.models_dir = models_dir
        self._loaded = False
        self._stack_models = []  # [(model, scaler, feature_names), ...]

    def _get_project_root(self):
        """Parent of app directory (for optional stack model paths)."""
        return os.path.dirname(path_utils.get_resource_dir())

    def _load_stack_models(self):
        """Load optional stack models from sibling project folders."""
        root = self._get_project_root()
        stack_paths = [
            os.path.join(root, 'AI Bot 1', 'models'),
            os.path.join(root, 'AI Bot v2', 'models'),
            os.path.join(root, 'AI Bot 3', 'models'),
        ]
        self._stack_models = []
        for p in stack_paths:
            try:
                model_p = os.path.join(p, 'signal_classifier.pkl')
                scaler_p = os.path.join(p, 'feature_scaler.pkl')
                meta_p = os.path.join(p, 'model_meta.json')
                if not os.path.exists(model_p) or not os.path.exists(scaler_p):
                    self._stack_models.append(None)
                    continue
                m = joblib.load(model_p)
                s = joblib.load(scaler_p)
                fn = []
                if os.path.exists(meta_p):
                    with open(meta_p, 'r') as f:
                        fn = json.load(f).get('feature_names', [])
                self._stack_models.append((m, s, fn))
            except Exception:
                self._stack_models.append(None)
        loaded = sum(1 for x in self._stack_models if x is not None)
        if loaded > 0:
            print(f"True stacking: {loaded}/3 sub-models loaded")

    def load_model(self):
        """Load main model/scaler and optional stack models."""
        if self._loaded:
            return True
            
        try:
            model_path = os.path.join(self.models_dir, 'signal_classifier.pkl')
            scaler_path = os.path.join(self.models_dir, 'feature_scaler.pkl')
            meta_path = os.path.join(self.models_dir, 'model_meta.json')
            
            if not os.path.exists(model_path):
                print(f"ML model not found: {model_path}")
                return False
            
            self.model = joblib.load(model_path)
            self.scaler = joblib.load(scaler_path)
            
            if os.path.exists(meta_path):
                with open(meta_path, 'r') as f:
                    meta = json.load(f)
                    self.feature_names = meta.get('feature_names', [])
            
            if any(c in self.feature_names for c in META_CONF_COLUMNS):
                self._load_stack_models()

            self._loaded = True
            print(f"ML model loaded: {len(self.feature_names)} features")
            return True

        except Exception as e:
            print(f"Model load error: {e}")
            return False

    def prepare_features(self, df, entry_price, btc_df=None, signal_type='LONG'):
        """Build feature dict for one signal."""
        current = df.iloc[-1]
        
        features = {}
        
        # Technical indicators (MACD_HIST column name from indicators.py)
        features['rsi_14'] = current.get('RSI', 50)
        features['rsi_21'] = current.get('RSI_21', 50) if 'RSI_21' in current else current.get('RSI', 50)
        features['macd_histogram'] = current.get('MACD_HIST', current.get('MACD_Hist', 0))
        
        # EMA features
        ema_20 = current.get('EMA_20', entry_price)
        ema_50 = current.get('EMA_50', entry_price)
        ema_200 = current.get('EMA_200', entry_price)
        
        features['ema_20_50_diff'] = (ema_20 - ema_50) / ema_50 * 100 if ema_50 > 0 else 0
        features['ema_50_200_diff'] = (ema_50 - ema_200) / ema_200 * 100 if ema_200 > 0 else 0
        features['price_vs_ema_200'] = (entry_price - ema_200) / ema_200 * 100 if ema_200 > 0 else 0
        features['entry_distance_to_ema20_pct'] = (entry_price - ema_20) / ema_20 * 100 if ema_20 > 0 else 0
        features['entry_distance_to_ema50_pct'] = (entry_price - ema_50) / ema_50 * 100 if ema_50 > 0 else 0
        
        # Candle position
        candle_high = current.get('high', entry_price)
        candle_low = current.get('low', entry_price)
        candle_range = candle_high - candle_low
        
        if candle_range > 0:
            features['entry_vs_candle_high_pct'] = (candle_high - entry_price) / candle_range * 100
            features['entry_vs_candle_low_pct'] = (entry_price - candle_low) / candle_range * 100
        else:
            features['entry_vs_candle_high_pct'] = 50
            features['entry_vs_candle_low_pct'] = 50
        
        # Volume & Volatility
        features['volume_zscore'] = self._calc_volume_zscore(df)
        features['atr_pct'] = current.get('ATR', 0) / entry_price * 100 if entry_price > 0 else 0
        features['atr_zscore'] = self._calc_atr_zscore(df)
        features['bb_width_pct'] = current.get('BB_Width_Pct', 10)
        
        # WaveTrend
        features['wt_1'] = current.get('WT_1', 0)
        features['wt_2'] = current.get('WT_2', 0)
        
        # ADX
        features['adx'] = current.get('ADX', 25)
        
        # Context features
        now = datetime.now(timezone.utc)
        features['ctx_hour'] = now.hour
        features['ctx_day_of_week'] = now.weekday()
        features['ctx_is_weekend'] = 1 if now.weekday() >= 5 else 0
        
        # BTC context
        if btc_df is not None and len(btc_df) > 0:
            btc_current = btc_df.iloc[-1]
            features['ctx_btc_rsi'] = btc_current.get('RSI', 50)
            
            if len(btc_df) >= 24:
                btc_prev = btc_df.iloc[-24]['close']
                features['ctx_btc_change_24h'] = (btc_current['close'] - btc_prev) / btc_prev * 100
            else:
                features['ctx_btc_change_24h'] = 0
            
            features['ctx_btc_trend_down'] = 1 if btc_current.get('RSI', 50) < 40 else 0
        else:
            features['ctx_btc_rsi'] = 50
            features['ctx_btc_change_24h'] = 0
            features['ctx_btc_trend_down'] = 0
        
        # Market regime
        features['ctx_regime_trending'] = 1 if features['adx'] > 25 else 0
        features['ctx_market_regime_score'] = min(features['adx'] / 50, 1.0)
        
        # Trade setup
        sl_pct = 0.04
        tp1_pct = 0.015
        features['sl_distance_pct'] = sl_pct * 100
        features['tp1_distance_pct'] = tp1_pct * 100
        features['risk_reward_ratio'] = tp1_pct / sl_pct if sl_pct > 0 else 0
        
        return features
    
    def _calc_volume_zscore(self, df, window=20):
        if len(df) < window:
            return 0
        volumes = df['volume'].tail(window)
        mean = volumes.mean()
        std = volumes.std()
        if std > 0:
            return (df.iloc[-1]['volume'] - mean) / std
        return 0
    
    def _calc_atr_zscore(self, df, window=14):
        if 'ATR' not in df.columns or len(df) < window:
            return 0
        atrs = df['ATR'].tail(window)
        mean = atrs.mean()
        std = atrs.std()
        if std > 0:
            return (df.iloc[-1]['ATR'] - mean) / std
        return 0
    
    def _get_stack_confidence(self, features, stack_idx):
        """Confidence from stack model; 0.5 on failure."""
        if not self._stack_models or stack_idx >= len(self._stack_models):
            return 0.5
        entry = self._stack_models[stack_idx]
        if entry is None:
            return 0.5
        model, scaler, fn = entry
        vec = []
        for name in fn:
            v = features.get(name, 0)
            if pd.isna(v):
                v = 0
            vec.append(float(v))
        try:
            X = np.array(vec).reshape(1, -1)
            X_scaled = scaler.transform(X)
            return float(model.predict_proba(X_scaled)[0][1])
        except Exception:
            return 0.5

    def predict_proba(self, features):
        if not self._loaded:
            self.load_model()
        
        if self.model is None:
            return 0.5

        # Meta features: fill AI1/2/3 confidence from stack models
        feats = dict(features)
        if any(c in self.feature_names for c in META_CONF_COLUMNS):
            for i, col in enumerate(META_CONF_COLUMNS):
                if col in self.feature_names:
                    feats[col] = self._get_stack_confidence(features, i)

        feature_vector = []
        for name in self.feature_names:
            value = feats.get(name, 0)
            if pd.isna(value):
                value = 0
            feature_vector.append(value)
        
        X = np.array(feature_vector).reshape(1, -1)
        X_scaled = self.scaler.transform(X)
        proba = self.model.predict_proba(X_scaled)[0][1]
        return float(proba)
    
    def should_take_signal(self, df, entry_price, btc_df=None, 
                           signal_type='LONG', threshold=0.65):
        features = self.prepare_features(df, entry_price, btc_df, signal_type)
        confidence = self.predict_proba(features)
        return confidence >= threshold, confidence


_signal_filter = None

def get_filter():
    global _signal_filter
    if _signal_filter is None:
        _signal_filter = SignalFilter()
    return _signal_filter

def get_confidence(signal_type, df, entry_price=None, btc_df=None):
    filter_instance = get_filter()
    if entry_price is None:
        entry_price = df.iloc[-1]['close']
    features = filter_instance.prepare_features(df, entry_price, btc_df, signal_type)
    return filter_instance.predict_proba(features)
