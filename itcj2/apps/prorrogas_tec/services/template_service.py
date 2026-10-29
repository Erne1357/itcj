"""Plantillas ``.docx`` de Prórrogas: subir, validar, guardar y resolver cuál usar.

Reglas (spec §6.3):

- Solo ``.docx`` de hasta 5 MB, año entre 2020 y 2100.
- Los marcadores deben estar en el catálogo del formato (una errata como
  ``{{nombr}}`` se rechaza nombrándola) y los obligatorios no pueden faltar.
- Un marcador casi bien escrito (``{{Nombre}}``, ``{{año}}``, ``{{fecha}``) también
  se rechaza: si no, saldría impreso tal cual en la carta.
- Ninguna plantilla se edita ni se borra. Para un formato y un año se usa la
  más reciente de ese año; si no hay, la más reciente del año anterior más
  cercano; si no hay, la plantilla del sistema.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from itcj2.apps.prorrogas_tec.documents.catalog import DOC_TYPES, default_template_path
from itcj2.apps.prorrogas_tec.models.template import ProrrogaTemplate
from itcj2.apps.prorrogas_tec.services.docx_fill import InvalidDocx, find_malformed, find_placeholders
from itcj2.config import get_settings
from itcj2.core.utils.safe_paths import safe_join

MAX_TEMPLATE_BYTES = 5 * 1024 * 1024
YEAR_MIN, YEAR_MAX = 2020, 2100


class TemplateError(ValueError):
    """Plantilla rechazada. ``code`` es estable (la API lo devuelve tal cual)."""

    def __init__(self, code: str, message: str, **detail):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


def _base() -> Path:
    return Path(get_settings().PRORROGAS_UPLOAD_PATH)


def _lista(names) -> str:
    return ", ".join(sorted(names))


class TemplateService:

    @staticmethod
    def abs_path(rel: str) -> Path:
        return safe_join(_base(), rel)

    @staticmethod
    def read_bytes(t: ProrrogaTemplate) -> bytes:
        return TemplateService.abs_path(t.file_path).read_bytes()

    @staticmethod
    def upload(db: Session, *, doc_type: str, year: int, filename: str, data: bytes,
               actor_id: int | None) -> ProrrogaTemplate:
        tipo = DOC_TYPES.get(doc_type)
        if tipo is None:
            raise TemplateError("tipo_invalido", "El tipo de documento no existe.")
        if not YEAR_MIN <= int(year) <= YEAR_MAX:
            raise TemplateError("anio_invalido", f"El año debe estar entre {YEAR_MIN} y {YEAR_MAX}.")
        if not (filename or "").lower().endswith(".docx"):
            raise TemplateError("extension_invalida", "Solo se aceptan archivos de Word (.docx).")
        if len(data) > MAX_TEMPLATE_BYTES:
            raise TemplateError("archivo_muy_grande", "El archivo pasa de 5 MB.")
        try:
            found = find_placeholders(data)
            malformed = find_malformed(data)
        except InvalidDocx:
            raise TemplateError("docx_invalido", "El archivo no es un documento de Word válido.")
        if malformed:
            raise TemplateError(
                "marcadores_mal_escritos",
                f"La plantilla tiene marcadores mal escritos: {_lista(malformed)}. "
                "Escríbelos en minúsculas, sin acentos ni espacios y con dos llaves de cada lado, "
                "como {{nombre}}.",
                mal_escritos=sorted(malformed),
            )
        unknown = found - tipo.allowed
        if unknown:
            raise TemplateError(
                "placeholders_desconocidos",
                f"La plantilla tiene marcadores que no existen: {_lista(unknown)}.",
                desconocidos=sorted(unknown),
            )
        missing = tipo.required - found
        if missing:
            raise TemplateError(
                "placeholders_faltantes",
                f"A la plantilla le faltan marcadores obligatorios: {_lista(missing)}.",
                faltantes=sorted(missing),
            )

        sha = hashlib.sha256(data).hexdigest()
        rel = f"templates/{int(year)}/{doc_type}-{sha[:12]}.docx"
        _write_atomic(TemplateService.abs_path(rel), data)

        t = ProrrogaTemplate(
            doc_type=doc_type,
            year=int(year),
            original_name=Path(filename).name,
            file_path=rel,
            size_bytes=len(data),
            sha256=sha,
            placeholders=sorted(found),
            uploaded_by_id=actor_id,
        )
        db.add(t)
        db.commit()
        db.refresh(t)
        return t

    @staticmethod
    def active(db: Session, doc_type: str, year: int) -> ProrrogaTemplate | None:
        """La que se usa para ``doc_type`` en ``year`` (o None = la del sistema)."""
        q = db.query(ProrrogaTemplate).filter(ProrrogaTemplate.doc_type == doc_type)
        same = (q.filter(ProrrogaTemplate.year == year)
                .order_by(ProrrogaTemplate.uploaded_at.desc(), ProrrogaTemplate.id.desc())
                .first())
        if same is not None:
            return same
        return (q.filter(ProrrogaTemplate.year < year)
                .order_by(ProrrogaTemplate.year.desc(), ProrrogaTemplate.uploaded_at.desc(),
                          ProrrogaTemplate.id.desc())
                .first())

    @staticmethod
    def resolve(db: Session, doc_type: str, year: int) -> tuple[bytes, ProrrogaTemplate | None]:
        if doc_type not in DOC_TYPES:
            raise TemplateError("tipo_invalido", "El tipo de documento no existe.")
        t = TemplateService.active(db, doc_type, year)
        if t is not None:
            return TemplateService.read_bytes(t), t
        return default_template_path(doc_type).read_bytes(), None

    @staticmethod
    def years(db: Session, *, current_year: int) -> list[int]:
        """Años con plantillas subidas más el actual, del más reciente al más viejo."""
        rows = db.query(ProrrogaTemplate.year).distinct().all()
        return sorted({current_year, *(r[0] for r in rows)}, reverse=True)


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".docx")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
