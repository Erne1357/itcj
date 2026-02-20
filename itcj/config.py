# itcj/config.py
import os
import json

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "mysecretkey")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "my_jwt_secret")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///default.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    COOKIE_SECURE = False
    COOKIE_SAMESITE = "Lax"
    JWT_EXPIRES_HOURS = 12
    JWT_REFRESH_THRESHOLD_SECONDS = 2 * 3600  # 2 horas para refresh JWT
    STATIC_VERSION = "1.0.11114786"

    INSTANCE_PATH = os.path.abspath('instance')
    HELPDESK_UPLOAD_PATH = os.path.join(INSTANCE_PATH, 'apps', 'helpdesk')
    HELPDESK_MAX_FILE_SIZE = 3 * 1024 * 1024  # 3MB (imágenes)
    HELPDESK_ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
    HELPDESK_MAX_DOCUMENT_SIZE = 25 * 1024 * 1024    # 25MB (documentos: xlsx, pdf, doc, etc.)
    HELPDESK_ALLOWED_DOC_EXTENSIONS = {'xlsx', 'xls', 'csv', 'pdf', 'doc', 'docx'}
    HELPDESK_MAX_RESOLUTION_FILES = 10
    HELPDESK_MAX_COMMENT_FILES = 3
    HELPDESK_AUTO_DELETE_DAYS = 2

    VISTETEC_UPLOAD_PATH = os.path.join(INSTANCE_PATH, 'apps', 'vistetec', 'garments')
    VISTETEC_MAX_IMAGE_SIZE = 3 * 1024 * 1024  # 10MB (cliente comprime, servidor re-comprime)
    VISTETEC_ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}

    @staticmethod
    def load_static_manifest():
        """Carga el manifiesto de hashes de archivos estaticos.

        El manifiesto es generado por docker/scripts/generate-static-manifest.sh
        durante el deploy y contiene hashes MD5 de cada archivo estatico.

        Returns:
            dict: Manifiesto con estructura {app: {archivo: hash, ...}, ...}
        """
        manifest_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'static-manifest.json'
        )
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"WARN: No se pudo cargar static-manifest.json: {e}")
        return {}