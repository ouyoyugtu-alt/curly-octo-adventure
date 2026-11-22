import time
import ccxt
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
    page_title="Futures Strict Signal Engine + HTF",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

TIMEFRAMES = ["5m", "15m", "30m", "1h", "2h", "4h", "1d"]

HTF_MAP = {
    "5m": "1h",
    "15m": "1h",
    "30m": "4h",
    "1h": "4h",
    "2h": "4h",
    "4h": "1d",
    "1d": "1d",
}


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


def normalize_symbol(raw_symbol: str) -> str:
    s = (raw_symbol or "BTC/USDT").strip().upper()
    s = s.replace("-SWAP", "").replace(":USDT", "").replace("-", "/")
    if "/" not in s:
        s = f"{s}/USDT"
    base, quote = s.split("/")[:2]
    return f"{base.strip()}/{(quote or 'USDT').strip()}"


def ex_symbol(clean_sym: str, ex_name: str) -> str:
    base, quote = clean_sym.split("/")
    if ex_name == "binance":
        return f"{base}/{quote}"
    if ex_name == "bybit":
        return f"{base}/{quote}:{quote}"
    if ex_name == "okx":
        return f"{base}-{quote}-SWAP"
    return clean_sym


def fetch_ohlcv(ex_name: str, clean_sym: str, timeframe: str, limit: int = 400) -> pd.DataFrame:
    ex = EXCHANGES[ex_name]
    ohlcv = ex.fetch_ohlcv(ex_symbol(clean_sym, ex_name), timeframe, limit=limit)
    if not ohlcv or len(ohlcv) < 220:
        raise ValueError(f"بيانات غير كافية من {ex_name}")
    df = pd.DataFrame(ohlcv, columns=["time", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["time"], unit="ms")
    return df


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    c = d["close"].astype(float)
    h = d["high"].astype(float)
    l = d["low"].astype(float)
    v = d["volume"].astype(float)

    d["ema20"] = c.ewm(span=20, adjust=False).mean()
    d["ema50"] = c.ewm(span=50, adjust=False).mean()
    d["ema200"] = c.ewm(span=200, adjust=False).mean()

    delta = c.diff()
    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / loss.replace(0.0, np.nan)
    d["rsi"] = 100.0 - (100.0 / (1.0 + rs))

    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    d["macd"] = ema12 - ema26
    d["macd_sig"] = d["macd"].ewm(span=9, adjust=False).mean()
    d["macd_hist"] = d["macd"] - d["macd_sig"]

    prev_c = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    d["atr"] = tr.rolling(14).mean()

    d["bb_mid"] = c.rolling(20).mean()
    d["bb_std"] = c.rolling(20).std()
    d["bb_up"] = d["bb_mid"] + 2.0 * d["bb_std"]
    d["bb_dn"] = d["bb_mid"] - 2.0 * d["bb_std"]

    d["vol_ma"] = v.rolling(20).mean()

    rsi_min = d["rsi"].rolling(14).min()
    rsi_max = d["rsi"].rolling(14).max()
    d["stoch_rsi"] = (d["rsi"] - rsi_min) / (rsi_max - rsi_min).replace(0.0, np.nan)

    return d


def detect_htf_bias(clean_sym: str, htf: str) -> dict:
    """يحدد اتجاه الفريم الأعلى (صاعد / هابط / محايد) من أول منصة متاحة"""
    for ex_name in ["okx", "bybit", "binance"]:
        try:
            df = compute_indicators(fetch_ohlcv(ex_name, clean_sym, htf, limit=300))
            last = df.iloc[-1]
            price = float(last["close"])
            ema50 = float(last["ema50"]) if pd.notna(last["ema50"]) else price
            ema200 = float(last["ema200"]) if pd.notna(last["ema200"]) else price
            rsi = float(last["rsi"]) if pd.notna(last["rsi"]) else 50.0

            if price > ema200 and ema50 >= ema200 and rsi >= 45:
                bias = "LONG"
                desc = f"صاعد على {htf} (فوق EMA200 و EMA50، RSI={rsi:.1f})"
            elif price < ema200 and ema50 <= ema200 and rsi <= 55:
                bias = "SHORT"
                desc = f"هابط على {htf} (تحت EMA200 و EMA50، RSI={rsi:.1f})"
            else:
                bias = "NEUTRAL"
                desc = f"متذبذب/محايد على {htf} (RSI={rsi:.1f})"

            return {"htf": htf, "bias": bias, "source": ex_name.upper(), "desc": desc}
        except Exception:
            continue

    return {"htf": htf, "bias": "UNKNOWN", "source": "NONE", "desc": f"تعذر جلب بيانات الفريم الأعلى {htf}"}


def strict_signal_engine(df: pd.DataFrame, min_score: int = 7) -> dict:
    last = df.iloc[-1]
    prev = df.iloc[-2]

    price = float(last["close"])
    atr = float(last["atr"]) if pd.notna(last["atr"]) and last["atr"] > 0 else price * 0.01

    long_pts = 0
    short_pts = 0
    long_checks = []
    short_checks = []

    ema200_up = pd.notna(last["ema200"]) and price > last["ema200"]
    ema200_dn = pd.notna(last["ema200"]) and price < last["ema200"]

    if ema200_up:
        long_pts += 2
        long_checks.append("فوق EMA 200 (اتجاه عام صاعد)")
    elif ema200_dn:
        short_pts += 2
        short_checks.append("تحت EMA 200 (اتجاه عام هابط)")

    if pd.notna(last["ema20"]) and pd.notna(last["ema50"]):
        if last["ema20"] > last["ema50"] and price > last["ema20"]:
            long_pts += 2
            long_checks.append("السعر أعلى من EMA 20 و EMA 50 بترتيب صاعد")
        elif last["ema20"] < last["ema50"] and price < last["ema20"]:
            short_pts += 2
            short_checks.append("السعر أدنى من EMA 20 و EMA 50 بترتيب هابط")

    if pd.notna(last["rsi"]):
        rsi = float(last["rsi"])
        if 48 <= rsi <= 68 and ema200_up:
            long_pts += 2
            long_checks.append(f"RSI عند {rsi:.1f} (زخم صعود صحي)")
        elif rsi < 32:
            long_pts += 2
            long_checks.append(f"RSI عند {rsi:.1f} (تشبع بيعي قوي)")
        elif 32 <= rsi <= 52 and ema200_dn:
            short_pts += 2
            short_checks.append(f"RSI عند {rsi:.1f} (زخم هبوط صحي)")
        elif rsi > 68:
            short_pts += 2
            short_checks.append(f"RSI عند {rsi:.1f} (تشبع شرائي قوي)")

    if pd.notna(last["macd"]) and pd.notna(last["macd_sig"]) and pd.notna(prev["macd_hist"]):
        bull_cross = last["macd"] > last["macd_sig"] and prev["macd"] <= prev["macd_sig"]
        bear_cross = last["macd"] < last["macd_sig"] and prev["macd"] >= prev["macd_sig"]
        if bull_cross:
            long_pts += 2
            long_checks.append("تقاطع MACD صاعد جديد")
        elif last["macd"] > last["macd_sig"] and last["macd_hist"] > 0 and last["macd_hist"] > prev["macd_hist"]:
            long_pts += 1
            long_checks.append("زخم MACD إيجابي متزايد")

        if bear_cross:
            short_pts += 2
            short_checks.append("تقاطع MACD هابط جديد")
        elif last["macd"] < last["macd_sig"] and last["macd_hist"] < 0 and last["macd_hist"] < prev["macd_hist"]:
            short_pts += 1
            short_checks.append("زخم MACD سلبي متزايد")

    if pd.notna(last["vol_ma"]) and last["vol_ma"] > 0:
        vol_ratio = float(last["volume"] / last["vol_ma"])
        if vol_ratio >= 1.35 and last["close"] > prev["close"]:
            long_pts += 2
            long_checks.append(f"حجم تداول قوي ({vol_ratio:.2f}x من المتوسط) مع شمعة صاعدة")
        elif vol_ratio >= 1.35 and last["close"] < prev["close"]:
            short_pts += 2
            short_checks.append(f"حجم تداول قوي ({vol_ratio:.2f}x من المتوسط) مع شمعة هابطة")

    if pd.notna(last["bb_dn"]) and pd.notna(last["bb_up"]):
        if price <= last["bb_dn"] * 1.002:
            long_pts += 1
            long_checks.append("قرب الحد السفلي لـ Bollinger")
        elif price >= last["bb_up"] * 0.998:
            short_pts += 1
            short_checks.append("قرب الحد العلوي لـ Bollinger")

    if pd.notna(last["stoch_rsi"]):
        srsi = float(last["stoch_rsi"])
        if srsi < 0.2:
            long_pts += 1
            long_checks.append("Stochastic RSI في منطقة تشبع بيعي")
        elif srsi > 0.8:
            short_pts += 1
            short_checks.append("Stochastic RSI في منطقة تشبع شرائي")

    max_pts = 12.0
    if long_pts >= min_score and (long_pts - short_pts) >= 3:
        direction = "LONG"
        pts = long_pts
        checks = long_checks
        sl = price - atr * 1.5
        tp1 = price + atr * 1.8
        tp2 = price + atr * 3.0
        tp3 = price + atr * 4.5
    elif short_pts >= min_score and (short_pts - long_pts) >= 3:
        direction = "SHORT"
        pts = short_pts
        checks = short_checks
        sl = price + atr * 1.5
        tp1 = price - atr * 1.8
        tp2 = price - atr * 3.0
        tp3 = price - atr * 4.5
    else:
        best_pts = max(long_pts, short_pts)
        best_checks = long_checks if long_pts >= short_pts else short_checks
        return {
            "signal": "WAIT",
            "price": price,
            "score": best_pts,
            "long_pts": long_pts,
            "short_pts": short_pts,
            "confidence": round(min(92.0, (best_pts / max_pts) * 100.0), 1),
            "checks": best_checks,
        }

    risk = abs(price - sl)
    rr_tp2 = abs(tp2 - price) / risk if risk > 0 else 0.0
    confidence = round(min(97.0, max(65.0, (pts / max_pts) * 100.0)), 1)

    return {
        "signal": direction,
        "price": price,
        "entry": price,
        "stop_loss": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rr": rr_tp2,
        "score": pts,
        "long_pts": long_pts,
        "short_pts": short_pts,
        "confidence": confidence,
        "checks": checks,
    }


def analyze_strict_multi(
    raw_symbol: str,
    timeframe: str,
    min_score: int = 7,
    htf_mode: str = "إلزامي (توافق كامل)",
    custom_htf: str | None = None,
) -> dict:
    clean = normalize_symbol(raw_symbol)
    htf = custom_htf or HTF_MAP.get(timeframe, "4h")
    htf_info = detect_htf_bias(clean, htf) if htf_mode != "معطّل" else {
        "htf": htf,
        "bias": "DISABLED",
        "source": "-",
        "desc": "تم تعطيل فحص الفريم الأعلى",
    }

    details = {}
    dfs = {}

    for name in EXCHANGES:
        try:
            df = compute_indicators(fetch_ohlcv(name, clean, timeframe))
            details[name] = strict_signal_engine(df, min_score=min_score)
            dfs[name] = df
        except Exception as e:
            details[name] = {"error": f"[{type(e).__name__}] {e}"}

    active = [k for k, v in details.items() if "error" not in v]
    votes = {"LONG": 0, "SHORT": 0, "WAIT": 0}
    for k in active:
        votes[details[k].get("signal", "WAIT")] += 1

    if len(active) == 0:
        final = "WAIT"
        status = "تعذر الاتصال بالمنصات حالياً"
    elif len(active) == 1:
        if votes["LONG"] == 1:
            final = "LONG"
            status = f"إشارة صعود من منصة {active[0].upper()} (المنصات الأخرى غير متاحة)"
        elif votes["SHORT"] == 1:
            final = "SHORT"
            status = f"إشارة هبوط من منصة {active[0].upper()} (المنصات الأخرى غير متاحة)"
        else:
            final = "WAIT"
            status = f"منصة {active[0].upper()} متاحة وحالتها انتظار"
    else:
        if votes["LONG"] >= 2 and votes["LONG"] > votes["SHORT"]:
            final = "LONG"
            status = f"توافق {votes['LONG']} من {len(active)} منصات على الصعود"
        elif votes["SHORT"] >= 2 and votes["SHORT"] > votes["LONG"]:
            final = "SHORT"
            status = f"توافق {votes['SHORT']} من {len(active)} منصات على الهبوط"
        else:
            final = "WAIT"
            status = "لا يوجد توافق كافٍ بين المنصات — الانتظار أفضل"

    htf_bias = htf_info["bias"]
    htf_aligned = (final in ("LONG", "SHORT") and htf_bias == final)

    if final in ("LONG", "SHORT") and htf_mode != "معطّل":
        if htf_bias not in ("UNKNOWN", "DISABLED"):
            if htf_mode == "إلزامي (توافق كامل)" and htf_bias != final:
                final = "WAIT"
                status = f"تم تحويلها إلى انتظار لأن الفريم الأعلى ({htf}) اتجاهه {htf_bias}"
            elif htf_mode == "تعزيز الدقة (إضافة نقاط)":
                if htf_aligned:
                    status = f"{status} | مؤكد على الفريم الأعلى ({htf})"
                elif htf_bias != "NEUTRAL":
                    status = f"{status} | تنبيه: الفريم الأعلى ({htf}) يعاكس الاتجاه ({htf_bias})"

    agreeing = [v for v in details.values() if "error" not in v and v.get("signal") == final]
    if agreeing and final != "WAIT":
        conf_vals = []
        for r in agreeing:
            c_val = r["confidence"]
            if htf_mode == "تعزيز الدقة (إضافة نقاط)":
                if htf_aligned:
                    c_val = min(98.0, c_val + 6.0)
                elif htf_bias not in ("NEUTRAL", "UNKNOWN", "DISABLED"):
                    c_val = max(55.0, c_val - 8.0)
            conf_vals.append(c_val)

        levels = {
            "entry": float(np.mean([x["entry"] for x in agreeing])),
            "stop_loss": float(np.mean([x["stop_loss"] for x in agreeing])),
            "tp1": float(np.mean([x["tp1"] for x in agreeing])),
            "tp2": float(np.mean([x["tp2"] for x in agreeing])),
            "tp3": float(np.mean([x["tp3"] for x in agreeing])),
            "rr": float(np.mean([x["rr"] for x in agreeing])),
            "confidence": float(np.mean(conf_vals)),
            "score": float(np.mean([x["score"] for x in agreeing])),
        }
        checks = list(agreeing[0].get("checks", []))
        if htf_aligned:
            checks.insert(0, f"تأكيد الفريم الأعلى ({htf}): {htf_info['desc']}")
    else:
        levels = None
        best = max([v for v in details.values() if "error" not in v], key=lambda x: x.get("score", 0), default={})
        checks = list(best.get("checks", []))

    return {
        "symbol": clean,
        "timeframe": timeframe,
        "htf_info": htf_info,
        "htf_aligned": htf_aligned,
        "final": final,
        "status": status,
        "votes": votes,
        "levels": levels,
        "checks": checks,
        "details": details,
        "dfs": dfs,
    }


@st.cache_data(ttl=120, show_spinner=False)
def list_futures_symbols(scan_all: bool = False, top_n: int = 50):
    source = None
    markets = {}
    tickers = {}

    for ex_name in ["okx", "bybit", "binance"]:
        try:
            ex = EXCHANGES[ex_name]
            markets = ex.load_markets()
            tickers = ex.fetch_tickers()
            source = ex_name
            break
        except Exception:
            continue

    if not source or not markets:
        return [], None

    vol_map = {}
    for raw_s, m in markets.items():
        if not m.get("swap"):
            continue
        if raw_s.endswith("/USDT:USDT"):
            clean = raw_s.split(":")[0]
        elif raw_s.endswith("-USDT-SWAP"):
            clean = raw_s.replace("-USDT-SWAP", "/USDT")
        else:
            continue
        vol = tickers.get(raw_s, {}).get("quoteVolume") or tickers.get(clean, {}).get("quoteVolume") or 0.0
        if clean not in vol_map or float(vol) > vol_map[clean]:
            vol_map[clean] = float(vol)

    ordered = [s for s, _ in sorted(vol_map.items(), key=lambda x: x[1], reverse=True)]
    return (ordered if scan_all else ordered[:top_n]), source


def scan_strict_opportunities(
    timeframe: str,
    scan_all: bool,
    top_n: int,
    min_score: int,
    min_confidence: float,
    direction_filter: str,
    htf_mode: str,
    custom_htf: str | None,
):
    syms, source = list_futures_symbols(scan_all=scan_all, top_n=top_n)
    if not syms:
        return [], source, 0

    found = []
    prog = st.progress(0.0, text="جاري فحص العملات مع تأكيد الفريم الأعلى...")
    total = len(syms)

    for i, sym in enumerate(syms, 1):
        try:
            r = analyze_strict_multi(
                sym,
                timeframe,
                min_score=min_score,
                htf_mode=htf_mode,
                custom_htf=custom_htf,
            )
            sig = r["final"]
            if sig != "WAIT" and r["levels"]:
                conf = r["levels"]["confidence"]
                ok_dir = (
                    direction_filter == "الكل"
                    or (direction_filter == "صعود (LONG)" and sig == "LONG")
                    or (direction_filter == "هبوط (SHORT)" and sig == "SHORT")
                )
                if ok_dir and conf >= min_confidence:
                    found.append({
                        "العملة": r["symbol"],
                        "الاتجاه": "صعود (LONG)" if sig == "LONG" else "هبوط (SHORT)",
                        "الدقة %": round(conf, 1),
                        "الفريم الأعلى": f"{r['htf_info']['htf']} ({r['htf_info']['bias']})",
                        "الدخول": r["levels"]["entry"],
                        "وقف الخسارة (SL)": r["levels"]["stop_loss"],
                        "الهدف 1 (TP1)": r["levels"]["tp1"],
                        "الهدف 2 (TP2)": r["levels"]["tp2"],
                        "الهدف 3 (TP3)": r["levels"]["tp3"],
                        "R:R": round(r["levels"]["rr"], 2),
                    })
        except Exception:
            pass
        prog.progress(i / total, text=f"فحص {i} / {total}: {sym}")
        time.sleep(0.08)

    prog.empty()
    found.sort(key=lambda x: (x["الدقة %"], x["R:R"]), reverse=True)
    return found, source, total


def fmt_num(val):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "-"
    if val >= 1000:
        return f"{val:,.2f}"
    if val >= 1:
        return f"{val:.4f}"
    return f"{val:.6f}"


def build_copy_summary(res: dict, leverage: int) -> str:
    """ينشئ نصاً جاهزاً للنسخ الفوري للصفقات المؤكدة"""
    L = res["levels"]
    sig = res["final"]
    htf = res["htf_info"]
    side_ar = "صعود (LONG)" if sig == "LONG" else "هبوط (SHORT)"
    return (
        f"العملة: {res['symbol']} | الاتجاه: {side_ar}\n"
        f"الفريم: {res['timeframe']} | الفريم الأعلى: {htf['htf']} ({htf['bias']})\n"
        f"نسبة الدقة: {L['confidence']:.1f}% | الرافعة المقترحة: {leverage}x\n"
        f"الدخول (Entry): {fmt_num(L['entry'])}\n"
        f"وقف الخسارة (SL): {fmt_num(L['stop_loss'])}\n"
        f"الهدف 1 (TP1): {fmt_num(L['tp1'])}\n"
        f"الهدف 2 (TP2): {fmt_num(L['tp2'])}\n"
        f"الهدف 3 (TP3): {fmt_num(L['tp3'])}\n"
        f"نسبة R:R: 1:{L['rr']:.2f}"
    )


def show_signal_view(res: dict, leverage: int, size_usdt: float):
    sig = res["final"]
    htf = res["htf_info"]

    st.subheader(f"{res['symbol']} — فريم `{res['timeframe']}` (تأكيد الفريم الأعلى: `{htf['htf']}`)")
    st.caption(f"{res['status']} | {htf['desc']}")

    if sig == "LONG":
        st.success("الترجيح الفني: صعود (LONG) — تحققت شروط الدخول وتأكيد الفريم")
    elif sig == "SHORT":
        st.error("الترجيح الفني: هبوط (SHORT) — تحققت شروط الدخول وتأكيد الفريم")
    else:
        st.warning("الترجيح الفني: انتظار (WAIT) — لا توجد إشارة دخول مؤكدة حالياً")

    if res["levels"] and sig in ("LONG", "SHORT"):
        L = res["levels"]
        entry, sl, tp1, tp2, tp3 = L["entry"], L["stop_loss"], L["tp1"], L["tp2"], L["tp3"]

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("نسبة الدقة", f"{L['confidence']:.1f}%")
        c2.metric("نقطة الدخول", fmt_num(entry))
        c3.metric("وقف الخسارة (SL)", fmt_num(sl))
        c4.metric("الهدف الرئيسي (TP2)", fmt_num(tp2))
        c5.metric("R:R", f"1:{L['rr']:.2f}")

        g1, g2, g3 = st.columns(3)
        g1.info(f"**خروج جزئي / تأمين (TP1):** `{fmt_num(tp1)}`")
        g2.success(f"**هدف رئيسي (TP2):** `{fmt_num(tp2)}`")
        g3.info(f"**هدف ممتد (TP3):** `{fmt_num(tp3)}`")

        if sig == "LONG":
            sl_pct = (sl - entry) / entry * 100.0 * leverage
            tp1_pct = (tp1 - entry) / entry * 100.0 * leverage
            tp2_pct = (tp2 - entry) / entry * 100.0 * leverage
            tp3_pct = (tp3 - entry) / entry * 100.0 * leverage
        else:
            sl_pct = (entry - sl) / entry * 100.0 * leverage
            tp1_pct = (entry - tp1) / entry * 100.0 * leverage
            tp2_pct = (entry - tp2) / entry * 100.0 * leverage
            tp3_pct = (entry - tp3) / entry * 100.0 * leverage

        st.write(
            f"**حساب الصفقة (رافعة {leverage}x | مبلغ {size_usdt:.2f} USDT):** "
            f"خسارة الوقف `{sl_pct:+.2f}%` (`{size_usdt * sl_pct / 100:+.2f} USDT`) | "
            f"TP1 `{tp1_pct:+.2f}%` | "
            f"TP2 `{tp2_pct:+.2f}%` (`{size_usdt * tp2_pct / 100:+.2f} USDT`) | "
            f"TP3 `{tp3_pct:+.2f}%`"
        )

        st.markdown("**ملخص الصفقة جاهز للنسخ:**")
        st.code(build_copy_summary(res, leverage), language="text")

    if res["checks"]:
        with st.expander("شروط التحليل الفني وتأكيد الفريم الأعلى", expanded=(sig != "WAIT")):
            for item in res["checks"]:
                st.write(f"- {item}")

    with st.expander("تفاصيل المنصات", expanded=False):
        for name, d in res["details"].items():
            if "error" in d:
                st.error(f"**{name.upper()}:** {d['error']}")
            else:
                st.write(f"**{name.upper()}:** `{d.get('signal')}` | الدقة: `{d.get('confidence', 0):.1f}%` | السعر: `{fmt_num(d.get('price'))}`")


def show_chart_view(res: dict):
    dfs = res.get("dfs", {})
    df = dfs.get("okx") or dfs.get("bybit") or dfs.get("binance")
    if df is None or df.empty:
        st.warning("لا توجد بيانات متاحة للرسم البياني.")
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
        for lbl, val, dash in [
            ("Entry", L["entry"], "dot"),
            ("SL", L["stop_loss"], "dash"),
            ("TP1", L["tp1"], "dash"),
            ("TP2", L["tp2"], "solid"),
            ("TP3", L["tp3"], "dot"),
        ]:
            fig.add_hline(y=val, line_dash=dash, annotation_text=f"{lbl}: {fmt_num(val)}")

    fig.update_layout(title=f"{res['symbol']} ({res['timeframe']})", xaxis_rangeslider_visible=False, height=480)
    st.plotly_chart(fig, use_container_width=True)


st.title("محرك إشارات الفيوتشر عالي الدقة 🎯")
st.caption("تحديد الصعود والهبوط ونقاط الدخول والخروج ووقف الخسارة مع تأكيد الفريم الأعلى")

with st.sidebar:
    st.header("الإعدادات")
    mode = st.radio("الوضع", ["تحليل عملة", "بحث في كل العملات", "رسم بياني"], index=0)
    timeframe = st.selectbox("الفريم الأساسي", TIMEFRAMES, index=3)

    htf_mode = st.selectbox(
        "شرط تأكيد الفريم الأعلى",
        ["إلزامي (توافق كامل)", "تعزيز الدقة (إضافة نقاط)", "معطّل"],
        index=0,
    )
    auto_htf = HTF_MAP.get(timeframe, "4h")
    use_custom_htf = st.checkbox(f"تحديد فريم أعلى يدوياً (الافتراضي: {auto_htf})", value=False)
    custom_htf = st.selectbox("اختر الفريم الأعلى", TIMEFRAMES, index=5) if use_custom_htf else None

    min_score = st.slider("صرامة الإشارة (النقاط المطلوبة)", min_value=5, max_value=10, value=7)
    min_confidence = st.slider("الحد الأدنى للدقة %", min_value=55, max_value=95, value=70, step=5)

    st.divider()
    leverage = st.slider("الرافعة المالية", min_value=1, max_value=125, value=20)
    size_usdt = st.number_input("مبلغ الصفقة (USDT)", min_value=10.0, value=100.0, step=10.0)

    if mode in ("تحليل عملة", "رسم بياني"):
        symbol_in = st.text_input("العملة (أي عملة مثلاً BTC, ETH, SOL, SUI)", value="BTC/USDT")
    else:
        symbol_in = "BTC/USDT"

    if mode == "بحث في كل العملات":
        scan_all = st.checkbox("فحص كل العملات المتاحة", value=False)
        top_n = st.slider("عدد العملات الأعلى سيولة", min_value=20, max_value=200, value=60, step=10)
        direction_filter = st.selectbox("نوع الإشارة المطلوبة", ["الكل", "صعود (LONG)", "هبوط (SHORT)"], index=0)
    else:
        scan_all = False
        top_n = 60
        direction_filter = "الكل"

go_btn = st.button("تنفيذ التحليل الآن", type="primary", use_container_width=True)

if mode in ("تحليل عملة", "رسم بياني"):
    sig_key = f"{symbol_in}|{timeframe}|{min_score}|{htf_mode}|{custom_htf}"
    if go_btn or st.session_state.get("last_key") != sig_key:
        with st.spinner("جاري تحليل العملة ومطابقة الفريم الأعلى..."):
            st.session_state["last_res"] = analyze_strict_multi(
                symbol_in,
                timeframe,
                min_score=min_score,
                htf_mode=htf_mode,
                custom_htf=custom_htf,
            )
            st.session_state["last_key"] = sig_key

    res = st.session_state.get("last_res")
    if res:
        show_signal_view(res, leverage, size_usdt)
        if mode == "رسم بياني":
            show_chart_view(res)

elif mode == "بحث في كل العملات":
    if go_btn:
        rows, src, cnt = scan_strict_opportunities(
            timeframe=timeframe,
            scan_all=scan_all,
            top_n=top_n,
            min_score=min_score,
            min_confidence=float(min_confidence),
            direction_filter=direction_filter,
            htf_mode=htf_mode,
            custom_htf=custom_htf,
        )
        st.session_state["scan_data"] = (rows, src, cnt, timeframe)

    if "scan_data" in st.session_state:
        rows, src, cnt, tf_used = st.session_state["scan_data"]
        st.caption(f"المصدر: `{(src or 'غير متاح').upper()}` | الفريم: `{tf_used}` | تم فحص: `{cnt}` عملة | الفرص المؤكدة: `{len(rows)}`")
        if not rows:
            st.info("لا توجد فرص مؤكدة مع الفريم الأعلى حالياً. جرّب فريم آخر أو اجعل التأكيد (تعزيز الدقة) بدلاً من إلزامي.")
        else:
            df_tbl = pd.DataFrame(rows)
            for col in ["الدخول", "وقف الخسارة (SL)", "الهدف 1 (TP1)", "الهدف 2 (TP2)", "الهدف 3 (TP3)"]:
                df_tbl[col] = df_tbl[col].apply(fmt_num)
            st.dataframe(df_tbl, use_container_width=True, hide_index=True)

            pick = st.selectbox("اختر عملة من الجدول لعرض تفاصيل الدخول والخروج والشارت:", [r["العملة"] for r in rows])
            if pick and st.button("عرض تفاصيل العملة"):
                one_res = analyze_strict_multi(
                    pick,
                    tf_used,
                    min_score=min_score,
                    htf_mode=htf_mode,
                    custom_htf=custom_htf,
                )
                show_signal_view(one_res, leverage, size_usdt)
                show_chart_view(one_res)
