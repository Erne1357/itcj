"""Tests de la página **dashboard** de Calidad (F5, sección "dashboard").

Cubre ``itcj2/apps/adhoc/pages/dashboard.py`` (``GET /adhoc/dashboard``,
permiso ``adhoc.dashboard.page.view``), su template, su CSS y su JS.

Qué se comprueba y por qué:

* **View-model** (``build_card``): el legacy metía la lógica de "atención
  requerida", el formato de fecha y el origen de la tarea dentro de Jinja. Aquí
  vive en Python y se prueba sin HTTP.
* **N+1 de solicitantes** (``_creator_names``): una query en lote, y ninguna si
  no hay creadores. El legacy hacía ``tarea.creator.first_name`` por tarjeta.
* **Gate real**: el legacy tenía ``@login_required`` *encima* de ``@bp.route``
  (bug #25), o sea la página era pública. Aquí: 302 a login para anónimo y 403
  HTML sin el permiso.
* **XSS**: la descripción de la tarea sale escapada del template.
* **Reglas duras del plan §6.2/§6.3** sobre mis tres archivos estáticos.

Harness (plan §9.1): las páginas devuelven HTML (302/403 renderizado, no JSON);
un JWT con ``role="admin"`` bypasea los permisos, así que el 403 se prueba con
``role="staff"`` + ``patch`` de ``cached_has_assignment``/``cached_perms``; los
imports son locales dentro de las funciones, así que se parchea el **módulo
fuente**.

Nota de cableado: ``pages/router.py`` es propiedad de la fase siguiente, así que
todavía no incluye este router (y ``pages/home.py`` sirve un placeholder de F0 en
la misma URL). El fixture ``client`` levanta por eso una app mínima con el mismo
middleware de JWT y los mismos manejadores de error que la real, y monta encima
**solo** el router de esta sección con su prefijo ``/adhoc``: así el gate y el
render se prueban de verdad sin depender del archivo compartido ni pisar al
placeholder.
"""
import re
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from itcj2.apps.adhoc.pages.dashboard import (
    DASHBOARD_PERM,
    _action_flags,
    _creator_names,
    _format_date,
    build_card,
    router as dashboard_router,
)
from itcj2.apps.adhoc.services.task_service import AdhocTaskService
from itcj2.database import get_db
from tests.conftest import TEST_SECRET, make_jwt

APP_ROOT = Path(__file__).resolve().parents[3] / "itcj2" / "apps" / "adhoc"
TEMPLATE = APP_ROOT / "templates" / "adhoc" / "dashboard" / "dashboard.html"
CSS = APP_ROOT / "static" / "css" / "dashboard" / "dashboard.css"
JS = APP_ROOT / "static" / "js" / "dashboard" / "dashboard.js"

TODAY = date(2026, 8, 25)


# ==========================================================================
# Dobles
# ==========================================================================

class FakeUser:
    def __init__(self, uid, full_name):
        self.id = uid
        self.full_name = full_name


class FakeParent:
    def __init__(self, title=None, version=None):
        self.title = title
        self.version = version


class FakeTask:
    """Lo mínimo que build_card() toca de una AdhocTask."""

    def __init__(self, **kw):
        self.id = kw.get("id", 1)
        self.description = kw.get("description", "Revisar extintores")
        self.status = kw.get("status", "Pendiente")
        self.priority = kw.get("priority", "Media")
        self.due_date = kw.get("due_date")
        self.created_by_id = kw.get("created_by_id")
        self.comments = kw.get("comments", [])
        self.incident_id = kw.get("incident_id")
        self.program_id = kw.get("program_id")
        self.document_id = kw.get("document_id")
        self.incident = kw.get("incident")
        self.program = kw.get("program")
        self.document = kw.get("document")


class StubDb:
    """Sesión falsa: solo tiene que servir el lote de solicitantes.

    Cuenta las llamadas a ``query`` para poder afirmar que el dashboard no
    dispara un SELECT por tarjeta (el N+1 del legacy).
    """

    def __init__(self, users=None):
        self.users = list(users or [])
        self.queries = 0

    def query(self, *args, **kwargs):
        self.queries += 1
        return self

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return list(self.users)


# ==========================================================================
# _format_date
# ==========================================================================

class TestFormatDate:
    def test_fecha_en_espanol_sin_depender_del_locale(self):
        """`strftime('%b')` da "Aug" con el locale C del contenedor."""
        assert _format_date(date(2026, 8, 5)) == "05 ago 2026"
        assert _format_date(date(2026, 12, 31)) == "31 dic 2026"

    def test_sin_fecha(self):
        assert _format_date(None) == "Sin fecha"


# ==========================================================================
# build_card
# ==========================================================================

class TestBuildCard:
    def test_tarea_documental_en_revision(self):
        task = FakeTask(
            status="En Revisión",
            document_id=7,
            document=FakeParent("Manual de Calidad", "2.1"),
        )
        card = build_card(task, {}, TODAY)
        assert card["parent_kind"] == "document"
        assert card["parent_label"] == "Documento ISO"
        assert card["parent_title"] == "Manual de Calidad"
        assert card["parent_version"] == "2.1"
        assert card["is_review"] is True

    def test_incidencia_no_expone_version(self):
        task = FakeTask(incident_id=3, incident=FakeParent("Fuga de agua", "9.9"))
        card = build_card(task, {}, TODAY)
        assert card["parent_kind"] == "incident"
        assert card["parent_label"] == "Incidencia"
        assert card["parent_version"] is None

    def test_evento_de_programa(self):
        task = FakeTask(program_id=4, program=FakeParent("Auditoría interna"))
        card = build_card(task, {}, TODAY)
        assert card["parent_kind"] == "program"
        assert card["parent_label"] == "Programa"

    def test_sin_padre_no_revienta(self):
        card = build_card(FakeTask(), {}, TODAY)
        assert card["parent_kind"] is None
        assert card["parent_label"] == "Sin origen"
        assert card["parent_title"] is None

    def test_vencida_pide_atencion(self):
        task = FakeTask(due_date=date(2026, 8, 1), status="Pendiente")
        card = build_card(task, {}, TODAY)
        assert card["is_overdue"] is True
        assert card["needs_attention"] is True

    @pytest.mark.parametrize("status", ["Completada", "En Revisión"])
    def test_vencida_pero_ya_resuelta_no_alarma(self, status):
        """Si ya está en manos de otro, la fecha pasada no es una alerta."""
        task = FakeTask(due_date=date(2026, 8, 1), status=status)
        card = build_card(task, {}, TODAY)
        assert card["is_overdue"] is False
        assert card["needs_attention"] is False

    def test_urgente_pide_atencion_aunque_no_venza(self):
        task = FakeTask(priority="Urgente", due_date=date(2027, 1, 1))
        assert build_card(task, {}, TODAY)["needs_attention"] is True

    def test_en_espera_queda_bloqueada(self):
        card = build_card(FakeTask(status="En Espera"), {}, TODAY)
        assert card["is_locked"] is True
        assert card["is_review"] is False

    def test_rechazada(self):
        assert build_card(FakeTask(status="Rechazada"), {}, TODAY)["is_rejected"] is True

    def test_solicitante_resuelto_del_lote(self):
        task = FakeTask(created_by_id=42)
        assert build_card(task, {42: "Ana López"}, TODAY)["creator_name"] == "Ana López"

    def test_solicitante_desconocido_cae_a_sistema(self):
        assert build_card(FakeTask(), {}, TODAY)["creator_name"] == "Sistema"

    def test_cuenta_comentarios_sin_query_extra(self):
        card = build_card(FakeTask(comments=[object(), object()]), {}, TODAY)
        assert card["comments_count"] == 2


# ==========================================================================
# _creator_names — el N+1 del legacy
# ==========================================================================

class TestCreatorNames:
    def test_sin_creadores_no_consulta(self):
        db = StubDb()
        assert _creator_names(db, [FakeTask(), FakeTask()]) == {}
        assert db.queries == 0

    def test_una_sola_query_para_todas_las_tarjetas(self):
        db = StubDb([FakeUser(1, "Ana López"), FakeUser(2, "Beto Ruiz")])
        tasks = [FakeTask(created_by_id=1), FakeTask(created_by_id=2), FakeTask(created_by_id=1)]
        assert _creator_names(db, tasks) == {1: "Ana López", 2: "Beto Ruiz"}
        assert db.queries == 1

    def test_usuario_sin_nombre_cae_a_sistema(self):
        db = StubDb([FakeUser(1, None)])
        assert _creator_names(db, [FakeTask(created_by_id=1)]) == {1: "Sistema"}

    def test_error_de_bd_no_tumba_la_pagina(self):
        db = MagicMock()
        db.query.side_effect = RuntimeError("sin BD")
        assert _creator_names(db, [FakeTask(created_by_id=1)]) == {}


# ==========================================================================
# _action_flags — solo ocultan botones, no son el gate
# ==========================================================================

class TestActionFlags:
    def test_admin_global_ve_todo(self):
        db = MagicMock()
        flags = _action_flags(db, {"sub": "1", "role": "admin"})
        assert flags == {"can_workflow": True, "can_comment": True}
        db.query.assert_not_called()

    def test_permisos_parciales(self):
        with patch(
            "itcj2.core.services.authz_cache.cached_perms",
            return_value={"adhoc.tasks.api.workflow"},
        ):
            flags = _action_flags(MagicMock(), {"sub": "9", "role": "staff"})
        assert flags == {"can_workflow": True, "can_comment": False}

    def test_error_al_calcular_permisos_oculta_los_botones(self):
        with patch(
            "itcj2.core.services.authz_cache.cached_perms",
            side_effect=RuntimeError("sin Redis ni BD"),
        ):
            flags = _action_flags(MagicMock(), {"sub": "9", "role": "staff"})
        assert flags == {"can_workflow": False, "can_comment": False}


# ==========================================================================
# HTTP
# ==========================================================================

@pytest.fixture(scope="module")
def db_stub():
    return StubDb()


@pytest.fixture(scope="module")
def client(db_stub):
    """App mínima con SOLO el router de esta sección montado en ``/adhoc``.

    No se usa ``create_app()`` para no acoplar los tests de esta sección al
    cableado de ``pages/router.py`` (ni al resto de apps del proyecto): el
    montaje completo lo cubre ``test_pages_base.py`` por HTTP contra la app
    real. Aquí se replica lo que sí importa para probar la página:
    el middleware de JWT (que llena ``request.state.current_user``) y los
    manejadores de ``PageLoginRequired`` / ``PageForbidden``.
    """
    from fastapi import FastAPI

    with patch("itcj2.middleware._JWT_SECRET", TEST_SECRET):
        from itcj2.main import _register_error_handlers
        from itcj2.middleware import setup_middleware

        app = FastAPI()
        setup_middleware(app)
        app.include_router(dashboard_router, prefix="/adhoc")
        _register_error_handlers(app)

        def _override():
            yield db_stub

        app.dependency_overrides[get_db] = _override
        with TestClient(app) as c:
            yield c
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def admin_headers():
    return {"Cookie": f"itcj_token={make_jwt(user_id=200, role='admin')}"}


@pytest.fixture()
def staff_headers():
    return {"Cookie": f"itcj_token={make_jwt(user_id=201, role='staff')}"}


@pytest.fixture()
def board():
    """Patchea el tablero para no tocar BD; recibe la lista de tareas."""
    def _apply(tasks):
        return patch.object(AdhocTaskService, "get_dashboard_tasks", return_value=tasks)
    return _apply


#: Todos los permisos que la página consulta. El JWT con ``role="admin"``
#: bypasea `require_perms` de la API, pero NO `require_page_app`, que resuelve
#: contra `cached_has_assignment`/`cached_perms`: en los tests hay que
#: parchearlos igual (y son imports locales → se parchea el módulo fuente).
FULL_PERMS = {DASHBOARD_PERM, "adhoc.tasks.api.workflow", "adhoc.tasks.api.comment"}


@pytest.fixture(autouse=True)
def authz():
    """Gate de página parcheado. Mutar ``authz["perms"]`` cambia el escenario."""
    state = {"has": True, "perms": set(FULL_PERMS)}
    with patch(
        "itcj2.core.services.authz_cache.cached_has_assignment",
        side_effect=lambda *a, **k: state["has"],
    ), patch(
        "itcj2.core.services.authz_cache.cached_perms",
        side_effect=lambda *a, **k: set(state["perms"]),
    ):
        yield state


class TestPaginaDashboard:
    def test_anonimo_va_al_login(self, client):
        res = client.get("/adhoc/dashboard", follow_redirects=False)
        assert res.status_code in (302, 307)
        assert "/itcj/login" in res.headers["location"]

    def test_sin_acceso_a_la_app_es_403_html(self, client, staff_headers, board, authz):
        authz["has"] = False
        with board([]):
            res = client.get("/adhoc/dashboard", headers=staff_headers)
        assert res.status_code == 403
        assert "text/html" in res.headers["content-type"]

    def test_sin_permiso_de_pagina_es_403_html(self, client, staff_headers, board, authz):
        authz["perms"] = {"adhoc.documents.page.list"}
        with board([]):
            res = client.get("/adhoc/dashboard", headers=staff_headers)
        assert res.status_code == 403
        assert "text/html" in res.headers["content-type"]

    def test_con_el_permiso_exacto_responde_200(self, client, staff_headers, board, authz):
        authz["perms"] = {DASHBOARD_PERM}
        with board([]):
            res = client.get("/adhoc/dashboard", headers=staff_headers)
        assert res.status_code == 200
        assert DASHBOARD_PERM == "adhoc.dashboard.page.view"

    def test_tablero_vacio_pinta_el_estado_vacio(self, client, admin_headers, board):
        with board([]):
            html = client.get("/adhoc/dashboard", headers=admin_headers).text
        assert "adhoc-empty" in html
        assert "Todo al día" in html
        assert "adhoc-kanban" not in html

    def test_pinta_una_tarjeta_por_tarea(self, client, admin_headers, board):
        tasks = [
            FakeTask(id=11, description="Cambiar extintor", due_date=date(2026, 9, 1)),
            FakeTask(id=12, description="Actualizar procedimiento", status="En Espera"),
        ]
        with board(tasks):
            html = client.get("/adhoc/dashboard", headers=admin_headers).text
        assert html.count('data-adhoc-task="') == 2
        assert 'data-adhoc-task-status="En Espera"' in html
        assert "Cambiar extintor" in html
        assert "01 sep 2026" in html

    def test_escapa_la_descripcion_de_la_tarea(self, client, admin_headers, board):
        payload = '<img src=x onerror="alert(1)">'
        with board([FakeTask(id=13, description=payload)]):
            html = client.get("/adhoc/dashboard", headers=admin_headers).text
        assert "<img src=x" not in html
        assert "&lt;img" in html

    def test_tarea_documental_muestra_el_documento(self, client, admin_headers, board):
        task = FakeTask(
            id=14, status="En Revisión", document_id=3,
            document=FakeParent("Manual de Calidad", "2.1"),
        )
        with board([task]):
            html = client.get("/adhoc/dashboard", headers=admin_headers).text
        assert "Manual de Calidad" in html
        assert "(v2.1)" in html
        assert "Documento ISO" in html

    def test_estaticos_versionados_de_la_seccion(self, client, admin_headers, board):
        with board([]):
            html = client.get("/adhoc/dashboard", headers=admin_headers).text
        assert "/static/adhoc/css/dashboard/dashboard.css?v=" in html
        assert "/static/adhoc/js/dashboard/dashboard.js?v=" in html

    def test_bloque_de_constantes_es_json_no_ejecutable(self, client, admin_headers, board):
        with board([]):
            html = client.get("/adhoc/dashboard", headers=admin_headers).text
        assert '<script id="adhoc-page-data" type="application/json">' in html
        assert '"can_workflow"' in html

    def test_modal_es_bootstrap_no_modal_overlay(self, client, admin_headers, board):
        with board([]):
            html = client.get("/adhoc/dashboard", headers=admin_headers).text
        assert 'id="adhoc-wf-modal"' in html
        assert "modal fade" in html
        assert 'data-bs-dismiss="modal"' in html
        assert "modal-overlay" not in html

    def test_botones_de_workflow_se_ocultan_sin_permiso(self, client, staff_headers, board, authz):
        authz["perms"] = {DASHBOARD_PERM}
        with board([]):
            html = client.get("/adhoc/dashboard", headers=staff_headers).text
        assert "data-adhoc-wf-action" not in html
        assert "data-adhoc-wf-comment-save" not in html

    def test_botones_de_workflow_visibles_para_admin(self, client, admin_headers, board):
        with board([]):
            html = client.get("/adhoc/dashboard", headers=admin_headers).text
        for accion in ("terminar", "rechazar", "aprobar"):
            assert f'data-adhoc-wf-action="{accion}"' in html
        assert "data-adhoc-wf-comment-save" in html

    def test_nav_inyectado(self, client, admin_headers, board):
        with board([]):
            html = client.get("/adhoc/dashboard", headers=admin_headers).text
        assert "adhoc-nav" in html
        assert 'href="/adhoc/documentos"' in html


# ==========================================================================
# Reglas duras del plan sobre los archivos de esta sección
# ==========================================================================

def _strip_jinja_comments(text):
    return re.sub(r"\{#.*?#\}", "", text, flags=re.S)


def _strip_js_comments(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(
        line for line in text.splitlines()
        if not line.lstrip().startswith(("//", "*"))
    )


class TestReglasDuras:
    def test_template_sin_css_inline(self):
        text = _strip_jinja_comments(TEMPLATE.read_text(encoding="utf-8"))
        assert "<style" not in text
        assert 'style="' not in text

    def test_template_sin_handlers_inline(self):
        text = _strip_jinja_comments(TEMPLATE.read_text(encoding="utf-8"))
        assert "onclick=" not in text
        assert "onchange=" not in text

    def test_template_solo_lleva_el_script_de_constantes(self):
        """El único <script> inline permitido es el bloque application/json."""
        text = _strip_jinja_comments(TEMPLATE.read_text(encoding="utf-8"))
        inline = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", text)
        assert inline == [], inline

    def test_template_usa_iconos_bootstrap(self):
        text = TEMPLATE.read_text(encoding="utf-8")
        assert "bi bi-" in text
        assert "fa-solid" not in text
        assert "fa-regular" not in text

    def test_template_declara_el_modal_en_su_bloque(self):
        """El legacy los dejaba inline al final del contenido, con .modal-overlay."""
        text = _strip_jinja_comments(TEMPLATE.read_text(encoding="utf-8"))
        bloque = text.index("{% block modals %}")
        fin = text.index("{% endblock %}", bloque)
        assert bloque < text.index('id="adhoc-wf-modal"') < fin

    def test_js_es_iife_estricto(self):
        text = JS.read_text(encoding="utf-8")
        assert "'use strict'" in text
        assert text.lstrip().startswith("/**")

    def test_js_sin_dialogos_nativos(self):
        """Criterio de aceptación 5 del plan (el legacy tenía 14)."""
        text = _strip_js_comments(JS.read_text(encoding="utf-8"))
        for needle in ("alert(", "confirm(", "prompt("):
            hits = [
                m.start() for m in re.finditer(re.escape(needle), text)
                if not re.search(r"[\w.]$", text[:m.start()])
            ]
            assert not hits, f"dashboard.js usa {needle}"

    def test_js_solo_expone_su_namespace(self):
        text = JS.read_text(encoding="utf-8")
        assert set(re.findall(r"^\s*(window\.\w+)\s*=", text, re.M)) == {"window.AdhocDashboard"}

    def test_js_sin_template_literals(self):
        """Sin backticks no puede existir el `${c.texto}` que causó el XSS."""
        text = _strip_js_comments(JS.read_text(encoding="utf-8"))
        assert "`" not in text
        assert "${" not in text

    def test_js_escapa_los_comentarios_y_sus_autores(self):
        """dashboard.html:395 volcaba ${c.texto} y ${c.usuario} sin escapar."""
        text = _strip_js_comments(JS.read_text(encoding="utf-8"))
        assert "escapeHtml(c.comment" in text
        assert "escapeHtml(userName(c.user" in text
        assert "escapeHtml(c.file_name" in text

    def test_js_escapa_los_datos_del_padre_y_de_las_validaciones(self):
        text = _strip_js_comments(JS.read_text(encoding="utf-8"))
        assert "escapeHtml(parent.title" in text
        assert "escapeHtml(userName(a.user))" in text
        # El helper de celda escapa etiqueta Y valor: es el que pinta el padre.
        assert text.count("U.escapeHtml") >= 10

    def test_js_apunta_a_la_api_v2(self):
        text = _strip_js_comments(JS.read_text(encoding="utf-8"))
        assert "/tasks/' + encodeURIComponent(state.taskId) + '/workflow'" in text
        assert "/app_prueba/" not in text
        assert "/api/tasks/" not in text

    def test_css_no_redefine_clases_de_bootstrap(self):
        css = CSS.read_text(encoding="utf-8")
        selectores = re.findall(r"^\s*([.#][^{\n]+?)\s*\{", css, re.M)
        prohibidas = re.compile(
            r"(^|[\s,>])\.(form-control|form-group|form-row|form-label|form-select|"
            r"card|badge-|alert-|bg-)"
        )
        for selector in selectores:
            for parte in selector.split(","):
                parte = parte.strip()
                if not parte.startswith("."):
                    continue
                assert not prohibidas.search(" " + parte), parte

    def test_css_comentarios_balanceados_y_sin_cierre_sobre_token(self):
        """Gotcha real del repo: un cierre de comentario pegado a un comodín."""
        css = CSS.read_text(encoding="utf-8")
        assert "-*/" not in css
        assert css.count("/*") == css.count("*/")

    def test_css_usa_tokens_no_hex_sueltos(self):
        css = re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.S)
        assert "var(--adhoc-primary)" in css
        # El violeta del legacy solo puede venir del token.
        assert "#4834d4" not in css

    def test_css_prefija_todas_sus_clases(self):
        css = re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.S)
        for selector in re.findall(r"^\s*([.#][^{\n]+?)\s*\{", css, re.M):
            for parte in re.findall(r"\.[A-Za-z][\w-]*", selector):
                assert parte.startswith((".adhoc-", ".is-")), parte
