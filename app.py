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

# --- SQLAlchemy Base ---
class Base(DeclarativeBase):
    pass

# --- Initialize Flask app ---
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "yasmin-secret")

# --- Database configuration ---
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///local.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(model_class=Base)
db.init_app(app)

# --- Models import ---
with app.app_context():
    from models import Conversation, Message
    db.create_all()

@app.route("/")
def index():
    return render_template("index.html", app_title="Yasmin GPT Chat")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
