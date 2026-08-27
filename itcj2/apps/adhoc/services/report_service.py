"""Los cinco reportes imprimibles de Calidad.

En el legacy esto vivía en ``routes/api/api_reports.py`` y devolvía **HTML desde
``/api/``** (bug #21 del plan). Aquí el service solo produce **datos**: una lista
de columnas y una lista de filas ya aplanadas y formateadas. La página
(``pages/reports.py``) las pinta con un único template y el módulo JS las exporta
a Excel. Ninguna de las dos capas sabe nada de SQL ni de fechas.

Los tres defectos del original que este módulo corrige
--------------------------------------------------------------------------

1. **Filtro de área en Python.** ``obtener_usuarios_filtrados`` traía todos los
   usuarios de la app y luego hacía
   ``[u for u in usuarios if u.areas_asignadas and u.areas_asignadas[0].name == f_area]``.
   Aquí el filtro es un ``IN (SELECT … FROM adhoc_user_areas …)``.

2. **Solo miraba la primera área.** El ``[0]`` de arriba: quien tuviera dos
   áreas desaparecía del reporte al filtrar por la segunda, y en la columna
   "Área Asignada" se le escondían las demás. Ahora el filtro casa con
   *cualquiera* de sus áreas y la columna las lista todas.

3. **N+1 masivo.** Una consulta de tareas y otra de documentos **por cada
   usuario** (``for u in usuarios_filtrados: Task.query.filter(...)``). Aquí hay
   una sola consulta por colección, con ``IN (…)`` sobre los ids ya conocidos:
   el coste en consultas es constante, no proporcional al número de filas.

Y un cuarto, heredado de todo el legacy: ``app_id = 4`` hardcodeado
(``api_reports.py:29``), que en la BD de itcj2 es *warehouse*. La app se resuelve
siempre por ``key='adhoc'``.

Alcance documental: solo la versión vigente
-------------------------------------------

Los cinco reportes miran **únicamente** los documentos con ``is_current=True``.
No es un filtro de conveniencia ni una optimización: es control documental.
``adhoc_documents`` guarda la cadena de versiones completa (``parent_id`` apunta
a la raíz, y hay exactamente una fila ``is_current=True`` por cadena), así que
sin ese filtro un reporte imprimible saca varias filas con el **mismo `code`** y
ninguna columna que diga cuál está en vigor. Un reporte imprimible del SGC es lo
que se entrega en una auditoría ISO 9001, y entregar ahí las versiones superadas
como si estuvieran vigentes es una no conformidad de 7.5.3 (impedir el uso no
intencionado de documentos obsoletos). El historial completo se consulta donde
corresponde: ``GET /api/adhoc/v2/documents/{document_id}/versions``.

El filtro vive en **dos** consultas, no en una: ``_fetch_documents`` (los cuatro
reportes que parten de documentos) y ``_documents_by_author`` (el quinto,
``usuarios_documentos``, que parte de usuarios y agrupa por autor). Si se toca
una, se toca la otra.

Contrato de errores
-------------------
* :class:`LookupError` — el tipo de reporte no existe → la página responde 404.

Sin paginación (un reporte imprimible se emite entero o no sirve), pero **con un
techo defensivo**: :attr:`ReportService.MAX_ROWS` limita las entidades de origen
y la respuesta trae ``truncated`` para que la página lo avise en pantalla.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Final, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased, joinedload

from itcj2.apps.adhoc.utils.constants import REPORT_TYPES

logger = logging.getLogger(__name__)

__all__ = ["ReportService", "REPORT_META", "REPORT_FORMATS", "FORMAT_DEFAULT"]

#: Formatos de salida del formulario de selección. El legacy hacía
#: ``if formato == 'sencillo': … else: …``, así que cualquier basura en la query
#: string ("formato=<script>") caía en la rama "completo". Aquí es una whitelist
#: y lo desconocido cae al default.
REPORT_FORMATS: Final[tuple[str, ...]] = ("sencillo", "completo")
FORMAT_DEFAULT: Final[str] = "sencillo"

_NA: Final[str] = "N/A"
_NO_AREA: Final[str] = "Sin Área"

#: Metadatos de los 5 reportes. `sheet` y `file_prefix` los consume el módulo JS
#: de exportación (los 5 archivos del legacy eran el MISMO código y solo se
#: diferenciaban en estos dos valores y en el nombre de la clase).
#: `subject` dice sobre qué entidad filtra la pantalla de selección, para que el
#: modal enseñe la vista previa correcta.
REPORT_META: Final[dict[str, dict[str, str]]] = {
    "area_usuarios": {
        "title": "Reporte de Área y Usuarios",
        "label": "Área y Usuarios",
        "sheet": "Usuarios y Areas",
        "file_prefix": "Reporte_Areas_Usuarios",
        "subject": "users",
        "icon": "fa-solid fa-layer-group",
        "icon_overlay": "fa-solid fa-users",
    },
    "usuarios_tareas": {
        "title": "Reporte de Usuarios y Tareas",
        "label": "Usuarios y Tareas",
        "sheet": "Tareas",
        "file_prefix": "Reporte_Usuarios_Tareas",
        "subject": "users",
        "icon": "fa-solid fa-user-tie",
        "icon_overlay": "fa-solid fa-list-check",
    },
    "usuarios_documentos": {
        "title": "Reporte de Usuarios y Documentos",
        "label": "Usuarios y Documentos",
        "sheet": "UsuariosDocumentos",
        "file_prefix": "Reporte_Usuarios_Documentos",
        "subject": "users",
        "icon": "fa-solid fa-users",
        "icon_overlay": "fa-solid fa-file-pdf",
    },
    "documentos_usuarios": {
        "title": "Reporte de Documentos y Usuarios",
        "label": "Documentos y Usuarios",
        "sheet": "DocumentosUsuarios",
        "file_prefix": "Reporte_Documentos_Usuarios",
        "subject": "documents",
        "icon": "fa-solid fa-file-signature",
        "icon_overlay": "fa-solid fa-user-tag",
    },
    "documentos_notas": {
        "title": "Reporte de Documentos y Notas",
        "label": "Documentos y Notas",
        "sheet": "DocumentosNotas",
        "file_prefix": "Reporte_Documentos_Notas",
        "subject": "documents",
        "icon": "fa-solid fa-file-lines",
        "icon_overlay": "fa-solid fa-note-sticky",
    },
}

# Falla en el import si alguien añade un tipo en constants.py y se olvida aquí
# (o al revés): las dos listas TIENEN que ser la misma.
assert set(REPORT_META) == set(REPORT_TYPES), (
    "REPORT_META y utils.constants.REPORT_TYPES divergen: "
    f"{set(REPORT_META) ^ set(REPORT_TYPES)}"
)


# ==========================================================================
# Helpers de formato — el template no formatea nada
# ==========================================================================

def _clean(value: str | None) -> str:
    return (value or "").strip()


def _full_name(user) -> str:
    """``"Nombre Apellido"`` o ``"N/A"``. Molde: ``api_reports.nombre_usuario``."""
    if user is None:
        return _NA
    name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    return name or _NA


def _fmt_date(value: date | datetime | None) -> str:
    if value is None:
        return _NA
    return value.strftime("%d/%m/%Y")


def _col(key: str, label: str, align: str = "start") -> dict[str, str]:
    return {"key": key, "label": label, "align": align}


# ==========================================================================
# Service
# ==========================================================================

class ReportService:
    """Los 5 reportes + los datos de la pantalla de selección.

    Todos los métodos son de solo lectura: no hay ``commit`` en este módulo.
    """

    #: Techo de entidades de origen (usuarios o documentos) por reporte. No es
    #: paginación —un reporte imprimible se emite entero—, es un seguro contra
    #: un ``SELECT`` sin límite el día que la tabla crezca. Se lee como atributo
    #: de clase a propósito: los tests lo bajan con ``monkeypatch``.
    MAX_ROWS: int = 5000

    # ----------------------------------------------------------------------
    # Fachada
    # ----------------------------------------------------------------------

    @staticmethod
    def build_report(
        db: Session,
        report_type: str,
        *,
        nombre: str | None = "",
        apellidos: str | None = "",
        area: str | None = "",
        formato: str | None = FORMAT_DEFAULT,
    ) -> dict[str, Any]:
        """Construye un reporte completo (metadatos + columnas + filas).

        Args:
            report_type: uno de :data:`REPORT_META`.
            nombre: sobre usuarios filtra ``first_name``; sobre documentos,
                ``title`` **o** ``code`` (así lo hacía el legacy).
            apellidos: ``last_name`` del usuario o del **autor** del documento.
            area: nombre exacto del área (el ``<select>`` de la pantalla).
            formato: ``sencillo`` | ``completo``; cualquier otra cosa cae a
                ``sencillo``.

        Raises:
            LookupError: ``report_type`` desconocido. El legacy devolvía la
                cadena cruda ``"Reporte no encontrado", 404``.
        """
        meta = REPORT_META.get(report_type)
        if meta is None:
            raise LookupError(f"Tipo de reporte desconocido: {report_type!r}")

        fmt = formato if formato in REPORT_FORMATS else FORMAT_DEFAULT
        filters = {
            "nombre": _clean(nombre),
            "apellidos": _clean(apellidos),
            "area": _clean(area),
        }
        detailed = fmt == "completo"

        builder = _BUILDERS[report_type]
        columns, rows, subjects, truncated = builder(db, filters, detailed)

        return {
            "report_type": report_type,
            "title": meta["title"],
            "label": meta["label"],
            "sheet": meta["sheet"],
            "file_prefix": meta["file_prefix"],
            "subject": meta["subject"],
            "formato": fmt,
            "columns": columns,
            "rows": rows,
            "total": len(rows),
            "subjects": subjects,
            "truncated": truncated,
            "max_rows": ReportService.MAX_ROWS,
            "filters": filters,
        }

    @staticmethod
    def get_selection_data(db: Session) -> dict[str, Any]:
        """Contexto de ``/adhoc/reportes``: tarjetas, áreas y las dos vistas previas.

        Las dos vistas previas (usuarios y documentos) son las del legacy, que
        las repartía entre dos modales distintos. Van juntas y sin ``<option>``
        pre-renderizados: la página las emite dentro del bloque
        ``<script type="application/json">`` y el JS las pinta escapando.
        """
        users, _u_trunc = ReportService._fetch_users(db, {"nombre": "", "apellidos": "", "area": ""})
        areas_by_user = ReportService._areas_by_user(db, [u.id for u in users])
        documents, _d_trunc = ReportService._fetch_documents(
            db, {"nombre": "", "apellidos": "", "area": ""}, with_flow=False
        )

        return {
            "reports": [
                {
                    "type": key,
                    "title": meta["title"],
                    "label": meta["label"],
                    "subject": meta["subject"],
                    "icon": meta["icon"],
                    "icon_overlay": meta["icon_overlay"],
                }
                for key, meta in REPORT_META.items()
            ],
            "formats": list(REPORT_FORMATS),
            "areas": ReportService.list_areas(db),
            "users": [
                {
                    "first_name": user.first_name or "",
                    "last_name": f"{user.last_name or ''} {user.middle_name or ''}".strip(),
                    "areas": _join_areas(areas_by_user.get(user.id)),
                }
                for user in users
            ],
            "documents": [
                {
                    "code": doc.code or _NA,
                    "title": doc.title,
                    "author": _full_name(doc.author),
                    "area": doc.area.name if doc.area else _NA,
                    "status": doc.status or _NA,
                    "version": doc.version or _NA,
                    "created_at": _fmt_date(doc.created_at),
                    "notes": doc.notes or "Sin notas",
                }
                for doc in documents
            ],
        }

    @staticmethod
    def list_areas(db: Session) -> list[dict[str, Any]]:
        """Áreas activas, para el ``<select>`` de filtro.

        ``is_active`` es NOT NULL en ``adhoc_areas`` (en el legacy era nullable
        y las filas con NULL se evaporaban del filtro ``active=True``).
        """
        from itcj2.apps.adhoc.models import AdhocArea

        rows = (
            db.query(AdhocArea)
            .filter(AdhocArea.is_active.is_(True))
            .order_by(AdhocArea.name.asc())
            .all()
        )
        return [{"id": a.id, "name": a.name, "color": a.color} for a in rows]

    # ----------------------------------------------------------------------
    # Selección de entidades — el filtrado ocurre AQUÍ, en SQL
    # ----------------------------------------------------------------------

    @staticmethod
    def _app_id(db: Session) -> int | None:
        """Id de ``core_apps`` resuelto por ``key`` (nunca hardcodeado)."""
        from itcj2.core.models.app import App
        from itcj2.apps.adhoc.utils.constants import APP_KEY

        return db.query(App.id).filter(App.key == APP_KEY).scalar()

    @staticmethod
    def _fetch_users(db: Session, filters: dict[str, str]) -> tuple[list, bool]:
        """Usuarios **activos con acceso a Calidad**, ya filtrados en SQL.

        Devuelve ``(usuarios, truncado)``. Se pide un registro de más que el
        techo para saber si había más sin traérselos todos.
        """
        from itcj2.apps.adhoc.models import AdhocArea, adhoc_user_areas
        from itcj2.core.models.user import User
        from itcj2.core.models.user_app_role import UserAppRole

        app_id = ReportService._app_id(db)
        if app_id is None:
            # Sin fila en core_apps no hay a quién listar. Fail-closed: el
            # legacy, con su app_id=4, listaba a los usuarios de otra app.
            logger.warning("adhoc reports: la app 'adhoc' no está en core_apps")
            return [], False

        query = (
            db.query(User)
            .join(UserAppRole, UserAppRole.user_id == User.id)
            .filter(User.is_active.is_(True), UserAppRole.app_id == app_id)
        )

        if filters["nombre"]:
            query = query.filter(User.first_name.ilike(f"%{filters['nombre']}%"))
        if filters["apellidos"]:
            query = query.filter(User.last_name.ilike(f"%{filters['apellidos']}%"))
        if filters["area"]:
            # EL arreglo: subconsulta sobre la tabla de asociación en vez del
            # `areas_asignadas[0]` en memoria. Casa con CUALQUIERA de sus áreas.
            in_area = (
                select(adhoc_user_areas.c.user_id)
                .join(AdhocArea, AdhocArea.id == adhoc_user_areas.c.area_id)
                .where(AdhocArea.name == filters["area"])
            )
            query = query.filter(User.id.in_(in_area))

        limit = ReportService.MAX_ROWS
        rows = (
            query.distinct()
            .order_by(User.last_name.asc(), User.first_name.asc(), User.id.asc())
            .limit(limit + 1)
            .all()
        )
        return rows[:limit], len(rows) > limit

    @staticmethod
    def _fetch_documents(
        db: Session, filters: dict[str, str], *, with_flow: bool
    ) -> tuple[list, bool]:
        """Documentos **vigentes**, filtrados en SQL, con la carga previa que toque.

        ``with_flow=True`` añade el flujo, sus pasos y los validadores de cada
        paso — las tres colecciones que ``documentos_usuarios`` recorre. Sin
        esto, cada ``doc.flow.steps[i].assignees`` sería una consulta más.

        Las versiones superadas quedan fuera (ver el encabezado del módulo).
        Esta es la fuente de documentos de cuatro de los cinco reportes; el
        quinto, ``usuarios_documentos``, agrupa por autor y va por
        ``_documents_by_author``, que repite el mismo filtro. Son los **dos**
        sitios donde se aplica el criterio, y tienen que moverse juntos.
        """
        from itcj2.apps.adhoc.models import (
            AdhocApprovalFlow,
            AdhocApprovalFlowStep,
            AdhocArea,
            AdhocDocument,
        )
        from itcj2.core.models.user import User

        options = [
            joinedload(AdhocDocument.author),
            joinedload(AdhocDocument.area),
            joinedload(AdhocDocument.category),
        ]
        if with_flow:
            options.append(
                joinedload(AdhocDocument.flow)
                .selectinload(AdhocApprovalFlow.steps)
                .selectinload(AdhocApprovalFlowStep.assignees)
            )

        query = db.query(AdhocDocument).options(*options)

        # Control documental, NO una optimización. La tabla guarda la cadena de
        # versiones entera y solo una fila por cadena es la punta; sin este
        # WHERE los reportes arrastran las versiones superadas, repetidas bajo
        # el mismo `code` y sin nada que las distinga en el papel impreso. Eso
        # es exactamente lo que la cláusula 7.5.3 de ISO 9001 prohíbe entregar.
        #
        # Ojo: `is_current` NO equivale a `status != 'Obsoleto'`. Hay filas
        # históricas que son punta de su cadena y a la vez están marcadas
        # 'Obsoleto' (dato legítimo, no una inconsistencia que arreglar): siguen
        # saliendo en los reportes y su estado se lee en la columna "Estado".
        query = query.filter(AdhocDocument.is_current.is_(True))

        if filters["nombre"]:
            like = f"%{filters['nombre']}%"
            query = query.filter(
                AdhocDocument.title.ilike(like) | AdhocDocument.code.ilike(like)
            )
        if filters["apellidos"]:
            # Alias propio: el joinedload de `author` monta su propia copia de
            # core_users, y reutilizar esa para filtrar la volvería un INNER
            # JOIN silencioso (perdiendo los documentos sin autor).
            author = aliased(User)
            query = query.join(author, AdhocDocument.author_id == author.id).filter(
                author.last_name.ilike(f"%{filters['apellidos']}%")
            )
        if filters["area"]:
            doc_area = aliased(AdhocArea)
            query = query.join(doc_area, AdhocDocument.area_id == doc_area.id).filter(
                doc_area.name == filters["area"]
            )

        limit = ReportService.MAX_ROWS
        rows = (
            query.order_by(AdhocDocument.created_at.desc(), AdhocDocument.id.desc())
            .limit(limit + 1)
            .all()
        )
        return rows[:limit], len(rows) > limit

    # ----------------------------------------------------------------------
    # Cargas en lote (una consulta por colección, nunca una por usuario)
    # ----------------------------------------------------------------------

    @staticmethod
    def _areas_by_user(db: Session, user_ids: Sequence[int]) -> dict[int, list[str]]:
        from itcj2.apps.adhoc.models import AdhocArea, adhoc_user_areas

        if not user_ids:
            return {}

        out: dict[int, list[str]] = {}
        rows = (
            db.query(adhoc_user_areas.c.user_id, AdhocArea.name)
            .join(AdhocArea, AdhocArea.id == adhoc_user_areas.c.area_id)
            .filter(adhoc_user_areas.c.user_id.in_(user_ids))
            .order_by(AdhocArea.name.asc())
            .all()
        )
        for user_id, name in rows:
            out.setdefault(user_id, []).append(name)
        return out

    @staticmethod
    def _tasks_by_user(db: Session, user_ids: Sequence[int]) -> dict[int, list]:
        from itcj2.apps.adhoc.models import AdhocTask, adhoc_task_assignees

        if not user_ids:
            return {}

        out: dict[int, list] = {}
        rows = (
            db.query(adhoc_task_assignees.c.user_id, AdhocTask)
            .join(AdhocTask, AdhocTask.id == adhoc_task_assignees.c.task_id)
            .filter(adhoc_task_assignees.c.user_id.in_(user_ids))
            .order_by(AdhocTask.id.asc())
            .all()
        )
        for user_id, task in rows:
            out.setdefault(user_id, []).append(task)
        return out

    @staticmethod
    def _documents_by_author(db: Session, user_ids: Sequence[int]) -> dict[int, list]:
        """Documentos **vigentes** de cada autor, en un solo golpe.

        Es la fuente de ``usuarios_documentos`` y la única del módulo que no
        pasa por ``_fetch_documents``: aquí se agrupa por autor, no se filtra por
        los criterios del formulario. Por eso el filtro de control documental se
        repite —``is_current=True``, el mismo del encabezado del módulo—: sin él
        este reporte era el hueco por el que las versiones superadas entraban al
        papel que se pone sobre la mesa en una auditoría, tanto en la columna
        "Total Documentos" como en las filas de detalle. Hoy pasa desapercibido
        solo porque los dos autores con versiones superadas están inactivos y
        ``_fetch_users`` los descarta; en cuanto alguien anexe una versión desde
        el panel, el autor de la superada será un usuario activo.
        """
        from itcj2.apps.adhoc.models import AdhocDocument

        if not user_ids:
            return {}

        out: dict[int, list] = {}
        rows = (
            db.query(AdhocDocument)
            .options(joinedload(AdhocDocument.category))
            .filter(
                AdhocDocument.author_id.in_(user_ids),
                AdhocDocument.is_current.is_(True),
            )
            .order_by(AdhocDocument.created_at.desc(), AdhocDocument.id.desc())
            .all()
        )
        for doc in rows:
            out.setdefault(doc.author_id, []).append(doc)
        return out


def _join_areas(names: Iterable[str] | None) -> str:
    """Todas las áreas del usuario, no solo la primera (bug del legacy)."""
    names = list(names or [])
    return ", ".join(names) if names else _NO_AREA


# ==========================================================================
# Constructores por tipo de reporte
#
# Cada uno devuelve (columns, rows, subjects, truncated). Las filas son PLANAS:
# un dict por <tr> con una clave por columna. El legacy usaba `colspan` para las
# filas "sin datos", lo que desalineaba la exportación de SheetJS
# (`XLSX.utils.table_to_book` lee el <table> tal cual); aquí todas las filas
# tienen todas las celdas.
# ==========================================================================

def _build_area_usuarios(db: Session, filters: dict[str, str], detailed: bool):
    users, truncated = ReportService._fetch_users(db, filters)
    areas_by_user = ReportService._areas_by_user(db, [u.id for u in users])

    columns = [
        _col("first_name", "Nombre"),
        _col("last_name", "Apellidos"),
        _col("areas", "Área Asignada"),
    ]
    if detailed:
        columns += [_col("email", "Correo Electrónico"), _col("status", "Estado")]

    rows = []
    for user in users:
        row = {
            "first_name": user.first_name or "",
            "last_name": user.last_name or "",
            "areas": _join_areas(areas_by_user.get(user.id)),
        }
        if detailed:
            row["email"] = user.email or _NA
            row["status"] = "Activo" if user.is_active else "Inactivo"
        rows.append(row)

    return columns, rows, len(users), truncated


def _build_usuarios_tareas(db: Session, filters: dict[str, str], detailed: bool):
    users, truncated = ReportService._fetch_users(db, filters)
    user_ids = [u.id for u in users]
    areas_by_user = ReportService._areas_by_user(db, user_ids)
    tasks_by_user = ReportService._tasks_by_user(db, user_ids)

    columns = [
        _col("user", "Colaborador"),
        _col("areas", "Área"),
        _col("total_tasks", "Total Tareas Asignadas", "center"),
    ]
    if detailed:
        columns += [
            _col("description", "Descripción de la Tarea"),
            _col("status", "Estatus"),
            _col("due_date", "Fecha Límite"),
        ]

    rows = []
    for user in users:
        tasks = tasks_by_user.get(user.id, [])
        base = {
            "user": _full_name(user),
            "areas": _join_areas(areas_by_user.get(user.id)),
            "total_tasks": len(tasks),
        }
        if not detailed:
            rows.append(base)
            continue
        if not tasks:
            rows.append({**base, "description": "Sin tareas asignadas",
                         "status": "", "due_date": ""})
            continue
        for task in tasks:
            rows.append({
                **base,
                "description": task.description or "",
                "status": task.status or _NA,
                "due_date": _fmt_date(task.due_date),
            })

    return columns, rows, len(users), truncated


def _build_usuarios_documentos(db: Session, filters: dict[str, str], detailed: bool):
    users, truncated = ReportService._fetch_users(db, filters)
    user_ids = [u.id for u in users]
    areas_by_user = ReportService._areas_by_user(db, user_ids)
    docs_by_author = ReportService._documents_by_author(db, user_ids)

    columns = [
        _col("user", "Usuario"),
        _col("areas", "Área"),
        _col("total_documents", "Total Documentos", "center"),
    ]
    if detailed:
        columns += [
            _col("code", "Código"),
            _col("title", "Título"),
            _col("version", "Versión"),
            _col("doc_status", "Estado"),
            _col("category", "Categoría"),
            _col("created_at", "Fecha Creación"),
        ]

    rows = []
    for user in users:
        docs = docs_by_author.get(user.id, [])
        base = {
            "user": _full_name(user),
            "areas": _join_areas(areas_by_user.get(user.id)),
            "total_documents": len(docs),
        }
        if not detailed:
            rows.append(base)
            continue
        if not docs:
            rows.append({
                **base,
                "code": "Sin documentos asignados como autor",
                "title": "", "version": "", "doc_status": "",
                "category": "", "created_at": "",
            })
            continue
        for doc in docs:
            rows.append({
                **base,
                "code": doc.code or _NA,
                "title": doc.title or "",
                "version": doc.version or _NA,
                "doc_status": doc.status or _NA,
                "category": doc.category.name if doc.category else _NA,
                "created_at": _fmt_date(doc.created_at),
            })

    return columns, rows, len(users), truncated


def _ordered_steps(doc) -> list:
    """Pasos del flujo ordenados por ``step_order``.

    El ``relationship`` ya trae ``order_by``, pero el orden se reafirma aquí:
    es el que decide el número de fila del reporte detallado y no debe depender
    de cómo se haya cargado la colección.
    """
    flow = doc.flow
    if flow is None:
        return []
    return sorted(flow.steps or [], key=lambda s: (s.step_order or 0, s.id or 0))


def _build_documentos_usuarios(db: Session, filters: dict[str, str], detailed: bool):
    documents, truncated = ReportService._fetch_documents(db, filters, with_flow=True)

    if detailed:
        columns = [
            _col("code", "Código"),
            _col("title", "Título"),
            _col("author", "Autor"),
            _col("flow_name", "Flujo"),
            _col("flow_description", "Descripción Flujo"),
            _col("step_order", "Orden Paso", "center"),
            _col("step_name", "Paso"),
            _col("days_limit", "Límite Días", "center"),
            _col("assigned_users", "Usuarios Asignados"),
        ]
    else:
        columns = [
            _col("code", "Código"),
            _col("title", "Título"),
            _col("author", "Autor"),
            _col("flow_name", "Flujo"),
            _col("total_steps", "Total Pasos", "center"),
            _col("assigned_users", "Usuarios Asignados"),
        ]

    rows = []
    for doc in documents:
        steps = _ordered_steps(doc)
        base = {
            "code": doc.code or _NA,
            "title": doc.title or "",
            "author": _full_name(doc.author),
            "flow_name": doc.flow.name if doc.flow else "Sin flujo",
        }

        if not detailed:
            seen: set[int] = set()
            names: list[str] = []
            for step in steps:
                for user in step.assignees:
                    if user.id in seen:
                        continue
                    seen.add(user.id)
                    names.append(_full_name(user))
            rows.append({
                **base,
                "total_steps": len(steps),
                "assigned_users": ", ".join(names) if names else "Sin asignados",
            })
            continue

        flow_description = (
            doc.flow.description if doc.flow and doc.flow.description else _NA
        )
        if not steps:
            rows.append({
                **base,
                "flow_name": "Sin flujo",
                "flow_description": _NA,
                "step_order": _NA,
                "step_name": "Sin pasos",
                "days_limit": _NA,
                "assigned_users": "Sin asignados",
            })
            continue
        for step in steps:
            names = [_full_name(u) for u in step.assignees]
            rows.append({
                **base,
                "flow_description": flow_description,
                "step_order": step.step_order,
                "step_name": step.name or "",
                "days_limit": step.days_limit,
                "assigned_users": ", ".join(names) if names else "Sin asignados",
            })

    return columns, rows, len(documents), truncated


def _build_documentos_notas(db: Session, filters: dict[str, str], detailed: bool):
    documents, truncated = ReportService._fetch_documents(db, filters, with_flow=False)

    if detailed:
        columns = [
            _col("code", "Código"),
            _col("title", "Título"),
            _col("version", "Versión"),
            _col("doc_status", "Estado"),
            _col("author", "Autor"),
            _col("approval_date", "Fecha Aprobación"),
            _col("notes", "Notas"),
        ]
    else:
        columns = [
            _col("code", "Código"),
            _col("title", "Título"),
            _col("doc_status", "Estado"),
            _col("author", "Autor"),
            _col("has_notes", "Tiene Nota", "center"),
        ]

    rows = []
    for doc in documents:
        base = {
            "code": doc.code or _NA,
            "title": doc.title or "",
            "doc_status": doc.status or _NA,
            "author": _full_name(doc.author),
        }
        if detailed:
            rows.append({
                **base,
                "version": doc.version or _NA,
                "approval_date": _fmt_date(doc.approval_date),
                "notes": doc.notes or "Sin notas",
            })
        else:
            rows.append({**base, "has_notes": "Sí" if doc.notes else "No"})

    return columns, rows, len(documents), truncated


_BUILDERS = {
    "area_usuarios": _build_area_usuarios,
    "usuarios_tareas": _build_usuarios_tareas,
    "usuarios_documentos": _build_usuarios_documentos,
    "documentos_usuarios": _build_documentos_usuarios,
    "documentos_notas": _build_documentos_notas,
}
