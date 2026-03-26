import pandas as pd
import ta
import config

def calculate_wavetrend(df):
    """
    WaveTrend (LazyBear-style).
    Manual implementation — not in `ta` as a single indicator.
    """
    n1 = config.WT_CHANNEL_LEN
    n2 = config.WT_AVERAGE_LEN
    
    def ema(series, length):
        return series.ewm(span=length, adjust=False).mean()

    def sma(series, length):
        return series.rolling(window=length).mean()

    ap = (df['high'] + df['low'] + df['close']) / 3
    esa = ema(ap, n1)
    d = ema((ap - esa).abs(), n1)
    
    d = d.replace(0, 0.000001)
    
    ci = (ap - esa) / (0.015 * d)
    tci = ema(ci, n2)
    
    df['WT_1'] = tci
    df['WT_2'] = sma(tci, 4)
    return df

def calculate_adx(df):
    """
    Average Directional Index
    """
    adx_indicator = ta.trend.ADXIndicator(high=df['high'], low=df['low'], close=df['close'], window=14)
    df['ADX'] = adx_indicator.adx()
    return df

def calculate_atr(df):
    """
    Average True Range
    """
    atr_indicator = ta.volatility.AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14)
    df['ATR'] = atr_indicator.average_true_range()
    return df

def calculate_rsi(df):
    """RSI 14 and 21."""
    rsi_14 = ta.momentum.RSIIndicator(close=df['close'], window=14)
    rsi_21 = ta.momentum.RSIIndicator(close=df['close'], window=21)
    df['RSI'] = rsi_14.rsi()
    df['RSI_21'] = rsi_21.rsi()
    return df


def calculate_macd(df):
    """MACD, signal, histogram."""
    macd_indicator = ta.trend.MACD(close=df['close'], window_slow=26, window_fast=12, window_sign=9)
    df['MACD'] = macd_indicator.macd()
    df['MACD_SIGNAL'] = macd_indicator.macd_signal()
    df['MACD_HIST'] = macd_indicator.macd_diff()
    return df


def calculate_ema(df):
    """EMA 20, 50, 200."""
    df['EMA_20'] = ta.trend.EMAIndicator(close=df['close'], window=20).ema_indicator()
    df['EMA_50'] = ta.trend.EMAIndicator(close=df['close'], window=50).ema_indicator()
    df['EMA_200'] = ta.trend.EMAIndicator(close=df['close'], window=200).ema_indicator()
    return df


def calculate_bollinger_bands(df):
    bb_indicator = ta.volatility.BollingerBands(close=df['close'], window=20, window_dev=2)
    df['BB_LOWER'] = bb_indicator.bollinger_lband()
    df['BB_MIDDLE'] = bb_indicator.bollinger_mavg()
    df['BB_UPPER'] = bb_indicator.bollinger_hband()
    return df


def calculate_all_indicators(df):
    """Compute all indicators (extended set for ML)."""
    # Cast OHLCV to float; keep timestamp as-is
    numeric_cols = ['open', 'high', 'low', 'close', 'volume']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = df[col].astype(float)
    
    df = calculate_wavetrend(df)
    if config.USE_ADX_FILTER:
        df = calculate_adx(df)
    df = calculate_atr(df)
    df = calculate_rsi(df)
    df = calculate_macd(df)
    df = calculate_ema(df)
    df = calculate_bollinger_bands(df)
    return df
