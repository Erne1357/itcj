"""Purga de NIPs precargados (spec 2026-10-13 N §2 N2/N3, §5.4, §7 punto 7).

`purge_for_cohort` (al cerrar la convocatoria, dentro de `set_window`) y
`purge_stale` + `titulatec purgar-nips` (barrido manual). Ninguna imprime ni
registra un control o un NIP: solo el conteo.
"""
from __future__ import annotations

import inspect
import logging
import re

import pytest
from click.testing import CliRunner

from itcj2.cli.titulatec import purgar_nips_command

pytestmark = pytest.mark.usefixtures("audit_mark")

CENTINELA = "7391"
_CENTINELA_RE = re.compile(rf"(?<!\d){CENTINELA}(?!\d)")


def _stash():
    from itcj2.apps.titulatec.services.nip_stash_service import NipStashService
    return NipStashService


def _make_req(db_session, cohort, *, control, status="pending_review"):
    from itcj2.apps.titulatec.models import EnrollmentRequest

    row = EnrollmentRequest(
        cohort_id=cohort.id, control_number=control,
        first_name="EGRESADA", last_name="PURGADA", middle_name=None,
        program_id=None, program_text="Ingenieria Ficticia",
        phone="6561234567", contact_email="purga@example.invalid",
        has_efirma=True, kind="unknown", status=status, verify_send_count=0,
    )
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


def _guardar(db_session, control):
    _stash().put(db_session, control, CENTINELA, actor_id=None)


def _hay(db_session, control) -> bool:
    from itcj2.apps.titulatec.models import NipStash
    return db_session.get(NipStash, control) is not None


def _cerrar(db_session, cohort, actor):
    from itcj2.apps.titulatec.services.cohort_service import CohortService

    return CohortService.set_window(db_session, cohort.id, opens_at=cohort.opens_at,
                                    closes_at=cohort.closes_at, status="closed",
                                    actor_id=actor.id)


# ---------------------------------------------------------------------------
# purge_for_cohort
# ---------------------------------------------------------------------------
def test_cerrar_purga_la_rechazada(db_session, make_cohort, make_head, llave):
    cohort = make_cohort(status="open")
    _make_req(db_session, cohort, control="99580001", status="rejected")
    _guardar(db_session, "99580001")

    _cerrar(db_session, cohort, make_head())

    assert not _hay(db_session, "99580001")


def test_cerrar_no_purga_la_pendiente(db_session, make_cohort, make_head, llave):
    cohort = make_cohort(status="open")
    for control, status in (("99580002", "pending_review"), ("99580003", "awaiting_access")):
        _make_req(db_session, cohort, control=control, status=status)
        _guardar(db_session, control)

    _cerrar(db_session, cohort, make_head())

    assert _hay(db_session, "99580002") and _hay(db_session, "99580003")


def test_no_purga_si_hay_otra_solicitud_viva_en_otra_convocatoria(
    db_session, make_cohort, llave,
):
    """Review Focus 2: rechazada en una convocatoria, pendiente en otra."""
    cerrada = make_cohort(status="closed")
    otra = make_cohort(status="open")
    _make_req(db_session, cerrada, control="99580004", status="rejected")
    _make_req(db_session, otra, control="99580004", status="pending_review")
    _guardar(db_session, "99580004")

    n = _stash().purge_for_cohort(db_session, cerrada.id)

    assert n == 0 and _hay(db_session, "99580004")


def test_purga_los_que_ya_tienen_cuenta_aunque_la_solicitud_siga_viva(
    db_session, make_cohort, llave,
):
    cohort = make_cohort(status="open")
    _make_req(db_session, cohort, control="99580005", status="pending_review")
    _cuenta(db_session, "99580005")
    _guardar(db_session, "99580005")

    n = _stash().purge_for_cohort(db_session, cohort.id)

    assert n == 1 and not _hay(db_session, "99580005")


def test_purge_for_cohort_no_toca_controles_de_otras_convocatorias(
    db_session, make_cohort, llave,
):
    cohort = make_cohort(status="open")
    otra = make_cohort(status="open")
    _make_req(db_session, otra, control="99580006", status="rejected")
    _guardar(db_session, "99580006")

    _stash().purge_for_cohort(db_session, cohort.id)

    assert _hay(db_session, "99580006")


def test_los_metodos_de_purga_no_commitean():
    """La transacción es del llamador (`set_window` / el CLI)."""
    for nombre in ("purge_for_cohort", "purge_stale"):
        assert ".commit(" not in inspect.getsource(getattr(_stash(), nombre))


def test_closed_a_open_no_restaura_nada_ni_truena(db_session, make_cohort, make_head, llave):
    from itcj2.apps.titulatec.services.cohort_service import CohortService

    cohort = make_cohort(status="open")
    _make_req(db_session, cohort, control="99580008", status="rejected")
    _guardar(db_session, "99580008")
    jefa = make_head()
    _cerrar(db_session, cohort, jefa)

    CohortService.set_window(db_session, cohort.id, opens_at=cohort.opens_at,
                             closes_at=cohort.closes_at, status="open", actor_id=jefa.id)

    assert not _hay(db_session, "99580008")


def test_cerrar_sin_llave_tambien_purga(db_session, make_cohort, make_head, llave,
                                        monkeypatch):
    """Borrar no necesita la llave."""
    from itcj2.config import get_settings

    cohort = make_cohort(status="open")
    _make_req(db_session, cohort, control="99580009", status="rejected")
    _guardar(db_session, "99580009")
    monkeypatch.setattr(get_settings(), "TITULATEC_NIP_STASH_KEY", None)

    _cerrar(db_session, cohort, make_head())

    assert not _hay(db_session, "99580009")


def test_la_purga_no_loguea_controles_ni_nips(db_session, make_cohort, llave, caplog):
    cohort = make_cohort(status="open")
    _make_req(db_session, cohort, control="99580010", status="rejected")
    _guardar(db_session, "99580010")

    with caplog.at_level(logging.DEBUG):
        _stash().purge_for_cohort(db_session, cohort.id)
        _stash().purge_stale(db_session)

    assert "99580010" not in caplog.text and not _CENTINELA_RE.search(caplog.text)


def _bajas_del_stash(db_session):
    from tests.fastapi.titulatec.conftest import audit_query

    return [f for f in audit_query(db_session).all()
            if f.action == "data.delete" and f.entity_type == "titulatec_nip_stash"]


def _sin_secretos(filas):
    for f in filas:
        for valor in (f.before, f.after, f.payload, f.reason, f.subject_label):
            assert CENTINELA not in str(valor), (f.action, valor)
            assert "gAAAA" not in str(valor), (f.action, valor)  # token Fernet


def test_cerrar_deja_rastro_de_cada_nip_purgado_sin_cifrado(
    db_session, make_cohort, make_head, llave,
):
    cohort = make_cohort(status="open")
    for c in ("99580101", "99580102"):
        _make_req(db_session, cohort, control=c, status="rejected")
        _guardar(db_session, c)

    _cerrar(db_session, cohort, make_head())

    bajas = _bajas_del_stash(db_session)
    assert sorted(b.before["control_number"] for b in bajas) == ["99580101", "99580102"]
    assert all(b.before["nip_cipher"] == "***" for b in bajas)
    _sin_secretos(bajas)


def test_purge_stale_deja_rastro_de_cada_nip_purgado(db_session, make_cohort, llave):
    cerrada = make_cohort(status="closed")
    _make_req(db_session, cerrada, control="99580103", status="rejected")
    _guardar(db_session, "99580103")

    assert _stash().purge_stale(db_session) >= 1

    bajas = _bajas_del_stash(db_session)
    assert [b.before["control_number"] for b in bajas] == ["99580103"]
    assert bajas[0].before["nip_cipher"] == "***"
    _sin_secretos(bajas)


# ---------------------------------------------------------------------------
# purge_stale
# ---------------------------------------------------------------------------
def test_purge_stale_borra_cuenta_y_rechazadas_de_convocatorias_cerradas(
    db_session, make_cohort, llave,
):
    cerrada = make_cohort(status="closed")
    abierta = make_cohort(status="open")
    _make_req(db_session, cerrada, control="99580011", status="rejected")        # purga
    _make_req(db_session, abierta, control="99580012", status="rejected")        # convocatoria abierta
    _make_req(db_session, cerrada, control="99580013", status="rejected")
    _make_req(db_session, abierta, control="99580013", status="pending_review")  # viva en otra
    _make_req(db_session, abierta, control="99580014", status="pending_review")
    _cuenta(db_session, "99580014")                                              # cuenta
    _make_req(db_session, cerrada, control="99580015", status="pending_review")  # viva
    for c in ("99580011", "99580012", "99580013", "99580014", "99580015"):
        _guardar(db_session, c)

    n = _stash().purge_stale(db_session)

    assert n >= 2
    assert not _hay(db_session, "99580011") and not _hay(db_session, "99580014")
    assert _hay(db_session, "99580012") and _hay(db_session, "99580013")
    assert _hay(db_session, "99580015")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _seed_vencida(db_session, make_cohort):
    cohort = make_cohort(status="closed")
    _make_req(db_session, cohort, control="99580020", status="rejected")
    _guardar(db_session, "99580020")


def test_cli_dry_run_no_borra(db_session, patched_session_local, make_cohort, llave):
    _seed_vencida(db_session, make_cohort)

    res = CliRunner().invoke(purgar_nips_command, ["--dry-run"])

    assert res.exit_code == 0, res.output
    assert _hay(db_session, "99580020")
    assert "dry-run" in res.output.lower() and "no se borró" in res.output.lower()
    assert "99580020" not in res.output and not _CENTINELA_RE.search(res.output)


def test_cli_borra_e_imprime_solo_el_conteo(db_session, patched_session_local,
                                            make_cohort, llave):
    _seed_vencida(db_session, make_cohort)

    res = CliRunner().invoke(purgar_nips_command, [])

    assert res.exit_code == 0, res.output
    assert not _hay(db_session, "99580020")
    assert re.search(r"\b\d+\b", res.output)
    assert "99580020" not in res.output and not _CENTINELA_RE.search(res.output)


def test_rechazada_en_otra_convocatoria_abierta_conserva_el_nip_hasta_que_cierre(
    db_session, make_cohort, make_head, llave,
):
    """Rechazada en A (abierta, reabrible) y en B: cerrar B no purga; cerrar A sí."""
    a = make_cohort(status="open")
    b = make_cohort(status="open")
    _make_req(db_session, a, control="99580030", status="rejected")
    _make_req(db_session, b, control="99580030", status="rejected")
    _guardar(db_session, "99580030")
    jefa = make_head()

    _cerrar(db_session, b, jefa)
    assert _hay(db_session, "99580030")
    assert _stash().purge_stale(db_session) >= 0 and _hay(db_session, "99580030")

    _cerrar(db_session, a, jefa)
    assert not _hay(db_session, "99580030")
