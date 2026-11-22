import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

st.set_page_config(
    page_title="كاشف سيولة الحيتان - العقود الآجلة",
    page_icon="🐋",
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

st.title("🐋 أداة رصد السيولة وحساب الأهداف ووقف الخسارة (العقود الآجلة)")
st.caption(
    "تنبيه: هذه الأداة تحليلية لمساعدتك في رصد قفزات الحجم وبناء إدارة المخاطر؛ وليست توصية استثمارية أو ضماناً للربح."
)

# --- الشريط الجانبي: البحث والإعدادات ---
st.sidebar.header("⚙️ إعدادات الفحص والبحث")

st.sidebar.subheader("🔎 البحث عن عملة أو رمز")
quick_picks = {
    "بحث حر (اكتب أي عملة بالأسفل)": "",
    "بيتكوين (BTC-USD)": "BTC-USD",
    "إيثيريوم (ETH-USD)": "ETH-USD",
    "سولانا (SOL-USD)": "SOL-USD",
    "ريبل (XRP-USD)": "XRP-USD",
    "عقود S&P 500 الآجلة (ES=F)": "ES=F",
    "عقود Nasdaq الآجلة (NQ=F)": "NQ=F",
    "الذهب الآجل (GC=F)": "GC=F",
    "النفط الخام الآجل (CL=F)": "CL=F",
}

selected_quick = st.sidebar.selectbox("اختيار سريع (اختياري)", list(quick_picks.keys()))
default_symbol = quick_picks[selected_quick] if quick_picks[selected_quick] else "BTC-USD"

raw_query = st.sidebar.text_input(
    "اكتب رمز العملة أو الزوج للبحث",
    value=default_symbol,
    placeholder="مثال: SOL أو AVAX-USD أو EURUSD=X",
    help="للعملات الرقمية في Yahoo Finance يمكن كتابة الرمز مثل SOL أو بصيغة SOL-USD"
).strip().upper()

# تنسيق تلقائي إذا كتب المستخدم رمز عملة رقمية بدون لاحقة مثل BTC أو SOL
if raw_query and "-" not in raw_query and "=" not in raw_query and not raw_query.endswith("USD"):
    symbol = f"{raw_query}-USD"
else:
    symbol = raw_query or "BTC-USD"

st.sidebar.caption(f"الرمز الفعلي قيد الفحص: `{symbol}`")

interval = st.sidebar.selectbox("الفاصل الزمني", ["15m", "1h", "4h", "1d"], index=1)
period = st.sidebar.selectbox("فترة البيانات التاريخية", ["5d", "1mo", "3mo", "6mo", "1y"], index=1)

st.sidebar.subheader("🎯 معايير رصد صفقات الحيتان")
vol_multiplier = st.sidebar.slider("مضاعف قفزة الحجم (مقارنة بالمتوسط)", 1.5, 5.0, 2.2, 0.1)
vol_window = st.sidebar.slider("نافذة متوسط الحجم (عدد الشموع)", 10, 50, 20, 1)

st.sidebar.subheader("🛡️ إدارة المخاطر والوقف والأهداف")
atr_period = st.sidebar.slider("فترة مؤشر ATR", 7, 28, 14, 1)
sl_atr_mult = st.sidebar.slider("مضاعف وقف الخسارة (× ATR)", 0.5, 3.0, 1.5, 0.1)
tp1_rr = st.sidebar.slider("نسبة العائد للهدف الأول (R:R)", 1.0, 3.0, 1.5, 0.1)
tp2_rr = st.sidebar.slider("نسبة العائد للهدف الثاني (R:R)", 2.0, 6.0, 3.0, 0.2)
account_size = st.sidebar.number_input("رأس المال ($)", min_value=100.0, value=10000.0, step=500.0)
risk_pct = st.sidebar.slider("نسبة المخاطرة في الصفقة (%)", 0.25, 5.0, 1.0, 0.25)

use_demo = st.sidebar.checkbox("استخدام بيانات تجريبية إذا تعذر الاتصال بالبيانات الحية", value=True)


def generate_demo_data(n=200, seed=42):
    rng = np.random.default_rng(seed)
    dates = pd.date_range(end=pd.Timestamp.now(), periods=n, freq="h")
    close = 2650.0 + np.cumsum(rng.normal(0, 8, size=n))
    high = close + rng.uniform(2, 14, size=n)
    low = close - rng.uniform(2, 14, size=n)
    open_p = np.roll(close, 1)
    open_p[0] = close[0]
    volume = rng.integers(800, 3500, size=n).astype(float)

    for idx in [45, 92, 148, 185]:
        if idx < n:
            direction = 1 if idx % 2 == 0 else -1
            volume[idx] = rng.uniform(7500, 14000)
            close[idx] = open_p[idx] + direction * rng.uniform(12, 26)
            high[idx] = max(open_p[idx], close[idx]) + rng.uniform(2, 8)
            low[idx] = min(open_p[idx], close[idx]) - rng.uniform(2, 8)

    df = pd.DataFrame({
        "Open": open_p,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": volume,
    }, index=dates)
    return df


@st.cache_data(ttl=120)
def load_market_data(sym: str, per: str, inter: str):
    df = yf.download(sym, period=per, interval=inter, progress=False, auto_adjust=False)
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    return df


def analyze_whales(df: pd.DataFrame):
    data = df.copy()
    data["Vol_SMA"] = data["Volume"].rolling(vol_window).mean()
    data["Vol_Ratio"] = data["Volume"] / data["Vol_SMA"].replace(0, np.nan)

    prev_close = data["Close"].shift(1)
    tr = pd.concat([
        data["High"] - data["Low"],
        (data["High"] - prev_close).abs(),
        (data["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    data["ATR"] = tr.rolling(atr_period).mean()

    data["Direction"] = np.where(
        data["Close"] > data["Open"], "شراء (Long)",
        np.where(data["Close"] < data["Open"], "بيع (Short)", "محايد")
    )

    data["Whale_Signal"] = (
        (data["Vol_Ratio"] >= vol_multiplier)
        & (data["Direction"] != "محايد")
        & data["ATR"].notna()
    )

    risk_dist = data["ATR"] * sl_atr_mult
    data["Entry"] = data["Close"]

    data["Stop_Loss"] = np.where(
        data["Direction"] == "شراء (Long)",
        data["Entry"] - risk_dist,
        np.where(data["Direction"] == "بيع (Short)", data["Entry"] + risk_dist, np.nan)
    )

    data["TP1"] = np.where(
        data["Direction"] == "شراء (Long)",
        data["Entry"] + (risk_dist * tp1_rr),
        np.where(data["Direction"] == "بيع (Short)", data["Entry"] - (risk_dist * tp1_rr), np.nan)
    )

    data["TP2"] = np.where(
        data["Direction"] == "شراء (Long)",
        data["Entry"] + (risk_dist * tp2_rr),
        np.where(data["Direction"] == "بيع (Short)", data["Entry"] - (risk_dist * tp2_rr), np.nan)
    )

    data["Risk_Per_Unit"] = (data["Entry"] - data["Stop_Loss"]).abs()
    max_loss_dollars = account_size * (risk_pct / 100.0)
    data["Suggested_Units"] = np.where(
        data["Risk_Per_Unit"] > 0,
        max_loss_dollars / data["Risk_Per_Unit"],
        0.0
    )

    return data.dropna(subset=["ATR", "Vol_SMA"])


raw_df = load_market_data(symbol, period, interval)
source_label = "بيانات السوق (Yahoo Finance)"

if raw_df.empty:
    if use_demo:
        raw_df = generate_demo_data()
        source_label = "بيانات تجريبية (Demo)"
    else:
        st.error(f"تعذر جلب البيانات للرمز `{symbol}`. جرّب رمزاً آخر أو فعّل البيانات التجريبية من الشريط الجانبي.")
        st.stop()

df_analyzed = analyze_whales(raw_df)
signals = df_analyzed[df_analyzed["Whale_Signal"]].copy()

st.info(
    f"الرمز: **`{symbol}`** | المصدر: **{source_label}** | "
    f"الشموع المحللة: **{len(df_analyzed)}** | إشارات الحيتان: **{len(signals)}**"
)

# --- عرض أحدث إشارة حوت ---
if not signals.empty:
    latest = signals.iloc[-1]
    st.subheader("📌 أحدث إشارة مرصودة ومستويات المخاطرة والأهداف")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("نوع الإشارة", str(latest["Direction"]))
    c2.metric("سعر الدخول التقريبي", f"{latest['Entry']:.4f}")
    c3.metric("وقف الخسارة (SL)", f"{latest['Stop_Loss']:.4f}")
    c4.metric(f"الهدف الأول (TP1 - {tp1_rr}R)", f"{latest['TP1']:.4f}")
    c5.metric(f"الهدف الثاني (TP2 - {tp2_rr}R)", f"{latest['TP2']:.4f}")

    risk_amount = account_size * (risk_pct / 100.0)
    st.markdown(
        f"- **مضاعف الحجم:** `{latest['Vol_Ratio']:.2f}x` من متوسط آخر `{vol_window}` شموع\n"
        f"- **قيمة ATR الحالية:** `{latest['ATR']:.4f}` | **مسافة الوقف:** `{latest['Risk_Per_Unit']:.4f}`\n"
        f"- **الحد الأقصى للمخاطرة في الصفقة:** `${risk_amount:,.2f}` | **حجم الوحدات/العقود التقديري:** `{latest['Suggested_Units']:.2f}`"
    )
else:
    st.warning("لم يتم رصد إشارات حيتان بالمعايير الحالية. حاول خفض (مضاعف قفزة الحجم) أو تغيير الفاصل الزمني.")

# --- الرسم البياني التفاعلي ---
st.subheader("📈 الرسم البياني وإشارات الحجم")

fig = go.Figure()

fig.add_trace(go.Candlestick(
    x=df_analyzed.index,
    open=df_analyzed["Open"],
    high=df_analyzed["High"],
    low=df_analyzed["Low"],
    close=df_analyzed["Close"],
    name="السعر"
))

if not signals.empty:
    long_sig = signals[signals["Direction"] == "شراء (Long)"]
    short_sig = signals[signals["Direction"] == "بيع (Short)"]

    fig.add_trace(go.Scatter(
        x=long_sig.index,
        y=long_sig["Low"] * 0.998,
        mode="markers",
        marker=dict(symbol="triangle-up", size=12, color="green"),
        name="إشارة شراء (حجم مرتفع)"
    ))

    fig.add_trace(go.Scatter(
        x=short_sig.index,
        y=short_sig["High"] * 1.002,
        mode="markers",
        marker=dict(symbol="triangle-down", size=12, color="red"),
        name="إشارة بيع (حجم مرتفع)"
    ))

    last_row = signals.iloc[-1]
    fig.add_hline(y=last_row["Stop_Loss"], line_dash="dash", line_color="red", annotation_text="SL")
    fig.add_hline(y=last_row["TP1"], line_dash="dot", line_color="green", annotation_text="TP1")
    fig.add_hline(y=last_row["TP2"], line_dash="dot", line_color="blue", annotation_text="TP2")

fig.update_layout(
    height=520,
    xaxis_rangeslider_visible=False,
    template="plotly_dark"
)
st.plotly_chart(fig, use_container_width=True)

# --- جدول الإشارات التاريخية ---
if not signals.empty:
    st.subheader("📋 سجل الإشارات المرصودة")
    table_df = pd.DataFrame({
        "الوقت": signals.index.strftime("%Y-%m-%d %H:%M"),
        "الاتجاه": signals["Direction"].values,
        "مضاعف الحجم": signals["Vol_Ratio"].round(2).values,
        "الدخول": signals["Entry"].round(4).values,
        "وقف الخسارة": signals["Stop_Loss"].round(4).values,
        "الهدف 1": signals["TP1"].round(4).values,
        "الهدف 2": signals["TP2"].round(4).values,
        "حجم مقترح": signals["Suggested_Units"].round(2).values,
    })
    st.dataframe(table_df.iloc[::-1], use_container_width=True, hide_index=True)
