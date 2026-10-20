"""Dictamen de la fase 2 desde el panel de Citas, con el checklist al lado.

Hasta ahora el panel solo ofrecia un enlace al expediente. La Tarea 7 hizo que
aprobar la fase 2 se niegue con requisitos pendientes, asi que un boton
«Aprobar» sin checklist al lado obligaria al oficial a irse al expediente y
volver — el viaje que esta tarea elimina.

Las rutas son HERMANAS de las del expediente, no las mismas: estas devuelven
`#appt-shell`. Reusar las de `admin.py` meteria el expediente dentro del panel
de Citas.

Dos correcciones al brief, ambas por como esta escrito el codigo:

* La ficha del alumno (`_appt_attend.html`) solo se incluye cuando la sub-vista
  es `atender` (`appointments_body.html`); `?selected=` a secas pinta la agenda.
  Por eso el helper `_panel` manda `v=atender`.
* El actor SIN el permiso de marcar no puede salir de `make_head`: `make_role`
  es idempotente por NOMBRE y solo ANADE permisos, asi que reusar `ROLE_HEAD`
  le regalaria el `requirement.mark` que la jefa de `esc` ya metio en ese rol.
  Se usa `make_app_user_without_perms`, que tiene su propio rol.
"""
from __future__ import annotations

from urllib.parse import unquote

import pytest

import itcj2.models  # noqa: F401

MARK = "titulatec.process.api.requirement.mark"
APPROVE = "titulatec.process.api.approve_phase"
REJECT = "titulatec.process.api.reject_phase"
READ_ALL = "titulatec.process.api.read.all"
VIEW = "titulatec.appointment.page.list"
FULL = (READ_ALL, VIEW, MARK, APPROVE, REJECT)


def _msg(resp) -> str:
    return unquote(resp.headers.get("X-Tt-Error", ""))


@pytest.fixture()
def esc(db_session, seed_phase_defs, seed_document_types, make_head, make_student,
        make_cohort, make_process, make_program, make_appointment):
    """Cita ya atendida en fase 2, con un requisito obligatorio pendiente.

    El proceso lleva CARRERA a proposito: `process_in_scope` manda un proceso sin
    carrera al cubo «Sin carrera», gateado por `titulatec.officers.api.manage`,
    y la ruta contestaria 404 antes de llegar a lo que se mide.
    """
    from itcj2.apps.titulatec.models import CotejoRequirement

    seed_phase_defs()
    seed_document_types()
    cohort = make_cohort()
    student = make_student()
    program = make_program("Ingenieria Ficticia B")
    process = make_process(student, cohort=cohort, program=program,
                           current_phase=2)
    req = CotejoRequirement(cohort_id=cohort.id, label="e.Firma (SAT)",
                            hint="Constancia vigente.", icon="shield-check",
                            order_index=0, is_required=True, is_active=True,
                            code="efirma")
    db_session.add(req)
    db_session.flush()
    appt = make_appointment(process, status="attended")
    jefa = make_head(perm_codes=FULL)
    return {"cohort": cohort, "process": process, "req": req, "program": program,
            "appt": appt, "jefa": jefa, "student": student}


def _panel(client_as, esc, extra=""):
    """El shell de Citas con la ficha del proceso seleccionada.

    `v=atender` es OBLIGATORIO: `appointments_body.html` solo incluye
    `_appt_attend.html` en esa sub-vista.
    """
    return client_as(esc["jefa"]).get(
        f"/titulatec/admin/appointments/body"
        f"?v=atender&selected={esc['process'].id}{extra}",
        follow_redirects=False)


class TestPanel:
    def test_ya_no_manda_al_expediente_y_ofrece_los_dos_botones(self, client_as, esc):
        """Aprobar es un POST directo; Rechazar es la NAVEGACION a `&rechazar=`,
        que abre el textarea (el `POST .../fase2/rechazar` vive dentro de ese
        modo — lo cubre `TestRechazar`). Por eso aqui se afirma la entrada a
        cada uno, no dos URLs de POST."""
        r = _panel(client_as, esc)
        assert r.status_code == 200
        assert "Ir al proceso a aprobar fase 02" not in r.text
        assert "/fase2/aprobar" in r.text
        assert f"rechazar={esc['process'].id}" in r.text

    def test_pinta_el_checklist_de_su_convocatoria(self, client_as, esc):
        r = _panel(client_as, esc)
        assert "e.Firma (SAT)" in r.text
        assert f'id="appt-req-{esc["req"].id}"' in r.text

    def test_el_checklist_apunta_a_la_ruta_de_citas_no_a_la_del_expediente(
        self, client_as, esc,
    ):
        """La ruta del expediente devuelve `#exp-shell`: cableada aqui, el swap
        meteria el expediente dentro de `#appt-shell`."""
        r = _panel(client_as, esc)
        assert f"/appointments/{esc['process'].id}/requisitos/{esc['req'].id}" in r.text
        assert f"/processes/{esc['process'].id}/requisitos/" not in r.text

    def test_el_contexto_no_lleva_objetos_orm(self, db_session, esc):
        """El harness NO puede observar un DetachedInstanceError: `close()` es un
        no-op. Se afirma la FORMA del contexto, no el sintoma."""
        from itcj2.apps.titulatec.pages.appointments import _detail_ctx
        ctx = _detail_ctx(db_session, esc["process"].id, user_id=esc["jefa"].id)
        assert ctx["requisitos"], "el checklist llego vacio: no se mide nada"
        for fila in ctx["requisitos"]:
            assert isinstance(fila, dict)
            for v in fila.values():
                assert not hasattr(v, "_sa_instance_state"), fila

    def test_el_contexto_trae_las_mismas_claves_que_el_expediente(self, db_session, esc):
        """Mismo contrato de fila, para que la plantilla sea intercambiable."""
        from itcj2.apps.titulatec.pages.appointments import _detail_ctx
        ctx = _detail_ctx(db_session, esc["process"].id, user_id=esc["jefa"].id)
        assert ctx["can_mark_reqs"] is True
        fila = ctx["requisitos"][0]
        assert set(fila) == {"id", "icon", "label", "hint", "required",
                             "auto_source", "done", "status", "source",
                             "note", "when"}
        assert fila["id"] == esc["req"].id
        assert fila["icon"] == "shield-check"
        assert fila["hint"] == "Constancia vigente."
        assert fila["done"] is False and fila["status"] is None

    def test_sin_usuario_no_revienta(self, db_session, esc):
        """`user_id=None` sale por el alcance, NO por un `TypeError` dentro del
        calculo de permisos: el contrato dice que ese caso pinta apagado."""
        from itcj2.apps.titulatec.pages.appointments import _detail_ctx
        assert _detail_ctx(db_session, esc["process"].id, user_id=None) is None

    def test_quien_no_puede_marcar_no_ve_los_controles(
        self, db_session, client_as, esc, make_app_user_without_perms,
    ):
        """Un boton que contesta 403 es peor que no estar. El actor lleva
        `read.all`, asi que SI ve la ficha: lo unico que le falta es marcar."""
        from itcj2.apps.titulatec.pages.appointments import _detail_ctx

        miron = make_app_user_without_perms((READ_ALL, VIEW))
        ctx = _detail_ctx(db_session, esc["process"].id, user_id=miron.id)
        assert ctx is not None and ctx["can_mark_reqs"] is False

        r = client_as(miron).get(
            f"/titulatec/admin/appointments/body"
            f"?v=atender&selected={esc['process'].id}", follow_redirects=False)
        assert r.status_code == 200
        assert "e.Firma (SAT)" in r.text, "el checklist debe verse, aunque apagado"
        assert f"/requisitos/{esc['req'].id}" not in r.text


class TestMarcar:
    def test_marca_y_el_panel_lo_refleja(self, client_as, esc):
        r = client_as(esc["jefa"]).post(
            f"/titulatec/admin/appointments/{esc['process'].id}/requisitos/{esc['req'].id}",
            data={"action": "mark", "note": "Trajo la constancia."})
        assert r.status_code == 200
        assert "appt-shell" in r.text
        assert "exp-shell" not in r.text

        from itcj2.apps.titulatec.models import RequirementFulfillment
        from itcj2.database import SessionLocal
        db = SessionLocal()
        fila = (db.query(RequirementFulfillment)
                .filter_by(process_id=esc["process"].id,
                           requirement_id=esc["req"].id).first())
        assert fila is not None and fila.status == "fulfilled"
        assert fila.checked_by_id == esc["jefa"].id

    def test_desmarca(self, client_as, esc):
        c = client_as(esc["jefa"])
        url = (f"/titulatec/admin/appointments/{esc['process'].id}"
               f"/requisitos/{esc['req'].id}")
        c.post(url, data={"action": "mark"})
        r = c.post(url, data={"action": "unmark"})
        assert r.status_code == 200

        from itcj2.apps.titulatec.models import RequirementFulfillment
        from itcj2.database import SessionLocal
        db = SessionLocal()
        fila = (db.query(RequirementFulfillment)
                .filter_by(process_id=esc["process"].id,
                           requirement_id=esc["req"].id).first())
        assert fila is None or fila.status not in ("fulfilled", "waived")

    def test_requisito_de_otra_convocatoria_no_se_marca(self, client_as, esc,
                                                        make_cohort, db_session):
        from itcj2.apps.titulatec.models import CotejoRequirement
        ajeno = CotejoRequirement(cohort_id=make_cohort().id, label="Ajeno",
                                  order_index=0, is_required=True, is_active=True)
        db_session.add(ajeno)
        db_session.flush()

        r = client_as(esc["jefa"]).post(
            f"/titulatec/admin/appointments/{esc['process'].id}/requisitos/{ajeno.id}",
            data={"action": "mark"})
        assert r.status_code == 400
        assert _msg(r)

    def test_requisito_automatico_es_de_solo_lectura(self, client_as, esc, db_session):
        from itcj2.apps.titulatec.models import CotejoRequirement
        auto = CotejoRequirement(cohort_id=esc["cohort"].id, label="Encuesta",
                                 order_index=1, is_required=True, is_active=True,
                                 auto_source="graduate_survey")
        db_session.add(auto)
        db_session.flush()

        r = client_as(esc["jefa"]).post(
            f"/titulatec/admin/appointments/{esc['process'].id}/requisitos/{auto.id}",
            data={"action": "mark"})
        assert r.status_code == 400
        assert "sistema" in _msg(r)

    def test_sin_el_permiso_de_marcar_no_pasa(self, client_as, esc,
                                              make_app_user_without_perms):
        """Par negativo/positivo sobre la MISMA ruta y el MISMO recurso.

        `make_app_user_without_perms` y no `make_head`: aquel tiene su propio rol
        y `make_role` nunca revoca (conftest.py:265-286).
        """
        otro = make_app_user_without_perms((READ_ALL, VIEW, APPROVE, REJECT))
        url = (f"/titulatec/admin/appointments/{esc['process'].id}"
               f"/requisitos/{esc['req'].id}")

        r_no = client_as(otro).post(url, data={"action": "mark"},
                                    follow_redirects=False)
        r_si = client_as(esc["jefa"]).post(url, data={"action": "mark"},
                                           follow_redirects=False)

        assert r_no.status_code == 403, (
            f"la ruta contesto {r_no.status_code} a quien NO tiene {MARK}. "
            f"Si es 200, alguien amplio la lista de permisos.")
        assert r_si.status_code == 200, r_si.text[:300]


class TestAprobar:
    def test_con_requisito_pendiente_se_niega_y_dice_cual(self, client_as, esc):
        r = client_as(esc["jefa"]).post(
            f"/titulatec/admin/appointments/{esc['process'].id}/fase2/aprobar")
        assert r.status_code == 400
        assert "e.Firma (SAT)" in _msg(r)

    def test_marcando_primero_ya_aprueba(self, client_as, esc):
        c = client_as(esc["jefa"])
        c.post(f"/titulatec/admin/appointments/{esc['process'].id}/requisitos/{esc['req'].id}",
               data={"action": "mark"})
        r = c.post(f"/titulatec/admin/appointments/{esc['process'].id}/fase2/aprobar")
        assert r.status_code == 200
        assert "appt-shell" in r.text
        assert "exp-shell" not in r.text

        from itcj2.database import SessionLocal
        from itcj2.apps.titulatec.models import TitulationProcess
        db = SessionLocal()
        assert db.get(TitulationProcess, esc["process"].id).current_phase == 3

    def test_sin_el_permiso_de_aprobar_no_pasa(self, client_as, esc,
                                               make_app_user_without_perms):
        """`require_page_app(perms=[...])` es OR: un codigo de mas regala la
        feature a quien lo tenga."""
        otro = make_app_user_without_perms((READ_ALL, VIEW, MARK, REJECT))
        r = client_as(otro).post(
            f"/titulatec/admin/appointments/{esc['process'].id}/fase2/aprobar",
            follow_redirects=False)
        assert r.status_code == 403


class TestRechazar:
    def test_sin_motivo_no_rechaza(self, client_as, esc):
        r = client_as(esc["jefa"]).post(
            f"/titulatec/admin/appointments/{esc['process'].id}/fase2/rechazar",
            data={"reason": "   "})
        assert r.status_code == 400
        assert _msg(r)

        from itcj2.database import SessionLocal
        from itcj2.apps.titulatec.models import ProcessPhase
        db = SessionLocal()
        ph = (db.query(ProcessPhase)
              .filter_by(process_id=esc["process"].id, phase_number=2).first())
        assert ph.status != "rejected", "rechazo sin motivo: el alumno no sabe que corregir"

    def test_con_motivo_rechaza(self, client_as, esc):
        r = client_as(esc["jefa"]).post(
            f"/titulatec/admin/appointments/{esc['process'].id}/fase2/rechazar",
            data={"reason": "Le falto el acta certificada."})
        assert r.status_code == 200
        assert "appt-shell" in r.text
        assert "exp-shell" not in r.text

        from itcj2.database import SessionLocal
        from itcj2.apps.titulatec.models import ProcessPhase
        db = SessionLocal()
        ph = (db.query(ProcessPhase)
              .filter_by(process_id=esc["process"].id, phase_number=2).first())
        assert ph.status == "rejected"
        assert ph.rejection_reason == "Le falto el acta certificada."

    def test_rechaza_aunque_falte_un_requisito(self, client_as, esc):
        """`reject_phase` NO consulta el checklist a proposito (Tarea 7)."""
        r = client_as(esc["jefa"]).post(
            f"/titulatec/admin/appointments/{esc['process'].id}/fase2/rechazar",
            data={"reason": "No trajo nada."})
        assert r.status_code == 200

    def test_el_modo_rechazo_abre_el_textarea_en_el_panel(self, client_as, esc):
        r = _panel(client_as, esc, extra=f"&rechazar={esc['process'].id}")
        assert r.status_code == 200
        assert 'name="reason"' in r.text
        assert "/fase2/rechazar" in r.text

    def test_sin_el_modo_rechazo_no_hay_textarea(self, client_as, esc):
        """El par positivo del anterior: sin `&rechazar=` el textarea no esta."""
        assert 'name="reason"' not in _panel(client_as, esc).text

    def test_tras_rechazar_el_panel_ya_no_ofrece_el_textarea(self, client_as, esc):
        """`_action_ctx` descarta `rechazar` por lo mismo que descarta `mover`:
        es un estado de «estoy a mitad de una accion» y la accion termino."""
        r = client_as(esc["jefa"]).post(
            f"/titulatec/admin/appointments/{esc['process'].id}/fase2/rechazar"
            f"?v=atender&rechazar={esc['process'].id}",
            data={"reason": "Le falto el acta certificada."})
        assert r.status_code == 200
        assert 'name="reason"' not in r.text

    def test_sin_el_permiso_de_rechazar_no_pasa(self, client_as, esc,
                                                make_app_user_without_perms):
        otro = make_app_user_without_perms((READ_ALL, VIEW, MARK, APPROVE))
        r = client_as(otro).post(
            f"/titulatec/admin/appointments/{esc['process'].id}/fase2/rechazar",
            data={"reason": "x"}, follow_redirects=False)
        assert r.status_code == 403


class TestAlcance:
    def test_fuera_de_carrera_da_404_limpio(self, client_as, esc, make_officer):
        """El encargado SI trae los tres permisos: asi el 404 solo puede venir
        del guard de carrera, no de `require_page_app`."""
        from tests.fastapi.titulatec.conftest import OFFICER_PERMS

        oficial, _pos = make_officer(
            programs=[], perm_codes=OFFICER_PERMS + (MARK, APPROVE, REJECT))
        for url in (f"/titulatec/admin/appointments/{esc['process'].id}"
                    f"/requisitos/{esc['req'].id}",
                    f"/titulatec/admin/appointments/{esc['process'].id}/fase2/aprobar",
                    f"/titulatec/admin/appointments/{esc['process'].id}/fase2/rechazar"):
            r = client_as(oficial).post(url, data={"reason": "x", "action": "mark"},
                                        follow_redirects=False)
            assert r.status_code == 404, f"[{url}] respondio {r.status_code}"
            assert not r.headers.get("X-Tt-Error"), "el 404 no debe llevar oraculo"

    def test_en_su_carrera_el_mismo_encargado_si_pasa(self, client_as, esc, make_officer):
        """La asercion negativa no va sola: mismo actor, misma ruta, 200."""
        from tests.fastapi.titulatec.conftest import OFFICER_PERMS

        oficial, _pos = make_officer(
            programs=[esc["program"]], perm_codes=OFFICER_PERMS + (MARK, APPROVE, REJECT))
        r = client_as(oficial).post(
            f"/titulatec/admin/appointments/{esc['process'].id}"
            f"/requisitos/{esc['req'].id}",
            data={"action": "mark"}, follow_redirects=False)
        assert r.status_code == 200, r.text[:300]
