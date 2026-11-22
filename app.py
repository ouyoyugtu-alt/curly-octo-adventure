import asyncio
import json
import threading
import time
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
import websockets

st.set_page_config(
    page_title="راصد حيتان الفيوتشر المباشر",
    page_icon="🐋",
    layout="wide",
)

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

st.title("🐋 راصد صفقات الحيتان والتصفيات الحقيقية (Futures)")
st.caption(
    "بث مباشر لصفقات التنفيذ الكبيرة (aggTrade) والتصفيات (forceOrder) في عقود الفيوتشر — "
    "الأداة لرصد السيولة وإدارة المخاطر وليست توصية أو ضماناً للربح."
)

# --- تهيئة الحالة العامة ---
if "events" not in st.session_state:
    st.session_state.events = []
if "worker_thread" not in st.session_state:
    st.session_state.worker_thread = None
if "stop_event" not in st.session_state:
    st.session_state.stop_event = None
if "active_symbol" not in st.session_state:
    st.session_state.active_symbol = ""


def ws_listener(symbol: str, min_trade_usd: float, min_liq_usd: float, events_buffer: list, stop_flag: threading.Event):
    sym = symbol.lower()
    url = f"wss://fstream.binance.com/stream?streams={sym}@aggTrade/{sym}@forceOrder"

    async def runner():
        while not stop_flag.is_set():
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    while not stop_flag.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        except asyncio.TimeoutError:
                            continue

                        payload = json.loads(raw)
                        stream = payload.get("stream", "")
                        data = payload.get("data", {})
                        now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")

                        if stream.endswith("@aggTrade"):
                            price = float(data["p"])
                            qty = float(data["q"])
                            usd_val = price * qty
                            if usd_val >= min_trade_usd:
                                side = "بيع هجومي (Sell)" if data["m"] else "شراء هجومي (Buy)"
                                events_buffer.append({
                                    "الوقت (UTC)": now_str,
                                    "النوع": "صفقة حوت",
                                    "الاتجاه": side,
                                    "السعر": round(price, 4),
                                    "الكمية": round(qty, 4),
                                    "القيمة ($)": round(usd_val, 0),
                                })
                                del events_buffer[:-200]

                        elif stream.endswith("@forceOrder"):
                            order = data.get("o", {})
                            price = float(order.get("p", 0))
                            qty = float(order.get("q", 0))
                            usd_val = price * qty
                            if usd_val >= min_liq_usd:
                                liq_side = "تصفية لونغ (Long)" if order.get("S") == "SELL" else "تصفية شورت (Short)"
                                events_buffer.append({
                                    "الوقت (UTC)": now_str,
                                    "النوع": "تصفية كبيرة",
                                    "الاتجاه": liq_side,
                                    "السعر": round(price, 4),
                                    "الكمية": round(qty, 4),
                                    "القيمة ($)": round(usd_val, 0),
                                })
                                del events_buffer[:-200]
            except Exception:
                if not stop_flag.is_set():
                    time.sleep(2)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(runner())
    finally:
        loop.close()


# --- الشريط الجانبي ---
st.sidebar.header("⚙️ إعدادات البث المباشر")
symbol_input = st.sidebar.text_input("رمز العملة في الفيوتشر", value="BTCUSDT").strip().upper()
min_trade_usd = st.sidebar.number_input("حد الصفقة الكبيرة ($)", min_value=10000.0, value=250000.0, step=25000.0)
min_liq_usd = st.sidebar.number_input("حد التصفية الكبيرة ($)", min_value=10000.0, value=100000.0, step=25000.0)

st.sidebar.subheader("🛡️ حاسبة إدارة المخاطر السريعة")
entry_price = st.sidebar.number_input("سعر الدخول المقترح", min_value=0.0001, value=90000.0, step=100.0, format="%.4f")
stop_price = st.sidebar.number_input("سعر وقف الخسارة (SL)", min_value=0.0001, value=89100.0, step=100.0, format="%.4f")
tp1_price = st.sidebar.number_input("الهدف الأول (TP1)", min_value=0.0001, value=91800.0, step=100.0, format="%.4f")
tp2_price = st.sidebar.number_input("الهدف الثاني (TP2)", min_value=0.0001, value=93600.0, step=100.0, format="%.4f")
balance = st.sidebar.number_input("الرصيد ($)", min_value=10.0, value=1000.0, step=100.0)
risk_pct = st.sidebar.slider("مخاطرة الصفقة (%)", 0.25, 5.0, 1.0, 0.25)

col_btn1, col_btn2, col_btn3 = st.columns(3)
start_clicked = col_btn1.button("▶️ تشغيل البث الحقيقي", use_container_width=True)
stop_clicked = col_btn2.button("⏹️ إيقاف البث", use_container_width=True)
clear_clicked = col_btn3.button("🗑️ مسح السجل", use_container_width=True)

if clear_clicked:
    st.session_state.events.clear()

if stop_clicked and st.session_state.stop_event is not None:
    st.session_state.stop_event.set()
    st.session_state.worker_thread = None

if start_clicked:
    if st.session_state.stop_event is not None:
        st.session_state.stop_event.set()
    stop_flag = threading.Event()
    st.session_state.stop_event = stop_flag
    st.session_state.active_symbol = symbol_input
    t = threading.Thread(
        target=ws_listener,
        args=(symbol_input, min_trade_usd, min_liq_usd, st.session_state.events, stop_flag),
        daemon=True,
    )
    t.start()
    st.session_state.worker_thread = t

is_running = st.session_state.worker_thread is not None and st.session_state.worker_thread.is_alive()
st.info(
    f"حالة البث: **{'🟢 متصل (' + st.session_state.active_symbol + ')' if is_running else '⚪ متوقف'}** | "
    f"عدد الأحداث الملتقطة: **{len(st.session_state.events)}**"
)

# --- ملخص إدارة المخاطر ---
risk_dist = abs(entry_price - stop_price)
max_loss = balance * (risk_pct / 100.0)
pos_size = (max_loss / risk_dist) if risk_dist > 0 else 0.0

m1, m2, m3, m4 = st.columns(4)
m1.metric("الحد الأقصى للخسارة", f"${max_loss:,.2f}")
m2.metric("حجم المركز التقديري", f"{pos_size:.4f}")
m3.metric("مسافة الوقف", f"{risk_dist:.4f}")
m4.metric("الهدف 1 / الهدف 2", f"{tp1_price:.4f} / {tp2_price:.4f}")

# --- عرض الصفقات والتصفيات الحقيقية ---
if st.session_state.events:
    df_ev = pd.DataFrame(st.session_state.events).iloc[::-1]
    st.dataframe(df_ev, use_container_width=True, hide_index=True)
else:
    st.warning("اضغط على (تشغيل البث الحقيقي) وانتظر وصول صفقات أو تصفيات تتجاوز الحد المحدد بالدولار.")

auto_refresh = st.checkbox("تحديث تلقائي للواجهة كل ثانيتين أثناء البث", value=True)
if is_running and auto_refresh:
    time.sleep(2)
    st.rerun()
