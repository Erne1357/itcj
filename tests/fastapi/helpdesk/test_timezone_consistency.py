"""Los timestamps del proyecto se guardan en hora LOCAL, no en UTC.

Postgres corre con `timezone = America/Ciudad_Juarez`, asi que todos los
`server_default=func.now()` / `text("NOW()")` de los modelos escriben hora local
(10:43), igual que `now_local()`. `datetime.utcnow()` escribe 16:43: seis horas
adelantado respecto de todo lo demas.

Mientras el valor solo se guarda y se muestra, el sintoma es un timestamp
desfasado. Cuando se usa como CORTE de una consulta —comparado contra columnas
escritas en local— la ventana entera se recorre seis horas.
"""
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import itcj2.models  # noqa: F401  (resuelve mappers)
from itcj2.apps.helpdesk.api.department_head import get_pending_tasks
from itcj2.apps.helpdesk.models.category import Category
from itcj2.apps.helpdesk.models.ticket import Ticket
from itcj2.apps.helpdesk.utils.timezone_utils import now_local
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.position import Position, PositionAppPerm, UserPosition
from itcj2.core.models.user import User

SUBTREE = "helpdesk.tickets.api.read.subtree"
RAIZ = Path(__file__).resolve().parents[3] / "itcj2"


# --------------------------------------------------------------------------
# Guarda estatica: que no vuelva a colarse utcnow() en codigo de produccion.
# --------------------------------------------------------------------------

def test_ningun_modulo_de_produccion_usa_utcnow():
    """`utcnow()` devuelve UTC naive; el resto del sistema escribe local naive.

    Mezclarlos no truena —ambos son naive— simplemente da resultados corridos
    seis horas, que es la peor forma de fallar: en silencio.
    """
    # El módulo que define el reemplazo lo nombra en su docstring para explicar
    # de qué está protegiendo; es la única mención legítima.
    EXENTO = RAIZ / "core" / "utils" / "timezone.py"

    infractores = []
    for py in RAIZ.rglob("*.py"):
        if "__pycache__" in py.parts or py == EXENTO:
            continue
        texto = py.read_text(encoding="utf-8", errors="replace")
        for numero, linea in enumerate(texto.splitlines(), 1):
            if "utcnow()" in linea and not linea.lstrip().startswith("#"):
                infractores.append(f"{py.relative_to(RAIZ.parent)}:{numero}")

    assert not infractores, (
        "usar now_local() (o func.now() en el modelo) en vez de utcnow():\n  "
        + "\n  ".join(infractores)
    )


# --------------------------------------------------------------------------
# Consecuencia real: el corte de "tickets sin calificar" del jefe de depto.
# --------------------------------------------------------------------------

def _dept(db, code):
    d = Department(code=code, name=code, is_active=True)
    db.add(d); db.commit(); db.refresh(d)
    return d


def _user(db, last):
    u = User(first_name="TZ", last_name=last, is_active=True)
    db.add(u); db.commit(); db.refresh(u)
    return u


def _category(db):
    c = db.query(Category).filter_by(code="tz_cat").first()
    if not c:
        c = Category(area="SOPORTE", code="tz_cat", name="tz", is_active=True)
        db.add(c); db.commit(); db.refresh(c)
    return c


def _grant_subtree(db, user, dept):
    app = db.query(App).filter_by(key="helpdesk").first()
    perm = db.query(Permission).filter_by(app_id=app.id, code=SUBTREE).first()
    if not perm:
        perm = Permission(app_id=app.id, code=SUBTREE, name=SUBTREE)
        db.add(perm); db.commit(); db.refresh(perm)
    pos = Position(code=f"tz_pos_{dept.code}", title="Jefe", department_id=dept.id,
                   is_active=True, allows_multiple=True)
    db.add(pos); db.commit(); db.refresh(pos)
    db.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=perm.id, allow=True))
    db.add(UserPosition(user_id=user.id, position_id=pos.id,
                        start_date=(now_local() - timedelta(days=365)).date(), is_active=True))
    db.commit()
    return pos


def _ticket_resuelto_hace(db, numero, requester, dept, delta):
    t = Ticket(
        ticket_number=numero, requester_id=requester.id,
        requester_department_id=dept.id, area="SOPORTE",
        category_id=_category(db).id, priority="MEDIA", title=numero,
        description="x", status="RESOLVED_SUCCESS",
        # Naive local, igual que lo escribe ticket_service.resolve_ticket.
        resolved_at=now_local().replace(tzinfo=None) - delta,
        created_by_id=requester.id, updated_by_id=requester.id,
    )
    db.add(t); db.commit()
    return t


def test_el_corte_de_30_dias_no_pierde_las_ultimas_horas(db_session):
    """Un ticket resuelto hace 29 dias y 21 horas SIGUE dentro de la ventana.

    Con `utcnow()` el corte quedaba seis horas mas tarde que el "hace 30 dias"
    real, asi que la franja entre 29d18h y 30d desaparecia del contador aunque
    la lista de tickets del jefe si la mostraba.
    """
    dept = _dept(db_session, "tz_dept")
    jefe = _user(db_session, "Jefe")
    solicitante = _user(db_session, "Solicitante")
    _grant_subtree(db_session, jefe, dept)

    _ticket_resuelto_hace(db_session, "TZ-BORDE-1", solicitante, dept,
                          timedelta(days=29, hours=21))

    resultado = get_pending_tasks(user={"sub": str(jefe.id), "role": None}, db=db_session)

    assert resultado["data"]["unrated_tickets"]["count"] == 1


def test_el_corte_sigue_excluyendo_lo_verdaderamente_viejo(db_session):
    """La otra mitad del contrato: pasados los 30 dias, fuera."""
    dept = _dept(db_session, "tz_dept_viejo")
    jefe = _user(db_session, "JefeViejo")
    solicitante = _user(db_session, "SolicitanteViejo")
    _grant_subtree(db_session, jefe, dept)

    _ticket_resuelto_hace(db_session, "TZ-VIEJO-1", solicitante, dept,
                          timedelta(days=31))

    resultado = get_pending_tasks(user={"sub": str(jefe.id), "role": None}, db=db_session)

    assert resultado["data"]["unrated_tickets"]["count"] == 0


# --------------------------------------------------------------------------
# Query.get() legacy: SQLAlchemy 2.0 lo marca como LegacyAPIWarning y lo va a
# quitar. CLAUDE.md ya manda usar db.get(Model, id) para lookup por PK.
# --------------------------------------------------------------------------

def test_ningun_modulo_usa_el_query_get_legacy():
    import re

    patron = re.compile(r"\.query\([A-Za-z_][A-Za-z0-9_]*\)\.get\(")
    infractores = []
    for py in RAIZ.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        for numero, linea in enumerate(py.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if patron.search(linea):
                infractores.append(f"{py.relative_to(RAIZ.parent)}:{numero}")

    assert not infractores, (
        "usar db.get(Modelo, id) en vez de db.query(Modelo).get(id):\n  "
        + "\n  ".join(infractores)
    )
