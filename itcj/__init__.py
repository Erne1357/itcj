# itcj/__init__.py
from flask import Flask, request, jsonify, render_template, redirect, url_for, g, current_app
from .core.extensions import db, migrate
from werkzeug.exceptions import HTTPException
from .core.utils.jwt_tools import encode_jwt, decode_jwt
from itcj.core.utils.role_home import role_home
from itcj.core.services.authz_service import user_roles_in_app
import time
from werkzeug.middleware.proxy_fix import ProxyFix

def create_app():
    # Crea la app Flask con template folder personalizado
    app = Flask(__name__, 
                instance_relative_config=True,
                template_folder='core/templates')
    
    # Configuración de la aplicación
    app.config.from_object('itcj.config.Config')
    app.config.from_pyfile('config.py', silent=True)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    # Cargar manifiesto de estaticos para versionado por archivo
    from .config import Config
    app.config['_STATIC_MANIFEST'] = Config.load_static_manifest()

    # Inicializa las extensiones
    db.init_app(app)
    migrate.init_app(app, db)

    from .core.sockets import init_socketio
    socketio = init_socketio(app)
    app.extensions['socketio'] = socketio

    # Registrar blueprints
    register_blueprints(app)
    register_error_handlers(app)

    #Registrar comandos
    from itcj.apps.helpdesk.commands import register_helpdesk_commands
    from itcj.apps.agendatec.commands import register_agendatec_commands
    from itcj.core.commands import register_commands
    register_helpdesk_commands(app)
    register_agendatec_commands(app)
    register_commands(app)


    @app.before_request
    def load_current_user():
        g.current_user = None
        token = request.cookies.get("itcj_token")
        data = decode_jwt(token) if token else None
        if data:
            g.current_user = data
            now = int(time.time())
            if data.get("exp", 0) - now < app.config["JWT_REFRESH_THRESHOLD_SECONDS"]:
                g._refresh_token = True
        else:
            g._refresh_token = False

    @app.after_request
    def maybe_refresh_cookie(resp):
        if getattr(g, "_refresh_token", False) and g.current_user:
            new_token = encode_jwt(
                {"sub": g.current_user["sub"], "role": list(user_roles_in_app(int(g.current_user["sub"]), 'itcj')),
                 "cn": g.current_user.get("cn"), "name": g.current_user.get("name")},
                hours=current_app.config["JWT_EXPIRES_HOURS"]
            )
            resp.set_cookie(
                "itcj_token", new_token, httponly=True,
                samesite=current_app.config["COOKIE_SAMESITE"],
                secure=current_app.config["COOKIE_SECURE"],
                max_age=current_app.config["JWT_EXPIRES_HOURS"] * 3600,
                path="/"
            )
        return resp

    @app.teardown_request
    def cleanup_db(exc=None):
        if exc is not None:
            try:
                db.session.rollback()
            except Exception:
                pass
        try:
            db.session.remove()
        except Exception:
            pass

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/")
    def home():
        if g.current_user:
            user_id = int(g.current_user["sub"])
            # Obtener roles en todas las apps
            roles_itcj = set(user_roles_in_app(user_id, 'itcj'))
            roles_agendatec = set(user_roles_in_app(user_id, 'agendatec'))
            # Si solo tiene rol student en agendatec, redirigir directo
            if (not roles_itcj or roles_itcj == {"student"}) and "student" in roles_agendatec:
                return redirect("/agendatec/student/home")
            # Si tiene roles en itcj, usar la lógica normal
            return redirect(role_home(roles_itcj or roles_agendatec))
        return redirect(url_for("pages_core.pages_auth.login_page"))
    
    @app.context_processor
    def inject_globals():
        manifest = current_app.config.get("_STATIC_MANIFEST", {})
        fallback = current_app.config.get("STATIC_VERSION", "1.0.0")
        def sv(app_name: str, filename: str) -> str:
            """Retorna el hash de un archivo estatico especifico.

            Uso en template:
                {{ url_for('static', ...) }}?v={{ sv('agendatec', 'js/toast.js') }}

            Args:
                app_name: Nombre de la app (core, agendatec, helpdesk)
                filename: Ruta del archivo relativa al directorio static de la app

            Returns:
                Hash del archivo o fallback global si no existe en el manifiesto
            """
            return manifest.get(app_name, {}).get(filename, fallback)

        def _icon_for(label: str) -> str:
            """Iconos para navegación global (no específicos de apps)"""
            lbl = (label or "").lower()
            if "dashboard" in lbl: return "bi-grid"
            if "configuración" in lbl: return "bi-gear-fill"
            if "perfil" in lbl: return "bi-person"
            if "logout" in lbl: return "bi-box-arrow-right"
            return "bi-circle"

        def is_active(url: str) -> bool:
            p = request.path
            return p == url or p.startswith(url + "/")

        def nav_for(role: str | None):
            """Navegación GLOBAL del sistema (no específica de apps)"""
            if not role:
                return []

            global_nav = []

            # Navegación para admins (configuración del sistema)
            if role == "admin":
                global_nav.extend([
                    {"label": "Configuración", "endpoint": "pages_core.pages_config.settings", "roles": ["admin"]},
                ])

            # Agregar navegación de apps específicas aquí si es necesario
            # Por ahora, cada app maneja su propia navegación

            filtered = [item for item in global_nav if role in item["roles"]]

            return [{
                "label": item["label"],
                "endpoint": item["endpoint"],
                "url": url_for(item["endpoint"]),
                "icon": _icon_for(item["label"]),
            } for item in filtered]

        return {
            "current_user": g.current_user,
            "static_version": fallback,  # Compatibilidad (se puede eliminar despues)
            "sv": sv,                    # Nueva funcion: sv('app', 'ruta/archivo.js')
            "nav_for": nav_for,
            "is_active": is_active,
        }

    return app, socketio

def register_blueprints(app):
    """Registro centralizado de todos los blueprints"""
    
    # Core APIs y páginas
    from itcj.core import api_core_bp, pages_core_bp
    app.register_blueprint(api_core_bp, url_prefix="/api/core/v1")
    app.register_blueprint(pages_core_bp, url_prefix="/itcj")
    
    # Apps específicas
    from itcj.apps.agendatec import agendatec_api_bp, agendatec_pages_bp
    from itcj.apps.helpdesk import helpdesk_api_bp, helpdesk_pages_bp
    
    # APIs de apps
    app.register_blueprint(agendatec_api_bp, url_prefix="/api/agendatec/v1")
    app.register_blueprint(helpdesk_api_bp, url_prefix="/api/help-desk/v1")
    
    # Páginas de apps
    app.register_blueprint(agendatec_pages_bp, url_prefix="/agendatec")
    app.register_blueprint(helpdesk_pages_bp, url_prefix="/help-desk")

def register_error_handlers(app):
    """Manejo centralizado de errores"""
    ERROR_MESSAGES = {
        400: {
            'title': 'Solicitud Incorrecta',
            'message': 'La solicitud no pudo ser procesada debido a un error del cliente.'
        },
        401: {
            'title': 'No Autorizado',
            'message': 'Necesitas autenticarte para acceder a este recurso.'
        },
        403: {
            'title': 'Acceso Prohibido',
            'message': 'No tienes permisos para acceder a este recurso.'
        },
        404: {
            'title': 'Página No Encontrada',
            'message': 'El recurso que buscas no existe o ha sido movido.'
        },
        405: {
            'title': 'Método No Permitido',
            'message': 'El método HTTP utilizado no está permitido para este recurso.'
        },
        409: {
            'title': 'Conflicto de Recurso',
            'message': 'La solicitud no pudo completarse debido a un conflicto con el estado actual del recurso.'
        },
        413: {
            'title': 'Carga Demasiado Grande',
            'message': 'El archivo o datos enviados superan el tamaño máximo permitido.'
        },
        415: {
            'title': 'Tipo de Contenido No Soportado',
            'message': 'El formato de los datos enviados no es compatible con este servicio.'
        },
        429: {
            'title': 'Demasiadas Solicitudes',
            'message': 'Has excedido el límite de solicitudes permitidas. Intenta de nuevo más tarde.'
        },
        500: {
            'title': 'Error Interno del Servidor',
            'message': 'Algo salió mal en nuestros servidores. Estamos trabajando para solucionarlo.'
        },
        502: {
            'title': 'Puerta de Enlace Incorrecta',
            'message': 'El servidor recibió una respuesta inválida del servidor upstream.'
        },
        503: {
            'title': 'Servicio No Disponible',
            'message': 'El servidor no está disponible temporalmente. Intenta de nuevo más tarde.'
        },
        504: {
            'title': 'Tiempo de Espera Agotado',
            'message': 'El servidor tardó demasiado tiempo en responder. Intenta de nuevo más tarde.'
        }
    }

    def wants_json():
        return request.path.startswith("/api/")

    def render_error_page(status_code, error_info):
        return render_template("core/errors/core_error.html",
                             error_code=status_code,
                             error_title=error_info['title'],
                             error_message=error_info['message']), status_code

    @app.errorhandler(HTTPException)
    def handle_http_exception(e: HTTPException):
        code = e.code or 500
        error_info = ERROR_MESSAGES.get(code, {
            'title': e.name or "Error",
            'message': e.description or "Ha ocurrido un error inesperado."
        })
        
        if wants_json():
            payload = {"error": getattr(e, "name", "error"), "status": code}
            if getattr(e, "description", None):
                payload["detail"] = e.description
            return jsonify(payload), code

        if code == 401:
            return redirect(url_for("pages_core.pages_auth.login_page"))
        page_code = code if code in ERROR_MESSAGES else 500
        error_data = ERROR_MESSAGES.get(page_code, ERROR_MESSAGES[500])
        return render_error_page(page_code, error_data)

    @app.errorhandler(Exception)
    def handle_unexpected(e: Exception):
        app.logger.exception("Unhandled exception")
        if wants_json():
            return jsonify({"error": "internal_error", "status": 500}), 500
        return render_error_page(500, ERROR_MESSAGES[500])

    # Handlers explícitos para códigos comunes
    for code in [400, 401, 403, 404, 405, 409, 413, 415, 429, 500, 502, 503, 504]:
        def _factory(c):
            def _h(_e):
                if wants_json():
                    return jsonify({"error": _e.name if isinstance(_e, HTTPException) else "error", "status": c}), c
                if c == 401:
                    return redirect(url_for("pages_core.pages_auth.login_page"))
                error_data = ERROR_MESSAGES.get(c, {
                    'title': 'Error',
                    'message': 'Ha ocurrido un error inesperado.'
                })
                return render_error_page(c, error_data)
            return _h
        app.register_error_handler(code, _factory(code))