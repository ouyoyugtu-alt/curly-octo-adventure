import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from core import fetch_ohlcv, add_indicators, analyze_multi, scan_market, get_exchanges
from config import *

st.set_page_config(page_title=APP_TITLE, page_icon=APP_ICON, layout="wide")

# ---------- CSS ----------
st.markdown("""
<style>
  .signal-long  { background:#0f5132; color:#d1e7dd; padding:14px; border-radius:10px; text-align:center; }
  .signal-short { background:#842029; color:#f8d7da; padding:14px; border-radius:10px; text-align:center; }
  .signal-wait  { background:#664d03; color:#fff3cd; padding:14px; border-radius:10px; text-align:center; }
  .metric-box   { background:#1e1e1e; padding:12px; border-radius:8px; text-align:center; margin:4px; }
</style>
""", unsafe_allow_html=True)

def fmt(p):
    if p is None: return "-"
    if p >= 1000: return f"{p:,.2f}"
    if p >= 1:    return f"{p:.4f}"
    return f"{p:.6f}"

def render_levels(L, direction, leverage, pos_size_usd):
    if not L: return
    entry = L["entry"]; sl = L["stop_loss"]; tp2 = L["tp2"]
    if direction == "LONG":
        pnl_sl = (sl - entry) / entry * 100 * leverage
        pnl_tp2 = (tp2 - entry) / entry * 100 * leverage
    else:
        pnl_sl = (entry - sl) / entry * 100 * leverage
        pnl_tp2 = (entry - tp2) / entry * 100 * leverage

    c1, c2, c3 = st.columns(3)
    c1.metric("💰 الدخول", fmt(entry))
    c2.metric("🛑 SL", fmt(sl), f"{pnl_sl:+.2f}%")
    c3.metric("⚖️ R:R", f"1:{L['rr']:.2f}")

    c4, c5, c6 = st.columns(3)
    c4.metric("🎯 TP1", fmt(L["tp1"]))
    c5.metric("🎯 TP2", fmt(tp2), f"{pnl_tp2:+.2f}%")
    c6.metric("🎯 TP3", fmt(L["tp3"]))

    loss_usd = abs(pos_size_usd * pnl_sl / 100 / leverage)
    gain_usd = abs(pos_size_usd * pnl_tp2 / 100 / leverage)
    st.caption(f"💵 حجم {pos_size_usd}$ → خسارة ≈ {loss_usd:.2f}$ | ربح TP2 ≈ {gain_usd:.2f}$")

def render_result(r, leverage, pos_size):
    votes = r["votes"]
    st.markdown("---")
    st.subheader(f"📊 {r['symbol']} — فريم {r['timeframe']}")
    st.write(f"🗳️ تصويت: LONG={votes['LONG']} | SHORT={votes['SHORT']} | WAIT={votes['WAIT']}")

    if r["final"] == "LONG":
        st.markdown('<div class="signal-long"><h3>🟢 LONG</h3></div>', unsafe_allow_html=True)
    elif r["final"] == "SHORT":
        st.markdown('<div class="signal-short"><h3>🔴 SHORT</h3></div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="signal-wait"><h3>🟡 WAIT</h3></div>', unsafe_allow_html=True)

    for name, d in r["details"].items():
        with st.expander(f"{name.upper()} — {d.get('signal','ERROR')}"):
            if "error" in d:
                st.error(d["error"]); continue
            st.write(f"نقاط: {d.get('score', 0)}")
            for rs in d.get("reasons", []):
                st.write(f"- {rs}")

    if r["levels"]:
        st.markdown("#### ✅ المستويات الموصى بها")
        render_levels(r["levels"], r["final"], leverage, pos_size)

# ---------- Sidebar ----------
with st.sidebar:
    st.header("⚙️ الإعدادات")
    mode = st.radio("الوضع", ["تحليل عملة", "مسح السوق", "رسم بياني"])
    timeframe = st.selectbox("الفريم", list(TIMEFRAMES.keys()), index=2)
    leverage = st.slider("الليفرج", 1, 50, TIMEFRAMES[timeframe]["leverage"])
    pos_size = st.number_input("حجم المركز (USDT)", 10.0, 10000.0, 100.0, 10.0)

    symbol = st.text_input("العملة", "BTC/USDT") if mode != "مسح السوق" else None
    top_n = st.slider("عدد العملات للمسح", 5, 50, 20) if mode == "مسح السوق" else None

# ---------- Main ----------
st.title(APP_TITLE)
st.caption(f"Binance + Bybit + OKX — {BUILD_VERSION}")

if mode == "تحليل عملة":
    if st.button("🔍 تحليل", type="primary", use_container_width=True):
        with st.spinner("جارٍ التحليل..."):
            try:
                render_result(analyze_multi(symbol, timeframe), leverage, pos_size)
            except Exception as e:
                st.error(str(e))

elif mode == "مسح السوق":
    if st.button("🚀 مسح السوق", type="primary", use_container_width=True):
        prog = st.progress(0.0, text="بدء")
        def cb(i, n, s): prog.progress((i+1)/n, text=f"{i+1}/{n} — {s}")
        with st.spinner("جارٍ المسح..."):
            res = scan_market(timeframe, top_n, cb)
        prog.empty()
        if not res:
            st.warning("لم يتم إيجاد فرص.")
        else:
            for r in res:
                render_result(r, leverage, pos_size)

elif mode == "رسم بياني":
    if st.button("📈 عرض الشارت", use_container_width=True):
        try:
            df = fetch_ohlcv("binance", symbol, timeframe)
            df = add_indicators(df)
            fig = go.Figure(go.Candlestick(
                x=df["time"], open=df["open"], high=df["high"],
                low=df["low"], close=df["close"], name="Price"))
            for col, colr in [("ema20","orange"),("ema50","blue"),("ema200","purple")]:
                fig.add_scatter(x=df["time"], y=df[col], name=col, line=dict(color=colr, width=1))
            fig.update_layout(height=600, xaxis_rangeslider_visible=False, template="plotly_dark")
            st.plotly_chart(fig, use_container_width=True)

            sig = analyze_multi(symbol, timeframe)
            if sig["levels"]:
                render_levels(sig["levels"], sig["final"], leverage, pos_size)
        except Exception as e:
            st.error(str(e))