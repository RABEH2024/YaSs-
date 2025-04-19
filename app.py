# --- START OF REFACTORED app.py ---
import os
import logging
import requests
import json
import uuid
import re # For email validation
from datetime import datetime
from functools import wraps

from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

# --- Basic Setup ---
# Use INFO level for production, DEBUG for development
# Consider configuring logging further (e.g., file output)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Base Class for SQLAlchemy models ---
# Define Base before db if using this pattern
class Base(DeclarativeBase):
    pass

# --- Initialize Flask ---
app = Flask(__name__)

# --- Configuration ---
# IMPORTANT: Use a strong, unique secret key stored in environment variables for production
app.secret_key = os.environ.get("SESSION_SECRET")
if not app.secret_key:
    logger.critical("FATAL: SESSION_SECRET environment variable is not set. Application cannot run securely.")
    # In a real deployment, you might exit here or raise a critical error
    # For now, we'll let it potentially run with a default (unsafe) key if the code below sets one.
    app.secret_key = "unsafe-default-key-please-set-session-secret"


# Get API keys from environment variables
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not OPENROUTER_API_KEY:
    logger.warning("OPENROUTER_API_KEY environment variable not set. OpenRouter API will not be available.")
if not GEMINI_API_KEY:
    logger.warning("GEMINI_API_KEY environment variable not set. Gemini API backup will not be available.")

# Other app configurations
APP_URL = os.environ.get("APP_URL")
if not APP_URL:
     logger.warning("APP_URL environment variable not set. Defaulting to http://localhost:5000.")
     APP_URL = "http://localhost:5000"

APP_TITLE = "Yasmin GPT Chat" # App name for OpenRouter

# Configure the SQLAlchemy database
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    logger.error("DATABASE_URL environment variable not set. Defaulting to SQLite database 'yasmin_chat_local.db'. USER DATA WILL BE LOST ON RESTART/REDEPLOY ON RENDER.")
    # Use a different name to avoid conflict if an old one exists
    DATABASE_URL = "sqlite:///yasmin_chat_local.db"

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 280, # Recycle connections periodically
    "pool_pre_ping": True, # Check connection validity before use
}
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# --- Initialize Database Extension ---
# Define db using the Base class BEFORE defining models that use it
db = SQLAlchemy(model_class=Base)

# --- Model Definitions ---
# Define models AFTER db is created, inheriting from db.Model

class User(UserMixin, db.Model):
    __tablename__ = "users" # Explicit table name recommended
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    # Increased length for modern hash algorithms (e.g., Argon2, scrypt)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password) # Uses strong default method

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # get_id is provided by UserMixin

    def __repr__(self):
        admin_status = "Admin" if self.is_admin else "User"
        return f'<User {self.id}: {self.username} ({admin_status})>'

    def to_dict(self): # Added for potential API use
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "is_admin": self.is_admin,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class Conversation(db.Model):
    __tablename__ = "conversations"
    # Use String for UUID primary key
    id = db.Column(db.String(36), primary_key=True)
    title = db.Column(db.String(100), nullable=False, default="محادثة جديدة")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    # Relationship to Messages - use lazy='dynamic' for querying, cascade deletes
    messages = db.relationship("Message", backref="conversation", lazy='dynamic', cascade="all, delete-orphan")

    def add_message(self, role, content):
        """Helper method to add a message and update timestamp."""
        message = Message(conversation_id=self.id, role=role, content=content)
        db.session.add(message)
        # Explicitly set updated_at when adding related object
        self.updated_at = datetime.utcnow()
        db.session.add(self) # Mark conversation itself as dirty
        return message

    def get_ordered_messages(self):
        """Returns messages ordered by creation time."""
        return self.messages.order_by(Message.created_at.asc()).all()

    def to_dict(self):
        ordered_messages = self.get_ordered_messages()
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            # Ensure messages are included in dict
            "messages": [msg.to_dict() for msg in ordered_messages]
        }

    def __repr__(self):
        return f'<Conversation {self.id} - "{self.title}">'

class Message(db.Model):
    __tablename__ = "messages"
    id = db.Column(db.Integer, primary_key=True)
    # Ensure ondelete='CASCADE' works with your DB (usually does)
    conversation_id = db.Column(db.String(36), db.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False)  # 'user' or 'assistant'
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    def to_dict(self):
        return {
            "id": self.id, # Good to include message ID
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f'<Message {self.id} ({self.role}) in Conv {self.conversation_id}>'


# --- Initialize Extensions with App ---
# Call init_app AFTER models are defined and app is configured
db.init_app(app)

# Initialize Flask-Login AFTER User model is defined and app is configured
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'admin_login' # Redirect non-logged-in users to this view
login_manager.login_message = 'يرجى تسجيل الدخول للوصول إلى هذه الصفحة الإدارية.'
login_manager.login_message_category = 'warning'

# --- Flask-Login User Loader ---
@login_manager.user_loader
def load_user(user_id):
    """Loads user object from user ID stored in session."""
    try:
        # Use db.session.get for primary key lookups (more efficient)
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        logger.error(f"Invalid user_id type in session: {user_id}")
        return None

# --- Decorators ---
def admin_required(f):
    """Decorator to require admin privileges for a route."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return login_manager.unauthorized() # Standard Flask-Login handling
        # Check if user object has is_admin attr and if it's True
        if not getattr(current_user, 'is_admin', False):
            flash('غير مصرح لك بالوصول إلى هذه الصفحة. صلاحيات المدير مطلوبة.', 'danger')
            return redirect(url_for('index')) # Redirect non-admins away
        return f(*args, **kwargs)
    return decorated_function

# --- Helper Functions & Data ---

# Yasmin's offline responses (keep these)
offline_responses = {
    "السلام عليكم": "وعليكم السلام! أنا ياسمين. للأسف، لا يوجد اتصال بالإنترنت حاليًا.",
    "كيف حالك": "أنا بخير شكراً لك. لكن لا يمكنني الوصول للنماذج الذكية الآن بسبب انقطاع الإنترنت.",
    "مرحبا": "أهلاً بك! أنا ياسمين. أعتذر، خدمة الإنترنت غير متوفرة حالياً.",
    "شكرا": "على الرحب والسعة! أتمنى أن يعود الاتصال قريباً.",
    "مع السلامة": "إلى اللقاء! آمل أن أتمكن من مساعدتك بشكل أفضل عند عودة الإنترنت."
}
default_offline_response = "أعتذر، لا يمكنني معالجة طلبك الآن. يبدو أن هناك مشكلة في الاتصال بالإنترنت أو أن النماذج غير متاحة حالياً."

def call_gemini_api(prompt_messages, max_tokens=512, temperature=0.7):
    """Calls the Google Gemini API (requires GEMINI_API_KEY)."""
    if not GEMINI_API_KEY:
        logger.warning("Gemini API key not configured. Skipping Gemini call.")
        return None, "مفتاح Gemini API غير متوفر"

    # Use a known working model endpoint
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={GEMINI_API_KEY}"
    headers = {'Content-Type': 'application/json'}

    # Format messages for Gemini API ('user' and 'model' roles)
    gemini_messages = []
    for msg in prompt_messages:
        role = 'user' if msg.get('role') == 'user' else 'model'
        content = msg.get('content', '')
        if not content: continue # Skip empty messages
        gemini_messages.append({"role": role, "parts": [{"text": content}]})

    if not gemini_messages:
        return None, "لا يوجد محتوى صالح لإرساله إلى Gemini."

    payload = {
        "contents": gemini_messages,
        "generationConfig": {
            "maxOutputTokens": int(max_tokens),
            "temperature": float(temperature)
        },
         "safetySettings": [ # Adjust safety settings as needed
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        ]
    }

    try:
        logger.debug(f"Calling Gemini API ({api_url}) with {len(gemini_messages)} messages.")
        response = requests.post(api_url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        response_data = response.json()

        if 'candidates' in response_data and len(response_data['candidates']) > 0:
            candidate = response_data['candidates'][0]
            finish_reason = candidate.get('finishReason', 'UNKNOWN')
            if finish_reason == 'STOP' or finish_reason == 'MAX_TOKENS':
                 if 'content' in candidate and 'parts' in candidate['content'] and len(candidate['content']['parts']) > 0:
                    text = candidate['content']['parts'][0].get('text', '').strip()
                    if text: return text, None # Success (or partial success on MAX_TOKENS)
                 logger.warning("Gemini response candidate has empty/missing text part.")
                 return None, "استجابة فارغة من Gemini."
            elif finish_reason == 'SAFETY':
                logger.warning("Gemini response blocked due to safety settings.")
                return None, "تم حظر الرد بواسطة مرشحات الأمان في Gemini."
            else:
                logger.warning(f"Gemini response finished with unexpected reason: {finish_reason}. Response: {response_data}")
                return None, f"سبب إنهاء غير متوقع من Gemini: {finish_reason}"
        elif 'promptFeedback' in response_data and response_data['promptFeedback'].get('blockReason'):
            block_reason = response_data['promptFeedback']['blockReason']
            logger.warning(f"Gemini prompt blocked due to: {block_reason}")
            return None, f"تم حظر الطلب بواسطة Gemini بسبب: {block_reason}"
        else:
            logger.error(f"No valid candidates found in Gemini response: {response_data}")
            return None, "لم يتم العثور على استجابة صالحة من Gemini"

    except requests.exceptions.Timeout:
        logger.error("Timeout calling Gemini API.")
        return None, "انتهت مهلة الاتصال بـ Gemini."
    except requests.exceptions.RequestException as e:
        logger.error(f"Error calling Gemini API: {e}")
        error_detail = str(e)
        if e.response is not None:
            try: error_detail = e.response.json().get('error', {}).get('message', str(e))
            except: error_detail = e.response.text[:500]
        return None, f"خطأ في الاتصال بـ Gemini: {error_detail}"
    except Exception as e:
        logger.exception(f"Unexpected error calling Gemini API: {e}")
        return None, f"خطأ غير متوقع أثناء استدعاء Gemini: {str(e)}"


# --- Main Application Routes ---
@app.route('/')
def index():
    """Serves the main chat interface page."""
    # Assumes 'templates/index.html' exists
    return render_template('index.html', app_title=APP_TITLE)

# --- API Routes ---

@app.route('/api/chat', methods=['POST'])
def chat():
    """Handles incoming chat messages, interacts with AI models, and stores conversation."""
    if not request.is_json:
        return jsonify({"error": "الطلب يجب أن يكون بصيغة JSON"}), 415

    try:
        data = request.json
        user_message = data.get('message', '').strip()
        model = data.get('model', 'mistralai/mistral-7b-instruct')
        conversation_id = data.get('conversation_id')
        temperature = float(data.get('temperature', 0.7))
        max_tokens = int(data.get('max_tokens', 1024))

        if not user_message:
            return jsonify({"error": "الرسالة فارغة"}), 400

        db_conversation = None
        is_new_conversation = False

        # Use a single transaction for get/create and adding user message
        try:
            with db.session.begin_nested(): # Use nested transaction
                if conversation_id:
                    db_conversation = db.session.get(Conversation, conversation_id)

                if not db_conversation:
                    conversation_id = str(uuid.uuid4()) # Generate new ID
                    initial_title = (user_message[:97] + '...') if len(user_message) > 100 else user_message
                    db_conversation = Conversation(id=conversation_id, title=initial_title)
                    db.session.add(db_conversation)
                    is_new_conversation = True
                    logger.info(f"Creating new conversation with ID: {conversation_id}")

                # Add user message within the same transaction
                db_conversation.add_message('user', user_message)

            db.session.commit() # Commit the outer transaction

        except Exception as e:
            db.session.rollback()
            logger.exception(f"Database error during chat init/user message save (Conv ID: {conversation_id}): {e}")
            return jsonify({"error": "حدث خطأ في قاعدة البيانات أثناء حفظ الرسالة."}), 500


        # --- Prepare messages for the API ---
        # Fetch full history from DB after saving user message
        db_messages_orm = db_conversation.get_ordered_messages()
        messages_for_api = [{"role": msg.role, "content": msg.content} for msg in db_messages_orm]

        ai_reply = None
        error_message = None
        used_backup = False
        api_source = "Offline"

        # 1. Try OpenRouter API
        if OPENROUTER_API_KEY:
            try:
                logger.info(f"Attempting OpenRouter API call (Conv: {conversation_id}, Model: {model})")
                response = requests.post(
                    url="https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "HTTP-Referer": APP_URL,
                        "X-Title": APP_TITLE,
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": model, "messages": messages_for_api,
                        "temperature": temperature, "max_tokens": max_tokens,
                    },
                    timeout=90
                )
                response.raise_for_status()
                api_response = response.json()
                choices = api_response.get('choices', [])
                if choices:
                    message_content = choices[0].get('message', {}).get('content')
                    if message_content:
                        ai_reply = message_content.strip()
                        api_source = "OpenRouter"
                        logger.info(f"Success from OpenRouter (Conv: {conversation_id}).")
                    else: error_message = "استجابة فارغة من OpenRouter."
                else: error_message = "استجابة غير متوقعة من OpenRouter."

            except requests.exceptions.Timeout:
                 logger.error(f"Timeout calling OpenRouter (Conv: {conversation_id}).")
                 error_message = "انتهت مهلة الاتصال بـ OpenRouter."
            except requests.exceptions.RequestException as e:
                logger.error(f"Error calling OpenRouter (Conv: {conversation_id}): {e}")
                error_detail = str(e)
                if e.response is not None:
                    try: error_detail = e.response.json().get('error',{}).get('message', str(e))
                    except: error_detail = e.response.text[:500]
                    error_message = f"خطأ من OpenRouter ({e.response.status_code}): {error_detail}"
                else: error_message = f"خطأ في الاتصال بـ OpenRouter: {error_detail}"
            except Exception as e:
                 logger.exception(f"Unexpected error during OpenRouter call (Conv: {conversation_id}): {e}")
                 error_message = f"خطأ غير متوقع في OpenRouter: {str(e)}"

        # 2. Try Gemini API as backup if OpenRouter failed
        if not ai_reply and GEMINI_API_KEY:
            logger.info(f"Trying Gemini API backup (Conv: {conversation_id}).")
            gemini_reply, gemini_error = call_gemini_api(messages_for_api, max_tokens, temperature)
            if gemini_reply:
                ai_reply = gemini_reply.strip()
                used_backup = True
                api_source = "Gemini"
                error_message = None # Clear previous error
                logger.info(f"Success from Gemini (backup) (Conv: {conversation_id}).")
            else:
                combined_error = f"فشل النموذج الاحتياطي (Gemini): {gemini_error}"
                if error_message: combined_error = f"{error_message} | {combined_error}"
                error_message = combined_error
                logger.error(f"Gemini backup failed (Conv: {conversation_id}): {gemini_error}")

        # 3. Use offline responses if both APIs failed
        if not ai_reply:
            logger.warning(f"Using offline response (Conv: {conversation_id}). Last API error: {error_message}")
            user_msg_lower = user_message.lower()
            matched_offline = False
            for key, response_text in offline_responses.items():
                 if re.search(rf'\b{re.escape(key.lower())}\b', user_msg_lower):
                    ai_reply = response_text
                    matched_offline = True
                    break
            if not matched_offline: ai_reply = default_offline_response

            # Save offline response to DB
            try:
                with db.session.begin_nested():
                    db_conversation.add_message('assistant', ai_reply)
                db.session.commit()
            except Exception as e:
                 db.session.rollback()
                 logger.error(f"Failed to save offline assistant response to DB (Conv: {conversation_id}): {e}")
                 # Continue to return response to user even if DB save fails

            return jsonify({
                "reply": ai_reply, "conversation_id": conversation_id,
                "offline": True, "error": error_message, "api_source": api_source,
                "is_new_conversation": is_new_conversation
            }), 200 # Return 200 OK for offline response

        # --- If API call (OpenRouter or Gemini) was successful ---
        if ai_reply:
            try:
                with db.session.begin_nested():
                    db_conversation.add_message('assistant', ai_reply)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.exception(f"Database error saving assistant message (Conv ID: {conversation_id}): {e}")
                # Inform user but maybe the frontend can handle the reply display?
                # Return 500 as the state is inconsistent
                return jsonify({"error": "فشل في حفظ رد المساعد في قاعدة البيانات."}), 500

            return jsonify({
                "reply": ai_reply, "conversation_id": conversation_id,
                "backup_used": used_backup, "offline": False, "api_source": api_source,
                "is_new_conversation": is_new_conversation
            })

        # Fallback error
        logger.error(f"Reached end of /api/chat logic unexpectedly (Conv: {conversation_id})")
        return jsonify({"error": "حدث خطأ غير معروف في الخادم."}), 500

    except Exception as e:
        # Catch any unexpected errors during request processing
        db.session.rollback() # Ensure rollback on any exception
        logger.exception("Unhandled exception in /api/chat route")
        return jsonify({"error": "حدث خطأ داخلي غير متوقع في الخادم."}), 500


@app.route('/api/regenerate', methods=['POST'])
def regenerate():
    """Regenerates the last assistant response in a conversation."""
    if not request.is_json:
        return jsonify({"error": "الطلب يجب أن يكون بصيغة JSON"}), 415

    try:
        data = request.json
        messages_history = data.get('messages', []) # History from frontend
        model = data.get('model', 'mistralai/mistral-7b-instruct')
        conversation_id = data.get('conversation_id')
        temperature = float(data.get('temperature', 0.7))
        max_tokens = int(data.get('max_tokens', 1024))

        if not conversation_id: return jsonify({"error": "معرّف المحادثة مطلوب"}), 400
        if not messages_history: return jsonify({"error": "لا توجد رسائل لإعادة التوليد"}), 400

        db_conversation = db.session.get(Conversation, conversation_id)
        if not db_conversation: return jsonify({"error": "المحادثة غير موجودة"}), 404

        # --- Prepare messages for API ---
        # Remove the *last* message from history *only if* it was from the assistant
        messages_for_api = list(messages_history)
        last_msg_removed = False
        if messages_for_api and messages_for_api[-1].get("role") == "assistant":
            messages_for_api.pop()
            last_msg_removed = True
            logger.info(f"Regenerate: Removed last assistant message for API call (Conv: {conversation_id}).")
        elif not messages_for_api:
             return jsonify({"error": "لا توجد رسائل كافية لإعادة التوليد بعد إزالة الرد الأخير."}), 400

        ai_reply = None
        error_message = None
        used_backup = False
        api_source = "Offline"

        # 1. Try OpenRouter API
        if OPENROUTER_API_KEY:
            try:
                logger.info(f"Attempting OpenRouter API for regeneration (Conv: {conversation_id}, Model: {model})")
                response = requests.post(
                    url="https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}", "HTTP-Referer": APP_URL,
                        "X-Title": APP_TITLE, "Content-Type": "application/json"
                    },
                    json={
                        "model": model, "messages": messages_for_api,
                        "temperature": temperature, "max_tokens": max_tokens,
                    },
                    timeout=90
                )
                response.raise_for_status()
                api_response = response.json()
                choices = api_response.get('choices', [])
                if choices:
                    message_content = choices[0].get('message', {}).get('content')
                    if message_content:
                        ai_reply = message_content.strip()
                        api_source = "OpenRouter"
                        logger.info(f"Success regenerating from OpenRouter (Conv: {conversation_id}).")
                    else: error_message = "استجابة إعادة التوليد فارغة من OpenRouter."
                else: error_message = "استجابة إعادة التوليد غير متوقعة من OpenRouter."

            except requests.exceptions.Timeout:
                 logger.error(f"Timeout calling OpenRouter for regeneration (Conv: {conversation_id}).")
                 error_message = "انتهت مهلة الاتصال بـ OpenRouter عند إعادة التوليد."
            except requests.exceptions.RequestException as e:
                logger.error(f"Error calling OpenRouter for regeneration (Conv: {conversation_id}): {e}")
                error_detail = str(e)
                if e.response is not None:
                    try: error_detail = e.response.json().get('error',{}).get('message', str(e))
                    except: error_detail = e.response.text[:500]
                    error_message = f"خطأ من OpenRouter ({e.response.status_code}): {error_detail}"
                else: error_message = f"خطأ في الاتصال بـ OpenRouter: {error_detail}"
            except Exception as e:
                 logger.exception(f"Unexpected error during OpenRouter regeneration (Conv: {conversation_id}): {e}")
                 error_message = f"خطأ غير متوقع في OpenRouter: {str(e)}"

        # 2. Try Gemini API as backup
        if not ai_reply and GEMINI_API_KEY:
            logger.info(f"Trying Gemini API backup for regeneration (Conv: {conversation_id}).")
            gemini_reply, gemini_error = call_gemini_api(messages_for_api, max_tokens, temperature)
            if gemini_reply:
                ai_reply = gemini_reply.strip()
                used_backup = True
                api_source = "Gemini"
                error_message = None # Clear previous error
                logger.info(f"Success regenerating from Gemini (backup) (Conv: {conversation_id}).")
            else:
                combined_error = f"فشل النموذج الاحتياطي (Gemini): {gemini_error}"
                if error_message: combined_error = f"{error_message} | {combined_error}"
                error_message = combined_error
                logger.error(f"Gemini backup failed for regeneration (Conv: {conversation_id}): {gemini_error}")

        # 3. Handle failure to regenerate
        if not ai_reply:
            final_error_msg = f"فشلت عملية إعادة توليد الرد. {error_message or 'النماذج غير متاحة.'}"
            logger.error(f"Failed to regenerate response for Conv {conversation_id}. Error: {error_message}")
            return jsonify({"error": final_error_msg}), 503 # Service Unavailable

        # --- If regeneration API call was successful ---
        if ai_reply:
            try:
                with db.session.begin_nested():
                    if last_msg_removed:
                        # Find the *actual* last assistant message in the database and update it
                        last_assistant_msg_orm = db.session.execute(
                            db.select(Message)
                            .filter_by(conversation_id=conversation_id, role='assistant')
                            .order_by(Message.created_at.desc())
                        ).scalars().first()

                        if last_assistant_msg_orm:
                            last_assistant_msg_orm.content = ai_reply
                            last_assistant_msg_orm.created_at = datetime.utcnow() # Update timestamp
                            db.session.add(last_assistant_msg_orm)
                            logger.info(f"Updated last assistant message (ID: {last_assistant_msg_orm.id}) in DB for Conv {conversation_id}.")
                        else:
                             # Should not happen if last_msg_removed is True, but handle defensively
                             logger.warning(f"Regenerate inconsistency: last msg removed from history, but no assistant msg found in DB for Conv {conversation_id}. Adding as new.")
                             db_conversation.add_message('assistant', ai_reply)
                    else:
                        # If last message in history was user, add the new response
                         logger.info(f"Adding regenerated response as new assistant message (Conv: {conversation_id}).")
                         db_conversation.add_message('assistant', ai_reply)

                    # Update the conversation's overall timestamp
                    db_conversation.updated_at = datetime.utcnow()
                    db.session.add(db_conversation)

                db.session.commit()

            except Exception as e:
                db.session.rollback()
                logger.exception(f"Database error saving regenerated message (Conv ID: {conversation_id}): {e}")
                return jsonify({"error": "فشل في حفظ الرد المُعاد توليده في قاعدة البيانات."}), 500

            return jsonify({
                "reply": ai_reply, "conversation_id": conversation_id,
                "backup_used": used_backup, "offline": False, "api_source": api_source
            })

    except Exception as e:
        db.session.rollback()
        logger.exception("Unhandled exception in /api/regenerate route")
        return jsonify({"error": f"حدث خطأ داخلي غير متوقع: {str(e)}"}), 500


@app.route('/api/conversations/<string:conversation_id>', methods=['GET'])
def get_conversation(conversation_id):
    """Fetches a specific conversation and its messages."""
    try:
        # Validate UUID format roughly
        if len(conversation_id) != 36: return jsonify({"error": "معرف المحادثة غير صالح"}), 400

        db_conversation = db.session.get(Conversation, conversation_id)
        if not db_conversation: return jsonify({"error": "المحادثة غير موجودة"}), 404

        return jsonify(db_conversation.to_dict())

    except Exception as e:
        logger.exception(f"Error fetching conversation {conversation_id}: {e}")
        return jsonify({"error": f"خطأ في جلب المحادثة: {str(e)}"}), 500

@app.route('/api/conversations', methods=['GET'])
def list_conversations():
    """Lists all conversation IDs and titles, sorted by last updated."""
    try:
        conversations_orm = db.session.execute(
            db.select(Conversation).order_by(Conversation.updated_at.desc())
        ).scalars().all()
        conversation_list = [
            {"id": conv.id, "title": conv.title, "updated_at": conv.updated_at.isoformat()}
            for conv in conversations_orm
        ]
        return jsonify({"conversations": conversation_list})
    except Exception as e:
        logger.exception(f"Error listing conversations: {e}")
        return jsonify({"error": f"خطأ في عرض المحادثات: {str(e)}"}), 500

@app.route('/api/conversations/<string:conversation_id>', methods=['DELETE'])
def delete_conversation(conversation_id):
    """Deletes a specific conversation and its messages."""
    try:
        db_conversation = db.session.get(Conversation, conversation_id)
        if not db_conversation: return jsonify({"error": "المحادثة غير موجودة"}), 404

        db.session.delete(db_conversation) # Cascade delete handles messages
        db.session.commit()
        logger.info(f"Deleted conversation {conversation_id}")
        return jsonify({"success": True, "message": "تم حذف المحادثة بنجاح"})

    except Exception as e:
        db.session.rollback()
        logger.exception(f"Error deleting conversation {conversation_id}: {e}")
        return jsonify({"error": f"خطأ في حذف المحادثة: {str(e)}"}), 500

@app.route('/api/models', methods=['GET'])
def get_models():
    """Returns a list of available models."""
    # Keep this list updated or fetch dynamically if possible
    models = [
        {"id": "mistralai/mistral-7b-instruct", "name": "Mistral 7B Instruct"},
        {"id": "google/gemma-7b-it", "name": "Google Gemma 7B IT"},
        {"id": "meta-llama/llama-3-8b-instruct", "name": "Meta Llama 3 8B Instruct"},
        {"id": "anthropic/claude-3-haiku-20240307", "name": "Anthropic Claude 3 Haiku"},
        {"id": "anthropic/claude-3-sonnet-20240229", "name": "Anthropic Claude 3 Sonnet"},
        {"id": "openai/gpt-3.5-turbo", "name": "OpenAI GPT-3.5 Turbo"},
        {"id": "openai/gpt-4-turbo", "name": "OpenAI GPT-4 Turbo"},
        {"id": "openai/gpt-4o", "name": "OpenAI GPT-4o"},
    ]
    return jsonify({"models": models})


# ----- Admin Panel Routes -----
# Assumes templates exist under 'templates/admin/'

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """Handles admin login."""
    if current_user.is_authenticated and getattr(current_user, 'is_admin', False):
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password')

        if not username or not password:
            flash('يرجى إدخال اسم المستخدم وكلمة المرور.', 'danger')
            return render_template('admin/login.html', username=username) # Pass back username

        user = db.session.execute(db.select(User).filter_by(username=username)).scalar_one_or_none()

        if user and user.check_password(password):
            if user.is_admin:
                login_user(user, remember=True) # Remember the user
                next_page = request.args.get('next')
                # Add basic URL validation for 'next' if needed to prevent open redirects
                logger.info(f"Admin user '{user.username}' logged in successfully.")
                flash('تم تسجيل الدخول بنجاح.', 'success')
                return redirect(next_page or url_for('admin_dashboard'))
            else:
                flash('ليس لديك صلاحيات الوصول للوحة التحكم الإدارية.', 'warning')
                logger.warning(f"Non-admin user '{user.username}' attempted admin login.")
        else:
            flash('اسم المستخدم أو كلمة المرور غير صحيحة.', 'danger')
            logger.warning(f"Failed admin login attempt for username: '{username}'.")

    return render_template('admin/login.html') # Render on GET or failed POST

@app.route('/admin/logout')
@login_required
def admin_logout():
    """Handles admin logout."""
    username = getattr(current_user, 'username', 'Unknown')
    logout_user()
    flash('تم تسجيل الخروج بنجاح.', 'success')
    logger.info(f"User '{username}' logged out from admin panel.")
    return redirect(url_for('admin_login'))

@app.route('/admin')
@admin_required # Ensures only authenticated admins can access
def admin_dashboard():
    """Displays the main admin dashboard."""
    try:
        user_count = db.session.scalar(db.select(db.func.count(User.id)))
        conversation_count = db.session.scalar(db.select(db.func.count(Conversation.id)))
        message_count = db.session.scalar(db.select(db.func.count(Message.id)))
        recent_conversations = db.session.execute(
            db.select(Conversation).order_by(Conversation.updated_at.desc()).limit(5)
        ).scalars().all()

        return render_template('admin/dashboard.html',
                               user_count=user_count,
                               conversation_count=conversation_count,
                               message_count=message_count,
                               recent_conversations=recent_conversations)
    except Exception as e:
        logger.exception("Error loading admin dashboard")
        flash("حدث خطأ أثناء تحميل لوحة التحكم.", "danger")
        return redirect(url_for('index'))

@app.route('/admin/users')
@admin_required
def admin_users():
    """Displays the list of users."""
    try:
        users = db.session.execute(db.select(User).order_by(User.username)).scalars().all()
        return render_template('admin/users.html', users=users)
    except Exception as e:
        logger.exception("Error loading admin users page")
        flash("حدث خطأ أثناء تحميل قائمة المستخدمين.", "danger")
        return redirect(url_for('admin_dashboard'))

@app.route('/admin/users/create', methods=['GET', 'POST'])
@admin_required
def admin_create_user():
    """Handles creation of new users."""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password')
        is_admin = 'is_admin' in request.form

        # Server-Side Validation
        errors = []
        if not username: errors.append("اسم المستخدم مطلوب.")
        if not email: errors.append("البريد الإلكتروني مطلوب.")
        elif not re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", email):
             errors.append("صيغة البريد الإلكتروني غير صحيحة.")
        if not password: errors.append("كلمة المرور مطلوبة.")
        elif len(password) < 8: errors.append("كلمة المرور يجب أن تكون 8 أحرف على الأقل.")

        if errors:
            for error in errors: flash(error, 'danger')
            return render_template('admin/create_user.html', username=username, email=email, is_admin=is_admin)

        # Check uniqueness
        existing_user = db.session.scalar(db.select(User).filter(
            (User.username == username) | (User.email == email)
        ))
        if existing_user:
            if existing_user.username == username: flash(f"اسم المستخدم '{username}' مستخدم بالفعل.", 'danger')
            if existing_user.email == email: flash(f"البريد الإلكتروني '{email}' مستخدم بالفعل.", 'danger')
            return render_template('admin/create_user.html', username=username, email=email, is_admin=is_admin)

        # Create User
        try:
            new_user = User(username=username, email=email, is_admin=is_admin)
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()
            logger.info(f"Admin '{current_user.username}' created new user '{username}' (Admin: {is_admin}).")
            flash('تم إنشاء المستخدم بنجاح!', 'success')
            return redirect(url_for('admin_users'))
        except Exception as e:
            db.session.rollback()
            logger.exception("Error creating new user in database")
            flash(f"حدث خطأ أثناء إنشاء المستخدم: {str(e)}", 'danger')
            return render_template('admin/create_user.html', username=username, email=email, is_admin=is_admin)

    return render_template('admin/create_user.html')

@app.route('/admin/users/<int:user_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_edit_user(user_id):
    """Handles editing of existing users."""
    user = db.session.get(User, user_id)
    if not user:
        flash('المستخدم غير موجود.', 'danger')
        return redirect(url_for('admin_users'))

    if request.method == 'POST':
        original_username = user.username
        original_email = user.email
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        new_password = request.form.get('new_password')
        is_admin = 'is_admin' in request.form

        errors = []
        if not username: errors.append("اسم المستخدم مطلوب.")
        if not email: errors.append("البريد الإلكتروني مطلوب.")
        elif not re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", email):
             errors.append("صيغة البريد الإلكتروني غير صحيحة.")
        if new_password and len(new_password) < 8:
             errors.append("كلمة المرور الجديدة يجب أن تكون 8 أحرف على الأقل.")

        if errors:
            for error in errors: flash(error, 'danger')
            return render_template('admin/edit_user.html', user=user) # Show form with original data

        # Check uniqueness if changed
        if username != original_username or email != original_email:
            existing_check = db.session.scalar(db.select(User).filter(
                User.id != user_id,
                (User.username == username) | (User.email == email)
            ))
            if existing_check:
                if existing_check.username == username: flash(f"اسم المستخدم '{username}' مستخدم بالفعل.", 'danger')
                if existing_check.email == email: flash(f"البريد الإلكتروني '{email}' مستخدم بالفعل.", 'danger')
                return render_template('admin/edit_user.html', user=user)

        # Update User
        try:
            user.username = username
            user.email = email
            # Simple check to prevent removing the last admin
            if user.is_admin and not is_admin:
                 admin_count = db.session.scalar(db.select(db.func.count(User.id)).filter_by(is_admin=True))
                 if admin_count <= 1:
                      flash("لا يمكن إزالة صلاحيات المدير من الحساب الوحيد المتبقي.", "danger")
                      return render_template('admin/edit_user.html', user=user)

            user.is_admin = is_admin
            if new_password:
                user.set_password(new_password)
                logger.info(f"Admin '{current_user.username}' updated password for user '{username}'.")

            db.session.commit()
            logger.info(f"Admin '{current_user.username}' updated profile for '{username}'.")
            flash('تم تحديث بيانات المستخدم بنجاح.', 'success')
            return redirect(url_for('admin_users'))

        except Exception as e:
            db.session.rollback()
            logger.exception(f"Error updating user {user_id}")
            flash(f"حدث خطأ أثناء تحديث المستخدم: {str(e)}", 'danger')
            return render_template('admin/edit_user.html', user=user)

    return render_template('admin/edit_user.html', user=user)

@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    """Handles deletion of a user."""
    user_to_delete = db.session.get(User, user_id)
    if not user_to_delete:
        flash('المستخدم غير موجود.', 'warning')
    elif user_to_delete.id == current_user.id:
        flash('لا يمكنك حذف حسابك الحالي.', 'danger')
    else:
        # Check if they are the last admin
        if user_to_delete.is_admin:
            admin_count = db.session.scalar(db.select(db.func.count(User.id)).filter_by(is_admin=True))
            if admin_count <= 1:
                flash("لا يمكن حذف المدير الوحيد المتبقي.", "danger")
                return redirect(url_for('admin_users'))
        try:
            username_deleted = user_to_delete.username
            db.session.delete(user_to_delete)
            db.session.commit()
            logger.info(f"Admin '{current_user.username}' deleted user '{username_deleted}' (ID: {user_id}).")
            flash(f"تم حذف المستخدم '{username_deleted}' بنجاح.", 'success')
        except Exception as e:
            db.session.rollback()
            logger.exception(f"Error deleting user {user_id}")
            flash(f"حدث خطأ أثناء حذف المستخدم: {str(e)}", 'danger')

    return redirect(url_for('admin_users'))

@app.route('/admin/conversations')
@admin_required
def admin_conversations():
    """Displays a list of all conversations."""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = 25 # Conversations per page
        # Paginate using SQLAlchemy 2.0 style
        pagination = db.paginate(db.select(Conversation).order_by(Conversation.updated_at.desc()),
                                 page=page, per_page=per_page, error_out=False)

        return render_template('admin/conversations.html',
                               conversations=pagination.items, # Use pagination.items
                               pagination=pagination) # Pass pagination object
    except Exception as e:
        logger.exception("Error loading admin conversations page")
        flash("حدث خطأ أثناء تحميل قائمة المحادثات.", "danger")
        return redirect(url_for('admin_dashboard'))

@app.route('/admin/conversations/<string:conversation_id>')
@admin_required
def admin_view_conversation(conversation_id):
    """Displays the messages within a specific conversation."""
    try:
        conversation = db.session.get(Conversation, conversation_id)
        if not conversation:
            flash('المحادثة غير موجودة.', 'danger')
            return redirect(url_for('admin_conversations'))
        # Messages are loaded via the relationship and ordered helper
        messages = conversation.get_ordered_messages()
        return render_template('admin/view_conversation.html',
                               conversation=conversation,
                               messages=messages) # Pass messages explicitly
    except Exception as e:
        logger.exception(f"Error viewing conversation {conversation_id}")
        flash("حدث خطأ أثناء عرض المحادثة.", "danger")
        return redirect(url_for('admin_conversations'))

@app.route('/admin/conversations/<string:conversation_id>/delete', methods=['POST'])
@admin_required
def admin_delete_conversation(conversation_id):
    """Handles deleting a specific conversation."""
    try:
        conversation = db.session.get(Conversation, conversation_id)
        if not conversation:
            flash('المحادثة غير موجودة.', 'warning')
        else:
            db.session.delete(conversation)
            db.session.commit()
            logger.info(f"Admin '{current_user.username}' deleted conversation {conversation_id}.")
            flash('تم حذف المحادثة بنجاح.', 'success')
    except Exception as e:
        db.session.rollback()
        logger.exception(f"Error deleting conversation {conversation_id}")
        flash(f"حدث خطأ أثناء حذف المحادثة: {str(e)}", 'danger')
    return redirect(url_for('admin_conversations'))


# --- Database Initialization and Admin User Creation ---
def initialize_database():
    """Creates database tables and the first admin user if they don't exist."""
    with app.app_context():
        logger.info("Checking database tables...")
        try:
            # Create tables based on models if they don't exist
            # Consider using Flask-Migrate for production schema management
            db.create_all()
            logger.info("Database tables checked/created.")
        except Exception as e:
            logger.critical(f"CRITICAL: Error creating/checking database tables: {e}", exc_info=True)
            # If the DB can't be reached/created, the app likely can't function.
            # You might want to raise the exception or exit.
            return # Stop initialization if DB fails

        # Check if any admin users exist
        try:
            admin_exists = db.session.scalar(db.select(User).filter_by(is_admin=True).limit(1))

            if not admin_exists:
                logger.info("No admin user found. Creating default admin...")
                default_admin_username = "admin"
                default_admin_email = "admin@example.com" # CHANGE THIS
                # Use environment variable for default password, fallback is insecure
                default_admin_password = os.environ.get("DEFAULT_ADMIN_PASSWORD")
                if not default_admin_password:
                    default_admin_password = "YasminAdminChangeMe!" # INSECURE FALLBACK
                    logger.warning("DEFAULT_ADMIN_PASSWORD environment variable not set. USING INSECURE DEFAULT PASSWORD. Please set it and change the password immediately after first login.")

                # Final check to ensure default user doesn't exist somehow
                existing_default = db.session.scalar(db.select(User).filter(
                    (User.username == default_admin_username) | (User.email == default_admin_email)
                ))

                if not existing_default:
                    admin = User(
                        username=default_admin_username,
                        email=default_admin_email,
                        is_admin=True
                    )
                    admin.set_password(default_admin_password)
                    db.session.add(admin)
                    db.session.commit()
                    logger.info(f"Default admin user '{default_admin_username}' created. PLEASE CHANGE THE DEFAULT PASSWORD!")
                else:
                    logger.info("Default admin username/email already exists, skipping creation.")
            else:
                logger.info("Admin user already exists. Skipping default admin creation.")

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error checking/creating admin user: {e}", exc_info=True)

# Add a context processor to make 'now' available in templates
@app.context_processor
def inject_now():
    return {'now': datetime.utcnow()}

# --- Main Execution ---
if __name__ == '__main__':
    # Create tables and default admin *within app context* before running
    initialize_database()

    # Get port from environment variable for deployment platforms like Render
    port = int(os.environ.get("PORT", 5000))
    # Set debug mode based on FLASK_DEBUG env var (False by default)
    debug_mode = os.environ.get("FLASK_DEBUG", "False").lower() == "true"

    logger.info(f"Starting Flask application on host 0.0.0.0, port {port} with debug mode: {debug_mode}")
    # Use host='0.0.0.0' to be accessible externally (required for containers/Render)
    # Turn OFF debug mode in production for security and performance
    app.run(host='0.0.0.0', port=port, debug=debug_mode)

# --- END OF REFACTORED app.py ---
