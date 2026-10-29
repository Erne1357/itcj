"""Firma del estudiante: PNG en base64 o data URL, validada antes de estamparla."""
from __future__ import annotations

import base64
from io import BytesIO

from PIL import Image

from itcj2.apps.prorrogas_tec.services.errors import ServiceError

MAX_BYTES = 200_000
MAX_SIDE = 2000


def parse_signature(raw: str) -> bytes:
    """Devuelve los bytes del PNG. Errores: ``firma_invalida``, ``firma_muy_grande``, ``firma_vacia``."""
    b64 = (raw or "").strip()
    if b64.startswith("data:"):
        _, _, b64 = b64.partition(",")
    if len(b64) > MAX_BYTES * 4 // 3 + 4:  # antes de decodificar
        raise ServiceError("firma_muy_grande", "La firma es demasiado grande.")
    try:
        data = base64.b64decode(b64, validate=True)
        img = Image.open(BytesIO(data), formats=["PNG"])
    except Image.DecompressionBombError:
        raise ServiceError("firma_muy_grande", "La firma es demasiado grande.")
    except Exception:  # parser de entrada no confiable: cualquier fallo es firma inválida
        raise ServiceError("firma_invalida", "La firma no es una imagen PNG válida.")
    if len(data) > MAX_BYTES or max(img.size) > MAX_SIDE:
        raise ServiceError("firma_muy_grande", "La firma es demasiado grande.")
    if "A" not in img.getbands() and "transparency" not in img.info:  # sin alfa no hay trazo que medir
        raise ServiceError("firma_invalida", "La firma debe ser un PNG con fondo transparente.")
    try:
        vacia = img.convert("RGBA").getchannel("A").getbbox() is None
    except Exception:
        raise ServiceError("firma_invalida", "La firma no es una imagen PNG válida.")
    if vacia:
        raise ServiceError("firma_vacia", "Dibuja tu firma antes de enviar.")
    return data
