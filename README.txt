GALEIC FUTURES PRO - FREE MOBILE EDITION

المحتويات:
- app.py
- requirements.txt

المميزات:
- واجهة Streamlit متوافقة مع الهاتف.
- بحث عن عقود USDT الدائمة في Binance وBybit وOKX وGate.io.
- رسم شموع يابانية من Bybit مع EMA 20/50/200 وBollinger Bands.
- فريمات من دقيقة إلى أسبوع.
- مؤشرات RSI وMACD وATR.
- لوحة عقود Bybit: تغير 24 ساعة، Funding Rate، Open Interest، حجم التداول، ونسبة Long/Short عند توفرها.
- إشارة LONG / SHORT / WAIT مع وقف وأهداف تقديرية مبنية على ATR.
- مفضلة العملات.
- ترتيب العملات حسب توافق المؤشرات على فريم 15 دقيقة.

التثبيت:
pip install -r requirements.txt
streamlit run app.py

النشر على Streamlit:
استبدل app.py و requirements.txt في مستودع GitHub ثم Commit Changes وانتظر إعادة النشر.

حدود النسخة المجانية:
- البحث يفحص إدراج العقد في المنصات الأربع، لكن الرسم ولوحة المشتقات يعتمدان على Bybit.
- قد تحجب استضافة Streamlit بعض واجهات المنصات (403/429/451). تعذر الاتصال لا يعني أن العملة غير مدرجة.
- لا تشمل النسخة خرائط التصفية الحرارية أو سجل التصفية الشامل.
- المفضلة والترتيب محفوظان ضمن جلسة Streamlit الحالية وقد يعاد ضبطهما عند انتهاء الجلسة.
- الإشارات تقديرية وليست احتمالات نجاح أو ضمان ربح.
