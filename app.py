# --- Imports ---
import os
import logging
import requests
import json
import uuid
import re # Added for email validation
from datetime import datetime
from functools import wraps

from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

# --- Basic Setup ---
logging.basicConfig(level=logging.INFO) # Use INFO level for production, DEBUG for development
logger = logging.getLogger(__name__)

# --- Base Class for SQLAlchemy models ---
class Base(DeclarativeBase):
    pass

# --- Initialize Flask ---
app = Flask(__name__)
# IMPORTANT: Use a strong, unique secret key stored in environment variables for production
app.secret_key = os.environ.get("SESSION_SECRET", "change-this-to-a-strong-random-secret-key")

# --- Configuration ---
# Get API keys from environment variables
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not OPENROUTER_API_KEY:
    logger.warning("OPENROUTER_API_KEY environment variable not set. OpenRouter API will not be available.")
if not GEMINI_API_KEY:
    logger.warning("GEMINI_API_KEY environment variable not set. Gemini API backup will not be available.")


# Other app configurations
APP_URL = os.environ.get("APP_URL", "http://localhost:5000") # Set this correctly in your environment
APP_TITLE = "Yasmin GPT Chat"

# Configure the SQLAlchemy database
# Use DATABASE_URL environment variable (e.g., postgresql://user:password@host:port/database or sqlite:///project.db)
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    logger.warning("DATABASE_URL environment variable not set. Defaulting to SQLite database 'yasmin_chat.db'.")
    DATABASE_URL = "sqlite:///yasmin_chat.db"

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 280, # Slightly less than default MySQL wait_timeout
    "pool_pre_ping": True,
}
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# --- Initialize Database (SQLAlchemy) ---
# Define db using the Base class BEFORE defining models
db = SQLAlchemy(model_class=Base)

# --- Model Definitions ---
# Ensure models inherit from db.Model AFTER db is initialized
class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    # Increased length for modern hash algorithms (like Argon2, scrypt)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)

    def set_password(self, password):
        # Use default method=scrypt if available, otherwise pbkdf2:sha256
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # get_id is provided by UserMixin, no need to override

    def __repr__(self):
        return f'<User {self.username}>'

class Conversation(db.Model):
    __tablename__ = "conversations"
    id = db.Column(db.String, primary_key=True) # UUID stored as string
    title = db.Column(db.String(255), nullable=True) # Allow null title initially
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    # Relationship to Messages - cascade deletes so messages are removed when conversation is deleted
    messages = db.relationship("Message", backref="conversation", lazy='dynamic', cascade="all, delete-orphan")

    def add_message(self, role, content):
        message = Message(conversation_id=self.id, role=role, content=content)
        db.session.add(message)
        # Mark conversation as modified to trigger onupdate (though explicit is safer)
        self.updated_at = datetime.utcnow()
        db.session.add(self)

    def get_ordered_messages(self):
        """Returns messages ordered by creation time."""
        # Use the relationship with lazy='dynamic' and order_by
        return self.messages.order_by(Message.created_at.asc()).all()

    def to_dict(self):
        # Fetch ordered messages using the dedicated method
        ordered_messages = self.get_ordered_messages()
        return {
            "id": self.id,
            "title": self.title or "محادثة جديدة", # Provide default title if null
            "messages": [msg.to_dict() for msg in ordered_messages],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }

    def __repr__(self):
        return f'<Conversation {self.id} - "{self.title}">'

class Message(db.Model):
    __tablename__ = "messages"
    id = db.Column(db.Integer, primary_key=True)
    # Ensure ondelete='CASCADE' works with your DB (usually does)
    conversation_id = db.Column(db.String, db.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = db.Column(db.String(50), nullable=False) # 'user' or 'assistant'
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    def to_dict(self):
        return {
            "id": self.id, # Include ID for potential frontend use
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at.isoformat()
        }

    def __repr__(self):
        return f'<Message {self.id} ({self.role}) in Conv {self.conversation_id}>'

# --- Initialize Extensions with App ---
db.init_app(app) # Initialize SQLAlchemy AFTER models are defined if Base is used this way

# Initialize Flask-Login AFTER User model is defined
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'admin_login'
login_manager.login_message = 'يرجى تسجيل الدخول للوصول إلى هذه الصفحة.'
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
            # Use standard Flask-Login handling for unauthorized access
            return login_manager.unauthorized()
        if not getattr(current_user, 'is_admin', False): # Check if is_admin exists and is True
            flash('غير مصرح لك بالوصول إلى هذه الصفحة. صلاحيات المدير مطلوبة.', 'danger')
            # Redirect to index for non-admins trying admin pages
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

    # Use the latest stable chat model endpoint (check Google AI docs for current models)
    # gemini-1.5-flash-latest is generally a good balance
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={GEMINI_API_KEY}"
    headers = {'Content-Type': 'application/json'}

    # Format messages for Gemini API (uses 'user' and 'model' roles)
    gemini_messages = []
    for msg in prompt_messages:
        role = 'user' if msg.get('role') == 'user' else 'model'
        content = msg.get('content', '')
        if not content: continue # Skip empty messages
        gemini_messages.append({"role": role, "parts": [{"text": content}]})

    # Ensure the last message is from the 'user' role if the history isn't empty
    if gemini_messages and gemini_messages[-1]['role'] == 'model':
        logger.warning("The last message in history sent to Gemini was from 'model'. This might lead to unexpected behavior.")
        # Depending on the model, it might expect a user prompt last.
        # Consider if you need to append a dummy user message or handle this case.

    if not gemini_messages:
        return None, "لا يوجد محتوى صالح لإرساله إلى Gemini."

    payload = {
        "contents": gemini_messages,
        "generationConfig": {
            "maxOutputTokens": int(max_tokens), # Ensure integer
            "temperature": float(temperature) # Ensure float
        },
         "safetySettings": [ # Optional: Adjust safety settings if needed
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        ]
    }

    try:
        logger.debug(f"Calling Gemini API ({api_url}) with {len(gemini_messages)} messages.")
        response = requests.post(api_url, headers=headers, json=payload, timeout=60) # Increased timeout
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        response_data = response.json()

        # --- Parse Gemini Response ---
        if 'candidates' in response_data and len(response_data['candidates']) > 0:
            candidate = response_data['candidates'][0]
            # Check for finish reason (e.g., SAFETY)
            finish_reason = candidate.get('finishReason', 'UNKNOWN')
            if finish_reason == 'STOP':
                if 'content' in candidate and 'parts' in candidate['content'] and len(candidate['content']['parts']) > 0:
                    text = candidate['content']['parts'][0].get('text', '')
                    if text:
                        return text, None # Success
                    else:
                        logger.warning("Gemini response candidate has empty text part.")
                        return None, "استجابة فارغة من Gemini."
                else:
                    logger.warning(f"Gemini response structure unexpected (no content/parts): {candidate}")
                    return None, "استجابة غير متوقعة من Gemini."
            elif finish_reason == 'SAFETY':
                logger.warning("Gemini response blocked due to safety settings.")
                # Optionally, inspect candidate['safetyRatings'] for details
                return None, "تم حظر الرد بواسطة مرشحات الأمان في Gemini."
            elif finish_reason == 'MAX_TOKENS':
                 logger.warning("Gemini response stopped due to max tokens limit.")
                 # Return partial text if available
                 if 'content' in candidate and 'parts' in candidate['content'] and len(candidate['content']['parts']) > 0:
                    text = candidate['content']['parts'][0].get('text', '')
                    if text: return text, None # Return partial
                 return None, "وصل الرد للحد الأقصى للرموز من Gemini."
            else:
                logger.warning(f"Gemini response finished with unexpected reason: {finish_reason}. Response: {response_data}")
                return None, f"سبب إنهاء غير متوقع من Gemini: {finish_reason}"

        # Check for prompt feedback blocks (e.g., input was unsafe)
        elif 'promptFeedback' in response_data and response_data['promptFeedback'].get('blockReason'):
            block_reason = response_data['promptFeedback']['blockReason']
            logger.warning(f"Gemini prompt blocked due to: {block_reason}")
            # Inspect response_data['promptFeedback']['safetyRatings'] for details
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
        # Try to get more detail from the response body if available
        if e.response is not None:
            try:
                error_json = e.response.json()
                if 'error' in error_json and 'message' in error_json['error']:
                    error_detail = error_json['error']['message']
            except (json.JSONDecodeError, AttributeError):
                error_detail = e.response.text[:500] # Limit length
        return None, f"خطأ في الاتصال بـ Gemini: {error_detail}"
    except Exception as e:
        logger.exception(f"Unexpected error calling Gemini API: {e}") # Log full traceback
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
        return jsonify({"error": "الطلب يجب أن يكون بصيغة JSON"}), 415 # Unsupported Media Type

    try:
        data = request.json
        user_message = data.get('message', '').strip()
        model = data.get('model', 'mistralai/mistral-7b-instruct') # Default model
        conversation_id = data.get('conversation_id')
        temperature = float(data.get('temperature', 0.7)) # Ensure float
        max_tokens = int(data.get('max_tokens', 1024)) # Ensure int, increase default

        if not user_message:
            return jsonify({"error": "الرسالة فارغة"}), 400

        db_conversation = None
        is_new_conversation = False

        with db.session.begin_nested(): # Use nested transaction for get/create
            if conversation_id:
                # Use db.session.get for efficient primary key lookup
                db_conversation = db.session.get(Conversation, conversation_id)

            # If conversation doesn't exist or ID wasn't provided, create a new one
            if not db_conversation:
                conversation_id = str(uuid.uuid4())
                # Use user message as initial title, truncate safely
                initial_title = (user_message[:47] + '...') if len(user_message) > 50 else user_message
                db_conversation = Conversation(id=conversation_id, title=initial_title)
                db.session.add(db_conversation)
                is_new_conversation = True
                logger.info(f"Creating new conversation with ID: {conversation_id}")

            # Add user message to the database conversation
            db_conversation.add_message('user', user_message)

        # Commit the transaction for get/create and user message add
        db.session.commit()

        # --- Prepare messages for the API ---
        # Fetch full history from DB to ensure consistency
        # get_ordered_messages handles the ordering
        db_messages_orm = db_conversation.get_ordered_messages()
        messages_for_api = [{"role": msg.role, "content": msg.content} for msg in db_messages_orm]

        ai_reply = None
        error_message = None
        used_backup = False
        api_source = "Offline" # Default if no API works

        # 1. Try OpenRouter API
        if OPENROUTER_API_KEY:
            try:
                logger.info(f"Attempting OpenRouter API call (Conv: {conversation_id}, Model: {model})")
                response = requests.post(
                    url="https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "HTTP-Referer": APP_URL, # Required by OpenRouter
                        "X-Title": APP_TITLE,     # Optional
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": model,
                        "messages": messages_for_api,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        # Consider adding other params like top_p, presence_penalty if needed
                    },
                    timeout=90 # Increased timeout for potentially longer responses
                )
                response.raise_for_status() # Raise exception for non-200 responses
                api_response = response.json()

                # Check response structure carefully
                choices = api_response.get('choices', [])
                if choices and isinstance(choices, list) and len(choices) > 0:
                    message_content = choices[0].get('message', {}).get('content')
                    if message_content:
                        ai_reply = message_content.strip()
                        api_source = "OpenRouter"
                        logger.info(f"Successfully received reply from OpenRouter (Conv: {conversation_id}).")
                    else:
                        logger.warning(f"OpenRouter response message content is empty/missing. Response: {api_response}")
                        error_message = "استجابة فارغة من OpenRouter."
                else:
                    logger.warning(f"OpenRouter response structure unexpected (no choices/message). Response: {api_response}")
                    error_message = "استجابة غير متوقعة من OpenRouter."

            except requests.exceptions.Timeout:
                 logger.error(f"Timeout calling OpenRouter API (Conv: {conversation_id}).")
                 error_message = "انتهت مهلة الاتصال بـ OpenRouter."
            except requests.exceptions.RequestException as e:
                logger.error(f"Error calling OpenRouter (Conv: {conversation_id}): {e}")
                # Try to parse error details from response if available
                error_detail = str(e)
                if e.response is not None:
                    try:
                        err_json = e.response.json()
                        if 'error' in err_json and isinstance(err_json['error'], dict) and 'message' in err_json['error']:
                            error_detail = err_json['error']['message']
                        elif 'detail' in err_json: # Some APIs use 'detail'
                             error_detail = str(err_json['detail'])
                    except (json.JSONDecodeError, AttributeError):
                        error_detail = e.response.text[:500]
                    error_message = f"خطأ من OpenRouter ({e.response.status_code}): {error_detail}"
                else:
                     error_message = f"خطأ في الاتصال بـ OpenRouter: {error_detail}"

            except Exception as e:
                 logger.exception(f"Unexpected error during OpenRouter call (Conv: {conversation_id}): {e}")
                 error_message = f"خطأ غير متوقع في OpenRouter: {str(e)}"

        # 2. Try Gemini API as backup if OpenRouter failed
        if not ai_reply and GEMINI_API_KEY:
            logger.info(f"OpenRouter failed or key missing. Trying Gemini API as backup (Conv: {conversation_id}).")
            gemini_reply, gemini_error = call_gemini_api(messages_for_api, max_tokens, temperature)
            if gemini_reply:
                ai_reply = gemini_reply.strip()
                used_backup = True
                api_source = "Gemini"
                error_message = None # Clear previous error if backup succeeds
                logger.info(f"Successfully received reply from Gemini (backup) (Conv: {conversation_id}).")
            else:
                # Combine errors if OpenRouter also failed
                combined_error = f"فشل النموذج الاحتياطي (Gemini): {gemini_error}"
                if error_message: # Prepend OpenRouter error if it exists
                     combined_error = f"{error_message} | {combined_error}"
                error_message = combined_error
                logger.error(f"Gemini backup failed (Conv: {conversation_id}): {gemini_error}")

        # 3. Use offline responses if both APIs failed
        if not ai_reply:
            logger.warning(f"Both APIs failed or unavailable. Using offline response (Conv: {conversation_id}).")
            # Simple keyword check for offline response
            matched_offline = False
            user_msg_lower = user_message.lower()
            for key, response in offline_responses.items():
                # More robust check: ensure the keyword is a whole word or common phrase part
                 if re.search(rf'\b{re.escape(key.lower())}\b', user_msg_lower):
                    ai_reply = response
                    matched_offline = True
                    break
            if not matched_offline:
                ai_reply = default_offline_response

            # Log the final error that prevented API use
            logger.info(f"Providing offline response for Conv {conversation_id}. Last API error: {error_message}")

            # Add the offline assistant response to DB
            try:
                with db.session.begin_nested():
                    db_conversation.add_message('assistant', ai_reply)
                db.session.commit()
            except Exception as e:
                 db.session.rollback()
                 # Log error but continue to return the offline response to user
                 logger.error(f"Failed to save offline assistant response to DB (Conv: {conversation_id}): {e}")

            return jsonify({
                "reply": ai_reply,
                "conversation_id": conversation_id,
                "offline": True, # Indicate offline response
                "error": error_message, # Include last error message for info
                "api_source": api_source,
                "is_new_conversation": is_new_conversation # Let frontend know if it was created
            }), 200 # Return 200 even for offline, use flags

        # --- If API call (OpenRouter or Gemini) was successful ---
        if ai_reply:
            # Add successful assistant response to database
            try:
                with db.session.begin_nested():
                    db_conversation.add_message('assistant', ai_reply)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error adding assistant message to DB (Conv: {conversation_id}): {e}")
                # Return error to frontend as saving failed
                return jsonify({"error": "فشل في حفظ رد المساعد في قاعدة البيانات"}), 500

            return jsonify({
                "reply": ai_reply,
                "conversation_id": conversation_id,
                "backup_used": used_backup,
                "offline": False,
                "api_source": api_source,
                "is_new_conversation": is_new_conversation
            })

        # Fallback in case logic somehow doesn't return (shouldn't happen)
        logger.error(f"Reached end of /api/chat without returning a response (Conv: {conversation_id})")
        return jsonify({"error": "حدث خطأ غير متوقع في منطق الخادم"}), 500

    except Exception as e:
        db.session.rollback() # Rollback any potential partial DB changes
        logger.exception("Unhandled exception in /api/chat route") # Log full traceback
        # Avoid exposing internal details in production error messages
        return jsonify({"error": "حدث خطأ داخلي غير متوقع في الخادم"}), 500


@app.route('/api/regenerate', methods=['POST'])
def regenerate():
    """Regenerates the last assistant response in a conversation."""
    if not request.is_json:
        return jsonify({"error": "الطلب يجب أن يكون بصيغة JSON"}), 415

    try:
        data = request.json
        messages_history = data.get('messages', []) # Full history from frontend
        model = data.get('model', 'mistralai/mistral-7b-instruct')
        conversation_id = data.get('conversation_id')
        temperature = float(data.get('temperature', 0.7))
        max_tokens = int(data.get('max_tokens', 1024))

        if not conversation_id:
            return jsonify({"error": "معرّف المحادثة مطلوب"}), 400

        if not messages_history or len(messages_history) < 1:
             # Need at least one message (user) to generate from
            return jsonify({"error": "لا توجد رسائل كافية لإعادة التوليد"}), 400

        # Get conversation from database to verify it exists
        db_conversation = db.session.get(Conversation, conversation_id)
        if not db_conversation:
            return jsonify({"error": "المحادثة غير موجودة"}), 404

        # --- Prepare messages for API ---
        # Use the history provided by the frontend for context,
        # removing the *last* message only if it was from the assistant.
        messages_for_api = list(messages_history) # Create a copy
        last_msg_removed = False
        if messages_for_api and messages_for_api[-1].get("role") == "assistant":
            messages_for_api.pop()
            last_msg_removed = True
            logger.info(f"Regenerate: Removed last assistant message from history for API call (Conv: {conversation_id}).")
        elif not messages_for_api:
             # If history was only the assistant message, it's now empty
              return jsonify({"error": "لا توجد رسائل كافية لإعادة التوليد بعد إزالة الرد الأخير."}), 400
        else:
             # Last message was from user - regenerate based on existing history
             logger.info(f"Regenerate: Last message was from user, regenerating based on current history (Conv: {conversation_id}).")


        ai_reply = None
        error_message = None
        used_backup = False
        api_source = "Offline"

        # 1. Try OpenRouter API
        if OPENROUTER_API_KEY:
            try:
                logger.info(f"Attempting OpenRouter API call for regeneration (Conv: {conversation_id}, Model: {model})")
                response = requests.post(
                    url="https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "HTTP-Referer": APP_URL,
                        "X-Title": APP_TITLE,
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": model,
                        "messages": messages_for_api,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                    timeout=90
                )
                response.raise_for_status()
                api_response = response.json()

                choices = api_response.get('choices', [])
                if choices and isinstance(choices, list) and len(choices) > 0:
                    message_content = choices[0].get('message', {}).get('content')
                    if message_content:
                        ai_reply = message_content.strip()
                        api_source = "OpenRouter"
                        logger.info(f"Successfully regenerated reply from OpenRouter (Conv: {conversation_id}).")
                    else:
                         logger.warning(f"OpenRouter regenerate response message content empty. Response: {api_response}")
                         error_message = "استجابة إعادة التوليد فارغة من OpenRouter."
                else:
                    logger.warning(f"OpenRouter regenerate response structure unexpected. Response: {api_response}")
                    error_message = "استجابة إعادة التوليد غير متوقعة من OpenRouter."

            except requests.exceptions.Timeout:
                 logger.error(f"Timeout calling OpenRouter API during regeneration (Conv: {conversation_id}).")
                 error_message = "انتهت مهلة الاتصال بـ OpenRouter عند إعادة التوليد."
            except requests.exceptions.RequestException as e:
                logger.error(f"Error calling OpenRouter for regeneration (Conv: {conversation_id}): {e}")
                error_detail = str(e)
                if e.response is not None:
                    try:
                        err_json = e.response.json()
                        if 'error' in err_json and isinstance(err_json['error'], dict) and 'message' in err_json['error']:
                            error_detail = err_json['error']['message']
                        elif 'detail' in err_json:
                             error_detail = str(err_json['detail'])
                    except (json.JSONDecodeError, AttributeError):
                         error_detail = e.response.text[:500]
                    error_message = f"خطأ من OpenRouter ({e.response.status_code}): {error_detail}"
                else:
                    error_message = f"خطأ في الاتصال بـ OpenRouter: {error_detail}"
            except Exception as e:
                 logger.exception(f"Unexpected error during OpenRouter regeneration call (Conv: {conversation_id}): {e}")
                 error_message = f"خطأ غير متوقع في OpenRouter: {str(e)}"

        # 2. Try Gemini API as backup if OpenRouter failed
        if not ai_reply and GEMINI_API_KEY:
            logger.info(f"OpenRouter failed regeneration. Trying Gemini API backup (Conv: {conversation_id}).")
            gemini_reply, gemini_error = call_gemini_api(messages_for_api, max_tokens, temperature)
            if gemini_reply:
                ai_reply = gemini_reply.strip()
                used_backup = True
                api_source = "Gemini"
                error_message = None # Clear previous error
                logger.info(f"Successfully regenerated reply from Gemini (backup) (Conv: {conversation_id}).")
            else:
                combined_error = f"فشل النموذج الاحتياطي (Gemini): {gemini_error}"
                if error_message:
                     combined_error = f"{error_message} | {combined_error}"
                error_message = combined_error
                logger.error(f"Gemini backup failed for regeneration (Conv: {conversation_id}): {gemini_error}")

        # 3. Handle failure to regenerate (NO offline fallback for regenerate)
        if not ai_reply:
            final_error_msg = f"فشلت عملية إعادة توليد الرد. {error_message or 'النماذج غير متاحة.'}"
            logger.error(f"Failed to regenerate response for Conv {conversation_id}. Error: {error_message}")
            return jsonify({"error": final_error_msg}), 503 # Service Unavailable is appropriate

        # --- If regeneration API call was successful ---
        if ai_reply:
            try:
                with db.session.begin_nested():
                    # Find the *actual* last assistant message in the database to update it
                    last_assistant_msg_orm = db.session.execute(
                        db.select(Message)
                        .filter_by(conversation_id=conversation_id, role='assistant')
                        .order_by(Message.created_at.desc())
                    ).scalars().first() # Use first()

                    if last_assistant_msg_orm and last_msg_removed:
                        # Update existing message content and timestamp if we removed one from history
                        last_assistant_msg_orm.content = ai_reply
                        last_assistant_msg_orm.created_at = datetime.utcnow() # Reflect regeneration time
                        db.session.add(last_assistant_msg_orm)
                        logger.info(f"Updated last assistant message (ID: {last_assistant_msg_orm.id}) in DB for Conv {conversation_id}.")
                    elif last_assistant_msg_orm and not last_msg_removed:
                        # If the last message was 'user', we are adding a *new* assistant message after it
                        logger.info(f"Adding regenerated response as new assistant message after user msg (Conv: {conversation_id}).")
                        db_conversation.add_message('assistant', ai_reply)
                    else:
                        # No prior assistant message OR history didn't end with assistant. Add as new.
                        logger.info(f"Adding regenerated response as the first/new assistant message (Conv: {conversation_id}).")
                        db_conversation.add_message('assistant', ai_reply)

                    # Update the conversation's updated_at timestamp
                    db_conversation.updated_at = datetime.utcnow()
                    db.session.add(db_conversation)

                db.session.commit()

            except Exception as e:
                db.session.rollback()
                logger.error(f"Error saving regenerated message to DB (Conv: {conversation_id}): {e}")
                return jsonify({"error": "فشل في حفظ الرد المُعاد توليده في قاعدة البيانات"}), 500

            return jsonify({
                "reply": ai_reply,
                "conversation_id": conversation_id,
                "backup_used": used_backup,
                "offline": False,
                "api_source": api_source
            })

    except Exception as e:
        db.session.rollback()
        logger.exception("Unhandled exception in /api/regenerate route")
        return jsonify({"error": f"حدث خطأ داخلي غير متوقع: {str(e)}"}), 500


@app.route('/api/conversations/<string:conversation_id>', methods=['GET'])
def get_conversation(conversation_id):
    """Fetches a specific conversation and its messages from the database."""
    try:
        # Validate UUID format if desired, though db.session.get handles non-matches
        # try:
        #     uuid.UUID(conversation_id)
        # except ValueError:
        #     return jsonify({"error": "معرف المحادثة غير صالح"}), 400

        db_conversation = db.session.get(Conversation, conversation_id)

        if not db_conversation:
            logger.info(f"Conversation not found: {conversation_id}")
            return jsonify({"error": "المحادثة غير موجودة"}), 404

        # Convert to dict format expected by the frontend
        conversation_dict = db_conversation.to_dict()
        return jsonify(conversation_dict)

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

        # Convert to list of dicts with id, title, and updated_at
        conversation_list = [
            {
                "id": conv.id,
                "title": conv.title or "محادثة جديدة",
                "updated_at": conv.updated_at.isoformat()
             }
            for conv in conversations_orm
        ]

        return jsonify({"conversations": conversation_list})
    except Exception as e:
        logger.exception(f"Error listing conversations: {e}")
        return jsonify({"error": f"خطأ في عرض المحادثات: {str(e)}"}), 500

@app.route('/api/conversations/<string:conversation_id>', methods=['DELETE'])
def delete_conversation(conversation_id):
    """Deletes a specific conversation and its messages from the database."""
    try:
        db_conversation = db.session.get(Conversation, conversation_id)

        if not db_conversation:
            logger.warning(f"Attempted to delete non-existent conversation: {conversation_id}")
            return jsonify({"error": "المحادثة غير موجودة"}), 404

        # Delete conversation (cascading delete should handle messages)
        db.session.delete(db_conversation)
        db.session.commit()
        logger.info(f"Deleted conversation with ID: {conversation_id}")

        return jsonify({"success": True, "message": "تم حذف المحادثة بنجاح"})

    except Exception as e:
        db.session.rollback()
        logger.exception(f"Error deleting conversation {conversation_id}: {e}")
        return jsonify({"error": f"خطأ في حذف المحادثة: {str(e)}"}), 500


@app.route('/api/models', methods=['GET'])
def get_models():
    """Returns a list of available models for the frontend dropdown."""
    # Consider making this list configurable (e.g., from settings or env var)
    # Ensure model IDs match exactly what OpenRouter expects.
    models = [
        {"id": "mistralai/mistral-7b-instruct", "name": "Mistral 7B Instruct"},
        {"id": "google/gemma-7b-it", "name": "Google Gemma 7B IT"},
        {"id": "meta-llama/llama-3-8b-instruct", "name": "Meta Llama 3 8B Instruct"},
        # Use specific dated versions for Claude models if needed
        {"id": "anthropic/claude-3-haiku-20240307", "name": "Anthropic Claude 3 Haiku"},
        {"id": "anthropic/claude-3-sonnet-20240229", "name": "Anthropic Claude 3 Sonnet"},
        # GPT models
        {"id": "openai/gpt-3.5-turbo", "name": "OpenAI GPT-3.5 Turbo"},
        {"id": "openai/gpt-4-turbo", "name": "OpenAI GPT-4 Turbo"},
        {"id": "openai/gpt-4o", "name": "OpenAI GPT-4o"}, # Add GPT-4o
        # Other options
        # {"id": "anthropic/claude-3-opus-20240229", "name": "Anthropic Claude 3 Opus"},
        # {"id": "google/gemma-2b-it", "name": "Google Gemma 2B IT"}
    ]
    return jsonify({"models": models})


# ----- Admin Panel Routes -----
# Assumes templates exist under a 'templates/admin/' directory

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """Handles admin login."""
    if current_user.is_authenticated and getattr(current_user, 'is_admin', False):
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password')

        if not username or not password:
            flash('يرجى إدخال اسم المستخدم وكلمة المرور', 'danger')
            # Render again, potentially passing back username if needed
            return render_template('admin/login.html', username=username, app_title=APP_TITLE)

        # Case-insensitive username lookup? Optional, but often user-friendly.
        user = db.session.execute(
            db.select(User).filter(User.username.ilike(username)) # Use ilike for case-insensitive
        ).scalar_one_or_none()

        login_attempt_user = username # For logging failed attempts

        if user and user.check_password(password):
            if user.is_admin:
                # Login successful
                login_user(user, remember=True) # Add remember me functionality
                next_page = request.args.get('next')
                flash('تم تسجيل الدخول بنجاح.', 'success')
                logger.info(f"Admin user '{user.username}' logged in successfully.")
                # Validate next_page to prevent open redirect vulnerability
                # if next_page and is_safe_url(next_page): # Implement is_safe_url check
                #    return redirect(next_page)
                return redirect(next_page or url_for('admin_dashboard'))
            else:
                # Valid user but not admin
                flash('ليس لديك صلاحيات الوصول للوحة التحكم الإدارية.', 'warning')
                logger.warning(f"Non-admin user '{user.username}' attempted admin login.")
                login_attempt_user = user.username # Log actual username found
        else:
            # Invalid username or password
            flash('اسم المستخدم أو كلمة المرور غير صحيحة.', 'danger')
            logger.warning(f"Failed admin login attempt for username: '{login_attempt_user}'.")

    # Render login page on GET or failed POST
    return render_template('admin/login.html', app_title=APP_TITLE)

@app.route('/admin/logout')
@login_required # Requires login, but admin check happens implicitly via usage context
def admin_logout():
    """Handles admin logout."""
    username = getattr(current_user, 'username', 'Unknown') # Get username before logout
    logout_user()
    flash('تم تسجيل الخروج بنجاح.', 'success')
    logger.info(f"User '{username}' logged out from admin.")
    return redirect(url_for('admin_login'))

@app.route('/admin')
@admin_required # Ensures only authenticated admins can access
def admin_dashboard():
    """Displays the main admin dashboard."""
    try:
        # Get summary statistics (more efficient counts)
        user_count = db.session.scalar(db.select(db.func.count(User.id)))
        conversation_count = db.session.scalar(db.select(db.func.count(Conversation.id)))
        message_count = db.session.scalar(db.select(db.func.count(Message.id)))

        # Get latest conversations
        recent_conversations = db.session.execute(
            db.select(Conversation).order_by(Conversation.updated_at.desc()).limit(5)
        ).scalars().all()

        return render_template('admin/dashboard.html',
                               user_count=user_count,
                               conversation_count=conversation_count,
                               message_count=message_count,
                               recent_conversations=recent_conversations,
                               app_title=APP_TITLE)
    except Exception as e:
        logger.exception("Error loading admin dashboard")
        flash("حدث خطأ أثناء تحميل لوحة التحكم.", "danger")
        return redirect(url_for('index')) # Redirect non-admins away


# --- Admin User Management ---

@app.route('/admin/users')
@admin_required
def admin_users():
    """Displays the list of users."""
    try:
        # Order users for consistent display
        users = db.session.execute(db.select(User).order_by(User.username)).scalars().all()
        return render_template('admin/users.html', users=users, app_title=APP_TITLE)
    except Exception as e:
        logger.exception("Error loading admin users page")
        flash("حدث خطأ أثناء تحميل قائمة المستخدمين.", "danger")
        return redirect(url_for('admin_dashboard'))

@app.route('/admin/users/create', methods=['GET', 'POST'])
@admin_required
def admin_create_user():
    """Handles creation of new users."""
    if request.method == 'POST':
        # Strip whitespace from inputs
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password') # Don't strip password
        is_admin = 'is_admin' in request.form

        # --- Server-Side Validation ---
        errors = []
        if not username: errors.append("اسم المستخدم مطلوب.")
        if not email: errors.append("البريد الإلكتروني مطلوب.")
        elif not re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", email):
             errors.append("صيغة البريد الإلكتروني غير صحيحة.")
        if not password: errors.append("كلمة المرور مطلوبة.")
        elif len(password) < 8: # Basic password length check
             errors.append("كلمة المرور يجب أن تكون 8 أحرف على الأقل.")

        if errors:
            for error in errors: flash(error, 'danger')
            # Return form with entered values (except password)
            return render_template('admin/create_user.html', username=username, email=email, is_admin=is_admin, app_title=APP_TITLE)

        # Check if username or email already exists (case-insensitive check)
        existing_user = db.session.execute(
            db.select(User).filter(
                (User.username.ilike(username)) | (User.email == email) # Use ilike for username
            )
        ).scalar_one_or_none()

        if existing_user:
            if existing_user.username.lower() == username.lower():
                 flash(f"اسم المستخدم '{username}' مستخدم بالفعل.", 'danger')
            if existing_user.email == email:
                 flash(f"البريد الإلكتروني '{email}' مستخدم بالفعل.", 'danger')
            return render_template('admin/create_user.html', username=username, email=email, is_admin=is_admin, app_title=APP_TITLE)

        # Create new user
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
            flash(f"حدث خطأ أثناء إنشاء المستخدم في قاعدة البيانات: {str(e)}", 'danger')
            # Show form again with values
            return render_template('admin/create_user.html', username=username, email=email, is_admin=is_admin, app_title=APP_TITLE)

    # Render blank form on GET request
    return render_template('admin/create_user.html', app_title=APP_TITLE)

@app.route('/admin/users/<int:user_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_edit_user(user_id):
    """Handles editing of existing users."""
    # Use db.session.get for primary key lookup
    user = db.session.get(User, user_id)
    if not user:
        flash('المستخدم غير موجود.', 'danger')
        return redirect(url_for('admin_users'))

    if request.method == 'POST':
        # Store original values for comparison/logging
        original_username = user.username
        original_email = user.email

        # Get and sanitize form data
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        new_password = request.form.get('new_password') # Optional new password
        is_admin = 'is_admin' in request.form

        # --- Server-Side Validation ---
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
            # Re-render edit form with current user data (not submitted data)
            return render_template('admin/edit_user.html', user=user, app_title=APP_TITLE)

        # Check if NEW username or email already exists (excluding the current user)
        if username.lower() != original_username.lower() or email != original_email:
            existing_user_check = db.session.execute(
                db.select(User).filter(
                    User.id != user_id, # Exclude self
                    (User.username.ilike(username)) | (User.email == email)
                )
            ).scalar_one_or_none()

            if existing_user_check:
                if existing_user_check.username.lower() == username.lower():
                     flash(f"اسم المستخدم '{username}' مستخدم بالفعل من قبل مستخدم آخر.", 'danger')
                if existing_user_check.email == email:
                     flash(f"البريد الإلكتروني '{email}' مستخدم بالفعل من قبل مستخدم آخر.", 'danger')
                # Re-render edit form
                return render_template('admin/edit_user.html', user=user, app_title=APP_TITLE)

        # Update user information
        try:
            user.username = username
            user.email = email
            # Prevent admin from accidentally de-admining themselves if they are the only admin?
            # Add logic here if needed. For now, allow changing own status.
            user.is_admin = is_admin

            if new_password:
                user.set_password(new_password)
                logger.info(f"Admin '{current_user.username}' updated password for user '{username}'.")

            db.session.commit()
            logger.info(f"Admin '{current_user.username}' updated user profile for '{username}'.")
            flash('تم تحديث بيانات المستخدم بنجاح.', 'success')
            return redirect(url_for('admin_users'))

        except Exception as e:
            db.session.rollback()
            logger.exception(f"Error updating user {user_id} in database")
            flash(f"حدث خطأ أثناء تحديث المستخدم: {str(e)}", 'danger')
            # Re-render edit form
            return render_template('admin/edit_user.html', user=user, app_title=APP_TITLE)

    # Render edit form on GET request
    return render_template('admin/edit_user.html', user=user, app_title=APP_TITLE)

@app.route('/admin/users/<int:user_id>/delete', methods=['POST']) # Use POST for destructive actions
@admin_required
def admin_delete_user(user_id):
    """Handles deletion of a user."""
    user_to_delete = db.session.get(User, user_id)

    if not user_to_delete:
        flash('المستخدم المراد حذفه غير موجود.', 'warning')
    elif user_to_delete.id == current_user.id:
        flash('لا يمكنك حذف حسابك الحالي.', 'danger')
    else:
        # Optional: Check if they are the last admin before deleting?
        # is_last_admin = user_to_delete.is_admin and db.session.scalar(db.select(db.func.count(User.id)).filter_by(is_admin=True)) == 1
        # if is_last_admin:
        #     flash('لا يمكن حذف المدير الوحيد المتبقي.', 'danger')
        # else:
        try:
            username_deleted = user_to_delete.username # Get username for logging before delete
            db.session.delete(user_to_delete)
            db.session.commit()
            logger.info(f"Admin '{current_user.username}' deleted user '{username_deleted}' (ID: {user_id}).")
            flash(f"تم حذف المستخدم '{username_deleted}' بنجاح.", 'success')
        except Exception as e:
            db.session.rollback()
            logger.exception(f"Error deleting user {user_id}")
            flash(f"حدث خطأ أثناء حذف المستخدم: {str(e)}", 'danger')

    return redirect(url_for('admin_users'))

# --- Admin Conversations Management ---

@app.route('/admin/conversations')
@admin_required
def admin_conversations():
    """Displays a list of all conversations."""
    try:
        # Paginate conversations for better performance if many exist
        page = request.args.get('page', 1, type=int)
        per_page = 20 # Number of conversations per page
        pagination = db.session.execute(
            db.select(Conversation).order_by(Conversation.updated_at.desc())
        ).paginate(page=page, per_page=per_page, error_out=False)

        conversations = pagination.items
        return render_template('admin/conversations.html',
                               conversations=conversations,
                               pagination=pagination,
                               app_title=APP_TITLE)
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

        # Fetch ordered messages
        messages = conversation.get_ordered_messages()

        return render_template('admin/view_conversation.html',
                               conversation=conversation,
                               messages=messages, # Pass messages separately
                               app_title=APP_TITLE)
    except Exception as e:
        logger.exception(f"Error viewing conversation {conversation_id}")
        flash("حدث خطأ أثناء عرض المحادثة.", "danger")
        return redirect(url_for('admin_conversations'))

@app.route('/admin/conversations/<string:conversation_id>/delete', methods=['POST']) # Use POST
@admin_required
def admin_delete_conversation(conversation_id):
    """Handles deleting a specific conversation."""
    try:
        conversation = db.session.get(Conversation, conversation_id)
        if not conversation:
            flash('المحادثة غير موجودة.', 'warning')
        else:
            db.session.delete(conversation) # Cascade delete should handle messages
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
            # Create tables based on models
            db.create_all()
            logger.info("Database tables checked/created successfully.")
        except Exception as e:
            logger.error(f"Error creating database tables: {e}", exc_info=True)
            # Depending on the error, you might want to exit or handle differently
            return # Stop if tables can't be created

        # Check if any admin users exist
        admin_exists = db.session.scalar(db.select(User).filter_by(is_admin=True).limit(1))

        if not admin_exists:
            logger.info("No admin user found. Creating default admin...")
            default_admin_username = "admin"
            default_admin_email = "admin@example.com" # Change this
            # Generate a strong default password OR retrieve from env var
            default_admin_password = os.environ.get("DEFAULT_ADMIN_PASSWORD", "YasminAdminChangeMe!")
            if default_admin_password == "YasminAdminChangeMe!":
                 logger.warning("Using insecure default admin password. Set DEFAULT_ADMIN_PASSWORD environment variable.")

            # Ensure the default admin doesn't somehow exist with different case
            existing_default = db.session.scalar(db.select(User).filter(
                (User.username.ilike(default_admin_username)) | (User.email == default_admin_email)
            ))

            if not existing_default:
                try:
                    admin = User(
                        username=default_admin_username,
                        email=default_admin_email,
                        is_admin=True
                    )
                    admin.set_password(default_admin_password)
                    db.session.add(admin)
                    db.session.commit()
                    logger.info(f"Default admin user '{default_admin_username}' created. PLEASE CHANGE THE DEFAULT PASSWORD!")
                except Exception as e:
                    db.session.rollback()
                    logger.error(f"Failed to create default admin user: {e}", exc_info=True)
            else:
                 logger.info("Default admin username/email already exists, skipping creation.")
        else:
            logger.info("Admin user already exists.")

# --- Main Execution ---
if __name__ == '__main__':
    # Create tables and default admin before running the app
    initialize_database()

    # Use Gunicorn or Waitress for production instead of Flask's development server
    # Get port from environment variable for deployment flexibility (e.g., Render)
    port = int(os.environ.get("PORT", 5000))
    # Set debug=False for production
    debug_mode = os.environ.get("FLASK_DEBUG", "False").lower() == "true"
    logger.info(f"Starting Flask application on port {port} with debug mode: {debug_mode}")
    # host='0.0.0.0' makes it accessible externally (needed for containers/deployment)
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
