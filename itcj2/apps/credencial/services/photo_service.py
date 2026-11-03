"""Fotos oficiales de credencial: normalización, almacenamiento y carga masiva.

Este módulo es el único que conoce el formato en disco (JPEG, ``PHOTO_MIME``).
"""
import io
import logging
import secrets
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from itcj2.apps.credencial.models import CredentialPhoto
    from itcj2.core.models.user import User

logger = logging.getLogger(__name__)

PHOTO_SIZE = (456, 600)  # ancho x alto; aspecto del hueco 235:309
PHOTO_MIME = "image/jpeg"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 25_000_000  # un PNG liso de 100 MP pesa KB pero ocupa GB al decodificar
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


class PhotoError(ValueError):
    """La imagen no se puede aceptar; el mensaje es apto para mostrarse."""


@dataclass(frozen=True)
class PhotoImportRow:
    filename: str
    status: Literal["created", "replaced", "no_student", "invalid"]
    detail: str = ""


def _root() -> str:
    from itcj2.config import get_settings
    return get_settings().CREDENCIAL_PHOTO_PATH


class PhotoService:
    @staticmethod
    def normalize(data: bytes) -> bytes:
        if len(data) > MAX_UPLOAD_BYTES:
            raise PhotoError("La imagen pesa más de 10 MB")
        try:
            probe = Image.open(io.BytesIO(data))
            fmt = probe.format
            if probe.width * probe.height > MAX_PIXELS:
                raise PhotoError("La imagen tiene demasiados píxeles")
            probe.verify()
            if fmt not in ALLOWED_FORMATS:
                raise PhotoError("Formato no permitido; usa JPG, PNG o WEBP")
            img = Image.open(io.BytesIO(data))  # verify() deja el objeto inservible
            img = ImageOps.exif_transpose(img)
            rgba = img.convert("RGBA")
            flat = Image.new("RGB", rgba.size, (255, 255, 255))
            flat.paste(rgba, mask=rgba.getchannel("A"))
            flat = ImageOps.fit(flat, PHOTO_SIZE, Image.LANCZOS, centering=(0.5, 0.4))
            out = io.BytesIO()
            flat.save(out, "JPEG", quality=85)  # sin exif=: no se copia ningún metadato
            return out.getvalue()
        except PhotoError:
            raise
        except Image.DecompressionBombError:
            raise PhotoError("La imagen tiene demasiados píxeles")
        except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
            raise PhotoError("El archivo no es una imagen válida")

    @staticmethod
    def save(db: Session, user_id: int, data: bytes, uploaded_by_id: int | None):
        from itcj2.apps.credencial.models import CredentialPhoto
        from itcj2.core.utils.safe_paths import safe_join

        jpeg = PhotoService.normalize(data)
        root = Path(_root())
        root.mkdir(parents=True, exist_ok=True)
        photo = db.get(CredentialPhoto, user_id)
        old_name = photo.file_name if photo else None
        new_name = f"{uuid.uuid4().hex}.jpg"
        new_path = safe_join(root, new_name)
        new_path.write_bytes(jpeg)
        try:
            if photo is None:
                photo = CredentialPhoto(user_id=user_id, ref=secrets.token_urlsafe(12))
                db.add(photo)
            photo.file_name = new_name
            photo.width, photo.height = PHOTO_SIZE
            photo.size_bytes = len(jpeg)
            photo.uploaded_by_id = uploaded_by_id
            db.commit()
        except Exception:
            db.rollback()
            new_path.unlink(missing_ok=True)
            raise
        if old_name:
            try:
                safe_join(root, old_name).unlink(missing_ok=True)
            except OSError:
                logger.warning("credencial: no se pudo borrar foto vieja user_id=%s", user_id)
        db.refresh(photo)
        return photo, ("replaced" if old_name else "created")

    @staticmethod
    def delete(db: Session, user_id: int) -> bool:
        from itcj2.apps.credencial.models import CredentialPhoto
        from itcj2.core.utils.safe_paths import safe_join

        photo = db.get(CredentialPhoto, user_id)
        if photo is None:
            return False
        name = photo.file_name
        db.delete(photo)
        db.commit()
        try:
            safe_join(_root(), name).unlink(missing_ok=True)
        except OSError:
            logger.warning("credencial: no se pudo borrar foto user_id=%s", user_id)
        return True

    @staticmethod
    def path(photo: "CredentialPhoto") -> Path:
        from itcj2.core.utils.safe_paths import safe_join
        return safe_join(_root(), photo.file_name)

    @staticmethod
    def read_bytes(photo: "CredentialPhoto") -> bytes:
        """Lanza OSError si el archivo no existe; quien muestre la foto lo maneja."""
        return PhotoService.path(photo).read_bytes()

    @staticmethod
    def match_filename(db: Session, filename: str) -> "User | None":
        from itcj2.apps.titulatec.services.import_service import normalize_control
        from itcj2.core.models.user import User

        control = normalize_control(Path(filename).stem)
        if not control:
            return None
        return db.query(User).filter_by(control_number=control).first()

    @staticmethod
    def import_batch(db: Session, files: list[tuple[str, bytes]],
                     uploaded_by_id: int | None) -> list[PhotoImportRow]:
        rows = []
        for filename, data in files:
            user = PhotoService.match_filename(db, filename)
            if user is None:
                rows.append(PhotoImportRow(filename, "no_student", "Ningún alumno con ese número de control"))
                continue
            try:
                _, status = PhotoService.save(db, user.id, data, uploaded_by_id)
            except PhotoError as e:
                rows.append(PhotoImportRow(filename, "invalid", str(e)))
            except Exception as e:
                logger.exception("credencial: fallo al guardar %s", filename)
                rows.append(PhotoImportRow(filename, "invalid", f"Error al guardar ({type(e).__name__})"))
            else:
                rows.append(PhotoImportRow(filename, status))
        return rows
