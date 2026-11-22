import time
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

# ==========================================
# GALEIC FUTURES PRO
# BYBIT V5 API
# ==========================================

API = "https://api.bybit.com"
CATEGORY = "linear"

session = requests.Session()
session.headers.update({
    "User-Agent": "GALEIC-FUTURES-PRO/2.0"
})

st.set_page_config(
    page_title="GALEIC FUTURES PRO",
    page_icon="📊",
    layout="wide"
)

st.markdown("""
<style>
html, body, [class*="css"] {
    direction: rtl;
}
[data-testid="stAppViewContainer"] {
    background: #08111f;
}
[data-testid="stSidebar"] {
    background: #101b2b;
}
.block-container {
    padding-top: 1.2rem;
}
div[data-testid="stMetric"] {
    background: #111f33;
    border: 1px solid #263b57;
    padding: 12px;
    border-radius: 12px;
}
</style>
""", unsafe_allow_html=True)

st.title("📊 GALEIC FUTURES PRO")

st.caption(
    "منصة تحليل عقود Bybit USDT Perpetual "
    "باستخدام بيانات السوق العامة."
)


# ==========================================
# API CONNECTION
# ==========================================

class MarketDataError(Exception):
    pass


def bybit_get(path, params=None):

    try:
        response = session.get(
            API + path,
            params=params or {},
            timeout=20
        )

        if response.status_code in (403, 451):
            raise MarketDataError(
                f"رفض مزود البيانات الاتصال: HTTP "
                f"{response.status_code}. "
                "قد يكون الوصول مقيداً من منطقة الاستضافة."
            )

        if response.status_code == 429:
            raise MarketDataError(
                "تجاوزت حد الطلبات. حاول بعد قليل."
            )

        response.raise_for_status()
        payload = response.json()

    except requests.RequestException as exc:
        raise MarketDataError(
            f"خطأ في الاتصال: {exc}"
        )

    if payload.get("retCode") != 0:
        raise MarketDataError(
            payload.get("retMsg", "خطأ من Bybit API")
        )

    return payload


# ==========================================
# MARKET TICKERS
# ==========================================

@st.cache_data(ttl=45)
def get_linear_tickers():

    payload = bybit_get(
        "/v5/market/tickers",
        {"category": CATEGORY}
    )

    rows = payload["result"]["list"]

    df = pd.DataFrame(rows)

    if df.empty:
        raise MarketDataError(
            "لم يتم العثور على بيانات السوق."
        )

    for col in [
        "lastPrice",
        "volume24h",
        "turnover24h",
        "price24hPcnt"
    ]:
        df[col] = pd.to_numeric(
            df[col],
            errors="coerce"
        )

    df = df[
        df["symbol"].str.endswith("USDT", na=False)
    ].copy()

    return df


# ==========================================
# CANDLE DATA
# ==========================================

@st.cache_data(ttl=20)
def get_klines(symbol, interval, limit=300):

    payload = bybit_get(
        "/v5/market/kline",
        {
            "category": CATEGORY,
            "symbol": symbol,
            "interval": str(interval),
            "limit": limit
        }
    )

    rows = payload["result"]["list"]

    if not rows:
        raise MarketDataError(
            f"لا توجد بيانات للرمز {symbol}"
        )

    df = pd.DataFrame(
        rows,
        columns=[
            "start_ms",
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
            "Turnover"
        ]
    )

    df["start_ms"] = pd.to_numeric(
        df["start_ms"]
    )

    for col in [
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
        "Turnover"
    ]:
        df[col] = pd.to_numeric(
            df[col],
            errors="coerce"
        )

    df["time"] = pd.to_datetime(
        df["start_ms"],
        unit="ms",
        utc=True
    )

    df = df.dropna()

    df = df.sort_values("time")

    df = df.set_index("time")

    now_ms = int(
        pd.Timestamp.now(tz="UTC").timestamp() * 1000
    )

    interval_ms = int(interval) * 60_000

    df = df[
        (df["start_ms"] + interval_ms) <= now_ms
    ]

    return df[
        [
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
            "Turnover"
        ]
    ]


# ==========================================
# TECHNICAL INDICATORS
# ==========================================

def add_indicators(df):

    d = df.copy()

    d["EMA20"] = d["Close"].ewm(
        span=20,
        adjust=False
    ).mean()

    d["EMA50"] = d["Close"].ewm(
        span=50,
        adjust=False
    ).mean()

    d["EMA200"] = d["Close"].ewm(
        span=200,
        adjust=False
    ).mean()

    delta = d["Close"].diff()

    gain = delta.clip(lower=0)

    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1/14,
        adjust=False,
        min_periods=14
    ).mean()

    avg_loss = loss.ewm(
        alpha=1/14,
        adjust=False,
        min_periods=14
    ).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)

    d["RSI"] = 100 - (
        100 / (1 + rs)
    )

    d.loc[
        (avg_loss == 0) & (avg_gain > 0),
        "RSI"
    ] = 100

    ema12 = d["Close"].ewm(
        span=12,
        adjust=False
    ).mean()

    ema26 = d["Close"].ewm(
        span=26,
        adjust=False
    ).mean()

    d["MACD"] = ema12 - ema26

    d["MACD_SIGNAL"] = d["MACD"].ewm(
        span=9,
        adjust=False
    ).mean()

    previous_close = d["Close"].shift(1)

    tr = pd.concat(
        [
            d["High"] - d["Low"],
            (d["High"] - previous_close).abs(),
            (d["Low"] - previous_close).abs()
        ],
        axis=1
    ).max(axis=1)

    d["ATR"] = tr.ewm(
        alpha=1/14,
        adjust=False,
        min_periods=14
    ).mean()

    d["VOL_MA20"] = d["Volume"].rolling(20).mean()

    d["VOL_RATIO"] = (
        d["Volume"] /
        d["VOL_MA20"].replace(0, np.nan)
    )

    return d.dropna(
        subset=[
            "EMA200",
            "RSI",
            "MACD_SIGNAL",
            "ATR",
            "VOL_RATIO"
        ]
    )


# ==========================================
# TREND ANALYSIS
# ==========================================

def get_trend(df):

    x = df.iloc[-1]

    if (
        x["Close"] > x["EMA20"]
        and x["EMA20"] > x["EMA50"]
        and x["EMA50"] > x["EMA200"]
    ):
        return "صاعد"

    if (
        x["Close"] < x["EMA20"]
        and x["EMA20"] < x["EMA50"]
        and x["EMA50"] < x["EMA200"]
    ):
        return "هابط"

    return "محايد"


# ==========================================
# SIGNAL ENGINE
# ==========================================

def analyze_symbol(
    symbol,
    sl_atr,
    rr1,
    rr2,
    rr3
):

    d15 = add_indicators(
        get_klines(symbol, "15", 300)
    )

    d1 = add_indicators(
        get_klines(symbol, "60", 300)
    )

    d4 = add_indicators(
        get_klines(symbol, "240", 300)
    )

    if min(len(d15), len(d1), len(d4)) < 5:
        return None

    x = d15.iloc[-1]

    trend15 = get_trend(d15)
    trend1 = get_trend(d1)
    trend4 = get_trend(d4)

    long_score = 0
    short_score = 0

    if trend4 == "صاعد":
        long_score += 25

    if trend4 == "هابط":
        short_score += 25

    if trend1 == "صاعد":
        long_score += 25

    if trend1 == "هابط":
        short_score += 25

    if x["Close"] > x["EMA20"]:
        long_score += 10

    if x["Close"] < x["EMA20"]:
        short_score += 10

    if 50 < x["RSI"] < 70:
        long_score += 10

    if 30 < x["RSI"] < 50:
        short_score += 10

    if x["MACD"] > x["MACD_SIGNAL"]:
        long_score += 10

    if x["MACD"] < x["MACD_SIGNAL"]:
        short_score += 10

    if x["VOL_RATIO"] >= 1.5:

        if x["Close"] > x["Open"]:
            long_score += 10

        elif x["Close"] < x["Open"]:
            short_score += 10

    previous_high = d15["High"].iloc[-21:-1].max()

    previous_low = d15["Low"].iloc[-21:-1].min()

    if x["Close"] > previous_high:
        long_score += 10

    if x["Close"] < previous_low:
        short_score += 10

    signal = "WAIT"
    score = max(long_score, short_score)

    if (
        long_score >= 70
        and long_score > short_score
        and trend4 == "صاعد"
        and trend1 == "صاعد"
    ):
        signal = "LONG"
        score = long_score

    elif (
        short_score >= 70
        and short_score > long_score
        and trend4 == "هابط"
        and trend1 == "هابط"
    ):
        signal = "SHORT"
        score = short_score

    entry = float(x["Close"])
    atr = float(x["ATR"])

    if not np.isfinite(atr) or atr <= 0:
        return None

    if signal == "LONG":

        distance = atr * sl_atr

        sl = entry - distance

        tp1 = entry + distance * rr1

        tp2 = entry + distance * rr2

        tp3 = entry + distance * rr3

    elif signal == "SHORT":

        distance = atr * sl_atr

        sl = entry + distance

        tp1 = entry - distance * rr1

        tp2 = entry - distance * rr2

        tp3 = entry - distance * rr3

    else:

        sl = np.nan
        tp1 = np.nan
        tp2 = np.nan
        tp3 = np.nan

    return {
        "symbol": symbol,
        "signal": signal,
        "score": int(score),
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rsi": float(x["RSI"]),
        "atr": atr,
        "volume_ratio": float(x["VOL_RATIO"]),
        "trend15": trend15,
        "trend1": trend1,
        "trend4": trend4,
        "chart": d15
    }


def fmt_price(value):

    if pd.isna(value):
        return "—"

    return f"{value:,.8g}"


# ==========================================
# SIDEBAR SETTINGS
# ==========================================

st.sidebar.header("⚙️ إعدادات التحليل")

mode = st.sidebar.radio(
    "وضع التشغيل",
    [
        "تحليل عملة",
        "ماسح العملات"
    ]
)

min_score = st.sidebar.slider(
    "الحد الأدنى لقوة الإشارة",
    60, 100, 70
)

sl_atr = st.sidebar.slider(
    "وقف الخسارة ATR",
    0.5, 3.0, 1.5, 0.1
)

rr1 = st.sidebar.number_input(
    "الهدف الأول R",
    0.5, 5.0, 1.0
)

rr2 = st.sidebar.number_input(
    "الهدف الثاني R",
    1.0, 8.0, 2.0
)

rr3 = st.sidebar.number_input(
    "الهدف الثالث R",
    1.5, 12.0, 3.0
)

capital = st.sidebar.number_input(
    "رأس المال بالدولار",
    min_value=10.0,
    value=1000.0,
    step=100.0
)

risk_pct = st.sidebar.slider(
    "المخاطرة %",
    0.1, 5.0, 1.0, 0.1
)

leverage = st.sidebar.number_input(
    "الرافعة للتقدير فقط",
    1, 125, 5
)


# ==========================================
# SINGLE COIN ANALYSIS
# ==========================================

if mode == "تحليل عملة":

    symbol = st.sidebar.text_input(
        "رمز العقد",
        "BTCUSDT"
    ).strip().upper()

    if st.button(
        "🔍 تحليل الآن",
        type="primary",
        use_container_width=True
    ):

        if not symbol.endswith("USDT"):

            st.error(
                "أدخل رمزاً مثل BTCUSDT أو ETHUSDT"
            )

        else:

            try:

                with st.spinner(
                    "جاري تحميل البيانات وتحليل السوق..."
                ):

                    result = analyze_symbol(
                        symbol,
                        sl_atr,
                        rr1,
                        rr2,
                        rr3
                    )

                if result is None:

                    st.warning(
                        "البيانات غير كافية."
                    )

                else:

                    c1, c2, c3, c4 = st.columns(4)

                    c1.metric(
                        "الإشارة",
                        result["signal"]
                    )

                    c2.metric(
                        "قوة الإشارة",
                        f'{result["score"]}/100'
                    )

                    c3.metric(
                        "RSI",
                        f'{result["rsi"]:.1f}'
                    )

                    c4.metric(
                        "حجم التداول",
                        f'{result["volume_ratio"]:.2f}x'
                    )

                    t1, t2, t3 = st.columns(3)

                    t1.metric(
                        "اتجاه 4H",
                        result["trend4"]
                    )

                    t2.metric(
                        "اتجاه 1H",
                        result["trend1"]
                    )

                    t3.metric(
                        "اتجاه 15M",
                        result["trend15"]
                    )

                    if result["signal"] != "WAIT":

                        st.subheader(
                            "🎯 مستويات الصفقة"
                        )

                        p1, p2, p3, p4, p5 = st.columns(5)

                        p1.metric(
                            "الدخول",
                            fmt_price(result["entry"])
                        )

                        p2.metric(
                            "وقف الخسارة",
                            fmt_price(result["sl"])
                        )

                        p3.metric(
                            "TP1",
                            fmt_price(result["tp1"])
                        )

                        p4.metric(
                            "TP2",
                            fmt_price(result["tp2"])
                        )

                        p5.metric(
                            "TP3",
                            fmt_price(result["tp3"])
                        )

                        risk_cash = (
                            capital * risk_pct / 100
                        )

                        risk_unit = abs(
                            result["entry"] - result["sl"]
                        )

                        qty = (
                            risk_cash / risk_unit
                            if risk_unit else 0
                        )

                        notional = qty * result["entry"]

                        margin = notional / leverage

                        st.info(
                            f"المخاطرة: ${risk_cash:,.2f} | "
                            f"الكمية التقديرية: {qty:.6g} | "
                            f"القيمة الاسمية: ${notional:,.2f} | "
                            f"الهامش التقريبي: ${margin:,.2f}"
                        )

                    else:

                        st.warning(
                            "لا توجد إشارة دخول مكتملة حالياً."
                        )

                    # CHART

                    chart = result["chart"].tail(150)

                    fig = go.Figure()

                    fig.add_trace(
                        go.Candlestick(
                            x=chart.index,
                            open=chart["Open"],
                            high=chart["High"],
                            low=chart["Low"],
                            close=chart["Close"],
                            name="15M"
                        )
                    )

                    for col in [
                        "EMA20",
                        "EMA50",
                        "EMA200"
                    ]:

                        fig.add_trace(
                            go.Scatter(
                                x=chart.index,
                                y=chart[col],
                                mode="lines",
                                name=col
                            )
                        )

                    if result["signal"] != "WAIT":

                        levels = [
                            (result["sl"], "SL"),
                            (result["tp1"], "TP1"),
                            (result["tp2"], "TP2"),
                            (result["tp3"], "TP3")
                        ]

                        for price, label in levels:

                            fig.add_hline(
                                y=price,
                                line_dash="dash",
                                annotation_text=label
                            )

                    fig.update_layout(
                        template="plotly_dark",
                        height=590,
                        xaxis_rangeslider_visible=False
                    )

                    st.plotly_chart(
                        fig,
                        use_container_width=True
                    )

                    st.caption(
                        f"آخر شمعة مغلقة: {chart.index[-1]}"
                    )

            except Exception as exc:

                st.error(str(exc))


# ==========================================
# MARKET SCANNER
# ==========================================

else:

    st.subheader(
        "🔎 ماسح عقود Bybit USDT"
    )

    scan_count = st.sidebar.slider(
        "عدد العملات للفحص",
        5, 30, 10
    )

    if st.button(
        "🚀 ابدأ مسح السوق",
        type="primary",
        use_container_width=True
    ):

        try:

            with st.spinner(
                "تحميل قائمة العملات..."
            ):

                tickers = get_linear_tickers()

                tickers = tickers.sort_values(
                    "turnover24h",
                    ascending=False
                ).head(scan_count)

            results = []

            progress = st.progress(0)

            status = st.empty()

            total = max(len(tickers), 1)

            for i, row in enumerate(
                tickers.itertuples(index=False),
                start=1
            ):

                symbol = row.symbol

                status.caption(
                    f"فحص {symbol} — {i}/{total}"
                )

                try:

                    item = analyze_symbol(
                        symbol,
                        sl_atr,
                        rr1,
                        rr2,
                        rr3
                    )

                    if (
                        item
                        and item["signal"] != "WAIT"
                        and item["score"] >= min_score
                    ):

                        results.append(item)

                except MarketDataError:

                    raise

                except Exception:

                    pass

                progress.progress(i / total)

                time.sleep(0.12)

            progress.empty()

            status.empty()

            if results:

                results.sort(
                    key=lambda item: item["score"],
                    reverse=True
                )

                table = pd.DataFrame([

                    {
                        "العقد": item["symbol"],
                        "الإشارة": item["signal"],
                        "القوة": item["score"],
                        "السعر": item["entry"],
                        "RSI": round(item["rsi"], 1),
                        "الحجم": round(
                            item["volume_ratio"], 2
                        ),
                        "اتجاه 4H": item["trend4"],
                        "اتجاه 1H": item["trend1"]
                    }

                    for item in results

                ])

                st.success(
                    f"تم العثور على {len(results)} إشارة."
                )

                st.dataframe(
                    table,
                    use_container_width=True,
                    hide_index=True
                )

                selected = st.selectbox(
                    "اختر عقداً لعرض مستوياته",
                    [
                        item["symbol"]
                        for item in results
                    ]
                )

                chosen = next(
                    item for item in results
                    if item["symbol"] == selected
                )

                a, b, c, d, e = st.columns(5)

                a.metric(
                    "الدخول",
                    fmt_price(chosen["entry"])
                )

                b.metric(
                    "وقف الخسارة",
                    fmt_price(chosen["sl"])
                )

                c.metric(
                    "TP1",
                    fmt_price(chosen["tp1"])
                )

                d.metric(
                    "TP2",
                    fmt_price(chosen["tp2"])
                )

                e.metric(
                    "TP3",
                    fmt_price(chosen["tp3"])
                )

            else:

                st.warning(
                    "لم تظهر إشارات مطابقة للشروط."
                )

        except Exception as exc:

            st.error(str(exc))


# ==========================================
# FOOTER
# ==========================================

st.divider()

st.caption(
    "GALEIC FUTURES PRO | "
    "Data Provider: Bybit V5 API | "
    "تحليل فني فقط، لا يوجد تنفيذ تلقائي للصفقات."
    )
