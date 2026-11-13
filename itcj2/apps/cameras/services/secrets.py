"""Cifrado Fernet de credenciales de DVR y normalización del patrón de desbloqueo.

Los mensajes de error nunca incluyen el valor recibido.
"""
from __future__ import annotations

import re

from cryptography.fernet import Fernet, InvalidToken

from itcj2.config import get_settings

PATTERN_MIN_LEN = 4
PATTERN_MAX_LEN = 9
_SEPARATORS = re.compile(r"[\s\-→,·.>]+")


class CamerasKeyMissing(Exception):
    """No hay CAMERAS_SECRET_KEY válida (o el token no se puede descifrar con ella)."""


class CamerasDecryptError(CamerasKeyMissing):
    """Hay llave pero no sirve para este token (llave rotada o dato corrupto)."""


def _fernet() -> Fernet:
    # Se lee en cada llamada: los tests parchean el singleton de settings.
    key = get_settings().CAMERAS_SECRET_KEY
    if not key:
        raise CamerasKeyMissing("CAMERAS_SECRET_KEY no configurada")
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError):
        raise CamerasKeyMissing("CAMERAS_SECRET_KEY inválida") from None


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode("utf-8")).decode()


def decrypt(token: str) -> str:
    f = _fernet()
    try:
        return f.decrypt(token.encode()).decode("utf-8")
    except InvalidToken:
        raise CamerasDecryptError("No se pudo descifrar con la llave vigente") from None


def normalize_pattern(raw: str) -> str:
    """Quita separadores y valida: dígitos 1-9, sin repetir, 4 a 9 de largo."""
    s = _SEPARATORS.sub("", raw or "")
    if (not re.fullmatch(r"[1-9]+", s) or len(set(s)) != len(s)
            or not PATTERN_MIN_LEN <= len(s) <= PATTERN_MAX_LEN):
        raise ValueError(
            f"Patrón inválido: usa de {PATTERN_MIN_LEN} a {PATTERN_MAX_LEN} dígitos "
            "del 1 al 9, sin repetir."
        )
    return s
