# ==================================================
# === main.py ===
# ==================================================
import sys
from app import app, db # استيراد app و db من app.py

def create_tables():
    """Creates database tables if they don't exist."""
    with app.app_context():
        print("Attempting to create database tables...")
        try:
            db.create_all()
            print("Database tables created successfully or already exist.")
        except Exception as e:
            print(f"Error creating database tables: {e}")
            # Consider exiting if table creation fails in production setup
            # sys.exit(1)

if __name__ == '__main__':
    # Check for command line argument to create tables (for Render build command)
    if len(sys.argv) > 1 and sys.argv[1] == 'db_create_all':
        create_tables()
        sys.exit(0) # Exit after creating tables

    # Run the Flask development server (Gunicorn is used in production via render.yaml)
    print("Starting Flask development server on http://0.0.0.0:5000")
    # Use debug=False for production-like testing, True for development features
    is_development = os.environ.get("FLASK_ENV", "production") == "development"
    app.run(host='0.0.0.0', port=5000, debug=is_development)

# ==================================================
# ============ END OF FILE 2 =======================
# ==============
