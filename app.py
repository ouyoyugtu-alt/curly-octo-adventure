import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go
from datetime import timedelta

# =========================================================
# GALEIC FUTURES PRO - Market analysis only
# Default provider: Bybit USDT perpetual public market data.
# No API keys, account access, or order execution.
# =========================================================

st.set_page_config(
    page_title="GALEIC FUTURES PRO",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

BYBIT_URL = "https://api.bybit.com"
BINANCE_URL = "https://fapi.binance.com"

# Bybit V5 interval values. All are supported by the linear kline endpoint.
TIMEFRAMES = {
    "1m": ("1", "1 دقيقة", 1),
    "3m": ("3", "3 دقائق", 3),
    "5m": ("5", "5 دقائق", 5),
    "15m": ("15", "15 دقيقة", 15),
    "30m": ("30", "30 دقيقة", 30),
    "1h": ("60", "1 ساعة", 60),
    "2h": ("120", "ساعتان", 120),
    "4h": ("240", "4 ساعات", 240),
    "6h": ("360", "6 ساعات", 360),
    "12h": ("720", "12 ساعة", 720),
    "1d": ("D", "يومي", 1440),
    "1w": ("W", "أسبوعي", 10080),
}

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800&display=swap');
html, body, [class*="css"] {font-family:'Cairo',sans-serif;}
.stApp {background:radial-gradient(circle at top right,#14243b 0%,#080d16 43%,#05080e 100%);color:#f4f7fb;}
.block-container {max-width:1180px;padding-top:1rem;padding-bottom:2rem;}
.hero {background:linear-gradient(120deg,rgba(18,35,58,.98),rgba(8,14,24,.98));border:1px solid #29435f;border-radius:22px;padding:22px 24px;margin-bottom:18px;}
.brand {font-size:clamp(25px,5vw,38px);font-weight:800;color:#e8c66a;margin:0;}
.sub {color:#b6c4d6;font-size:14px;margin-top:5px;}
.panel {background:rgba(14,23,36,.96);border:1px solid #20354d;border-radius:18px;padding:16px 18px;margin:12px 0;}
.metric {background:linear-gradient(145deg,#13243a,#0c1522);border:1px solid #29425e;border-radius:15px;padding:13px 9px;text-align:center;min-height:83px;}
.metric-label {font-size:12px;color:#9fb1c6;}
.metric-value {font-size:clamp(16px,3vw,22px);font-weight:800;color:#f6f8fb;direction:ltr;overflow-wrap:anywhere;}
.gold {color:#e8c66a!important;} .buy {color:#20d69a!important;} .sell {color:#ff6577!important;} .wait {color:#e8c66a!important;}
.small-note {font-size:12px;color:#9fb1c6;}
div.stButton>button {border-radius:12px;border:1px solid #d2ad50;background:linear-gradient(90deg,#c99d3d,#f0d27b);color:#111827;font-weight:800;min-height:48px;width:100%;}
div.stButton>button:hover {border-color:#ffe7a3;color:#000;}
[data-testid="stTextInput"] input,[data-testid="stSelectbox"] div[data-baseweb="select"] {background:#101b2a;color:#fff;border-radius:10px;}
@media(max-width:640px){.block-container{padding-left:.75rem;padding-right:.75rem;padding-top:.6rem}.hero{padding:16px}.panel{padding:12px}.sub{font-size:12px}}
</style>
""", unsafe_allow_html=True)


class MarketAPIError(Exception):
    pass


def http_get(base, path, params=None):
    try:
        r = requests.get(
            base + path,
            params=params,
            timeout=(8, 20),
            headers={"User-Agent": "GaleicFuturesPro/2.0"}
        )
    except requests.RequestException as e:
        raise MarketAPIError(f"تعذر الاتصال بمزود البيانات: {e}") from e

    if r.status_code == 451:
        raise MarketAPIError(
            "مزود البيانات رفض الطلب برمز HTTP 451 (قيود وصول/منطقة أو استضافة). "
            "هذا ليس خطأ في واجهة التطبيق. اختر مزود بيانات آخر من القائمة."
        )
    if r.status_code in (403, 429):
        raise MarketAPIError(
            f"المزود رفض الطلب برمز HTTP {r.status_code}. قد يكون الوصول محجوباً أو تجاوزت حد الطلبات. حاول لاحقاً أو اختر مزوداً آخر."
        )
    if r.status_code != 200:
        raise MarketAPIError(f"استجابة غير ناجحة من مزود البيانات: HTTP {r.status_code}.")
    try:
        return r.json()
    except ValueError as e:
        raise MarketAPIError("أعاد مزود البيانات استجابة غير مفهومة.") from e


@st.cache_data(ttl=1800, show_spinner=False)
def get_bybit_symbols():
    all_symbols = []
    cursor = None
    # Fetch all pages, not just the first 500 contracts.
    for _ in range(10):
        params = {"category": "linear", "limit": 1000, "status": "Trading"}
        if cursor:
            params["cursor"] = cursor
        data = http_get(BYBIT_URL, "/v5/market/instruments-info", params)
        if data.get("retCode") != 0:
            raise MarketAPIError(f"Bybit: {data.get('retMsg', 'خطأ غير معروف')}")
        result = data.get("result", {})
        for item in result.get("list", []):
            if (item.get("quoteCoin") == "USDT"
                and item.get("settleCoin") == "USDT"
                and item.get("contractType") == "LinearPerpetual"
                and item.get("status") == "Trading"):
                all_symbols.append(item["symbol"])
        cursor = result.get("nextPageCursor")
        if not cursor:
            break
    if not all_symbols:
        raise MarketAPIError("لم تصل قائمة عقود Bybit USDT الدائمة.")
    return sorted(set(all_symbols))


@st.cache_data(ttl=1800, show_spinner=False)
def get_binance_symbols():
    data = http_get(BINANCE_URL, "/fapi/v1/exchangeInfo")
    symbols = []
    for item in data.get("symbols", []):
        if (item.get("quoteAsset") == "USDT"
            and item.get("contractType") == "PERPETUAL"
            and item.get("status") == "TRADING"):
            symbols.append(item["symbol"])
    if not symbols:
        raise MarketAPIError("لم تصل قائمة عقود Binance USDT الدائمة.")
    return sorted(symbols)


@st.cache_data(ttl=10, show_spinner=False)
def get_bybit_klines(symbol, timeframe, limit=500):
    interval = TIMEFRAMES[timeframe][0]
    data = http_get(BYBIT_URL, "/v5/market/kline", {
        "category": "linear", "symbol": symbol, "interval": interval, "limit": limit
    })
    if data.get("retCode") != 0:
        raise MarketAPIError(f"Bybit: {data.get('retMsg', 'تعذر جلب الشموع')}")
    rows = data.get("result", {}).get("list", [])
    if not rows:
        raise MarketAPIError("لا توجد بيانات شموع لهذا الزوج والفريم.")
    # Bybit returns newest-first: startTime, open, high, low, close, volume, turnover.
    df = pd.DataFrame(rows, columns=["open_time","open","high","low","close","volume","turnover"])
    df["open_time"] = pd.to_datetime(pd.to_numeric(df["open_time"]), unit="ms", utc=True)
    for col in ["open","high","low","close","volume","turnover"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.sort_values("open_time").reset_index(drop=True)
    duration = timedelta(minutes=TIMEFRAMES[timeframe][2])
    now = pd.Timestamp.now(tz="UTC")
    # Drop current candle if its scheduled end time has not passed.
    if len(df) and df.iloc[-1]["open_time"] + duration > now:
        df = df.iloc[:-1].copy()
    return df.dropna().reset_index(drop=True)


@st.cache_data(ttl=10, show_spinner=False)
def get_binance_klines(symbol, timeframe, limit=500):
    data = http_get(BINANCE_URL, "/fapi/v1/klines", {
        "symbol": symbol, "interval": timeframe, "limit": limit
    })
    cols = ["open_time","open","high","low","close","volume","close_time",
            "quote_volume","trades","taker_buy_base","taker_buy_quote","ignore"]
    df = pd.DataFrame(data, columns=cols)
    if df.empty:
        raise MarketAPIError("لا توجد بيانات شموع لهذا الزوج والفريم.")
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    for col in ["open","high","low","close","volume","quote_volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    now = pd.Timestamp.now(tz="UTC")
    if len(df) and df.iloc[-1]["close_time"] > now:
        df = df.iloc[:-1].copy()
    return df.dropna().reset_index(drop=True)


def indicators(source):
    d = source.copy()
    c, h, l = d.close, d.high, d.low
    d["ema20"] = c.ewm(span=20, adjust=False).mean()
    d["ema50"] = c.ewm(span=50, adjust=False).mean()
    d["ema200"] = c.ewm(span=200, adjust=False).mean()
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    d["rsi"] = (100 - 100/(1+rs)).fillna(50)
    e12 = c.ewm(span=12, adjust=False).mean()
    e26 = c.ewm(span=26, adjust=False).mean()
    d["macd"] = e12-e26
    d["macd_signal"] = d.macd.ewm(span=9, adjust=False).mean()
    prev = c.shift(1)
    tr = pd.concat([(h-l),(h-prev).abs(),(l-prev).abs()],axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1/14, adjust=False).mean()
    d["vol_avg"] = d.volume.rolling(20).mean()
    return d.replace([np.inf,-np.inf],np.nan).dropna().reset_index(drop=True)


def analyze(d):
    if len(d) < 205:
        raise MarketAPIError("البيانات التاريخية غير كافية لحساب EMA200. اختر فريماً آخر أو حاول لاحقاً.")
    x, p = d.iloc[-1], d.iloc[-2]
    checks_long = [
        (x.ema20 > x.ema50, "EMA20 أعلى من EMA50"),
        (x.ema50 > x.ema200, "EMA50 أعلى من EMA200"),
        (x.close > x.ema20, "السعر أعلى EMA20"),
        (x.macd > x.macd_signal, "MACD إيجابي"),
        (50 <= x.rsi < 72, "RSI ضمن نطاق داعم للصعود"),
        (x.volume > x.vol_avg, "حجم التداول أعلى من متوسط 20 شمعة"),
        (x.close > p.close, "الإغلاق أعلى من الشمعة السابقة"),
    ]
    checks_short = [
        (x.ema20 < x.ema50, "EMA20 أسفل EMA50"),
        (x.ema50 < x.ema200, "EMA50 أسفل EMA200"),
        (x.close < x.ema20, "السعر أسفل EMA20"),
        (x.macd < x.macd_signal, "MACD سلبي"),
        (28 < x.rsi <= 50, "RSI ضمن نطاق داعم للهبوط"),
        (x.volume > x.vol_avg, "حجم التداول أعلى من متوسط 20 شمعة"),
        (x.close < p.close, "الإغلاق أسفل الشمعة السابقة"),
    ]
    ls = round(sum(bool(v) for v,_ in checks_long)/7*100)
    ss = round(sum(bool(v) for v,_ in checks_short)/7*100)
    if ls >= 72 and ls > ss:
        side, score, checks = "LONG", ls, checks_long
    elif ss >= 72 and ss > ls:
        side, score, checks = "SHORT", ss, checks_short
    else:
        side, score, checks = "WAIT", max(ls,ss), checks_long if ls >= ss else checks_short

    entry = float(x.close)
    atr = float(x.atr)
    if side == "LONG":
        stop = entry - 1.5*atr
        risk = entry-stop
        targets = [entry+risk, entry+2*risk, entry+3*risk]
    elif side == "SHORT":
        stop = entry + 1.5*atr
        risk = stop-entry
        targets = [entry-risk, entry-2*risk, entry-3*risk]
    else:
        stop, targets, risk = None, [], None
    return {
        "side":side, "score":score, "long_score":ls, "short_score":ss,
        "entry":entry, "stop":stop, "targets":targets, "atr":atr,
        "rsi":float(x.rsi), "ema20":float(x.ema20), "ema50":float(x.ema50),
        "ema200":float(x.ema200), "macd":float(x.macd),
        "volume_ratio":float(x.volume/x.vol_avg) if x.vol_avg else 0,
        "checks":checks, "candle_time":x.open_time
    }


def price(v):
    if v is None or not np.isfinite(v):
        return "—"
    if abs(v) >= 1000: return f"{v:,.2f}"
    if abs(v) >= 1: return f"{v:,.6f}".rstrip("0").rstrip(".")
    return f"{v:.10f}".rstrip("0").rstrip(".")


def chart(df, result, symbol, timeframe):
    view = df.tail(140)
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=view.open_time, open=view.open, high=view.high, low=view.low, close=view.close,
        name="السعر", increasing_line_color="#19c99a", decreasing_line_color="#ff6577"
    ))
    for col, label, color in [
        ("ema20","EMA 20","#e8c66a"),("ema50","EMA 50","#55a8ff"),("ema200","EMA 200","#b18cff")
    ]:
        fig.add_trace(go.Scatter(x=view.open_time,y=view[col],name=label,line=dict(width=1.2,color=color)))
    if result["side"] != "WAIT":
        lines = [("الدخول",result["entry"],"#e8c66a"),("وقف الخسارة",result["stop"],"#ff6577")]
        lines += [(f"TP{i+1}",v,"#19c99a") for i,v in enumerate(result["targets"])]
        for label, val, color in lines:
            fig.add_hline(y=val,line_dash="dash",line_color=color,
                          annotation_text=f"{label}: {price(val)}",annotation_position="top right")
    fig.update_layout(
        template="plotly_dark",height=480,margin=dict(l=5,r=5,t=45,b=5),
        paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(7,13,22,.8)",
        xaxis_rangeslider_visible=False,title=f"{symbol} · {timeframe}",
        legend=dict(orientation="h",y=1.08,x=0)
    )
    return fig


# ---------------- UI ----------------
st.markdown("""
<div class="hero" dir="rtl">
 <div class="brand">GALEIC FUTURES PRO</div>
 <div class="sub">محلل عقود آجلة · LONG / SHORT · تحليل فقط دون تنفيذ صفقات</div>
</div>
""", unsafe_allow_html=True)

st.markdown('<div class="panel" dir="rtl">', unsafe_allow_html=True)
st.subheader("مصدر بيانات العقود")
provider = st.selectbox(
    "اختر منصة البيانات",
    ["Bybit Futures (موصى به)", "Binance Futures"],
    help="تم جعل Bybit افتراضياً لأن لقطة الخطأ أظهرت أن Binance أعاد HTTP 451 من بيئة الاستضافة."
)
st.markdown("</div>", unsafe_allow_html=True)

try:
    with st.spinner("تحميل أزواج العقود الدائمة..."):
        symbols = get_bybit_symbols() if provider.startswith("Bybit") else get_binance_symbols()
except MarketAPIError as e:
    st.error(str(e))
    if provider.startswith("Binance"):
        st.info("جرّب اختيار Bybit Futures من مصدر البيانات. لن نحاول تجاوز قيود الوصول إلى Binance.")
    st.stop()
except Exception as e:
    st.error("تعذر تحميل قائمة العملات.")
    st.caption(str(e))
    st.stop()

st.markdown('<div class="panel" dir="rtl">', unsafe_allow_html=True)
st.subheader("🔎 ابحث عن العملة واختر الفريم")
query = st.text_input("ابحث برمز العملة أو الزوج", placeholder="مثال: BTC أو ETH أو SOLUSDT").strip().upper()
filtered = [s for s in symbols if query in s] if query else [s for s in ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT"] if s in symbols]
if not filtered:
    st.warning("لم نعثر على زوج مطابق في عقود USDT الدائمة لهذه المنصة.")
    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()
c1,c2 = st.columns([1.2,1])
with c1:
    symbol = st.selectbox("زوج التداول",filtered)
with c2:
    timeframe = st.selectbox("الفريم الزمني",list(TIMEFRAMES.keys()),index=3,
                             format_func=lambda k:f"{k} — {TIMEFRAMES[k][1]}")
run = st.button("📊 تحليل العملة",use_container_width=True)
st.caption("تُستبعد الشمعة الحالية غير المكتملة. القائمة خاصة بعقود USDT الدائمة المتاحة للتداول.")
st.markdown("</div>", unsafe_allow_html=True)

if run:
    try:
        with st.spinner(f"جارٍ تحليل {symbol} على فريم {timeframe}..."):
            raw = get_bybit_klines(symbol,timeframe) if provider.startswith("Bybit") else get_binance_klines(symbol,timeframe)
            prepared = indicators(raw)
            result = analyze(prepared)
            st.session_state["analysis_result"] = {
                "provider":provider,"symbol":symbol,"timeframe":timeframe,
                "df":prepared,"result":result
            }
    except MarketAPIError as e:
        st.error(str(e))
    except Exception as e:
        st.error("حدث خطأ غير متوقع أثناء التحليل.")
        st.caption(f"التفاصيل: {e}")

saved = st.session_state.get("analysis_result")
if saved:
    if (saved["provider"],saved["symbol"],saved["timeframe"]) != (provider,symbol,timeframe):
        st.info("تم تغيير مصدر البيانات أو العملة أو الفريم. اضغط «تحليل العملة» لتحديث النتائج.")
    else:
        r,df = saved["result"],saved["df"]
        side = r["side"]
        side_text = "شراء LONG" if side=="LONG" else "بيع SHORT" if side=="SHORT" else "انتظار — لا توجد إشارة قوية"
        css = "buy" if side=="LONG" else "sell" if side=="SHORT" else "wait"
        st.markdown(
            f'<div class="panel" dir="rtl"><h3>نتيجة التحليل: <span class="{css}">{side_text}</span></h3>'
            f'<div class="small-note">مصدر البيانات: {provider} · آخر شمعة مغلقة: {r["candle_time"].strftime("%Y-%m-%d %H:%M UTC")}</div></div>',
            unsafe_allow_html=True
        )
        cols = st.columns(3)
        for col,label,val,cl in [
            (cols[0],"السعر المرجعي",price(r["entry"]),""),
            (cols[1],"قوة توافق المؤشرات",f'{r["score"]}/100',"gold"),
            (cols[2],"RSI",f'{r["rsi"]:.1f}',"")
        ]:
            with col:
                st.markdown(f'<div class="metric"><div class="metric-label">{label}</div><div class="metric-value {cl}">{val}</div></div>',unsafe_allow_html=True)
        if side != "WAIT":
            labels = [("الدخول",r["entry"]),("وقف الخسارة",r["stop"]),("TP1",r["targets"][0]),("TP2",r["targets"][1]),("TP3",r["targets"][2])]
            cols = st.columns(5)
            for col,(label,val) in zip(cols,labels):
                with col:
                    st.markdown(f'<div class="metric"><div class="metric-label">{label}</div><div class="metric-value">{price(val)}</div></div>',unsafe_allow_html=True)
            st.success("توافقت شروط التحليل مع اتجاه واحد. هذا ليس ضماناً للربح أو تحقق الأهداف.")
        else:
            st.warning("لا توجد إشارة تستوفي الحد المحدد. الانتظار أفضل من فرض صفقة.")
            st.caption(f'درجة LONG: {r["long_score"]}/100 · درجة SHORT: {r["short_score"]}/100')
        st.plotly_chart(chart(df,r,symbol,timeframe),use_container_width=True,config={"displayModeBar":False})
        left,right = st.columns(2)
        with left:
            st.markdown('<div class="panel" dir="rtl">',unsafe_allow_html=True)
            st.subheader("قراءة المؤشرات")
            st.write(f'EMA 20: **{price(r["ema20"])}**')
            st.write(f'EMA 50: **{price(r["ema50"])}**')
            st.write(f'EMA 200: **{price(r["ema200"])}**')
            st.write(f'MACD: **{r["macd"]:.8f}**')
            st.write(f'الحجم / متوسط 20 شمعة: **{r["volume_ratio"]:.2f}x**')
            st.markdown("</div>",unsafe_allow_html=True)
        with right:
            st.markdown('<div class="panel" dir="rtl">',unsafe_allow_html=True)
            st.subheader("أسباب تقييم الاتجاه")
            for passed,desc in r["checks"]:
                st.write(("🟢 " if passed else "⚪ ")+desc)
            st.markdown("</div>",unsafe_allow_html=True)

        st.markdown("""
        <div class="panel small-note" dir="rtl">
        <b>تنبيه:</b> درجة 0–100 تعني نسبة توافق الشروط الفنية فقط وليست احتمال نجاح الصفقة.
        مستويات الوقف والأهداف تقديرية ومحسوبة من ATR، ولا تضمن التنفيذ أو الوصول إليها.
        لا تستخدم الإشارات بأموال حقيقية قبل إجراء اختبار تاريخي وتجريبي شامل. هذا التطبيق لا ينفذ أوامر تداول.
        </div>
        """,unsafe_allow_html=True)

st.markdown('<div class="small-note" style="text-align:center;padding:18px" dir="rtl">GALEIC FUTURES PRO · بيانات سوق عامة · لا يحتاج API Key · لا ينفذ صفقات</div>',unsafe_allow_html=True)
