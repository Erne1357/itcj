"""Aprobar sin cuenta con el NIP del SII precargado (spec 2026-10-13 N §5.2, §5.4,
§5.5, §6 y §7 2-6 y 8).

En producción el modo es `sii` con el SII apagado (D11): aprobar sin cuenta ES
pasarla a Accesos. Con un NIP precargado (`NipStashService`, cifrado) ese
camino FORZADO crea la cuenta con él, como la rama «sin cuenta» de
`grant_access`, y manda el MISMO correo de Accesos (con el NIP). El «pasar a
Accesos» EXPLÍCITO (el argumento `to_access`) sigue yendo a Accesos y el NIP se
queda guardado. El modo alterno nunca lo usa. Crear la cuenta por CUALQUIER
camino (`_create_account`) borra el NIP precargado en la misma transacción.

El NIP nunca sale a la bitácora, a un `ProcessEvent` ni a un log: se busca un
NIP centinela en todo lo que escribe el camino nuevo.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime

import pytest
from cryptography.fernet import Fernet

from tests.fastapi.titulatec.conftest import audit_query

pytestmark = pytest.mark.usefixtures("audit_mark")

CENTINELA = "7391"
# Solo el NIP AISLADO: un id o un número de control que lo contenga no cuenta.
_CENTINELA_RE = re.compile(rf"(?<!\d){CENTINELA}(?!\d)")
NIP_TECLEADO = "5555"
MSG_NO_PROCESS = "No se pudo crear el proceso; revisa los datos de la solicitud."


# ---------------------------------------------------------------------------
# Fixtures locales (patrón de la suite: no se importan de otro archivo)
# ---------------------------------------------------------------------------
@pytest.fixture()
def d11(modo_sii, monkeypatch):
    """El caso de producción: modo `sii` con el SII apagado (backend
    `disabled`, D11). Mismo parche que `test_enrollment_inbox.py`."""
    from itcj2.apps.titulatec.services.sii.client import SiiConfig

    monkeypatch.setattr(SiiConfig, "backend", staticmethod(lambda: "disabled"))


@pytest.fixture()
def correo_falso(monkeypatch):
    """El correo REAL del helper con Graph falso: `(asunto, destinatarios, html)`."""
    from itcj2.apps.titulatec.services.student_mail import MailSettings

    monkeypatch.setattr(MailSettings, "enabled", staticmethod(lambda: False))
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


def _svc():
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    return EnrollmentRequestService


def _stash():
    from itcj2.apps.titulatec.services.nip_stash_service import NipStashService
    return NipStashService


def _make_req(db_session, cohort, *, control, status="pending_review", **kw):
    from itcj2.apps.titulatec.models import EnrollmentRequest

    row = EnrollmentRequest(
        cohort_id=cohort.id, control_number=control,
        first_name="EGRESADA", last_name="PRECARGADA", middle_name=None,
        program_id=None, program_text="Ingenieria Ficticia",
        phone="6561234567", contact_email="precargada@example.invalid",
        has_efirma=True, kind="unknown", status=status, verify_send_count=0,
    )
    for k, v in kw.items():
        setattr(row, k, v)
    db_session.add(row)
    db_session.flush()
    return row


def _cuenta(db_session, control):
    """Cuenta que YA existe en `core_users` (NIP «9999»)."""
    from itcj2.core.models.user import User
    from itcj2.core.utils.security import hash_nip

    user = User(username=control, control_number=control, first_name="YA",
                last_name="EXISTIA", password_hash=hash_nip("9999"), is_active=True,
                must_change_password=False)
    db_session.add(user)
    db_session.flush()
    return user


def _usuario(db_session, control):
    from itcj2.core.models.user import User
    return db_session.query(User).filter_by(control_number=control).first()


def _guardar(db_session, control, nip=CENTINELA):
    _stash().put(db_session, control, nip, actor_id=None)


def _hay_nip(db_session, control) -> bool:
    from itcj2.apps.titulatec.models import NipStash
    return db_session.get(NipStash, control) is not None


def _textos(value):
    """Toda cadena dentro de `value` (llaves incluidas). Los enteros no: un NIP
    que se filtrara viaja como texto."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from _textos(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _textos(v)


def _filtra(value) -> bool:
    return any(_CENTINELA_RE.search(s) for s in _textos(value))


# ---------------------------------------------------------------------------
# §7.2 · D11 + NIP precargado: cuenta, correo de Accesos, fila borrada
# ---------------------------------------------------------------------------
def test_d11_con_nip_precargado_crea_la_cuenta_y_manda_el_correo_de_accesos(
    db_session, make_cohort, make_user, listo, d11, llave, espia_correo,
):
    from itcj2.core.utils.security import verify_nip

    se = make_user(first_name="SERVICIOS", last_name="ESCOLARES")
    req = _make_req(db_session, make_cohort(status="open"), control="99570001")
    _guardar(db_session, "99570001")

    res = _svc().approve_detailed(db_session, req.id, nip="", program_id=None,
                                  actor_id=se.id)

    assert res.ok is True and res.detail, res          # el folio
    assert res.nip_failure is None
    db_session.refresh(req)
    assert req.status == "converted"
    assert req.nip_source == "preloaded"
    assert req.reviewed_by_id == se.id and req.reviewed_at is not None
    assert req.access_granted_by_id == se.id, "quien aprueba es quien da el acceso"
    assert req.access_granted_at is not None
    assert req.access_sent_at is not None, "el correo salió: se sella"
    user = _usuario(db_session, "99570001")
    assert verify_nip(CENTINELA, user.password_hash)
    assert user.must_change_password is True
    assert espia_correo == [("send_enrollment_approved",
                             {"nip": CENTINELA, "reassigned": False,
                              "nip_source": "preloaded"})]
    assert not _hay_nip(db_session, "99570001"), "el NIP se borra al usarlo"


def test_el_correo_es_el_de_accesos_con_el_nip_en_claro(
    db_session, make_cohort, make_user, listo, d11, llave, correo_falso,
):
    """N1: el MISMO correo que manda Accesos (`_mail_access`), con el NIP; no el
    del SII («tu NIP del SII», sin credencial)."""
    se = make_user()
    req = _make_req(db_session, make_cohort(status="open"), control="99570002")
    _guardar(db_session, "99570002")

    assert _svc().approve_detailed(db_session, req.id, nip="", program_id=None,
                                   actor_id=se.id).ok

    (asunto, destinatarios, html), = correo_falso
    assert asunto == "[TitulaTec ITCJ] Tu acceso a la plataforma"
    assert destinatarios == ["precargada@example.invalid"]
    assert CENTINELA in html
    assert "NIP del SII" not in html


def test_si_el_correo_no_sale_la_cuenta_queda_y_accesos_lo_ve_como_no_enviado(
    db_session, make_cohort, make_user, listo, d11, llave, monkeypatch,
):
    """§6: igual que Accesos — `access_sent_at` NULL, «correo no enviado» y CC
    puede reasignar el NIP (`preloaded` se porta como `center`)."""
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    monkeypatch.setattr(TitulaTecEmailHelper, "send_enrollment_approved",
                        staticmethod(lambda *a, **k: False))
    se = make_user()
    req = _make_req(db_session, make_cohort(status="open"), control="99570003")
    _guardar(db_session, "99570003")

    res = _svc().approve_detailed(db_session, req.id, nip="", program_id=None,
                                  actor_id=se.id)

    assert res.ok is True
    db_session.refresh(req)
    assert req.status == "converted" and req.access_sent_at is None
    assert _svc().access_mail_unsent(req) is True
    assert _svc().can_reassign_nip(req, _usuario(db_session, "99570003")) is True
    assert not _hay_nip(db_session, "99570003")


def test_con_acceso_de_accesos_lista_las_cuentas_precargadas(
    db_session, make_cohort, make_user, listo, d11, llave, espia_correo,
):
    """«Con acceso» solo excluye `nip_source = 'sii'`: las del lote entran, como
    las de `center` (spec N §5.2)."""
    from itcj2.apps.titulatec.models import EnrollmentRequest as ER
    from itcj2.apps.titulatec.pages.access_admin import _tab_filter

    se = make_user()
    req = _make_req(db_session, make_cohort(status="open"), control="99570004")
    _guardar(db_session, "99570004")
    assert _svc().approve_detailed(db_session, req.id, nip="", program_id=None,
                                   actor_id=se.id).ok

    assert (db_session.query(ER.id)
            .filter(_tab_filter("granted"), ER.id == req.id).count()) == 1


# ---------------------------------------------------------------------------
# §7.3 · «Pasar a Accesos» explícito: Accesos, el NIP sigue
# ---------------------------------------------------------------------------
def test_pasar_a_accesos_explicito_va_a_accesos_y_conserva_el_nip(
    db_session, make_cohort, make_user, listo, d11, llave, espia_correo,
):
    se = make_user()
    req = _make_req(db_session, make_cohort(status="open"), control="99570005")
    _guardar(db_session, "99570005")

    res = _svc().approve_detailed(db_session, req.id, nip="", program_id=None,
                                  actor_id=se.id, to_access=True)

    assert res == (True, "", None)
    db_session.refresh(req)
    assert req.status == "awaiting_access" and req.nip_source is None
    assert _usuario(db_session, "99570005") is None
    assert espia_correo == []
    assert _hay_nip(db_session, "99570005"), "el NIP se queda guardado"


# ---------------------------------------------------------------------------
# §7.4 · Sin NIP precargado: Accesos, como hoy (regresión de D11)
# ---------------------------------------------------------------------------
def test_d11_sin_nip_precargado_pasa_a_accesos_como_hoy(
    db_session, make_cohort, make_user, listo, d11, llave, espia_correo,
):
    se = make_user()
    req = _make_req(db_session, make_cohort(status="open"), control="99570006")

    res = _svc().approve_detailed(db_session, req.id, nip="", program_id=None,
                                  actor_id=se.id)

    assert res == (True, "", None)
    db_session.refresh(req)
    assert req.status == "awaiting_access" and req.reviewed_by_id == se.id
    assert req.nip_source is None and req.access_granted_at is None
    assert _usuario(db_session, "99570006") is None
    assert espia_correo == []


def test_sin_llave_el_nip_guardado_se_ignora_y_se_conserva(
    db_session, make_cohort, make_user, listo, d11, llave, espia_correo, monkeypatch,
):
    """Review Focus 3 (llave ausente): aprobar cae a Accesos como hoy."""
    from itcj2.config import get_settings

    se = make_user()
    req = _make_req(db_session, make_cohort(status="open"), control="99570007")
    _guardar(db_session, "99570007")
    monkeypatch.setattr(get_settings(), "TITULATEC_NIP_STASH_KEY", None)

    res = _svc().approve_detailed(db_session, req.id, nip="", program_id=None,
                                  actor_id=se.id)

    assert res == (True, "", None)
    assert req.status == "awaiting_access"
    assert _usuario(db_session, "99570007") is None and espia_correo == []
    assert _hay_nip(db_session, "99570007")


def test_llave_cambiada_cae_a_accesos_con_warning_sin_datos(
    db_session, make_cohort, make_user, listo, d11, llave, espia_correo, monkeypatch,
    caplog,
):
    """Review Focus 3 (llave cambiada después de cargar): Accesos, un WARNING
    sin el control ni el NIP, nada truena y el NIP no se borra."""
    from itcj2.config import get_settings

    se = make_user()
    req = _make_req(db_session, make_cohort(status="open"), control="99570008")
    _guardar(db_session, "99570008")
    monkeypatch.setattr(get_settings(), "TITULATEC_NIP_STASH_KEY",
                        Fernet.generate_key().decode())

    with caplog.at_level(logging.DEBUG):
        res = _svc().approve_detailed(db_session, req.id, nip="", program_id=None,
                                      actor_id=se.id)

    assert res == (True, "", None)
    assert req.status == "awaiting_access"
    assert _usuario(db_session, "99570008") is None and espia_correo == []
    assert _hay_nip(db_session, "99570008")
    avisos = [r for r in caplog.records if r.levelname == "WARNING"]
    assert avisos, "la llave cambiada deja un WARNING"
    assert "99570008" not in caplog.text
    assert not _CENTINELA_RE.search(caplog.text)


# ---------------------------------------------------------------------------
# Modos: oficial lo usa, alterno nunca
# ---------------------------------------------------------------------------
def test_modo_oficial_con_nip_precargado_crea_la_cuenta(
    db_session, make_cohort, make_user, listo, llave, espia_correo,
):
    """El autouse `_modo_oficial_por_defecto` deja `school_services`: aprobar
    sin cuenta también caía a Accesos, y también usa el NIP precargado."""
    from itcj2.core.utils.security import verify_nip

    assert _svc().reviewer_mode() == "school_services"
    se = make_user()
    req = _make_req(db_session, make_cohort(status="open"), control="99570009")
    _guardar(db_session, "99570009")

    res = _svc().approve_detailed(db_session, req.id, nip="", program_id=None,
                                  actor_id=se.id)

    assert res.ok is True and res.detail
    assert req.status == "converted" and req.nip_source == "preloaded"
    assert verify_nip(CENTINELA, _usuario(db_session, "99570009").password_hash)
    assert not _hay_nip(db_session, "99570009")


def test_modo_alterno_usa_el_nip_tecleado_y_borra_el_precargado(
    db_session, make_cohort, make_user, listo, llave, espia_correo, modo_alterno,
):
    """En el alterno quien aprueba teclea el NIP (spec N §3, fuera de alcance):
    el precargado no se usa, pero crear la cuenta lo borra (§5.4)."""
    from itcj2.core.utils.security import verify_nip

    cc = make_user()
    req = _make_req(db_session, make_cohort(status="open"), control="99570010")
    _guardar(db_session, "99570010")

    res = _svc().approve_detailed(db_session, req.id, nip=NIP_TECLEADO, program_id=None,
                                  actor_id=cc.id)

    assert res.ok is True
    assert req.status == "converted" and req.nip_source == "form"
    user = _usuario(db_session, "99570010")
    assert verify_nip(NIP_TECLEADO, user.password_hash)
    assert not verify_nip(CENTINELA, user.password_hash)
    assert not _hay_nip(db_session, "99570010")


# ---------------------------------------------------------------------------
# §7.5 · Con cuenta + NIP: liga; el NIP se descarta
# ---------------------------------------------------------------------------
def test_con_cuenta_sale_la_liga_y_el_nip_precargado_se_descarta(
    db_session, make_cohort, make_user, listo, d11, llave, espia_correo,
):
    from itcj2.core.utils.security import verify_nip

    se = make_user()
    cuenta = _cuenta(db_session, "99570011")
    req = _make_req(db_session, make_cohort(status="open"), control="99570011")
    _guardar(db_session, "99570011")

    res = _svc().approve_detailed(db_session, req.id, nip="", program_id=None,
                                  actor_id=se.id)

    assert res == (True, "", None)
    db_session.refresh(req)
    assert req.status == "approved" and req.verify_token_hash is not None
    assert req.nip_source is None
    assert verify_nip("9999", cuenta.password_hash), "la cuenta no se toca"
    assert [n for n, _ in espia_correo] == ["send_verify_enrollment"]
    assert not _hay_nip(db_session, "99570011")


# ---------------------------------------------------------------------------
# §7.6 · Rechazar conserva; reabrir + aprobar lo usa
# ---------------------------------------------------------------------------
def test_rechazar_conserva_el_nip_y_reabrir_y_aprobar_lo_usa(
    db_session, make_cohort, make_user, listo, d11, llave, espia_correo,
):
    from itcj2.core.utils.security import verify_nip

    se = make_user()
    req = _make_req(db_session, make_cohort(status="open"), control="99570012")
    _guardar(db_session, "99570012")

    assert _svc().reject(db_session, req.id, note="No aparece en el padrón.",
                         actor_id=se.id) is True
    assert req.status == "rejected"
    assert _hay_nip(db_session, "99570012"), "N3: rechazar no borra el NIP"

    assert _svc().reopen(db_session, req.id, note="Aclaró en ventanilla.",
                         actor_id=se.id) == (True, "")
    res = _svc().approve_detailed(db_session, req.id, nip="", program_id=None,
                                  actor_id=se.id)

    assert res.ok is True
    db_session.refresh(req)
    assert req.status == "converted" and req.nip_source == "preloaded"
    assert verify_nip(CENTINELA, _usuario(db_session, "99570012").password_hash)
    assert not _hay_nip(db_session, "99570012")


# ---------------------------------------------------------------------------
# §7.8 · `grant_access` con NIP tecleado borra el precargado
# ---------------------------------------------------------------------------
def test_dar_acceso_con_nip_tecleado_borra_el_precargado(
    db_session, make_cohort, make_user, listo, d11, llave, espia_correo,
):
    from itcj2.core.utils.security import verify_nip

    se = make_user(first_name="SERVICIOS", last_name="ESCOLARES")
    cc = make_user(first_name="CENTRO", last_name="COMPUTO")
    req = _make_req(db_session, make_cohort(status="open"), control="99570013",
                    status="awaiting_access", reviewed_by_id=se.id,
                    reviewed_at=datetime.now())
    _guardar(db_session, "99570013")

    ok, folio = _svc().grant_access(db_session, req.id, nip=NIP_TECLEADO, actor_id=cc.id)

    assert ok is True and folio
    assert req.status == "converted" and req.nip_source == "center"
    user = _usuario(db_session, "99570013")
    assert verify_nip(NIP_TECLEADO, user.password_hash)
    assert not _hay_nip(db_session, "99570013"), "no queda un NIP huérfano"
    assert espia_correo == [("send_enrollment_approved",
                             {"nip": NIP_TECLEADO, "reassigned": False,
                              "nip_source": "manual"})]


# ---------------------------------------------------------------------------
# §6 · Fallo al crear la cuenta: nada cambia y el NIP sigue
# ---------------------------------------------------------------------------
def test_si_no_se_crea_el_proceso_nada_cambia_y_el_nip_sigue(
    db_session, make_cohort, make_user, listo, d11, llave, espia_correo, monkeypatch,
):
    from itcj2.apps.titulatec.services import import_service

    monkeypatch.setattr(import_service.ImportService, "import_rows",
                        staticmethod(lambda *a, **k: {"processes_created": 0}))
    se = make_user()
    req = _make_req(db_session, make_cohort(status="open"), control="99570014")
    _guardar(db_session, "99570014")

    res = _svc().approve_detailed(db_session, req.id, nip="", program_id=None,
                                  actor_id=se.id)

    assert res == (False, MSG_NO_PROCESS, None)
    db_session.refresh(req)
    assert req.status == "pending_review" and req.reviewed_by_id is None
    assert req.nip_source is None and req.access_granted_at is None
    assert _usuario(db_session, "99570014") is None
    assert espia_correo == []
    assert _hay_nip(db_session, "99570014"), "el savepoint deshizo el borrado"


def test_si_crear_la_cuenta_truena_el_savepoint_deja_el_nip(
    db_session, make_cohort, make_user, listo, d11, llave, espia_correo, monkeypatch,
):
    """Una excepción dentro de `_create_account` sube (la ruta hace rollback),
    pero su savepoint ya deshizo todo, incluido el borrado del NIP."""
    from itcj2.apps.titulatec.services import import_service

    def _truena(*a, **k):
        raise RuntimeError("falla simulada")

    monkeypatch.setattr(import_service.ImportService, "import_rows",
                        staticmethod(_truena))
    se = make_user()
    req = _make_req(db_session, make_cohort(status="open"), control="99570015")
    _guardar(db_session, "99570015")

    with pytest.raises(RuntimeError):
        _svc().approve_detailed(db_session, req.id, nip="", program_id=None,
                                actor_id=se.id)

    assert req.status == "pending_review"
    assert _usuario(db_session, "99570015") is None
    assert espia_correo == []
    assert _hay_nip(db_session, "99570015")


# ---------------------------------------------------------------------------
# §5.5 · Bitácora y el NIP centinela
# ---------------------------------------------------------------------------
def test_el_camino_nuevo_audita_preloaded_y_el_nip_no_sale_a_ningun_lado(
    db_session, make_cohort, make_user, listo, d11, llave, espia_correo, caplog,
):
    from itcj2.apps.titulatec.models import ProcessEvent

    se = make_user()
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99570016")
    _guardar(db_session, "99570016")

    with caplog.at_level(logging.DEBUG):
        res = _svc().approve_detailed(db_session, req.id, nip="", program_id=None,
                                      actor_id=se.id)
    assert res.ok is True
    db_session.refresh(req)

    filas = audit_query(db_session).all()
    aprobadas = [f for f in filas if f.action == "enrollment.approved"
                 and f.entity_id == req.id]
    assert len(aprobadas) == 1
    assert aprobadas[0].payload == {"path": "preloaded", "cohort_id": cohort.id}
    assert aprobadas[0].actor_id == se.id
    assert aprobadas[0].after == {"status": "converted"}
    for f in filas:
        for valor in (f.before, f.after, f.payload, f.reason, f.subject_label):
            assert not _filtra(valor), (f.action, valor)
    # La red de la bitácora registra el borrado del NIP, sin el token cifrado:
    # la bitácora es inmutable y el NIP tiene que poder desaparecer de verdad.
    bajas = [f for f in filas if f.action == "data.delete"
             and f.entity_type == "titulatec_nip_stash"]
    assert len(bajas) == 1 and bajas[0].module == "enrollment"
    assert bajas[0].before["nip_cipher"] == "***"
    assert bajas[0].before["control_number"] == "99570016"

    eventos = (db_session.query(ProcessEvent)
               .filter_by(process_id=req.converted_process_id).all())
    assert eventos
    alta = [e for e in eventos if e.event_type == "enrollment_self_service"]
    assert alta and alta[0].payload.get("nip_source") == "preloaded"
    assert alta[0].payload.get("approved_by_id") == se.id
    assert alta[0].payload.get("granted_by_id") == se.id
    for e in eventos:
        assert not _filtra(e.payload), e.payload
        assert not _CENTINELA_RE.search(json.dumps(e.payload or {}))

    assert not _CENTINELA_RE.search(caplog.text)
    assert not _CENTINELA_RE.search(res.detail)


def test_la_bitacora_dice_que_la_cuenta_nacio_al_aprobar_no_en_accesos():
    """Única comparación de `nip_source` donde `preloaded` NO se porta como
    `center`: en el alta del expediente (`audit_admin._alta_label`) `center`
    es «Centro de Cómputo le dio acceso», y aquí CC no intervino — la cuenta
    nació al aprobar (quien aprueba = quien da el acceso)."""
    from itcj2.apps.titulatec.pages.audit_admin import _ALTA_APROBAR, _alta_label

    assert _alta_label({"activation": "nip_personal_email", "nip_source": "preloaded",
                        "approved_by_id": 7, "granted_by_id": 7}) == _ALTA_APROBAR


# ---------------------------------------------------------------------------
# Bandeja de Solicitudes: la fila con NIP precargado lo promete y no manda
# `to_access` (con D11 la fila sin cuenta manda `to_access=1`, que es el
# EXPLÍCITO: sin esto el NIP precargado nunca se usaría desde la bandeja)
# ---------------------------------------------------------------------------
URL = "/titulatec/admin/solicitudes"
LIST_PERMS = (
    "titulatec.enrollment_request.page.list",
    "titulatec.enrollment_request.api.approve",
    "titulatec.enrollment_request.api.reject",
    "titulatec.process.api.read.all",      # -> officer_programs() == "ALL"
)
TO_ACCESS_INPUT = '<input type="hidden" name="to_access" value="1">'
NOTA_PRECARGADO = "La cuenta nace con el NIP del SII que se cargó en lote; el correo lo lleva."


def _fila(html: str, req) -> str:
    """El `<tr>` de la solicitud en la bandeja."""
    marca = f'id="tt-req-{req.id}"'
    assert marca in html, f"no está la fila de la solicitud {req.id}"
    return html.split(marca, 1)[1].split("</tr>", 1)[0]


def _plano(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def _aviso(resp) -> tuple[str, str]:
    from urllib.parse import unquote
    return (unquote(resp.headers.get("X-Tt-Notice", "")),
            resp.headers.get("X-Tt-Notice-Kind", ""))


def test_d11_la_fila_con_nip_precargado_ofrece_dar_acceso_sin_to_access(
    client_as, db_session, make_head, make_cohort, d11, llave,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    con_nip = _make_req(db_session, cohort, control="99570020")
    _guardar(db_session, "99570020")
    sin_nip = _make_req(db_session, cohort, control="99570021")
    _cuenta(db_session, "99570022")
    con_cuenta = _make_req(db_session, cohort, control="99570022")
    _guardar(db_session, "99570022")

    html = client_as(head).get(f"{URL}/body?cohort_id={cohort.id}").text

    fila = _fila(html, con_nip)
    assert "Aprobar y dar acceso" in fila
    assert TO_ACCESS_INPUT not in fila and 'name="to_access"' not in fila
    assert NOTA_PRECARGADO in _plano(fila)
    assert CENTINELA not in html
    otra = _fila(html, sin_nip)
    assert "Aprobar y pasar a Accesos" in otra and TO_ACCESS_INPUT in otra, (
        "sin NIP precargado la fila no cambia")
    assert NOTA_PRECARGADO not in _plano(otra)
    liga = _fila(html, con_cuenta)
    assert "Aprobar y enviar liga" in liga and NOTA_PRECARGADO not in _plano(liga)


def test_sin_llave_la_fila_sigue_ofreciendo_pasar_a_accesos(
    client_as, db_session, make_head, make_cohort, d11, llave, monkeypatch,
):
    """Sin llave aprobar no puede usar el NIP: la fila no lo promete."""
    from itcj2.config import get_settings

    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99570023")
    _guardar(db_session, "99570023")
    monkeypatch.setattr(get_settings(), "TITULATEC_NIP_STASH_KEY", None)

    fila = _fila(client_as(head).get(f"{URL}/body?cohort_id={cohort.id}").text, req)

    assert "Aprobar y pasar a Accesos" in fila and TO_ACCESS_INPUT in fila
    assert NOTA_PRECARGADO not in _plano(fila)


def test_con_el_sii_conectado_la_fila_no_promete_el_nip_precargado(
    client_as, db_session, make_head, make_cohort, modo_sii, llave, monkeypatch,
):
    """SII conectado: manda el SII vivo (spec N §3), el precargado no se usa."""
    from itcj2.apps.titulatec.services.sii.client import SiiConfig

    monkeypatch.setattr(SiiConfig, "backend", staticmethod(lambda: "fake"))
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99570024")
    _guardar(db_session, "99570024")

    fila = _fila(client_as(head).get(f"{URL}/body?cohort_id={cohort.id}").text, req)

    assert NOTA_PRECARGADO not in _plano(fila)
    assert TO_ACCESS_INPUT in fila, "sin consulta, la fila ofrece pasar a Accesos"


def test_modo_oficial_la_fila_con_nip_precargado_ofrece_dar_acceso(
    client_as, db_session, make_head, make_cohort, llave,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    con_nip = _make_req(db_session, cohort, control="99570025")
    _guardar(db_session, "99570025")
    sin_nip = _make_req(db_session, cohort, control="99570026")

    html = client_as(head).get(f"{URL}/body?cohort_id={cohort.id}").text

    fila = _fila(html, con_nip)
    assert "Aprobar y dar acceso" in fila and 'name="to_access"' not in fila
    assert NOTA_PRECARGADO in _plano(fila)
    otra = _fila(html, sin_nip)
    assert "Aprobar y dar acceso" not in otra and NOTA_PRECARGADO not in _plano(otra)


@pytest.mark.parametrize("sale", [True, False], ids=["correo_sale", "correo_no_sale"])
def test_d11_ruta_aprobar_con_nip_precargado_avisa_el_folio_y_el_correo(
    client_as, db_session, make_head, make_cohort, listo, d11, llave, monkeypatch, caplog,
    sale,
):
    """Lo que manda la fila (sin `to_access`): cuenta creada, y el aviso dice el
    folio y si el correo salió (patrón de F9). Nunca el NIP."""
    from itcj2.apps.titulatec.models import TitulationProcess
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    monkeypatch.setattr(TitulaTecEmailHelper, "send_enrollment_approved",
                        staticmethod(lambda *a, **k: sale))
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99570027")
    _guardar(db_session, "99570027")

    with caplog.at_level(logging.DEBUG):
        resp = client_as(head).post(
            f"{URL}/{req.id}/aprobar",
            data={"program_id": "", "status": "pending_review", "cohort_id": str(cohort.id)})

    assert resp.status_code == 200, resp.headers.get("X-Tt-Error")
    db_session.refresh(req)
    assert (req.status, req.nip_source) == ("converted", "preloaded")
    folio = db_session.get(TitulationProcess, req.converted_process_id).folio
    if sale:
        assert _aviso(resp) == (
            f"Cuenta creada (folio {folio}) con el NIP precargado; se le mandó por "
            "correo.", "success")
    else:
        assert _aviso(resp) == (
            f"Cuenta creada (folio {folio}) con el NIP precargado, pero el correo no "
            "salió: Centro de Cómputo le reasigna el NIP desde Accesos.", "warning")
    assert not _CENTINELA_RE.search(resp.text)
    assert not _CENTINELA_RE.search(" ".join(f"{k}: {v}" for k, v in resp.headers.items()))
    assert not _CENTINELA_RE.search(caplog.text)


# ---------------------------------------------------------------------------
# Repaso de la tarea 2: legibilidad, D10 y el predicado único
# ---------------------------------------------------------------------------
def test_readable_devuelve_solo_los_que_descifran_con_un_warning_agregado(
    db_session, llave, caplog, monkeypatch,
):
    """Con la llave cambiada ninguno descifra: UN WARNING (no uno por fila), sin
    controles ni NIP."""
    from itcj2.config import get_settings

    for c in ("99570040", "99570041", "99570042"):
        _guardar(db_session, c)
    assert _stash().readable(db_session, ["99570040", "99570041", "99570099"]) == {
        "99570040", "99570041"}

    monkeypatch.setattr(get_settings(), "TITULATEC_NIP_STASH_KEY",
                        Fernet.generate_key().decode())
    with caplog.at_level(logging.DEBUG):
        ok = _stash().readable(db_session, ["99570040", "99570041", "99570042"])

    assert ok == set()
    avisos = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(avisos) == 1
    assert "9957004" not in caplog.text and not _CENTINELA_RE.search(caplog.text)


def test_readable_sin_llave_es_vacio_y_sin_warning(db_session, llave, caplog, monkeypatch):
    from itcj2.config import get_settings

    _guardar(db_session, "99570043")
    monkeypatch.setattr(get_settings(), "TITULATEC_NIP_STASH_KEY", None)
    with caplog.at_level(logging.DEBUG):
        assert _stash().readable(db_session, ["99570043"]) == set()
    assert not [r for r in caplog.records if r.levelname == "WARNING"]


def test_llave_cambiada_la_fila_no_promete_el_nip_y_ofrece_pasar_a_accesos(
    client_as, db_session, make_head, make_cohort, d11, llave, monkeypatch,
):
    """Repaso T2 Minor 1: un guardado que no se puede descifrar no se promete."""
    from itcj2.config import get_settings

    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99570044")
    _guardar(db_session, "99570044")
    monkeypatch.setattr(get_settings(), "TITULATEC_NIP_STASH_KEY",
                        Fernet.generate_key().decode())

    fila = _fila(client_as(head).get(f"{URL}/body?cohort_id={cohort.id}").text, req)

    assert "Aprobar y pasar a Accesos" in fila and TO_ACCESS_INPUT in fila
    assert NOTA_PRECARGADO not in _plano(fila)


def test_dar_acceso_con_cuenta_aparecida_d10_descarta_el_nip_precargado(
    db_session, make_cohort, make_user, listo, llave, correo_falso,
):
    """Repaso T2 Minor 2: la rama D10 de `grant_access` también borra el guardado."""
    se, cc = make_user(), make_user()
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99570045", status="awaiting_access",
                    reviewed_by_id=se.id)
    _cuenta(db_session, "99570045")
    _guardar(db_session, "99570045")

    ok, detalle = _svc().grant_access(db_session, req.id, nip="", actor_id=cc.id)

    assert (ok, detalle) == (True, "")
    assert req.status == "approved"
    assert not _hay_nip(db_session, "99570045")


@pytest.mark.parametrize("mode,forced,esperado", [
    ("school_services", False, True),
    ("school_services", True, True),
    ("sii", True, True),
    ("sii", False, False),
    ("computer_center", False, False),
    ("computer_center", True, False),
])
def test_preloaded_applies_tabla(mode, forced, esperado):
    assert _svc().preloaded_applies(mode, forced_access=forced) is esperado


def test_bandeja_y_servicio_usan_el_mismo_predicado():
    """Repaso T2 Minor 3: la condición de modo vive en un solo sitio."""
    import inspect

    from itcj2.apps.titulatec.pages import requests_admin

    assert "preloaded_applies" in inspect.getsource(requests_admin._preloaded_controls)
    assert "preloaded_applies" in inspect.getsource(_svc()._preloaded_nip)
