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

Y un quinto, que no era del legacy sino de la migración: ``usuarios_documentos``
se titulaba "Usuarios y Documentos" y contaba **autorías**, mientras las dos
tablas con la evidencia de difusión (``adhoc_document_visibility``,
``adhoc_document_acknowledgements``) no tenían ninguna pantalla. Los tests de
:class:`TestDifusionDocumental` fijan lo que el reporte mide hoy: qué documentos
se le difundieron a cada persona, cuáles acusó y **cuándo**.
"""
import uuid
from contextlib import contextmanager
from datetime import date, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import event

from itcj2.apps.adhoc.models import (
    AdhocApprovalFlow,
    AdhocApprovalFlowStep,
    AdhocArea,
    AdhocDocument,
    AdhocDocumentAcknowledgement,
    AdhocDocumentVisibility,
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


def _grant_visibility(db, doc, *users):
    """Difunde un documento a N usuarios (``adhoc_document_visibility``)."""
    for user in users:
        db.add(AdhocDocumentVisibility(document_id=doc.id, user_id=user.id))
    db.flush()


def _acknowledge(db, doc, user, when=None):
    """Acuse de recibo con fecha REAL.

    ``acknowledged_at`` es NOT NULL a propósito en el modelo: un acuse sin fecha
    no sostiene una auditoría. Aquí se siembra siempre con una.
    """
    ack = AdhocDocumentAcknowledgement(
        document_id=doc.id,
        user_id=user.id,
        acknowledged_at=when or datetime(2023, 6, 21, 9, 30),
    )
    db.add(ack)
    db.flush()
    return ack


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


def _full(user) -> str:
    """El nombre tal y como lo compone el reporte (``_full_name``)."""
    return f"{user.first_name or ''} {user.last_name or ''}".strip()


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
# usuarios_documentos — difusión documental (ISO 9001:2015 §7.5.3)
#
# El reporte se reescribió: contaba documentos por AUTORÍA (``author_id``, 3
# autores distintos en toda la base) y hoy sale de ``adhoc_document_visibility``
# cruzada con ``adhoc_document_acknowledgements`` por ``(document_id, user_id)``.
# ---------------------------------------------------------------------------

class TestDifusionDocumental:
    def test_la_coleccion_sale_de_la_difusion_no_de_la_autoria(
        self, db_session, adhoc_app, adhoc_role
    ):
        """El defecto que cerró esta reescritura, fijado como regresión.

        El autor de dos documentos a quien nadie difundió nada **no** está en un
        reporte de difusión; quien tiene una fila de visibilidad, sí.
        """
        tag = _tag()
        autor = _make_user(db_session, adhoc_app, adhoc_role, first=f"AUTOR{tag}")
        receptor = _make_user(db_session, adhoc_app, adhoc_role, first=f"RECEPTOR{tag}")
        _make_document(db_session, title="Mio 1", author=autor)
        _make_document(db_session, title="Mio 2", author=autor)
        difundido = _make_document(db_session, title="Difundido", author=autor)
        _grant_visibility(db_session, difundido, receptor)

        report = ReportService.build_report(db_session, "usuarios_documentos",
                                            nombre=tag)
        filas = _rows(report)
        assert [f["user"] for f in filas] == [_full(receptor)]
        assert filas[0]["assigned"] == 1

    def test_cuenta_asignados_acusados_y_porcentaje(
        self, db_session, adhoc_app, adhoc_role
    ):
        tag = _tag()
        user = _make_user(db_session, adhoc_app, adhoc_role, first=f"DIF{tag}")
        docs = [_make_document(db_session, title=f"Doc {i} {tag}") for i in range(4)]
        _grant_visibility(db_session, docs[0], user)
        _grant_visibility(db_session, docs[1], user)
        _grant_visibility(db_session, docs[2], user)
        _grant_visibility(db_session, docs[3], user)
        _acknowledge(db_session, docs[0], user)

        fila = _rows(ReportService.build_report(
            db_session, "usuarios_documentos", nombre=f"DIF{tag}"))[0]
        assert fila["assigned"] == 4
        assert fila["acknowledged"] == 1
        assert fila["coverage"] == 25

    def test_sin_documentos_difundidos_no_divide_entre_cero(
        self, db_session, adhoc_app, adhoc_role
    ):
        """Toda su difusión apunta a versiones superadas: fila sí, ``0 %`` sin reventar."""
        tag = _tag()
        user = _make_user(db_session, adhoc_app, adhoc_role, first=f"VACIO{tag}")
        superada = _make_document(db_session, title=f"Superada {tag}", is_current=False)
        _grant_visibility(db_session, superada, user)

        fila = _rows(ReportService.build_report(
            db_session, "usuarios_documentos", nombre=f"VACIO{tag}",
            formato="completo"))[0]
        assert fila["assigned"] == 0
        assert fila["coverage"] == 0
        assert fila["code"] == "Sin documentos difundidos"

    def test_completo_una_fila_por_documento_con_la_fecha_del_acuse(
        self, db_session, adhoc_app, adhoc_role
    ):
        """La fecha es el dato que un auditor pide primero."""
        tag = _tag()
        user = _make_user(db_session, adhoc_app, adhoc_role, first=f"FECHA{tag}")
        acusado = _make_document(db_session, title="Manual de calidad", code="MC-01",
                                 version="2.1", status="Aprobado")
        pendiente = _make_document(db_session, title="Procedimiento", code="PR-02",
                                   version="1.0", status="Aprobado")
        _grant_visibility(db_session, acusado, user)
        _grant_visibility(db_session, pendiente, user)
        _acknowledge(db_session, acusado, user, when=datetime(2019, 11, 15, 8, 0))

        filas = _rows(ReportService.build_report(
            db_session, "usuarios_documentos", nombre=f"FECHA{tag}", formato="completo"))
        por_codigo = {f["code"]: f for f in filas}

        assert len(filas) == 2
        assert por_codigo["MC-01"]["title"] == "Manual de calidad"
        assert por_codigo["MC-01"]["version"] == "2.1"
        assert por_codigo["MC-01"]["doc_status"] == "Aprobado"
        assert por_codigo["MC-01"]["ack_date"] == "15/11/2019"
        assert por_codigo["PR-02"]["ack_date"] == "Sin acuse"

    def test_el_acuse_es_por_par_documento_usuario(
        self, db_session, adhoc_app, adhoc_role
    ):
        """Que un compañero acuse el documento no acusa por mí."""
        tag = _tag()
        acusa = _make_user(db_session, adhoc_app, adhoc_role, first=f"ACUSA{tag}",
                           last="AAA")
        calla = _make_user(db_session, adhoc_app, adhoc_role, first=f"CALLA{tag}",
                           last="BBB")
        doc = _make_document(db_session, title=f"Compartido {tag}", code=f"CP-{tag[:5]}")
        _grant_visibility(db_session, doc, acusa, calla)
        _acknowledge(db_session, doc, acusa)

        filas = _rows(ReportService.build_report(
            db_session, "usuarios_documentos", nombre=tag, formato="completo"))
        por_usuario = {f["user"]: f for f in filas}

        assert por_usuario[_full(acusa)]["acknowledged"] == 1
        assert por_usuario[_full(acusa)]["ack_date"] == "21/06/2023"
        assert por_usuario[_full(calla)]["acknowledged"] == 0
        assert por_usuario[_full(calla)]["ack_date"] == "Sin acuse"

    def test_quien_ya_no_puede_entrar_a_la_app_sale_marcado(
        self, db_session, adhoc_app, adhoc_role
    ):
        """La difusión de 2019-2025 se hizo a gente que hoy está de baja.

        Esconderla falsearía la evidencia: sale, con la marca. En la base real
        son 30 de los 55 usuarios con difusión.
        """
        tag = _tag()
        dentro = _make_user(db_session, adhoc_app, adhoc_role, first=f"ACC{tag}",
                            last="AAA")
        baja = _make_user(db_session, adhoc_app, adhoc_role, first=f"ACC{tag}",
                          last="BBB", active=False)
        doc = _make_document(db_session, title=f"Politica {tag}")
        _grant_visibility(db_session, doc, dentro, baja)

        filas = _rows(ReportService.build_report(
            db_session, "usuarios_documentos", nombre=f"ACC{tag}"))
        por_usuario = {f["user"]: f for f in filas}

        assert len(filas) == 2, "el usuario de baja tiene que salir, no desaparecer"
        assert por_usuario[_full(dentro)]["access"] == "Con acceso"
        assert por_usuario[_full(baja)]["access"] == "Sin acceso"

    def test_la_marca_es_texto_en_columna_propia(self, db_session, adhoc_app, adhoc_role):
        """Sobrevive al .xlsx.

        La exportación es ``XLSX.utils.table_to_book``, que lee el ``<table>``
        del DOM: lo único que llega al archivo es el texto de la celda. Una
        marca hecha con una clase de CSS o un icono se quedaría en pantalla.
        Y va en columna propia para poder filtrar por ella en Excel sin
        ensuciar la columna "Usuario".
        """
        tag = _tag()
        user = _make_user(db_session, adhoc_app, adhoc_role, first=f"MARCA{tag}")
        doc = _make_document(db_session, title=f"Doc {tag}")
        _grant_visibility(db_session, doc, user)

        report = ReportService.build_report(db_session, "usuarios_documentos",
                                            nombre=f"MARCA{tag}")
        fila = _rows(report)[0]
        assert "access" in _col_keys(report)
        assert isinstance(fila["access"], str)
        assert fila["access"] in ("Con acceso", "Sin acceso")
        # El nombre queda limpio: la marca no se cuela como sufijo.
        assert fila["user"] == _full(user)

    def test_el_porcentaje_redondea_al_entero_mas_cercano(
        self, db_session, adhoc_app, adhoc_role
    ):
        """El contrato es entero y redondeado, no truncado.

        Con 3 documentos difundidos, 1 acuse es 33 (de 33.33) y 2 son 67 (de
        66.66): truncar daría 66 y le quitaría un punto a la única columna del
        papel que un auditor mira dos veces. Entero y no ``"67 %"`` porque en la
        hoja de Excel un texto ordena ``"100 %" < "67 %"``, justo al revés de lo
        que se quiere leer en un reporte de difusión.
        """
        tag = _tag()
        poco = _make_user(db_session, adhoc_app, adhoc_role, first=f"PCT{tag}",
                          last="AAA")
        mucho = _make_user(db_session, adhoc_app, adhoc_role, first=f"PCT{tag}",
                           last="BBB")
        docs = [_make_document(db_session, title=f"Doc {i} {tag}") for i in range(3)]
        for doc in docs:
            _grant_visibility(db_session, doc, poco, mucho)
        _acknowledge(db_session, docs[0], poco)
        _acknowledge(db_session, docs[0], mucho)
        _acknowledge(db_session, docs[1], mucho)

        filas = _rows(ReportService.build_report(
            db_session, "usuarios_documentos", nombre=f"PCT{tag}"))
        por_usuario = {f["user"]: f for f in filas}

        assert por_usuario[_full(poco)]["coverage"] == 33
        assert por_usuario[_full(mucho)]["coverage"] == 67
        # Número, no cadena: la unidad ya está en el encabezado de la columna.
        assert isinstance(por_usuario[_full(poco)]["coverage"], int)

    def test_el_acuse_de_una_version_superada_no_infla_el_porcentaje(
        self, db_session, adhoc_app, adhoc_role
    ):
        """Los acuses se piden por usuario; el cruce lo hace el par.

        ``_acknowledged_at_by_pair`` no filtra por documento —pedir un segundo
        ``IN`` de ids no ahorra nada y añade un sitio donde desincronizar el
        criterio de vigencia—, así que quien recorta es
        ``_visibility_by_user``. Si el cruce se hiciera por usuario en vez de
        por par, este caso daría 1 acuse sobre 1 documento: 100 % de cobertura
        para alguien que no ha acusado el documento vigente. Y no es teórico:
        2 679 de las 9 390 filas de visibilidad apuntan a versiones superadas.
        """
        tag = _tag()
        user = _make_user(db_session, adhoc_app, adhoc_role, first=f"SUP{tag}")
        raiz = _make_document(db_session, title=f"Manual {tag}", code=f"MC-{tag[:6]}",
                              version="1.0", is_current=False, status="Obsoleto")
        vigente = _make_document(db_session, title=f"Manual {tag}", code=raiz.code,
                                 version="2.0", is_current=True, parent=raiz)
        _grant_visibility(db_session, raiz, user)
        _grant_visibility(db_session, vigente, user)
        # Acusó la vieja y nunca la nueva: es exactamente el hueco de difusión
        # que el reporte tiene que enseñar.
        _acknowledge(db_session, raiz, user)

        fila = _rows(ReportService.build_report(
            db_session, "usuarios_documentos", nombre=f"SUP{tag}"))[0]

        assert fila["assigned"] == 1
        assert fila["acknowledged"] == 0
        assert fila["coverage"] == 0
        # Pero el acuse NO se pierde: sale en su propia columna. Es la mitad que
        # faltaba —contarlo como 0 a secas dejaba en el papel "esta persona no
        # acusó nada", que es falso—.
        assert fila["prior_acks"] == 1

    def test_el_acuse_de_una_version_superada_no_se_pierde_del_papel(
        self, db_session, adhoc_app, adhoc_role
    ):
        """Un 0 a secas era una afirmación falsa; ahora el papel lo dice todo.

        El caso vive en la base: 6 personas cuyo ÚNICO acuse está sobre una
        versión superada imprimían "Documentos Acusados: 0 · % de Difusión: 0"
        sin nada que lo matizara, mientras el modal de difusión del panel
        enseñaba ese mismo acuse con su fecha. Dos superficies de la misma app
        contando distinto, y la que se lleva el auditor era la que callaba.

        Lo que NO se hace es cruzar por raíz de cadena para "recuperar" el
        acuse: eso imprimiría que acusó el documento en vigor, y lo fija
        ``test_el_acuse_previo_no_cuenta_como_acuse_del_vigente``.
        """
        tag = _tag()
        user = _make_user(db_session, adhoc_app, adhoc_role, first=f"PREV{tag}")
        raiz = _make_document(db_session, title=f"Manual {tag}", code=f"PV-{tag[:6]}",
                              version="1.0", is_current=False, status="Obsoleto")
        vigente = _make_document(db_session, title=f"Manual {tag}", code=raiz.code,
                                 version="2.0", is_current=True, parent=raiz)
        _grant_visibility(db_session, raiz, user)
        _grant_visibility(db_session, vigente, user)
        _acknowledge(db_session, raiz, user, when=datetime(2019, 12, 6, 14, 8))

        detalle = _rows(ReportService.build_report(
            db_session, "usuarios_documentos", nombre=f"PREV{tag}", formato="completo"))
        fila = next(f for f in detalle if f["code"] == raiz.code)

        # La versión que se lista es la vigente...
        assert fila["version"] == "2.0"
        # ...la celda de fecha no dice "Sin acuse" a secas...
        assert fila["ack_date"] == "Sin acuse (acusó una versión anterior)"
        # ...y NO se cuela la fecha del acuse viejo como si fuera del vigente.
        assert "2019" not in fila["ack_date"]

    def test_el_acuse_previo_no_cuenta_como_acuse_del_vigente(
        self, db_session, adhoc_app, adhoc_role
    ):
        """La cadena NO es la unidad del acuse, y esto es lo que lo impide.

        Es la corrección que parecía obvia y habría sido peor: contar por
        ``coalesce(parent_id, id)`` imprimiría "acusó recibo del documento en
        vigor" con la fecha de un acuse anterior a que esa versión existiera.
        En la base real es el usuario 7650: acusó ``046`` v2.0 el 2019-12-06 y
        la versión en vigor es la v3.0 aprobada en 2022. Dar eso por bueno es
        justo lo que la cláusula 7.5.3 existe para impedir.
        """
        tag = _tag()
        user = _make_user(db_session, adhoc_app, adhoc_role, first=f"CAD{tag}")
        raiz = _make_document(db_session, title=f"Guia {tag}", code=f"CD-{tag[:6]}",
                              version="1.0", is_current=False, status="Obsoleto")
        vigente = _make_document(db_session, title=f"Guia {tag}", code=raiz.code,
                                 version="3.0", is_current=True, parent=raiz)
        _grant_visibility(db_session, raiz, user)
        _grant_visibility(db_session, vigente, user)
        _acknowledge(db_session, raiz, user, when=datetime(2019, 12, 6, 14, 8))

        fila = _rows(ReportService.build_report(
            db_session, "usuarios_documentos", nombre=f"CAD{tag}"))[0]

        assert fila["acknowledged"] == 0, "el acuse de la v1.0 no acusa la v3.0"
        assert fila["coverage"] == 0

    def test_acusar_las_dos_versiones_no_cuenta_dos_veces(
        self, db_session, adhoc_app, adhoc_role
    ):
        """Quien acusó la vieja Y la nueva no arrastra una nota al pie.

        De los 84 acuses sobre versiones superadas de la base, 51 son este caso:
        la misma persona acusó también la vigente. Sumarlos en la columna de
        acuses previos inflaría el papel con evidencia duplicada.
        """
        tag = _tag()
        user = _make_user(db_session, adhoc_app, adhoc_role, first=f"DOS{tag}")
        raiz = _make_document(db_session, title=f"Proc {tag}", code=f"DS-{tag[:6]}",
                              version="1.0", is_current=False, status="Obsoleto")
        vigente = _make_document(db_session, title=f"Proc {tag}", code=raiz.code,
                                 version="2.0", is_current=True, parent=raiz)
        _grant_visibility(db_session, raiz, user)
        _grant_visibility(db_session, vigente, user)
        _acknowledge(db_session, raiz, user, when=datetime(2019, 1, 1, 8, 0))
        _acknowledge(db_session, vigente, user, when=datetime(2022, 5, 4, 10, 0))

        fila = _rows(ReportService.build_report(
            db_session, "usuarios_documentos", nombre=f"DOS{tag}"))[0]

        assert fila["acknowledged"] == 1
        assert fila["coverage"] == 100
        assert fila["prior_acks"] == 0, "acusó la vigente: no hay nada que anotar"

    def test_los_rotulos_declaran_el_alcance_porque_el_excel_solo_lleva_la_tabla(
        self, db_session
    ):
        """El .xlsx no tiene cabecera: el rótulo es el único sitio donde cabe.

        La exportación es ``XLSX.utils.table_to_book``, que copia **solo el
        ``<table>``**. Si el alcance viviera solo en la cabecera de la hoja, el
        archivo que se lleva el auditor saldría con dos columnas llamadas
        "Documentos Asignados" y "Documentos Acusados" sin decir sobre qué
        conjunto se contaron.
        """
        report = ReportService.build_report(db_session, "usuarios_documentos")
        etiquetas = {c["key"]: c["label"] for c in report["columns"]}

        assert etiquetas["assigned"] == "Documentos Asignados (versión vigente)"
        assert etiquetas["acknowledged"] == "Documentos Acusados (versión vigente)"
        assert etiquetas["prior_acks"] == "Acuses en Versiones Superadas"
        # Y la hoja impresa además lo explica en palabras.
        assert "versión en vigor" in report["scope_note"]

    def test_solo_este_reporte_declara_alcance(self, db_session):
        """Los otros cuatro no tienen nada que declarar y no imprimen la línea."""
        for tipo in REPORT_META:
            nota = ReportService.build_report(db_session, tipo)["scope_note"]
            if tipo == "usuarios_documentos":
                assert nota
            else:
                assert nota is None, tipo

    def test_sin_poder_resolver_el_acceso_la_marca_es_na(
        self, db_session, adhoc_app, adhoc_role
    ):
        """Sin fila de ``adhoc`` en ``core_apps`` no se acusa a nadie de nada.

        ``_users_with_app_access`` devuelve ``None`` y la columna sale en
        ``N/A``: es el equivalente al fail-closed de ``_fetch_users`` —allí no se
        lista a nadie; aquí no se afirma que alguien perdió el acceso—. Escribir
        "Sin acceso" por no haber podido comprobarlo pondría en el papel de una
        auditoría una acusación que el servidor no sostiene.
        """
        from fastapi import HTTPException

        tag = _tag()
        user = _make_user(db_session, adhoc_app, adhoc_role, first=f"NA{tag}")
        doc = _make_document(db_session, title=f"Doc {tag}")
        _grant_visibility(db_session, doc, user)

        with patch("itcj2.core.services.authz_service.users_with_assignment_select",
                   side_effect=HTTPException(status_code=404, detail="App inexistente")):
            filas = _rows(ReportService.build_report(
                db_session, "usuarios_documentos", nombre=f"NA{tag}"))

        assert filas[0]["access"] == "N/A"
        # Lo que sí se sabe se sigue contando.
        assert filas[0]["assigned"] == 1

    def test_el_meta_habla_de_difusion_pero_la_clave_no_se_toca(self):
        """El rótulo cambió; la URL no podía cambiar.

        ``usuarios_documentos`` está en ``REPORT_TYPES`` y es
        ``/adhoc/reportes/usuarios_documentos``, una URL viva que se comparte por
        correo. Lo que se corrigió es lo que el papel dice que mide: un reporte
        titulado "Usuarios y Documentos" que contaba autorías salía en blanco
        —3 autores en toda la base— y no es lo que pide la §7.5.3.
        """
        from itcj2.apps.adhoc.utils.constants import REPORT_TYPES

        meta = REPORT_META["usuarios_documentos"]
        assert "usuarios_documentos" in REPORT_TYPES
        assert "Difusión" in meta["title"]
        assert "Difusion" in meta["file_prefix"]
        assert meta["subject"] == "users"

    def test_carga_en_lote_no_n_mas_uno(self, db_session, adhoc_app, adhoc_role):
        """55 usuarios y 9 390 pares: un N+1 aquí son 55 consultas."""
        tag = _tag()
        doc = _make_document(db_session, title=f"Comun {tag}")
        primero = _make_user(db_session, adhoc_app, adhoc_role, first=f"DIFN{tag}")
        _grant_visibility(db_session, doc, primero)
        _acknowledge(db_session, doc, primero)

        with count_queries(db_session) as una:
            ReportService.build_report(db_session, "usuarios_documentos",
                                       nombre=f"DIFN{tag}", formato="completo")
        con_uno = len(una)

        for i in range(3):
            extra = _make_user(db_session, adhoc_app, adhoc_role,
                               first=f"DIFN{tag}", last=f"APELLIDO{i}")
            _grant_visibility(db_session, doc, extra)
            _acknowledge(db_session, doc, extra)

        with count_queries(db_session) as cuatro:
            report = ReportService.build_report(db_session, "usuarios_documentos",
                                                nombre=f"DIFN{tag}", formato="completo")

        assert len({r["user"] for r in _rows(report)}) == 4
        assert len(cuatro) == con_uno, (con_uno, len(cuatro))


# ---------------------------------------------------------------------------
# Los otros cuatro reportes NO se movieron
#
# La reescritura de `usuarios_documentos` tocó un solo constructor, pero comparte
# con los demás `_fetch_users`, `_areas_by_user`, `_fetch_documents` y el techo
# de `MAX_ROWS`. Lo que estos tests fijan es que cada reporte sigue midiendo lo
# suyo, y sobre todo que `documentos_usuarios` —cuyo nombre es el de este del
# revés— siga siendo otra cosa: mide los VALIDADORES del flujo de aprobación,
# no la lista de distribución.
# ---------------------------------------------------------------------------

class TestNoRegresionDeLosOtrosCuatro:
    #: Las cuatro claves que solo tiene el reporte de difusión.
    COLUMNAS_DE_DIFUSION = {"access", "assigned", "acknowledged", "coverage"}

    @pytest.mark.parametrize("report_type", [
        "area_usuarios", "usuarios_tareas", "documentos_usuarios", "documentos_notas",
    ])
    @pytest.mark.parametrize("formato", ["sencillo", "completo"])
    def test_ninguno_publica_las_columnas_de_difusion(
        self, db_session, report_type, formato
    ):
        report = ReportService.build_report(
            db_session, report_type, formato=formato, nombre=f"zz{_tag()}"
        )
        assert set(_col_keys(report)) & self.COLUMNAS_DE_DIFUSION == set()

    def test_documentos_usuarios_sigue_midiendo_validadores_no_destinatarios(
        self, db_session, adhoc_app, adhoc_role
    ):
        """Los dos nombres se parecen; los conceptos no tienen nada que ver.

        ``documentos_usuarios`` responde "quién tiene que APROBAR este
        documento" —los validadores de los pasos de su flujo—, y
        ``usuarios_documentos`` responde "a quién se le DISTRIBUYÓ". Una persona
        puede estar en una lista y no en la otra, que es justo lo que se siembra
        aquí.
        """
        tag = _tag()
        validador = _make_user(db_session, adhoc_app, adhoc_role,
                               first="Vale", last=f"Validador{tag}")
        destinatario = _make_user(db_session, adhoc_app, adhoc_role,
                                  first="Desi", last=f"Destinatario{tag}")
        flow = _make_flow(db_session)
        _make_step(db_session, flow, name="Revisión", order=1, assignees=[validador])
        titulo = f"Procedimiento {tag}"
        doc = _make_document(db_session, title=titulo, flow=flow)
        _grant_visibility(db_session, doc, destinatario)
        _acknowledge(db_session, doc, destinatario)

        fila = _rows(ReportService.build_report(
            db_session, "documentos_usuarios", nombre=titulo))[0]

        assert f"Vale Validador{tag}" in fila["assigned_users"]
        assert f"Desi Destinatario{tag}" not in fila["assigned_users"]
        assert fila["total_steps"] == 1

    def test_usuarios_tareas_no_cuenta_documentos_difundidos(
        self, db_session, adhoc_app, adhoc_role
    ):
        """Difundir un documento no le crea trabajo a nadie.

        Los dos reportes parten de usuarios y comparten ``_fetch_users``; lo que
        cambia es la colección que se les cruza.
        """
        tag = _tag()
        user = _make_user(db_session, adhoc_app, adhoc_role, first=f"TAR{tag}")
        doc = _make_document(db_session, title=f"Doc {tag}")
        _grant_visibility(db_session, doc, user)
        _acknowledge(db_session, doc, user)

        fila = _rows(ReportService.build_report(
            db_session, "usuarios_tareas", nombre=f"TAR{tag}", formato="completo"))[0]

        assert fila["total_tasks"] == 0
        assert fila["description"] == "Sin tareas asignadas"

    def test_area_usuarios_sigue_partiendo_de_quien_tiene_acceso(
        self, db_session, adhoc_app, adhoc_role
    ):
        """Las dos colecciones son distintas **a propósito**, y en los dos sentidos.

        ``area_usuarios`` lista a quien puede entrar a Calidad (29 personas);
        ``usuarios_documentos`` lista a quien tiene difusión (55, de las que 26
        ya no entran). Intersecarlas habría borrado del papel a esas 26 —y con
        ellas buena parte de las 9 390 filas de evidencia—, pero tampoco vale lo
        contrario: quien tiene acceso y ninguna difusión sigue teniendo que salir
        en el reporte de áreas.
        """
        tag = _tag()
        sin_difusion = _make_user(db_session, adhoc_app, adhoc_role,
                                  first=f"AMB{tag}", last="AAA")
        con_difusion = _make_user(db_session, adhoc_app, adhoc_role,
                                  first=f"AMB{tag}", last="BBB")
        doc = _make_document(db_session, title=f"Doc {tag}")
        _grant_visibility(db_session, doc, con_difusion)

        areas = {r["first_name"] + r["last_name"]
                 for r in _rows(ReportService.build_report(
                     db_session, "area_usuarios", nombre=f"AMB{tag}"))}
        difusion = {r["user"] for r in _rows(ReportService.build_report(
            db_session, "usuarios_documentos", nombre=f"AMB{tag}"))}

        assert areas == {f"AMB{tag}AAA", f"AMB{tag}BBB"}
        assert difusion == {_full(con_difusion)}

    def test_documentos_notas_ignora_por_completo_la_difusion(self, db_session,
                                                              adhoc_app, adhoc_role):
        """Un documento sin destinatarios sale igual: mide notas, no difusión."""
        tag = _tag()
        _make_document(db_session, title=f"Sin difundir {tag}", notes="Revisar anexo")

        fila = _rows(ReportService.build_report(
            db_session, "documentos_notas", nombre=tag))[0]

        assert fila["has_notes"] == "Sí"


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

    def test_el_reporte_de_difusion_tampoco_cuenta_las_superadas(
        self, db_session, adhoc_app, adhoc_role
    ):
        """``usuarios_documentos`` es el único que no pasa por ``_fetch_documents``.

        Parte de la lista de difusión (``_visibility_by_user``), así que el
        filtro de control documental hay que repetirlo ahí. Sin él la persona
        sale con dos filas del mismo ``code``, dos versiones y dos porcentajes.
        No es teórico: 2 679 de las 9 390 filas de ``adhoc_document_visibility``
        apuntan a una versión superada (58 documentos).
        """
        tag = _tag()
        lector = _make_user(db_session, adhoc_app, adhoc_role, first=f"DIFVER{tag}")
        raiz = _make_document(db_session, title=f"Manual {tag}", code=f"MC-{tag[:6]}",
                              version="1.0", is_current=False, status="Obsoleto")
        vigente = _make_document(db_session, title=f"Manual {tag}", code=raiz.code,
                                 version="2.0", is_current=True, parent=raiz)
        # La difusión histórica apunta a las DOS filas de la cadena.
        _grant_visibility(db_session, raiz, lector)
        _grant_visibility(db_session, vigente, lector)

        report = ReportService.build_report(
            db_session, "usuarios_documentos", nombre=lector.first_name,
            formato="completo",
        )
        filas = _rows(report)

        assert [f["assigned"] for f in filas] == [1]
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

    def test_la_difusion_tiene_techo_de_FILAS_no_solo_de_personas(
        self, db_session, adhoc_app, adhoc_role, monkeypatch
    ):
        """``MAX_ROWS`` cuenta personas; en este reporte lo que crece son filas.

        Desde que el formato completo abre una fila por par (usuario,
        documento), las dos cosas dejaron de ser la misma: en la base real son
        55 personas —muy por debajo del techo de 5 000— y **6 711 filas**, unos
        8,7 MB de HTML, con ``truncated`` apagado. El aviso de la página era
        literalmente veraz e inalcanzable: para que saltara harían falta 5 000
        personas con difusión, o sea ~600 000 filas emitidas antes de que el
        seguro mirase.
        """
        tag = _tag()
        user = _make_user(db_session, adhoc_app, adhoc_role, first=f"FILA{tag}")
        for i in range(4):
            doc = _make_document(db_session, title=f"Masa {tag} {i}")
            _grant_visibility(db_session, doc, user)

        # Una sola persona: MAX_ROWS ni se acerca, y aun así hay que cortar.
        monkeypatch.setattr(ReportService, "MAX_ROWS", 5000)
        monkeypatch.setattr(ReportService, "MAX_DETAIL_ROWS", 3)
        report = ReportService.build_report(
            db_session, "usuarios_documentos", nombre=f"FILA{tag}", formato="completo")

        assert len(_rows(report)) == 3
        assert report["truncated"] is True
        assert report["max_detail_rows"] == 3

    def test_el_techo_de_filas_no_recorta_el_formato_sencillo(
        self, db_session, adhoc_app, adhoc_role, monkeypatch
    ):
        """Una fila por persona: ahí el techo de detalle no tiene nada que hacer."""
        tag = _tag()
        user = _make_user(db_session, adhoc_app, adhoc_role, first=f"SENC{tag}")
        for i in range(4):
            doc = _make_document(db_session, title=f"Simple {tag} {i}")
            _grant_visibility(db_session, doc, user)

        monkeypatch.setattr(ReportService, "MAX_DETAIL_ROWS", 3)
        report = ReportService.build_report(
            db_session, "usuarios_documentos", nombre=f"SENC{tag}")

        assert len(_rows(report)) == 1
        assert report["truncated"] is False
        assert _rows(report)[0]["assigned"] == 4


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
            # `preview` dice de qué colección salen las filas de la previa;
            # `subject`, qué panel se enseña. No son la misma clave.
            assert card["preview"] in ("users", "users_diffusion", "documents")

    def test_la_previa_de_difusion_sale_de_la_lista_de_difusion(
        self, db_session, adhoc_app, adhoc_role
    ):
        """La previa tiene que enseñar la MISMA colección que el reporte lista.

        Es el fallo que este test fija: ``usuarios_documentos`` dejó de partir
        de ``_fetch_users`` (29 personas con acceso) y pasó a partir de
        ``_fetch_users_with_visibility`` (55 con difusión), pero la previa
        siguió saliendo de la primera. Resultado: filtrar por alguien que SÍ
        sale en el reporte —30 personas están en ese hueco— contestaba "0
        coincidencias", y quien usaba la previa para comprobar si una persona
        tiene evidencia de difusión concluía que no la tiene.

        Aquí el usuario NO tiene acceso a la app (sin ``app``/``role``) pero sí
        difusión: tiene que estar en ``users_diffusion`` y no en ``users``.
        """
        tag = _tag()
        sin_acceso = _make_user(db_session, first=f"PREVIA{tag}")
        doc = _make_document(db_session, title=f"Difundido {tag}")
        _grant_visibility(db_session, doc, sin_acceso)

        data = ReportService.get_selection_data(db_session)
        nombres_previa = {u["first_name"] for u in data["users"]}
        nombres_difusion = {u["first_name"] for u in data["users_diffusion"]}

        assert sin_acceso.first_name in nombres_difusion
        assert sin_acceso.first_name not in nombres_previa
        # Y el reporte lo lista: previa y reporte ya coinciden.
        filas = _rows(ReportService.build_report(
            db_session, "usuarios_documentos", nombre=f"PREVIA{tag}"))
        assert [f["user"] for f in filas] == [_full(sin_acceso)]

    def test_la_previa_de_difusion_trae_las_mismas_columnas_que_la_de_usuarios(
        self, db_session, adhoc_app, adhoc_role
    ):
        """Comparten panel en el modal, así que tienen que compartir forma."""
        area = _make_area(db_session)
        user = _make_user(db_session, adhoc_app, adhoc_role, first=f"FORMA{_tag()}")
        _assign_area(db_session, user, area)
        doc = _make_document(db_session, title=f"Doc {_tag()}")
        _grant_visibility(db_session, doc, user)

        data = ReportService.get_selection_data(db_session)
        fila = next(u for u in data["users_diffusion"]
                    if u["first_name"] == user.first_name)

        assert set(fila) == {"first_name", "last_name", "areas"}
        assert fila["areas"] == area.name
