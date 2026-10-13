"""Cifrado y CRUD de los NIPs precargados (`titulatec_nip_stash`).

Sin commit en ningún método: la transacción es del llamador. El NIP y el
número de control NUNCA van a un log ni a un mensaje de excepción.
"""
from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Iterable

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func
from sqlalchemy.orm import Session

from itcj2.apps.titulatec.models.nip_stash import NipStash
from itcj2.apps.titulatec.services.enrollment_request_service import nip_format_ok
from itcj2.config import get_settings

logger = logging.getLogger(__name__)

# Llaves FIJAS del resultado de `load_rows` (el orden es el del reporte).
LOAD_BUCKETS = ("granted", "stored", "stored_rejected", "has_account", "no_request",
                "invalid_nip", "duplicate", "failed")

_MSG_EXCEL = ("NIP inválido: deben ser 4 dígitos (¿Excel quitó un cero a la "
              "izquierda?).")
_MSG_NIP = "NIP inválido: deben ser 4 dígitos."
_MSG_CONTROL = "Número de control inválido."
_MSG_DUP = "El control aparece más de una vez en el archivo; no se cargó ninguna."
_MSG_NO_MAIL = ("La cuenta se creó pero el correo no salió: Accesos la muestra como "
                "«correo no enviado».")


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


def _stash_keys(db: Session) -> set[str]:
    return {c for (c,) in db.query(NipStash.control_number).all()}


def _normalizados(controles) -> set[str]:
    from itcj2.apps.titulatec.services.import_service import normalize_control

    return {normalize_control(c or "") for c in controles} - {""}


def _controles_vivos(db: Session) -> set[str]:
    """Controles con alguna solicitud viva en CUALQUIER convocatoria."""
    from itcj2.apps.titulatec.models import EnrollmentRequest
    from itcj2.apps.titulatec.models.enrollment_request import OPEN_STATUSES

    return _normalizados(c for (c,) in db.query(EnrollmentRequest.control_number)
                         .filter(EnrollmentRequest.status.in_(OPEN_STATUSES)).all())


def _rechazo_reabrible(db: Session, cerrando: int) -> set[str]:
    """Controles con una solicitud `rejected` en una convocatoria distinta de
    `cerrando` que NO está `closed`. La que se cierra cuenta como cerrada;
    misma regla que `purge_stale` (todas las rechazadas, de convocatorias
    cerradas)."""
    from itcj2.apps.titulatec.models import Cohort, EnrollmentRequest

    return _normalizados(
        c for (c,) in db.query(EnrollmentRequest.control_number)
        .join(Cohort, Cohort.id == EnrollmentRequest.cohort_id)
        .filter(EnrollmentRequest.status == "rejected",
                EnrollmentRequest.cohort_id != cerrando,
                Cohort.status != "closed").all())


def _con_cuenta(db: Session, llaves: set[str]) -> set[str]:
    from itcj2.core.models.user import User

    if not llaves:
        return set()
    return _normalizados(c for (c,) in db.query(User.control_number)
                         .filter(User.control_number.in_(llaves)).all()) & llaves


def _borrar(db: Session, llaves: set[str]) -> int:
    if not llaves:
        return 0
    n = (db.query(NipStash).filter(NipStash.control_number.in_(llaves))
         .delete(synchronize_session="fetch"))
    db.flush()
    return n


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
    def readable(db: Session, controls: Iterable[str]) -> set[str]:
        """Los `controls` (ya normalizados) cuyo NIP guardado SÍ se descifra.

        Para la bandeja, que solo debe prometer «dar acceso» donde aprobar podrá
        usar el NIP. Sin llave -> vacío y sin aviso (ya es el caso conocido). Con
        filas ilegibles (llave cambiada) deja UN solo WARNING agregado, sin
        controles ni NIP, en vez de uno por fila como `peek`. Solo lee.
        """
        f = _fernet()
        llaves = set(controls)
        if f is None or not llaves:
            return set()
        ok: set[str] = set()
        mal = 0
        for fila in db.query(NipStash).filter(NipStash.control_number.in_(llaves)).all():
            try:
                f.decrypt(fila.nip_cipher.encode("ascii"))
                ok.add(fila.control_number)
            except (InvalidToken, UnicodeError):
                mal += 1
        if mal:
            logger.warning("%d NIP(s) precargado(s) ilegible(s) con la llave actual "
                           "(¿cambió TITULATEC_NIP_STASH_KEY?).", mal)
        return ok

    @staticmethod
    def purge_for_cohort(db: Session, cohort_id: int) -> int:
        """Borra los NIP de los controles con solicitud en `cohort_id` que ya no
        pueden usarlos: (a) ninguna solicitud VIVA (`OPEN_STATUSES`) en NINGUNA
        convocatoria, o (b) ya tienen cuenta. Devuelve cuántas filas borró. Sin
        commit (lo hace `set_window`) y sin llave: borrar no descifra. No loguea
        controles ni NIP.
        """
        from itcj2.apps.titulatec.models import EnrollmentRequest

        guardados = _stash_keys(db)
        if not guardados:
            return 0
        del_cohorte = {c for (c,) in db.query(EnrollmentRequest.control_number)
                       .filter(EnrollmentRequest.cohort_id == cohort_id).all()}
        candidatos = _normalizados(del_cohorte) & guardados
        if not candidatos:
            return 0
        # Una rechazada en otra convocatoria que sigue abierta aún se puede
        # reabrir: su NIP se queda hasta que ESA convocatoria cierre.
        sin_uso = candidatos - _controles_vivos(db) - _rechazo_reabrible(db, cohort_id)
        victimas = sin_uso | (candidatos & _con_cuenta(db, candidatos))
        return _borrar(db, victimas)

    @staticmethod
    def purge_stale(db: Session) -> int:
        """Barrido de todo el guardado: borra (b) los que ya tienen cuenta y los
        controles sin solicitud viva cuyas solicitudes son TODAS `rejected` de
        convocatorias `closed`. Un control sin ninguna solicitud no se toca.
        Devuelve cuántas filas borró. Sin commit (el CLI decide). No loguea datos.
        """
        from itcj2.apps.titulatec.models import Cohort, EnrollmentRequest
        from itcj2.apps.titulatec.services.import_service import normalize_control

        guardados = _stash_keys(db)
        if not guardados:
            return 0
        victimas = _con_cuenta(db, guardados)
        vivos = _controles_vivos(db)
        por_control: dict[str, list[bool]] = {}
        for control, status, cohorte in (
                db.query(EnrollmentRequest.control_number, EnrollmentRequest.status,
                         Cohort.status)
                .join(Cohort, Cohort.id == EnrollmentRequest.cohort_id).all()):
            llave = normalize_control(control or "")
            if llave in guardados:
                por_control.setdefault(llave, []).append(
                    status == "rejected" and cohorte == "closed")
        victimas |= {c for c, todas in por_control.items() if all(todas)} - vivos
        return _borrar(db, victimas)

    @staticmethod
    def discard(db: Session, control: str) -> bool:
        """Borra la fila. True si existía. Sin commit."""
        fila = db.get(NipStash, control)
        if fila is None:
            return False
        db.delete(fila)
        db.flush()
        return True

    @staticmethod
    def load_rows(db: Session, rows: list[tuple[str, str]], *, actor_id: int,
                  dry_run: bool, send_mail: bool,
                  on_row: Callable[[str, str, str], None] | None = None,
                  ) -> dict[str, list[tuple[str, str]]]:
        """Carga en lote `(control, nip)` del SII. Devuelve `{bucket: [(control, motivo)]}`.

        Los buckets (`LOAD_BUCKETS`) y sus motivos NUNCA llevan el NIP. Por control:

        - repetido en el archivo -> `duplicate` (ninguna aparición se carga);
        - NIP que no son 4 dígitos -> `invalid_nip` (con la pista de Excel si son 1-3);
        - ya hay cuenta en `core_users` -> `has_account`, sea cual sea la solicitud;
        - solicitud VIVA (`OPEN_STATUSES`; si hay varias, la `awaiting_access` y
          luego la más nueva): `awaiting_access` recibe el acceso
          (`grant_access(nip_source="preloaded")`) -> `granted`; el resto guarda
          el NIP cifrado -> `stored`;
        - solo solicitudes `rejected` -> se guarda igual (se puede reabrir) ->
          `stored_rejected`; ninguna -> `no_request`.

        Una transacción por fila (`grant_access` y el guardado commitean). Un
        fallo, un correo que no sale o una excepción dejan esa fila en `failed` y
        el lote sigue. `dry_run` clasifica (solo lee) y no escribe nada: ni
        guardado, ni acceso, ni bitácora. `send_mail=False`: la cuenta se crea
        sin correo y `access_sent_at` queda NULL.

        `on_row(bucket, control, motivo)`: se llama AL MOMENTO por cada fila
        `granted` o `failed` (fuera de `dry_run`), para que el CLI deje rastro
        si el lote se interrumpe a medias. Nunca recibe el NIP.
        """
        from itcj2.apps.titulatec.models import EnrollmentRequest
        from itcj2.apps.titulatec.models.enrollment_request import OPEN_STATUSES
        from itcj2.apps.titulatec.services.audit_service import AuditService
        from itcj2.apps.titulatec.services.enrollment_request_service import (
            CONTROL_NUMBER_RE, EnrollmentRequestService, _audit_subject,
        )
        from itcj2.apps.titulatec.services.import_service import normalize_control
        from itcj2.core.models.user import User

        out: dict[str, list[tuple[str, str]]] = {b: [] for b in LOAD_BUCKETS}
        limpias = [(normalize_control(c), (n or "").strip()) for c, n in rows]
        limpias = [(c, n) for c, n in limpias if c or n]
        veces = Counter(c for c, _ in limpias)
        vistos: set[str] = set()

        for control, nip in limpias:
            if veces[control] > 1:
                if control not in vistos:
                    out["duplicate"].append((control, _MSG_DUP))
                vistos.add(control)
                continue
            if not nip_format_ok(nip):
                pista = nip.isascii() and nip.isdigit() and 1 <= len(nip) <= 3
                out["invalid_nip"].append((control, _MSG_EXCEL if pista else _MSG_NIP))
                continue
            if not CONTROL_NUMBER_RE.fullmatch(control):
                out["no_request"].append((control, _MSG_CONTROL))
                continue
            if db.query(User.id).filter(User.control_number == control).first():
                out["has_account"].append((control, "Ya tiene cuenta."))
                continue

            solicitudes = (db.query(EnrollmentRequest)
                           .filter(EnrollmentRequest.control_number == control)
                           .order_by(EnrollmentRequest.id.desc()).all())
            vivas = [r for r in solicitudes if r.status in OPEN_STATUSES]
            if vivas:
                req = next((r for r in vivas if r.status == "awaiting_access"), vivas[0])
                bucket = "granted" if req.status == "awaiting_access" else "stored"
            elif any(r.status == "rejected" for r in solicitudes):
                req = next(r for r in solicitudes if r.status == "rejected")
                bucket = "stored_rejected"
            else:
                out["no_request"].append((control, "Sin solicitud de inscripción."))
                continue

            if dry_run:
                out[bucket].append((control, ""))
                continue

            req_id = req.id
            antes = (len(out["granted"]), len(out["failed"]))
            try:
                if bucket == "granted":
                    ok, detalle = EnrollmentRequestService.grant_access(
                        db, req_id, nip=nip, actor_id=actor_id,
                        nip_source="preloaded", send_mail=send_mail)
                    if not ok:
                        out["failed"].append((control, detalle))
                    elif send_mail and req.access_sent_at is None:
                        # La cuenta ya existe y está commiteada; solo falta el aviso.
                        out["failed"].append((control, _MSG_NO_MAIL))
                    else:
                        out["granted"].append((control, ""))
                else:
                    reemplazo = NipStashService.put(db, control, nip, actor_id=actor_id)
                    AuditService.record(
                        db, "enrollment.nip_preloaded",
                        entity_type="enrollment_request", entity_id=req_id,
                        subject=_audit_subject(req),
                        payload={"replaced": reemplazo}, actor_id=actor_id)
                    db.commit()
                    out[bucket].append((control, "Reemplazó el NIP anterior." if reemplazo else ""))
            except Exception as exc:
                db.rollback()
                # Solo el tipo: el texto de una excepción podría arrastrar datos.
                logger.error("Carga de NIP: falló una fila (%s).", type(exc).__name__)
                out["failed"].append((control, f"Error inesperado ({type(exc).__name__})."))
            if on_row is not None:
                for b in ("granted", "failed"):
                    if len(out[b]) > antes[0 if b == "granted" else 1]:
                        on_row(b, control, out[b][-1][1])
        return out
