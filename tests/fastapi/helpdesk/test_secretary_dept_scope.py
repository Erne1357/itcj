"""El departamento que ve una secretaría en helpdesk, y los tickets que alcanza.

Caso real (palvarado, 2026-09-04): puesto de auxiliar en Ingeniería Industrial
(alta 2026-06-29, NO otorga helpdesk) + puesto de secretaria en División de
Estudios Profesionales (alta 2026-09-01, sí lo otorga). El dashboard le enseñaba
«Ingeniería Industrial» y sin un solo ticket. Eran DOS fallos apilados:

1. **El departamento.** `pages/secretary.py` resolvía con
   `db_user.get_current_department()`, el resolver AGNÓSTICO: devuelve cualquier
   departamento con puesto vigente y desempata por el MÁS ANTIGUO, sin mirar si
   ese puesto otorga la app. Medido: agnóstico -> Industrial (16), por
   procedencia -> División (18).

2. **El scope.** El acceso departamental se abría por ROL (`department_head`)
   y no por PERMISO (`helpdesk.tickets.api.read.department`). Una secretaría
   tiene el permiso y nunca entraba a esa rama, así que solo veía los tickets
   donde era solicitante o asignada. Pasaba desapercibido porque la secretaría
   crea casi todos los tickets de su departamento: una veía 20 de los 21 de su
   depto —le faltaba el que había creado otra persona— y nadie lo notaba.

Arreglar solo el (1) no quita el síntoma: simulado con el departamento correcto,
seguía devolviendo 0 de los 27 tickets sellados con él.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

import itcj2.models  # noqa: F401  (resuelve los mappers)

from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.position import Position, PositionAppRole, UserPosition
from itcj2.core.models.role import Role
from itcj2.core.models.role_permission import RolePermission
from itcj2.core.models.user import User

HOY = date.today()
READ_DEPT = "helpdesk.tickets.api.read.department"


# ---------------------------------------------------------------------------
# Andamiaje: el grafo mínimo de organigrama + autorización
# ---------------------------------------------------------------------------
@pytest.fixture()
def org(db_session):
    """Fábrica de departamentos, puestos y usuarios con acceso por PUESTO.

    El acceso se da siempre por puesto (`PositionAppRole`) y no por asignación
    directa al usuario: es lo único que ancla el departamento, y sin ancla el
    resolver se va al respaldo y el test no probaría lo que dice probar.
    """
    from itcj2.core.services.authz_cache import invalidate_user_app

    app = db_session.query(App).filter_by(key="helpdesk").first()
    assert app is not None, "falta la app helpdesk (la siembra el conftest raíz)"
    n = {"i": 0}

    def _sig():
        n["i"] += 1
        return f"sds{n['i']}"

    def _dept(nombre=None):
        d = Department(code=f"sds_dept_{_sig()}", name=nombre or f"Depto {_sig()}",
                       is_active=True)
        db_session.add(d)
        db_session.flush()
        return d

    def _rol(nombre, perms=()):
        r = db_session.query(Role).filter_by(name=nombre).first()
        if r is None:
            r = Role(name=nombre)
            db_session.add(r)
            db_session.flush()
        for code in perms:
            p = db_session.query(Permission).filter_by(app_id=app.id, code=code).first()
            if p is None:
                p = Permission(app_id=app.id, code=code, name=code)
                db_session.add(p)
                db_session.flush()
            ya = db_session.query(RolePermission).filter_by(
                role_id=r.id, perm_id=p.id).first()
            if ya is None:
                db_session.add(RolePermission(role_id=r.id, perm_id=p.id))
        db_session.flush()
        return r

    def _persona(*puestos):
        """`puestos` = [(depto, rol|None, antiguedad_dias)]. rol None = no da la app."""
        u = User(first_name="PRUEBA", last_name=f"SCOPE{_sig()}", is_active=True)
        db_session.add(u)
        db_session.flush()
        for depto, rol, dias in puestos:
            pos = Position(code=f"sds_pos_{_sig()}", title="Puesto de prueba",
                           department_id=depto.id, is_active=True, allows_multiple=True)
            db_session.add(pos)
            db_session.flush()
            db_session.add(UserPosition(user_id=u.id, position_id=pos.id,
                                        start_date=HOY - timedelta(days=dias),
                                        is_active=True))
            if rol is not None:
                db_session.add(PositionAppRole(position_id=pos.id, app_id=app.id,
                                               role_id=rol.id))
        db_session.flush()
        invalidate_user_app(u.id, "helpdesk")
        return u

    return {"dept": _dept, "rol": _rol, "persona": _persona,
            "secretaria": _rol("sds_secretary", [READ_DEPT]),
            "jefa": _rol("sds_head", [READ_DEPT]),
            "sin_scope": _rol("sds_staff", ["helpdesk.tickets.api.read.own"])}


@pytest.fixture()
def hacer_ticket(db_session):
    """Ticket sellado con un departamento concreto."""
    from itcj2.apps.helpdesk.models.category import Category
    from itcj2.apps.helpdesk.models.ticket import Ticket

    cat = Category(area="SOPORTE", code=f"sds_cat_{id(db_session)}",
                   name="Categoria de prueba", is_active=True)
    db_session.add(cat)
    db_session.flush()
    n = {"i": 0}

    def _make(solicitante, depto, titulo="Ticket de prueba"):
        n["i"] += 1
        t = Ticket(ticket_number=f"SDS-{id(db_session) % 100000}-{n['i']:03d}",
                   requester_id=solicitante.id, requester_department_id=depto.id,
                   area="SOPORTE", category_id=cat.id, priority="MEDIA",
                   title=titulo, description="d", status="PENDING",
                   created_by_id=solicitante.id, updated_by_id=solicitante.id)
        db_session.add(t)
        db_session.flush()
        return t

    return _make


def _listar(db, usuario, roles, **kw):
    from itcj2.apps.helpdesk.services import ticket_service
    return ticket_service.list_tickets(db, user_id=usuario.id, user_roles=roles,
                                       page=1, per_page=50, **kw)


# ===========================================================================
# 1. El departamento se resuelve por la app, no por antigüedad
# ===========================================================================
def test_el_dashboard_toma_el_depto_del_puesto_que_da_helpdesk(org, db_session):
    """El puesto más ANTIGUO no otorga la app; el que la otorga es el nuevo."""
    from itcj2.apps.helpdesk.pages.secretary import _helpdesk_departments

    ajeno = org["dept"]("Ingenieria Industrial de prueba")
    propio = org["dept"]("Division de Estudios de prueba")
    u = org["persona"]((ajeno, None, 500), (propio, org["secretaria"], 3))

    deptos = _helpdesk_departments(db_session, u.id)

    assert [d.id for d in deptos] == [propio.id], (
        "se coló el departamento cuyo puesto no otorga helpdesk")


def test_una_secretaria_de_dos_departamentos_los_ve_los_dos(org, db_session):
    """`app_departments` es PLURAL. La página enseñaba uno solo."""
    from itcj2.apps.helpdesk.pages.secretary import _helpdesk_departments

    a, b = org["dept"]("Depto A"), org["dept"]("Depto B")
    u = org["persona"]((a, org["secretaria"], 300), (b, org["secretaria"], 10))

    assert {d.id for d in _helpdesk_departments(db_session, u.id)} == {a.id, b.id}


def test_la_pagina_ya_no_usa_el_resolver_agnostico():
    """Estructural: `get_current_department` desempata por el puesto más antiguo
    SIN mirar la app. No vuelve a entrar aquí por descuido.

    Se recorre el AST y no el texto: el docstring del módulo NOMBRA el resolver
    justo para explicar por qué no se usa, y una búsqueda en texto plano se
    acusaba sola.
    """
    import ast
    from pathlib import Path
    import itcj2.apps.helpdesk.pages.secretary as mod

    arbol = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
    llamadas = {
        n.func.attr for n in ast.walk(arbol)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    } | {
        n.func.id for n in ast.walk(arbol)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    agnosticos = {"get_current_department", "get_primary_user_department"}
    assert not (llamadas & agnosticos), f"resolver agnóstico vivo: {llamadas & agnosticos}"
    assert "app_departments" in llamadas


# ===========================================================================
# 2. El scope departamental se abre por PERMISO, no por rol
# ===========================================================================
def test_la_secretaria_ve_un_ticket_que_no_creo_ella(org, db_session, hacer_ticket):
    """El corazón del bug: tenía `read.department` y el código miraba el rol."""
    depto = org["dept"]()
    secre = org["persona"]((depto, org["secretaria"], 10))
    otra = org["persona"]((depto, org["sin_scope"], 10))
    ajeno = hacer_ticket(otra, depto, "Lo levantó otra persona")

    r = _listar(db_session, secre, {"secretary"}, department_ids={depto.id})

    assert ajeno.ticket_number in {t["ticket_number"] for t in r["tickets"]}


def test_lo_que_lista_es_lo_que_deja_abrir(org, db_session, hacer_ticket):
    """`list_tickets` y `can_user_view_ticket` tienen que moverse juntos: si no,
    el ticket sale en la lista y da 403 al abrirlo."""
    from itcj2.apps.helpdesk.services.ticket_service import can_user_view_ticket

    depto = org["dept"]()
    secre = org["persona"]((depto, org["secretaria"], 10))
    otra = org["persona"]((depto, org["sin_scope"], 10))
    t = hacer_ticket(otra, depto)

    r = _listar(db_session, secre, {"secretary"}, department_ids={depto.id})
    en_lista = t.ticket_number in {x["ticket_number"] for x in r["tickets"]}

    assert en_lista is can_user_view_ticket(db_session, t, secre.id)
    assert en_lista, "no lista ni deja abrir: el scope sigue cerrado"


def test_el_jefe_de_depto_no_pierde_nada(org, db_session, hacer_ticket):
    """La positiva del cambio: cambiar rol por permiso no puede quitar acceso.

    Comprobado sobre la base real antes de tocarlo: 0 personas tienen el rol
    `department_head` sin el permiso `read.department`.
    """
    depto = org["dept"]()
    jefa = org["persona"]((depto, org["jefa"], 10))
    otra = org["persona"]((depto, org["sin_scope"], 10))
    t = hacer_ticket(otra, depto)

    r = _listar(db_session, jefa, {"department_head"}, department_ids={depto.id})
    assert t.ticket_number in {x["ticket_number"] for x in r["tickets"]}


def test_sin_el_permiso_solo_ve_los_suyos(org, db_session, hacer_ticket):
    """La negativa que hace útil a la positiva: el scope no se regala a todos."""
    depto = org["dept"]()
    llano = org["persona"]((depto, org["sin_scope"], 10))
    otra = org["persona"]((depto, org["sin_scope"], 10))
    suyo = hacer_ticket(llano, depto, "Mío")
    ajeno = hacer_ticket(otra, depto, "De otra persona")

    r = _listar(db_session, llano, {"staff"}, department_ids={depto.id})
    numeros = {x["ticket_number"] for x in r["tickets"]}

    assert suyo.ticket_number in numeros
    assert ajeno.ticket_number not in numeros, "sin read.department vio uno ajeno"


def test_el_scope_no_cruza_a_otro_departamento(org, db_session, hacer_ticket):
    """El permiso abre SU departamento, no todos."""
    mio, ajeno_d = org["dept"](), org["dept"]()
    secre = org["persona"]((mio, org["secretaria"], 10))
    forastera = org["persona"]((ajeno_d, org["sin_scope"], 10))
    de_fuera = hacer_ticket(forastera, ajeno_d)

    r = _listar(db_session, secre, {"secretary"})
    assert de_fuera.ticket_number not in {x["ticket_number"] for x in r["tickets"]}


# ===========================================================================
# 3. La misma familia: «¿es del Centro de Cómputo?»
# ===========================================================================
def test_ser_del_centro_de_computo_mira_TODOS_los_puestos(org, db_session):
    """Preguntaba por el departamento PRIMARIO (el del puesto más antiguo).

    Quien tuviera un puesto viejo en otro sitio y otro en Centro de Cómputo
    recibía «no» y perdía en silencio la edición de inventario. Hoy no le pasa a
    nadie —comprobado en la base— pero está a un alta de distancia.
    """
    from itcj2.apps.helpdesk.utils.inventory_access import is_comp_center_user

    otro = org["dept"]("Un depto cualquiera")
    computo = org["dept"]("CENTRO DE COMPUTO")
    u = org["persona"]((otro, None, 900), (computo, None, 5))

    assert is_comp_center_user(db_session, u.id) is True


def test_quien_no_es_de_computo_sigue_sin_serlo(org, db_session):
    from itcj2.apps.helpdesk.utils.inventory_access import is_comp_center_user
    u = org["persona"]((org["dept"]("Otro depto"), None, 10))
    assert is_comp_center_user(db_session, u.id) is False

def test_quien_tiene_read_subtree_no_pierde_sus_sub_departamentos(org, db_session, hacer_ticket):
    """El filtro de la página tiene que salir del MISMO conjunto que la visibilidad.

    Con un conjunto exacto de departamentos, un jefe con `read.subtree` perdía
    sus sub-departamentos. Medido sobre la base real antes de corregirlo: uno de
    ellos pasaba de 486 tickets a 20.
    """
    from itcj2.apps.helpdesk.services.ticket_service import department_scope_ids
    from itcj2.core.models.department import Department

    padre = org["dept"]("Subdireccion de prueba")
    jefa_sub = org["rol"]("sds_head_subtree",
                          [READ_DEPT, "helpdesk.tickets.api.read.subtree"])
    jefa = org["persona"]((padre, jefa_sub, 10))

    hijo = org["dept"]("Depto hijo")
    db_session.query(Department).filter_by(id=hijo.id).update({"parent_id": padre.id})
    db_session.flush()

    otra = org["persona"]((hijo, org["sin_scope"], 5))
    del_hijo = hacer_ticket(otra, hijo, "Del sub-departamento")

    assert hijo.id in department_scope_ids(db_session, jefa.id), (
        "el sub-departamento se cayó del alcance")

    r = _listar(db_session, jefa, {"department_head"},
                department_ids=department_scope_ids(db_session, jefa.id))
    assert del_hijo.ticket_number in {x["ticket_number"] for x in r["tickets"]}


def test_sin_alcance_departamental_la_pagina_no_se_queda_en_blanco(org, db_session, hacer_ticket):
    """Un conjunto VACÍO se traduce en `IN (-1)` y borra hasta los tickets propios.

    Hoy nadie abre esa página sin `read.department`, pero es un acoplamiento
    entre dos permisos: el modo de fallo tiene que ser degradar a «lo mío», no
    apagarse.
    """
    from itcj2.apps.helpdesk.services.ticket_service import department_scope_ids

    depto = org["dept"]()
    llano = org["persona"]((depto, org["sin_scope"], 10))
    suyo = hacer_ticket(llano, depto, "Mío")

    assert department_scope_ids(db_session, llano.id) == set()

    # Es lo que hace la página: conjunto vacío -> None, no `set()`.
    r = _listar(db_session, llano, {"staff"},
                department_ids=department_scope_ids(db_session, llano.id) or None)
    assert suyo.ticket_number in {x["ticket_number"] for x in r["tickets"]}

def test_los_kpis_del_dashboard_no_dan_403_a_la_secretaria(org, db_session, monkeypatch):
    """`/stats/department/{id}` tenía el MISMO gate por rol.

    Los cuatro KPIs de la cabecera salían con «-» y un 403 en consola para las 28
    secretarías, desde siempre. Solo se hizo visible al corregir el departamento
    que la página pedía: antes pedía el equivocado y fallaba igual.
    """
    from fastapi import HTTPException
    from itcj2.apps.helpdesk.api.stats import get_department_stats

    depto = org["dept"]()
    secre = org["persona"]((depto, org["secretaria"], 10))

    r = get_department_stats(department_id=depto.id,
                             user={"sub": str(secre.id), "role": ""}, db=db_session)
    assert r["success"] is True
    assert r["data"]["department_id"] == depto.id


def test_los_kpis_de_otro_departamento_siguen_prohibidos(org, db_session):
    """La negativa: el permiso abre SU departamento, no cualquiera."""
    import pytest as _pytest
    from fastapi import HTTPException
    from itcj2.apps.helpdesk.api.stats import get_department_stats

    mio, ajeno = org["dept"](), org["dept"]()
    secre = org["persona"]((mio, org["secretaria"], 10))

    with _pytest.raises(HTTPException) as exc:
        get_department_stats(department_id=ajeno.id,
                             user={"sub": str(secre.id), "role": ""}, db=db_session)
    assert exc.value.status_code == 403
