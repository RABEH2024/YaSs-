from app import db # استيراد db من app.py
from datetime import datetime, timezone
import uuid

class Conversation(db.Model):
    __tablename__ = 'conversation'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = db.Column(db.String(100), nullable=False, default="محادثة جديدة")
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    messages = db.relationship('Message', backref='conversation', lazy='dynamic', cascade="all, delete-orphan")

    def to_dict(self, include_messages=False):
        data = { "id": self.id, "title": self.title, "created_at": self.created_at.isoformat() if self.created_at else None, "updated_at": self.updated_at.isoformat() if self.updated_at else None, }
        if include_messages:
            msgs = self.messages.order_by(Message.created_at.asc()).all()
            data["messages"] = [msg.to_dict() for msg in msgs]
        return data

    def add_message(self, role, content):
        message = Message(role=role, content=content, conversation_id=self.id)
        db.session.add(message)
        self.updated_at = datetime.now(timezone.utc)
        return message

class Message(db.Model):
    __tablename__ = 'message'
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    conversation_id = db.Column(db.String(36), db.ForeignKey('conversation.id', ondelete='CASCADE'), nullable=False)

    def to_dict(self):
        return { "id": self.id, "role": self.role, "content": self.content, "created_at": self.created_at.isoformat() if self.created_at else None }
