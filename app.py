# 
import logging
import requests
import json
import uuid
from datetime import datetime, timezone
from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import desc # لاستيراد desc
import google.generativeai as genai # استيراد مكتبة Gemini
from huggingface_hub import InferenceClient # استيراد مكتبة Hugging Face

# --- Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class Base(DeclarativeBase): pass

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key-change-me") # مفتاح سري

# --- Database Config ---
db_url = os.environ.get("DATABASE_URL")
if not db_url:
    logger.warning("DATABASE_URL not set. Using in-memory SQLite (not persistent).")
    db_url = "sqlite:///:memory:" # قاعدة بيانات مؤقتة للاختبار المحلي

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_recycle": 280, "pool_pre_ping": True}

db = SQLAlchemy(model_class=Base)
db.init_app(app)

# --- Import Models After db Initialization ---
# يجب أن يتم هذا الاستيراد بعد تعريف `db`
from models import Conversation, Message

# --- API Keys & Config ---
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
HUGGINGFACE_API_TOKEN = os.environ.get("HUGGINGFACE_API_TOKEN")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY") # احتياطي إضافي

# --- Configure AI Clients ---
if GOOGLE_API_KEY:
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        logger.info("Google Gemini API configured.")
    except Exception as e:
        logger.error(f"Failed to configure Google Gemini API: {e}")
        GOOGLE_API_KEY = None # تعطيل Gemini إذا فشل الإعداد
else:
    logger.warning("GOOGLE_API_KEY not found. Gemini API will not be used as primary.")

hf_client = None
if HUGGINGFACE_API_TOKEN:
    try:
        hf_client = InferenceClient(token=HUGGINGFACE_API_TOKEN)
        logger.info("Hugging Face Inference Client configured.")
    except Exception as e:
        logger.error(f"Failed to configure Hugging Face Client: {e}")
        HUGGINGFACE_API_TOKEN = None # تعطيله إذا فشل
else:
    logger.warning("HUGGINGFACE_API_TOKEN not found. Hugging Face API will not be used.")

# --- Offline Responses ---
offline_responses = { "السلام عليكم": "وعليكم السلام!", "كيف حالك": "بخير، شكراً لك!", "شكرا": "عفواً!" }
default_offline_response = "أعتذر، لا أستطيع المساعدة الآن. حاول مرة أخرى لاحقًا."

# --- Helper Functions for AI Calls ---

async def call_gemini_api_async(history):
    if not GOOGLE_API_KEY: return None, "Gemini API key not configured."
    logger.info("Attempting Gemini API call...")
    try:
        model = genAI.GenerativeModel('gemini-1.5-flash')
        # تحويل السجل إلى تنسيق Gemini (user/model)
        gemini_history = []
        system_prompt = "أنت ياسمين، مساعدة ذكية تتحدث العربية بطلاقة. كن ودودًا ومفيدًا ومختصرًا."
        for msg in history:
            role = "user" if msg["role"] == "user" else "model"
            gemini_history.append({"role": role, "parts": [{"text": msg["content"]}]})

        # إزالة آخر رسالة (رسالة المستخدم الحالية) من السجل
        current_message_content = gemini_history.pop()["parts"][0]["text"]

        chat = model.start_chat(history=gemini_history)
        response = await chat.send_message_async(
             [{"text": system_prompt}, {"text": current_message_content}], # إضافة رسالة النظام مع رسالة المستخدم
             generation_config=genai.types.GenerationConfig(
                 temperature=0.7, max_output_tokens=512
             ),
             safety_settings=[ # إعدادات السلامة
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
             ]
        )
        logger.info("Gemini API call successful.")
        return response.text, None
    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        # التحقق من أخطاء السلامة
        if hasattr(e, 'response') and hasattr(e.response, 'prompt_feedback') and e.response.prompt_feedback.block_reason:
             return None, f"تم حظر الرد بواسطة Gemini بسبب: {e.response.prompt_feedback.block_reason}"
        return None, f"خطأ في Gemini: {str(e)}"

async def call_huggingface_api_async(history):
    if not hf_client: return None, "Hugging Face client not configured."
    logger.info("Attempting Hugging Face API call...")
    try:
        # بناء prompt مناسب للنموذج
        system_prompt = "أنت ياسمين، مساعدة ذكية تتحدث العربية بطلاقة. كن ودودًا ومفيدًا ومختصرًا."
        prompt = f"<s>[INST] <<SYS>>\n{system_prompt}\n<</SYS>>\n\n"
        for i, msg in enumerate(history):
            if msg["role"] == "user":
                prompt += f"{msg['content']} [/INST]"
            elif msg["role"] == "assistant":
                 # إضافة استجابة المساعد السابقة قبل الـ INST التالي
                 if i < len(history) - 1 and history[i+1]["role"] == "user":
                     prompt += f" {msg['content']}</s><s>[INST]"
                 else: # إذا كانت آخر رسالة هي للمساعد (نادر، لكن للتحقق)
                     prompt += f" {msg['content']}" # لا نضيف INST بعدها

        # إضافة الرد المتوقع من ياسمين في النهاية (إذا كانت آخر رسالة من المستخدم)
        if history[-1]["role"] == "user":
             prompt += " Yasmin: " # أو أي صيغة يتوقعها النموذج

        # نموذج مجاني جيد للغة العربية
        model_id = "mistralai/Mistral-7B-Instruct-v0.1" # أو جرب "google/gemma-7b-it"
        logger.debug(f"HF Prompt (start): {prompt[:150]}...")

        response_iterator = hf_client.text_generation(
            prompt,
            model=model_id,
            max_new_tokens=300,
            temperature=0.7,
            top_p=0.95,
            repetition_penalty=1.1,
            return_full_text=False, # مهم للحصول على الرد فقط
            stream=False # تعطيل الدفق للحصول على الرد الكامل مرة واحدة
        )

        # بما أن stream=False، يجب أن يكون الرد هو النتيجة مباشرة
        ai_reply = response_iterator.strip() if isinstance(response_iterator, str) else ""


        if not ai_reply:
             # محاولة قراءة الخطأ إذا كان الكائن يحتوي عليه
             error_info = getattr(response_iterator, 'error', 'No response text.')
             logger.error(f"Hugging Face returned empty or invalid response: {error_info}")
             raise ValueError(f"Hugging Face response error: {error_info}")

        logger.info("Hugging Face API call successful.")
        return ai_reply, None
    except Exception as e:
        logger.error(f"Hugging Face API error: {e}")
        return None, f"خطأ في Hugging Face: {str(e)}"

async def call_deepseek_api_async(history):
    if not DEEPSEEK_API_KEY: return None, "Deepseek API key not configured."
    logger.info("Attempting Deepseek API call (Fallback)...")
    try:
        deepseek_messages = [{"role": msg["role"], "content": msg["content"]} for msg in history]
        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
            json={"model": "deepseek-chat", "messages": deepseek_messages, "temperature": 0.7, "max_tokens": 500},
            timeout=25 # مهلة أقصر
        )
        response.raise_for_status()
        data = response.json()
        reply = data.choices[0]['message']['content'].strip()
        logger.info("Deepseek API call successful.")
        return reply, None
    except Exception as e:
        logger.error(f"Deepseek API error: {e}")
        return None, f"خطأ في Deepseek: {str(e)}"

# --- Flask Routes ---

@app.route('/')
def index():
    """Renders the main chat page."""
    return render_template('index.html', app_title="ياسمين GPT")

@app.route('/static/<path:filename>')
def static_files(filename):
    """Serves static files."""
    return send_from_directory('static', filename)

@app.route('/api/chat', methods=['POST'])
async def chat():
    """Handles chat messages, interacts with AI, and stores conversation."""
    try:
        data = request.json
        user_message_content = data.get('message')
        conversation_id = data.get('conversation_id') # قد يكون null لمحادثة جديدة

        if not user_message_content:
            return jsonify({"error": "الرسالة فارغة"}), 400

        # --- Conversation Handling ---
        if conversation_id:
            db_conversation = db.session.execute(db.select(Conversation).filter_by(id=conversation_id)).scalar_one_or_none()
            if not db_conversation:
                # إذا لم يتم العثور على ID، أنشئ محادثة جديدة
                logger.warning(f"Conversation ID {conversation_id} not found, creating new.")
                conversation_id = None # لإجبار إنشاء محادثة جديدة أدناه
            else:
                 # جلب آخر N رسالة للسياق
                 history_limit = 10
                 db_messages = db.session.execute(
                     db.select(Message)
                     .filter_by(conversation_id=conversation_id)
                     .order_by(Message.created_at.desc())
                     .limit(history_limit)
                 ).scalars().all()
                 # عكس الترتيب ليكون الأقدم أولاً
                 history = [{"role": msg.role, "content": msg.content} for msg in reversed(db_messages)]
        else:
            db_conversation = None
            history = []

        if not db_conversation:
            conversation_id = str(uuid.uuid4())
            title = user_message_content[:30] + ('...' if len(user_message_content) > 30 else '')
            db_conversation = Conversation(id=conversation_id, title=title)
            db.session.add(db_conversation)
            # لا تقم بعمل commit هنا بعد، انتظر حتى يتم إضافة رسالة المستخدم والرد

        # إضافة رسالة المستخدم للسجل المؤقت ولقاعدة البيانات
        history.append({"role": "user", "content": user_message_content})
        user_db_message = db_conversation.add_message('user', user_message_content)
        db.session.add(user_db_message) # إضافة الرسالة للجلسة

        # --- AI Call Logic ---
        ai_reply = None
        error_message = None
        provider_used = "Offline"

        # 1. Try Google Gemini (if key exists)
        if GOOGLE_API_KEY:
            ai_reply, error_message = await call_gemini_api_async(history)
            if ai_reply: provider_used = "Google Gemini"

        # 2. Try Hugging Face (if Gemini failed/no key, and HF key exists)
        if not ai_reply and HUGGINGFACE_API_TOKEN:
            ai_reply, error_message = await call_huggingface_api_async(history)
            if ai_reply: provider_used = "Hugging Face"

        # 3. Try Deepseek (if both failed/no keys, and Deepseek key exists)
        if not ai_reply and DEEPSEEK_API_KEY:
             ai_reply, error_message = await call_deepseek_api_async(history)
             if ai_reply: provider_used = "Deepseek"

        # 4. Use Offline Response if all APIs failed or no keys
        if not ai_reply:
            logger.warning(f"All API attempts failed or no keys configured. Using offline response. Last error: {error_message}")
            # البحث عن رد مناسب في القاموس
            matched_offline = False
            for key, response in offline_responses.items():
                if key.lower() in user_message_content.lower():
                    ai_reply = response
                    matched_offline = True
                    break
            if not matched_offline:
                ai_reply = default_offline_response

            # إضافة رسالة الخطأ (إذا وجدت) ورسالة الرد الثابت
            if error_message:
                 error_db_msg = db_conversation.add_message('error', f"خطأ في الاتصال بالـ API: {error_message}")
                 db.session.add(error_db_msg)
            ai_db_message = db_conversation.add_message('assistant', ai_reply)
            db.session.add(ai_db_message)
            db.session.commit() # حفظ كل شيء الآن
            return jsonify({
                "reply": ai_reply, "conversation_id": conversation_id,
                "offline": True, "error": error_message or "No API available."
            }), 503 # Service Unavailable

        # --- Store AI reply and commit ---
        ai_db_message = db_conversation.add_message('assistant', ai_reply)
        db.session.add(ai_db_message)
        db.session.commit() # حفظ رسالة المستخدم، رسالة الرد، وتحديث المحادثة

        logger.info(f"Successfully generated reply using {provider_used}.")
        return jsonify({"reply": ai_reply, "conversation_id": conversation_id})

    except Exception as e:
        db.session.rollback() # التراجع عن أي تغييرات في قاعدة البيانات عند حدوث خطأ فادح
        logger.exception("Critical error in /api/chat endpoint.") # تسجيل الخطأ مع traceback
        return jsonify({"error": f"حدث خطأ داخلي خطير: {str(e)}"}), 500

@app.route('/api/conversations', methods=['GET'])
def list_conversations():
    """Lists all conversations, ordered by last updated."""
    try:
        conversations_list = db.session.execute(
            db.select(Conversation).order_by(desc(Conversation.updated_at))
        ).scalars().all()
        return jsonify({"conversations": [conv.to_dict() for conv in conversations_list]})
    except Exception as e:
        logger.error(f"Error listing conversations: {e}")
        return jsonify({"error": "فشل جلب المحادثات"}), 500

@app.route('/api/conversations/<conversation_id>', methods=['GET'])
def get_conversation(conversation_id):
    """Gets a specific conversation and its messages."""
    try:
        db_conversation = db.session.execute(
            db.select(Conversation).filter_by(id=conversation_id)
        ).scalar_one_or_none()

        if not db_conversation:
            return jsonify({"error": "المحادثة غير موجودة"}), 404

        # استخدام include_messages=True لجلب الرسائل مع المحادثة
        return jsonify(db_conversation.to_dict(include_messages=True))
    except Exception as e:
        logger.error(f"Error fetching conversation {conversation_id}: {e}")
        return jsonify({"error": "فشل جلب تفاصيل المحادثة"}), 500

@app.route('/api/conversations/<conversation_id>', methods=['DELETE'])
def delete_conversation(conversation_id):
    """Deletes a conversation and its messages."""
    try:
        db_conversation = db.session.execute(
            db.select(Conversation).filter_by(id=conversation_id)
        ).scalar_one_or_none()

        if not db_conversation:
            return jsonify({"error": "المحادثة غير موجودة"}), 404

        db.session.delete(db_conversation)
        db.session.commit()
        logger.info(f"Deleted conversation {conversation_id}")
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting conversation {conversation_id}: {e}")
        return jsonify({"error": "فشل حذف المحادثة"}), 500

# ==============================================================
