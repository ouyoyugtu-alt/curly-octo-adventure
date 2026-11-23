import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go
from concurrent.futures import ThreadPoolExecutor, as_completed

st.set_page_config(page_title="GALEIC FUTURES PRO", page_icon="📈", layout="wide")
FRAMES = {
    "1m": ("1m", 1), "3m": ("3m", 3), "5m": ("5m", 5), "15m": ("15m", 15),
    "30m": ("30m", 30), "1h": ("1h", 60), "2h": ("2h", 120), "4h": ("4h", 240),
    "6h": ("6h", 360), "12h": ("12h", 720), "1D": ("1d", 1440), "1W": ("1w", 10080)
}
POPULAR = ["BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "AVAX", "LINK", "SUI"]
PROVIDERS = ["تلقائي (تجربة كل المصادر)", "Gate.io Futures", "OKX Futures", "Binance Futures", "Bybit Futures"]
TIMEOUT = (6, 12)
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 (compatible; GaleicFutures/2.0)", "Accept": "application/json"})

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;500;600;700;800&display=swap');
html,body,[class*="css"]{font-family:'Cairo',sans-serif}
.stApp{background:#080d16;color:#eef3fa}
.block-container{max-width:1250px;padding-top:1rem;padding-bottom:2rem}
.hero{background:linear-gradient(115deg,#172b45,#0b1320);border:1px solid #2c4562;border-radius:20px;padding:18px;margin-bottom:14px}
.brand{font-size:clamp(25px,5vw,36px);font-weight:800;color:#e8c66a}
.muted{color:#a9b8ca;font-size:13px}
.panel{background:#101a29;border:1px solid #22364e;border-radius:16px;padding:14px;margin:10px 0}
.tile{background:linear-gradient(145deg,#17283e,#101a29);border:1px solid #2b4058;border-radius:13px;padding:12px 8px;text-align:center;min-height:76px}
.tile small{color:#9fb0c4;font-size:12px}.tile strong{display:block;color:#f5f7fb;font-size:clamp(14px,2.6vw,21px);overflow-wrap:anywhere}
.up{color:#20d69a!important}.down{color:#ff687a!important}.gold{color:#e8c66a!important}
div.stButton>button{border-radius:11px;min-height:44px;font-weight:700}
div.stButton>button[kind="primary"]{background:linear-gradient(90deg,#c99d3d,#f0d27b);color:#111827;border:0}
[data-testid="stDataFrame"]{width:100%}
@media(max-width:640px){.block-container{padding-left:.65rem;padding-right:.65rem}.panel{padding:10px}.hero{padding:14px}}
</style>
""", unsafe_allow_html=True)

class MarketError(Exception):
    pass

def request_json(url, params=None):
    try:
        response = SESSION.get(url, params=params, timeout=TIMEOUT)
        if response.status_code != 200:
            raise MarketError(f"HTTP {response.status_code} من {response.url}")
        data = response.json()
        return data
    except requests.RequestException as exc:
        raise MarketError(f"تعذر الاتصال: {exc.__class__.__name__}") from exc
    except ValueError as exc:
        raise MarketError("المصدر أعاد استجابة غير صالحة.") from exc

def clean_symbol(value):
    s = str(value).strip().upper().replace("/", "").replace("-", "").replace(" ", "")
    if s.endswith(".P"):
        s = s[:-2]
    if s.endswith("USDT"):
        s = s[:-4]
    if not s or not s.isalnum() or len(s) > 20:
        raise MarketError("أدخل رمزاً صحيحاً مثل BTC أو ETH أو SOLUSDT.")
    return s

def provider_order(choice):
    if choice == "تلقائي (تجربة كل المصادر)":
        return ["Gate.io Futures", "OKX Futures", "Binance Futures", "Bybit Futures"]
    return [choice]

def gate_candles(symbol, frame, limit=500):
    interval = FRAMES[frame][0]
    contract = f"{symbol}_USDT"
    data = request_json("https://api.gateio.ws/api/v4/futures/usdt/candlesticks",
                        {"contract": contract, "interval": interval, "limit": limit})
    if not isinstance(data, list) or not data:
        raise MarketError(f"لا توجد شموع للعقد {contract} على Gate.io.")
    df = pd.DataFrame(data)
    # Gate returns dictionaries: t, v, c, h, l, o
    if not {"t", "o", "h", "l", "c"}.issubset(df.columns):
        raise MarketError("صيغة شموع Gate.io غير متوقعة.")
    out = pd.DataFrame({
        "time": pd.to_datetime(pd.to_numeric(df["t"]), unit="s", utc=True),
        "open": pd.to_numeric(df["o"]), "high": pd.to_numeric(df["h"]),
        "low": pd.to_numeric(df["l"]), "close": pd.to_numeric(df["c"]),
        "volume": pd.to_numeric(df["v"]) if "v" in df else 0
    })
    return out.sort_values("time").reset_index(drop=True)

def okx_bar(frame):
    return {"1m":"1m","3m":"3m","5m":"5m","15m":"15m","30m":"30m","1h":"1H",
            "2h":"2H","4h":"4H","6h":"6H","12h":"12H","1D":"1D","1W":"1W"}[frame]

def okx_candles(symbol, frame, limit=300):
    inst = f"{symbol}-USDT-SWAP"
    data = request_json("https://www.okx.com/api/v5/market/candles",
                        {"instId": inst, "bar": okx_bar(frame), "limit": str(min(limit, 300))})
    if data.get("code") != "0" or not data.get("data"):
        raise MarketError(f"عقد {inst} غير متاح على OKX.")
    rows = data["data"]
    df = pd.DataFrame(rows, columns=["ts","open","high","low","close","volume","volCcy","volQuote","confirm"])
    out = pd.DataFrame({
        "time": pd.to_datetime(pd.to_numeric(df.ts), unit="ms", utc=True),
        "open": pd.to_numeric(df.open), "high": pd.to_numeric(df.high),
        "low": pd.to_numeric(df.low), "close": pd.to_numeric(df.close),
        "volume": pd.to_numeric(df.volume)
    })
    out = out[out["time"] < pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=FRAMES[frame][1])]
    return out.sort_values("time").reset_index(drop=True)

def binance_candles(symbol, frame, limit=500):
    interval = FRAMES[frame][0]
    data = request_json("https://fapi.binance.com/fapi/v1/klines",
                        {"symbol": f"{symbol}USDT", "interval": interval, "limit": limit})
    if not isinstance(data, list) or not data:
        raise MarketError("العقد غير متاح على Binance Futures.")
    df = pd.DataFrame(data, columns=["ts","open","high","low","close","volume","close_time","q","n","tb","tq","ignore"])
    out = pd.DataFrame({
        "time": pd.to_datetime(pd.to_numeric(df.ts), unit="ms", utc=True),
        "open": pd.to_numeric(df.open), "high": pd.to_numeric(df.high),
        "low": pd.to_numeric(df.low), "close": pd.to_numeric(df.close),
        "volume": pd.to_numeric(df.volume)
    })
    return out.sort_values("time").reset_index(drop=True)

def bybit_candles(symbol, frame, limit=500):
    interval = {"1D":"D","1W":"W"}.get(frame, str(FRAMES[frame][1]))
    data = request_json("https://api.bybit.com/v5/market/kline",
                        {"category":"linear","symbol":f"{symbol}USDT","interval":interval,"limit":limit})
    if data.get("retCode") != 0 or not data.get("result",{}).get("list"):
        raise MarketError(data.get("retMsg", "العقد غير متاح على Bybit."))
    df = pd.DataFrame(data["result"]["list"], columns=["ts","open","high","low","close","volume","turnover"])
    out = pd.DataFrame({
        "time": pd.to_datetime(pd.to_numeric(df.ts), unit="ms", utc=True),
        "open": pd.to_numeric(df.open), "high": pd.to_numeric(df.high),
        "low": pd.to_numeric(df.low), "close": pd.to_numeric(df.close),
        "volume": pd.to_numeric(df.volume)
    })
    out = out[out["time"] < pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=FRAMES[frame][1])]
    return out.sort_values("time").reset_index(drop=True)

FETCHERS = {
    "Gate.io Futures": gate_candles,
    "OKX Futures": okx_candles,
    "Binance Futures": binance_candles,
    "Bybit Futures": bybit_candles
}

@st.cache_data(ttl=35, show_spinner=False)
def load_market_data(symbol, frame, choice):
    failures = []
    for name in provider_order(choice):
        try:
            df = FETCHERS[name](symbol, frame)
            if len(df) < 30:
                raise MarketError("عدد الشموع المستلمة قليل.")
            return df, name, failures
        except Exception as exc:
            failures.append(f"{name}: {str(exc)[:180]}")
    raise MarketError("لم ينجح أي مصدر بيانات.\n" + "\n".join(failures))

@st.cache_data(ttl=90, show_spinner=False)
def search_listings(symbol):
    results = []
    # Gate contracts
    try:
        data = request_json("https://api.gateio.ws/api/v4/futures/usdt/contracts")
        found = any(isinstance(x,dict) and x.get("name")==f"{symbol}_USDT" and not x.get("in_delisting",False) for x in data)
        results.append({"المنصة":"Gate.io Futures","الحالة":"متاح" if found else "غير مدرج"})
    except Exception as e: results.append({"المنصة":"Gate.io Futures","الحالة":f"تعذر الاتصال: {str(e)[:65]}"})
    # OKX
    try:
        data = request_json("https://www.okx.com/api/v5/public/instruments", {"instType":"SWAP"})
        found = any(x.get("instId")==f"{symbol}-USDT-SWAP" and x.get("state")=="live" for x in data.get("data",[]))
        results.append({"المنصة":"OKX Futures","الحالة":"متاح" if found else "غير مدرج"})
    except Exception as e: results.append({"المنصة":"OKX Futures","الحالة":f"تعذر الاتصال: {str(e)[:65]}"})
    # Binance
    try:
        data = request_json("https://fapi.binance.com/fapi/v1/exchangeInfo")
        found = any(x.get("symbol")==f"{symbol}USDT" and x.get("contractType")=="PERPETUAL" and x.get("status")=="TRADING" for x in data.get("symbols",[]))
        results.append({"المنصة":"Binance Futures","الحالة":"متاح" if found else "غير مدرج"})
    except Exception as e: results.append({"المنصة":"Binance Futures","الحالة":f"تعذر الاتصال: {str(e)[:65]}"})
    # Bybit
    try:
        data = request_json("https://api.bybit.com/v5/market/instruments-info", {"category":"linear","symbol":f"{symbol}USDT"})
        found = any(x.get("symbol")==f"{symbol}USDT" and x.get("status")=="Trading" for x in data.get("result",{}).get("list",[]))
        results.append({"المنصة":"Bybit Futures","الحالة":"متاح" if found else "غير مدرج"})
    except Exception as e: results.append({"المنصة":"Bybit Futures","الحالة":f"تعذر الاتصال: {str(e)[:65]}"})
    return results

def add_indicators(df):
    x = df.copy()
    c, h, low = x.close, x.high, x.low
    for n in (20,50,200):
        x[f"ema{n}"] = c.ewm(span=n, adjust=False).mean()
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    x["rsi"] = (100 - 100/(1+rs)).fillna(50)
    e12, e26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    x["macd"] = e12-e26
    x["macds"] = x.macd.ewm(span=9, adjust=False).mean()
    tr = pd.concat([h-low, (h-c.shift()).abs(), (low-c.shift()).abs()], axis=1).max(axis=1)
    x["atr"] = tr.ewm(alpha=1/14, adjust=False).mean()
    x["bbmid"] = c.rolling(20).mean()
    sd = c.rolling(20).std()
    x["bbup"], x["bblow"] = x.bbmid+2*sd, x.bbmid-2*sd
    return x.replace([np.inf,-np.inf], np.nan).dropna().reset_index(drop=True)

def make_signal(df):
    if len(df) < 205:
        raise MarketError("نحتاج 205 شموع على الأقل لحساب EMA200. جرّب فريماً أكبر أو عقداً أقدم.")
    x, prev = df.iloc[-1], df.iloc[-2]
    long_checks = [x.ema20>x.ema50, x.ema50>x.ema200, x.close>x.ema20,
                   x.macd>x.macds, 50<=x.rsi<70, x.close>prev.close]
    short_checks = [x.ema20<x.ema50, x.ema50<x.ema200, x.close<x.ema20,
                    x.macd<x.macds, 30<x.rsi<=50, x.close<prev.close]
    long_score, short_score = round(sum(long_checks)/6*100), round(sum(short_checks)/6*100)
    if long_score >= 67 and long_score > short_score: side, score = "LONG", long_score
    elif short_score >= 67 and short_score > long_score: side, score = "SHORT", short_score
    else: side, score = "WAIT", max(long_score, short_score)
    entry, atr = float(x.close), float(x.atr)
    if side == "LONG":
        stop = entry - 1.5*atr
        targets = [entry+(entry-stop)*r for r in (1,2,3)]
    elif side == "SHORT":
        stop = entry + 1.5*atr
        targets = [entry-(stop-entry)*r for r in (1,2,3)]
    else: stop, targets = None, []
    return {"side":side,"score":score,"long":long_score,"short":short_score,
            "entry":entry,"stop":stop,"targets":targets,"rsi":float(x.rsi),
            "ema20":float(x.ema20),"ema50":float(x.ema50),"ema200":float(x.ema200),
            "macd":float(x.macd),"macds":float(x.macds),"atr":atr,"time":x.time}

def fmt(value):
    if value is None: return "—"
    try:
        v=float(value)
        if not np.isfinite(v): return "—"
        if abs(v)>=1000: return f"{v:,.2f}"
        if abs(v)>=1: return f"{v:,.6f}".rstrip("0").rstrip(".")
        return f"{v:.10f}".rstrip("0").rstrip(".")
    except Exception: return "—"

def tile(label,value,cls=""):
    st.markdown(f'<div class="tile"><small>{label}</small><strong class="{cls}">{value}</strong></div>', unsafe_allow_html=True)

def draw_chart(df, symbol, provider):
    v=df.tail(220)
    fig=go.Figure()
    fig.add_trace(go.Candlestick(x=v.time,open=v.open,high=v.high,low=v.low,close=v.close,
        name="السعر",increasing_line_color="#20c997",decreasing_line_color="#ff687a"))
    for col,name,color in [("ema20","EMA20","#e8c66a"),("ema50","EMA50","#55a8ff"),
                           ("ema200","EMA200","#b18cff"),("bbup","BB Upper","#778899"),("bblow","BB Lower","#778899")]:
        fig.add_trace(go.Scatter(x=v.time,y=v[col],name=name,line=dict(width=1,color=color)))
    fig.update_layout(template="plotly_dark",height=440,margin=dict(l=5,r=5,t=35,b=5),
        paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="#0b1421",xaxis_rangeslider_visible=False,
        title=f"{symbol}USDT · {provider}",legend=dict(orientation="h",y=1.08),autosize=True)
    return fig

st.markdown('<div class="hero" dir="rtl"><div class="brand">GALEIC FUTURES PRO</div><div class="muted">تحليل عقود آجلة فقط · بيانات عامة · لا ينفذ صفقات</div></div>', unsafe_allow_html=True)

with st.container():
    st.markdown('<div class="panel" dir="rtl">', unsafe_allow_html=True)
    st.subheader("🔎 البحث وتحليل العملة")
    a,b=st.columns([2,1])
    with a: symbol_input=st.text_input("ابحث عن العملة أو الزوج", value=st.session_state.get("symbol","BTC"), placeholder="BTC أو BTCUSDT")
    with b: provider=st.selectbox("مصدر البيانات",PROVIDERS,index=0)
    frame=st.selectbox("الفريم الزمني",list(FRAMES.keys()),index=3)
    analyze=st.button("📊 تحليل العملة",type="primary",use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

if "symbol" not in st.session_state: st.session_state.symbol="BTC"
if analyze:
    try: st.session_state.symbol=clean_symbol(symbol_input)
    except MarketError as e: st.error(str(e))
    st.session_state.do_analysis=True

symbol=st.session_state.symbol
if st.session_state.get("do_analysis"):
    try:
        with st.spinner("تحميل بيانات السوق وحساب المؤشرات..."):
            raw, used_provider, failures=load_market_data(symbol,frame,provider)
            data=add_indicators(raw)
            signal=make_signal(data)
        st.success(f"تم تحميل البيانات بنجاح من {used_provider}.")
        if failures:
            with st.expander("مصادر تعذر استخدامها قبل نجاح المصدر الحالي"):
                st.write("\n".join(failures))
        st.subheader(f"📈 الرسم البياني — {symbol}USDT")
        st.plotly_chart(draw_chart(data,symbol,used_provider),use_container_width=True,
                        config={"displaylogo":False,"scrollZoom":True,"responsive":True})
        st.subheader("📊 مؤشرات السوق")
        x=data.iloc[-1]
        cols=st.columns(4)
        for col,(label,val,cl) in zip(cols,[("السعر",fmt(x.close),""),("RSI",f"{x.rsi:.1f}",""),
            ("MACD","صاعد" if x.macd>x.macds else "هابط","up" if x.macd>x.macds else "down"),("ATR",fmt(x.atr),"")]):
            with col: tile(label,val,cl)
        cols=st.columns(3)
        for col,(label,val) in zip(cols,[("EMA20",fmt(x.ema20)),("EMA50",fmt(x.ema50)),("EMA200",fmt(x.ema200))]):
            with col: tile(label,val)
        st.subheader("🎯 إشارة الدخول والخروج")
        side=signal["side"]
        cls="up" if side=="LONG" else "down" if side=="SHORT" else "gold"
        label={"LONG":"LONG — شراء","SHORT":"SHORT — بيع","WAIT":"WAIT — انتظار"}[side]
        st.markdown(f'<h2 class="{cls}">{label}</h2>',unsafe_allow_html=True)
        cols=st.columns(3)
        for col,(label,val) in zip(cols,[("قوة التوافق",f'{signal["score"]}/100'),
            ("تقييم LONG",f'{signal["long"]}/100'),("تقييم SHORT",f'{signal["short"]}/100')]):
            with col: tile(label,val)
        if side!="WAIT":
            cols=st.columns(5)
            levels=[("الدخول",signal["entry"]),("وقف الخسارة",signal["stop"])]+[(f"TP{i+1}",v) for i,v in enumerate(signal["targets"])]
            for col,(label,val) in zip(cols,levels):
                with col: tile(label,fmt(val))
        else: st.info("لا توجد فرصة تحقق شروط الاستراتيجية حالياً. لا تدخل لمجرد ظهور نتيجة تحليل.")
        st.caption("آخر شمعة مغلقة: "+signal["time"].strftime("%Y-%m-%d %H:%M UTC"))
        st.caption("الإشارة مبنية على EMA20/50/200 وRSI وMACD وحركة الإغلاق وATR. نسبة التوافق ليست احتمال ربح.")
    except Exception as e:
        st.error(f"تعذر إكمال التحليل: {e}")
        st.info("جرّب وضع مصدر البيانات على «تلقائي» أو اختيار Gate.io / OKX. إذا كانت كل المصادر محجوبة من استضافة Streamlit فلن يحل تغيير الواجهة المشكلة.")

with st.expander("🔍 فحص إدراج العملة في المنصات"):
    check_symbol=st.text_input("رمز العملة للفحص",value=symbol,key="listing_symbol")
    if st.button("فحص المنصات"):
        try:
            with st.spinner("فحص إدراج العقد..."):
                st.dataframe(pd.DataFrame(search_listings(clean_symbol(check_symbol))),use_container_width=True,hide_index=True)
        except Exception as e: st.error(str(e))

st.markdown('<div class="muted" style="text-align:center;padding:16px" dir="rtl">GALEIC FUTURES PRO · نسخة مجانية · تحليل فقط دون تنفيذ صفقات<br>الأسواق عالية المخاطر؛ لا توجد دقة مضمونة أو أهداف مضمونة. اختبر الاستراتيجية تجريبياً قبل المخاطرة.</div>', unsafe_allow_html=True)
