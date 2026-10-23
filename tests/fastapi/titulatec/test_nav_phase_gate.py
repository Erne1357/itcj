"""Menú y aterrizaje de las pantallas que operan una fase (ruling R5, revisión de
rama de la fase 4).

En producción el corte a T-soft es 3 y el DML base YA da `synodal.page.list` a
`titulatec_vinculacion` (y a `admin` los permisos de fase 2 tras
`init-titulatec-fase-2`): sin una guarda de fase, «Sinodales» se vería en el
menú y la vinculación aterrizaría ahí al desplegar, aunque la pantalla sea un
estado vacío. Regla de la casa: con el corte en 3 nada nuevo es visible.

- `nav._NAV_PHASE_GATE`: la fase mínima de cada pantalla, por CÓDIGO del
  catálogo (`format_b` para «Titulación»; `synodal_assignment` para
  «Sinodales», «Docentes» y «Carreras por depto»). `admin_nav_items` oculta el
  ítem si `PhaseService._handoff_phase() <= número de esa fase`; sin la fase en
  el catálogo, oculto (falla cerrado). Una sola consulta al catálogo por menú,
  y ninguna si el usuario no tiene ítems con fase.
- `resolve_dashboard_url(..., operable=...)`: los aterrizajes condicionales
  (Titulación y Sinodales) exigen permiso Y que su fase se opere; sin
  `operable`, falla cerrado al aterrizaje de siempre. `landing.py` lo calcula
  con `PhaseService.operable_codes`.
"""
from __future__ import annotations

import os
import re

import lxml.html
import pytest
from sqlalchemy import event

from itcj2.apps.titulatec.services.phase_service import PhaseService

_RUN = os.getpid()
ROLE_TODO = f"tt_test_navgate_todo_{_RUN}"
ROLE_SIN_FASE = f"tt_test_navgate_sinfase_{_RUN}"

DOCS = ("/titulatec/admin/documents", "Documentos", "titulatec.document.page.list")
TITULACION = ("/titulatec/admin/titulacion", "Titulación", "titulatec.titulacion.page.list")
SINODALES = ("/titulatec/admin/sinodales", "Sinodales", "titulatec.synodal.page.list")
DOCENTES = ("/titulatec/admin/docentes", "Docentes", "titulatec.teacher.page.list")
CARRERAS = ("/titulatec/admin/carreras-deptos", "Carreras por depto",
            "titulatec.program_department.page.list")
FASE_4 = (SINODALES, DOCENTES, CARRERAS)
TODOS = (DOCS, TITULACION) + FASE_4
PERMS = tuple(p for _u, _l, p in TODOS)

VINCULACION = "/titulatec/vinculacion/"
LIBERADOS = "/titulatec/admin/liberados"


@pytest.fixture()
def corte(monkeypatch, seed_phase_defs):
    seed_phase_defs()

    def _fijar(fase):
        monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: fase))
    return _fijar


def _items(user_id, db):
    from itcj2.apps.titulatec.pages.nav import admin_nav_items
    return [(i["url"], i["label"]) for i in admin_nav_items(user_id, db)]


def _sidebar(html: str) -> list[tuple[str, str]]:
    doc = lxml.html.fromstring(html)
    return [(a.get("hx-get"), " ".join(a.text_content().split()))
            for a in doc.xpath('//aside[@id="ttSide"]//a[@hx-get]')]


def _par(item):
    url, label, _p = item
    return (url, label)


class _Contador:
    def __init__(self, conexion):
        self.conexion, self.sentencias = conexion, []

    def __enter__(self):
        event.listen(self.conexion, "before_cursor_execute", self._ver)
        return self

    def __exit__(self, *exc):
        event.remove(self.conexion, "before_cursor_execute", self._ver)
        return False

    def _ver(self, conn, cursor, statement, params, context, executemany):
        self.sentencias.append(" ".join(statement.split()))

    def del_catalogo(self):
        return [s for s in self.sentencias if "titulatec_phase_definitions" in s]


# ---------------------------------------------------------------------------
# La tabla
# ---------------------------------------------------------------------------
def test_la_tabla_de_fases_minimas_es_la_del_ruling():
    from itcj2.apps.titulatec.pages.nav import _ADMIN_NAV, _NAV_PHASE_GATE

    assert _NAV_PHASE_GATE == {
        TITULACION[0]: "format_b",
        SINODALES[0]: "synodal_assignment",
        DOCENTES[0]: "synodal_assignment",
        CARRERAS[0]: "synodal_assignment",
        # «Mis revisiones» del docente (fase 5 §8.2, test_revisiones_admin.py).
        "/titulatec/admin/revisiones": "synodal_review",
    }
    # Cada llave es un ítem real del menú (un typo dejaría la guarda muerta).
    assert set(_NAV_PHASE_GATE) <= {url for _l, _i, url, _n in _ADMIN_NAV}


# ---------------------------------------------------------------------------
# `admin_nav_items`
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("cut,visibles", [
    (3, (DOCS,)),                         # producción: nada de fase 3 en adelante
    (4, (DOCS, TITULACION)),              # el Formato B se opera; la fase 4 no
    (10, TODOS),                          # dev
])
def test_el_menu_oculta_lo_que_el_corte_no_opera(cut, visibles, corte, db_session,
                                                 make_user, make_role, grant_user_role):
    corte(cut)
    user = make_user(first_name="TODO", last_name="NAVGATE")
    grant_user_role(user, make_role(ROLE_TODO, PERMS))

    items = _items(user.id, db_session)

    assert [i for i in items if i in {_par(t) for t in TODOS}] == [_par(t) for t in visibles]


@pytest.mark.parametrize("cut", [3, 10])
def test_admin_y_vinculacion_con_los_roles_reales(cut, corte, db_session, make_user,
                                                  make_role, grant_user_role):
    """Los nombres REALES de los roles (la base de dev ya trae sus permisos de
    fase 2; en CI se crean aquí): con el corte en 3 ninguno ve las pantallas de
    fase; con 10, sí."""
    corte(cut)
    admin = make_user(first_name="ADMIN", last_name="NAVGATE")
    grant_user_role(admin, make_role("admin", PERMS))
    vinc = make_user(first_name="VINCULACION", last_name="NAVGATE")
    grant_user_role(vinc, make_role("titulatec_vinculacion",
                                    (SINODALES[2], DOCENTES[2])))

    del_admin = set(_items(admin.id, db_session))
    de_vinc = set(_items(vinc.id, db_session))

    gated_admin = {_par(t) for t in (TITULACION,) + FASE_4}
    gated_vinc = {_par(SINODALES), _par(DOCENTES)}
    if cut == 3:
        assert not del_admin & gated_admin, del_admin
        assert not de_vinc & gated_vinc, de_vinc
        assert _par(DOCS) in del_admin    # control anti-vacío
    else:
        assert gated_admin <= del_admin
        assert gated_vinc <= de_vinc


def test_sin_la_fase_en_el_catalogo_el_item_se_oculta(corte, db_session, make_user,
                                                      make_role, grant_user_role,
                                                      monkeypatch):
    """Falla cerrado: un catálogo sin `synodal_assignment` no abre nada."""
    corte(10)
    real = PhaseService.operable_codes

    def _sin_fase_4(db, codes):
        return real(db, [c for c in codes if c != "synodal_assignment"])

    monkeypatch.setattr(PhaseService, "operable_codes", staticmethod(_sin_fase_4))
    user = make_user(first_name="SINFASE", last_name="NAVGATE")
    grant_user_role(user, make_role(ROLE_SIN_FASE, PERMS))

    items = _items(user.id, db_session)

    assert _par(TITULACION) in items
    assert not {_par(t) for t in FASE_4} & set(items)


def test_un_catalogo_que_truena_oculta_solo_los_items_de_fase(corte, db_session, make_user,
                                                             make_role, grant_user_role,
                                                             monkeypatch):
    corte(10)

    def _truena(db, codes):
        raise RuntimeError("catalogo caido")

    monkeypatch.setattr(PhaseService, "operable_codes", staticmethod(_truena))
    user = make_user(first_name="TRUENA", last_name="NAVGATE")
    grant_user_role(user, make_role(ROLE_TODO, PERMS))

    assert _items(user.id, db_session) == [_par(DOCS)]


def test_el_menu_consulta_el_catalogo_una_vez_y_solo_si_hace_falta(
        corte, db_session, make_user, make_role, grant_user_role):
    from itcj2.core.services.authz_cache import cached_perms

    corte(10)
    con = make_user(first_name="CON", last_name="NAVGATE")
    grant_user_role(con, make_role(ROLE_TODO, PERMS))
    sin = make_user(first_name="SIN", last_name="NAVGATE")
    grant_user_role(sin, make_role(f"{ROLE_TODO}_docs", (DOCS[2],)))
    for u in (con, sin):
        cached_perms(db_session, u.id, "titulatec")   # caché tibia

    with _Contador(db_session.get_bind()) as c_con:
        _items(con.id, db_session)
    with _Contador(db_session.get_bind()) as c_sin:
        _items(sin.id, db_session)

    assert len(c_con.del_catalogo()) == 1, c_con.del_catalogo()
    assert c_sin.del_catalogo() == [], c_sin.del_catalogo()


def test_la_pagina_completa_pinta_el_menu_recortado(corte, client_as, make_user, make_role,
                                                    grant_user_role):
    corte(3)
    user = make_user(first_name="PAGINA", last_name="NAVGATE")
    grant_user_role(user, make_role(ROLE_TODO, PERMS))

    resp = client_as(user).get(DOCS[0])

    assert resp.status_code == 200, resp.text[:300]
    menu = _sidebar(resp.text)
    assert _par(DOCS) in menu
    assert not {_par(t) for t in (TITULACION,) + FASE_4} & set(menu), menu


# ---------------------------------------------------------------------------
# Aterrizaje
# ---------------------------------------------------------------------------
def test_resolve_dashboard_url_exige_permiso_y_fase_operable():
    from itcj2.apps.titulatec.pages.nav import resolve_dashboard_url

    vinc, tit = {"titulatec_vinculacion"}, {"titulatec_titulacion"}
    assert resolve_dashboard_url(vinc, perms={SINODALES[2]},
                                 operable={"synodal_assignment"}) == SINODALES[0]
    assert resolve_dashboard_url(vinc, perms={SINODALES[2]}, operable=set()) == VINCULACION
    # Sin `operable` (otros llamadores): falla cerrado, el aterrizaje de siempre.
    assert resolve_dashboard_url(vinc, perms={SINODALES[2]}) == VINCULACION
    # Operable sin el permiso tampoco.
    assert resolve_dashboard_url(vinc, perms=set(),
                                 operable={"synodal_assignment"}) == VINCULACION

    assert resolve_dashboard_url(tit, perms={TITULACION[2]},
                                 operable={"format_b"}) == TITULACION[0]
    assert resolve_dashboard_url(tit, perms={TITULACION[2]}, operable=set()) == LIBERADOS
    # La fase de OTRA pantalla no abre esta.
    assert resolve_dashboard_url(tit, perms={TITULACION[2]},
                                 operable={"synodal_assignment"}) == LIBERADOS


def _rol_real(db_session, make_role, nombre, perm):
    """El rol REAL (el landing resuelve por nombre) con `perm` concedido."""
    return make_role(nombre, (perm,))


@pytest.mark.parametrize("cut,destino", [(3, VINCULACION), (10, SINODALES[0])])
def test_el_landing_de_vinculacion_sigue_al_corte(cut, destino, corte, db_session, client_as,
                                                  make_user, make_role, grant_user_role):
    corte(cut)
    user = make_user(first_name="COORD", last_name="NAVGATE")
    grant_user_role(user, _rol_real(db_session, make_role, "titulatec_vinculacion",
                                    SINODALES[2]))

    resp = client_as(user).get("/titulatec/", follow_redirects=False)

    assert resp.status_code == 302, resp.text[:300]
    assert resp.headers["location"] == destino


@pytest.mark.parametrize("cut,destino", [(3, LIBERADOS), (4, TITULACION[0])])
def test_el_landing_de_titulacion_sigue_al_corte(cut, destino, corte, db_session, client_as,
                                                 make_user, make_role, grant_user_role):
    corte(cut)
    user = make_user(first_name="AUX", last_name="NAVGATE")
    grant_user_role(user, _rol_real(db_session, make_role, "titulatec_titulacion",
                                    TITULACION[2]))

    resp = client_as(user).get("/titulatec/", follow_redirects=False)

    assert resp.status_code == 302, resp.text[:300]
    assert resp.headers["location"] == destino


def test_landing_calcula_la_fase_con_el_catalogo():
    """Estructural: el landing pasa `operable` (no deja el default fail-closed
    por olvido, que mandaría a todos a su aterrizaje viejo para siempre)."""
    from pathlib import Path
    import itcj2.apps.titulatec as _tt_pkg

    fuente = (Path(_tt_pkg.__file__).resolve().parent / "pages" / "landing.py").read_text(
        encoding="utf-8")
    llamadas = [m.group(0) for m in re.finditer(r"resolve_dashboard_url\(.*?\)\n", fuente, re.S)]
    assert llamadas and all("operable=" in c for c in llamadas), llamadas
    assert "operable_codes" in fuente
