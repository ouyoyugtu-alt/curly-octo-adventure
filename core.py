import ccxt
import pandas as pd
import numpy as np
import time
import streamlit as st

# ---------------- كاش المنصات ----------------
@st.cache_resource
def get_exchanges():
    return {
        "binance": ccxt.binance({
            "options": {"defaultType": "future"},
            "enableRateLimit": True,
        }),
        "bybit": ccxt.bybit({
            "options": {"defaultType": "swap"},
            "enableRateLimit": True,
        }),
        "okx": ccxt.okx({
            "options": {"defaultType": "swap"},
            "enableRateLimit": True,
        }),
    }


def _symbols(symbol):
    """يقبل BTC/USDT أو BTC-USDT ويرجع صيغاً لكل منصة."""
    base, quote = symbol.replace("-", "/").upper().split("/")
    return {
        "binance": f"{base}/{quote}",
        "bybit":   f"{base}/{quote}:{quote}",
        "okx":     f"{base}-{quote}-SWAP",
    }


# ---------------- جلب البيانات ----------------
@st.cache_data(ttl=30)
def fetch_ohlcv(exchange_name: str, symbol: str, timeframe: str, limit: int = 500):
    ex = get_exchanges()[exchange_name]
    sym = _symbols(symbol)[exchange_name]
    data = ex.fetch_ohlcv(sym, timeframe, limit=limit)
    if not data or len(data) < 210:
        raise ValueError(f"بيانات غير كافية من {exchange_name} لـ {symbol}")
    df = pd.DataFrame(data, columns=["time","open","high","low","close","volume"])
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    return df


# ---------------- المؤشرات ----------------
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df["ema20"]  = df["close"].ewm(span=20,  adjust=False).mean()
    df["ema50"]  = df["close"].ewm(span=50,  adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()

    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    exp1 = df["close"].ewm(span=12, adjust=False).mean()
    exp2 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"]      = exp1 - exp2
    df["macd_sig"]  = df["macd"].ewm(span=9, adjust=False).mean()

    df["tr"] = np.maximum(
        df["high"] - df["low"],
        np.maximum(abs(df["high"] - df["close"].shift()),
                   abs(df["low"]  - df["close"].shift()))
    )
    df["atr"] = df["tr"].rolling(14).mean()

    df["bb_mid"] = df["close"].rolling(20).mean()
    df["bb_std"] = df["close"].rolling(20).std()
    df["bb_up"]  = df["bb_mid"] + 2 * df["bb_std"]
    df["bb_dn"]  = df["bb_mid"] - 2 * df["bb_std"]

    df["vol_ma"] = df["volume"].rolling(20).mean()

    rmin = df["rsi"].rolling(14).min()
    rmax = df["rsi"].rolling(14).max()
    df["stoch_rsi"] = (df["rsi"] - rmin) / (rmax - rmin).replace(0, np.nan)

    return df


# ---------------- محرك الإشارات ----------------
def make_signal(df: pd.DataFrame) -> dict:
    last, prev = df.iloc[-1], df.iloc[-2]
    long_s = short_s = 0
    reasons = []

    if last["close"] > last["ema200"]:
        long_s += 2; reasons.append("📈 فوق EMA200")
    else:
        short_s += 2; reasons.append("📉 تحت EMA200")

    if last["ema20"] > last["ema50"]: long_s += 1
    else: short_s += 1

    if last["rsi"] < 35:
        long_s += 2; reasons.append(f"🟢 RSI={last['rsi']:.1f}")
    elif last["rsi"] > 65:
        short_s += 2; reasons.append(f"🔴 RSI={last['rsi']:.1f}")

    if last["macd"] > last["macd_sig"] and prev["macd"] <= prev["macd_sig"]:
        long_s += 2; reasons.append("✅ تقاطع MACD صاعد")
    elif last["macd"] < last["macd_sig"] and prev["macd"] >= prev["macd_sig"]:
        short_s += 2; reasons.append("✅ تقاطع MACD هابط")

    if last["volume"] > last["vol_ma"] * 1.2:
        if last["close"] > prev["close"]:
            long_s += 1; reasons.append("💪 حجم مؤكد صعود")
        else:
            short_s += 1; reasons.append("💪 حجم مؤكد هبوط")

    if last["close"] < last["bb_dn"]:
        long_s += 1; reasons.append("📊 تحت Bollinger السفلي")
    elif last["close"] > last["bb_up"]:
        short_s += 1; reasons.append("📊 فوق Bollinger العلوي")

    if last["stoch_rsi"] < 0.2: long_s += 1
    elif last["stoch_rsi"] > 0.8: short_s += 1

    if long_s >= 5 and long_s > short_s:
        direction = "LONG"
    elif short_s >= 5 and short_s > long_s:
        direction = "SHORT"
    else:
        return {"signal": "WAIT", "long_score": long_s,
                "short_score": short_s, "reasons": reasons}

    price = float(last["close"]); atr = float(last["atr"])
    if direction == "LONG":
        sl, tp1, tp2, tp3 = price-1.5*atr, price+2*atr, price+3.5*atr, price+5*atr
    else:
        sl, tp1, tp2, tp3 = price+1.5*atr, price-2*atr, price-3.5*atr, price-5*atr

    risk = abs(price - sl); reward = abs(tp2 - price)
    rr = reward / risk if risk > 0 else 0

    return {
        "signal": direction, "price": price,
        "stop_loss": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "rr": rr, "rsi": float(last["rsi"]),
        "score": max(long_s, short_s), "reasons": reasons,
    }


# ---------------- تحليل متعدد المنصات ----------------
@st.cache_data(ttl=30)
def analyze_multi(symbol: str, timeframe: str) -> dict:
    details = {}
    for name in ["binance", "bybit", "okx"]:
        try:
            df = fetch_ohlcv(name, symbol, timeframe)
            df = add_indicators(df)
            details[name] = make_signal(df)
        except Exception as e:
            details[name] = {"error": str(e)}

    votes = {"LONG": 0, "SHORT": 0, "WAIT": 0}
    for r in details.values():
        if "error" in r: continue
        votes[r.get("signal", "WAIT")] += 1

    if votes["LONG"] >= 2 and votes["LONG"] > votes["SHORT"]:
        final = "LONG"
    elif votes["SHORT"] >= 2 and votes["SHORT"] > votes["LONG"]:
        final = "SHORT"
    else:
        final = "WAIT"

    same = [r for r in details.values()
            if r.get("signal") == final and "error" not in r]
    levels = None
    if same and final != "WAIT":
        levels = {k: float(np.mean([r["price" if k=="entry" else k] for r in same]))
                  for k in ["entry","stop_loss","tp1","tp2","tp3"]}
        levels["rr"] = float(np.mean([r["rr"] for r in same]))

    return {
        "symbol": symbol, "timeframe": timeframe,
        "votes": votes, "final": final,
        "levels": levels, "details": details,
    }


# ---------------- مسح السوق ----------------
def scan_market(timeframe: str, top_n: int = 25, progress_cb=None):
    ex = get_exchanges()["binance"]
    try:
        tickers = ex.fetch_tickers()
    except Exception:
        tickers = {}

    markets = [s for s in ex.markets
               if ex.markets[s].get("swap") and s.endswith("/USDT:USDT")]
    markets.sort(
        key=lambda s: tickers.get(s, {}).get("quoteVolume", 0) or 0,
        reverse=True,
    )
    markets = markets[:top_n]

    results = []
    for i, s in enumerate(markets):
        if progress_cb: progress_cb(i, len(markets), s)
        try:
            clean = s.split(":")[0]
            r = analyze_multi(clean, timeframe)
            if r["final"] != "WAIT" and r["levels"]:
                results.append(r)
        except Exception:
            continue
        time.sleep(0.15)

    results.sort(key=lambda x: (x["votes"][x["final"]], x["levels"]["rr"]), reverse=True)
    return results