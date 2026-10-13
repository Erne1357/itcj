"""Carga por lote de NIPs del SII (spec 2026-10-13 N §5.3, §5.5, §6 y §7 9-10).

`NipStashService.load_rows` clasifica cada `(control, nip)` en un bucket fijo y
actúa: `awaiting_access` recibe el acceso (`grant_access(nip_source="preloaded")`),
el resto de las solicitudes vivas guarda el NIP cifrado para la aprobación. Los
buckets traen `(control, motivo)` y NUNCA el NIP. Además cubre los dos kwargs
nuevos de `grant_access` (`send_mail`, `nip_source`).
"""
from __future__ import annotations

import json
import re

import pytest

from tests.fastapi.titulatec.conftest import audit_query

pytestmark = pytest.mark.usefixtures("audit_mark")

CENTINELA = "7391"
_CENTINELA_RE = re.compile(rf"(?<!\d){CENTINELA}(?!\d)")
BUCKETS = ("granted", "stored", "stored_rejected", "has_account", "no_request",
           "invalid_nip", "duplicate", "failed")


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
        first_name="EGRESADA", last_name="DELLOTE", middle_name=None,
        program_id=None, program_text="Ingenieria Ficticia",
        phone="6561234567", contact_email="lote@example.invalid",
        has_efirma=True, kind="unknown", status=status, verify_send_count=0,
    )
    for k, v in kw.items():
        setattr(row, k, v)
    db_session.add(row)
    db_session.flush()
    return row


def _cuenta(db_session, control):
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


def _hay_nip(db_session, control) -> bool:
    from itcj2.apps.titulatec.models import NipStash
    return db_session.get(NipStash, control) is not None


def _carga(db_session, rows, actor, *, dry_run=False, send_mail=True):
    return _stash().load_rows(db_session, rows, actor_id=actor.id,
                              dry_run=dry_run, send_mail=send_mail)


def _controles(res, bucket):
    return [c for c, _ in res[bucket]]


# ---------------------------------------------------------------------------
# grant_access: send_mail y nip_source (rulings R1 + R9)
# ---------------------------------------------------------------------------
def test_grant_access_sin_correo_crea_la_cuenta_y_no_manda(
    db_session, make_cohort, make_user, listo, espia_correo,
):
    actor = make_user()
    req = _make_req(db_session, make_cohort(status="open"), control="99580001",
                    status="awaiting_access", reviewed_by_id=actor.id)

    ok, detalle = _svc().grant_access(db_session, req.id, nip="5555",
                                      actor_id=actor.id, send_mail=False)

    assert ok is True and detalle
    db_session.refresh(req)
    assert req.status == "converted"
    assert req.access_granted_by_id == actor.id
    assert req.access_sent_at is None
    assert _svc().access_mail_unsent(req) is True
    assert _usuario(db_session, "99580001") is not None
    assert espia_correo == [], "send_mail=False no manda nada"


def test_grant_access_por_omision_manda_y_es_center(
    db_session, make_cohort, make_user, listo, espia_correo,
):
    actor = make_user()
    req = _make_req(db_session, make_cohort(status="open"), control="99580002",
                    status="awaiting_access", reviewed_by_id=actor.id)

    ok, _ = _svc().grant_access(db_session, req.id, nip="5555", actor_id=actor.id)

    assert ok is True
    db_session.refresh(req)
    assert req.nip_source == "center"
    assert req.access_sent_at is not None
    assert [n for n, _ in espia_correo] == ["send_enrollment_approved"]


def test_grant_access_con_nip_source_preloaded(
    db_session, make_cohort, make_user, listo, espia_correo,
):
    actor = make_user()
    req = _make_req(db_session, make_cohort(status="open"), control="99580003",
                    status="awaiting_access", reviewed_by_id=actor.id)

    ok, _ = _svc().grant_access(db_session, req.id, nip="5555", actor_id=actor.id,
                                nip_source="preloaded")

    assert ok is True
    db_session.refresh(req)
    assert req.nip_source == "preloaded"
    assert espia_correo[0][1]["nip_source"] == "preloaded"


# ---------------------------------------------------------------------------
# load_rows: un bucket por caso
# ---------------------------------------------------------------------------
def test_devuelve_siempre_las_ocho_llaves(db_session, make_user, llave):
    res = _carga(db_session, [], make_user())
    assert tuple(res) == BUCKETS and all(v == [] for v in res.values())


def test_awaiting_access_recibe_el_acceso(
    db_session, make_cohort, make_user, listo, llave, espia_correo,
):
    from itcj2.core.utils.security import verify_nip

    actor = make_user()
    req = _make_req(db_session, make_cohort(status="open"), control="99580010",
                    status="awaiting_access", reviewed_by_id=actor.id)

    res = _carga(db_session, [("99580010", CENTINELA)], actor)

    assert _controles(res, "granted") == ["99580010"]
    assert sum(len(v) for v in res.values()) == 1
    db_session.refresh(req)
    assert req.status == "converted" and req.nip_source == "preloaded"
    assert req.access_sent_at is not None
    assert verify_nip(CENTINELA, _usuario(db_session, "99580010").password_hash)
    assert not _hay_nip(db_session, "99580010")


def test_pendiente_guarda_el_nip_y_audita_sin_el(
    db_session, make_cohort, make_user, llave,
):
    actor = make_user()
    cohort = make_cohort(status="open")
    r1 = _make_req(db_session, cohort, control="99580011", status="pending_review")
    _make_req(db_session, cohort, control="99580012", status="unverified")

    res = _carga(db_session, [("99580011", CENTINELA), ("99580012", "1234")], actor)

    assert sorted(_controles(res, "stored")) == ["99580011", "99580012"]
    assert _stash().peek(db_session, "99580011") == CENTINELA
    filas = audit_query(db_session).filter_by(action="enrollment.nip_preloaded").all()
    assert len(filas) == 2
    assert {f.entity_id for f in filas} >= {r1.id}
    for f in filas:
        assert f.entity_type == "enrollment_request"
        assert f.payload == {"replaced": False}
        assert not _CENTINELA_RE.search(json.dumps(f.payload, default=str))
        assert f.actor_id == actor.id


def test_volver_a_cargar_reemplaza_y_lo_dice_la_bitacora(
    db_session, make_cohort, make_user, llave,
):
    actor = make_user()
    _make_req(db_session, make_cohort(status="open"), control="99580013")

    _carga(db_session, [("99580013", "1111")], actor)
    res = _carga(db_session, [("99580013", "2222")], actor)

    assert _controles(res, "stored") == ["99580013"]
    assert _stash().peek(db_session, "99580013") == "2222"
    reemplazos = [f.payload["replaced"] for f in
                  audit_query(db_session).filter_by(action="enrollment.nip_preloaded")
                  .order_by("id").all()]
    assert reemplazos == [False, True]


def test_solo_rechazada_va_a_stored_rejected_y_se_guarda(
    db_session, make_cohort, make_user, llave,
):
    actor = make_user()
    _make_req(db_session, make_cohort(status="open"), control="99580014",
              status="rejected")

    res = _carga(db_session, [("99580014", CENTINELA)], actor)

    assert _controles(res, "stored_rejected") == ["99580014"]
    assert res["stored"] == []
    assert _stash().peek(db_session, "99580014") == CENTINELA


def test_la_solicitud_viva_gana_sobre_la_rechazada_de_otra_convocatoria(
    db_session, make_cohort, make_user, llave,
):
    actor = make_user()
    _make_req(db_session, make_cohort(status="closed"), control="99580015",
              status="rejected")
    _make_req(db_session, make_cohort(status="open"), control="99580015",
              status="pending_review")

    res = _carga(db_session, [("99580015", CENTINELA)], actor)

    assert _controles(res, "stored") == ["99580015"]
    assert res["stored_rejected"] == []


def test_con_cuenta_no_hace_nada_aunque_la_solicitud_este_viva(
    db_session, make_cohort, make_user, llave,
):
    actor = make_user()
    _cuenta(db_session, "99580016")
    _make_req(db_session, make_cohort(status="open"), control="99580016",
              status="awaiting_access")

    res = _carga(db_session, [("99580016", CENTINELA)], actor)

    assert _controles(res, "has_account") == ["99580016"]
    assert not _hay_nip(db_session, "99580016")


def test_sin_solicitud(db_session, make_user, llave):
    res = _carga(db_session, [("99580017", CENTINELA)], make_user())

    assert _controles(res, "no_request") == ["99580017"]
    assert not _hay_nip(db_session, "99580017")


def test_nip_invalido_con_la_pista_de_excel(db_session, make_cohort, make_user, llave):
    actor = make_user()
    _make_req(db_session, make_cohort(status="open"), control="99580018")

    res = _carga(db_session, [("99580018", "123")], actor)

    (control, motivo), = res["invalid_nip"]
    assert control == "99580018"
    assert "Excel" in motivo and "cero" in motivo
    assert not _hay_nip(db_session, "99580018")


def test_nip_invalido_de_otra_forma_no_lleva_la_pista(
    db_session, make_cohort, make_user, llave,
):
    actor = make_user()
    _make_req(db_session, make_cohort(status="open"), control="99580019")

    res = _carga(db_session, [("99580019", "12a4"), ("99580020", "")], actor)

    assert _controles(res, "invalid_nip") == ["99580019", "99580020"]
    assert all("Excel" not in m for _, m in res["invalid_nip"])


def test_duplicado_descarta_ambas_apariciones(
    db_session, make_cohort, make_user, llave,
):
    actor = make_user()
    _make_req(db_session, make_cohort(status="open"), control="99580021")

    res = _carga(db_session, [("99580021", "1111"), ("99580021", "2222")], actor)

    assert _controles(res, "duplicate") == ["99580021"]
    assert res["stored"] == []
    assert not _hay_nip(db_session, "99580021")


def test_el_control_con_L_se_normaliza_tambien_para_los_duplicados(
    db_session, make_cohort, make_user, llave,
):
    actor = make_user()
    cohort = make_cohort(status="open")
    _make_req(db_session, cohort, control="99580022")
    _make_req(db_session, cohort, control="99580023")

    res = _carga(db_session, [(" l99580022 ", CENTINELA),
                              ("L99580023", "1111"), ("99580023", "2222")], actor)

    assert _controles(res, "stored") == ["99580022"]
    assert _controles(res, "duplicate") == ["99580023"]
    assert _stash().peek(db_session, "99580022") == CENTINELA


# ---------------------------------------------------------------------------
# Correo que falla / sin correo / dry-run
# ---------------------------------------------------------------------------
def test_correo_que_falla_deja_la_cuenta_y_sigue_con_la_siguiente(
    db_session, make_cohort, make_user, listo, llave, monkeypatch,
):
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    resultados = iter([False, True])
    monkeypatch.setattr(TitulaTecEmailHelper, "send_enrollment_approved",
                        staticmethod(lambda *a, **k: next(resultados)))
    actor = make_user()
    cohort = make_cohort(status="open")
    r1 = _make_req(db_session, cohort, control="99580030",
                   status="awaiting_access", reviewed_by_id=actor.id)
    r2 = _make_req(db_session, cohort, control="99580031",
                   status="awaiting_access", reviewed_by_id=actor.id)

    res = _carga(db_session, [("99580030", CENTINELA), ("99580031", "4321")], actor)

    assert _controles(res, "failed") == ["99580030"]
    assert _controles(res, "granted") == ["99580031"]
    assert not any(_CENTINELA_RE.search(m) for _, m in res["failed"])
    db_session.refresh(r1)
    db_session.refresh(r2)
    assert r1.status == "converted" and r1.access_sent_at is None
    assert _usuario(db_session, "99580030") is not None
    assert r2.access_sent_at is not None


def test_sin_correo_crea_la_cuenta_y_queda_como_no_enviado(
    db_session, make_cohort, make_user, listo, llave, espia_correo,
):
    actor = make_user()
    req = _make_req(db_session, make_cohort(status="open"), control="99580032",
                    status="awaiting_access", reviewed_by_id=actor.id)

    res = _carga(db_session, [("99580032", CENTINELA)], actor, send_mail=False)

    assert _controles(res, "granted") == ["99580032"]
    db_session.refresh(req)
    assert req.access_sent_at is None and _svc().access_mail_unsent(req)
    assert espia_correo == []


def test_grant_que_falla_va_a_failed_con_su_motivo(
    db_session, make_cohort, make_user, listo, llave, espia_correo,
):
    actor = make_user()
    # Convocatoria cerrada: grant_access la rechaza con un motivo.
    _make_req(db_session, make_cohort(status="closed"), control="99580033",
              status="awaiting_access", reviewed_by_id=actor.id)

    res = _carga(db_session, [("99580033", CENTINELA)], actor)

    (control, motivo), = res["failed"]
    assert control == "99580033" and motivo
    assert not _CENTINELA_RE.search(motivo)
    assert _usuario(db_session, "99580033") is None


def test_dry_run_clasifica_pero_no_toca_nada(
    db_session, make_cohort, make_user, listo, llave, espia_correo,
):
    actor = make_user()
    cohort = make_cohort(status="open")
    aw = _make_req(db_session, cohort, control="99580040", status="awaiting_access",
                   reviewed_by_id=actor.id)
    _make_req(db_session, cohort, control="99580041")
    _make_req(db_session, make_cohort(status="closed"), control="99580042",
              status="rejected")
    _cuenta(db_session, "99580043")
    antes = audit_query(db_session).count()

    res = _carga(db_session, [
        ("99580040", CENTINELA), ("99580041", "1234"), ("99580042", "1234"),
        ("99580043", "1234"), ("99580044", "1234"), ("99580045", "12"),
        ("99580046", "1111"), ("99580046", "2222"),
    ], actor, dry_run=True)

    assert _controles(res, "granted") == ["99580040"]
    assert _controles(res, "stored") == ["99580041"]
    assert _controles(res, "stored_rejected") == ["99580042"]
    assert _controles(res, "has_account") == ["99580043"]
    assert _controles(res, "no_request") == ["99580044"]
    assert _controles(res, "invalid_nip") == ["99580045"]
    assert _controles(res, "duplicate") == ["99580046"]
    db_session.refresh(aw)
    assert aw.status == "awaiting_access"
    assert _usuario(db_session, "99580040") is None
    assert not any(_hay_nip(db_session, c) for c in ("99580040", "99580041", "99580042"))
    assert audit_query(db_session).count() == antes
    assert espia_correo == []


def test_ningun_motivo_ni_bucket_contiene_el_nip(
    db_session, make_cohort, make_user, listo, llave, espia_correo,
):
    actor = make_user()
    cohort = make_cohort(status="open")
    _make_req(db_session, cohort, control="99580050", status="awaiting_access",
              reviewed_by_id=actor.id)
    _make_req(db_session, cohort, control="99580051")
    _cuenta(db_session, "99580052")

    res = _carga(db_session, [("99580050", CENTINELA), ("99580051", CENTINELA),
                              ("99580052", CENTINELA), ("99580053", CENTINELA)], actor)

    assert not _CENTINELA_RE.search(json.dumps(res, default=str))
    for f in audit_query(db_session).all():
        assert not _CENTINELA_RE.search(json.dumps(f.payload, default=str))


# ---------------------------------------------------------------------------
# Excepción a media carga: la fila falla, las demás se aplican, la sesión sirve
# ---------------------------------------------------------------------------
def test_excepcion_en_grant_access_deja_la_fila_en_failed_y_sigue(
    db_session, make_cohort, make_user, listo, llave, espia_correo, monkeypatch,
):
    actor = make_user()
    cohort = make_cohort(status="open")
    for c in ("99580060", "99580061", "99580062"):
        _make_req(db_session, cohort, control=c, status="awaiting_access",
                  reviewed_by_id=actor.id)
    real = _svc().grant_access
    llamadas = []

    def _grant(db, req_id, **kw):
        llamadas.append(req_id)
        if len(llamadas) == 2:
            raise RuntimeError(f"revienta con {CENTINELA}")
        return real(db, req_id, **kw)

    monkeypatch.setattr(_svc(), "grant_access", staticmethod(_grant))

    res = _carga(db_session, [("99580060", CENTINELA), ("99580061", CENTINELA),
                              ("99580062", CENTINELA)], actor)

    assert _controles(res, "granted") == ["99580060", "99580062"]
    (control, motivo), = res["failed"]
    assert control == "99580061"
    assert "RuntimeError" in motivo and not _CENTINELA_RE.search(motivo)
    assert _usuario(db_session, "99580060") is not None
    assert _usuario(db_session, "99580062") is not None
    assert _usuario(db_session, "99580061") is None
    # La sesión sigue sirviendo después del rollback.
    assert db_session.query(type(actor)).filter_by(id=actor.id).first() is not None


def test_excepcion_en_put_deja_la_fila_en_failed_y_sigue(
    db_session, make_cohort, make_user, llave, monkeypatch,
):
    actor = make_user()
    cohort = make_cohort(status="open")
    for c in ("99580070", "99580071", "99580072"):
        _make_req(db_session, cohort, control=c)
    real = _stash().put

    def _put(db, control, nip, *, actor_id):
        if control == "99580071":
            raise RuntimeError(f"revienta con {nip}")
        return real(db, control, nip, actor_id=actor_id)

    monkeypatch.setattr(_stash(), "put", staticmethod(_put))

    res = _carga(db_session, [("99580070", CENTINELA), ("99580071", CENTINELA),
                              ("99580072", "4321")], actor)

    assert _controles(res, "stored") == ["99580070", "99580072"]
    (control, motivo), = res["failed"]
    assert control == "99580071"
    assert "RuntimeError" in motivo and not _CENTINELA_RE.search(motivo)
    assert _hay_nip(db_session, "99580070") and _hay_nip(db_session, "99580072")
    assert not _hay_nip(db_session, "99580071")
    assert db_session.query(type(actor)).filter_by(id=actor.id).first() is not None


def test_on_row_avisa_granted_y_failed_al_momento_y_sin_nip(
    db_session, make_cohort, make_user, listo, llave, monkeypatch,
):
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    resultados = iter([True, False])
    monkeypatch.setattr(TitulaTecEmailHelper, "send_enrollment_approved",
                        staticmethod(lambda *a, **k: next(resultados)))
    actor = make_user()
    cohort = make_cohort(status="open")
    for c in ("99580080", "99580081"):
        _make_req(db_session, cohort, control=c, status="awaiting_access",
                  reviewed_by_id=actor.id)
    _make_req(db_session, cohort, control="99580082")
    avisos = []

    _stash().load_rows(db_session, [("99580080", CENTINELA), ("99580081", CENTINELA),
                                    ("99580082", CENTINELA)],
                       actor_id=actor.id, dry_run=False, send_mail=True,
                       on_row=lambda *a: avisos.append(a))

    assert [(b, c) for b, c, _ in avisos] == [("granted", "99580080"),
                                              ("failed", "99580081")]
    assert not _CENTINELA_RE.search(json.dumps(avisos))
