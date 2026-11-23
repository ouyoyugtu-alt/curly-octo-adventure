import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go
from datetime import datetime, timezone

# -------------------- إعدادات عامة --------------------
st.set_page_config(
    page_title="GALEIC FUTURES PRO",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

BASE_URL = "https://fapi.binance.com"
INTERVALS = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w"]
INTERVAL_LABELS = {
    "1m": "1 دقيقة", "3m": "3 دقائق", "5m": "5 دقائق", "15m": "15 دقيقة",
    "30m": "30 دقيقة", "1h": "1 ساعة", "2h": "ساعتان", "4h": "4 ساعات",
    "6h": "6 ساعات", "8h": "8 ساعات", "12h": "12 ساعة", "1d": "يومي",
    "3d": "3 أيام", "1w": "أسبوعي"
}

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800&display=swap');
html, body, [class*="css"] {font-family:'Cairo',sans-serif;}
.stApp {background: radial-gradient(circle at top right,#14243b 0%,#080d16 42%,#05080e 100%); color:#f4f7fb;}
.block-container {max-width:1180px; padding-top:1.2rem; padding-bottom:2rem;}
.hero {background:linear-gradient(120deg,rgba(18,35,58,.96),rgba(8,14,24,.96));border:1px solid #24415f;border-radius:22px;padding:22px 24px;margin-bottom:18px;box-shadow:0 12px 35px rgba(0,0,0,.25);}
.brand {font-size:clamp(25px,5vw,38px);font-weight:800;letter-spacing:.4px;color:#e8c66a;margin:0;}
.sub {color:#aebdd0;font-size:14px;margin-top:4px;}
.panel {background:rgba(14,23,36,.94);border:1px solid #20354d;border-radius:18px;padding:16px 18px;margin:12px 0;}
.metric {background:linear-gradient(145deg,#13243a,#0c1522);border:1px solid #29425e;border-radius:15px;padding:14px 12px;text-align:center;min-height:88px;}
.metric-label {font-size:12px;color:#9fb1c6;}
.metric-value {font-size:clamp(17px,3vw,23px);font-weight:800;color:#f6f8fb;direction:ltr;}
.gold {color:#e8c66a!important;}
.buy {color:#20d69a!important;}
.sell {color:#ff6577!important;}
.wait {color:#e8c66a!important;}
.small-note {font-size:12px;color:#9fb1c6;}
div.stButton > button {border-radius:12px;border:1px solid #d2ad50;background:linear-gradient(90deg,#c99d3d,#f0d27b);color:#111827;font-weight:800;min-height:48px;width:100%;}
div.stButton > button:hover {border-color:#ffe7a3;color:#000;filter:brightness(1.06);}
[data-testid="stTextInput"] input,[data-testid="stSelectbox"] div[data-baseweb="select"] {background:#101b2a;color:#fff;border-radius:10px;}
[data-testid="stAlert"] {border-radius:12px;}
footer {visibility:hidden;}
@media(max-width:640px){.block-container{padding-left: .8rem;padding-right:.8rem;padding-top:.7rem}.hero{padding:17px}.panel{padding:13px}.sub{font-size:12px}}
</style>
""", unsafe_allow_html=True)


def api_get(path, params=None, timeout=15):
    response = requests.get(BASE_URL + path, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=1800, show_spinner=False)
def get_symbols():
    data = api_get("/fapi/v1/exchangeInfo")
    symbols = []
    for item in data.get("symbols", []):
        if (item.get("quoteAsset") == "USDT"
            and item.get("contractType") == "PERPETUAL"
            and item.get("status") == "TRADING"):
            symbols.append(item["symbol"])
    return sorted(symbols)


@st.cache_data(ttl=8, show_spinner=False)
def get_klines(symbol, interval, limit=300):
    raw = api_get("/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": limit})
    cols = ["open_time","open","high","low","close","volume","close_time","quote_volume",
            "trades","taker_buy_base","taker_buy_quote","ignore"]
    df = pd.DataFrame(raw, columns=cols)
    for col in ["open","high","low","close","volume","quote_volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    # استبعاد الشمعة الحالية غير المكتملة حتى لا تصدر إشارة قبل الإغلاق
    now = pd.Timestamp.now(tz="UTC")
    if len(df) > 1 and df.iloc[-1]["close_time"] > now:
        df = df.iloc[:-1].copy()
    return df.dropna().reset_index(drop=True)


def add_indicators(df):
    d = df.copy()
    close = d["close"]
    high, low = d["high"], d["low"]
    d["ema20"] = close.ewm(span=20, adjust=False).mean()
    d["ema50"] = close.ewm(span=50, adjust=False).mean()
    d["ema200"] = close.ewm(span=200, adjust=False).mean()

    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    d["rsi"] = 100 - (100 / (1 + rs))
    d["rsi"] = d["rsi"].fillna(50)

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    d["macd"] = ema12 - ema26
    d["macd_signal"] = d["macd"].ewm(span=9, adjust=False).mean()
    d["macd_hist"] = d["macd"] - d["macd_signal"]

    prev_close = close.shift(1)
    tr = pd.concat([(high-low), (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1/14, adjust=False).mean()
    d["vol_sma20"] = d["volume"].rolling(20).mean()
    d["bb_mid"] = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    d["bb_upper"] = d["bb_mid"] + 2 * bb_std
    d["bb_lower"] = d["bb_mid"] - 2 * bb_std
    return d.dropna().reset_index(drop=True)


def analyze(df):
    last = df.iloc[-1]
    prev = df.iloc[-2]
    close = float(last["close"])
    atr = float(last["atr"])
    if not np.isfinite(atr) or atr <= 0:
        raise ValueError("تعذر حساب ATR بصورة سليمة.")

    long_checks = [
        (last["ema20"] > last["ema50"], "EMA20 أعلى من EMA50"),
        (last["ema50"] > last["ema200"], "EMA50 أعلى من EMA200"),
        (last["close"] > last["ema20"], "السعر أعلى EMA20"),
        (last["macd"] > last["macd_signal"], "MACD إيجابي"),
        (last["rsi"] >= 50 and last["rsi"] < 72, "RSI يدعم الصعود دون تشبع مرتفع"),
        (last["volume"] > last["vol_sma20"], "حجم التداول أعلى من متوسط 20 شمعة"),
        (last["close"] > prev["close"], "إغلاق أعلى من الشمعة السابقة"),
    ]
    short_checks = [
        (last["ema20"] < last["ema50"], "EMA20 أسفل EMA50"),
        (last["ema50"] < last["ema200"], "EMA50 أسفل EMA200"),
        (last["close"] < last["ema20"], "السعر أسفل EMA20"),
        (last["macd"] < last["macd_signal"], "MACD سلبي"),
        (last["rsi"] <= 50 and last["rsi"] > 28, "RSI يدعم الهبوط دون تشبع منخفض"),
        (last["volume"] > last["vol_sma20"], "حجم التداول أعلى من متوسط 20 شمعة"),
        (last["close"] < prev["close"], "إغلاق أسفل الشمعة السابقة"),
    ]
    long_score = int(round(sum(bool(x[0]) for x in long_checks) / len(long_checks) * 100))
    short_score = int(round(sum(bool(x[0]) for x in short_checks) / len(short_checks) * 100))

    if long_score >= 72 and long_score > short_score:
        direction, score, checks = "LONG", long_score, long_checks
    elif short_score >= 72 and short_score > long_score:
        direction, score, checks = "SHORT", short_score, short_checks
    else:
        direction, score, checks = "WAIT", max(long_score, short_score), long_checks if long_score >= short_score else short_checks

    # مستويات تقديرية مبنية على ATR؛ لا تمثل ضماناً لوصول السعر إليها
    entry = close
    if direction == "LONG":
        sl = entry - 1.5 * atr
        risk = entry - sl
        targets = [entry + risk, entry + 2*risk, entry + 3*risk]
    elif direction == "SHORT":
        sl = entry + 1.5 * atr
        risk = sl - entry
        targets = [entry - risk, entry - 2*risk, entry - 3*risk]
    else:
        sl = None
        targets = []
        risk = None

    return {
        "direction": direction, "score": score, "long_score": long_score,
        "short_score": short_score, "entry": entry, "sl": sl,
        "targets": targets, "atr": atr, "rsi": float(last["rsi"]),
        "ema20": float(last["ema20"]), "ema50": float(last["ema50"]),
        "ema200": float(last["ema200"]), "macd": float(last["macd"]),
        "volume_ratio": float(last["volume"] / last["vol_sma20"]) if last["vol_sma20"] else 0,
        "checks": checks, "candle_time": last["close_time"]
    }


def fmt_price(value):
    if value is None or not np.isfinite(value):
        return "—"
    if abs(value) >= 1000:
        return f"{value:,.2f}"
    if abs(value) >= 1:
        return f"{value:,.5f}".rstrip("0").rstrip(".")
    return f"{value:.8f}".rstrip("0").rstrip(".")


def make_chart(df, result, symbol):
    view = df.tail(120).copy()
    fig = go.Figure(data=[go.Candlestick(
        x=view["open_time"], open=view["open"], high=view["high"],
        low=view["low"], close=view["close"], name="السعر",
        increasing_line_color="#16c79a", decreasing_line_color="#ff6577"
    )])
    fig.add_trace(go.Scatter(x=view["open_time"], y=view["ema20"], name="EMA 20", line=dict(width=1.2, color="#e8c66a")))
    fig.add_trace(go.Scatter(x=view["open_time"], y=view["ema50"], name="EMA 50", line=dict(width=1.2, color="#55a8ff")))
    fig.add_trace(go.Scatter(x=view["open_time"], y=view["ema200"], name="EMA 200", line=dict(width=1.2, color="#b18cff")))
    if result["direction"] in ("LONG", "SHORT"):
        levels = [("الدخول", result["entry"], "#e8c66a"), ("وقف الخسارة", result["sl"], "#ff6577")]
        levels += [(f"TP{i+1}", p, "#16c79a") for i,p in enumerate(result["targets"])]
        for label, price, color in levels:
            fig.add_hline(y=price, line_dash="dash", line_color=color,
                          annotation_text=f"{label}: {fmt_price(price)}",
                          annotation_position="top right")
    fig.update_layout(
        template="plotly_dark", height=520, margin=dict(l=8,r=8,t=35,b=8),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(7,13,22,.8)",
        xaxis_rangeslider_visible=False, title=f"{symbol} · الشموع والمؤشرات",
        legend=dict(orientation="h", y=1.08, x=0)
    )
    return fig


# -------------------- واجهة التطبيق --------------------
st.markdown("""
<div class="hero" dir="rtl">
  <div class="brand">GALEIC FUTURES PRO</div>
  <div class="sub">محلل عقود Binance Futures · إشارات LONG / SHORT · تحليل فقط دون تنفيذ صفقات</div>
</div>
""", unsafe_allow_html=True)

try:
    symbols = get_symbols()
except Exception as exc:
    st.error("تعذر الاتصال ببيانات Binance Futures. تحقق من الإنترنت ثم أعد تحميل الصفحة.")
    st.caption(f"تفاصيل تقنية: {exc}")
    st.stop()

st.markdown('<div class="panel" dir="rtl">', unsafe_allow_html=True)
st.subheader("🔎 ابحث عن العملة واختر الفريم")
query = st.text_input("ابحث باسم العملة أو الزوج", placeholder="مثال: BTC أو ETH أو SOLUSDT").strip().upper()
matches = [s for s in symbols if query in s] if query else ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]
matches = [s for s in matches if s in symbols]
if not matches:
    st.warning("لا توجد أزواج USDT-M Futures مطابقة. جرّب رمزاً آخر.")
    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

c1, c2 = st.columns([1.25, 1])
with c1:
    selected_symbol = st.selectbox("زوج التداول", matches, index=0)
with c2:
    selected_interval = st.selectbox(
        "الفريم الزمني",
        INTERVALS,
        index=INTERVALS.index("15m"),
        format_func=lambda x: f"{x} — {INTERVAL_LABELS[x]}"
    )
analyze_clicked = st.button("📊 تحليل العملة", use_container_width=True)
st.markdown('<div class="small-note">تُستخدم آخر شمعة مغلقة فقط. البحث يعرض عقود USDT-M الدائمة المتاحة للتداول.</div>', unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)

if analyze_clicked:
    with st.spinner(f"جارٍ تحليل {selected_symbol} على فريم {selected_interval}..."):
        try:
            raw_df = get_klines(selected_symbol, selected_interval, 300)
            if len(raw_df) < 210:
                st.error("البيانات التاريخية غير كافية لهذا الفريم لإجراء تحليل EMA200 موثوق.")
                st.stop()
            data = add_indicators(raw_df)
            result = analyze(data)
            st.session_state["last_analysis"] = {
                "symbol": selected_symbol, "interval": selected_interval,
                "data": data, "result": result
            }
        except requests.RequestException as exc:
            st.error("فشل جلب بيانات السوق من Binance. أعد المحاولة بعد قليل.")
            st.caption(str(exc))
        except Exception as exc:
            st.error("حدث خطأ أثناء التحليل.")
            st.caption(str(exc))

if "last_analysis" in st.session_state:
    saved = st.session_state["last_analysis"]
    if saved["symbol"] != selected_symbol or saved["interval"] != selected_interval:
        st.info("غيّرت العملة أو الفريم. اضغط «تحليل العملة» لتحديث النتائج.")
    else:
        result, data = saved["result"], saved["data"]
        direction = result["direction"]
        color_class = "buy" if direction == "LONG" else "sell" if direction == "SHORT" else "wait"
        direction_ar = "شراء (LONG)" if direction == "LONG" else "بيع (SHORT)" if direction == "SHORT" else "انتظار — لا توجد إشارة قوية"
        st.markdown(f'<div class="panel" dir="rtl"><h3>نتيجة التحليل: <span class="{color_class}">{direction_ar}</span></h3><div class="small-note">آخر شمعة مغلقة: {result["candle_time"].strftime("%Y-%m-%d %H:%M UTC")}</div></div>', unsafe_allow_html=True)

        m1, m2, m3 = st.columns(3)
        with m1:
            st.markdown(f'<div class="metric"><div class="metric-label">السعر / الدخول المرجعي</div><div class="metric-value">{fmt_price(result["entry"])}</div></div>', unsafe_allow_html=True)
        with m2:
            st.markdown(f'<div class="metric"><div class="metric-label">قوة توافق المؤشرات</div><div class="metric-value gold">{result["score"]}/100</div></div>', unsafe_allow_html=True)
        with m3:
            st.markdown(f'<div class="metric"><div class="metric-label">RSI</div><div class="metric-value">{result["rsi"]:.1f}</div></div>', unsafe_allow_html=True)

        if direction in ("LONG", "SHORT"):
            a,b,c,d,e = st.columns(5)
            values = [("الدخول",result["entry"]),("وقف الخسارة",result["sl"]),("TP1",result["targets"][0]),("TP2",result["targets"][1]),("TP3",result["targets"][2])]
            for col,(label,val) in zip([a,b,c,d,e],values):
                with col:
                    st.markdown(f'<div class="metric"><div class="metric-label">{label}</div><div class="metric-value">{fmt_price(val)}</div></div>', unsafe_allow_html=True)
            st.success("الإشارة اجتازت حد التوافق المحدد في هذه النسخة. هذا لا يعني ضمان تنفيذ الصفقة أو تحقق الأهداف.")
        else:
            st.warning("لا توجد حالياً إشارة تستوفي شروط التوافق. الأفضل الانتظار بدلاً من فرض صفقة.")
            st.caption(f"درجة LONG: {result['long_score']}/100 · درجة SHORT: {result['short_score']}/100")

        st.plotly_chart(make_chart(data, result, selected_symbol), use_container_width=True, config={"displayModeBar": False})

        left, right = st.columns(2)
        with left:
            st.markdown('<div class="panel" dir="rtl">', unsafe_allow_html=True)
            st.subheader("🧭 قراءة المؤشرات")
            st.write(f"EMA 20: **{fmt_price(result['ema20'])}**")
            st.write(f"EMA 50: **{fmt_price(result['ema50'])}**")
            st.write(f"EMA 200: **{fmt_price(result['ema200'])}**")
            st.write(f"MACD: **{result['macd']:.6f}**")
            st.write(f"حجم التداول / متوسطه: **{result['volume_ratio']:.2f}x**")
            st.markdown("</div>", unsafe_allow_html=True)
        with right:
            st.markdown('<div class="panel" dir="rtl">', unsafe_allow_html=True)
            st.subheader("✅ شروط الاتجاه")
            for passed, description in result["checks"]:
                st.write(("🟢 " if passed else "⚪ ") + description)
            st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("""
        <div class="panel small-note" dir="rtl">
        <b>تنبيه مخاطر:</b> هذه أداة تحليل فني تعليمية وليست نصيحة استثمارية. درجة التوافق ليست احتمال نجاح.
        مستويات الأهداف ووقف الخسارة تقديرية ومبنية على ATR، وقد لا تُنفذ عند السعر المحدد بسبب الانزلاق السعري
        أو الرسوم أو ظروف السوق. اختبر الاستراتيجية تاريخياً وعلى حساب تجريبي قبل المخاطرة بأموال حقيقية.
        </div>
        """, unsafe_allow_html=True)

st.markdown('<div class="small-note" style="text-align:center;padding:18px" dir="rtl">GALEIC FUTURES PRO · بيانات عامة من Binance Futures · لا يتم تنفيذ أي أوامر تداول</div>', unsafe_allow_html=True)
