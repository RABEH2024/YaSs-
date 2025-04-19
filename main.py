import sys
import os
from app import app, db # استيراد app و db من app.py

def create_tables():
    """Creates database tables if they don't exist."""
    with app.app_context():
        print("Attempting to create database tables...")
        try:
            # استيراد النماذج داخل السياق للتأكد من تهيئة التطبيق
            from models import Conversation, Message
            db.create_all()
            print("Database tables created successfully or already exist.")
        except Exception as e:
            print(f"Error creating database tables: {e}")
            sys.exit(1) # الخروج إذا فشل إنشاء الجداول

if __name__ == '__main__':
    # Check for command line argument to create tables (for Render build command)
    if len(sys.argv) > 1 and sys.argv[1] == 'db_create_all':
        create_tables()
        sys.exit(0) # Exit after creating tables

    # Run the Flask development server
    # Gunicorn will be used in production via render.yaml
    print("Starting Flask development server on http://0.0.0.0:5000")
    # Set debug based on environment, default to False for safety
    is_development = os.environ.get("FLASK_ENV", "production").lower() == "development"
    # ملاحظة: لا تقم بتشغيل debug=True في بيئة الإنتاج على Render
    app.run(host='0.0.0.0', port=5000, debug=is_development)
