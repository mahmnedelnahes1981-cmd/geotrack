# GeoTrack — BOQ → Handover, for Drilling & Deep Foundations

**من المقايسة للميدان للفاتورة.** منصة واحدة تستخرج بنود المقايسة من ملفات Excel/PDF (عربي وإنجليزي)، تسعّر البنود بقائمة أسعار الشركة، تتابع التنفيذ في الموقع (متاح بدون إنترنت للسواق)، وتقفل المشروع بحصر أعمال + فاتورة ختامية + تقرير فني PDF — جاهز للعرض كـ Portfolio Flagship.

**From bid to handover — one platform.** Extracts BOQ line items from Excel/PDF attachments (Arabic & English), prices them from the company's price list, tracks field execution (offline-first site app), and closes out with as-built reports and a final invoice.

> الحالة: **المرحلة الأولى + الثانية + الثالثة مكتملتان — 83 اختبارًا أخضر.** بدون Auth بعد (مؤجل للإطلاق التجاري).

---

## لماذا GeoTrack؟

شركات الحفر والأساسات العميقة (الخوازيق الدقيقة، الستائر اللوحية، الجيت جروت) بتعاني من فجوة واحدة: المقايسة تتكتب في Word/Excel، والتسعير يتعمل يدوي، والتنفيذ يتسجل في دفاتر ورقية، والفاتورة النهائية تتلم من الدفاتر دي كلها. GeoTrack بيقفل الدورة دي كلها في مكان واحد:

- **العرض يتبني لوحده** من ملفات العميل (مع مراجعة بشرية قبل أي اعتماد).
- **السواق يسجل شغل يومه من التليفون** حتى لو الموقع بدون نت — السجلات بتتزامن تلقائيًا أول ما الشبكة ترجع.
- **الفاتورة النهائية محسوبة من الواقع**: كميات منفذة فعليًا × أسعار العرض المعتمد — مفيش أرقام متخمنة.

---

## لقطات من النظام (Screenshots)

أضف صور الشاشات في مجلد `docs/screenshots/` واربطها هنا قبل النشر على GitHub:

- لوحة التحكم التنفيذية (`docs/screenshots/dashboard.png`)
- شاشة المراجعة والتسعير (`docs/screenshots/review-ui.png`)
- شاشة سواق الحفار RTL — Offline First (`docs/screenshots/field-mobile.png`)
- نموذج عرض السعر / التقرير الفني PDF (`docs/screenshots/quote-pdf.png`)

---

## الوحدات الثلاث

### 1) المقايسات والتسعير (Phase 1)

| خطوة | اللي بيحصل |
|---|---|
| رفع ملف | Excel/CSV/PDF رقمي — كشف أوتوماتيك لصف العناوين AR/EN، دعم أرقام عربية (٨٥٠) وفواصل US/EU |
| قراءة الـ PDF | pdfplumber للجداول + **إصلاح النص العربي** المخزن بترتيب بصري (presentation forms → نص منطقي) |
| التطبيع (اختياري) | LLM (OpenAI-compatible — Ollama محلي أو أي API) بضبط `temperature=0` — **الـ LLM ممنوع من لمس الكميات/الوحدات**؛ العين البشرية بتعتمد كل بند |
| مراجعة بشرية | Review UI (Jinja2 + HTMX) — اعتماد/تعديل/رفض بلا reload، الثقة بألوان |
| التسعير | `(material+labor+equipment) × (1+overhead%) × (1+profit%)` + تحويل وحدات حتمي (طن↔كجم، ساعة↔يوم) — **لا تسعير صامت**: أي لبس وحدات → البند يُستبعد مع سبب صريح |
| العرض | عرض سعر احترافي PDF (عربي/إنجليزي) + Versioning (v1, v2…) |

### 2) العمليات الميدانية (Phase 2)

- **شاشة سواق الحفار** (`/projects/{id}/field`): أزرار كبيرة، RTL، **تعمل بدون إنترنت** — كل سجل بيتخزن على الجهاز (localStorage) وبيتزامن تلقائيًا بـ `client_uuid` (مفيش تكرار) أو بزر مزامنة.
- **المعدات**: `/rigs` — تخصيص حفار لمشروع من نقرة (حفار الصيانة ما بيتخصصش)، فك التخصيص تلقائي عند التسليم.
- **تتبع التنفيذ** (`/projects/{id}`): "المتعاقد مقابل المنفذ" لكل بند (حفر/خرسانة/ستائر) + نسبة الإنجاز الإجمالية.

### 3) التسليم والفوترة (Phase 3)

- **فاتورة ختامية As-Built** (`/invoices/{id}`): الكميات الفعلية من السجل الميداني × أسعار العرض المعتمد — مقارنة "قيمة العقد vs المنفذ"، والبنود بدون مقياس ميداني تُذكر صراحة كمستبعدة.
- **تقرير فني للتسليم** (`/projects/{id}/report.pdf`): كل سجل حفر + إجماليات (أطول/متوسط عمق، خرسانة، ساعات، أيام بملاحظات) + فراغ توقيع للمهندس والاستشاري.
- **تقفيل المشروع**: زر "🏁 إنهاء وتسليم" — المشروع يصبح completed والحفار يرجع متاح تلقائيًا.
- **لوحة التحكم** (`/`): كروت إحصائية + أحدث المشاريع بروابط مباشرة.

---

## المعمارية

```
ملف المقايسة (Excel / CSV / PDF)
        │
        ▼
┌───────────────────┐      ┌─────────────────┐      ┌──────────────────┐
│ Extractors        │ ───▶ │ LLM Normalizer  │ ───▶ │ Human Review UI  │
│ (حتمي deterministic│     │ (اختياري، temp=0)│      │ (Jinja2 + HTMX)  │
│  AR/EN, وحدات)    │      └─────────────────┘      └────────┬─────────┘
└───────────────────┘                                          ▼
                                              ┌──────────────────────────────┐
                                              │ Pricing Engine (unit_factor, │
                                              │ versioning, VAT configurable)│
                                              └──────────────┬───────────────┘
                                                             ▼
       ┌───────────────────────────────────────────────────────────────┐
       │  Quote PDF  ─►  قبول العرض  ─►  تنفيذ ميداني (offline-first:   │
       │  daily_logs + rigs)  ─►  تتبع الإنجاز  ─►  فاتورة ختامية PDF    │
       │  + تقرير فني للتسليم  ─►  تقفيل المشروع ─►  لوحة التحكم         │
       └───────────────────────────────────────────────────────────────┘
```

طبقات مقصودة بوضوح: **الاستخراج deterministic** (نفس الملف → نفس الناتج)، **الذكاء اختياري** (الـ LLM ما بيختلقش أرقام)، **الاعتماد البشري إجباري** قبل أي ثمن.

---

## التقنية

| الطبقة | الاختيار |
|---|---|
| Backend | Python 3.12 · FastAPI · SQLAlchemy 2 · Alembic |
| DB | SQLite للتطوير (افتراضي) — الانتقال لـ PostgreSQL بتغيير `DATABASE_URL` فقط |
| LLM | OpenAI-compatible (Ollama محلي افتراضيًا — qwen2.5vl/llama3 — أو Gemini/OpenAI بـ 3 أسطر في `.env`) |
| PDFs | fpdf2 + arabic-reshaper + python-bidi (RTL كامل: عرض/فاتورة/تقرير) |
| Frontend | Jinja2 + HTMX (بدون build step) + CSS RTL مخصص — كل مكتبة JS vendored (offline-friendly) |
| Tests | pytest — 83 اختبارًا (وحدات + تكامل + UI عبر TestClient) |

---

## التشغيل من الصفر (Windows / PowerShell)

المتطلبات: Python 3.12+.

```powershell
git clone <your-repo-url> geotrack
cd geotrack

python -m venv .venv
.\.venv\Scripts\pip install -e ".[dev]"
.\.venv\Scripts\alembic upgrade head

# بيانات تجريبية: قائمة أسعار + أسطول (5 معدات)
.\.venv\Scripts\python scripts\seed_price_list.py
.\.venv\Scripts\python scripts\seed_rigs.py

# تشغيل السيرفر
.\.venv\Scripts\python -m uvicorn app.main:app --reload
# افتح http://127.0.0.1:8000
```

### التشغيل بـ Docker (FastAPI + PostgreSQL)

```powershell
docker compose up -d --build
# التطبيق يعمل على http://localhost:8000 والـ migrations تُنفذ تلقائيًا عند الإقلاع
```

> مسار Postgres جاهز من ناحية الكود (`DATABASE_URL=postgresql+psycopg2://geotrack:geotrack@db:5432/geotrack`)،
> والـ migrations تُنفذ عند إقلاع الحاوية (`alembic upgrade head`). ملفات Docker مُقدَّمة كبداية جاهزة للتخصيص —
> لم تُبنَ محليًا على جهاز التطوير هذا (لا يوجد Docker عليه)؛ التطبيق نفسه يعمل بدون Docker على SQLite.

### الدورة الكاملة بدقيقتين (Demo)

```powershell
# 1) استورد ملف مقايسة عربي حقيقي للديمو (خوازيق + ستائر)
.\.venv\Scripts\python scripts\ingest_demo.py tests\fixtures\boq_ar_micropiles.pdf
# → document #1 · 5 بنود (حفر 850م / تسليح 12.5 طن / خرسانة 96م³ / ستائر 420م² / مقطوعية)

# 2) اعتماد تجريبي لكل البنود وربطها ببنود قائمة الأسعار + إنشاء عرض السعر
.\.venv\Scripts\python scripts\demo_approve.py 1
# → GT-0001-v1 — grand total 223,868.73 USD

# 3) سجلات ميدانية تجريبية (+ تخصيص DRL-001)
.\.venv\Scripts\python scripts\demo_logs.py 1

# 4) افتح المتصفح:
#    /projects/1       → قارن "المتعاقد vs المنفذ" · 🧾 إنشاء فاتورة ختامية · 🏁 إنهاء وتسليم المشروع
#    /projects/1/field → شاشة سواق الحفار (موبايل) — تشتغل بدون نت
#    /                 → لوحة التحكم التنفيذية
```

لو عايز تبدأ نضيف بالكامل: احذف `geotrack.db` ثم `alembic upgrade head` — كل البيئة التجريبية بتتبني بـ 3 أوامر seed.

---

## الاختبارات والجودة

```powershell
.\.venv\Scripts\python -m pytest        # 83 passed
```

- **Golden files** حقيقية: PDFs/Excel/CSV عربية وإنجليزية (معالجة أرقام هندية، وحدات مثل "م²" و"طن").
- الاختبارات بتغطي: الاستخراج، تطبيع الوحدات، طبقة الـ LLM (بعميل وهمي)، محرك التسعير (معادلات متحققة يدويًا)، الفوترة As-built، الفواتير، قبول العرض، تخصيص الحفارات، المزامنة بدون نت (dedupe + رفض كميات سالبة)، وتشغيل الـ UI كاملًا.

---

## الإعدادات (.env)

| المتغير | الافتراضي | الغرض |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./geotrack.db` | ضع `postgresql+psycopg2://user:pass@host/db` للإنتاج |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | Ollama محلي · `qwen2.5vl:7b` | أي OpenAI-compatible endpoint — Gemini/OpenAI بتغيير 3 أسطر |
| `QUOTE_TAX_RATE` | `14.0` | الضريبة الافتراضية لكل عرض/فاتورة جديدة (قابلة للتعديل من الواجهة) |
| `QUOTE_VALIDITY_DAYS` | `30` | صلاحية عرض السعر |
| `COMPANY_*` | قيم توضيحية | هوية الشركة على الـ PDFs (الاسم AR/EN، العنوان، التليفون، الرقم الضريبي) |
| `UPLOAD_DIR` | `./storage/uploads` | مرفقات وصور المعدات (تُستبعد من git) |

`.env` **مستبعد من git**؛ `.env.example` فيه كل المفاتيح بلا قيم سرية.

---

## هيكل المشروع

```
geotrack/
├── .env.example              # كل الإعدادات بلا أسرار
├── .gitignore                # Python · .venv · .env · geotrack.db · storage/
├── .dockerignore             # استبعاد الملفات المحلية من صورة Docker
├── Dockerfile                # حاوية FastAPI + Alembic
├── docker-compose.yml        # app + PostgreSQL 16
├── .github/workflows/ci.yml  # تشغيل pytest تلقائيًا على GitHub
├── alembic/                  # 3 migrations: base → field-ops → invoices
├── alembic.ini
├── pyproject.toml            # metadata + dependencies + pytest config
├── README.md
├── app/
│   ├── main.py               # FastAPI app factory + /health
│   ├── config.py             # pydantic-settings (.env)
│   ├── db.py                 # engine + Base + get_db
│   ├── models.py             # 12 جدولًا (SQLite/PostgreSQL-portable)
│   ├── services.py           # ingest_file(): ملف → Document + proposed BoqItems
│   ├── pricing.py            # محرك التسعير + versioning العروض
│   ├── invoicing.py          # الفوترة الختامية (توزيع فعلي على بنود العقد)
│   ├── progress.py           # المتعاقد مقابل المنفذ
│   ├── pdf_common.py         # أدوات PDF مشتركة (RTL)
│   ├── quote_pdf.py          # PDF عرض السعر
│   ├── invoice_pdf.py        # PDF الفاتورة الختامية
│   ├── report_pdf.py         # PDF التقرير الفني للتسليم
│   ├── seed.py               # قائمة الأسعار (20 بندًا، AR/EN)
│   ├── extract/              # Excel · CSV · PDF + Arabic-fix + units + header detection
│   ├── llm/                  # OpenAI-compatible client + Pydantic strict schema
│   ├── routers/              # web · quotes · projects · field · handover
│   ├── static/               # CSS RTL · field.js (offline queue) · htmx vendored
│   └── templates/            # Jinja2 templates (dashboard/…/quote/invoice/field)
├── scripts/                  # demo_* · seed_* · ingest_demo · make_golden_files
└── tests/                    # 83 اختبارًا + golden fixtures (AR/EN)
```

---

## ملاحظات للإنتاج (بصراحة)

- **لا يوجد Auth بعد** — مثالي للعرض المحلي والديمو؛ قبل أي بيانات عميل حقيقي: أضف أدوارًا (مدير/قارئ/مسجل ميداني) وربطًا واحدًا بـ Postgres حقيقي + HTTPS.
- **المعالجة متزامنة** — ملفات الـ BOQ الكبيرة المستقبلية تحتاج worker (RQ/Celery)؛ الكود مصمم ليقبل ده كطبقة عزل.
- **التكامل التشيكي** (ISDOC، Pohoda/Money S3) مخطوط له في البنية لكن غير مربوط بعد.
- **المعدات أسعار استرشادية** — قائمة الأسعار الافتراضية للتجربة فقط؛ العميل يستبدلها بقائمته الفعلية عبر `/rigs` و`price_lists`.
- **مسار Postgres غير مُختبَر ضد سيرفر حي** على جهاز التطوير هذا؛ الـ Docker Compose يُقدَّم كبداية للتخصيص، والبديل المؤكد للتشغيل هو SQLite بدون Docker.

---

## Roadmap

1. Auth + أدوار (مدير / قارئ / مسجل موقع) — مرحلة الإطلاق التجاري
2. مزامنة ثنائية الاتجاه (تعديل/حذف السجلات) + إشعارات
3. فواتير ISDOC + ربط محاسبي (Pohoda/Money S3)
4. نشر Docker (app + Postgres + Caddy TLS) + staging ببيانات العميل

---

**GeoTrack** — صُنع بإتقان. 83/83 اختبار أخضر.
