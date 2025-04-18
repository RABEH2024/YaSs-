# This script is primarily intended to be run during the build process on Render
# to ensure database tables are created.

from app import app, db

print("Attempting to initialize database...")
try:
    # Use app_context to access application settings and database
    with app.app_context():
        # Import models inside the context JUST before create_all
        # This ensures they are registered with SQLAlchemy metadata
        from models import Conversation, Message
        print("Creating database tables if they don't exist...")
        db.create_all()
        print("Database tables checked/created successfully.")
except ImportError as e:
     print(f"Import Error during DB initialization: {e}")
     print("Ensure models.py exists and defines Conversation and Message.")
     # Re-raise to fail the build if critical models are missing
     raise e
except Exception as e:
    # Log any other exceptions during DB setup
    print(f"Error during database table creation: {e}")
    # Re-raise the exception to make the build process fail if DB setup fails
    raise e

print("Database initialization script finished.")

# Do NOT include app.run() here for production deployment with Gunicorn.
# The 'web' process in Procfile (gunicorn app:app) handles running the app.
