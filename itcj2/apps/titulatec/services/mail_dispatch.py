"""Despachador de los correos del proceso al egresado (spec 2026-09-28 §6 C3).

La tarea periódica `titulatec.email_dispatch` (cada 5 minutos) llama a
`MailDispatcher.run`: toma lo pendiente de `titulatec_email_outbox`, lo manda
por Graph y deja el desenlace en cada fila. Es el ÚNICO que envía y el único
que cambia `status` después del encolado (`StudentMail.enqueue`).

UNA CORRIDA (`run`)
1. Correo apagado (`MailSettings.enabled()` falso) → `{"disabled": True}` sin
   tocar la BD: lo encolado se queda `pending` y sale al volver a encender.
2. Candidatas: `pending` con `not_before <= now`, por `id`, hasta `limit`, bajo
   `FOR UPDATE SKIP LOCKED`: lo que otra corrida tiene tomado ni se ve.
3. Unidades, en el orden de su primera candidata: el GRUPO (`group_key`, con
   TODAS sus filas `pending`, aunque el `limit` haya dejado fuera alguna) o la
   fila suelta. Un grupo cuya fila más nueva tiene `created_at > now - espera`
   (`MailSettings.digest_minutes()`) sigue recibiendo movimientos: no se toca
   (`waiting`, D7).
4. Cada unidad, en este orden: proceso revocado → `obsolete` («inscripción
   revocada»: su aviso es la fila `process_cancelled`); sin correo personal
   (`StudentMail.contact_email`) → `no_recipient`; `MailComposer.compose` →
   `Obsolete` → `obsolete` con su motivo; si no, `email_helper.deliver_detailed`.
   Las filas de INSCRIPCIÓN (`ENROLLMENT_KINDS`, spec 2026-10-05-titulatec-
   rendimiento-design.md §3.7) van por su propio camino
   (`_unidad_inscripcion`): sin el «revocado → obsoleto» del proceso (el aviso
   de la revocación ES una de ellas, y el del folio sale aunque después la
   revoquen), con el MISMO destinatario que su envío en línea
   (`_destinatarios_inscripcion`: el personal de la solicitud para el rechazo,
   el institucional para el folio y «ya inscrito», los dos para la revocación;
   sin ninguno, `no_recipient`) y, al salir, el sello que hoy escribía el
   servicio (`_SELLOS`: `rejection_sent_at`) en la MISMA transacción.
5. Salió → `sent` con `sent_at`, `sent_to` y `subject`, y `last_error` vacío
   (el motivo de un intento anterior ya no describe el correo). No salió →
   `attempts + 1` y `not_before = now + backoff_minutes(attempts)`; al llegar a
   `MailSettings.max_attempts()`, `failed`. `last_error` legible. Todas las
   filas de una unidad quedan con el mismo desenlace y el mismo conteo de
   intentos: el intento es del CORREO, no de cada fila.
6. E9 ampliado: sin cuenta de Graph y fuera de producción,
   `[TT-MAIL] kind -> destinatario · asunto · liga` al log. En producción, jamás.
   A `deliver_detailed` se le pasa `link=None` (ruling 12): su `[TT-VERIFY-LINK]`
   es de la liga de activación de la inscripción, no de estas.

Devuelve cuántas UNIDADES (correos) terminaron en cada desenlace:
`{"sent", "failed", "retry", "no_recipient", "obsolete", "waiting"}`.

TRANSACCIONES Y CONCURRENCIA (Review Focus 1: la misma fila jamás sale dos veces)
- Una unidad = una transacción, con `commit` al cerrarla. Ese commit suelta
  TODOS los candados, también los de la selección; por eso cada unidad vuelve a
  tomar sus filas (`FOR UPDATE SKIP LOCKED`, solo si siguen `pending`, con
  `populate_existing`: nada de lo que hay en memoria se da por bueno). Lo que
  otra corrida tomó o ya mandó entretanto se salta.
- Un grupo del que otra corrida tiene alguna fila se deja entero para después:
  si no, saldrían dos correos con mitades del grupo.
- Excepción inesperada en una unidad (componer, renderizar, enviar…):
  `rollback` y, en una transacción nueva, intento fallido de todas sus filas
  con «Error interno al preparar el correo» (ruling 2026-09-29): si no, se
  reintentaría en cada corrida sin fin y jamás se vería «Falló» en el
  expediente.
  El lote sigue con la siguiente unidad.
- Que celery corte la tarea (`SoftTimeLimitExceeded`) TAMBIÉN es un intento
  fallido de la unidad en curso («Tiempo agotado al enviar», ruling 14):
  `rollback`, el intento en una transacción nueva, y se vuelve a lanzar (el
  lote termina ahí). Sin contarlo, un Graph colgado se reintentaría en cada
  corrida sin tope. Si el corte cae DENTRO de `graph_send_mail`, lo atrapa
  `email_helper._send` (compartido con los correos de inscripción, que no
  cambian) como cualquier error de envío: cuenta como «Error al enviar» y la
  corrida termina por el presupuesto. Para no llegar al corte, la corrida deja
  de tomar unidades pasado `_PRESUPUESTO_S`; lo que quedó lo toma la
  siguiente.
- Entrega «al menos una vez»: se envía y DESPUÉS se marca. Si el commit que
  marca `sent` fallara, el correo volvería a salir; por eso lo que se escribe
  tras un envío siempre cabe en su columna (`_cabe`).

El reloj es `now`: por omisión `db_now()`, la hora local naive que escribe
`NOW()` en Postgres (con ella nacen `created_at` y `not_before`).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import func
from sqlalchemy.orm import Session

from itcj2.core.utils.timezone import db_now

logger = logging.getLogger(__name__)

# Lo que cuenta `run`, uno por unidad.
_DESENLACES = ("sent", "failed", "retry", "no_recipient", "obsolete", "waiting")

# Clase de unidad: `(_GRUPO, group_key)` o `(_SUELTA, id)`.
_GRUPO, _SUELTA = "grupo", "fila"

# Tope de la espera entre intentos (1, 2, 4, 8, 16, 32… minutos).
_BACKOFF_TOPE_MIN = 60

# Presupuesto de una corrida: pasado este tiempo no se toma otra unidad. La
# tarea tiene `soft_time_limit=50` y un envío puede tardar hasta 30 s (el
# `timeout` de `graph_send_mail`): la unidad que empieza dentro del presupuesto
# termina antes del corte. Lo que queda sale en la corrida siguiente (cada 5
# minutos). `_reloj` es el reloj monotónico (las pruebas lo sustituyen).
_PRESUPUESTO_S = 15
_reloj = time.monotonic

# Código de `deliver_detailed` → `last_error` legible (bitácora del expediente).
_MOTIVOS = {
    "cuenta_no_conectada": "Cuenta de correo no conectada",
    "plantilla": "Error en la plantilla",
    "envio": "Error al enviar",
}
_ERROR_INTERNO = "Error interno al preparar el correo"
_TIEMPO_AGOTADO = "Tiempo agotado al enviar"
_REVOCADA = "inscripción revocada"
_SIN_PROCESO = "el proceso o su alumno ya no existe"

# Correo de inscripción -> columna de la SOLICITUD que se sella al salir (la que
# hoy escribía el servicio tras el envío en línea). Los otros tres no tienen.
_SELLOS = {"enrollment_rejected": "rejection_sent_at"}


def _unidades(candidatas: list) -> list[tuple[str, object]]:
    """Unidades en el orden de su primera candidata (las filas de un grupo
    forman UNA)."""
    vistas: dict[tuple[str, object], None] = {}
    for fila in candidatas:
        unidad = (_GRUPO, fila.group_key) if fila.group_key else (_SUELTA, fila.id)
        vistas.setdefault(unidad, None)
    return list(vistas)


def _cargar(db: Session, candidatas: list) -> tuple[dict, dict]:
    """Procesos y alumnos de las candidatas en dos consultas, no dos por unidad."""
    from itcj2.apps.titulatec.models import TitulationProcess
    from itcj2.core.models.user import User

    pids = {f.process_id for f in candidatas if f.process_id is not None}
    if not pids:
        return {}, {}
    procesos = {p.id: p for p in
                db.query(TitulationProcess).filter(TitulationProcess.id.in_(pids)).all()}
    uids = {p.student_id for p in procesos.values()}
    alumnos = ({u.id: u for u in db.query(User).filter(User.id.in_(uids)).all()}
               if uids else {})
    return procesos, alumnos


def _tomar(db: Session, unidad: tuple[str, object], now: datetime) -> list | None:
    """Toma con candado las filas `pending` de la unidad, frescas de la BD, o
    `None` si aquí ya no hay nada que hacer: otra corrida la mandó, la tiene
    tomada (en un grupo basta UNA fila) o la reprogramó para después."""
    from itcj2.apps.titulatec.models import EmailOutbox

    clase, llave = unidad
    de_la_unidad = (EmailOutbox.group_key == llave if clase == _GRUPO
                    else EmailOutbox.id == llave)
    filas = (db.query(EmailOutbox)
             .filter(EmailOutbox.status == "pending", de_la_unidad)
             .order_by(EmailOutbox.id)
             .with_for_update(skip_locked=True)
             .populate_existing()
             .all())
    if not filas:
        return None
    if clase == _GRUPO:
        pendientes = (db.query(func.count(EmailOutbox.id))
                      .filter(EmailOutbox.status == "pending", de_la_unidad)
                      .scalar())
        if pendientes != len(filas):
            logger.info("[titulatec] Correos: otra corrida tiene parte del grupo %s; "
                        "se deja para después", llave)
            return None
    if not any(f.not_before <= now for f in filas):
        return None
    return filas


def _cabe(valor: str | None, columna: str) -> str | None:
    """`valor` recortado al largo de su columna del outbox."""
    from itcj2.apps.titulatec.models import EmailOutbox

    if valor is None:
        return None
    return valor[:EmailOutbox.__table__.c[columna].type.length]


def _cerrar(filas: list, status: str, motivo: str | None = None) -> str:
    """Desenlace final sin envío (`obsolete`, `no_recipient`)."""
    for fila in filas:
        fila.status = status
        if motivo is not None:
            fila.last_error = _cabe(motivo, "last_error")
    return status


def _fallar(filas: list, now: datetime, motivo: str) -> str:
    """Intento fallido de la unidad: otra espera, o `failed` al llegar al tope."""
    from itcj2.apps.titulatec.services.student_mail import MailSettings

    intento = max(f.attempts or 0 for f in filas) + 1
    agotado = intento >= MailSettings.max_attempts()
    espera = timedelta(minutes=MailDispatcher.backoff_minutes(intento))
    for fila in filas:
        fila.attempts = intento
        fila.last_error = _cabe(motivo, "last_error")
        if agotado:
            fila.status = "failed"
        else:
            fila.not_before = now + espera
    return "failed" if agotado else "retry"


def _primera(filas: list):
    """La fila del primer evento de la unidad: orden `(created_at, id)`, el
    mismo del compositor."""
    return min(filas, key=lambda f: (f.created_at, f.id))


def _marcar_enviado(filas: list, now: datetime, to: str, subject: str) -> str:
    """Desenlace `sent`: `sent_at`, `sent_to`, `subject` y sin `last_error` (el
    motivo de un intento anterior ya no describe el correo que llegó)."""
    for fila in filas:
        fila.status = "sent"
        fila.sent_at = now
        fila.sent_to = _cabe(to, "sent_to")
        fila.subject = _cabe(subject, "subject")
        fila.last_error = None
    return "sent"


def _destinatarios_inscripcion(db: Session, kind: str, *, req, process, user) -> list[str]:
    """A quién va un correo de inscripción: EXACTAMENTE a quien lo mandaba
    `TitulaTecEmailHelper` en línea (spec 2026-10-05 §3.7, «el mismo que hoy»;
    tabla en el docstring de `email_helper`). El rechazo, al correo PERSONAL
    de la solicitud; el folio y «ya inscrito», al INSTITUCIONAL de la cuenta
    (E8: nunca al correo tecleado); la revocación, a los dos
    (`process_cancelled_recipients`, compartido con el envío en línea)."""
    from itcj2.apps.titulatec.services import email_helper
    from itcj2.core.utils.email_tools import student_email

    if kind == "enrollment_rejected":
        correo = (req.contact_email or "").strip() if req is not None else ""
        return [req.contact_email] if correo else []
    if user is None:
        return []
    if kind == "process_cancelled":
        return email_helper.process_cancelled_recipients(db, process, user)
    correo = student_email(user)
    return [correo] if correo else []


class MailDispatcher:
    """Manda lo pendiente de la bandeja de salida. Contrato completo en el
    docstring del módulo."""

    @staticmethod
    def backoff_minutes(attempt: int) -> int:
        """Minutos de espera tras el intento fallido número `attempt`:
        1, 2, 4, 8, 16, 32 (`2 ** (attempt - 1)`), con tope de 60."""
        return min(2 ** (max(attempt, 1) - 1), _BACKOFF_TOPE_MIN)

    @staticmethod
    def run(db: Session, *, now: datetime | None = None, limit: int = 50) -> dict:
        """Una corrida: `{"disabled": True}` con el correo apagado; si no,
        cuántas unidades terminaron en cada desenlace."""
        from itcj2.apps.titulatec.services.student_mail import MailSettings

        if not MailSettings.enabled():
            return {"disabled": True}
        from itcj2.apps.titulatec.models import EmailOutbox

        now = now or db_now()
        inicio = _reloj()
        out = dict.fromkeys(_DESENLACES, 0)
        candidatas = (db.query(EmailOutbox)
                      .filter(EmailOutbox.status == "pending",
                              EmailOutbox.not_before <= now)
                      .order_by(EmailOutbox.id)
                      .limit(limit)
                      .with_for_update(skip_locked=True)
                      .all())
        procesos, alumnos = _cargar(db, candidatas)
        for unidad in _unidades(candidatas):
            if _reloj() - inicio >= _PRESUPUESTO_S:
                logger.info("[titulatec] Correos: se agotó el presupuesto de %s s de la "
                            "corrida; lo que falta sale en la siguiente", _PRESUPUESTO_S)
                break
            desenlace = MailDispatcher._despachar(db, unidad, now, procesos, alumnos)
            if desenlace is not None:
                out[desenlace] += 1
        db.commit()          # sin unidades, cierra la selección (suelta sus candados)
        return out

    @staticmethod
    def _despachar(db: Session, unidad: tuple[str, object], now: datetime,
                   procesos: dict, alumnos: dict) -> str | None:
        """Una unidad en su propia transacción. Una excepción inesperada es un
        intento fallido (registrado en otra transacción) y el lote sigue; el
        corte de celery también es un intento fallido, pero se vuelve a lanzar
        y el lote termina ahí."""
        try:
            desenlace = MailDispatcher._unidad(db, unidad, now, procesos, alumnos)
            db.commit()
            return desenlace
        except SoftTimeLimitExceeded:
            db.rollback()
            logger.warning("[titulatec] Celery cortó el despacho a media unidad (%s %s): "
                           "cuenta como intento", *unidad)
            MailDispatcher._intento_fallido(db, unidad, now, _TIEMPO_AGOTADO)
            raise
        except Exception:
            db.rollback()
            logger.exception("[titulatec] Error interno al despachar el correo (%s %s)",
                             *unidad)
            return MailDispatcher._intento_fallido(db, unidad, now, _ERROR_INTERNO)

    @staticmethod
    def _intento_fallido(db: Session, unidad: tuple[str, object], now: datetime,
                         motivo: str) -> str | None:
        """Tras el `rollback` de una unidad que reventó: en una transacción NUEVA,
        intento fallido de todas sus filas (`retry` o `failed` al tope). Nunca
        lanza: si ni esto se puede, queda en el log y la fila sigue `pending`."""
        try:
            filas = _tomar(db, unidad, now)
            desenlace = None if filas is None else _fallar(filas, now, motivo)
            db.commit()
            return desenlace
        except Exception:
            db.rollback()
            logger.exception("[titulatec] No se pudo registrar el intento fallido del "
                             "correo (%s %s)", *unidad)
            return None

    @staticmethod
    def _unidad(db: Session, unidad: tuple[str, object], now: datetime,
                procesos: dict, alumnos: dict) -> str | None:
        """Decide el desenlace de la unidad y, si toca, manda su correo. No
        hace commit (lo hace `_despachar`); `None` = nada que hacer aquí."""
        from itcj2.apps.titulatec.models import TitulationProcess
        from itcj2.apps.titulatec.models.email_outbox import ENROLLMENT_KINDS
        from itcj2.apps.titulatec.services import email_helper
        from itcj2.apps.titulatec.services.mail_compose import MailComposer, Obsolete
        from itcj2.apps.titulatec.services.student_mail import MailSettings, StudentMail
        from itcj2.core.models.user import User

        filas = _tomar(db, unidad, now)
        if filas is None:
            return None
        if unidad[0] == _GRUPO:
            espera = timedelta(minutes=MailSettings.digest_minutes())
            if max(f.created_at for f in filas) > now - espera:
                return "waiting"
        if any(f.kind in ENROLLMENT_KINDS for f in filas):
            return MailDispatcher._unidad_inscripcion(db, filas, now, procesos, alumnos)

        pid = filas[0].process_id
        process = None
        if pid is not None:
            process = procesos.get(pid) or db.get(TitulationProcess, pid)
        user = None
        if process is not None:
            user = alumnos.get(process.student_id) or db.get(User, process.student_id)
        if process is None or user is None:
            return _cerrar(filas, "obsolete", _SIN_PROCESO)
        if process.status == "cancelled":
            return _cerrar(filas, "obsolete", _REVOCADA)
        to = StudentMail.contact_email(db, process)
        if not to:
            return _cerrar(filas, "no_recipient")
        correo = MailComposer.compose(db, filas, process, user)
        if isinstance(correo, Obsolete):
            return _cerrar(filas, "obsolete", correo.reason)

        kind = _primera(filas).kind
        # `link=None` (ruling 12): el E9 de `deliver_detailed` (`[TT-VERIFY-LINK]`)
        # es de la liga de ACTIVACIÓN; la de este correo sale en el `[TT-MAIL]` de abajo.
        ok, error = email_helper.deliver_detailed(
            template=correo.template, context=correo.context, subject=correo.subject,
            to=to, que=f"mail:{kind}", link=None)
        if ok:
            return _marcar_enviado(filas, now, to, correo.subject)
        if error == "cuenta_no_conectada" and not email_helper._is_production():
            logger.warning("[TT-MAIL] %s -> %s · %s · %s",
                           kind, to, correo.subject, correo.link)
        return _fallar(filas, now, _MOTIVOS.get(error, _MOTIVOS["envio"]))

    @staticmethod
    def _unidad_inscripcion(db: Session, filas: list, now: datetime,
                            procesos: dict, alumnos: dict) -> str:
        """Un correo de inscripción (spec 2026-10-05 §3.7; siempre fila
        suelta). Resuelve la solicitud, el proceso y el alumno de la fila; el
        compositor re-valida (D8); sale UN mensaje con todos los destinatarios
        de `_destinatarios_inscripcion` en «Para» (como el envío en línea de la
        revocación); al salir, `sent_to` lleva esos buzones y la solicitud
        recibe su sello (`_SELLOS`) en esta misma transacción. Si no sale,
        intento fallido con su motivo. No hace commit (lo hace `_despachar`)."""
        from itcj2.apps.titulatec.models import EnrollmentRequest, TitulationProcess
        from itcj2.apps.titulatec.services import email_helper
        from itcj2.apps.titulatec.services.mail_compose import MailComposer, Obsolete
        from itcj2.core.models.user import User

        fila = filas[0]
        process = user = req = None
        if fila.process_id is not None:
            process = procesos.get(fila.process_id) or db.get(TitulationProcess,
                                                               fila.process_id)
        if fila.user_id is not None:
            user = alumnos.get(fila.user_id) or db.get(User, fila.user_id)
        if fila.enrollment_request_id is not None:
            req = db.get(EnrollmentRequest, fila.enrollment_request_id)
        if ((fila.process_id is not None and process is None)
                or (fila.user_id is not None and user is None)):
            return _cerrar(filas, "obsolete", _SIN_PROCESO)

        correo = MailComposer.compose(db, filas, process, user)
        if isinstance(correo, Obsolete):
            return _cerrar(filas, "obsolete", correo.reason)
        destinos = _destinatarios_inscripcion(db, fila.kind, req=req, process=process,
                                              user=user)
        if not destinos:
            return _cerrar(filas, "no_recipient")

        # UN solo mensaje de Graph con todos los destinatarios (la revocación va
        # al institucional y al personal: la misma persona). Uno por buzón eran
        # dos esperas de hasta 30 s contra el `soft_time_limit=50` de la tarea,
        # y un corte o un fallo en el segundo reintentaba también el primero.
        ok, error = email_helper.deliver_detailed(
            template=correo.template, context=correo.context, subject=correo.subject,
            to=destinos, que=f"mail:{fila.kind}", link=None)
        if ok:
            columna = _SELLOS.get(fila.kind)
            if columna is not None and req is not None:
                setattr(req, columna, now)
            return _marcar_enviado(filas, now, ", ".join(destinos), correo.subject)
        if error == "cuenta_no_conectada" and not email_helper._is_production():
            logger.warning("[TT-MAIL] %s -> %s · %s · %s", fila.kind, ", ".join(destinos),
                           correo.subject, correo.link)
        return _fallar(filas, now, _MOTIVOS.get(error, _MOTIVOS["envio"]))
