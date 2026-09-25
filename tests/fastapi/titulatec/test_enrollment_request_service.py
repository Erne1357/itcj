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

    assert not hasattr(mod, "VERIFY_TTL_HOURS"), (
        "la vida de la liga sale de TITULATEC_ENROLLMENT_LINK_TTL_DAYS vía "
        "`_link_ttl_hours()`; una constante paralela divergiría en silencio")
    assert mod.EnrollmentRequestService._link_ttl_hours() == 504, (
        "por omisión la liga de activación vive 21 días")
    assert mod.MAX_VERIFY_SENDS == 3
    assert mod.MIN_SECONDS_BETWEEN_SENDS == 300
    assert mod.MAX_PUBLIC_BODY_BYTES == 256 * 1024
    assert mod.STATUSES == (
        "unverified", "verified", "pending_review", "approved", "rejected", "converted",
        "awaiting_access")
    assert "awaiting_access" in mod._REJECTABLE, "SE cancela una que espera a Cómputo"
    assert "awaiting_access" not in mod._REVIEWABLE, "SE ya la aprobó"
    assert mod._STATUS_GROUP["awaiting_access"] == "access"
    assert mod.CONTROL_NUMBER_RE is re_original, (
        "CONTROL_NUMBER_RE debe ser el MISMO objeto que import_service.py: dos "
        "regex que divergen validarian numeros de control distinto segun la "
        "ruta que se tome."
    )


def test_la_vida_de_la_liga_sigue_a_link_ttl_hours_en_bd_y_en_redis(monkeypatch):
    """`_link_ttl_hours()` es la ÚNICA fuente: el vencimiento en BD y el TTL del
    claro en Redis la leen en cada llamada, no una copia tomada al importar."""
    import uuid

    from itcj2.apps.titulatec.models import EnrollmentRequest
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService, _TOKEN_CACHE_PREFIX, _redis, _sha256,
        _token_cache_delete, _token_cache_put,
    )

    monkeypatch.setattr(EnrollmentRequestService, "_link_ttl_hours",
                        staticmethod(lambda: 48))

    req = EnrollmentRequest(contact_email="alguien@example.invalid")
    EnrollmentRequestService._issue_activation(req)
    vence = datetime.now() + timedelta(hours=48)
    assert abs((req.verify_expires_at - vence).total_seconds()) < 120

    raw = f"token-de-prueba-{uuid.uuid4().hex}"
    _token_cache_put(raw)
    try:
        ttl = _redis().ttl(_TOKEN_CACHE_PREFIX + _sha256(raw))
        assert 48 * 3600 - 120 < ttl <= 48 * 3600
    finally:
        _token_cache_delete(_sha256(raw))


def test_link_ttl_days_es_el_accesor_publico_y_sigue_a_link_ttl_hours(monkeypatch):
    """Las páginas pintan «N días»: lo leen de `link_ttl_days()`, no del
    privado `_link_ttl_hours()`. Deriva de él, así que parchear la fuente única
    sigue alcanzando a todos."""
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    monkeypatch.setattr(EnrollmentRequestService, "_link_ttl_hours",
                        staticmethod(lambda: 24))
    assert EnrollmentRequestService.link_ttl_days() == 1
    monkeypatch.setattr(EnrollmentRequestService, "_link_ttl_hours",
                        staticmethod(lambda: 21 * 24))
    assert EnrollmentRequestService.link_ttl_days() == 21


def test_cohort_gate_es_el_unico_corte_de_convocatoria_de_la_bandeja(db_session, make_cohort):
    """approve / resend_link / grant_access repetían el mismo par de ifs."""
    import inspect as _inspect
    from types import SimpleNamespace as NS

    from itcj2.apps.titulatec.services import enrollment_request_service as mod

    abierta, cerrada = make_cohort(status="open"), make_cohort(status="closed")
    assert mod._cohort_gate(db_session, NS(cohort_id=abierta.id)) == (abierta, None)
    assert mod._cohort_gate(db_session, NS(cohort_id=cerrada.id)) == (
        None, "Esa convocatoria está cerrada.")
    assert mod._cohort_gate(db_session, NS(cohort_id=987654321)) == (
        None, "La convocatoria ya no existe.")
    for nombre in ("approve", "resend_link", "grant_access"):
        cuerpo = _inspect.getsource(getattr(mod.EnrollmentRequestService, nombre))
        assert "_cohort_gate(db, req)" in cuerpo, nombre
        assert "accepts_enrollment_followup" not in cuerpo, nombre


def test_ni_las_paginas_ni_el_correo_llaman_al_privado_link_ttl_hours():
    from pathlib import Path

    from itcj2.apps.titulatec.pages import access_admin, requests_admin
    from itcj2.apps.titulatec.services import email_helper

    for mod in (access_admin, requests_admin, email_helper):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert "_link_ttl_hours(" not in src, mod.__name__
        assert "link_ttl_days()" in src, mod.__name__


class TestSettingsDeLaInscripcion:
    """Valor inválido truena al construir `Settings` (mismo criterio que
    `TITULATEC_HANDOFF_PHASE`): mejor no arrancar que operar con una liga de
    0 días o con un modo de revisión que nadie implementa."""

    def test_los_defaults_son_21_dias_y_el_modo_oficial(self, monkeypatch):
        """`Settings()` a secas lee `.env` y el entorno del proceso (C7/I-1 de
        la revision final): sin aislarla, esta prueba mide lo que haya en el
        contenedor, no el DEFAULT declarado. `_env_file=None` + `delenv` de
        ambas variables fuerza el default real de `Field(...)`."""
        from itcj2.config import Settings

        monkeypatch.delenv("TITULATEC_ENROLLMENT_LINK_TTL_DAYS", raising=False)
        monkeypatch.delenv("TITULATEC_ENROLLMENT_REVIEWER", raising=False)
        s = Settings(_env_file=None)
        assert s.TITULATEC_ENROLLMENT_LINK_TTL_DAYS == 21
        assert s.TITULATEC_ENROLLMENT_REVIEWER == "school_services"

    def test_la_vida_de_la_liga_va_de_1_a_90_dias(self):
        from pydantic import ValidationError
        from itcj2.config import Settings

        for invalido in (0, -1, 91):
            with pytest.raises(ValidationError):
                Settings(TITULATEC_ENROLLMENT_LINK_TTL_DAYS=invalido)
        for valido in (1, 21, 90):
            assert (Settings(TITULATEC_ENROLLMENT_LINK_TTL_DAYS=valido)
                    .TITULATEC_ENROLLMENT_LINK_TTL_DAYS == valido)

    def test_el_revisor_solo_admite_los_dos_modos(self):
        from pydantic import ValidationError
        from itcj2.config import Settings

        with pytest.raises(ValidationError):
            Settings(TITULATEC_ENROLLMENT_REVIEWER="x")
        for valido in ("school_services", "computer_center"):
            assert (Settings(TITULATEC_ENROLLMENT_REVIEWER=valido)
                    .TITULATEC_ENROLLMENT_REVIEWER == valido)


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
        _TOKEN_CACHE_PREFIX, _redis, _sha256, _token_cache_delete,
        _token_cache_get, _token_cache_put,
    )

    raw = f"token-de-prueba-{uuid.uuid4().hex}"
    digest = _sha256(raw)

    assert _token_cache_get(digest) is None, "no deberia haber nada cacheado aun"
    _token_cache_put(raw)
    assert _token_cache_get(digest) == raw
    ttl = _redis().ttl(_TOKEN_CACHE_PREFIX + digest)
    assert 504 * 3600 - 120 < ttl <= 504 * 3600, "el claro vive lo mismo que la liga: 21 días"

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
    # El rechazo se commitea PRIMERO; el correo sale despues; y solo entonces
    # se sella `rejection_sent_at`, en un tercer commit propio (mismo patron
    # que `verify_sent_at`/`_mail_activation`).
    assert orden == ["commit", "correo", "commit"], (
        "el aviso salió antes de commitear el rechazo, o no se selló después")
    assert req.rejection_sent_at is not None
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
# Índice parcial de solicitud VIVA: `approved` y `awaiting_access` también
# cuentan (2026-09-15 / 2026-09-24)
# ---------------------------------------------------------------------------
# `approved` significa "la liga de activación va en camino". `awaiting_access`
# significa "Servicios Escolares ya aprobó y Centro de Cómputo todavía no da
# NIP/usuario". Si otra solicitud del mismo control pudiera nacer viva en la
# misma convocatoria, la bandeja podría aprobarla también y la misma persona
# recibiría dos ligas (o un NIP repetido). La regla vive en la BD, no solo en
# `create()`: dos altas simultáneas no pasan por el mismo `if`.
_PREDICADO_VIVO = ("status IN ('unverified','verified','pending_review','approved',"
                    "'awaiting_access')")
_PREDICADO_ANTERIOR = "status IN ('unverified','verified','pending_review','approved')"


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

    for viva in ("pending_review", "approved", "awaiting_access"):
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
                 / "tt20260924a_titulatec_enrollment_access.py")
    src = migracion.read_text(encoding="utf-8")
    assert 'revision = "tt20260924a"' in src
    assert 'down_revision = "hd20260922a"' in src
    assert _norm(_PREDICADO_VIVO) in _norm(src), "el upgrade debe crear el predicado nuevo"
    assert _norm(_PREDICADO_ANTERIOR) in _norm(src), "el downgrade debe restaurar el anterior"


def test_el_downgrade_devuelve_las_awaiting_access_a_revision_antes_del_indice_viejo():
    """El predicado viejo no conoce `awaiting_access`: sin el UPDATE esas filas
    quedan atoradas en un estado que ningún código de antes lee, y fuera del
    índice abren la puerta a una segunda solicitud viva del mismo par. El
    UPDATE no puede violar el índice viejo: el nuevo ya impedía que una
    `awaiting_access` conviviera con otra viva del mismo (convocatoria, control).
    """
    import importlib.util
    import re
    from pathlib import Path

    import itcj2

    ruta = (Path(itcj2.__file__).resolve().parent.parent / "migrations" / "versions"
            / "tt20260924a_titulatec_enrollment_access.py")
    spec = importlib.util.spec_from_file_location("_tt20260924a", ruta)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)

    pasos = []

    class _Op:
        def execute(self, sql):
            pasos.append(("execute", re.sub(r"\s+", " ", str(sql)).strip()))

        def __getattr__(self, nombre):
            return lambda *a, **k: pasos.append((nombre, a))

    mig.op = _Op()
    mig.downgrade()

    sqls = [sql for tipo, sql in pasos if tipo == "execute"]
    update = next(i for i, sql in enumerate(sqls) if sql.startswith("UPDATE"))
    crea_viejo = next(i for i, sql in enumerate(sqls)
                      if sql.startswith("CREATE UNIQUE INDEX")
                      and "'awaiting_access'" not in sql)
    assert update < crea_viejo, sqls
    assert sqls[update] == ("UPDATE titulatec_enrollment_requests SET status = "
                            "'pending_review' WHERE status = 'awaiting_access'")
    assert "awaiting_access" in (mig.__doc__ or "").split("downgrade", 1)[-1], (
        "el docstring de la migración debe decir qué hace el downgrade con esas filas")


# ---------------------------------------------------------------------------
# reject(): sella `rejection_sent_at` SOLO si el correo salió (2026-09-17)
# ---------------------------------------------------------------------------
def test_reject_sella_rejection_sent_at_si_el_correo_salio(
    db_session, make_cohort, make_user, correo_falso,
):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    actor = make_user()
    cohort = make_cohort()
    req, _ = _fila(db_session, cohort, control="99000030")

    ok = EnrollmentRequestService.reject(db_session, req.id, note="Motivo",
                                         actor_id=actor.id)

    assert ok is True
    assert req.status == "rejected"
    assert req.rejection_sent_at is not None


def test_reject_no_sella_rejection_sent_at_si_el_correo_no_salio(
    db_session, make_cohort, make_user, monkeypatch,
):
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    monkeypatch.setattr(TitulaTecEmailHelper, "send_enrollment_rejected",
                        staticmethod(lambda db, req: False))
    actor = make_user()
    cohort = make_cohort()
    req, _ = _fila(db_session, cohort, control="99000031")

    ok = EnrollmentRequestService.reject(db_session, req.id, note="Motivo",
                                         actor_id=actor.id)

    assert ok is True, "el rechazo en sí no depende de que el correo salga"
    assert req.status == "rejected"
    assert req.rejection_sent_at is None


# ---------------------------------------------------------------------------
# entry_year(): año de ingreso por control, con pivote de siglo inyectable
# (2026-09-17)
# ---------------------------------------------------------------------------
def test_entry_year_con_pivote_de_siglo_dinamico():
    from datetime import date

    from itcj2.apps.titulatec.services.enrollment_request_service import entry_year

    hoy = date(2026, 9, 17)     # pivote = 26

    assert entry_year("26110123", today=hoy) == "2026"    # yy == pivote  -> 2000+yy
    assert entry_year("21110123", today=hoy) == "2021"    # yy < pivote   -> 2000+yy
    assert entry_year("90110123", today=hoy) == "1990"    # yy > pivote   -> 1900+yy
    assert entry_year("27110123", today=hoy) == "1927"    # yy == pivote+1 -> 1900+yy


def test_entry_year_lee_los_2_digitos_tras_la_letra_opcional():
    from datetime import date

    from itcj2.apps.titulatec.services.enrollment_request_service import entry_year

    hoy = date(2026, 9, 17)

    assert entry_year("L21105023", today=hoy) == "2021"
    assert entry_year("21105023", today=hoy) == "2021"


def test_entry_year_sin_ano_para_un_control_que_no_casa():
    from itcj2.apps.titulatec.services.enrollment_request_service import entry_year

    assert entry_year("") == "Sin año"
    assert entry_year(None) == "Sin año"
    assert entry_year("abcdefgh") == "Sin año"     # 2 letras seguidas: no hay 2 dígitos tras UNA


def test_entry_year_usa_hoy_real_si_no_se_inyecta_today():
    from datetime import date

    from itcj2.apps.titulatec.services.enrollment_request_service import entry_year

    pivote = date.today().year % 100
    assert entry_year(f"{pivote:02d}000001") == str(2000 + pivote)


# ---------------------------------------------------------------------------
# stats(): KPIs y "por año de ingreso" (2026-09-17)
# ---------------------------------------------------------------------------
def test_stats_agrupa_solicitudes_por_estado_sin_pestana_ni_limite(db_session, make_cohort):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    cohort = make_cohort()
    for i, status in enumerate(
        ("pending_review", "unverified", "verified", "approved", "converted", "rejected",
         "awaiting_access"),
        start=1,
    ):
        _fila(db_session, cohort, control=f"9970{i:04d}", status=status)

    # `cohort_id` acota a la convocatoria RECIÉN CREADA: sin esto, `scope="ALL"`
    # también cuenta filas reales preexistentes en la BD de dev (de otras
    # convocatorias), que no son parte de este test.
    stats = EnrollmentRequestService.stats(db_session, scope="ALL", cohort_id=cohort.id)

    assert stats["counts"] == {
        "total": 7, "review": 3, "access": 1, "sent": 1, "converted": 1, "rejected": 1,
    }
    for anio in stats["by_year"]:
        assert set(anio) == {"year", "slug", "total", "review", "access", "sent",
                             "converted", "rejected"}
    assert sum(a["access"] for a in stats["by_year"]) == 1


def test_stats_respeta_el_alcance_por_carrera(db_session, make_cohort, make_program):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    cohort = make_cohort()
    prog_a = make_program("Carrera A de stats")
    prog_b = make_program("Carrera B de stats")
    _fila(db_session, cohort, control="99710001", program_id=prog_a.id)
    _fila(db_session, cohort, control="99710002", program_id=prog_b.id)

    stats = EnrollmentRequestService.stats(db_session, scope={prog_a.id})

    assert stats["counts"]["total"] == 1


def test_stats_con_alcance_vacio_devuelve_todo_en_cero_sin_reventar(db_session, make_cohort):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    cohort = make_cohort()
    _fila(db_session, cohort, control="99710010")

    stats = EnrollmentRequestService.stats(db_session, scope=set())

    assert stats == {
        "counts": {"total": 0, "review": 0, "access": 0, "sent": 0, "converted": 0,
                   "rejected": 0},
        "by_year": [], "year_max": 0,
    }


def test_stats_filtra_por_convocatoria(db_session, make_cohort):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    c1 = make_cohort()
    c2 = make_cohort()
    _fila(db_session, c1, control="99710020")
    _fila(db_session, c2, control="99710021")

    stats = EnrollmentRequestService.stats(db_session, scope="ALL", cohort_id=c1.id)

    assert stats["counts"]["total"] == 1


def test_stats_por_ano_cuenta_personas_unicas_por_su_solicitud_mas_reciente(
    db_session, make_cohort,
):
    """DOS solicitudes del MISMO control (una `rejected` vieja, una
    `pending_review` nueva): "por año" cuenta UNA persona, con el estado de la
    MÁS RECIENTE — nunca las dos solicitudes por separado."""
    from datetime import date

    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    cohort = make_cohort()
    control = "21110099"
    _fila(db_session, cohort, control=control, status="rejected")
    _fila(db_session, cohort, control=control, status="pending_review")
    _fila(db_session, cohort, control="21110100", status="converted")   # otra persona, mismo año

    # `cohort_id`: sin acotar, la BD de dev puede traer otro control real que
    # también empiece con "21" y contamine el bucket 2021 de este test.
    stats = EnrollmentRequestService.stats(db_session, scope="ALL", cohort_id=cohort.id,
                                           today=date(2026, 9, 17))

    anio = next(y for y in stats["by_year"] if y["year"] == "2021")
    assert anio["total"] == 2
    assert anio["review"] == 1         # la MAS RECIENTE de `control` es pending_review
    assert anio["converted"] == 1
    assert anio["rejected"] == 0       # la rejected vieja de esa MISMA persona ya no cuenta aparte


def test_stats_ordena_anios_descendente_con_sin_ano_al_final(db_session, make_cohort):
    from datetime import date

    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    cohort = make_cohort()
    _fila(db_session, cohort, control="90000001")      # 1990
    _fila(db_session, cohort, control="21000002")       # 2021
    _fila(db_session, cohort, control="abcdefgh")       # no casa -> Sin año

    stats = EnrollmentRequestService.stats(db_session, scope="ALL", cohort_id=cohort.id,
                                           today=date(2026, 9, 17))

    assert [y["year"] for y in stats["by_year"]] == ["2021", "1990", "Sin año"]
    assert stats["year_max"] == 1
    sin_anio = next(y for y in stats["by_year"] if y["year"] == "Sin año")
    assert sin_anio["slug"] == "sin-anio"
    veintiuno = next(y for y in stats["by_year"] if y["year"] == "2021")
    assert veintiuno["slug"] == "2021"


def test_stats_resume_personas_generaciones_rango_y_pico(db_session, make_cohort):
    """El `<summary>` del bloque plegable se lee con el bloque CERRADO, así que
    tiene que bastar solo: personas únicas, generaciones, rango y año pico.

    El pico desempata por el año MÁS RECIENTE (2021 y 2018 empatan con 2) y
    «Sin año» cuenta como generación pero no entra al rango ni compite."""
    from datetime import date

    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    cohort = make_cohort()
    _fila(db_session, cohort, control="18000001")
    _fila(db_session, cohort, control="18000002")
    _fila(db_session, cohort, control="21000001", status="rejected")
    _fila(db_session, cohort, control="21000001")             # misma persona: cuenta 1
    _fila(db_session, cohort, control="21000002")
    _fila(db_session, cohort, control="03000001")             # 2003
    _fila(db_session, cohort, control="abcdefgh")             # Sin año

    resumen = EnrollmentRequestService.stats(
        db_session, scope="ALL", cohort_id=cohort.id, today=date(2026, 9, 17))["summary"]

    assert resumen["people"] == 6
    assert resumen["generations"] == 4                        # 2021, 2018, 2003, Sin año
    assert resumen["span"] == "2003–2021"
    assert resumen["peak"] == {"year": "2021", "total": 2}


def test_stats_resumen_sin_solicitudes_no_revienta(db_session, make_cohort):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    cohort = make_cohort()
    resumen = EnrollmentRequestService.stats(
        db_session, scope="ALL", cohort_id=cohort.id)["summary"]

    assert resumen == {"people": 0, "generations": 0, "span": "", "peak": None}
