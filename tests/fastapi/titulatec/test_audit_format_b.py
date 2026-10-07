"""Bitácora (Task 6): el Formato B deja rastro de guardado, envío y dictamen.

Los valores personales (domicilio, teléfonos) ya los guarda la red ORM como
`data.*`; la acción explícita lleva solo el paso y los NOMBRES de lo que cambió.
"""
from __future__ import annotations

import pytest

from itcj2.apps.titulatec.models.audit_log import TitulatecAuditLog
from itcj2.apps.titulatec.services.format_b_service import FormatBService


def _acciones(db, action):
    db.flush()
    return (db.query(TitulatecAuditLog)
            .filter_by(source="action", action=action)
            .order_by(TitulatecAuditLog.id).all())


@pytest.fixture()
def escenario(db_session, seed_phase_defs, make_student, make_process, monkeypatch):
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    # Corte a T-soft levantado (mecanismo de reversión documentado): sin esto la
    # fase 3 ya no se ejecuta ni se dictamina en esta app.
    monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: 9))
    seed_phase_defs()
    alumno = make_student()
    proc = make_process(alumno, current_phase=3)
    fb = FormatBService.get_or_create(db_session, proc)
    return {"alumno": alumno, "proc": proc, "fb": fb}


def test_guardar_paso_registra_paso_y_campos_cambiados(db_session, escenario):
    fb, proc = escenario["fb"], escenario["proc"]
    FormatBService.save_step(db_session, fb, 3, {"project_name": "Proyecto X"})

    fila = _acciones(db_session, "format_b.step_saved")[0]
    assert fila.process_id == proc.id
    assert fila.payload["step"] == 3
    assert fila.payload["changed_fields"] == ["project_name"]
    assert "Proyecto X" not in str(fila.payload)  # el valor lo guarda la red ORM
    assert fila.payload["status_reset"] is False


def test_guardar_paso_tras_rechazo_marca_que_volvio_a_borrador(db_session, escenario):
    fb = escenario["fb"]
    fb.status = "rejected"
    db_session.flush()
    FormatBService.save_step(db_session, fb, 3, {"project_name": "Otro"})
    fila = _acciones(db_session, "format_b.step_saved")[0]
    assert fila.payload["status_reset"] is True


def test_enviar_registra_la_fase(db_session, escenario):
    FormatBService.submit(db_session, escenario["fb"], escenario["proc"])
    fila = _acciones(db_session, "format_b.submitted")[0]
    assert fila.process_id == escenario["proc"].id
    assert fila.payload["phase_number"] == 3


def test_dictamen_registra_estado_y_nota_en_reason(db_session, escenario, make_user):
    revisor = make_user(first_name="REVISOR")
    FormatBService.review(db_session, escenario["fb"], escenario["proc"],
                          status="rejected", note="Falta el nombre del proyecto",
                          reviewer_id=revisor.id)
    fila = _acciones(db_session, "format_b.reviewed")[0]
    assert fila.payload == {"status": "rejected"}
    assert fila.reason == "Falta el nombre del proyecto"
    assert fila.actor_id == revisor.id


def test_dictamen_fuera_de_fase_no_deja_fila(db_session, escenario, make_user):
    """La guarda de fase truena ANTES de registrar: nada de «aprobado» fantasma."""
    escenario["proc"].current_phase = 1
    db_session.flush()
    with pytest.raises(Exception):
        FormatBService.review(db_session, escenario["fb"], escenario["proc"],
                              status="approved", note=None,
                              reviewer_id=make_user().id)
    assert _acciones(db_session, "format_b.reviewed") == []


def test_guardar_paso_sin_cambios_no_deja_fila(db_session, escenario):
    fb = escenario["fb"]
    FormatBService.save_step(db_session, fb, 3, {"project_name": "Mismo"})
    FormatBService.save_step(db_session, fb, 3, {"project_name": "Mismo"})
    assert len(_acciones(db_session, "format_b.step_saved")) == 1
