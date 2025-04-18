from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
import os
import requests

app = Flask(__name__)

# إعداد الاتصال بقاعدة البيانات
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL_EXTERNAL")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# نموذج المستخدم
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)

# نقطة اختبار
@app.route("/")
def index():
    return "API شغالة!"

# إدخال مستخدم جديد
@app.route("/user", methods=["POST"])
def add_user():
    data = request.get_json()
    new_user = User(name=data["name"])
    db.session.add(new_user)
    db.session.commit()
    return jsonify({"message": "User added!"}), 201

# استدعاء OpenRouter
@app.route("/openrouter", methods=["POST"])
def chat_openrouter():
    prompt = request.json.get("prompt", "")
    headers = {
        "Authorization": f"Bearer {os.environ.get('OPENROUTER_API_KEY')}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "mistralai/mixtral-8x7b",
        "messages": [{"role": "user", "content": prompt}]
    }
    r = requests.post("https://openrouter.ai/api/v1/chat/completions", json=payload, headers=headers)
    return r.json()

# استدعاء Gemini
@app.route("/gemini", methods=["POST"])
def chat_gemini():
    prompt = request.json.get("prompt", "")
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    key = os.environ.get("GEMINI_API_KEY")
    r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-pro:generateContent?key={key}", json=payload, headers=headers)
    return r.json()

if __name__ == "__main__":
    app.run(debug=True)
