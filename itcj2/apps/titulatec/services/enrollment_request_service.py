"""Solicitudes de auto-inscripción a una convocatoria de titulación.

FLUJO (2026-09-24; manda sobre el de 2026-09-15 y sobre §6.6-6.10 del diseño
original; spec `2026-09-24-titulatec-accesos-centro-computo-design.md` §3).
Toda solicitud pasa por una revisión y el acceso llega SOLO por correo. Quién
revisa lo decide `reviewer_mode()` (TITULATEC_ENROLLMENT_REVIEWER): en el modo
OFICIAL Servicios Escolares (SE) aprueba y Centro de Cómputo (CC) da el NIP; en
el ALTERNO, CC hace las dos cosas en un paso.

    create()                 ─► pending_review                          (sin correo)
    approve() [SE, oficial]  ─┬─ CON cuenta ─► approved                 liga al correo personal
                              └─ SIN cuenta ─► awaiting_access          SIN correo
    approve() [CC, alterno]  ─┬─ CON cuenta ─► approved                 liga
                              └─ SIN cuenta ─► converted                usuario + NIP (un paso)
    approve() [SE, sii]      ─┬─ CON cuenta ─► approved                 liga
                              ├─ SIN cuenta ─► converted                NIP DEL SII (correo sin NIP)
                              └─ SIN cuenta, to_access ─► awaiting_access  SIN correo (Accesos
                                 da el NIP). Si el SII no da un NIP válido al aprobar, nada
                                 se escribe y la bandeja ofrece esta rama.
                                 (el SII solo INFORMA —veredicto, reglas y estado del NIP en
                                 la bandeja—; nada se aprueba solo: ver eligibility_service.py)
    grant_access() [CC]      ─── awaiting_access ─┬─ SIN cuenta ─► converted  usuario + NIP
                                                  └─ CON cuenta (D10) ─► approved  liga
    return_to_review() [CC]  ─── awaiting_access ─► pending_review      return_note, sin correo
    verify() [liga]          ─── approved ─► converted | pending_review (review_note)
    reject() [SE | CC alt.]  ─── pending_review | awaiting_access | approved | legado
                                 ─► rejected                            (correo; la liga muere)
    reopen() [SE]            ─── rejected ─► pending_review             reopen_note (aclaró en
                                 ventanilla), sin correo; luego se aprueba normal
    reassign_nip() [CC]      ─── converted (cuenta creada por la solicitud y que
                                 nunca ha iniciado sesión) ─► converted  NIP nuevo
                                 (+ correo, u omitido para dictarlo por teléfono)
    resend_access_notice() [SE, sii] ─ converted (NIP DEL SII, correo no salió)
                                 ─► converted  el mismo correo SIN NIP; ninguna credencial

El alumno no se entera de `awaiting_access`: ni correo al aprobar ni al
devolver. `unverified` y `verified` son estados LEGADO del flujo con liga
previa: ya no se escriben, pero sus filas se pueden aprobar o rechazar.

"¿TIENE CUENTA?" SE DECIDE CONTRA `core_users` AL MOMENTO, nunca con `kind` (que
`create()` guarda solo para mostrar): al aprobar y OTRA VEZ al dar acceso (D10).
Si un CSV o un alta manual creó la cuenta entre SE y CC, «dar acceso» se desvía
a la liga y el NIP se ignora: crear otra cuenta chocaría con la real y el NIP
pisaría su contraseña.

RIESGO ACEPTADO Y SU CONTENCIÓN (invariante; sustituye a los rulings R5, B1 y
D17). La liga de una cuenta existente viaja al correo que TECLEÓ el solicitante:
quien escriba un número de control ajeno con su correo y pase la revisión puede
dejar inscrita a esa persona. En el modo `sii` la bandeja muestra además si el
NOMBRE tecleado es el del SII (`eligibility_service.identity_block`), pero la
revisión sigue siendo de SE. Para que no escale:

  1. Sobre una cuenta que NO creó la solicitud JAMÁS se escribe
     `password_hash`, `must_change_password` ni `core_student_profile`, ni en
     `approve()`, ni en `grant_access()`, ni en `verify()`/`_convert()`, ni en
     `reassign_nip()` (que solo acepta la cuenta que creó ESA solicitud y que
     nunca ha iniciado sesión —`last_login` nulo—: `can_reassign_nip` más la
     señal positiva `_request_created_account`, porque una cuenta del CSV que
     llegó por D10 también nace con `must_change_password` y dueña del
     proceso). Lo único
     que recibe es el proceso y los roles de egresado (`graduate`, que
     desplaza a `student`; ver `ImportService.import_rows`).
     EXCEPCIÓN APROBADA (2026-09-15): abrir la liga pasa `is_active` de False a
     True. Sin eso la persona quedaba inscrita sin poder entrar. El riesgo es
     reactivar una cuenta que alguien desactivó a propósito, y se contiene así:
     solo lo hace la liga de una solicitud APROBADA (nunca `approve()`, que
     únicamente la emite); la bandeja pinta «Cuenta desactivada: se reactiva al
     abrir la liga» antes de aprobar; la contraseña no cambia, así que quien
     tecleó un control ajeno sigue sin poder entrar; el aviso con folio va al
     institucional (3), y el `ProcessEvent` registra `reactivated: true`.
  2. Una cuenta existente sin `password_hash` no recibe liga: se da de alta
     desde la convocatoria.
  3. El aviso con folio de `verify()` va al buzón INSTITUCIONAL de la cuenta:
     es la alarma de su dueña, y no depende de nada que se tecleó.
  4. No hay segunda liga. La de contacto canjeaba contra el perfil con la sola
     prueba del buzón tecleado: dejó de emitirse y el 2026-09-15 se retiró
     también su canje (`confirm_contact`, `GET /titulatec/inscripcion/correo` y
     la plantilla). Sus columnas quedan en la BD como legado sin uso.

Una cuenta NUEVA solo conoce su NIP por el correo que manda `_mail_access()`
(tras `grant_access`, el `approve` alterno o `reassign_nip`). EL NIP NUNCA SALE de
otra forma: ni al log, ni al `detalle` que la ruta pone en `X-Tt-Error`, ni al
payload de un `ProcessEvent`.

«CORREO NO ENVIADO» (D8) es `access_mail_unsent(req)`: `converted`, SIN liga
(`verify_token_hash` nulo), `access_granted_at` lleno y `access_sent_at` nulo.
NO es solo «granted lleno y sent nulo»: la rama con liga de `grant_access` (D10)
sella `access_granted_*` y nunca `access_sent_at` (su envío va en
`verify_sent_at`), y la rama de fallo de `verify()` devuelve esa fila a
`pending_review` SIN limpiar `access_granted_*`. Por lo mismo, «tiene
`access_granted_at`» no implica `converted`: una D10 devuelta lo conserva.
Reasignar el NIP es otra pregunta (`can_reassign_nip` + la señal positiva de
`reassign_nip`) y no depende de `access_sent_at`.

TOKEN (E7). La BD guarda SOLO `sha256(token)` y la comparación decisiva usa
`hmac.compare_digest`. El texto claro vive en Redis bajo `tt:enroll:tok:<sha256>`
lo mismo que la liga, y solo para que el reenvío PÚBLICO no rote: rotar desde un
endpoint anónimo dejaría a un extraño matar la liga de otra persona. Sin esa
copia el reenvío público falla CERRADO. La bandeja sí rota: su actor está
autenticado y acotado por carrera.

CORREO E INVALIDACIÓN DE AUTHZ SIEMPRE DESPUÉS DEL COMMIT. `msgraph_mail` es un
`requests.post` síncrono: dentro de la transacción retendría los advisory
locks, y un correo mandado antes de un commit que falla habla de algo que no
existe. Ningún método del helper lanza, así que un fallo de buzón no revierte
nada ya commiteado. El caché de authz, tirado antes del commit, lo repoblaría
una lectura concurrente con los roles de antes. Desde 2026-10-05 (spec
`2026-10-05-titulatec-rendimiento-design.md` §3.7, P-D1) los correos SIN
secreto de este módulo —el aviso con folio de `verify`, el rechazo de
`reject` y el «ya tienes un proceso» de `create`— ni siquiera salen aquí: se
ENCOLAN en `titulatec_email_outbox` dentro de la transacción (`StudentMail`) y
los manda el despachador. Solo con el correo apagado salen en línea, después
del commit, como antes. Los que llevan liga o NIP no cambian.

VENTANA (D5, spec 2026-09-24). `opens_at`/`closes_at` solo filtran el formulario
público (`CohortService.is_public_enrollment_open`, en la ruta). Todo lo que
sigue a una solicitud ya enviada —`approve`, `grant_access`, `verify`/`_convert`,
`resend_link` y `resend`— exige solo `status == 'open'`
(`CohortService.accepts_enrollment_followup`): una convocatoria `closed` pausa
sus procesos y tampoco emite ni canjea ligas, pero pasar `closes_at` no deja
varada a nadie que entró a tiempo. La liga vive `_link_ttl_hours()`.

CONCURRENCIA. Toda transición de una solicitud (`approve`, `grant_access`,
`return_to_review`, `reassign_nip`, `verify`, `reject`, `reopen`, `resend_link`,
`resend`, `resend_access_notice`) toma
`pg_advisory_xact_lock(_REQUEST_LOCK_NS, req.id)` y hace `db.refresh(req)`
ANTES de leer el estado: bajo READ COMMITTED, quien esperó el lock puede seguir
teniendo en memoria el estado de antes de esperarlo. Los tests estructurales de
cada método fijan ese orden.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
from datetime import date, datetime, timedelta
from typing import NamedTuple

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from itcj2.apps.titulatec.services.email_helper import PUBLIC_ORIGIN
from itcj2.apps.titulatec.services.import_service import CONTROL_NUMBER_RE

logger = logging.getLogger("itcj2.apps.titulatec.enrollment_request")

STATUSES = ("unverified", "verified", "pending_review", "approved", "rejected", "converted",
            "awaiting_access")

# Desde dónde la bandeja aprueba (y rechaza, junto con `approved` y
# `awaiting_access`). `awaiting_access` NO es aprobable: SE ya la aprobó, y
# volver a aprobarla da su propio motivo (`_MSG_IN_ACCESS`).
_REVIEWABLE = ("pending_review", "unverified", "verified")
_REJECTABLE = _REVIEWABLE + ("approved", "awaiting_access")

# Agrupa los 7 STATUSES en los 5 cubos que pinta la bandeja (KPIs y "por año de
# ingreso", `EnrollmentRequestService.stats`): el legado `unverified`/`verified`
# cuenta como "por revisar", igual que en `_TAB_STATUSES` de `pages/requests_admin.py`.
_STATUS_GROUP = {s: "review" for s in _REVIEWABLE}
_STATUS_GROUP.update(awaiting_access="access", approved="sent", converted="converted",
                     rejected="rejected")

# Quién revisa en cada modo (`TITULATEC_ENROLLMENT_REVIEWER`); lo leen los textos
# públicos y los correos vía `EnrollmentRequestService.reviewer_label()`.
_REVIEWER_LABELS = {
    "school_services": "Servicios Escolares",
    "computer_center": "Centro de Cómputo",
    # Modo `sii` (por omisión, spec 2026-09-27): el SII solo INFORMA (veredicto
    # + NIP); quien aprueba y responde por la solicitud (rechazos, excepciones)
    # sigue siendo SE, igual que en el modo oficial.
    "sii": "Servicios Escolares",
}

# `control_number` -> año de ingreso, para el bloque "Por año de ingreso" de la
# bandeja. `CONTROL_NUMBER_RE` (import_service.py) ya exige `^[A-Za-z]?\d{8}$`;
# esto solo lee los 2 dígitos que siguen a la letra opcional, así que tolera un
# control legado o mal formado sin reventar (cae a "Sin año").
_ENTRY_YEAR_RE = re.compile(r"^[A-Za-z]?(\d{2})")

# EL NIP: 4 dígitos ASCII. `[0-9]`, no `\d`: en `re` de Python `\d` también
# casa dígitos Unicode («１２３４», «١٢٣٤») que nadie puede teclear en el login.
# Única regla: `nip_format_ok`, que usan `_create_account`, `reassign_nip` y
# `EligibilityService.classify_sii_nip`.
_NIP_RE = re.compile(r"[0-9]{4}")


def nip_format_ok(nip: str | None) -> bool:
    """¿`nip` sirve como NIP (exactamente 4 dígitos ASCII, `_NIP_RE`)? La
    ÚNICA regla del NIP: la usan `_create_account` y `reassign_nip`, y
    `EligibilityService.classify_sii_nip` para decir si el del SII serviría
    SIN mostrarlo — a través de ella la aplican la consulta al SII, la
    aprobación del modo `sii` y `sii-check`."""
    return bool(_NIP_RE.fullmatch(nip or ""))


def entry_year(control: str | None, today: date | None = None) -> str:
    """Año de ingreso a 4 dígitos, o `"Sin año"` si el control no case (o es `None`).

    Pivote dinámico sobre los 2 últimos dígitos del año actual (o `today`,
    inyectable para test): `yy <= hoy % 100` -> `2000 + yy`; si no, `1900 + yy`.
    Ej. con hoy=2026: 26 -> 2026, 21 -> 2021, 90 -> 1990.
    """
    m = _ENTRY_YEAR_RE.match((control or "").strip())
    if not m:
        return "Sin año"
    yy = int(m.group(1))
    pivote = (today or date.today()).year % 100
    return str(2000 + yy if yy <= pivote else 1900 + yy)


# La MISMA lectura que `_ENTRY_YEAR_RE`, en el dialecto de Postgres: el `\s*`
# hace lo que el `.strip()` de `entry_year` (un espacio al frente no cambia el
# año). `[0-9]` y no `\d`: los controles reales son ASCII (`CONTROL_NUMBER_RE`).
_ENTRY_YEAR_SQL = r"^\s*[A-Za-z]?([0-9]{2})"


def entry_year_filter(column, year: str | None, today: date | None = None):
    """Predicado SQL «`entry_year(column) == year`», o `None` si `year` no sirve.

    El filtro «Año de ingreso» de la bandeja: va en la consulta (la bandeja
    pagina), con la MISMA regla que `entry_year`, que es la que cuenta el bloque
    «Por año de ingreso» — si se separan, el filtro y el conteo discrepan
    (lo fija `test_requests_filters.py`). `year` es un año de 4 dígitos que el
    pivote de hoy produzca (con hoy=2026, «2090» no existe: 90 se lee 1990) o
    `"Sin año"` (control que no empieza con 2 dígitos tras la letra opcional).
    """
    from sqlalchemy import func, not_, or_

    if year == "Sin año":
        return or_(column.is_(None), not_(column.op("~")(_ENTRY_YEAR_SQL)))
    if not (isinstance(year, str) and len(year) == 4 and year.isascii() and year.isdigit()):
        return None
    yy = f"{int(year) % 100:02d}"
    if entry_year(yy, today) != year:
        return None
    return func.substring(column, _ENTRY_YEAR_SQL) == yy


def enrollment_request_search(q):
    """Predicado de búsqueda sobre `EnrollmentRequest`, o `None` sin búsqueda.

    Constructor ÚNICO de la búsqueda de solicitudes: lo usan la bandeja de
    Solicitudes (`pages/requests_admin.py::_body_ctx`) y la de Accesos
    (spec 2026-10-04 §4-§5, Ruling R1). `q` se normaliza aquí
    (`utils.paging.normalize_q`: `strip()`, 100 caracteres, vacío = `None`).

    Casa, en `ILIKE` con `\\`, `%` y `_` escapados (`like_pattern`): número de
    control (y, exacto, en MAYÚSCULA: la forma de `CONTROL_NUMBER_RE`), el
    nombre en el orden del formulario (nombre, paterno, materno) y en el de la
    bandeja (paterno, materno, nombre), el correo de contacto y el folio del
    proceso en que se convirtió (`converted_process_id`, subconsulta `IN`).

    Uso: `cond = enrollment_request_search(q)`; `if cond is not None:
    query = query.filter(cond)`.
    """
    from sqlalchemy import func, or_, select

    from itcj2.apps.titulatec.models import EnrollmentRequest, TitulationProcess
    from itcj2.apps.titulatec.utils.paging import like_pattern, normalize_q

    q = normalize_q(q)
    if q is None:
        return None
    p = like_pattern(q)
    er = EnrollmentRequest
    return or_(
        er.control_number.ilike(p, escape="\\"),
        er.control_number == q.upper(),
        func.concat_ws(" ", er.first_name, er.last_name, er.middle_name).ilike(p, escape="\\"),
        func.concat_ws(" ", er.last_name, er.middle_name, er.first_name).ilike(p, escape="\\"),
        er.contact_email.ilike(p, escape="\\"),
        er.converted_process_id.in_(
            select(TitulationProcess.id).where(TitulationProcess.folio.ilike(p, escape="\\"))),
    )

# La vida de la liga NO es una constante: `EnrollmentRequestService._link_ttl_hours()`
# (TITULATEC_ENROLLMENT_LINK_TTL_DAYS, 21 días por omisión).
MAX_VERIFY_SENDS = 3             # tope del reenvío PÚBLICO; la bandeja no lo tiene
MIN_SECONDS_BETWEEN_SENDS = 300
MAX_PUBLIC_BODY_BYTES = 256 * 1024

# Alias del origen público único (`email_helper.PUBLIC_ORIGIN`, spec 2026-09-28
# C7): las ligas de correo salen de ahí, nunca del `Host` de la petición (que el
# cliente controla). Conserva el nombre porque lo usan `_verify_link` y sus pruebas.
PUBLIC_BASE_URL = PUBLIC_ORIGIN

# Prefijo de Redis del TEXTO CLARO del token. La llave es el propio hash, así que
# una entrada rancia jamás puede aplicarse a otra solicitud.
_TOKEN_CACHE_PREFIX = "tt:enroll:tok:"

# Namespace del advisory lock POR SOLICITUD. Distinto de `_FOLIO_LOCK_NS`
# (`import_service.py`, por convocatoria) para que un id de solicitud y uno de
# convocatoria del mismo número no se bloqueen entre sí. Orden global: solicitud
# y luego folios (`approve` y `verify` toman este antes de `import_rows`); nadie
# toma el de folios primero, así que no hay ciclo.
_REQUEST_LOCK_NS = 0x7456  # "tV"

# Lo que ve el oficial en `X-Tt-Error` o en la `review_note` de una solicitud
# devuelta a revisión. Nunca el NIP.
_MSG_GONE = "La solicitud ya no existe."
_MSG_ALREADY_APPROVED = "Esa solicitud ya fue aprobada; usa Reenviar liga."
_MSG_RESOLVED = "Esa solicitud ya se resolvió."
_MSG_NO_COHORT = "La convocatoria ya no existe."
_MSG_COHORT_CLOSED = "Esa convocatoria está cerrada."
_MSG_BAD_DATA = "El número de control o el nombre no tienen formato válido."
_MSG_BAD_NIP = "El NIP debe ser exactamente 4 dígitos."
_MSG_OTHER_COHORT = "Esa persona ya tiene un proceso en otra convocatoria."
_MSG_REVOKED_HERE = ("Esa persona tiene una inscripción revocada en esta convocatoria; "
                     "solo puede inscribirse en otra.")
_MSG_NO_PASSWORD = ("Esa cuenta no tiene contraseña; dala de alta desde la convocatoria "
                    "y rechaza esta solicitud.")
# Los mismos dos motivos, dichos a Centro de Cómputo en el modo oficial: no da
# de alta desde la convocatoria ni rechaza, pero sí devuelve a SE con nota.
_CC_OFFICIAL_MSGS = {
    _MSG_NO_PASSWORD: ("Esa cuenta no tiene contraseña; devuélvela a Servicios Escolares "
                       "con esa nota para que la dé de alta desde la convocatoria."),
    _MSG_OTHER_COHORT: ("Esa persona ya tiene un proceso en otra convocatoria; devuélvela "
                        "a Servicios Escolares con esa nota."),
}
_MSG_NO_PROCESS = "No se pudo crear el proceso; revisa los datos de la solicitud."
_MSG_ONLY_APPROVED = "Solo se reenvía la liga de solicitudes aprobadas."
_MSG_IN_ACCESS = "Ya está en Centro de Cómputo para su acceso."
_MSG_NOT_AWAITING = "Esa solicitud ya no está esperando acceso."
_MSG_RETURN_NOTE = "Escribe el motivo de la devolución."
_MSG_RETURN_NOTE_LONG = "El motivo de la devolución no puede pasar de 2000 caracteres."
_RETURN_NOTE_MAX = 2000
_MSG_NOT_REJECTED = "Esa solicitud ya no está rechazada."
_MSG_REOPEN_NOTE = "Escribe qué se aclaró con la persona."
_MSG_REOPEN_NOTE_LONG = "La nota no puede pasar de 2000 caracteres."
_MSG_REOPEN_OTHER_OPEN = ("Esa persona ya tiene otra solicitud en curso en esta "
                          "convocatoria; atiende esa.")
_MSG_REOPEN_OTHER_CONVERTED = ("Esa persona ya quedó inscrita en esta convocatoria "
                               "con otra solicitud.")
_MSG_NOT_REASSIGNABLE = ("Solo se reasigna el NIP de una cuenta que creó esta solicitud "
                         "y que nunca ha iniciado sesión.")
# «Reenviar aviso» (spec 2026-09-27 D12, `resend_access_notice`).
_MSG_NO_ACCESS_NOTICE = "Esa solicitud no tiene un aviso de acceso pendiente."
_MSG_ACCESS_NOTICE_NOT_SENT = "El correo no salió; intenta más tarde."
# Modo `sii` (spec 2026-09-25): la cuenta nueva nace con el NIP del SII. Si AL
# APROBAR el SII no da uno válido, el motivo por estado
# (`EligibilityService.classify_sii_nip`; spec 2026-09-27 §A4): la salida es
# pasar la solicitud a Accesos. Ningún mensaje lleva el valor.
_NIP_FAILURE_MSGS = {
    "missing": "El SII no tiene NIP para esta persona.",
    "invalid": "El NIP del SII no tiene un formato válido (4 dígitos).",
    "unavailable": "El SII no respondió al pedir el NIP.",
    "error": "No se pudo leer el NIP en el SII (revisa la configuración de las reglas).",
}
# Falla al CREAR la cuenta con el NIP del SII (`_create_account_with_sii_nip`):
# no es del NIP, así que nadie toca `nip_status` —sigue `available`— y la fila
# sigue ofreciendo «Aprobar y dar acceso» (`approval_path`). El motivo pide eso,
# reintentar; «pásala a Accesos» recomendaría un botón que esa fila no tiene.
_MSG_SII_ACCOUNT_FAILED = "No se pudo crear la cuenta con el NIP del SII; intenta de nuevo."
_NOTE_LINK_COHORT_CLOSED = "La convocatoria estaba cerrada cuando se abrió la liga de activación."
_NOTE_LINK_NO_ACCOUNT = "La cuenta de ese número de control ya no existe."
_NOTE_LINK_NO_PROCESS = ("No se pudo crear el proceso al abrir la liga; revisa los datos "
                         "de la solicitud.")

# De dónde salió el NIP de la cuenta que CREÓ la solicitud
# (`EnrollmentRequest.nip_source`, spec 2026-09-27 §A6): `sii` = el de la
# consulta al SII; `center` = el que capturó Centro de Cómputo en Accesos
# (`grant_access`); `form` = el del formulario del modo alterno. Lo escribe
# SOLO `_create_account`; «Con acceso» deja fuera las `sii`.
NIP_SOURCES = ("sii", "center", "form")

# Camino de aprobación que ofrece la bandeja (`approval_path`, Ruling R8) ->
# texto del botón. Lo leen la bandeja y `sii-check --cohort`, que así dicen lo
# mismo.
APPROVAL_LABELS = {
    "link": "Aprobar y enviar liga",
    "sii_nip": "Aprobar y dar acceso",
    "access": "Aprobar y pasar a Accesos",
}


class ApproveResult(NamedTuple):
    """Lo que devuelve `EnrollmentRequestService.approve_detailed`.

    `nip_failure` ∈ {missing, invalid, unavailable, error} SOLO cuando, en el
    modo `sii` con el SII configurado, sin cuenta y sin `to_access`, el SII no
    dio un NIP válido AL APROBAR: nada escrito de la solicitud y la bandeja
    ofrece pasarla a Accesos. En cualquier otro caso `None` (sin SII
    configurado, aprobar sin cuenta ya es pasarla a Accesos). `detail` nunca
    lleva el NIP.
    """
    ok: bool
    detail: str
    nip_failure: str | None


def _sha256(raw: str) -> str:
    return hashlib.sha256((raw or "").encode("utf-8")).hexdigest()


def _redis():
    try:
        from itcj2.core.utils.redis_conn import get_redis
        return get_redis()
    except Exception:
        return None


def _token_cache_put(raw: str) -> None:
    r = _redis()
    if r is None:
        return
    try:
        r.setex(_TOKEN_CACHE_PREFIX + _sha256(raw),
                EnrollmentRequestService._link_ttl_hours() * 3600, raw)
    except Exception as exc:
        logger.warning("No se pudo cachear el token de inscripción: %s", exc)


def _token_cache_get(digest: str) -> str | None:
    r = _redis()
    if r is None or not digest:
        return None
    try:
        val = r.get(_TOKEN_CACHE_PREFIX + digest)
    except Exception:
        return None
    if val is None:
        return None
    return val.decode("utf-8") if isinstance(val, bytes) else str(val)


def _token_cache_delete(digest: str | None) -> None:
    """Borra el claro de una liga que murió (rechazo, rotación). Best-effort:
    aunque la copia sobreviva, la BD ya no tiene el hash y nada la resuelve."""
    r = _redis()
    if r is None or not digest:
        return
    try:
        r.delete(_TOKEN_CACHE_PREFIX + digest)
    except Exception as exc:
        logger.warning("No se pudo borrar el token de inscripción de Redis: %s", exc)


def _verify_link(raw: str) -> str:
    return f"{PUBLIC_BASE_URL}/titulatec/inscripcion/verificar?t={raw}"


def _hash_ip(ip: str | None) -> str | None:
    """`sha256(ip + SECRET_KEY)`. La IP en claro nunca se guarda (§8.2)."""
    if not ip:
        return None
    from itcj2.config import get_settings
    return hashlib.sha256((ip + get_settings().SECRET_KEY).encode("utf-8")).hexdigest()


def _full_name(req) -> str:
    return " ".join(x for x in (req.last_name, req.middle_name, req.first_name) if x).strip()


def _audit_subject(req) -> str:
    """«nº control · nombre» de la solicitud, para la bitácora (spec 2026-10-07)."""
    return f"{(req.control_number or '').strip()} · {_full_name(req)}"


def _has_process_in_other_cohort(db: Session, user_id: int, cohort_id: int) -> bool:
    """D5 exceptuando la convocatoria de la solicitud: impide entrar a una SEGUNDA
    convocatoria, no atender la propia."""
    from itcj2.apps.titulatec.models import TitulationProcess

    return (db.query(TitulationProcess)
            .filter(TitulationProcess.student_id == user_id,
                    TitulationProcess.cohort_id != cohort_id,
                    TitulationProcess.status.in_(("active", "on_hold")))
            .first()) is not None


def _has_revoked_process_here(db: Session, user_id: int, cohort_id: int) -> bool:
    """¿La cuenta tiene una inscripción REVOCADA en esta misma convocatoria?

    D5 solo cuenta procesos vivos, así que una revocada no impide inscribirse
    en OTRA convocatoria. En la MISMA no se puede: hay una sola fila por
    `(alumno, convocatoria)` (`uq_titulatec_process_student_cohort`) e
    `import_rows` reutiliza la que encuentra, así que aprobar «convertía» la
    solicitud al proceso revocado y la persona seguía cancelada sin aviso.
    """
    from itcj2.apps.titulatec.models import TitulationProcess

    return (db.query(TitulationProcess.id)
            .filter(TitulationProcess.student_id == user_id,
                    TitulationProcess.cohort_id == cohort_id,
                    TitulationProcess.status == "cancelled")
            .first()) is not None


def _cohort_gate(db: Session, req):
    """Corte de convocatoria de la bandeja: `(cohort, None)` o `(None, motivo)`.

    Lo comparten `approve`, `grant_access` y `resend_link`: la convocatoria
    tiene que existir y seguir `open` (`CohortService.accepts_enrollment_followup`;
    las fechas no cuentan, VENTANA en el módulo). `verify` no lo usa: su motivo
    va a la `review_note`, no al oficial.
    """
    from itcj2.apps.titulatec.models import Cohort
    from itcj2.apps.titulatec.services.cohort_service import CohortService

    cohort = db.get(Cohort, req.cohort_id)
    if cohort is None:
        return None, _MSG_NO_COHORT
    if not CohortService.accepts_enrollment_followup(cohort):
        return None, _MSG_COHORT_CLOSED
    return cohort, None


# `activation` del `enrollment_self_service` que escribe `_create_account` (la
# solicitud CREÓ la cuenta y le dio NIP). El de `_convert` (liga sobre una cuenta
# que ya existía) es "personal_email_link".
_ACTIVATION_NEW_ACCOUNT = "nip_personal_email"


def _request_created_account(db: Session, req, proc) -> bool:
    """Señal POSITIVA de que `req` creó la cuenta dueña de `proc` (invariante 1).

    Busca el `enrollment_self_service` de `proc` que dejó `_create_account` para
    ESTA solicitud (`request_id == req.id`, `activation ==
    _ACTIVATION_NEW_ACCOUNT`). Una fila D10 lleva el de `_convert`
    (`"personal_email_link"`), así que no la cumple aunque su liga muera o su
    cuenta del CSV siga con `must_change_password`.
    """
    from itcj2.apps.titulatec.models import ProcessEvent

    eventos = (db.query(ProcessEvent)
               .filter_by(process_id=proc.id, event_type="enrollment_self_service")
               .all())
    return any((ev.payload or {}).get("request_id") == req.id
               and (ev.payload or {}).get("activation") == _ACTIVATION_NEW_ACCOUNT
               for ev in eventos)


class EnrollmentRequestService:
    """Alta, revisión, activación, rechazo y reenvío de solicitudes de inscripción."""

    @staticmethod
    def create(db: Session, cohort, data: dict, *, client_ip: str | None):
        """Alta de solicitud. Devuelve `(req|None, outcome)`.

        `outcome ∈ 'created' | 'existing_request' | 'existing_process'`. Las tres
        ramas producen la MISMA respuesta HTTP (E8), así que la ruta ignora a
        propósito el valor de retorno.

        Ninguna rama emite una liga ni escribe sobre una solicitud ajena: todas se
        disparan con un número de control que cualquiera puede teclear. La única
        que manda correo es la del proceso vivo, y lo manda al buzón
        institucional de la cuenta, cuya posesión no depende del formulario.
        """
        from itcj2.core.models.user import User
        from itcj2.apps.titulatec.models import EnrollmentRequest, TitulationProcess
        from itcj2.apps.titulatec.models.enrollment_request import OPEN_STATUSES
        from itcj2.apps.titulatec.services.audit_service import AuditService
        from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper
        from itcj2.apps.titulatec.services.student_mail import StudentMail

        control = (data.get("control_number") or "").strip()
        user = db.query(User).filter_by(control_number=control).first()

        # (a) Proceso vivo en CUALQUIER convocatoria (D5): sin solicitud; se le
        #     avisa a su institucional en cuál está. El aviso se ENCOLA (spec
        #     2026-10-05 §3.7, P-D1): su fila es la única escritura y se
        #     commitea aquí. Con el correo apagado, o si ese commit falla, cae
        #     al envío en línea de siempre (invariante 5); la respuesta pública
        #     es la misma en todas las ramas (E8).
        if user is not None:
            proc = (db.query(TitulationProcess)
                    .filter(TitulationProcess.student_id == user.id,
                            TitulationProcess.status.in_(("active", "on_hold")))
                    .order_by(TitulationProcess.created_at.desc(),
                              TitulationProcess.id.desc())
                    .first())
            if proc is not None:
                pid = proc.id
                encolado = StudentMail.already_enrolled(db, proc)
                if encolado:
                    try:
                        db.commit()
                    except Exception:
                        logger.warning("No se pudo encolar el aviso de proceso vivo del "
                                       "proceso %s; sale en línea", pid)
                        try:
                            db.rollback()
                        except Exception:      # pragma: no cover - sesión ya inservible
                            pass
                        encolado = False
                if not encolado:
                    TitulaTecEmailHelper.send_already_enrolled(db, user, proc)
                return None, "existing_process"

        # (b) Solicitud viva en esta convocatoria: no se toca. Ni correo, ni
        #     reenvío, ni los datos nuevos que traiga este intento.
        live = (db.query(EnrollmentRequest)
                .filter(EnrollmentRequest.cohort_id == cohort.id,
                        EnrollmentRequest.control_number == control,
                        EnrollmentRequest.status.in_(OPEN_STATUSES))
                .order_by(EnrollmentRequest.id.desc())
                .first())
        if live is not None:
            return live, "existing_request"

        # (c) Nueva: a la bandeja. Dos altas simultáneas del mismo control chocan
        #     en `uq_titulatec_enrollment_req_open` y la ruta cae a la misma tarjeta.
        req = EnrollmentRequest(
            cohort_id=cohort.id,
            control_number=control,
            first_name=data.get("first_name") or "",
            last_name=data.get("last_name") or "",
            middle_name=data.get("middle_name") or None,
            program_id=data.get("program_id"),
            program_text=data.get("program_text") or None,
            phone=data.get("phone") or "",
            contact_email=data.get("contact_email") or "",
            has_efirma=bool(data.get("has_efirma")),
            kind="known" if user is not None else "unknown",
            status="pending_review",
            verify_send_count=0,
            created_ip_hash=_hash_ip(client_ip),
        )
        db.add(req)
        db.flush()              # el id de la solicitud, para la bitácora
        # Alta PÚBLICA: sin sesión el contexto sale `public`. Del contacto solo
        # va el canal; ni correo, ni teléfono, ni IP (esa va en su columna).
        AuditService.record(
            db, "enrollment.request_created",
            entity_type="enrollment_request", entity_id=req.id,
            subject=_audit_subject(req),
            payload={"channel": "public_form", "kind": req.kind,
                     "cohort_id": cohort.id, "program_id": req.program_id,
                     "has_efirma": req.has_efirma})
        db.commit()
        if EnrollmentRequestService.reviewer_mode() == "sii":
            # Modo `sii`: la consulta de elegibilidad corre en celery, DESPUÉS
            # del commit y sin esperar (best-effort, nunca lanza). La
            # respuesta pública no cambia (E8); si no se encola, la recoge el
            # barrido periódico. Con el SII sin configurar (D11) no se publica
            # nada —el corte vive en `enqueue_check`— y la solicitud queda
            # «Sin consultar» hasta que el barrido corra con el SII listo.
            from itcj2.apps.titulatec.services import eligibility_service
            eligibility_service.enqueue_check(req.id)
        return req, "created"

    @staticmethod
    def reviewer_mode() -> str:
        """`"sii"` (POR OMISIÓN, spec 2026-09-27): el SII informa el veredicto y
        el NIP (`EligibilityService`), pero SE decide siempre desde la bandeja
        — nada se aprueba solo. `"school_services"` / `"computer_center"`:
        modos de RESPALDO (comportamiento sin cambios), activables solo por
        variable de entorno.

        Sale de TITULATEC_ENROLLMENT_REVIEWER (+ reinicio; un valor inválido
        truena al arrancar). Los tests parchean ESTE método, nunca `get_settings`.
        """
        from itcj2.config import get_settings

        return get_settings().TITULATEC_ENROLLMENT_REVIEWER

    @staticmethod
    def reviewer_label() -> str:
        """Nombre de quien revisa según el modo: «Servicios Escolares» (oficial y
        `sii`) | «Centro de Cómputo» (alterno)."""
        return _REVIEWER_LABELS[EnrollmentRequestService.reviewer_mode()]

    @staticmethod
    def approval_path(has_account: bool, nip_status: str | None) -> str:
        """La aprobación que OFRECE la bandeja en el modo `sii`: `"link"` |
        `"sii_nip"` | `"access"` (Ruling R8; el texto de cada una, en
        `APPROVAL_LABELS`). Puro: no toca la BD.

        Con cuenta, la liga (el NIP no importa); sin cuenta y con el NIP del SII
        `available` en la consulta vigente, la cuenta con ese NIP; cualquier
        otro estado —o sin consulta— pasa a Accesos. Es lo que la fila
        PROMETE; lo que ocurre lo decide `approve_detailed` bajo el lock, contra
        `core_users` y el SII de ese momento (con cuenta sale la liga aunque se
        pida Accesos).
        """
        if has_account:
            return "link"
        if nip_status == "available":
            return "sii_nip"
        return "access"

    @staticmethod
    def approve(db: Session, req_id: int, *, nip: str, program_id: int | None,
                actor_id: int, to_access: bool = False):
        """Aprueba una solicitud de la bandeja. Devuelve `(ok, detalle)`.

        Compatibilidad: es `approve_detailed(...)[:2]`, que tiene el contrato
        completo. Quien necesita distinguir la falla del NIP del SII (la ruta
        de la bandeja) llama a `approve_detailed`.
        """
        return EnrollmentRequestService.approve_detailed(
            db, req_id, nip=nip, program_id=program_id, actor_id=actor_id,
            to_access=to_access)[:2]

    @staticmethod
    def approve_detailed(db: Session, req_id: int, *, nip: str, program_id: int | None,
                         actor_id: int, to_access: bool = False) -> ApproveResult:
        """Aprueba una solicitud de la bandeja. Devuelve `ApproveResult`.

        En éxito `detail` es el folio (cuenta nueva) o `""` (liga emitida o
        pasó a Centro de Cómputo); en fallo, el motivo que ve el oficial.
        Aprobable desde `pending_review` y el legado `unverified`/`verified`;
        sobre `awaiting_access` devuelve `_MSG_IN_ACCESS`.

        - CON cuenta en `core_users` (todos los modos): el NIP y `to_access` se
          ignoran -> liga de activación (`_link_ttl_hours()`) al correo
          personal -> `approved` (`_issue_link_for_account`). La cuenta no se
          toca, ni siquiera se reactiva: eso lo hace abrir la liga (invariante
          1 del módulo). Sin `password_hash` no hay liga (invariante 2).
        - SIN cuenta, modo OFICIAL: NO valida el NIP, NO crea usuario, NO manda
          correo -> `awaiting_access`. El NIP lo da Centro de Cómputo
          (`grant_access`).
        - SIN cuenta, modo ALTERNO: NIP obligatorio -> `_create_account`
          (`nip_source="form"`) -> `converted`; usuario + NIP al correo
          personal. El caché de authz de los roles nuevos se tira DESPUÉS del
          commit.
        - SIN cuenta, modo `sii` (SE aprueba siempre: el SII solo informa):
          - `to_access=True` («Aprobar y pasar a Accesos»): la rama del modo
            oficial -> `awaiting_access`, sin usuario ni correo, y SIN
            preguntarle el NIP al SII (ni aquí ni en `_approve_locked`).
          - `to_access=False` («Aprobar y dar acceso»): el NIP del formulario
            se IGNORA; se le pide al SII SIN el lock (`_sii_nip_unlocked`:
            suelta el lock, pregunta, lo vuelve a tomar y revalida el estado y
            la convocatoria) -> `_create_account_with_sii_nip`
            (`must_change_password=False`, `nip_source="sii"`) -> `converted`;
            correo SIN el NIP («tu NIP del SII»). Si el SII no da un NIP válido,
            `nip_failure` es su estado (`classify_sii_nip`: missing | invalid |
            unavailable | error) y `detail` su motivo (`_NIP_FAILURE_MSGS`):
            nada escrito de la solicitud, y la consulta vigente guarda ese
            `nip_status` (`EligibilityService.record_nip_status`, transacción
            propia y corta, DESPUÉS de soltar el lock) para que la bandeja
            ofrezca Accesos.
          - SII SIN CONFIGURAR (D11, `EligibilityService.sii_configured()`
            falso): aprobar sin `to_access` ES pasarla a Accesos (revisión
            final F8). No hay SII al cual pedirle el NIP: un POST así (la
            página del modo oficial abierta el día del deploy, o una vieja en
            caché) se trata como `to_access=True`, sin consultar al SII ni
            dejar un WARNING por clic. «¿Tiene cuenta?» se sigue decidiendo
            bajo el lock en `_approve_locked`: con cuenta sale la liga.

        La convocatoria solo tiene que estar `open`: pasada `closes_at` se sigue
        aprobando lo que entró a tiempo (VENTANA, en el módulo).

        Aquí viven las guardas de la BANDEJA (lock, estado, convocatoria) y el
        NIP pedido sin lock; lo que decide y escribe la aprobación es
        `_approve_locked`, el núcleo único (solo lo llama esta función; lo fija
        una prueba estructural).

        INVARIANTE: un fallo no deja NADA escrito de la solicitud, ni siquiera
        en la sesión. Toda validación ocurre antes de escribir, y la única que
        llega después (no se creó el proceso) deshace su savepoint. Lo único
        que escribe un fallo es el `nip_status` de la consulta de arriba.
        """
        from itcj2.apps.titulatec.models import EnrollmentRequest

        req = db.get(EnrollmentRequest, req_id)
        if req is None:
            return ApproveResult(False, _MSG_GONE, None)
        if not to_access and EnrollmentRequestService.reviewer_mode() == "sii":
            from itcj2.apps.titulatec.services.eligibility_service import (
                EligibilityService,
            )

            # D11: sin SII al cual pedirle el NIP, aprobar ES pasarla a Accesos
            # (con cuenta `_approve_locked` ignora `to_access` y manda la liga).
            if not EligibilityService.sii_configured():
                to_access = True
        # Modo `sii` sin cuenta y sin `to_access`: el NIP se pide al SII SIN el
        # lock (puede tardar sus timeouts) y la segunda vuelta revalida todo
        # bajo el lock (`_sii_nip_unlocked`). En cualquier otro caso hay una
        # sola vuelta.
        sii_nip = None
        while True:
            db.execute(text("SELECT pg_advisory_xact_lock(:ns, :key)"),
                       {"ns": _REQUEST_LOCK_NS, "key": int(req.id)})
            db.refresh(req)

            if req.status == "approved":
                return ApproveResult(False, _MSG_ALREADY_APPROVED, None)
            if req.status == "awaiting_access":
                return ApproveResult(False, _MSG_IN_ACCESS, None)
            if req.status not in _REVIEWABLE:
                return ApproveResult(False, _MSG_RESOLVED, None)

            cohort, motivo = _cohort_gate(db, req)
            if cohort is None:
                return ApproveResult(False, motivo, None)
            if sii_nip is None and not to_access:
                sii_nip = EnrollmentRequestService._sii_nip_unlocked(db, req)
                if sii_nip is not None:
                    continue
            break

        ok, detalle, nip_failure = EnrollmentRequestService._approve_locked(
            db, req, cohort, actor_id=actor_id,
            program_id=program_id if program_id else req.program_id, nip=nip,
            sii_nip=sii_nip, to_access=to_access)
        if nip_failure is not None:
            # `_approve_locked` no escribió nada: se cierra la transacción (suelta
            # el lock de la solicitud) y la consulta vigente guarda lo que el SII
            # acaba de decir, en la suya. Nunca lanza.
            from itcj2.apps.titulatec.services.eligibility_service import (
                EligibilityService,
            )

            rid, check_id = req.id, req.last_check_id
            db.commit()
            EligibilityService.record_nip_status(db, rid, check_id, nip_failure)
        return ApproveResult(ok, detalle, nip_failure)

    @staticmethod
    def _sii_nip_unlocked(db: Session, req):
        """El NIP del SII para aprobar `req`, pedido SIN el lock. `None` si no
        hace falta pedirlo.

        Solo en el modo `sii` y si el número de control NO tiene cuenta (con
        cuenta sale la liga, sin NIP). Hace `commit` antes de preguntar: suelta
        el lock de la solicitud y cierra la transacción, así el SII puede tardar
        sus timeouts sin tener a nadie esperando ni una conexión de PgBouncer
        ocupada (revisión final C6/C8). No escribe nada: quien llama estaba
        solo leyendo. Devuelve lo mismo que `fetch_sii_nip`, `(Secret | None,
        falla)`; el llamador vuelve a tomar el lock, REVALIDA el estado y se lo
        pasa a `_approve_locked` (`sii_nip`).
        """
        from itcj2.core.models.user import User

        if EnrollmentRequestService.reviewer_mode() != "sii":
            return None
        control = (req.control_number or "").strip()
        if not CONTROL_NUMBER_RE.fullmatch(control):
            return None
        if db.query(User.id).filter_by(control_number=control).first() is not None:
            return None
        db.commit()
        from itcj2.apps.titulatec.services.eligibility_service import fetch_sii_nip

        return fetch_sii_nip(control)

    @staticmethod
    def _approve_locked(db: Session, req, cohort, *, actor_id: int | None,
                        program_id: int | None, nip: str | None = None,
                        event_extra: dict | None = None, sii_nip=None,
                        to_access: bool = False):
        """Núcleo ÚNICO de la aprobación. Solo lo llama `approve_detailed()` (la
        bandeja de Servicios Escolares; `approve()` le delega; una prueba
        estructural recorre `itcj2/` y lo exige). `actor_id` sigue admitiendo
        `None` por compatibilidad.

        Precondiciones del llamador: el lock de la solicitud tomado, `req`
        refrescada, su estado ya validado (la bandeja acepta el legado
        `unverified`/`verified`) y `cohort` salida de `_cohort_gate`. TODO lo
        que decide y escribe la aprobación vive aquí.

        Devuelve `(ok, detalle, nip_failure)`:

        - éxito: `(True, folio | "", None)`, ya commiteado; el correo, la liga
          en Redis y la invalidación de authz van DESPUÉS del commit;
        - fallo: `(False, motivo, None)` sin nada escrito (invariante de
          `approve_detailed()`), que devuelve el motivo;
        - el SII no dio un NIP válido (modo `sii`, sin cuenta, sin
          `to_access`): `(False, _NIP_FAILURE_MSGS[estado], estado)` con
          `estado` = `EligibilityService.classify_sii_nip` (missing | invalid |
          unavailable | error). Nada escrito.

        `to_access=True` (modo `sii`, sin cuenta): la rama del modo oficial
        (`awaiting_access`, sin usuario ni correo) y el SII NO se consulta. Con
        cuenta se ignora (sale la liga); fuera del modo `sii` no cambia nada.

        `event_extra` se suma al payload del `ProcessEvent` de la cuenta nueva.

        `sii_nip` = `(Secret | None, falla)` ya pedido SIN el lock
        (`_sii_nip_unlocked`). Si falta —la cuenta desapareció entre las dos
        vueltas— se pide aquí, con el lock: es la excepción, no el camino.
        """
        from itcj2.core.models.user import User
        from itcj2.apps.titulatec.services.import_service import ImportService

        from itcj2.apps.titulatec.services.audit_service import AuditService

        control = (req.control_number or "").strip()
        if not CONTROL_NUMBER_RE.fullmatch(control) or not _full_name(req):
            return False, _MSG_BAD_DATA, None

        user = db.query(User).filter_by(control_number=control).first()
        now = datetime.now()
        estado_previo = req.status

        if user is not None:
            # ── CON cuenta (todos los modos): liga de activación; la cuenta
            #    no se toca ──
            ok, detalle, raw = EnrollmentRequestService._issue_link_for_account(db, req, user)
            if not ok:
                return False, detalle, None
            req.program_id = program_id
            req.reviewed_by_id = actor_id
            req.reviewed_at = now
            antes, despues = AuditService.changes({"status": estado_previo},
                                                  {"status": req.status})
            AuditService.record(
                db, "enrollment.approved",
                entity_type="enrollment_request", entity_id=req.id,
                subject=_audit_subject(req), before=antes, after=despues,
                payload={"path": "existing_account", "cohort_id": req.cohort_id},
                actor_id=actor_id)
            db.commit()
            _token_cache_put(raw)
            EnrollmentRequestService._mail_activation(db, req, raw)
            return True, "", None

        mode = EnrollmentRequestService.reviewer_mode()
        if mode == "sii" and not to_access:
            # ── SIN cuenta, modo sii: usuario nuevo con el NIP DEL SII ──
            # El NIP del formulario se ignora.
            from itcj2.apps.titulatec.services.eligibility_service import (
                EligibilityService, fetch_sii_nip,
            )

            secret, falla = sii_nip if sii_nip is not None else fetch_sii_nip(control)
            sii_nip = None
            # De aquí solo sale el ESTADO; el `Secret` se revela para
            # clasificarlo y, si sirve, para hashearlo (abajo).
            estado = EligibilityService.classify_sii_nip(secret, falla)
            if estado != "available":
                del secret
                return False, _NIP_FAILURE_MSGS[estado], estado
            ok, detalle, summary, user = EnrollmentRequestService._create_account_with_sii_nip(
                db, req, cohort, secret, program_id=program_id,
                actor_id=actor_id, approved_by_id=actor_id,
                event_extra={**(event_extra or {}), "nip_source": "sii"})
            del secret
            if not ok:
                return False, detalle, None
            req.reviewed_by_id = actor_id
            req.reviewed_at = now
            db.commit()
            ImportService.invalidate_authz((summary or {}).get("authz_touched"))
            EnrollmentRequestService._mail_access(db, req, user, None, nip_source="sii")
            return True, detalle, None

        if mode != "computer_center":
            # ── SIN cuenta, modo oficial (o `sii` pasándola a Accesos): a
            #    Centro de Cómputo, sin usuario ni correo ──
            req.status = "awaiting_access"
            req.program_id = program_id
            req.reviewed_by_id = actor_id
            req.reviewed_at = now
            antes, despues = AuditService.changes({"status": estado_previo},
                                                  {"status": req.status})
            AuditService.record(
                db, "enrollment.approved",
                entity_type="enrollment_request", entity_id=req.id,
                subject=_audit_subject(req), before=antes, after=despues,
                payload={"path": "awaiting_access", "cohort_id": req.cohort_id},
                actor_id=actor_id)
            db.commit()
            return True, "", None

        # ── SIN cuenta, modo alterno: usuario nuevo con el NIP, en un paso ──
        # (Cuenta nueva, también la del SII de arriba: `_create_account` ya
        # escribe el `enrollment_self_service` que la bitácora refleja; sin
        # acción explícita para no duplicarlo.)
        ok, detalle, summary, user = EnrollmentRequestService._create_account(
            db, req, cohort, nip=nip, program_id=program_id,
            actor_id=actor_id, approved_by_id=actor_id, nip_source="form",
            event_extra=event_extra)
        if not ok:
            return False, detalle, None
        req.reviewed_by_id = actor_id
        req.reviewed_at = now
        db.commit()
        # Después del commit: antes, una lectura concurrente repoblaría el caché
        # de authz con los roles de antes de aprobar.
        ImportService.invalidate_authz((summary or {}).get("authz_touched"))
        EnrollmentRequestService._mail_access(db, req, user, nip)
        return True, detalle, None

    @staticmethod
    def grant_access(db: Session, req_id: int, *, nip: str, actor_id: int):
        """Centro de Cómputo da el acceso a una solicitud `awaiting_access`.

        Devuelve `(ok, detalle)`: en éxito el folio (cuenta creada) o `""` (liga
        emitida, D10); en fallo, el motivo que ve CC.

        Lock + refresh ANTES de leer el estado. Revalida todo lo que pudo
        cambiar desde que SE aprobó: que la convocatoria siga `open` (las fechas
        no cuentan, VENTANA), el formato de los datos y —D10— "¿tiene cuenta?"
        otra vez contra `core_users`:

        - SIN cuenta: NIP de 4 dígitos -> `_create_account` -> `converted`;
          commit, caché de authz, usuario + NIP al correo personal y sello de
          `access_sent_at` si salió (`_mail_access`).
        - CON cuenta (un CSV o un alta manual la creó entretanto): el NIP se
          ignora -> la misma rama que `approve()` con cuenta
          (`_issue_link_for_account`: D5 y contraseña) -> `approved`, liga al
          correo personal. Si D5 o la contraseña la frenan, en el modo oficial
          el motivo se le dice a CC como algo que SÍ puede hacer
          (`_CC_OFFICIAL_MSGS`: devolverla a SE con esa nota); el de SE («dala
          de alta desde la convocatoria y rechaza») no es suyo. Sella `access_granted_*` (CC actuó y la fila vive en
          su pestaña «Con acceso») pero NO `access_sent_at`: el envío de la liga
          lo registra `verify_sent_at`, y la fila no es «correo no enviado»
          (`access_mail_unsent`) ni admite reasignar NIP (la cuenta no la creó
          la solicitud).

        `reviewed_by_id`/`reviewed_at` siguen siendo de SE: dar acceso no
        reescribe quién aprobó.

        INVARIANTE heredado de `approve()`: `(False, motivo)` no deja nada
        escrito, y el NIP nunca sale (log, `detalle`, payload).
        """
        from itcj2.core.models.user import User
        from itcj2.apps.titulatec.models import EnrollmentRequest
        from itcj2.apps.titulatec.services.import_service import ImportService

        req = db.get(EnrollmentRequest, req_id)
        if req is None:
            return False, _MSG_GONE
        db.execute(text("SELECT pg_advisory_xact_lock(:ns, :key)"),
                   {"ns": _REQUEST_LOCK_NS, "key": int(req.id)})
        db.refresh(req)

        if req.status != "awaiting_access":
            return False, _MSG_NOT_AWAITING

        cohort, motivo = _cohort_gate(db, req)
        if cohort is None:
            return False, motivo

        control = (req.control_number or "").strip()
        if not CONTROL_NUMBER_RE.fullmatch(control) or not _full_name(req):
            return False, _MSG_BAD_DATA

        user = db.query(User).filter_by(control_number=control).first()
        if user is not None:
            # ── D10: apareció una cuenta; liga, el NIP se ignora ──
            ok, detalle, raw = EnrollmentRequestService._issue_link_for_account(db, req, user)
            if not ok:
                if EnrollmentRequestService.reviewer_mode() != "computer_center":
                    detalle = _CC_OFFICIAL_MSGS.get(detalle, detalle)
                return False, detalle
            req.access_granted_by_id = actor_id
            req.access_granted_at = datetime.now()
            # Bitácora (revisión final M6): sin esto el paso `awaiting_access →
            # approved` que dio Centro de Cómputo solo quedaba en filas
            # `data.update`. Después de las validaciones (el `if not ok` de
            # arriba), antes del commit; el NIP tecleado se ignora y no va.
            from itcj2.apps.titulatec.services.audit_service import AuditService
            antes, despues = AuditService.changes({"status": "awaiting_access"},
                                                  {"status": req.status})
            AuditService.record(
                db, "enrollment.approved",
                entity_type="enrollment_request", entity_id=req.id,
                subject=_audit_subject(req), before=antes, after=despues,
                payload={"path": "existing_account", "via": "access",
                         "cohort_id": req.cohort_id},
                actor_id=actor_id)
            db.commit()
            _token_cache_put(raw)
            EnrollmentRequestService._mail_activation(db, req, raw)
            return True, ""

        ok, detalle, summary, user = EnrollmentRequestService._create_account(
            db, req, cohort, nip=nip, program_id=req.program_id,
            actor_id=actor_id, approved_by_id=req.reviewed_by_id, nip_source="center")
        if not ok:
            return False, detalle
        db.commit()
        ImportService.invalidate_authz((summary or {}).get("authz_touched"))
        EnrollmentRequestService._mail_access(db, req, user, nip)
        return True, detalle

    @staticmethod
    def return_to_review(db: Session, req_id: int, *, note: str, actor_id: int):
        """Centro de Cómputo devuelve a SE una solicitud `awaiting_access`.

        Devuelve `(ok, detalle)`. Nota obligatoria de hasta 2000 caracteres ya
        sin espacios en los extremos: una más larga se RECHAZA con motivo (no se
        recorta en silencio, que le perdería a CC el final de lo que escribió;
        la forma de la bandeja lleva `maxlength="2000"`). La solicitud vuelve a
        `pending_review` con `returned_by_id`/`returned_at`/`return_note`.
        `reviewed_*` y `review_note` no se tocan (son de SE). SIN correo: el
        alumno no se entera del paso intermedio.
        """
        from itcj2.apps.titulatec.models import EnrollmentRequest
        from itcj2.apps.titulatec.services.audit_service import AuditService

        motivo = (note or "").strip()
        if not motivo:
            return False, _MSG_RETURN_NOTE
        if len(motivo) > _RETURN_NOTE_MAX:
            return False, _MSG_RETURN_NOTE_LONG
        req = db.get(EnrollmentRequest, req_id)
        if req is None:
            return False, _MSG_GONE
        db.execute(text("SELECT pg_advisory_xact_lock(:ns, :key)"),
                   {"ns": _REQUEST_LOCK_NS, "key": int(req.id)})
        db.refresh(req)

        if req.status != "awaiting_access":
            return False, _MSG_NOT_AWAITING

        req.status = "pending_review"
        req.returned_by_id = actor_id
        req.returned_at = datetime.now()
        req.return_note = motivo
        AuditService.record(
            db, "access.returned",
            entity_type="enrollment_request", entity_id=req.id,
            subject=_audit_subject(req), reason=motivo,
            before={"status": "awaiting_access"}, after={"status": "pending_review"},
            actor_id=actor_id)
        db.commit()
        return True, ""

    @staticmethod
    def can_reassign_nip(req, user) -> bool:
        """¿Se puede reasignar el NIP de `req`? Puro: no toca la BD.

        `user` es la cuenta que hoy tiene el número de control de la solicitud
        (o `None`). Solo una solicitud `converted` a la que se le DIO acceso con
        NIP (`access_granted_at`, sin liga: `verify_token_hash` nulo) y cuya
        cuenta NUNCA ha iniciado sesión (`last_login` nulo; lo sella
        `auth_service.authenticate` en cada entrada) y conserva
        `must_change_password`. La bandeja lo usa para pintar el botón, aunque el
        correo haya salido (un correo mal escrito también «sale»);
        `reassign_nip` lo repite bajo el bloqueo de la cuenta.

        `must_change_password` SOLO no basta (revisión final C1): en un egresado
        nunca se limpia —TitulaTec no tiene pantalla de cambio y
        `core/api/users.py::password_state` solo lo exige con la contraseña por
        omisión—, así que una cuenta que lleva semanas entrando lo sigue
        teniendo en True.

        Es condición NECESARIA, no suficiente. Deja fuera la rama D10 solo
        porque `verify()` conserva el hash al convertir (idempotencia); una
        cuenta del CSV también nace con `must_change_password`. Lo que protege
        de verdad a esa cuenta ajena (invariante 1) es la señal POSITIVA que
        `reassign_nip` exige además: `_request_created_account`.
        """
        return (req.status == "converted"
                and req.access_granted_at is not None
                and req.verify_token_hash is None
                and user is not None
                and user.last_login is None
                and bool(user.must_change_password))

    @staticmethod
    def access_mail_unsent(req) -> bool:
        """¿La fila marca «correo no enviado» (D8)? Puro: no toca la BD.

        Único predicado de esa marca; la bandeja de Centro de Cómputo lo usa en
        vez de derivarlo. Verdadero solo para una solicitud `converted` a la que
        se le dio acceso CON NIP (`access_granted_at` lleno, sin liga:
        `verify_token_hash` nulo) y cuyo correo con usuario + NIP no salió
        (`access_sent_at` nulo; `_mail_access` lo sella si sale).

        NO basta «`access_granted_at` lleno y `access_sent_at` nulo»: la rama con
        liga de `grant_access` (D10) sella `access_granted_*` y NUNCA
        `access_sent_at` (el envío de su liga va en `verify_sent_at`), y si
        `verify()` la devuelve a `pending_review` conserva ese sello de CC. Una
        fila `converted` con el hash de la liga es D10 abierta: su correo es el
        de la liga, no el del NIP.
        """
        return (req.status == "converted"
                and req.access_granted_at is not None
                and req.verify_token_hash is None
                and req.access_sent_at is None)

    @staticmethod
    def resend_access_notice(db: Session, req_id: int) -> tuple[bool, str]:
        """«Reenviar aviso» (spec 2026-09-27 D12). Devuelve `(ok, detalle)`.

        Para una cuenta que nació con el NIP DEL SII (`nip_source == "sii"`,
        modo `sii`) cuyo correo de acceso no salió (`access_sent_at` nulo). Ese
        correo NO lleva NIP —el alumno ya sabe el suyo del SII—, así que
        reenviarlo no expone nada; por lo mismo, aquí no se toca ninguna
        credencial (ni `hash_nip`, ni `password_hash`, ni
        `must_change_password`): para un NIP nuevo está `reassign_nip`.

        Lock + refresh ANTES de leer el estado. Exige `converted`,
        `nip_source == "sii"`, `access_sent_at` nulo y que la cuenta del
        número de control sea la dueña del proceso en que se convirtió
        (`converted_process_id`, el que creó `_create_account`); si no,
        `(False, _MSG_NO_ACCESS_NOTICE)` sin escribir nada. Commit ANTES del
        correo (suelta el lock: `msgraph_mail` es un `requests.post`
        síncrono); `_mail_access` sella `access_sent_at` si sale ->
        `(True, "")`; si no, `(False, _MSG_ACCESS_NOTICE_NOT_SENT)` y la fila
        sigue «correo no enviado».
        """
        from itcj2.core.models.user import User
        from itcj2.apps.titulatec.models import EnrollmentRequest, TitulationProcess
        from itcj2.apps.titulatec.services.audit_service import AuditService

        req = db.get(EnrollmentRequest, req_id)
        if req is None:
            return False, _MSG_GONE
        db.execute(text("SELECT pg_advisory_xact_lock(:ns, :key)"),
                   {"ns": _REQUEST_LOCK_NS, "key": int(req.id)})
        db.refresh(req)

        if (req.status != "converted" or req.nip_source != "sii"
                or req.access_sent_at is not None or req.converted_process_id is None):
            return False, _MSG_NO_ACCESS_NOTICE
        user = (db.query(User)
                .filter_by(control_number=(req.control_number or "").strip()).first())
        proc = db.get(TitulationProcess, req.converted_process_id)
        if user is None or proc is None or proc.student_id != user.id:
            return False, _MSG_NO_ACCESS_NOTICE

        # Lo único que este commit persiste es la petición de reenvío (sin NIP:
        # el aviso del SII no lo lleva).
        AuditService.record(
            db, "enrollment.notice_resent",
            entity_type="enrollment_request", entity_id=req.id,
            process_id=req.converted_process_id, subject=_audit_subject(req))
        db.commit()          # suelta el lock antes del correo
        if EnrollmentRequestService._mail_access(db, req, user, None, nip_source="sii"):
            return True, ""
        return False, _MSG_ACCESS_NOTICE_NOT_SENT

    @staticmethod
    def reassign_nip(db: Session, req_id: int, *, nip: str, actor_id: int,
                     send_mail: bool = True):
        """CC reasigna el NIP de una cuenta que nunca ha iniciado sesión (D8).

        Para cuando el correo con el NIP no salió o salió a una dirección mal
        escrita. Devuelve `(ok, detalle)`. Lock de la solicitud + refresh; luego
        la cuenta del control se lee con `FOR UPDATE` (y `populate_existing`,
        para no decidir con la copia del mapa de identidad) y, BAJO ESE
        BLOQUEO, se exige `can_reassign_nip` (nunca ha iniciado sesión), que sea
        la dueña del proceso de la solicitud Y la señal POSITIVA de que ESTA
        solicitud la creó (`_request_created_account`). Sin el bloqueo, un
        cambio de contraseña concurrente quedaría pisado por el NIP. Invariante
        1: sobre una cuenta que NO creó la solicitud jamás se escribe
        credencial, y en una fila D10 las dos primeras no bastan (la cuenta del
        CSV nace con `must_change_password` y `_convert` le crea el proceso a
        ELLA).

        Escribe `password_hash = hash_nip(nip)`, revoca las sesiones de la
        cuenta en la MISMA transacción (`session_service.bump_version(db=db)`:
        quien entró con el NIP anterior —p. ej. el dueño del correo mal
        escrito— no puede fijar su propia contraseña después), sella
        `access_granted_*`, deja `access_sent_at` en NULL y agrega
        `enrollment_access_reset` SIN el NIP. Si no pudo revocar, lanza
        `RuntimeError` antes de commitear (la ruta hace rollback).

        `send_mail=True`: correo después del commit con el texto «Este NIP
        reemplaza al que te enviamos antes» (`_mail_access(reassigned=True)`,
        que sella `access_sent_at` si sale). `send_mail=False` («lo dicto por
        teléfono»): no se manda nada y `access_sent_at` queda NULL.
        """
        from itcj2.core.models.user import User
        from itcj2.core.services import session_service
        from itcj2.core.utils.security import hash_nip
        from itcj2.apps.titulatec.models import (
            EnrollmentRequest, ProcessEvent, TitulationProcess,
        )

        if not nip_format_ok(nip):
            return False, _MSG_BAD_NIP
        req = db.get(EnrollmentRequest, req_id)
        if req is None:
            return False, _MSG_GONE
        db.execute(text("SELECT pg_advisory_xact_lock(:ns, :key)"),
                   {"ns": _REQUEST_LOCK_NS, "key": int(req.id)})
        db.refresh(req)

        user = (db.query(User)
                .filter_by(control_number=(req.control_number or "").strip())
                .populate_existing()
                .with_for_update()
                .first())
        if not EnrollmentRequestService.can_reassign_nip(req, user):
            return False, _MSG_NOT_REASSIGNABLE
        proc = db.get(TitulationProcess, req.converted_process_id)
        if proc is None or proc.student_id != user.id:
            return False, _MSG_NOT_REASSIGNABLE
        if not _request_created_account(db, req, proc):
            return False, _MSG_NOT_REASSIGNABLE

        user.password_hash = hash_nip(nip)
        if session_service.bump_version(user.id, db=db) is None:
            # `bump_version` nunca lanza: un `None` aquí dejaría la credencial
            # nueva con las sesiones del NIP anterior vivas.
            raise RuntimeError("reassign_nip: no se pudieron revocar las sesiones")
        req.access_granted_by_id = actor_id
        req.access_granted_at = datetime.now()
        req.access_sent_at = None
        db.add(ProcessEvent(
            process_id=proc.id, actor_id=actor_id,
            event_type="enrollment_access_reset", phase_number=0,
            # Se muestra en el expediente: aquí NO va el NIP.
            payload={"request_id": req.id},
        ))
        db.commit()
        # Segundo borrado de la época en caché, ya con el commit hecho (patrón
        # de `users_admin`): cierra la ventana en que un lector la repuebla con
        # la época vieja.
        session_service.forget_cached_version(user.id)
        if send_mail:
            EnrollmentRequestService._mail_access(db, req, user, nip, reassigned=True)
        return True, ""

    @staticmethod
    def _issue_link_for_account(db: Session, req, user):
        """Rama CON cuenta de `approve()` y de `grant_access()` (D10).

        Devuelve `(ok, detalle, raw)`. Valida D5 (la cuenta ya tiene proceso en
        OTRA convocatoria) y la contraseña (invariante 2) ANTES de escribir; en
        éxito emite la liga (`_issue_activation`), fija el contador y deja la
        solicitud `approved`. No toca la cuenta, no commitea ni manda: el
        llamador sella sus columnas, commitea, cachea el claro y manda
        (`_mail_activation`), en ese orden.
        """
        if _has_process_in_other_cohort(db, user.id, req.cohort_id):
            return False, _MSG_OTHER_COHORT, None
        if _has_revoked_process_here(db, user.id, req.cohort_id):
            return False, _MSG_REVOKED_HERE, None
        if not user.password_hash:
            return False, _MSG_NO_PASSWORD, None
        raw = EnrollmentRequestService._issue_activation(req)
        req.verify_send_count = 1
        req.status = "approved"
        return True, "", raw

    @staticmethod
    def _create_account(db: Session, req, cohort, *, nip: str, program_id: int | None,
                        actor_id: int | None, approved_by_id: int | None,
                        nip_source: str,
                        must_change_password: bool = True,
                        event_extra: dict | None = None):
        """Crea la cuenta NUEVA de una solicitud sin cuenta. `(ok, detalle, summary, user)`.

        Lo usan `_approve_locked` (el núcleo de `approve_detailed`: modo
        alterno, y modo `sii` vía `_create_account_with_sii_nip`) y
        `grant_access()`.
        `nip_source` (obligatorio, `NIP_SOURCES`) dice de dónde salió el NIP y
        queda en `req.nip_source`: `"form"` el alterno, `"center"` Centro de
        Cómputo, `"sii"` el modo `sii`. En este último el NIP es el del SII:
        `must_change_password` `False` (es suyo, no uno que alguien le dictó) y
        `event_extra` suma al payload del `ProcessEvent` también su
        `nip_source`. NIP de 4 dígitos
        -> `User` con `hash_nip(nip)` (nunca `set_initial_credential`, que
        pondría el número de control, dato público), `must_change_password` y el
        alias legado `graduate` -> proceso y roles de egresado (`import_rows`
        con `commit=False` y `repair_credentials=False`) -> perfil -> solicitud
        `converted` con `access_granted_*` -> `ProcessEvent` con
        `approved_by_id` (quien aprobó) y `granted_by_id` (quien dio el acceso),
        SIN el NIP.

        Todo corre en un SAVEPOINT: si no se crea el proceso se deshace y
        devuelve `(False, _MSG_NO_PROCESS, None, None)` sin dejar nada escrito;
        una excepción lo deshace y sube. No commitea, no tira el caché de authz
        ni manda correo: eso es del llamador, después de SU commit, con
        `summary["authz_touched"]` y `_mail_access`.
        """
        from itcj2.core.models.role import Role
        from itcj2.core.models.user import User
        from itcj2.core.services.student_profile_service import StudentProfileService
        from itcj2.core.utils.security import hash_nip
        from itcj2.apps.titulatec.models import ProcessEvent, TitulationProcess
        from itcj2.apps.titulatec.services.import_service import (
            GRADUATE_ROLE, ImportService,
        )

        if nip_source not in NIP_SOURCES:
            raise ValueError(f"nip_source fuera de {NIP_SOURCES}: {nip_source!r}")
        if not nip_format_ok(nip):
            return False, _MSG_BAD_NIP, None, None
        control = (req.control_number or "").strip()

        savepoint = db.begin_nested()
        try:
            # El alias legado nace `graduate`: el mismo que `import_rows` le deja
            # a una cuenta que ya existía (`_sync_graduate_roles`).
            graduate_role = db.query(Role).filter_by(name=GRADUATE_ROLE).first()
            user = User(
                username=control, control_number=control,
                first_name=req.first_name, last_name=req.last_name,
                middle_name=req.middle_name or None,
                email=None,
                role_id=graduate_role.id if graduate_role else None,
                is_active=True, must_change_password=must_change_password,
            )
            user.password_hash = hash_nip(nip)   # nunca `set_initial_credential`
            db.add(user)
            db.flush()

            # `commit=False`: `import_rows` solo hace `flush` y el llamador es
            # dueño único de su transacción (Finding 2, ronda 1 de revisión).
            # Por lo mismo, el caché de authz de los roles que deja lo tira el
            # llamador después de su commit, con los pares del summary.
            summary = ImportService.import_rows(
                db, cohort,
                [{"control_number": control, "full_name": _full_name(req), "email": None,
                  "program_id": program_id, "modality_id": None}],
                actor_id=actor_id, source="enrollment_request",
                repair_credentials=False, commit=False,
            )
            proc = (db.query(TitulationProcess)
                    .filter_by(student_id=user.id, cohort_id=req.cohort_id).first())
            if proc is None:
                savepoint.rollback()
                return False, _MSG_NO_PROCESS, None, None

            # El perfil de un usuario recién creado sí se llena: es lo único que
            # se sabe de él y no pisa nada de nadie.
            StudentProfileService.set_fields(
                db, user.id,
                contact_email=req.contact_email, phone=req.phone,
                has_efirma=req.has_efirma, program_text=req.program_text,
                program_id=program_id,
            )
            now = datetime.now()
            req.status = "converted"
            req.program_id = program_id
            req.converted_process_id = proc.id
            req.nip_source = nip_source
            req.access_granted_by_id = actor_id
            req.access_granted_at = now
            db.add(ProcessEvent(
                process_id=proc.id, actor_id=actor_id,
                event_type="enrollment_self_service", phase_number=0,
                # Se muestra en el expediente: aquí NO va el NIP.
                payload={"request_id": req.id, "folio": proc.folio,
                         "preexisting_process": False, "reviewed": True,
                         # La señal que exige `reassign_nip`
                         # (`_request_created_account`).
                         "activation": _ACTIVATION_NEW_ACCOUNT,
                         "approved_by_id": approved_by_id,
                         "granted_by_id": actor_id,
                         **(event_extra or {})},
            ))
            folio = proc.folio
            savepoint.commit()
        except Exception:
            if savepoint.is_active:
                savepoint.rollback()
            raise
        return True, folio, summary, user

    @staticmethod
    def _create_account_with_sii_nip(db: Session, req, cohort, secret, *,
                                     program_id: int | None, actor_id: int | None,
                                     approved_by_id: int | None, event_extra: dict):
        """`_create_account` con el NIP del SII (`secret`, un `sii.rules.Secret`).

        Mismo retorno `(ok, detalle, summary, user)`; la solicitud queda con
        `nip_source="sii"`. El NIP se revela SOLO para hashearlo y nunca sale de
        aquí: un NIP con otro formato devuelve el motivo `invalid` de
        `_NIP_FAILURE_MSGS` (sin el valor; `_approve_locked` ya lo frena antes
        con `classify_sii_nip`), y CUALQUIER excepción se convierte en
        `(False, _MSG_SII_ACCOUNT_FAILED, …)` tras `rollback()`, registrando solo
        su TIPO — el mensaje de un error de la BD trae los parámetros del INSERT
        (el hash del NIP; Review Focus 1). El rollback suelta el lock y deshace
        todo lo que el llamador no había commiteado.
        """
        try:
            ok, detalle, summary, user = EnrollmentRequestService._create_account(
                db, req, cohort, nip=secret.reveal(), program_id=program_id,
                actor_id=actor_id, approved_by_id=approved_by_id, nip_source="sii",
                must_change_password=False, event_extra=event_extra)
        except Exception as exc:  # noqa: BLE001 — el texto puede traer el hash
            db.rollback()
            logger.warning("No se pudo crear la cuenta de la solicitud %s con el NIP "
                           "del SII (%s)", req.id, type(exc).__name__)
            return False, _MSG_SII_ACCOUNT_FAILED, None, None
        if not ok and detalle == _MSG_BAD_NIP:
            detalle = _NIP_FAILURE_MSGS["invalid"]
        return ok, detalle, summary, user

    @staticmethod
    def _mail_access(db: Session, req, user, nip: str | None, *, reassigned: bool = False,
                     nip_source: str = "manual") -> bool:
        """Manda usuario + NIP al correo personal. Llamar SOLO después del commit.

        `reassigned=True` (desde `reassign_nip`): el correo dice que el NIP
        reemplaza al anterior. `nip_source="sii"` (modo `sii`): la cuenta nació
        con el NIP del SII y el correo NO lo lleva (`nip` es `None`).

        Si el correo sale, sella `access_sent_at` en un commit propio (mismo
        patrón que `_mail_activation`/`verify_sent_at`); si no, la fila queda
        con `access_granted_at` y sin `access_sent_at`: «correo no enviado»
        (`access_mail_unsent`).
        Un fallo al sellar no deshace nada: el correo ya salió.
        """
        from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

        rid = req.id
        ok = TitulaTecEmailHelper.send_enrollment_approved(db, req, user, nip=nip,
                                                           reassigned=reassigned,
                                                           nip_source=nip_source)
        if ok:
            try:
                req.access_sent_at = datetime.now()
                db.commit()
            except Exception:
                logger.warning("No se pudo sellar el envío del acceso de la solicitud %s", rid)
                try:
                    db.rollback()
                except Exception:      # pragma: no cover - sesión ya inservible
                    pass
        return ok

    @staticmethod
    def verify(db: Session, token: str):
        """Abre la liga de activación. Devuelve `(req|None, outcome)`.

        `outcome ∈ 'converted' | 'already_converted' | 'pending_review' |
        'expired' | 'invalid'`. Solo una solicitud `approved` con la liga vigente
        se convierte; `pending_review`, `rejected`, el legado y un token
        desconocido son `invalid` (invariante: nadie obtiene acceso sin la liga
        de una solicitud aprobada).

        IDEMPOTENTE: Outlook Safe Links y los escáneres corporativos pre-abren
        la liga en cuanto llega. Una convertida devuelve `already_converted` con
        la misma tarjeta, y el hash no se borra al convertir para eso. Las marcas
        puras `can_reassign_nip`/`access_mail_unsent` también se apoyan en ese
        hash para dejar fuera a una D10 convertida; si algún día se borra aquí,
        hay que revisarlas (`reassign_nip` no depende de él: exige la señal
        positiva `_request_created_account`).

        La comparación decisiva usa `hmac.compare_digest`: es una credencial al
        portador y un `==` de Python filtraría por temporización cuántos bytes
        acertó quien lo intenta. Se repite DESPUÉS del lock porque, mientras se
        esperaba, la bandeja pudo rotar la liga (reenvío) o matarla (rechazo).

        Lock por solicitud + `db.refresh(req)` antes de leer el estado: el
        prefetch del escáner en paralelo con el clic humano es el caso NORMAL.

        La primera apertura sella `verified_at`, también cuando la liga ya venció
        (la bandeja muestra "abierta" y el oficial sabe que la persona lo intentó).

        Si `_convert` falla una revalidación, la solicitud vuelve a
        `pending_review` con la nota y la liga muere; en una fila D10 queda el
        sello `access_granted_*` de CC (ver «CORREO NO ENVIADO» en el módulo).
        `_convert` corre en un
        SAVEPOINT: al deshacerlo desaparece lo que `import_rows` ya había hecho
        `flush` (rol de la app, proceso) sin soltar el lock ni perder lo que esta
        pasada decidió. Esa era la trampa de la revisión final §3: un `rollback()`
        completo tira también `verified_at` y expira la solicitud. Una excepción
        no es una revalidación: sube a la ruta, que hace `rollback()` y la
        solicitud sigue aprobada con la liga viva.

        El aviso con folio (al institucional) se ENCOLA en la misma transacción
        de la conversión (`StudentMail.enrollment_verified`, spec 2026-10-05
        §3.7) y lo manda el despachador. Con el correo apagado sale en línea
        (`send_enrollment_done`) después del commit, como antes.
        """
        from itcj2.apps.titulatec.models import EnrollmentRequest, TitulationProcess
        from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper
        from itcj2.apps.titulatec.services.student_mail import StudentMail

        if not token:
            return None, "invalid"
        digest = _sha256(token)
        # La búsqueda por índice la hace O(1); la comparación constante decide.
        req = (db.query(EnrollmentRequest)
               .filter(EnrollmentRequest.verify_token_hash == digest).first())
        if req is None or not hmac.compare_digest(req.verify_token_hash or "", digest):
            return None, "invalid"

        db.execute(text("SELECT pg_advisory_xact_lock(:ns, :key)"),
                   {"ns": _REQUEST_LOCK_NS, "key": int(req.id)})
        db.refresh(req)
        if not hmac.compare_digest(req.verify_token_hash or "", digest):
            return None, "invalid"

        if req.status == "converted":
            return req, "already_converted"
        if req.status != "approved":
            return req, "invalid"

        if req.verified_at is None:
            req.verified_at = datetime.now()
        if req.verify_expires_at is None or req.verify_expires_at < datetime.now():
            db.commit()
            return req, "expired"

        touched: list = []
        savepoint = db.begin_nested()
        try:
            ok, detail = EnrollmentRequestService._convert(db, req, authz_touched=touched)
        except Exception:
            if savepoint.is_active:
                savepoint.rollback()
            raise

        if not ok:
            savepoint.rollback()
            # Se reaplica todo lo que esta pasada decide; el lock sigue tomado
            # porque es de la transacción externa, no del savepoint.
            muerta = req.verify_token_hash
            req.status = "pending_review"
            req.review_note = detail
            req.verified_at = req.verified_at or datetime.now()
            req.verify_token_hash = None
            req.verify_expires_at = None
            db.commit()
            _token_cache_delete(muerta)
            return req, "pending_review"

        savepoint.commit()
        proc = db.get(TitulationProcess, req.converted_process_id)
        # La fila del aviso con folio entra en ESTE commit (P-D1).
        encolado = proc is not None and StudentMail.enrollment_verified(db, req, proc)
        db.commit()
        # Después del commit, con los pares que dejó `import_rows` dentro de
        # `_convert` (ver `ImportService.invalidate_authz`).
        from itcj2.apps.titulatec.services.import_service import ImportService
        ImportService.invalidate_authz(touched)
        if not encolado and proc is not None:
            # Correo apagado: en línea, como antes (invariante 5).
            TitulaTecEmailHelper.send_enrollment_done(db, req, proc)
        return req, "converted"

    @staticmethod
    def _convert(db: Session, req, *, authz_touched: list | None = None):
        """Inscribe la CUENTA EXISTENTE de una solicitud aprobada. `(ok, detalle)`.

        En éxito `detalle` es el folio; en fallo, la `review_note` para la bandeja.
        Todo lo que pudo cambiar desde la aprobación se revisa ANTES de
        `import_rows`: que la convocatoria siga `open` (las fechas no cuentan,
        ver VENTANA en el módulo), formato de los datos, que la
        cuenta siga existiendo, D5 y la contraseña.

        Solo escribe proceso y roles de egresado (vía `import_rows` con
        `commit=False` y `repair_credentials=False`, que no toca credencial,
        `is_active` ni `must_change_password` de una cuenta que ya existe: le deja
        `graduate` y le quita `student`), la solicitud y el `ProcessEvent`. NADA
        del perfil (invariante 1 del módulo). Su ÚNICA escritura propia sobre la
        cuenta es reactivarla si estaba desactivada, con `reactivated` en el
        payload: la excepción aprobada del invariante 1. No commitea, no tira el
        caché de authz ni manda correo: eso es de `verify()`, que recibe en
        `authz_touched` los pares que `import_rows` cambió.

        No se ramifica sobre `processes_created`: si un CSV creó el proceso
        mientras la persona no abría la liga, la conversión es igual de exitosa.
        Solo la AUSENCIA de proceso es un fallo.
        """
        from itcj2.core.models.user import User
        from itcj2.apps.titulatec.models import Cohort, ProcessEvent, TitulationProcess
        from itcj2.apps.titulatec.services.cohort_service import CohortService
        from itcj2.apps.titulatec.services.import_service import ImportService

        # El estado se revisa sobre la convocatoria GUARDADA en la solicitud: el
        # periodo va dentro del folio y de la ruta en disco.
        cohort = db.get(Cohort, req.cohort_id)
        if not CohortService.accepts_enrollment_followup(cohort):
            return False, _NOTE_LINK_COHORT_CLOSED

        control = (req.control_number or "").strip()
        full_name = _full_name(req)
        if not CONTROL_NUMBER_RE.fullmatch(control) or not full_name:
            return False, _MSG_BAD_DATA

        user = db.query(User).filter_by(control_number=control).first()
        if user is None:
            return False, _NOTE_LINK_NO_ACCOUNT
        if _has_process_in_other_cohort(db, user.id, req.cohort_id):
            return False, _MSG_OTHER_COHORT
        if _has_revoked_process_here(db, user.id, req.cohort_id):
            return False, _MSG_REVOKED_HERE
        if not user.password_hash:
            return False, _MSG_NO_PASSWORD

        ya_existia = (db.query(TitulationProcess)
                      .filter_by(student_id=user.id, cohort_id=req.cohort_id)
                      .first()) is not None

        summary = ImportService.import_rows(
            db, cohort,
            [{"control_number": control, "full_name": full_name, "email": None,
              "program_id": req.program_id, "modality_id": None}],
            actor_id=None, source="self_service", repair_credentials=False,
            commit=False,
        )
        if authz_touched is not None:
            authz_touched.extend((summary or {}).get("authz_touched") or ())

        proc = (db.query(TitulationProcess)
                .filter_by(student_id=user.id, cohort_id=req.cohort_id).first())
        if proc is None:
            return False, _NOTE_LINK_NO_PROCESS

        # EXCEPCIÓN APROBADA al invariante 1 (2026-09-15): la liga de una
        # solicitud aprobada reactiva la cuenta desactivada. Es la única
        # escritura sobre la cuenta además de roles y proceso, y va aquí, con el
        # proceso ya creado: una revalidación fallida no llega, y cualquier
        # fallo posterior la deshace con el savepoint de `verify`.
        reactivada = not user.is_active
        if reactivada:
            user.is_active = True

        req.status = "converted"
        req.converted_process_id = proc.id
        db.add(ProcessEvent(
            process_id=proc.id, actor_id=None,
            event_type="enrollment_self_service", phase_number=0,
            payload={"request_id": req.id, "folio": proc.folio,
                     "preexisting_process": ya_existia,
                     "activation": "personal_email_link",
                     "approved_by_id": req.reviewed_by_id,
                     # Rastro de la excepción: la bandeja la anuncia antes de
                     # aprobar y el expediente la conserva después.
                     "reactivated": reactivada},
        ))
        return True, proc.folio

    @staticmethod
    def reject(db: Session, req_id: int, *, note: str, actor_id: int) -> bool:
        """Rechaza con motivo obligatorio. `True` si se rechazó.

        Aplica desde `pending_review`, `awaiting_access` (SE cancela una que
        esperaba a Centro de Cómputo), `approved` (cancela una liga en camino) y
        el legado. La liga muere en BD y en Redis. El índice parcial deja volver
        a intentar.

        El correo con el motivo (al personal, firmado por `reviewer_label()`) se
        ENCOLA en la misma transacción del rechazo (`StudentMail.
        enrollment_rejected`, spec 2026-10-05 §3.7): lo manda el despachador,
        que sella `rejection_sent_at` al salir. Mientras su fila esté `pending`
        la bandeja dice «en cola»; `NULL` sin fila pendiente es «correo no
        enviado».

        Con el correo apagado sale en línea después del commit, como antes: si
        SALE, sella `rejection_sent_at` en un commit propio (mismo patrón que
        `_mail_activation`/`verify_sent_at`; un fallo al sellar no deshace
        nada, el correo ya salió).
        """
        from itcj2.apps.titulatec.models import EnrollmentRequest
        from itcj2.apps.titulatec.services.audit_service import AuditService
        from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper
        from itcj2.apps.titulatec.services.student_mail import StudentMail

        motivo = (note or "").strip()
        if not motivo:
            return False
        req = db.get(EnrollmentRequest, req_id)
        if req is None:
            return False
        db.execute(text("SELECT pg_advisory_xact_lock(:ns, :key)"),
                   {"ns": _REQUEST_LOCK_NS, "key": int(req.id)})
        db.refresh(req)
        if req.status not in _REJECTABLE:
            return False

        muerta = req.verify_token_hash
        estado_previo = req.status
        req.status = "rejected"
        req.review_note = motivo[:2000]
        req.reviewed_by_id = actor_id
        req.reviewed_at = datetime.now()
        req.verify_token_hash = None
        req.verify_expires_at = None
        # La fila del correo entra en ESTE commit (P-D1).
        encolado = StudentMail.enrollment_rejected(db, req)
        AuditService.record(
            db, "enrollment.rejected",
            entity_type="enrollment_request", entity_id=req.id,
            subject=_audit_subject(req), reason=motivo,
            before={"status": estado_previo}, after={"status": "rejected"},
            actor_id=actor_id)
        db.commit()
        _token_cache_delete(muerta)
        if not encolado and TitulaTecEmailHelper.send_enrollment_rejected(db, req):
            try:
                req.rejection_sent_at = datetime.now()
                db.commit()
            except Exception:
                logger.warning(
                    "No se pudo sellar el envío del rechazo de la solicitud %s", req_id)
                try:
                    db.rollback()
                except Exception:      # pragma: no cover - sesión ya inservible
                    pass
        return True

    @staticmethod
    def reopen(db: Session, req_id: int, *, note: str, actor_id: int):
        """SE deshace un rechazo: `rejected -> pending_review`. `(ok, detalle)`.

        Para cuando la persona va a ventanilla y aclara lo que motivó el
        rechazo. Nota obligatoria (qué se aclaró), ≤2000 tras quitar espacios
        y, como en `return_to_review`, una más larga se RECHAZA en vez de
        recortarse. Escribe `reopened_*`/`reopen_note`; `review_note` y
        `reviewed_*` se quedan con el rechazo deshecho hasta que SE vuelva a
        resolver. Después se aprueba por el camino normal (SII, NIP, liga).

        SIN correo: la persona está en ventanilla. Si el correo del rechazo
        seguía en el outbox, el despachador lo cierra `obsolete` al ver que la
        solicitud ya no está `rejected` (D8, `_compose_enrollment_rejected`).
        `rejection_sent_at` se limpia: el sello es del rechazo VIGENTE, y si SE
        la rechaza otra vez la bandeja tiene que poder decir «en cola».

        No se reabre si la convocatoria ya no acepta seguimiento (el mismo
        corte que `approve`), ni si el mismo control tiene OTRA solicitud viva
        (el índice parcial lo prohibiría) o ya inscrita en esta convocatoria.
        """
        from itcj2.apps.titulatec.models import EnrollmentRequest
        from itcj2.apps.titulatec.models.enrollment_request import OPEN_STATUSES
        from itcj2.apps.titulatec.services.audit_service import AuditService

        motivo = (note or "").strip()
        if not motivo:
            return False, _MSG_REOPEN_NOTE
        if len(motivo) > _RETURN_NOTE_MAX:
            return False, _MSG_REOPEN_NOTE_LONG
        req = db.get(EnrollmentRequest, req_id)
        if req is None:
            return False, _MSG_GONE
        db.execute(text("SELECT pg_advisory_xact_lock(:ns, :key)"),
                   {"ns": _REQUEST_LOCK_NS, "key": int(req.id)})
        db.refresh(req)
        if req.status != "rejected":
            return False, _MSG_NOT_REJECTED
        cohort, cerrada = _cohort_gate(db, req)
        if cohort is None:
            return False, cerrada

        otras = {s for (s,) in (
            db.query(EnrollmentRequest.status)
            .filter(EnrollmentRequest.cohort_id == req.cohort_id,
                    EnrollmentRequest.control_number == req.control_number,
                    EnrollmentRequest.id != req.id,
                    EnrollmentRequest.status.in_(OPEN_STATUSES + ("converted",)))
            .all())}
        if otras & set(OPEN_STATUSES):
            return False, _MSG_REOPEN_OTHER_OPEN
        if "converted" in otras:
            return False, _MSG_REOPEN_OTHER_CONVERTED

        req.status = "pending_review"
        req.reopened_by_id = actor_id
        req.reopened_at = datetime.now()
        req.reopen_note = motivo
        req.rejection_sent_at = None
        AuditService.record(
            db, "enrollment.reopened",
            entity_type="enrollment_request", entity_id=req.id,
            subject=_audit_subject(req), reason=motivo,
            before={"status": "rejected"}, after={"status": "pending_review"},
            actor_id=actor_id)
        try:
            db.commit()
        except IntegrityError:
            # Otra solicitud del mismo control entró viva entre la consulta y el
            # commit (el lock es por solicitud, no por control): el índice
            # parcial la detiene aquí.
            db.rollback()
            return False, _MSG_REOPEN_OTHER_OPEN
        return True, ""

    @staticmethod
    def resend_link(db: Session, req_id: int):
        """Reenvío desde la bandeja. Devuelve `(ok, detalle)`.

        Solo para `approved`, y ROTA la liga: hash y vencimiento nuevos, la copia
        vieja se borra de Redis y la liga anterior deja de servir. Rotar es seguro
        aquí porque el actor está autenticado y la ruta ya lo acotó por carrera;
        el veto a rotar es del reenvío PÚBLICO. No lleva presupuesto.

        Con la convocatoria `closed` (pausa) no se emite liga nueva; pasada
        `closes_at` sí (VENTANA, en el módulo).
        """
        from itcj2.apps.titulatec.models import EnrollmentRequest
        from itcj2.apps.titulatec.services.audit_service import AuditService

        req = db.get(EnrollmentRequest, req_id)
        if req is None:
            return False, _MSG_GONE
        db.execute(text("SELECT pg_advisory_xact_lock(:ns, :key)"),
                   {"ns": _REQUEST_LOCK_NS, "key": int(req.id)})
        db.refresh(req)
        if req.status != "approved":
            return False, _MSG_ONLY_APPROVED
        cohort, motivo = _cohort_gate(db, req)
        if cohort is None:
            return False, motivo

        muerta = req.verify_token_hash
        raw = EnrollmentRequestService._issue_activation(req)
        req.verify_send_count = (req.verify_send_count or 0) + 1
        # La liga nueva jamás entra a la bitácora; solo el hecho y quién lo pidió.
        AuditService.record(
            db, "enrollment.link_resent",
            entity_type="enrollment_request", entity_id=req.id,
            subject=_audit_subject(req), payload={"by": "admin"})
        db.commit()
        _token_cache_delete(muerta)
        _token_cache_put(raw)
        EnrollmentRequestService._mail_activation(db, req, raw)
        return True, ""

    @staticmethod
    def resend(db: Session, control_number: str, contact_email: str) -> str:
        """Reenvío PÚBLICO de la liga. Devuelve `'sent'` o `'noop'`.

        Solo actúa sobre una solicitud `approved` que case con
        (control_number, contact_email), y reenvía EL MISMO token (el claro de
        Redis): no rota ni alarga la vida de la liga, que las fija la bandeja.
        Presupuesto: `MAX_VERIFY_SENDS` envíos en total y al menos
        `MIN_SECONDS_BETWEEN_SENDS` entre uno y otro.

        `'noop'` cubre TODO lo que no manda correo: no casa, otro estado, tope,
        muy pronto, convocatoria no `open` (las fechas no cuentan: VENTANA, en el
        módulo), liga vencida y la falta del claro en Redis
        (se falla cerrado). La respuesta HTTP es la misma en todos los casos: esa
        igualdad es un invariante (§6.8), no un descuido; darle tarjeta propia a
        cualquiera de ellos haría del endpoint un oráculo de existencia.

        La llave nunca es el `id`: es un BigInteger secuencial y cualquiera
        enumeraría 1..N para disparar correos a buzones ajenos.
        """
        from sqlalchemy import func
        from itcj2.core.utils.email_tools import normalize_email
        from itcj2.apps.titulatec.models import Cohort, EnrollmentRequest
        from itcj2.apps.titulatec.services.audit_service import AuditService
        from itcj2.apps.titulatec.services.cohort_service import CohortService

        control = (control_number or "").strip()
        email = normalize_email(contact_email) or ""
        if not control or not email:
            return "noop"

        req = (db.query(EnrollmentRequest)
               .filter(EnrollmentRequest.control_number == control,
                       func.lower(EnrollmentRequest.contact_email) == email.lower(),
                       EnrollmentRequest.status == "approved")
               .order_by(EnrollmentRequest.id.desc())
               .first())
        if req is None:
            return "noop"
        db.execute(text("SELECT pg_advisory_xact_lock(:ns, :key)"),
                   {"ns": _REQUEST_LOCK_NS, "key": int(req.id)})
        db.refresh(req)
        if req.status != "approved":
            return "noop"

        cohort = db.get(Cohort, req.cohort_id)
        if not CohortService.accepts_enrollment_followup(cohort):
            return "noop"
        now = datetime.now()
        if (req.verify_send_count or 0) >= MAX_VERIFY_SENDS:
            return "noop"
        if (req.verify_sent_at is not None
                and (now - req.verify_sent_at).total_seconds() < MIN_SECONDS_BETWEEN_SENDS):
            return "noop"
        if req.verify_expires_at is None or req.verify_expires_at < now:
            return "noop"
        raw = _token_cache_get(req.verify_token_hash or "")
        if raw is None:
            return "noop"

        req.verify_send_count = (req.verify_send_count or 0) + 1
        AuditService.record(
            db, "enrollment.link_resent",
            entity_type="enrollment_request", entity_id=req.id,
            subject=_audit_subject(req), payload={"by": "public"})
        db.commit()
        return "sent" if EnrollmentRequestService._mail_activation(db, req, raw) else "noop"

    @staticmethod
    def _link_ttl_hours() -> int:
        """Vida de la liga de activación, en horas (TITULATEC_ENROLLMENT_LINK_TTL_DAYS).

        ÚNICA fuente: el vencimiento en BD (`_issue_activation`), el TTL del
        claro en Redis (`_token_cache_put`) y los "N días" del correo
        (`TitulaTecEmailHelper.send_verify_enrollment`) la llaman en cada uso,
        así que no pueden divergir. Los tests parchean ESTE método, nunca
        `get_settings`.
        """
        from itcj2.config import get_settings

        return get_settings().TITULATEC_ENROLLMENT_LINK_TTL_DAYS * 24

    @staticmethod
    def link_ttl_days() -> int:
        """Vida de la liga en DÍAS, para lo que la pinta (bandejas y correo).

        Accesor PÚBLICO: las páginas y el helper de correo no llaman al privado
        `_link_ttl_hours()`. Deriva de él, así que sigue siendo una sola fuente
        (y parchear `_link_ttl_hours` en un test alcanza también a este).
        """
        return EnrollmentRequestService._link_ttl_hours() // 24

    @staticmethod
    def _issue_activation(req) -> str:
        """Emite (o rota) la liga de activación de `req`. Devuelve el claro.

        Solo sella la fila; el llamador fija el contador, commitea, cachea el
        claro y manda (`_mail_activation`), en ese orden. `verify_sent_at` y
        `verified_at` vuelven a NULL: "enviada" y "abierta" hablan de la liga
        vigente, no de una anterior.
        """
        raw = secrets.token_urlsafe(32)
        req.verify_token_hash = _sha256(raw)
        req.verify_expires_at = (datetime.now()
                                 + timedelta(hours=EnrollmentRequestService._link_ttl_hours()))
        req.verify_sent_to = req.contact_email
        req.verify_sent_at = None
        req.verified_at = None
        return raw

    @staticmethod
    def _mail_activation(db: Session, req, raw: str) -> bool:
        """Manda la liga al correo personal. Llamar SOLO después del commit.

        Si el correo sale, sella `verify_sent_at` en un commit propio; si no, la
        bandeja lo muestra como "correo no enviado" y ofrece reenviar. Un fallo
        al sellar no deshace nada: el correo ya salió.
        """
        from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

        rid = req.id
        ok = TitulaTecEmailHelper.send_verify_enrollment(db, req, link=_verify_link(raw))
        if ok:
            try:
                req.verify_sent_at = datetime.now()
                db.commit()
            except Exception:
                logger.warning("No se pudo sellar el envío de la liga de la solicitud %s", rid)
                try:
                    db.rollback()
                except Exception:      # pragma: no cover - sesión ya inservible
                    pass
        return ok

    @staticmethod
    def stats(db: Session, *, scope, cohort_id: int | None = None, today: date | None = None):
        """KPIs y "por año de ingreso" de la bandeja. Puro respecto a HTTP: solo
        lee, no lanza, no depende de `Request`. `pages/requests_admin.py::_body_ctx`
        solo la invoca.

        `scope`: `'ALL'` o `set[int]` de `program_id`, el MISMO criterio que
        `scope_service.officer_programs` — el mismo con el que la bandeja filtra su
        listado (invariante: los KPIs y el listado cuentan sobre el mismo universo).
        Un set vacío devuelve todo en cero sin tocar la BD: el caller real
        (`_body_ctx`) ya corta antes con `no_programs`, esto es solo para no
        reventar si alguien la llama igual.

        Devuelve `{"counts": {...}, "by_year": [...], "year_max": int}`:

        - `counts`: conteos de SOLICITUDES (una fila = una solicitud) agrupados con
          `_STATUS_GROUP` — `total`, `review` (por revisar, incluido el legado),
          `access` (en Centro de Cómputo, `awaiting_access`), `sent` (liga
          enviada), `converted` (inscritas), `rejected`. Mismo alcance
          y `cohort_id` que el listado, pero SIN filtro de pestaña, sin búsqueda
          y sin paginar: es el universo completo de la convocatoria (o de todas).
        - `by_year`: una entrada por año de ingreso (`entry_year`, orden
          descendente, "Sin año" al final), contando PERSONAS únicas (número de
          control distinto) por la solicitud MÁS RECIENTE (`created_at`, `id`) de
          cada una dentro de este mismo alcance/convocatoria — no solicitudes:
          dos intentos de la misma persona no deben contarla dos veces. Cada
          entrada trae el mismo desglose de `counts` sobre esas personas.
        - `year_max`: el `total` más alto de `by_year` (0 si está vacío), para que
          la plantilla dibuje la barra de cada año proporcional al máximo sin
          tener que recalcularlo (p. ej. como `max` de un `<meter>`).
        """
        from itcj2.apps.titulatec.models import EnrollmentRequest

        counts = {"total": 0, "review": 0, "access": 0, "sent": 0, "converted": 0,
                  "rejected": 0}
        if scope != "ALL" and not scope:
            return {"counts": counts, "by_year": [], "year_max": 0}

        q = db.query(EnrollmentRequest.id, EnrollmentRequest.control_number,
                     EnrollmentRequest.status, EnrollmentRequest.created_at)
        if scope != "ALL":
            q = q.filter(EnrollmentRequest.program_id.in_(scope))
        if cohort_id:
            q = q.filter(EnrollmentRequest.cohort_id == cohort_id)

        # Más reciente por control: (created_at, id) más alto gana. `created_at`
        # trae `server_default=NOW()` (nunca NULL en una fila real), `datetime.min`
        # es solo para que el `max()` no reviente si alguna vez lo fuera.
        latest_by_control: dict[str, tuple] = {}
        for rid, control, status, created_at in q.all():
            counts["total"] += 1
            counts[_STATUS_GROUP.get(status, "review")] += 1
            if not control:
                continue
            key = (created_at or datetime.min, rid)
            if control not in latest_by_control or key > latest_by_control[control][0]:
                latest_by_control[control] = (key, status)

        years: dict[str, dict] = {}
        for control, (_key, status) in latest_by_control.items():
            year = entry_year(control, today)
            if year not in years:
                # `slug` es un token seguro para `id="..."` en la plantilla: "Sin
                # año" trae espacio y una ñ, y un `id` con espacio es HTML
                # inválido (rompe el emparejado de Idiomorph). Los años reales ya
                # son 4 dígitos: sirven tal cual.
                slug = year if year != "Sin año" else "sin-anio"
                years[year] = {"year": year, "slug": slug, "total": 0, "review": 0,
                               "access": 0, "sent": 0, "converted": 0, "rejected": 0}
            bucket = years[year]
            bucket["total"] += 1
            bucket[_STATUS_GROUP.get(status, "review")] += 1

        by_year = sorted(
            years.values(),
            key=lambda y: (0, -int(y["year"])) if y["year"] != "Sin año" else (1, 0),
        )
        year_max = max((y["total"] for y in by_year), default=0)

        # Lo que se lee con el bloque CERRADO (`<summary>` de la bandeja): con
        # 20+ generaciones el bloque abierto no cabe en pantalla, así que el
        # resumen tiene que bastar para decidir si vale la pena abrirlo.
        # `peak` desempata por el año MÁS RECIENTE; «Sin año» no compite ni
        # entra al rango.
        reales = [y for y in by_year if y["year"] != "Sin año"]
        pico = max(reales, key=lambda y: (y["total"], int(y["year"])), default=None)
        summary = {
            "people": len(latest_by_control),
            "generations": len(by_year),
            "span": (f"{reales[-1]['year']}–{reales[0]['year']}"
                     if len(reales) > 1 else (reales[0]["year"] if reales else "")),
            "peak": ({"year": pico["year"], "total": pico["total"]} if pico else None),
        }
        return {"counts": counts, "by_year": by_year, "year_max": year_max,
                "summary": summary}
