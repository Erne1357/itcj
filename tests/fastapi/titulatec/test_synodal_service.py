"""Fase 4 (sinodales), tarea 5: `SynodalService` y la puerta generalizada del motor.

Spec 2026-10-21-titulatec-fase4-sinodales §10 (motor), §11 (avisos) y §16b R-D
(quién opera qué departamento). Lo que se fija aquí:

- asignar los 4 aprueba la fase 4 y el proceso pasa a la 5 en UNA transacción,
  con el evento `synodals_assigned` y la bitácora `synodal.assigned`;
- las negativas (fuera de alcance, carrera sin departamento, faltan, repetidos,
  no docente del departamento, perfil incompleto, ya asignados, otra fase, corte
  en 3) no escriben nada;
- dos personas asignando el mismo proceso: la segunda ve «ya tiene sinodales»
  BAJO el candado (relectura, `set_committed_value`) y deshace (RF3);
- una sola puerta: aprobar o rechazar la fase 4 por el motor genérico da
  `SYNODAL_ONLY_MSG`, aun con la marca de otra fase o sin los 4 vigentes;
- sustituir (D8): motivo obligatorio, historial, índices parciales (ida y
  vuelta) y solo con la fase 4 aprobada y la 5 sin aprobar;
- `can_operate` (R-D): jefe y coordinador de su departamento; la carrera
  remapeada mueve el alcance (RF4); `read.all` opera cualquier depto mapeado;
- avisos DESPUÉS del commit: una `Notification` por sinodal y el correo
  (parcheado); una falla de correo queda en la bitácora y no revierte nada.

Todo test levanta el corte EXPLÍCITO en 9 (el comando corre con 3, como
producción); las pruebas del corte lo vuelven a fijar en 3.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.orm.attributes import set_committed_value

from itcj2.apps.titulatec.services import email_helper
from itcj2.apps.titulatec.services.phase_service import PhaseService
from itcj2.apps.titulatec.services.synodal_service import (
    ALREADY_ASSIGNED_MSG, IN_OTHER_ROLE_MSG, INACTIVE_TEACHER_MSG, INERT_MSG, MISSING_MSG,
    NEW_USER_MSG, NOT_APPLICABLE_LABEL, NOT_IN_APP_LABEL, PENDING_LABEL,
    NO_HOLDER_MSG, NO_PROFILE_MSG, NOT_ACTIVE_MSG, NOT_MAPPED_MSG, NOT_TEACHER_MSG,
    OUT_OF_SCOPE_MSG, REASON_MSG, REPEATED_MSG, REPLACE_WINDOW_MSG, ROLE_LABELS,
    ROLE_MSG, ROLES, SAME_PERSON_MSG, SynodalService,
)
from tests.fastapi.titulatec.conftest import _n, audit_query

pytestmark = pytest.mark.usefixtures("audit_mark")

READ_ALL = "titulatec.process.api.read.all"
PROYECTO = "Sistema de control de inventarios"
CARRERA_OFICIAL = "Ingeniería Ficticia Oficial de Sinodales"


# ---------------------------------------------------------------------------
# Andamiaje
# ---------------------------------------------------------------------------
@pytest.fixture()
def corte(monkeypatch):
    """Fija el corte a T-soft. `corte(9)` lo apaga; `corte(3)` es producción."""
    def _fijar(fase):
        monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: fase))
    return _fijar


@pytest.fixture(autouse=True)
def correos(monkeypatch, patched_session_local, corte):
    """Corte en 9, `SessionLocal` = la sesión del test (los avisos abren la
    suya tras el commit) y el correo parcheado: registra cada envío y falla
    para los buzones que diga `fallan` ({correo: motivo})."""
    corte(9)
    enviados, fallan = [], {}

    def _deliver(*, template, context, subject, to, que, link=None):
        enviados.append({"template": template, "context": dict(context),
                         "subject": subject, "to": to, "que": que})
        motivo = fallan.get(to)
        return (False, motivo) if motivo else (True, None)

    monkeypatch.setattr(email_helper, "deliver_detailed", _deliver)
    return SimpleNamespace(enviados=enviados, fallan=fallan)


@pytest.fixture()
def esc(db_session, seed_phase_defs, make_program, make_department,
        make_program_department, make_academic_head, make_teacher, make_user,
        make_student, make_process, make_modality, make_format_b):
    """Carrera mapeada a un departamento con su jefe, su coordinador de
    vinculación y 5 docentes con perfil; alumno en la fase pedida (4 por
    omisión) con el Formato B aprobado y la modalidad ya en el proceso."""
    def _build(*, current_phase=4, status="active", mapped=True):
        seed_phase_defs()
        n = _n()
        programa = make_program(f"Ingenieria Ficticia Sinodales {n}")
        depto = make_department(name=f"Depto sinodales {n}")
        if mapped:
            make_program_department(programa, depto, official_name=CARRERA_OFICIAL)
        jefe = make_academic_head(depto, kind="head")
        coord = make_academic_head(depto, kind="coord")
        docentes = [make_teacher(depto, user=make_user(first_name=f"DOCENTE{i}",
                                                       last_name=f"SINODAL{n}"))
                    for i in range(5)]
        modalidad = make_modality(name="Tesis de prueba", requires_synodals=True)
        alumno = make_student(first_name="ANA", last_name="PEREZ")
        proc = make_process(alumno, program=programa, modality=modalidad,
                            current_phase=current_phase, status=status)
        make_format_b(proc, status="approved", modality=modalidad, submission_count=1,
                      project_name=PROYECTO)
        return SimpleNamespace(programa=programa, depto=depto, jefe=jefe, coord=coord,
                               docentes=docentes, alumno=alumno, proc=proc,
                               modalidad=modalidad)
    return _build


@pytest.fixture()
def otro_depto(make_department, make_academic_head, make_teacher, make_user):
    """Otro departamento académico con su jefe y 4 docentes."""
    def _build():
        n = _n()
        depto = make_department(name=f"Otro depto sinodales {n}")
        jefe = make_academic_head(depto, kind="head")
        docentes = [make_teacher(depto, user=make_user(first_name=f"OTRO{i}",
                                                       last_name=f"DOCENTE{n}"))
                    for i in range(4)]
        return SimpleNamespace(depto=depto, jefe=jefe, docentes=docentes)
    return _build


@pytest.fixture()
def rollbacks(db_session, monkeypatch):
    """Cuenta los `db.rollback()` (y los deja ocurrir): un error ANTES del
    candado no deshace nada; uno BAJO el candado sí, antes de re-lanzar."""
    llamadas = []
    original = db_session.rollback

    def _contado():
        llamadas.append(1)
        return original()
    monkeypatch.setattr(db_session, "rollback", _contado)
    return llamadas


def _ids(docentes) -> dict:
    return dict(president_id=docentes[0].id, secretary_id=docentes[1].id,
                vocal_id=docentes[2].id, alternate_id=docentes[3].id)


def _asignar(db, e, actor=None, docentes=None):
    return SynodalService.assign(db, e.proc, (actor or e.jefe).id,
                                 **_ids(docentes or e.docentes))


def _vigentes(db, pid) -> dict:
    from itcj2.apps.titulatec.models import SynodalAssignment
    return {r: u for r, u in db.query(SynodalAssignment.role, SynodalAssignment.user_id)
            .filter(SynodalAssignment.process_id == pid,
                    SynodalAssignment.is_active.is_(True)).all()}


def _filas(db, pid) -> list:
    from itcj2.apps.titulatec.models import SynodalAssignment
    return (db.query(SynodalAssignment).filter_by(process_id=pid)
            .order_by(SynodalAssignment.id).all())


def _fases(db, pid) -> dict:
    from itcj2.apps.titulatec.models import ProcessPhase
    return {p.phase_number: p.status
            for p in db.query(ProcessPhase).filter_by(process_id=pid).all()}


def _eventos(db, pid, tipo) -> list:
    from itcj2.apps.titulatec.models import ProcessEvent
    return (db.query(ProcessEvent).filter_by(process_id=pid, event_type=tipo)
            .order_by(ProcessEvent.id).all())


def _acciones(db, action) -> list:
    from itcj2.apps.titulatec.models.audit_log import TitulatecAuditLog
    db.flush()
    return (audit_query(db).filter_by(source="action", action=action)
            .order_by(TitulatecAuditLog.id).all())


def _avisos(db, user_ids, tipo=None) -> list:
    from itcj2.core.models.notification import Notification
    q = db.query(Notification).filter(Notification.user_id.in_(list(user_ids)),
                                      Notification.app_name == "titulatec")
    if tipo:
        q = q.filter(Notification.type == tipo)
    return q.order_by(Notification.id).all()


def _nombre(user) -> str:
    return " ".join(p for p in (user.first_name, user.last_name, user.middle_name) if p)


def _sin_escribir(db, e) -> None:
    """Ninguna fila, evento ni dictamen: la fase 4 sigue en curso."""
    db.expire_all()
    assert _vigentes(db, e.proc.id) == {}
    assert _eventos(db, e.proc.id, "synodals_assigned") == []
    assert e.proc.current_phase == 4
    assert _fases(db, e.proc.id)[4] == "in_progress"
    assert _acciones(db, "synodal.assigned") == []
    assert PhaseService.DOOR_KEY not in db.info


# ---------------------------------------------------------------------------
# Asignar: el camino feliz
# ---------------------------------------------------------------------------
class TestAsignar:
    @pytest.mark.parametrize("quien", ["jefe", "coord"])
    def test_aprueba_la_fase_4_y_el_proceso_pasa_a_la_5(self, db_session, esc, quien):
        e = esc()
        actor = getattr(e, quien)

        out = _asignar(db_session, e, actor=actor)

        esperados = dict(zip(ROLES, (d.id for d in e.docentes)))
        assert out["next_phase"] == 5 and out["completed"] is False
        assert out["synodals"] == esperados
        db_session.expire_all()
        assert e.proc.current_phase == 5
        fases = _fases(db_session, e.proc.id)
        assert fases[4] == "approved" and fases[5] == "in_progress"
        assert _vigentes(db_session, e.proc.id) == esperados
        for fila in _filas(db_session, e.proc.id):
            assert fila.is_active and fila.assigned_by_id == actor.id

        pares = [{"role": r, "user_id": u} for r, u in esperados.items()]
        (evento,) = _eventos(db_session, e.proc.id, "synodals_assigned")
        assert evento.payload == {"synodals": pares}
        assert evento.phase_number == 4 and evento.actor_id == actor.id
        aprobadas = [ev for ev in _eventos(db_session, e.proc.id, "phase_approved")
                     if ev.phase_number == 4]
        assert len(aprobadas) == 1

        (bitacora,) = _acciones(db_session, "synodal.assigned")
        assert bitacora.process_id == e.proc.id and bitacora.actor_id == actor.id
        # La posición viaja como VALOR: una llave «secretary» saldría "***" (D9).
        assert bitacora.payload["synodals"] == pares
        (espejo,) = (audit_query(db_session)
                     .filter_by(source="process_event",
                                action="process.synodals_assigned").all())
        assert espejo.payload["synodals"] == pares
        assert PhaseService.DOOR_KEY not in db_session.info, "la puerta se cierra"
        # Fase 5 (spec 2026-10-22 §6.2): en la MISMA transacción nace la
        # conversación de revisión, abierta y con su mensaje de apertura.
        from itcj2.apps.titulatec.models import ChatMessage, ProcessChat
        from itcj2.apps.titulatec.services.review_service import OPEN_CHAT_MSG
        chat = db_session.query(ProcessChat).filter_by(process_id=e.proc.id).one()
        assert chat.closed_at is None
        assert [(m.kind, m.author_id, m.body)
                for m in db_session.query(ChatMessage).filter_by(chat_id=chat.id)] == [
            ("system", None, OPEN_CHAT_MSG)]

    def test_con_el_corte_en_la_5_no_se_abre_la_conversacion(self, db_session, esc, corte):
        """R7 (fase 5): con el corte a T-soft en la fase 5 la revisión es de
        T-soft; la fase 4 sí se asigna y avanza, pero no nace la conversación."""
        from itcj2.apps.titulatec.models import ProcessChat

        corte(5)
        e = esc()

        out = _asignar(db_session, e)

        assert out["next_phase"] == 5
        assert db_session.query(ProcessChat).filter_by(process_id=e.proc.id).count() == 0

    def test_acepta_los_ids_como_texto(self, db_session, esc):
        """La ruta los manda tal cual llegan del formulario."""
        e = esc()
        SynodalService.assign(db_session, e.proc, e.jefe.id,
                              **{k: str(v) for k, v in _ids(e.docentes).items()})
        assert e.proc.current_phase == 5

    @pytest.mark.parametrize("cambio", [{"president_id": None}, {"vocal_id": ""},
                                        {"alternate_id": "abc"}, {"secretary_id": True}])
    def test_faltan_sinodales(self, db_session, esc, cambio):
        e = esc()
        datos = {**_ids(e.docentes), **cambio}
        with pytest.raises(ValueError) as exc:
            SynodalService.assign(db_session, e.proc, e.jefe.id, **datos)
        assert str(exc.value) == MISSING_MSG
        _sin_escribir(db_session, e)

    def test_repetidos(self, db_session, esc, rollbacks):
        e = esc()
        datos = {**_ids(e.docentes), "alternate_id": e.docentes[0].id}
        with pytest.raises(ValueError) as exc:
            SynodalService.assign(db_session, e.proc, e.jefe.id, **datos)
        assert str(exc.value) == REPEATED_MSG
        assert rollbacks == []
        _sin_escribir(db_session, e)

    def test_no_docente_del_departamento(self, db_session, esc, otro_depto, rollbacks):
        e = esc()
        ajeno = otro_depto().docentes[0]
        datos = {**_ids(e.docentes), "secretary_id": ajeno.id}

        with pytest.raises(ValueError) as exc:
            SynodalService.assign(db_session, e.proc, e.jefe.id, **datos)

        assert str(exc.value) == NOT_TEACHER_MSG.format(posicion="Secretario",
                                                        nombre=_nombre(ajeno))
        assert rollbacks == [], "falla sin candado: no hay nada que deshacer"
        _sin_escribir(db_session, e)

    @pytest.mark.parametrize("como", ["sin_perfil", "grado_en_blanco", "cedula_en_blanco"])
    def test_perfil_incompleto(self, db_session, esc, como):
        from itcj2.apps.titulatec.models import TeacherProfile
        e = esc()
        perfil = db_session.get(TeacherProfile, e.docentes[2].id)
        if como == "sin_perfil":
            db_session.delete(perfil)
        elif como == "grado_en_blanco":
            perfil.academic_degree = "   "
        else:
            perfil.professional_license = ""
        db_session.flush()

        with pytest.raises(ValueError) as exc:
            _asignar(db_session, e)

        assert str(exc.value) == NO_PROFILE_MSG.format(posicion="Vocal",
                                                       nombre=_nombre(e.docentes[2]))
        _sin_escribir(db_session, e)

    def test_docente_con_la_cuenta_desactivada(self, db_session, esc, rollbacks):
        """Hallazgo 3 de la revisión de rama: el puesto docente sigue vigente
        pero la cuenta está desactivada (no podría entrar a la fase 5)."""
        e = esc()
        e.docentes[1].is_active = False
        db_session.flush()

        with pytest.raises(ValueError) as exc:
            _asignar(db_session, e)

        assert str(exc.value) == INACTIVE_TEACHER_MSG.format(
            posicion="Secretario", nombre=_nombre(e.docentes[1]))
        assert rollbacks == [], "falla sin candado: no hay nada que deshacer"
        _sin_escribir(db_session, e)

    def test_en_otra_fase_lo_niega_el_motor(self, db_session, esc):
        e = esc(current_phase=3)
        with pytest.raises(ValueError) as exc:
            _asignar(db_session, e)
        assert "Solo puedes actuar sobre la fase en curso" in str(exc.value)
        assert _vigentes(db_session, e.proc.id) == {}

    def test_con_el_proceso_pausado_lo_niega_el_motor(self, db_session, esc):
        e = esc(status="on_hold")
        with pytest.raises(ValueError) as exc:
            _asignar(db_session, e)
        assert "on_hold" in str(exc.value)
        assert _vigentes(db_session, e.proc.id) == {}


# ---------------------------------------------------------------------------
# Ya asignados (RF3): la segunda persona ve «ya tiene sinodales» sin escribir
# ---------------------------------------------------------------------------
class TestYaAsignados:
    def test_asignar_de_nuevo_lo_niega_sin_candado(self, db_session, esc, rollbacks):
        e = esc()
        _asignar(db_session, e)
        db_session.expire_all()

        with pytest.raises(ValueError) as exc:
            _asignar(db_session, e, actor=e.coord)

        assert str(exc.value).startswith(ALREADY_ASSIGNED_MSG.rstrip("."))
        assert rollbacks == []

    def test_dos_a_la_vez_el_segundo_lo_ve_bajo_el_candado(self, db_session, esc,
                                                           rollbacks, correos):
        """Carrera determinista (técnica de `test_format_b_service.py::
        TestRelecturaBajoElBloqueo`): el jefe gana; el coordinador todavía ve
        en memoria la fase 4 SIN sinodales, como cuando abrió la pantalla.
        Sin la relectura bajo el candado su verificación pasaría."""
        e = esc()
        _asignar(db_session, e)                                   # el jefe gana
        ganadores = _vigentes(db_session, e.proc.id)
        set_committed_value(e.proc, "current_phase", 4)           # lo que leyó el coord
        set_committed_value(e.proc, "synodal_assignments", [])
        avisos_antes = len(correos.enviados)

        with pytest.raises(ValueError) as exc:
            SynodalService.assign(db_session, e.proc, e.coord.id,
                                  president_id=e.docentes[4].id,
                                  secretary_id=e.docentes[3].id,
                                  vocal_id=e.docentes[2].id,
                                  alternate_id=e.docentes[1].id)

        mensaje = str(exc.value)
        assert mensaje.startswith(ALREADY_ASSIGNED_MSG.rstrip("."))
        assert "JEFE ACADEMICO" in mensaje, "dice quién los registró"
        assert rollbacks == [1], "falla bajo el candado: deshace antes de re-lanzar"
        db_session.expire_all()
        assert e.proc.current_phase == 5
        assert _vigentes(db_session, e.proc.id) == ganadores
        assert len(_eventos(db_session, e.proc.id, "synodals_assigned")) == 1
        assert len([ev for ev in _eventos(db_session, e.proc.id, "phase_approved")
                    if ev.phase_number == 4]) == 1
        assert len(_acciones(db_session, "synodal.assigned")) == 1
        assert PhaseService.DOOR_KEY not in db_session.info
        assert len(correos.enviados) == avisos_antes, "el perdedor no avisa a nadie"


# ---------------------------------------------------------------------------
# Una sola puerta: el motor genérico no mueve la fase 4
# ---------------------------------------------------------------------------
class TestUnaSolaPuerta:
    def test_aprobar_la_fase_4_directo_con_los_4_vigentes(self, db_session, esc,
                                                          make_synodals):
        e = esc()
        make_synodals(e.proc, dict(zip(ROLES, e.docentes)), assigned_by=e.jefe)

        with pytest.raises(ValueError) as exc:
            PhaseService.approve_phase(db_session, e.proc, 4, reviewer_id=e.jefe.id)

        assert str(exc.value) == PhaseService.SYNODAL_ONLY_MSG
        assert e.proc.current_phase == 4
        assert _fases(db_session, e.proc.id)[4] == "in_progress"

    def test_la_fase_4_no_tiene_rechazo(self, db_session, esc, make_synodals):
        """Ni con la marca de rechazo abierta a mano: el servicio nunca la abre."""
        e = esc()
        make_synodals(e.proc, dict(zip(ROLES, e.docentes)), assigned_by=e.jefe)
        for marca in (None, "rejected"):
            if marca:
                PhaseService.open_door(db_session, "synodal_assignment", e.proc.id, marca)
            with pytest.raises(ValueError) as exc:
                PhaseService.reject_phase(db_session, e.proc, 4, reviewer_id=e.jefe.id,
                                          reason="por la otra puerta")
            assert str(exc.value) == PhaseService.SYNODAL_ONLY_MSG
            assert PhaseService.DOOR_KEY not in db_session.info, "se consume"
        assert _eventos(db_session, e.proc.id, "phase_rejected") == []

    def test_una_marca_ajena_no_abre_la_puerta(self, db_session, esc, make_synodals):
        e = esc()
        make_synodals(e.proc, dict(zip(ROLES, e.docentes)), assigned_by=e.jefe)
        for codigo, pid in (("format_b", e.proc.id), ("synodal_assignment", e.proc.id + 1)):
            PhaseService.open_door(db_session, codigo, pid, "approved")
            with pytest.raises(ValueError) as exc:
                PhaseService.approve_phase(db_session, e.proc, 4, reviewer_id=e.jefe.id)
            assert str(exc.value) == PhaseService.SYNODAL_ONLY_MSG
            assert PhaseService.DOOR_KEY not in db_session.info, "se consume"
        assert e.proc.current_phase == 4

    def test_la_marca_correcta_sin_los_4_vigentes_no_abre(self, db_session, esc,
                                                          make_synodals):
        """La guarda también mira el estado: la marca sola no basta."""
        e = esc()
        make_synodals(e.proc, dict(zip(ROLES[:3], e.docentes)), assigned_by=e.jefe)
        PhaseService.open_door(db_session, "synodal_assignment", e.proc.id, "approved")
        with pytest.raises(ValueError) as exc:
            PhaseService.approve_phase(db_session, e.proc, 4, reviewer_id=e.jefe.id)
        assert str(exc.value) == PhaseService.SYNODAL_ONLY_MSG
        assert e.proc.current_phase == 4

    def test_open_door_solo_conoce_las_fases_con_puerta(self, db_session):
        with pytest.raises(ValueError):
            PhaseService.open_door(db_session, "final_docs", 1, "approved")
        with pytest.raises(ValueError):
            PhaseService.open_door(db_session, "synodal_assignment", 1, "aprobado")
        assert PhaseService.DOOR_KEY not in db_session.info
        # Fase 5 (spec 2026-10-22 §6.4): la revisión de sinodales también
        # tiene puerta (`ReviewService.vote`); su caso vive en test_review_service.py.
        # Fase 6 (spec fase 6 §10): el Anexo III (`AnexoService`), en test_anexo_door.py.
        assert set(PhaseService._DOOR_PHASES) == {"format_b", "synodal_assignment",
                                                  "synodal_review", "anexo_iii"}
        assert PhaseService._DOOR_PHASES["synodal_review"] == PhaseService.REVIEW_ONLY_MSG
        assert PhaseService._DOOR_PHASES["anexo_iii"] == PhaseService.ANEXO_ONLY_MSG
        assert PhaseService._DOOR_PHASES["synodal_assignment"] == (
            "Los sinodales se registran desde la pestaña Sinodales.")

    def test_las_fases_sin_puerta_no_cambian(self, db_session, esc):
        # La 7 y no la 6: desde la fase 6 el Anexo III tiene su propia puerta.
        e = esc(current_phase=7)
        out = PhaseService.approve_phase(db_session, e.proc, 7, reviewer_id=e.jefe.id)
        assert out["next_phase"] == 8


# ---------------------------------------------------------------------------
# Corte a T-soft (R-G): con el corte en la fase 4 o antes, nada se opera
# ---------------------------------------------------------------------------
class TestCorte:
    def test_con_el_corte_en_3_no_se_asigna_ni_se_avisa(self, db_session, esc, corte,
                                                        correos):
        e = esc()
        corte(3)
        assert SynodalService.operable(db_session) is False

        with pytest.raises(ValueError) as exc:
            _asignar(db_session, e)
        assert str(exc.value) == INERT_MSG
        _sin_escribir(db_session, e)

        SynodalService.send_assignment_notices(e.proc.id, [d.id for d in e.docentes],
                                               kind="assigned")
        assert correos.enviados == []
        assert _avisos(db_session, [d.id for d in e.docentes]) == []

    def test_con_el_corte_en_4_tampoco(self, db_session, esc, corte):
        e = esc()
        corte(4)
        with pytest.raises(ValueError) as exc:
            _asignar(db_session, e)
        assert str(exc.value) == INERT_MSG

    def test_con_el_corte_en_3_no_se_sustituye(self, db_session, esc, corte):
        e = esc()
        _asignar(db_session, e)
        corte(3)
        with pytest.raises(ValueError) as exc:
            SynodalService.replace(db_session, e.proc, e.jefe.id, role="vocal",
                                   new_user_id=e.docentes[4].id, reason="Licencia")
        assert str(exc.value) == INERT_MSG
        assert _vigentes(db_session, e.proc.id)["vocal"] == e.docentes[2].id


# ---------------------------------------------------------------------------
# Alcance (R-D, RF4)
# ---------------------------------------------------------------------------
class TestAlcance:
    def test_jefe_y_coordinador_operan_su_departamento(self, db_session, esc, otro_depto):
        e = esc()
        ajeno = otro_depto()
        assert SynodalService.can_operate(db_session, e.jefe.id, e.proc) is True
        assert SynodalService.can_operate(db_session, e.coord.id, e.proc) is True
        assert SynodalService.can_operate(db_session, ajeno.jefe.id, e.proc) is False
        assert SynodalService.can_operate(db_session, e.alumno.id, e.proc) is False

    def test_fuera_de_alcance_no_escribe(self, db_session, esc, otro_depto, rollbacks):
        e = esc()
        ajeno = otro_depto()
        with pytest.raises(ValueError) as exc:
            _asignar(db_session, e, actor=ajeno.jefe)
        assert str(exc.value) == OUT_OF_SCOPE_MSG
        assert rollbacks == []
        _sin_escribir(db_session, e)

    def test_carrera_sin_departamento(self, db_session, esc, make_head):
        e = esc(mapped=False)
        admin = make_head(perm_codes=(READ_ALL,))
        assert SynodalService.can_operate(db_session, admin.id, e.proc) is False
        with pytest.raises(ValueError) as exc:
            _asignar(db_session, e, actor=admin)
        assert str(exc.value) == NOT_MAPPED_MSG
        _sin_escribir(db_session, e)

    def test_proceso_sin_carrera(self, db_session, esc, make_head):
        e = esc()
        e.proc.program_id = None
        db_session.flush()
        admin = make_head(perm_codes=(READ_ALL,))
        assert SynodalService.can_operate(db_session, admin.id, e.proc) is False
        assert SynodalService.can_operate(db_session, admin.id, None) is False

    def test_remapear_la_carrera_mueve_quien_opera(self, db_session, esc, otro_depto,
                                                   make_program_department):
        """RF4: el departamento viejo deja de operar el proceso y el nuevo sí;
        los docentes del viejo ya no sirven para esa carrera."""
        e = esc()
        nuevo = otro_depto()
        make_program_department(e.programa, nuevo.depto)

        assert SynodalService.can_operate(db_session, e.jefe.id, e.proc) is False
        assert SynodalService.can_operate(db_session, nuevo.jefe.id, e.proc) is True
        with pytest.raises(ValueError) as exc:
            _asignar(db_session, e)
        assert str(exc.value) == OUT_OF_SCOPE_MSG
        with pytest.raises(ValueError) as exc:
            _asignar(db_session, e, actor=nuevo.jefe)
        assert str(exc.value) == NOT_TEACHER_MSG.format(posicion="Presidente",
                                                        nombre=_nombre(e.docentes[0]))

        _asignar(db_session, e, actor=nuevo.jefe, docentes=nuevo.docentes)
        assert _vigentes(db_session, e.proc.id) == dict(
            zip(ROLES, (d.id for d in nuevo.docentes)))

    def test_read_all_opera_cualquier_departamento(self, db_session, esc, make_head):
        e = esc()
        admin = make_head(perm_codes=(READ_ALL,))
        assert SynodalService.can_operate(db_session, admin.id, e.proc) is True
        _asignar(db_session, e, actor=admin)
        assert e.proc.current_phase == 5


# ---------------------------------------------------------------------------
# Sustituir (D8)
# ---------------------------------------------------------------------------
class TestSustituir:
    def test_feliz_deja_historial_y_avisa(self, db_session, esc, correos):
        """Con el Secretario a propósito: su código contiene «secret», y la
        bitácora enmascara las LLAVES que lo contienen (D9)."""
        e = esc()
        _asignar(db_session, e)
        saliente, entrante = e.docentes[1], e.docentes[4]
        correos.enviados.clear()

        SynodalService.replace(db_session, e.proc, e.coord.id, role="secretary",
                               new_user_id=entrante.id, reason="  Licencia   médica ")

        db_session.expire_all()
        assert _vigentes(db_session, e.proc.id)["secretary"] == entrante.id
        viejo = next(f for f in _filas(db_session, e.proc.id)
                     if f.user_id == saliente.id)
        assert viejo.is_active is False and viejo.role == "secretary"
        assert viejo.replaced_at is not None
        assert viejo.replaced_by_id == e.coord.id
        assert viejo.replacement_reason == "Licencia médica"
        assert e.proc.current_phase == 5
        assert _fases(db_session, e.proc.id)[4] == "approved"

        (hist,) = SynodalService.history(db_session, e.proc.id)
        assert hist["role"] == "secretary" and hist["role_label"] == "Secretario"
        assert hist["user_id"] == saliente.id and hist["name"] == _nombre(saliente)
        assert hist["replacement_user_id"] == entrante.id
        assert hist["replacement_name"] == _nombre(entrante)
        assert hist["replaced_by_id"] == e.coord.id
        assert hist["replaced_by_name"] == _nombre(e.coord)
        assert hist["reason"] == "Licencia médica"
        assert hist["replaced_at"] == viejo.replaced_at

        (evento,) = _eventos(db_session, e.proc.id, "synodal_replaced")
        assert evento.payload == {"role": "secretary", "previous_user_id": saliente.id,
                                  "user_id": entrante.id, "reason": "Licencia médica"}
        (bitacora,) = _acciones(db_session, "synodal.replaced")
        assert bitacora.before == {"user_id": saliente.id}
        assert bitacora.after == {"user_id": entrante.id}
        assert bitacora.payload == {"role": "secretary"}
        assert bitacora.reason == "Licencia médica"

        assert len(_avisos(db_session, [e.alumno.id], "SYNODAL_REPLACED")) == 1
        assert len(_avisos(db_session, [entrante.id], "SYNODAL_ASSIGNED")) == 1
        assert len(_avisos(db_session, [saliente.id], "SYNODAL_RELEASED")) == 1
        # Fase 5 (spec 2026-10-22 §6.3): la sustitución queda en la conversación.
        from itcj2.apps.titulatec.models import ChatMessage, ProcessChat
        chat = db_session.query(ProcessChat).filter_by(process_id=e.proc.id).one()
        ultimo = (db_session.query(ChatMessage).filter_by(chat_id=chat.id)
                  .order_by(ChatMessage.id.desc()).first())
        assert (ultimo.kind, ultimo.author_id) == ("system", None)
        assert ultimo.body == (f"{_nombre(entrante)} sustituye a {_nombre(saliente)} "
                               "como Secretario.")
        destinos = {c["to"]: (c["context"]["kind"], c["context"]["posicion"])
                    for c in correos.enviados}
        assert destinos == {entrante.email: ("replaced_in", "Secretario"),
                            saliente.email: ("replaced_out", "Secretario")}

    def test_ida_y_vuelta_respeta_los_indices_parciales(self, db_session, esc):
        """Los índices únicos son PARCIALES (`WHERE is_active`): la misma persona
        puede volver a la misma posición con su fila vieja en el historial."""
        e = esc()
        _asignar(db_session, e)
        SynodalService.replace(db_session, e.proc, e.jefe.id, role="vocal",
                               new_user_id=e.docentes[4].id, reason="Licencia")
        SynodalService.replace(db_session, e.proc, e.jefe.id, role="vocal",
                               new_user_id=e.docentes[2].id, reason="Volvió")

        db_session.expire_all()
        assert _vigentes(db_session, e.proc.id)["vocal"] == e.docentes[2].id
        vocales = [f for f in _filas(db_session, e.proc.id) if f.role == "vocal"]
        assert [(f.user_id, f.is_active) for f in vocales] == [
            (e.docentes[2].id, False), (e.docentes[4].id, False), (e.docentes[2].id, True)]
        hist = SynodalService.history(db_session, e.proc.id)
        assert [(h["user_id"], h["replacement_user_id"]) for h in hist] == [
            (e.docentes[2].id, e.docentes[4].id), (e.docentes[4].id, e.docentes[2].id)]

    def test_dos_vigentes_en_la_misma_posicion_no_caben(self, db_session, esc):
        """Respaldo de la BD si alguien escribiera sin pasar por el servicio."""
        from sqlalchemy.exc import IntegrityError

        from itcj2.apps.titulatec.models import SynodalAssignment
        e = esc()
        _asignar(db_session, e)
        with pytest.raises(IntegrityError):
            with db_session.begin_nested():
                db_session.add(SynodalAssignment(process_id=e.proc.id, role="vocal",
                                                 user_id=e.docentes[4].id,
                                                 assigned_by_id=e.jefe.id))
                db_session.flush()

    @pytest.mark.parametrize("motivo", [None, "", "   ", "x" * 501])
    def test_motivo_obligatorio(self, db_session, esc, motivo):
        e = esc()
        _asignar(db_session, e)
        with pytest.raises(ValueError) as exc:
            SynodalService.replace(db_session, e.proc, e.jefe.id, role="vocal",
                                   new_user_id=e.docentes[4].id, reason=motivo)
        assert str(exc.value) == REASON_MSG
        assert _vigentes(db_session, e.proc.id)["vocal"] == e.docentes[2].id

    def test_posicion_o_docente_no_reconocidos(self, db_session, esc):
        e = esc()
        _asignar(db_session, e)
        with pytest.raises(ValueError) as exc:
            SynodalService.replace(db_session, e.proc, e.jefe.id, role="vocal_suplente",
                                   new_user_id=e.docentes[4].id, reason="Licencia")
        assert str(exc.value) == ROLE_MSG
        with pytest.raises(ValueError) as exc:
            SynodalService.replace(db_session, e.proc, e.jefe.id, role="vocal",
                                   new_user_id="", reason="Licencia")
        assert str(exc.value) == NEW_USER_MSG

    def test_con_la_fase_5_aprobada_no_se_sustituye(self, db_session, esc):
        from itcj2.apps.titulatec.models import ProcessPhase
        e = esc()
        _asignar(db_session, e)
        fase5 = (db_session.query(ProcessPhase)
                 .filter_by(process_id=e.proc.id, phase_number=5).one())
        fase5.status = "approved"
        db_session.flush()

        with pytest.raises(ValueError) as exc:
            SynodalService.replace(db_session, e.proc, e.jefe.id, role="vocal",
                                   new_user_id=e.docentes[4].id, reason="Licencia")
        assert str(exc.value) == REPLACE_WINDOW_MSG
        assert _vigentes(db_session, e.proc.id)["vocal"] == e.docentes[2].id
        assert _eventos(db_session, e.proc.id, "synodal_replaced") == []

    def test_sin_la_fase_4_aprobada_no_se_sustituye(self, db_session, esc, make_synodals):
        e = esc()
        make_synodals(e.proc, dict(zip(ROLES, e.docentes)), assigned_by=e.jefe)
        with pytest.raises(ValueError) as exc:
            SynodalService.replace(db_session, e.proc, e.jefe.id, role="vocal",
                                   new_user_id=e.docentes[4].id, reason="Licencia")
        assert str(exc.value) == REPLACE_WINDOW_MSG

    def test_con_el_proceso_pausado_no_se_sustituye(self, db_session, esc):
        e = esc()
        _asignar(db_session, e)
        e.proc.status = "on_hold"
        db_session.flush()
        with pytest.raises(ValueError) as exc:
            SynodalService.replace(db_session, e.proc, e.jefe.id, role="vocal",
                                   new_user_id=e.docentes[4].id, reason="Licencia")
        assert str(exc.value) == NOT_ACTIVE_MSG.format(estado="on_hold")

    def test_la_misma_persona_o_una_que_ya_es_sinodal(self, db_session, esc):
        e = esc()
        _asignar(db_session, e)
        with pytest.raises(ValueError) as exc:
            SynodalService.replace(db_session, e.proc, e.jefe.id, role="vocal",
                                   new_user_id=e.docentes[2].id, reason="Licencia")
        assert str(exc.value) == SAME_PERSON_MSG.format(nombre=_nombre(e.docentes[2]),
                                                        posicion="Vocal")
        with pytest.raises(ValueError) as exc:
            SynodalService.replace(db_session, e.proc, e.jefe.id, role="vocal",
                                   new_user_id=e.docentes[0].id, reason="Licencia")
        assert str(exc.value) == IN_OTHER_ROLE_MSG.format(nombre=_nombre(e.docentes[0]),
                                                          posicion="Presidente")
        assert _eventos(db_session, e.proc.id, "synodal_replaced") == []

    def test_sin_quien_ocupe_la_posicion(self, db_session, esc, make_synodals):
        """Dato incoherente (fase 4 aprobada con 3 vigentes): no hay a quién
        sustituir."""
        e = esc(current_phase=5)
        make_synodals(e.proc, dict(zip(ROLES[:3], e.docentes)), assigned_by=e.jefe)
        with pytest.raises(ValueError) as exc:
            SynodalService.replace(db_session, e.proc, e.jefe.id, role="alternate",
                                   new_user_id=e.docentes[4].id, reason="Licencia")
        assert str(exc.value) == NO_HOLDER_MSG.format(posicion="Vocal Suplente")

    def test_el_nuevo_debe_ser_docente_con_perfil(self, db_session, esc, otro_depto):
        from itcj2.apps.titulatec.models import TeacherProfile
        e = esc()
        _asignar(db_session, e)
        ajeno = otro_depto().docentes[0]
        with pytest.raises(ValueError) as exc:
            SynodalService.replace(db_session, e.proc, e.jefe.id, role="vocal",
                                   new_user_id=ajeno.id, reason="Licencia")
        assert str(exc.value) == NOT_TEACHER_MSG.format(posicion="Vocal",
                                                        nombre=_nombre(ajeno))
        db_session.delete(db_session.get(TeacherProfile, e.docentes[4].id))
        db_session.flush()
        with pytest.raises(ValueError) as exc:
            SynodalService.replace(db_session, e.proc, e.jefe.id, role="vocal",
                                   new_user_id=e.docentes[4].id, reason="Licencia")
        assert str(exc.value) == NO_PROFILE_MSG.format(posicion="Vocal",
                                                       nombre=_nombre(e.docentes[4]))

    def test_el_nuevo_no_puede_tener_la_cuenta_desactivada(self, db_session, esc):
        e = esc()
        _asignar(db_session, e)
        e.docentes[4].is_active = False
        db_session.flush()

        with pytest.raises(ValueError) as exc:
            SynodalService.replace(db_session, e.proc, e.jefe.id, role="vocal",
                                   new_user_id=e.docentes[4].id, reason="Licencia")

        assert str(exc.value) == INACTIVE_TEACHER_MSG.format(
            posicion="Vocal", nombre=_nombre(e.docentes[4]))
        db_session.expire_all()
        assert _vigentes(db_session, e.proc.id)["vocal"] == e.docentes[2].id

    def test_fuera_de_alcance(self, db_session, esc, otro_depto):
        e = esc()
        _asignar(db_session, e)
        with pytest.raises(ValueError) as exc:
            SynodalService.replace(db_session, e.proc, otro_depto().jefe.id, role="vocal",
                                   new_user_id=e.docentes[4].id, reason="Licencia")
        assert str(exc.value) == OUT_OF_SCOPE_MSG

    def test_relectura_bajo_el_candado(self, db_session, esc, rollbacks):
        """Dos sustituciones de la misma posición a la vez: la segunda todavía
        ve en memoria al vocal original. Bajo el candado relee y descubre que
        su «saliente» ya no es el vigente: deshace sin escribir."""
        from itcj2.apps.titulatec.models import SynodalAssignment
        e = esc()
        _asignar(db_session, e)
        original = (db_session.query(SynodalAssignment)
                    .filter_by(process_id=e.proc.id, role="vocal").one())
        SynodalService.replace(db_session, e.proc, e.jefe.id, role="vocal",
                               new_user_id=e.docentes[4].id, reason="Primera")
        set_committed_value(original, "is_active", True)          # lo que vio la 2.ª
        set_committed_value(e.proc, "synodal_assignments",
                            [f for f in _filas(db_session, e.proc.id)
                             if f.role != "vocal" or f.id == original.id])
        rollbacks.clear()

        with pytest.raises(ValueError) as exc:
            SynodalService.replace(db_session, e.proc, e.coord.id, role="vocal",
                                   new_user_id=e.docentes[4].id, reason="Segunda")

        assert str(exc.value) == SAME_PERSON_MSG.format(nombre=_nombre(e.docentes[4]),
                                                        posicion="Vocal")
        assert rollbacks == [1]
        db_session.expire_all()
        assert len(_eventos(db_session, e.proc.id, "synodal_replaced")) == 1
        assert _vigentes(db_session, e.proc.id)["vocal"] == e.docentes[4].id


# ---------------------------------------------------------------------------
# Lecturas
# ---------------------------------------------------------------------------
class TestLeyendaSinSinodales:
    """Hallazgo 8: «Todavía no se asignan» solo cuando de verdad falta
    asignarlos; EGEL salta la fase y con el corte la fase no está en la app."""

    def test_por_asignar(self, db_session, esc):
        e = esc()
        assert SynodalService.empty_label(db_session, e.proc) == PENDING_LABEL

    def test_la_modalidad_salta_la_fase_4(self, db_session, esc, make_modality, corte):
        e = esc()
        egel = make_modality(name="EGEL de prueba", requires_synodals=False,
                             skips_phases=[4, 5])
        e.proc.modality_id = egel.id
        db_session.flush()
        db_session.expire(e.proc)
        assert SynodalService.empty_label(db_session, e.proc) == NOT_APPLICABLE_LABEL
        corte(3)   # «no aplica» gana: es un hecho de la modalidad, no del corte
        assert SynodalService.empty_label(db_session, e.proc) == NOT_APPLICABLE_LABEL

    def test_la_fase_ya_marcada_como_saltada(self, db_session, esc):
        from itcj2.apps.titulatec.models import ProcessPhase
        e = esc(current_phase=6)
        (db_session.query(ProcessPhase).filter_by(process_id=e.proc.id, phase_number=4)
         .one()).status = "skipped"
        db_session.flush()
        assert SynodalService.empty_label(db_session, e.proc) == NOT_APPLICABLE_LABEL

    def test_con_el_corte_la_fase_no_esta_en_la_app(self, db_session, esc, corte):
        e = esc()
        corte(3)
        assert SynodalService.empty_label(db_session, e.proc) == NOT_IN_APP_LABEL
        corte(4)
        assert SynodalService.empty_label(db_session, e.proc) == NOT_IN_APP_LABEL


class TestLecturas:
    def test_active_for_process_en_orden_con_grado_y_cedula(self, db_session, esc):
        from itcj2.apps.titulatec.models import TeacherProfile
        e = esc()
        perfil = db_session.get(TeacherProfile, e.docentes[1].id)
        perfil.academic_degree, perfil.professional_license = "Doctor en Ciencias", "7654321"
        db_session.flush()
        # Se registran en desorden de posición: la lista sale en el orden del oficio.
        SynodalService.assign(db_session, e.proc, e.jefe.id,
                              president_id=e.docentes[3].id, secretary_id=e.docentes[1].id,
                              vocal_id=e.docentes[0].id, alternate_id=e.docentes[2].id)

        activos = SynodalService.active_for_process(db_session, e.proc.id)

        assert [a["role"] for a in activos] == list(ROLES)
        assert [a["role_label"] for a in activos] == [
            "Presidente", "Secretario", "Vocal", "Vocal Suplente"]
        assert [a["user_id"] for a in activos] == [
            e.docentes[3].id, e.docentes[1].id, e.docentes[0].id, e.docentes[2].id]
        secretario = activos[1]
        assert secretario["name"] == _nombre(e.docentes[1])
        assert secretario["academic_degree"] == "Doctor en Ciencias"
        assert secretario["professional_license"] == "7654321"
        assert secretario["assigned_at"] is not None
        assert set(secretario) == {"role", "role_label", "user_id", "name",
                                   "academic_degree", "professional_license", "assigned_at"}

    def test_sin_sinodales(self, db_session, esc):
        e = esc()
        assert SynodalService.active_for_process(db_session, e.proc.id) == []
        assert SynodalService.history(db_session, e.proc.id) == []
        assert SynodalService.last_change_at(db_session, e.proc.id) is None

    def test_last_change_at_es_el_registro_o_la_ultima_sustitucion(self, db_session, esc):
        e = esc()
        _asignar(db_session, e)
        registro = SynodalService.last_change_at(db_session, e.proc.id)
        assert registro == SynodalService.active_for_process(
            db_session, e.proc.id)[0]["assigned_at"]

        SynodalService.replace(db_session, e.proc, e.jefe.id, role="vocal",
                               new_user_id=e.docentes[4].id, reason="Licencia")
        cambio = SynodalService.last_change_at(db_session, e.proc.id)
        (hist,) = SynodalService.history(db_session, e.proc.id)
        assert cambio == hist["replaced_at"] and cambio >= registro

    def test_las_etiquetas_de_posicion(self):
        assert ROLES == ("president", "secretary", "vocal", "alternate")
        assert ROLE_LABELS == {"president": "Presidente", "secretary": "Secretario",
                               "vocal": "Vocal", "alternate": "Vocal Suplente"}
        assert SynodalService.ROLES == ROLES and SynodalService.ROLE_LABELS == ROLE_LABELS


# ---------------------------------------------------------------------------
# Avisos a los sinodales (§11): después del commit, best-effort
# ---------------------------------------------------------------------------
class TestAvisos:
    def test_al_asignar_avisa_a_los_4_despues_del_commit(self, db_session, esc, correos,
                                                         monkeypatch):
        e = esc()
        orden = []
        commit = db_session.commit

        def _commit():
            orden.append("commit")
            return commit()
        monkeypatch.setattr(db_session, "commit", _commit)
        deliver = email_helper.deliver_detailed

        def _deliver(**kw):
            orden.append("correo")
            return deliver(**kw)
        monkeypatch.setattr(email_helper, "deliver_detailed", _deliver)

        _asignar(db_session, e)

        assert orden[0] == "commit", "la asignación commitea antes de avisar"
        assert orden.count("correo") == 4
        ids = [d.id for d in e.docentes[:4]]
        avisos = _avisos(db_session, ids, "SYNODAL_ASSIGNED")
        assert sorted(a.user_id for a in avisos) == sorted(ids)
        assert all(a.data["process_id"] == e.proc.id for a in avisos)
        assert {c["to"] for c in correos.enviados} == {d.email for d in e.docentes[:4]}
        por_buzon = {c["to"]: c for c in correos.enviados}
        presidente = por_buzon[e.docentes[0].email]
        assert presidente["template"] == "synodal_assigned.html"
        contexto = presidente["context"]
        assert contexto["kind"] == "assigned"
        assert contexto["posicion"] == "Presidente"
        assert contexto["nombre"] == _nombre(e.docentes[0])
        assert contexto["alumno"] == "ANA PEREZ"
        assert contexto["control"] == e.alumno.control_number
        assert contexto["carrera"] == CARRERA_OFICIAL
        assert contexto["opcion"] == "Tesis de prueba"
        assert contexto["titulo"] == PROYECTO
        assert contexto["link"].endswith("next=%2Ftitulatec%2F")

    def test_la_opcion_oficial_gana_al_nombre_de_la_modalidad(self, db_session, esc,
                                                             correos):
        e = esc()
        e.modalidad.option_label = "Tesis Profesional"
        db_session.flush()
        _asignar(db_session, e)
        assert {c["context"]["opcion"] for c in correos.enviados} == {"Tesis Profesional"}

    def test_una_falla_de_correo_queda_en_la_bitacora_y_no_revierte(self, db_session, esc,
                                                                    correos):
        e = esc()
        correos.fallan[e.docentes[1].email] = "envio"

        _asignar(db_session, e)

        db_session.expire_all()
        assert e.proc.current_phase == 5
        (falla,) = _acciones(db_session, "synodal.mail_failed")
        assert falla.entity_id == e.docentes[1].id and falla.process_id == e.proc.id
        assert falla.payload == {"kind": "assigned", "error": "envio"}

    def test_si_el_aviso_truena_la_asignacion_sigue(self, db_session, esc, monkeypatch):
        from itcj2.core.services.notification_service import NotificationService
        e = esc()

        def _truena(*_a, **_k):
            raise RuntimeError("Graph caído")
        monkeypatch.setattr(email_helper, "deliver_detailed", _truena)
        monkeypatch.setattr(NotificationService, "create", staticmethod(_truena))

        out = _asignar(db_session, e)

        assert out["next_phase"] == 5
        db_session.expire_all()
        assert len(_vigentes(db_session, e.proc.id)) == 4

    def test_kind_desconocido_es_error_de_programacion(self):
        with pytest.raises(ValueError):
            SynodalService.send_assignment_notices(1, [1], kind="removed")

    @pytest.mark.parametrize("kind", ["assigned", "replaced_in", "replaced_out"])
    def test_la_plantilla_escapa_y_trae_los_datos(self, kind):
        from itcj2.apps.titulatec.pages.nav import titulatec_templates
        html = titulatec_templates.get_template("titulatec/email/synodal_assigned.html").render(
            kind=kind, nombre="<script>x</script>", posicion="Vocal Suplente",
            alumno="ANA PEREZ", control="99000001", carrera=CARRERA_OFICIAL,
            opcion="Tesis Profesional", titulo=PROYECTO,
            link="https://enlinea.invalid/itcj/login?next=%2Ftitulatec%2F")
        assert "<script>x</script>" not in html and "&lt;script&gt;" in html
        for dato in ("Vocal Suplente", "ANA PEREZ", "99000001", CARRERA_OFICIAL,
                     "Tesis Profesional", PROYECTO):
            assert dato in html, (kind, dato)
        assert ("enlinea.invalid" in html) is (kind != "replaced_out")
