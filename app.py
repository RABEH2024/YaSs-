import os
import logging
import requests
import json
import uuid
from datetime import datetime, timezone
from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import desc
import google.generativeai as genai
from huggingface_hub import InferenceClient, HfApi
from huggingface_hub.inference._text_generation import TextGenerationError # لاستيراد الخطأ المحدد
from dotenv import load_dotenv

# --- Setup ---
load_dotenv() # تحميل متغيرات البيئة من ملف .env

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class Base(DeclarativeBase): pass

# تعريف db هنا ليتم استيراده في models.py
db = SQLAlchemy(model_class=Base)

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.environ.get("SESSION_SECRET", "a-very-secret-key-for-dev")

# --- Database Config ---
db_url = os.environ.get("DATABASE_URL")
if not db_url:
    logger.error("FATAL: DATABASE_URL environment variable is not set.")
    # في بيئة الإنتاج، يجب أن يتوقف التطبيق هنا
    # For local testing without Render DB, uncomment the line below:
    # db_url = "sqlite:///./local_yasmin.db"
    # logger.warning("Using local SQLite database (local_yasmin.db).")
    # يمكنك إيقاف التطبيق إذا كنت تريد فرض وجود قاعدة بيانات في الإنتاج
    exit("Database URL is required.")


app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_recycle": 280, "pool_pre_ping": True}

db.init_app(app)

# --- Import Models After db Initialization ---
from models import Conversation, Message

# --- API Keys & Config ---
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
HUGGINGFACE_API_TOKEN = os.environ.get("HUGGINGFACE_API_TOKEN")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY") # احتياطي إضافي

# --- Configure AI Clients ---
gemini_model = None
if GOOGLE_API_KEY:
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        gemini_model = genai.GenerativeModel('gemini-1.5-flash')
        logger.info("Google Gemini API configured successfully.")
    except Exception as e:
        logger.error(f"Failed to configure Google Gemini API: {e}")
        GOOGLE_API_KEY = None # تعطيله إذا فشل الإعداد
else:
    logger.warning("GOOGLE_API_KEY not found. Gemini will not be the primary API.")

hf_client = None
# نماذج مقترحة لـ Hugging Face (يمكن تغييرها)
# تأكد من أن النموذج يدعم text-generation أو conversational
DEFAULT_HF_MODEL = "mistralai/Mistral-7B-Instruct-v0.1"
# DEFAULT_HF_MODEL = "google/gemma-7b-it" # بديل آخر
if HUGGINGFACE_API_TOKEN:
    try:
        hf_client = InferenceClient(token=HUGGINGFACE_API_TOKEN)
        # اختبار بسيط للاتصال (اختياري)
        # hf_api = HfApi()
        # hf_api.whoami(token=HUGGINGFACE_API_TOKEN)
        logger.info(f"Hugging Face Inference Client configured (default model: {DEFAULT_HF_MODEL}).")
    except Exception as e:
        logger.error(f"Failed to configure Hugging Face Client: {e}")
        HUGGINGFACE_API_TOKEN = None
else:
    logger.warning("HUGGINGFACE_API_TOKEN not found. Hugging Face API will not be used.")

# --- Offline Responses ---
offline_responses = { "السلام عليكم": "وعليكم السلام!", "كيف حالك": "بخير، شكراً لك!", "شكرا": "عفواً!" }
default_offline_response = "أعتذر، لا أستطيع المساعدة الآن. قد تكون هناك مشكلة في الاتصال بخدمات الذكاء الاصطناعي."

# --- Helper Functions for AI Calls ---

async def call_gemini_api_async(history, temperature, max_tokens):
    if not gemini_model: return None, "Gemini API not configured."
    logger.info("Attempting Gemini API call...")
    try:
        gemini_history = []
        system_prompt = "أنت ياسمين، مساعدة ذكية تتحدث العربية بطلاقة. كن ودودًا ومفيدًا ومختصرًا."
        # تحويل السجل لتنسيق Gemini (user/model) وفصل رسالة النظام
        for msg in history:
            role = "user" if msg["role"] == "user" else "model"
            gemini_history.append({"role": role, "parts": [{"text": msg["content"]}]})

        # آخر رسالة هي رسالة المستخدم الحالية
        current_message_parts = gemini_history.pop()["parts"]

        chat = gemini_model.start_chat(history=gemini_history)
        response = await chat.send_message_async(
             [{"text": system_prompt}, *current_message_parts], # إضافة رسالة النظام مع رسالة المستخدم
             generation_config=genai.types.GenerationConfig(
                 temperature=temperature, max_output_tokens=max_tokens
             ),
             safety_settings=[ # إعدادات السلامة
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
             ]
        )
        logger.info("Gemini API call successful.")
        # التحقق من وجود محتوى قبل إرجاعه
        if response.text:
            return response.text, None
        else:
            # التحقق من سبب الحظر
            block_reason = response.prompt_feedback.block_reason if response.prompt_feedback else "Unknown"
            safety_ratings = response.candidates[0].safety_ratings if response.candidates else "N/A"
            logger.warning(f"Gemini response blocked. Reason: {block_reason}. Ratings: {safety_ratings}")
            return None, f"تم حظر الرد بواسطة Gemini (السبب: {block_reason})"

    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        error_detail = str(e)
        if "API key not valid" in error_detail: return None, "مفتاح Google API غير صالح."
        if "SAFETY" in error_detail: return None, "تم حظر الرد بسبب إعدادات السلامة."
        return None, f"خطأ في Gemini: {error_detail}"

async def call_huggingface_api_async(history, model_id, temperature, max_tokens):
    if not hf_client: return None, "Hugging Face client not configured."
    logger.info(f"Attempting Hugging Face API call (Model: {model_id})...")
    try:
        system_prompt = "أنت ياسمين، مساعدة ذكية تتحدث العربية بطلاقة. كن ودودًا ومفيدًا ومختصرًا."
        # بناء prompt مناسب لنموذج Instruct
        prompt = f"<s>[INST] <<SYS>>\n{system_prompt}\n<</SYS>>\n\n"
        for i, msg in enumerate(history):
             # إضافة رسالة المستخدم الحالية في النهاية
            if i == len(history) - 1 and msg["role"] == "user":
                 prompt += f"{msg['content']} [/INST]"
            # إضافة رد المساعد السابق
            elif msg["role"] == "assistant":
                 prompt += f" {msg['content']}</s><s>[INST]"
            # إضافة رسالة مستخدم سابقة
            elif msg["role"] == "user":
                 prompt += f"{msg['content']} [/INST]"


        logger.debug(f"HF Prompt (start): {prompt[:150]}...")

        # استخدام text_generation مباشرة
        response_text = hf_client.text_generation(
            prompt,
            model=model_id,
            max_new_tokens=max_tokens,
            temperature=temperature if temperature > 0 else None, # Temperature must be > 0 for HF
            top_p=0.95,
            repetition_penalty=1.1,
            return_full_text=False,
            # لا يوجد signal في الإصدار الحالي من مكتبة HF Hub، نعتمد على timeout الخادم
        )

        ai_reply = response_text.strip() if isinstance(response_text, str) else ""

        if not ai_reply:
            logger.error(f"Hugging Face returned empty response for model {model_id}.")
            raise ValueError("Hugging Face returned empty response.")

        logger.info("Hugging Face API call successful.")
        return ai_reply, None
    except TextGenerationError as e: # التعامل مع خطأ HF المحدد
        logger.error(f"Hugging Face Text Generation Error: {e}")
        error_msg = f"خطأ في Hugging Face: {e}"
        if "Rate limit reached" in str(e):
            error_msg = "تم تجاوز حد الطلبات لـ Hugging Face. حاول لاحقًا."
        elif "Model is overloaded" in str(e):
             error_msg = f"النموذج {model_id} مشغول حاليًا. حاول لاحقًا أو اختر نموذجًا آخر."
        return None, error_msg
    except Exception as e:
        logger.error(f"Hugging Face API general error: {e}")
        return None, f"خطأ في Hugging Face: {str(e)}"

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
        user_message_content = data.get('message') # الرسالة الجديدة من المستخدم
        history_from_frontend = data.get('history', []) # السجل من الواجهة الأمامية
        conversation_id = data.get('conversation_id')
        model_requested = data.get('model', DEFAULT_HF_MODEL) # النموذج المطلوب
        temperature = data.get('temperature', 0.7)
        max_tokens = data.get('max_tokens', 512)

        if not user_message_content:
            return jsonify({"error": "الرسالة فارغة"}), 400

        # --- Conversation Handling ---
        db_conversation = None
        if conversation_id:
            db_conversation = db.session.execute(db.select(Conversation).filter_by(id=conversation_id)).scalar_one_or_none()
            if not db_conversation:
                logger.warning(f"Conversation ID {conversation_id} not found, creating new.")
                conversation_id = None

        if not conversation_id:
            conversation_id = str(uuid.uuid4())
            title = user_message_content[:30] + ('...' if len(user_message_content) > 30 else '')
            db_conversation = Conversation(id=conversation_id, title=title)
            db.session.add(db_conversation)

        # إضافة رسالة المستخدم لقاعدة البيانات (commit لاحقًا)
        user_db_message = db_conversation.add_message('user', user_message_content)
        db.session.add(user_db_message)

        # بناء السجل الكامل للـ API (بما في ذلك الرسالة الحالية)
        full_history_for_api = history_from_frontend + [{"role": "user", "content": user_message_content}]

        # --- AI Call Logic ---
        ai_reply = None
        error_message = None
        provider_used = "Offline"

        # 1. Try Google Gemini (if key exists)
        if GOOGLE_API_KEY:
            ai_reply, error_message = await call_gemini_api_async(full_history_for_api, temperature, max_tokens)
            if ai_reply: provider_used = "Google Gemini"

        # 2. Try Hugging Face (if Gemini failed/no key, and HF key exists)
        if not ai_reply and HUGGINGFACE_API_TOKEN:
            # استخدام النموذج المطلوب من الواجهة أو الافتراضي
            hf_model_to_use = model_requested if model_requested.startswith(('mistralai/', 'google/', 'meta-llama/')) else DEFAULT_HF_MODEL
            ai_reply, error_message = await call_huggingface_api_async(full_history_for_api, hf_model_to_use, temperature, max_tokens)
            if ai_reply: provider_used = f"Hugging Face ({hf_model_to_use})"

        # 3. Try Deepseek (Fallback if others failed/unavailable)
        if not ai_reply and DEEPSEEK_API_KEY:
             ai_reply, error_message = await call_deepseek_api_async(full_history_for_api) # Deepseek قد لا يدعم T/max_tokens
             if ai_reply: provider_used = "Deepseek"

        # 4. Use Offline Response if all APIs failed or no keys
        if not ai_reply:
            logger.warning(f"All API attempts failed or no keys configured. Using offline response. Last error: {error_message}")
            matched_offline = False
            for key, response in offline_responses.items():
                if key.lower() in user_message_content.lower():
                    ai_reply = response; matched_offline = True; break
            if not matched_offline: ai_reply = default_offline_response

            if error_message:
                 error_db_msg = db_conversation.add_message('error', f"خطأ API: {error_message}")
                 db.session.add(error_db_msg)
            ai_db_message = db_conversation.add_message('assistant', ai_reply)
            db.session.add(ai_db_message)
            db.session.commit()
            return jsonify({ "reply": ai_reply, "conversation_id": conversation_id, "offline": True, "error": error_message or "No API available." }), 503

        # --- Store AI reply and commit ---
        ai_db_message = db_conversation.add_message('assistant', ai_reply)
        db.session.add(ai_db_message)
        db.session.commit()

        logger.info(f"Successfully generated reply using {provider_used}.")
        return jsonify({"reply": ai_reply, "conversation_id": conversation_id})

    except Exception as e:
        db.session.rollback()
        logger.exception("Critical error in /api/chat endpoint.")
        return jsonify({"error": f"حدث خطأ داخلي خطير: {str(e)}"}), 500

@app.route('/api/conversations', methods=['GET'])
def list_conversations_route():
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
def get_conversation_route(conversation_id):
    """Gets a specific conversation and its messages."""
    try:
        db_conversation = db.session.execute(
            db.select(Conversation).filter_by(id=conversation_id)
        ).scalar_one_or_none()
        if not db_conversation: return jsonify({"error": "المحادثة غير موجودة"}), 404
        return jsonify(db_conversation.to_dict(include_messages=True))
    except Exception as e:
        logger.error(f"Error fetching conversation {conversation_id}: {e}")
        return jsonify({"error": "فشل جلب تفاصيل المحادثة"}), 500

@app.route('/api/conversations/<conversation_id>', methods=['DELETE'])
def delete_conversation_route(conversation_id):
    """Deletes a conversation and its messages."""
    try:
        db_conversation = db.session.execute(
            db.select(Conversation).filter_by(id=conversation_id)
        ).scalar_one_or_none()
        if not db_conversation: return jsonify({"error": "المحادثة غير موجودة"}), 404
        db.session.delete(db_conversation)
        db.session.commit()
        logger.info(f"Deleted conversation {conversation_id}")
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting conversation {conversation_id}: {e}")
        return jsonify({"error": "فشل حذف المحادثة"}), 500

# --- Error Handler ---
@app.errorhandler(Exception)
def handle_exception(e):
    """Global error handler."""
    logger.exception("An unhandled exception occurred") # Log the full traceback
    # في بيئة الإنتاج، قد ترغب في إخفاء تفاصيل الخطأ
    # return jsonify(error="حدث خطأ داخلي في الخادم."), 500
    return jsonify(error=str(e)), 500


====================================
