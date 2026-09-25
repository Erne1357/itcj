"""Tareas celery del SII (spec 2026-09-25 §3.4, Tarea 4).

Sin broker ni worker: se llama el cuerpo de la tarea (`task.run`, que en una
tarea `bind=True` ya trae `self`) con `EligibilityService` parcheado, y el
`retry` de la tarea se sustituye por un registro. `SessionLocal` apunta a la
sesión del test (`patched_session_local`).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import itcj2.tasks.titulatec_tasks as tasks
from itcj2.apps.titulatec.services.eligibility_service import EligibilityService


class _Retry(Exception):
    pass


@pytest.fixture()
def reintentos(monkeypatch):
    """`self.retry(...)` registra sus argumentos y corta como lo hace celery."""
    llamadas = []

    def _retry(*args, **kwargs):
        llamadas.append(kwargs)
        raise _Retry()

    monkeypatch.setattr(tasks.sii_check_request, "retry", _retry)
    return llamadas


@pytest.fixture()
def consulta(monkeypatch, patched_session_local):
    """`EligibilityService.check` devuelve lo que diga la prueba y anota cómo
    se llamó."""
    estado = {"resultado": None, "llamadas": []}

    def _check(db, req_id, *, attempt=1, force=False):
        estado["llamadas"].append({"db": db, "req_id": req_id, "attempt": attempt,
                                   "force": force})
        return estado["resultado"]

    monkeypatch.setattr(EligibilityService, "check", staticmethod(_check))
    monkeypatch.setattr(EligibilityService, "max_attempts", staticmethod(lambda: 3))
    return estado


def _chk(status, attempt=1):
    return SimpleNamespace(id=77, status=status, attempt=attempt)


def test_las_tareas_estan_registradas_y_el_worker_las_carga():
    from itcj2.celery_app import celery_app

    assert "itcj2.tasks.titulatec_tasks" in celery_app.conf.include
    assert "itcj2.tasks.titulatec_tasks.sii_check_request" in celery_app.tasks


def test_consulta_apta_no_reintenta(consulta, reintentos, db_session):
    consulta["resultado"] = _chk("apt")

    out = tasks.sii_check_request.run(req_id=5)

    assert out == {"req_id": 5, "check_id": 77, "status": "apt", "attempt": 1}
    assert reintentos == []
    llamada, = consulta["llamadas"]
    assert llamada["req_id"] == 5 and llamada["attempt"] == 1 and llamada["force"] is False
    assert llamada["db"].get_bind() is db_session.get_bind(), "usa SessionLocal()"


def test_error_reintenta_con_el_siguiente_intento_y_espera_creciente(consulta, reintentos):
    consulta["resultado"] = _chk("error", attempt=1)
    with pytest.raises(_Retry):
        tasks.sii_check_request.run(req_id=5)

    consulta["resultado"] = _chk("error", attempt=2)
    with pytest.raises(_Retry):
        tasks.sii_check_request.run(req_id=5, attempt=2)

    primero, segundo = reintentos
    assert primero["kwargs"] == {"req_id": 5, "attempt": 2, "force": False}
    assert segundo["kwargs"] == {"req_id": 5, "attempt": 3, "force": False}
    assert 0 < primero["countdown"] < segundo["countdown"] <= 3600


def test_en_el_tope_de_intentos_ya_no_reintenta(consulta, reintentos):
    consulta["resultado"] = _chk("error", attempt=3)

    out = tasks.sii_check_request.run(req_id=5, attempt=3)

    assert out["status"] == "error"
    assert reintentos == []


def test_un_reintento_forzado_no_arrastra_force(consulta, reintentos):
    """«Reintentar consulta» fuerza SOLO la primera; los reintentos por error
    ya siguen la cuenta normal (y respetan el tope)."""
    consulta["resultado"] = _chk("error", attempt=1)

    with pytest.raises(_Retry):
        tasks.sii_check_request.run(req_id=5, force=True)

    assert consulta["llamadas"][0]["force"] is True
    assert reintentos[0]["kwargs"]["force"] is False


def test_sin_consulta_no_hace_nada(consulta, reintentos):
    consulta["resultado"] = None

    out = tasks.sii_check_request.run(req_id=5)

    assert out == {"req_id": 5, "skipped": True}
    assert reintentos == []


# ---------------------------------------------------------------------------
# sii_sweep (periódica) y su alta en la BD
# ---------------------------------------------------------------------------
def test_el_barrido_esta_registrado_y_catalogado():
    from itcj2.celery_app import celery_app

    assert "itcj2.tasks.titulatec_tasks.sii_sweep" in celery_app.tasks
    definicion, = tasks.TASK_DEFINITIONS
    assert definicion["task_name"] == "itcj2.tasks.titulatec_tasks.sii_sweep"
    assert definicion["app_name"] == "titulatec"


def test_el_barrido_corre_con_su_sesion_y_su_presupuesto(monkeypatch, patched_session_local,
                                                         db_session):
    llamadas = []

    def _sweep(db, *, now=None, cohort_id=None, max_seconds=None):
        llamadas.append((db.get_bind() is db_session.get_bind(), cohort_id, max_seconds))
        return {"checked": 2, "approved": 1, "retried": 0}

    monkeypatch.setattr(EligibilityService, "sweep", staticmethod(_sweep))

    out = tasks.sii_sweep.run()

    assert out == {"checked": 2, "approved": 1, "retried": 0}
    (misma_sesion, cohort_id, presupuesto), = llamadas
    assert misma_sesion and cohort_id is None
    assert 0 < presupuesto < tasks.sii_sweep.soft_time_limit, (
        "el presupuesto termina antes de que celery corte la tarea")


def test_la_periodica_se_da_de_alta_con_los_seeders_de_titulatec():
    """El scheduler lee `core_periodic_tasks` (DatabaseScheduler): el alta va
    por DML plegado a `SEED_FILES` (`init-titulatec`), antes del 15 que debe
    seguir siendo el último."""
    from itcj2.cli.titulatec import SEED_FILES

    nombre = "sii_2026_09/16_insert_sii_sweep_task.sql"
    assert nombre in SEED_FILES
    assert SEED_FILES.index(nombre) < SEED_FILES.index("15_grant_admin_all_perms.sql")
    assert SEED_FILES[-1] == "15_grant_admin_all_perms.sql"


# ---------------------------------------------------------------------------
# CLI `titulatec sii-sweep`
# ---------------------------------------------------------------------------
def _cli(*args):
    from click.testing import CliRunner
    from itcj2.cli.titulatec import titulatec_cli

    return CliRunner().invoke(titulatec_cli, list(args))


def _modo(monkeypatch, mode):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    monkeypatch.setattr(EnrollmentRequestService, "reviewer_mode",
                        staticmethod(lambda: mode))


def test_cli_sii_sweep_imprime_lo_que_hizo(monkeypatch, patched_session_local):
    _modo(monkeypatch, "sii")
    llamadas = []

    def _sweep(db, *, now=None, cohort_id=None, max_seconds=None):
        llamadas.append(cohort_id)
        return {"checked": 3, "approved": 2, "retried": 1}

    monkeypatch.setattr(EligibilityService, "sweep", staticmethod(_sweep))

    res = _cli("sii-sweep", "--cohort", "12")

    assert res.exit_code == 0, res.output
    assert llamadas == [12]
    assert "consultadas: 3" in res.output.lower()
    assert "reintentadas: 1" in res.output.lower()
    assert "aprobadas: 2" in res.output.lower()


def test_cli_sii_sweep_fuera_del_modo_sii_avisa_y_no_barre(monkeypatch, patched_session_local):
    _modo(monkeypatch, "school_services")
    monkeypatch.setattr(EligibilityService, "sweep",
                        staticmethod(lambda *a, **k: pytest.fail("no debió barrer")))

    res = _cli("sii-sweep")

    assert res.exit_code == 0, res.output
    assert "school_services" in res.output
