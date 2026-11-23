import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go

st.set_page_config(page_title="GALEIC FUTURES PRO", page_icon="📈", layout="wide")
OKX="https://www.okx.com"
BYBIT="https://api.bybit.com"
FRAMES={"1m":("1m","1 دقيقة",1),"3m":("3m","3 دقائق",3),"5m":("5m","5 دقائق",5),
"15m":("15m","15 دقيقة",15),"30m":("30m","30 دقيقة",30),"1h":("1H","1 ساعة",60),
"2h":("2H","ساعتان",120),"4h":("4H","4 ساعات",240),"6h":("6H","6 ساعات",360),
"12h":("12H","12 ساعة",720),"1d":("1D","يومي",1440),"1w":("1W","أسبوعي",10080)}

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
.metric-label{font-size:12px;color:#9fb1c6}.metric-value{font-size:clamp(15px,3vw,21px);font-weight:800;color:#fff;direction:ltr;overflow-wrap:anywhere}
.buy{color:#20d69a!important}.sell{color:#ff6577!important}.wait{color:#e8c66a!important}.gold{color:#e8c66a!important}
div.stButton>button{width:100%;min-height:49px;border-radius:12px;background:linear-gradient(90deg,#c99d3d,#f0d27b);color:#111827;border:1px solid #d2ad50;font-weight:800}
[data-testid="stTextInput"] input,[data-testid="stSelectbox"] div[data-baseweb="select"]{background:#101b2a;color:white}
@media(max-width:640px){.block-container{padding-left:.7rem;padding-right:.7rem}.hero{padding:15px}.panel{padding:11px}}
</style>""",unsafe_allow_html=True)

class DataError(Exception): pass

def get_json(base,path,params):
    try:
        r=requests.get(base+path,params=params,timeout=(8,20),headers={"User-Agent":"Mozilla/5.0 GALEIC-PRO"})
    except requests.RequestException as e:
        raise DataError("تعذر الاتصال بمصدر البيانات. افحص الإنترنت أو جرّب المنصة الأخرى.") from e
    if r.status_code in (403,451,429):
        msg={403:"رفض مزود البيانات الاتصال (403).",451:"الوصول إلى مزود البيانات مقيّد (451).",429:"تجاوزت حد الطلبات مؤقتاً (429)."}
        raise DataError(msg[r.status_code]+" جرّب المصدر الآخر.")
    if r.status_code!=200: raise DataError(f"فشل الاتصال: HTTP {r.status_code}.")
    try:return r.json()
    except ValueError as e: raise DataError("استجابة مزود البيانات غير مفهومة.") from e

def normalize(raw):
    s=raw.strip().upper().replace("/","").replace("-","").replace(" ","")
    if s.endswith(".P"):s=s[:-2]
    base=s[:-4] if s.endswith("USDT") else s
    if not base or not base.isalnum() or len(base)>20: raise DataError("اكتب رمزاً صحيحاً مثل BTC أو ACEUSDT.")
    return base,base+"USDT"

@st.cache_data(ttl=900,show_spinner=False)
def okx_contracts():
    j=get_json(OKX,"/api/v5/public/instruments",{"instType":"SWAP"})
    if j.get("code")!="0":raise DataError("OKX: "+str(j.get("msg","تعذر تحميل قائمة العقود.")))
    out={}
    for x in j.get("data",[]):
        if x.get("state")=="live" and x.get("ctType")=="linear" and x.get("quoteCcy")=="USDT" and x.get("settleCcy")=="USDT":
            out[x.get("baseCcy","").upper()]=x["instId"]
    return out

def fetch_okx(base,frame):
    contracts=okx_contracts()
    inst=contracts.get(base)
    if not inst:
        raise DataError(f"العملة {base} غير مدرجة حالياً كعقد دائم USDT على OKX. جرّب Bybit Futures أو تحقق من رمز العملة.")
    j=get_json(OKX,"/api/v5/market/candles",{"instId":inst,"bar":FRAMES[frame][0],"limit":"300"})
    if j.get("code")!="0":raise DataError(f"OKX ({inst}): {j.get('msg','تعذر جلب الشموع')}")
    rows=j.get("data",[])
    if not rows:raise DataError(f"لا توجد شموع للعقد {inst}.")
    d=pd.DataFrame(rows,columns=["ts","open","high","low","close","volume","v2","v3","confirm"])
    d["open_time"]=pd.to_datetime(pd.to_numeric(d.ts),unit="ms",utc=True)
    for c in ["open","high","low","close","volume"]:d[c]=pd.to_numeric(d[c],errors="coerce")
    d=d[d.confirm.astype(str)=="1"].sort_values("open_time")
    return d[["open_time","open","high","low","close","volume"]].dropna().reset_index(drop=True),inst

def fetch_bybit(symbol,frame):
    interval={"1m":"1","3m":"3","5m":"5","15m":"15","30m":"30","1h":"60","2h":"120","4h":"240","6h":"360","12h":"720","1d":"D","1w":"W"}[frame]
    j=get_json(BYBIT,"/v5/market/kline",{"category":"linear","symbol":symbol,"interval":interval,"limit":"500"})
    if j.get("retCode")!=0:raise DataError("Bybit: "+str(j.get("retMsg","لم يتم العثور على العقد.")))
    rows=j.get("result",{}).get("list",[])
    if not rows:raise DataError(f"لا يوجد عقد {symbol} في Bybit Futures.")
    d=pd.DataFrame(rows,columns=["ts","open","high","low","close","volume","turnover"])
    d["open_time"]=pd.to_datetime(pd.to_numeric(d.ts),unit="ms",utc=True)
    for c in ["open","high","low","close","volume"]:d[c]=pd.to_numeric(d[c],errors="coerce")
    d=d.sort_values("open_time").reset_index(drop=True)
    duration=pd.Timedelta(minutes=FRAMES[frame][2])
    if len(d) and d.iloc[-1].open_time+duration>pd.Timestamp.now(tz="UTC"):d=d.iloc[:-1]
    return d[["open_time","open","high","low","close","volume"]].dropna().reset_index(drop=True),symbol

def indicators(d):
    d=d.copy();c,h,l=d.close,d.high,d.low
    d["ema20"]=c.ewm(span=20,adjust=False).mean();d["ema50"]=c.ewm(span=50,adjust=False).mean();d["ema200"]=c.ewm(span=200,adjust=False).mean()
    delta=c.diff();gain=delta.clip(lower=0).ewm(alpha=1/14,adjust=False).mean();loss=(-delta.clip(upper=0)).ewm(alpha=1/14,adjust=False).mean()
    d["rsi"]=(100-100/(1+gain/loss.replace(0,np.nan))).fillna(50)
    e12=c.ewm(span=12,adjust=False).mean();e26=c.ewm(span=26,adjust=False).mean()
    d["macd"]=e12-e26;d["macds"]=d.macd.ewm(span=9,adjust=False).mean()
    prev=c.shift(1);tr=pd.concat([h-l,(h-prev).abs(),(l-prev).abs()],axis=1).max(axis=1)
    d["atr"]=tr.ewm(alpha=1/14,adjust=False).mean();d["volavg"]=d.volume.rolling(20).mean()
    return d.replace([np.inf,-np.inf],np.nan).dropna().reset_index(drop=True)

def analyze(d):
    if len(d)<205:raise DataError("عدد الشموع المغلقة غير كافٍ لحساب EMA200. جرّب فريماً أكبر.")
    x,p=d.iloc[-1],d.iloc[-2]
    lr=[(x.ema20>x.ema50,"EMA20 أعلى EMA50"),(x.ema50>x.ema200,"EMA50 أعلى EMA200"),(x.close>x.ema20,"السعر أعلى EMA20"),(x.macd>x.macds,"MACD إيجابي"),(50<=x.rsi<72,"RSI يدعم الصعود"),(x.volume>x.volavg,"الحجم أعلى متوسط 20 شمعة"),(x.close>p.close,"الإغلاق أعلى من السابق")]
    sr=[(x.ema20<x.ema50,"EMA20 أسفل EMA50"),(x.ema50<x.ema200,"EMA50 أسفل EMA200"),(x.close<x.ema20,"السعر أسفل EMA20"),(x.macd<x.macds,"MACD سلبي"),(28<x.rsi<=50,"RSI يدعم الهبوط"),(x.volume>x.volavg,"الحجم أعلى متوسط 20 شمعة"),(x.close<p.close,"الإغلاق أسفل السابق")]
    ls=round(sum(bool(a) for a,b in lr)/7*100);ss=round(sum(bool(a) for a,b in sr)/7*100)
    if ls>=72 and ls>ss:side,score,rules="LONG",ls,lr
    elif ss>=72 and ss>ls:side,score,rules="SHORT",ss,sr
    else:side,score,rules="WAIT",max(ls,ss),lr if ls>=ss else sr
    entry,atr=float(x.close),float(x.atr)
    if side=="LONG":stop=entry-1.5*atr;risk=entry-stop;targets=[entry+risk,entry+2*risk,entry+3*risk]
    elif side=="SHORT":stop=entry+1.5*atr;risk=stop-entry;targets=[entry-risk,entry-2*risk,entry-3*risk]
    else:stop=None;targets=[]
    return {"side":side,"score":score,"ls":ls,"ss":ss,"entry":entry,"stop":stop,"targets":targets,"rsi":float(x.rsi),"ema20":float(x.ema20),"ema50":float(x.ema50),"ema200":float(x.ema200),"macd":float(x.macd),"volratio":float(x.volume/x.volavg) if x.volavg else 0,"rules":rules,"candle":x.open_time}

def fmt(v):
    if v is None or not np.isfinite(v):return "—"
    if abs(v)>=1000:return f"{v:,.2f}"
    if abs(v)>=1:return f"{v:,.6f}".rstrip("0").rstrip(".")
    return f"{v:.10f}".rstrip("0").rstrip(".")

def chart(d,r,title):
    v=d.tail(140);f=go.Figure()
    f.add_trace(go.Candlestick(x=v.open_time,open=v.open,high=v.high,low=v.low,close=v.close,name="السعر",increasing_line_color="#19c99a",decreasing_line_color="#ff6577"))
    for c,n,k in [("ema20","EMA20","#e8c66a"),("ema50","EMA50","#55a8ff"),("ema200","EMA200","#b18cff")]:f.add_trace(go.Scatter(x=v.open_time,y=v[c],name=n,line=dict(width=1.2,color=k)))
    if r["side"]!="WAIT":
        levels=[("الدخول",r["entry"],"#e8c66a"),("وقف الخسارة",r["stop"],"#ff6577")]+[(f"TP{i+1}",p,"#19c99a") for i,p in enumerate(r["targets"])]
        for n,y,k in levels:f.add_hline(y=y,line_dash="dash",line_color=k,annotation_text=f"{n}: {fmt(y)}")
    f.update_layout(template="plotly_dark",height=440,margin=dict(l=5,r=5,t=40,b=5),paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(7,13,22,.8)",xaxis_rangeslider_visible=False,title=title)
    return f

# Controls are displayed before any API request, so API errors never hide the search form.
st.markdown('<div class="hero" dir="rtl"><div class="brand">GALEIC FUTURES PRO</div><div class="sub">محلل عقود آجلة · LONG / SHORT · تحليل فقط دون تنفيذ صفقات</div></div>',unsafe_allow_html=True)
st.markdown('<div class="panel" dir="rtl">',unsafe_allow_html=True)
st.subheader("1. مصدر بيانات العقود")
provider=st.selectbox("اختر المنصة",["OKX Futures","Bybit Futures"])
st.caption("عقود USDT الدائمة فقط · لا تحتاج مفاتيح API")
st.markdown("</div>",unsafe_allow_html=True)
st.markdown('<div class="panel" dir="rtl">',unsafe_allow_html=True)
st.subheader("2. ابحث عن العملة")
typed=st.text_input("رمز العملة أو الزوج",value="BTC",placeholder="BTC أو ETH أو ACEUSDT")
frame=st.selectbox("3. اختر الفريم الزمني",list(FRAMES),index=3,format_func=lambda k:f"{k} — {FRAMES[k][1]}")
st.caption("اكتب الرمز الأساسي أو الزوج مع USDT.")
clicked=st.button("📊 تحليل العملة",use_container_width=True)
st.markdown("</div>",unsafe_allow_html=True)

if clicked:
    try:
        base,symbol=normalize(typed)
        with st.spinner(f"جارٍ البحث عن {base} وجلب الشموع..."):
            if provider=="OKX Futures":raw,exchange_symbol=fetch_okx(base,frame)
            else:raw,exchange_symbol=fetch_bybit(symbol,frame)
            data=indicators(raw);result=analyze(data)
            st.session_state["galeic_v4"]={"provider":provider,"base":base,"exchange_symbol":exchange_symbol,"frame":frame,"data":data,"result":result}
    except DataError as e:
        st.error(str(e));st.info("إذا لم تكن العملة مدرجة على هذه المنصة، بدّل إلى المنصة الأخرى ثم اضغط تحليل العملة.")
    except Exception as e:
        st.error("حدث خطأ غير متوقع أثناء التحليل.");st.caption(str(e))

saved=st.session_state.get("galeic_v4")
if saved:
    try:current_base,_=normalize(typed)
    except DataError:current_base=""
    if (saved["provider"],saved["base"],saved["frame"])!=(provider,current_base,frame):
        st.info("غيّرت العملة أو المنصة أو الفريم. اضغط تحليل العملة لتحديث النتائج.")
    else:
        r,d=saved["result"],saved["data"];side=r["side"]
        label="شراء LONG" if side=="LONG" else "بيع SHORT" if side=="SHORT" else "انتظار — لا توجد إشارة قوية"
        css="buy" if side=="LONG" else "sell" if side=="SHORT" else "wait"
        st.markdown(f'<div class="panel" dir="rtl"><h3>نتيجة التحليل: <span class="{css}">{label}</span></h3><div class="note">المنصة: {provider} · العقد: {saved["exchange_symbol"]} · آخر شمعة مغلقة: {r["candle"].strftime("%Y-%m-%d %H:%M UTC")}</div></div>',unsafe_allow_html=True)
        cards=[("السعر المرجعي",fmt(r["entry"]),""),("توافق المؤشرات",f'{r["score"]}/100',"gold"),("RSI",f'{r["rsi"]:.1f}',"")]
        cols=st.columns(3)
        for col,(n,v,k) in zip(cols,cards):
            with col:st.markdown(f'<div class="metric"><div class="metric-label">{n}</div><div class="metric-value {k}">{v}</div></div>',unsafe_allow_html=True)
        if side!="WAIT":
            cols=st.columns(5);levels=[("الدخول",r["entry"]),("وقف الخسارة",r["stop"]),("TP1",r["targets"][0]),("TP2",r["targets"][1]),("TP3",r["targets"][2])]
            for col,(n,v) in zip(cols,levels):
                with col:st.markdown(f'<div class="metric"><div class="metric-label">{n}</div><div class="metric-value">{fmt(v)}</div></div>',unsafe_allow_html=True)
        else:st.warning(f'لا توجد إشارة قوية. LONG: {r["ls"]}/100 · SHORT: {r["ss"]}/100')
        st.plotly_chart(chart(d,r,f'{saved["exchange_symbol"]} · {frame}'),use_container_width=True,config={"displayModeBar":False})
        a,b=st.columns(2)
        with a:
            st.markdown('<div class="panel" dir="rtl">',unsafe_allow_html=True);st.subheader("المؤشرات")
            st.write(f'EMA20: **{fmt(r["ema20"])}**');st.write(f'EMA50: **{fmt(r["ema50"])}**');st.write(f'EMA200: **{fmt(r["ema200"])}**');st.write(f'MACD: **{r["macd"]:.8f}**');st.write(f'الحجم/المتوسط: **{r["volratio"]:.2f}x**');st.markdown("</div>",unsafe_allow_html=True)
        with b:
            st.markdown('<div class="panel" dir="rtl">',unsafe_allow_html=True);st.subheader("أسباب التقييم")
            for ok,desc in r["rules"]:st.write(("🟢 " if ok else "⚪ ")+desc)
            st.markdown("</div>",unsafe_allow_html=True)
        st.markdown('<div class="panel note" dir="rtl"><b>تنبيه:</b> درجة التوافق ليست احتمال نجاح. الأهداف ووقف الخسارة تقديرية باستخدام ATR ولا تضمن الوصول إليها. الأداة لا تنفذ صفقات.</div>',unsafe_allow_html=True)

st.markdown('<div class="note" style="text-align:center;padding:15px" dir="rtl">GALEIC FUTURES PRO · تحليل فقط · لا يحتاج مفاتيح API</div>',unsafe_allow_html=True)
