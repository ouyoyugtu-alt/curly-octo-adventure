import ccxt
import pandas as pd
import numpy as np
from colorama import Fore, Style, init
import time

init(autoreset=True)

# ============================================================
#                    إعداد المنصات
# ============================================================
EXCHANGES = {
    'binance': ccxt.binance({'options': {'defaultType': 'future'}, 'enableRateLimit': True}),
    'bybit':   ccxt.bybit({'options': {'defaultType': 'swap'}, 'enableRateLimit': True}),
    'okx':     ccxt.okx({'options': {'defaultType': 'swap'}, 'enableRateLimit': True}),
}

def get_symbol_candidates(symbol):
    """يرجع الصيغ الممكنة للرمز حسب المنصة"""
    base, quote = symbol.replace('-', '/').replace('SWAP', '').split('/')
    return {
        'binance': f"{base}/{quote}",
        'bybit':   f"{base}/{quote}:{quote}",
        'okx':     f"{base}-{quote}-SWAP",
    }

# ============================================================
#                   جلب البيانات
# ============================================================
def fetch_data(exchange_name, symbol, timeframe, limit=500):
    ex = EXCHANGES[exchange_name]
    candidates = get_symbol_candidates(symbol)
    sym = candidates[exchange_name]
    ohlcv = ex.fetch_ohlcv(sym, timeframe, limit=limit)
    if not ohlcv or len(ohlcv) < 200:
        raise ValueError(f"بيانات غير كافية من {exchange_name} لـ {symbol}")
    df = pd.DataFrame(ohlcv, columns=['time','open','high','low','close','volume'])
    return df

# ============================================================
#                   المؤشرات
# ============================================================
def calculate_indicators(df):
    df['ema20']  = df['close'].ewm(span=20).mean()
    df['ema50']  = df['close'].ewm(span=50).mean()
    df['ema200'] = df['close'].ewm(span=200).mean()

    # RSI
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df['rsi'] = 100 - (100 / (1 + rs))

    # MACD
    exp1 = df['close'].ewm(span=12).mean()
    exp2 = df['close'].ewm(span=26).mean()
    df['macd']   = exp1 - exp2
    df['signal'] = df['macd'].ewm(span=9).mean()

    # ATR
    df['tr'] = np.maximum(
        df['high'] - df['low'],
        np.maximum(abs(df['high'] - df['close'].shift()),
                   abs(df['low']  - df['close'].shift()))
    )
    df['atr'] = df['tr'].rolling(14).mean()

    # Bollinger
    df['bb_mid'] = df['close'].rolling(20).mean()
    df['bb_std'] = df['close'].rolling(20).std()
    df['bb_up']  = df['bb_mid'] + 2 * df['bb_std']
    df['bb_dn']  = df['bb_mid'] - 2 * df['bb_std']

    # Volume
    df['vol_ma'] = df['volume'].rolling(20).mean()

    # Stochastic RSI
    rsi_min = df['rsi'].rolling(14).min()
    rsi_max = df['rsi'].rolling(14).max()
    df['stoch_rsi'] = (df['rsi'] - rsi_min) / (rsi_max - rsi_min).replace(0, np.nan)

    return df

# ============================================================
#                   محرك الإشارات
# ============================================================
def signal_engine(df):
    last = df.iloc[-1]
    prev = df.iloc[-2]
    long_score  = 0
    short_score = 0
    reasons = []

    # 1) الاتجاه العام (EMA200)
    if last['close'] > last['ema200']:
        long_score += 2
        reasons.append("📈 فوق EMA200 (اتجاه صاعد)")
    else:
        short_score += 2
        reasons.append("📉 تحت EMA200 (اتجاه هابط)")

    # 2) تقاطع EMA20/50
    if last['ema20'] > last['ema50']:
        long_score += 1
    else:
        short_score += 1

    # 3) RSI
    if last['rsi'] < 35:
        long_score += 2
        reasons.append(f"🟢 RSI={last['rsi']:.1f} (تشبع بيعي)")
    elif last['rsi'] > 65:
        short_score += 2
        reasons.append(f"🔴 RSI={last['rsi']:.1f} (تشبع شرائي)")

    # 4) MACD
    if last['macd'] > last['signal'] and prev['macd'] <= prev['signal']:
        long_score += 2
        reasons.append("✅ تقاطع MACD صاعد")
    elif last['macd'] < last['signal'] and prev['macd'] >= prev['signal']:
        short_score += 2
        reasons.append("✅ تقاطع MACD هابط")

    # 5) الحجم
    if last['volume'] > last['vol_ma'] * 1.2:
        if last['close'] > prev['close']:
            long_score += 1
            reasons.append("💪 حجم مرتفع مؤكد")
        else:
            short_score += 1

    # 6) تأكيد Bollinger
    if last['close'] < last['bb_dn']:
        long_score += 1
        reasons.append("📊 تحت Bollinger السفلي")
    elif last['close'] > last['bb_up']:
        short_score += 1
        reasons.append("📊 فوق Bollinger العلوي")

    # 7) Stochastic RSI
    if last['stoch_rsi'] < 0.2:
        long_score += 1
    elif last['stoch_rsi'] > 0.8:
        short_score += 1

    # القرار
    if long_score >= 5 and long_score > short_score:
        direction = "LONG"
    elif short_score >= 5 and short_score > long_score:
        direction = "SHORT"
    else:
        return {"signal": "WAIT", "long_score": long_score,
                "short_score": short_score, "reasons": reasons}

    price = last['close']
    atr   = last['atr']

    if direction == "LONG":
        sl  = price - atr * 1.5
        tp1 = price + atr * 2.0
        tp2 = price + atr * 3.5
        tp3 = price + atr * 5.0
    else:
        sl  = price + atr * 1.5
        tp1 = price - atr * 2.0
        tp2 = price - atr * 3.5
        tp3 = price - atr * 5.0

    risk   = abs(price - sl)
    reward = abs(tp2 - price)
    rr     = reward / risk if risk > 0 else 0

    return {
        "signal": direction,
        "entry": price,
        "stop_loss": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rr": rr,
        "rsi": last['rsi'],
        "score": max(long_score, short_score),
        "reasons": reasons
    }

# ============================================================
#               التحليل عبر أكثر من منصة (تجميعي ومرن)
# ============================================================
def analyze_multi(symbol, timeframe, leverage_suggestion=None):
    """يحلل العملة على المنصات المتاحة ويقبل الإشارة حتى لو توقفت بعض المنصات"""
    results = {}
    for name in EXCHANGES:
        try:
            df = fetch_data(name, symbol, timeframe)
            df = calculate_indicators(df)
            res = signal_engine(df)
            res['price'] = df['close'].iloc[-1]
            results[name] = res
        except Exception as e:
            # حفظ نص الخطأ بوضوح مع نوعه
            results[name] = {
                "error": f"[{type(e).__name__}] {str(e)}"
            }

    # التصويت وحساب عدد المنصات النشطة
    votes = {"LONG": 0, "SHORT": 0, "WAIT": 0}
    active_exchanges = 0
    for name, r in results.items():
        if 'error' in r:
            continue
        active_exchanges += 1
        votes[r.get('signal', 'WAIT')] += 1

    # القرار النهائي المرن: يعتمد الأغلبية المتاحة (حتى لو عملت منصة واحدة فقط)
    if active_exchanges == 0:
        final = "WAIT"
        status_note = "⚠️ تعطل الاتصال بجميع المنصات"
    elif active_exchanges == 1:
        if votes["LONG"] == 1:
            final = "LONG"
            status_note = "⚠️ تنبيه: إشارة معتمدة على منصة واحدة فقط متاحة"
        elif votes["SHORT"] == 1:
            final = "SHORT"
            status_note = "⚠️ تنبيه: إشارة معتمدة على منصة واحدة فقط متاحة"
        else:
            final = "WAIT"
            status_note = "ℹ️ منصة واحدة متاحة وحالتها انتظار"
    else:
        # في حال توفر منصتين أو ثلاث، نطلب أغلبية واضحة (أو صوتين على الأقل)
        min_votes = 2 if active_exchanges >= 2 else 1
        if votes["LONG"] >= min_votes and votes["LONG"] > votes["SHORT"]:
            final = "LONG"
            status_note = f"✅ توافق {votes['LONG']} من {active_exchanges} منصات"
        elif votes["SHORT"] >= min_votes and votes["SHORT"] > votes["LONG"]:
            final = "SHORT"
            status_note = f"✅ توافق {votes['SHORT']} من {active_exchanges} منصات"
        else:
            final = "WAIT"
            status_note = "ℹ️ لا يوجد إجماع كافٍ بين المنصات المتاحة"

    # متوسط السعر والمستويات من المنصات المتفقة
    same = [r for r in results.values() if r.get('signal') == final and 'error' not in r]
    if same and final != "WAIT":
        avg = {
            "entry":     np.mean([r['price']      for r in same]),
            "stop_loss": np.mean([r['stop_loss']  for r in same]),
            "tp1":       np.mean([r['tp1']        for r in same]),
            "tp2":       np.mean([r['tp2']        for r in same]),
            "tp3":       np.mean([r['tp3']        for r in same]),
            "rr":        np.mean([r['rr']         for r in same]),
        }
    else:
        avg = None

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "votes": votes,
        "active_exchanges": active_exchanges,
        "status_note": status_note,
        "final": final,
        "levels": avg,
        "details": results
    }

# ============================================================
#                   العرض الجميل
# ============================================================
def fmt_price(p):
    if p >= 1000:  return f"{p:,.2f}"
    elif p >= 1:   return f"{p:.4f}"
    else:          return f"{p:.6f}"

def print_result(r, leverage=10):
    print("\n" + "="*65)
    print(f"  📊 {r['symbol']}  |  فريم: {r['timeframe']}")
    print("="*65)

    votes = r['votes']
    color = Fore.GREEN if r['final'] == "LONG" else (Fore.RED if r['final'] == "SHORT" else Fore.YELLOW)
    print(f"  🗳️  تصويت المنصات ({r.get('active_exchanges', 0)}/3 نشطة): LONG={votes['LONG']} | SHORT={votes['SHORT']} | WAIT={votes['WAIT']}")
    print(f"  🎯 القرار النهائي: {color}{r['final']}{Style.RESET_ALL}  ({r.get('status_note', '')})")

    for name, d in r['details'].items():
        if 'error' in d:
            print(f"\n  ❌ {name.upper()} فشل الاتصال:\n     السبب: {d['error']}")
            continue
        c = Fore.GREEN if d.get('signal')=="LONG" else (Fore.RED if d.get('signal')=="SHORT" else Fore.YELLOW)
        print(f"\n  ── {name.upper()} ──  {c}{d.get('signal','WAIT')}{Style.RESET_ALL}  "
              f"(نقاط: {d.get('score', 0)})")
        if d.get('signal') != 'WAIT':
            print(f"     💰 السعر: {fmt_price(d['price'])}")
            print(f"     🛑 SL: {fmt_price(d['stop_loss'])}")
            print(f"     🎯 TP1: {fmt_price(d['tp1'])}  |  "
                  f"TP2: {fmt_price(d['tp2'])}  |  TP3: {fmt_price(d['tp3'])}")
            print(f"     ⚖️  R:R = 1:{d['rr']:.2f}")

    if r['levels']:
        L = r['levels']
        print("\n" + "-"*65)
        print(f"  ✅ المستويات الموصى بها:")
        print(f"     💰 الدخول:        {fmt_price(L['entry'])}")
        print(f"     🛑 وقف الخسارة:  {fmt_price(L['stop_loss'])}")
        print(f"     🎯 الهدف 1:      {fmt_price(L['tp1'])}")
        print(f"     🎯 الهدف 2:      {fmt_price(L['tp2'])}")
        print(f"     🎯 الهدف 3:      {fmt_price(L['tp3'])}")
        print(f"     ⚖️  R:R = 1:{L['rr']:.2f}")
        print(f"     🔥 ليفرج مقترح: {leverage}x")

        entry = L['entry']
        if r['final'] == "LONG":
            pnl_sl = (L['stop_loss'] - entry) / entry * 100 * leverage
            pnl_tp2 = (L['tp2'] - entry) / entry * 100 * leverage
        else:
            pnl_sl = (entry - L['stop_loss']) / entry * 100 * leverage
            pnl_tp2 = (entry - L['tp2']) / entry * 100 * leverage
        print(f"     📉 خسارة متوقعة على SL  : {pnl_sl:+.2f}% (برافعة)")
        print(f"     📈 ربح متوقع على TP2    : {pnl_tp2:+.2f}% (برافعة)")

    print("\n  📝 أسباب الإشارة:")
    for name, d in r['details'].items():
        if 'error' not in d and d.get('signal') == r['final'] and d.get('reasons'):
            for reason in d['reasons'][:5]:
                print(f"     • {reason}")
            break

# ============================================================
#               البحث عن أفضل الفرص في السوق (مع بديل تلقائي)
# ============================================================
def scan_top_symbols(top_n=30, timeframe='1h', min_score=5):
    """يمسح أفضل العملات من Binance أو OKX كبديل تلقائي ثم يحللها"""
    source_ex = None
    markets = {}
    tickers = {}

    # محاولة الجلب من Binance أولاً ثم OKX كبديل في حال الحظر السحابي
    for candidate in ['binance', 'okx']:
        try:
            ex = EXCHANGES[candidate]
            markets = ex.load_markets()
            tickers = ex.fetch_tickers()
            source_ex = candidate
            break
        except Exception as e:
            print(f"⚠️ تعذر جلب قائمة العملات من {candidate}: [{type(e).__name__}] {e}")

    if not source_ex:
        return []

    usdt = [s for s in markets if markets[s].get('swap') and s.endswith('/USDT:USDT')]
    usdt_sorted = sorted(
        usdt,
        key=lambda s: tickers.get(s, {}).get('quoteVolume', 0) or 0,
        reverse=True
    )[:top_n]

    opportunities = []
    for s in usdt_sorted:
        try:
            clean = s.split(':')[0]  # BTC/USDT
            r = analyze_multi(clean, timeframe)
            if r['final'] != "WAIT" and r['levels']:
                opportunities.append(r)
        except Exception:
            continue
        time.sleep(0.2)

    opportunities.sort(key=lambda x: x['votes'][x['final']], reverse=True)
    return opportunities
