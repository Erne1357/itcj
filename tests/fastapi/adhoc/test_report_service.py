"""Tests de ``itcj2.apps.adhoc.services.report_service`` (sección Reportes, F5).

Contra Postgres real (fixture ``db_session``) y no con ``MagicMock``, por el
mismo motivo que ``test_user_admin_service``: **lo que hay que demostrar aquí es
que el filtrado ocurre en SQL**. Un mock no puede distinguir un ``WHERE`` de un
``[u for u in usuarios if ...]``, que es justo el bug del legacy.

Los tres bugs del legacy que estos tests fijan como regresión
(``routes/api/api_reports.py``):

1. **Filtro de área en Python** — ``obtener_usuarios_filtrados`` traía TODOS los
   usuarios de la app y luego los recortaba en memoria.
2. **Solo miraba la primera área** — ``u.areas_asignadas[0].name == f_area``:
   quien tuviera dos áreas desaparecía del reporte al filtrar por la segunda.
3. **N+1 masivo** — una consulta de tareas y otra de documentos **por cada
   usuario** (``for u in usuarios_filtrados: Task.query...``).

El (3) se prueba con ``count_queries``: se mide el número de sentencias con 1
usuario y con 4, y se exige que sea **el mismo**. Es la única forma no frágil de
afirmar "carga en lote" sin cablear un número mágico de consultas.

Un cuarto bug, más sutil, también cubierto: ``app_id = 4`` hardcodeado
(``api_reports.py:29``), que en la BD de itcj2 es *warehouse*.
"""
import uuid
from contextlib import contextmanager
from datetime import date, datetime

import pytest
from sqlalchemy import event

from itcj2.apps.adhoc.models import (
    AdhocApprovalFlow,
    AdhocApprovalFlowStep,
    AdhocArea,
    AdhocDocument,
    AdhocDocumentCategory,
    AdhocIncident,
    AdhocTask,
    adhoc_flow_step_assignees,
    adhoc_task_assignees,
    adhoc_user_areas,
)
from itcj2.apps.adhoc.services.report_service import (
    REPORT_META,
    ReportService,
)
from itcj2.core.models.app import App
from itcj2.core.models.role import Role
from itcj2.core.models.user import User
from itcj2.core.models.user_app_role import UserAppRole


# ---------------------------------------------------------------------------
# Fixtures y helpers de siembra (todo dentro de la transacción que se revierte)
# ---------------------------------------------------------------------------

@pytest.fixture()
def adhoc_app(db_session):
    app = db_session.query(App).filter_by(key="adhoc").one_or_none()
    if app is None:
        app = App(key="adhoc", name="Calidad", is_active=True)
        db_session.add(app)
        db_session.flush()
    return app


@pytest.fixture()
def adhoc_role(db_session):
    role = db_session.query(Role).filter_by(name="consult").one_or_none()
    if role is None:
        role = Role(name="consult")
        db_session.add(role)
        db_session.flush()
    return role


def _tag() -> str:
    """Sufijo único: la BD de dev ya tiene filas reales y los nombres son UNIQUE."""
    return uuid.uuid4().hex[:12]


_UNSET = object()


def _make_user(db, app=None, role=None, first="ANA", last="TEST", active=True, email=_UNSET):
    user = User(
        username=f"e2e_{_tag()}",
        first_name=first,
        last_name=last,
        email=f"{_tag()}@test.local" if email is _UNSET else email,
        is_active=active,
    )
    db.add(user)
    db.flush()
    if app is not None and role is not None:
        db.add(UserAppRole(user_id=user.id, app_id=app.id, role_id=role.id))
        db.flush()
    return user


def _make_area(db, name=None):
    area = AdhocArea(name=name or f"e2e_area_{_tag()}", color="#4834d4")
    db.add(area)
    db.flush()
    return area


def _assign_area(db, user, area):
    db.execute(adhoc_user_areas.insert().values(user_id=user.id, area_id=area.id))
    db.flush()


def _make_document(db, title="Doc", author=None, area=None, code=None,
                   flow=None, status="Borrador", notes=None, version="1.0",
                   category=None, approval_date=None, is_current=True, parent=None):
    """Un documento del SGC.

    ``is_current=False`` + ``parent=<raíz>`` siembra una **versión superada**:
    la forma real de los datos es plana (``parent_id`` apunta siempre a la raíz
    de la cadena, nunca a la versión anterior) y hay exactamente una fila
    ``is_current=True`` por cadena.
    """
    doc = AdhocDocument(
        code=code if code is not None else f"E2E-{_tag()[:6]}",
        title=title,
        version=version,
        status=status,
        notes=notes,
        approval_date=approval_date,
        area_id=area.id if area else None,
        author_id=author.id if author else None,
        flow_id=flow.id if flow else None,
        category_id=category.id if category else None,
        is_current=is_current,
        parent_id=parent.id if parent else None,
    )
    db.add(doc)
    db.flush()
    return doc


def _make_flow(db, name=None, description=None):
    flow = AdhocApprovalFlow(name=name or f"e2e_flow_{_tag()}", description=description)
    db.add(flow)
    db.flush()
    return flow


def _make_step(db, flow, name="Paso", order=1, days=3, assignees=()):
    step = AdhocApprovalFlowStep(flow_id=flow.id, name=name, step_order=order, days_limit=days)
    db.add(step)
    db.flush()
    for user in assignees:
        db.execute(
            adhoc_flow_step_assignees.insert().values(step_id=step.id, user_id=user.id)
        )
    db.flush()
    return step


def _make_incident(db, title="Incidencia"):
    inc = AdhocIncident(title=title)
    db.add(inc)
    db.flush()
    return inc


def _make_task(db, incident, description="Tarea", status="Pendiente",
               due=None, assignees=()):
    task = AdhocTask(
        description=description,
        status=status,
        priority="Media",
        due_date=due,
        incident_id=incident.id,
    )
    db.add(task)
    db.flush()
    for user in assignees:
        db.execute(adhoc_task_assignees.insert().values(task_id=task.id, user_id=user.id))
    db.flush()
    return task


@contextmanager
def count_queries(db_session):
    """Cuenta las sentencias SQL emitidas dentro del bloque.

    Se engancha al engine ya conectado y se hace ``flush()`` antes de escuchar,
    para que los INSERT pendientes de la siembra no contaminen la medición.
    """
    db_session.flush()
    engine = db_session.connection().engine
    seen: list[str] = []

    def _on(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", _on)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", _on)


def _rows(report):
    return report["rows"]


def _col_keys(report):
    return [c["key"] for c in report["columns"]]


# ---------------------------------------------------------------------------
# Metadatos y despacho
# ---------------------------------------------------------------------------

class TestMetadatos:
    def test_los_cinco_tipos_del_plan_estan_declarados(self):
        from itcj2.apps.adhoc.utils.constants import REPORT_TYPES

        assert set(REPORT_META) == set(REPORT_TYPES)

    def test_cada_tipo_trae_titulo_hoja_y_prefijo_de_archivo(self):
        for key, meta in REPORT_META.items():
            assert meta["title"], key
            # Excel: la hoja no admite []:*?/\ y se corta a 31 caracteres.
            assert meta["sheet"] and len(meta["sheet"]) <= 31, key
            assert not set(meta["sheet"]) & set("[]:*?/\\"), key
            assert meta["file_prefix"], key

    def test_tipo_desconocido_es_lookup_error(self, db_session):
        """El legacy devolvía la cadena cruda ``"Reporte no encontrado", 404``."""
        with pytest.raises(LookupError):
            ReportService.build_report(db_session, "no_existe")

    @pytest.mark.parametrize("report_type", list(REPORT_META))
    def test_todos_los_tipos_responden_sin_datos(self, db_session, report_type):
        report = ReportService.build_report(db_session, report_type, nombre=f"zz{_tag()}")
        assert report["report_type"] == report_type
        assert report["rows"] == []
        assert report["total"] == 0
        assert report["columns"]

    def test_formato_invalido_cae_a_sencillo(self, db_session):
        report = ReportService.build_report(
            db_session, "area_usuarios", formato="<script>", nombre=f"zz{_tag()}"
        )
        assert report["formato"] == "sencillo"

    def test_formato_completo_se_respeta(self, db_session):
        report = ReportService.build_report(
            db_session, "area_usuarios", formato="completo", nombre=f"zz{_tag()}"
        )
        assert report["formato"] == "completo"
        assert "email" in _col_keys(report)

    def test_los_filtros_vuelven_en_la_respuesta(self, db_session):
        report = ReportService.build_report(
            db_session, "area_usuarios",
            nombre="  Ana  ", apellidos="Perez", area="Calidad",
        )
        assert report["filters"] == {
            "nombre": "Ana", "apellidos": "Perez", "area": "Calidad",
        }


# ---------------------------------------------------------------------------
# Selección de usuarios — los tres bugs del legacy
# ---------------------------------------------------------------------------

class TestSeleccionDeUsuarios:
    def test_solo_usuarios_con_acceso_a_calidad(self, db_session, adhoc_app, adhoc_role):
        dentro = _make_user(db_session, adhoc_app, adhoc_role, first=f"DENTRO{_tag()}")
        fuera = _make_user(db_session, first=f"FUERA{_tag()}")

        report = ReportService.build_report(db_session, "area_usuarios")
        nombres = {r["first_name"] for r in _rows(report)}

        assert dentro.first_name in nombres
        assert fuera.first_name not in nombres

    def test_la_app_se_resuelve_por_key_no_por_id_4(self, db_session, adhoc_app, adhoc_role):
        """Regresión de ``app_id = 4`` (api_reports.py:29) = warehouse en itcj2."""
        otra = db_session.query(App).filter(App.key != "adhoc").first()
        assert otra is not None
        role = db_session.query(Role).first()

        intruso = _make_user(db_session, first=f"INTRUSO{_tag()}")
        db_session.add(UserAppRole(user_id=intruso.id, app_id=otra.id, role_id=role.id))
        db_session.flush()

        report = ReportService.build_report(db_session, "area_usuarios")
        assert intruso.first_name not in {r["first_name"] for r in _rows(report)}

    def test_usuarios_inactivos_fuera(self, db_session, adhoc_app, adhoc_role):
        baja = _make_user(db_session, adhoc_app, adhoc_role,
                          first=f"BAJA{_tag()}", active=False)
        report = ReportService.build_report(db_session, "area_usuarios")
        assert baja.first_name not in {r["first_name"] for r in _rows(report)}

    def test_no_duplica_al_tener_varios_roles(self, db_session, adhoc_app, adhoc_role):
        user = _make_user(db_session, adhoc_app, adhoc_role, first=f"MULTI{_tag()}")
        otro_rol = db_session.query(Role).filter(Role.id != adhoc_role.id).first()
        db_session.add(
            UserAppRole(user_id=user.id, app_id=adhoc_app.id, role_id=otro_rol.id)
        )
        db_session.flush()

        report = ReportService.build_report(db_session, "area_usuarios")
        nombres = [r["first_name"] for r in _rows(report)]
        assert nombres.count(user.first_name) == 1

    def test_filtra_por_nombre_y_apellidos_sin_distinguir_mayusculas(
        self, db_session, adhoc_app, adhoc_role
    ):
        tag = _tag()
        buscado = _make_user(db_session, adhoc_app, adhoc_role,
                             first=f"Rosalinda{tag}", last=f"Quezada{tag}")
        _make_user(db_session, adhoc_app, adhoc_role,
                   first=f"Otro{tag}", last=f"Distinto{tag}")

        report = ReportService.build_report(db_session, "area_usuarios", nombre=f"rosalinda{tag}")
        assert [r["first_name"] for r in _rows(report)] == [buscado.first_name]

        report = ReportService.build_report(db_session, "area_usuarios", apellidos=f"QUEZADA{tag}")
        assert [r["last_name"] for r in _rows(report)] == [buscado.last_name]

    def test_filtro_por_area_encuentra_la_segunda_area(
        self, db_session, adhoc_app, adhoc_role
    ):
        """**El bug**: el legacy comparaba solo ``areas_asignadas[0].name``.

        Un usuario con dos áreas desaparecía del reporte al filtrar por la que
        no fuera la primera.
        """
        primera = _make_area(db_session)
        segunda = _make_area(db_session)
        user = _make_user(db_session, adhoc_app, adhoc_role, first=f"DOSAREAS{_tag()}")
        _assign_area(db_session, user, primera)
        _assign_area(db_session, user, segunda)

        report = ReportService.build_report(db_session, "area_usuarios", area=segunda.name)
        assert user.first_name in {r["first_name"] for r in _rows(report)}

    def test_filtro_por_area_excluye_a_quien_no_la_tiene(
        self, db_session, adhoc_app, adhoc_role
    ):
        area = _make_area(db_session)
        dentro = _make_user(db_session, adhoc_app, adhoc_role, first=f"CONAREA{_tag()}")
        fuera = _make_user(db_session, adhoc_app, adhoc_role, first=f"SINAREA{_tag()}")
        _assign_area(db_session, dentro, area)

        report = ReportService.build_report(db_session, "area_usuarios", area=area.name)
        nombres = {r["first_name"] for r in _rows(report)}
        assert dentro.first_name in nombres
        assert fuera.first_name not in nombres

    def test_el_filtro_de_area_es_sql_no_python(self, db_session, adhoc_app, adhoc_role):
        """El SELECT de usuarios debe traer YA filtrado, no recortar en memoria.

        Se comprueba de dos formas complementarias: la sentencia menciona la
        tabla de asociación, y el número de sentencias no crece con el número de
        usuarios descartados.
        """
        area = _make_area(db_session)
        elegido = _make_user(db_session, adhoc_app, adhoc_role, first=f"ELEGIDO{_tag()}")
        _assign_area(db_session, elegido, area)
        for _ in range(4):
            _make_user(db_session, adhoc_app, adhoc_role, first=f"RUIDO{_tag()}")

        with count_queries(db_session) as stmts:
            report = ReportService.build_report(db_session, "area_usuarios", area=area.name)

        assert [r["first_name"] for r in _rows(report)] == [elegido.first_name]
        assert any("adhoc_user_areas" in s for s in stmts), stmts

    def test_columna_de_area_lista_todas_las_areas(self, db_session, adhoc_app, adhoc_role):
        """El legacy pintaba ``areas_asignadas[0].name`` y escondía el resto."""
        a1 = _make_area(db_session, name=f"e2e_AAA_{_tag()}")
        a2 = _make_area(db_session, name=f"e2e_BBB_{_tag()}")
        user = _make_user(db_session, adhoc_app, adhoc_role, first=f"DOSAREAS{_tag()}")
        _assign_area(db_session, user, a1)
        _assign_area(db_session, user, a2)

        report = ReportService.build_report(db_session, "area_usuarios", nombre=user.first_name)
        fila = _rows(report)[0]
        assert a1.name in fila["areas"]
        assert a2.name in fila["areas"]

    def test_usuario_sin_area(self, db_session, adhoc_app, adhoc_role):
        user = _make_user(db_session, adhoc_app, adhoc_role, first=f"HUERFANO{_tag()}")
        report = ReportService.build_report(db_session, "area_usuarios", nombre=user.first_name)
        assert _rows(report)[0]["areas"] == "Sin Área"

    def test_formato_completo_agrega_correo_y_estado(self, db_session, adhoc_app, adhoc_role):
        user = _make_user(db_session, adhoc_app, adhoc_role,
                          first=f"CORREO{_tag()}", email="quien@itcj.test")
        report = ReportService.build_report(
            db_session, "area_usuarios", nombre=user.first_name, formato="completo"
        )
        fila = _rows(report)[0]
        assert fila["email"] == "quien@itcj.test"
        assert fila["status"] == "Activo"

    def test_sin_correo_muestra_na(self, db_session, adhoc_app, adhoc_role):
        user = _make_user(db_session, adhoc_app, adhoc_role,
                          first=f"SINCORREO{_tag()}", email=None)
        report = ReportService.build_report(
            db_session, "area_usuarios", nombre=user.first_name, formato="completo"
        )
        assert _rows(report)[0]["email"] == "N/A"


# ---------------------------------------------------------------------------
# usuarios_tareas
# ---------------------------------------------------------------------------

class TestUsuariosTareas:
    def test_cuenta_las_tareas_asignadas(self, db_session, adhoc_app, adhoc_role):
        user = _make_user(db_session, adhoc_app, adhoc_role, first=f"CONTAR{_tag()}")
        inc = _make_incident(db_session)
        _make_task(db_session, inc, description="T1", assignees=[user])
        _make_task(db_session, inc, description="T2", assignees=[user])

        report = ReportService.build_report(
            db_session, "usuarios_tareas", nombre=user.first_name
        )
        assert [r["total_tasks"] for r in _rows(report)] == [2]

    def test_completo_una_fila_por_tarea(self, db_session, adhoc_app, adhoc_role):
        user = _make_user(db_session, adhoc_app, adhoc_role, first=f"DETALLE{_tag()}")
        inc = _make_incident(db_session)
        _make_task(db_session, inc, description="Revisar extintor",
                   status="En Proceso", due=date(2026, 3, 4), assignees=[user])
        _make_task(db_session, inc, description="Cambiar señalética", assignees=[user])

        report = ReportService.build_report(
            db_session, "usuarios_tareas", nombre=user.first_name, formato="completo"
        )
        filas = _rows(report)
        assert len(filas) == 2
        descripciones = {r["description"] for r in filas}
        assert descripciones == {"Revisar extintor", "Cambiar señalética"}
        con_fecha = next(r for r in filas if r["description"] == "Revisar extintor")
        assert con_fecha["due_date"] == "04/03/2026"
        assert con_fecha["status"] == "En Proceso"

    def test_completo_usuario_sin_tareas_sigue_apareciendo(
        self, db_session, adhoc_app, adhoc_role
    ):
        """El legacy pintaba un ``<td colspan=3>Sin tareas asignadas</td>``.

        Aquí la fila conserva todas las celdas (el colspan desalineaba la
        exportación a Excel de SheetJS) y el texto va en la primera columna de
        detalle.
        """
        user = _make_user(db_session, adhoc_app, adhoc_role, first=f"OCIOSO{_tag()}")
        report = ReportService.build_report(
            db_session, "usuarios_tareas", nombre=user.first_name, formato="completo"
        )
        fila = _rows(report)[0]
        assert fila["total_tasks"] == 0
        assert fila["description"] == "Sin tareas asignadas"
        assert len(fila) >= len(_col_keys(report))

    def test_sin_fecha_limite_muestra_na(self, db_session, adhoc_app, adhoc_role):
        user = _make_user(db_session, adhoc_app, adhoc_role, first=f"SINFECHA{_tag()}")
        inc = _make_incident(db_session)
        _make_task(db_session, inc, assignees=[user])
        report = ReportService.build_report(
            db_session, "usuarios_tareas", nombre=user.first_name, formato="completo"
        )
        assert _rows(report)[0]["due_date"] == "N/A"

    def test_carga_en_lote_no_n_mas_uno(self, db_session, adhoc_app, adhoc_role):
        """El coste en consultas NO puede crecer con el número de usuarios.

        El legacy hacía ``for u in usuarios: Task.query.filter(...)``.
        """
        tag = _tag()
        inc = _make_incident(db_session)
        primero = _make_user(db_session, adhoc_app, adhoc_role, first=f"LOTE{tag}")
        _make_task(db_session, inc, assignees=[primero])

        with count_queries(db_session) as una:
            ReportService.build_report(db_session, "usuarios_tareas",
                                       nombre=f"LOTE{tag}", formato="completo")
        con_uno = len(una)

        for i in range(3):
            extra = _make_user(db_session, adhoc_app, adhoc_role,
                               first=f"LOTE{tag}", last=f"APELLIDO{i}")
            _make_task(db_session, inc, assignees=[extra])

        with count_queries(db_session) as cuatro:
            report = ReportService.build_report(db_session, "usuarios_tareas",
                                                nombre=f"LOTE{tag}", formato="completo")

        assert len({r["user"] for r in _rows(report)}) == 4
        assert len(cuatro) == con_uno, (con_uno, len(cuatro))


# ---------------------------------------------------------------------------
# usuarios_documentos
# ---------------------------------------------------------------------------

class TestUsuariosDocumentos:
    def test_cuenta_documentos_de_los_que_es_autor(self, db_session, adhoc_app, adhoc_role):
        user = _make_user(db_session, adhoc_app, adhoc_role, first=f"AUTOR{_tag()}")
        otro = _make_user(db_session, adhoc_app, adhoc_role, first=f"AJENO{_tag()}")
        _make_document(db_session, title="Mio 1", author=user)
        _make_document(db_session, title="Mio 2", author=user)
        _make_document(db_session, title="Suyo", author=otro)

        report = ReportService.build_report(
            db_session, "usuarios_documentos", nombre=user.first_name
        )
        assert [r["total_documents"] for r in _rows(report)] == [2]

    def test_completo_detalla_cada_documento(self, db_session, adhoc_app, adhoc_role):
        cat = AdhocDocumentCategory(name=f"e2e_cat_{_tag()}")
        db_session.add(cat)
        db_session.flush()
        user = _make_user(db_session, adhoc_app, adhoc_role, first=f"AUTOR{_tag()}")
        _make_document(db_session, title="Manual de calidad", author=user,
                       code="MC-01", version="2.1", status="Aprobado", category=cat)

        report = ReportService.build_report(
            db_session, "usuarios_documentos", nombre=user.first_name, formato="completo"
        )
        fila = _rows(report)[0]
        assert fila["code"] == "MC-01"
        assert fila["title"] == "Manual de calidad"
        assert fila["version"] == "2.1"
        assert fila["doc_status"] == "Aprobado"
        assert fila["category"] == cat.name
        assert fila["created_at"]

    def test_completo_usuario_sin_documentos(self, db_session, adhoc_app, adhoc_role):
        user = _make_user(db_session, adhoc_app, adhoc_role, first=f"NADA{_tag()}")
        report = ReportService.build_report(
            db_session, "usuarios_documentos", nombre=user.first_name, formato="completo"
        )
        fila = _rows(report)[0]
        assert fila["total_documents"] == 0
        assert fila["code"] == "Sin documentos asignados como autor"

    def test_carga_en_lote_no_n_mas_uno(self, db_session, adhoc_app, adhoc_role):
        tag = _tag()
        primero = _make_user(db_session, adhoc_app, adhoc_role, first=f"DOCS{tag}")
        _make_document(db_session, author=primero)

        with count_queries(db_session) as una:
            ReportService.build_report(db_session, "usuarios_documentos",
                                       nombre=f"DOCS{tag}", formato="completo")
        con_uno = len(una)

        for i in range(3):
            extra = _make_user(db_session, adhoc_app, adhoc_role,
                               first=f"DOCS{tag}", last=f"APELLIDO{i}")
            _make_document(db_session, author=extra)

        with count_queries(db_session) as cuatro:
            report = ReportService.build_report(db_session, "usuarios_documentos",
                                                nombre=f"DOCS{tag}", formato="completo")

        assert len({r["user"] for r in _rows(report)}) == 4
        assert len(cuatro) == con_uno, (con_uno, len(cuatro))


# ---------------------------------------------------------------------------
# documentos_usuarios
# ---------------------------------------------------------------------------

class TestDocumentosUsuarios:
    def test_sencillo_deduplica_validadores_entre_pasos(self, db_session, adhoc_app, adhoc_role):
        repetido = _make_user(db_session, adhoc_app, adhoc_role, first="Ana", last="Cruz")
        otro = _make_user(db_session, adhoc_app, adhoc_role, first="Beto", last="Lara")
        flow = _make_flow(db_session)
        _make_step(db_session, flow, name="Revisión", order=1, assignees=[repetido])
        _make_step(db_session, flow, name="Aprobación", order=2, assignees=[repetido, otro])
        titulo = f"Procedimiento {_tag()}"
        _make_document(db_session, title=titulo, flow=flow)

        report = ReportService.build_report(
            db_session, "documentos_usuarios", nombre=titulo
        )
        fila = _rows(report)[0]
        assert fila["total_steps"] == 2
        assert fila["assigned_users"].count("Ana Cruz") == 1
        assert "Beto Lara" in fila["assigned_users"]

    def test_completo_una_fila_por_paso_en_orden(self, db_session, adhoc_app, adhoc_role):
        validador = _make_user(db_session, adhoc_app, adhoc_role, first="Ana", last="Cruz")
        flow = _make_flow(db_session, description="Flujo de dos pasos")
        _make_step(db_session, flow, name="Segundo", order=2, days=5, assignees=[validador])
        _make_step(db_session, flow, name="Primero", order=1, days=2, assignees=[validador])
        titulo = f"Instructivo {_tag()}"
        _make_document(db_session, title=titulo, flow=flow)

        report = ReportService.build_report(
            db_session, "documentos_usuarios", nombre=titulo, formato="completo"
        )
        filas = _rows(report)
        assert [f["step_name"] for f in filas] == ["Primero", "Segundo"]
        assert [f["step_order"] for f in filas] == [1, 2]
        assert filas[0]["days_limit"] == 2
        assert filas[0]["flow_description"] == "Flujo de dos pasos"

    def test_documento_sin_flujo(self, db_session, adhoc_app, adhoc_role):
        titulo = f"Suelto {_tag()}"
        _make_document(db_session, title=titulo)

        sencillo = ReportService.build_report(db_session, "documentos_usuarios", nombre=titulo)
        assert _rows(sencillo)[0]["flow_name"] == "Sin flujo"
        assert _rows(sencillo)[0]["assigned_users"] == "Sin asignados"

        completo = ReportService.build_report(
            db_session, "documentos_usuarios", nombre=titulo, formato="completo"
        )
        fila = _rows(completo)[0]
        assert fila["step_name"] == "Sin pasos"
        assert fila["step_order"] == "N/A"
        assert fila["days_limit"] == "N/A"

    def test_paso_sin_validadores(self, db_session, adhoc_app, adhoc_role):
        flow = _make_flow(db_session)
        _make_step(db_session, flow, name="Huérfano", order=1)
        titulo = f"Formato {_tag()}"
        _make_document(db_session, title=titulo, flow=flow)

        report = ReportService.build_report(
            db_session, "documentos_usuarios", nombre=titulo, formato="completo"
        )
        assert _rows(report)[0]["assigned_users"] == "Sin asignados"

    def test_filtro_de_texto_busca_en_codigo_y_titulo(self, db_session):
        tag = _tag()
        _make_document(db_session, title="Titulo cualquiera", code=f"ABC{tag}")
        report = ReportService.build_report(db_session, "documentos_usuarios", nombre=f"abc{tag}")
        assert len(_rows(report)) == 1

    def test_filtro_de_apellidos_aplica_al_autor(self, db_session, adhoc_app, adhoc_role):
        tag = _tag()
        autor = _make_user(db_session, adhoc_app, adhoc_role, last=f"Villalobos{tag}")
        _make_document(db_session, title=f"Con autor {tag}", author=autor)
        _make_document(db_session, title=f"Sin autor {tag}")

        report = ReportService.build_report(
            db_session, "documentos_usuarios", nombre=tag, apellidos=f"villalobos{tag}"
        )
        assert [r["title"] for r in _rows(report)] == [f"Con autor {tag}"]

    def test_filtro_de_area_del_documento_es_sql(self, db_session):
        tag = _tag()
        area = _make_area(db_session)
        _make_document(db_session, title=f"Con area {tag}", area=area)
        _make_document(db_session, title=f"Sin area {tag}")

        with count_queries(db_session) as stmts:
            report = ReportService.build_report(
                db_session, "documentos_usuarios", nombre=tag, area=area.name
            )
        assert [r["title"] for r in _rows(report)] == [f"Con area {tag}"]
        assert any("adhoc_areas" in s for s in stmts), stmts

    def test_autor_ausente_es_na(self, db_session):
        titulo = f"Anonimo {_tag()}"
        _make_document(db_session, title=titulo)
        report = ReportService.build_report(db_session, "documentos_usuarios", nombre=titulo)
        assert _rows(report)[0]["author"] == "N/A"

    def test_carga_en_lote_no_n_mas_uno(self, db_session, adhoc_app, adhoc_role):
        tag = _tag()
        validador = _make_user(db_session, adhoc_app, adhoc_role)
        flow = _make_flow(db_session)
        _make_step(db_session, flow, order=1, assignees=[validador])
        _make_step(db_session, flow, order=2, assignees=[validador])
        _make_document(db_session, title=f"Lote {tag} 1", flow=flow)

        with count_queries(db_session) as uno:
            ReportService.build_report(db_session, "documentos_usuarios",
                                       nombre=tag, formato="completo")
        con_uno = len(uno)

        for i in range(2, 6):
            _make_document(db_session, title=f"Lote {tag} {i}", flow=flow)

        with count_queries(db_session) as cinco:
            report = ReportService.build_report(db_session, "documentos_usuarios",
                                                nombre=tag, formato="completo")

        assert len({r["title"] for r in _rows(report)}) == 5
        assert len(cinco) == con_uno, (con_uno, len(cinco))


# ---------------------------------------------------------------------------
# documentos_notas
# ---------------------------------------------------------------------------

class TestDocumentosNotas:
    def test_sencillo_marca_si_tiene_nota(self, db_session):
        tag = _tag()
        _make_document(db_session, title=f"Con nota {tag}", notes="Revisar anexo")
        _make_document(db_session, title=f"Sin nota {tag}")

        report = ReportService.build_report(db_session, "documentos_notas", nombre=tag)
        por_titulo = {r["title"]: r for r in _rows(report)}
        assert por_titulo[f"Con nota {tag}"]["has_notes"] == "Sí"
        assert por_titulo[f"Sin nota {tag}"]["has_notes"] == "No"

    def test_completo_incluye_notas_y_fecha_de_aprobacion(self, db_session):
        tag = _tag()
        _make_document(
            db_session, title=f"Aprobado {tag}", status="Aprobado", notes="Con observaciones",
            approval_date=datetime(2026, 1, 15, 9, 30),
        )
        report = ReportService.build_report(
            db_session, "documentos_notas", nombre=tag, formato="completo"
        )
        fila = _rows(report)[0]
        assert fila["notes"] == "Con observaciones"
        assert fila["approval_date"] == "15/01/2026"

    def test_completo_sin_nota_ni_aprobacion(self, db_session):
        tag = _tag()
        _make_document(db_session, title=f"Crudo {tag}")
        report = ReportService.build_report(
            db_session, "documentos_notas", nombre=tag, formato="completo"
        )
        fila = _rows(report)[0]
        assert fila["notes"] == "Sin notas"
        assert fila["approval_date"] == "N/A"

    def test_codigo_ausente_es_na(self, db_session):
        tag = _tag()
        doc = _make_document(db_session, title=f"Sin codigo {tag}")
        doc.code = None
        db_session.flush()
        report = ReportService.build_report(db_session, "documentos_notas", nombre=tag)
        assert _rows(report)[0]["code"] == "N/A"


# ---------------------------------------------------------------------------
# Versiones superadas: NUNCA salen en un reporte imprimible
# ---------------------------------------------------------------------------

class TestSoloVersionesVigentes:
    """La cadena de versiones se recorta a su punta en los cinco reportes.

    No es cosmética: un reporte imprimible del SGC es lo que se pone sobre la
    mesa en una auditoría ISO 9001, y la cláusula 7.5.3 exige impedir el uso no
    intencionado de documentos obsoletos. Como todas las versiones de una cadena
    comparten el ``code`` y el papel no trae ninguna columna que las distinga,
    listarlas juntas es entregar documentación superada como si estuviera en
    vigor.
    """

    @pytest.mark.parametrize("report_type", ["documentos_usuarios", "documentos_notas"])
    def test_los_reportes_de_documentos_solo_ven_la_vigente(self, db_session, report_type):
        tag = _tag()
        raiz = _make_document(db_session, title=f"Manual {tag}", code=f"MC-{tag[:6]}",
                              version="1.0", is_current=False)
        _make_document(db_session, title=f"Manual {tag}", code=raiz.code,
                       version="2.0", is_current=False, parent=raiz)
        _make_document(db_session, title=f"Manual {tag}", code=raiz.code,
                       version="3.0", is_current=True, parent=raiz)

        report = ReportService.build_report(db_session, report_type, nombre=tag)
        filas = _rows(report)

        # Una sola fila pese a que la cadena tiene tres versiones con el MISMO code.
        assert len(filas) == 1, filas
        assert filas[0]["code"] == raiz.code
        assert report["subjects"] == 1

    def test_la_version_superada_no_aparece_ni_filtrando_por_su_titulo(self, db_session):
        tag = _tag()
        raiz = _make_document(db_session, title=f"Superada {tag}", is_current=False)
        _make_document(db_session, title=f"Vigente {tag}", is_current=True, parent=raiz)

        report = ReportService.build_report(db_session, "documentos_notas",
                                            nombre=f"Superada {tag}")
        assert _rows(report) == []

    def test_la_punta_marcada_obsoleto_sigue_saliendo(self, db_session):
        """``is_current`` no es ``status != 'Obsoleto'``.

        En los datos reales hay filas que son punta de su cadena y a la vez
        están en estado ``Obsoleto``. Son historia legítima y el reporte las
        emite: lo que se recorta es la versión **superada**, no el estado.
        """
        tag = _tag()
        _make_document(db_session, title=f"Retirado {tag}", status="Obsoleto",
                       is_current=True)

        report = ReportService.build_report(db_session, "documentos_notas", nombre=tag)
        filas = _rows(report)
        assert len(filas) == 1
        assert filas[0]["doc_status"] == "Obsoleto"

    def test_el_reporte_por_autor_tampoco_cuenta_las_superadas(
        self, db_session, adhoc_app, adhoc_role
    ):
        """``usuarios_documentos`` es el único que no pasa por ``_fetch_documents``.

        Parte de usuarios y agrupa por autor (``_documents_by_author``), así que
        el filtro de control documental hay que repetirlo ahí. Sin él, la
        columna "Total Documentos" contaba las versiones superadas y el formato
        completo las imprimía una por una, con el mismo ``code`` que la vigente
        y sin ninguna columna que las distinga.
        """
        tag = _tag()
        autor = _make_user(db_session, adhoc_app, adhoc_role, first=f"AUTORVER{tag}")
        raiz = _make_document(db_session, title=f"Manual {tag}", code=f"MC-{tag[:6]}",
                              version="1.0", author=autor, is_current=False,
                              status="Obsoleto")
        _make_document(db_session, title=f"Manual {tag}", code=raiz.code, version="2.0",
                       author=autor, is_current=True, parent=raiz)

        report = ReportService.build_report(
            db_session, "usuarios_documentos", nombre=autor.first_name,
            formato="completo",
        )
        filas = _rows(report)

        assert [f["total_documents"] for f in filas] == [1]
        assert [f["version"] for f in filas] == ["2.0"]
        assert "Obsoleto" not in {f["doc_status"] for f in filas}

    def test_la_pantalla_de_seleccion_tampoco_las_lista(self, db_session):
        """``get_selection_data`` comparte ``_fetch_documents``: mismo criterio.

        La vista previa del modal es de donde el usuario copia el código para
        filtrar; si ahí aparecieran las superadas, filtraría por un documento
        que el reporte no va a imprimir.
        """
        tag = _tag()
        raiz = _make_document(db_session, title=f"Previa superada {tag}", is_current=False)
        _make_document(db_session, title=f"Previa vigente {tag}", is_current=True, parent=raiz)

        titulos = {d["title"] for d in ReportService.get_selection_data(db_session)["documents"]}
        assert f"Previa vigente {tag}" in titulos
        assert f"Previa superada {tag}" not in titulos


# ---------------------------------------------------------------------------
# Límite defensivo
# ---------------------------------------------------------------------------

class TestLimiteDefensivo:
    def test_trunca_y_avisa(self, db_session, adhoc_app, adhoc_role, monkeypatch):
        """Sin paginación, pero tampoco un ``SELECT *`` sin techo."""
        tag = _tag()
        for _ in range(3):
            _make_user(db_session, adhoc_app, adhoc_role, first=f"TOPE{tag}")

        monkeypatch.setattr(ReportService, "MAX_ROWS", 2)
        report = ReportService.build_report(db_session, "area_usuarios", nombre=f"TOPE{tag}")

        assert len(_rows(report)) == 2
        assert report["truncated"] is True
        assert report["max_rows"] == 2

    def test_sin_truncar_la_bandera_es_falsa(self, db_session, adhoc_app, adhoc_role):
        user = _make_user(db_session, adhoc_app, adhoc_role, first=f"POCO{_tag()}")
        report = ReportService.build_report(db_session, "area_usuarios", nombre=user.first_name)
        assert report["truncated"] is False

    def test_documentos_tambien_tienen_techo(self, db_session, monkeypatch):
        tag = _tag()
        for i in range(3):
            _make_document(db_session, title=f"Techo {tag} {i}")

        monkeypatch.setattr(ReportService, "MAX_ROWS", 2)
        report = ReportService.build_report(db_session, "documentos_notas", nombre=tag)
        assert report["truncated"] is True


# ---------------------------------------------------------------------------
# Datos de la pantalla de selección
# ---------------------------------------------------------------------------

class TestSelectionData:
    def test_trae_areas_usuarios_y_documentos(self, db_session, adhoc_app, adhoc_role):
        area = _make_area(db_session)
        user = _make_user(db_session, adhoc_app, adhoc_role, first=f"SEL{_tag()}")
        _assign_area(db_session, user, area)
        _make_document(db_session, title=f"Sel {_tag()}", author=user, area=area)

        data = ReportService.get_selection_data(db_session)

        assert area.name in {a["name"] for a in data["areas"]}
        fila = next(u for u in data["users"] if u["first_name"] == user.first_name)
        assert fila["areas"] == area.name
        assert data["documents"]
        assert {"code", "title", "author", "area", "status", "version",
                "created_at", "notes"} <= set(data["documents"][0])

    def test_solo_areas_activas(self, db_session):
        viva = _make_area(db_session)
        muerta = _make_area(db_session)
        muerta.is_active = False
        db_session.flush()

        nombres = {a["name"] for a in ReportService.get_selection_data(db_session)["areas"]}
        assert viva.name in nombres
        assert muerta.name not in nombres

    def test_no_dispara_una_consulta_por_usuario(self, db_session, adhoc_app, adhoc_role):
        area = _make_area(db_session)
        primero = _make_user(db_session, adhoc_app, adhoc_role)
        _assign_area(db_session, primero, area)

        with count_queries(db_session) as una:
            ReportService.get_selection_data(db_session)
        con_uno = len(una)

        for _ in range(3):
            extra = _make_user(db_session, adhoc_app, adhoc_role)
            _assign_area(db_session, extra, area)

        with count_queries(db_session) as cuatro:
            ReportService.get_selection_data(db_session)

        assert len(cuatro) == con_uno, (con_uno, len(cuatro))

    def test_lista_los_tipos_de_reporte_para_las_tarjetas(self, db_session):
        data = ReportService.get_selection_data(db_session)
        tarjetas = data["reports"]
        assert [c["type"] for c in tarjetas] == list(REPORT_META)
        for card in tarjetas:
            assert card["title"]
            # Toda la app volvió a Font Awesome 6.4, como el legacy.
            assert card["icon"].startswith("fa-")
            assert card["icon_overlay"].startswith("fa-")
            assert card["subject"] in ("users", "documents")
