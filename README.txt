GALEIC FUTURES PRO V4
======================
إصلاح خطأ OKX Instrument ID:
- لم يعد التطبيق يخمّن اسم العقد.
- يستعلم أولاً عن عقود OKX الدائمة الحية من نوع Linear وتسوية USDT.
- يطابق رمز العملة مع baseCcy ويستخدم instId الرسمي.
- إذا لم تكن العملة مدرجة كعقد دائم USDT على OKX تظهر رسالة واضحة ويمكن تجربة Bybit.
- البحث والفريم وزر التحليل تظهر قبل الاتصال بمزود البيانات.

التحديث:
استبدل app.py و requirements.txt في GitHub ثم Commit Changes وانتظر إعادة نشر Streamlit.

اختبار:
اختر OKX Futures، اكتب BTC أو ACE، اختر 15m، ثم تحليل العملة.
إذا لم يكن العقد متاحاً على OKX بدّل إلى Bybit Futures.

تشغيل محلي:
pip install -r requirements.txt
streamlit run app.py

الأداة تحليل فقط ولا تنفذ صفقات. الإشارات تقديرية وليست ضماناً للربح.
