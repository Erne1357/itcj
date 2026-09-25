"""Elegibilidad automática contra el SII: consulta, aprobación automática y
barrido (spec 2026-09-25 §3.4, Tarea 4).

Corre con el SII FALSO y las reglas sintéticas de `sii_fixtures/` (se parchea
`SiiConfig`, nunca `get_settings`). El JSON del SII falso lo arma cada prueba
en `tmp_path` con números de control `9958xxxx`: los `2011xxxx` de
`sii_fixtures/fake_sii.json` podrían existir como cuentas reales en la BD de
dev, y «¿tiene cuenta?» se decide contra `core_users`.

Máquina que fija este archivo:

    create() [modo sii]  ─commit─► enqueue_check(req_id)      (best-effort)
    check()              lock ─► fila `pending` ─commit─► SII (SIN lock)
                         ─► lock + refresh ─► apt | not_apt | error
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from itcj2.apps.titulatec.services.sii.client import SiiConfig

FIXTURES = Path(__file__).parent / "sii_fixtures"
NIP_SII = "4321"
RULES_VERSION = "test-2026-09-25.1"


# ---------------------------------------------------------------------------
# Fixtures locales
# ---------------------------------------------------------------------------
class _FakeSii:
    """Arma el JSON del SII falso por prueba (controles sintéticos)."""

    def __init__(self, path: Path):
        self.path = path
        self.data = {"queries": {"alumno": {}, "adeudos": {}, "nip": {}}}
        self.backend = "fake"
        self.rules = FIXTURES
        self._write()

    def _write(self):
        self.path.write_text(json.dumps(self.data), encoding="utf-8")

    def alumno(self, control, *, nombre="EGRESADA", paterno="DEL SII", materno=None,
               carrera="Ingenieria Ficticia", nip=NIP_SII, **over):
        row = {"no_de_control": control, "nombre": nombre, "apellido_paterno": paterno,
               "apellido_materno": materno, "carrera": carrera, "anio_ingreso": 2019,
               "estatus": "EGRESADO", "creditos_aprobados": 260, "creditos_carrera": 260,
               "servicio_social": "S", "residencia": "S"}
        row.update(over)
        self.data["queries"]["alumno"][control] = [row]
        if nip is not None:
            self.data["queries"]["nip"][control] = [{"nip": nip}]
        self._write()

    def no_apta(self, control, **kw):
        self.alumno(control, creditos_aprobados=200, **kw)

    def caido(self, control):
        self.data["queries"]["alumno"][control] = {"error": "unavailable"}
        self._write()

    def nip_caido(self, control):
        self.data["queries"]["nip"][control] = {"error": "unavailable"}
        self._write()


@pytest.fixture()
def sii(monkeypatch, tmp_path):
    fake = _FakeSii(tmp_path / "fake_sii.json")
    monkeypatch.setattr(SiiConfig, "backend", staticmethod(lambda: fake.backend))
    monkeypatch.setattr(SiiConfig, "fake_file", staticmethod(lambda: fake.path))
    monkeypatch.setattr(SiiConfig, "rules_dir", staticmethod(lambda: Path(fake.rules)))
    monkeypatch.setattr(SiiConfig, "odbc_connection_string", staticmethod(lambda: ""))
    return fake


@pytest.fixture()
def modo_sii(monkeypatch):
    """Modo `sii` (se parchea el método, nunca `get_settings`)."""
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    monkeypatch.setattr(EnrollmentRequestService, "reviewer_mode",
                        staticmethod(lambda: "sii"))


@pytest.fixture(autouse=True)
def _ventana_y_tope(monkeypatch):
    """Ventana 0 h y 5 intentos, fijos aunque el `.env` del contenedor diga otra cosa."""
    from itcj2.apps.titulatec.services.eligibility_service import EligibilityService

    monkeypatch.setattr(EligibilityService, "delay_hours", staticmethod(lambda: 0))
    monkeypatch.setattr(EligibilityService, "max_attempts", staticmethod(lambda: 5))


@pytest.fixture(autouse=True)
def _sin_celery(monkeypatch):
    """`enqueue_check` jamás toca el broker en esta suite; registra las llamadas."""
    llamadas = []
    monkeypatch.setattr(
        "itcj2.apps.titulatec.services.eligibility_service.enqueue_check",
        lambda req_id, **kw: llamadas.append((req_id, kw)))
    return llamadas


@pytest.fixture()
def espia_helper(monkeypatch):
    """Sustituye TODOS los `send_*` del helper por un registro de llamadas."""
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    llamadas = []
    for nombre in [n for n in dir(TitulaTecEmailHelper) if n.startswith("send_")]:
        monkeypatch.setattr(
            TitulaTecEmailHelper, nombre,
            staticmethod(lambda *a, _n=nombre, **k: llamadas.append((_n, k)) or True))
    return llamadas


def _svc():
    from itcj2.apps.titulatec.services.eligibility_service import EligibilityService
    return EligibilityService


def _ers():
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    return EnrollmentRequestService


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


def _checks(db_session, req):
    from itcj2.apps.titulatec.models import EligibilityCheck
    return (db_session.query(EligibilityCheck).filter_by(request_id=req.id)
            .order_by(EligibilityCheck.id).all())


def _check_row(db_session, req, *, status, attempt=1, started_at=None, finished_at=None,
               rules_version=RULES_VERSION):
    """Check ya hecho (historial), apuntado como vigente."""
    from itcj2.apps.titulatec.models import EligibilityCheck

    now = datetime.now()
    chk = EligibilityCheck(request_id=req.id, status=status, attempt=attempt,
                           rules_version=rules_version, started_at=started_at or now,
                           finished_at=finished_at if status != "pending" else None)
    if status != "pending" and chk.finished_at is None:
        chk.finished_at = now
    db_session.add(chk)
    db_session.flush()
    req.last_check_id = chk.id
    db_session.flush()
    return chk


# ---------------------------------------------------------------------------
# Modo y etiqueta
# ---------------------------------------------------------------------------
def test_en_modo_sii_responde_servicios_escolares(modo_sii):
    assert _ers().reviewer_mode() == "sii"
    assert _ers().reviewer_label() == "Servicios Escolares"


def test_los_settings_se_leen_por_metodos_estaticos(monkeypatch):
    from itcj2.apps.titulatec.services.eligibility_service import EligibilityService
    from itcj2.config import get_settings

    monkeypatch.undo()   # quita el autouse que fija 0 h / 5 intentos
    monkeypatch.setattr(get_settings(), "TITULATEC_SII_AUTO_APPROVE_DELAY_HOURS", 7)
    monkeypatch.setattr(get_settings(), "TITULATEC_SII_MAX_ATTEMPTS", 3)
    assert EligibilityService.delay_hours() == 7
    assert EligibilityService.max_attempts() == 3


# ---------------------------------------------------------------------------
# check(): veredictos
# ---------------------------------------------------------------------------
def test_apta_registra_la_consulta_con_reglas_hechos_y_version(
    db_session, make_cohort, sii, modo_sii,
):
    cohort = make_cohort(status="open")
    cohort.sii_auto_approve = False      # esta prueba mira solo la consulta
    req = _make_req(db_session, cohort, control="99580001")
    sii.alumno("99580001")

    chk = _svc().check(db_session, req.id)

    assert chk is not None
    assert chk.status == "apt"
    assert chk.attempt == 1
    assert chk.rules_version == RULES_VERSION
    assert [r["rule"] for r in chk.results] == [
        "existe", "estatus", "creditos", "servicio_social", "residencia", "sin_adeudos"]
    assert all(r["ok"] for r in chk.results)
    assert chk.facts == {"estatus": "EGRESADO", "creditos_aprobados": 260,
                         "creditos_carrera": 260, "anio_ingreso": 2019}
    assert chk.error is None
    assert chk.finished_at is not None and chk.duration_ms is not None
    assert chk.identity_mismatch is None
    assert req.last_check_id == chk.id
    assert req.status == "pending_review"
    assert _svc().latest_check(db_session, req).id == chk.id


def test_no_apta_guarda_el_motivo_exacto(db_session, make_cohort, sii, modo_sii):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580002")
    sii.no_apta("99580002")

    chk = _svc().check(db_session, req.id)

    assert chk.status == "not_apt"
    fallas = [r for r in chk.results if not r["ok"]]
    assert fallas == [{"rule": "creditos", "ok": False,
                       "message": "Le faltan créditos: 200 de 260."}]
    assert req.status == "pending_review", "no apta queda «Por revisar»"


def test_sii_caido_es_error_y_la_solicitud_sigue_por_revisar(
    db_session, make_cohort, sii, modo_sii,
):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580003")
    sii.caido("99580003")

    chk = _svc().check(db_session, req.id)

    assert chk.status == "error"
    assert "no disponible" in chk.error
    assert chk.finished_at is not None
    assert req.status == "pending_review"
    assert req.last_check_id == chk.id


def test_backend_deshabilitado_es_error(db_session, make_cohort, sii, modo_sii):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580004")
    sii.backend = "disabled"

    chk = _svc().check(db_session, req.id)

    assert chk.status == "error"
    assert "deshabilitada" in chk.error


def test_sin_reglas_es_error(db_session, make_cohort, sii, modo_sii, tmp_path):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580005")
    sii.rules = tmp_path / "no_hay_reglas"

    chk = _svc().check(db_session, req.id)

    assert chk.status == "error"
    assert "rules.toml" in chk.error


def test_una_falla_inesperada_es_error_sin_su_mensaje(
    db_session, make_cohort, sii, modo_sii, monkeypatch, caplog,
):
    """Un error que no es del SII puede traer cualquier cosa en su texto: solo
    el tipo llega a la fila y al log."""
    from itcj2.apps.titulatec.services.sii import client as sii_client

    def _revienta():
        raise RuntimeError("PWD=secreto-del-driver")

    monkeypatch.setattr(sii_client, "get_sii_client", _revienta)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580006")

    with caplog.at_level("DEBUG"):
        chk = _svc().check(db_session, req.id)

    assert chk.status == "error"
    assert "RuntimeError" in chk.error
    assert "secreto" not in chk.error
    assert "secreto" not in caplog.text


def test_discrepancia_de_identidad_se_registra(db_session, make_cohort, sii, modo_sii):
    cohort = make_cohort(status="open")
    cohort.sii_auto_approve = False
    req = _make_req(db_session, cohort, control="99580007")
    sii.alumno("99580007", nombre="OTRA PERSONA", carrera="Arquitectura")

    chk = _svc().check(db_session, req.id)

    assert chk.status == "apt", "la identidad informa, no decide"
    assert chk.identity_mismatch == {
        "first_name": {"form": "EGRESADA", "sii": "OTRA PERSONA"},
        "program": {"form": "Ingenieria Ficticia", "sii": "Arquitectura"},
    }


def test_identidad_igual_salvo_acentos_y_mayusculas_no_es_discrepancia(
    db_session, make_cohort, sii, modo_sii,
):
    cohort = make_cohort(status="open")
    cohort.sii_auto_approve = False
    req = _make_req(db_session, cohort, control="99580008", first_name="María José",
                    last_name="Núñez", middle_name="López")
    sii.alumno("99580008", nombre="  MARIA  JOSE ", paterno="NUNEZ", materno="LOPEZ",
               carrera="INGENIERÍA FICTICIA")

    chk = _svc().check(db_session, req.id)

    assert chk.identity_mismatch is None


def test_el_nip_del_sii_no_se_guarda_ni_se_registra(
    db_session, make_cohort, sii, modo_sii, caplog,
):
    cohort = make_cohort(status="open")
    cohort.sii_auto_approve = False
    req = _make_req(db_session, cohort, control="99580009")
    sii.alumno("99580009", nip="8642")

    with caplog.at_level("DEBUG"):
        chk = _svc().check(db_session, req.id)

    guardado = json.dumps([chk.results, chk.facts, chk.identity_mismatch, chk.error,
                           repr(chk)], default=str)
    assert "8642" not in guardado
    assert "8642" not in caplog.text


# ---------------------------------------------------------------------------
# check(): guardas, carreras e idempotencia (Review Focus 2 y 3)
# ---------------------------------------------------------------------------
def test_fuera_del_modo_sii_no_consulta(db_session, make_cohort, sii):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580010")
    sii.alumno("99580010")

    assert _svc().check(db_session, req.id) is None
    assert _checks(db_session, req) == []


@pytest.mark.parametrize("estado", ["approved", "rejected", "converted", "awaiting_access"])
def test_solo_consulta_solicitudes_por_revisar(db_session, make_cohort, sii, modo_sii, estado):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580011", status=estado)
    sii.alumno("99580011")

    assert _svc().check(db_session, req.id) is None
    assert _checks(db_session, req) == []


def test_la_tarea_que_corre_antes_de_ver_el_alta_no_hace_nada(db_session, sii, modo_sii):
    """Carrera alta ↔ tarea: la solicitud todavía no es visible → `None`; el
    barrido la recoge después (no hay check vigente)."""
    assert _svc().check(db_session, 987654321) is None


def test_no_duplica_una_consulta_en_curso(db_session, make_cohort, sii, modo_sii):
    """Dos tareas del mismo `req_id` a la vez: la segunda ve la fila `pending`
    fresca de la primera y no consulta (ni con `force`)."""
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580012")
    sii.alumno("99580012")
    en_curso = _check_row(db_session, req, status="pending")

    assert _svc().check(db_session, req.id, attempt=2) is None
    assert _svc().check(db_session, req.id, force=True) is None
    assert [c.id for c in _checks(db_session, req)] == [en_curso.id]


def test_una_consulta_colgada_se_retoma_con_el_siguiente_intento(
    db_session, make_cohort, sii, modo_sii,
):
    cohort = make_cohort(status="open")
    cohort.sii_auto_approve = False
    req = _make_req(db_session, cohort, control="99580013")
    sii.alumno("99580013")
    _check_row(db_session, req, status="pending",
               started_at=datetime.now() - timedelta(hours=1))

    chk = _svc().check(db_session, req.id, attempt=2)

    assert chk is not None and chk.attempt == 2 and chk.status == "apt"
    assert req.last_check_id == chk.id


def test_el_mismo_intento_dos_veces_consulta_una_sola_vez(
    db_session, make_cohort, sii, modo_sii,
):
    cohort = make_cohort(status="open")
    cohort.sii_auto_approve = False
    req = _make_req(db_session, cohort, control="99580014")
    sii.no_apta("99580014")

    primero = _svc().check(db_session, req.id)
    segundo = _svc().check(db_session, req.id)

    assert primero is not None and segundo is None
    assert len(_checks(db_session, req)) == 1


def test_force_consulta_otra_vez_con_el_siguiente_numero_de_intento(
    db_session, make_cohort, sii, modo_sii,
):
    """«Reintentar consulta» de la bandeja: vuelve a preguntar aunque ya haya
    veredicto (el SII pudo cambiar)."""
    cohort = make_cohort(status="open")
    cohort.sii_auto_approve = False
    req = _make_req(db_session, cohort, control="99580015")
    sii.no_apta("99580015")
    _svc().check(db_session, req.id)
    sii.alumno("99580015")

    chk = _svc().check(db_session, req.id, force=True)

    assert chk.attempt == 2 and chk.status == "apt"
    assert req.last_check_id == chk.id
    assert [c.status for c in _checks(db_session, req)] == ["not_apt", "apt"]


def test_no_pasa_del_tope_de_intentos_sin_force(db_session, make_cohort, sii, modo_sii):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580016")
    sii.caido("99580016")
    _check_row(db_session, req, status="error", attempt=5)

    assert _svc().check(db_session, req.id, attempt=6) is None
    assert len(_checks(db_session, req)) == 1


def test_la_consulta_al_sii_corre_sin_el_lock_de_la_solicitud(
    db_session, make_cohort, sii, modo_sii, monkeypatch,
):
    """Orden: lock → fila `pending` → COMMIT (suelta el lock) → SII → lock otra
    vez → commit. Mientras el SII responde, la fila `pending` ya es la vigente
    («Consultando…» en la bandeja)."""
    from itcj2.apps.titulatec.models import EligibilityCheck
    from itcj2.apps.titulatec.services.sii.client import FakeSiiClient

    cohort = make_cohort(status="open")
    cohort.sii_auto_approve = False
    req = _make_req(db_session, cohort, control="99580017")
    sii.alumno("99580017")

    pasos = []
    commit_real, execute_real = db_session.commit, db_session.execute
    query_real = FakeSiiClient.query

    def _commit():
        pasos.append("commit")
        return commit_real()

    def _execute(stmt, *a, **k):
        if "pg_advisory_xact_lock" in str(stmt):
            pasos.append("lock")
        return execute_real(stmt, *a, **k)

    def _query(self, sql, params, **kw):
        if "sii" not in pasos:
            vigente = db_session.get(EligibilityCheck, req.last_check_id)
            pasos.append(("vigente", vigente.status if vigente else None))
        pasos.append("sii")
        return query_real(self, sql, params, **kw)

    monkeypatch.setattr(db_session, "commit", _commit)
    monkeypatch.setattr(db_session, "execute", _execute)
    monkeypatch.setattr(FakeSiiClient, "query", _query)

    _svc().check(db_session, req.id)

    primera = pasos.index(("vigente", "pending"))
    antes = [p for p in pasos[:primera] if p in ("lock", "commit")]
    assert antes == ["lock", "commit"], pasos
    despues = [p for p in pasos[primera:] if p in ("lock", "commit")]
    assert despues[:2] == ["lock", "commit"], pasos


# ---------------------------------------------------------------------------
# create(): encola tras el commit, solo en modo sii
# ---------------------------------------------------------------------------
def _datos(control):
    return {"control_number": control, "first_name": "EGRESADA", "last_name": "DEL SII",
            "phone": "6561234567", "contact_email": "sii@example.invalid",
            "has_efirma": True, "program_text": "Ingenieria Ficticia"}


def test_el_alta_en_modo_sii_encola_la_consulta_despues_del_commit(
    db_session, make_cohort, modo_sii, monkeypatch, _sin_celery,
):
    pasos = []
    commit_real = db_session.commit
    monkeypatch.setattr(db_session, "commit",
                        lambda: pasos.append("commit") or commit_real())
    monkeypatch.setattr(
        "itcj2.apps.titulatec.services.eligibility_service.enqueue_check",
        lambda req_id, **kw: pasos.append(("encola", req_id)))
    cohort = make_cohort(status="open")

    req, outcome = _ers().create(db_session, cohort, _datos("99580020"), client_ip=None)

    assert outcome == "created"
    assert pasos == ["commit", ("encola", req.id)]


def test_el_alta_fuera_del_modo_sii_no_encola(db_session, make_cohort, _sin_celery):
    cohort = make_cohort(status="open")

    req, outcome = _ers().create(db_session, cohort, _datos("99580021"), client_ip=None)

    assert outcome == "created" and req is not None
    assert _sin_celery == []


def test_enqueue_check_nunca_lanza(monkeypatch, caplog):
    """Best-effort: sin broker el alta sigue igual (y la recoge el barrido)."""
    import importlib

    mod = importlib.import_module("itcj2.apps.titulatec.services.eligibility_service")
    monkeypatch.undo()   # el `enqueue_check` real, sin el parche autouse
    from itcj2.celery_app import celery_app

    def _sin_broker(*a, **k):
        raise ConnectionError("redis://:clave@broker caído")

    monkeypatch.setattr(celery_app, "send_task", _sin_broker)
    with caplog.at_level("WARNING"):
        assert mod.enqueue_check(42) is None
    assert "42" in caplog.text
    assert "clave" not in caplog.text


def test_enqueue_check_manda_la_tarea_por_nombre_sin_reintentar_el_broker(monkeypatch):
    import importlib

    mod = importlib.import_module("itcj2.apps.titulatec.services.eligibility_service")
    monkeypatch.undo()
    from itcj2.celery_app import celery_app

    enviados = []
    monkeypatch.setattr(celery_app, "send_task",
                        lambda name, **kw: enviados.append((name, kw)))

    mod.enqueue_check(42)
    mod.enqueue_check(44, force=True)

    assert enviados[0] == ("itcj2.tasks.titulatec_tasks.sii_check_request",
                           {"kwargs": {"req_id": 42, "attempt": 1, "force": False},
                            "retry": False})
    assert enviados[1][1]["kwargs"] == {"req_id": 44, "attempt": 1, "force": True}
