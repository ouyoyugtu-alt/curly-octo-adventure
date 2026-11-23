import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go
from concurrent.futures import ThreadPoolExecutor, as_completed

st.set_page_config(page_title="GALEIC FUTURES PRO", page_icon="📈", layout="wide")
BYBIT="https://api.bybit.com"
FRAMES={"1m":("1",1),"3m":("3",3),"5m":("5",5),"15m":("15",15),"30m":("30",30),
"1h":("60",60),"2h":("120",120),"4h":("240",240),"6h":("360",360),"12h":("720",720),
"1D":("D",1440),"1W":("W",10080)}
POPULAR=["BTC","ETH","SOL","XRP","BNB","DOGE","ADA","AVAX","LINK","SUI"]

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;500;600;700;800&display=swap');
html,body,[class*="css"]{font-family:'Cairo',sans-serif}
.stApp{background:#080d16;color:#eef3fa}.block-container{max-width:1250px;padding-top:1rem;padding-bottom:2rem}
.hero{background:linear-gradient(115deg,#172b45,#0b1320);border:1px solid #2c4562;border-radius:20px;padding:18px;margin-bottom:14px}
.brand{font-size:clamp(25px,5vw,36px);font-weight:800;color:#e8c66a}.muted{color:#a9b8ca;font-size:13px}
.panel{background:#101a29;border:1px solid #22364e;border-radius:16px;padding:14px;margin:10px 0}
.tile{background:linear-gradient(145deg,#17283e,#101a29);border:1px solid #2b4058;border-radius:13px;padding:12px 8px;text-align:center;min-height:76px}
.tile small{color:#9fb0c4;font-size:12px}.tile strong{display:block;color:#f5f7fb;font-size:clamp(15px,2.6vw,21px);overflow-wrap:anywhere}
.up{color:#20d69a!important}.down{color:#ff687a!important}.gold{color:#e8c66a!important}
div.stButton>button{border-radius:11px;min-height:43px;font-weight:700}
div.stButton>button[kind="primary"]{background:linear-gradient(90deg,#c99d3d,#f0d27b);color:#111827;border:0}
@media(max-width:640px){.block-container{padding-left:.65rem;padding-right:.65rem}.panel{padding:10px}.hero{padding:14px}}
</style>""",unsafe_allow_html=True)

class MarketError(Exception): pass

def get_json(url,params=None):
    try:r=requests.get(url,params=params,timeout=(7,15),headers={"User-Agent":"Mozilla/5.0 GALEIC"})
    except requests.RequestException as e:raise MarketError("تعذر الاتصال بمصدر البيانات. تحقق من الإنترنت.") from e
    if r.status_code in (403,429,451):raise MarketError(f"رفض مزود البيانات الطلب HTTP {r.status_code}. جرّب لاحقاً أو مصدراً آخر.")
    if r.status_code!=200:raise MarketError(f"فشل الاتصال HTTP {r.status_code}.")
    try:return r.json()
    except ValueError as e:raise MarketError("استجابة مزود البيانات غير مفهومة.") from e

def base_symbol(raw):
    s=str(raw).strip().upper().replace("/","").replace("-","").replace(" ","")
    if s.endswith(".P"):s=s[:-2]
    if s.endswith("USDT"):s=s[:-4]
    if not s or not s.isalnum() or len(s)>20:raise MarketError("أدخل رمزاً صحيحاً مثل BTC أو ETH أو SOLUSDT.")
    return s

@st.cache_data(ttl=600,show_spinner=False)
def search_exchanges(base):
    pair=base+"USDT";out=[]
    # Binance
    try:
        j=get_json("https://fapi.binance.com/fapi/v1/exchangeInfo")
        ok=any(x.get("symbol")==pair and x.get("contractType")=="PERPETUAL" and x.get("status")=="TRADING" for x in j.get("symbols",[]))
        out.append({"المنصة":"Binance Futures","الحالة":"متاح" if ok else "غير مدرج"})
    except Exception:out.append({"المنصة":"Binance Futures","الحالة":"تعذر الاتصال"})
    # Bybit
    try:
        j=get_json(BYBIT+"/v5/market/instruments-info",{"category":"linear","symbol":pair})
        ok=any(x.get("symbol")==pair and x.get("status")=="Trading" for x in j.get("result",{}).get("list",[]))
        out.append({"المنصة":"Bybit Futures","الحالة":"متاح" if ok else "غير مدرج"})
    except Exception:out.append({"المنصة":"Bybit Futures","الحالة":"تعذر الاتصال"})
    # OKX
    try:
        j=get_json("https://www.okx.com/api/v5/public/instruments",{"instType":"SWAP"})
        ok=any(x.get("baseCcy")==base and x.get("quoteCcy")=="USDT" and x.get("settleCcy")=="USDT" and x.get("state")=="live" and x.get("ctType")=="linear" for x in j.get("data",[]))
        out.append({"المنصة":"OKX Futures","الحالة":"متاح" if ok else "غير مدرج"})
    except Exception:out.append({"المنصة":"OKX Futures","الحالة":"تعذر الاتصال"})
    # Gate
    try:
        j=get_json("https://api.gateio.ws/api/v4/futures/usdt/contracts")
        ok=any(x.get("name")==base+"_USDT" and not x.get("in_delisting",False) for x in j if isinstance(x,dict))
        out.append({"المنصة":"Gate.io Futures","الحالة":"متاح" if ok else "غير مدرج"})
    except Exception:out.append({"المنصة":"Gate.io Futures","الحالة":"تعذر الاتصال"})
    return out

@st.cache_data(ttl=45,show_spinner=False)
def candles(symbol,frame):
    j=get_json(BYBIT+"/v5/market/kline",{"category":"linear","symbol":symbol+"USDT","interval":FRAMES[frame][0],"limit":500})
    if j.get("retCode")!=0:raise MarketError("Bybit: "+str(j.get("retMsg","تعذر جلب الشموع.")))
    rows=j.get("result",{}).get("list",[])
    if not rows:raise MarketError(f"لا توجد شموع للعقد {symbol}USDT على Bybit.")
    d=pd.DataFrame(rows,columns=["ts","open","high","low","close","volume","turnover"])
    d["time"]=pd.to_datetime(pd.to_numeric(d.ts),unit="ms",utc=True)
    for c in ["open","high","low","close","volume"]:d[c]=pd.to_numeric(d[c],errors="coerce")
    d=d.sort_values("time").reset_index(drop=True)
    dur=pd.Timedelta(minutes=FRAMES[frame][1])
    if len(d) and d.iloc[-1].time+dur>pd.Timestamp.now(tz="UTC"):d=d.iloc[:-1]
    return d[["time","open","high","low","close","volume"]].dropna().reset_index(drop=True)

@st.cache_data(ttl=30,show_spinner=False)
def ticker(symbol):
    j=get_json(BYBIT+"/v5/market/tickers",{"category":"linear","symbol":symbol+"USDT"})
    a=j.get("result",{}).get("list",[])
    if j.get("retCode")!=0 or not a:raise MarketError("بيانات العقود غير متاحة لهذه العملة.")
    return a[0]

@st.cache_data(ttl=60,show_spinner=False)
def oi_data(symbol):
    j=get_json(BYBIT+"/v5/market/open-interest",{"category":"linear","symbol":symbol+"USDT","intervalTime":"15min","limit":1})
    a=j.get("result",{}).get("list",[])
    return float(a[0]["openInterest"]) if j.get("retCode")==0 and a else None

@st.cache_data(ttl=60,show_spinner=False)
def ls_data(symbol):
    j=get_json(BYBIT+"/v5/market/account-ratio",{"category":"linear","symbol":symbol+"USDT","period":"15min","limit":1})
    a=j.get("result",{}).get("list",[])
    return a[0] if j.get("retCode")==0 and a else None

def indicators(d):
    x=d.copy();c,h,l=x.close,x.high,x.low
    for n in [20,50,200]:x[f"ema{n}"]=c.ewm(span=n,adjust=False).mean()
    delta=c.diff();gain=delta.clip(lower=0).ewm(alpha=1/14,adjust=False).mean();loss=(-delta.clip(upper=0)).ewm(alpha=1/14,adjust=False).mean()
    x["rsi"]=(100-100/(1+gain/loss.replace(0,np.nan))).fillna(50)
    e12=c.ewm(span=12,adjust=False).mean();e26=c.ewm(span=26,adjust=False).mean()
    x["macd"]=e12-e26;x["macds"]=x.macd.ewm(span=9,adjust=False).mean()
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    x["atr"]=tr.ewm(alpha=1/14,adjust=False).mean()
    x["bbmid"]=c.rolling(20).mean();sd=c.rolling(20).std()
    x["bbup"]=x.bbmid+2*sd;x["bblow"]=x.bbmid-2*sd
    x["volavg"]=x.volume.rolling(20).mean()
    return x.replace([np.inf,-np.inf],np.nan).dropna().reset_index(drop=True)

def signal_for(d):
    if len(d)<205:raise MarketError("الشموع غير كافية لحساب EMA200. اختر فريماً أكبر.")
    x,p=d.iloc[-1],d.iloc[-2]
    up=[x.ema20>x.ema50,x.ema50>x.ema200,x.close>x.ema20,x.macd>x.macds,50<=x.rsi<70,x.close>p.close]
    dn=[x.ema20<x.ema50,x.ema50<x.ema200,x.close<x.ema20,x.macd<x.macds,30<x.rsi<=50,x.close<p.close]
    a=round(100*sum(up)/6);b=round(100*sum(dn)/6)
    if a>=67 and a>b:side,score="LONG",a
    elif b>=67 and b>a:side,score="SHORT",b
    else:side,score="WAIT",max(a,b)
    entry=float(x.close);atr=float(x.atr)
    if side=="LONG":stop=entry-1.5*atr;targets=[entry+(entry-stop)*k for k in (1,2,3)]
    elif side=="SHORT":stop=entry+1.5*atr;targets=[entry-(stop-entry)*k for k in (1,2,3)]
    else:stop=None;targets=[]
    return {"side":side,"score":score,"long":a,"short":b,"entry":entry,"stop":stop,"targets":targets,
            "rsi":float(x.rsi),"ema20":float(x.ema20),"ema50":float(x.ema50),"ema200":float(x.ema200),
            "macd":float(x.macd),"atr":atr,"time":x.time}

def fmt(v):
    if v is None:return "—"
    try:
        v=float(v)
        if not np.isfinite(v):return "—"
        return f"{v:,.2f}" if abs(v)>=1000 else (f"{v:,.6f}".rstrip("0").rstrip(".") if abs(v)>=1 else f"{v:.10f}".rstrip("0").rstrip("."))
    except Exception:return "—"

def tile(label,value,cls=""):
    st.markdown(f'<div class="tile"><small>{label}</small><strong class="{cls}">{value}</strong></div>',unsafe_allow_html=True)

def chart(d,symbol):
    v=d.tail(220);f=go.Figure()
    f.add_trace(go.Candlestick(x=v.time,open=v.open,high=v.high,low=v.low,close=v.close,name="السعر",increasing_line_color="#20c997",decreasing_line_color="#ff687a"))
    for col,name,color in [("ema20","EMA20","#e8c66a"),("ema50","EMA50","#55a8ff"),("ema200","EMA200","#b18cff"),("bbup","BB Upper","#778899"),("bblow","BB Lower","#778899")]:
        f.add_trace(go.Scatter(x=v.time,y=v[col],name=name,line=dict(width=1,color=color,dash="dot" if "BB" in name else "solid")))
    f.update_layout(template="plotly_dark",height=450,margin=dict(l=5,r=5,t=35,b=5),paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="#0b1421",xaxis_rangeslider_visible=False,title=f"{symbol}USDT · شموع يابانية",legend=dict(orientation="h",y=1.08))
    return f

def scan_one(s):
    try:
        d=indicators(candles(s,"15m"));r=signal_for(d)
        return {"العملة":s,"الإشارة":r["side"],"قوة التوافق":r["score"],"RSI":round(r["rsi"],1)}
    except Exception:return {"العملة":s,"الإشارة":"غير متاح","قوة التوافق":0,"RSI":"—"}

st.markdown('<div class="hero" dir="rtl"><div class="brand">GALEIC FUTURES PRO</div><div class="muted">منصة تحليل العملات والعقود الآجلة · بيانات عامة مجانية · تحليل فقط</div></div>',unsafe_allow_html=True)

# Search bar
st.markdown('<div class="panel" dir="rtl">',unsafe_allow_html=True)
st.subheader("🔎 البحث الشامل عن العملات")
c1,c2=st.columns([3,1])
with c1:q=st.text_input("رمز العملة",value=st.session_state.get("active_symbol","BTC"),placeholder="BTC / ETH / SOL")
with c2:
    st.write("");st.write("")
    search=st.button("بحث في المنصات",type="primary",use_container_width=True)
if search:
    try:
        s=base_symbol(q)
        with st.spinner("يتم البحث في المنصات..."):st.session_state["exchange_results"]=search_exchanges(s)
        st.session_state["active_symbol"]=s
    except MarketError as e:st.error(str(e))
symbol=st.session_state.get("active_symbol","BTC")
if st.session_state.get("exchange_results"):
    st.caption(f"حالة إدراج {symbol}USDT")
    st.dataframe(pd.DataFrame(st.session_state["exchange_results"]),use_container_width=True,hide_index=True)
st.markdown("</div>",unsafe_allow_html=True)

# Chart and timeframe selector
st.markdown('<div class="panel" dir="rtl">',unsafe_allow_html=True)
st.subheader(f"📊 الرسم البياني — {symbol}USDT")
frame=st.radio("الفريم الزمني",list(FRAMES),index=3,horizontal=True)
st.caption("الرسم والمؤشرات من Bybit Futures عبر واجهة بيانات عامة.")
st.markdown("</div>",unsafe_allow_html=True)
try:
    with st.spinner("تحميل الرسم والشموع..."):
        raw=candles(symbol,frame);data=indicators(raw);sig=signal_for(data)
    st.plotly_chart(chart(data,symbol),use_container_width=True,config={"displaylogo":False,"scrollZoom":True,"responsive":True})
except Exception as e:
    data,sig=None,None
    st.warning(str(e))

# Market indicators
st.markdown('<div class="panel" dir="rtl">',unsafe_allow_html=True)
st.subheader("📈 لوحة مؤشرات السوق")
if data is not None:
    x=data.iloc[-1]
    vals=[("السعر",fmt(x.close),""),("RSI",f"{x.rsi:.1f}",""),("MACD","صاعد" if x.macd>x.macds else "هابط","up" if x.macd>x.macds else "down"),("ATR",fmt(x.atr),"")]
    cols=st.columns(4)
    for col,(a,b,c) in zip(cols,vals):
        with col:tile(a,b,c)
    cols=st.columns(3)
    for col,(a,b) in zip(cols,[("EMA20",fmt(x.ema20)),("EMA50",fmt(x.ema50)),("EMA200",fmt(x.ema200))]):
        with col:tile(a,b)
else:st.info("ستظهر المؤشرات بعد تحميل بيانات العملة.")
st.markdown("</div>",unsafe_allow_html=True)

# Futures metrics
st.markdown('<div class="panel" dir="rtl">',unsafe_allow_html=True)
st.subheader("⚡ لوحة العقود الآجلة — Bybit")
try:
    t=ticker(symbol);oi=oi_data(symbol);ratio=ls_data(symbol)
    change=float(t.get("price24hPcnt",0))*100;fund=float(t.get("fundingRate",0))*100
    cols=st.columns(4)
    vals=[("تغير 24 ساعة",f"{change:+.2f}%","up" if change>=0 else "down"),("Funding Rate",f"{fund:+.4f}%",""),("Open Interest",fmt(oi),""),("حجم 24 ساعة",fmt(t.get("turnover24h")),"")]
    for col,(a,b,c) in zip(cols,vals):
        with col:tile(a,b,c)
    if ratio:
        cols=st.columns(2)
        with cols[0]:tile("نسبة LONG",f'{float(ratio.get("buyRatio",0))*100:.1f}%')
        with cols[1]:tile("نسبة SHORT",f'{float(ratio.get("sellRatio",0))*100:.1f}%')
    else:st.caption("نسبة Long/Short غير متاحة حالياً.")
except Exception as e:st.warning("تعذر تحميل بيانات العقود: "+str(e))
st.caption("البيانات مجانية من Bybit؛ بعض الحقول قد لا تتوفر لكل عقد.")
st.markdown("</div>",unsafe_allow_html=True)

# Signal panel
st.markdown('<div class="panel" dir="rtl">',unsafe_allow_html=True)
st.subheader("🎯 إشارات الدخول والخروج")
if sig:
    side=sig["side"];label="LONG — شراء" if side=="LONG" else "SHORT — بيع" if side=="SHORT" else "WAIT — انتظار"
    cls="up" if side=="LONG" else "down" if side=="SHORT" else "gold"
    st.markdown(f'<h2 class="{cls}">{label}</h2>',unsafe_allow_html=True)
    cols=st.columns(3)
    for col,(a,b) in zip(cols,[("قوة التوافق",f'{sig["score"]}/100'),("تقييم LONG",f'{sig["long"]}/100'),("تقييم SHORT",f'{sig["short"]}/100')]):
        with col:tile(a,b)
    if side!="WAIT":
        cols=st.columns(5);levels=[("الدخول",sig["entry"]),("وقف الخسارة",sig["stop"])]+[(f"TP{i+1}",v) for i,v in enumerate(sig["targets"])]
        for col,(a,b) in zip(cols,levels):
            with col:tile(a,fmt(b))
    else:st.info("لا توجد إشارة قوية حالياً؛ الأفضل انتظار تأكيد بدلاً من الدخول القسري.")
    st.caption("آخر شمعة مغلقة: "+sig["time"].strftime("%Y-%m-%d %H:%M UTC"))
else:st.info("حمّل بيانات العملة لعرض الإشارة.")
st.markdown("</div>",unsafe_allow_html=True)

# Favorites
st.markdown('<div class="panel" dir="rtl">',unsafe_allow_html=True)
st.subheader("⭐ قائمة العملات المفضلة")
if "favorites" not in st.session_state:st.session_state["favorites"]=["BTC","ETH","SOL"]
a,b=st.columns([3,1])
with a:fav=st.text_input("أضف عملة",placeholder="مثال XRP",key="fav_input")
with b:
    st.write("");st.write("")
    if st.button("إضافة ⭐",use_container_width=True):
        try:
            z=base_symbol(fav)
            if z not in st.session_state["favorites"]:st.session_state["favorites"].append(z)
        except MarketError as e:st.error(str(e))
favs=st.session_state["favorites"]
if favs:
    selected=st.selectbox("اختر عملة",favs)
    if st.button("فتح تحليل العملة المختارة",use_container_width=True):
        st.session_state["active_symbol"]=selected;st.rerun()
    delete=st.selectbox("حذف عملة",["—"]+favs)
    if delete!="—" and st.button("حذف من المفضلة"):
        st.session_state["favorites"]=[z for z in favs if z!=delete];st.rerun()
st.markdown("</div>",unsafe_allow_html=True)

# Ranking
st.markdown('<div class="panel" dir="rtl">',unsafe_allow_html=True)
st.subheader("🏆 ترتيب العملات حسب قوة الإشارة")
st.caption("يفحص العملات المفضلة والعملات الرئيسية على فريم 15 دقيقة.")
if st.button("تحديث ترتيب العملات",use_container_width=True):
    todo=list(dict.fromkeys(favs+POPULAR));rows=[];bar=st.progress(0)
    with ThreadPoolExecutor(max_workers=4) as pool:
        fs=[pool.submit(scan_one,z) for z in todo]
        for i,f in enumerate(as_completed(fs),1):
            rows.append(f.result());bar.progress(i/len(fs))
    st.session_state["ranking"]=pd.DataFrame(rows).sort_values("قوة التوافق",ascending=False)
if "ranking" in st.session_state:st.dataframe(st.session_state["ranking"],use_container_width=True,hide_index=True)
st.markdown("</div>",unsafe_allow_html=True)

st.markdown('<div class="muted" style="text-align:center;padding:15px" dir="rtl">GALEIC FUTURES PRO · نسخة مجانية · تحليل فقط دون تنفيذ صفقات<br>الإشارات تقديرية وليست ضماناً للربح. بيانات التصفية والخرائط الحرارية المتقدمة غير مشمولة.</div>',unsafe_allow_html=True)
