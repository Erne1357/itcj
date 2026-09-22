import os
import json
from functools import lru_cache
from pydantic import Field
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
    #
    # Bump 2026-09-14 (c): fix B1 — `survey.js::applyVisibility` comparaba
    # `values[k] === cond[k]` sin importar que `cond[k]` ahora puede ser una
    # LISTA (`visible_when` con semantica "alguna de estas", ya soportada por
    # `survey_validator.py::is_visible`). Un texto nunca es `===` a un arreglo,
    # así que toda seccion condicionada por una lista quedaba oculta para
    # siempre y el envío final la reportaba "por corregir" sin un solo campo
    # visible en pantalla. Sin el bump, quien ya tenía la encuesta en caché
    # sigue atascado con el JS viejo.
    #
    # Bump 2026-09-15: rediseño de la pantalla de la encuesta de egresados —
    # `public.css` reescribe su bloque (riel de pasos en escritorio y chips en
    # móvil, preguntas en tarjetas, opciones como tiles, escala en chips, barra
    # de acciones) y `titulatec/js/public/survey.js` gana `revealCurrentStep`
    # (deja el chip del paso actual a la vista en móvil). Sin el bump, quien ya
    # tenía la encuesta en caché ve el marcado nuevo con la hoja vieja: sin
    # reglas para `.tt-opt`/`.tt-steps-mark` las opciones salen como casillas
    # sueltas y el indicador de pasos como una lista cruda.
    #
    # Bump 2026-09-15 (2): `public.css` (encuesta compacta en móvil),
    # `js/public/survey.js` (nota «Guardando… / Guardado hh:mm»),
    # `titulatec.css` (estados hover/foco/pulsado de `.tt-btn-*` y la sección de
    # información de requisitos), `js/admin/cotejo-info-editor.js` (nuevo) y
    # `js/shared/titulatec-utils.js` (guarda del puente `htmx:confirm`). Sin el
    # bump, el editor de requisitos y la nota de guardado llegan sin su JS.
    #
    # Bump 2026-09-15 (3): `public.css` gana `.tt-public-bar-back`, el botón
    # «Volver a TitulaTec» de la barra de la encuesta.
    #
    # Bump 2026-09-15 (4): auto-agendado del egresado — `titulatec.css` gana el
    # bloque de la pantalla de cita (`.tt-daybar`/`.tt-daychip`, rejilla de
    # franjas, walk-in) y `js/student/errors.js` pasa a DECODIFICAR
    # `X-Tt-Error`. Sin el bump, el alumno recibe el CSS viejo (las franjas
    # salen sin rejilla) y los mensajes nuevos llegan percent-codificados.
    #
    # Bump 2026-09-16 (5): UI del encargado del auto-agendado — `titulatec.css`
    # gana los tres modos de visibilidad del espacio (`.tt-vis*`), el
    # distintivo «El alumno agendó» dentro de `.tt-seat .meta` y el historial
    # de intentos (`.tt-attempts`). Sin el bump, el editor de espacios pinta
    # los tres radios sin rejilla (caen como una lista cruda de casillas), el
    # distintivo del asiento sale sin contraste y el historial sin separación.
    # Bump 2026-09-16 (6): limpieza de `partials/cita_card.html` — sus ocho
    # `style=` y su `onclick` inline pasan a `titulatec.css` (`.tt-cita-note`,
    # `.tt-cita-when`, `.tt-cita-where`, `.tt-cita-changed`, `.tt-cita-btn` y
    # `.tt-cita-more-sum`, este ultimo para el `<details>` que sustituye al
    # `onclick`). Sin el bump, el alumno recibe el CSS viejo: la tarjeta pierde
    # tamanos y color —el texto cae al del `<body>`— y el nuevo «Solicitar
    # cambio» se pinta como un `<summary>` crudo, con su triangulo y sin
    # objetivo tactil.
    #
    # Bump 2026-09-21: corte a T-soft, ronda de fix 1 (Hallazgo 1) — `titulatec.css`
    # gana `.tt-handoff-note` (padding-bottom 88px, mismo colchon que `.tt-canvas`)
    # en el copy de T-soft del panel del acordeon del dashboard del alumno
    # (deliberadamente NO en la tarjeta grande de la fase actual, ver el
    # comentario de la clase). Sin el bump, el FAB standalone del core se sigue
    # montando sobre la ultima linea del aviso cuando el alumno se desplaza
    # hasta el borde de un panel expandido.
    #
    # Bump 2026-09-21 (2): ronda de fix 2 -- la medicion de la ronda anterior
    # (117px de holgura, tarjeta grande sin `.tt-handoff-note`) solo se probo a
    # 390x844. A 375x667 (iPhone SE) esa misma tarjeta, con la fase 3 actual y
    # SIN SCROLLEAR, ya solapaba el FAB en -59.5px: el FAB es fixed a 80px del
    # fondo del VIEWPORT, asi que la holgura depende del alto, no del ancho.
    # Pero `.tt-handoff-note` (padding DESPUES del texto) sola no alcanza ahi:
    # el alumno nunca desplaza para ver esta tarjeta -sale completa desde la
    # primera pintura-, asi que el padding de despues no mueve el texto, que
    # ya esta pintado en su posicion final. `titulatec.css` gana ademas
    # `.tt-handoff-note--hero` (margin-top 88px, ANTES del texto -reemplaza el
    # `mt-3` que ya traia el parrafo, no se le suma-) solo para la tarjeta
    # grande (dashboard.html), que empuja el parrafo bajo el FAB en vez de
    # encima. Sin el bump, la tarjeta sigue sin colchon en pantallas bajas y
    # el FAB tapa el aviso ya al cargar la pagina, sin necesidad de que el
    # alumno haga nada.
    #
    # Bump 2026-09-21 (3): la carrera pasa a ser obligatoria y siempre del
    # catálogo en la inscripción pública (elimina el caso de raíz de "mi
    # carrera no aparece", que dejaba la solicitud sin `program_id` y por
    # tanto invisible para todo encargado de carrera). `enroll_form.html`
    # pierde la opción `__other__` y la fila de texto libre; `js/public/
    # enroll.js` queda vacío (esa era su única lógica). Sin el bump, quien ya
    # tenía la página en caché sigue corriendo el JS viejo, que ahora apunta a
    # un nodo (`program-text-wrap`) que ya no existe en el HTML.
    #
    # Bump 2026-09-21 (4): ronda de fix 1 sobre el bump (3) -- `public.css`
    # pierde la regla `.tt-enroll-row[hidden]` (sección 5) y toda la sección
    # "9. Movimiento" (la animación de `[data-tt-enroll="program-text-wrap"]`),
    # las dos huérfanas desde que ese campo se eliminó del HTML. Sin el bump,
    # quien ya tenía la hoja en caché conserva reglas muertas que no hacen daño
    # hoy pero confunden al próximo diff.
    #
    # Bump 2026-09-21 (5): arregla el desalineamiento de Carrera/Número de
    # control en `.tt-enroll-row--pair` (`public.css`, sección 5). Convierte
    # esa fila en subgrid de 4 pistas -etiqueta/aviso/campo/error- con
    # colocación explícita por hijo, para que un aviso (`.tt-hint`) en una
    # sola celda ya no empuje su campo una pista más abajo que el de la celda
    # vecina. Solo CSS, sin cambios de HTML. Sin el bump, quien ya tenía la
    # hoja en caché sigue viendo el `<select>` de Carrera desalineado.
    #
    # Bump 2026-09-21 (6): ronda de fix 1 sobre el bump (5) -- el orden de
    # pistas del subgrid de `.tt-enroll-row--pair` (`public.css`, sección 5)
    # pasa de etiqueta/aviso/campo/error a etiqueta/campo/error/aviso, porque
    # el orden anterior dejaba la etiqueta de Número de control flotando
    # ~79px sobre su `<input>` (la pista de aviso, vacía en esa celda, caía
    # ENTRE etiqueta y campo). El aviso de Carrera se mueve en
    # `enroll_form.html` de antes a después del `<select>` (y del bloque de
    # error), y `public.css` (bloque 6) gana la regla `.tt-field ~ .tt-hint`
    # para darle margen arriba en vez de abajo. Sin el bump, quien ya tenía
    # la hoja en caché sigue viendo la etiqueta flotando.
    #
    # Bump 2026-09-22: "Partir ticket" en la pantalla de asignación de
    # helpdesk. `js/admin/assign_tickets.js` gana el modal de partir
    # (`openSplitTicketModal`, tarjetas de parte y envío a
    # `POST /tickets/{id}/split`) y además da `source` propio a cada petición de
    # `refreshLists()` (sin él htmx encolaba las tres en <body> y la pestaña
    # Asignado nunca se recargaba); `css/admin/assign_tickets.css` gana los
    # estilos `.hd-split-*` y deja pasar los clics por el contenedor de toasts.
    # Sin el bump, quien ya tenía la página en caché recibe el HTML nuevo, con
    # el botón "Partir" en cada tarjeta, contra el JS viejo que no define
    # `openSplitTicketModal`: el botón no hace nada y solo deja un
    # ReferenceError en la consola.
    STATIC_VERSION: str = "1.0.1111562"

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

    # Logging (itcj2/observability/logging_config.py). `json` = una línea JSON
    # por registro con el contexto de la petición (lo que Loki espera en prod);
    # `text` = legible para dev (docker-compose.dev.yml lo pone, R5). Un valor
    # inválido tumba el arranque: configure_logging() corre en create_app().
    # LOG_LEVEL=WARNING calla los logger.info de la app sin tocar código (R6);
    # la línea por petición (`itcj2.access`) sale siempre.
    LOG_FORMAT: str = "json"
    LOG_LEVEL: str = "INFO"

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

    # Auto-agendado de la cita de cotejo por el egresado (spec 2026-09-15).
    # D8: agenda hasta 1 h antes de la franja y cancela hasta 2 h antes. Las dos
    # ventanas son SOLO del alumno; el encargado no tiene límite de tiempo.
    # D9: tope de cancelaciones PROPIAS (las del encargado no le consumen cupo).
    # Al llegar al tope pierde el auto-agendado y pasa al cubo "Requieren que
    # les agendes" de la cola del encargado — sigue pudiendo llegar sin cita a
    # un espacio abierto, que es otra cosa (`can_walkin`).
    TITULATEC_SELF_BOOK_MIN_LEAD_MINUTES: int = 60
    TITULATEC_SELF_CANCEL_MIN_LEAD_MINUTES: int = 120
    TITULATEC_SELF_CANCEL_MAX: int = 3

    # Corte a T-soft (spec 2026-09-21): primera fase que ya NO se opera en esta
    # app -- de ahí en adelante el proceso lo atiende el Departamento de
    # Titulación en su propio sistema (T-soft). 9 la desactiva (el catálogo real
    # va de 0 a 8, así que ninguna fase legítima la alcanza).
    # Piso en 3 (arreglo A6, revision final 2026-09-21): la fase 2 es la
    # LIBERACION hacia T-soft (`PhaseService.approve_phase(2)`, mueve
    # `current_phase` de 2 a 3) y SIEMPRE debe poder aprobarse -- un 0, 1 o 2
    # por error congelaria tambien esa liberacion, y el proceso dejaria de
    # avanzar para todo el mundo sin decir por que (`_transition_error`/
    # `_student_action_error` comparan `phase_number >= _handoff_phase()`
    # ANTES que cualquier otra regla). `Field(ge=3)` hace que un valor invalido
    # truene fuerte al arrancar (`get_settings()`), no en silencio a media
    # operacion.
    TITULATEC_HANDOFF_PHASE: int = Field(default=3, ge=3)

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
