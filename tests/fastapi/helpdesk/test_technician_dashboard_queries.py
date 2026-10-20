"""El dashboard del técnico arma sus listas con UNA consulta (rendimiento 2026-10-14).

La página completa pintaba 4 listas (En espera, Trabajando, Del equipo,
Historial) llamando `list_tickets` cuatro veces: cada una con su `count`, su
`select` y su juego de cargas en lote de relaciones (usuarios ×13, colaboradores,
equipos de inventario, departamentos, categorías...), aunque la tarjeta solo
pinta nombre del solicitante, de quien creó y del asignado, categoría y
`split_from`. En prod (trazas de Tempo): 51 sentencias y 156 ms para un técnico;
medido en dev con 7680/7681: 36 y 46 sentencias. Ahora `list_ticket_sections`
trae las cuatro listas en una sola sentencia (`UNION ALL` + join de las
relaciones de la tarjeta) y `Ticket.to_card_dict()` arma lo que la tarjeta lee.

Se fija:
1. las consultas NO crecen con el número de tickets (2 por sección o 5);
2. el resultado es el MISMO que el del algoritmo anterior —copia congelada
   `_viejo_*`: 4 `list_tickets` con sus filtros, límites y el corte de fecha
   del historial— en ids, orden y conteos de cada sección, para técnicos de los
   dos equipos, un usuario sin rol de técnico (su visibilidad por solicitante /
   asignado) y un admin;
3. el HTML de la página y de cada fragmento HTMX es byte a byte el de antes;
4. `to_card_dict` es subconjunto de `to_dict(include_relations=True)`.

Las filas las siembra cada test dentro de la transacción del arnés (se revierte)
y se afirma sobre ellas, nunca sobre un total de la base: dev comparte BD con
datos reales.
"""
import re
import time
from datetime import date, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

import itcj2.models  # noqa: F401
from itcj2.apps.helpdesk.models.ticket import Ticket
from itcj2.apps.helpdesk.pages import technician
from itcj2.apps.helpdesk.services import ticket_service
from itcj2.apps.helpdesk.utils.teams import tech_team
from itcj2.config import get_settings
from itcj2.core.models.app import App
from itcj2.core.models.permission import Permission
from itcj2.core.models.role import Role
from itcj2.core.models.role_permission import RolePermission
from itcj2.core.models.user import User
from itcj2.core.models.user_app_role import UserAppRole
from itcj2.database import get_db
from itcj2.main import create_app

from ._catalog import ensure_helpdesk_category, ensure_helpdesk_priority

DASH_PERM = "helpdesk.dashboard.technician"
PAGE_URL = "/help-desk/technician/dashboard"
TABS = ("assigned", "inProgress", "team", "resolved")
RESUELTOS = ("RESOLVED_SUCCESS", "RESOLVED_FAILED", "CLOSED")


def _hoy():
    """Mismo reloj que el código bajo prueba (`date.today()` en la pestaña de
    historial): las fechas de resolución se siembran relativas a él, y el oráculo
    y la versión nueva lo leen en el mismo instante. No hay `NOW()` de BD de por
    medio, así que el desfase UTC/local de CI no entra en juego."""
    return date.today()


# ───────────────────────── oráculo: el algoritmo anterior ─────────────────────────

def _viejo_query_tech_tickets(user_id, user_roles, tab, hist="all", search=None, db=None):
    """Copia LITERAL (congelada) de `pages/technician.py::_query_tech_tickets`
    antes de este cambio. No la "arregles" ni la acerques al código nuevo: es
    la referencia contra la que se compara."""
    from datetime import date, timedelta

    from itcj2.apps.helpdesk.services import ticket_service
    from itcj2.database import SessionLocal

    own = db is None
    _db = SessionLocal() if own else db
    try:
        if tab == "assigned":
            res = ticket_service.list_tickets(_db, user_id=user_id, user_roles=user_roles,
                                              assigned_to_me=True, status=["ASSIGNED"], per_page=100)
            return res["tickets"]
        if tab == "inProgress":
            res = ticket_service.list_tickets(_db, user_id=user_id, user_roles=user_roles,
                                              assigned_to_me=True, status=["IN_PROGRESS"], per_page=100)
            return res["tickets"]
        if tab == "team":
            team = tech_team(user_roles)
            if not team:
                return []
            res = ticket_service.list_tickets(_db, user_id=user_id, user_roles=user_roles,
                                              assigned_to_team=team, status=["ASSIGNED"],
                                              search=search or None, per_page=100)
            return res["tickets"]
        if tab == "resolved":
            res = ticket_service.list_tickets(_db, user_id=user_id, user_roles=user_roles,
                                              assigned_to_me=True,
                                              status=["RESOLVED_SUCCESS", "RESOLVED_FAILED", "CLOSED"],
                                              search=search or None, per_page=50)
            tickets = res["tickets"]
            today = date.today()
            cutoff = None
            if hist == "today":
                cutoff = today
            elif hist == "week":
                cutoff = today - timedelta(days=7)
            elif hist == "month":
                cutoff = today - timedelta(days=30)
            if cutoff is not None:
                cs = cutoff.isoformat()
                tickets = [t for t in tickets if (t.get("resolved_at") or "")[:10] >= cs]
            return tickets[:20]
        return []
    finally:
        if own:
            _db.close()


def _viejo_tabs(user_id, user_roles, tabs, hist="all", search=None, db=None):
    """Lo que hacía la página: una llamada del algoritmo anterior por pestaña."""
    return {t: _viejo_query_tech_tickets(user_id, user_roles, t, hist, search, db) for t in tabs}


# ──────────────────────────────── infraestructura ────────────────────────────────

@pytest.fixture()
def client(db_session):
    """TestClient con la app real; `get_db` apunta a la sesión transaccional."""
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def patched_session_local(db_session, monkeypatch):
    """El código que abre `SessionLocal()` por su cuenta usa la sesión del test
    (sin `close()` ni `rollback()`: ver `test_ticket_split_tech_page.py`)."""
    class _NoClose:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def close(self):
            pass

        def rollback(self):
            pass

    monkeypatch.setattr("itcj2.database.SessionLocal", lambda: _NoClose(db_session))
    return db_session


def _cookie(user_id):
    settings = get_settings()
    now = int(time.time())
    payload = {"sub": str(user_id), "role": None, "cn": None, "name": "Test",
               "iat": now, "exp": now + 24 * 3600}
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    return {"Cookie": f"itcj_token={token}"}


def _commit(db, obj):
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def _sentencias(db, fn):
    """(sentencias SQL normalizadas, resultado) de `fn()` sobre la conexión de la sesión."""
    vistas = []

    def _registrar(conn, cursor, statement, *_a):
        vistas.append(" ".join(statement.split()))

    conn = db.connection()
    event.listen(conn, "before_cursor_execute", _registrar)
    try:
        resultado = fn()
    finally:
        event.remove(conn, "before_cursor_execute", _registrar)
    return vistas, resultado


def _lecturas(sentencias, tabla):
    """Cuántas sentencias leen `tabla` (en `FROM` o en un `JOIN`)."""
    patron = re.compile(rf"\b(?:FROM|JOIN) {tabla}\b")
    return sum(1 for s in sentencias if patron.search(s))


# ─────────────────────────────────── siembra ───────────────────────────────────

def _mundo(db):
    """Usuarios, categorías y el contador de folios para armar tickets."""
    ensure_helpdesk_priority(db, "MEDIA")
    cat_a = ensure_helpdesk_category(db, code="tdq_cat_a", area="SOPORTE")
    cat_b = ensure_helpdesk_category(db, code="tdq_cat_b", area="SOPORTE")
    return {
        "tech": _commit(db, User(first_name="Tec", last_name="Dq", is_active=True)),
        "otro_tech": _commit(db, User(first_name="Otro", middle_name="Tec", last_name="Dq",
                                      is_active=True)),
        "reqs": [_commit(db, User(first_name=f"Req{i}", last_name="Dq", is_active=True))
                 for i in range(2)],
        "creador": _commit(db, User(first_name="Crea", last_name="Dq", is_active=True)),
        "cats": [cat_a, cat_b],
        "seq": [0],
    }


def _ticket(db, m, status, *, user=None, team=None, resolved_dias=None, titulo=None,
            split_from=None):
    """Un ticket. `created_at` crece con el orden de creación (distinto en cada
    uno: sin empates el orden de las listas es determinista).
    `resolved_dias`: hace cuántos días se resolvió."""
    m["seq"][0] += 1
    n = m["seq"][0]
    resuelto = status in RESUELTOS
    t = Ticket(
        ticket_number=f"TKDQ-{n:04d}",
        requester_id=m["reqs"][n % 2].id,
        requester_department_id=None,
        area="SOPORTE",
        category_id=m["cats"][n % 2].id,
        priority="MEDIA",
        title=titulo or f"ticket dq {n}",
        description=f"descripción del ticket dq {n}",
        location="Aula 7" if n % 3 == 0 else None,
        status=status,
        assigned_to_user_id=user.id if user else None,
        assigned_to_team=team,
        created_by_id=m["creador"].id,
        updated_by_id=m["creador"].id,
        created_at=datetime(2026, 3, 1) + timedelta(minutes=n),
        split_from_ticket_id=split_from.id if split_from else None,
    )
    if resuelto:
        dias = 0 if resolved_dias is None else resolved_dias
        t.resolved_at = datetime.combine(_hoy() - timedelta(days=dias), datetime.min.time()) \
            + timedelta(hours=12)
        t.resolved_by_id = user.id if user else m["otro_tech"].id
        t.resolution_notes = f"nota de resolución {n}"
        t.rating_attention, t.rating_speed, t.rating_efficiency = 5, 4, True
        t.rating_comment = f"comentario {n}"
    return _commit(db, t)


def _sembrar(db, m, por_seccion, *, ruido=True):
    """`por_seccion` tickets en cada una de las 4 listas del técnico `m["tech"]`
    (+ ruido que NO debe salir en ninguna)."""
    tech, otro = m["tech"], m["otro_tech"]
    padre = None
    for k in range(por_seccion):
        a = _ticket(db, m, "ASSIGNED", user=tech, titulo=f"ZQ asignado {k}",
                    split_from=padre)
        padre = padre or a          # los siguientes se "partieron" del primero
        _ticket(db, m, "IN_PROGRESS", user=tech)
        _ticket(db, m, "ASSIGNED", team="soporte", titulo=f"ZQ equipo {k}")
        _ticket(db, m, RESUELTOS[k % 3], user=tech, resolved_dias=(0, 3, 10, 40)[k % 4],
                titulo=f"ZQ resuelto {k}")
    if ruido:
        _ticket(db, m, "ASSIGNED", user=otro)                    # de otro técnico
        _ticket(db, m, "IN_PROGRESS", user=otro)
        _ticket(db, m, "ASSIGNED", team="desarrollo")            # cola del otro equipo
        _ticket(db, m, "PENDING")                                # sin asignar
        _ticket(db, m, RESUELTOS[0], user=otro, resolved_dias=0)


def _ids(listas):
    return {tab: [t["id"] for t in lista] for tab, lista in listas.items()}


def _es_subconjunto(chico, grande, ruta="ticket"):
    """`chico` (to_card_dict) cabe en `grande` (to_dict): mismas claves y valores."""
    if isinstance(chico, dict):
        assert isinstance(grande, dict), ruta
        for clave, valor in chico.items():
            assert clave in grande, f"{ruta}.{clave} no está en to_dict"
            _es_subconjunto(valor, grande[clave], f"{ruta}.{clave}")
    else:
        assert chico == grande, f"{ruta}: {chico!r} != {grande!r}"


# ──────────────────────── 1. las consultas no crecen con los tickets ────────────────────────

def _correr_tabs(db, m):
    uid = m["tech"].id                       # antes de expirar: leerlo después sería una consulta
    db.expire_all()      # sin esto las relaciones salen de memoria y no se vería un N+1
    return _sentencias(db, lambda: technician._query_tech_tabs(
        uid, {"tech_soporte"}, technician._TABS, hist="all", db=db))


def test_las_consultas_no_crecen_con_los_tickets(db_session):
    m = _mundo(db_session)
    _sembrar(db_session, m, 2)
    pocas, res2 = _correr_tabs(db_session, m)
    assert all(len(res2[t]) == 2 for t in TABS), _ids(res2)

    _sembrar(db_session, m, 3)       # ahora 5 por sección
    muchas, res5 = _correr_tabs(db_session, m)
    assert all(len(res5[t]) == 5 for t in TABS), _ids(res5)

    assert len(muchas) == len(pocas), f"N+1: {len(pocas)} sentencias con 2 tickets, {len(muchas)} con 5"
    # Una sentencia para las 4 listas: nada de `count`, ni cargas en lote.
    assert len(muchas) == 1, muchas
    assert _lecturas(muchas, "helpdesk_ticket") == 1
    assert _lecturas(muchas, "core_users") <= 1
    for tabla in ("helpdesk_ticket_collaborator", "helpdesk_ticket_inventory_items",
                  "helpdesk_inventory_items", "core_departments"):
        assert _lecturas(muchas, tabla) == 0, tabla
    assert not [s for s in muchas if s.startswith("SELECT count(")]


def test_un_fragmento_de_una_pestana_tambien_es_una_consulta(db_session):
    m = _mundo(db_session)
    _sembrar(db_session, m, 3)
    uid = m["tech"].id
    for tab in TABS:
        db_session.expire_all()
        sentencias, lista = _sentencias(db_session, lambda: technician._query_tech_tickets(
            uid, {"tech_soporte"}, tab, hist="all", db=db_session))
        assert len(lista) == 3, tab
        assert len(sentencias) == 1, (tab, sentencias)


def test_un_tecnico_no_pide_la_secretaria_ni_los_departamentos(db_session):
    """Los roles de acceso total se revisan antes: sin consulta de puestos."""
    m = _mundo(db_session)
    _sembrar(db_session, m, 1)
    for roles in ({"tech_soporte"}, {"tech_desarrollo"}, {"admin"}):
        sentencias, _ = _sentencias(db_session, lambda: ticket_service.list_ticket_sections(
            db_session, m["tech"].id, roles,
            {"assigned": {"assigned_to_me": True, "status": ["ASSIGNED"], "limit": 100}}))
        assert len(sentencias) == 1, (roles, sentencias)


def test_la_pagina_completa_no_crece_con_los_tickets(client, patched_session_local):
    """De punta a punta: la página hace UNA lectura de `helpdesk_ticket` y el
    total de sentencias no depende de cuántos tickets haya."""
    db = patched_session_local
    m = _mundo(db)
    _dar_rol_tecnico(db, m["tech"])
    _sembrar(db, m, 2)
    headers = _cookie(m["tech"].id)

    def _pedir():
        # Mismo protocolo para las dos medidas: una petición de calentamiento
        # (cachés de authz, memoria de apps por sesión) y la que se cuenta.
        assert client.get(PAGE_URL, headers=headers).status_code == 200
        db.expire_all()
        sentencias, r = _sentencias(db, lambda: client.get(PAGE_URL, headers=headers))
        assert r.status_code == 200, r.text
        return sentencias

    pocas = _pedir()
    _sembrar(db, m, 3)
    muchas = _pedir()

    assert len(muchas) == len(pocas), f"{len(pocas)} sentencias con 2 tickets, {len(muchas)} con 5"
    assert _lecturas(muchas, "helpdesk_ticket") == 1, [s[:120] for s in muchas]
    assert _lecturas(muchas, "helpdesk_ticket_collaborator") == 0
    assert _lecturas(muchas, "helpdesk_ticket_inventory_items") == 0
    assert not [s for s in muchas if s.startswith("SELECT count(")]


# ─────────────── 2. el resultado es el del algoritmo anterior (oráculo) ───────────────

CASOS = [
    pytest.param({"tech_soporte"}, "week", None, id="soporte-semana"),
    pytest.param({"tech_soporte"}, "all", None, id="soporte-todo"),
    pytest.param({"tech_soporte"}, "today", None, id="soporte-hoy"),
    pytest.param({"tech_soporte"}, "month", None, id="soporte-mes"),
    pytest.param({"tech_soporte"}, "all", "ZQ", id="soporte-busqueda"),
    pytest.param({"tech_soporte"}, "all", "no-existe-xyz", id="soporte-busqueda-sin-coincidencias"),
    pytest.param({"tech_desarrollo"}, "week", None, id="desarrollo"),
    pytest.param({"tech_soporte", "tech_desarrollo"}, "all", None, id="ambos-equipos"),
    pytest.param({"admin"}, "week", None, id="admin"),
    pytest.param({"staff"}, "all", None, id="sin-rol-de-tecnico"),
    pytest.param(set(), "all", "ZQ", id="sin-roles-busqueda"),
]


@pytest.mark.parametrize("roles,hist,search", CASOS)
def test_mismas_listas_que_el_algoritmo_anterior(db_session, roles, hist, search):
    m = _mundo(db_session)
    _sembrar(db_session, m, 6)
    uid = m["tech"].id

    db_session.expire_all()
    nuevo = technician._query_tech_tabs(uid, roles, technician._TABS, hist, search, db_session)
    db_session.expunge_all()
    viejo = _viejo_tabs(uid, roles, technician._TABS, hist, search, db_session)

    assert _ids(nuevo) == _ids(viejo)          # mismos tickets, mismo orden y mismo conteo
    for tab in TABS:
        assert len(nuevo[tab]) == len(viejo[tab]), tab
        for n, v in zip(nuevo[tab], viejo[tab]):
            _es_subconjunto(n, v, f"{tab}[{v['ticket_number']}]")


def test_el_oraculo_no_es_vacuo(db_session):
    """Con el caso base cada lista trae algo y la cola de equipo respeta el equipo."""
    m = _mundo(db_session)
    _sembrar(db_session, m, 6)
    uid = m["tech"].id
    soporte = _ids(_viejo_tabs(uid, {"tech_soporte"}, technician._TABS, "all", None, db_session))
    assert [len(soporte[t]) for t in TABS] == [6, 6, 6, 6]
    desarrollo = _viejo_tabs(uid, {"tech_desarrollo"}, ("team",), "all", None, db_session)["team"]
    assert [t["ticket_number"] for t in desarrollo] != []                  # la cola del otro equipo
    assert not set(t["id"] for t in desarrollo) & set(soporte["team"])
    # sin rol de técnico no hay equipo: la lista de equipo es vacía
    assert _viejo_tabs(uid, {"staff"}, ("team",), "all", None, db_session)["team"] == []


def test_el_limite_del_historial_se_aplica_antes_del_corte_de_fecha(db_session):
    """El historial toma los 50 más recientes y DESPUÉS filtra por fecha: los
    dos más viejos, resueltos hoy, no entran en "semana" porque quedan fuera
    del límite. La versión nueva debe conservar esa regla."""
    m = _mundo(db_session)
    tech = m["tech"]
    filas = []
    for k in range(52):
        m["seq"][0] += 1
        n = m["seq"][0]
        resuelto_hoy = k < 2                          # los 2 más viejos (por created_at)
        filas.append(Ticket(
            ticket_number=f"TKDQL-{n:04d}", requester_id=m["reqs"][0].id, area="SOPORTE",
            category_id=m["cats"][0].id, priority="MEDIA", title=f"lim {n}", description="x",
            status="CLOSED", assigned_to_user_id=tech.id, created_by_id=m["creador"].id,
            updated_by_id=m["creador"].id, created_at=datetime(2026, 3, 1) + timedelta(minutes=n),
            resolved_at=datetime.combine(_hoy() - timedelta(days=0 if resuelto_hoy else 40),
                                         datetime.min.time()) + timedelta(hours=12),
            resolved_by_id=tech.id,
        ))
    db_session.add_all(filas)
    db_session.commit()
    roles = {"tech_soporte"}

    for hist in ("week", "all"):
        db_session.expire_all()
        nuevo = technician._query_tech_tabs(tech.id, roles, ("resolved",), hist, None, db_session)
        db_session.expunge_all()
        viejo = _viejo_tabs(tech.id, roles, ("resolved",), hist, None, db_session)
        assert _ids(nuevo) == _ids(viejo), hist
    assert viejo["resolved"] != []                    # "all": los 20 más recientes
    semana = _viejo_tabs(tech.id, roles, ("resolved",), "week", None, db_session)["resolved"]
    assert semana == []                               # la regla que se conserva


def test_la_visibilidad_de_quien_no_es_tecnico_sigue_acotada(db_session):
    """Sin rol de técnico solo se ve lo propio (solicitante o asignado): un
    ticket de otro, sin relación con el usuario, no sale aunque coincida."""
    m = _mundo(db_session)
    tech, otro = m["tech"], m["otro_tech"]
    propio = _ticket(db_session, m, "ASSIGNED", user=tech)
    ajeno = _ticket(db_session, m, "ASSIGNED", user=otro)

    nuevo = ticket_service.list_ticket_sections(
        db_session, tech.id, {"staff"},
        {"a": {"status": ["ASSIGNED"], "limit": 100},                       # sin assigned_to_me
         "b": {"status": ["ASSIGNED"], "assigned_to_me": True, "limit": 100}})
    viejo = ticket_service.list_tickets(db_session, user_id=tech.id, user_roles={"staff"},
                                        status=["ASSIGNED"], per_page=100)["tickets"]
    assert [t["id"] for t in nuevo["a"]] == [t["id"] for t in viejo] == [propio.id]
    assert ajeno.id not in [t["id"] for t in nuevo["a"]]
    assert [t["id"] for t in nuevo["b"]] == [propio.id]


# ─────────────────────── list_ticket_sections (el servicio) ───────────────────────

def test_secciones_orden_limite_y_secciones_vacias(db_session):
    m = _mundo(db_session)
    tech = m["tech"]
    creados = [_ticket(db_session, m, "ASSIGNED", user=tech) for _ in range(5)]
    res = ticket_service.list_ticket_sections(db_session, tech.id, {"tech_soporte"}, {
        "dos": {"assigned_to_me": True, "status": ["ASSIGNED"], "limit": 2},
        "todos": {"assigned_to_me": True, "status": ["ASSIGNED"], "limit": 100},
        "nada": {"assigned_to_me": True, "status": ["IN_PROGRESS"], "limit": 100},
    })
    nuevo_a_viejo = [t.id for t in reversed(creados)]
    assert [t["id"] for t in res["dos"]] == nuevo_a_viejo[:2]       # límite sobre lo MÁS NUEVO
    assert [t["id"] for t in res["todos"]] == nuevo_a_viejo
    assert res["nada"] == []                                        # la sección existe, vacía
    assert ticket_service.list_ticket_sections(db_session, tech.id, {"admin"}, {}) == {}


def test_una_seccion_sola_y_con_busqueda_filtra_como_list_tickets(db_session):
    m = _mundo(db_session)
    tech = m["tech"]
    _ticket(db_session, m, "ASSIGNED", team="soporte", titulo="impresora ZQ rota")
    _ticket(db_session, m, "ASSIGNED", team="soporte", titulo="proyector")
    spec = {"assigned_to_team": "soporte", "status": ["ASSIGNED"], "search": "ZQ", "limit": 100}
    una = ticket_service.list_ticket_sections(db_session, tech.id, {"tech_soporte"}, {"cola": spec})
    viejo = ticket_service.list_tickets(db_session, user_id=tech.id, user_roles={"tech_soporte"},
                                        assigned_to_team="soporte", status=["ASSIGNED"],
                                        search="ZQ", per_page=100)["tickets"]
    assert [t["id"] for t in una["cola"]] == [t["id"] for t in viejo]
    assert [t["title"] for t in una["cola"]] == ["impresora ZQ rota"]


# ───────────── 3. to_card_dict es subconjunto de to_dict y la tarjeta no pide más ─────────────

def test_to_card_dict_es_subconjunto_de_to_dict(db_session):
    m = _mundo(db_session)
    _sembrar(db_session, m, 4)
    db_session.expire_all()
    res = technician._query_tech_tabs(m["tech"].id, {"tech_soporte"}, technician._TABS, "all",
                                      None, db_session)
    db_session.expunge_all()
    vistos = 0
    for lista in res.values():
        for card in lista:
            completo = db_session.get(Ticket, card["id"]).to_dict(include_relations=True)
            _es_subconjunto(card, completo, card["ticket_number"])
            vistos += 1
    assert vistos == 16
    # ejercita las ramas: con y sin `split_from`, con y sin asignado, con ubicación
    todas = [c for lista in res.values() for c in lista]
    assert any(c["split_from"] for c in todas) and any(not c["split_from"] for c in todas)
    assert any(c["assigned_to"] for c in todas) and any(c["assigned_to"] is None for c in todas)
    assert any(c["location"] for c in todas)


def test_la_tarjeta_no_lee_claves_que_to_card_dict_no_trae():
    """Guarda contra que un cambio en `ticket_card.html` (o en la lista del
    técnico) lea algo que el dict recortado no trae: se pintaría VACÍO en
    silencio. `requester_department` solo se lee con `show_department`, que el
    dashboard del técnico no pasa; las demás vistas usan `to_dict` completo."""
    from pathlib import Path

    base = Path(technician.__file__).resolve().parents[1] / "templates" / "helpdesk"
    texto = (base / "_components" / "ticket_card.html").read_text(encoding="utf-8") + \
        (base / "technician" / "_dashboard_list.html").read_text(encoding="utf-8")
    leidas = set(re.findall(r"\b(?:ticket|t)\.([a-z_]+)", texto))
    # Contra una instancia vacía: `to_card_dict` solo lee atributos propios.
    traidas = set(Ticket(id=1, ticket_number="X", created_at=None).to_card_dict())
    fuera = leidas - traidas - {"requester_department", "get"}
    assert not fuera, f"la tarjeta lee {sorted(fuera)} y to_card_dict no lo trae"


# ───────────────────────────── 4. el HTML es el de antes ─────────────────────────────

def _dar_rol_tecnico(db, user, role_name="tech_soporte"):
    """Rol de técnico en helpdesk CON el permiso de la página (por `RolePermission`,
    la forma real en que el DML se lo da)."""
    app = db.query(App).filter_by(key="helpdesk").first()
    role = db.query(Role).filter_by(name=role_name).first() or _commit(db, Role(name=role_name))
    if not db.query(UserAppRole).filter_by(user_id=user.id, app_id=app.id, role_id=role.id).first():
        db.add(UserAppRole(user_id=user.id, app_id=app.id, role_id=role.id))
    perm = db.query(Permission).filter_by(app_id=app.id, code=DASH_PERM).first() or _commit(
        db, Permission(app_id=app.id, code=DASH_PERM, name=DASH_PERM))
    if not db.query(RolePermission).filter_by(role_id=role.id, perm_id=perm.id).first():
        db.add(RolePermission(role_id=role.id, perm_id=perm.id))
    db.commit()


def test_el_html_es_identico_al_del_algoritmo_anterior(client, patched_session_local, monkeypatch):
    """Página completa y fragmento de cada pestaña (con filtros del historial):
    se pide con la versión nueva y con el algoritmo anterior puesto en su lugar."""
    db = patched_session_local
    m = _mundo(db)
    _dar_rol_tecnico(db, m["tech"])
    _sembrar(db, m, 6)
    headers = _cookie(m["tech"].id)
    htmx = {**headers, "HX-Request": "true"}

    pedidos = [(PAGE_URL, headers)]
    pedidos += [(f"{PAGE_URL}?tab={tab}", htmx) for tab in ("assigned", "inProgress", "team")]
    pedidos += [(f"{PAGE_URL}?tab=resolved&hist={hist}{extra}", htmx)
                for hist in ("today", "week", "month", "all")
                for extra in ("", "&search=ZQ")]
    pedidos.append((f"{PAGE_URL}?tab=team&search=ZQ", htmx))
    pedidos.append((f"{PAGE_URL}?tab=pestana-inexistente", htmx))

    nuevos = []
    for url, h in pedidos:
        db.expire_all()
        r = client.get(url, headers=h)
        assert r.status_code == 200, (url, r.text[:300])
        nuevos.append(r.text)

    monkeypatch.setattr(technician, "_query_tech_tabs", _viejo_tabs)
    for (url, h), nuevo in zip(pedidos, nuevos):
        db.expire_all()
        r = client.get(url, headers=h)
        assert r.status_code == 200, url
        assert r.text == nuevo, f"el HTML de {url} cambió"

    # y no es vacuo: la página trae los tickets sembrados
    assert "TKDQ-" in nuevos[0] and "ZQ asignado" in nuevos[0] and "Aula 7" in nuevos[0]
