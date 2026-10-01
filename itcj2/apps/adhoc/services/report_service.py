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
reportes que parten de documentos) y ``_visibility_by_user`` (el quinto,
``usuarios_documentos``, que parte de usuarios y cruza la lista de difusión).
Si se toca una, se toca la otra. El segundo sitio pesa en la base real: 2 679 de
las 9 390 filas de ``adhoc_document_visibility`` apuntan a una versión superada
(58 documentos). De esas, 2 433 son la MISMA persona sobre otra versión del
mismo ``code`` —ahí el filtro deduplica— y **246 no tienen sustituta**: la
versión en vigor de esa cadena no le está difundida a esa persona, así que el
filtro no quita una fila repetida, quita una fila. Se asume: lo que el reporte
promete es la difusión de lo que hoy está en vigor, y esas 246 son difusión de
algo que ya no lo está.

Y el acuse se cuenta sobre la MISMA versión, nunca sobre la cadena
------------------------------------------------------------------

Consecuencia directa de lo anterior, y la parte que más fácil es equivocar. En
``adhoc_document_acknowledgements`` hay 84 acuses sobre versiones superadas; 33
de ellos no tienen equivalente del mismo usuario sobre la versión en vigor. Es
tentador "recuperarlos" cruzando por raíz de cadena (``coalesce(parent_id, id)``)
para que dejen de salir como ceros. **No se hace, y es deliberado.**

El caso que lo decide está en la base: el usuario 7650 acusó el documento 51
—``046`` v2.0— el 2019-12-06. La versión en vigor de esa cadena es la 131, v3.0,
aprobada el 2022-02-01. Contar aquel acuse como acuse de la v3.0 imprimiría
"acusó recibo del documento en vigor el 06/12/2019", tres años antes de que esa
versión existiera. Eso no es recuperar evidencia: es fabricarla, y justo del
tipo que la cláusula 7.5.3 existe para impedir —dar por recibida la versión
vigente por quien solo recibió una superada—.

Lo que sí se hace es no esconderlos. La columna **"Acuses en Versiones
Superadas"** cuenta, por persona, las cadenas donde acusó una versión anterior y
**no** la vigente, y en el formato completo la celda de fecha lo dice fila por
fila (``_NO_ACK_PRIOR``). Así el cero de la columna de acusados es verdad —no
acusó *esta* versión— y el auditor ve que hubo un acuse previo sin que el papel
afirme que cubre el documento en vigor. Los rótulos llevan "(versión vigente)"
porque la exportación a Excel es ``XLSX.utils.table_to_book``, que copia **solo
el ``<table>``**: en el .xlsx que se lleva el auditor los encabezados de columna
son el único sitio donde cabe el alcance. En la hoja impresa va además como
línea de cabecera (``scope_note``).

Qué mide ``usuarios_documentos``: difusión, no autoría
---------------------------------------------------------

Hasta agosto de 2026 este reporte contaba los documentos de los que el usuario
era **autor** (``author_id``). Eso no lo pide ninguna cláusula de la norma y en
la base real salía casi en blanco: 202 documentos, 62 con autor y **3 autores
distintos** en diez años de SGC. Mientras tanto, las dos tablas que sí guardan
la evidencia que ISO 9001:2015 §7.5.3 obliga a controlar —la **distribución** de
la información documentada— no tenían ninguna pantalla:
``adhoc_document_visibility`` (9 390 filas, 55 usuarios, 198 documentos) y
``adhoc_document_acknowledgements`` (987 acuses con fecha real, del 2019-11-15 al
2025-02-12). El propio proveedor legacy llamaba ``UsuariosxDocumento`` a la vista
de la primera: es el dato que el título del reporte siempre prometió.

Hoy la colección sale de la lista de difusión y se cruza con los acuses por
``(document_id, user_id)``: cuántos documentos se le difundieron a cada persona,
cuántos acusó y qué porcentaje representa. La autoría sigue a la vista donde
significa algo —la ficha del documento y la lista—, no en un reporte imprimible.

**El reporte no lista a quien puede entrar hoy, lista a quien se le difundió.**
Son conjuntos distintos: de los 55 usuarios con difusión solo 25 conservan el
acceso, y los otros 30 salen igual con la columna "Acceso" en ``Sin acceso``. La
difusión de 2019-2025 se hizo a esas personas y esconderlas falsearía la
evidencia. Por eso es el único reporte que **no** parte de ``_fetch_users``.

Y una frontera que no se cruza: ``adhoc_document_visibility`` alimenta este
reporte y **nada más**. No decide qué documentos ve cada usuario en la lista de
consulta —la app tiene permisos planos por decisión explícita (gotcha 2 del
CLAUDE.md del app) y usarla como scope por fila sería cambiar el modelo de
autorización, no corregir un dato huérfano—.

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

#: Celdas del reporte de difusión. Son TEXTO dentro del ``<td>`` a propósito: la
#: exportación es ``XLSX.utils.table_to_book``, que lee el ``<table>`` del DOM tal
#: cual, así que una marca hecha con una clase de CSS, un icono o un color se
#: quedaría en la pantalla y no llegaría al .xlsx, que es el archivo que el
#: auditor se lleva.
_NO_ACK: Final[str] = "Sin acuse"
#: La persona acusó otra versión de ESTA cadena, pero no la que está en vigor.
#: Es su propia celda y no un ``_NO_ACK`` a secas porque son dos hechos
#: distintos —"nunca acusó nada de este documento" y "acusó, pero la versión
#: que acusó ya no es la controlada"— y solo el segundo tiene algo que
#: perseguir: pedirle el acuse de la versión nueva.
_NO_ACK_PRIOR: Final[str] = "Sin acuse (acusó una versión anterior)"
_ACCESS_YES: Final[str] = "Con acceso"
_ACCESS_NO: Final[str] = "Sin acceso"
_NO_DOCS: Final[str] = "Sin documentos difundidos"

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
        "preview": "users",
        "icon": "fa-solid fa-layer-group",
        "icon_overlay": "fa-solid fa-users",
    },
    "usuarios_tareas": {
        "title": "Reporte de Usuarios y Tareas",
        "label": "Usuarios y Tareas",
        "sheet": "Tareas",
        "file_prefix": "Reporte_Usuarios_Tareas",
        "subject": "users",
        "preview": "users",
        "icon": "fa-solid fa-user-tie",
        "icon_overlay": "fa-solid fa-list-check",
    },
    # Difusión documental. El rótulo dice lo que la consulta hace: la colección
    # sale de `adhoc_document_visibility` cruzada con los acuses, no de
    # `author_id` (ver el encabezado del módulo). La CLAVE no se toca:
    # `usuarios_documentos` está en `utils.constants.REPORT_TYPES` y es la URL
    # `/adhoc/reportes/usuarios_documentos` que ya existe.
    "usuarios_documentos": {
        "title": "Reporte de Difusión Documental por Usuario",
        "label": "Difusión Documental",
        "sheet": "DifusionDocumental",
        "file_prefix": "Reporte_Difusion_Documental",
        "subject": "users",
        # La vista previa de ESTE reporte no es la de los otros dos de personas.
        # `subject` sigue diciendo "se filtra por persona" —de eso dependen el
        # panel del modal y el rótulo del filtro de la hoja impresa—, pero la
        # colección que hay que previsualizar es la de `_fetch_users_with_
        # visibility` (55), no la de `_fetch_users` (29). Con una sola clave para
        # las dos cosas, filtrar por alguien que SÍ sale en el reporte
        # previsualizaba "0 coincidencias".
        "preview": "users_diffusion",
        "scope_note": (
            "Alcance: solo la versión en vigor de cada documento. Un acuse "
            "sobre una versión superada no cuenta como acuse del documento "
            "vigente; se informa aparte, en la columna «Acuses en Versiones "
            "Superadas»."
        ),
        "icon": "fa-solid fa-users",
        "icon_overlay": "fa-solid fa-file-circle-check",
    },
    "documentos_usuarios": {
        "title": "Reporte de Documentos y Usuarios",
        "label": "Documentos y Usuarios",
        "sheet": "DocumentosUsuarios",
        "file_prefix": "Reporte_Documentos_Usuarios",
        "subject": "documents",
        "preview": "documents",
        "icon": "fa-solid fa-file-signature",
        "icon_overlay": "fa-solid fa-user-tag",
    },
    "documentos_notas": {
        "title": "Reporte de Documentos y Notas",
        "label": "Documentos y Notas",
        "sheet": "DocumentosNotas",
        "file_prefix": "Reporte_Documentos_Notas",
        "subject": "documents",
        "preview": "documents",
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

    #: Techo de **filas emitidas** en el formato completo. ``MAX_ROWS`` topa las
    #: entidades de ORIGEN, y desde que ``usuarios_documentos`` abre una fila por
    #: par (usuario, documento) esas dos cosas dejaron de ser la misma: con los
    #: datos reales son 55 usuarios —muy por debajo de 5 000— y **6 711 filas**,
    #: once veces el siguiente reporte más grande (``usuarios_tareas``, 607) y
    #: ~8,7 MB de HTML que además recorre ``XLSX.utils.table_to_book`` en el
    #: navegador. Sin este segundo techo el seguro no se activaría nunca: harían
    #: falta 5 000 personas con difusión, que a ~122 documentos por persona son
    #: ~600 000 filas emitidas ANTES de que ``MAX_ROWS`` mirase.
    #:
    #: El valor es holgado a propósito —~3× la salida real de hoy—: esto no es
    #: paginación, es el tope que impide que un reporte imprimible se convierta
    #: en un cuelgue del navegador. Un reporte de auditoría recortado es malo;
    #: uno que no se puede abrir, peor. Cuando corta, ``truncated`` se enciende y
    #: la página lo avisa.
    MAX_DETAIL_ROWS: int = 20000

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
            "max_detail_rows": ReportService.MAX_DETAIL_ROWS,
            # Alcance impreso en la cabecera de la hoja. Solo lo declara el
            # reporte que lo necesita; en los otros cuatro es None y el template
            # no pinta la línea.
            "scope_note": meta.get("scope_note"),
            "filters": filters,
        }

    @staticmethod
    def get_selection_data(db: Session) -> dict[str, Any]:
        """Contexto de ``/adhoc/reportes``: tarjetas, áreas y las **tres** vistas previas.

        Las del legacy eran dos (usuarios y documentos), repartidas entre dos
        modales distintos. Van juntas y sin ``<option>`` pre-renderizados: la
        página las emite dentro del bloque ``<script type="application/json">``
        y el JS las pinta escapando.

        La tercera, ``users_diffusion``, existe porque ``usuarios_documentos``
        dejó de partir de ``_fetch_users``. Una vista previa solo sirve si
        enseña **la misma colección que el reporte va a listar**: mientras
        ambas salían de ``_fetch_users`` bastaba una, pero hoy son 29 personas
        contra 55, con 30 que están en el reporte y no en la previa. Sin esta
        lista, escribir "Lizette" en el filtro decía "0 coincidencias" para
        alguien que en el reporte sale con 56 documentos difundidos, y quien usa
        la previa para comprobar si una persona tiene evidencia de difusión
        concluía que no la tiene y no llegaba a generar el reporte.

        Cuesta una consulta más y ninguna decisión nueva: es
        :meth:`_fetch_users_with_visibility` con los filtros vacíos, el mismo
        molde que las otras dos.
        """
        vacios = {"nombre": "", "apellidos": "", "area": ""}
        users, _u_trunc = ReportService._fetch_users(db, vacios)
        difusion, _f_trunc = ReportService._fetch_users_with_visibility(db, vacios)
        # Un solo golpe de áreas para las dos listas de personas: se solapan en
        # 25 de 59 ids y pedirlas dos veces sería repetir media consulta.
        areas_by_user = ReportService._areas_by_user(
            db, list({u.id for u in users} | {u.id for u in difusion})
        )
        documents, _d_trunc = ReportService._fetch_documents(db, vacios, with_flow=False)

        def _fila_persona(user) -> dict[str, Any]:
            return {
                "first_name": user.first_name or "",
                "last_name": f"{user.last_name or ''} {user.middle_name or ''}".strip(),
                "areas": _join_areas(areas_by_user.get(user.id)),
            }

        return {
            "reports": [
                {
                    "type": key,
                    "title": meta["title"],
                    "label": meta["label"],
                    "subject": meta["subject"],
                    "preview": meta["preview"],
                    "icon": meta["icon"],
                    "icon_overlay": meta["icon_overlay"],
                }
                for key, meta in REPORT_META.items()
            ],
            "formats": list(REPORT_FORMATS),
            "areas": ReportService.list_areas(db),
            "users": [_fila_persona(user) for user in users],
            "users_diffusion": [_fila_persona(user) for user in difusion],
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
    def _users_with_app_access(db: Session) -> set[int] | None:
        """Ids de quienes **pueden entrar** hoy a Calidad. Una vez por reporte.

        La regla no se reimplementa: es
        ``users_with_assignment_select(db, "adhoc")`` —las cuatro vías de
        ``require_app``: rol o permiso directo, rol o permiso heredado de un
        puesto vigente— con el mismo filtro ``is_active`` que le añaden
        ``api/tasks._app_user_ids`` y ``pages/_work_context.assignable_users``.
        **Tiene que ser el mismo conjunto que esos dos**: si el papel impreso
        marcara "sin acceso" a alguien a quien el desplegable de asignación sí
        ofrece, la evidencia y la pantalla que la corrige dirían cosas distintas.

        Cuesta **dos** consultas fijas (la fila de ``core_apps`` y el ``SELECT``
        de ids) y se resuelve una sola vez para todas las filas del reporte: no
        depende de cuántos usuarios traiga.

        Devuelve ``None`` si la app no está en ``core_apps``
        (``users_with_assignment_select`` resuelve esa fila y lanza 404 si
        falta). Sin conjunto no se afirma nada: la columna sale en ``N/A``, que
        es el equivalente al fail-closed de ``_fetch_users`` —allí no se lista a
        nadie; aquí no se acusa a nadie de haber perdido el acceso—.
        """
        from fastapi import HTTPException

        from itcj2.apps.adhoc.utils.constants import APP_KEY
        from itcj2.core.models.user import User
        from itcj2.core.services.authz_service import users_with_assignment_select

        try:
            rows = (
                db.query(User.id)
                .filter(
                    User.is_active.is_(True),
                    User.id.in_(users_with_assignment_select(db, APP_KEY)),
                )
                .all()
            )
        except HTTPException:
            logger.warning(
                "adhoc reports: no se pudo resolver el conjunto de usuarios con acceso"
            )
            return None
        return {row[0] for row in rows}

    @staticmethod
    def _fetch_users_with_visibility(
        db: Session, filters: dict[str, str]
    ) -> tuple[list, bool]:
        """Usuarios **a los que se les difundió algún documento**, filtrados en SQL.

        La colección de ``usuarios_documentos`` y lo único del módulo que no sale
        de ``_fetch_users``. La diferencia no es cosmética: sin filtros,
        ``_fetch_users`` devuelve 29 personas (activas y con acceso) de las que
        solo 25 tienen difusión, mientras que ``adhoc_document_visibility`` tiene
        55 usuarios. Intersecar habría borrado del papel a 30 personas a las que
        la organización sí difundió documentos entre 2019 y 2025, y con ellas
        buena parte de las 9 390 filas de evidencia.

        Por eso aquí **no** hay filtro de ``is_active`` ni de asignación a la app:
        quien ya no puede entrar sale igual, marcado en la columna "Acceso" con
        el conjunto de :meth:`_users_with_app_access`.

        Los filtros de la pantalla (nombre, apellidos, área) sí se aplican, con
        el mismo SQL que ``_fetch_users`` —incluida la subconsulta de área, que
        casa con *cualquiera* de las áreas del usuario y no con la primera—.
        """
        from itcj2.apps.adhoc.models import (
            AdhocArea,
            AdhocDocumentVisibility,
            adhoc_user_areas,
        )
        from itcj2.core.models.user import User

        con_difusion = select(AdhocDocumentVisibility.user_id).distinct()
        query = db.query(User).filter(User.id.in_(con_difusion))

        if filters["nombre"]:
            query = query.filter(User.first_name.ilike(f"%{filters['nombre']}%"))
        if filters["apellidos"]:
            query = query.filter(User.last_name.ilike(f"%{filters['apellidos']}%"))
        if filters["area"]:
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
        quinto, ``usuarios_documentos``, parte de la lista de difusión y va por
        ``_visibility_by_user``, que repite el mismo filtro. Son los **dos**
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
    def _visibility_by_user(db: Session, user_ids: Sequence[int]) -> dict[int, list]:
        """Documentos **vigentes** difundidos a cada usuario, en un solo golpe.

        Una consulta con ``IN`` sobre los ids ya conocidos, nunca una por
        usuario: con 55 usuarios y 9 390 pares, el N+1 que este módulo existe
        para no repetir son 55 consultas.

        Repite el filtro de control documental (``is_current=True``, el del
        encabezado del módulo) porque no pasa por ``_fetch_documents``, y aquí
        no es una precaución teórica: 2 679 filas de visibilidad apuntan a
        versiones superadas de 58 documentos. De esas, 2 433 son la misma persona
        sobre otra versión del mismo ``code`` —sin el filtro saldría con dos
        filas, dos versiones y dos acuses distintos, y el papel de la auditoría
        diría que hay dos documentos controlados donde hay uno—.

        Las otras **246 no se deduplican, se pierden**: la versión en vigor de
        esa cadena no está difundida a esa persona, así que el filtro le quita
        una fila sin ponerle otra. Se acepta porque es lo que el reporte
        promete —la difusión de lo que hoy está en vigor— y porque el acuse que
        colgara de ellas no desaparece del papel: lo recoge
        :meth:`_prior_ack_roots_by_user` en su propia columna.

        Orden por ``code``: es como se lee una lista de documentos controlados,
        y el orden de las filas de detalle no debe depender de cómo devuelva la
        BD la tabla de asociación.
        """
        from itcj2.apps.adhoc.models import AdhocDocument, AdhocDocumentVisibility

        if not user_ids:
            return {}

        out: dict[int, list] = {}
        rows = (
            db.query(AdhocDocumentVisibility.user_id, AdhocDocument)
            .join(
                AdhocDocument,
                AdhocDocument.id == AdhocDocumentVisibility.document_id,
            )
            .filter(
                AdhocDocumentVisibility.user_id.in_(user_ids),
                AdhocDocument.is_current.is_(True),
            )
            .order_by(AdhocDocument.code.asc(), AdhocDocument.id.asc())
            .all()
        )
        for user_id, doc in rows:
            out.setdefault(user_id, []).append(doc)
        return out

    @staticmethod
    def _acknowledged_at_by_pair(
        db: Session, user_ids: Sequence[int]
    ) -> dict[tuple[int, int], datetime]:
        """``(document_id, user_id) -> acknowledged_at``, en **una** consulta.

        El cruce de la evidencia. ``adhoc_document_acknowledgements`` tiene
        ``UNIQUE(document_id, user_id)``, así que el par es clave y el dict no
        pierde filas; y ``acknowledged_at`` es NOT NULL, así que lo que significa
        "no acusó" es la ausencia de clave, nunca un ``None``.

        No se filtra por documento: se piden los acuses de los usuarios del
        reporte y el cruce lo hace el diccionario contra lo que
        :meth:`_visibility_by_user` ya devolvió vigente. Meter aquí un segundo
        ``IN`` de ids de documento no ahorra nada y añade un sitio donde
        desincronizar el criterio de vigencia.
        """
        from itcj2.apps.adhoc.models import AdhocDocumentAcknowledgement as Ack

        if not user_ids:
            return {}

        rows = (
            db.query(Ack.document_id, Ack.user_id, Ack.acknowledged_at)
            .filter(Ack.user_id.in_(user_ids))
            .all()
        )
        return {(doc_id, uid): fecha for doc_id, uid, fecha in rows}

    @staticmethod
    def _prior_ack_roots_by_user(
        db: Session, user_ids: Sequence[int]
    ) -> dict[int, set[int]]:
        """``user_id -> {raíces de cadena}`` acusadas SOLO en una versión superada.

        Lo que el alcance "solo la versión en vigor" deja fuera, contado sin
        falsearlo. Una raíz entra aquí cuando la persona acusó **alguna** versión
        superada de esa cadena y **ninguna** vigente; si acusó las dos, el acuse
        bueno ya está en :meth:`_acknowledged_at_by_pair` y aquí no aparece —de
        los 84 acuses sobre versiones superadas, 51 son exactamente ese caso y
        contarlos otra vez inflaría la columna con evidencia duplicada—.

        Por qué NO se cuenta cruzando por raíz y ya: el encabezado del módulo lo
        argumenta con el caso del usuario 7650 (acusó ``046`` v2.0 en 2019; la
        vigente es la v3.0 de 2022). Aquí la unidad es la CADENA y no el
        documento a propósito: la pregunta que responde la columna es "¿de este
        documento hubo alguna vez un acuse suyo?", no "¿acusó esta versión?".

        Una consulta y el resto en Python: agrupar por raíz en SQL exigiría un
        ``NOT EXISTS`` correlacionado sobre la misma tabla, y las filas que se
        traen son las mismas que ya viajan para el cruce (987 en la base real).
        ``coalesce(parent_id, id)`` es clave de cadena válida porque
        ``parent_id`` apunta **siempre** a la raíz —nunca a un eslabón
        intermedio— y hay exactamente una fila ``is_current`` por cadena;
        ambas verificadas contra la base.
        """
        from itcj2.apps.adhoc.models import AdhocDocument
        from itcj2.apps.adhoc.models import AdhocDocumentAcknowledgement as Ack

        if not user_ids:
            return {}

        rows = (
            db.query(
                Ack.user_id,
                AdhocDocument.id,
                AdhocDocument.parent_id,
                AdhocDocument.is_current,
            )
            .join(AdhocDocument, AdhocDocument.id == Ack.document_id)
            .filter(Ack.user_id.in_(user_ids))
            .all()
        )

        vigentes: dict[int, set[int]] = {}
        superadas: dict[int, set[int]] = {}
        for uid, doc_id, parent_id, es_vigente in rows:
            raiz = parent_id or doc_id
            destino = vigentes if es_vigente else superadas
            destino.setdefault(uid, set()).add(raiz)

        out: dict[int, set[int]] = {}
        for uid, raices in superadas.items():
            solo_superadas = raices - vigentes.get(uid, set())
            if solo_superadas:
                out[uid] = solo_superadas
        return out


def _join_areas(names: Iterable[str] | None) -> str:
    """Todas las áreas del usuario, no solo la primera (bug del legacy)."""
    names = list(names or [])
    return ", ".join(names) if names else _NO_AREA


def _access_label(con_acceso: set[int] | None, user_id: int) -> str:
    """Marca de "ya no puede entrar a la app", como TEXTO de la celda.

    La exportación es ``XLSX.utils.table_to_book``, que lee el ``<table>`` del
    DOM tal cual: una clase de CSS, un icono o un color se quedarían en la
    pantalla y el .xlsx —el archivo que el auditor se lleva— no diría nada.

    Y va en **columna propia**, no como sufijo del nombre, para que en Excel se
    pueda filtrar y ordenar por ella sin ensuciar la columna "Usuario", que es
    la que se cruza con cualquier otra lista de personal.
    """
    if con_acceso is None:
        return _NA
    return _ACCESS_YES if user_id in con_acceso else _ACCESS_NO


def _pct(part: int, total: int) -> int:
    """Porcentaje entero; ``0`` si no hay nada difundido (sin división por cero).

    Número, no la cadena ``"45%"``: la unidad ya está en el encabezado de la
    columna, y en la hoja de Excel un texto ordena ``"100%" < "45%"``, que es
    justo al revés de lo que se quiere mirar en un reporte de difusión.
    """
    if not total:
        return 0
    return round(part * 100 / total)


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
    """Difusión documental por usuario — la evidencia de ISO 9001:2015 §7.5.3.

    Lo que mide y por qué dejó de contar autorías está en el encabezado del
    módulo. Aquí lo relevante es la forma: **seis consultas fijas** —las dos de
    ``_users_with_app_access``, la de la colección, la de áreas, la de
    documentos difundidos y la de acuses— y son seis con un usuario y con
    cincuenta y cinco. Ninguna carga cuelga del bucle.

    El formato completo abre una fila por **par** (usuario, documento), no por
    usuario: es el nivel al que se pide la evidencia —"enséñame cuándo acusó
    esta persona este documento"—. Esas filas las topa
    :attr:`ReportService.MAX_DETAIL_ROWS`, no ``MAX_ROWS``: el segundo cuenta
    entidades de origen y aquí son 55 contra 6 711 filas emitidas, así que
    aplicado solo él el seguro no se activaría nunca (ver su comentario).

    Los rótulos de las dos columnas de conteo llevan "(versión vigente)" y no es
    verbosidad: la exportación a Excel copia **solo el ``<table>``**, así que en
    el .xlsx que se lleva el auditor el encabezado de columna es el único sitio
    donde cabe decir qué se contó.
    """
    users, truncated = ReportService._fetch_users_with_visibility(db, filters)
    user_ids = [u.id for u in users]
    areas_by_user = ReportService._areas_by_user(db, user_ids)
    docs_by_user = ReportService._visibility_by_user(db, user_ids)
    acuses = ReportService._acknowledged_at_by_pair(db, user_ids)
    acuses_previos = ReportService._prior_ack_roots_by_user(db, user_ids)
    con_acceso = ReportService._users_with_app_access(db)

    columns = [
        _col("user", "Usuario"),
        _col("areas", "Área"),
        _col("access", "Acceso", "center"),
        _col("assigned", "Documentos Asignados (versión vigente)", "center"),
        _col("acknowledged", "Documentos Acusados (versión vigente)", "center"),
        _col("coverage", "% de Difusión", "center"),
        # Va DESPUÉS del porcentaje: las tres de arriba son la medida y se leen
        # juntas; esta es la nota al pie que impide leer un 0 como "esta persona
        # nunca acusó nada". Sin ella, 6 personas con acuse real —fechado, entre
        # 2019 y 2021— salían con "Acusados: 0 · Difusión: 0 %" y nada que lo
        # matizara, mientras el modal de difusión del panel enseñaba ese mismo
        # acuse: dos superficies de la misma app contándose distinto.
        _col("prior_acks", "Acuses en Versiones Superadas", "center"),
    ]
    if detailed:
        columns += [
            _col("code", "Código"),
            _col("title", "Título"),
            _col("version", "Versión"),
            _col("doc_status", "Estado"),
            # La columna que un auditor pide primero: 987 acuses con fecha real
            # entre 2019 y 2025. Sin fecha, el acuse es una afirmación; con
            # fecha, es evidencia.
            _col("ack_date", "Fecha de Acuse"),
        ]

    rows = []
    for user in users:
        docs = docs_by_user.get(user.id, [])
        acusados = sum(1 for doc in docs if (doc.id, user.id) in acuses)
        previas = acuses_previos.get(user.id, frozenset())
        base = {
            "user": _full_name(user),
            "areas": _join_areas(areas_by_user.get(user.id)),
            "access": _access_label(con_acceso, user.id),
            "assigned": len(docs),
            "acknowledged": acusados,
            "coverage": _pct(acusados, len(docs)),
            "prior_acks": len(previas),
        }
        if not detailed:
            rows.append(base)
            continue
        if not docs:
            # Toda la difusión de esta persona apunta a versiones superadas: la
            # fila se queda (su nombre SÍ está en la lista de difusión) pero no
            # hay documento vigente que enseñar.
            rows.append({
                **base,
                "code": _NO_DOCS,
                "title": "", "version": "", "doc_status": "", "ack_date": "",
            })
            continue
        for doc in docs:
            fecha = acuses.get((doc.id, user.id))
            if fecha:
                ack_date = _fmt_date(fecha)
            elif (doc.parent_id or doc.id) in previas:
                # No acusó ESTA versión, pero sí una anterior de la misma
                # cadena. Decirlo aquí es lo que separa "no consta nada" de "hay
                # que pedirle el acuse de la versión nueva".
                ack_date = _NO_ACK_PRIOR
            else:
                ack_date = _NO_ACK
            rows.append({
                **base,
                "code": doc.code or _NA,
                "title": doc.title or "",
                "version": doc.version or _NA,
                "doc_status": doc.status or _NA,
                "ack_date": ack_date,
            })
            # El techo se comprueba DENTRO del bucle de documentos, no solo
            # entre personas: una sola persona con difusión desbocada bastaría
            # para desbordar el navegador si solo se mirara al cambiar de fila.
            if len(rows) >= ReportService.MAX_DETAIL_ROWS:
                return columns, rows, len(users), True

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
