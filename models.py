from app import db
from datetime import datetime

# جدول المحادثات
class Conversation(db.Model):
    __tablename__ = 'conversations'

    id = db.Column(db.String(36), primary_key=True)  # UUID
    title = db.Column(db.String(100), nullable=False, default="محادثة جديدة")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # علاقة واحد إلى متعدد مع الرسائل
    messages = db.relationship('Message', backref='conversation', lazy=True, cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "messages": [msg.to_dict() for msg in self.messages]
        }

    def add_message(self, role, content):
        """إضافة رسالة للمحادثة"""
        message = Message(
            role=role,
            content=content,
            conversation_id=self.id
        )
        db.session.add(message)
        self.updated_at = datetime.utcnow()
        return message


# جدول الرسائل
class Message(db.Model):
    __tablename__ = 'messages'

    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(20), nullable=False)  # 'user' أو 'assistant'
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # علاقة بالجدول Conversation
    conversation_id = db.Column(db.String(36), db.ForeignKey('conversations.id'), nullable=False)

    def to_dict(self):
        return {
            "role": self.role,
            "content": self.content,
