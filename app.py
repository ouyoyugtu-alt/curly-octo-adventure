import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

st.set_page_config(
    page_title="فلتر إشارات 1h بـ 4h - العقود الآجلة",
    page_icon="📊",
    layout="wide",
)

# --- تنسيق RTL وتحسين العرض على الجوال ---
st.markdown("""
<style>
    .stApp, .stMarkdown, .stSelectbox, .stSlider, .stNumberInput, .stTextInput {
        direction: rtl;
        text-align: right;
    }
    @media (max-width: 768px) {
        [data-testid="stSidebar"] {
            width: 85vw !important;
            min-width: 85vw !important;
        }
    }
</style>
""", unsafe_allow_html=True)

st.title("📊 فلتر إشارات فريم 1 ساعة بناءً على فريم 4 ساعات")
st.caption(
    "فريم 4h يحدد الاتجاه العام عبر EMA، وفريم 1h يولّد الإشارة ويحسب الوقف والأهداف عبر ATR — "
    "أداة تحليلية لإدارة المخاطر وليست توصية أو ضماناً للربح."
)

# --- الشريط الجانبي: البحث والإعدادات ---
st.sidebar.header("⚙️ البحث والإعدادات")

quick_picks = {
    "بحث حر (اكتب أي رمز بالأسفل)": "",
    "بيتكوين (BTC-USD)": "BTC-USD",
    "إيثيريوم (ETH-USD)": "ETH-USD",
    "سولانا (SOL-USD)": "SOL-USD",
    "الذهب الآجل (GC=F)": "GC=F",
    "النفط الخام الآجل (CL=F)": "CL=F",
    "عقود S&P 500 الآجلة (ES=F)": "ES=F",
}

selected_quick = st.sidebar.selectbox("اختيار سريع", list(quick_picks.keys()))
default_sym = quick_picks[selected_quick] if quick_picks[selected_quick] else "BTC-USD"

raw_query = st.sidebar.text_input(
    "ابحث عن عملة أو رمز",
    value=default_sym,
    placeholder="مثال: BTC أو SOL-USD أو GC=F",
).strip().upper()

if raw_query and "-" not in raw_query and "=" not in raw_query and not raw_query.endswith("USD"):
    symbol = f"{raw_query}-USD"
else:
    symbol = raw_query or "BTC-USD"

st.sidebar.caption(f"الرمز الفعلي: `{symbol}`")

period = st.sidebar.selectbox("فترة البيانات التاريخية", ["1mo", "3mo", "6mo", "1y"], index=1)

st.sidebar.subheader("🧭 إعدادات فلتر 4h و1h")
ema_4h_period = st.sidebar.slider("فترة EMA على فريم 4h", 10, 100, 20, 1)
breakout_lookback = st.sidebar.slider("عدد شموع القمة/القاع للكسر على 1h", 2, 10, 3, 1)

st.sidebar.subheader("🛡️ وقف الخسارة والأهداف وإدارة المخاطر")
atr_1h_period = st.sidebar.slider("فترة ATR على فريم 1h", 7, 28, 14, 1)
sl_atr_mult = st.sidebar.slider("مضاعف وقف الخسارة (× ATR)", 0.5, 3.0, 1.5, 0.1)
tp1_rr = st.sidebar.slider("نسبة الهدف الأول (TP1 R:R)", 1.0, 3.0, 1.5, 0.1)
tp2_rr = st.sidebar.slider("نسبة الهدف الثاني (TP2 R:R)", 2.0, 6.0, 3.0, 0.2)
account_size = st.sidebar.number_input("رأس المال ($)", min_value=100.0, value=10000.0, step=500.0)
risk_pct = st.sidebar.slider("مخاطرة الصفقة (%)", 0.25, 5.0, 1.0, 0.25)

use_demo = st.sidebar.checkbox("استخدام بيانات تجريبية إذا لم تتوفر بيانات حية", value=True)


def generate_demo_1h(n=480, seed=42):
    rng = np.random.default_rng(seed)
    dates = pd.date_range(end=pd.Timestamp.now(), periods=n, freq="h")
    close = 61000.0 + np.cumsum(rng.normal(0, 280, size=n))
    high = close + rng.uniform(80, 420, size=n)
    low = close - rng.uniform(80, 420, size=n)
    open_p = np.roll(close, 1)
    open_p[0] = close[0]
    volume = rng.integers(500, 3000, size=n).astype(float)
    return pd.DataFrame({
        "Open": open_p,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": volume,
    }, index=dates)


@st.cache_data(ttl=120)
def load_1h_data(sym: str, per: str):
    df = yf.download(sym, period=per, interval="1h", progress=False, auto_adjust=False)
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna().sort_index()
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_convert(None)
    return df


def build_4h_from_1h(df_1h: pd.DataFrame) -> pd.DataFrame:
    agg = {
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    }
    df_4h = df_1h.resample("4h", label="left", closed="left").agg(agg).dropna()
    return df_4h


def filter_1h_with_4h(df_1h: pd.DataFrame, df_4h: pd.DataFrame) -> pd.DataFrame:
    d1 = df_1h.copy().sort_index()
    d4 = df_4h.copy().sort_index()

    d4["EMA_4H"] = d4["Close"].ewm(span=ema_4h_period, adjust=False).mean()
    d4["Trend_4H"] = np.where(
        d4["Close"] > d4["EMA_4H"], "BULLISH",
        np.where(d4["Close"] < d4["EMA_4H"], "BEARISH", "NEUTRAL")
    )

    d1 = pd.merge_asof(
        d1,
        d4[["EMA_4H", "Trend_4H"]],
        left_index=True,
        right_index=True,
        direction="backward",
    )

    prev_close = d1["Close"].shift(1)
    tr = pd.concat([
        d1["High"] - d1["Low"],
        (d1["High"] - prev_close).abs(),
        (d1["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    d1["ATR_1H"] = tr.rolling(atr_1h_period).mean()

    prev_high = d1["High"].shift(1).rolling(breakout_lookback).max()
    prev_low = d1["Low"].shift(1).rolling(breakout_lookback).min()

    raw_long_1h = (d1["Close"] > d1["Open"]) & (d1["Close"] > prev_high)
    raw_short_1h = (d1["Close"] < d1["Open"]) & (d1["Close"] < prev_low)

    d1["Filtered_Signal"] = np.where(
        raw_long_1h & (d1["Trend_4H"] == "BULLISH"), "شراء (Long)",
        np.where(raw_short_1h & (d1["Trend_4H"] == "BEARISH"), "بيع (Short)", "تجاهل")
    )

    risk_dist = d1["ATR_1H"] * sl_atr_mult
    d1["Entry"] = np.where(d1["Filtered_Signal"] != "تجاهل", d1["Close"], np.nan)

    d1["Stop_Loss"] = np.where(
        d1["Filtered_Signal"] == "شراء (Long)", d1["Entry"] - risk_dist,
        np.where(d1["Filtered_Signal"] == "بيع (Short)", d1["Entry"] + risk_dist, np.nan)
    )

    d1["TP1"] = np.where(
        d1["Filtered_Signal"] == "شراء (Long)", d1["Entry"] + (risk_dist * tp1_rr),
        np.where(d1["Filtered_Signal"] == "بيع (Short)", d1["Entry"] - (risk_dist * tp1_rr), np.nan)
    )

    d1["TP2"] = np.where(
        d1["Filtered_Signal"] == "شراء (Long)", d1["Entry"] + (risk_dist * tp2_rr),
        np.where(d1["Filtered_Signal"] == "بيع (Short)", d1["Entry"] - (risk_dist * tp2_rr), np.nan)
    )

    d1["Risk_Per_Unit"] = (d1["Entry"] - d1["Stop_Loss"]).abs()
    max_loss_dollars = account_size * (risk_pct / 100.0)
    d1["Suggested_Units"] = np.where(
        d1["Risk_Per_Unit"] > 0,
        max_loss_dollars / d1["Risk_Per_Unit"],
        0.0
    )

    return d1.dropna(subset=["ATR_1H", "EMA_4H"])


raw_1h = load_1h_data(symbol, period)
source_label = "بيانات السوق (Yahoo Finance)"

if raw_1h.empty:
    if use_demo:
        raw_1h = generate_demo_1h()
        source_label = "بيانات تجريبية (Demo)"
    else:
        st.error(f"تعذر جلب بيانات `1h` للرمز `{symbol}`.")
        st.stop()

df_4h = build_4h_from_1h(raw_1h)
df_filtered = filter_1h_with_4h(raw_1h, df_4h)
active_signals = df_filtered[df_filtered["Filtered_Signal"] != "تجاهل"].copy()

latest_trend_4h = df_filtered["Trend_4H"].iloc[-1] if not df_filtered.empty else "غير محدد"
trend_ar = "صاعد (BULLISH)" if latest_trend_4h == "BULLISH" else ("هابط (BEARISH)" if latest_trend_4h == "BEARISH" else "محايد")

st.info(
    f"الرمز: **`{symbol}`** | المصدر: **{source_label}** | "
    f"اتجاه 4h الحالي: **{trend_ar}** | الإشارات المفلترة على 1h: **{len(active_signals)}**"
)

# --- عرض أحدث إشارة مفلترة ---
if not active_signals.empty:
    last_sig = active_signals.iloc[-1]
    st.subheader("📌 أحدث إشارة 1h متوافقة مع اتجاه 4h")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("الإشارة", str(last_sig["Filtered_Signal"]))
    c2.metric("الدخول", f"{last_sig['Entry']:.2f}")
    c3.metric("وقف الخسارة (SL)", f"{last_sig['Stop_Loss']:.2f}")
    c4.metric(f"الهدف 1 ({tp1_rr}R)", f"{last_sig['TP1']:.2f}")
    c5.metric(f"الهدف 2 ({tp2_rr}R)", f"{last_sig['TP2']:.2f}")

    max_loss = account_size * (risk_pct / 100.0)
    st.markdown(
        f"- **مسافة الوقف:** `{last_sig['Risk_Per_Unit']:.2f}` | "
        f"**الحد الأقصى للمخاطرة:** `${max_loss:,.2f}` | "
        f"**الحجم التقديري:** `{last_sig['Suggested_Units']:.4f}`"
    )
else:
    st.warning("لا توجد إشارات متوافقة بين 4h و1h بالإعدادات الحالية؛ جرّب تعديل نافذة الكسر أو فترة EMA.")

# --- الرسم البياني لفريم 1h مع EMA فريم 4h ---
st.subheader("📈 شارت 1 ساعة مع خط اتجاه 4 ساعات (EMA)")

fig = go.Figure()
fig.add_trace(go.Candlestick(
    x=df_filtered.index,
    open=df_filtered["Open"],
    high=df_filtered["High"],
    low=df_filtered["Low"],
    close=df_filtered["Close"],
    name="شموع 1h"
))

fig.add_trace(go.Scatter(
    x=df_filtered.index,
    y=df_filtered["EMA_4H"],
    mode="lines",
    line=dict(color="orange", width=2),
    name=f"EMA {ema_4h_period} (فريم 4h)"
))

if not active_signals.empty:
    longs = active_signals[active_signals["Filtered_Signal"] == "شراء (Long)"]
    shorts = active_signals[active_signals["Filtered_Signal"] == "بيع (Short)"]

    fig.add_trace(go.Scatter(
        x=longs.index,
        y=longs["Low"] * 0.998,
        mode="markers",
        marker=dict(symbol="triangle-up", size=12, color="lime"),
        name="شراء مفلتر"
    ))

    fig.add_trace(go.Scatter(
        x=shorts.index,
        y=shorts["High"] * 1.002,
        mode="markers",
        marker=dict(symbol="triangle-down", size=12, color="red"),
        name="بيع مفلتر"
    ))

    last_row = active_signals.iloc[-1]
    fig.add_hline(y=last_row["Stop_Loss"], line_dash="dash", line_color="red", annotation_text="SL")
    fig.add_hline(y=last_row["TP1"], line_dash="dot", line_color="green", annotation_text="TP1")
    fig.add_hline(y=last_row["TP2"], line_dash="dot", line_color="cyan", annotation_text="TP2")

fig.update_layout(height=520, xaxis_rangeslider_visible=False, template="plotly_dark")
st.plotly_chart(fig, use_container_width=True)

# --- جدول الإشارات المفلترة ---
if not active_signals.empty:
    st.subheader("📋 سجل الإشارات المفلترة")
    out_df = pd.DataFrame({
        "الوقت": active_signals.index.strftime("%Y-%m-%d %H:%M"),
        "اتجاه 4h": active_signals["Trend_4H"].values,
        "إشارة 1h": active_signals["Filtered_Signal"].values,
        "الدخول": active_signals["Entry"].round(2).values,
        "وقف الخسارة": active_signals["Stop_Loss"].round(2).values,
        "الهدف 1": active_signals["TP1"].round(2).values,
        "الهدف 2": active_signals["TP2"].round(2).values,
        "حجم مقترح": active_signals["Suggested_Units"].round(4).values,
    })
    st.dataframe(out_df.iloc[::-1], use_container_width=True, hide_index=True)
