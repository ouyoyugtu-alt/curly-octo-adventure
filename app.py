import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go

from datetime import datetime

# =====================================
# GALEIC FUTURES PRO
# Binance USDT-M Futures Analyzer
# =====================================

API = "https://fapi.binance.com"

st.set_page_config(
    page_title="GALEIC FUTURES PRO",
    page_icon="🚀",
    layout="wide"
)

st.markdown("""
<style>
.stApp {
    background: #080d18;
    color: white;
    direction: rtl;
}
section[data-testid="stSidebar"] {
    background: #101827;
}
.metric-box {
    background: #111c2e;
    padding: 18px;
    border-radius: 12px;
    border: 1px solid #263650;
    text-align: center;
}
</style>
""", unsafe_allow_html=True)

st.title("🚀 GALEIC FUTURES PRO")
st.caption("Advanced Binance Futures Analysis System")

# =====================================
# API FUNCTIONS
# =====================================

@st.cache_data(ttl=15)
def get_server_time():
    r = requests.get(API + "/fapi/v1/time", timeout=10)
    r.raise_for_status()
    return r.json()["serverTime"]


@st.cache_data(ttl=60)
def get_symbols():

    r = requests.get(
        API + "/fapi/v1/exchangeInfo",
        timeout=15
    )

    r.raise_for_status()

    data = r.json()

    return [
        x["symbol"]
        for x in data["symbols"]
        if x["quoteAsset"] == "USDT"
        and x["contractType"] == "PERPETUAL"
        and x["status"] == "TRADING"
    ]


@st.cache_data(ttl=15)
def get_tickers():

    r = requests.get(
        API + "/fapi/v1/ticker/24hr",
        timeout=15
    )

    r.raise_for_status()

    return pd.DataFrame(r.json())


@st.cache_data(ttl=20)
def get_klines(symbol, interval, limit=300):

    r = requests.get(
        API + "/fapi/v1/klines",
        params={
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        },
        timeout=15
    )

    r.raise_for_status()

    data = r.json()

    columns = [
        "time", "Open", "High", "Low",
        "Close", "Volume", "close_time",
        "quote_volume", "trades",
        "taker_buy_volume",
        "taker_buy_quote", "ignore"
    ]

    df = pd.DataFrame(data, columns=columns)

    for col in [
        "Open", "High", "Low",
        "Close", "Volume"
    ]:
        df[col] = pd.to_numeric(df[col])

    df["time"] = pd.to_datetime(
        df["time"], unit="ms"
    )

    # حذف الشمعة التي لم تغلق بعد
    server_time = get_server_time()

    df = df[
        df["close_time"].astype("int64")
        < server_time
    ].copy()

    df.set_index("time", inplace=True)

    return df


# =====================================
# INDICATORS
# =====================================

def indicators(df):

    d = df.copy()

    d["EMA20"] = d.Close.ewm(
        span=20, adjust=False
    ).mean()

    d["EMA50"] = d.Close.ewm(
        span=50, adjust=False
    ).mean()

    d["EMA200"] = d.Close.ewm(
        span=200, adjust=False
    ).mean()

    delta = d.Close.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1/14, adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=1/14, adjust=False
    ).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)

    d["RSI"] = 100 - (100 / (1 + rs))

    ema12 = d.Close.ewm(
        span=12, adjust=False
    ).mean()

    ema26 = d.Close.ewm(
        span=26, adjust=False
    ).mean()

    d["MACD"] = ema12 - ema26

    d["MACD_SIGNAL"] = d.MACD.ewm(
        span=9, adjust=False
    ).mean()

    prev = d.Close.shift(1)

    tr = pd.concat([
        d.High - d.Low,
        (d.High - prev).abs(),
        (d.Low - prev).abs()
    ], axis=1).max(axis=1)

    d["ATR"] = tr.ewm(
        alpha=1/14, adjust=False
    ).mean()

    d["VOL_MA"] = d.Volume.rolling(20).mean()

    d["VOL_RATIO"] = (
        d.Volume / d.VOL_MA.replace(0, np.nan)
    )

    return d.dropna()


# =====================================
# TREND ANALYSIS
# =====================================

def get_trend(df):

    x = df.iloc[-1]

    if (
        x.Close > x.EMA20
        and x.EMA20 > x.EMA50
        and x.EMA50 > x.EMA200
    ):
        return "BULLISH"

    if (
        x.Close < x.EMA20
        and x.EMA20 < x.EMA50
        and x.EMA50 < x.EMA200
    ):
        return "BEARISH"

    return "NEUTRAL"


# =====================================
# SIGNAL ENGINE
# =====================================

def analyze(symbol):

    d15 = indicators(
        get_klines(symbol, "15m")
    )

    d1 = indicators(
        get_klines(symbol, "1h")
    )

    d4 = indicators(
        get_klines(symbol, "4h")
    )

    if min(len(d15), len(d1), len(d4)) < 30:
        return None

    a = d15.iloc[-1]
    h1 = d1.iloc[-1]
    h4 = d4.iloc[-1]

    trend15 = get_trend(d15)
    trend1 = get_trend(d1)
    trend4 = get_trend(d4)

    score_long = 0
    score_short = 0

    # الاتجاه 4H
    if trend4 == "BULLISH":
        score_long += 25

    if trend4 == "BEARISH":
        score_short += 25

    # الاتجاه 1H
    if trend1 == "BULLISH":
        score_long += 25

    if trend1 == "BEARISH":
        score_short += 25

    # EMA 15M
    if a.Close > a.EMA20:
        score_long += 10

    if a.Close < a.EMA20:
        score_short += 10

    # RSI
    if 50 < a.RSI < 70:
        score_long += 10

    if 30 < a.RSI < 50:
        score_short += 10

    # MACD
    if a.MACD > a.MACD_SIGNAL:
        score_long += 10

    if a.MACD < a.MACD_SIGNAL:
        score_short += 10

    # Volume
    if a.VOL_RATIO >= 1.5:
        if a.Close > a.Open:
            score_long += 10

        elif a.Close < a.Open:
            score_short += 10

    # اختراق القمة أو القاع السابق
    previous_high = d15.High.iloc[-21:-1].max()
    previous_low = d15.Low.iloc[-21:-1].min()

    if a.Close > previous_high:
        score_long += 10

    if a.Close < previous_low:
        score_short += 10

    # اختيار الإشارة
    if score_long >= 70 and score_long > score_short:

        signal = "LONG"
        score = score_long

    elif score_short >= 70 and score_short > score_long:

        signal = "SHORT"
        score = score_short

    else:

        signal = "WAIT"
        score = max(score_long, score_short)

    entry = float(a.Close)
    atr = float(a.ATR)

    if not np.isfinite(atr) or atr <= 0:
        return None

    sl_distance = atr * 1.5

    if signal == "LONG":

        sl = entry - sl_distance

        tp1 = entry + sl_distance
        tp2 = entry + sl_distance * 2
        tp3 = entry + sl_distance * 3

    elif signal == "SHORT":

        sl = entry + sl_distance

        tp1 = entry - sl_distance
        tp2 = entry - sl_distance * 2
        tp3 = entry - sl_distance * 3

    else:

        sl = np.nan
        tp1 = np.nan
        tp2 = np.nan
        tp3 = np.nan

    return {
        "symbol": symbol,
        "signal": signal,
        "score": score,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rsi": float(a.RSI),
        "volume": float(a.VOL_RATIO),
        "atr": atr,
        "trend4": trend4,
        "trend1": trend1,
        "trend15": trend15,
        "chart": d15
    }


# =====================================
# SIDEBAR
# =====================================

st.sidebar.title("⚙️ إعدادات النظام")

mode = st.sidebar.radio(
    "نوع التحليل",
    ["تحليل عملة واحدة", "ماسح العملات"]
)

min_score = st.sidebar.slider(
    "أقل قوة للإشارة",
    60, 100, 70
)

risk_percent = st.sidebar.slider(
    "نسبة المخاطرة %",
    0.25, 5.0, 1.0
)

capital = st.sidebar.number_input(
    "رأس المال بالدولار",
    min_value=10.0,
    value=1000.0
)

leverage = st.sidebar.slider(
    "الرافعة المالية",
    1, 50, 5
)


# =====================================
# SINGLE COIN
# =====================================

if mode == "تحليل عملة واحدة":

    symbol = st.sidebar.text_input(
        "رمز العملة",
        "BTCUSDT"
    ).strip().upper()

    if st.button("🔍 ابدأ التحليل", use_container_width=True):

        try:

            with st.spinner("جاري تحليل السوق..."):

                result = analyze(symbol)

            if result is None:
                st.warning("لا توجد بيانات كافية.")
                st.stop()

            st.subheader(f"📊 تحليل {symbol}")

            color = (
                "🟢" if result["signal"] == "LONG"
                else "🔴" if result["signal"] == "SHORT"
                else "🟡"
            )

            c1, c2, c3 = st.columns(3)

            c1.metric(
                "الإشارة",
                color + " " + result["signal"]
            )

            c2.metric(
                "قوة الإشارة",
                f'{result["score"]}/100'
            )

            c3.metric(
                "RSI",
                f'{result["rsi"]:.2f}'
            )

            if result["signal"] != "WAIT":

                st.success("تم اكتشاف فرصة تداول محتملة")

                c1, c2, c3 = st.columns(3)

                c1.metric("Entry", f'{result["entry"]:.6g}')
                c2.metric("Stop Loss", f'{result["sl"]:.6g}')
                c3.metric("ATR", f'{result["atr"]:.6g}')

                c1, c2, c3 = st.columns(3)

                c1.metric("TP1", f'{result["tp1"]:.6g}')
                c2.metric("TP2", f'{result["tp2"]:.6g}')
                c3.metric("TP3", f'{result["tp3"]:.6g}')

                risk_money = capital * risk_percent / 100

                qty = risk_money / abs(
                    result["entry"] - result["sl"]
                )

                notional = qty * result["entry"]

                st.info(
                    f"""
                    مبلغ المخاطرة: ${risk_money:.2f}

                    كمية العملة التقديرية: {qty:.6g}

                    القيمة الاسمية للصفقة: ${notional:.2f}

                    الهامش التقريبي عند رافعة {leverage}x:
                    ${notional / leverage:.2f}
                    """
                )

            else:

                st.warning("لا توجد إشارة دخول مكتملة حالياً.")

            # CHART

            d = result["chart"].tail(120)

            fig = go.Figure()

            fig.add_trace(go.Candlestick(
                x=d.index,
                open=d.Open,
                high=d.High,
                low=d.Low,
                close=d.Close,
                name="15M"
            ))

            for col in ["EMA20", "EMA50", "EMA200"]:

                fig.add_trace(go.Scatter(
                    x=d.index,
                    y=d[col],
                    name=col,
                    mode="lines"
                ))

            if result["signal"] != "WAIT":

                for price, name in [
                    (result["sl"], "SL"),
                    (result["tp1"], "TP1"),
                    (result["tp2"], "TP2"),
                    (result["tp3"], "TP3")
                ]:

                    fig.add_hline(
                        y=price,
                        annotation_text=name,
                        line_dash="dash"
                    )

            fig.update_layout(
                template="plotly_dark",
                height=600,
                xaxis_rangeslider_visible=False
            )

            st.plotly_chart(
                fig,
                use_container_width=True
            )

        except Exception as e:

            st.error(f"خطأ أثناء التحليل: {e}")


# =====================================
# MARKET SCANNER
# =====================================

else:

    st.subheader("🔎 ماسح فرص العقود الآجلة")

    scan_count = st.sidebar.slider(
        "عدد العملات للفحص",
        5, 50, 20
    )

    if st.button("🚀 ابدأ فحص السوق"):

        try:

            with st.spinner("جاري فحص العملات..."):

                symbols = get_symbols()

                tickers = get_tickers()

                tickers = tickers[
                    tickers.symbol.isin(symbols)
                ].copy()

                tickers["quoteVolume"] = pd.to_numeric(
                    tickers["quoteVolume"]
                )

                top = tickers.sort_values(
                    "quoteVolume",
                    ascending=False
                ).head(scan_count)

                results = []

                progress = st.progress(0)

                for i, symbol in enumerate(top.symbol):

                    try:

                        result = analyze(symbol)

                        if result:

                            if (
                                result["signal"] != "WAIT"
                                and result["score"] >= min_score
                            ):

                                results.append(result)

                    except Exception:
                        pass

                    progress.progress(
                        (i + 1) / len(top)
                    )

                progress.empty()

            if results:

                table = pd.DataFrame([
                    {
                        "العملة": x["symbol"],
                        "الإشارة": x["signal"],
                        "القوة": x["score"],
                        "السعر": x["entry"],
                        "RSI": round(x["rsi"], 2),
                        "Volume": round(x["volume"], 2),
                        "الاتجاه 4H": x["trend4"],
                        "الاتجاه 1H": x["trend1"]
                    }
                    for x in results
                ])

                table = table.sort_values(
                    "القوة",
                    ascending=False
                )

                st.success(
                    f"تم العثور على {len(results)} فرصة محتملة"
                )

                st.dataframe(
                    table,
                    use_container_width=True,
                    hide_index=True
                )

                selected = st.selectbox(
                    "اختر عملة لعرض تفاصيلها",
                    table["العملة"].tolist()
                )

                chosen = next(
                    x for x in results
                    if x["symbol"] == selected
                )

                st.json({
                    "Signal": chosen["signal"],
                    "Score": chosen["score"],
                    "Entry": chosen["entry"],
                    "Stop Loss": chosen["sl"],
                    "TP1": chosen["tp1"],
                    "TP2": chosen["tp2"],
                    "TP3": chosen["tp3"]
                })

            else:

                st.warning(
                    "لم يتم العثور على إشارات قوية حالياً."
                )

        except Exception as e:

            st.error(f"فشل فحص السوق: {e}")


st.divider()

st.caption(
    "GALEIC FUTURES PRO | Market Analysis System | "
    "التحليل لا يضمن الربح ولا ينفذ الصفقات تلقائياً."
    )
