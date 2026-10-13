"""Cifrado y CRUD de los NIPs precargados (`titulatec_nip_stash`).

Sin commit en ningún método: la transacción es del llamador. El NIP y el
número de control NUNCA van a un log ni a un mensaje de excepción.
"""
from __future__ import annotations

import logging

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func
from sqlalchemy.orm import Session

from itcj2.apps.titulatec.models.nip_stash import NipStash
from itcj2.apps.titulatec.services.enrollment_request_service import nip_format_ok
from itcj2.config import get_settings

logger = logging.getLogger(__name__)


def _fernet() -> Fernet | None:
    """`Fernet` con la llave vigente, o None si no hay (o no sirve). Se lee en
    cada llamada: un cambio de llave se nota sin reiniciar y los tests parchean
    el singleton de `get_settings()`."""
    key = get_settings().TITULATEC_NIP_STASH_KEY
    if not key:
        return None
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError):
        return None


class NipStashService:
    @staticmethod
    def available() -> bool:
        """¿Hay llave utilizable? Sin ella no se puede cargar ni leer."""
        return _fernet() is not None

    @staticmethod
    def put(db: Session, control: str, nip: str, *, actor_id: int | None) -> bool:
        """Guarda (cifrado) el NIP de `control`. True = reemplazó una fila previa.

        `ValueError` si el NIP no cumple `nip_format_ok` o no hay llave; el
        mensaje no incluye el NIP. Sin commit.
        """
        if not nip_format_ok(nip):
            raise ValueError("NIP inválido: deben ser 4 dígitos.")
        f = _fernet()
        if f is None:
            raise ValueError("TITULATEC_NIP_STASH_KEY no está configurada.")
        cipher = f.encrypt(nip.encode("ascii")).decode("ascii")
        fila = db.get(NipStash, control)
        if fila is not None:
            fila.nip_cipher = cipher
            fila.loaded_by_id = actor_id
            # La fecha refleja la última carga, no la primera.
            fila.loaded_at = func.now()
            db.flush()
            return True
        db.add(NipStash(control_number=control, nip_cipher=cipher, loaded_by_id=actor_id))
        db.flush()
        return False

    @staticmethod
    def peek(db: Session, control: str) -> str | None:
        """NIP en claro o None (sin fila, sin llave o llave cambiada)."""
        f = _fernet()
        if f is None:
            return None
        fila = db.get(NipStash, control)
        if fila is None:
            return None
        try:
            return f.decrypt(fila.nip_cipher.encode("ascii")).decode("ascii")
        except InvalidToken:
            # Genérico a propósito: sin control ni NIP. La llave cambió
            # después de cargar.
            logger.warning("NIP precargado ilegible con la llave actual "
                           "(¿cambió TITULATEC_NIP_STASH_KEY?).")
            return None

    @staticmethod
    def discard(db: Session, control: str) -> bool:
        """Borra la fila. True si existía. Sin commit."""
        fila = db.get(NipStash, control)
        if fila is None:
            return False
        db.delete(fila)
        db.flush()
        return True
