import time
import ccxt
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
    page_title="Futures Signal Scanner Pro v3.0",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

TIMEFRAMES = ["5m", "15m", "30m", "1h", "2h", "4h", "1d"]


# ============================================================
#                    إعداد المنصات
# ============================================================
@st.cache_resource
def get_exchanges():
    return {
        "okx": ccxt.okx({
            "options": {"defaultType": "swap"},
            "enableRateLimit": True,
            "timeout": 15000,
        }),
        "bybit": ccxt.bybit({
            "options": {"defaultType": "swap"},
            "enableRateLimit": True,
            "timeout": 15000,
        }),
        "binance": ccxt.binance({
            "options": {"defaultType": "future"},
            "enableRateLimit": True,
            "timeout": 15000,
        }),
    }


EXCHANGES = get_exchanges()


def normalize_input_symbol(raw_symbol: str) -> str:
    s = (raw_symbol or "BTC/USDT").strip().upper()
    s = s.replace("-SWAP", "").replace(":USDT", "").replace("-", "/")
    if "/" not in s:
        s = f"{s}/USDT"
    base, quote = s.split("/")[:2]
    base = base.strip()
    quote = (quote or "USDT").strip()
    return f"{base}/{quote}"


def get_symbol_for_exchange(clean_symbol: str, exchange_name: str) -> str:
    base, quote = clean_symbol.split("/")
    if exchange_name == "binance":
        return f"{base}/{quote}"
    if exchange_name == "bybit":
        return f"{base}/{quote}:{quote}"
    if exchange_name == "okx":
        return f"{base}-{quote}-SWAP"
    return clean_symbol


# ============================================================
#                   جلب البيانات والمؤشرات
# ============================================================
def fetch_ohlcv_df(exchange_name: str, clean_symbol: str, timeframe: str, limit: int = 400) -> pd.DataFrame:
    ex = EXCHANGES[exchange_name]
    sym = get_symbol_for_exchange(clean_symbol, exchange_name)
    ohlcv = ex.fetch_ohlcv(sym, timeframe, limit=limit)
    if not ohlcv or len(ohlcv) < 210:
        raise ValueError(f"بيانات غير كافية ({len(ohlcv) if ohlcv else 0} شمعة) من {exchange_name} لـ {sym}")
    df = pd.DataFrame(ohlcv, columns=["time", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["time"], unit="ms")
    return df


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    close = d["close"].astype(float)
    high = d["high"].astype(float)
    low = d["low"].astype(float)
    vol = d["volume"].astype(float)

    d["ema20"] = close.ewm(span=20, adjust=False).mean()
    d["ema50"] = close.ewm(span=50, adjust=False).mean()
    d["ema200"] = close.ewm(span=200, adjust=False).mean()

    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / loss.replace(0.0, np.nan)
    d["rsi"] = 100.0 - (100.0 / (1.0 + rs))

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    d["macd"] = ema12 - ema26
    d["macd_signal"] = d["macd"].ewm(span=9, adjust=False).mean()
    d["macd_hist"] = d["macd"] - d["macd_signal"]

    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    d["atr"] = tr.rolling(14).mean()

    d["bb_mid"] = close.rolling(20).mean()
    d["bb_std"] = close.rolling(20).std()
    d["bb_up"] = d["bb_mid"] + 2.0 * d["bb_std"]
    d["bb_dn"] = d["bb_mid"] - 2.0 * d["bb_std"]

    d["vol_ma"] = vol.rolling(20).mean()

    rsi_min = d["rsi"].rolling(14).min()
    rsi_max = d["rsi"].rolling(14).max()
    d["stoch_rsi"] = (d["rsi"] - rsi_min) / (rsi_max - rsi_min).replace(0.0, np.nan)

    return d


# ============================================================
#                   محرك الإشارات والأهداف
# ============================================================
def evaluate_signal(df: pd.DataFrame, min_score: int = 6) -> dict:
    last = df.iloc[-1]
    prev = df.iloc[-2]

    long_score = 0
    short_score = 0
    long_reasons = []
    short_reasons = []

    price = float(last["close"])
    atr = float(last["atr"]) if pd.notna(last["atr"]) and last["atr"] > 0 else price * 0.012

    # 1. الاتجاه العام طويل المدى (EMA 200)
    if pd.notna(last["ema200"]):
        if price > last["ema200"]:
            long_score += 2
            long_reasons.append("السعر أعلى من EMA 200 (اتجاه عام صاعد)")
        else:
            short_score += 2
            short_reasons.append("السعر أدنى من EMA 200 (اتجاه عام هابط)")

    # 2. اصطفاف المتوسطات المتوسطة (EMA 20 / EMA 50)
    if pd.notna(last["ema20"]) and pd.notna(last["ema50"]):
        if last["ema20"] > last["ema50"] and price > last["ema20"]:
            long_score += 2
            long_reasons.append("توافق EMA 20 فوق EMA 50 مع زخم سعري إيجابي")
        elif last["ema20"] < last["ema50"] and price < last["ema20"]:
            short_score += 2
            short_reasons.append("توافق EMA 20 تحت EMA 50 مع زخم سعري سلبي")

    # 3. مؤشر RSI
    if pd.notna(last["rsi"]):
        rsi_val = float(last["rsi"])
        if rsi_val < 35:
            long_score += 2
            long_reasons.append(f"RSI عند {rsi_val:.1f} (منطقة تشبع بيعي / ارتداد محتمل)")
        elif 45 <= rsi_val <= 65 and price > last["ema50"]:
            long_score += 1
            long_reasons.append(f"RSI صحي عند {rsi_val:.1f} داعم للصعود")
        elif rsi_val > 65:
            short_score += 2
            short_reasons.append(f"RSI عند {rsi_val:.1f} (منطقة تشبع شرائي / تصحيح محتمل)")
        elif 35 <= rsi_val <= 55 and price < last["ema50"]:
            short_score += 1
            short_reasons.append(f"RSI داعم للهبوط عند {rsi_val:.1f}")

    # 4. مؤشر MACD
    if pd.notna(last["macd"]) and pd.notna(last["macd_signal"]) and pd.notna(prev["macd"]) and pd.notna(prev["macd_signal"]):
        bull_cross = last["macd"] > last["macd_signal"] and prev["macd"] <= prev["macd_signal"]
        bear_cross = last["macd"] < last["macd_signal"] and prev["macd"] >= prev["macd_signal"]
        if bull_cross or (last["macd"] > last["macd_signal"] and last["macd_hist"] > prev["macd_hist"]):
            long_score += 2 if bull_cross else 1
            long_reasons.append("تقاطع/زخم MACD إيجابي")
        elif bear_cross or (last["macd"] < last["macd_signal"] and last["macd_hist"] < prev["macd_hist"]):
            short_score += 2 if bear_cross else 1
            short_reasons.append("تقاطع/زخم MACD سلبي")

    # 5. حجم التداول (Volume)
    if pd.notna(last["vol_ma"]) and last["vol_ma"] > 0 and last["volume"] > last["vol_ma"] * 1.25:
        if last["close"] >= prev["close"]:
            long_score += 1
            long_reasons.append("ارتفاع حجم التداول أعلى من المتوسط مع شمعة صاعدة")
        else:
            short_score += 1
            short_reasons.append("ارتفاع حجم التداول أعلى من المتوسط مع شمعة هابطة")

    # 6. نطاقات بولينجر (Bollinger Bands)
    if pd.notna(last["bb_dn"]) and pd.notna(last["bb_up"]):
        if price <= last["bb_dn"] * 1.002:
            long_score += 1
            long_reasons.append("ملامسة/اختراق الحد السفلي لـ Bollinger")
        elif price >= last["bb_up"] * 0.998:
            short_score += 1
            short_reasons.append("ملامسة/اختراق الحد العلوي لـ Bollinger")

    # 7. Stochastic RSI
    if pd.notna(last["stoch_rsi"]):
        srsi = float(last["stoch_rsi"])
        if srsi < 0.2:
            long_score += 1
            long_reasons.append("Stochastic RSI في منطقة تشبع بيعي")
        elif srsi > 0.8:
            short_score += 1
            short_reasons.append("Stochastic RSI في منطقة تشبع شرائي")

    max_possible = 11.0
    if long_score >= min_score and long_score > short_score:
        direction = "LONG"
        score = long_score
        reasons = long_reasons
        sl = price - atr * 1.4
        tp1 = price + atr * 1.8
        tp2 = price + atr * 3.0
        tp3 = price + atr * 4.5
    elif short_score >= min_score and short_score > long_score:
        direction = "SHORT"
        score = short_score
        reasons = short_reasons
        sl = price + atr * 1.4
        tp1 = price - atr * 1.8
        tp2 = price - atr * 3.0
        tp3 = price - atr * 4.5
    else:
        direction = "WAIT"
        score = max(long_score, short_score)
        reasons = long_reasons if long_score >= short_score else short_reasons
        return {
            "signal": "WAIT",
            "price": price,
            "score": score,
            "confidence": round(min(95.0, (score / max_possible) * 100.0), 1),
            "long_score": long_score,
            "short_score": short_score,
            "reasons": reasons,
        }

    risk = abs(price - sl)
    reward_tp2 = abs(tp2 - price)
    rr_tp2 = reward_tp2 / risk if risk > 0 else 0.0
    confidence = round(min(98.0, max(55.0, (score / max_possible) * 100.0)), 1)

    return {
        "signal": direction,
        "price": price,
        "entry": price,
        "stop_loss": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rr": rr_tp2,
        "score": score,
        "confidence": confidence,
        "long_score": long_score,
        "short_score": short_score,
        "rsi": float(last["rsi"]) if pd.notna(last["rsi"]) else 50.0,
        "reasons": reasons,
    }


def analyze_symbol_multi(raw_symbol: str, timeframe: str, min_score: int = 6) -> dict:
    clean_symbol = normalize_input_symbol(raw_symbol)
    results = {}
    dfs = {}

    for name in EXCHANGES:
        try:
            df = fetch_ohlcv_df(name, clean_symbol, timeframe)
            df_ind = add_indicators(df)
            res = evaluate_signal(df_ind, min_score=min_score)
            results[name] = res
            dfs[name] = df_ind
        except Exception as e:
            results[name] = {"error": f"[{type(e).__name__}] {e}"}

    active = [name for name, r in results.items() if "error" not in r]
    votes = {"LONG": 0, "SHORT": 0, "WAIT": 0}
    for name in active:
        votes[results[name].get("signal", "WAIT")] += 1

    if len(active) == 0:
        final = "WAIT"
        note = "تعذر الاتصال بجميع المنصات حالياً"
    elif len(active) == 1:
        if votes["LONG"] == 1:
            final = "LONG"
            note = f"إشارة من منصة واحدة متاحة ({active[0].upper()}) — يُنصح بإدارة مخاطر صارمة"
        elif votes["SHORT"] == 1:
            final = "SHORT"
            note = f"إشارة من منصة واحدة متاحة ({active[0].upper()}) — يُنصح بإدارة مخاطر صارمة"
        else:
            final = "WAIT"
            note = f"منصة واحدة متاحة ({active[0].upper()}) وحالتها انتظار"
    else:
        needed = 2
        if votes["LONG"] >= needed and votes["LONG"] > votes["SHORT"]:
            final = "LONG"
            note = f"توافق {votes['LONG']} من {len(active)} منصات"
        elif votes["SHORT"] >= needed and votes["SHORT"] > votes["LONG"]:
            final = "SHORT"
            note = f"توافق {votes['SHORT']} من {len(active)} منصات"
        else:
            final = "WAIT"
            note = "لا يوجد إجماع كافٍ بين المنصات المتاحة"

    agreeing = [r for r in results.values() if "error" not in r and r.get("signal") == final]
    if agreeing and final != "WAIT":
        levels = {
            "entry": float(np.mean([r["entry"] for r in agreeing])),
            "stop_loss": float(np.mean([r["stop_loss"] for r in agreeing])),
            "tp1": float(np.mean([r["tp1"] for r in agreeing])),
            "tp2": float(np.mean([r["tp2"] for r in agreeing])),
            "tp3": float(np.mean([r["tp3"] for r in agreeing])),
            "rr": float(np.mean([r["rr"] for r in agreeing])),
            "confidence": float(np.mean([r["confidence"] for r in agreeing])),
            "score": int(round(np.mean([r["score"] for r in agreeing]))),
        }
        reasons = agreeing[0].get("reasons", [])
    else:
        levels = None
        best = max(
            [r for r in results.values() if "error" not in r],
            key=lambda x: x.get("score", 0),
            default={},
        )
        reasons = best.get("reasons", [])

    return {
        "symbol": clean_symbol,
        "timeframe": timeframe,
        "votes": votes,
        "active_count": len(active),
        "note": note,
        "final": final,
        "levels": levels,
        "reasons": reasons,
        "details": results,
        "dfs": dfs,
    }


# ============================================================
#               مسح جميع / أفضل عملات الفيوتشر
# ============================================================
@st.cache_data(ttl=120, show_spinner=False)
def get_futures_universe(scan_all: bool = False, top_n: int = 40):
    source_used = None
    markets = {}
    tickers = {}

    for ex_name in ["okx", "bybit", "binance"]:
        try:
            ex = EXCHANGES[ex_name]
            markets = ex.load_markets()
            tickers = ex.fetch_tickers()
            source_used = ex_name
            break
        except Exception:
            continue

    if not source_used or not markets:
        return [], None

    usdt_swaps = []
    for raw_sym, m in markets.items():
        if not m.get("swap"):
            continue
        if raw_sym.endswith("/USDT:USDT"):
            clean = raw_sym.split(":")[0]
        elif raw_sym.endswith("-USDT-SWAP"):
            clean = raw_sym.replace("-USDT-SWAP", "/USDT")
        else:
            continue

        vol = tickers.get(raw_sym, {}).get("quoteVolume") or tickers.get(clean, {}).get("quoteVolume") or 0.0
        usdt_swaps.append((clean, float(vol)))

    # إزالة التكرار مع الإبقاء على أعلى حجم تداول
    best_vol = {}
    for sym, vol in usdt_swaps:
        if sym not in best_vol or vol > best_vol[sym]:
            best_vol[sym] = vol

    sorted_syms = sorted(best_vol.items(), key=lambda x: x[1], reverse=True)
    if scan_all:
        selected = [s for s, _ in sorted_syms]
    else:
        selected = [s for s, _ in sorted_syms[:top_n]]

    return selected, source_used


def scan_market_opportunities(
    timeframe: str,
    scan_all: bool = False,
    top_n: int = 40,
    min_score: int = 6,
    signal_filter: str = "الكل",
    min_confidence: float = 60.0,
):
    symbols, source_used = get_futures_universe(scan_all=scan_all, top_n=top_n)
    if not symbols:
        return [], source_used, 0

    opportunities = []
    progress = st.progress(0.0, text="جاري فحص أزواج الفيوتشر...")
    total = len(symbols)

    for idx, sym in enumerate(symbols, 1):
        try:
            r = analyze_symbol_multi(sym, timeframe, min_score=min_score)
            final = r["final"]
            if final != "WAIT" and r["levels"]:
                conf = r["levels"]["confidence"]
                passes_type = (
                    signal_filter == "الكل"
                    or (signal_filter == "LONG فقط" and final == "LONG")
                    or (signal_filter == "SHORT فقط" and final == "SHORT")
                )
                if passes_type and conf >= min_confidence:
                    opportunities.append({
                        "العملة": r["symbol"],
                        "الإشارة": final,
                        "الثقة %": conf,
                        "النقاط": r["levels"]["score"],
                        "التصويت": f"L:{r['votes']['LONG']} / S:{r['votes']['SHORT']}",
                        "الدخول": r["levels"]["entry"],
                        "وقف الخسارة": r["levels"]["stop_loss"],
                        "الهدف 1": r["levels"]["tp1"],
                        "الهدف 2": r["levels"]["tp2"],
                        "الهدف 3": r["levels"]["tp3"],
                        "R:R": round(r["levels"]["rr"], 2),
                    })
        except Exception:
            pass
        progress.progress(idx / total, text=f"فحص {idx} من {total}: {sym}")
        time.sleep(0.08)

    progress.empty()
    opportunities.sort(key=lambda x: (x["الثقة %"], x["R:R"]), reverse=True)
    return opportunities, source_used, total


# ============================================================
#                   العرض والرسوم البيانية
# ============================================================
def fmt_p(val):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "-"
    if val >= 1000:
        return f"{val:,.2f}"
    if val >= 1:
        return f"{val:.4f}"
    return f"{val:.6f}"


def render_signal_card(res: dict, leverage: int, position_size: float):
    final = res["final"]
    votes = res["votes"]

    st.markdown(f"### {res['symbol']} — فريم `{res['timeframe']}`")
    st.caption(f"تصويت: LONG={votes['LONG']} | SHORT={votes['SHORT']} | WAIT={votes['WAIT']} — {res['note']}")

    if final == "LONG":
        st.success("إشارة دخول شراء (LONG)")
    elif final == "SHORT":
        st.error("إشارة دخول بيع (SHORT)")
    else:
        st.warning("حالة انتظار (WAIT) — لم تكتمل شروط الدخول عالية الدقة بعد")

    if res["levels"]:
        L = res["levels"]
        entry = L["entry"]
        sl = L["stop_loss"]
        tp1 = L["tp1"]
        tp2 = L["tp2"]
        tp3 = L["tp3"]

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("نسبة الثقة", f"{L['confidence']:.1f}%")
        m2.metric("سعر الدخول", fmt_p(entry))
        m3.metric("وقف الخسارة (SL)", fmt_p(sl))
        m4.metric("الهدف 2 (TP2)", fmt_p(tp2))
        m5.metric("نسبة R:R", f"1:{L['rr']:.2f}")

        t1, t2, t3 = st.columns(3)
        t1.info(f"**الهدف الأول (TP1 — قريب):** `{fmt_p(tp1)}`")
        t2.info(f"**الهدف الثاني (TP2 — رئيسي):** `{fmt_p(tp2)}`")
        t3.info(f"**الهدف الثالث (TP3 — ممتد):** `{fmt_p(tp3)}`")

        if final == "LONG":
            sl_pct = (sl - entry) / entry * 100.0 * leverage
            tp1_pct = (tp1 - entry) / entry * 100.0 * leverage
            tp2_pct = (tp2 - entry) / entry * 100.0 * leverage
            tp3_pct = (tp3 - entry) / entry * 100.0 * leverage
        else:
            sl_pct = (entry - sl) / entry * 100.0 * leverage
            tp1_pct = (entry - tp1) / entry * 100.0 * leverage
            tp2_pct = (entry - tp2) / entry * 100.0 * leverage
            tp3_pct = (entry - tp3) / entry * 100.0 * leverage

        est_loss = position_size * (sl_pct / 100.0)
        est_tp2 = position_size * (tp2_pct / 100.0)

        st.write(
            f"**تقدير الصفقة (رافعة {leverage}x | مركز {position_size:.2f} USDT):** "
            f"وقف الخسارة `{sl_pct:+.2f}%` (`{est_loss:+.2f} USDT`) | "
            f"TP1 `{tp1_pct:+.2f}%` | "
            f"TP2 `{tp2_pct:+.2f}%` (`{est_tp2:+.2f} USDT`) | "
            f"TP3 `{tp3_pct:+.2f}%`"
        )

    if res["reasons"]:
        with st.expander("المؤشرات والأسباب الفنية الداعمة", expanded=(final != "WAIT")):
            for rsn in res["reasons"]:
                st.write(f"- {rsn}")

    with st.expander("حالة المنصات وتفاصيل الاتصال", expanded=False):
        for ex_name, d in res["details"].items():
            if "error" in d:
                st.error(f"**{ex_name.upper()}:** {d['error']}")
            else:
                st.write(
                    f"**{ex_name.upper()}:** `{d.get('signal')}` | "
                    f"الثقة: `{d.get('confidence', 0):.1f}%` | "
                    f"السعر: `{fmt_p(d.get('price'))}`"
                )


def render_candlestick(res: dict):
    dfs = res.get("dfs", {})
    df = dfs.get("okx") or dfs.get("bybit") or dfs.get("binance")
    if df is None or df.empty:
        st.warning("لا توجد بيانات كافية لرسم الشارت.")
        return

    sub = df.tail(140)
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=sub["timestamp"],
            open=sub["open"],
            high=sub["high"],
            low=sub["low"],
            close=sub["close"],
            name="السعر",
        )
    )
    fig.add_trace(go.Scatter(x=sub["timestamp"], y=sub["ema20"], name="EMA 20", mode="lines"))
    fig.add_trace(go.Scatter(x=sub["timestamp"], y=sub["ema50"], name="EMA 50", mode="lines"))
    fig.add_trace(go.Scatter(x=sub["timestamp"], y=sub["ema200"], name="EMA 200", mode="lines"))

    if res.get("levels"):
        L = res["levels"]
        for label, val, style in [
            ("Entry", L["entry"], "dot"),
            ("Stop Loss", L["stop_loss"], "dash"),
            ("TP1", L["tp1"], "dash"),
            ("TP2", L["tp2"], "solid"),
            ("TP3", L["tp3"], "dot"),
        ]:
            fig.add_hline(y=val, line_dash=style, annotation_text=f"{label}: {fmt_p(val)}")

    fig.update_layout(
        title=f"{res['symbol']} — فريم {res['timeframe']}",
        xaxis_rangeslider_visible=False,
        height=500,
    )
    st.plotly_chart(fig, use_container_width=True)


# ============================================================
#                   الواجهة الرئيسية
# ============================================================
st.title("Futures Signal Scanner Pro v3.0")
st.caption("تحليل عقود الفيوتشر متعددة الفريمات • بحث شامل في العملات • إشارات دخول ووقف وأهداف")

with st.sidebar:
    st.header("إعدادات التحليل")
    mode = st.radio(
        "اختر الوضع",
        ["تحليل عملة محددة", "بحث في كل العملات", "رسم بياني + مستويات"],
        index=0,
    )
    timeframe = st.selectbox("اختر الفريم", TIMEFRAMES, index=3)  # الافتراضي 1h
    min_score = st.slider("حد الدقة / النقاط المطلوبة للإشارة", min_value=4, max_value=9, value=6)
    min_confidence = st.slider("الحد الأدنى لنسبة الثقة %", min_value=50, max_value=90, value=65, step=5)

    st.divider()
    st.subheader("إدارة المخاطر (للحساب التقديري)")
    leverage = st.slider("الرافعة المالية (Leverage)", min_value=1, max_value=125, value=20)
    position_size = st.number_input("حجم المركز (USDT)", min_value=10.0, value=100.0, step=10.0)

    if mode in ("تحليل عملة محددة", "رسم بياني + مستويات"):
        symbol_input = st.text_input("اسم العملة (أي عملة مثلاً BTC, ETH, SOL, XRP, DOGE)", value="BTC/USDT")
    else:
        symbol_input = "BTC/USDT"

    if mode == "بحث في كل العملات":
        scan_all = st.checkbox("فحص كل العملات المتاحة في السوق (قد يستغرق وقتاً أطول)", value=False)
        top_n = st.slider("عدد العملات الأعلى سيولة عند عدم فحص الكل", min_value=20, max_value=150, value=50, step=10)
        signal_filter = st.selectbox("تصفية الإشارات", ["الكل", "LONG فقط", "SHORT فقط"], index=0)
    else:
        scan_all = False
        top_n = 50
        signal_filter = "الكل"

run_clicked = st.button("تشغيل التحليل / البحث الآن", type="primary", use_container_width=True)

if mode in ("تحليل عملة محددة", "رسم بياني + مستويات"):
    key_sig = f"{symbol_input}|{timeframe}|{min_score}"
    if run_clicked or st.session_state.get("single_key") != key_sig:
        with st.spinner(f"جاري تحليل {normalize_input_symbol(symbol_input)} على فريم {timeframe}..."):
            st.session_state["single_result"] = analyze_symbol_multi(
                symbol_input, timeframe, min_score=min_score
            )
            st.session_state["single_key"] = key_sig

    res = st.session_state.get("single_result")
    if res:
        render_signal_card(res, leverage, position_size)
        if mode == "رسم بياني + مستويات":
            render_candlestick(res)

elif mode == "بحث في كل العملات":
    if run_clicked:
        opps, src, scanned_count = scan_market_opportunities(
            timeframe=timeframe,
            scan_all=scan_all,
            top_n=top_n,
            min_score=min_score,
            signal_filter=signal_filter,
            min_confidence=float(min_confidence),
        )
        st.session_state["scan_pack"] = (opps, src, scanned_count, timeframe)

    if "scan_pack" in st.session_state:
        opps, src, scanned_count, tf_used = st.session_state["scan_pack"]
        st.caption(
            f"المصدر: `{(src or 'غير متاح').upper()}` | "
            f"الفريم: `{tf_used}` | "
            f"العملات المفحوصة: `{scanned_count}` | "
            f"الفرص المطابقة: `{len(opps)}`"
        )
        if not opps:
            st.info("لم يتم العثور على فرص تحقق شروط الدقة والثقة الحالية على هذا الفريم. جرّب فريم آخر أو خفّض نسبة الثقة قليلاً.")
        else:
            df_opps = pd.DataFrame(opps)
            for col in ["الدخول", "وقف الخسارة", "الهدف 1", "الهدف 2", "الهدف 3"]:
                df_opps[col] = df_opps[col].apply(fmt_p)
            st.dataframe(df_opps, use_container_width=True, hide_index=True)

            selected_coin = st.selectbox(
                "اختر عملة من النتائج لعرض تفاصيلها الكاملة والشارت:",
                options=[row["العملة"] for row in opps],
            )
            if selected_coin and st.button("عرض تفاصيل العملة المختارة"):
                detail_res = analyze_symbol_multi(selected_coin, tf_used, min_score=min_score)
                render_signal_card(detail_res, leverage, position_size)
                render_candlestick(detail_res)
