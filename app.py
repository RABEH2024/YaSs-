# --- START OF FINAL app.py ---
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
from flask_migrate import Migrate # *** ADDED Migrate ***

# --- Basic Setup ---
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=log_level, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Base Class for SQLAlchemy models ---
class Base(DeclarativeBase):
    pass

# --- Initialize Flask ---
app = Flask(__name__)

# --- Configuration ---
# Render auto-generates SESSION_SECRET via render.yaml
app.secret_key = os.environ.get("SESSION_SECRET")
if not app.secret_key and os.environ.get("FLASK_ENV") != "development": # Warn only if not in local dev
    logger.critical("FATAL: SESSION_SECRET environment variable is not set. Application cannot run securely.")

# API Keys (Set in Render Environment)
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not OPENROUTER_API_KEY:
    logger.warning("OPENROUTER_API_KEY environment variable not set. OpenRouter API will not be available.")
if not GEMINI_API_KEY:
    logger.warning("GEMINI_API_KEY environment variable not set. Gemini API backup will not be available.")

# App URL (Crucial for Referer header)
APP_URL = os.environ.get("APP_URL")
if not APP_URL:
     APP_URL = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:5000") # Use Render URL if available
     logger.warning(f"APP_URL environment variable not explicitly set. Using default/detected: {APP_URL}")

APP_TITLE = "Yasmin GPT Chat"

# Database Configuration (MUST be set via DATABASE_URL env var on Render)
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    logger.critical("CRITICAL: DATABASE_URL environment variable is not set. Application cannot connect to database.")
    # Exit or raise error in production if DB is essential
    if os.environ.get("FLASK_ENV") != "development":
         raise ValueError("DATABASE_URL environment variable is required for production.")
    else: # Fallback for local dev only if needed (not recommended for Git)
        DATABASE_URL = "sqlite:///local_dev.db"
        logger.warning(f"Using local SQLite DB: {DATABASE_URL}. DO NOT use this in production or commit the DB file.")


app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 280, # Important for managed databases
    "pool_pre_ping": True,
}
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# --- Initialize Database Extension ---
db = SQLAlchemy(model_class=Base)

# --- Model Definitions ---

class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        admin_status = "Admin" if self.is_admin else "User"
        return f'<User {self.id}: {self.username} ({admin_status})>'

    def to_dict(self): # For potential future API use
        return {
            "id": self.id, "username": self.username, "email": self.email,
            "is_admin": self.is_admin,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class Conversation(db.Model):
    __tablename__ = "conversations"
    # Use String for UUID primary key with a default generator
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = db.Column(db.String(100), nullable=False, default="محادثة جديدة")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    # Relationship to Messages - lazy='dynamic' allows further querying, cascade deletes messages if conversation is deleted
    messages = db.relationship("Message", backref="conversation", lazy='dynamic', cascade="all, delete-orphan")

    def add_message(self, role, content):
        """Helper method to add a message and update conversation timestamp."""
        message = Message(conversation_id=self.id, role=role, content=content)
        db.session.add(message)
        # Explicitly mark conversation as updated
        self.updated_at = datetime.utcnow()
        db.session.add(self) # Ensure conversation update is persisted
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
            "messages": [msg.to_dict() for msg in ordered_messages] # Ensure messages are in the dict
        }

    def __repr__(self):
        return f'<Conversation {self.id} - "{self.title}">'

class Message(db.Model):
    __tablename__ = "messages"
    id = db.Column(db.Integer, primary_key=True)
    # ForeignKey with ondelete='CASCADE' ensures messages are deleted if conversation is deleted (DB level)
    conversation_id = db.Column(db.String(36), db.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False)  # 'user' or 'assistant'
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    def to_dict(self):
        return {
            "id": self.id, # Include message ID
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f'<Message {self.id} ({self.role}) in Conv {self.conversation_id}>'

# --- Initialize Extensions with App ---
# init_app calls AFTER models are defined and app is configured
db.init_app(app)
migrate = Migrate(app, db) # Initialize Flask-Migrate

# Initialize Flask-Login AFTER User model is defined
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'admin_login' # Redirect view for @login_required
login_manager.login_message = 'يرجى تسجيل الدخول للوصول إلى هذه الصفحة الإدارية.'
login_manager.login_message_category = 'warning'

# --- Flask-Login User Loader ---
@login_manager.user_loader
def load_user(user_id):
    """Loads user object from user ID stored in session."""
    try:
        # Use db.session.get for primary key lookup (more efficient)
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
            # Use standard Flask-Login handler for unauthorized access
            return login_manager.unauthorized()
        # Check if user object has is_admin attribute and if it's True
        if not getattr(current_user, 'is_admin', False):
            flash('غير مصرح لك بالوصول إلى هذه الصفحة. صلاحيات المدير مطلوبة.', 'danger')
            # Redirect non-admins away from admin pages
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# --- Helper Functions & Data ---

# Yasmin's offline responses
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

    # Use a known working model endpoint (check Google AI docs for latest)
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={GEMINI_API_KEY}"
    headers = {'Content-Type': 'application/json'}

    # Format messages for Gemini API ('user' and 'model' roles)
    gemini_messages = []
    for msg in prompt_messages:
        role = 'user' if msg.get('role') == 'user' else 'model'
        content = msg.get('content', '')
        if not content: continue # Skip empty messages
        gemini_messages.append({"role": role, "parts": [{"text": content}]})

    # Handle case where filtering leaves no messages
    if not gemini_messages:
        logger.warning("No valid messages to send to Gemini API after filtering.")
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
        response = requests.post(api_url, headers=headers, json=payload, timeout=60) # 60 sec timeout
        response.raise_for_status() # Raises HTTPError for bad responses (4xx or 5xx)
        response_data = response.json()

        # Parse Gemini response carefully
        if 'candidates' in response_data and response_data['candidates']:
            candidate = response_data['candidates'][0]
            finish_reason = candidate.get('finishReason', 'UNKNOWN')

            if finish_reason == 'STOP' or finish_reason == 'MAX_TOKENS':
                 if 'content' in candidate and 'parts' in candidate['content'] and candidate['content']['parts']:
                    text = candidate['content']['parts'][0].get('text', '').strip()
                    if text:
                         logger.info(f"Gemini success (Finish Reason: {finish_reason}).")
                         return text, None # Success (or partial success on MAX_TOKENS)
                 logger.warning("Gemini response candidate has empty/missing text part.")
                 return None, "استجابة فارغة من Gemini."
            elif finish_reason == 'SAFETY':
                logger.warning("Gemini response blocked due to safety settings.")
                return None, "تم حظر الرد بواسطة مرشحات الأمان في Gemini."
            else:
                # Log other unexpected finish reasons
                logger.warning(f"Gemini response finished with unexpected reason: {finish_reason}. Response: {response_data}")
                return None, f"سبب إنهاء غير متوقع من Gemini: {finish_reason}"
        elif 'promptFeedback' in response_data and response_data['promptFeedback'].get('blockReason'):
            block_reason = response_data['promptFeedback']['blockReason']
            logger.warning(f"Gemini prompt blocked due to: {block_reason}")
            return None, f"تم حظر الطلب بواسطة Gemini بسبب: {block_reason}"
        else:
            # Log if the response structure is unexpected
            logger.error(f"No valid candidates found in Gemini response: {response_data}")
            return None, "لم يتم العثور على استجابة صالحة من Gemini"

    except requests.exceptions.Timeout:
        logger.error("Timeout calling Gemini API.")
        return None, "انتهت مهلة الاتصال بـ Gemini."
    except requests.exceptions.RequestException as e:
        # Log details about the request error
        logger.error(f"Error calling Gemini API: {e}", exc_info=True)
        error_detail = str(e)
        if e.response is not None:
            try:
                # Try to get a more specific error message from the response body
                error_data = e.response.json()
                error_detail = error_data.get('error', {}).get('message', e.response.text[:500])
            except json.JSONDecodeError:
                 error_detail = e.response.text[:500] # Use raw text if not JSON
            except Exception:
                 error_detail = e.response.text[:500] # Fallback
            error_message = f"خطأ في الاتصال بـ Gemini ({e.response.status_code}): {error_detail}"
        else:
             error_message = f"خطأ في الاتصال بـ Gemini: {error_detail}"
        return None, error_message
    except Exception as e:
        # Catch-all for any other unexpected errors during the API call
        logger.exception(f"Unexpected error calling Gemini API: {e}")
        return None, f"خطأ غير متوقع أثناء استدعاء Gemini: {str(e)}"

# --- Main Application Routes ---
@app.route('/')
def index():
    """Serves the main chat interface page."""
    return render_template('index.html', app_title=APP_TITLE)

# --- API Routes ---

@app.route('/api/chat', methods=['POST'])
def chat():
    """Handles incoming chat messages, interacts with AI models, and stores conversation."""
    if not request.is_json:
        return jsonify({"error": "الطلب يجب أن يكون بصيغة JSON"}), 415 # Unsupported Media Type

    try:
        data = request.json
        user_message = data.get('message', '').strip()
        model = data.get('model', 'mistralai/mistral-7b-instruct') # Default model
        conversation_id = data.get('conversation_id')
        temperature = float(data.get('temperature', 0.7))
        max_tokens = int(data.get('max_tokens', 1024)) # Increased default

        if not user_message:
            return jsonify({"error": "الرسالة فارغة"}), 400 # Bad Request

        db_conversation = None
        is_new_conversation = False

        # Use a single transaction for get/create and adding user message
        try:
            # Use nested transaction to handle potential errors during save
            with db.session.begin_nested():
                if conversation_id:
                    db_conversation = db.session.get(Conversation, conversation_id) # Use get() for PK lookup

                if not db_conversation:
                    # Default function in model sets ID, just create object
                    initial_title = (user_message[:97] + '...') if len(user_message) > 100 else user_message
                    db_conversation = Conversation(title=initial_title)
                    db.session.add(db_conversation)
                    # Flush to get the generated ID before adding the message requires it
                    db.session.flush()
                    conversation_id = db_conversation.id # Get the generated ID
                    is_new_conversation = True
                    logger.info(f"Creating new conversation with ID: {conversation_id}")

                # Add user message within the same transaction
                db_conversation.add_message('user', user_message)

            # Commit the outer transaction if nested block succeeded
            db.session.commit()

        except Exception as e:
            db.session.rollback() # Rollback on any error during DB interaction
            logger.exception(f"Database error during chat init/user message save (Conv ID: {conversation_id}): {e}")
            return jsonify({"error": "حدث خطأ في قاعدة البيانات أثناء حفظ الرسالة."}), 500 # Internal Server Error


        # --- Prepare messages for the API ---
        # Fetch full history from DB *after* saving the user message
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
                        "HTTP-Referer": APP_URL, # *** CRITICAL: Pass the Referer ***
                        "X-Title": APP_TITLE,    # Optional: Helps OpenRouter identify your app
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": model,
                        "messages": messages_for_api,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                    timeout=90 # Increased timeout for potentially slow models
                )
                response.raise_for_status() # Check for HTTP errors
                api_response = response.json()
                choices = api_response.get('choices', [])
                if choices:
                    message_content = choices[0].get('message', {}).get('content')
                    if message_content:
                        ai_reply = message_content.strip()
                        api_source = "OpenRouter"
                        logger.info(f"Success from OpenRouter (Conv: {conversation_id}).")
                    else:
                        logger.warning(f"OpenRouter response has empty message content (Conv: {conversation_id}). Response: {api_response}")
                        error_message = "استجابة فارغة من OpenRouter."
                else:
                    logger.warning(f"OpenRouter response structure missing 'choices' (Conv: {conversation_id}). Response: {api_response}")
                    error_message = "استجابة غير متوقعة من OpenRouter (بدون خيارات)."

            except requests.exceptions.Timeout:
                 logger.error(f"Timeout calling OpenRouter (Conv: {conversation_id}).")
                 error_message = "انتهت مهلة الاتصال بـ OpenRouter."
            except requests.exceptions.RequestException as e:
                logger.error(f"Error calling OpenRouter (Conv: {conversation_id}): {e}", exc_info=True)
                error_detail = str(e)
                status_code = ""
                if e.response is not None:
                    status_code = f" ({e.response.status_code})"
                    try:
                        error_data = e.response.json()
                        error_detail = error_data.get('error',{}).get('message', e.response.text[:500])
                    except json.JSONDecodeError:
                         error_detail = e.response.text[:500]
                    except Exception:
                         error_detail = e.response.text[:500] # Fallback
                error_message = f"خطأ من OpenRouter{status_code}: {error_detail}"
            except Exception as e:
                 # Catch any other unexpected error during the OpenRouter call
                 logger.exception(f"Unexpected error during OpenRouter call (Conv: {conversation_id}): {e}")
                 error_message = f"خطأ غير متوقع في OpenRouter: {str(e)}"

        # 2. Try Gemini API as backup if OpenRouter failed AND Gemini key is present
        if not ai_reply and GEMINI_API_KEY:
            logger.info(f"OpenRouter failed or unavailable. Trying Gemini API backup (Conv: {conversation_id}).")
            gemini_reply, gemini_error = call_gemini_api(messages_for_api, max_tokens, temperature)
            if gemini_reply:
                ai_reply = gemini_reply # Already stripped in call_gemini_api
                used_backup = True
                api_source = "Gemini"
                error_message = None # Clear previous OpenRouter error if Gemini succeeded
                logger.info(f"Success from Gemini (backup) (Conv: {conversation_id}).")
            else:
                # Combine errors if both failed
                combined_error = f"فشل النموذج الاحتياطي (Gemini): {gemini_error}"
                if error_message: # Keep the original error message too
                     combined_error = f"{error_message} | {combined_error}"
                error_message = combined_error
                logger.error(f"Gemini backup also failed (Conv: {conversation_id}): {gemini_error}")

        # 3. Use offline responses if both APIs failed or were unavailable
        if not ai_reply:
            logger.warning(f"Both APIs failed or unavailable. Using offline response (Conv: {conversation_id}). Last API error: {error_message}")
            user_msg_lower = user_message.lower()
            matched_offline = False
            # Simple keyword matching for offline responses
            for key, response_text in offline_responses.items():
                 if key.lower() in user_msg_lower:
                    ai_reply = response_text
                    matched_offline = True
                    break
            if not matched_offline:
                ai_reply = default_offline_response

            # Save the offline response to the database as well
            try:
                with db.session.begin_nested():
                    db_conversation.add_message('assistant', ai_reply)
                db.session.commit()
            except Exception as e:
                 db.session.rollback()
                 logger.error(f"Failed to save offline assistant response to DB (Conv: {conversation_id}): {e}")
                 # Continue to return response to user even if DB save fails here

            # Return 200 OK for offline response, but include offline flag and error context
            return jsonify({
                "reply": ai_reply, "conversation_id": conversation_id,
                "offline": True, "error": error_message, "api_source": api_source,
                "is_new_conversation": is_new_conversation # Let frontend know if it's new
            }), 200 # It's not a server *failure*, just offline operation

        # --- If API call (OpenRouter or Gemini) was successful ---
        if ai_reply:
            try:
                # Save the successful AI response to the database
                with db.session.begin_nested():
                    db_conversation.add_message('assistant', ai_reply)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.exception(f"Database error saving successful assistant message (Conv ID: {conversation_id}): {e}")
                # Return 500 because the state is inconsistent (reply generated but not saved)
                return jsonify({"error": "فشل في حفظ رد المساعد في قاعدة البيانات بعد نجاح الاستدعاء."}), 500

            # Return the successful response
            return jsonify({
                "reply": ai_reply, "conversation_id": conversation_id,
                "backup_used": used_backup, "offline": False, "api_source": api_source,
                "is_new_conversation": is_new_conversation
            })

        # Fallback error if logic somehow reaches here without a reply
        logger.error(f"Reached end of /api/chat logic unexpectedly (Conv: {conversation_id}). Final error state: {error_message}")
        return jsonify({"error": error_message or "حدث خطأ غير معروف في الخادم."}), 500

    except Exception as e:
        # Catch any unexpected errors during request processing (e.g., JSON parsing)
        db.session.rollback() # Ensure rollback on any top-level exception
        logger.exception("Unhandled exception in /api/chat route")
        return jsonify({"error": "حدث خطأ داخلي غير متوقع في الخادم."}), 500


@app.route('/api/regenerate', methods=['POST'])
def regenerate():
    """Regenerates the last assistant response in a conversation."""
    if not request.is_json:
        return jsonify({"error": "الطلب يجب أن يكون بصيغة JSON"}), 415

    try:
        data = request.json
        messages_history = data.get('messages', []) # Get history from frontend
        model = data.get('model', 'mistralai/mistral-7b-instruct')
        conversation_id = data.get('conversation_id')
        temperature = float(data.get('temperature', 0.7))
        max_tokens = int(data.get('max_tokens', 1024)) # Match chat endpoint

        if not conversation_id: return jsonify({"error": "معرّف المحادثة مطلوب"}), 400
        if not messages_history: return jsonify({"error": "لا توجد رسائل لإعادة التوليد"}), 400

        # Fetch conversation from DB to ensure it exists
        db_conversation = db.session.get(Conversation, conversation_id)
        if not db_conversation: return jsonify({"error": "المحادثة غير موجودة"}), 404

        # --- Prepare messages for API ---
        # Remove the *last* message from the *provided* history *only if* it was from the assistant
        # This assumes the frontend sends the history *before* regeneration was requested
        messages_for_api = list(messages_history)
        last_msg_was_assistant = False
        if messages_for_api and messages_for_api[-1].get("role") == "assistant":
            messages_for_api.pop()
            last_msg_was_assistant = True
            logger.info(f"Regenerate: Removed last assistant message from provided history for API call (Conv: {conversation_id}).")
        # If history only had one message (assistant), this list will be empty
        if not messages_for_api:
             logger.error(f"Regenerate: Not enough messages left after removing last assistant message (Conv: {conversation_id}).")
             return jsonify({"error": "لا توجد رسائل كافية لإعادة التوليد بعد إزالة الرد الأخير."}), 400

        ai_reply = None
        error_message = None
        used_backup = False
        api_source = "Offline" # Start assuming offline

        # 1. Try OpenRouter API
        if OPENROUTER_API_KEY:
            try:
                logger.info(f"Attempting OpenRouter API for regeneration (Conv: {conversation_id}, Model: {model})")
                response = requests.post(
                    url="https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "HTTP-Referer": APP_URL, # *** Pass Referer ***
                        "X-Title": APP_TITLE,
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": model,
                        "messages": messages_for_api, # Send history *without* the last AI reply
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                    timeout=90 # Increased timeout
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

            # --- Keep the same detailed error handling as in /chat ---
            except requests.exceptions.Timeout:
                 logger.error(f"Timeout calling OpenRouter for regeneration (Conv: {conversation_id}).")
                 error_message = "انتهت مهلة الاتصال بـ OpenRouter عند إعادة التوليد."
            except requests.exceptions.RequestException as e:
                logger.error(f"Error calling OpenRouter for regeneration (Conv: {conversation_id}): {e}", exc_info=True)
                error_detail = str(e)
                status_code = ""
                if e.response is not None:
                    status_code = f" ({e.response.status_code})"
                    try: error_detail = e.response.json().get('error',{}).get('message', e.response.text[:500])
                    except: error_detail = e.response.text[:500]
                error_message = f"خطأ من OpenRouter{status_code}: {error_detail}"
            except Exception as e:
                 logger.exception(f"Unexpected error during OpenRouter regeneration (Conv: {conversation_id}): {e}")
                 error_message = f"خطأ غير متوقع في OpenRouter: {str(e)}"

        # 2. Try Gemini API as backup
        if not ai_reply and GEMINI_API_KEY:
            logger.info(f"Trying Gemini API backup for regeneration (Conv: {conversation_id}).")
            gemini_reply, gemini_error = call_gemini_api(messages_for_api, max_tokens, temperature)
            if gemini_reply:
                ai_reply = gemini_reply # Already stripped
                used_backup = True
                api_source = "Gemini"
                error_message = None # Clear previous error
                logger.info(f"Success regenerating from Gemini (backup) (Conv: {conversation_id}).")
            else:
                combined_error = f"فشل النموذج الاحتياطي (Gemini): {gemini_error}"
                if error_message: combined_error = f"{error_message} | {combined_error}"
                error_message = combined_error
                logger.error(f"Gemini backup failed for regeneration (Conv: {conversation_id}): {gemini_error}")

        # 3. Handle failure to regenerate from any online source
        if not ai_reply:
            final_error_msg = f"فشلت عملية إعادة توليد الرد. {error_message or 'النماذج غير متاحة أو حدث خطأ.'}"
            logger.error(f"Failed to regenerate response for Conv {conversation_id}. Error: {error_message}")
            # Return Service Unavailable as we couldn't fulfill the request
            return jsonify({"error": final_error_msg}), 503

        # --- If regeneration API call was successful ---
        if ai_reply:
            try:
                # Use nested transaction for DB update
                with db.session.begin_nested():
                    if last_msg_was_assistant:
                        # Find the *actual last* assistant message in the database for this conversation
                        last_assistant_msg_orm = db.session.execute(
                            db.select(Message)
                            .filter_by(conversation_id=conversation_id, role='assistant')
                            .order_by(Message.created_at.desc()) # Get the most recent one
                        ).scalars().first()

                        if last_assistant_msg_orm:
                            # Update the content and timestamp of the existing message
                            last_assistant_msg_orm.content = ai_reply
                            last_assistant_msg_orm.created_at = datetime.utcnow() # Mark as freshly generated
                            db.session.add(last_assistant_msg_orm)
                            logger.info(f"Updated last assistant message (ID: {last_assistant_msg_orm.id}) in DB for Conv {conversation_id}.")
                        else:
                             # This case *shouldn't* happen if last_msg_was_assistant is True based on frontend history,
                             # but handle defensively: add as a new message if the last one somehow disappeared from DB.
                             logger.warning(f"Regenerate inconsistency: history indicated last msg was assistant, but none found in DB for Conv {conversation_id}. Adding as new.")
                             db_conversation.add_message('assistant', ai_reply)
                    else:
                        # If the last message in the provided history was from the user,
                        # this regeneration acts like a normal reply, so add it as a new message.
                         logger.info(f"Adding regenerated response as new assistant message (Conv: {conversation_id}), as last history message was from user.")
                         db_conversation.add_message('assistant', ai_reply)

                    # Always update the conversation's overall timestamp
                    db_conversation.updated_at = datetime.utcnow()
                    db.session.add(db_conversation)

                # Commit the outer transaction
                db.session.commit()

            except Exception as e:
                db.session.rollback()
                logger.exception(f"Database error saving regenerated message (Conv ID: {conversation_id}): {e}")
                # Return 500 as state is inconsistent
                return jsonify({"error": "فشل في حفظ الرد المُعاد توليده في قاعدة البيانات."}), 500

            # Return the successfully regenerated reply
            return jsonify({
                "reply": ai_reply, "conversation_id": conversation_id,
                "backup_used": used_backup, "offline": False, "api_source": api_source
                # No need for is_new_conversation flag here
            })

    except Exception as e:
        db.session.rollback()
        logger.exception("Unhandled exception in /api/regenerate route")
        return jsonify({"error": f"حدث خطأ داخلي غير متوقع في إعادة التوليد: {str(e)}"}), 500


@app.route('/api/conversations/<string:conversation_id>', methods=['GET'])
def get_conversation(conversation_id):
    """Fetches a specific conversation and its messages."""
    try:
        # Basic validation of ID format can prevent some errors
        # A full UUID check is more complex, this is a simple length check
        if len(conversation_id) != 36:
             logger.warning(f"Received invalid conversation ID format: {conversation_id}")
             return jsonify({"error": "معرف المحادثة غير صالح"}), 400

        db_conversation = db.session.get(Conversation, conversation_id)
        if not db_conversation:
             return jsonify({"error": "المحادثة غير موجودة"}), 404 # Not Found

        # Use the to_dict method which includes ordered messages
        return jsonify(db_conversation.to_dict())

    except Exception as e:
        logger.exception(f"Error fetching conversation {conversation_id}: {e}")
        return jsonify({"error": f"خطأ في جلب المحادثة: {str(e)}"}), 500

@app.route('/api/conversations', methods=['GET'])
def list_conversations():
    """Lists all conversation IDs, titles, and last updated time."""
    try:
        conversations_orm = db.session.execute(
            db.select(Conversation).order_by(Conversation.updated_at.desc()) # Order by most recently updated
        ).scalars().all()
        # Return a list of simplified conversation objects for the sidebar
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
    """Deletes a specific conversation and its messages (via cascade)."""
    try:
        db_conversation = db.session.get(Conversation, conversation_id)
        if not db_conversation:
             return jsonify({"error": "المحادثة غير موجودة"}), 404

        db.session.delete(db_conversation) # Cascade delete should handle related messages
        db.session.commit()
        logger.info(f"Deleted conversation {conversation_id}")
        return jsonify({"success": True, "message": "تم حذف المحادثة بنجاح"})

    except Exception as e:
        db.session.rollback()
        logger.exception(f"Error deleting conversation {conversation_id}: {e}")
        return jsonify({"error": f"خطأ في حذف المحادثة: {str(e)}"}), 500

@app.route('/api/models', methods=['GET'])
def get_models():
    """Returns a list of available models (hardcoded for now)."""
    # Consider fetching this dynamically from OpenRouter if the list changes often
    # or making it configurable via environment variables.
    models = [
        {"id": "mistralai/mistral-7b-instruct", "name": "Mistral 7B Instruct"},
        {"id": "google/gemma-7b-it", "name": "Google Gemma 7B IT"},
        {"id": "meta-llama/llama-3-8b-instruct", "name": "Meta Llama 3 8B Instruct"},
        {"id": "anthropic/claude-3-haiku-20240307", "name": "Anthropic Claude 3 Haiku"},
        {"id": "anthropic/claude-3-sonnet-20240229", "name": "Anthropic Claude 3 Sonnet"},
        {"id": "openai/gpt-3.5-turbo", "name": "OpenAI GPT-3.5 Turbo"},
        {"id": "openai/gpt-4-turbo", "name": "OpenAI GPT-4 Turbo"},
        {"id": "openai/gpt-4o", "name": "OpenAI GPT-4o"}, # Add new popular models
    ]
    return jsonify({"models": models})


# ----- Admin Panel Routes -----
# These routes require the corresponding templates in templates/admin/

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

        # Query for the user
        user = db.session.execute(db.select(User).filter_by(username=username)).scalar_one_or_none()

        # Check password and admin status
        if user and user.check_password(password):
            if user.is_admin:
                login_user(user, remember=True) # Remember the user session
                next_page = request.args.get('next')
                # TODO: Add basic URL validation for 'next' to prevent open redirects
                logger.info(f"Admin user '{user.username}' logged in successfully.")
                flash('تم تسجيل الدخول بنجاح.', 'success')
                return redirect(next_page or url_for('admin_dashboard'))
            else:
                # Correct password but not an admin
                flash('ليس لديك صلاحيات الوصول للوحة التحكم الإدارية.', 'warning')
                logger.warning(f"Non-admin user '{user.username}' attempted admin login.")
        else:
            # Incorrect username or password
            flash('اسم المستخدم أو كلمة المرور غير صحيحة.', 'danger')
            logger.warning(f"Failed admin login attempt for username: '{username}'.")

    # Render login page on GET or failed POST
    return render_template('admin/login.html')

@app.route('/admin/logout')
@login_required # Ensure user is logged in to log out
def admin_logout():
    """Handles admin logout."""
    username = getattr(current_user, 'username', 'Unknown')
    logout_user()
    flash('تم تسجيل الخروج بنجاح.', 'success')
    logger.info(f"User '{username}' logged out from admin panel.")
    return redirect(url_for('admin_login'))

@app.route('/admin')
@admin_required # Custom decorator checks for authenticated admin
def admin_dashboard():
    """Displays the main admin dashboard with stats."""
    try:
        # Use SQLAlchemy 2.0 style for scalar queries
        user_count = db.session.scalar(db.select(db.func.count(User.id))) or 0
        conversation_count = db.session.scalar(db.select(db.func.count(Conversation.id))) or 0
        message_count = db.session.scalar(db.select(db.func.count(Message.id))) or 0

        # Get recent conversations
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
        # Redirect to main app page if admin dashboard fails catastrophically
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
    """Handles creation of new users by an admin."""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password')
        is_admin = 'is_admin' in request.form # Check if checkbox is checked

        # Server-Side Validation
        errors = []
        if not username: errors.append("اسم المستخدم مطلوب.")
        if not email: errors.append("البريد الإلكتروني مطلوب.")
        # Basic email format check using regex
        elif not re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", email):
             errors.append("صيغة البريد الإلكتروني غير صحيحة.")
        if not password: errors.append("كلمة المرور مطلوبة.")
        elif len(password) < 8: errors.append("كلمة المرور يجب أن تكون 8 أحرف على الأقل.") # Basic length check

        if errors:
            for error in errors: flash(error, 'danger')
            # Return form with submitted values to avoid retyping
            return render_template('admin/create_user.html', username=username, email=email, is_admin=is_admin)

        # Check uniqueness (username OR email)
        existing_user = db.session.scalar(db.select(User).filter(
            (User.username == username) | (User.email == email)
        ))
        if existing_user:
            if existing_user.username == username: flash(f"اسم المستخدم '{username}' مستخدم بالفعل.", 'danger')
            if existing_user.email == email: flash(f"البريد الإلكتروني '{email}' مستخدم بالفعل.", 'danger')
            return render_template('admin/create_user.html', username=username, email=email, is_admin=is_admin)

        # Create User in Database
        try:
            new_user = User(username=username, email=email, is_admin=is_admin)
            new_user.set_password(password) # Hash the password
            db.session.add(new_user)
            db.session.commit()
            logger.info(f"Admin '{current_user.username}' created new user '{username}' (Admin: {is_admin}).")
            flash('تم إنشاء المستخدم بنجاح!', 'success')
            return redirect(url_for('admin_users'))
        except Exception as e:
            db.session.rollback() # Rollback DB changes on error
            logger.exception("Error creating new user in database")
            flash(f"حدث خطأ أثناء إنشاء المستخدم: {str(e)}", 'danger')
            # Show form again with data
            return render_template('admin/create_user.html', username=username, email=email, is_admin=is_admin)

    # Render empty form on GET request
    return render_template('admin/create_user.html')

@app.route('/admin/users/<int:user_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_edit_user(user_id):
    """Handles editing of existing users by an admin."""
    # Fetch the user by ID or return 404
    user = db.session.get(User, user_id)
    if not user:
        flash('المستخدم غير موجود.', 'danger')
        return redirect(url_for('admin_users'))

    if request.method == 'POST':
        original_username = user.username
        original_email = user.email
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        new_password = request.form.get('new_password') # Optional new password
        is_admin = 'is_admin' in request.form

        # --- Validation ---
        errors = []
        if not username: errors.append("اسم المستخدم مطلوب.")
        if not email: errors.append("البريد الإلكتروني مطلوب.")
        elif not re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", email):
             errors.append("صيغة البريد الإلكتروني غير صحيحة.")
        # Validate password only if a new one is provided
        if new_password and len(new_password) < 8:
             errors.append("كلمة المرور الجديدة يجب أن تكون 8 أحرف على الأقل.")

        if errors:
            for error in errors: flash(error, 'danger')
            # Show form again with original user data if validation fails
            return render_template('admin/edit_user.html', user=user)

        # --- Uniqueness Check (if username/email changed) ---
        if username != original_username or email != original_email:
            existing_check = db.session.scalar(db.select(User).filter(
                User.id != user_id, # Exclude the current user
                (User.username == username) | (User.email == email)
            ))
            if existing_check:
                if existing_check.username == username: flash(f"اسم المستخدم '{username}' مستخدم بالفعل.", 'danger')
                if existing_check.email == email: flash(f"البريد الإلكتروني '{email}' مستخدم بالفعل.", 'danger')
                # Show form again with original user data
                return render_template('admin/edit_user.html', user=user)

        # --- Update User ---
        try:
            user.username = username
            user.email = email

            # Safety check: prevent removing the last admin's privileges
            if user.is_admin and not is_admin: # If user WAS admin but checkbox is now unchecked
                 admin_count = db.session.scalar(db.select(db.func.count(User.id)).filter_by(is_admin=True))
                 if admin_count is not None and admin_count <= 1:
                      flash("لا يمكن إزالة صلاحيات المدير من الحساب الوحيد المتبقي.", "danger")
                      # Prevent the change and re-render the form
                      return render_template('admin/edit_user.html', user=user)

            user.is_admin = is_admin # Update admin status

            # Update password only if a new one was provided
            if new_password:
                user.set_password(new_password)
                logger.info(f"Admin '{current_user.username}' updated password for user '{username}'.")

            db.session.commit() # Commit all changes
            logger.info(f"Admin '{current_user.username}' updated profile for user '{username}'.")
            flash('تم تحديث بيانات المستخدم بنجاح.', 'success')
            return redirect(url_for('admin_users'))

        except Exception as e:
            db.session.rollback()
            logger.exception(f"Error updating user {user_id}")
            flash(f"حدث خطأ أثناء تحديث المستخدم: {str(e)}", 'danger')
            # Re-render form with original data on error
            return render_template('admin/edit_user.html', user=user)

    # Render form with existing user data on GET request
    return render_template('admin/edit_user.html', user=user)

@app.route('/admin/users/<int:user_id>/delete', methods=['POST']) # Use POST for delete actions
@admin_required
def admin_delete_user(user_id):
    """Handles deletion of a user by an admin."""
    user_to_delete = db.session.get(User, user_id)

    if not user_to_delete:
        flash('المستخدم غير موجود.', 'warning')
    # Prevent admin from deleting themselves
    elif user_to_delete.id == current_user.id:
        flash('لا يمكنك حذف حسابك الحالي.', 'danger')
    else:
        # Safety check: prevent deleting the last admin
        if user_to_delete.is_admin:
            admin_count = db.session.scalar(db.select(db.func.count(User.id)).filter_by(is_admin=True))
            if admin_count is not None and admin_count <= 1:
                flash("لا يمكن حذف المدير الوحيد المتبقي.", "danger")
                return redirect(url_for('admin_users'))
        try:
            # Proceed with deletion
            username_deleted = user_to_delete.username # Get username for logging before delete
            db.session.delete(user_to_delete)
            db.session.commit()
            logger.info(f"Admin '{current_user.username}' deleted user '{username_deleted}' (ID: {user_id}).")
            flash(f"تم حذف المستخدم '{username_deleted}' بنجاح.", 'success')
        except Exception as e:
            db.session.rollback()
            logger.exception(f"Error deleting user {user_id}")
            flash(f"حدث خطأ أثناء حذف المستخدم: {str(e)}", 'danger')

    # Redirect back to the users list in all cases after processing
    return redirect(url_for('admin_users'))

@app.route('/admin/conversations')
@admin_required
def admin_conversations():
    """Displays a list of all conversations (consider pagination for large numbers)."""
    try:
        # Simple fetch without pagination for now
        conversations = db.session.execute(
             db.select(Conversation).order_by(Conversation.updated_at.desc())
        ).scalars().all()

        # --- OR --- Use Pagination (if you have many conversations) ---
        # page = request.args.get('page', 1, type=int)
        # per_page = 20 # Number of conversations per page
        # pagination = db.paginate(
        #     db.select(Conversation).order_by(Conversation.updated_at.desc()),
        #     page=page, per_page=per_page, error_out=False
        # )
        # conversations = pagination.items # Use items from pagination object
        # return render_template('admin/conversations.html',
        #                        conversations=conversations,
        #                        pagination=pagination) # Pass pagination object to template
        # -----------------------------------------------------------

        return render_template('admin/conversations.html', conversations=conversations)

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

        # Fetch ordered messages using the helper method in the model
        messages = conversation.get_ordered_messages()

        return render_template('admin/view_conversation.html',
                               conversation=conversation,
                               messages=messages) # Pass messages explicitly to template
    except Exception as e:
        logger.exception(f"Error viewing conversation {conversation_id}")
        flash("حدث خطأ أثناء عرض المحادثة.", "danger")
        return redirect(url_for('admin_conversations'))

@app.route('/admin/conversations/<string:conversation_id>/delete', methods=['POST']) # Use POST for delete
@admin_required
def admin_delete_conversation(conversation_id):
    """Handles deleting a specific conversation."""
    try:
        conversation = db.session.get(Conversation, conversation_id)
        if not conversation:
            flash('المحادثة غير موجودة.', 'warning')
        else:
            db.session.delete(conversation) # Cascade delete defined in model relationship handles messages
            db.session.commit()
            logger.info(f"Admin '{current_user.username}' deleted conversation {conversation_id}.")
            flash('تم حذف المحادثة بنجاح.', 'success')
    except Exception as e:
        db.session.rollback()
        logger.exception(f"Error deleting conversation {conversation_id}")
        flash(f"حدث خطأ أثناء حذف المحادثة: {str(e)}", 'danger')

    # Redirect back to the conversations list
    return redirect(url_for('admin_conversations'))


# --- Context Processor ---
# Makes 'now' available in all templates (used in admin base footer)
@app.context_processor
def inject_now():
    return {'now': datetime.utcnow()}

# --- Flask CLI Commands ---
@app.cli.command("create-admin")
def create_admin_command():
    """Creates the default admin user if none exists. Requires DEFAULT_ADMIN_PASSWORD env var."""
    with app.app_context(): # Ensure commands run within app context
        try:
            admin_exists = db.session.scalar(db.select(User).filter_by(is_admin=True).limit(1))
            if not admin_exists:
                logger.info("No admin user found. Attempting to create default admin...")
                default_admin_username = os.environ.get("DEFAULT_ADMIN_USERNAME", "admin")
                # Use a dedicated email or make it configurable
                default_admin_email = os.environ.get("DEFAULT_ADMIN_EMAIL", "admin@change.me")
                default_admin_password = os.environ.get("DEFAULT_ADMIN_PASSWORD")

                if not default_admin_password:
                    logger.error("DEFAULT_ADMIN_PASSWORD environment variable is not set. Cannot create admin user.")
                    print("Error: DEFAULT_ADMIN_PASSWORD environment variable is not set.")
                    return # Exit command if password is not set

                # Final check to ensure default user doesn't somehow exist with different case etc.
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
                    logger.info(f"Default admin user '{default_admin_username}' created successfully.")
                    print(f"Default admin user '{default_admin_username}' created.")
                    print("IMPORTANT: Change the default password/email if they are insecure!")
                else:
                    logger.info("Default admin username/email already exists, skipping creation.")
                    print("Default admin username/email already exists, skipping creation.")
            else:
                logger.info("Admin user already exists. Skipping default admin creation.")
                print("Admin user already exists. Skipping default admin creation.")

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error checking/creating admin user via command: {e}", exc_info=True)
            print(f"Error during admin user creation: {e}")

# --- Main Execution Block (for local development via `python app.py`) ---
# This block is NOT executed when running with Gunicorn on Render.
if __name__ == '__main__':
    # Use environment variables for port and debug mode control
    port = int(os.environ.get("PORT", 5000))
    # Debug mode should be disabled in production (controlled by FLASK_DEBUG env var typically)
    # Gunicorn usually manages the number of workers, not Flask's dev server.
    debug_mode = os.environ.get("FLASK_DEBUG", "False").lower() in ['true', '1', 't']

    logger.info(f"Starting Flask development server on http://0.0.0.0:{port}/ with debug mode: {debug_mode}")
    # host='0.0.0.0' makes the server accessible externally (needed for Docker/VMs/networks)
    app.run(host='0.0.0.0', port=port, debug=debug_mode)

# --- END OF FINAL app.py ---
