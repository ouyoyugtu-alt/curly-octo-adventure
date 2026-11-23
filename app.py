import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go
from datetime import timedelta

st.set_page_config(page_title="GALEIC FUTURES PRO", page_icon="📈", layout="wide")

BYBIT = "https://api.bybit.com"
OKX = "https://www.okx.com"

FRAMES = {
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
html,body,[class*="css"]{font-family:'Cairo',sans-serif}
.stApp{background:radial-gradient(circle at top right,#14243b 0%,#080d16 43%,#05080e 100%);color:#f4f7fb}
.block-container{max-width:1150px;padding-top:1rem;padding-bottom:2rem}
.hero{background:linear-gradient(120deg,#12233a,#080e18);border:1px solid #29435f;border-radius:22px;padding:20px;margin-bottom:16px}
.brand{font-size:clamp(25px,5vw,38px);font-weight:800;color:#e8c66a}
.sub,.note{color:#aebdd0;font-size:13px}
.panel{background:rgba(14,23,36,.96);border:1px solid #20354d;border-radius:17px;padding:15px;margin:12px 0}
.metric{background:linear-gradient(145deg,#13243a,#0c1522);border:1px solid #29425e;border-radius:14px;padding:12px 6px;text-align:center;min-height:78px}
.metric-label{font-size:12px;color:#9fb1c6}
.metric-value{font-size:clamp(15px,3vw,21px);font-weight:800;color:#fff;direction:ltr;overflow-wrap:anywhere}
.buy{color:#20d69a!important}.sell{color:#ff6577!important}.wait{color:#e8c66a!important}.gold{color:#e8c66a!important}
div.stButton>button{width:100%;min-height:48px;border-radius:12px;background:linear-gradient(90deg,#c99d3d,#f0d27b);color:#111827;border:1px solid #d2ad50;font-weight:800}
[data-testid="stTextInput"] input,[data-testid="stSelectbox"] div[data-baseweb="select"]{background:#101b2a;color:white}
@media(max-width:640px){.block-container{padding-left:.7rem;padding-right:.7rem}.hero{padding:15px}.panel{padding:11px}}
</style>
""", unsafe_allow_html=True)


class DataError(Exception):
    pass


def get_json(url, params=None):
    try:
        response = requests.get(
            url, params=params, timeout=(8, 18),
            headers={"User-Agent": "Mozilla/5.0 GaleicFuturesPro/3.0"}
        )
    except requests.RequestException as exc:
        raise DataError("تعذر الاتصال بمصدر البيانات. افحص الإنترنت أو جرّب المصدر الآخر.") from exc

    if response.status_code in (403, 451, 429):
        explanations = {
            403: "HTTP 403: مزود البيانات أو شبكة الاستضافة رفضت الطلب.",
            451: "HTTP 451: الوصول مقيّد من مزود البيانات أو بيئة الاستضافة.",
            429: "HTTP 429: تم تجاوز حد الطلبات مؤقتاً."
        }
        raise DataError(explanations[response.status_code] + " اختر OKX أو Bybit من مصدر البيانات.")
    if response.status_code != 200:
        raise DataError(f"فشل الاتصال بمزود البيانات: HTTP {response.status_code}.")
    try:
        return response.json()
    except ValueError as exc:
        raise DataError("استجابة مزود البيانات ليست JSON صالحاً.") from exc


def clean_symbol(text):
    s = text.strip().upper().replace("/", "").replace("-", "").replace(" ", "")
    if s.endswith(".P"):
        s = s[:-2]
    if not s:
        raise DataError("اكتب رمز العملة أولاً، مثل BTC أو BTCUSDT.")
    if s.endswith("USDT"):
        base = s[:-4]
    else:
        base = s
    if not base.isalnum() or len(base) > 20:
        raise DataError("رمز العملة غير صالح. استخدم مثلاً BTC أو BTCUSDT.")
    return base + "USDT", base


def fetch_bybit(symbol, frame):
    interval = FRAMES[frame][0]
    data = get_json(BYBIT + "/v5/market/kline", {
        "category": "linear", "symbol": symbol, "interval": interval, "limit": 500
    })
    if data.get("retCode") != 0:
        raise DataError("Bybit: " + str(data.get("retMsg", "لم يتم العثور على الزوج.")))
    rows = data.get("result", {}).get("list", [])
    if not rows:
        raise DataError("لم يتم العثور على هذا الزوج في عقود Bybit USDT الدائمة.")
    df = pd.DataFrame(rows, columns=["ts","open","high","low","close","volume","turnover"])
    df["open_time"] = pd.to_datetime(pd.to_numeric(df["ts"]), unit="ms", utc=True)
    for col in ["open","high","low","close","volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.sort_values("open_time").reset_index(drop=True)
    duration = timedelta(minutes=FRAMES[frame][2])
    if len(df) and df.iloc[-1].open_time + duration > pd.Timestamp.now(tz="UTC"):
        df = df.iloc[:-1]
    return df[["open_time","open","high","low","close","volume"]].dropna().reset_index(drop=True)


def fetch_okx(symbol, frame):
    _, base = clean_symbol(symbol)
    bar = {
        "1m":"1m","3m":"3m","5m":"5m","15m":"15m","30m":"30m",
        "1h":"1H","2h":"2H","4h":"4H","6h":"6H","12h":"12H",
        "1d":"1D","1w":"1W"
    }[frame]
    inst = f"{base}-USDT-SWAP"
    data = get_json(OKX + "/api/v5/market/candles", {
        "instId": inst, "bar": bar, "limit": "300"
    })
    if data.get("code") != "0":
        raise DataError("OKX: " + str(data.get("msg", "تعذر جلب بيانات الزوج.")))
    rows = data.get("data", [])
    if not rows:
        raise DataError(f"لم يتم العثور على عقد {inst} في OKX.")
    df = pd.DataFrame(rows, columns=["ts","open","high","low","close","volume","vol_ccy","vol_quote","confirm"])
    df["open_time"] = pd.to_datetime(pd.to_numeric(df["ts"]), unit="ms", utc=True)
    for col in ["open","high","low","close","volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.sort_values("open_time").reset_index(drop=True)
    # OKX confirm=1 means candle closed; exclude unconfirmed candle regardless of local clock.
    df = df[df["confirm"].astype(str) == "1"]
    return df[["open_time","open","high","low","close","volume"]].dropna().reset_index(drop=True)


def add_indicators(df):
    d = df.copy()
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
    d["macd"] = e12 - e26
    d["macd_signal"] = d.macd.ewm(span=9, adjust=False).mean()
    prev = c.shift(1)
    tr = pd.concat([(h-l),(h-prev).abs(),(l-prev).abs()],axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1/14, adjust=False).mean()
    d["vol_avg"] = d.volume.rolling(20).mean()
    return d.replace([np.inf,-np.inf],np.nan).dropna().reset_index(drop=True)


def analyze(d):
    if len(d) < 205:
        raise DataError("الشموع المتاحة غير كافية لحساب EMA200. جرّب فريماً آخر.")
    x,p = d.iloc[-1],d.iloc[-2]
    long_rules = [
        (x.ema20>x.ema50,"EMA20 أعلى EMA50"),
        (x.ema50>x.ema200,"EMA50 أعلى EMA200"),
        (x.close>x.ema20,"السعر أعلى EMA20"),
        (x.macd>x.macd_signal,"MACD إيجابي"),
        (50<=x.rsi<72,"RSI يدعم الصعود"),
        (x.volume>x.vol_avg,"الحجم أعلى من متوسط 20 شمعة"),
        (x.close>p.close,"إغلاق أعلى من الشمعة السابقة"),
    ]
    short_rules = [
        (x.ema20<x.ema50,"EMA20 أسفل EMA50"),
        (x.ema50<x.ema200,"EMA50 أسفل EMA200"),
        (x.close<x.ema20,"السعر أسفل EMA20"),
        (x.macd<x.macd_signal,"MACD سلبي"),
        (28<x.rsi<=50,"RSI يدعم الهبوط"),
        (x.volume>x.vol_avg,"الحجم أعلى من متوسط 20 شمعة"),
        (x.close<p.close,"إغلاق أسفل من الشمعة السابقة"),
    ]
    ls = round(sum(bool(a) for a,_ in long_rules)/7*100)
    ss = round(sum(bool(a) for a,_ in short_rules)/7*100)
    if ls>=72 and ls>ss: side,score,rules="LONG",ls,long_rules
    elif ss>=72 and ss>ls: side,score,rules="SHORT",ss,short_rules
    else: side,score,rules="WAIT",max(ls,ss),long_rules if ls>=ss else short_rules
    entry,atr=float(x.close),float(x.atr)
    if side=="LONG":
        stop=entry-1.5*atr; risk=entry-stop; targets=[entry+risk,entry+2*risk,entry+3*risk]
    elif side=="SHORT":
        stop=entry+1.5*atr; risk=stop-entry; targets=[entry-risk,entry-2*risk,entry-3*risk]
    else: stop=None; targets=[]
    return {"side":side,"score":score,"long_score":ls,"short_score":ss,
            "entry":entry,"stop":stop,"targets":targets,"rsi":float(x.rsi),
            "ema20":float(x.ema20),"ema50":float(x.ema50),"ema200":float(x.ema200),
            "macd":float(x.macd),"volratio":float(x.volume/x.vol_avg) if x.vol_avg else 0,
            "rules":rules,"candle":x.open_time}


def fmt(v):
    if v is None or not np.isfinite(v): return "—"
    if abs(v)>=1000: return f"{v:,.2f}"
    if abs(v)>=1: return f"{v:,.6f}".rstrip("0").rstrip(".")
    return f"{v:.10f}".rstrip("0").rstrip(".")


def draw_chart(df,r,symbol,frame):
    v=df.tail(130)
    fig=go.Figure()
    fig.add_trace(go.Candlestick(x=v.open_time,open=v.open,high=v.high,low=v.low,close=v.close,
                                 name="السعر",increasing_line_color="#19c99a",decreasing_line_color="#ff6577"))
    for col,name,color in [("ema20","EMA20","#e8c66a"),("ema50","EMA50","#55a8ff"),("ema200","EMA200","#b18cff")]:
        fig.add_trace(go.Scatter(x=v.open_time,y=v[col],name=name,line=dict(width=1.2,color=color)))
    if r["side"]!="WAIT":
        lines=[("الدخول",r["entry"],"#e8c66a"),("وقف الخسارة",r["stop"],"#ff6577")]
        lines += [(f"TP{i+1}",p,"#19c99a") for i,p in enumerate(r["targets"])]
        for label,y,color in lines:
            fig.add_hline(y=y,line_dash="dash",line_color=color,annotation_text=f"{label}: {fmt(y)}")
    fig.update_layout(template="plotly_dark",height=450,margin=dict(l=5,r=5,t=40,b=5),
                      paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(7,13,22,.8)",
                      xaxis_rangeslider_visible=False,title=f"{symbol} · {frame}")
    return fig


# UI is rendered BEFORE any network call. Thus 403/451 cannot hide the search controls.
st.markdown('<div class="hero" dir="rtl"><div class="brand">GALEIC FUTURES PRO</div><div class="sub">تحليل عقود آجلة · إشارات LONG / SHORT · تحليل فقط دون تنفيذ صفقات</div></div>',unsafe_allow_html=True)

st.markdown('<div class="panel" dir="rtl">',unsafe_allow_html=True)
st.subheader("1. مصدر بيانات العقود")
provider=st.selectbox("اختر المنصة",["OKX Futures","Bybit Futures"],index=0)
st.caption("إذا رفض أحد المزودين الاتصال، جرّب الآخر. لا يلزم API Key.")
st.markdown("</div>",unsafe_allow_html=True)

st.markdown('<div class="panel" dir="rtl">',unsafe_allow_html=True)
st.subheader("2. ابحث عن العملة")
typed=st.text_input("اكتب رمز العملة أو الزوج",value="BTC",placeholder="BTC أو BTCUSDT أو ETH")
symbol,base=clean_symbol(typed) if typed.strip() else ("BTCUSDT","BTC")
frame=st.selectbox("3. اختر الفريم الزمني",list(FRAMES.keys()),index=3,
                   format_func=lambda k:f"{k} — {FRAMES[k][1]}")
st.caption(f"الزوج المطلوب: {symbol} · ستظهر النتائج بعد الضغط على زر التحليل.")
go=st.button("📊 تحليل العملة",use_container_width=True)
st.markdown("</div>",unsafe_allow_html=True)

if go:
    try:
        with st.spinner(f"جارٍ جلب بيانات {symbol} وتحليلها..."):
            if provider.startswith("OKX"):
                raw=fetch_okx(symbol,frame)
            else:
                raw=fetch_bybit(symbol,frame)
            prepared=add_indicators(raw)
            result=analyze(prepared)
            st.session_state["galeic_result"]={"provider":provider,"symbol":symbol,"frame":frame,"df":prepared,"result":result}
    except DataError as exc:
        st.error(str(exc))
        st.info("ملاحظة: أزرار البحث والفريم ظاهرة بالأعلى. إذا فشل المصدر الحالي، بدّله إلى المنصة الأخرى ثم أعد التحليل.")
    except Exception as exc:
        st.error("حدث خطأ غير متوقع أثناء جلب البيانات أو التحليل.")
        st.caption(str(exc))

saved=st.session_state.get("galeic_result")
if saved:
    if (saved["provider"],saved["symbol"],saved["frame"])!=(provider,symbol,frame):
        st.info("غيّرت المصدر أو العملة أو الفريم. اضغط «تحليل العملة» لتحديث النتائج.")
    else:
        r,df=saved["result"],saved["df"]
        side=r["side"]
        side_label="شراء LONG" if side=="LONG" else "بيع SHORT" if side=="SHORT" else "انتظار — لا توجد إشارة قوية"
        cls="buy" if side=="LONG" else "sell" if side=="SHORT" else "wait"
        st.markdown(f'<div class="panel" dir="rtl"><h3>نتيجة التحليل: <span class="{cls}">{side_label}</span></h3><div class="note">المصدر: {provider} · آخر شمعة مغلقة: {r["candle"].strftime("%Y-%m-%d %H:%M UTC")}</div></div>',unsafe_allow_html=True)
        cols=st.columns(3)
        for col,label,value,klass in [(cols[0],"السعر المرجعي",fmt(r["entry"]),""),(cols[1],"توافق المؤشرات",f'{r["score"]}/100',"gold"),(cols[2],"RSI",f'{r["rsi"]:.1f}',"")]:
            with col: st.markdown(f'<div class="metric"><div class="metric-label">{label}</div><div class="metric-value {klass}">{value}</div></div>',unsafe_allow_html=True)
        if side!="WAIT":
            cols=st.columns(5)
            levels=[("الدخول",r["entry"]),("وقف الخسارة",r["stop"]),("TP1",r["targets"][0]),("TP2",r["targets"][1]),("TP3",r["targets"][2])]
            for col,(label,value) in zip(cols,levels):
                with col: st.markdown(f'<div class="metric"><div class="metric-label">{label}</div><div class="metric-value">{fmt(value)}</div></div>',unsafe_allow_html=True)
        else:
            st.warning(f'لا توجد إشارة قوية حالياً. LONG: {r["long_score"]}/100 · SHORT: {r["short_score"]}/100')
        st.plotly_chart(draw_chart(df,r,symbol,frame),use_container_width=True,config={"displayModeBar":False})
        left,right=st.columns(2)
        with left:
            st.markdown('<div class="panel" dir="rtl">',unsafe_allow_html=True)
            st.subheader("المؤشرات")
            st.write(f'EMA20: **{fmt(r["ema20"])}**')
            st.write(f'EMA50: **{fmt(r["ema50"])}**')
            st.write(f'EMA200: **{fmt(r["ema200"])}**')
            st.write(f'MACD: **{r["macd"]:.8f}**')
            st.write(f'الحجم/المتوسط: **{r["volratio"]:.2f}x**')
            st.markdown("</div>",unsafe_allow_html=True)
        with right:
            st.markdown('<div class="panel" dir="rtl">',unsafe_allow_html=True)
            st.subheader("أسباب التقييم")
            for ok,desc in r["rules"]: st.write(("🟢 " if ok else "⚪ ")+desc)
            st.markdown("</div>",unsafe_allow_html=True)
        st.markdown('<div class="panel note" dir="rtl"><b>تنبيه:</b> درجة التوافق ليست احتمال نجاح. مستويات الوقف والأهداف تقديرية باستخدام ATR ولا تضمن الوصول أو التنفيذ. اختبر الاستراتيجية تجريبياً قبل المخاطرة. الأداة لا تنفذ صفقات.</div>',unsafe_allow_html=True)

st.markdown('<div class="note" style="text-align:center;padding:15px" dir="rtl">GALEIC FUTURES PRO · تحليل فقط · لا يحتاج مفاتيح API</div>',unsafe_allow_html=True)
