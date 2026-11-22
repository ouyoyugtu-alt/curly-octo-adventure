import time
import ccxt
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from colorama import Fore, Style, init

init(autoreset=True)

st.set_page_config(
    page_title="Futures Signal Scanner Pro",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
#                    إعداد المنصات
# ============================================================
@st.cache_resource
def get_exchanges():
    return {
        "binance": ccxt.binance({
            "options": {"defaultType": "future"},
            "enableRateLimit": True,
            "timeout": 15000,
        }),
        "bybit": ccxt.bybit({
            "options": {"defaultType": "swap"},
            "enableRateLimit": True,
            "timeout": 15000,
        }),
        "okx": ccxt.okx({
            "options": {"defaultType": "swap"},
            "enableRateLimit": True,
            "timeout": 15000,
        }),
    }


EXCHANGES = get_exchanges()


def get_symbol_candidates(symbol):
    """يرجع الصيغة المناسبة للرمز حسب كل منصة"""
    cleaned = symbol.strip().upper().replace("-", "/").replace(":USDT", "").replace("-SWAP", "")
    if "/" not in cleaned:
        cleaned = f"{cleaned}/USDT"
    base, quote = cleaned.split("/")[:2]
    return {
        "binance": f"{base}/{quote}",
        "bybit": f"{base}/{quote}:{quote}",
        "okx": f"{base}-{quote}-SWAP",
    }


# ============================================================
#                   جلب البيانات وحساب المؤشرات
# ============================================================
def fetch_data(exchange_name, symbol, timeframe, limit=500):
    ex = EXCHANGES[exchange_name]
    sym = get_symbol_candidates(symbol)[exchange_name]
    ohlcv = ex.fetch_ohlcv(sym, timeframe, limit=limit)
    if not ohlcv or len(ohlcv) < 200:
        raise ValueError(f"بيانات غير كافية من {exchange_name} لـ {symbol}")
    df = pd.DataFrame(ohlcv, columns=["time", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["time"], unit="ms")
    return df


def calculate_indicators(df):
    df = df.copy()
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()

    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    exp1 = df["close"].ewm(span=12, adjust=False).mean()
    exp2 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = exp1 - exp2
    df["signal"] = df["macd"].ewm(span=9, adjust=False).mean()

    prev_close = df["close"].shift()
    df["tr"] = np.maximum(
        df["high"] - df["low"],
        np.maximum((df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()),
    )
    df["atr"] = df["tr"].rolling(14).mean()

    df["bb_mid"] = df["close"].rolling(20).mean()
    df["bb_std"] = df["close"].rolling(20).std()
    df["bb_up"] = df["bb_mid"] + 2 * df["bb_std"]
    df["bb_dn"] = df["bb_mid"] - 2 * df["bb_std"]

    df["vol_ma"] = df["volume"].rolling(20).mean()

    rsi_min = df["rsi"].rolling(14).min()
    rsi_max = df["rsi"].rolling(14).max()
    df["stoch_rsi"] = (df["rsi"] - rsi_min) / (rsi_max - rsi_min).replace(0, np.nan)

    return df


# ============================================================
#                   محرك الإشارات
# ============================================================
def signal_engine(df):
    last = df.iloc[-1]
    prev = df.iloc[-2]
    long_score = 0
    short_score = 0
    reasons = []

    if last["close"] > last["ema200"]:
        long_score += 2
        reasons.append("فوق EMA200 (اتجاه صاعد)")
    else:
        short_score += 2
        reasons.append("تحت EMA200 (اتجاه هابط)")

    if last["ema20"] > last["ema50"]:
        long_score += 1
        reasons.append("EMA20 أعلى من EMA50")
    else:
        short_score += 1
        reasons.append("EMA20 أدنى من EMA50")

    if pd.notna(last["rsi"]):
        if last["rsi"] < 35:
            long_score += 2
            reasons.append(f"RSI={last['rsi']:.1f} (تشبع بيعي)")
        elif last["rsi"] > 65:
            short_score += 2
            reasons.append(f"RSI={last['rsi']:.1f} (تشبع شرائي)")

    if last["macd"] > last["signal"] and prev["macd"] <= prev["signal"]:
        long_score += 2
        reasons.append("تقاطع MACD صاعد")
    elif last["macd"] < last["signal"] and prev["macd"] >= prev["signal"]:
        short_score += 2
        reasons.append("تقاطع MACD هابط")

    if pd.notna(last["vol_ma"]) and last["vol_ma"] > 0 and last["volume"] > last["vol_ma"] * 1.2:
        if last["close"] > prev["close"]:
            long_score += 1
            reasons.append("حجم تداول مرتفع مؤكد للصعود")
        else:
            short_score += 1
            reasons.append("حجم تداول مرتفع مؤكد للهبوط")

    if last["close"] < last["bb_dn"]:
        long_score += 1
        reasons.append("السعر أسفل Bollinger السفلي")
    elif last["close"] > last["bb_up"]:
        short_score += 1
        reasons.append("السعر أعلى Bollinger العلوي")

    if pd.notna(last["stoch_rsi"]):
        if last["stoch_rsi"] < 0.2:
            long_score += 1
            reasons.append("Stochastic RSI منخفض")
        elif last["stoch_rsi"] > 0.8:
            short_score += 1
            reasons.append("Stochastic RSI مرتفع")

    if long_score >= 5 and long_score > short_score:
        direction = "LONG"
    elif short_score >= 5 and short_score > long_score:
        direction = "SHORT"
    else:
        return {
            "signal": "WAIT",
            "long_score": long_score,
            "short_score": short_score,
            "score": max(long_score, short_score),
            "reasons": reasons,
        }

    price = float(last["close"])
    atr = float(last["atr"]) if pd.notna(last["atr"]) and last["atr"] > 0 else price * 0.01

    if direction == "LONG":
        sl = price - atr * 1.5
        tp1 = price + atr * 2.0
        tp2 = price + atr * 3.5
        tp3 = price + atr * 5.0
    else:
        sl = price + atr * 1.5
        tp1 = price - atr * 2.0
        tp2 = price - atr * 3.5
        tp3 = price - atr * 5.0

    risk = abs(price - sl)
    reward = abs(tp2 - price)
    rr = reward / risk if risk > 0 else 0.0

    return {
        "signal": direction,
        "entry": price,
        "stop_loss": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rr": rr,
        "rsi": float(last["rsi"]) if pd.notna(last["rsi"]) else 50.0,
        "score": max(long_score, short_score),
        "reasons": reasons,
    }


# ============================================================
#               التحليل متعدد المنصات بمرونة
# ============================================================
def analyze_multi(symbol, timeframe):
    results = {}
    dfs = {}

    for name in EXCHANGES:
        try:
            df = fetch_data(name, symbol, timeframe)
            df = calculate_indicators(df)
            res = signal_engine(df)
            res["price"] = float(df["close"].iloc[-1])
            results[name] = res
            dfs[name] = df
        except Exception as e:
            results[name] = {"error": f"[{type(e).__name__}] {e}"}

    votes = {"LONG": 0, "SHORT": 0, "WAIT": 0}
    active_exchanges = 0
    for _, r in results.items():
        if "error" in r:
            continue
        active_exchanges += 1
        votes[r.get("signal", "WAIT")] += 1

    if active_exchanges == 0:
        final = "WAIT"
        status_note = "تعذر الاتصال بجميع المنصات"
    elif active_exchanges == 1:
        if votes["LONG"] == 1:
            final = "LONG"
            status_note = "إشارة معتمدة على منصة واحدة متاحة (حذر)"
        elif votes["SHORT"] == 1:
            final = "SHORT"
            status_note = "إشارة معتمدة على منصة واحدة متاحة (حذر)"
        else:
            final = "WAIT"
            status_note = "منصة واحدة متاحة وحالتها انتظار (WAIT)"
    else:
        min_votes = 2
        if votes["LONG"] >= min_votes and votes["LONG"] > votes["SHORT"]:
            final = "LONG"
            status_note = f"توافق {votes['LONG']} من {active_exchanges} منصات"
        elif votes["SHORT"] >= min_votes and votes["SHORT"] > votes["LONG"]:
            final = "SHORT"
            status_note = f"توافق {votes['SHORT']} من {active_exchanges} منصات"
        else:
            final = "WAIT"
            status_note = "لا يوجد إجماع كافٍ بين المنصات المتاحة"

    same = [r for r in results.values() if r.get("signal") == final and "error" not in r]
    if same and final != "WAIT":
        levels = {
            "entry": float(np.mean([r["price"] for r in same])),
            "stop_loss": float(np.mean([r["stop_loss"] for r in same])),
            "tp1": float(np.mean([r["tp1"] for r in same])),
            "tp2": float(np.mean([r["tp2"] for r in same])),
            "tp3": float(np.mean([r["tp3"] for r in same])),
            "rr": float(np.mean([r["rr"] for r in same])),
        }
    else:
        levels = None

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "votes": votes,
        "active_exchanges": active_exchanges,
        "status_note": status_note,
        "final": final,
        "levels": levels,
        "details": results,
        "dfs": dfs,
    }


# ============================================================
#               مسح السوق ببديل تلقائي آمن
# ============================================================
def scan_top_symbols(top_n=20, timeframe="1h"):
    tickers = {}
    markets = {}
    source_used = None

    for ex_name in ["okx", "binance", "bybit"]:
        try:
            ex = EXCHANGES[ex_name]
            markets = ex.load_markets()
            tickers = ex.fetch_tickers()
            source_used = ex_name
            break
        except Exception:
            continue

    if not source_used or not markets:
        return [], None

    swap_symbols = [
        s for s, m in markets.items()
        if m.get("swap") and (s.endswith("/USDT:USDT") or s.endswith("-USDT-SWAP"))
    ]

    top_symbols = sorted(
        swap_symbols,
        key=lambda s: tickers.get(s, {}).get("quoteVolume", 0) or 0,
        reverse=True,
    )[:top_n]

    opportunities = []
    for raw_sym in top_symbols:
        try:
            if "-USDT-SWAP" in raw_sym:
                clean_sym = raw_sym.replace("-USDT-SWAP", "/USDT")
            else:
                clean_sym = raw_sym.split(":")[0]
            r = analyze_multi(clean_sym, timeframe)
            if r["final"] != "WAIT" and r["levels"]:
                opportunities.append(r)
        except Exception:
            continue
        time.sleep(0.15)

    opportunities.sort(key=lambda x: x["votes"].get(x["final"], 0), reverse=True)
    return opportunities, source_used


# ============================================================
#                   أدوات العرض
# ============================================================
def fmt_price(p):
    if p is None:
        return "-"
    if p >= 1000:
        return f"{p:,.2f}"
    if p >= 1:
        return f"{p:.4f}"
    return f"{p:.6f}"


def render_exchange_cards(result):
    for name, d in result["details"].items():
        if "error" in d:
            with st.expander(f"{name.upper()} — ERROR", expanded=False):
                st.error(d["error"])
        else:
            sig = d.get("signal", "WAIT")
            score = d.get("score", 0)
            with st.expander(f"{name.upper()} — {sig}", expanded=(sig != "WAIT")):
                st.write(f"النقاط: {score}")
                if sig != "WAIT":
                    st.write(
                        f"السعر: {fmt_price(d['price'])} | "
                        f"SL: {fmt_price(d['stop_loss'])} | "
                        f"TP1: {fmt_price(d['tp1'])} | "
                        f"TP2: {fmt_price(d['tp2'])} | "
                        f"TP3: {fmt_price(d['tp3'])} | "
                        f"R:R = 1:{d['rr']:.2f}"
                    )


def render_signal_summary(result, leverage, position_size):
    final = result["final"]
    votes = result["votes"]

    st.subheader(f"{result['symbol']} — فريم {result['timeframe']}")
    st.caption(
        f"تصويت: LONG={votes['LONG']} | SHORT={votes['SHORT']} | WAIT={votes['WAIT']} "
        f"— {result['status_note']}"
    )

    if final == "LONG":
        st.success("LONG")
    elif final == "SHORT":
        st.error("SHORT")
    else:
        st.warning("WAIT")

    render_exchange_cards(result)

    if result["levels"]:
        L = result["levels"]
        entry = L["entry"]
        sl = L["stop_loss"]
        tp1 = L["tp1"]
        tp2 = L["tp2"]
        tp3 = L["tp3"]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("الدخول", fmt_price(entry))
        c2.metric("وقف الخسارة (SL)", fmt_price(sl))
        c3.metric("الهدف 2 (TP2)", fmt_price(tp2))
        c4.metric("R:R", f"1:{L['rr']:.2f}")

        st.write(f"الأهداف: TP1 = {fmt_price(tp1)} | TP2 = {fmt_price(tp2)} | TP3 = {fmt_price(tp3)}")

        if final == "LONG":
            pnl_sl_pct = (sl - entry) / entry * 100 * leverage
            pnl_tp2_pct = (tp2 - entry) / entry * 100 * leverage
        else:
            pnl_sl_pct = (entry - sl) / entry * 100 * leverage
            pnl_tp2_pct = (entry - tp2) / entry * 100 * leverage

        est_loss_usdt = position_size * (pnl_sl_pct / 100.0)
        est_profit_usdt = position_size * (pnl_tp2_pct / 100.0)

        st.info(
            f"الرافعة: {leverage}x | حجم المركز: {position_size:.2f} USDT | "
            f"تأثير SL: {pnl_sl_pct:+.2f}% ({est_loss_usdt:+.2f} USDT) | "
            f"تأثير TP2: {pnl_tp2_pct:+.2f}% ({est_profit_usdt:+.2f} USDT)"
        )

    for _, d in result["details"].items():
        if "error" not in d and d.get("signal") == final and d.get("reasons"):
            st.markdown("**الأسباب:**")
            for reason in d["reasons"][:5]:
                st.write(f"- {reason}")
            break


def render_chart(result):
    dfs = result.get("dfs", {})
    df = dfs.get("okx") or dfs.get("bybit") or dfs.get("binance")
    if df is None or df.empty:
        st.warning("لا توجد بيانات متاحة لرسم الشارت حالياً.")
        return

    tail = df.tail(150)
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=tail["timestamp"],
            open=tail["open"],
            high=tail["high"],
            low=tail["low"],
            close=tail["close"],
            name="السعر",
        )
    )
    fig.add_trace(go.Scatter(x=tail["timestamp"], y=tail["ema20"], name="EMA 20", mode="lines"))
    fig.add_trace(go.Scatter(x=tail["timestamp"], y=tail["ema50"], name="EMA 50", mode="lines"))
    fig.add_trace(go.Scatter(x=tail["timestamp"], y=tail["ema200"], name="EMA 200", mode="lines"))
    fig.update_layout(
        title=f"{result['symbol']} ({result['timeframe']})",
        xaxis_rangeslider_visible=False,
        height=480,
    )
    st.plotly_chart(fig, use_container_width=True)


# ============================================================
#                   الواجهة الرئيسية
# ============================================================
st.title("Scanner Pro")
st.caption("Binance + Bybit + OKX — v2.0")

with st.sidebar:
    st.header("الإعدادات")
    mode = st.radio(
        "الوضع",
        ["تحليل عملة", "مسح السوق", "رسم بياني"],
        index=0,
    )
    timeframe = st.selectbox("الفريم", ["15m", "1h", "4h"], index=1)
    leverage = st.slider("الليفرج", min_value=1, max_value=100, value=32)
    position_size = st.number_input("حجم المركز (USDT)", min_value=10.0, value=100.0, step=10.0)
    symbol = st.text_input("العملة", value="BTC/USDT")
    top_n = st.slider("عدد العملات في مسح السوق", min_value=10, max_value=40, value=20, step=5)

run_btn = st.button("تحليل", type="primary", use_container_width=True)

if mode in ("تحليل عملة", "رسم بياني"):
    if run_btn or "last_single_result" not in st.session_state:
        with st.spinner("جاري تحليل العملة..."):
            st.session_state["last_single_result"] = analyze_multi(symbol, timeframe)

    res = st.session_state["last_single_result"]
    render_signal_summary(res, leverage, position_size)
    if mode == "رسم بياني":
        render_chart(res)

elif mode == "مسح السوق":
    if run_btn:
        with st.spinner("جاري مسح السوق..."):
            opps, source_used = scan_top_symbols(top_n=top_n, timeframe=timeframe)
            st.session_state["last_scan"] = (opps, source_used)

    if "last_scan" in st.session_state:
        opps, source_used = st.session_state["last_scan"]
        if source_used:
            st.caption(f"مصدر قائمة العملات: {source_used.upper()} — عدد الفرص المكتشفة: {len(opps)}")
        if not opps:
            st.info("لا توجد فرص مكتملة حالياً على الإعدادات المختارة.")
        else:
            for idx, opp in enumerate(opps, 1):
                L = opp["levels"]
                st.markdown(
                    f"**{idx}. {opp['symbol']} — {opp['final']}** | "
                    f"الدخول: `{fmt_price(L['entry'])}` | "
                    f"SL: `{fmt_price(L['stop_loss'])}` | "
                    f"TP2: `{fmt_price(L['tp2'])}` | "
                    f"R:R: `1:{L['rr']:.2f}` | "
                    f"التصويت: `LONG={opp['votes']['LONG']}, SHORT={opp['votes']['SHORT']}`"
                )
