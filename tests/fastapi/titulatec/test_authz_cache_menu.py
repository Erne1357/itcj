"""R2 (spec rendimiento 2026-10-05 §3.3, hallazgo H5): permisos con caché y menú
admin evaluado solo donde se pinta.

Antes: `render_titulatec` llamaba a `admin_nav_items` en TODO render autenticado
(alumno y parciales HTMX incluidos), y éste abría una 3.ª sesión de BD y
resolvía los permisos SIN caché (~10 consultas). Además 12 sitios más de
`itcj2/apps/titulatec` llamaban a `get_user_permissions_for_app` sin caché.

Ahora:

1. Todos los sitios van por `cached_perms` (la MISMA fuente que el gate).
2. `admin_nav` entra al contexto como un CALLABLE perezoso y solo lo invoca
   `admin/base_admin.html`. Las vistas del alumno y los parciales no lo pagan.
3. `admin_nav_items(user_id, db=None)` usa la sesión que le pasen.

Los contadores miden SENTENCIAS sobre filas sembradas por el propio test
(`before_cursor_execute` en la conexión del test): nunca un total absoluto que
dependa de los datos reales de la base de dev.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import lxml.html
import pytest
from sqlalchemy import event

DASHBOARD = "/titulatec/student/dashboard"
DOCS_PAGE = "/titulatec/admin/documents"
DOCS_BODY = "/titulatec/admin/documents/body"

# Tablas que SOLO toca el cómputo de permisos efectivos (`effective_perm_set`:
# directos, vía roles y denegados). Con la caché tibia ninguna consulta debe
# tocarlas.
_TABLAS_DE_PERMISOS = re.compile(r"\bcore_(?:role_)?permissions\b")


class _Contador:
    """Cuenta las sentencias SQL reales que pasan por la conexión del test."""

    def __init__(self, conexion):
        self.conexion = conexion
        self.sentencias = []

    def __enter__(self):
        event.listen(self.conexion, "before_cursor_execute", self._ver)
        return self

    def __exit__(self, *exc):
        event.remove(self.conexion, "before_cursor_execute", self._ver)
        return False

    def _ver(self, conn, cursor, statement, params, context, executemany):
        self.sentencias.append(" ".join(statement.split()))

    def __len__(self):
        return len(self.sentencias)

    def de_permisos(self):
        return [s for s in self.sentencias if _TABLAS_DE_PERMISOS.search(s)]


@pytest.fixture()
def nav_spy(monkeypatch):
    """Registra cada llamada a `admin_nav_items`. Se parchea el atributo del
    módulo: `render_titulatec` lo resuelve como global en cada llamada."""
    import itcj2.apps.titulatec.pages.nav as nav

    llamadas: list = []
    original = nav.admin_nav_items

    def _espia(*args, **kwargs):
        llamadas.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(nav, "admin_nav_items", _espia)
    return llamadas


@pytest.fixture()
def alumno_con_proceso(make_student, make_process, seed_phase_defs, seed_document_types):
    seed_phase_defs()
    seed_document_types()
    student = make_student()
    make_process(student, current_phase=1)
    return student


# ---------------------------------------------------------------------------
# 1. El alumno y los parciales no pagan el menú admin
# ---------------------------------------------------------------------------
def test_el_tablero_del_alumno_no_calcula_el_menu_admin(client_as, alumno_con_proceso,
                                                        nav_spy):
    resp = client_as(alumno_con_proceso).get(DASHBOARD)

    assert resp.status_code == 200, resp.text[:500]
    assert nav_spy == [], "el tablero del alumno evaluó el menú admin %d vez/veces" % len(nav_spy)


def test_el_tablero_del_alumno_no_emite_consultas_de_permisos_con_la_cache_tibia(
    client_as, db_session, alumno_con_proceso,
):
    """Primera petición: el gate llena la caché (y lo que haga la página).
    Segunda: ninguna sentencia puede tocar las tablas de permisos efectivos --
    antes el menú las recomputaba SIN caché en cada render."""
    cli = client_as(alumno_con_proceso)
    assert cli.get(DASHBOARD).status_code == 200

    with _Contador(db_session.get_bind()) as c:
        resp = cli.get(DASHBOARD)

    assert resp.status_code == 200, resp.text[:500]
    assert c.de_permisos() == [], "\n".join(c.de_permisos())


def test_un_parcial_htmx_admin_no_evalua_el_menu(client_as, make_head, nav_spy):
    """`documents/body` es un parcial (no extiende `base_admin.html`)."""
    head = make_head()

    resp = client_as(head).get(DOCS_BODY)

    assert resp.status_code == 200, resp.text[:500]
    assert nav_spy == []


def test_la_pagina_admin_completa_evalua_el_menu_una_sola_vez(client_as, make_head, nav_spy):
    head = make_head()

    resp = client_as(head).get(DOCS_PAGE)

    assert resp.status_code == 200, resp.text[:500]
    assert len(nav_spy) == 1, "se esperaba 1 evaluación del menú, hubo %d" % len(nav_spy)


# ---------------------------------------------------------------------------
# 2. El menú admin sigue siendo el que corresponde al permiso
# ---------------------------------------------------------------------------
def _sidebar(html: str) -> list[tuple[str, str]]:
    doc = lxml.html.fromstring(html)
    return [(a.get("hx-get"), " ".join(a.text_content().split()))
            for a in doc.xpath('//aside[@id="ttSide"]//a[@hx-get]')]


def test_la_pagina_admin_pinta_solo_los_items_que_concede_cada_permiso(client_as, make_head):
    head = make_head(perm_codes=("titulatec.document.page.list",
                                 "titulatec.appointment.page.list"))

    resp = client_as(head).get(DOCS_PAGE)

    assert resp.status_code == 200, resp.text[:500]
    assert _sidebar(resp.text) == [
        ("/titulatec/admin/documents", "Documentos"),
        ("/titulatec/admin/appointments", "Citas de cotejo"),
    ]


def test_el_menu_sigue_la_tabla_de_nav_para_el_set_completo(client_as, make_head):
    """Con el set por omisión de la jefa el menú es exactamente lo que
    `_ADMIN_NAV` concede a esos permisos, en el orden de la tabla."""
    from itcj2.apps.titulatec.pages.nav import _ADMIN_NAV
    from tests.fastapi.titulatec.conftest import HEAD_PERMS

    head = make_head()

    resp = client_as(head).get(DOCS_PAGE)

    assert resp.status_code == 200, resp.text[:500]
    esperado = [(url, label) for label, _i, url, need in _ADMIN_NAV
                if set(HEAD_PERMS) & need]
    assert _sidebar(resp.text) == esperado
    assert esperado, "control anti-vacío: la jefa debe ver al menos un item"


# ---------------------------------------------------------------------------
# 3. `admin_nav_items(user_id, db=None)`
# ---------------------------------------------------------------------------
def test_admin_nav_items_usa_la_sesion_que_recibe(db_session, make_head, monkeypatch):
    """Con `db` no abre una 3.ª sesión: `SessionLocal` no se toca."""
    from itcj2.apps.titulatec.pages.nav import admin_nav_items

    head = make_head(perm_codes=("titulatec.document.page.list",))

    def _prohibida():
        raise AssertionError("admin_nav_items abrió su propia sesión teniendo `db`")

    monkeypatch.setattr("itcj2.database.SessionLocal", _prohibida)

    items = admin_nav_items(head.id, db_session)

    assert [i["label"] for i in items] == ["Documentos"]


def test_admin_nav_items_sin_db_abre_la_suya_como_antes(patched_session_local, make_head):
    from itcj2.apps.titulatec.pages.nav import admin_nav_items

    head = make_head(perm_codes=("titulatec.document.page.list",))

    items = admin_nav_items(head.id)

    assert items == [{"label": "Documentos", "icon": "bi-file-earmark-check",
                      "url": "/titulatec/admin/documents"}]


def test_admin_nav_items_usa_la_cache(db_session, make_head):
    """Con la caché tibia no emite consultas de permisos."""
    from itcj2.apps.titulatec.pages.nav import admin_nav_items
    from itcj2.core.services.authz_cache import cached_perms

    head = make_head()
    cached_perms(db_session, head.id, "titulatec")  # tibia

    with _Contador(db_session.get_bind()) as c:
        items = admin_nav_items(head.id, db_session)

    assert items
    assert c.de_permisos() == [], "\n".join(c.de_permisos())


def test_el_menu_es_un_callable_perezoso_en_el_contexto(db_session, make_head, monkeypatch):
    """`render_titulatec` NO calcula nada: deja un callable que solo evalúa
    quien lo invoque. Se mira el contexto que llega a la plantilla."""
    from starlette.requests import Request
    import itcj2.apps.titulatec.pages.nav as nav

    head = make_head()
    capturado: dict = {}

    def _fake_response(request, template, ctx, status_code=200):
        capturado.update(ctx)
        return None

    monkeypatch.setattr(nav.titulatec_templates, "TemplateResponse", _fake_response)
    llamadas: list = []
    original = nav.admin_nav_items
    monkeypatch.setattr(nav, "admin_nav_items",
                        lambda *a, **k: llamadas.append(a) or original(*a, **k))

    scope = {"type": "http", "method": "GET", "path": "/x", "headers": [],
             "query_string": b"", "server": ("t", 80), "scheme": "http"}
    request = Request(scope)
    request.state.current_user = {"sub": str(head.id)}

    nav.render_titulatec(request, "titulatec/student/dashboard.html", {})

    assert callable(capturado["admin_nav"])
    assert llamadas == [], "render_titulatec evaluó el menú al armar el contexto"


# ---------------------------------------------------------------------------
# 4. Los sitios migrados: misma respuesta, misma fuente que el gate
# ---------------------------------------------------------------------------
_APP_DIR = Path(__file__).resolve().parents[3] / "itcj2" / "apps" / "titulatec"


def test_ningun_sitio_de_titulatec_llama_a_get_user_permissions_for_app():
    """Estructural: la única fuente de permisos de TitulaTec es `cached_perms`.
    Barre `itcj2/apps/titulatec/**/*.py` por llamadas e importaciones."""
    culpables = []
    for path in sorted(_APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                nombre = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
                if nombre == "get_user_permissions_for_app":
                    culpables.append(f"{path.relative_to(_APP_DIR)}:{node.lineno}")
            elif isinstance(node, ast.ImportFrom):
                if any(a.name == "get_user_permissions_for_app" for a in node.names):
                    culpables.append(f"{path.relative_to(_APP_DIR)}:{node.lineno} (import)")
    assert culpables == [], "sitios sin migrar a cached_perms:\n  " + "\n  ".join(culpables)


def test_cached_perms_devuelve_lo_mismo_que_get_user_permissions_for_app(
    db_session, make_head, make_student,
):
    from itcj2.core.services.authz_cache import cached_perms
    from itcj2.core.services.authz_service import get_user_permissions_for_app

    for actor in (make_head(), make_student()):
        esperado = get_user_permissions_for_app(db_session, actor.id, "titulatec")
        frio = cached_perms(db_session, actor.id, "titulatec")
        tibio = cached_perms(db_session, actor.id, "titulatec")
        assert esperado  # control anti-vacío
        assert frio == esperado == tibio


def _sitio_visible_kinds(db, uid, **_):
    from itcj2.apps.titulatec.pages.certificates_admin import _visible_kinds
    return _visible_kinds(db, uid)


def _sitio_puede_todo(db, uid, **_):
    from itcj2.apps.titulatec.pages.appointments import _puede_todo
    return _puede_todo(db, uid)


def _sitio_cotejo_reqs(db, uid, *, cohort, **_):
    from itcj2.apps.titulatec.pages.admin import _cotejo_reqs_ctx
    return _cotejo_reqs_ctx(db, cohort.id, uid)["can_edit_reqs"]


def _sitio_docs_body(db, uid, **_):
    from itcj2.apps.titulatec.pages.documents import _body_ctx
    return _body_ctx(db, user_id=uid, status_filter=None,
                     selected_id=None)["can_review_docs"]


def _sitio_handoff_body(db, uid, **_):
    from itcj2.apps.titulatec.pages.handoff_admin import _body_ctx
    return _body_ctx(db, user_id=uid, cohort_id=None, program_id=None,
                     modality_id=None, q=None, page=1)["can_export"]


_SITIOS = [
    pytest.param(_sitio_visible_kinds, id="certificates_admin._visible_kinds"),
    pytest.param(_sitio_puede_todo, id="appointments._puede_todo"),
    pytest.param(_sitio_cotejo_reqs, id="admin._cotejo_reqs_ctx"),
    pytest.param(_sitio_docs_body, id="documents._body_ctx"),
    pytest.param(_sitio_handoff_body, id="handoff_admin._body_ctx"),
]


@pytest.mark.parametrize("sitio", _SITIOS)
def test_cada_sitio_migrado_usa_la_cache_tibia(sitio, db_session, make_head, make_cohort,
                                               seed_document_types):
    """Con la caché tibia ningún sitio emite consultas de permisos efectivos."""
    from itcj2.core.services.authz_cache import cached_perms

    seed_document_types()
    head = make_head()
    cohort = make_cohort()
    cached_perms(db_session, head.id, "titulatec")  # tibia

    with _Contador(db_session.get_bind()) as c:
        sitio(db_session, head.id, cohort=cohort)

    assert c.de_permisos() == [], "\n".join(c.de_permisos())


def test_los_sitios_migrados_dicen_lo_mismo_con_y_sin_permiso(db_session, make_head,
                                                              make_cohort,
                                                              seed_document_types):
    """Mismas respuestas que antes de migrar: con el permiso, verdadero; sin él,
    falso. (Los `can_*` ya existentes; `_visible_kinds` en el orden de CERT_KINDS)."""
    from itcj2.apps.titulatec.pages.certificates_admin import CERT_KINDS, _KIND_PERM

    seed_document_types()
    cohort = make_cohort()
    # Cada actor lleva un rol FICTICIO propio: `make_head` reutiliza el rol por
    # nombre y SUMA permisos, así que dos jefes en un test compartirían el
    # segundo set. Un solo set con TODO y otro con NADA relevante basta.
    con = make_head(perm_codes=(
        "titulatec.review_window.api.manage.all",
        "titulatec.cohort.api.cotejo_reqs",
        "titulatec.document.api.approve",
        "titulatec.handoff.api.export",
        *_KIND_PERM.values(),
    ))

    assert _sitio_puede_todo(db_session, con.id) is True
    assert _sitio_cotejo_reqs(db_session, con.id, cohort=cohort) is True
    assert _sitio_docs_body(db_session, con.id) is True
    assert _sitio_handoff_body(db_session, con.id) is True
    assert _sitio_visible_kinds(db_session, con.id) == list(CERT_KINDS)
