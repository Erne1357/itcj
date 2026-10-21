"""Bitácora (Task 6): el Formato B deja rastro de guardado, envío y dictamen.

Los valores personales (domicilio, teléfonos) ya los guarda la red ORM como
`data.*`; la acción explícita lleva solo el paso y los NOMBRES de lo que cambió.

Fase 3 (2026-10-21): `save_step` valida y ya no regresa `rejected` a `draft`
(sin `status_reset`); el dictamen pasa por `FormatBService.approve`/`.reject`
(se retiró `review`) y `format_b.reviewed` lleva resultado, ronda y campos.
"""
from __future__ import annotations

import pytest

from itcj2.apps.titulatec.models.audit_log import TitulatecAuditLog
from itcj2.apps.titulatec.services.format_b_service import FormatBService
from tests.fastapi.titulatec.conftest import audit_query

# La bitácora de dev ya trae filas reales: solo las de ESTA prueba (`id > marca`).
pytestmark = pytest.mark.usefixtures("audit_mark")


def _acciones(db, action):
    db.flush()
    return (audit_query(db)
            .filter_by(source="action", action=action)
            .order_by(TitulatecAuditLog.id).all())


@pytest.fixture()
def escenario(db_session, seed_phase_defs, make_student, make_process, make_modality,
              monkeypatch):
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    # Corte a T-soft levantado (mecanismo de reversión documentado): sin esto la
    # fase 3 ya no se ejecuta ni se dictamina en esta app.
    monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: 9))
    seed_phase_defs()
    alumno = make_student()
    proc = make_process(alumno, current_phase=3)
    fb = FormatBService.get_or_create(db_session, proc)
    return {"alumno": alumno, "proc": proc, "fb": fb, "modalidad": make_modality()}


def _enviar(db, escenario):
    """Llena los 3 pasos con datos válidos y envía."""
    fb, proc = escenario["fb"], escenario["proc"]
    FormatBService.save_step(db, fb, 1, {
        "gender": "male", "age": "25", "mobile_phone": "6561234567",
        "postal_code": "32000", "neighborhood": "Centro", "street": "Calle Uno",
        "ext_number": "10"})
    FormatBService.save_step(db, fb, 2, {
        "modality_id": str(escenario["modalidad"].id), "study_plan": "ISIC-2010-224",
        "admission_date": "2018-08", "graduation_date": "2023-06"})
    FormatBService.save_step(db, fb, 3, {"project_name": "Proyecto de prueba X"})
    FormatBService.submit(db, fb, proc)


def test_guardar_paso_registra_paso_y_campos_cambiados(db_session, escenario):
    fb, proc = escenario["fb"], escenario["proc"]
    FormatBService.save_step(db_session, fb, 3, {"project_name": "Proyecto X"})

    fila = _acciones(db_session, "format_b.step_saved")[0]
    assert fila.process_id == proc.id
    assert fila.payload["step"] == 3
    assert fila.payload["changed_fields"] == ["project_name"]
    assert "Proyecto X" not in str(fila.payload)  # el valor lo guarda la red ORM
    assert "status_reset" not in fila.payload     # ya no hay regreso a borrador


def test_guardar_paso_tras_rechazo_conserva_el_rechazo(db_session, escenario):
    fb = escenario["fb"]
    fb.status = "rejected"
    db_session.flush()
    FormatBService.save_step(db_session, fb, 3, {"project_name": "Otro proyecto"})
    fila = _acciones(db_session, "format_b.step_saved")[0]
    assert fila.payload["changed_fields"] == ["project_name"]
    assert fb.status == "rejected"


def test_un_paso_invalido_no_deja_fila(db_session, escenario):
    from itcj2.apps.titulatec.services.format_b_validation import FormatBValidationError
    with pytest.raises(FormatBValidationError):
        FormatBService.save_step(db_session, escenario["fb"], 3, {"project_name": "Corto"})
    assert _acciones(db_session, "format_b.step_saved") == []


def test_enviar_registra_la_fase_y_la_ronda(db_session, escenario):
    _enviar(db_session, escenario)
    fila = _acciones(db_session, "format_b.submitted")[0]
    assert fila.process_id == escenario["proc"].id
    assert fila.payload["phase_number"] == 3
    assert fila.payload["round"] == 1


def test_observar_registra_resultado_campos_y_nota_en_reason(db_session, escenario,
                                                             make_user):
    revisor = make_user(first_name="REVISOR")
    _enviar(db_session, escenario)
    FormatBService.reject(db_session, escenario["proc"], revisor.id,
                          general_note="Falta el nombre del proyecto",
                          field_notes={"project_name": "Incompleto"})
    fila = _acciones(db_session, "format_b.reviewed")[0]
    assert fila.payload == {"status": "rejected", "round": 1, "fields": ["project_name"]}
    assert fila.reason == "Falta el nombre del proyecto"
    assert fila.actor_id == revisor.id
    assert "Proyecto de prueba X" not in str(fila.payload)   # sin valores personales


def test_aprobar_registra_resultado_y_ronda(db_session, escenario, make_user):
    revisor = make_user(first_name="REVISOR")
    _enviar(db_session, escenario)
    FormatBService.approve(db_session, escenario["proc"], revisor.id)
    fila = _acciones(db_session, "format_b.reviewed")[0]
    assert fila.payload == {"status": "approved", "round": 1}
    assert fila.reason is None
    assert fila.actor_id == revisor.id


def test_dictamen_fuera_de_fase_no_deja_fila(db_session, escenario, make_user):
    """La guarda de fase truena ANTES de registrar: nada de «aprobado» fantasma."""
    _enviar(db_session, escenario)
    escenario["proc"].current_phase = 1
    db_session.commit()
    with pytest.raises(ValueError):
        FormatBService.approve(db_session, escenario["proc"], make_user().id)
    assert _acciones(db_session, "format_b.reviewed") == []


def test_guardar_paso_sin_cambios_no_deja_fila(db_session, escenario):
    fb = escenario["fb"]
    FormatBService.save_step(db_session, fb, 3, {"project_name": "Mismo proyecto"})
    FormatBService.save_step(db_session, fb, 3, {"project_name": "Mismo proyecto"})
    assert len(_acciones(db_session, "format_b.step_saved")) == 1
