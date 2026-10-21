"""Motor del Formato B (spec 2026-10-21 fase 3 §5.1, §5.4, §6, §7, §8.5, Task 3).

`FormatBService` es la ÚNICA puerta que mueve el Formato B y la fase 3: guarda
pasos validados (sin tocar `rejected`), envía con validación total y congelado,
dictamina acoplado a `PhaseService` en una transacción y corrige el registro.
Del lado del motor, `approve_phase`/`reject_phase` de la fase `format_b` exigen
que el Formato B ya esté dictaminado en la sesión: no hay otra puerta.

Todo test que opera la fase 3 levanta el corte EXPLÍCITO (Ruling R7): el
contenedor de dev trae 10 y CI/producción 3; nada depende del entorno. Las
pruebas del corte en 3 lo fijan también explícito.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from itcj2.apps.titulatec.services.format_b_service import (
    ALREADY_SUBMITTED_MSG, EDIT_LOCKED_MSG, NEED_OBSERVATION_MSG, FormatBService,
)
from itcj2.apps.titulatec.services.format_b_validation import FormatBValidationError
from itcj2.apps.titulatec.services.phase_service import PhaseService
from tests.fastapi.titulatec.conftest import audit_query

pytestmark = pytest.mark.usefixtures("audit_mark")


# ---------------------------------------------------------------------------
# Escenario
# ---------------------------------------------------------------------------
@pytest.fixture()
def corte(monkeypatch):
    """Fija el corte a T-soft (R7). `corte(9)` lo apaga; `corte(3)` es prod."""
    def _fijar(fase):
        monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: fase))
    return _fijar


@pytest.fixture()
def revisor(make_user):
    return make_user(first_name="LUISA", last_name="REVISORA")


@pytest.fixture()
def esc(db_session, seed_phase_defs, make_program, make_modality, make_student,
        make_process, corte):
    """Alumno en la fase 3 con carrera de licenciatura, sin modalidad en el
    proceso (como deja la inscripción pública, D8), y dos modalidades del
    catálogo: una con sinodales y otra que los salta (EGEL)."""
    def _build(*, current_phase=3, status="active", modality=None, cut=9):
        corte(cut)
        seed_phase_defs()
        programa = make_program("Ingenieria Ficticia Formato B")
        residencias = make_modality(name="Residencias de prueba", requires_synodals=True)
        egel = make_modality(name="EGEL de prueba", requires_synodals=False,
                             skips_phases=[4, 5])
        alumno = make_student(first_name="ANA", last_name="PEREZ")
        proc = make_process(alumno, program=programa, current_phase=current_phase,
                            status=status, modality=modality)
        return SimpleNamespace(alumno=alumno, proc=proc, programa=programa,
                               residencias=residencias, egel=egel)
    return _build


def _paso1(**cambios):
    datos = {"gender": "female", "age": "24", "mobile_phone": "656 123 4567",
             "phone": "", "postal_code": "32000", "neighborhood": "Centro",
             "street": "Av. Juarez", "ext_number": "123", "int_number": ""}
    datos.update(cambios)
    return datos


def _paso2(modalidad, **cambios):
    datos = {"modality_id": str(modalidad.id), "study_plan": "isic-2010-224",
             "admission_date": "2018-08", "graduation_date": "2023-06"}
    datos.update(cambios)
    return datos


def _paso3(**cambios):
    datos = {"project_name": "Sistema de control de inventarios"}
    datos.update(cambios)
    return datos


def _llenar(db, fb, modalidad):
    FormatBService.save_step(db, fb, 1, _paso1())
    FormatBService.save_step(db, fb, 2, _paso2(modalidad))
    FormatBService.save_step(db, fb, 3, _paso3())


def _enviado(db, e, modalidad=None):
    fb = FormatBService.get_or_create(db, e.proc)
    _llenar(db, fb, modalidad or e.residencias)
    FormatBService.submit(db, fb, e.proc)
    return fb


def _fases(db, pid):
    from itcj2.apps.titulatec.models import ProcessPhase
    return {p.phase_number: p.status
            for p in db.query(ProcessPhase).filter_by(process_id=pid).all()}


def _eventos(db, pid, tipo):
    from itcj2.apps.titulatec.models import ProcessEvent
    return (db.query(ProcessEvent).filter_by(process_id=pid, event_type=tipo)
            .order_by(ProcessEvent.id).all())


def _acciones(db, action):
    from itcj2.apps.titulatec.models.audit_log import TitulatecAuditLog
    db.flush()
    return (audit_query(db).filter_by(source="action", action=action)
            .order_by(TitulatecAuditLog.id).all())


# ---------------------------------------------------------------------------
# validation_ctx y precargas
# ---------------------------------------------------------------------------
class TestContextoYPrecarga:
    def test_el_contexto_sale_del_catalogo(self, db_session, esc, make_modality):
        e = esc()
        inactiva = make_modality(name="Modalidad retirada")
        inactiva.is_active = False
        db_session.flush()
        fb = FormatBService.get_or_create(db_session, e.proc)

        ctx = FormatBService.validation_ctx(db_session, fb)
        assert e.residencias.id in ctx.modality_ids and e.egel.id in ctx.modality_ids
        assert inactiva.id not in ctx.modality_ids
        assert ctx.requires_project is None          # sin modalidad: se exige

        fb.modality_id = e.egel.id
        db_session.flush()
        assert FormatBService.validation_ctx(db_session, fb).requires_project is False
        fb.modality_id = e.residencias.id
        db_session.flush()
        assert FormatBService.validation_ctx(db_session, fb).requires_project is True

    def test_precarga_telefono_reticula_y_modalidad(self, db_session, esc):
        from itcj2.core.models.student_profile import StudentProfile
        e = esc()
        e.proc.modality_id = e.residencias.id
        db_session.add(StudentProfile(user_id=e.alumno.id, phone="+52 (656) 123-4567",
                                      reticula="  isic-2010-224 "))
        db_session.flush()

        fb = FormatBService.get_or_create(db_session, e.proc)

        assert fb.mobile_phone == "6561234567"
        assert fb.study_plan == "ISIC-2010-224"
        assert fb.modality_id == e.residencias.id
        assert fb.program_id is None, "la carrera ya no se precarga: se congela al enviar"
        assert fb.status == "draft"

    def test_un_telefono_invalido_del_perfil_no_se_precarga(self, db_session, esc):
        from itcj2.core.models.student_profile import StudentProfile
        e = esc()
        db_session.add(StudentProfile(user_id=e.alumno.id, phone="656-1234"))
        db_session.flush()

        fb = FormatBService.get_or_create(db_session, e.proc)

        assert fb.mobile_phone is None
        assert fb.study_plan is None and fb.modality_id is None

    def test_to_ctx_lleva_la_modalidad(self, db_session, esc):
        e = esc(modality=None)
        fb = FormatBService.get_or_create(db_session, e.proc)
        fb.modality_id = e.egel.id
        assert FormatBService.to_ctx(fb)["modality_id"] == e.egel.id

    def test_lo_precargado_no_cuenta_como_paso_hecho(self, db_session, esc):
        from itcj2.core.models.student_profile import StudentProfile
        e = esc()
        e.proc.modality_id = e.residencias.id
        db_session.add(StudentProfile(user_id=e.alumno.id, phone="6561234567",
                                      reticula="ISIC-2010-224"))
        db_session.flush()
        fb = FormatBService.get_or_create(db_session, e.proc)

        prog = FormatBService.progress(fb)
        assert [s["done"] for s in prog["steps"]] == [False, False, False]
        assert prog["step"] == 1

    def test_sin_proyecto_requerido_el_paso_3_cuenta_al_terminar_el_2(self, db_session, esc):
        e = esc()
        fb = FormatBService.get_or_create(db_session, e.proc)
        FormatBService.save_step(db_session, fb, 1, _paso1())
        FormatBService.save_step(db_session, fb, 2, _paso2(e.egel))
        FormatBService.save_step(db_session, fb, 3, {})

        prog = FormatBService.progress(fb)
        assert [s["done"] for s in prog["steps"]] == [True, True, True]


# ---------------------------------------------------------------------------
# save_step
# ---------------------------------------------------------------------------
class TestGuardarPaso:
    def test_un_paso_invalido_no_escribe_nada_y_lanza_con_los_errores(self, db_session, esc):
        e = esc()
        fb = FormatBService.get_or_create(db_session, e.proc)

        with pytest.raises(FormatBValidationError) as exc:
            FormatBService.save_step(db_session, fb, 1,
                                     _paso1(age="17", mobile_phone="123", street="Av. Nueva"))

        assert exc.value.step == 1
        assert set(exc.value.errors) == {"age", "mobile_phone"}
        db_session.expire_all()
        fb = FormatBService.get_or_create(db_session, e.proc)
        assert (fb.gender, fb.age, fb.street) == (None, None, None), "no guarda NADA del paso"
        assert _acciones(db_session, "format_b.step_saved") == []

    def test_un_paso_valido_guarda_normalizado(self, db_session, esc):
        e = esc()
        fb = FormatBService.get_or_create(db_session, e.proc)

        FormatBService.save_step(db_session, fb, 1, _paso1(street="  Av.   Juarez  "))
        FormatBService.save_step(db_session, fb, 2, _paso2(e.residencias))

        assert fb.mobile_phone == "6561234567"
        assert fb.street == "Av. Juarez"
        assert fb.age == 24
        assert fb.study_plan == "ISIC-2010-224"
        assert fb.modality_id == e.residencias.id
        assert fb.admission_date.isoformat() == "2018-08-01"
        fila = _acciones(db_session, "format_b.step_saved")[0]
        assert fila.payload["step"] == 1
        assert "6561234567" not in str(fila.payload)

    @pytest.mark.parametrize("estado", ["submitted", "approved"])
    def test_un_formato_enviado_no_se_edita(self, db_session, esc, make_format_b, estado):
        e = esc()
        fb = make_format_b(e.proc, status=estado)

        with pytest.raises(ValueError) as exc:
            FormatBService.save_step(db_session, fb, 1, _paso1())

        assert str(exc.value) == EDIT_LOCKED_MSG
        assert fb.gender is None

    def test_guardar_conserva_rejected(self, db_session, esc, make_format_b):
        """P9: el primer guardado ya no regresa `rejected` a `draft`."""
        e = esc()
        fb = make_format_b(e.proc, status="rejected")

        FormatBService.save_step(db_session, fb, 1, _paso1())

        db_session.expire_all()
        assert FormatBService.get_or_create(db_session, e.proc).status == "rejected"


# ---------------------------------------------------------------------------
# submit
# ---------------------------------------------------------------------------
class TestEnviar:
    def test_envio_feliz(self, db_session, esc):
        e = esc()
        e.alumno.middle_name = "LOPEZ"
        db_session.flush()

        fb = _enviado(db_session, e)

        assert fb.status == "submitted"
        assert fb.submission_count == 1
        assert fb.submitted_at is not None
        assert _fases(db_session, e.proc.id)[3] == "in_review"
        # Congelado: lo que se dictamina es lo que quedó guardado (§6).
        assert (fb.first_name, fb.last_name, fb.middle_name) == ("ANA", "PEREZ", "LOPEZ")
        assert fb.control_number == e.alumno.control_number
        assert fb.program_id == e.programa.id
        assert fb.titulation_type == "Residencias de prueba"
        (ev,) = _eventos(db_session, e.proc.id, "format_b_submitted")
        assert ev.payload == {"round": 1} and ev.phase_number == 3
        assert ev.actor_id == e.alumno.id
        fila = _acciones(db_session, "format_b.submitted")[0]
        assert fila.payload["phase_number"] == 3 and fila.payload["round"] == 1

    def test_doble_envio_el_segundo_falla_y_la_ronda_sube_una_vez(self, db_session, esc):
        """RF1: doble clic o dos pestañas."""
        e = esc()
        fb = _enviado(db_session, e)

        with pytest.raises(ValueError) as exc:
            FormatBService.submit(db_session, fb, e.proc)

        assert str(exc.value) == ALREADY_SUBMITTED_MSG
        db_session.expire_all()
        fb = FormatBService.get_or_create(db_session, e.proc)
        assert fb.submission_count == 1
        assert len(_eventos(db_session, e.proc.id, "format_b_submitted")) == 1

    def test_borrador_viejo_invalido_lleva_al_primer_paso_con_errores(self, db_session, esc,
                                                                    make_format_b):
        """RF3: datos guardados antes de las validaciones (edad vacía, teléfono
        de 8 dígitos) no se envían."""
        e = esc()
        fb = make_format_b(e.proc, gender="male", age=None, mobile_phone="65612345",
                           modality=e.residencias, study_plan="ISIC-2010-224",
                           project_name="Proyecto viejo de prueba")

        with pytest.raises(FormatBValidationError) as exc:
            FormatBService.submit(db_session, fb, e.proc)

        assert exc.value.step == 1
        assert {"age", "mobile_phone"} <= set(exc.value.errors)
        assert fb.status == "draft" and fb.submission_count == 0
        assert _fases(db_session, e.proc.id)[3] == "in_progress"
        assert _eventos(db_session, e.proc.id, "format_b_submitted") == []

    def test_el_error_del_paso_2_lleva_al_paso_2(self, db_session, esc, make_format_b):
        e = esc()
        fb = FormatBService.get_or_create(db_session, e.proc)
        FormatBService.save_step(db_session, fb, 1, _paso1())
        FormatBService.save_step(db_session, fb, 3, _paso3())

        with pytest.raises(FormatBValidationError) as exc:
            FormatBService.submit(db_session, fb, e.proc)

        assert exc.value.step == 2
        assert "modality_id" in exc.value.errors

    def test_reenvio_tras_observaciones_es_la_ronda_2(self, db_session, esc, revisor):
        e = esc()
        fb = _enviado(db_session, e)
        primero = fb.submitted_at
        FormatBService.reject(db_session, e.proc, revisor.id, general_note=None,
                              field_notes={"postal_code": "No coincide"})
        FormatBService.save_step(db_session, fb, 1, _paso1(postal_code="32001"))

        FormatBService.submit(db_session, fb, e.proc)

        assert fb.status == "submitted" and fb.submission_count == 2
        assert fb.submitted_at >= primero
        assert fb.review_observations["fields"]["postal_code"]["note"] == "No coincide", \
            "las observaciones sobreviven al reenvío"
        rondas = [ev.payload["round"] for ev in _eventos(db_session, e.proc.id,
                                                          "format_b_submitted")]
        assert rondas == [1, 2]

    def test_sin_sinodales_el_proyecto_se_guarda_null(self, db_session, esc):
        e = esc()
        fb = FormatBService.get_or_create(db_session, e.proc)
        FormatBService.save_step(db_session, fb, 1, _paso1())
        FormatBService.save_step(db_session, fb, 3, _paso3())       # con residencias
        FormatBService.save_step(db_session, fb, 2, _paso2(e.egel))  # cambia a EGEL

        FormatBService.submit(db_session, fb, e.proc)

        assert fb.status == "submitted"
        assert fb.project_name is None
        assert fb.titulation_type == "EGEL de prueba"

    def test_fuera_de_fase_no_se_envia(self, db_session, esc, make_format_b):
        e = esc(current_phase=2)
        fb = make_format_b(e.proc)

        with pytest.raises(ValueError):
            FormatBService.submit(db_session, fb, e.proc)
        assert fb.status == "draft"


# ---------------------------------------------------------------------------
# approve
# ---------------------------------------------------------------------------
class TestAprobar:
    def test_aprobar_residencias_avanza_a_la_4_y_graba_la_modalidad(self, db_session, esc,
                                                                    revisor):
        e = esc()
        fb = _enviado(db_session, e)
        assert e.proc.modality_id is None

        out = FormatBService.approve(db_session, e.proc, revisor.id)

        assert out == {"next_phase": 4, "completed": False}
        assert fb.status == "approved"
        assert fb.approved_by_id == revisor.id and fb.approved_at is not None
        assert fb.reviewed_by_id == revisor.id and fb.reviewed_at is not None
        assert e.proc.modality_id == e.residencias.id
        assert e.proc.current_phase == 4
        fases = _fases(db_session, e.proc.id)
        assert fases[3] == "approved" and fases[4] == "in_progress"
        (ev,) = _eventos(db_session, e.proc.id, "phase_approved")
        assert ev.payload == {"format_b": {"round": 1}}
        fila = _acciones(db_session, "format_b.reviewed")[0]
        assert fila.payload["status"] == "approved"
        assert fila.actor_id == revisor.id

    def test_modalidad_sin_sinodales_salta_4_y_5(self, db_session, esc, revisor):
        """RF5: el alumno eligió EGEL en el paso 2; aprobar salta a la 6."""
        e = esc()
        _enviado(db_session, e, modalidad=e.egel)

        out = FormatBService.approve(db_session, e.proc, revisor.id)

        assert out["next_phase"] == 6
        assert e.proc.current_phase == 6
        fases = _fases(db_session, e.proc.id)
        assert (fases[4], fases[5], fases[6]) == ("skipped", "skipped", "in_progress")

    def test_aprobar_y_luego_observar_el_segundo_dice_ya_dictaminado(self, db_session, esc,
                                                                     revisor, make_user):
        """RF2: A aprueba mientras B observa."""
        e = esc()
        fb = _enviado(db_session, e)
        FormatBService.approve(db_session, e.proc, revisor.id)

        with pytest.raises(ValueError) as exc:
            FormatBService.reject(db_session, e.proc, make_user().id, general_note="Tarde",
                                  field_notes={})

        assert "ya fue dictaminado" in str(exc.value)
        assert "LUISA REVISORA" in str(exc.value)
        assert fb.status == "approved"
        assert _eventos(db_session, e.proc.id, "phase_rejected") == []

    def test_aprobar_dos_veces(self, db_session, esc, revisor):
        e = esc()
        _enviado(db_session, e)
        FormatBService.approve(db_session, e.proc, revisor.id)

        with pytest.raises(ValueError) as exc:
            FormatBService.approve(db_session, e.proc, revisor.id)
        assert "ya fue dictaminado" in str(exc.value)

    def test_un_borrador_no_se_dictamina(self, db_session, esc, make_format_b, revisor):
        e = esc()
        make_format_b(e.proc)
        with pytest.raises(ValueError):
            FormatBService.approve(db_session, e.proc, revisor.id)

    def test_proceso_pausado_falla_con_el_motor_y_no_escribe(self, db_session, esc, revisor):
        """RF4: el mensaje es el del motor y no queda nada a medias."""
        e = esc()
        fb = _enviado(db_session, e)
        e.proc.status = "on_hold"
        db_session.commit()

        with pytest.raises(ValueError) as exc:
            FormatBService.approve(db_session, e.proc, revisor.id)

        assert "ya no admite cambios de fase" in str(exc.value)
        db_session.expire_all()
        assert fb.status == "submitted" and fb.approved_by_id is None
        assert e.proc.modality_id is None and e.proc.current_phase == 3
        assert _eventos(db_session, e.proc.id, "phase_approved") == []
        assert _acciones(db_session, "format_b.reviewed") == []

    def test_si_el_motor_truena_se_revierte_todo(self, db_session, esc, revisor, monkeypatch):
        e = esc()
        fb = _enviado(db_session, e)                     # `submit` ya commiteó

        def _truena(*_a, **_k):
            raise RuntimeError("falla inesperada del motor")
        monkeypatch.setattr(PhaseService, "approve_phase", staticmethod(_truena))

        with pytest.raises(RuntimeError):
            FormatBService.approve(db_session, e.proc, revisor.id)

        assert fb.status == "submitted"
        assert e.proc.modality_id is None
        assert _acciones(db_session, "format_b.reviewed") == []


# ---------------------------------------------------------------------------
# reject
# ---------------------------------------------------------------------------
class TestObservar:
    def test_observar_regresa_al_alumno_con_campos(self, db_session, esc, revisor):
        e = esc()
        fb = _enviado(db_session, e)

        FormatBService.reject(db_session, e.proc, revisor.id,
                              general_note="Revisa tu domicilio",
                              field_notes={"street": "Falta el número de calle",
                                           "postal_code": "No coincide con la colonia",
                                           "age": "   "})

        assert fb.status == "rejected"
        assert fb.rejection_reason == "Revisa tu domicilio"
        assert fb.reviewed_by_id == revisor.id and fb.reviewed_at is not None
        obs = fb.review_observations
        assert obs["general"] == "Revisa tu domicilio"
        assert obs["reviewer_id"] == revisor.id and obs["at"]
        assert obs["fields"] == {
            "street": {"note": "Falta el número de calle", "value": "Av. Juarez"},
            "postal_code": {"note": "No coincide con la colonia", "value": "32000"},
        }, "una nota en blanco no observa el campo"
        assert e.proc.current_phase == 3
        assert _fases(db_session, e.proc.id)[3] == "rejected"
        (ev,) = _eventos(db_session, e.proc.id, "phase_rejected")
        assert ev.payload["reason"] == ("Revisa tu domicilio. "
                                        "Campos a corregir: Código postal, Calle.")
        assert ev.payload["format_b"] == {"round": 1, "fields": ["postal_code", "street"]}
        fila = _acciones(db_session, "format_b.reviewed")[0]
        assert fila.payload == {"status": "rejected", "round": 1,
                                "fields": ["postal_code", "street"]}
        assert fila.reason == "Revisa tu domicilio"

    def test_solo_nota_general(self, db_session, esc, revisor):
        e = esc()
        fb = _enviado(db_session, e)
        FormatBService.reject(db_session, e.proc, revisor.id, general_note="  Todo mal  ",
                              field_notes={})
        assert fb.review_observations["fields"] == {}
        (ev,) = _eventos(db_session, e.proc.id, "phase_rejected")
        assert ev.payload["reason"] == "Todo mal"

    def test_la_modalidad_se_observa_con_su_valor(self, db_session, esc, revisor):
        e = esc()
        fb = _enviado(db_session, e)
        FormatBService.reject(db_session, e.proc, revisor.id, general_note=None,
                              field_notes={"modality_id": "Tu caso es tesis"})
        assert fb.review_observations["fields"]["modality_id"]["value"] == str(e.residencias.id)
        (ev,) = _eventos(db_session, e.proc.id, "phase_rejected")
        assert ev.payload["reason"] == "Campos a corregir: Tipo de titulación."

    @pytest.mark.parametrize("general, campos", [
        (None, {}), ("   ", {}), ("", {"street": "  "}),
    ])
    def test_sin_observaciones_no_se_regresa(self, db_session, esc, revisor, general, campos):
        e = esc()
        fb = _enviado(db_session, e)
        with pytest.raises(ValueError) as exc:
            FormatBService.reject(db_session, e.proc, revisor.id, general_note=general,
                                  field_notes=campos)
        assert str(exc.value) == NEED_OBSERVATION_MSG
        assert fb.status == "submitted"

    @pytest.mark.parametrize("campo", ["first_name", "control_number", "program_id",
                                       "titulation_type", "status"])
    def test_campos_del_registro_no_se_observan(self, db_session, esc, revisor, campo):
        e = esc()
        fb = _enviado(db_session, e)
        with pytest.raises(ValueError):
            FormatBService.reject(db_session, e.proc, revisor.id, general_note="Mal",
                                  field_notes={campo: "Está mal"})
        assert fb.status == "submitted"
        assert _eventos(db_session, e.proc.id, "phase_rejected") == []


# ---------------------------------------------------------------------------
# Una sola puerta: el motor de fases
# ---------------------------------------------------------------------------
class TestUnaSolaPuerta:
    def test_aprobar_la_fase_3_directo_con_fb_enviado(self, db_session, esc, revisor):
        e = esc()
        fb = _enviado(db_session, e)

        with pytest.raises(ValueError) as exc:
            PhaseService.approve_phase(db_session, e.proc, 3, reviewer_id=revisor.id)

        assert str(exc.value) == PhaseService.FORMAT_B_ONLY_MSG
        assert fb.status == "submitted"
        assert _fases(db_session, e.proc.id)[3] == "in_review"

    def test_rechazar_la_fase_3_directo_con_fb_enviado(self, db_session, esc, revisor):
        e = esc()
        _enviado(db_session, e)

        with pytest.raises(ValueError) as exc:
            PhaseService.reject_phase(db_session, e.proc, 3, reviewer_id=revisor.id,
                                      reason="por la otra puerta")

        assert str(exc.value) == PhaseService.FORMAT_B_ONLY_MSG
        assert _eventos(db_session, e.proc.id, "phase_rejected") == []

    def test_aprobar_la_fase_3_sin_formato_b(self, db_session, esc, revisor):
        e = esc()
        with pytest.raises(ValueError) as exc:
            PhaseService.approve_phase(db_session, e.proc, 3, reviewer_id=revisor.id)
        assert str(exc.value) == PhaseService.FORMAT_B_ONLY_MSG

    def test_las_demas_fases_no_cambian(self, db_session, esc, revisor):
        e = esc(current_phase=4)
        out = PhaseService.approve_phase(db_session, e.proc, 4, reviewer_id=revisor.id)
        assert out["next_phase"] == 5


# ---------------------------------------------------------------------------
# Corte a T-soft en 3 (producción)
# ---------------------------------------------------------------------------
class TestCorteEnTres:
    def test_con_el_corte_en_3_no_se_envia(self, db_session, esc, make_format_b):
        e = esc(cut=3)
        fb = make_format_b(e.proc)

        with pytest.raises(ValueError) as exc:
            FormatBService.submit(db_session, fb, e.proc)

        assert str(exc.value) == PhaseService.HANDOFF_MSG
        assert fb.status == "draft"

    def test_con_el_corte_en_3_no_se_dictamina(self, db_session, esc, make_format_b,
                                               revisor):
        e = esc(cut=3)
        fb = make_format_b(e.proc, status="submitted", modality=e.residencias,
                           submission_count=1)

        for dictamen in (lambda: FormatBService.approve(db_session, e.proc, revisor.id),
                         lambda: FormatBService.reject(db_session, e.proc, revisor.id,
                                                       general_note="No", field_notes={})):
            with pytest.raises(ValueError) as exc:
                dictamen()
            assert str(exc.value) == PhaseService.HANDOFF_MSG
        assert fb.status == "submitted" and e.proc.current_phase == 3
        assert _acciones(db_session, "format_b.reviewed") == []

    def test_con_el_corte_en_3_no_se_corrige_el_registro(self, db_session, esc,
                                                         make_format_b, revisor):
        e = esc(cut=3)
        make_format_b(e.proc, status="submitted", submission_count=1)
        with pytest.raises(ValueError) as exc:
            FormatBService.correct_registry(db_session, e.proc, revisor.id,
                                            first_name="ANNA", last_name="PEREZ",
                                            middle_name=None, program_id=e.programa.id,
                                            reason="Acta")
        assert str(exc.value) == PhaseService.HANDOFF_MSG
        assert e.alumno.first_name == "ANA"


# ---------------------------------------------------------------------------
# correct_registry (D9, §8.5)
# ---------------------------------------------------------------------------
class TestCorregirRegistro:
    def test_en_borrador_no_se_corrige(self, db_session, esc, revisor):
        e = esc()
        FormatBService.get_or_create(db_session, e.proc)
        with pytest.raises(ValueError):
            FormatBService.correct_registry(db_session, e.proc, revisor.id,
                                            first_name="ANNA", last_name="PEREZ",
                                            middle_name=None, program_id=e.programa.id,
                                            reason="Acta de nacimiento")
        assert e.alumno.first_name == "ANA"

    def test_cambiar_de_nivel_no_se_permite(self, db_session, esc, revisor, make_program):
        e = esc()
        _enviado(db_session, e)
        maestria = make_program("Maestria Ficticia Formato B", level="maestria")

        with pytest.raises(ValueError):
            FormatBService.correct_registry(db_session, e.proc, revisor.id,
                                            first_name="ANA", last_name="PEREZ",
                                            middle_name=None, program_id=maestria.id,
                                            reason="Se equivocó de carrera")
        assert e.proc.program_id == e.programa.id

    @pytest.mark.parametrize("cambios", [
        {"first_name": "   "}, {"last_name": ""}, {"reason": "  "},
        {"program_id": 987654321},
    ])
    def test_datos_obligatorios(self, db_session, esc, revisor, cambios):
        e = esc()
        _enviado(db_session, e)
        datos = {"first_name": "ANNA", "last_name": "PEREZ", "middle_name": None,
                 "program_id": e.programa.id, "reason": "Acta de nacimiento"}
        datos.update(cambios)
        with pytest.raises(ValueError):
            FormatBService.correct_registry(db_session, e.proc, revisor.id, **datos)
        assert e.alumno.first_name == "ANA"

    def test_sin_cambios_no_hay_nada_que_corregir(self, db_session, esc, revisor):
        e = esc()
        _enviado(db_session, e)
        with pytest.raises(ValueError):
            FormatBService.correct_registry(db_session, e.proc, revisor.id,
                                            first_name="ANA", last_name="PEREZ",
                                            middle_name=None, program_id=e.programa.id,
                                            reason="Revisión")

    def test_correccion_feliz(self, db_session, esc, revisor, make_program):
        from itcj2.core.models.notification import Notification
        e = esc()
        fb = _enviado(db_session, e)
        otra = make_program("Ingenieria Ficticia Formato B Dos")

        cambios = FormatBService.correct_registry(
            db_session, e.proc, revisor.id, first_name="  ANNA   MARIA ",
            last_name="PEREZ", middle_name="GOMEZ", program_id=otra.id,
            reason="Coincide con el acta")

        assert cambios == {"first_name": ("ANA", "ANNA MARIA"),
                           "middle_name": (None, "GOMEZ"),
                           "program_id": (e.programa.id, otra.id)}
        assert (e.alumno.first_name, e.alumno.middle_name) == ("ANNA MARIA", "GOMEZ")
        assert e.proc.program_id == otra.id
        assert (fb.first_name, fb.middle_name, fb.program_id) == ("ANNA MARIA", "GOMEZ", otra.id)
        assert fb.status == "submitted", "corregir el registro no regresa el Formato B"
        fila = _acciones(db_session, "format_b.registry_corrected")[0]
        assert fila.reason == "Coincide con el acta"
        assert fila.before == {"first_name": "ANA", "middle_name": None,
                               "program_id": e.programa.id}
        assert fila.after == {"first_name": "ANNA MARIA", "middle_name": "GOMEZ",
                              "program_id": otra.id}
        assert fila.actor_id == revisor.id
        (ev,) = _eventos(db_session, e.proc.id, "format_b_registry_corrected")
        assert ev.actor_id == revisor.id and ev.phase_number == 3
        assert ev.payload["reason"] == "Coincide con el acta"
        assert ev.payload["fields"] == ["first_name", "middle_name", "program_id"]
        aviso = (db_session.query(Notification)
                 .filter_by(user_id=e.alumno.id, type="REGISTRY_CORRECTED").one())
        assert "nombre y carrera" in aviso.body


# ---------------------------------------------------------------------------
# display_sections (lo usan T4, T6 y T8)
# ---------------------------------------------------------------------------
def _filas(secciones):
    return {r["field"]: r for s in secciones for r in s["rows"]}


class TestSecciones:
    def test_estructura_y_borrador_en_vivo(self, db_session, esc):
        e = esc()
        fb = FormatBService.get_or_create(db_session, e.proc)
        FormatBService.save_step(db_session, fb, 1, _paso1())
        e.alumno.first_name = "ANITA"          # el registro cambia: el borrador lo ve
        db_session.flush()

        secciones = FormatBService.display_sections(db_session, fb, e.proc)

        assert [s["key"] for s in secciones] == ["personal", "escolar", "proyecto"]
        filas = _filas(secciones)
        assert filas["first_name"]["value"] == "ANITA"
        assert filas["first_name"]["editable"] is False
        assert filas["middle_name"]["value"] == "—"
        assert filas["program_id"]["value"] == "Ingenieria Ficticia Formato B"
        assert filas["gender"]["value"] == "Mujer" and filas["gender"]["editable"] is True
        assert filas["mobile_phone"]["value"] == "6561234567"
        assert filas["admission_date"]["value"] == "—"
        for fila in filas.values():
            assert set(fila) >= {"field", "label", "value", "editable", "observation",
                                 "changed"}
            assert fila["observation"] is None and fila["changed"] is False

    def test_sin_formato_b(self, db_session, esc):
        e = esc()
        filas = _filas(FormatBService.display_sections(db_session, None, e.proc))
        assert filas["first_name"]["value"] == "ANA"
        assert filas["street"]["value"] == "—"

    def test_enviado_muestra_la_copia_congelada(self, db_session, esc):
        e = esc()
        fb = _enviado(db_session, e)
        e.alumno.first_name = "OTRO NOMBRE"
        db_session.flush()

        filas = _filas(FormatBService.display_sections(db_session, fb, e.proc))

        assert filas["first_name"]["value"] == "ANA"
        assert filas["modality_id"]["value"] == "Residencias de prueba"
        assert filas["admission_date"]["value"] == "agosto de 2018"
        assert filas["project_name"]["value"] == "Sistema de control de inventarios"

    def test_observaciones_y_corregido(self, db_session, esc, revisor):
        e = esc()
        fb = _enviado(db_session, e)
        FormatBService.reject(db_session, e.proc, revisor.id, general_note=None,
                              field_notes={"postal_code": "No coincide",
                                           "street": "Incompleta"})
        FormatBService.save_step(db_session, fb, 1, _paso1(postal_code="32001"))

        filas = _filas(FormatBService.display_sections(db_session, fb, e.proc))

        assert filas["postal_code"]["observation"] == {"note": "No coincide",
                                                      "value_at_review": "32000"}
        assert filas["postal_code"]["changed"] is True
        assert filas["street"]["observation"]["note"] == "Incompleta"
        assert filas["street"]["changed"] is False
        assert filas["age"]["observation"] is None

    def test_sin_proyecto_requerido_no_se_observa(self, db_session, esc):
        e = esc()
        fb = _enviado(db_session, e, modalidad=e.egel)
        filas = _filas(FormatBService.display_sections(db_session, fb, e.proc))
        assert filas["project_name"]["editable"] is False
        assert filas["project_name"]["value"] == "No aplica para esta modalidad"


# ---------------------------------------------------------------------------
# Ruta del alumno (adaptación mínima del Ruling R8; la ola 3 la reescribe)
# ---------------------------------------------------------------------------
_PERMS_ALUMNO = ("titulatec.format_b.page.fill", "titulatec.format_b.api.save",
                 "titulatec.format_b.api.submit")


class TestRutaDelAlumno:
    def test_un_paso_invalido_responde_200_sin_guardar(self, db_session, esc, client_as,
                                                       make_student, make_process):
        e = esc()
        alumno = make_student(perm_codes=_PERMS_ALUMNO)
        proc = make_process(alumno, program=e.programa, current_phase=3)

        resp = client_as(alumno).post("/titulatec/student/formato-b/step/1",
                                      data=_paso1(age="12"))

        assert resp.status_code == 200, resp.text[:300]
        db_session.expire_all()
        fb = FormatBService.get_or_create(db_session, proc)
        assert fb.gender is None and fb.age is None

    def test_un_formato_enviado_responde_400_con_el_motivo(self, db_session, esc, client_as,
                                                           make_student, make_process,
                                                           make_format_b):
        from urllib.parse import unquote
        e = esc()
        alumno = make_student(perm_codes=_PERMS_ALUMNO)
        proc = make_process(alumno, program=e.programa, current_phase=3)
        make_format_b(proc, status="submitted", submission_count=1)

        resp = client_as(alumno).post("/titulatec/student/formato-b/step/1", data=_paso1())

        assert resp.status_code == 400
        assert unquote(resp.headers["X-Tt-Error"]) == EDIT_LOCKED_MSG


# ---------------------------------------------------------------------------
# Bitácora: el espejo de los eventos nuevos cae en «Formato B»
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("tipo", ["format_b_submitted", "format_b_registry_corrected"])
def test_el_espejo_de_los_eventos_del_formato_b_cae_en_su_modulo(tipo):
    from itcj2.apps.titulatec.models.process_event import EVENT_TYPES
    from itcj2.apps.titulatec.services.audit_actions import process_event_module

    assert tipo in EVENT_TYPES
    assert process_event_module(tipo) == "format_b"
