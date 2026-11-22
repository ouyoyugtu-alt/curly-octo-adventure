import time
import requests
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ============================================================
# GALEIC FUTURES PRO — Binance USDT-M public market data
# Analysis only: this app does NOT place orders.
# ============================================================

API = "https://fapi.binance.com"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "GALEIC-FUTURES-PRO/1.0"})

st.set_page_config(
    page_title="GALEIC FUTURES PRO",
    page_icon="📊",
    layout="wide",
)

st.markdown("""
<style>
html, body, [class*="css"] { direction: rtl; }
[data-testid="stAppViewContainer"] { background: #08111f; }
[data-testid="stSidebar"] { background: #101b2b; }
.block-container { padding-top: 1.3rem; }
div[data-testid="stMetric"] {
    background: #111f33; border: 1px solid #263b57;
    padding: 12px; border-radius: 12px;
}
</style>
""", unsafe_allow_html=True)

st.title("📊 GALEIC FUTURES PRO")
st.caption(
    "ماسح وتحليل عقود Binance USDT-M Futures باستخدام بيانات السوق العامة. "
    "تحليل تعليمي فقط — لا ينفّذ صفقات ولا يضمن الأرباح."
)

# -------------------- API --------------------

def api_get(path, params=None, timeout=15):
    url = API + path
    response = SESSION.get(url, params=params or {}, timeout=timeout)
    if response.status_code == 429:
        raise RuntimeError("Binance rate limit: انتظر قليلاً ثم أعد المحاولة.")
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict) and data.get("code") is not None and int(data["code"]) < 0:
        raise RuntimeError(data.get("msg", "Binance API error"))
    return data

@st.cache_data(ttl=300, show_spinner=False)
def get_usdt_perpetual_symbols():
    info = api_get("/fapi/v1/exchangeInfo")
    return [
        s["symbol"] for s in info["symbols"]
        if s.get("quoteAsset") == "USDT"
        and s.get("contractType") == "PERPETUAL"
        and s.get("status") == "TRADING"
    ]

@st.cache_data(ttl=45, show_spinner=False)
def get_tickers_24h():
    data = api_get("/fapi/v1/ticker/24hr")
    df = pd.DataFrame(data)
    for col in ["quoteVolume", "lastPrice", "priceChangePercent"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df

@st.cache_data(ttl=20, show_spinner=False)
def get_klines(symbol, interval, limit=300):
    rows = api_get(
        "/fapi/v1/klines",
        {"symbol": symbol, "interval": interval, "limit": limit}
    )
    cols = [
        "open_time", "Open", "High", "Low", "Close", "Volume",
        "close_time", "quote_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore"
    ]
    df = pd.DataFrame(rows, columns=cols)
    numeric = ["Open", "High", "Low", "Close", "Volume", "close_time", "quote_volume"]
    for col in numeric:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    # Exclude the currently-forming candle using Binance server time.
    server_ms = int(api_get("/fapi/v1/time")["serverTime"])
    df = df[df["close_time"] < server_ms].copy()
    df = df.dropna(subset=["Open", "High", "Low", "Close", "Volume"])
    df = df.set_index("time").sort_index()
    return df[["Open", "High", "Low", "Close", "Volume", "quote_volume"]]

# -------------------- Indicators --------------------

def add_indicators(df):
    d = df.copy()
    d["EMA20"] = d["Close"].ewm(span=20, adjust=False).mean()
    d["EMA50"] = d["Close"].ewm(span=50, adjust=False).mean()
    d["EMA200"] = d["Close"].ewm(span=200, adjust=False).mean()

    delta = d["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    d["RSI"] = 100 - (100 / (1 + rs))
    d.loc[(avg_loss == 0) & (avg_gain > 0), "RSI"] = 100

    ema12 = d["Close"].ewm(span=12, adjust=False).mean()
    ema26 = d["Close"].ewm(span=26, adjust=False).mean()
    d["MACD"] = ema12 - ema26
    d["MACD_SIGNAL"] = d["MACD"].ewm(span=9, adjust=False).mean()

    previous_close = d["Close"].shift(1)
    tr = pd.concat([
        d["High"] - d["Low"],
        (d["High"] - previous_close).abs(),
        (d["Low"] - previous_close).abs()
    ], axis=1).max(axis=1)
    d["ATR"] = tr.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    d["VOL_MA20"] = d["Volume"].rolling(20).mean()
    d["VOL_RATIO"] = d["Volume"] / d["VOL_MA20"].replace(0, np.nan)
    return d.dropna(subset=["EMA200", "RSI", "MACD_SIGNAL", "ATR", "VOL_RATIO"])

def trend_of(df):
    x = df.iloc[-1]
    if x["Close"] > x["EMA20"] > x["EMA50"] > x["EMA200"]:
        return "صاعد"
    if x["Close"] < x["EMA20"] < x["EMA50"] < x["EMA200"]:
        return "هابط"
    return "محايد"

def analyze_symbol(symbol, sl_atr, rr1, rr2, rr3):
    d15 = add_indicators(get_klines(symbol, "15m", 300))
    d1 = add_indicators(get_klines(symbol, "1h", 300))
    d4 = add_indicators(get_klines(symbol, "4h", 300))
    if min(len(d15), len(d1), len(d4)) < 5:
        return None

    x = d15.iloc[-1]
    t1 = trend_of(d1)
    t4 = trend_of(d4)
    t15 = trend_of(d15)

    long_score = 0
    short_score = 0

    if t4 == "صاعد": long_score += 25
    if t4 == "هابط": short_score += 25
    if t1 == "صاعد": long_score += 25
    if t1 == "هابط": short_score += 25

    if x["Close"] > x["EMA20"]: long_score += 10
    if x["Close"] < x["EMA20"]: short_score += 10

    if 50 < x["RSI"] < 70: long_score += 10
    if 30 < x["RSI"] < 50: short_score += 10

    if x["MACD"] > x["MACD_SIGNAL"]: long_score += 10
    if x["MACD"] < x["MACD_SIGNAL"]: short_score += 10

    if x["VOL_RATIO"] >= 1.5:
        if x["Close"] > x["Open"]: long_score += 10
        if x["Close"] < x["Open"]: short_score += 10

    prior_high = d15["High"].iloc[-21:-1].max()
    prior_low = d15["Low"].iloc[-21:-1].min()
    if x["Close"] > prior_high: long_score += 10
    if x["Close"] < prior_low: short_score += 10

    if long_score >= 70 and long_score > short_score and t4 == "صاعد" and t1 == "صاعد":
        signal, score = "LONG", long_score
    elif short_score >= 70 and short_score > long_score and t4 == "هابط" and t1 == "هابط":
        signal, score = "SHORT", short_score
    else:
        signal, score = "WAIT", max(long_score, short_score)

    entry = float(x["Close"])
    atr = float(x["ATR"])
    if not np.isfinite(atr) or atr <= 0:
        return None

    if signal == "LONG":
        distance = atr * sl_atr
        sl = entry - distance
        tp1, tp2, tp3 = entry + distance*rr1, entry + distance*rr2, entry + distance*rr3
    elif signal == "SHORT":
        distance = atr * sl_atr
        sl = entry + distance
        tp1, tp2, tp3 = entry - distance*rr1, entry - distance*rr2, entry - distance*rr3
    else:
        sl = tp1 = tp2 = tp3 = np.nan

    return {
        "symbol": symbol, "signal": signal, "score": int(score),
        "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "rsi": float(x["RSI"]), "atr": atr,
        "volume_ratio": float(x["VOL_RATIO"]),
        "trend15": t15, "trend1": t1, "trend4": t4,
        "chart": d15
    }

def fmt_price(value):
    if pd.isna(value):
        return "—"
    return f"{value:,.8g}"

# -------------------- Sidebar --------------------

st.sidebar.header("⚙️ إعدادات التحليل")
mode = st.sidebar.radio("وضع التشغيل", ["تحليل عملة", "ماسح العملات"])
min_score = st.sidebar.slider("الحد الأدنى لقوة الإشارة", 60, 100, 70)
sl_atr = st.sidebar.slider("وقف الخسارة (مضاعف ATR)", 0.5, 3.0, 1.5, 0.1)
rr1 = st.sidebar.number_input("مضاعف الهدف الأول R", 0.5, 5.0, 1.0, 0.5)
rr2 = st.sidebar.number_input("مضاعف الهدف الثاني R", 1.0, 8.0, 2.0, 0.5)
rr3 = st.sidebar.number_input("مضاعف الهدف الثالث R", 1.5, 12.0, 3.0, 0.5)
capital = st.sidebar.number_input("رأس المال بالدولار", min_value=10.0, value=1000.0, step=100.0)
risk_pct = st.sidebar.slider("المخاطرة من رأس المال (%)", 0.1, 5.0, 1.0, 0.1)
leverage = st.sidebar.number_input("الرافعة المستخدمة (للتقدير فقط)", 1, 125, 5)
st.sidebar.caption("الرافعة لا تغيّر مبلغ المخاطرة المحسوب. راجع هامش الصيانة ورسوم التداول قبل أي صفقة.")

# -------------------- Single symbol --------------------

if mode == "تحليل عملة":
    symbol = st.sidebar.text_input("رمز العقد", "BTCUSDT").strip().upper()
    if st.button("🔍 تحليل الآن", type="primary", use_container_width=True):
        if not symbol.endswith("USDT"):
            st.error("أدخل رمز عقد USDT-M مثل BTCUSDT أو ETHUSDT.")
        else:
            try:
                with st.spinner("يتم جلب البيانات وتحليل الفريمات المغلقة..."):
                    result = analyze_symbol(symbol, sl_atr, rr1, rr2, rr3)
                if result is None:
                    st.warning("البيانات غير كافية لهذا العقد.")
                else:
                    a, b, c, d = st.columns(4)
                    a.metric("الإشارة", result["signal"])
                    b.metric("قوة الشروط", f'{result["score"]}/100')
                    c.metric("RSI — 15m", f'{result["rsi"]:.1f}')
                    d.metric("حجم التداول / متوسطه", f'{result["volume_ratio"]:.2f}x')

                    t1c, t2c, t3c = st.columns(3)
                    t1c.metric("اتجاه 4H", result["trend4"])
                    t2c.metric("اتجاه 1H", result["trend1"])
                    t3c.metric("اتجاه 15M", result["trend15"])

                    if result["signal"] != "WAIT":
                        st.subheader("مستويات الصفقة التقديرية")
                        p1, p2, p3, p4, p5 = st.columns(5)
                        p1.metric("الدخول", fmt_price(result["entry"]))
                        p2.metric("وقف الخسارة", fmt_price(result["sl"]))
                        p3.metric("TP1", fmt_price(result["tp1"]))
                        p4.metric("TP2", fmt_price(result["tp2"]))
                        p5.metric("TP3", fmt_price(result["tp3"]))

                        risk_money = capital * risk_pct / 100
                        risk_per_unit = abs(result["entry"] - result["sl"])
                        quantity = risk_money / risk_per_unit if risk_per_unit else 0
                        notional = quantity * result["entry"]
                        margin_est = notional / leverage
                        st.info(
                            f"مبلغ المخاطرة النظري: ${risk_money:,.2f} | "
                            f"الكمية التقديرية: {quantity:.6g} | "
                            f"القيمة الاسمية: ${notional:,.2f} | "
                            f"الهامش التقريبي عند {leverage}x: ${margin_est:,.2f}. "
                            "هذه الحسابات لا تشمل الرسوم أو الانزلاق أو قواعد التصفية."
                        )
                    else:
                        st.warning("لا توجد إشارة مستوفية للشروط حالياً. لا تدخل لمجرد ارتفاع التقييم.")

                    chart = result["chart"].tail(150)
                    fig = go.Figure()
                    fig.add_trace(go.Candlestick(
                        x=chart.index, open=chart["Open"], high=chart["High"],
                        low=chart["Low"], close=chart["Close"], name="15m"
                    ))
                    for col in ["EMA20", "EMA50", "EMA200"]:
                        fig.add_trace(go.Scatter(x=chart.index, y=chart[col], name=col, mode="lines"))
                    if result["signal"] != "WAIT":
                        for price, label in [
                            (result["sl"], "SL"), (result["tp1"], "TP1"),
                            (result["tp2"], "TP2"), (result["tp3"], "TP3")
                        ]:
                            fig.add_hline(y=price, line_dash="dash", annotation_text=label)
                    fig.update_layout(
                        template="plotly_dark", height=600,
                        xaxis_rangeslider_visible=False,
                        margin=dict(l=10, r=10, t=30, b=10)
                    )
                    st.plotly_chart(fig, use_container_width=True)
                    st.caption(f"آخر شمعة 15m مغلقة: {result['chart'].index[-1]}")
            except Exception as exc:
                st.error(f"تعذر التحليل: {exc}")

# -------------------- Scanner --------------------

else:
    st.subheader("🔎 ماسح عقود USDT-M")
    scan_count = st.sidebar.slider("عدد العملات الأعلى حجماً للفحص", 5, 40, 15)
    if st.button("🚀 ابدأ مسح السوق", type="primary", use_container_width=True):
        try:
            with st.spinner("تحميل قائمة العقود وأحجام التداول..."):
                symbols = set(get_usdt_perpetual_symbols())
                tickers = get_tickers_24h()
                tickers = tickers[tickers["symbol"].isin(symbols)].copy()
                tickers = tickers.sort_values("quoteVolume", ascending=False).head(scan_count)

            results = []
            progress = st.progress(0)
            status = st.empty()
            total = max(len(tickers), 1)
            for i, row in enumerate(tickers.itertuples(index=False), start=1):
                sym = getattr(row, "symbol")
                status.caption(f"فحص {sym} — {i}/{total}")
                try:
                    item = analyze_symbol(sym, sl_atr, rr1, rr2, rr3)
                    if item and item["signal"] != "WAIT" and item["score"] >= min_score:
                        results.append(item)
                except Exception:
                    pass
                progress.progress(i / total)
                time.sleep(0.08)

            progress.empty()
            status.empty()
            if results:
                results.sort(key=lambda z: z["score"], reverse=True)
                table = pd.DataFrame([{
                    "العقد": x["symbol"], "الإشارة": x["signal"],
                    "القوة": x["score"], "السعر": x["entry"],
                    "RSI": round(x["rsi"], 1),
                    "حجم التداول x": round(x["volume_ratio"], 2),
                    "اتجاه 4H": x["trend4"], "اتجاه 1H": x["trend1"]
                } for x in results])
                st.success(f"تم العثور على {len(results)} إشارة مطابقة للشروط ضمن {len(tickers)} عقداً مفحوصاً.")
                st.dataframe(table, use_container_width=True, hide_index=True)
                selected = st.selectbox("اختر عقداً لعرض المستويات", [x["symbol"] for x in results])
                chosen = next(x for x in results if x["symbol"] == selected)
                q1, q2, q3, q4, q5 = st.columns(5)
                q1.metric("الدخول", fmt_price(chosen["entry"]))
                q2.metric("SL", fmt_price(chosen["sl"]))
                q3.metric("TP1", fmt_price(chosen["tp1"]))
                q4.metric("TP2", fmt_price(chosen["tp2"]))
                q5.metric("TP3", fmt_price(chosen["tp3"]))
            else:
                st.warning("لم تظهر إشارات مستوفية للشروط في العملات المفحوصة. هذا أفضل من فرض صفقة.")
        except Exception as exc:
            st.error(f"تعذر تشغيل الماسح: {exc}")

st.divider()
st.caption(
    "GALEIC FUTURES PRO • بيانات عامة من Binance USDT-M Futures • "
    "الإشارات شروط فنية وليست احتمالات نجاح. اختبر الاستراتيجية تاريخياً وعلى حساب تجريبي أولاً."
)
