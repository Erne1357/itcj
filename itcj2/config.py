import os
import json
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Static versioning
    # Bump 2026-08-10: la revisión de helpdesk tocó 55 archivos CSS/JS (registro
    # de orígenes, sockets, filtros, detalle de equipo, asignación, home). Sin
    # este bump el navegador serviría los assets viejos desde caché y los
    # cambios no se verían hasta un refresh forzado.
    # Bump 2026-08-25: alta de la app adhoc (Calidad) — nuevos estáticos bajo
    # /static/adhoc/ y ajuste del dashboard del core.
    # Bump 2026-08-27: adjuntos de incidencias (adhoc) — modal de archivos en
    # incidents.js/incidents.html y la clase .adhoc-file-none compartida en
    # work-items.css.
    # Bump 2026-08-28: edición de documentos (adhoc, A14) — documents-panel.js
    # (el modal del alta en modo edición) y documents-panel.css. Va en el mismo
    # commit que el cambio, no después: no hay `static-manifest.json` en el
    # repo, así que `sv()` cae SIEMPRE a esta constante, y nginx sirve
    # /static/adhoc/ con `immutable` a un año (docker/nginx/nginx.prod.conf).
    # Sin bump la URL es byte a byte la misma y el navegador ni revalida: quien
    # ya había abierto el panel seguiría ejecutando el JS anterior —sin el botón
    # "Editar"— hasta un ctrl+F5 que nadie sabe que hace falta.
    # Bump 2026-08-28: flujo de trabajo de tareas (adhoc, B3) — dashboard.js y
    # tasks.js pierden ~760 líneas que se mudaron al módulo nuevo
    # work/workflow-modal.{js,css}, más dashboard.css y tasks.css. Archivos
    # nuevos y archivos adelgazados en el mismo commit: sin bump el navegador
    # ejecuta el dashboard viejo pidiendo funciones que ya no existen ahí.
    # Bump 2026-08-28: revisión de B3 (adhoc) — workflow-modal.js sella cada
    # carga con un testigo de apertura (respuesta vieja pintada en el diálogo
    # nuevo) y tasks.js deja inerte el contador apagado, que hasta ahora caía en
    # el atajo de fila y abría el modal de edición.
    STATIC_VERSION: str = "1.0.1111530"

    # Database
    DATABASE_URL: str = "postgresql+psycopg2://postgres:password@pgbouncer:5432/itcj"

    # Pool SQLAlchemy — POR PROCESO (F2.1). Con uvicorn --workers N cada worker
    # abre su propio pool, así que el techo real es N*(POOL_SIZE+MAX_OVERFLOW).
    # Prod: backend HTTP 8+4 x4 workers = 48; sockets 5+5 = 10. Todo por debajo
    # de max_client_conn=500 de pgbouncer, que multiplexa a 50 backends reales.
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 20

    # Rol del proceso (F2.1 — split HTTP / Socket.IO):
    #   all    → un proceso sirve HTTP + /socket.io/ (dev, tests, CLI: default)
    #   http   → NO monta Socket.IO ni retransmite task_events; solo emite por
    #            Redis. Es el rol de los 4 workers uvicorn de prod.
    #   socket → sirve /socket.io/ y retransmite task_events. 1 solo proceso.
    # Ver docker/compose/docker-compose.prod.yml y docs/infra/RUNBOOK_workers.md
    APP_ROLE: str = "all"

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # Security
    SECRET_KEY: str = "dev"
    JWT_SECRET_KEY: str = "my_jwt_secret"
    JWT_EXPIRES_HOURS: int = 12
    JWT_REFRESH_THRESHOLD_SECONDS: int = 2 * 3600  # 2 horas

    # Authz cache (F1.1) — TTL en segundos del caché read-through de permisos
    # efectivos por (usuario, app) en Redis. Red de seguridad si se omite una
    # invalidación; bajar para refrescar más rápido a costa de más misses.
    AUTHZ_CACHE_TTL: int = 300

    # Presencia (core-config-revamp F6) — ventana en segundos para considerar
    # "activo" a un usuario en los sorted-sets presence:notify:*. La poda ocurre
    # EN LECTURA (presence_service.get_counts); no hay heartbeat.
    PRESENCE_WINDOW_SECONDS: int = 300

    # OAuth de correo (config → email, C6 core-config-revamp): TTL en segundos
    # del nonce anti-CSRF guardado en Redis como oauth:state:{nonce} -> app_key.
    EMAIL_OAUTH_STATE_TTL: int = 600

    # Cookies
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"

    # Secreto del endpoint interno /static-update. Antes NO era campo de Settings
    # y extra="ignore" lo descartaba → el guard nunca disparaba (endpoint abierto).
    # Vacío = fail-closed (rechaza todo) hasta configurarlo.
    DEPLOY_SECRET: str = ""

    # Rate limit de login (contador de FALLOS por IP y por cuenta en ventana móvil).
    LOGIN_FAIL_WINDOW: int = 300          # segundos
    LOGIN_FAIL_MAX_IP: int = 30           # fallos por IP antes de 429
    LOGIN_FAIL_MAX_ACCOUNT: int = 8       # fallos por cuenta antes de 429

    # Environment
    FLASK_ENV: str = "production"
    APP_TZ: str = "America/Ciudad_Juarez"

    # CORS
    CORS_ORIGINS: str = ""

    # Domain
    DOMAIN: str = "http://localhost:8080"

    # Uploads
    INSTANCE_PATH: str = os.path.abspath("instance")
    HELPDESK_UPLOAD_PATH: str = os.path.join(os.path.abspath("instance"), "apps", "helpdesk")
    HELPDESK_RETIREMENT_PATH: str = os.path.join(os.path.abspath("instance"), "apps", "helpdesk", "retirement_requests")
    HELPDESK_MAX_FILE_SIZE: int = 3 * 1024 * 1024
    HELPDESK_ALLOWED_EXTENSIONS: str = "jpg,jpeg,png,gif,webp"
    HELPDESK_MAX_DOCUMENT_SIZE: int = 25 * 1024 * 1024
    HELPDESK_ALLOWED_DOC_EXTENSIONS: str = "xlsx,xls,csv,pdf,doc,docx"
    HELPDESK_MAX_RESOLUTION_FILES: int = 10
    HELPDESK_MAX_COMMENT_FILES: int = 3

    MAINT_UPLOAD_PATH: str = os.path.join(os.path.abspath("instance"), "apps", "maint")
    MAINT_MAX_FILE_SIZE: int = 3 * 1024 * 1024
    MAINT_MAX_PDF_SIZE: int = 10 * 1024 * 1024
    MAINT_ALLOWED_IMAGE_EXTENSIONS: str = "jpg,jpeg,png,gif,webp"
    MAINT_ALLOWED_DOC_EXTENSIONS: str = "pdf"
    MAINT_MAX_RESOLUTION_FILES: int = 5
    MAINT_MAX_COMMENT_FILES: int = 3
    MAINT_AUTO_DELETE_DAYS: int = 7

    VISTETEC_UPLOAD_PATH: str = os.path.join(os.path.abspath("instance"), "apps", "vistetec", "garments")
    VISTETEC_MAX_IMAGE_SIZE: int = 3 * 1024 * 1024
    VISTETEC_ALLOWED_EXTENSIONS: str = "jpg,jpeg,png,webp"

    # TitulaTec — archivos del proceso de titulación.
    # Estructura: instance/apps/titulatec/{convocatoria}/{control_number}/{tipo_documento}.{ext}
    # Solo se conserva la última versión de cada documento (se sobreescribe por nombre fijo).
    TITULATEC_UPLOAD_PATH: str = os.path.join(os.path.abspath("instance"), "apps", "titulatec")
    TITULATEC_MAX_IMAGE_SIZE: int = 3 * 1024 * 1024
    TITULATEC_MAX_PDF_SIZE: int = 10 * 1024 * 1024
    TITULATEC_ALLOWED_IMAGE_EXTENSIONS: str = "jpg,jpeg,png,webp"
    TITULATEC_ALLOWED_DOC_EXTENSIONS: str = "pdf"
    # Umbrales de "días sin moverse" para señalar procesos atorados en la bandeja admin.
    TITULATEC_IDLE_WARN_DAYS: int = 7    # ámbar a partir de aquí
    TITULATEC_IDLE_CRIT_DAYS: int = 14   # rojo (atorado) a partir de aquí

    # Adhoc (Calidad / SGC ISO 9001) — adjuntos de documentos, eventos de
    # programa, comentarios de tarea e indicadores.
    # Estructura: instance/apps/adhoc/{documents,program_events,task_comments,indicators}/{entity_id}/
    ADHOC_UPLOAD_PATH: str = os.path.join(os.path.abspath("instance"), "apps", "adhoc")
    ADHOC_MAX_FILE_SIZE: int = 10 * 1024 * 1024
    ADHOC_ALLOWED_EXTENSIONS: str = "pdf,doc,docx,xls,xlsx,ppt,pptx,jpg,jpeg,png,webp,csv,txt"


    model_config = {"env_file": ".env", "extra": "ignore"}

    def get_cors_origins(self) -> list[str]:
        if self.FLASK_ENV == "development":
            return [
                "http://localhost:8080",
                "http://127.0.0.1:8080",
                "http://localhost:8000",
                "http://127.0.0.1:8000",
                "http://localhost:8001",
                "http://127.0.0.1:8001",
            ]
        if self.CORS_ORIGINS:
            return [o.strip() for o in self.CORS_ORIGINS.split(",")]
        return [
            "https://enlinea.cdjuarez.tecnm.mx",
            "https://siiapec.cdjuarez.tecnm.mx",
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_static_manifest() -> dict:
    """Carga el manifiesto de hashes de archivos estáticos (compartido con Flask)."""
    manifest_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "static-manifest.json",
    )
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}
