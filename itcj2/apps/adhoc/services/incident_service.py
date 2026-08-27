"""Servicio de incidencias del SGC (``adhoc_incidents``).

Sustituye a ``routes/api/api_incidents.py`` del legacy, que era un CRUD sin
capa de servicio: la lógica vivía dentro de tres vistas Flask que leían
``request.form`` directamente, envueltas en un ``except Exception`` que
imprimía con ``print()`` y devolvía **siempre** un redirect "exitoso" — un
``get_or_404`` fallido, un ``IntegrityError`` de FK y una fecha mal formada
producían exactamente la misma respuesta que un alta correcta.

Qué cambia aquí, punto por punto:

* **La transacción es del service.** ``bulk_create``/``update``/``delete``
  commitean; los endpoints no tocan la sesión.
* **Las FKs se validan antes de insertar** (:meth:`IncidentService._check_refs`),
  en una query por catálogo, no una por fila. El legacy dejaba que Postgres
  reventara a mitad del lote y perdía **todas** las incidencias del envío por
  culpa de una sola categoría inexistente.
* **404 es 404.** ``update`` y ``delete`` devuelven ``None``/``False`` cuando la
  incidencia no existe, y el endpoint traduce eso a ``HTTPException(404)``.
  ``ValueError`` queda reservado para entrada inválida (400).
* **Sin N+1.** El listado hace ``joinedload`` de los tres catálogos y del
  responsable (todos ``many-to-one``, así que no multiplican filas ni falsean
  el ``count()``), y el conteo de tareas sale de **una** query agrupada
  (:meth:`IncidentService.task_counts`).
* **Borrar cascadea.** ``adhoc_tasks.incident_id`` es ``ON DELETE CASCADE`` en
  la BD y ``AdhocIncident`` no declara relationship inverso, así que
  ``db.delete()`` emite un DELETE pelado y Postgres arrastra tareas,
  asignados, comentarios y aprobaciones. El legacy dejaba huérfanas las tareas
  (o reventaba con ``IntegrityError``, tragado).

Vocabularios: ``status ∈ {No Iniciada, Iniciada, Cerrada}`` y
``priority ∈ {Baja, Media, Alta, Urgente}`` los garantizan los schemas
Pydantic (``schemas/incidents.py``) y, como red, los ``CheckConstraint`` de la
tabla. El workflow de tareas escribe ``'Cerrada'`` aquí — nunca
``'Completado'``, que es el vocabulario de los eventos de programa.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from itcj2.models.base import Pagination, paginate

logger = logging.getLogger(__name__)

__all__ = [
    "IncidentService", "ORDERABLE_COLUMNS", "UPLOAD_KIND",
    "IncidentNotFound", "IncidentFileNotFound",
]

#: Columnas por las que se puede ordenar el listado. Whitelist explícita: el
#: valor llega de un query param y se resuelve con ``getattr`` sobre el modelo.
ORDERABLE_COLUMNS: frozenset[str] = frozenset({
    "id", "folio", "title", "status", "priority",
    "start_date", "commitment_date", "real_date",
    "created_at", "updated_at",
})

#: ``campo del payload`` -> ``(modelo referenciado, etiqueta legible)``.
_FK_LABELS: dict[str, str] = {
    "category_id": "categoría de incidencia",
    "area_id": "área",
    "process_id": "proceso",
    "responsible_id": "usuario responsable",
}

#: Almacén de ``upload_service`` para los adjuntos de incidencia. Espejo de
#: ``program_event_service.UPLOAD_KIND``.
UPLOAD_KIND = "incidents"


class IncidentNotFound(LookupError):
    """La incidencia no existe.

    Los métodos de adjuntos (``list_files``/``add_files``) la lanzan para
    poder distinguir "incidencia inexistente" de "archivo inexistente"
    (:class:`IncidentFileNotFound`). El CRUD base de arriba (``get``/
    ``update``/``delete``) no la usa a propósito: ya tiene su propio contrato
    probado (``None``/``False``) y cambiarlo aquí rompería esos tests sin
    necesidad.
    """


class IncidentFileNotFound(LookupError):
    """El adjunto de la incidencia no existe. El endpoint lo traduce a 404."""


class IncidentService:
    """CRUD de incidencias. Todos los métodos son ``@staticmethod``."""

    # ----------------------------------------------------------------------
    # Lectura
    # ----------------------------------------------------------------------

    @staticmethod
    def list(
        db: Session,
        *,
        page: int = 1,
        per_page: int = 20,
        q: Optional[str] = None,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        category_id: Optional[int] = None,
        area_id: Optional[int] = None,
        process_id: Optional[int] = None,
        responsible_id: Optional[int] = None,
        start_from: Optional[date] = None,
        start_to: Optional[date] = None,
        commitment_from: Optional[date] = None,
        commitment_to: Optional[date] = None,
        order_by: str = "id",
        order_dir: str = "desc",
    ) -> Pagination:
        """Listado filtrado y paginado.

        ``q`` busca en ``folio``, ``title`` y ``description`` (``ILIKE``).
        Devuelve el ``Pagination`` de ``itcj2.models.base``: ``.items`` trae las
        incidencias de la página con catálogos y responsable ya cargados.

        El orden por defecto es DESCENDENTE, igual que documentos
        (``document_service.list_documents``) y eventos de programa
        (``program_event_service``). Con ``asc`` la incidencia recién creada
        aterrizaba en la última página: con las 276 del histórico del SGC eso
        significa que el usuario la da de alta y desaparece de su vista.

        Lanza ``ValueError`` si ``order_by`` no está en
        :data:`ORDERABLE_COLUMNS` (el parámetro viene del cliente y termina en
        un ``getattr`` sobre el modelo).
        """
        from itcj2.apps.adhoc.models.incidents import AdhocIncident

        if order_by not in ORDERABLE_COLUMNS:
            raise ValueError(
                f"No se puede ordenar por '{order_by}'. "
                f"Válidas: {', '.join(sorted(ORDERABLE_COLUMNS))}"
            )
        if order_dir not in ("asc", "desc"):
            raise ValueError("La dirección de orden debe ser 'asc' o 'desc'")

        query = db.query(AdhocIncident).options(
            joinedload(AdhocIncident.category),
            joinedload(AdhocIncident.area),
            joinedload(AdhocIncident.process),
            joinedload(AdhocIncident.responsible),
        )

        if q:
            patron = f"%{q.strip()}%"
            query = query.filter(
                or_(
                    AdhocIncident.folio.ilike(patron),
                    AdhocIncident.title.ilike(patron),
                    AdhocIncident.description.ilike(patron),
                )
            )
        if status:
            query = query.filter(AdhocIncident.status == status)
        if priority:
            query = query.filter(AdhocIncident.priority == priority)
        if category_id is not None:
            query = query.filter(AdhocIncident.category_id == category_id)
        if area_id is not None:
            query = query.filter(AdhocIncident.area_id == area_id)
        if process_id is not None:
            query = query.filter(AdhocIncident.process_id == process_id)
        if responsible_id is not None:
            query = query.filter(AdhocIncident.responsible_id == responsible_id)
        if start_from is not None:
            query = query.filter(AdhocIncident.start_date >= start_from)
        if start_to is not None:
            query = query.filter(AdhocIncident.start_date <= start_to)
        if commitment_from is not None:
            query = query.filter(AdhocIncident.commitment_date >= commitment_from)
        if commitment_to is not None:
            query = query.filter(AdhocIncident.commitment_date <= commitment_to)

        columna = getattr(AdhocIncident, order_by)
        query = query.order_by(columna.desc() if order_dir == "desc" else columna.asc())
        # Desempate estable: sin esto dos filas con el mismo `status` pueden
        # saltar de página entre peticiones.
        if order_by != "id":
            query = query.order_by(AdhocIncident.id.asc())

        return paginate(query, page=page, per_page=per_page)

    @staticmethod
    def get(db: Session, incident_id: int):
        """Una incidencia por PK, o ``None``."""
        from itcj2.apps.adhoc.models.incidents import AdhocIncident

        return db.get(AdhocIncident, incident_id)

    @staticmethod
    def task_counts(db: Session, incident_ids: Iterable[int]) -> dict[int, int]:
        """``{incident_id: nº de tareas}`` en UNA query agrupada.

        Las incidencias sin tareas simplemente no aparecen en el dict (el
        serializador ya usa ``0`` por defecto).
        """
        from sqlalchemy import func

        from itcj2.apps.adhoc.models.tasks import AdhocTask

        ids = [int(i) for i in incident_ids or []]
        if not ids:
            return {}

        filas = (
            db.query(AdhocTask.incident_id, func.count(AdhocTask.id))
            .filter(AdhocTask.incident_id.in_(ids))
            .group_by(AdhocTask.incident_id)
            .all()
        )
        return {incident_id: total for incident_id, total in filas}

    # ----------------------------------------------------------------------
    # Escritura
    # ----------------------------------------------------------------------

    @staticmethod
    def bulk_create(db: Session, items: Sequence[Any]) -> list:
        """Alta masiva. ``items`` es una lista de ``IncidentCreate``.

        Valida **todas** las FKs de **todo** el lote antes de insertar nada: o
        entran todas o no entra ninguna, y el motivo es un mensaje legible en
        vez de un ``IntegrityError``.
        """
        from itcj2.apps.adhoc.models.incidents import AdhocIncident

        if not items:
            raise ValueError("No se recibió ninguna incidencia")

        filas = [item.model_dump() for item in items]
        IncidentService._check_refs(db, filas)

        creadas = [AdhocIncident(**fila) for fila in filas]
        db.add_all(creadas)
        db.commit()
        for incidencia in creadas:
            db.refresh(incidencia)

        logger.info("[adhoc] %d incidencia(s) creada(s)", len(creadas))
        return creadas

    @staticmethod
    def update(db: Session, incident_id: int, data: Any):
        """PATCH parcial. Devuelve la incidencia, o ``None`` si no existe.

        Solo se aplican los campos presentes en el cuerpo
        (``model_dump(exclude_unset=True)``): un campo ausente conserva su
        valor, un ``null`` explícito limpia la columna. ``priority`` y
        ``status`` nunca pueden quedar en ``None`` — el schema los resuelve al
        default antes de llegar aquí.
        """
        from itcj2.apps.adhoc.models.incidents import AdhocIncident

        incidencia = db.get(AdhocIncident, incident_id)
        if incidencia is None:
            return None

        cambios = data.model_dump(exclude_unset=True)
        if not cambios:
            return incidencia

        # 🔧 D2: `title` es NOT NULL pero, a diferencia de `status`/`priority`,
        # no tiene un default razonable al que resolverse — un `""` que el
        # schema ya coaccionó a `None` (`AdhocSchema`/`empty_to_none`) se
        # rechaza aquí en vez de llegar como NULL a Postgres (IntegrityError
        # sin traducir -> 500).
        if "title" in cambios and not (cambios["title"] or "").strip():
            raise ValueError("El título no puede estar vacío")

        IncidentService._check_refs(db, [cambios])

        for campo, valor in cambios.items():
            setattr(incidencia, campo, valor)

        db.commit()
        db.refresh(incidencia)
        return incidencia

    @staticmethod
    def delete(db: Session, incident_id: int) -> bool:
        """Borra la incidencia. ``False`` si no existía.

        Las tareas hijas (y con ellas sus asignados, comentarios y
        aprobaciones) las arrastra el ``ON DELETE CASCADE`` de Postgres.
        """
        from itcj2.apps.adhoc.models.incidents import AdhocIncident

        incidencia = db.get(AdhocIncident, incident_id)
        if incidencia is None:
            return False

        db.delete(incidencia)
        db.commit()
        logger.info("[adhoc] Incidencia %s eliminada", incident_id)
        return True

    # ----------------------------------------------------------------------
    # Adjuntos
    # ----------------------------------------------------------------------
    #
    # Espejo literal de ``program_event_service.{list_files, add_files,
    # get_file, open_file, delete_file}``. Única diferencia real: aquí
    # ``AdhocIncidentFile.file_path`` es NULLABLE (351 adjuntos migrados del
    # SGC legacy, 51 de ellos sin binario en el servidor del proveedor), así
    # que ``open_file`` puede fallar con :class:`IncidentFileNotFound` por un
    # registro perfectamente válido, no solo por un archivo borrado a mano.

    @staticmethod
    def list_files(db: Session, incident_id: int) -> list:
        """Adjuntos de una incidencia, del más reciente al más antiguo.

        Incluye los registros sin binario (``file_path IS NULL``): ocultarlos
        perdería el rastro de qué se adjuntó y quién. El endpoint los
        serializa con ``is_available: false`` en vez de descartarlos.
        """
        from itcj2.apps.adhoc.models.incidents import AdhocIncident, AdhocIncidentFile

        if db.get(AdhocIncident, incident_id) is None:
            raise IncidentNotFound(f"La incidencia {incident_id} no existe")

        return (
            db.query(AdhocIncidentFile)
            .filter(AdhocIncidentFile.incident_id == incident_id)
            .order_by(AdhocIncidentFile.id.desc())
            .all()
        )

    @staticmethod
    def add_files(
        db: Session,
        incident_id: int,
        uploads: Sequence[Any],
        *,
        uploaded_by_id: Optional[int] = None,
    ) -> list:
        """Adjunta uno o más archivos a una incidencia existente.

        Raises:
            IncidentNotFound: la incidencia no existe.
            ValueError: no venía ningún archivo, o alguno es inválido
                (extensión fuera de whitelist, tamaño, nombre con traversal).
                En ese caso no queda ninguno: se borra del disco lo ya escrito
                y se hace rollback.
        """
        from itcj2.apps.adhoc.models.incidents import AdhocIncident, AdhocIncidentFile
        from itcj2.apps.adhoc.services import upload_service

        if db.get(AdhocIncident, incident_id) is None:
            raise IncidentNotFound(f"La incidencia {incident_id} no existe")

        usable = [u for u in (uploads or []) if getattr(u, "filename", None)]
        if not usable:
            raise ValueError("No se recibió ningún archivo")

        rows: list = []
        written: list[str] = []
        try:
            for upload in usable:
                meta = upload_service.save_upload(UPLOAD_KIND, incident_id, upload)
                written.append(meta["file_path"])
                row = AdhocIncidentFile(
                    incident_id=incident_id,
                    file_path=meta["file_path"],
                    original_name=meta["original_name"],
                    mime_type=meta["mime_type"],
                    size_bytes=meta["size_bytes"],
                    uploaded_by_id=uploaded_by_id,
                )
                db.add(row)
                rows.append(row)
            db.commit()
        except Exception:
            db.rollback()
            for relative in written:
                upload_service.delete_file(UPLOAD_KIND, relative)
            raise

        for row in rows:
            db.refresh(row)
        logger.info(
            "[adhoc] %d adjunto(s) agregado(s) a la incidencia %s", len(rows), incident_id
        )
        return rows

    @staticmethod
    def get_file(db: Session, file_id: int):
        """Adjunto por PK o :class:`IncidentFileNotFound`."""
        from itcj2.apps.adhoc.models.incidents import AdhocIncidentFile

        row = db.get(AdhocIncidentFile, file_id)
        if row is None:
            raise IncidentFileNotFound(f"El archivo {file_id} no existe")
        return row

    @staticmethod
    def open_file(file_row: Any) -> Path:
        """Ruta absoluta y verificada del adjunto, lista para ``FileResponse``.

        Pasa por ``safe_join``: el valor de ``file_path`` viene de la BD y se
        trata como dato no confiable.

        Raises:
            IncidentFileNotFound: el registro no tiene binario asociado
                (``file_path`` es ``NULL`` — adjunto migrado sin archivo en el
                servidor del proveedor) o el fichero ya no está en disco / la
                ruta se sale de la raíz de uploads.
        """
        from itcj2.apps.adhoc.services import upload_service

        if not file_row.file_path:
            raise IncidentFileNotFound(
                f"El archivo {file_row.id} no tiene un binario disponible "
                "(adjunto migrado sin archivo en el servidor de origen)"
            )
        try:
            return upload_service.open_stored(UPLOAD_KIND, file_row.file_path)
        except ValueError as exc:
            raise IncidentFileNotFound(str(exc)) from exc

    @staticmethod
    def delete_file(db: Session, file_id: int) -> None:
        """Borra el adjunto: primero la fila, después el fichero del disco
        (si lo hay — puede ser un registro migrado sin binario)."""
        from itcj2.apps.adhoc.services import upload_service

        row = IncidentService.get_file(db, file_id)
        relative = row.file_path
        db.delete(row)
        db.commit()
        if relative:
            upload_service.delete_file(UPLOAD_KIND, relative)
        logger.info("[adhoc] Adjunto de incidencia %s eliminado", file_id)

    # ----------------------------------------------------------------------
    # Internos
    # ----------------------------------------------------------------------

    @staticmethod
    def _check_refs(db: Session, rows: Sequence[dict]) -> None:
        """Verifica que las FKs de ``rows`` existan. Una query por catálogo.

        ``rows`` son dicts ya validados por Pydantic (``model_dump``), así que
        los valores son ``int`` o ``None``. Lanza ``ValueError`` con el id
        concreto que falta — el endpoint lo convierte en 400.
        """
        from itcj2.apps.adhoc.models.incidents import AdhocIncidentCategory
        from itcj2.apps.adhoc.models.structure import AdhocArea, AdhocProcess
        from itcj2.core.models.user import User

        modelos = {
            "category_id": AdhocIncidentCategory,
            "area_id": AdhocArea,
            "process_id": AdhocProcess,
            "responsible_id": User,
        }

        for campo, modelo in modelos.items():
            ids = {row.get(campo) for row in rows if row.get(campo) is not None}
            if not ids:
                continue
            encontrados = {
                fila[0] for fila in db.query(modelo.id).filter(modelo.id.in_(ids)).all()
            }
            faltantes = sorted(ids - encontrados)
            if faltantes:
                raise ValueError(
                    f"No existe {_FK_LABELS[campo]} con id "
                    + ", ".join(str(i) for i in faltantes)
                )
