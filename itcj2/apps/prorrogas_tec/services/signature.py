"""Firma del estudiante: PNG en base64 o data URL, validada antes de estamparla."""
from __future__ import annotations

import base64
import binascii
from io import BytesIO

from PIL import Image, UnidentifiedImageError

from itcj2.apps.prorrogas_tec.services.errors import ServiceError

MAX_BYTES = 200_000
MAX_SIDE = 2000


def parse_signature(raw: str) -> bytes:
    """Devuelve los bytes del PNG. Errores: ``firma_invalida``, ``firma_muy_grande``, ``firma_vacia``."""
    b64 = (raw or "").strip()
    if b64.startswith("data:"):
        _, _, b64 = b64.partition(",")
    try:
        data = base64.b64decode(b64, validate=True)
        img = Image.open(BytesIO(data))
    except (binascii.Error, ValueError, UnidentifiedImageError, OSError):
        raise ServiceError("firma_invalida", "La firma no es una imagen PNG válida.")
    if img.format != "PNG":
        raise ServiceError("firma_invalida", "La firma no es una imagen PNG válida.")
    if len(data) > MAX_BYTES or max(img.size) > MAX_SIDE:
        raise ServiceError("firma_muy_grande", "La firma es demasiado grande.")
    try:
        vacia = img.convert("RGBA").getchannel("A").getbbox() is None
    except (OSError, ValueError, Image.DecompressionBombError):
        raise ServiceError("firma_invalida", "La firma no es una imagen PNG válida.")
    if vacia:
        raise ServiceError("firma_vacia", "Dibuja tu firma antes de enviar.")
    return data
