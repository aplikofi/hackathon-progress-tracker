import os
from datetime import timedelta
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'hackathon-tracker-secret-key')
    
    # Session Expiration & Management (Strict 2-hour lifetime)
    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)
    SESSION_REFRESH_EACH_REQUEST = True
    
    # Strict Multi-User Authentication Credentials from AUTH_USERS
    raw_auth = os.environ.get('AUTH_USERS', '')
    ALLOWED_USERS = {}
    if raw_auth:
        for item in raw_auth.split(','):
            if ':' in item:
                user, pwd = item.split(':', 1)
                if user.strip() and pwd.strip():
                    ALLOWED_USERS[user.strip().lower()] = pwd.strip()
    
    # Database configuration with postgres:// -> postgresql:// conversion
    raw_db_url = os.environ.get('DATABASE_URL')
    if raw_db_url and ('[YOUR-PASSWORD]' in raw_db_url or not raw_db_url.strip()):
        raw_db_url = None  # Fallback to local SQLite until real password is provided
    elif raw_db_url and raw_db_url.startswith("postgres://"):
        raw_db_url = raw_db_url.replace("postgres://", "postgresql://", 1)
    
    SQLALCHEMY_DATABASE_URI = raw_db_url or 'sqlite:///hackathons.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # SQLAlchemy Engine Pool Settings (Crucial for Supabase connection poolers)
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }
    
    # Supabase credentials
    SUPABASE_URL = os.environ.get('SUPABASE_URL')
    SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
    SUPABASE_BUCKET = os.environ.get('SUPABASE_BUCKET', 'attachments')
    
    # Supabase participated events bucket (separate from main attachments bucket)
    SUPABASE_PARTICIPATED_BUCKET = os.environ.get('SUPABASE_PARTICIPATED_BUCKET', '')
    
    # Local fallback file config
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
    PARTICIPATED_UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads', 'participated')
    ALLOWED_EXTENSIONS = {'md', 'pdf'}
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
