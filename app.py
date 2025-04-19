import os
import logging
import requests
import uuid
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase

# إعداد التسجيل (Logging)
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# قاعدة للنماذج
class Base(DeclarativeBase):
    pass

# إعداد تطبيق Flask
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "yasmin-gpt-secret-key")

# إعداد قاعدة البيانات مع خيار SQLite افتراضي
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///yasmin.db")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# تهيئة SQLAlchemy
db = SQLAlchemy(model_class=Base)
db.init_app(app)

# مفاتيح API
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# إعدادات عامة
APP_URL = os.environ.get("APP_URL", "http://localhost:5000")
APP_TITLE = "Yasmin GPT Chat"

# ردود ياسمين عند انقطاع الإنترنت
offline_responses = {
    "السلام عليكم": "وعليكم السلام! أنا ياسمين. للأسف، لا يوجد اتصال بالإنترنت حالياً.",
    "كيف حالك": "أنا بخير شكراً لك. لكن لا يمكنني الوصول للنماذج الذكية الآن بسبب انقطاع الإنترنت.",
    "مرحبا": "أهلاً بك! أنا ياسمين. أعتذر، خدمة الإنترنت غير متوفرة حالياً.",
    "شكرا": "على الرحب والسعة! أتمنى أن يعود الاتصال قريباً.",
    "مع السلامة": "إلى اللقاء! آمل أن أتمكن من مساعدتك بشكل أفضل عند عودة الإنترنت."
}
default_offline_response = "أعتذر، لا يمكنني معالجة طلبك الآن. يبدو أن هناك مشكلة في الاتصال بالإنترنت."

# الصفحة الرئيسية
@app.route('/')
def index():
    return render_template('index.html', app_title=APP_TITLE)

# دالة استخدام Gemini كنموذج احتياطي
def call_gemini_api(prompt, max_tokens=512):
    if not GEMINI_API_KEY:
        return None, "مفتاح Gemini API غير متوفر"
    
    try:
        formatted_prompt = ""
        if isinstance(prompt, list):
            for msg in prompt:
                role = "المستخدم: " if msg["role"] == "user" else "ياسمين: "
                formatted_prompt += f"{role}{msg['content']}\n\n"
        else:
            formatted_prompt = f"المستخدم: {prompt}\n\n"
        formatted_prompt += "ياسمين: "

        logger.debug(f"Calling Gemini API with prompt: {formatted_prompt[:100]}...")
        response = requests.post(
            url=f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}",
            headers={'Content-Type': 'application/json'},
            json={
                "contents": [{
                    "parts": [{"text": formatted_prompt}]
                }],
                "generationConfig": {
                    "maxOutputTokens": max_tokens,
                    "temperature": 0.7
                }
            }
        )
        response.raise_for_status()
        response_data = response.json()

        if 'candidates' in response_data and len(response_data['candidates']) > 0:
            text = response_data['candidates'][0]['content']['parts'][0]['text']
            return text, None
        else:
            return None, "لم يتم العثور على استجابة من Gemini"
    except Exception as e:
        logger.error(f"Error calling Gemini API: {e}")
        return None, str(e)

# --- API: دردشة ---
@app.route('/api/chat', methods=['POST'])
def chat():
    from models import Conversation, Message
    try:
        data = request.json
        user_message = data.get('message')
        model = data.get('model', 'mistralai/mistral-7b-instruct')
        history = data.get('history', [])
        conversation_id = data.get('conversation_id') or str(uuid.uuid4())
        temperature = data.get('temperature', 0.7)
        max_tokens = data.get('max_tokens', 512)

        if not user_message:
            return jsonify({"error": "الرسالة فارغة"}), 400

        db_conversation = db.session.execute(
            db.select(Conversation).filter_by(id=conversation_id)
        ).scalar_one_or_none()

        if not db_conversation:
            db_conversation = Conversation(id=conversation_id, title=user_message[:50])
            db.session.add(db_conversation)
            db.session.commit()

        db_conversation.add_message('user', user_message)
        db.session.commit()

        if not history:
            db_messages = db.session.execute(
                db.select(Message).filter_by(conversation_id=conversation_id).order_by(Message.created_at)
            ).scalars().all()
            messages = [{"role": msg.role, "content": msg.content} for msg in db_messages]
        else:
            messages = history + [{"role": "user", "content": user_message}]

        ai_reply, error_message, used_backup = None, None, False

        if OPENROUTER_API_KEY:
            try:
                response = requests.post(
                    url="https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "HTTP-Referer": APP_URL,
                        "X-Title": APP_TITLE,
                    },
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    }
                )
                response.raise_for_status()
                api_response = response.json()
                ai_reply = api_response['choices'][0]['message']['content']
            except Exception as e:
                logger.error(f"Error with OpenRouter: {e}")
                error_message = str(e)

        if not ai_reply and GEMINI_API_KEY:
            ai_reply, backup_error = call_gemini_api(messages, max_tokens)
            if ai_reply:
                used_backup = True
            else:
                error_message = f"فشل النموذج الاحتياطي: {backup_error}"

        if not ai_reply:
            for key in offline_responses:
                if key.lower() in user_message.lower():
                    ai_reply = offline_responses[key]
                    break
            ai_reply = ai_reply or default_offline_response
            return jsonify({
                "reply": ai_reply,
                "conversation_id": conversation_id,
                "offline": True,
                "error": error_message
            }), 503 if error_message else 200

        db_conversation.add_message('assistant', ai_reply)
        db.session.commit()

        if len(messages) <= 2:
            db_conversation.title = user_message[:50] if len(user_message) > 20 else "محادثة جديدة"
            db.session.commit()

        return jsonify({
            "reply": ai_reply,
            "conversation_id": conversation_id,
            "backup_used": used_backup
        })

    except Exception as e:
        logger.error(f"Internal error: {e}")
        return jsonify({"error": f"حدث خطأ غير متوقع: {str(e)}"}), 500

# نقطة تشغيل التطبيق
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
