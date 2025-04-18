import os
import logging
import requests
import json
import uuid
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# --- Base Class for SQLAlchemy models ---
class Base(DeclarativeBase):
    pass

# --- Initialize Flask and SQLAlchemy ---
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "a-very-strong-default-secret-key-CHANGE-ME") # غير هذا المفتاح

# Configure the SQLAlchemy database
# تأكد من أن DATABASE_URL مضبوط في متغيرات البيئة على Render
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///local_chat.db") # قاعدة بيانات محلية احتياطية
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 280, # أقل بقليل من 5 دقائق التي يوصي بها Render
    "pool_pre_ping": True,
}
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Initialize SQLAlchemy with app
db = SQLAlchemy(model_class=Base)
db.init_app(app)

# --- Get API keys from environment variables ---
# Primary API: OpenRouter
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
# Backup API: Gemini
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Other app configurations
APP_URL = os.environ.get("APP_URL", "http://localhost:5000") # Render سيضبط هذا تلقائياً أو يمكنك إضافته
APP_TITLE = "Yasmin GPT Chat"  # App name for OpenRouter

# --- Yasmin's offline responses ---
offline_responses = {
    "السلام عليكم": "وعليكم السلام! أنا ياسمين. للأسف، لا يوجد اتصال بالإنترنت حاليًا.",
    "كيف حالك": "أنا بخير شكراً لك. لكن لا يمكنني الوصول للنماذج الذكية الآن بسبب انقطاع الإنترنت.",
    "مرحبا": "أهلاً بك! أنا ياسمين. أعتذر، خدمة الإنترنت غير متوفرة حالياً.",
    "شكرا": "على الرحب والسعة! أتمنى أن يعود الاتصال قريباً.",
    "مع السلامة": "إلى اللقاء! آمل أن أتمكن من مساعدتك بشكل أفضل عند عودة الإنترنت."
}
default_offline_response = "أعتذر، لا يمكنني معالجة طلبك الآن. يبدو أن هناك مشكلة في الاتصال بالإنترنت أو أن الخدمة غير متاحة حالياً."

# --- Route for main page ---
@app.route('/')
def index():
    # استيراد النماذج هنا لتجنب مشاكل الاستيراد الدائري إذا تم وضع db.create_all() هنا
    # ولكن يفضل أن يكون في main.py أو أمر flask منفصل
    return render_template('index.html', app_title=APP_TITLE)

# Function to call Gemini API as a backup
def call_gemini_api(prompt_messages, max_tokens=512):
    """Call the Gemini API as a backup"""
    if not GEMINI_API_KEY:
        logger.warning("Gemini API key not found.")
        return None, "مفتاح Gemini API غير متوفر"

    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={GEMINI_API_KEY}"
    headers = {'Content-Type': 'application/json'}

    # Format messages for Gemini's 'contents' structure
    gemini_contents = []
    for msg in prompt_messages:
        # Map roles for Gemini: 'user' -> 'user', 'assistant' -> 'model'
        role = "user" if msg["role"] == "user" else "model"
        gemini_contents.append({"role": role, "parts": [{"text": msg["content"]}]})

    # Ensure the last message isn't from the model, Gemini expects user turn
    # If last message is assistant, we need to adjust or handle context differently.
    # For simplicity here, we assume the prompt_messages ends with a user message.
    if not gemini_contents or gemini_contents[-1]['role'] != 'user':
         logger.warning("Gemini API requires the last message to be from the user. Cannot call API.")
         # Handle this case - maybe return error or try formatting differently
         # For now, return error. You might need to adjust the history sent.
         return None, "الطلب المرسل إلى Gemini غير صحيح (يجب أن ينتهي برسالة مستخدم)."

    payload = {
        "contents": gemini_contents,
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": 0.7,
             # Add safety settings if needed
             "safetySettings": [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            ]
        }
    }

    try:
        logger.debug(f"Calling Gemini API...")
        response = requests.post(api_url, headers=headers, json=payload)
        response.raise_for_status()
        response_data = response.json()

        # Check for content and safety ratings
        if 'candidates' in response_data and response_data['candidates']:
            candidate = response_data['candidates'][0]
            # Check if content exists
            if 'content' in candidate and 'parts' in candidate['content'] and candidate['content']['parts']:
                 # Check for safety blocks before accessing text
                if 'safetyRatings' in candidate:
                    for rating in candidate['safetyRatings']:
                        if rating['probability'] in ['HIGH', 'MEDIUM']: # Or check threshold if API provides it
                            logger.warning(f"Gemini response blocked due to safety rating: {rating['category']}")
                            return None, f"تم حظر الرد من Gemini بسبب محتوى غير آمن ({rating['category']})."
                # If content exists and not blocked by safety
                text = candidate['content']['parts'][0]['text']
                return text, None
            # Handle case where response is blocked (no content part)
            elif 'finishReason' in candidate and candidate['finishReason'] == 'SAFETY':
                 logger.warning("Gemini response blocked due to SAFETY finishReason.")
                 return None, "تم حظر الرد من Gemini بسبب مخاوف تتعلق بالسلامة."
            else:
                 logger.warning(f"No content parts found in Gemini response candidate: {candidate}")
                 return None, "لم يتم العثور على محتوى نصي في استجابة Gemini."
        elif 'promptFeedback' in response_data and 'blockReason' in response_data['promptFeedback']:
            block_reason = response_data['promptFeedback']['blockReason']
            logger.warning(f"Gemini prompt blocked due to: {block_reason}")
            return None, f"تم حظر الطلب إلى Gemini بسبب: {block_reason}"
        else:
            logger.error(f"Unexpected Gemini API response format: {response_data}")
            return None, "تنسيق استجابة Gemini غير متوقع."

    except requests.exceptions.RequestException as e:
        logger.error(f"Error calling Gemini API: {e}")
        # Check if the error response is JSON and contains details
        error_detail = str(e)
        try:
            error_json = e.response.json()
            if 'error' in error_json and 'message' in error_json['error']:
                error_detail = error_json['error']['message']
        except:
            pass # Keep original error string if parsing fails
        return None, f"خطأ في الاتصال بـ Gemini: {error_detail}"
    except Exception as e:
        logger.error(f"Generic error in Gemini API call: {e}")
        return None, f"خطأ غير متوقع أثناء الاتصال بـ Gemini: {str(e)}"

# --- API route for chat ---
@app.route('/api/chat', methods=['POST'])
def chat():
    from models import Conversation, Message # Import inside function

    try:
        data = request.json
        user_message = data.get('message')
        model = data.get('model', 'mistralai/mistral-7b-instruct')
        history = data.get('history', [])
        conversation_id = data.get('conversation_id')
        temperature = data.get('temperature', 0.7)
        max_tokens = data.get('max_tokens', 512)

        if not user_message:
            return jsonify({"error": "الرسالة فارغة"}), 400

        db_conversation = None
        if conversation_id:
            db_conversation = db.session.execute(db.select(Conversation).filter_by(id=conversation_id)).scalar_one_or_none()

        if not db_conversation:
            conversation_id = str(uuid.uuid4())
            # Use first user message as title, limit length
            title = user_message[:50] + "..." if len(user_message) > 50 else user_message
            db_conversation = Conversation(id=conversation_id, title=title)
            db.session.add(db_conversation)
            # Commit here to ensure conversation exists before adding message
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error creating new conversation: {e}")
                return jsonify({"error": f"خطأ في قاعدة البيانات عند إنشاء محادثة جديدة: {str(e)}"}), 500

        # Add user message to database
        try:
            user_db_message = db_conversation.add_message('user', user_message)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error adding user message to DB: {e}")
            return jsonify({"error": f"خطأ في قاعدة البيانات عند حفظ رسالة المستخدم: {str(e)}"}), 500

        # Build messages for API (using history from DB for consistency)
        db_messages = db.session.execute(
            db.select(Message).filter_by(conversation_id=conversation_id).order_by(Message.created_at)
        ).scalars().all()
        messages_for_api = [{"role": msg.role, "content": msg.content} for msg in db_messages]

        # Ensure history isn't overly long (optional, prevents large API requests)
        MAX_HISTORY_LEN = 20 # Example limit
        if len(messages_for_api) > MAX_HISTORY_LEN:
             messages_for_api = messages_for_api[-MAX_HISTORY_LEN:]


        ai_reply = None
        error_message = None
        used_backup = False
        status_code = 200 # Default OK status

        # 1. Try OpenRouter
        if OPENROUTER_API_KEY:
            try:
                logger.debug(f"Sending request to OpenRouter with model: {model}")
                response = requests.post(
                    url="https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "HTTP-Referer": APP_URL,
                        "X-Title": APP_TITLE,
                        'Content-Type': 'application/json'
                    },
                    json={
                        "model": model,
                        "messages": messages_for_api,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                    timeout=30 # Add a timeout
                )
                response.raise_for_status()
                api_response = response.json()

                if 'choices' in api_response and api_response['choices']:
                     ai_reply = api_response['choices'][0].get('message', {}).get('content')
                     if not ai_reply:
                         logger.warning("OpenRouter responded successfully but with empty content.")
                         error_message = "OpenRouter returned an empty reply."
                else:
                    logger.warning(f"Unexpected response format from OpenRouter: {api_response}")
                    error_message = "Invalid response format from OpenRouter."

            except requests.exceptions.Timeout:
                 logger.error("Timeout connecting to OpenRouter.")
                 error_message = "Request to OpenRouter timed out."
                 status_code = 504 # Gateway Timeout
            except requests.exceptions.RequestException as e:
                logger.error(f"Error with OpenRouter: {e}")
                status_code = e.response.status_code if e.response is not None else 503
                error_message = f"OpenRouter Error ({status_code}): {str(e)}"
                # Attempt to parse error message from OpenRouter response
                try:
                    error_json = e.response.json()
                    if 'error' in error_json and 'message' in error_json['error']:
                        error_message = f"OpenRouter Error ({status_code}): {error_json['error']['message']}"
                except:
                    pass # Keep original error message

        # 2. Try Gemini if OpenRouter failed or key not present
        if not ai_reply and GEMINI_API_KEY:
            logger.info("OpenRouter failed or unavailable. Trying Gemini API as backup.")
            ai_reply, backup_error = call_gemini_api(messages_for_api, max_tokens)

            if ai_reply:
                used_backup = True
                error_message = None # Clear previous error if backup succeeded
                status_code = 200
            else:
                 # Combine errors or prioritize backup error
                 error_message = f"OpenRouter failed. Backup Gemini also failed: {backup_error}"
                 # Keep status code from OpenRouter failure or set generic service unavailable
                 status_code = status_code if status_code != 200 else 503

        # 3. Use Offline Response if both APIs fail
        final_response_offline = False
        if not ai_reply:
            logger.warning(f"Both APIs failed. Using offline response. Last error: {error_message}")
            final_response_offline = True
            status_code = 503 # Service Unavailable

            # Check specific offline responses
            matched_offline = False
            for key in offline_responses:
                if key.lower() in user_message.lower():
                    ai_reply = offline_responses[key]
                    matched_offline = True
                    break
            # Use default if no specific match
            if not matched_offline:
                ai_reply = default_offline_response

        # Add assistant response to database if it's not an error placeholder
        if ai_reply and not final_response_offline: # Only save successful online replies
             try:
                 db_conversation.add_message('assistant', ai_reply)
                 db.session.commit()
             except Exception as e:
                 db.session.rollback()
                 logger.error(f"Error adding assistant message to DB: {e}")
                 # Decide if this should overwrite the AI reply with a DB error
                 # For now, log it but send the AI reply obtained earlier.

        # Update conversation title if it was the first message
        if len(messages_for_api) <= 1 and db_conversation.title == user_message[:50]: # Check if title is still default
             # Maybe generate a better title based on the first exchange?
             # For now, we set it initially. If needed, update logic here.
             pass

        response_data = {
            "reply": ai_reply,
            "conversation_id": conversation_id,
            "backup_used": used_backup,
            "offline": final_response_offline,
            # Include error message only if something actually went wrong
            "error": error_message if final_response_offline or status_code >= 400 else None
        }

        return jsonify(response_data), status_code

    except Exception as e:
        logger.exception(f"Unhandled internal error in /api/chat: {e}") # Log full traceback
        db.session.rollback() # Rollback any potential DB changes from this request
        return jsonify({"error": f"حدث خطأ داخلي غير متوقع في الخادم."}), 500


# --- API route to regenerate a response ---
@app.route('/api/regenerate', methods=['POST'])
def regenerate():
    from models import Conversation, Message # Import inside function

    try:
        data = request.json
        conversation_id = data.get('conversation_id')
        model = data.get('model', 'mistralai/mistral-7b-instruct')
        temperature = data.get('temperature', 0.7)
        max_tokens = data.get('max_tokens', 512)

        if not conversation_id:
            return jsonify({"error": "معرّف المحادثة مطلوب"}), 400

        # Get conversation and messages from database
        db_conversation = db.session.execute(db.select(Conversation).filter_by(id=conversation_id)).scalar_one_or_none()
        if not db_conversation:
            return jsonify({"error": "المحادثة غير موجودة"}), 404

        db_messages = db.session.execute(
            db.select(Message).filter_by(conversation_id=conversation_id).order_by(Message.created_at)
        ).scalars().all()

        if not db_messages:
             return jsonify({"error": "لا توجد رسائل لإعادة التوليد"}), 400

        # Find the last assistant message to replace it
        last_assistant_message_index = -1
        for i in range(len(db_messages) - 1, -1, -1):
            if db_messages[i].role == 'assistant':
                last_assistant_message_index = i
                break

        # Prepare messages for API (exclude the last assistant message)
        if last_assistant_message_index != -1:
            messages_for_api = [{"role": msg.role, "content": msg.content} for msg in db_messages[:last_assistant_message_index]]
        else:
             # If no assistant message found yet, regenerate based on all messages
             messages_for_api = [{"role": msg.role, "content": msg.content} for msg in db_messages]

        if not messages_for_api:
             return jsonify({"error": "لا توجد رسائل كافية لإعادة التوليد"}), 400


        ai_reply = None
        error_message = None
        used_backup = False
        status_code = 200

        # 1. Try OpenRouter
        if OPENROUTER_API_KEY:
            try:
                logger.debug(f"Regenerating with OpenRouter, model: {model}")
                response = requests.post(
                     url="https://openrouter.ai/api/v1/chat/completions",
                     headers={
                         "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                         "HTTP-Referer": APP_URL,
                         "X-Title": APP_TITLE,
                         'Content-Type': 'application/json'
                     },
                     json={
                         "model": model,
                         "messages": messages_for_api,
                         "temperature": temperature,
                         "max_tokens": max_tokens,
                     },
                     timeout=30
                 )
                response.raise_for_status()
                api_response = response.json()

                if 'choices' in api_response and api_response['choices']:
                     ai_reply = api_response['choices'][0].get('message', {}).get('content')
                     if not ai_reply:
                         logger.warning("OpenRouter regeneration gave empty content.")
                         error_message = "OpenRouter returned an empty reply during regeneration."
                else:
                    logger.warning(f"Unexpected regen response from OpenRouter: {api_response}")
                    error_message = "Invalid response format from OpenRouter during regeneration."

            except requests.exceptions.Timeout:
                 logger.error("Timeout connecting to OpenRouter for regeneration.")
                 error_message = "Request to OpenRouter timed out during regeneration."
                 status_code = 504
            except requests.exceptions.RequestException as e:
                logger.error(f"Error with OpenRouter regeneration: {e}")
                status_code = e.response.status_code if e.response is not None else 503
                error_message = f"OpenRouter Regen Error ({status_code}): {str(e)}"
                try:
                    error_json = e.response.json()
                    if 'error' in error_json and 'message' in error_json['error']:
                        error_message = f"OpenRouter Regen Error ({status_code}): {error_json['error']['message']}"
                except:
                    pass

        # 2. Try Gemini if OpenRouter failed
        if not ai_reply and GEMINI_API_KEY:
            logger.info("Trying Gemini API as backup for regeneration.")
            ai_reply, backup_error = call_gemini_api(messages_for_api, max_tokens)

            if ai_reply:
                used_backup = True
                error_message = None
                status_code = 200
            else:
                 error_message = f"OpenRouter failed. Backup Gemini also failed during regen: {backup_error}"
                 status_code = status_code if status_code != 200 else 503

        # Handle failure of both APIs
        if not ai_reply:
            logger.error(f"Regeneration failed for both APIs. Last error: {error_message}")
            return jsonify({"error": error_message or "فشلت عملية إعادة التوليد لكلا النموذجين."}), status_code

        # Update or add the assistant message in the database
        try:
            if last_assistant_message_index != -1:
                # Update existing assistant message
                assistant_message_to_update = db_messages[last_assistant_message_index]
                assistant_message_to_update.content = ai_reply
                assistant_message_to_update.created_at = datetime.utcnow() # Update timestamp
                logger.debug(f"Updating message ID {assistant_message_to_update.id} with regenerated content.")
            else:
                # Add new assistant message if none existed
                logger.debug("No previous assistant message found, adding new one.")
                db_conversation.add_message('assistant', ai_reply)

            # Update conversation's updated_at timestamp
            db_conversation.updated_at = datetime.utcnow()
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating/adding regenerated message to DB: {e}")
            # Return the generated reply, but indicate DB error might have occurred
            return jsonify({
                "reply": ai_reply,
                "conversation_id": conversation_id,
                "backup_used": used_backup,
                "error": "تم توليد الرد بنجاح ولكن حدث خطأ أثناء حفظه في قاعدة البيانات."
            }), 500 # Internal Server Error due to DB issue

        return jsonify({
            "reply": ai_reply,
            "conversation_id": conversation_id,
            "backup_used": used_backup
        })

    except Exception as e:
        logger.exception(f"Unhandled internal error in /api/regenerate: {e}")
        db.session.rollback()
        return jsonify({"error": "حدث خطأ داخلي غير متوقع في الخادم."}), 500

# --- API route to get conversation history ---
@app.route('/api/conversations/<conversation_id>', methods=['GET'])
def get_conversation(conversation_id):
    from models import Conversation, Message # Import inside function
    try:
        db_conversation = db.session.execute(
            db.select(Conversation).filter_by(id=conversation_id)
        ).scalar_one_or_none()

        if not db_conversation:
            # Return empty state for frontend consistency
            return jsonify({"messages": [], "title": "محادثة جديدة", "id": None})

        # Fetch messages ordered by creation time
        db_messages = db.session.execute(
            db.select(Message)
            .filter_by(conversation_id=conversation_id)
            .order_by(Message.created_at)
        ).scalars().all()

        conversation_dict = db_conversation.to_dict() # Use the method but replace messages
        conversation_dict["messages"] = [msg.to_dict() for msg in db_messages] # Ensure correct order

        return jsonify(conversation_dict)
    except Exception as e:
        logger.error(f"Error fetching conversation {conversation_id}: {e}")
        return jsonify({"error": f"خطأ في استرجاع المحادثة: {str(e)}"}), 500

# --- API route to list all conversations ---
@app.route('/api/conversations', methods=['GET'])
def list_conversations():
    from models import Conversation # Import inside function
    try:
        conversations = db.session.execute(
            db.select(Conversation).order_by(Conversation.updated_at.desc())
        ).scalars().all()

        conversation_list = [
            {"id": conv.id, "title": conv.title,
             "updated_at": conv.updated_at.isoformat() if conv.updated_at else None}
            for conv in conversations
        ]

        return jsonify({"conversations": conversation_list})
    except Exception as e:
        logger.error(f"Error listing conversations: {e}")
        return jsonify({"error": f"خطأ في عرض قائمة المحادثات: {str(e)}"}), 500

# --- API route to delete a conversation ---
@app.route('/api/conversations/<conversation_id>', methods=['DELETE'])
def delete_conversation(conversation_id):
    from models import Conversation # Import inside function
    try:
        db_conversation = db.session.execute(db.select(Conversation).filter_by(id=conversation_id)).scalar_one_or_none()

        if not db_conversation:
            return jsonify({"error": "المحادثة غير موجودة"}), 404

        db.session.delete(db_conversation)
        db.session.commit()

        logger.info(f"Deleted conversation {conversation_id}")
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error deleting conversation {conversation_id}: {e}")
        db.session.rollback()
        return jsonify({"error": f"خطأ في حذف المحادثة: {str(e)}"}), 500

# --- API route to get available models ---
@app.route('/api/models', methods=['GET'])
def get_models():
    # Consider fetching this list dynamically from OpenRouter in the future
    models = [
        {"id": "mistralai/mistral-7b-instruct", "name": "Mistral 7B Instruct"},
        {"id": "google/gemma-7b-it", "name": "Gemma 7B IT"},
        {"id": "anthropic/claude-3-haiku-20240307", "name": "Claude 3 Haiku"},
        {"id": "meta-llama/llama-3-8b-instruct", "name": "LLaMA 3 8B Instruct"},
        {"id": "openai/gpt-3.5-turbo", "name": "GPT-3.5 Turbo"},
        {"id": "google/gemini-1.5-flash-latest", "name": "Gemini 1.5 Flash"}, # Added Gemini Flash
        {"id": "anthropic/claude-3-sonnet-20240229", "name": "Claude 3 Sonnet"},
        {"id": "anthropic/claude-3-opus-20240229", "name": "Claude 3 Opus"},
        {"id": "google/gemma-2b-it", "name": "Gemma 2B IT"}
    ]
    return jsonify({"models": models})

# --- Health Check Route (Good for Render) ---
@app.route('/healthz')
def health_check():
    # You could add a quick DB check here if needed
    # e.g., try: db.session.execute(db.select(1)); return "OK", 200
    # except: return "DB Error", 500
    return "OK", 200

# Remove or comment out the development server run block
# if __name__ == '__main__':
#     # This block should not run when deployed with Gunicorn
#     print("WARNING: Running Flask development server. Use Gunicorn in production.")
#     app.run(host='0.0.0.0', port=5000, debug=True)
