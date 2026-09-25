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

    def consulta_invalida(self, control):
        """`SiiQueryError`: el SII respondió, pero la consulta no sirve."""
        self.data["queries"]["alumno"][control] = {"error": "query"}
        self._write()

    def nip_invalido(self, control):
        """`SiiQueryError` al pedir el NIP (p. ej. sin permiso sobre la tabla)."""
        self.data["queries"]["nip"][control] = {"error": "query"}
        self._write()

    def nip_sin_columna(self, control):
        """La consulta del NIP no devuelve la columna de `[credential]`
        (`SiiRulesError`); la fila trae otro dato que NO debe aparecer."""
        self.data["queries"]["nip"][control] = [{"otra": "7777"}]
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
               rules_version=RULES_VERSION, retryable=None, identity_mismatch=None):
    """Check ya hecho (historial), apuntado como vigente."""
    from itcj2.apps.titulatec.models import EligibilityCheck

    now = datetime.now()
    chk = EligibilityCheck(request_id=req.id, status=status, attempt=attempt,
                           rules_version=rules_version, started_at=started_at or now,
                           finished_at=finished_at if status != "pending" else None,
                           retryable=retryable, identity_mismatch=identity_mismatch)
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


# Spec §3.4: se reintenta SOLO ante `SiiUnavailable` (conexión, timeout,
# backend apagado). Una regla rota o una consulta inválida no se arreglan
# solas: quedan en «Error» para Servicios Escolares, con su motivo.
@pytest.mark.parametrize("falla", ["caido", "deshabilitado"])
def test_el_sii_que_no_responde_es_un_error_reintentable(
    db_session, make_cohort, sii, modo_sii, falla,
):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580080")
    if falla == "caido":
        sii.caido("99580080")
    else:
        sii.backend = "disabled"

    chk = _svc().check(db_session, req.id)

    assert chk.status == "error"
    assert chk.retryable is True


@pytest.mark.parametrize("falla", ["consulta", "reglas", "inesperada"])
def test_un_error_de_configuracion_no_es_reintentable(
    db_session, make_cohort, sii, modo_sii, tmp_path, monkeypatch, falla,
):
    from itcj2.apps.titulatec.services.sii.client import FakeSiiClient

    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580081")
    if falla == "consulta":
        sii.consulta_invalida("99580081")
    elif falla == "reglas":
        sii.rules = tmp_path / "no_hay_reglas"
    else:
        def _revienta(self, *a, **k):
            raise RuntimeError("falla del cliente")
        monkeypatch.setattr(FakeSiiClient, "query", _revienta)

    chk = _svc().check(db_session, req.id)

    assert chk.status == "error"
    assert chk.retryable is False


def test_un_veredicto_no_es_error_ni_reintentable(db_session, make_cohort, sii, modo_sii):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580082")
    sii.no_apta("99580082")

    chk = _svc().check(db_session, req.id)

    assert chk.status == "not_apt"
    assert chk.retryable is None


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



# ---------------------------------------------------------------------------
# Aprobación automática (spec S2, S4, S5)
# ---------------------------------------------------------------------------
_NOTA_SIN_NIP = "El SII no devolvió NIP."


def _cuenta(db_session, control, *, password=True):
    from itcj2.core.models.user import User
    from itcj2.core.utils.security import hash_nip

    user = User(username=control, control_number=control, first_name="YA",
                last_name="EXISTIA", password_hash=hash_nip("9999") if password else None,
                is_active=True, must_change_password=False)
    db_session.add(user)
    db_session.flush()
    return user


def _usuario(db_session, control):
    from itcj2.core.models.user import User
    return db_session.query(User).filter_by(control_number=control).first()


def _eventos(db_session, proc_id):
    from itcj2.apps.titulatec.models import ProcessEvent
    return (db_session.query(ProcessEvent)
            .filter_by(process_id=proc_id, event_type="enrollment_self_service").all())


@pytest.fixture()
def listo(db_session, seed_phase_defs, titulatec_app, sii, modo_sii, espia_helper):
    """SII falso + modo sii + lo que `import_rows` necesita. Devuelve el espía
    de correos."""
    seed_phase_defs()
    return espia_helper


def _solicitud_apta(db_session, make_cohort, sii, control, *, cohort=None, **kw):
    cohort = cohort or make_cohort(status="open")
    req = _make_req(db_session, cohort, control=control)
    sii.alumno(control, **kw)
    return req, cohort


def test_apta_sin_cuenta_se_aprueba_sola_con_el_nip_del_sii(
    db_session, make_cohort, sii, listo, caplog,
):
    from itcj2.core.utils.security import verify_nip

    req, _ = _solicitud_apta(db_session, make_cohort, sii, "99580030", nip="2468")

    with caplog.at_level("DEBUG"):
        chk = _svc().check(db_session, req.id)

    assert chk.status == "apt"
    assert req.status == "converted"
    assert req.reviewed_by_id is None and req.reviewed_at is not None
    user = _usuario(db_session, "99580030")
    assert user is not None and verify_nip("2468", user.password_hash)
    assert user.must_change_password is False, "el NIP es suyo, del SII"
    ev, = _eventos(db_session, req.converted_process_id)
    assert ev.actor_id is None
    assert ev.payload["auto"] is True
    assert ev.payload["rules_version"] == RULES_VERSION
    assert ev.payload["check_id"] == chk.id
    assert ev.payload["nip_source"] == "sii"
    assert ev.payload["approved_by_id"] is None
    assert "2468" not in json.dumps(ev.payload)
    assert listo == [("send_enrollment_approved", {"nip": None, "reassigned": False,
                                                   "nip_source": "sii"})]
    assert "2468" not in caplog.text


def test_apta_con_cuenta_recibe_la_liga_y_la_cuenta_no_se_toca(
    db_session, make_cohort, sii, listo,
):
    from itcj2.core.utils.security import verify_nip

    user = _cuenta(db_session, "99580031")
    hash_antes = user.password_hash
    req, _ = _solicitud_apta(db_session, make_cohort, sii, "99580031")

    _svc().check(db_session, req.id)

    assert req.status == "approved"
    assert req.verify_token_hash is not None
    assert req.reviewed_by_id is None and req.reviewed_at is not None
    assert user.password_hash == hash_antes and verify_nip("9999", user.password_hash)
    assert [n for n, _ in listo] == ["send_verify_enrollment"]


def test_la_liga_de_una_aprobada_sola_deja_la_marca_auto_en_el_expediente(
    db_session, make_cohort, sii, listo, monkeypatch,
):
    from itcj2.apps.titulatec.services import enrollment_request_service as ers

    claros = []
    monkeypatch.setattr(ers, "_token_cache_put", claros.append)
    _cuenta(db_session, "99580032")
    req, _ = _solicitud_apta(db_session, make_cohort, sii, "99580032")
    chk = _svc().check(db_session, req.id)

    _req, outcome = _ers().verify(db_session, claros[0])

    assert outcome == "converted"
    ev, = _eventos(db_session, req.converted_process_id)
    assert ev.payload["auto"] is True and ev.payload["check_id"] == chk.id
    assert ev.payload["activation"] == "personal_email_link"


def test_con_el_interruptor_apagado_queda_por_revisar(db_session, make_cohort, sii, listo):
    cohort = make_cohort(status="open")
    cohort.sii_auto_approve = False
    req, _ = _solicitud_apta(db_session, make_cohort, sii, "99580033", cohort=cohort)

    chk = _svc().check(db_session, req.id)

    assert chk.status == "apt" and req.status == "pending_review"
    assert _usuario(db_session, "99580033") is None
    assert listo == []


def test_con_la_convocatoria_cerrada_queda_por_revisar(db_session, make_cohort, sii, listo):
    cohort = make_cohort(status="closed")
    req, _ = _solicitud_apta(db_session, make_cohort, sii, "99580034", cohort=cohort)

    _svc().check(db_session, req.id)

    assert req.status == "pending_review"
    assert listo == []


def test_con_ventana_de_veto_no_se_aprueba_al_consultar(
    db_session, make_cohort, sii, listo, monkeypatch,
):
    monkeypatch.setattr(_svc(), "delay_hours", staticmethod(lambda: 2))
    req, _ = _solicitud_apta(db_session, make_cohort, sii, "99580035")

    chk = _svc().check(db_session, req.id)
    ok, motivo = _svc().auto_approve(db_session, req.id)

    assert chk.status == "apt" and req.status == "pending_review"
    assert ok is False and "ventana" in motivo
    assert listo == []


def test_vencida_la_ventana_se_aprueba(db_session, make_cohort, sii, listo, monkeypatch):
    monkeypatch.setattr(_svc(), "delay_hours", staticmethod(lambda: 2))
    req, _ = _solicitud_apta(db_session, make_cohort, sii, "99580036")
    _svc().check(db_session, req.id)

    ok, folio = _svc().auto_approve(db_session, req.id,
                                    now=datetime.now() + timedelta(hours=3))

    assert ok is True and folio
    assert req.status == "converted"


@pytest.mark.parametrize("cambio", ["cerrada", "apagada"])
def test_si_la_convocatoria_cambia_dentro_de_la_ventana_no_se_aprueba(
    db_session, make_cohort, sii, listo, monkeypatch, cambio,
):
    """Review Focus 5: apta a las 10:00, ventana de 2 h, SE cierra la
    convocatoria (o apaga el interruptor) a las 11:00 → a las 12:01 no aprueba."""
    monkeypatch.setattr(_svc(), "delay_hours", staticmethod(lambda: 2))
    cohort = make_cohort(status="open")
    req, _ = _solicitud_apta(db_session, make_cohort, sii, "99580037", cohort=cohort)
    _svc().check(db_session, req.id)
    if cambio == "cerrada":
        cohort.status = "closed"
    else:
        cohort.sii_auto_approve = False
    db_session.flush()

    ok, _ = _svc().auto_approve(db_session, req.id, now=datetime.now() + timedelta(hours=3))

    assert ok is False
    assert req.status == "pending_review"
    assert _usuario(db_session, "99580037") is None
    assert listo == []


def test_apta_sin_nip_en_el_sii_queda_por_revisar_con_nota(
    db_session, make_cohort, sii, listo,
):
    req, _ = _solicitud_apta(db_session, make_cohort, sii, "99580038", nip=None)

    chk = _svc().check(db_session, req.id)

    assert chk.status == "apt"
    assert req.status == "pending_review"
    assert req.review_note == _NOTA_SIN_NIP
    assert _usuario(db_session, "99580038") is None
    assert listo == []


def test_si_el_sii_no_responde_al_pedir_el_nip_no_deja_nota(
    db_session, make_cohort, sii, listo,
):
    """Transitorio: sin nota, para que el barrido lo vuelva a intentar."""
    req, _ = _solicitud_apta(db_session, make_cohort, sii, "99580039")
    sii.nip_caido("99580039")

    _svc().check(db_session, req.id)

    assert req.status == "pending_review"
    assert req.review_note is None
    assert _usuario(db_session, "99580039") is None


def test_un_nip_del_sii_con_otro_formato_no_crea_cuenta_ni_se_filtra(
    db_session, make_cohort, sii, listo, caplog,
):
    req, _ = _solicitud_apta(db_session, make_cohort, sii, "99580040", nip="12AB")

    with caplog.at_level("DEBUG"):
        _svc().check(db_session, req.id)

    assert req.status == "pending_review"
    assert "4 dígitos" in req.review_note and "12AB" not in req.review_note
    assert _usuario(db_session, "99580040") is None
    assert "12AB" not in caplog.text


def test_con_cuenta_en_otra_convocatoria_queda_por_revisar_con_el_motivo(
    db_session, make_cohort, make_process, sii, listo,
):
    user = _cuenta(db_session, "99580041")
    make_process(user, cohort=make_cohort(status="open"))
    req, _ = _solicitud_apta(db_session, make_cohort, sii, "99580041")

    _svc().check(db_session, req.id)

    assert req.status == "pending_review"
    assert req.review_note == "Esa persona ya tiene un proceso en otra convocatoria."


def test_una_falla_al_crear_la_cuenta_no_filtra_el_nip_ni_su_hash(
    db_session, make_cohort, sii, listo, monkeypatch, caplog,
):
    """Review Focus 1: el error del driver de la BD trae los parámetros del
    INSERT (el hash del NIP). Ni ese texto ni el NIP llegan al log ni al motivo."""
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    from itcj2.core.utils.security import hash_nip

    req, _ = _solicitud_apta(db_session, make_cohort, sii, "99580042", nip="1593")
    db_session.commit()
    h = hash_nip("1593")

    def _revienta(*a, **k):
        raise RuntimeError(f"INSERT core_users [parameters: ('1593', '{h}')]")

    monkeypatch.setattr(EnrollmentRequestService, "_create_account",
                        staticmethod(_revienta))

    with caplog.at_level("DEBUG"):
        chk = _svc().check(db_session, req.id)

    assert chk.status == "apt"
    assert req.status == "pending_review"
    assert "1593" not in (req.review_note or "") and h not in (req.review_note or "")
    assert req.review_note, "queda con nota para que el barrido no insista"
    assert "1593" not in caplog.text and h not in caplog.text
    assert "RuntimeError" in caplog.text


def test_auto_approve_revalida_todo(db_session, make_cohort, sii, listo):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580043")

    ok, motivo = _svc().auto_approve(db_session, req.id)
    assert ok is False and "apta" in motivo, "sin consulta vigente no se aprueba"

    _check_row(db_session, req, status="not_apt")
    assert _svc().auto_approve(db_session, req.id)[0] is False

    _check_row(db_session, req, status="apt")
    req.status = "rejected"
    db_session.flush()
    assert _svc().auto_approve(db_session, req.id)[0] is False

    assert _svc().auto_approve(db_session, 987654321)[0] is False
    assert listo == []


def test_auto_approve_fuera_del_modo_sii_no_hace_nada(
    db_session, make_cohort, seed_phase_defs, titulatec_app, sii, espia_helper,
):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580044")
    _check_row(db_session, req, status="apt")

    ok, _ = _svc().auto_approve(db_session, req.id)

    assert ok is False and req.status == "pending_review"
    assert espia_helper == []


# ---------------------------------------------------------------------------
# approve() en modo sii: SE aprueba como excepción (o con el interruptor apagado)
# ---------------------------------------------------------------------------
def test_se_aprueba_sin_cuenta_con_el_nip_del_sii_e_ignora_el_del_formulario(
    db_session, make_cohort, make_user, sii, listo,
):
    from itcj2.core.utils.security import verify_nip

    se = make_user(first_name="SERVICIOS", last_name="ESCOLARES")
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580050")
    sii.no_apta("99580050", nip="3579")

    ok, folio = _ers().approve(db_session, req.id, nip="1111", program_id=None,
                               actor_id=se.id)

    assert ok is True and folio
    assert req.status == "converted" and req.reviewed_by_id == se.id
    user = _usuario(db_session, "99580050")
    assert verify_nip("3579", user.password_hash)
    assert not verify_nip("1111", user.password_hash)
    assert user.must_change_password is False
    ev, = _eventos(db_session, req.converted_process_id)
    assert ev.payload["nip_source"] == "sii" and "auto" not in ev.payload
    assert ev.payload["approved_by_id"] == se.id
    assert listo == [("send_enrollment_approved", {"nip": None, "reassigned": False,
                                                   "nip_source": "sii"})]


@pytest.mark.parametrize("falla", ["sin_nip", "caido"])
def test_se_no_puede_aprobar_sin_cuenta_si_el_sii_no_da_el_nip(
    db_session, make_cohort, make_user, sii, listo, falla,
):
    se = make_user()
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580051")
    if falla == "sin_nip":
        sii.alumno("99580051", nip=None)
    else:
        sii.alumno("99580051")
        sii.nip_caido("99580051")

    ok, motivo = _ers().approve(db_session, req.id, nip="", program_id=None, actor_id=se.id)

    assert (ok, motivo) == (False, "No se pudo obtener el NIP del SII.")
    assert req.status == "pending_review" and req.reviewed_by_id is None
    assert _usuario(db_session, "99580051") is None
    assert listo == []


def test_se_aprueba_con_cuenta_en_modo_sii_como_siempre(
    db_session, make_cohort, make_user, sii, listo,
):
    se = make_user()
    _cuenta(db_session, "99580052")
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580052")

    ok, detalle = _ers().approve(db_session, req.id, nip="", program_id=None,
                                 actor_id=se.id)

    assert (ok, detalle) == (True, "")
    assert req.status == "approved" and req.reviewed_by_id == se.id
    assert [n for n, _ in listo] == ["send_verify_enrollment"]


# ---------------------------------------------------------------------------
# sweep(): barrido periódico (acotado a una convocatoria: la BD de dev tiene
# solicitudes reales que el barrido global también vería)
# ---------------------------------------------------------------------------
def test_el_barrido_fuera_del_modo_sii_no_hace_nada(db_session, make_cohort, sii):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580060")
    sii.alumno("99580060")

    assert _svc().sweep(db_session, cohort_id=cohort.id) == {
        "checked": 0, "approved": 0, "retried": 0}
    assert _checks(db_session, req) == []


def test_el_barrido_consulta_reintenta_y_aprueba_lo_que_toca(
    db_session, make_cohort, sii, listo, monkeypatch,
):
    monkeypatch.setattr(_svc(), "delay_hours", staticmethod(lambda: 2))
    cohort = make_cohort(status="open")
    hace = datetime.now() - timedelta(hours=3)

    sin_consulta = _make_req(db_session, cohort, control="99580061")
    sii.no_apta("99580061")
    con_error = _make_req(db_session, cohort, control="99580062")
    sii.no_apta("99580062")
    _check_row(db_session, con_error, status="error", attempt=2, retryable=True)
    colgada = _make_req(db_session, cohort, control="99580063")
    sii.no_apta("99580063")
    _check_row(db_session, colgada, status="pending", started_at=hace)
    vencida = _make_req(db_session, cohort, control="99580064")
    sii.alumno("99580064")
    _check_row(db_session, vencida, status="apt", finished_at=hace)

    # Lo que NO se toca:
    en_ventana = _make_req(db_session, cohort, control="99580065")
    _check_row(db_session, en_ventana, status="apt")
    con_nota = _make_req(db_session, cohort, control="99580066",
                         review_note="El SII no devolvió NIP.")
    _check_row(db_session, con_nota, status="apt", finished_at=hace)
    en_tope = _make_req(db_session, cohort, control="99580067")
    _check_row(db_session, en_tope, status="error", attempt=5, retryable=True)
    no_apta = _make_req(db_session, cohort, control="99580068")
    _check_row(db_session, no_apta, status="not_apt")
    resuelta = _make_req(db_session, cohort, control="99580069", status="rejected")
    en_curso = _make_req(db_session, cohort, control="99580070")
    _check_row(db_session, en_curso, status="pending")
    # Spec §3.4: un error de configuración (reglas, consulta) no se reintenta.
    de_config = _make_req(db_session, cohort, control="99580078")
    sii.no_apta("99580078")
    _check_row(db_session, de_config, status="error", attempt=1, retryable=False)
    intactas = {r.id: r.last_check_id
                for r in (en_ventana, con_nota, en_tope, no_apta, resuelta, en_curso,
                          de_config)}

    out = _svc().sweep(db_session, cohort_id=cohort.id)

    assert out == {"checked": 1, "retried": 2, "approved": 1}
    assert [c.attempt for c in _checks(db_session, sin_consulta)] == [1]
    assert _svc().latest_check(db_session, con_error).attempt == 3
    assert _svc().latest_check(db_session, colgada).attempt == 2
    assert vencida.status == "converted"
    for r in (en_ventana, con_nota, en_tope, no_apta, resuelta, en_curso, de_config):
        db_session.refresh(r)
        assert r.last_check_id == intactas[r.id], r.control_number
        assert r.status in ("pending_review", "rejected")


def test_el_barrido_no_aprueba_con_la_convocatoria_cerrada_o_el_interruptor_apagado(
    db_session, make_cohort, sii, listo,
):
    hace = datetime.now() - timedelta(hours=1)
    cerrada = make_cohort(status="closed")
    apagada = make_cohort(status="open")
    apagada.sii_auto_approve = False
    for cohort, control in ((cerrada, "99580071"), (apagada, "99580072")):
        req = _make_req(db_session, cohort, control=control)
        sii.alumno(control)
        _check_row(db_session, req, status="apt", finished_at=hace)

        assert _svc().sweep(db_session, cohort_id=cohort.id)["approved"] == 0
        assert req.status == "pending_review"
    assert listo == []


def test_la_aprobacion_inmediata_de_una_consulta_del_barrido_cuenta(
    db_session, make_cohort, sii, listo,
):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580073")
    sii.alumno("99580073")

    out = _svc().sweep(db_session, cohort_id=cohort.id)

    assert out == {"checked": 1, "retried": 0, "approved": 1}
    assert req.status == "converted"


def test_una_solicitud_que_revienta_no_detiene_el_barrido(
    db_session, make_cohort, sii, modo_sii, monkeypatch, caplog,
):
    cohort = make_cohort(status="open")
    cohort.sii_auto_approve = False
    mala = _make_req(db_session, cohort, control="99580074")
    buena = _make_req(db_session, cohort, control="99580075")
    sii.no_apta("99580074")
    sii.no_apta("99580075")
    db_session.commit()
    check_real = _svc().check

    def _check(db, req_id, **kw):
        if req_id == mala.id:
            raise RuntimeError("PWD=secreto")
        return check_real(db, req_id, **kw)

    monkeypatch.setattr(_svc(), "check", staticmethod(_check))

    with caplog.at_level("WARNING"):
        out = _svc().sweep(db_session, cohort_id=cohort.id)

    assert out["checked"] == 1
    assert _checks(db_session, buena) and not _checks(db_session, mala)
    assert "RuntimeError" in caplog.text and "secreto" not in caplog.text


def test_el_barrido_respeta_su_presupuesto_de_tiempo(db_session, make_cohort, sii, modo_sii):
    cohort = make_cohort(status="open")
    for control in ("99580076", "99580077"):
        _make_req(db_session, cohort, control=control)
        sii.no_apta(control)

    out = _svc().sweep(db_session, cohort_id=cohort.id, max_seconds=0)

    assert out == {"checked": 0, "approved": 0, "retried": 0}


# ---------------------------------------------------------------------------
# Un solo núcleo de aprobación: `approve()` (SE) y la aprobación automática
# (hallazgo I3 de la revisión: una guarda nueva de `approve()` tiene que
# alcanzar también a la ruta desatendida)
# ---------------------------------------------------------------------------
def test_approve_y_la_aprobacion_automatica_comparten_el_nucleo(
    db_session, make_cohort, make_user, sii, listo, monkeypatch,
):
    llamadas = []

    def _nucleo(db, req, cohort, **kw):
        llamadas.append((req.id, cohort.id, kw))
        return False, "Guarda nueva del núcleo.", None

    monkeypatch.setattr(_ers(), "_approve_locked", staticmethod(_nucleo))
    se = make_user()
    cohort = make_cohort(status="open")
    por_se = _make_req(db_session, cohort, control="99580090")
    sola, _ = _solicitud_apta(db_session, make_cohort, sii, "99580091", cohort=cohort)

    assert _ers().approve(db_session, por_se.id, nip="", program_id=None,
                          actor_id=se.id) == (False, "Guarda nueva del núcleo.")
    _svc().check(db_session, sola.id)

    assert sola.status == "pending_review"
    assert sola.review_note == "Guarda nueva del núcleo."
    (id_se, _c1, kw_se), (id_auto, _c2, kw_auto) = llamadas
    assert (id_se, kw_se["actor_id"]) == (por_se.id, se.id)
    assert (id_auto, kw_auto["actor_id"]) == (sola.id, None)
    assert kw_auto["event_extra"]["auto"] is True
    assert listo == []


def test_la_aprobacion_automatica_no_repite_la_logica_de_approve():
    import inspect

    cuerpo = inspect.getsource(_svc().auto_approve)
    for copia in ("_issue_link_for_account", "_create_account_with_sii_nip",
                  "CONTROL_NUMBER_RE", "accepts_enrollment_followup", "fetch_sii_nip",
                  "_mail_access", "_mail_activation"):
        assert copia not in cuerpo, copia
    assert "_approve_locked(" in cuerpo
    assert "_cohort_gate(db, req)" in cuerpo
