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
app.secret_key = os.environ.get("SESSION_SECRET", "yasmin-gpt-secret-key")

# Configure the SQLAlchemy database
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
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
APP_URL = os.environ.get("APP_URL", "http://localhost:5000")
APP_TITLE = "Yasmin GPT Chat"  # App name for OpenRouter

# --- Yasmin's offline responses ---
offline_responses = {
    "السلام عليكم": "وعليكم السلام! أنا ياسمين. للأسف، لا يوجد اتصال بالإنترنت حاليًا.",
    "كيف حالك": "أنا بخير شكراً لك. لكن لا يمكنني الوصول للنماذج الذكية الآن بسبب انقطاع الإنترنت.",
    "مرحبا": "أهلاً بك! أنا ياسمين. أعتذر، خدمة الإنترنت غير متوفرة حالياً.",
    "شكرا": "على الرحب والسعة! أتمنى أن يعود الاتصال قريباً.",
    "مع السلامة": "إلى اللقاء! آمل أن أتمكن من مساعدتك بشكل أفضل عند عودة الإنترنت."
}
default_offline_response = "أعتذر، لا يمكنني معالجة طلبك الآن. يبدو أن هناك مشكلة في الاتصال بالإنترنت."

# In-memory storage for conversations
# In a production environment, this should be a database
conversations = {}

# --- Route for main page ---
@app.route('/')
def index():
    return render_template('index.html', app_title=APP_TITLE)

# Function to call Gemini API as a backup
def call_gemini_api(prompt, max_tokens=512):
    """Call the Gemini API as a backup when OpenRouter is not available"""
    if not GEMINI_API_KEY:
        return None, "مفتاح Gemini API غير متوفر"
    
    try:
        formatted_prompt = ""
        # Format the conversation history into a single text prompt
        if isinstance(prompt, list):
            for msg in prompt:
                role = "المستخدم: " if msg["role"] == "user" else "ياسمين: "
                formatted_prompt += f"{role}{msg['content']}\n\n"
        else:
            formatted_prompt = f"المستخدم: {prompt}\n\n"
        
        # Add a final prompt for the assistant to respond
        formatted_prompt += "ياسمين: "
        
        logger.debug(f"Calling Gemini API with prompt: {formatted_prompt[:100]}...")
        response = requests.post(
            url=f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}",
            headers={
                'Content-Type': 'application/json'
            },
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

# --- API route for chat ---
@app.route('/api/chat', methods=['POST'])
def chat():
    # Import models inside the function to avoid circular imports
    from models import Conversation, Message
    
    try:
        data = request.json
        user_message = data.get('message')
        model = data.get('model', 'mistralai/mistral-7b-instruct')  # Default model
        history = data.get('history', [])  # Get conversation history
        conversation_id = data.get('conversation_id')
        temperature = data.get('temperature', 0.7)  # Default temperature
        max_tokens = data.get('max_tokens', 512)  # Default max tokens
        
        if not conversation_id:
            conversation_id = str(uuid.uuid4())
            
        if not user_message:
            return jsonify({"error": "الرسالة فارغة"}), 400

        # Get or create conversation in database
        db_conversation = db.session.execute(db.select(Conversation).filter_by(id=conversation_id)).scalar_one_or_none()
        
        if not db_conversation:
            # Create new conversation
            db_conversation = Conversation(id=conversation_id, title=user_message[:50])
            db.session.add(db_conversation)
            db.session.commit()
            
        # Add user message to database
        db_conversation.add_message('user', user_message)
        db.session.commit()
            
        # Build messages for API (with context)
        # If history is empty, get from database
        if not history:
            db_messages = db.session.execute(
                db.select(Message).filter_by(conversation_id=conversation_id).order_by(Message.created_at)
            ).scalars().all()
            
            messages = [{"role": msg.role, "content": msg.content} for msg in db_messages]
        else:
            messages = history + [{"role": "user", "content": user_message}]

        ai_reply = None
        error_message = None
        used_backup = False
        
        # First try OpenRouter API
        if OPENROUTER_API_KEY:
            try:
                logger.debug(f"Sending request to OpenRouter with model: {model}")
                response = requests.post(
                    url="https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "HTTP-Referer": APP_URL,  # Required by OpenRouter
                        "X-Title": APP_TITLE,     # Optional but recommended
                    },
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    }
                )

                response.raise_for_status()  # Raise exception for non-200 responses

                api_response = response.json()
                ai_reply = api_response['choices'][0]['message']['content']
                
            except Exception as e:
                logger.error(f"Error with OpenRouter: {e}")
                error_message = str(e)
                
        # If OpenRouter failed or not available, try Gemini API as backup
        if not ai_reply and GEMINI_API_KEY:
            logger.info("Trying Gemini API as backup")
            ai_reply, backup_error = call_gemini_api(messages, max_tokens)
            
            if ai_reply:
                used_backup = True
            else:
                error_message = f"فشل محاولة استخدام النموذج الاحتياطي: {backup_error}"
                
        # If still no reply, check offline responses
        if not ai_reply:
            # Check if offline response exists for the message
            for key in offline_responses:
                if key.lower() in user_message.lower():
                    ai_reply = offline_responses[key]
                    break
                    
            # If no matching offline response, use default
            if not ai_reply:
                ai_reply = default_offline_response
                
            # Return with offline flag
            return jsonify({
                "reply": ai_reply,
                "conversation_id": conversation_id,
                "offline": True,
                "error": error_message
            }), 503 if error_message else 200
        
        # Add assistant response to database
        db_conversation.add_message('assistant', ai_reply)
        db.session.commit()
        
        # Update conversation title for new conversations
        if len(messages) <= 2:
            title = user_message[:50] if len(user_message) > 20 else "محادثة جديدة"
            db_conversation.title = title
            db.session.commit()
            
        return jsonify({
            "reply": ai_reply,
            "conversation_id": conversation_id,
            "backup_used": used_backup
        })

    except Exception as e:
        logger.error(f"Internal error: {e}")
        # Hide sensitive details in production
        return jsonify({"error": f"حدث خطأ غير متوقع في الخادم: {str(e)}"}), 500

# --- API route to regenerate a response ---
@app.route('/api/regenerate', methods=['POST'])
def regenerate():
    # Import models inside the function to avoid circular imports
    from models import Conversation, Message
    
    try:
        data = request.json
        messages = data.get('messages', [])
        model = data.get('model', 'mistralai/mistral-7b-instruct')
        conversation_id = data.get('conversation_id')
        temperature = data.get('temperature', 0.7)
        max_tokens = data.get('max_tokens', 512)

        if not conversation_id:
            return jsonify({"error": "معرّف المحادثة مطلوب"}), 400
            
        if not messages or len(messages) < 1:
            return jsonify({"error": "لا توجد رسائل لإعادة التوليد"}), 400

        # Get conversation from database
        db_conversation = db.session.execute(db.select(Conversation).filter_by(id=conversation_id)).scalar_one_or_none()
        
        if not db_conversation:
            return jsonify({"error": "المحادثة غير موجودة"}), 404
            
        # Remove the last message if it's from assistant
        if messages[-1]["role"] == "assistant":
            messages = messages[:-1]

        ai_reply = None
        error_message = None
        used_backup = False
        
        # First try OpenRouter API
        if OPENROUTER_API_KEY:
            try:
                logger.debug(f"Regenerating response with OpenRouter using model: {model}")
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
                logger.error(f"Error with OpenRouter during regeneration: {e}")
                error_message = str(e)
                
        # If OpenRouter failed or not available, try Gemini API as backup
        if not ai_reply and GEMINI_API_KEY:
            logger.info("Trying Gemini API as backup for regeneration")
            ai_reply, backup_error = call_gemini_api(messages, max_tokens)
            
            if ai_reply:
                used_backup = True
            else:
                error_message = f"فشل محاولة استخدام النموذج الاحتياطي: {backup_error}"
                return jsonify({"error": error_message}), 503
                
        if not ai_reply:
            return jsonify({"error": "فشلت عملية إعادة توليد الرد. يرجى المحاولة مرة أخرى."}), 503
        
        # Find and update the last assistant message in the database
        last_msg = db.session.execute(
            db.select(Message)
            .filter_by(conversation_id=conversation_id, role='assistant')
            .order_by(Message.created_at.desc())
        ).scalar_one_or_none()
        
        if last_msg:
            last_msg.content = ai_reply
            db.session.commit()
        else:
            # If no assistant message exists yet, add a new one
            db_conversation.add_message('assistant', ai_reply)
            db.session.commit()
            
        return jsonify({
            "reply": ai_reply,
            "conversation_id": conversation_id,
            "backup_used": used_backup
        })

    except Exception as e:
        logger.error(f"Internal error during regeneration: {e}")
        return jsonify({"error": f"حدث خطأ غير متوقع في الخادم: {str(e)}"}), 500

# --- API route to get conversation history ---
@app.route('/api/conversations/<conversation_id>', methods=['GET'])
def get_conversation(conversation_id):
    from models import Conversation
    
    try:
        # Get conversation from database
        db_conversation = db.session.execute(db.select(Conversation).filter_by(id=conversation_id)).scalar_one_or_none()
        
        if not db_conversation:
            return jsonify({"messages": [], "title": "محادثة جديدة"})
            
        # Convert to dict format expected by the frontend
        conversation_dict = db_conversation.to_dict()
        
        return jsonify({
            "messages": conversation_dict["messages"],
            "title": conversation_dict["title"]
        })
    except Exception as e:
        logger.error(f"Error fetching conversation: {e}")
        return jsonify({"error": str(e)}), 500

# --- API route to list all conversations ---
@app.route('/api/conversations', methods=['GET'])
def list_conversations():
    from models import Conversation
    
    try:
        # Get all conversations from database
        conversations = db.session.execute(
            db.select(Conversation).order_by(Conversation.updated_at.desc())
        ).scalars().all()
        
        # Convert to list of dicts with just id and title
        conversation_list = [
            {"id": conv.id, "title": conv.title, 
             "updated_at": conv.updated_at.isoformat() if conv.updated_at else None}
            for conv in conversations
        ]
        
        return jsonify({"conversations": conversation_list})
    except Exception as e:
        logger.error(f"Error listing conversations: {e}")
        return jsonify({"error": str(e)}), 500

# --- API route to delete a conversation ---
@app.route('/api/conversations/<conversation_id>', methods=['DELETE'])
def delete_conversation(conversation_id):
    from models import Conversation
    
    try:
        # Get conversation from database
        db_conversation = db.session.execute(db.select(Conversation).filter_by(id=conversation_id)).scalar_one_or_none()
        
        if not db_conversation:
            return jsonify({"error": "المحادثة غير موجودة"}), 404
            
        # Delete conversation
        db.session.delete(db_conversation)
        db.session.commit()
        
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error deleting conversation: {e}")
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

# --- API route to get available models ---
@app.route('/api/models', methods=['GET'])
def get_models():
    # Common OpenRouter models - in a production app, you would fetch this from OpenRouter API
    models = [
        {"id": "mistralai/mistral-7b-instruct", "name": "Mistral 7B"},
        {"id": "google/gemma-7b-it", "name": "Gemma 7B"},
        {"id": "anthropic/claude-3-haiku", "name": "Claude 3 Haiku"},
        {"id": "meta-llama/llama-3-8b-instruct", "name": "LLaMA 3 8B"},
        {"id": "openai/gpt-3.5-turbo", "name": "GPT-3.5 Turbo"},
        {"id": "anthropic/claude-3-opus", "name": "Claude 3 Opus"},
        {"id": "anthropic/claude-3-sonnet", "name": "Claude 3 Sonnet"},
        {"id": "google/gemma-2b-it", "name": "Gemma 2B"}
    ]
    return jsonify({"models": models})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
