import os
import json
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Static versioning
    # Bump 2026-09-04 (2): Mantenimiento cambia su icono bootstrap por maint.png
    # en el dashboard de escritorio y en el card movil.
    #
    # Bump 2026-09-04: el icono de Extensiones (directory.png) entra al dashboard
    # de escritorio y al card movil, y cambia `dashboard.js`. Sin bump, el navegador
    # con cache caliente serviria el JS viejo, que genera el tile con el icono
    # lucide en vez de reusar el de la plantilla.
    #
    # Bump 2026-09-03: el expediente del alumno añade `admin/expediente.js` (que
    # carga la base admin) y un bloque nuevo en `titulatec.css` (`.tt-exp-*` y
    # los tonos del historial). Con caché caliente, el acordeón de las 9 fases
    # se serviría sin CSS ni JS: todo abierto, sin poder plegar nada.
    #
    # Bump 2026-09-02: la revisión del admin de TitulaTec tocó `titulatec.css`
    # (retardo e indicador-overlay, `.tt-enter`, las tres zonas de Citas) y tres
    # módulos JS que además pasaron a cargarse desde la base admin
    # (`shared/titulatec-utils.js`, `admin/processes.js`, `admin/appointments.js`).
    # Sin este bump el navegador con caché caliente serviría el CSS/JS viejo
    # contra el HTML nuevo: los filtros de Procesos re-animarían la página, el
    # indicador volvería a parpadear y las Citas se verían sin su rejilla.
    #
    # Bump 2026-08-10: la revisión de helpdesk tocó 55 archivos CSS/JS (registro
    # de orígenes, sockets, filtros, detalle de equipo, asignación, home).
    #
    # Bump 2026-09-08: `titulatec.css` estrena las clases `.tt-win-*` del editor
    # de ventana de la convocatoria. Sin el bump, un navegador con caché caliente
    # sirve el CSS viejo contra el parcial nuevo y el formulario sale con los tres
    # controles estirados a toda la fila.
    #
    # Bump 2026-09-08 (b): la base pública de TitulaTec estrena DOS estáticos,
    # `titulatec/css/public.css` y `titulatec/js/shared/tt-errors.js`. Como no
    # existe `static-manifest.json` en la raíz, `sv()` cae siempre a esta
    # constante: sin el bump, un navegador con caché caliente sirve un 404
    # cacheado de ambos y la página pública sale sin tope de ancho y con el
    # botón mudo ante cualquier error de HTMX.
    #
    # Bump 2026-09-08 (c): `titulatec/css/public.css` gana la capa de la encuesta
    # pública (escala 1-5, errores en línea, secciones). Sin el bump, quien ya
    # abrió una página pública tiene la hoja anterior en caché y el cuestionario
    # sale sin la escala y con la trampa a la vista.
    #
    # Bump 2026-09-10: la Tarea 13 estrena `titulatec/js/public/survey.js`
    # (borrador local + autosave). El archivo no existía antes de hoy: sin el
    # bump, quien ya tenía la página pública abierta en caché sirve un 404
    # cacheado del script y se queda sin autoguardado ni fusión del borrador
    # local, en silencio -sin ningún error visible en pantalla-.
    #
    # Bump 2026-09-10 (b): la Tarea 14 hace que `auth.js` honre `?next=` (login
    # a media encuesta de egresados, TitulaTec) y `login.html` estrena el
    # atributo `data-next`. Sin el bump, quien ya tiene `/itcj/login` en caché
    # sigue sirviendo el `auth.js` viejo, que ignora `data-next` y manda
    # siempre a la home por rol: el `?next=` del banner de la encuesta se ve
    # en el HTML pero no se usa.
    #
    # Bump 2026-09-10 (c): la Tarea 19 estrena el formulario público de
    # inscripción — `titulatec/js/public/enroll.js` (nuevo) y una capa nueva en
    # `titulatec/css/public.css` (`.tt-field-error`, `.tt-enroll*`, `.tt-h1`).
    # Sin el bump, quien ya tenía una página pública abierta en caché sirve un
    # 404 cacheado del script nuevo y la hoja vieja: el campo de "carrera no
    # aparece" no alterna y los errores en línea salen sin estilo.
    #
    # Bump 2026-09-11: Tarea 27 relocaliza `.tt-field--xs` dentro de
    # `titulatec.css` (de una regla suelta al final del archivo a modificador
    # de `.tt-field` en INPUTS/FORM), para que `test_citas_sistema_visual.py`
    # deje de contarla como parte del bloque de Citas. El selector y el estilo
    # computado no cambian, pero el archivo sí, así que se bumpea igual.
    #
    # Bump 2026-09-14: Tarea 3 de la encuesta de egresados convierte
    # `survey_form.html` en un asistente por pasos — `public.css` estrena
    # `.tt-steps*` (indicador de progreso) y `.tt-survey-actions--steps`
    # (Atrás/Siguiente), y `titulatec/js/public/survey.js` gana el manejo de
    # `tt_step` y el foco al cambiar de paso. Sin el bump, quien ya tenía la
    # encuesta en caché sigue viendo el JS/CSS viejos: los botones nuevos
    # postearían al formulario completo en vez de a `/paso`, y el localStorage
    # arrastraría un `tt_step` que el HTML nuevo ya no espera ahí.
    #
    # Bump 2026-09-14 (b): ronda 2 de la Tarea 3 — el indicador de progreso
    # deja de ser decorativo (`.tt-steps-list`/`.tt-steps-item`/`.tt-steps-link`
    # nuevas en `public.css`, reemplazan a `.tt-steps-bar`/`.seg`) para poder
    # saltar directo a cualquier paso ya visitado. Sin el bump, la hoja vieja
    # en caché no trae ninguna regla para `.tt-steps-link` y el paso ya
    # visitado se ve como texto plano sin pista de que es clicable.
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


    model_config = {"env_file": ".env", "extra": "ignore"}

    def _extra_cors_origins(self) -> list[str]:
        """Orígenes de `CORS_ORIGINS`, sin vacíos ni duplicados de orden."""
        if not self.CORS_ORIGINS:
            return []
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    def get_cors_origins(self) -> list[str]:
        if self.FLASK_ENV == "development":
            # En dev, `CORS_ORIGINS` SE SUMA a los locales en vez de ignorarse.
            # Antes esta rama devolvía la lista fija y salía, así que poner la
            # variable en el .env no tenía ningún efecto en desarrollo: es justo
            # donde hace falta al exponer el entorno por un túnel para que alguien
            # pruebe desde fuera.
            base = [
                "http://localhost:8080",
                "http://127.0.0.1:8080",
                "http://localhost:8000",
                "http://127.0.0.1:8000",
                "http://localhost:8001",
                "http://127.0.0.1:8001",
            ]
            return base + [o for o in self._extra_cors_origins() if o not in base]
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
