import os
import sys
from dotenv import load_dotenv

# Ensure local imports work regardless of CWD or IDE context
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    import path_utils
    bot_env = os.path.join(path_utils.get_base_dir(), ".env")
    if os.path.exists(bot_env):
        load_dotenv(bot_env, override=True)  # Only this bot's .env in its base dir
except ImportError:
    pass

# API keys (from environment)
API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Trading
USE_TESTNET = False  # Testnet no longer supported (CCXT deprecation)
AUTO_TRADE = True     # Auto-trading enabled
IS_FUTURES = True    # Futures mode
LEVERAGE = 1         # Leverage (1x ~ no leverage)

TRADE_AMOUNT_TYPE = 'PERCENT'  # 'FIXED' (USDT) or 'PERCENT' (balance %)
TRADE_AMOUNT_VALUE = 0.05      # e.g. 5% of balance per trade

# Symbols to scan (Binance Futures compatible)
WATCHLIST = [
    # ================= MAJORS =================
    'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 'XRP/USDT',

    # ================= LAYER 1 =================
    'ADA/USDT', 'AVAX/USDT', 'DOT/USDT', 'NEAR/USDT', 'ATOM/USDT',
    'SUI/USDT', 'SEI/USDT', 'TIA/USDT', 'TRX/USDT', 'LTC/USDT',
    'APT/USDT', 'INJ/USDT', 'ALGO/USDT', 'TON/USDT',
    'HBAR/USDT', 'EGLD/USDT', 'FTM/USDT', 'FLOW/USDT', 'MINA/USDT',
    'ROSE/USDT', 'KAVA/USDT', 'ETC/USDT', 'BCH/USDT',

    # ================= LAYER 2 & SCALING =================
    'POL/USDT', 'ARB/USDT', 'OP/USDT', 'IMX/USDT', 'LDO/USDT',  # MATIC -> POL
    'LOOM/USDT', 'CELO/USDT', 'SKL/USDT',

    # ================= DEFI =================
    'LINK/USDT', 'UNI/USDT', 'AAVE/USDT', 'MKR/USDT', 'SNX/USDT',
    'CRV/USDT', 'COMP/USDT', 'SUSHI/USDT', 'BAL/USDT', 'CAKE/USDT',
    'DYDX/USDT', 'PENDLE/USDT', 'RUNE/USDT', 'ENA/USDT',
    '1INCH/USDT', 'ETHFI/USDT', 'AEVO/USDT', 'LISTA/USDT', 'REZ/USDT',

    # ================= ORACLE & DATA =================
    'PYTH/USDT', 'JUP/USDT', 'API3/USDT', 'BAND/USDT', 'TRB/USDT',
    'ZRO/USDT', 'W/USDT', 'JTO/USDT',

    # ================= AI =================
    'FET/USDT', 'RENDER/USDT', 'TAO/USDT', 'WLD/USDT',  # RNDR -> RENDER
    'OCEAN/USDT', 'AGIX/USDT', 'NMR/USDT', 'IO/USDT',
    'ARKM/USDT', 'AI/USDT', 'PHB/USDT',

    # ================= GAMING & METAVERSE =================
    'GALA/USDT', 'SAND/USDT', 'MANA/USDT', 'AXS/USDT', 'PIXEL/USDT',
    'ILV/USDT', 'MAGIC/USDT', 'ENJ/USDT', 'PORTAL/USDT', 'XAI/USDT',
    'YGG/USDT', 'NOT/USDT', 'ACE/USDT', 'MAVIA/USDT',

    # ================= MEME =================
    'DOGE/USDT', '1000SHIB/USDT', '1000PEPE/USDT', 'WIF/USDT', '1000FLOKI/USDT',
    '1000BONK/USDT', 'BOME/USDT', 'MEME/USDT', 'TURBO/USDT', 'MYRO/USDT',
    'NEIRO/USDT', 'DOGS/USDT', 'PEOPLE/USDT',

    # ================= STORAGE & INFRA =================
    'FIL/USDT', 'AR/USDT', 'STORJ/USDT', 'ANKR/USDT',
    'CKB/USDT', 'IOTX/USDT', 'AXL/USDT',

    # ================= PAYMENT & UTILITY =================
    'XLM/USDT', 'VET/USDT', 'THETA/USDT', 'XTZ/USDT',
    'IOTA/USDT', 'ZEC/USDT', 'DASH/USDT', 'NEO/USDT',

    # ================= PRIVACY =================
    'XMR/USDT', 'SCRT/USDT', 'ZEN/USDT',

    # ================= HIGH VOL / TREND =================
    'ALT/USDT', 'ORDI/USDT', '1000SATS/USDT', 'DYM/USDT', 'BB/USDT',

    # ================= EXTRA =================
    'SOON/USDT', 'SWARMS/USDT', 'TOSHI/USDT', 'USELESS/USDT', 'VINE/USDT',
    'XAN/USDT', 'YALA/USDT', 'ZETA/USDT', 'LSK/USDT',
]

# Remove duplicates while preserving order
WATCHLIST = list(dict.fromkeys(WATCHLIST))

TIMEFRAME = '4h'       # Main timeframe
SCALP_TIMEFRAME = '15m'
LIMIT = 500            # Number of candles to fetch

# WaveTrend
WT_CHANNEL_LEN = 10
WT_AVERAGE_LEN = 21
WT_MA_LEN = 4

# Thresholds
WT_BOUGHT_LEVEL_1 = 60
WT_BOUGHT_LEVEL_2 = 53
WT_SOLD_LEVEL_1 = -60
WT_SOLD_LEVEL_2 = -53

# Multi-trade
MAX_TRADES_PER_COIN = 3  # Max concurrent trades per coin (overridable in GUI)

# Risk
# ===================== CONSERVATIVE DEFAULTS =====================
STOP_LOSS_PCT = 0.04
TAKE_PROFIT_1_PCT = 0.015
TAKE_PROFIT_2_PCT = 0.03

# Filters
ADX_THRESHOLD = 20
USE_ADX_FILTER = True

# ===================== ML FILTER =====================
USE_ML_FILTER = True
ML_MODEL_PATH = "models/signal_classifier.pkl"
ML_SCALER_PATH = "models/feature_scaler.pkl"

ML_CONFIDENCE_THRESHOLD = 0.52                 # See model_meta.json
ML_SKIP_LOW_CONFIDENCE = True
ML_LOG_ALL_PREDICTIONS = True

ML_PAPER_TRADING = True
ML_LOG_FILE = "ml_predictions.log"
ML_SAVE_PREDICTIONS_JSONL = True
ML_PREDICTIONS_FILE = "ml_predictions.jsonl"

ML_AUTO_RETRAIN = False
ML_RETRAIN_THRESHOLD = 200

