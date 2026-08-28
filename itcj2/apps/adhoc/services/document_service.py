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
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import case, or_
from sqlalchemy.orm import Session, joinedload

from itcj2.apps.adhoc.models import (
    AdhocArea,
    AdhocDocument,
    AdhocDocumentCategory,
    AdhocDocumentClassification,
    AdhocProcess,
    AdhocTask,
)
from itcj2.apps.adhoc.schemas.documents import (
    DocumentCreate,
    DocumentFilters,
    DocumentUpdate,
)
from itcj2.apps.adhoc.services import upload_service
from itcj2.apps.adhoc.utils.constants import (
    DOCUMENT_EXPIRY_SOON_DAYS,
    DOCUMENT_STATUS_DEFAULT, DOCUMENT_STATUS_OBSOLETE,
    DOCUMENT_STATUSES_EDITABLE, DOCUMENT_STATUSES_FILE_REPLACEABLE,
    DOCUMENT_STATUSES_VIA_PATCH,
    TASK_STATUS_IN_REVIEW, TASK_STATUS_WAITING,
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


def _ha_circulado(doc: AdhocDocument) -> bool:
    """¿Este documento entró alguna vez a un flujo de aprobación?

    ``flow_id`` y ``current_step_id`` los escribe ``start_flow`` y **nadie los
    limpia después**: rechazar deja los dos puestos (``task_workflow_service``
    solo toca ``status``). Son, por tanto, la marca de que *ese* binario circuló
    y de que hay validadores que opinaron por escrito sobre él.

    El gate del archivo mira esto **además** del ``status`` porque el ``status``
    es un valor que el propio ``PATCH`` puede escribir, y eso abría la puerta
    de atrás: ``'Rechazado'`` está en :data:`DOCUMENT_STATUSES_EDITABLE` y
    ``'Borrador'`` en :data:`DOCUMENT_STATUSES_VIA_PATCH`, así que con un solo
    permiso (``adhoc.documents.api.update``) bastaban dos llamadas seguidas
    —``{"status": "Borrador"}`` y luego el archivo— para sustituir el adjunto
    que los validadores habían rechazado, dejando las filas de
    ``adhoc_task_approvals`` apuntando a un contenido que ya nadie puede ver.
    Un gate que se salta repitiéndolo no es un gate.
    """
    return doc.flow_id is not None or doc.current_step_id is not None


def _por_que_no_se_edita(status: str) -> str:
    """La causa real del 409, que no es la misma para todos los estados.

    El mensaje es lo único que la UI enseña (``documents-panel.js`` pinta el
    ``detail`` tal cual), así que no puede inventar historia. ``'Obsoleto'`` se
    alcanza también **sin flujo ninguno**: está en
    :data:`DOCUMENT_STATUSES_VIA_PATCH` justamente porque retirar un documento
    es una decisión legítima de Calidad, y hoy ya hay filas obsoletas con
    ``flow_id IS NULL``. Decirle a quien abre una de ellas que "ya pasó por el
    flujo de aprobación" es una explicación falsa: el motivo es que el estado es
    terminal.
    """
    if status == DOCUMENT_STATUS_OBSOLETE:
        return "es un estado terminal, un documento retirado no vuelve a edición"
    return (
        "lo escribe el flujo de aprobación, y un documento que está en él o que "
        "ya pasó por él no se reescribe"
    )


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
        today: Optional[date] = None,
    ):
        """Listado paginado con eager loading de los 5 catálogos.

        El legacy renderizaba la tabla desde la página y disparaba un N+1 por
        fila (categoría, área, proceso, clasificación y autor).

        **Por defecto solo devuelve la punta de cada cadena de versiones**
        (``filters.only_current``, que vale ``True`` si el query string no dice
        otra cosa). No es una preferencia estética: en la base hay 202
        documentos repartidos en 144 cadenas, y 54 códigos aparecen dos o tres
        veces. Sin este filtro, quien buscaba el procedimiento vigente recibía
        el vigente **y** sus dos versiones superadas, sin más señal para
        distinguirlos que un ``version`` que es ``String(10)``: el usuario se
        bajaba el PDF equivocado, que en un SGC ISO 9001 es exactamente el
        hallazgo de auditoría que el sistema existe para evitar. Las superadas
        se ven marcando "Ver versiones anteriores" (``only_current=false``) o,
        una cadena a la vez, en ``list_versions``.

        ``today`` es el mismo "hoy" que el endpoint le pasa a ``document_out``.
        Se recibe de fuera para que el ``WHERE`` de ``?expiring=vencidos`` y el
        ``expiry_state`` que se serializa salgan del **mismo** reloj: con dos
        ``date.today()`` independientes, una petición que cruce la medianoche
        puede devolver una fila que el filtro considera vencida y el badge pinta
        como "por vencer".
        """
        q = db.query(AdhocDocument).options(*_EAGER)

        if filters.status:
            q = q.filter(AdhocDocument.status == filters.status)
        if filters.only_current:
            q = q.filter(AdhocDocument.is_current.is_(True))
        if filters.expiring:
            # Tres cubos disjuntos y exhaustivos sobre `expiration_date`. Los
            # predicados replican `schemas.documents._expiry` uno a uno: si
            # alguno se toca, se tocan los dos, o la fila que el filtro
            # devuelve y el badge que pinta dejan de coincidir.
            hoy = today or date.today()
            limite = hoy + timedelta(days=DOCUMENT_EXPIRY_SOON_DAYS)
            if filters.expiring == "vencidos":
                q = q.filter(
                    AdhocDocument.expiration_date.isnot(None),
                    AdhocDocument.expiration_date < hoy,
                )
            elif filters.expiring == "por_vencer_30d":
                q = q.filter(
                    AdhocDocument.expiration_date.isnot(None),
                    AdhocDocument.expiration_date >= hoy,
                    AdhocDocument.expiration_date <= limite,
                )
            else:   # "vigentes" — sin vencimiento también cuenta como vigente
                q = q.filter(or_(
                    AdhocDocument.expiration_date.is_(None),
                    AdhocDocument.expiration_date > limite,
                ))
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

    @staticmethod
    def list_versions(db: Session, document_id: int) -> list[AdhocDocument]:
        """Cadena de versiones completa a la que pertenece ``document_id``.

        Da igual por dónde se entre —la raíz o cualquiera de sus versiones—:
        se normaliza a la raíz (``parent_id or id``) y se devuelven la raíz más
        todos sus hijos. La estructura migrada es **plana**, de profundidad 1
        (cero filas con un padre que a su vez tenga padre), así que un solo
        nivel de ``OR`` cubre la cadena entera; ``bulk_create`` mantiene esa
        invariante apuntando siempre a la raíz, nunca al hermano anterior.

        El orden es **la raíz primero y después por id ascendente**, es decir
        cronológico de alta. Ordenar por ``version`` sería lo intuitivo y está
        mal: es ``String(10)``, así que Postgres pondría ``'10.0'`` antes que
        ``'2.0'`` y el historial saldría desordenado justo en las cadenas
        largas, que son las únicas donde el historial importa.
        """
        doc = db.get(AdhocDocument, document_id)
        if doc is None:
            raise LookupError("Documento no encontrado")

        root_id = doc.parent_id or doc.id
        return (
            db.query(AdhocDocument)
            .options(*_EAGER)
            .filter(or_(
                AdhocDocument.id == root_id,
                AdhocDocument.parent_id == root_id,
            ))
            .order_by(
                case((AdhocDocument.id == root_id, 0), else_=1),
                AdhocDocument.id.asc(),
            )
            .all()
        )

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

        **Anexar una versión nueva** (``parent_id`` presente en la fila) es la
        única operación que mueve la cadena de versiones, y hace las tres cosas
        de golpe, dentro de la misma transacción:

        1. el documento nuevo cuelga de la **raíz** de la cadena
           (``parent.parent_id or parent.id``), no del hermano anterior — por
           eso la estructura se mantiene plana;
        2. nace como la punta (``is_current=True``);
        3. **toda** la cadena anterior —raíz incluida— pasa a
           ``is_current=False`` y ``status='Obsoleto'``, de un solo ``UPDATE``
           en lote.

        Los dos últimos van juntos a propósito: es lo que hacía el SGC original
        (su ``dap_approval_status = 2`` marca superado) y es la forma exacta de
        los datos migrados —144 cadenas, **exactamente una** fila
        ``is_current`` en cada una—. Dejar la versión anterior "vigente pero no
        actual" rompería esa invariante y las dos listas volverían a mostrar
        dos procedimientos vigentes con el mismo código.

        Y por eso mismo el anexado tiene una precondición: la cadena **no puede
        tener un flujo de aprobación en curso** (``AdhocConflict`` → 409, ver
        :meth:`_assert_sin_flujo_vivo`). Con tareas de flujo vivas el
        ``'Obsoleto'`` que escribe este método es reversible —quien apruebe la
        tarea huérfana devuelve el documento superado a ``'Aprobado'``—, así que
        la invariante que promete el párrafo de arriba solo se sostiene si el
        flujo anterior está cerrado antes de anexar.
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
                # El UPDATE de la cadena va ANTES de insertar la versión nueva:
                # si el documento nuevo ya estuviera en la sesión, el filtro
                # `parent_id == root_id` lo alcanzaría y nacería obsoleto.
                root_id = AdhocDocumentService._supersede_chain(db, data.get("parent_id"))

                doc = AdhocDocument(
                    code=data.get("code"),
                    title=data["title"],
                    version=data.get("version") or "1.0",
                    notes=data.get("notes"),
                    status=DOCUMENT_STATUS_DEFAULT,
                    expiration_date=data.get("expiration_date"),
                    parent_id=root_id,
                    category_id=data.get("category_id"),
                    area_id=data.get("area_id"),
                    process_id=data.get("process_id"),
                    classification_id=data.get("classification_id"),
                    author_id=author_id,
                )
                if root_id is not None:
                    # Sin padre no se toca: `is_current` lo pone el
                    # `server_default true` de la columna, como hasta ahora.
                    doc.is_current = True
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
        """``PATCH``: aplica solo los campos presentes en el payload.

        ``expiration_date`` no necesita tratamiento especial: Pydantic ya la
        entregó como ``date`` (o como ``None`` si llegó vacía, que es la forma
        legítima de quitarle la vigencia a un documento).

        Lo que **no** se puede tocar por aquí es ``is_current`` ni
        ``parent_id`` —no están en :class:`DocumentUpdate` y ``AdhocSchema``
        ignora los extras—: la cadena de versiones solo la mueve
        ``bulk_create``, que cambia punta y estado de todas las filas a la vez.

        **El documento tiene que estar en un estado que admita edición**, y ese
        gate vive aquí, en el service. Tres reglas, comprobadas antes de aplicar
        nada:

        1. una **versión superada** (``is_current=False``) no se edita nunca:
           es histórico, y en un SGC ISO 9001 el histórico es la evidencia de
           qué decía el documento cuando alguien lo firmó;
        2. solo se edita desde :data:`DOCUMENT_STATUSES_EDITABLE`
           (``'Borrador'`` y ``'Rechazado'``). Lo que ya pasó por el flujo de
           aprobación es inmutable: corregirlo es **anexar una versión nueva**,
           no reescribir la aprobada. Hoy eso deja editables 4 de los 202
           documentos migrados, y es la cifra correcta;
        3. el **archivo** solo se reemplaza desde
           :data:`DOCUMENT_STATUSES_FILE_REPLACEABLE` (solo ``'Borrador'``) **y**
           mientras el documento no haya entrado nunca a un flujo
           (:func:`_ha_circulado`). Es más estrecho que (2) a propósito: un
           ``'Rechazado'`` sí acepta que le corrijan los metadatos, pero no que
           le cambien el PDF debajo, porque sus validadores rechazaron *ese*
           archivo y la decisión quedó escrita en ``adhoc_task_approvals``.
           Además, el reemplazo borra el binario anterior del disco sin vuelta
           atrás. Las dos condiciones hacen falta: con solo la del ``status``,
           dos ``PATCH`` seguidos —uno que devuelve el documento a
           ``'Borrador'``, otro con el archivo— recuperaban el reemplazo, porque
           el estado de entrada es justo lo que este endpoint puede escribir.

        Los tres son :class:`AdhocConflict` (→ 409), no ``ValueError``: el
        documento existe y el payload es válido; lo que impide la operación es
        su **estado**. Ese es el contrato de errores que declara el módulo.

        Y va en el service, no en el JS, por el precedente que dejó B1: la
        misma regla de estados de ``start_flow`` (``DOCUMENT_STATUSES_STARTABLE``)
        existía desde la migración y **solo la respetaba ``documents-panel.js``**
        —escondía el botón del sello—, así que un POST a mano arrancaba un flujo
        sobre un documento obsoleto. Una regla que solo vive en el navegador no
        es una regla: el botón deshabilitado del panel es comodidad, esto es el
        gate.
        """
        doc = db.get(AdhocDocument, document_id)
        if doc is None:
            raise LookupError("Documento no encontrado")

        # (1) El histórico no se edita, aunque su `status` estuviera en la lista.
        if not doc.is_current:
            raise AdhocConflict(
                "No se puede editar una versión superada: este documento ya fue "
                "sustituido por una versión más nueva y el historial del SGC no "
                "se edita. Edite la versión vigente de la cadena."
            )
        # (2) Lo aprobado es inmutable; se corrige anexando una versión nueva.
        if doc.status not in DOCUMENT_STATUSES_EDITABLE:
            raise AdhocConflict(
                f"No se puede editar un documento en estado '{doc.status}': "
                f"{_por_que_no_se_edita(doc.status)}. Para corregirlo, anexe una "
                f"versión nueva. Solo se edita desde: "
                f"{', '.join(DOCUMENT_STATUSES_EDITABLE)}."
            )
        # (3) Gate aparte del (2): 'Rechazado' admite metadatos, no archivo.
        if _has_filename(upload):
            if doc.status not in DOCUMENT_STATUSES_FILE_REPLACEABLE:
                raise AdhocConflict(
                    f"No se puede reemplazar el archivo de un documento en estado "
                    f"'{doc.status}': los demás campos sí se pueden corregir, pero el "
                    f"adjunto solo se sustituye en "
                    f"{', '.join(DOCUMENT_STATUSES_FILE_REPLACEABLE)}. Para cambiar el "
                    f"archivo, anexe una versión nueva."
                )
            # El `status` de arriba no basta: es un valor que este mismo PATCH
            # puede escribir. Ver `_ha_circulado`.
            if _ha_circulado(doc):
                raise AdhocConflict(
                    "No se puede reemplazar el archivo de un documento que ya "
                    "circuló por un flujo de aprobación: sus validadores leyeron "
                    "ESE archivo y su decisión quedó escrita en el expediente. "
                    "Para cambiar el archivo, anexe una versión nueva."
                )

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

        Lo que **no** cae solo es la cadena de versiones:
        ``fk_adhoc_documents_parent_id`` se declaró sin ``ON DELETE`` (RESTRICT,
        igual que ``flow_id`` y ``current_step_id``), así que borrar la raíz de
        una cadena con versiones anexadas es un ``ForeignKeyViolation`` que
        ``_domain_errors`` no traduce y que el usuario ve como un 500 sin
        mensaje. Se rechaza antes, con el 409 que el módulo ya declara: la raíz
        es la **primera** versión del documento —el original del que cuelga todo
        el historial—, y perderla dejaría a las versiones posteriores sin la
        cabecera de su propia cadena. Se borran primero las anexadas, que es
        además el orden en que un SGC retira documentación.
        """
        doc = db.get(AdhocDocument, document_id)
        if doc is None:
            raise LookupError("Documento no encontrado")

        hijas = (
            db.query(AdhocDocument.id)
            .filter(AdhocDocument.parent_id == doc.id)
            .count()
        )
        if hijas:
            cuantas = (
                "1 versión posterior" if hijas == 1 else f"{hijas} versiones posteriores"
            )
            raise AdhocConflict(
                f"No se puede eliminar la versión raíz de una cadena con {cuantas}; "
                f"elimine primero las versiones anexadas."
            )

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
    def _supersede_chain(db: Session, parent_id: Optional[int]) -> Optional[int]:
        """Marca superada la cadena de ``parent_id`` y devuelve su raíz.

        Sin ``parent_id`` devuelve ``None`` y no toca nada (alta normal). Con
        él: valida que el documento exista (``ValueError`` → 400, no el
        ``IntegrityError`` a 500 del legacy), comprueba que la cadena no tenga
        un flujo de aprobación a medias (:meth:`_assert_sin_flujo_vivo`,
        ``AdhocConflict`` → 409), normaliza a la raíz y deja la cadena entera en
        ``is_current=False`` / ``status='Obsoleto'``.

        El ``UPDATE`` es **en lote**, no fila a fila: una cadena puede tener
        media docena de versiones y recorrerlas con el ORM son N ``SELECT`` +
        N ``UPDATE`` por cada alta. ``synchronize_session=False`` es seguro
        aquí porque los objetos afectados se releen —``bulk_create`` hace
        ``db.refresh`` de lo que crea, y la cadena vieja no vuelve a mirarse en
        esta transacción—; lo que no puede es correr **después** de insertar la
        versión nueva.
        """
        if not parent_id:
            return None

        parent = db.get(AdhocDocument, int(parent_id))
        if parent is None:
            raise ValueError(
                f"No existe el documento del que se anexa la versión: {parent_id}"
            )

        root_id = parent.parent_id or parent.id
        AdhocDocumentService._assert_sin_flujo_vivo(db, root_id)

        db.query(AdhocDocument).filter(or_(
            AdhocDocument.id == root_id,
            AdhocDocument.parent_id == root_id,
        )).update(
            {
                AdhocDocument.is_current: False,
                AdhocDocument.status: DOCUMENT_STATUS_OBSOLETE,
            },
            synchronize_session=False,
        )
        return root_id

    @staticmethod
    def _assert_sin_flujo_vivo(db: Session, root_id: int) -> None:
        """409 si la cadena de ``root_id`` tiene un flujo de aprobación a medias.

        Anexar una versión deja la cadena anterior en ``status='Obsoleto'``, que
        es un estado **terminal**. Si en ese momento el documento tiene tareas de
        flujo vivas —``'En Revisión'`` o ``'En Espera'``, el mismo par con el que
        el tablero reconoce al revisor documental—, el anexado dejaría un estado
        intermedio que se deshace solo:

        * los validadores conservan en su tablero la tarea *"Aprobar Documento:
          …"* de una versión que las dos listas ya ocultan, y no hay pantalla
          desde la que llegar al documento que están validando;
        * aprobar esa tarea huérfana hace que ``task_workflow_service`` vuelva a
          escribir ``status='Aprobado'`` sobre la versión superada, borrando en
          silencio el ``'Obsoleto'`` que el anexado acababa de poner y dejando
          dos filas de la misma cadena contando historias distintas.

        Lo que **no** se hace es cancelar por cuenta propia las tareas de
        terceros: el flujo se cierra por donde el SGC lo tiene previsto —se
        aprueba o se rechaza—, y esos dos caminos dejan registro de quién decidió
        en ``adhoc_task_approvals``. Cancelar en silencio para poder anexar
        borraría justo la evidencia que una auditoría ISO 9001 viene a mirar.
        """
        cadena = db.query(AdhocDocument.id).filter(or_(
            AdhocDocument.id == root_id,
            AdhocDocument.parent_id == root_id,
        ))
        viva = (
            db.query(AdhocTask.id)
            .filter(
                AdhocTask.document_id.in_(cadena),
                AdhocTask.status.in_((TASK_STATUS_IN_REVIEW, TASK_STATUS_WAITING)),
            )
            .first()
        )
        if viva is not None:
            raise AdhocConflict(
                "No se puede anexar una versión: el documento tiene un flujo de "
                "aprobación en curso. Termine o rechace el flujo antes de anexar "
                "la versión nueva."
            )

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
