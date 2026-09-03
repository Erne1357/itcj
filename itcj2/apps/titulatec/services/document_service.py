"""Lógica de documentos del proceso de titulación."""
from __future__ import annotations

from sqlalchemy.orm import Session


class DocumentService:
    INITIAL_DOC_TYPES = ["birth_certificate", "high_school_cert", "curp"]

    # ----------------------------------------------------------------- bitacora
    @staticmethod
    def _log(db: Session, process_id: int, actor_id: int | None, event_type: str,
             phase_number: int | None, payload: dict | None = None) -> None:
        """Escribe un `ProcessEvent`. Gemelo del de `appointment_service`.

        **No commitea**: se llama dentro de los metodos que ya son duenos de su
        transaccion, justo antes de su `commit()`.

        Existe porque de un documento no quedaba ABSOLUTAMENTE NADA de lo
        anterior: `save()` pisa la fila y `storage.save_document` pisa el archivo
        (nombre fijo `{type_code}.{ext}`), y `review()` pisa `review_note`. Un
        acta rechazada por falta de sello y vuelta a subir no dejaba ni el motivo
        ni la fecha ni quien la rechazo.
        """
        from itcj2.apps.titulatec.models import ProcessEvent
        db.add(ProcessEvent(
            process_id=process_id, actor_id=actor_id,
            event_type=event_type, phase_number=phase_number, payload=payload,
        ))

    @staticmethod
    def initial_docs_all_approved(db, process_id: int) -> bool:
        """True si los 3 documentos iniciales están en review_status='approved'."""
        for code in DocumentService.INITIAL_DOC_TYPES:
            doc = DocumentService.get_document(db, process_id, code)
            if not doc or doc.review_status != "approved":
                return False
        return True

    @staticmethod
    def initial_docs_summary(db, process_id: int) -> dict:
        """Resumen de los 3 documentos iniciales en **dos** consultas fijas.

        Lo consume el acordeón del dashboard del alumno, que se pinta 9 veces por
        carga: `initial_docs_all_approved` haría una consulta por código (y no
        distingue rechazado de faltante), así que ahí sería un N+1 en la pantalla
        más visitada de la app.

        `status` por documento: ``approved|rejected|pending|missing`` — ``missing``
        es el pseudo-estado de la UI cuando no hay fila (mismo criterio que
        `pages/documents.py:31`), no un valor de `Document.review_status`.
        """
        from itcj2.apps.titulatec.models import Document, DocumentType

        codes = DocumentService.INITIAL_DOC_TYPES
        docs = {
            d.type_code: d for d in
            db.query(Document)
            .filter(Document.process_id == process_id, Document.type_code.in_(codes))
            .all()
        }
        # Sin `is_active`: si un tipo se desactiva, el documento ya subido debe
        # seguir mostrándose con su nombre, no con el código crudo.
        names = {
            t.code: t.name for t in
            db.query(DocumentType).filter(DocumentType.code.in_(codes)).all()
        }

        items, counts = [], {"approved": 0, "rejected": 0, "pending": 0, "missing": 0}
        for code in codes:
            doc = docs.get(code)
            status = doc.review_status if doc else "missing"
            if status not in counts:          # valor inesperado en BD: no lo perdemos
                counts[status] = 0
            counts[status] += 1
            items.append({
                "code": code,
                "name": names.get(code, code),
                "status": status,
                "note": (doc.review_note if doc else None),
            })
        return {
            "total": len(codes),
            "uploaded": len(codes) - counts["missing"],
            "counts": counts,
            "items": items,
        }

    @staticmethod
    def get_active_process(db: Session, student_id: int):
        """Proceso activo más reciente del alumno (o None)."""
        from itcj2.apps.titulatec.models import TitulationProcess
        return (
            db.query(TitulationProcess)
            .filter_by(student_id=student_id)
            .order_by(TitulationProcess.created_at.desc())
            .first()
        )

    @staticmethod
    def _storage_keys(db: Session, process) -> tuple[str, str]:
        """Devuelve (period_code, control_number) para las rutas de archivo."""
        from itcj2.core.models.user import User
        period_code = process.cohort.period_code if process.cohort else "sin_periodo"
        student = db.get(User, process.student_id)
        control = (student.control_number if student else None) or str(process.student_id)
        return str(period_code), str(control)

    @staticmethod
    def get_document(db: Session, process_id: int, type_code: str):
        from itcj2.apps.titulatec.models import Document
        return (
            db.query(Document)
            .filter_by(process_id=process_id, type_code=type_code)
            .first()
        )

    @staticmethod
    def list_phase_document_types(db: Session, phase_number: int) -> list:
        from itcj2.apps.titulatec.models import DocumentType
        return (
            db.query(DocumentType)
            .filter_by(phase_number=phase_number, is_active=True)
            .order_by(DocumentType.id)
            .all()
        )

    @staticmethod
    def save(
        db: Session,
        process,
        type_code: str,
        *,
        raw: bytes,
        original_name: str,
        content_type: str | None,
        uploaded_by_id: int,
    ):
        """Guarda/sobreescribe el documento de un tipo. Solo última versión."""
        from itcj2.apps.titulatec.models import Document, DocumentType
        from itcj2.apps.titulatec.utils import storage

        dtype = db.query(DocumentType).filter_by(code=type_code, is_active=True).first()
        if not dtype:
            raise ValueError(f"Tipo de documento desconocido: {type_code}")

        period_code, control = DocumentService._storage_keys(db, process)
        meta = storage.save_document(
            raw=raw,
            original_name=original_name,
            content_type=content_type,
            period_code=period_code,
            control_number=control,
            type_code=type_code,
            file_kind=dtype.file_kind,
        )

        doc = DocumentService.get_document(db, process.id, type_code)
        if doc:
            doc.file_path = meta["file_path"]
            doc.original_name = meta["original_name"]
            doc.mime_type = meta["mime_type"]
            doc.size_bytes = meta["size_bytes"]
            doc.version = (doc.version or 1) + 1
            doc.review_status = "pending"
            doc.review_note = None
            doc.uploaded_by_id = uploaded_by_id
        else:
            doc = Document(
                process_id=process.id,
                phase_number=dtype.phase_number or 0,
                type_code=type_code,
                file_path=meta["file_path"],
                original_name=meta["original_name"],
                mime_type=meta["mime_type"],
                size_bytes=meta["size_bytes"],
                version=1,
                review_status="pending",
                uploaded_by_id=uploaded_by_id,
            )
            db.add(doc)

        db.flush()
        DocumentService._log(
            db, process.id, uploaded_by_id, "document_uploaded",
            dtype.phase_number,
            {"type_code": type_code, "original_name": doc.original_name,
             "version": doc.version},
        )
        db.commit()
        db.refresh(doc)
        return doc

    @staticmethod
    def review(db: Session, process_id: int, type_code: str, *, status: str, note: str | None, reviewer_id: int) -> bool:
        """Aprueba o rechaza un documento (status 'approved'|'rejected')."""
        doc = DocumentService.get_document(db, process_id, type_code)
        if not doc:
            return False
        doc.review_status = status
        doc.review_note = note or None
        doc.reviewed_by_id = reviewer_id

        # El evento guarda el motivo porque `review_note` es un solo hueco: la
        # siguiente revision lo pisa y el «por que» del rechazo anterior se va.
        DocumentService._log(
            db, process_id, reviewer_id,
            "document_approved" if status == "approved" else "document_rejected",
            doc.phase_number,
            {"type_code": type_code, "note": note or None},
        )

        if status == "rejected":
            from itcj2.apps.titulatec.models import TitulationProcess
            from itcj2.apps.titulatec.services.notify import notify_student
            proc = db.get(TitulationProcess, process_id)
            if proc:
                notify_student(db, proc.student_id, type="DOCUMENT_REJECTED",
                               title="Un documento necesita correcciones",
                               body=(note or "Revisa el documento rechazado y vuelve a subirlo."),
                               process_id=process_id, phase_number=1)

        db.commit()
        return True

    @staticmethod
    def delete(db: Session, process_id: int, type_code: str,
               *, actor_id: int | None = None) -> bool:
        """Borra la fila Y el archivo. Deja evento: un hueco sin explicacion en el
        expediente se lee como «nunca lo subio»."""
        from itcj2.apps.titulatec.utils import storage
        doc = DocumentService.get_document(db, process_id, type_code)
        if not doc:
            return False
        phase_number = doc.phase_number
        storage.delete_document_file(doc.file_path)
        db.delete(doc)
        DocumentService._log(db, process_id, actor_id, "document_deleted",
                             phase_number, {"type_code": type_code})
        db.commit()
        return True
