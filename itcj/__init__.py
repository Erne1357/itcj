# itcj/__init__.py
from flask import Flask, request, jsonify, render_template, redirect, url_for, g, current_app
from .core.extensions import db, migrate
from werkzeug.exceptions import HTTPException
from .core.utils.jwt_tools import encode_jwt, decode_jwt
from itcj.core.utils.role_home import role_home
import time
from werkzeug.middleware.proxy_fix import ProxyFix

def create_app():
    # Crea la app Flask
    app = Flask(__name__, instance_relative_config=True)
    
    # Configuración de la aplicación
    app.config.from_object('itcj.config.Config')
    app.config.from_pyfile('config.py', silent=True)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    # Inicializa las extensiones
    db.init_app(app)
    migrate.init_app(app, db)

    from .core.sockets import init_socketio
    socketio = init_socketio(app)
    app.extensions['socketio'] = socketio

    # Registrar blueprints
    register_blueprints(app)
    register_error_handlers(app)

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
                {"sub": g.current_user["sub"], "role": g.current_user["role"],
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
            return redirect(role_home(g.current_user.get("role")))
        return redirect(url_for("pages_core.pages_auth.login_page"))
    
    @app.context_processor
    def inject_globals():
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
            "static_version": current_app.config.get("STATIC_VERSION", "1.0.0"),
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
    from itcj.apps.tickets import tickets_api_bp, tickets_pages_bp
    
    # APIs de apps
    app.register_blueprint(agendatec_api_bp, url_prefix="/api/agendatec/v1")
    app.register_blueprint(tickets_api_bp, url_prefix="/api/tickets/v1")
    
    # Páginas de apps
    app.register_blueprint(agendatec_pages_bp, url_prefix="/agendatec")
    app.register_blueprint(tickets_pages_bp, url_prefix="/tickets")

def register_error_handlers(app):
    """Manejo centralizado de errores"""
    MESSAGES = {
        400: "Solicitud inválida",
        401: "No autenticado", 
        403: "Acceso prohibido",
        404: "Recurso no encontrado",
        405: "Método no permitido",
        409: "Conflicto de recurso",
        413: "Carga demasiado grande",
        415: "Tipo de contenido no soportado",
        429: "Demasiadas solicitudes",
        500: "Error interno del servidor",
        502: "Puerta de enlace inválida",
        503: "Servicio no disponible",
        504: "Tiempo de espera agotado",
    }

    def wants_json():
        return request.path.startswith("/api/")

    def render_error_page(status_code, message):
        return render_template("errors/error_page.html",
                             code=status_code,
                             message=message), status_code

    @app.errorhandler(HTTPException)
    def handle_http_exception(e: HTTPException):
        code = e.code or 500
        msg = MESSAGES.get(code, e.name or "Error")
        
        if wants_json():
            payload = {"error": getattr(e, "name", "error"), "status": code}
            if getattr(e, "description", None):
                payload["detail"] = e.description
            return jsonify(payload), code

        if code == 401:
            return redirect(url_for("pages_core.pages_auth.login_page"))
        page_code = code if code in MESSAGES else 500
        return render_error_page(page_code, msg)

    @app.errorhandler(Exception)
    def handle_unexpected(e: Exception):
        app.logger.exception("Unhandled exception")
        if wants_json():
            return jsonify({"error": "internal_error", "status": 500}), 500
        return render_error_page(500, MESSAGES[500])

    # Handlers explícitos para códigos comunes
    for code in [400, 401, 403, 404, 405, 409, 413, 415, 429, 500, 502, 503, 504]:
        def _factory(c):
            def _h(_e):
                if wants_json():
                    return jsonify({"error": _e.name if isinstance(_e, HTTPException) else "error", "status": c}), c
                if c == 401:
                    return redirect(url_for("pages_core.pages_auth.login_page"))
                return render_error_page(c, MESSAGES.get(c, "Error"))
            return _h
        app.register_error_handler(code, _factory(code))