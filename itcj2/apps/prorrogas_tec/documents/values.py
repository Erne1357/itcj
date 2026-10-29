"""Valores con los que se llena cada formato (se congelan en ``ProrrogaDocument.context``)."""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime

from itcj2.apps.prorrogas_tec.documents.catalog import DOC_TYPES
from itcj2.apps.prorrogas_tec.services.formatting import fecha_corta
from itcj2.apps.prorrogas_tec.services.identity import folio as make_folio

# Caracteres que XML 1.0 no admite (python-docx fallaría al escribirlos).
_XML_ILEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")


@dataclass(frozen=True)
class SignatureInfo:
    png: bytes
    signer_id: int
    signed_at: datetime
    ip: str | None = None
    user_agent: str | None = None


def clean_text(s: str | None) -> str:
    """Quita caracteres de control y junta saltos/espacios repetidos en uno."""
    return " ".join(_XML_ILEGAL.sub("", s or "").split())


def build_values(req, doc_type: str, *, today: date, extra: Mapping[str, str] | None = None,
                 signature: SignatureInfo | None = None) -> tuple[dict[str, str], dict[str, bytes]]:
    extra = extra or {}
    fol = make_folio(req.id)
    pool = {
        "fecha": fecha_corta(today),
        "folio": fol,
        "nombre": clean_text(req.student_name),
        "no_control": req.control_number,
        "carrera": clean_text(req.program_name),
        "semestre": clean_text(req.period_label),
        "correo": clean_text(req.email),
        "plazos_solicitados": str(req.requested_terms),
        "motivo": clean_text(req.reason),
        "fecha_solicitud": fecha_corta(req.created_at.date()),
        "comentario": clean_text(extra.get("comentario")),
        "motivo_rechazo": clean_text(extra.get("motivo_rechazo")),
        "firma_estudiante_leyenda": (
            f"Firmado electrónicamente por {clean_text(req.student_name)} el "
            f"{signature.signed_at:%d/%m/%Y %H:%M} · folio {fol}" if signature else ""),
    }
    # Cualquier otro marcador permitido (montos, pagos...) llega por `extra` o va vacío.
    values = {k: pool.get(k, clean_text(extra.get(k))) for k in DOC_TYPES[doc_type].allowed}
    images: dict[str, bytes] = {}
    if signature:
        images["firma_estudiante"] = signature.png
        values.pop("firma_estudiante", None)
    else:
        values["firma_estudiante"] = ""
    return values, images
