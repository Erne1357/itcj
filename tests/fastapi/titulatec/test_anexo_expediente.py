"""Fase 6, tarea 7: tarjeta de la fase 6 en el expediente y `AnexoService.empty_label`
(spec fase 6 §9.4; molde de `ReviewService.empty_label`)."""
from __future__ import annotations

import os

import pytest

from itcj2.apps.titulatec.models import ProcessPhase
from itcj2.apps.titulatec.services.anexo_service import (
    NOT_APPLICABLE_LABEL, NOT_IN_APP_LABEL, PENDING_LABEL, AnexoService,
)
from itcj2.apps.titulatec.services.phase_service import PhaseService

URL = "/titulatec/admin/processes"
ROLE = f"tt_test_anexo_exp_{os.getpid()}"
BASE = (
    "titulatec.dashboard.school_services",
    "titulatec.process.page.list",
    "titulatec.process.page.detail",
    "titulatec.document.page.list",
    "titulatec.document.api.read.all",
)
SIN = ("titulatec.synodal.api.read", "titulatec.anexo_iii.api.generate")
REV = ("titulatec.anexo_iii.api.review", "titulatec.titulacion.page.list")
PERMS = BASE + SIN + REV


def _corte(monkeypatch, n):
    monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: n))


# ---------------------------------------------------------------------------
# empty_label
# ---------------------------------------------------------------------------
def test_textos_verbatim():
    assert NOT_APPLICABLE_LABEL == "No aplica para esta modalidad."
    assert PENDING_LABEL == "El proceso todavía no llega al Anexo III."
    assert NOT_IN_APP_LABEL.startswith("Esta fase todavía no está en la app")
    assert "T-soft" in NOT_IN_APP_LABEL


def test_none_en_fase_6_y_despues(db_session, monkeypatch, make_anexo_case):
    _corte(monkeypatch, 9)
    c = make_anexo_case()
    assert AnexoService.empty_label(db_session, c.process) is None
    c.process.current_phase = c.anexo_phase + 1
    assert AnexoService.empty_label(db_session, c.process) is None


def test_pendiente_en_fase_5(db_session, monkeypatch, make_anexo_case):
    _corte(monkeypatch, 9)
    c = make_anexo_case()
    c.process.current_phase = c.review_phase
    assert AnexoService.empty_label(db_session, c.process) == PENDING_LABEL


@pytest.mark.parametrize("corte", [3, 5, 6])
def test_no_esta_en_la_app_con_corte_hasta_6(db_session, monkeypatch, make_anexo_case, corte):
    _corte(monkeypatch, 9)
    c = make_anexo_case()
    _corte(monkeypatch, corte)
    assert AnexoService.empty_label(db_session, c.process) == NOT_IN_APP_LABEL


def test_no_aplica_si_la_fase_esta_skipped(db_session, monkeypatch, make_anexo_case):
    _corte(monkeypatch, 9)
    c = make_anexo_case()
    fase = db_session.query(ProcessPhase).filter_by(
        process_id=c.process.id, phase_number=c.anexo_phase).one()
    fase.status = "skipped"
    db_session.flush()
    assert AnexoService.empty_label(db_session, c.process) == NOT_APPLICABLE_LABEL
    _corte(monkeypatch, 3)          # gana sobre el corte: es un hecho de la modalidad
    assert AnexoService.empty_label(db_session, c.process) == NOT_APPLICABLE_LABEL


def test_no_aplica_si_la_modalidad_salta_la_fase(db_session, monkeypatch, make_anexo_case):
    _corte(monkeypatch, 9)
    c = make_anexo_case()
    c.modality.skips_phases = [4, 5, c.anexo_phase]
    db_session.flush()
    assert AnexoService.empty_label(db_session, c.process) == NOT_APPLICABLE_LABEL


# ---------------------------------------------------------------------------
# Expediente
# ---------------------------------------------------------------------------
@pytest.fixture()
def lector(db_session, make_anexo_case, make_role, grant_user_role, client_as):
    def _build(perms=PERMS, **kw):
        c = make_anexo_case(**kw)
        grant_user_role(c.head, make_role(ROLE, perms))
        db_session.commit()
        return c, client_as(c.head)
    return _build


def _tarjeta_6(html: str) -> str:
    return " ".join(html.split('id="exp-panel-6"')[1].split('id="exp-fase-7"')[0].split())


def test_expediente_muestra_folio_y_estado_en_fase_6(lector, db_session, monkeypatch):
    _corte(monkeypatch, 9)
    c, cli = lector()
    anexo = AnexoService.ensure_folio(db_session, c.process, None)
    db_session.commit()
    resp = cli.get(f"{URL}/{c.process.id}?fase=6")
    assert resp.status_code == 200, resp.text[:400]
    tarjeta = _tarjeta_6(resp.text)
    assert anexo.folio in tarjeta
    assert "data-tt-exp-anexo" in resp.text
    # review + titulacion.page.list -> ligas de Titulacion (no la de Sinodales)
    assert f"/titulatec/admin/titulacion/anexo/{c.process.id}/anexo.pdf" in tarjeta
    assert f"/titulatec/admin/titulacion/anexo/{c.process.id}/escaneo" not in tarjeta  # sin escaneo
    assert "/admin/sinodales/" not in tarjeta
    assert "Esta fase todavía no está en la app: anexo" not in tarjeta


def test_expediente_fase_6_sin_folio_no_emite_uno(lector, db_session, monkeypatch):
    _corte(monkeypatch, 9)
    c, cli = lector()
    resp = cli.get(f"{URL}/{c.process.id}?fase=6")
    assert resp.status_code == 200
    assert "data-tt-exp-anexo" in resp.text
    db_session.expire_all()
    assert AnexoService.get(db_session, c.process.id) is None


def test_expediente_con_corte_3_dice_t_soft_y_no_pinta_ligas(lector, db_session, monkeypatch):
    _corte(monkeypatch, 9)
    c, cli = lector()
    _corte(monkeypatch, 3)
    resp = cli.get(f"{URL}/{c.process.id}?fase=6")
    assert resp.status_code == 200
    tarjeta = _tarjeta_6(resp.text)
    assert NOT_IN_APP_LABEL in tarjeta
    assert "anexo.pdf" not in tarjeta and "escaneo" not in tarjeta


def test_expediente_egel_no_aplica(lector, db_session, monkeypatch):
    _corte(monkeypatch, 9)
    c, cli = lector()
    c.modality.skips_phases = [4, 5, c.anexo_phase]
    db_session.commit()
    resp = cli.get(f"{URL}/{c.process.id}?fase=6")
    assert resp.status_code == 200
    assert NOT_APPLICABLE_LABEL in _tarjeta_6(resp.text)


def _con_escaneo(db, c):
    from itcj2.apps.titulatec.models import Document
    db.add(Document(process_id=c.process.id, phase_number=c.anexo_phase,
                    uploaded_by_id=c.student.id, type_code="anexo_iii", file_path="x/y.pdf",
                    original_name="y.pdf", mime_type="application/pdf", size_bytes=10,
                    review_status="pending", version=1))
    db.commit()


def test_ligas_de_titulacion_con_review_y_page_list_incluyen_escaneo(lector, db_session, monkeypatch):
    _corte(monkeypatch, 9)
    c, cli = lector()
    _con_escaneo(db_session, c)
    t = _tarjeta_6(cli.get(f"{URL}/{c.process.id}?fase=6").text)
    assert f"/titulatec/admin/titulacion/anexo/{c.process.id}/escaneo" in t
    assert f"/titulatec/admin/titulacion/anexo/{c.process.id}/anexo.pdf" in t
    assert "/admin/sinodales/" not in t


def test_solo_generate_y_synodal_read_da_pdf_de_sinodales_sin_escaneo(lector, db_session, monkeypatch):
    _corte(monkeypatch, 9)
    c, cli = lector(perms=BASE + SIN)
    _con_escaneo(db_session, c)
    t = _tarjeta_6(cli.get(f"{URL}/{c.process.id}?fase=6").text)
    assert f"/titulatec/admin/sinodales/{c.process.id}/anexo.pdf" in t
    assert "/admin/titulacion/" not in t and "escaneo" not in t.lower().replace("escaneo firmado", "")


def test_review_sin_page_list_no_da_ligas_de_titulacion(lector, db_session, monkeypatch):
    _corte(monkeypatch, 9)
    c, cli = lector(perms=BASE + ("titulatec.anexo_iii.api.review",))
    _con_escaneo(db_session, c)
    t = _tarjeta_6(cli.get(f"{URL}/{c.process.id}?fase=6").text)
    assert "/admin/titulacion/" not in t and "/admin/sinodales/" not in t


def test_sin_permisos_de_anexo_no_hay_ligas(lector, db_session, monkeypatch):
    _corte(monkeypatch, 9)
    c, cli = lector(perms=BASE)
    _con_escaneo(db_session, c)
    t = _tarjeta_6(cli.get(f"{URL}/{c.process.id}?fase=6").text)
    assert "anexo.pdf" not in t and "/escaneo" not in t
