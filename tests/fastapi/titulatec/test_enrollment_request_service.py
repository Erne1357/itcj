"""`EnrollmentRequestService` a nivel de servicio: alta, rechazo, tokens e índice.

Desde 2026-09-15 TODA solicitud pasa por la bandeja de Servicios Escolares:
`create()` deja la fila en `pending_review` sin token y sin correo, y el acceso
llega solo por correo tras la revisión (NIP para una cuenta nueva, liga de
activación para una que ya existe). Este archivo fija el alta, el rechazo y las
piezas de token que comparten `approve()`, `verify()` y los reenvíos.

El nivel HTTP (ventana pública, confirmación del correo, trampa, límites, E8
sobre bytes) vive en `test_enrollment_public.py`; la aprobación en
`test_enrollment_approve.py`; la liga en `test_enrollment_verify.py`; los
reenvíos en `test_enrollment_resend.py`.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

import pytest


# ---------------------------------------------------------------------------
# Captura de correo. Local a este archivo a propósito (mismo patrón que el resto
# de la suite): no se importa de otro módulo de pruebas.
# ---------------------------------------------------------------------------
@pytest.fixture()
def correo_falso(monkeypatch):
    """Captura los envíos de TitulaTecEmailHelper sin tocar Graph.

    Devuelve la lista de `(asunto, destinatarios, html)`, en el ORDEN en que se
    mandaron.
    """
    enviados = []

    class _Resp:
        status_code = 202
        text = ""

    def _fake_send(access_token, subject, content_html, to_list, save_to_sent=True):
        enviados.append((subject, list(to_list), content_html))
        return _Resp()

    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.acquire_token_silent",
                        lambda app_key: "token-de-prueba")
    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.graph_send_mail", _fake_send)
    return enviados


@pytest.fixture()
def espia_helper(monkeypatch):
    """Sustituye TODOS los `send_*` del helper por un registro de llamadas.

    Se enumeran con `dir()` en vez de una lista fija: un correo nuevo que alguien
    agregue al alta tiene que salir en rojo aquí sin que nadie actualice la lista.
    """
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    llamadas = []
    for nombre in [n for n in dir(TitulaTecEmailHelper) if n.startswith("send_")]:
        monkeypatch.setattr(
            TitulaTecEmailHelper, nombre,
            staticmethod(lambda *a, _n=nombre, **k: llamadas.append(_n) or True))
    return llamadas


@pytest.fixture()
def orden_commit_correo(db_session, monkeypatch):
    """Registra, en orden, cada `db_session.commit()` y cada envío por Graph.

    Es la forma de probar "el correo sale DESPUÉS del commit" dentro de una sola
    sesión: si el envío apareciera antes del primer commit, un fallo al
    commitear dejaría un correo que habla de algo que no existe.
    """
    orden, enviados = [], []
    commit_real = db_session.commit

    def _commit():
        orden.append("commit")
        return commit_real()

    class _Resp:
        status_code = 202
        text = ""

    def _fake_send(access_token, subject, content_html, to_list, save_to_sent=True):
        orden.append("correo")
        enviados.append((subject, list(to_list), content_html))
        return _Resp()

    monkeypatch.setattr(db_session, "commit", _commit)
    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.acquire_token_silent",
                        lambda app_key: "token-de-prueba")
    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.graph_send_mail", _fake_send)
    return orden, enviados


def _data(**kw):
    base = dict(control_number="99000001", first_name="EGRESADA", last_name="FICTICIA",
                middle_name="", program_id=None, program_text="Ingenieria Ficticia",
                phone="6561234567", contact_email="personal@example.invalid",
                has_efirma=False)
    base.update(kw)
    return base


def _fila(db_session, cohort, *, control, status="pending_review",
          email="personal@example.invalid", con_token=False, **kw):
    """Solicitud a mano. Con `con_token` trae liga emitida; devuelve `(req, token)`."""
    from itcj2.apps.titulatec.models import EnrollmentRequest

    token = secrets.token_urlsafe(32) if con_token else None
    row = EnrollmentRequest(
        cohort_id=cohort.id, control_number=control,
        first_name="EGRESADA", last_name="FICTICIA", phone="6560000000",
        contact_email=email, has_efirma=False, kind="unknown", status=status,
        verify_token_hash=(hashlib.sha256(token.encode("utf-8")).hexdigest()
                           if token else None),
        verify_expires_at=(datetime.now() + timedelta(days=7)) if token else None,
        verify_send_count=1 if token else 0,
    )
    for k, v in kw.items():
        setattr(row, k, v)
    db_session.add(row)
    db_session.flush()
    return row, token


# ---------------------------------------------------------------------------
# Constantes y piezas de token
# ---------------------------------------------------------------------------
def test_constantes_del_contrato():
    from itcj2.apps.titulatec.services import enrollment_request_service as mod
    from itcj2.apps.titulatec.services.import_service import CONTROL_NUMBER_RE as re_original

    assert mod.VERIFY_TTL_HOURS == 168, "la liga de activación vive 7 días"
    assert mod.MAX_VERIFY_SENDS == 3
    assert mod.MIN_SECONDS_BETWEEN_SENDS == 300
    assert mod.MAX_PUBLIC_BODY_BYTES == 256 * 1024
    assert mod.STATUSES == (
        "unverified", "verified", "pending_review", "approved", "rejected", "converted")
    assert mod.CONTROL_NUMBER_RE is re_original, (
        "CONTROL_NUMBER_RE debe ser el MISMO objeto que import_service.py: dos "
        "regex que divergen validarian numeros de control distinto segun la "
        "ruta que se tome."
    )


def test_ya_no_existe_ninguna_liga_de_contacto():
    """La segunda liga ("confirma tu correo de contacto") desaparece: el correo
    personal ya se prueba al abrir la liga de activación, que viaja justo ahí.
    El 2026-09-15 se retiró también su canje (`confirm_contact`, la ruta
    `GET /titulatec/inscripcion/correo` y su plantilla): canjeaba contra
    `core_student_profile` con la sola prueba de un buzón tecleado. Las columnas
    `contact_token_hash`/`contact_expires_at` quedan en BD como legado sin uso."""
    from itcj2.apps.titulatec.services import enrollment_request_service as mod

    for nombre in ("CONTACT_TTL_HOURS", "_contact_link"):
        assert not hasattr(mod, nombre), nombre
    for nombre in ("_issue_contact_token", "_send_contact_link", "confirm_contact"):
        assert not hasattr(mod.EnrollmentRequestService, nombre), nombre


def test_la_liga_de_activacion_usa_public_base_url_y_query_t():
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        PUBLIC_BASE_URL, _verify_link,
    )

    assert _verify_link("abc") == f"{PUBLIC_BASE_URL}/titulatec/inscripcion/verificar?t=abc"


def test_el_claro_del_token_vive_en_redis_lo_mismo_que_la_liga_y_se_puede_borrar():
    """E7: la BD solo guarda el sha256; el claro vive en Redis con la MISMA llave.

    `raw` lleva un `uuid4`: la llave es `sha256(raw)` y un literal fijo sobrevive
    entre corridas de la suite.
    """
    import uuid

    from itcj2.apps.titulatec.services.enrollment_request_service import (
        VERIFY_TTL_HOURS, _TOKEN_CACHE_PREFIX, _redis, _sha256, _token_cache_delete,
        _token_cache_get, _token_cache_put,
    )

    raw = f"token-de-prueba-{uuid.uuid4().hex}"
    digest = _sha256(raw)

    assert _token_cache_get(digest) is None, "no deberia haber nada cacheado aun"
    _token_cache_put(raw)
    assert _token_cache_get(digest) == raw
    ttl = _redis().ttl(_TOKEN_CACHE_PREFIX + digest)
    assert VERIFY_TTL_HOURS * 3600 - 120 < ttl <= VERIFY_TTL_HOURS * 3600

    _token_cache_delete(digest)
    assert _token_cache_get(digest) is None
    _token_cache_delete(None)          # best-effort: nunca revienta


# ---------------------------------------------------------------------------
# create(): toda solicitud nueva queda en revisión, sin token y sin correo
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("con_cuenta", [False, True], ids=["sin-cuenta", "con-cuenta"])
def test_create_deja_la_solicitud_en_revision_sin_token_ni_correo(
    db_session, make_cohort, make_student, espia_helper, correo_falso, con_cuenta,
):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    control = "99880001" if con_cuenta else "99000001"
    if con_cuenta:
        make_student(control_number=control)
    cohort = make_cohort()

    req, outcome = EnrollmentRequestService.create(
        db_session, cohort, _data(control_number=control), client_ip="203.0.113.1")

    assert outcome == "created"
    assert req.status == "pending_review"
    assert req.kind == ("known" if con_cuenta else "unknown"), "`kind` se guarda para mostrar"
    assert req.verify_token_hash is None
    assert req.verify_expires_at is None
    assert req.verify_send_count == 0
    assert req.verify_sent_to is None and req.verify_sent_at is None
    assert req.verified_at is None
    assert req.contact_token_hash is None
    assert espia_helper == [], "el alta no puede mandar ningún correo"
    assert correo_falso == []


@pytest.mark.parametrize("status", ["pending_review", "approved", "unverified", "verified"])
def test_create_con_una_solicitud_viva_no_hace_nada(
    db_session, make_cohort, espia_helper, status,
):
    """Rama (b). Se dispara con SOLO el número de control, que cualquiera puede
    teclear: no puede reenviar, rotar, redirigir ni reescribir nada de la
    solicitud de otra persona."""
    from itcj2.apps.titulatec.models import EnrollmentRequest
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    cohort = make_cohort()
    viva, _tok = _fila(db_session, cohort, control="99000002", status=status,
                       email="primero@example.invalid", con_token=(status == "approved"))
    hash_antes, envios_antes = viva.verify_token_hash, viva.verify_send_count

    req, outcome = EnrollmentRequestService.create(
        db_session, cohort,
        _data(control_number="99000002", contact_email="otro@example.invalid"),
        client_ip="203.0.113.4")

    assert outcome == "existing_request"
    assert req is not None and req.id == viva.id
    assert (db_session.query(EnrollmentRequest)
            .filter_by(cohort_id=cohort.id, control_number="99000002").count()) == 1
    db_session.refresh(viva)
    assert viva.status == status
    assert viva.contact_email == "primero@example.invalid"
    assert viva.verify_token_hash == hash_antes
    assert viva.verify_send_count == envios_antes
    assert espia_helper == []


def test_create_tras_un_rechazo_abre_una_solicitud_nueva(db_session, make_cohort):
    from itcj2.apps.titulatec.models import EnrollmentRequest
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    cohort = make_cohort()
    viejo, _ = _fila(db_session, cohort, control="99000003", status="rejected")

    req, outcome = EnrollmentRequestService.create(
        db_session, cohort, _data(control_number="99000003"), client_ip=None)

    assert outcome == "created"
    assert req.id != viejo.id and req.status == "pending_review"
    assert (db_session.query(EnrollmentRequest)
            .filter_by(cohort_id=cohort.id, control_number="99000003").count()) == 2


def test_create_con_proceso_vivo_avisa_al_institucional_y_no_crea_fila(
    db_session, make_cohort, make_student, make_process, seed_phase_defs,
    correo_falso,
):
    """D5: proceso vivo en CUALQUIER convocatoria bloquea, sin crear solicitud."""
    from itcj2.core.utils.email_tools import student_email
    from itcj2.apps.titulatec.models import EnrollmentRequest
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    seed_phase_defs()
    otra = make_cohort()
    cohort = make_cohort()
    alumno = make_student(control_number="99880002")
    make_process(alumno, cohort=otra)

    req, outcome = EnrollmentRequestService.create(
        db_session, cohort,
        _data(control_number="99880002", contact_email="extrano@example.invalid"),
        client_ip="203.0.113.5")

    assert outcome == "existing_process"
    assert req is None
    assert (db_session.query(EnrollmentRequest)
            .filter_by(control_number="99880002").count()) == 0
    assert [dest for _a, dest, _h in correo_falso] == [[student_email(alumno)]], (
        "el aviso va al buzón institucional, nunca al que se tecleó")


def test_created_ip_hash_nunca_guarda_la_ip_en_claro(db_session, make_cohort):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    cohort = make_cohort()

    req, _outcome = EnrollmentRequestService.create(
        db_session, cohort, _data(control_number="99000005"), client_ip="198.51.100.7")

    assert req.created_ip_hash is not None
    assert "198.51.100.7" not in req.created_ip_hash
    assert len(req.created_ip_hash) == 64  # hexdigest sha256


def test_created_ip_hash_es_none_sin_ip(db_session, make_cohort):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    cohort = make_cohort()

    req, _outcome = EnrollmentRequestService.create(
        db_session, cohort, _data(control_number="99000006"), client_ip=None)

    assert req.created_ip_hash is None


# ---------------------------------------------------------------------------
# reject(): desde revisión, aprobada o legado; mata la liga; correo tras commit
# ---------------------------------------------------------------------------
def test_rechazar_una_en_revision_la_cierra_y_avisa_despues_del_commit(
    db_session, make_cohort, make_user, orden_commit_correo,
):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    orden, enviados = orden_commit_correo
    actor = make_user()
    cohort = make_cohort()
    req, _ = _fila(db_session, cohort, control="99000010")

    ok = EnrollmentRequestService.reject(db_session, req.id,
                                         note="  No aparece en el padrón.  ",
                                         actor_id=actor.id)

    assert ok is True
    assert req.status == "rejected"
    assert req.review_note == "No aparece en el padrón."
    assert req.reviewed_by_id == actor.id and req.reviewed_at is not None
    assert orden == ["commit", "correo"], "el aviso salió antes de commitear el rechazo"
    (_asunto, destinatarios, html), = enviados
    assert destinatarios == ["personal@example.invalid"]
    assert "No aparece en el padrón." in html


def test_rechazar_una_aprobada_deja_su_liga_muerta(
    db_session, make_cohort, make_user, correo_falso,
):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService, _token_cache_get, _token_cache_put,
    )

    actor = make_user()
    cohort = make_cohort()
    req, token = _fila(db_session, cohort, control="99000011", status="approved",
                       con_token=True)
    digest = req.verify_token_hash
    _token_cache_put(token)

    ok = EnrollmentRequestService.reject(db_session, req.id, note="Cancelada",
                                         actor_id=actor.id)

    assert ok is True
    assert req.status == "rejected"
    assert req.verify_token_hash is None and req.verify_expires_at is None
    assert _token_cache_get(digest) is None, "el texto claro de la liga sigue en Redis"
    _, outcome = EnrollmentRequestService.verify(db_session, token)
    assert outcome == "invalid"


@pytest.mark.parametrize("status", ["unverified", "verified"])
def test_rechazar_una_solicitud_legado_tambien_aplica(
    db_session, make_cohort, make_user, correo_falso, status,
):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    actor = make_user()
    cohort = make_cohort()
    req, _ = _fila(db_session, cohort, control="99000012", status=status, con_token=True)

    assert EnrollmentRequestService.reject(db_session, req.id, note="Legado",
                                           actor_id=actor.id) is True
    assert req.status == "rejected" and req.verify_token_hash is None


@pytest.mark.parametrize("status", ["converted", "rejected"])
def test_rechazar_una_resuelta_no_hace_nada(
    db_session, make_cohort, make_user, correo_falso, status,
):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    actor = make_user()
    cohort = make_cohort()
    req, _ = _fila(db_session, cohort, control="99000013", status=status,
                   review_note="nota original")

    assert EnrollmentRequestService.reject(db_session, req.id, note="Otra",
                                           actor_id=actor.id) is False
    db_session.refresh(req)
    assert req.status == status and req.review_note == "nota original"
    assert correo_falso == []


def test_rechazar_sin_motivo_no_hace_nada(db_session, make_cohort, make_user, correo_falso):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    actor = make_user()
    cohort = make_cohort()
    req, _ = _fila(db_session, cohort, control="99000014")

    assert EnrollmentRequestService.reject(db_session, req.id, note="   ",
                                           actor_id=actor.id) is False
    assert req.status == "pending_review"
    assert correo_falso == []


def _cuerpo_sin_docstring(func):
    import inspect

    src = inspect.getsource(func)
    _, _, cuerpo = src.partition('"""')
    _, _, cuerpo = cuerpo.partition('"""')
    return cuerpo


def test_reject_toma_lock_y_refresca_antes_de_leer_status():
    """Mismo patrón que `verify()`: sin lock + refresh, un rechazo concurrente con
    la apertura de la liga podía leer `approved` ya convertido."""
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    cuerpo = _cuerpo_sin_docstring(EnrollmentRequestService.reject)
    lock_pos = cuerpo.index("pg_advisory_xact_lock")
    refresh_pos = cuerpo.index("db.refresh(req)")
    assert lock_pos < refresh_pos < cuerpo.index("req.status")


# ---------------------------------------------------------------------------
# Índice parcial de solicitud VIVA: `approved` también cuenta (2026-09-15)
# ---------------------------------------------------------------------------
# `approved` significa "la liga de activación va en camino". Si otra solicitud
# del mismo control pudiera nacer viva en la misma convocatoria, la bandeja
# podría aprobarla también y la misma persona recibiría dos ligas (o una liga y
# un NIP). La regla vive en la BD, no solo en `create()`: dos altas simultáneas
# no pasan por el mismo `if`.
_PREDICADO_VIVO = "status IN ('unverified','verified','pending_review','approved')"
_PREDICADO_ANTERIOR = "status IN ('unverified','verified','pending_review')"


def _fila_viva(cohort, control, status):
    from itcj2.apps.titulatec.models import EnrollmentRequest

    return EnrollmentRequest(
        cohort_id=cohort.id, control_number=control,
        first_name="EGRESADA", last_name="FICTICIA", phone="6560000000",
        contact_email="personal@example.invalid", has_efirma=False,
        kind="known", status=status,
    )


def test_una_solicitud_approved_bloquea_otra_viva_del_mismo_control(db_session, make_cohort):
    from sqlalchemy.exc import IntegrityError

    cohort = make_cohort()
    db_session.add(_fila_viva(cohort, "99000090", "approved"))
    db_session.flush()

    for viva in ("pending_review", "approved"):
        with pytest.raises(IntegrityError):
            with db_session.begin_nested():
                db_session.add(_fila_viva(cohort, "99000090", viva))
                db_session.flush()

    # El historial no estorba: `rejected` y `converted` siguen fuera del índice.
    db_session.add(_fila_viva(cohort, "99000090", "rejected"))
    db_session.add(_fila_viva(cohort, "99000090", "converted"))
    db_session.flush()


def test_el_modelo_y_la_migracion_declaran_el_mismo_predicado():
    """El CI arma el esquema con `create_all` (sin Alembic) y producción con la
    migración: si el `__table_args__` y la migración divergen, las dos bases
    aplican reglas distintas y ningún test de comportamiento lo nota en ambas.
    """
    import re
    from pathlib import Path

    import itcj2
    from itcj2.apps.titulatec.models import EnrollmentRequest

    def _norm(s):
        return re.sub(r"\s+", "", s)

    indice = next(i for i in EnrollmentRequest.__table__.indexes
                  if i.name == "uq_titulatec_enrollment_req_open")
    assert indice.unique
    assert _norm(str(indice.dialect_options["postgresql"]["where"])) == _norm(_PREDICADO_VIVO)

    migracion = (Path(itcj2.__file__).resolve().parent.parent / "migrations" / "versions"
                 / "tt20260915a_titulatec_enrollment_open_approved.py")
    src = migracion.read_text(encoding="utf-8")
    assert 'revision = "tt20260915a"' in src
    assert 'down_revision = "tt20260908a"' in src
    assert _norm(_PREDICADO_VIVO) in _norm(src), "el upgrade debe crear el predicado nuevo"
    assert _norm(_PREDICADO_ANTERIOR) in _norm(src), "el downgrade debe restaurar el anterior"
