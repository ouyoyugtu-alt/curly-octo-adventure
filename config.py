import os
from dotenv import load_dotenv

load_dotenv()

# -------- إعدادات عامة --------
APP_TITLE = "🎯 Futures Signal Scanner Pro"
APP_ICON = "🎯"
BUILD_VERSION = "v2.0"

# -------- المنصات المدعومة --------
EXCHANGES = ["binance", "bybit", "okx"]

# -------- الفريمات --------
TIMEFRAMES = {
    "5m":  {"leverage": 20, "min_rr": 2.0},
    "15m": {"leverage": 20, "min_rr": 2.0},
    "1h":  {"leverage": 10, "min_rr": 2.5},
    "4h":  {"leverage": 5,  "min_rr": 3.0},
    "1d":  {"leverage": 3,  "min_rr": 3.0},
}

# -------- إعدادات المسح --------
DEFAULT_SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
    "XRP/USDT", "ADA/USDT", "DOGE/USDT", "AVAX/USDT",
]

# -------- إعدادات API (اختياري) --------
BINANCE_KEY    = os.getenv("BINANCE_KEY", "")
BINANCE_SECRET = os.getenv("BINANCE_SECRET", "")
BYBIT_KEY      = os.getenv("BYBIT_KEY", "")
BYBIT_SECRET   = os.getenv("BYBIT_SECRET", "")
OKX_KEY        = os.getenv("OKX_KEY", "")
OKX_SECRET     = os.getenv("OKX_SECRET", "")
OKX_PASS       = os.getenv("OKX_PASS", "")