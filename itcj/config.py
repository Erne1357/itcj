# itcj/config.py
import os

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "mysecretkey")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "my_jwt_secret")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///default.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    COOKIE_SECURE = False
    COOKIE_SAMESITE = "Lax"
    JWT_EXPIRES_HOURS = 12
    JWT_REFRESH_THRESHOLD_SECONDS = 2 * 3600  # 2 horas para refresh JWT
    STATIC_VERSION = "1.0.11114675"

    INSTANCE_PATH = os.path.abspath('instance')
    HELPDESK_UPLOAD_PATH = os.path.join(INSTANCE_PATH, 'apps', 'helpdesk')
    HELPDESK_MAX_FILE_SIZE = 3 * 1024 * 1024  # 3MB
    HELPDESK_ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}