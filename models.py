from app import db
from datetime import datetime

# Database models for conversations
class Conversation(db.Model):
    id = db.Column(db.String(36), primary_key=True)  # UUID format
    title = db.Column(db.String(100), nullable=False, default="محادثة جديدة")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # One-to-many relationship with Message
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
        """Helper method to add a message to this conversation"""
        message = Message(role=role, content=content, conversation_id=self.id)
        db.session.add(message)
        self.updated_at = datetime.utcnow()
        return message

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(20), nullable=False)  # 'user' or 'assistant'
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    conversation_id = db.Column(db.String(36), db.ForeignKey('conversation.id'), nullable=False)
    
    def to_dict(self):
        return {
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }
