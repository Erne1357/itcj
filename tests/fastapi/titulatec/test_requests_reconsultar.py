"""«Reintentar consulta» en la bandeja de Solicitudes (modo `sii`, spec 2026-09-25 §3.5).

`POST /titulatec/admin/solicitudes/{id}/reconsultar` encola una consulta
forzada al SII (`eligibility_service.enqueue_check(id, force=True)`) y vuelve a
pintar la bandeja. Contrato que fija este archivo:

- UN código en `perms`: `titulatec.enrollment_request.api.approve` (globals).
- Solo en el modo `sii`: en los otros dos, 400 con motivo y nada encolado.
- Mismo alcance por carrera que aprobar: fuera de alcance = 404 liso.
- Solo una solicitud `pending_review` (lo único que `EligibilityService.check`
  consulta).
- NO duplica: con una consulta vigente en curso (`pending` fresca) responde
  400 sin encolar, y la bandeja que devuelve ya pinta «Consultando…» sin el
  botón, para que un segundo clic no pida otra.

Al final, el NIP del SII jamás llega al HTML de la bandeja, con una consulta
REAL al SII falso (no una fila sembrada a mano).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import unquote

import pytest

from itcj2.apps.titulatec.services.sii.client import SiiConfig
from tests.fastapi.titulatec.conftest import OFFICER_PERMS

URL = "/titulatec/admin/solicitudes"
FIXTURES = Path(__file__).parent / "sii_fixtures"

LIST_PERMS = (
    "titulatec.enrollment_request.page.list",
    "titulatec.enrollment_request.api.approve",
    "titulatec.enrollment_request.api.reject",
    "titulatec.process.api.read.all",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def modo_sii(monkeypatch):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    monkeypatch.setattr(EnrollmentRequestService, "reviewer_mode",
                        staticmethod(lambda: "sii"))


@pytest.fixture(autouse=True)
def _tope_y_ventana(monkeypatch):
    from itcj2.apps.titulatec.services.eligibility_service import EligibilityService

    monkeypatch.setattr(EligibilityService, "max_attempts", staticmethod(lambda: 5))
    monkeypatch.setattr(EligibilityService, "delay_hours", staticmethod(lambda: 0))


@pytest.fixture(autouse=True)
def encolado(monkeypatch):
    """`enqueue_check` jamás toca el broker aquí; registra cada llamada."""
    llamadas = []
    monkeypatch.setattr(
        "itcj2.apps.titulatec.services.eligibility_service.enqueue_check",
        lambda req_id, **kw: llamadas.append((req_id, kw)))
    return llamadas


def _make_req(db_session, cohort, *, control, status="pending_review", program=None, **kw):
    from itcj2.apps.titulatec.models import EnrollmentRequest

    row = EnrollmentRequest(
        cohort_id=cohort.id, control_number=control,
        first_name="EGRESADA", last_name="DEL SII", middle_name=None,
        program_id=getattr(program, "id", program), program_text="Ingenieria Ficticia",
        phone="6561234567", contact_email="sii@example.invalid",
        has_efirma=True, kind="unknown", status=status, verify_send_count=0,
    )
    for k, v in kw.items():
        setattr(row, k, v)
    db_session.add(row)
    db_session.flush()
    return row


def _consulta(db_session, req, *, status, attempt=1, started_at=None):
    from itcj2.apps.titulatec.models import EligibilityCheck

    now = datetime.now()
    chk = EligibilityCheck(request_id=req.id, status=status, attempt=attempt,
                           started_at=started_at or now,
                           finished_at=None if status == "pending" else now)
    db_session.add(chk)
    db_session.flush()
    req.last_check_id = chk.id
    db_session.flush()
    return chk


def _post(c, req, *, status="pending_review", cohort_id=""):
    return c.post(f"{URL}/{req.id}/reconsultar",
                  data={"status": status, "cohort_id": cohort_id},
                  follow_redirects=False)


def _fila(html: str, req) -> str:
    marca = f'id="tt-req-{req.id}"'
    assert marca in html, f"no está la fila de la solicitud {req.id}"
    return html.split(marca, 1)[1].split("</tr>", 1)[0]


def _plano(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


# ---------------------------------------------------------------------------
# Encola
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("vigente", [None, "not_apt", "error", "apt"])
def test_reconsultar_encola_una_consulta_forzada_y_repinta_la_bandeja(
    client_as, db_session, make_head, make_cohort, modo_sii, encolado, vigente,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99650001")
    if vigente:
        _consulta(db_session, req, status=vigente, attempt=2)

    resp = _post(client_as(head), req, cohort_id=str(cohort.id))

    assert resp.status_code == 200, resp.headers.get("X-Tt-Error")
    assert encolado == [(req.id, {"force": True})]
    assert 'id="tt-requests-body"' in resp.text
    assert unquote(resp.headers["X-Tt-Notice"]).startswith("Consulta al SII solicitada")
    # No duplica desde la UI: la fila ya dice «Consultando…» y no trae el botón.
    fila = _fila(resp.text, req)
    assert "Consultando…" in _plano(fila)
    assert "/reconsultar" not in fila


def test_reconsultar_vuelve_a_la_pestana_y_convocatoria_del_oficial(
    client_as, db_session, make_head, make_cohort, modo_sii,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99650002")

    resp = _post(client_as(head), req, status="all", cohort_id=str(cohort.id))

    assert resp.status_code == 200
    activa = re.search(r'id="tt-req-tab-([a-z_]+)"[^>]*aria-current="true"', resp.text)
    assert activa and activa.group(1) == "all"
    assert f"cohort_id={cohort.id}" in resp.text


# ---------------------------------------------------------------------------
# No duplica
# ---------------------------------------------------------------------------
def test_con_una_consulta_en_curso_no_encola_otra(
    client_as, db_session, make_head, make_cohort, modo_sii, encolado,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99650003")
    chk = _consulta(db_session, req, status="pending")

    resp = _post(client_as(head), req)

    assert resp.status_code == 400
    assert unquote(resp.headers["X-Tt-Error"]) == (
        "Ya se está consultando al SII; espera el resultado.")
    assert encolado == []
    db_session.refresh(req)
    assert req.last_check_id == chk.id, "no se abrió otra consulta"


def test_una_consulta_colgada_si_se_puede_reintentar(
    client_as, db_session, make_head, make_cohort, modo_sii, encolado,
):
    """`pending` de hace más de `_PENDING_STALE`: el servicio con `force` la retoma."""
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99650004")
    _consulta(db_session, req, status="pending",
              started_at=datetime.now() - timedelta(hours=1))

    resp = _post(client_as(head), req)

    assert resp.status_code == 200
    assert encolado == [(req.id, {"force": True})]


# ---------------------------------------------------------------------------
# Cortes
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("modo", ["school_services", "computer_center"])
def test_fuera_del_modo_sii_no_encola(
    client_as, db_session, make_head, make_cohort, monkeypatch, encolado, modo,
):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    monkeypatch.setattr(EnrollmentRequestService, "reviewer_mode",
                        staticmethod(lambda: modo))
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99650005")

    resp = _post(client_as(head), req)

    assert resp.status_code == 400
    assert unquote(resp.headers["X-Tt-Error"]) == (
        "La consulta al SII solo existe en el modo sii.")
    assert encolado == []


@pytest.mark.parametrize("estado", ["approved", "converted", "rejected", "unverified"])
def test_una_solicitud_que_no_esta_por_revisar_no_se_consulta(
    client_as, db_session, make_head, make_cohort, modo_sii, encolado, estado,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99650006", status=estado)

    resp = _post(client_as(head), req)

    assert resp.status_code == 400
    assert unquote(resp.headers["X-Tt-Error"]) == "Esa solicitud ya se resolvió."
    assert encolado == []


def test_una_solicitud_inexistente_da_404(client_as, make_head, modo_sii, encolado):
    head = make_head(perm_codes=LIST_PERMS)

    resp = client_as(head).post(f"{URL}/999999999/reconsultar", data={},
                                follow_redirects=False)

    assert resp.status_code == 404
    assert "X-Tt-Error" not in resp.headers
    assert encolado == []


def test_fuera_de_alcance_da_404_y_dentro_si_encola(
    client_as, db_session, make_officer, make_program, make_cohort, modo_sii, encolado,
):
    mia, ajena = make_program("Ing. Reconsultar Mia"), make_program("Ing. Reconsultar Ajena")
    encargado, _pos = make_officer([mia], perm_codes=OFFICER_PERMS + LIST_PERMS[:3])
    cohort = make_cohort(status="open")
    req_ajena = _make_req(db_session, cohort, control="99650007", program=ajena)
    req_mia = _make_req(db_session, cohort, control="99650008", program=mia)
    c = client_as(encargado)

    r_ajena = _post(c, req_ajena)
    r_mia = _post(c, req_mia)

    assert r_ajena.status_code == 404
    assert "X-Tt-Error" not in r_ajena.headers
    assert r_mia.status_code == 200
    assert encolado == [(req_mia.id, {"force": True})]


def test_sin_el_permiso_de_aprobar_no_pasa_y_con_el_si(
    client_as, db_session, make_app_user_without_perms, make_head, make_cohort,
    modo_sii, encolado,
):
    solo_ve = make_app_user_without_perms(perm_codes=(
        "titulatec.enrollment_request.page.list", "titulatec.process.api.read.all"))
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99650009")

    r_sin = _post(client_as(solo_ve), req)
    r_con = _post(client_as(head), req)

    assert r_sin.status_code == 403
    assert r_con.status_code == 200
    assert encolado == [(req.id, {"force": True})]


def test_la_ruta_pide_exactamente_el_permiso_de_aprobar():
    """UN código en `perms`: la lista es OR y uno de más abre la ruta."""
    import inspect

    from itcj2.apps.titulatec.pages import requests_admin

    fuente = inspect.getsource(requests_admin.reconsultar)
    assert 'perms=_APPROVE' in fuente
    assert requests_admin._APPROVE == ["titulatec.enrollment_request.api.approve"]


# ---------------------------------------------------------------------------
# El NIP del SII jamás en el HTML (consulta REAL al SII falso)
# ---------------------------------------------------------------------------
NIP_SII = "8642"


@pytest.fixture()
def sii_falso(monkeypatch, tmp_path):
    """SII falso con las reglas sintéticas de `sii_fixtures/` y un JSON propio
    (controles `9965xxxx`, que no existen como cuentas)."""
    data = {"queries": {"alumno": {}, "adeudos": {}, "nip": {}}}
    ruta = tmp_path / "fake_sii.json"

    def alumno(control, **over):
        row = {"no_de_control": control, "nombre": "EGRESADA", "apellido_paterno": "DEL SII",
               "apellido_materno": None, "carrera": "Ingenieria Ficticia",
               "anio_ingreso": 2019, "estatus": "EGRESADO", "creditos_aprobados": 260,
               "creditos_carrera": 260, "servicio_social": "S", "residencia": "S"}
        row.update(over)
        data["queries"]["alumno"][control] = [row]
        data["queries"]["nip"][control] = [{"nip": NIP_SII}]
        ruta.write_text(json.dumps(data), encoding="utf-8")

    ruta.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(SiiConfig, "backend", staticmethod(lambda: "fake"))
    monkeypatch.setattr(SiiConfig, "fake_file", staticmethod(lambda: ruta))
    monkeypatch.setattr(SiiConfig, "rules_dir", staticmethod(lambda: FIXTURES))
    monkeypatch.setattr(SiiConfig, "odbc_connection_string", staticmethod(lambda: ""))
    return alumno


def test_el_nip_del_sii_nunca_llega_a_la_bandeja(
    client_as, db_session, make_head, make_cohort, modo_sii, sii_falso,
):
    """Una no apta y una apta con la aprobación automática apagada quedan
    «Por revisar» con su consulta REAL; el SII tiene NIP para las dos."""
    from itcj2.apps.titulatec.services.eligibility_service import EligibilityService

    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    cohort.sii_auto_approve = False
    db_session.flush()
    no_apta = _make_req(db_session, cohort, control="99650020")
    sii_falso("99650020", creditos_aprobados=200)
    apta = _make_req(db_session, cohort, control="99650021")
    sii_falso("99650021")

    assert EligibilityService.check(db_session, no_apta.id).status == "not_apt"
    assert EligibilityService.check(db_session, apta.id).status == "apt"
    db_session.refresh(apta)
    assert apta.status == "pending_review", "el interruptor apagado la deja aquí"

    html = client_as(head).get(f"{URL}/body?cohort_id={cohort.id}").text

    assert "Le faltan créditos: 200 de 260." in _plano(_fila(html, no_apta))
    assert "La aprobación automática está apagada" in _plano(_fila(html, apta))
    assert NIP_SII not in html
