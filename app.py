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
from huggingface_hub.inference._text_generation import TextGenerationError
from dotenv import load_dotenv

# --- Setup ---
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class Base(DeclarativeBase): pass
db = SQLAlchemy(model_class=Base) # تعريف db هنا

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key-change-me")

# --- Database Config ---
db_url = os.environ.get("DATABASE_URL")
if not db_url:
    logger.error("FATAL: DATABASE_URL environment variable is not set.")
    exit("Database URL is required.")

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_recycle": 280, "pool_pre_ping": True}

db.init_app(app) # تهيئة db مع التطبيق

# --- Import Models After db Initialization ---
# يجب أن يتم هذا الاستيراد بعد db.init_app(app)
from models import Conversation, Message

# --- API Keys & Config ---
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
HUGGINGFACE_API_TOKEN = os.environ.get("HUGGINGFACE_API_TOKEN")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")

# --- Configure AI Clients ---
gemini_model = None
if GOOGLE_API_KEY:
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        gemini_model = genai.GenerativeModel('gemini-1.5-flash')
        logger.info("Google Gemini API configured successfully.")
    except Exception as e:
        logger.error(f"Failed to configure Google Gemini API: {e}")
        GOOGLE_API_KEY = None
else:
    logger.warning("GOOGLE_API_KEY not found. Gemini will not be the primary API.")

hf_client = None
DEFAULT_HF_MODEL = "mistralai/Mistral-7B-Instruct-v0.1"
if HUGGINGFACE_API_TOKEN:
    try:
        hf_client = InferenceClient(token=HUGGINGFACE_API_TOKEN)
        logger.info(f"Hugging Face Inference Client configured (default model: {DEFAULT_HF_MODEL}).")
    except Exception as e:
        logger.error(f"Failed to configure Hugging Face Client: {e}")
        HUGGINGFACE_API_TOKEN = None
else:
    logger.warning("HUGGINGFACE_API_TOKEN not found. Hugging Face API will not be used.")

# --- Offline Responses ---
offline_responses = { "السلام عليكم": "وعليكم السلام!", "كيف حالك": "بخير، شكراً لك!", "شكرا": "عفواً!" }
default_offline_response = "أعتذر، لا أستطيع المساعدة الآن. قد تكون هناك مشكلة في الاتصال بخدمات الذكاء الاصطناعي."

# --- Helper Functions for AI Calls (Synchronous) ---

def call_gemini_api(history, temperature, max_tokens):
    if not gemini_model: return None, "Gemini API not configured."
    logger.info("Attempting Gemini API call...")
    try:
        gemini_history = []
        system_prompt = "أنت ياسمين، مساعدة ذكية تتحدث العربية بطلاقة. كن ودودًا ومفيدًا ومختصرًا."
        for msg in history:
            role = "user" if msg["role"] == "user" else "model"
            gemini_history.append({"role": role, "parts": [{"text": msg["content"]}]})
        current_message_parts = gemini_history.pop()["parts"]
        chat = gemini_model.start_chat(history=gemini_history)
        response = chat.send_message(
             [{"text": system_prompt}, *current_message_parts],
             generation_config=genai.types.GenerationConfig(temperature=temperature, max_output_tokens=max_tokens),
             safety_settings=[{"category": c, "threshold": "BLOCK_MEDIUM_AND_ABOVE"} for c in genai.types.HarmCategory] # تبسيط إعدادات السلامة
        )
        logger.info("Gemini API call successful.")
        if response.text: return response.text, None
        else:
            block_reason = response.prompt_feedback.block_reason if response.prompt_feedback else "Unknown"
            logger.warning(f"Gemini response blocked. Reason: {block_reason}.")
            return None, f"تم حظر الرد بواسطة Gemini (السبب: {block_reason})"
    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        error_detail = str(e)
        if "API key not valid" in error_detail: return None, "مفتاح Google API غير صالح."
        if "SAFETY" in error_detail: return None, "تم حظر الرد بسبب إعدادات السلامة."
        return None, f"خطأ في Gemini: {error_detail}"

def call_huggingface_api(history, model_id, temperature, max_tokens):
    if not hf_client: return None, "Hugging Face client not configured."
    logger.info(f"Attempting Hugging Face API call (Model: {model_id})...")
    try:
        system_prompt = "أنت ياسمين، مساعدة ذكية تتحدث العربية بطلاقة. كن ودودًا ومفيدًا ومختصرًا."
        prompt = f"<s>[INST] <<SYS>>\n{system_prompt}\n<</SYS>>\n\n"
        for i, msg in enumerate(history):
            if i == len(history) - 1 and msg["role"] == "user": prompt += f"{msg['content']} [/INST]"
            elif msg["role"] == "assistant": prompt += f" {msg['content']}</s><s>[INST]"
            elif msg["role"] == "user": prompt += f"{msg['content']} [/INST]"
        if history[-1]["role"] == "user": prompt += " Yasmin: "
        logger.debug(f"HF Prompt (start): {prompt[:150]}...")
        response_text = hf_client.text_generation(
            prompt, model=model_id, max_new_tokens=max_tokens,
            temperature=temperature if temperature > 0.01 else None, # Temp must be > 0
            top_p=0.95, repetition_penalty=1.1, return_full_text=False
        )
        ai_reply = response_text.strip() if isinstance(response_text, str) else ""
        if not ai_reply: raise ValueError("Hugging Face returned empty response.")
        logger.info("Hugging Face API call successful.")
        return ai_reply, None
    except TextGenerationError as e:
        logger.error(f"Hugging Face Text Generation Error: {e}")
        error_msg = f"خطأ في Hugging Face: {e}"
        if "Rate limit reached" in str(e): error_msg = "تم تجاوز حد الطلبات لـ Hugging Face."
        elif "Model is overloaded" in str(e) or "currently loading" in str(e): error_msg = f"النموذج {model_id} مشغول أو قيد التحميل. حاول لاحقًا."
        return None, error_msg
    except Exception as e:
        logger.error(f"Hugging Face API general error: {e}")
        return None, f"خطأ في Hugging Face: {str(e)}"

def call_deepseek_api(history):
    if not DEEPSEEK_API_KEY: return None, "Deepseek API key not configured."
    logger.info("Attempting Deepseek API call (Fallback)...")
    try:
        deepseek_messages = [{"role": msg["role"], "content": msg["content"]} for msg in history]
        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
            json={"model": "deepseek-chat", "messages": deepseek_messages, "temperature": 0.7, "max_tokens": 500},
            timeout=25
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
    return render_template('index.html', app_title="ياسمين GPT")

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

@app.route('/api/chat', methods=['POST'])
def chat(): # Synchronous route
    try:
        data = request.json
        user_message_content = data.get('message')
        history_from_frontend = data.get('history', [])
        conversation_id = data.get('conversation_id')
        model_requested = data.get('model', DEFAULT_HF_MODEL)
        temperature = data.get('temperature', 0.7)
        max_tokens = data.get('max_tokens', 512)

        if not user_message_content: return jsonify({"error": "الرسالة فارغة"}), 400

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

        user_db_message = db_conversation.add_message('user', user_message_content)
        db.session.add(user_db_message)
        full_history_for_api = history_from_frontend + [{"role": "user", "content": user_message_content}]

        # --- AI Call Logic (Synchronous) ---
        ai_reply, error_message, provider_used = None, None, "Offline"

        if GOOGLE_API_KEY:
            ai_reply, error_message = call_gemini_api(full_history_for_api, temperature, max_tokens)
            if ai_reply: provider_used = "Google Gemini"
        if not ai_reply and HUGGINGFACE_API_TOKEN:
            hf_model_to_use = model_requested if model_requested.startswith(('mistralai/', 'google/', 'meta-llama/')) else DEFAULT_HF_MODEL
            ai_reply, error_message = call_huggingface_api(full_history_for_api, hf_model_to_use, temperature, max_tokens)
            if ai_reply: provider_used = f"Hugging Face ({hf_model_to_use})"
        if not ai_reply and DEEPSEEK_API_KEY:
             ai_reply, error_message = call_deepseek_api(full_history_for_api)
             if ai_reply: provider_used = "Deepseek"

        if not ai_reply:
            logger.warning(f"All API attempts failed. Using offline response. Last error: {error_message}")
            matched_offline = False
            for key, response in offline_responses.items():
                if key.lower() in user_message_content.lower(): ai_reply = response; matched_offline = True; break
            if not matched_offline: ai_reply = default_offline_response
            if error_message: db.session.add(db_conversation.add_message('error', f"خطأ API: {error_message}"))
            db.session.add(db_conversation.add_message('assistant', ai_reply))
            db.session.commit()
            return jsonify({ "reply": ai_reply, "conversation_id": conversation_id, "offline": True, "error": error_message or "No API available." }), 503

        # --- Store AI reply and commit ---
        db.session.add(db_conversation.add_message('assistant', ai_reply))
        db.session.commit()
        logger.info(f"Successfully generated reply using {provider_used}.")
        return jsonify({"reply": ai_reply, "conversation_id": conversation_id})

    except Exception as e:
        db.session.rollback()
        logger.exception("Critical error in /api/chat endpoint.")
        return jsonify({"error": f"حدث خطأ داخلي خطير: {str(e)}"}), 500

@app.route('/api/conversations', methods=['GET'])
def list_conversations_route():
    try:
        conversations_list = db.session.execute(db.select(Conversation).order_by(desc(Conversation.updated_at))).scalars().all()
        return jsonify({"conversations": [conv.to_dict() for conv in conversations_list]})
    except Exception as e:
        logger.error(f"Error listing conversations: {e}")
        return jsonify({"error": "فشل جلب المحادثات"}), 500

@app.route('/api/conversations/<conversation_id>', methods=['GET'])
def get_conversation_route(conversation_id):
    try:
        db_conversation = db.session.execute(db.select(Conversation).filter_by(id=conversation_id)).scalar_one_or_none()
        if not db_conversation: return jsonify({"error": "المحادثة غير موجودة"}), 404
        return jsonify(db_conversation.to_dict(include_messages=True))
    except Exception as e:
        logger.error(f"Error fetching conversation {conversation_id}: {e}")
        return jsonify({"error": "فشل جلب تفاصيل المحادثة"}), 500

@app.route('/api/conversations/<conversation_id>', methods=['DELETE'])
def delete_conversation_route(conversation_id):
    try:
        db_conversation = db.session.execute(db.select(Conversation).filter_by(id=conversation_id)).scalar_one_or_none()
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
    logger.exception("An unhandled exception occurred")
    # تفاصيل الخطأ قد تكون حساسة في الإنتاج
    error_message = str(e) if app.debug else "حدث خطأ داخلي في الخادم."
    return jsonify(error=error_message), 500

# لا تقم بتضمين app.run() هنا إذا كنت ستستخدم Gunicorn أو main.py
# if __name__ == '__main__':
#     app.run(host='0.0.0.0', port=5000, debug=True)
