"""Lógica de documentos del proceso de titulación."""
from __future__ import annotations

from sqlalchemy.orm import Session


class DocumentService:
    INITIAL_DOC_TYPES = ["birth_certificate", "high_school_cert", "curp"]

    @staticmethod
    def initial_docs_all_approved(db, process_id: int) -> bool:
        """True si los 3 documentos iniciales están en review_status='approved'."""
        for code in DocumentService.INITIAL_DOC_TYPES:
            doc = DocumentService.get_document(db, process_id, code)
            if not doc or doc.review_status != "approved":
                return False
        return True

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
    def delete(db: Session, process_id: int, type_code: str) -> bool:
        from itcj2.apps.titulatec.utils import storage
        doc = DocumentService.get_document(db, process_id, type_code)
        if not doc:
            return False
        storage.delete_document_file(doc.file_path)
        db.delete(doc)
        db.commit()
        return True
