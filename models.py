
Gemini 2.5 Pro Preview 03-25
Chat Prompt
yasmin-app.zip
229 688 tokens
اضف خاصية الصوت والتكلم مجانية من قوقل ستوديو api
حسنًا، سأقوم بإعادة بناء الكود ليكون تطبيق Flask (Python) احترافيًا يعتمد على واجهات برمجة تطبيقات مجانية قدر الإمكان، مع واجهة مستخدم محسنة ومجهز للنشر على Render.
الافتراضات والتغييرات:
الواجهة الخلفية: Flask (Python) كما في الملفات التي قدمتها.
قاعدة البيانات: PostgreSQL (كما هو متوقع لـ Render). سنستخدم SQLAlchemy.
المحادثة النصية (API):
الأولوية 1 (اختياري): Google Gemini (إذا تم توفير GOOGLE_API_KEY).
الأولوية 2 (افتراضي مجاني): Hugging Face Inference API (يتطلب HUGGINGFACE_API_TOKEN). سنستخدم نموذجًا مثل Mistral 7B Instruct أو Gemma 7B IT.
الأولوية 3 (احتياطي): ردود ثابتة في حالة عدم توفر أي مفتاح أو فشل الـ APIs.
الصوت (TTS/STT): سنستخدم Web Speech API المدمجة في المتصفح (مجانية). سيتم التعامل معها بالكامل في JavaScript بالواجهة الأمامية.
الواجهة الأمامية: HTML + CSS + Vanilla JavaScript (يتم تقديمه بواسطة Flask).
الاحترافية:
تصميم داكن/فاتح قابل للتبديل.
حفظ المحادثات في قاعدة البيانات.
إمكانية بدء محادثة جديدة وحذف القديمة.
إعدادات لاختيار النموذج (إذا كان OpenRouter متاحًا، لكن سنركز على HF/Gemini)، درجة الحرارة، إلخ.
أزرار نسخ وإعادة توليد للردود.
مؤشر للكتابة.
مؤشر لحالة الاتصال/عدم الاتصال.
تصميم متجاوب.
Render: سيتم تجهيز الملفات وهيكل المشروع ليكون متوافقًا مع Render. سنحتاج لملف render.yaml.
إزالة لوحة التحكم: لن يتم تضمين أي مسارات أو نماذج خاصة بالمشرفين.
هيكل الملفات:
yasmine-app/
├── app.py                 # ملف Flask الرئيسي (Routes, App Setup)
├── main.py                # نقطة الدخول لتشغيل التطبيق وإنشاء الجداول
├── models.py              # نماذج SQLAlchemy (Conversation, Message)
├── requirements.txt       # اعتماديات Python
├── static/
│   ├── css/
│   │   └── styles.css     # ملف CSS الرئيسي
│   └── js/
│       └── app.js         # ملف JavaScript للواجهة الأمامية
├── templates/
│   └── index.html         # قالب HTML الرئيسي
├── .env                   # (أنشئه بنفسك) متغيرات البيئة
├── .gitignore
└── render.yaml            # ملف إعدادات Render
Use code with caution.
ملف 1: الإعدادات والاعتماديات (requirements.txt, .env, .gitignore, render.yaml)
# ==================================================
# =============== FILE 1: SETUP FILES ==============
# ==================================================

# ==================================================
# === requirements.txt ===
# ==================================================
Flask>=2.3.0,<3.0.0
Flask-SQLAlchemy>=3.0.0,<4.0.0
SQLAlchemy>=1.4.0,<2.1.0 # تحديد إصدار متوافق مع Flask-SQLAlchemy 3.x
psycopg2-binary>=2.9.0,<3.0.0 # لـ PostgreSQL
requests>=2.28.0,<3.0.0
python-dotenv>=1.0.0,<2.0.0
gunicorn>=20.0.0,<23.0.0 # لخادم الإنتاج على Render
google-generativeai>=0.4.0 # لـ Gemini API
huggingface_hub>=0.19.0 # للحصول على معلومات النموذج (اختياري)
# email-validator غير مطلوب إذا لم يكن هناك تسجيل دخول معقد
# Flask-Login أو Flask-Session يمكن إضافتهما لاحقًا إذا احتجت لإدارة جلسات المستخدم

# ==================================================
# === .env (أنشئ هذا الملف بنفسك) ===
# ==================================================
# (مطلوب للخيار المجاني الافتراضي) رمز Hugging Face API
# احصل عليه من: https://huggingface.co/settings/tokens
HUGGINGFACE_API_TOKEN="hf_YOUR_HUGGINGFACE_TOKEN"

# (اختياري - أولوية أعلى إذا وُجد) مفتاح Google Gemini API
# احصل عليه من Google AI Studio: https://aistudio.google.com/app/apikey
GOOGLE_API_KEY="AIzaSyYOUR_GEMINI_API_KEY"

# (مطلوب) رابط قاعدة بيانات PostgreSQL من Render أو أي مزود آخر
# مثال: postgresql://user:password@host:port/database
DATABASE_URL="postgresql://..."

# (اختياري) مفتاح سري لجلسات Flask (إذا استخدمت لاحقًا)
# SESSION_SECRET="غير_هذا_المفتاح_السري_في_الإنتاج"

# (اختياري) عنوان URL للتطبيق (مهم لـ OpenRouter إذا استخدمته)
# APP_URL="https://your-app-name.onrender.com"

# ==================================================
# === .gitignore ===
# ==================================================
__pycache__/
*.pyc
*.pyo
*.pyd
.env
.DS_Store
venv/
dist/
build/
*.egg-info/
instance/

# ==================================================
# === render.yaml ===
# ==================================================
services:
  - type: web
    name: yasmine-chat-app
    env: python
    plan: free # أو خطة مدفوعة إذا احتجت موارد أكثر
    buildCommand: "pip install -r requirements.txt && python main.py db_create_all" # تثبيت الاعتماديات وإنشاء الجداول
    startCommand: "gunicorn app:app" # تشغيل التطبيق باستخدام Gunicorn
    envVars:
      - key: PYTHON_VERSION
        value: 3.11 # أو الإصدار الذي تفضله
      - key: DATABASE_URL
        fromDatabase:
          name: yasmine-db # اسم قاعدة بيانات PostgreSQL التي أنشأتها على Render
          property: connectionString
      - key: HUGGINGFACE_API_TOKEN
        sync: false # أدخله يدويًا كـ Secret في Render
      - key: GOOGLE_API_KEY # اختياري
        sync: false # أدخله يدويًا كـ Secret في Render
      # - key: SESSION_SECRET # إذا استخدمت جلسات
      #   generateValue: true # Render سيقوم بتوليد قيمة آمنة

databases:
  - name: yasmine-db
    databaseName: yasmine_db # اسم قاعدة البيانات الفعلي
    user: yasmine_user # اسم المستخدم
    plan: free # أو خطة مدفوعة
    region: frankfurt # اختر المنطقة الأقرب لك
    ipAllowList: [] # السماح بالاتصال من أي مكان (أو حدده إذا لزم الأمر)

# ==================================================
# ============ END OF FILE 1 =======================
# ==================================================
Use code with caution.
Text
ملف 2: الواجهة الخلفية (Backend Logic - app.py, models.py, main.py)
# ==================================================
# =========== FILE 2: BACKEND LOGIC ================
# ==================================================

# ==================================================
# === models.py ===
# ==================================================
from app import db # استيراد db من app.py
from datetime import datetime, timezone # استخدام timezone
import uuid

class Conversation(db.Model):
    __tablename__ = 'conversation' # اسم الجدول الصريح
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = db.Column(db.String(100), nullable=False, default="محادثة جديدة")
    # ربط المستخدم بالمحادثة (إذا أضفنا نموذج User لاحقًا)
    # user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    messages = db.relationship('Message', backref='conversation', lazy='dynamic', cascade="all, delete-orphan")

    def to_dict(self, include_messages=False):
        data = {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_messages:
            # جلب الرسائل مرتبة
            msgs = self.messages.order_by(Message.created_at.asc()).all()
            data["messages"] = [msg.to_dict() for msg in msgs]
        return data

    def add_message(self, role, content):
        """Helper method to add a message to this conversation"""
        message = Message(role=role, content=content, conversation_id=self.id)
        db.session.add(message)
        self.updated_at = datetime.now(timezone.utc) # تحديث وقت المحادثة
        return message

class Message(db.Model):
    __tablename__ = 'message' # اسم الجدول الصريح
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(20), nullable=False)  # 'user' or 'assistant' or 'error'
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    conversation_id = db.Column(db.String(36), db.ForeignKey('conversation.id', ondelete='CASCADE'), nullable=False)

    def to_dict(self):
        return {
            "id": self.id, # إضافة ID الرسالة
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

# 
