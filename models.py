from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

# جدول المستخدمين
class User(UserMixin, db.Model):
    __tablename__ = "users"  # مهم جداً لتفادي تعارض مع الكلمة المحجوزة 'user'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

    def set_password(self, password):
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        from werkzeug.security import check_password_hash
        return check_password_hash(self.password_hash, password)

    def get_id(self):
        return str(self.id)

# جدول المحادثات
class Conversation(db.Model):
    __tablename__ = "conversations"

    id = db.Column(db.String, primary_key=True)
    title = db.Column(db.String(255))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = db.relationship("Message", backref="conversation", lazy=True)

    def add_message(self, role, content):
        message = Message(
            conversation_id=self.id,
            role=role,
            content=content
        )
        db.session.add(message)
        self.updated_at = datetime.utcnow()

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "messages": [msg.to_dict() for msg in self.messages],
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

# جدول الرسائل
class Message(db.Model):
    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.String, db.ForeignKey("conversations.id"), nullable=False)
    role = db.Column(db.String(50))  # user / assistant
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at.isoformat()
        }
