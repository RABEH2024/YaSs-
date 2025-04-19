from datetime import datetime
from app import db

class Conversation(db.Model):
    __tablename__ = 'conversations'

    id = db.Column(db.String, primary_key=True)
    title = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = db.relationship('Message', backref='conversation', cascade='all, delete-orphan')

    def add_message(self, role, content):
        message = Message(
            conversation_id=self.id,
            role=role,
            content=content
        )
        db.session.add(message)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "messages": [msg.to_dict() for msg in self.messages],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

class Message(db.Model):
    __tablename__ = 'messages'

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.String, db.ForeignKey('conversations.id'), nullable=False)
    role = db.Column(db.String(20))  # 'user' or 'assistant'
    content = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }
