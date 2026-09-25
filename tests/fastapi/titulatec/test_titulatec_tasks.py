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
