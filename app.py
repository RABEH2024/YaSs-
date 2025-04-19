import os
import logging
import requests
import json
import uuid
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase

# إعداد السجل
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# --- قاعدة SQLAlchemy ---
class Base(DeclarativeBase):
    pass

# --- تهيئة التطبيق ---
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "yasmin-gpt-secret-key")

# إعداد قاعدة البيانات
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///local.db")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(model_class=Base)
db.init_app(app)

# إعداد المفاتيح من البيئة
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# إعدادات عامة
APP_URL = os.environ.get("APP_URL", "http://localhost:5000")
APP_TITLE = "Yasmin GPT Chat"

# ردود افتراضية عند انقطاع الاتصال
offline_responses = {
    "السلام عليكم": "وعليكم السلام! أنا ياسمين. للأسف، لا يوجد اتصال بالإنترنت حاليًا.",
    "كيف حالك": "أنا بخير شكراً لك. لكن لا يمكنني الوصول للنماذج الذكية الآن بسبب انقطاع الإنترنت.",
    "مرحبا": "أهلاً بك! أنا ياسمين. أعتذر، خدمة الإنترنت غير متوفرة حالياً.",
    "شكرا": "على الرحب والسعة! أتمنى أن يعود الاتصال قريباً.",
    "مع السلامة": "إلى اللقاء! آمل أن أتمكن من مساعدتك بشكل أفضل عند عودة الإنترنت."
}
default_offline_response = "أعتذر، لا يمكنني معالجة طلبك الآن. يبدو أن هناك مشكلة في الاتصال بالإنترنت."

conversations = {}

@app.route('/')
def index():
    return jsonify({"message": "مرحبًا بك في Yasmin GPT Chat"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
