"""
Fixtures compartidos para tests de la pestaña de Configuración del Helpdesk.

Estrategia (idéntica a tests/fastapi/maint/test_api_smoke.py):
- App real con create_app() + dependency_override de get_db con MagicMock.
- JWT firmado con SECRET_KEY real; role='admin' → require_perms hace bypass.
- NO se usa SQLite ni sesión real (incompatible con JSONB de modelos core).
- El mock_db expone un store de objetos en memoria que responde a:
    .get(Model, id)  → retorna el objeto del store o None
    .query(Model)    → retorna un QueryMock que filtra sobre el store
    .add(obj)        → añade al store con id autoincrementado
    .flush()         → confirma pending
    .commit()        → llama flush
    .refresh(obj)    → no-op
    .expire_all()    → no-op
- Los tests de cache usan directamente el módulo catalog_cache sin TestClient.
"""
import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import jwt
import pytest

import itcj2.models  # noqa: F401
from itcj2.config import get_settings
from itcj2.database import get_db
from itcj2.main import create_app
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def _admin_jwt(user_id: int = 1) -> str:
    settings = get_settings()
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "role": "admin",
        "cn": None,
        "name": "Config Test Admin",
        "iat": now,
        # 24h > JWT_REFRESH_THRESHOLD_SECONDS (2h) → middleware skip refresh → no SessionLocal()
        "exp": now + 86400,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def _no_role_jwt(user_id: int = 999) -> str:
    settings = get_settings()
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "role": None,
        "cn": None,
        "name": "Plain User",
        "iat": now,
        "exp": now + 3600,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


# ---------------------------------------------------------------------------
# ConfigDB: mock de sesión SQLAlchemy con store en memoria
# ---------------------------------------------------------------------------

class _QueryMock:
    """Mock de SQLAlchemy Query con filter/filter_by/order_by/all/first/count/scalar."""

    def __init__(self, store: list):
        self._items = list(store)
        self._kw_filters: dict = {}
        self._scalar_col: str | None = None  # columna para scalar() cuando viene de func.max

    def filter_by(self, **kwargs):
        m = _QueryMock(self._items)
        m._kw_filters = {**self._kw_filters, **kwargs}
        m._scalar_col = self._scalar_col
        return m

    def filter(self, *args):
        """
        Interpreta BinaryExpression simples (col == val, col >= val, col <= val).
        Expresiones complejas (func.upper, notin_, etc.) se ignoran de forma segura.
        """
        import operator as op
        import sqlalchemy.sql.operators as sa_ops

        for expr in args:
            try:
                # Solo procesar BinaryExpression con left siendo InstrumentedAttribute
                left = getattr(expr, "left", None)
                right = getattr(expr, "right", None)
                oper = getattr(expr, "operator", None)

                if left is None or right is None or oper is None:
                    continue

                # Extraer nombre de columna (directo o desde func.upper(col))
                col_key = getattr(left, "key", None)
                fn_transform = None  # transformación opcional al valor del item

                if col_key is None:
                    # Puede ser func.upper(col) u otra función — intentar extraer columna
                    fn_name = getattr(left, "name", None)
                    clauses = getattr(left, "clauses", None)
                    if clauses is not None:
                        for clause in clauses:
                            inner_key = getattr(clause, "key", None)
                            if inner_key:
                                col_key = inner_key
                                if fn_name == "upper":
                                    fn_transform = str.upper
                                break
                    if col_key is None:
                        continue

                # Extraer valor del lado derecho
                val = getattr(right, "value", right)

                # Filtrar según operador
                if oper == sa_ops.eq:
                    def _match_eq(item, _k=col_key, _v=val, _fn=fn_transform):
                        item_val = getattr(item, _k, None)
                        if item_val is None:
                            return False
                        if _fn:
                            item_val = _fn(str(item_val))
                        return item_val == _v
                    self._items = [i for i in self._items if _match_eq(i)]
                elif oper == sa_ops.ne:
                    self._items = [i for i in self._items if getattr(i, col_key, None) != val]
                elif oper == sa_ops.ge:
                    self._items = [i for i in self._items
                                   if getattr(i, col_key, None) is not None
                                   and getattr(i, col_key) >= val]
                elif oper == sa_ops.le:
                    self._items = [i for i in self._items
                                   if getattr(i, col_key, None) is not None
                                   and getattr(i, col_key) <= val]
                elif oper == sa_ops.gt:
                    self._items = [i for i in self._items
                                   if getattr(i, col_key, None) is not None
                                   and getattr(i, col_key) > val]
                elif oper == sa_ops.lt:
                    self._items = [i for i in self._items
                                   if getattr(i, col_key, None) is not None
                                   and getattr(i, col_key) < val]
                # else: operador desconocido → ignorar de forma segura
            except Exception:
                # Cualquier error al parsear → ignorar el filtro
                pass
        return self

    def order_by(self, *args):
        # Intenta ordenar por display_order si el atributo existe
        col = args[0] if args else None
        attr = None
        if col is not None:
            attr = getattr(col, "key", None) or getattr(col, "name", None)
        if attr:
            try:
                self._items = sorted(
                    self._items, key=lambda i: getattr(i, attr, 0)
                )
            except Exception:
                pass
        return self

    def options(self, *args):
        return self

    def offset(self, n: int):
        self._items = self._items[n:]
        return self

    def limit(self, n: int):
        self._items = self._items[:n]
        return self

    def _filtered(self):
        items = self._items
        for k, v in self._kw_filters.items():
            items = [i for i in items if getattr(i, k, None) == v]
        return items

    def all(self):
        return self._filtered()

    def first(self):
        items = self._filtered()
        return items[0] if items else None

    def count(self):
        return len(self._filtered())

    def scalar(self):
        items = self._filtered()
        if not items:
            return None
        try:
            col = self._scalar_col or "display_order"
            return max(getattr(i, col, 0) for i in items)
        except Exception:
            return None

    def notin_(self, *args):
        return self


class ConfigDB:
    """
    Mock de sesión SQLAlchemy para tests de config.
    Mantiene un store {ModelClass: {id: instance}}.
    """

    def __init__(self):
        self._store: dict = {}
        self._pending: list = []
        self._id_counter = 1

    def _next_id(self) -> int:
        val = self._id_counter
        self._id_counter += 1
        return val

    def _ensure(self, cls):
        if cls not in self._store:
            self._store[cls] = {}

    def get(self, cls, pk):
        self._ensure(cls)
        return self._store[cls].get(pk)

    def add(self, obj):
        self._pending.append(obj)

    def flush(self):
        for obj in self._pending:
            cls = type(obj)
            self._ensure(cls)
            if not getattr(obj, "id", None):
                obj.id = self._next_id()
            if hasattr(obj, "created_at") and obj.created_at is None:
                obj.created_at = datetime.utcnow()
            if hasattr(obj, "updated_at") and obj.updated_at is None:
                obj.updated_at = datetime.utcnow()
            if hasattr(obj, "changed_at") and obj.changed_at is None:
                obj.changed_at = datetime.utcnow()
            self._store[cls][obj.id] = obj
        self._pending.clear()

    def commit(self):
        self.flush()

    def refresh(self, obj):
        pass

    def expire_all(self):
        pass

    def expire(self, obj):
        pass

    def close(self):
        pass

    def delete(self, obj):
        cls = type(obj)
        self._ensure(cls)
        if obj.id in self._store[cls]:
            del self._store[cls][obj.id]

    def query(self, cls):
        """
        Acepta tanto clases modelo como expresiones func.max/func.min.
        Para expresiones de función, detecta la clase modelo subyacente y
        configura el QueryMock para que scalar() devuelva max(col).
        """
        try:
            import inspect
            # Detectar si cls es un modelo SQLAlchemy real (tiene __tablename__)
            if inspect.isclass(cls) and hasattr(cls, "__tablename__"):
                self._ensure(cls)
                items = list(self._store[cls].values())
                return _QueryMock(items)
            # Si es una expresión func (func.max, func.min, func.upper...)
            # intentar extraer el modelo subyacente de la columna
            fn_expr = cls
            col_clauses = getattr(fn_expr, "clauses", None)
            if col_clauses is not None:
                for clause in col_clauses:
                    # Columna puede ser InstrumentedAttribute (.class_, .key)
                    # o Column (.table.name, .name)
                    model_cls = getattr(clause, "class_", None)
                    col_key = getattr(clause, "key", None) or getattr(clause, "name", None)

                    if model_cls is None or not inspect.isclass(model_cls):
                        # Intentar buscar por nombre de tabla en el store
                        table = getattr(clause, "table", None)
                        table_name = getattr(table, "name", None)
                        if table_name:
                            for stored_cls in self._store:
                                if getattr(stored_cls, "__tablename__", None) == table_name:
                                    model_cls = stored_cls
                                    break

                    if model_cls is not None and inspect.isclass(model_cls):
                        self._ensure(model_cls)
                        items = list(self._store[model_cls].values())
                        mock = _QueryMock(items)
                        # Configurar scalar() para que use la columna correcta
                        if col_key:
                            mock._scalar_col = col_key
                        return mock
        except Exception:
            pass
        # Fallback: QueryMock vacío
        return _QueryMock([])


# ---------------------------------------------------------------------------
# Fixture: ConfigDB como db_session
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_session():
    """ConfigDB mock para tests — se crea nuevo por test."""
    return ConfigDB()


@pytest.fixture()
def app_client(db_session):
    """
    TestClient con get_db overrideado a ConfigDB.
    También pre-popula los caches de catalog_cache con valores stub para
    evitar que los handlers llamen a SessionLocal() (que requeriría Postgres).
    """
    import itcj2.apps.helpdesk.utils.catalog_cache as cc

    # Stub mínimo para que catalog_cache no intente abrir sesiones reales.
    # Los tests que prueben el cache real lo resetean con setup_method/teardown_method.
    _orig_priorities = cc._PRIORITIES_BY_CODE
    _orig_statuses = cc._STATUSES_BY_CODE
    _orig_transitions_from = cc._TRANSITIONS_BY_FROM_CODE
    _orig_transitions_full = cc._TRANSITIONS_FULL
    _orig_areas = cc._AREAS_BY_CODE
    _orig_templates = cc._NOTIFICATION_TEMPLATES_BY_CODE

    # Poblar con dicts vacíos para que _ensure_*loaded no llamen a BD
    if cc._PRIORITIES_BY_CODE is None:
        cc._PRIORITIES_BY_CODE = {}
    if cc._STATUSES_BY_CODE is None:
        cc._STATUSES_BY_CODE = {}
    if cc._TRANSITIONS_BY_FROM_CODE is None:
        cc._TRANSITIONS_BY_FROM_CODE = {}
        cc._TRANSITIONS_FULL = {}
    if cc._AREAS_BY_CODE is None:
        cc._AREAS_BY_CODE = {"DESARROLLO": {"code": "DESARROLLO", "is_active": True},
                              "SOPORTE": {"code": "SOPORTE", "is_active": True}}
    if cc._NOTIFICATION_TEMPLATES_BY_CODE is None:
        cc._NOTIFICATION_TEMPLATES_BY_CODE = {}

    app = create_app()

    def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override

    # Patch middleware SessionLocal to prevent real DB connections during JWT refresh.
    # The token exp is set to 24h but as safety net we also mock the middleware session.
    _mock_middleware_db = MagicMock()
    _mock_middleware_db.__enter__ = MagicMock(return_value=_mock_middleware_db)
    _mock_middleware_db.__exit__ = MagicMock(return_value=False)
    _mock_middleware_db.close = MagicMock()

    with patch("itcj2.utils.async_broadcast", MagicMock(return_value=None)):
        with patch("itcj2.database.SessionLocal", return_value=_mock_middleware_db):
            with TestClient(app, raise_server_exceptions=True) as client:
                client._db = db_session
                yield client

    app.dependency_overrides.clear()

    # Restaurar estado original del cache
    cc._PRIORITIES_BY_CODE = _orig_priorities
    cc._STATUSES_BY_CODE = _orig_statuses
    cc._TRANSITIONS_BY_FROM_CODE = _orig_transitions_from
    cc._TRANSITIONS_FULL = _orig_transitions_full
    cc._AREAS_BY_CODE = _orig_areas
    cc._NOTIFICATION_TEMPLATES_BY_CODE = _orig_templates


@pytest.fixture()
def admin_headers() -> dict:
    return {"Cookie": f"itcj_token={_admin_jwt()}"}


@pytest.fixture()
def no_auth_headers() -> dict:
    return {}


@pytest.fixture()
def no_perm_headers() -> dict:
    return {"Cookie": f"itcj_token={_no_role_jwt()}"}


# ---------------------------------------------------------------------------
# Factories de modelos de prueba
# ---------------------------------------------------------------------------

def make_priority(
    db: ConfigDB,
    code: str = "TEST",
    label: str = "Test Priority",
    sla_hours: int = 24,
    display_order: int = 99,
    is_active: bool = True,
    color: str = "#aabbcc",
    badge_class: str = "bg-secondary",
):
    from itcj2.apps.helpdesk.models.priority import Priority

    p = Priority(
        code=code,
        label=label,
        sla_hours=sla_hours,
        display_order=display_order,
        is_active=is_active,
        color=color,
        badge_class=badge_class,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(p)
    db.flush()
    return p


def make_status(
    db: ConfigDB,
    code: str = "TEST_STATUS",
    label: str = "Test Status",
    stage: str = "created",
    progress_pct: int = 0,
    is_open: bool = True,
    is_resolved: bool = False,
    is_terminal: bool = False,
    display_order: int = 99,
    is_active: bool = True,
    color: str = "#6c757d",
    badge_class: str = "bg-secondary",
    icon: str = "fa-circle",
):
    from itcj2.apps.helpdesk.models.ticket_status import TicketStatus

    s = TicketStatus(
        code=code,
        label=label,
        stage=stage,
        progress_pct=progress_pct,
        is_open=is_open,
        is_resolved=is_resolved,
        is_terminal=is_terminal,
        display_order=display_order,
        is_active=is_active,
        color=color,
        badge_class=badge_class,
        icon=icon,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(s)
    db.flush()
    return s


def make_transition(
    db: ConfigDB,
    from_status,
    to_status,
    required_perm: str = None,
    required_fields: list = None,
    is_active: bool = True,
):
    from itcj2.apps.helpdesk.models.status_transition import StatusTransition

    t = StatusTransition(
        from_status_id=from_status.id,
        to_status_id=to_status.id,
        required_perm=required_perm,
        required_fields=required_fields,
        is_active=is_active,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    # Set relationship refs for to_dict(include_status_codes=True)
    t.from_status = from_status
    t.to_status = to_status
    db.add(t)
    db.flush()
    return t


def make_area(
    db: ConfigDB,
    code: str = "TEST_AREA",
    label: str = "Test Area",
    icon: str = "fa-laptop",
    color: str = "#0d6efd",
    description: str = "Área de prueba",
    display_order: int = 99,
    is_active: bool = True,
):
    from itcj2.apps.helpdesk.models.area import Area

    a = Area(
        code=code,
        label=label,
        icon=icon,
        color=color,
        description=description,
        display_order=display_order,
        is_active=is_active,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(a)
    db.flush()
    return a


def make_notification_template(
    db: ConfigDB,
    code: str = "test_event",
    name: str = "Test Event",
    body_template: str = "Hello {{ ticket.title }}",
    subject_template: str = "Subject: {{ ticket.ticket_number }}",
    channel: str = "inapp",
    description: str = "Test template",
    is_active: bool = True,
):
    from itcj2.apps.helpdesk.models.notification_template import NotificationTemplate

    t = NotificationTemplate(
        code=code,
        name=name,
        body_template=body_template,
        subject_template=subject_template,
        channel=channel,
        description=description,
        is_active=is_active,
        updated_by=None,
        updated_by_id=None,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(t)
    db.flush()
    return t


def make_config_log(
    db: ConfigDB,
    user_id: int = 1,
    entity_type: str = "priority",
    entity_id: int = None,
    action: str = "create",
    before: dict = None,
    after: dict = None,
    ip_address: str = "127.0.0.1",
    changed_at: datetime = None,
):
    from itcj2.apps.helpdesk.models.config_change_log import ConfigChangeLog

    log = ConfigChangeLog(
        user_id=user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        before_data=before,
        after_data=after,
        ip_address=ip_address,
        changed_at=changed_at or datetime.utcnow(),
        user=None,
    )
    db.add(log)
    db.flush()
    return log
