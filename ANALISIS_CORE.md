# ANÁLISIS DE MEJORAS - CORE MODULE
## Sistema ITCJ - Infraestructura Base

**Fecha:** 2025-12-12
**Alcance:** Módulo Core (autenticación, autorización, dashboard, notificaciones)
**Criticidad:** ALTA - Afecta a todas las aplicaciones

---

## RESUMEN EJECUTIVO

El módulo **Core** es la infraestructura base que soporta todas las aplicaciones del sistema ITCJ. Presenta una **arquitectura sólida con autorización multinivel** (directa, basada en posiciones, basada en roles), pero tiene **problemas críticos de seguridad**, **performance en el dashboard** y **falta de documentación**.

### Hallazgos Críticos

🔴 **SEGURIDAD:**
- JWT secret con default "dev" (CRÍTICO)
- Cookies sin flag secure en producción
- Sin protección CSRF
- CORS no configurado consistentemente

🔴 **PERFORMANCE:**
- Dashboard carga "línea por línea" (archivo tutorial 1,495 líneas)
- Íconos se regeneran en cada render
- N+1 queries en servicio de perfil
- DateTime actualizado cada segundo (reflow constante)

✅ **FORTALEZAS:**
- Sistema de permisos multinivel excelente
- Servicios bien separados
- Notificaciones SSE + WebSocket
- Modelos bien estructurados

---

## 🚨 PRIORIDAD CRÍTICA / URGENTE

### 1. **Corregir JWT Secret por defecto (SEGURIDAD CRÍTICA)**

**Ubicación:** `itcj/core/utils/jwt_tools.py:5`

**Problema:**
```python
SECRET = os.getenv("SECRET_KEY", "dev")  # ⚠️ DEFAULT INSEGURO
```

Si `SECRET_KEY` no está configurado en las variables de entorno, el sistema usa **"dev"** como secreto, lo que permite:
- Cualquiera puede firmar tokens válidos
- Tokens pueden ser forjados
- Sesiones pueden ser secuestradas

**Solución: Fail-fast si no hay SECRET_KEY**

```python
# itcj/core/utils/jwt_tools.py
import os
import sys

# Require SECRET_KEY - NEVER use default in production
SECRET = os.getenv("SECRET_KEY")
if not SECRET:
    if os.getenv("FLASK_ENV") == "production":
        # CRITICAL: In production, SECRET_KEY MUST be set
        print("ERROR: SECRET_KEY environment variable is required in production")
        sys.exit(1)
    else:
        # Development only - use a random secret that changes on restart
        import secrets
        SECRET = secrets.token_urlsafe(32)
        print(f"WARNING: Using temporary SECRET_KEY for development: {SECRET[:10]}...")
        print("Set SECRET_KEY environment variable for consistent sessions")

ALGO = "HS256"
```

**Mejor aún: Validar en startup**

```python
# itcj/__init__.py (en create_app)
def create_app(config_name='development'):
    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Validate critical security settings
    validate_security_config(app)

    return app


def validate_security_config(app):
    """Validar configuración de seguridad al iniciar."""
    issues = []

    # Check SECRET_KEY
    if not app.config.get('SECRET_KEY') or app.config['SECRET_KEY'] == 'dev':
        if app.config.get('ENV') == 'production':
            issues.append("SECRET_KEY is not set or using default value")

    # Check JWT_SECRET_KEY
    if not os.getenv('JWT_SECRET_KEY'):
        if app.config.get('ENV') == 'production':
            issues.append("JWT_SECRET_KEY environment variable not set")

    # Check cookie security
    if app.config.get('ENV') == 'production':
        if not app.config.get('COOKIE_SECURE', False):
            issues.append("COOKIE_SECURE should be True in production")

    if issues:
        app.logger.error("SECURITY CONFIGURATION ERRORS:")
        for issue in issues:
            app.logger.error(f"  - {issue}")

        if app.config.get('ENV') == 'production':
            sys.exit(1)  # Fail in production
        else:
            app.logger.warning("⚠️  Running with insecure configuration in development mode")
```

**Esfuerzo estimado:** Muy Bajo (30 minutos)
**Impacto:** CRÍTICO (previene compromiso total del sistema)
**Riesgo:** Muy Bajo

---

### 2. **Habilitar cookies seguras en producción**

**Ubicación:** `itcj/config.py:9-10`

**Problema:**
```python
class Config:
    COOKIE_SECURE = False  # ⚠️ Permite transmisión por HTTP
    COOKIE_SAMESITE = "Lax"  # Podría ser "Strict"
```

**Solución: Configuración por ambiente**

```python
# itcj/config.py
import os

class Config:
    """Configuración base."""
    SECRET_KEY = os.environ.get('SECRET_KEY')
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY')

    # Cookies - configuración base
    SESSION_COOKIE_HTTPONLY = True  # Previene acceso via JavaScript
    SESSION_COOKIE_SAMESITE = 'Lax'  # Protección CSRF básica

    # En producción, estos se sobrescriben
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False


class DevelopmentConfig(Config):
    """Configuración de desarrollo."""
    DEBUG = True
    TESTING = False

    # Cookies inseguras OK en desarrollo (http://)
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_SAMESITE = 'Lax'


class ProductionConfig(Config):
    """Configuración de producción."""
    DEBUG = False
    TESTING = False

    # SEGURIDAD ESTRICTA en producción
    SESSION_COOKIE_SECURE = True   # Solo HTTPS
    REMEMBER_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = 'Strict'  # Máxima protección
    SESSION_COOKIE_HTTPONLY = True

    # Validar que SECRET_KEY esté configurado
    if not Config.SECRET_KEY:
        raise ValueError("SECRET_KEY environment variable must be set in production")

    if not Config.JWT_SECRET_KEY:
        raise ValueError("JWT_SECRET_KEY environment variable must be set in production")


class TestingConfig(Config):
    """Configuración para testing."""
    TESTING = True
    WTF_CSRF_ENABLED = False  # Disable CSRF for testing
    SESSION_COOKIE_SECURE = False
```

**Verificar en jwt_tools.py:**

```python
# itcj/core/utils/jwt_tools.py
from flask import current_app

def set_jwt_cookie(response, token):
    """Establecer cookie JWT con configuración segura."""
    response.set_cookie(
        'itcj_token',
        value=token,
        httponly=True,  # Previene XSS
        secure=current_app.config.get('SESSION_COOKIE_SECURE', False),  # HTTPS only en prod
        samesite=current_app.config.get('SESSION_COOKIE_SAMESITE', 'Lax'),
        max_age=3600 * 12  # 12 horas
    )
    return response
```

**Esfuerzo estimado:** Bajo (1 hora)
**Impacto:** Alto (previene session hijacking)
**Riesgo:** Bajo

---

### 3. **Implementar protección CSRF**

**Problema:**
No hay protección CSRF en formularios. Los endpoints POST/PUT/DELETE pueden ser explotados via CSRF.

**Solución: Implementar Flask-WTF o CSRFProtect**

```bash
# Agregar a requirements.txt
flask-wtf==1.2.1
```

```python
# itcj/core/extensions.py
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_socketio import SocketIO
from flask_wtf.csrf import CSRFProtect  # NUEVO

db = SQLAlchemy()
migrate = Migrate()
socketio = SocketIO()
csrf = CSRFProtect()  # NUEVO


# itcj/__init__.py
from itcj.core.extensions import db, migrate, socketio, csrf

def create_app(config_name='development'):
    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    socketio.init_app(app, cors_allowed_origins="*")
    csrf.init_app(app)  # NUEVO

    # Exempt API routes from CSRF (use token auth instead)
    csrf.exempt('api_bp')  # Exempt API blueprint

    return app
```

**Proteger formularios HTML:**

```html
<!-- core/templates/base.html -->
<head>
    <!-- ... -->
    <meta name="csrf-token" content="{{ csrf_token() }}">
</head>

<!-- En formularios -->
<form method="POST">
    {{ csrf_token() }}  <!-- WTForms automático -->
    <!-- o manual: -->
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
</form>
```

**Para AJAX requests:**

```javascript
// Agregar a base.html o archivo JS común
const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;

// En fetch calls
fetch('/api/endpoint', {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken  // Flask-WTF acepta este header
    },
    body: JSON.stringify(data)
});
```

**Configuración:**

```python
# config.py
class Config:
    # CSRF Protection
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None  # No expira
    WTF_CSRF_SSL_STRICT = False  # Set True in production with HTTPS

    # CSRF exempt routes (APIs con token auth)
    WTF_CSRF_CHECK_DEFAULT = False  # Opt-in per blueprint


class ProductionConfig(Config):
    WTF_CSRF_SSL_STRICT = True  # Strict HTTPS checking
```

**Esfuerzo estimado:** Medio (4 horas)
**Impacto:** Alto (previene CSRF attacks)
**Riesgo:** Medio (requiere testing de todos los formularios)

---

### 4. **Optimizar carga del dashboard (problema "línea por línea")**

**Problema identificado:**

El usuario reporta: *"la primera vez que lo carga el navegador, va por partes, así que quiero saber si hay forma de que lo cargue más rápido sin que parezca computadora vieja cargando linea por línea"*

**Causas raíz:**

1. **Tutorial de dashboard: 1,495 líneas** cargándose síncronamente
2. **Íconos Lucide regenerándose** en cada render
3. **CSS bloqueando** el render (6 archivos en `<head>`)
4. **Sin loading state** - usuario ve construcción progresiva

**Ubicación:**
- `itcj/core/templates/core/dashboard/dashboard.html`
- `itcj/core/static/js/dashboard/dashboard_tutorial.js` (1,495 líneas)
- `itcj/core/static/js/dashboard/dashboard.js` (472 líneas)

**Solución 1: Lazy-load del tutorial**

```html
<!-- core/templates/core/dashboard/dashboard.html -->
{% block extra_js %}
<!-- Cargar dashboard core -->
<script src="{{ url_for('core_static', filename='js/dashboard/dashboard.js') }}?v={{ config.STATIC_VERSION }}"></script>

<!-- ❌ ELIMINAR: No cargar tutorial automáticamente
<script src="{{ url_for('core_static', filename='js/dashboard/dashboard_tutorial.js') }}?v={{ config.STATIC_VERSION }}"></script>
-->

<!-- ✅ AGREGAR: Lazy load del tutorial -->
<script>
// Cargar tutorial solo cuando el usuario lo solicite
document.addEventListener('DOMContentLoaded', () => {
    const helpButton = document.querySelector('[data-action="show-tutorial"]');

    if (helpButton) {
        let tutorialLoaded = false;

        helpButton.addEventListener('click', async () => {
            if (!tutorialLoaded) {
                // Mostrar loading
                helpButton.innerHTML = '<i data-lucide="loader-2" class="animate-spin"></i> Cargando...';
                helpButton.disabled = true;

                // Cargar tutorial dinámicamente
                const script = document.createElement('script');
                script.src = "{{ url_for('core_static', filename='js/dashboard/dashboard_tutorial.js') }}?v={{ config.STATIC_VERSION }}";
                script.onload = () => {
                    tutorialLoaded = true;
                    // Iniciar tutorial
                    if (typeof DashboardTutorial !== 'undefined') {
                        DashboardTutorial.start();
                    }
                };
                script.onerror = () => {
                    alert('Error al cargar el tutorial');
                    helpButton.disabled = false;
                    helpButton.innerHTML = '<i data-lucide="help-circle"></i> Ayuda';
                };

                document.body.appendChild(script);
            } else {
                // Tutorial ya cargado, solo iniciarlo
                DashboardTutorial.start();
            }
        });
    }
});
</script>
{% endblock %}
```

**Ganancia:** -1,495 líneas en carga inicial (~70% reducción de JS)

---

**Solución 2: Optimizar regeneración de íconos**

```javascript
// itcj/core/static/js/dashboard/dashboard.js

class WindowsDesktop {
    constructor() {
        this.iconsInitialized = false;
    }

    init() {
        console.log("Initializing Windows Desktop...");

        // ❌ ELIMINAR: Llamada duplicada
        // lucide.createIcons();

        // ✅ SOLO inicializar íconos UNA VEZ
        if (!this.iconsInitialized) {
            lucide.createIcons();
            this.iconsInitialized = true;
        }

        this.setupGrid();
        this.setupPostMessageListener();
        this.updateDateTime();

        // ❌ CAMBIAR: No actualizar cada segundo
        // setInterval(() => this.updateDateTime(), 1000);

        // ✅ Actualizar cada minuto (suficiente para fecha/hora)
        setInterval(() => this.updateDateTime(), 60000);  // 60 segundos
    }

    renderGrid(apps) {
        // ... código de render ...

        // ❌ ELIMINAR: No regenerar todos los íconos
        // lucide.createIcons();

        // ✅ Solo crear íconos en elementos nuevos
        const newElements = this.gridContainer.querySelectorAll('[data-lucide]:not(.lucide)');
        if (newElements.length > 0) {
            lucide.createIcons({
                attrs: {
                    'stroke-width': 1.5
                },
                nameAttr: 'data-lucide'
            });
        }
    }

    updateDateTime() {
        const now = new Date();
        const dateElement = document.getElementById('current-date');
        const timeElement = document.getElementById('current-time');

        if (dateElement && timeElement) {
            // ✅ Usar Intl para formateo eficiente
            const dateFormatter = new Intl.DateTimeFormat('es-MX', {
                weekday: 'long',
                year: 'numeric',
                month: 'long',
                day: 'numeric'
            });

            const timeFormatter = new Intl.DateTimeFormat('es-MX', {
                hour: '2-digit',
                minute: '2-digit',
                hour12: true
            });

            // ✅ Usar textContent (más rápido que innerHTML)
            dateElement.textContent = dateFormatter.format(now);
            timeElement.textContent = timeFormatter.format(now);
        }
    }
}
```

**Ganancia:** Reduce reflows, mejora FPS

---

**Solución 3: Agregar loading state**

```html
<!-- core/templates/core/dashboard/dashboard.html -->
{% block content %}
<div id="dashboard-container">
    <!-- Loading overlay -->
    <div id="dashboard-loading" class="dashboard-loading">
        <div class="loading-spinner">
            <div class="spinner-border text-primary" role="status">
                <span class="visually-hidden">Cargando...</span>
            </div>
            <p class="mt-3">Cargando dashboard...</p>
        </div>
    </div>

    <!-- Dashboard content (initially hidden) -->
    <div id="dashboard-content" style="display: none;">
        <!-- Contenido existente del dashboard -->
    </div>
</div>

<style>
.dashboard-loading {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(255, 255, 255, 0.95);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 9999;
}

.loading-spinner {
    text-align: center;
}

/* Fade out animation */
.dashboard-loading.fade-out {
    animation: fadeOut 0.3s ease-out forwards;
}

@keyframes fadeOut {
    to {
        opacity: 0;
        pointer-events: none;
    }
}
</style>

<script>
document.addEventListener('DOMContentLoaded', () => {
    const loading = document.getElementById('dashboard-loading');
    const content = document.getElementById('dashboard-content');

    // Cuando todo esté listo
    window.addEventListener('load', () => {
        // Esperar un tick para asegurar render completo
        requestAnimationFrame(() => {
            // Fade out loading
            loading.classList.add('fade-out');

            // Mostrar contenido
            content.style.display = 'block';

            // Remover loading después de animación
            setTimeout(() => {
                loading.remove();
            }, 300);
        });
    });
});
</script>
{% endblock %}
```

**Ganancia:** Mejor percepción de carga, sin "línea por línea"

---

**Solución 4: Optimizar carga de CSS**

```html
<!-- core/templates/core/dashboard/dashboard.html -->
{% block extra_css %}
<!-- ❌ ANTES: 6 archivos CSS bloqueando render -->
<!--
<link rel="stylesheet" href="...bootstrap.css">
<link rel="stylesheet" href="...dashboard.css">
<link rel="stylesheet" href="...responsive.css">
...
-->

<!-- ✅ DESPUÉS: CSS crítico inline, resto async -->
<style>
    /* CSS crítico inline para first paint rápido */
    body { margin: 0; padding: 0; font-family: system-ui; }
    .dashboard-loading {
        position: fixed;
        inset: 0;
        background: #fff;
        display: flex;
        align-items: center;
        justify-content: center;
    }
</style>

<!-- CSS no crítico con preload + async -->
<link rel="preload" href="{{ url_for('core_static', filename='css/dashboard/dashboard.css') }}" as="style" onload="this.onload=null;this.rel='stylesheet'">
<link rel="preload" href="{{ url_for('core_static', filename='css/dashboard/responsive.css') }}" as="style" onload="this.onload=null;this.rel='stylesheet'">

<!-- Fallback para navegadores sin JS -->
<noscript>
    <link rel="stylesheet" href="{{ url_for('core_static', filename='css/dashboard/dashboard.css') }}">
    <link rel="stylesheet" href="{{ url_for('core_static', filename='css/dashboard/responsive.css') }}">
</noscript>
{% endblock %}
```

**Ganancia:** First Contentful Paint más rápido

---

**Resumen de mejoras de performance:**

| Optimización | Ganancia estimada | Esfuerzo |
|--------------|-------------------|----------|
| Lazy-load tutorial (1,495 líneas) | -70% JS inicial | Bajo |
| Optimizar íconos (una vez vs múltiple) | -50% tiempo render | Muy Bajo |
| Loading state | Mejor UX | Muy Bajo |
| Actualización DateTime (60s vs 1s) | -59 reflows/min | Muy Bajo |
| CSS async | -200ms first paint | Bajo |

**Esfuerzo total:** Medio (6 horas)
**Impacto:** Muy Alto (resuelve queja principal del usuario)
**Riesgo:** Bajo

---

## 🔥 PRIORIDAD ALTA

### 5. **Corregir N+1 queries en servicio de perfil**

**Ubicación:** `itcj/core/services/profile_service.py:60-75`

**Problema:**
```python
def get_user_profile_data(user_id):
    user = User.query.get(user_id)  # Query 1

    apps = App.query.filter_by(is_active=True).all()  # Query 2

    apps_data = []
    for app in apps:  # Para cada app (ej: 4 apps)
        roles = authz.user_roles_in_app(user_id, app.key)  # Query 3, 4, 5, 6
        direct_perms = authz.user_direct_perms_in_app(user_id, app.key)  # Query 7, 8, 9, 10
        perms_data = authz.effective_perms(user_id, app.key)  # Query 11-14 (hace 3 queries internas)

    # Total: 1 + 1 + (4 * (1 + 1 + 3)) = 22 queries para 4 apps
```

**Solución: Batch loading**

```python
# itcj/core/services/profile_service.py
from sqlalchemy.orm import joinedload, selectinload
from itcj.core.services import authz_service as authz

def get_user_profile_data(user_id):
    """Obtener datos de perfil de usuario con queries optimizadas."""

    # ✅ Query 1: Cargar usuario con relaciones
    user = User.query.options(
        joinedload(User.department),
        selectinload(User.positions).joinedload(UserPosition.position)
    ).get(user_id)

    if not user:
        return None

    # ✅ Query 2: Cargar apps activas
    apps = App.query.filter_by(is_active=True).all()

    # ✅ Query 3-5: Batch load TODOS los roles/permisos de UNA VEZ
    all_roles_map = _batch_load_user_roles(user_id, apps)
    all_perms_map = _batch_load_user_permissions(user_id, apps)

    # Construir respuesta sin queries adicionales
    apps_data = []
    for app in apps:
        app_roles = all_roles_map.get(app.key, [])
        app_perms = all_perms_map.get(app.key, {})

        apps_data.append({
            'app_key': app.key,
            'app_name': app.name,
            'roles': app_roles,
            'permissions': app_perms
        })

    return {
        'user': user.to_dict(),
        'apps': apps_data
    }


def _batch_load_user_roles(user_id, apps):
    """Cargar roles para todas las apps en una sola query."""
    from sqlalchemy import union, select
    from itcj.core.models import UserAppRole, PositionAppRole, Role, UserPosition

    app_keys = [app.key for app in apps]

    # Query combinada para roles directos + via posiciones
    direct_roles = (
        select(UserAppRole.app_id.label('app_key'), Role.name.label('role_name'))
        .join(Role, UserAppRole.role_id == Role.id)
        .join(App, UserAppRole.app_id == App.id)
        .where(UserAppRole.user_id == user_id)
        .where(App.key.in_(app_keys))
    )

    position_roles = (
        select(PositionAppRole.app_id.label('app_key'), Role.name.label('role_name'))
        .join(UserPosition, PositionAppRole.position_id == UserPosition.position_id)
        .join(Role, PositionAppRole.role_id == Role.id)
        .join(App, PositionAppRole.app_id == App.id)
        .where(UserPosition.user_id == user_id)
        .where(UserPosition.is_active == True)
        .where(App.key.in_(app_keys))
    )

    combined = union(direct_roles, position_roles)
    results = db.session.execute(combined).fetchall()

    # Organizar por app_key
    roles_map = {}
    for row in results:
        if row.app_key not in roles_map:
            roles_map[row.app_key] = []
        if row.role_name not in roles_map[row.app_key]:
            roles_map[row.app_key].append(row.role_name)

    return roles_map


def _batch_load_user_permissions(user_id, apps):
    """Cargar permisos para todas las apps en 3 queries."""
    from itcj.core.models import Permission, UserAppPerm, RolePermission

    app_keys = [app.key for app in apps]

    # Query 1: Permisos directos del usuario
    direct_perms = db.session.query(
        App.key.label('app_key'),
        Permission.code,
        UserAppPerm.allow
    ).join(
        Permission, UserAppPerm.perm_id == Permission.id
    ).join(
        App, Permission.app_id == App.id
    ).filter(
        UserAppPerm.user_id == user_id,
        App.key.in_(app_keys)
    ).all()

    # Query 2: Permisos via roles del usuario (pre-cargados)
    # ... implementación similar ...

    # Combinar y retornar mapa
    perms_map = {}
    # ... combinar resultados ...

    return perms_map
```

**Ganancia:** 22 queries → 5 queries (-77%)

**Esfuerzo estimado:** Alto (8 horas)
**Impacto:** Alto (mejora tiempo de carga de perfil)
**Riesgo:** Medio (requiere testing exhaustivo)

---

### 6. **Implementar caché de permisos**

**Problema:**
Permisos se consultan en CADA request via decoradores.

**Ubicación:**
- `itcj/core/utils/decorators.py` - @permission_required
- `itcj/core/services/authz_service.py` - effective_perms()

**Solución: Caché Redis**

```python
# itcj/core/services/authz_service.py
from itcj.core.extensions import redis_client
import json

PERMISSIONS_CACHE_TTL = 300  # 5 minutos

def effective_perms(user_id, app_key, use_cache=True):
    """
    Obtener permisos efectivos del usuario en una app.
    Con caché Redis para evitar queries repetidas.
    """
    cache_key = f"user:{user_id}:app:{app_key}:permissions"

    # Intentar obtener del caché
    if use_cache:
        cached = redis_client.get(cache_key)
        if cached:
            return json.loads(cached)

    # Si no está en caché, calcular
    result = _calculate_effective_perms(user_id, app_key)

    # Guardar en caché
    if use_cache:
        redis_client.setex(
            cache_key,
            PERMISSIONS_CACHE_TTL,
            json.dumps(result)
        )

    return result


def _calculate_effective_perms(user_id, app_key):
    """Cálculo real de permisos (código existente)."""
    # ... implementación existente de effective_perms ...
    pass


def invalidate_user_permissions_cache(user_id, app_key=None):
    """Invalidar caché de permisos cuando cambian roles/permisos."""
    if app_key:
        # Invalidar solo una app
        cache_key = f"user:{user_id}:app:{app_key}:permissions"
        redis_client.delete(cache_key)
    else:
        # Invalidar todas las apps
        pattern = f"user:{user_id}:app:*:permissions"
        for key in redis_client.scan_iter(match=pattern):
            redis_client.delete(key)


# Invalidar caché cuando se modifiquen asignaciones
def assign_role_to_user(user_id, app_key, role_id):
    """Asignar rol a usuario."""
    # ... código de asignación ...

    # Invalidar caché
    invalidate_user_permissions_cache(user_id, app_key)


def revoke_role_from_user(user_id, app_key, role_id):
    """Revocar rol de usuario."""
    # ... código de revocación ...

    # Invalidar caché
    invalidate_user_permissions_cache(user_id, app_key)
```

**Uso en decoradores:**

```python
# itcj/core/utils/decorators.py
def permission_required(perm_code, app_key=None):
    """Decorador para requerir permiso específico (con caché)."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not g.current_user:
                return redirect(url_for('core_pages.login'))

            user_id = g.current_user['sub']
            app = app_key or request.blueprint.split('_')[0]

            # ✅ Usar caché
            perms = authz.effective_perms(user_id, app, use_cache=True)

            if perm_code not in perms.get('granted', []):
                abort(403)

            return f(*args, **kwargs)
        return decorated_function
    return decorator
```

**Esfuerzo estimado:** Medio (4 horas)
**Impacto:** Alto (reduce carga DB significativamente)
**Riesgo:** Bajo (Redis ya está en uso)

---

### 7. **Mejorar algoritmo de hashing de contraseñas**

**Ubicación:** `itcj/core/models/user.py`

**Estado actual:**
```python
from werkzeug.security import generate_password_hash, check_password_hash

def set_nip(self, nip):
    # Usa pbkdf2:sha256 por defecto (werkzeug)
    self.password_hash = generate_password_hash(nip)

def verify_nip(self, nip):
    return check_password_hash(self.password_hash, nip)
```

**Problema:**
- pbkdf2:sha256 es aceptable pero **bcrypt o argon2 son más seguros**
- No hay configuración de iteraciones
- No hay rate limiting en login

**Solución: Migrar a Argon2**

```bash
# Agregar a requirements.txt
argon2-cffi==23.1.0
```

```python
# itcj/core/models/user.py
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHash

ph = PasswordHasher(
    time_cost=2,       # Iteraciones
    memory_cost=65536, # 64 MB
    parallelism=1,     # Threads
    hash_len=32,       # Longitud del hash
    salt_len=16        # Longitud del salt
)

class User(db.Model):
    # ... campos existentes ...

    def set_nip(self, nip):
        """Establecer NIP usando Argon2."""
        self.password_hash = ph.hash(nip)

    def verify_nip(self, nip):
        """Verificar NIP con soporte para migración desde werkzeug."""
        try:
            # Intentar con Argon2 primero
            ph.verify(self.password_hash, nip)

            # Rehash si necesita actualización
            if ph.check_needs_rehash(self.password_hash):
                self.set_nip(nip)
                db.session.commit()

            return True

        except (VerifyMismatchError, VerificationError, InvalidHash):
            # Fallback: verificar con werkzeug (migración)
            from werkzeug.security import check_password_hash

            if self.password_hash.startswith('scrypt:') or \
               self.password_hash.startswith('pbkdf2:'):
                # Hash antiguo de werkzeug
                if check_password_hash(self.password_hash, nip):
                    # ✅ Migrar a Argon2
                    self.set_nip(nip)
                    db.session.commit()
                    return True

            return False
```

**Migración gradual:**
- Contraseñas antiguas (werkzeug) siguen funcionando
- Al hacer login exitoso, se actualizan automáticamente a Argon2
- Nuevos usuarios usan Argon2 desde el inicio

**Esfuerzo estimado:** Medio (3 horas)
**Impacto:** Medio (mejor seguridad)
**Riesgo:** Bajo (migración transparente)

---

### 8. **Agregar rate limiting en login**

**Problema:**
Sin protección contra brute-force en endpoint de login.

**Solución:**

```bash
# Agregar a requirements.txt
flask-limiter==3.7.0
```

```python
# itcj/core/extensions.py
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=os.environ.get('REDIS_URL', 'redis://localhost:6379/0'),
    default_limits=["200 per day", "50 per hour"]
)


# itcj/__init__.py
from itcj.core.extensions import limiter

def create_app(config_name='development'):
    app = Flask(__name__)
    # ...
    limiter.init_app(app)
    return app
```

```python
# itcj/core/routes/api/auth.py
from itcj.core.extensions import limiter

@bp.route('/login', methods=['POST'])
@limiter.limit("5 per minute")  # Máximo 5 intentos por minuto
def login():
    """Login con rate limiting."""
    data = request.json

    # ... validación ...

    user = auth_service.authenticate(control_number, nip)

    if not user:
        # ⚠️ No revelar si el usuario existe
        return APIResponse.error(
            error_code='invalid_credentials',
            message='Credenciales inválidas',
            status=401
        )

    # ... generar token ...
```

**Rate limiting personalizado por usuario:**

```python
from flask_limiter.util import get_remote_address

def get_user_identifier():
    """Rate limit por IP + username si está disponible."""
    ip = get_remote_address()
    data = request.get_json() or {}
    username = data.get('control_number') or data.get('username')

    if username:
        return f"{ip}:{username}"
    return ip


limiter = Limiter(
    key_func=get_user_identifier,
    storage_uri=os.environ.get('REDIS_URL')
)
```

**Esfuerzo estimado:** Bajo (2 horas)
**Impacto:** Alto (previene brute-force)
**Riesgo:** Muy Bajo

---

## ⚠️ PRIORIDAD MEDIA

### 9. **Configurar CORS correctamente**

**Problema:**
CORS configurado en SocketIO pero no en Flask app principal.

**Ubicación:** `itcj/__init__.py`

**Solución:**

```bash
# Agregar a requirements.txt
flask-cors==5.0.0
```

```python
# itcj/core/extensions.py
from flask_cors import CORS

cors = CORS()


# itcj/__init__.py
from itcj.core.extensions import cors

def create_app(config_name='development'):
    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Configurar CORS
    cors.init_app(app, resources={
        r"/api/*": {
            "origins": app.config.get('CORS_ORIGINS', []),
            "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization", "X-CSRFToken"],
            "expose_headers": ["Content-Type", "X-Total-Count"],
            "supports_credentials": True,
            "max_age": 3600
        }
    })

    return app
```

```python
# config.py
class Config:
    # CORS Origins permitidos
    CORS_ORIGINS = []  # Ninguno por defecto (solo same-origin)


class DevelopmentConfig(Config):
    CORS_ORIGINS = [
        "http://localhost:3000",
        "http://localhost:5000",
        "http://127.0.0.1:5000"
    ]


class ProductionConfig(Config):
    # Solo el dominio de producción
    CORS_ORIGINS = [
        "https://itcj.cdjuarez.tecnm.mx",
        "https://www.itcj.cdjuarez.tecnm.mx"
    ]
```

**Esfuerzo estimado:** Bajo (1 hora)
**Impacto:** Medio (seguridad)
**Riesgo:** Bajo

---

### 10. **Agregar indices faltantes en tablas core**

**Ubicación:** `itcj/core/models/`

**Índices a agregar:**

```python
# itcj/core/models/permission.py
from sqlalchemy import Index

class Permission(db.Model):
    # ... campos existentes ...

    __table_args__ = (
        # Índice compuesto para búsquedas por app + código
        Index('ix_permissions_app_code', 'app_id', 'code'),

        # Búsquedas por solo app
        Index('ix_permissions_app_id', 'app_id'),
    )


# itcj/core/models/role_permission.py
class RolePermission(db.Model):
    # ... campos existentes ...

    __table_args__ = (
        # Búsquedas por permiso (inversa de rol)
        Index('ix_role_permissions_perm_id', 'perm_id'),
    )


# itcj/core/models/notification.py
class Notification(db.Model):
    # ... campos existentes ...

    __table_args__ = (
        # Ya tiene: ix_notification_user_id
        # Agregar índice compuesto para query común
        Index('ix_notifications_user_unread', 'user_id', 'is_read', 'created_at'),
    )


# itcj/core/models/user_position.py
class UserPosition(db.Model):
    # ... campos existentes ...

    __table_args__ = (
        # Búsqueda de posiciones activas de un usuario
        Index('ix_user_positions_user_active', 'user_id', 'is_active'),

        # Búsqueda de usuarios en una posición
        Index('ix_user_positions_position_active', 'position_id', 'is_active'),
    )
```

**Crear migración:**

```bash
flask db migrate -m "Add missing indexes to core tables"
flask db upgrade
```

**Esfuerzo estimado:** Muy Bajo (30 minutos)
**Impacto:** Medio (mejora queries)
**Riesgo:** Muy Bajo

---

### 11. **Implementar auditoría de cambios**

**Problema:**
No se registra quién modificó qué y cuándo.

**Solución: Tabla de auditoría**

```python
# itcj/core/models/audit_log.py
from itcj.core.extensions import db
from datetime import datetime

class AuditLog(db.Model):
    """Registro de auditoría de cambios."""
    __tablename__ = 'core_audit_logs'

    id = db.Column(db.Integer, primary_key=True)

    # Qué se modificó
    table_name = db.Column(db.String(100), nullable=False, index=True)
    record_id = db.Column(db.Integer, nullable=False, index=True)

    # Quién lo modificó
    user_id = db.Column(db.Integer, db.ForeignKey('core_users.id'), nullable=False, index=True)
    user = db.relationship('User', backref='audit_logs')

    # Cuándo
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Qué tipo de cambio
    action = db.Column(db.String(20), nullable=False)  # CREATE, UPDATE, DELETE

    # Detalles del cambio (JSONB)
    changes = db.Column(db.JSON)  # {"field": {"old": value, "new": value}}

    # Contexto adicional
    ip_address = db.Column(db.String(45))  # IPv6 compatible
    user_agent = db.Column(db.String(500))
    endpoint = db.Column(db.String(200))

    __table_args__ = (
        db.Index('ix_audit_logs_table_record', 'table_name', 'record_id'),
        db.Index('ix_audit_logs_user_timestamp', 'user_id', 'timestamp'),
    )

    def __repr__(self):
        return f'<AuditLog {self.action} on {self.table_name}#{self.record_id} by User#{self.user_id}>'
```

**Utility para logging:**

```python
# itcj/core/utils/audit.py
from itcj.core.models.audit_log import AuditLog
from itcj.core.extensions import db
from flask import request, g

def log_change(table_name, record_id, action, changes=None):
    """Registrar cambio en audit log."""
    if not hasattr(g, 'current_user') or not g.current_user:
        return  # No registrar si no hay usuario autenticado

    audit_entry = AuditLog(
        table_name=table_name,
        record_id=record_id,
        user_id=g.current_user['sub'],
        action=action,
        changes=changes,
        ip_address=request.remote_addr if request else None,
        user_agent=request.headers.get('User-Agent') if request else None,
        endpoint=request.endpoint if request else None
    )

    db.session.add(audit_entry)
    # Commit se hace en el request principal


def track_changes(old_obj, new_obj, fields):
    """Detectar cambios entre objetos."""
    changes = {}

    for field in fields:
        old_value = getattr(old_obj, field, None)
        new_value = getattr(new_obj, field, None)

        if old_value != new_value:
            changes[field] = {
                'old': old_value,
                'new': new_value
            }

    return changes if changes else None
```

**Uso en servicios:**

```python
# Ejemplo en user service
from itcj.core.utils.audit import log_change, track_changes

def update_user(user_id, data):
    """Actualizar usuario con auditoría."""
    user = User.query.get(user_id)

    # Guardar estado anterior
    old_user = copy.deepcopy(user)

    # Aplicar cambios
    for key, value in data.items():
        setattr(user, key, value)

    db.session.commit()

    # Registrar cambios
    changes = track_changes(old_user, user, ['email', 'is_active', 'full_name'])
    if changes:
        log_change('core_users', user_id, 'UPDATE', changes)

    return user
```

**Esfuerzo estimado:** Alto (6 horas)
**Impacto:** Alto (compliance, debugging)
**Riesgo:** Medio

---

## 📝 PRIORIDAD BAJA (Mejoras futuras)

### 12. **Implementar token refresh automático**

**Problema:**
Token refresh se hace en `after_request` con query authz (línea 57 de `__init__.py`).

**Mejora:**
Usar refresh token separado, sin queries en cada request.

**Esfuerzo:** Alto | **Impacto:** Medio | **Riesgo:** Medio

---

### 13. **Migrar notificaciones a solo SSE**

**Problema:**
Dual transport (SSE + WebSocket) agrega complejidad.

**Mejora:**
Deprecar WebSocket, usar solo SSE (más simple, HTTP/2 friendly).

**Esfuerzo:** Medio | **Impacto:** Bajo | **Riesgo:** Bajo

---

### 14. **Agregar 2FA (autenticación de dos factores)**

**Mejora:**
TOTP via Google Authenticator para cuentas admin.

**Esfuerzo:** Alto | **Impacto:** Alto | **Riesgo:** Medio

---

### 15. **Implementar sesiones de usuario activas**

**Mejora:**
Mostrar dispositivos/sesiones activas, permitir revocación.

**Esfuerzo:** Alto | **Impacto:** Medio | **Riesgo:** Bajo

---

### 16. **Agregar logging de intentos de login fallidos**

**Mejora:**
Registrar IPs con intentos fallidos, alertar en múltiples fallos.

**Esfuerzo:** Bajo | **Impacto:** Medio | **Riesgo:** Muy Bajo

---

### 17. **Implementar Content Security Policy (CSP)**

**Mejora:**
Headers CSP para prevenir XSS.

```python
@app.after_request
def set_csp(response):
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline' cdn.jsdelivr.net"
    return response
```

**Esfuerzo:** Medio | **Impacto:** Alto | **Riesgo:** Medio (puede romper CDNs)

---

### 18. **Migrar a JWT en headers (Authorization: Bearer)**

**Problema actual:**
JWT en cookies (bueno para CSRF, malo para APIs).

**Mejora:**
Soportar ambos: cookies para páginas, headers para API.

**Esfuerzo:** Medio | **Impacto:** Medio | **Riesgo:** Bajo

---

## 📊 RESUMEN DE PRIORIDADES

### Crítico / Urgente (Sprint 1: Semana 1-2)
| # | Mejora | Esfuerzo | Impacto | Archivos |
|---|--------|----------|---------|----------|
| 1 | JWT Secret validation | Muy Bajo | CRÍTICO | 2 |
| 2 | Cookies seguras | Bajo | Alto | 2 |
| 3 | Protección CSRF | Medio | Alto | 5 |
| 4 | Dashboard lazy-load | Medio | Muy Alto | 3 |

**Ganancia:** Seguridad crítica + UX dramáticamente mejorado

---

### Alta (Sprint 2-3: Semana 3-6)
| # | Mejora | Esfuerzo | Impacto |
|---|--------|----------|---------|
| 5 | N+1 queries perfil | Alto | Alto |
| 6 | Caché de permisos | Medio | Alto |
| 7 | Argon2 hashing | Medio | Medio |
| 8 | Rate limiting | Bajo | Alto |

**Ganancia:** Performance + seguridad robusta

---

### Media (Sprint 4-5: Semana 7-10)
| # | Mejora | Esfuerzo | Impacto |
|---|--------|----------|---------|
| 9 | CORS configuración | Bajo | Medio |
| 10 | Índices BD | Muy Bajo | Medio |
| 11 | Auditoría | Alto | Alto |

**Ganancia:** Compliance + observabilidad

---

### Baja (Backlog: Mes 3+)
| # | Mejora | Esfuerzo | Impacto |
|---|--------|----------|---------|
| 12-18 | Token refresh, 2FA, CSP, etc. | Variable | Variable |

---

## 🎯 PLAN DE ACCIÓN RECOMENDADO

### **Semana 1: Seguridad Crítica**
**Día 1-2:**
- [ ] Validar SECRET_KEY al inicio (30 min)
- [ ] Configurar cookies seguras por ambiente (1 hora)
- [ ] Testing de ambos cambios (2 horas)

**Día 3-5:**
- [ ] Implementar Flask-WTF CSRF (2 horas)
- [ ] Agregar tokens CSRF a formularios (2 horas)
- [ ] Testing exhaustivo de todos los formularios (4 horas)

### **Semana 2: Performance Dashboard**
**Día 1-2:**
- [ ] Lazy-load dashboard tutorial (2 horas)
- [ ] Optimizar regeneración de íconos (1 hora)
- [ ] Agregar loading state (2 horas)
- [ ] Testing cross-browser (2 horas)

**Día 3-5:**
- [ ] CSS async loading (1 hora)
- [ ] DateTime update cada 60s (30 min)
- [ ] Medir performance (lighthouse) (1 hora)
- [ ] Ajustes finales (2 horas)

### **Semana 3-4: Performance Backend**
- [ ] Implementar batch loading en profile service (6 horas)
- [ ] Implementar caché Redis de permisos (4 horas)
- [ ] Testing y medición de queries (4 horas)

### **Semana 5-6: Seguridad Adicional**
- [ ] Rate limiting (2 horas)
- [ ] Migración a Argon2 (3 horas)
- [ ] CORS configuration (1 hora)
- [ ] Testing de seguridad (4 horas)

### **Semana 7-8: Calidad**
- [ ] Índices de BD (30 min)
- [ ] Sistema de auditoría (6 horas)
- [ ] Testing integración (4 horas)

---

## 📚 RECURSOS

### Seguridad
- **OWASP Top 10:** https://owasp.org/www-project-top-ten/
- **Flask Security:** https://flask.palletsprojects.com/en/2.3.x/security/
- **Argon2:** https://argon2-cffi.readthedocs.io/

### Performance
- **Web Vitals:** https://web.dev/vitals/
- **Lighthouse:** https://developers.google.com/web/tools/lighthouse

### Testing
- **Flask-Testing:** https://flask-testing.readthedocs.io/

---

**Última actualización:** 2025-12-12
**Criticidad:** ALTA - Core afecta todas las apps
**Versión documento:** 1.0
