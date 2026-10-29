"""Genera, versiona y guarda los documentos (PDF) de una solicitud. No hace commit."""
from __future__ import annotations

import hashlib
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from itcj2.apps.prorrogas_tec.documents.values import SignatureInfo, build_values
from itcj2.apps.prorrogas_tec.models.document import ProrrogaDocument
from itcj2.apps.prorrogas_tec.models.signature import ProrrogaSignature
from itcj2.apps.prorrogas_tec.services import storage
from itcj2.apps.prorrogas_tec.services.docx_fill import fill_docx
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.events import log_event
from itcj2.apps.prorrogas_tec.services.template_service import TemplateService
from itcj2.core.utils import docx_pdf
from itcj2.core.utils.timezone import db_now


class DocumentService:

    @staticmethod
    def generate(db: Session, req, doc_type: str, *, actor_id: int | None, today: date,
                 extra=None, signature: SignatureInfo | None = None) -> ProrrogaDocument:
        values, images = build_values(req, doc_type, today=today, extra=extra, signature=signature)
        docx, template = TemplateService.resolve(db, doc_type, today.year)
        try:
            pdf = docx_pdf.docx_to_pdf(fill_docx(docx, values, images), kind="prorrogas_documento")
        except docx_pdf.CONVERSION_ERRORS:
            raise ServiceError("pdf_no_disponible",
                               "No se pudo generar el PDF. Intenta de nuevo en un momento.", status=503)

        previas = (db.query(ProrrogaDocument)
                   .filter_by(request_id=req.id, doc_type=doc_type).all())
        version = 1 + max((d.version for d in previas), default=0)
        ahora = db_now()
        for d in previas:
            if d.superseded_at is None:
                d.superseded_at = ahora

        rel = f"documentos/{req.id}/{doc_type}-v{version}.pdf"
        storage.write_atomic(rel, pdf)
        doc = ProrrogaDocument(
            request_id=req.id, doc_type=doc_type, version=version,
            template_id=template.id if template else None, context=values, file_path=rel,
            sha256=hashlib.sha256(pdf).hexdigest(), generated_by_id=actor_id,
            signed_at=signature.signed_at if signature else None,
        )
        db.add(doc)
        db.flush()
        if signature:
            png_rel = f"documentos/{req.id}/firma-{doc_type}-v{version}.png"
            storage.write_atomic(png_rel, signature.png)
            db.add(ProrrogaSignature(
                document_id=doc.id, signer_id=signature.signer_id, image_path=png_rel,
                signed_at=signature.signed_at, ip=signature.ip, user_agent=signature.user_agent,
                pdf_sha256=doc.sha256))
        log_event(db, event_type="documento_generado", request_id=req.id, actor_id=actor_id,
                  payload={"doc_type": doc_type, "version": version})
        return doc

    @staticmethod
    def read_pdf(doc: ProrrogaDocument) -> bytes:
        return storage.abs_path(doc.file_path).read_bytes()

    @staticmethod
    def current(db: Session, req) -> list[ProrrogaDocument]:
        return (db.query(ProrrogaDocument)
                .filter(ProrrogaDocument.request_id == req.id, ProrrogaDocument.superseded_at.is_(None))
                .order_by(ProrrogaDocument.generated_at, ProrrogaDocument.id).all())
