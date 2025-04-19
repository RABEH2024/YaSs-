from app import db # استيراد db من app.py الذي سيتم إنشاؤه لاحقًا
from datetime import datetime, timezone
import uuid

# --- Base Class for SQLAlchemy models (إذا لم تكن معرفة في app.py) ---
# from sqlalchemy.orm import DeclarativeBase
# class Base(DeclarativeBase):
#     pass
# db = SQLAlchemy(model_class=Base) # تعريف db هنا إذا لم يكن في app.py

class Conversation(db.Model):
    __tablename__ = 'conversation'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = db.Column(db.String(100), nullable=False, default="محادثة جديدة")
    # يمكنك إضافة user_id هنا إذا أردت ربط المحادثات بالمستخدمين لاحقًا
    # user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # علاقة واحد إلى متعدد مع الرسائل، مع الحذف التلقائي للرسائل عند حذف المحادثة
    messages = db.relationship('Message', backref='conversation', lazy='dynamic', cascade="all, delete-orphan")

    def to_dict(self, include_messages=False):
        """تحويل بيانات المحادثة إلى قاموس."""
        data = {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_messages:
            # جلب الرسائل مرتبة حسب وقت الإنشاء
            msgs = self.messages.order_by(Message.created_at.asc()).all()
            data["messages"] = [msg.to_dict() for msg in msgs]
        return data

    def add_message(self, role, content):
        """دالة مساعدة لإضافة رسالة لهذه المحادثة."""
        message = Message(role=role, content=content, conversation_id=self.id)
        db.session.add(message)
        self.updated_at = datetime.now(timezone.utc) # تحديث وقت آخر تعديل للمحادثة
        return message

class Message(db.Model):
    __tablename__ = 'message'
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(20), nullable=False)  # 'user' or 'assistant' or 'error'
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    # مفتاح خارجي يربط الرسالة بالمحادثة، مع الحذف المتتالي
    conversation_id = db.Column(db.String(36), db.ForeignKey('conversation.id', ondelete='CASCADE'), nullable=False)

    def to_dict(self):
        """تحويل بيانات الرسالة إلى قاموس."""
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

# يمكنك إضافة نموذج User هنا إذا احتجت إليه لاحقًا
# class User(db.Model):
#     __tablename__ = 'user'
#     id = db.Column(db.Integer, primary_key=True)
#     username = db.Column(db.String(80), unique=True, nullable=False)
#     # ... other fields
#     conversations = db.relationship('Conversation', backref='user', lazy=True)
