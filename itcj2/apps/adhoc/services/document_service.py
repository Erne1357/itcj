"""CRUD de documentos del SGC (Adhoc / Calidad).

Sustituye a ``api_docs.save_documents`` y a los trozos de ``api_tasks`` que
tocaban documentos, arreglando lo que el análisis (``docs/adhoc/analysis/
src_api.md``) documentó:

===========================================  ==================================
Legacy                                       Aquí
===========================================  ==================================
``except Exception`` + ``logger.exception``  Las excepciones **suben**. Una FK
y ``redirect(...)`` "exitoso": el usuario    inventada o un archivo inválido son
veía la pantalla de éxito con cero filas     un 400 con mensaje, y **no se
insertadas.                                  persiste nada** (las FK se validan
                                             antes de tocar la sesión).
Archivos por ``secure_filename`` + ``join``  ``upload_service`` (whitelist,
sin whitelist ni límite, sobrescribiendo.    límite, sufijo anti-colisión,
                                             ``safe_join``).
Borrar un documento dejaba el archivo        ``delete`` limpia el adjunto.
huérfano en disco.
``"El documento no tiene archivo adjunto."`` ``LookupError`` → 404 JSON con el
en **texto plano** con 404.                  sobre estándar.
===========================================  ==================================

**Contrato de errores** (lo traduce la capa API a ``HTTPException``):

* ``LookupError``   → 404 — la fila no existe.
* :class:`AdhocConflict` → 409 — existe pero su estado impide la operación.
* ``ValueError``    → 400 — la entrada es inválida (FK inexistente, título
  vacío, archivo rechazado…).

Ningún service lanza ``HTTPException``: así se prueban sin cliente HTTP.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from itcj2.apps.adhoc.models import (
    AdhocArea,
    AdhocDocument,
    AdhocDocumentCategory,
    AdhocDocumentClassification,
    AdhocProcess,
)
from itcj2.apps.adhoc.schemas.documents import (
    DocumentCreate,
    DocumentFilters,
    DocumentUpdate,
)
from itcj2.apps.adhoc.services import upload_service
from itcj2.apps.adhoc.utils.constants import (
    DOCUMENT_STATUS_DEFAULT, DOCUMENT_STATUSES_VIA_PATCH,
)
from itcj2.models.base import paginate

logger = logging.getLogger(__name__)

__all__ = ["AdhocConflict", "AdhocDocumentService"]

#: Kind de ``upload_service`` al que pertenecen los adjuntos de documento.
UPLOAD_KIND = "documents"


class AdhocConflict(RuntimeError):
    """409 — la fila existe pero su estado actual impide la operación.

    Vive aquí (y no en cada service) para que ``document_flow_service`` y la
    capa API compartan una sola clase; ``ValueError`` no sirve porque un
    conflicto de estado **no** es un error de entrada del cliente.
    """


#: Campo del payload → modelo al que apunta la FK. Se valida en lote: el legacy
#: dejaba que Postgres lanzara ``IntegrityError`` y lo convertía en un 500.
_FK_MODELS = {
    "category_id": AdhocDocumentCategory,
    "area_id": AdhocArea,
    "process_id": AdhocProcess,
    "classification_id": AdhocDocumentClassification,
}

_FK_LABELS = {
    "category_id": "categoría",
    "area_id": "área",
    "process_id": "proceso",
    "classification_id": "clasificación",
}

_EAGER = (
    joinedload(AdhocDocument.category),
    joinedload(AdhocDocument.area),
    joinedload(AdhocDocument.process),
    joinedload(AdhocDocument.classification),
    joinedload(AdhocDocument.author),
)


def _validate_fks(db: Session, payloads: Sequence[dict]) -> None:
    """Una query por tipo de FK para todo el lote (no una por documento)."""
    for field, model in _FK_MODELS.items():
        wanted = {p.get(field) for p in payloads if p.get(field)}
        if not wanted:
            continue
        found = {
            row[0]
            for row in db.query(model.id).filter(model.id.in_(wanted)).all()
        }
        missing = sorted(wanted - found)
        if missing:
            raise ValueError(
                f"No existe la {_FK_LABELS[field]} con id "
                f"{', '.join(str(m) for m in missing)}"
            )


def _has_filename(upload: Any) -> bool:
    """Un ``<input type=file>`` sin elegir manda una parte con filename vacío."""
    return bool(upload is not None and (getattr(upload, "filename", "") or "").strip())


class AdhocDocumentService:
    """Todo el CRUD de ``adhoc_documents``. Métodos estáticos, commit adentro."""

    # ------------------------------------------------------------------
    # Lectura
    # ------------------------------------------------------------------
    @staticmethod
    def get(db: Session, document_id: int) -> AdhocDocument:
        """Documento por PK con sus catálogos ya cargados. 404 si no existe."""
        doc = (
            db.query(AdhocDocument)
            .options(*_EAGER, joinedload(AdhocDocument.flow),
                     joinedload(AdhocDocument.current_step))
            .filter(AdhocDocument.id == document_id)
            .first()
        )
        if doc is None:
            raise LookupError("Documento no encontrado")
        return doc

    @staticmethod
    def list_documents(
        db: Session,
        filters: DocumentFilters,
        *,
        page: int = 1,
        per_page: int = 20,
    ):
        """Listado paginado con eager loading de los 5 catálogos.

        El legacy renderizaba la tabla desde la página y disparaba un N+1 por
        fila (categoría, área, proceso, clasificación y autor).
        """
        q = db.query(AdhocDocument).options(*_EAGER)

        if filters.status:
            q = q.filter(AdhocDocument.status == filters.status)
        for field in ("category_id", "area_id", "process_id", "classification_id",
                      "flow_id", "author_id"):
            value = getattr(filters, field)
            if value:
                q = q.filter(getattr(AdhocDocument, field) == value)
        if filters.q:
            like = f"%{filters.q}%"
            q = q.filter(or_(
                AdhocDocument.code.ilike(like),
                AdhocDocument.title.ilike(like),
            ))

        q = q.order_by(AdhocDocument.id.desc())
        return paginate(q, page, per_page)

    # ------------------------------------------------------------------
    # Escritura
    # ------------------------------------------------------------------
    @staticmethod
    def bulk_create(
        db: Session,
        items: Sequence[DocumentCreate],
        author_id: Optional[int],
        uploads: Optional[Sequence[Any]] = None,
    ) -> list[AdhocDocument]:
        """Alta masiva con un archivo opcional por fila (índice paralelo).

        ``uploads[i]`` corresponde a ``items[i]``; una entrada sin ``filename``
        (o ausente) significa "esta fila no trae archivo".

        Si algo falla a mitad se hace ``rollback`` **y** se borran los archivos
        ya escritos: el legacy dejaba basura en disco y filas a medias.
        """
        if not items:
            raise ValueError("No se recibió ningún documento para guardar")

        payloads = [i.model_dump() for i in items]
        _validate_fks(db, payloads)

        author_id = AdhocDocumentService._resolve_author(db, author_id)

        saved_paths: list[str] = []
        created: list[AdhocDocument] = []
        try:
            for index, data in enumerate(payloads):
                doc = AdhocDocument(
                    code=data.get("code"),
                    title=data["title"],
                    version=data.get("version") or "1.0",
                    notes=data.get("notes"),
                    status=DOCUMENT_STATUS_DEFAULT,
                    category_id=data.get("category_id"),
                    area_id=data.get("area_id"),
                    process_id=data.get("process_id"),
                    classification_id=data.get("classification_id"),
                    author_id=author_id,
                )
                db.add(doc)
                db.flush()          # necesitamos el id para la ruta del adjunto

                upload = uploads[index] if uploads and index < len(uploads) else None
                if _has_filename(upload):
                    stored = upload_service.save_upload(UPLOAD_KIND, doc.id, upload)
                    doc.file_url = stored["file_path"]
                    saved_paths.append(stored["file_path"])

                created.append(doc)

            db.commit()
        except Exception:
            db.rollback()
            for path in saved_paths:
                upload_service.delete_file(UPLOAD_KIND, path)
            raise

        for doc in created:
            db.refresh(doc)
        return created

    @staticmethod
    def update(
        db: Session,
        document_id: int,
        data: DocumentUpdate,
        *,
        upload: Any = None,
    ) -> AdhocDocument:
        """``PATCH``: aplica solo los campos presentes en el payload."""
        doc = db.get(AdhocDocument, document_id)
        if doc is None:
            raise LookupError("Documento no encontrado")

        changes = data.model_dump(exclude_unset=True)

        if "title" in changes:
            if not (changes["title"] or "").strip():
                raise ValueError("El título del documento no puede quedar vacío")
            changes["title"] = changes["title"].strip()
        if "version" in changes and not changes.get("version"):
            changes.pop("version")      # NOT NULL: un vacío no lo borra
        if "status" in changes:
            # `status` es NOT NULL con CheckConstraint: un '' escribiría NULL y
            # saldría como 500 sin traducir.
            if not (changes.get("status") or "").strip():
                changes.pop("status")
            elif changes["status"] not in DOCUMENT_STATUSES_VIA_PATCH:
                # 'En Revisión', 'Aprobado' y 'Rechazado' los produce el motor de
                # flujo. Dejarlos aquí permitiría marcar aprobado un documento
                # cuyo flujo sigue en el primer paso, con `adhoc_task_approvals`
                # vacío y `current_step_id` colgando de un paso ya superado.
                raise ValueError(
                    f"El estado '{changes['status']}' lo asigna el flujo de aprobación, "
                    f"no se puede escribir directamente. Permitidos aquí: "
                    f"{', '.join(DOCUMENT_STATUSES_VIA_PATCH)}"
                )

        _validate_fks(db, [changes])

        old_file = doc.file_url
        new_path: Optional[str] = None
        try:
            for field, value in changes.items():
                setattr(doc, field, value)

            if _has_filename(upload):
                stored = upload_service.save_upload(UPLOAD_KIND, doc.id, upload)
                new_path = stored["file_path"]
                doc.file_url = new_path

            db.commit()
        except Exception:
            db.rollback()
            if new_path:
                upload_service.delete_file(UPLOAD_KIND, new_path)
            raise

        if new_path and old_file and old_file != new_path:
            upload_service.delete_file(UPLOAD_KIND, old_file)

        db.refresh(doc)
        return doc

    @staticmethod
    def delete(db: Session, document_id: int) -> None:
        """Borra el documento y **su archivo**.

        Las tareas del documento caen por ``ondelete CASCADE``; el adjunto no
        tiene quien lo borre, así que lo hace este método (bug #18 en su versión
        documental).
        """
        doc = db.get(AdhocDocument, document_id)
        if doc is None:
            raise LookupError("Documento no encontrado")

        file_url = doc.file_url
        db.delete(doc)
        db.commit()

        if file_url:
            upload_service.delete_file(UPLOAD_KIND, file_url)

    # ------------------------------------------------------------------
    # Descarga
    # ------------------------------------------------------------------
    @staticmethod
    def resolve_download(db: Session, document_id: int) -> tuple[Path, str]:
        """``(ruta_absoluta, nombre_de_descarga)`` del adjunto del documento.

        404 tanto si el documento no existe como si no tiene archivo, y
        ``ValueError`` si la ruta almacenada es inválida (``open_stored`` la
        trata como dato no confiable).
        """
        doc = db.get(AdhocDocument, document_id)
        if doc is None:
            raise LookupError("Documento no encontrado")
        if not doc.file_url:
            raise LookupError("El documento no tiene archivo adjunto")

        try:
            path = upload_service.open_stored(UPLOAD_KIND, doc.file_url)
        except ValueError as exc:
            # "El archivo no existe" es un 404, no un 400.
            if "no existe" in str(exc).lower():
                raise LookupError("El archivo del documento no está disponible") from exc
            raise
        return path, path.name

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_author(db: Session, author_id: Optional[int]) -> Optional[int]:
        """Confirma que el autor exista en ``core_users``; si no, lo deja nulo.

        Comportamiento heredado del legacy (que logueaba "se guardará como
        Sistema"): un JWT de un usuario borrado no debe tumbar el alta.
        """
        if not author_id:
            return None
        from itcj2.core.models.user import User

        if db.get(User, int(author_id)) is None:
            logger.warning(
                "[adhoc] author_id=%s no existe en core_users; se guarda sin autor",
                author_id,
            )
            return None
        return int(author_id)
