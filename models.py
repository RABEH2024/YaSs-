from app import db
from datetime import datetime, timezone

# Database models for conversations
class Conversation(db.Model):
    id = db.Column(db.String(36), primary_key=True)  # UUID format
    title = db.Column(db.String(100), nullable=False, default="محادثة جديدة")
    # Use timezone-aware datetime
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # One-to-many relationship with Message
    # Cascade delete means if a Conversation is deleted, its Messages are also deleted.
    messages = db.relationship('Message', backref='conversation', lazy='dynamic', cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            # Note: 'messages' might be large. Fetch them separately if needed via the relation or dedicated query.
            # If lazy='dynamic', self.messages is a query object.
            # "messages": [msg.to_dict() for msg in self.messages.order_by(Message.created_at).all()]
        }

    def add_message(self, role, content):
        """Helper method to add a message to this conversation"""
        message = Message(role=role, content=content, conversation_id=self.id)
        # The 'updated_at' of the conversation is handled by onupdate
        db.session.add(message)
        # No need to return message unless specifically required by caller
        # We commit outside this helper usually

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(20), nullable=False)  # 'user' or 'assistant'
    content = db.Column(db.Text, nullable=False)
    # Use timezone-aware datetime
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    conversation_id = db.Column(db.String(36), db.ForeignKey('conversation.id', ondelete='CASCADE'), nullable=False)

    def to_dict(self):
        return {
            "id": self.id, # Add ID if useful for frontend updates
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }
