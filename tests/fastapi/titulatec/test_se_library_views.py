"""Servicios Escolares (SE): donación voluntaria de libro por convocatoria,
fila de solo lectura del no adeudo (panel de atender + expediente) y
respaldo «Constancia previa…» / «Deshacer» (D9) desde esas dos pantallas.

Spec `docs/superpowers/specs/2026-10-01-titulatec-biblioteca-caja-design.md`
§4.9 (SE), D5 (donación), D9 (constancia previa), D19 (donación obligatoria
al alta) y §5 invariante 6 (rutas de SE con `{process_id}` +
`assert_process_in_scope`). Tarea 11 del plan 2026-10-01-titulatec-
biblioteca-caja.

Ya construido y NO se vuelve a probar aquí: `LibraryClearanceService.
summary_for_process` / `for_process_locked` / `register_prior` /
`undo_prior` (`test_library_clearance_service.py`), `ClearanceGate`
(`test_clearance_gate.py`), la píldora `library_clearance_pill`
(`test_clearance_gate.py`, sección 9), el formato `parse_amount`/
`format_amount` (`test_library_clearance_service.py`).

El censo estructural de `test_scope_guard.py` (`test_toda_ruta_con_process_id_
invoca_el_guard`) es quien garantiza que las 4 rutas nuevas de respaldo
llaman `assert_process_in_scope` como primera sentencia del `try`; aquí solo
se ejercita el comportamiento (200/400/403/404).
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import unquote

import pytest

import itcj2.models  # noqa: F401

from tests.fastapi.titulatec.conftest import HEAD_PERMS, OFFICER_PERMS

# Servicios Escolares: alta/edición de convocatoria + respaldo de constancia
# previa. Los tres códigos nuevos (`cohort.api.create/update` ya existían;
# `library_clearance.api.prior` lo otorga el DML de la Tarea 6 a los dos
# roles de SE) -- aquí se arman a mano porque `HEAD_PERMS` no los trae.
SE_PERMS = HEAD_PERMS + (
    "titulatec.cohort.api.create", "titulatec.cohort.api.update",
    "titulatec.library_clearance.api.prior",
)


def _msg(resp) -> str:
    return unquote(resp.headers.get("X-Tt-Error", ""))


def _notice(resp) -> str:
    return unquote(resp.headers.get("X-Tt-Notice", ""))


@pytest.fixture()
def se(make_head):
    """Servicios Escolares sintética: ve TODO (`process.api.read.all` de
    `HEAD_PERMS`) + los tres permisos de esta tarea."""
    return make_head(perm_codes=SE_PERMS)


# ===========================================================================
# 1. Donación voluntaria de libro AL ALTA de la convocatoria (D5, D19)
# ===========================================================================
class TestDonacionAlAlta:
    def test_sin_donacion_no_crea_y_vuelve_con_el_aviso(
        self, db_session, client_as, se, make_period,
    ):
        from itcj2.apps.titulatec.models import Cohort

        periodo = make_period()

        resp = client_as(se).post(
            "/titulatec/admin/cohorts",
            data={"period_id": periodo.id, "opens_date": "2031-03-10",
                 "closes_date": "2031-03-20"},
            follow_redirects=False)

        assert resp.status_code == 303, resp.text[:300]
        assert resp.headers["location"] == "/titulatec/admin/cohorts?error=donacion"
        assert db_session.query(Cohort).filter_by(period_id=periodo.id).count() == 0

    @pytest.mark.parametrize("monto", ["", "-5", "abc", "100001"],
                            ids=["vacio", "negativo", "basura", "sobre-tope"])
    def test_donacion_invalida_no_crea(
        self, db_session, client_as, se, make_period, monto,
    ):
        from itcj2.apps.titulatec.models import Cohort

        periodo = make_period()

        resp = client_as(se).post(
            "/titulatec/admin/cohorts",
            data={"period_id": periodo.id, "opens_date": "2031-03-10",
                 "closes_date": "2031-03-20", "book_donation": monto},
            follow_redirects=False)

        assert resp.status_code == 303, resp.text[:300]
        assert resp.headers["location"] == "/titulatec/admin/cohorts?error=donacion"
        assert db_session.query(Cohort).filter_by(period_id=periodo.id).count() == 0

    def test_con_donacion_valida_la_congela_en_la_convocatoria(
        self, db_session, client_as, se, make_period,
    ):
        from itcj2.apps.titulatec.models import Cohort

        periodo = make_period()

        resp = client_as(se).post(
            "/titulatec/admin/cohorts",
            data={"period_id": periodo.id, "opens_date": "2031-03-10",
                 "closes_date": "2031-03-20", "book_donation": "1,200.50"},
            follow_redirects=False)

        assert resp.status_code == 303, resp.text[:300]
        assert resp.headers["location"] == "/titulatec/admin/cohorts"
        cohort = db_session.query(Cohort).filter_by(period_id=periodo.id).one()
        assert cohort.book_donation_amount == Decimal("1200.50")

    def test_la_ventana_invalida_sigue_mandando_a_error_ventana(
        self, db_session, client_as, se, make_period,
    ):
        """La donación no desplaza la validación existente de la ventana: si
        las dos fallan, gana la ventana (se revisa primero, igual que antes
        de esta tarea)."""
        from itcj2.apps.titulatec.models import Cohort

        periodo = make_period()

        resp = client_as(se).post(
            "/titulatec/admin/cohorts",
            data={"period_id": periodo.id, "book_donation": "800.00"},
            follow_redirects=False)

        assert resp.status_code == 303
        assert resp.headers["location"] == "/titulatec/admin/cohorts?error=ventana"
        assert db_session.query(Cohort).filter_by(period_id=periodo.id).count() == 0


# ===========================================================================
# 2. Donación EDITABLE en el panel Resumen (D5), con aviso de afectados
# ===========================================================================
class TestDonacionEditable:
    def test_se_edita_la_donacion_sin_afectados(
        self, db_session, client_as, se, make_cohort,
    ):
        cohort = make_cohort(book_donation_amount=Decimal("500.00"))

        resp = client_as(se).post(
            f"/titulatec/admin/cohorts/{cohort.id}/donacion",
            data={"book_donation": "900.00"})

        assert resp.status_code == 200, resp.text[:300]
        db_session.refresh(cohort)
        assert cohort.book_donation_amount == Decimal("900.00")
        assert _notice(resp) == "Donación guardada."
        assert resp.headers.get("X-Tt-Notice-Kind") == "success"

    def test_editar_con_casos_en_caja_avisa_cuantos_no_cambian(
        self, db_session, client_as, se, seed_phase_defs, seed_document_types,
        make_program, make_cohort, make_student, make_process,
    ):
        """Review Focus #2: el monto ya congelado en `LibraryClearance` NO se
        mueve al cambiar la donación de la convocatoria, y el aviso cuenta a
        los afectados."""
        from itcj2.apps.titulatec.services.cotejo_requirement_service import (
            CotejoRequirementService,
        )
        from itcj2.apps.titulatec.services.library_clearance_service import (
            LibraryClearanceService,
        )

        seed_phase_defs()
        seed_document_types()
        prog = make_program("Ingenieria de la Donacion")
        cohort = make_cohort(book_donation_amount=Decimal("500.00"))
        CotejoRequirementService.seed_defaults(db_session, cohort.id, commit=False)
        db_session.flush()
        proc = make_process(make_student(), cohort=cohort, program=prog,
                            current_phase=2, library_clearance="pending")
        clearance = LibraryClearanceService.get_for_process(db_session, proc.id)
        LibraryClearanceService.register(db_session, clearance.id, se.id,
                                         debt_amount=Decimal("400.00"))
        assert clearance.donation_amount == Decimal("500.00")

        resp = client_as(se).post(
            f"/titulatec/admin/cohorts/{cohort.id}/donacion",
            data={"book_donation": "900.00"})

        assert resp.status_code == 200, resp.text[:300]
        db_session.refresh(cohort)
        assert cohort.book_donation_amount == Decimal("900.00")
        db_session.refresh(clearance)
        assert clearance.donation_amount == Decimal("500.00"), (
            "el monto ya congelado no cambia al editar la donación")
        aviso = _notice(resp)
        assert "1 egresado" in aviso and "ya tiene" in aviso
        assert "no cambia para ellos" in aviso and "Biblioteca puede corregir" in aviso
        assert resp.headers.get("X-Tt-Notice-Kind") == "warning"

    def test_monto_invalido_400_sin_tocar_nada(self, db_session, client_as, se, make_cohort):
        cohort = make_cohort(book_donation_amount=Decimal("500.00"))

        resp = client_as(se).post(
            f"/titulatec/admin/cohorts/{cohort.id}/donacion",
            data={"book_donation": "-10"})

        assert resp.status_code == 400, resp.text[:300]
        assert "negativo" in _msg(resp)
        db_session.refresh(cohort)
        assert cohort.book_donation_amount == Decimal("500.00")

    def test_convocatoria_inexistente_404(self, client_as, se):
        resp = client_as(se).post(
            "/titulatec/admin/cohorts/987654321/donacion",
            data={"book_donation": "900.00"})

        assert resp.status_code == 404

    def test_sin_permiso_403(self, client_as, make_cohort, make_app_user_without_perms):
        cohort = make_cohort(book_donation_amount=Decimal("500.00"))
        quien = make_app_user_without_perms()

        resp = client_as(quien).post(
            f"/titulatec/admin/cohorts/{cohort.id}/donacion",
            data={"book_donation": "900.00"})

        assert resp.status_code == 403


# ===========================================================================
# 3. Fila `library_clearance` de SOLO LECTURA (panel de atender + expediente)
# ===========================================================================
@pytest.fixture()
def caso(db_session, seed_phase_defs, seed_document_types, make_program, make_cohort,
        make_review_day, make_review_window, make_officer, make_student, make_process,
        make_library_clearance, make_appointment):
    """Convocatoria CON el candado de biblioteca (`seed_defaults`) y un
    egresado «Por pagar en Caja» ($400 adeudo + $800 donación = $1,200), YA
    con una cita `attended` vigente -el no adeudo puede seguir pendiente con
    una cita viva (D17): su cita vieja no se toca-. `attended` y no
    `scheduled`: el checklist de requisitos (`_appt_attend.html`) SOLO se
    pinta tras el cotejo (`detail.appt.status == 'attended'`); sin cita
    vigente el panel tampoco lo deja seleccionar (`?selected=` solo alcanza
    la agenda, `pages/appointments.py::_shell_ctx`)."""
    from itcj2.apps.titulatec.services.cotejo_requirement_service import (
        CotejoRequirementService,
    )
    from itcj2.core.utils.timezone import db_now

    seed_phase_defs()
    seed_document_types()
    prog = make_program("Ingenieria de la Fila de Biblioteca")
    cohort = make_cohort(book_donation_amount=Decimal("800.00"))
    CotejoRequirementService.seed_defaults(db_session, cohort.id, commit=False)
    db_session.flush()
    dia = make_review_day(cohort, day=date.today() + timedelta(days=7))
    officer, pos = make_officer([prog])
    window = make_review_window(dia, officer, start="09:00", end="11:00",
                                slot=30, cap=1, position=pos)
    proc = make_process(make_student(), cohort=cohort, program=prog,
                        current_phase=2, library_clearance=None)
    make_library_clearance(proc, status="awaiting_payment",
                           debt_amount=Decimal("400.00"), donation_amount=Decimal("800.00"),
                           total_amount=Decimal("1200.00"), ready_at=db_now())
    appt = make_appointment(proc, status="attended", is_current=True)
    return {"prog": prog, "cohort": cohort, "officer": officer, "window": window,
            "proc": proc, "dia": dia, "appt": appt}


class TestFilaDeSoloLectura:
    def test_ya_no_imprime_el_codigo_crudo_en_atender(self, client_as, caso):
        resp = client_as(caso["officer"]).get(
            f"/titulatec/admin/appointments/body?v=atender&selected={caso['proc'].id}")

        assert resp.status_code == 200, resp.text[:300]
        assert "Lo acredita el sistema (library_clearance)" not in resp.text

    def test_pinta_la_pildora_y_el_total_por_cobrar_en_atender(self, client_as, caso):
        resp = client_as(caso["officer"]).get(
            f"/titulatec/admin/appointments/body?v=atender&selected={caso['proc'].id}")

        assert resp.status_code == 200
        assert "Por pagar en Caja" in resp.text
        assert "$1,200.00" in resp.text

    def test_ya_no_imprime_el_codigo_crudo_en_expediente(self, client_as, caso):
        resp = client_as(caso["officer"]).get(
            f"/titulatec/admin/processes/{caso['proc'].id}")

        assert resp.status_code == 200, resp.text[:300]
        assert "Lo acredita el sistema (library_clearance)" not in resp.text
        assert "Por pagar en Caja" in resp.text

    def test_liberado_por_pago_muestra_total_recibo_y_constancia(
        self, client_as, db_session, caso,
    ):
        from itcj2.apps.titulatec.services.library_clearance_service import (
            LibraryClearanceService,
        )

        clearance = LibraryClearanceService.get_for_process(db_session, caso["proc"].id)
        LibraryClearanceService.register_payment(
            db_session, clearance.id, caso["officer"].id, receipt_number="R-0099")

        resp = client_as(caso["officer"]).get(
            f"/titulatec/admin/processes/{caso['proc'].id}")

        assert resp.status_code == 200, resp.text[:300]
        assert "$1,200.00" in resp.text
        assert "R-0099" in resp.text
        assert "BIB-" in resp.text


# ===========================================================================
# 4. Respaldo «Constancia previa…» / «Deshacer» (D9), con `library_clearance.
#    api.prior`, desde el panel de atender y desde el expediente
# ===========================================================================
class TestRespaldoConstanciaPrevia:
    def test_se_registra_desde_el_expediente(self, client_as, db_session, se, caso):
        from itcj2.apps.titulatec.services.library_clearance_service import (
            LibraryClearanceService,
        )

        resp = client_as(se).post(
            f"/titulatec/admin/processes/{caso['proc'].id}/no-adeudo-previo",
            data={"issued_on": date.today().isoformat(), "note": "Trae su recibo"})

        assert resp.status_code == 200, resp.text[:300]
        clearance = LibraryClearanceService.get_for_process(db_session, caso["proc"].id)
        assert clearance.status == "cleared" and clearance.cleared_via == "prior"
        assert clearance.prior_by_id == se.id

    def test_se_registra_desde_el_panel_de_atender(self, client_as, db_session, se, caso):
        from itcj2.apps.titulatec.services.library_clearance_service import (
            LibraryClearanceService,
        )

        resp = client_as(se).post(
            f"/titulatec/admin/appointments/{caso['proc'].id}/no-adeudo-previo",
            data={"issued_on": date.today().isoformat()})

        assert resp.status_code == 200, resp.text[:300]
        clearance = LibraryClearanceService.get_for_process(db_session, caso["proc"].id)
        assert clearance.status == "cleared" and clearance.cleared_via == "prior"

    def test_se_deshace_desde_el_expediente(self, client_as, db_session, se, caso):
        from itcj2.apps.titulatec.services.library_clearance_service import (
            LibraryClearanceService,
        )

        clearance = LibraryClearanceService.get_for_process(db_session, caso["proc"].id)
        LibraryClearanceService.register_prior(db_session, clearance.id, se.id,
                                               issued_on=date.today(), by="school_services")

        resp = client_as(se).post(
            f"/titulatec/admin/processes/{caso['proc'].id}/no-adeudo-previo/deshacer",
            data={"reason": "Se equivocó de alumno"})

        assert resp.status_code == 200, resp.text[:300]
        db_session.refresh(clearance)
        assert clearance.status == "pending"

    def test_se_deshace_desde_el_panel_de_atender(self, client_as, db_session, se, caso):
        from itcj2.apps.titulatec.services.library_clearance_service import (
            LibraryClearanceService,
        )

        clearance = LibraryClearanceService.get_for_process(db_session, caso["proc"].id)
        LibraryClearanceService.register_prior(db_session, clearance.id, se.id,
                                               issued_on=date.today(), by="school_services")

        resp = client_as(se).post(
            f"/titulatec/admin/appointments/{caso['proc'].id}/no-adeudo-previo/deshacer",
            data={"reason": "Se equivocó de alumno"})

        assert resp.status_code == 200, resp.text[:300]
        db_session.refresh(clearance)
        assert clearance.status == "pending"

    def test_sin_permiso_403_en_expediente(self, client_as, caso, make_officer):
        otro, _pos = make_officer([caso["prog"]])  # OFFICER_PERMS, sin el de respaldo

        resp = client_as(otro).post(
            f"/titulatec/admin/processes/{caso['proc'].id}/no-adeudo-previo",
            data={"issued_on": date.today().isoformat()})

        assert resp.status_code == 403

    def test_sin_permiso_403_en_atender(self, client_as, caso, make_officer):
        otro, _pos = make_officer([caso["prog"]])

        resp = client_as(otro).post(
            f"/titulatec/admin/appointments/{caso['proc'].id}/no-adeudo-previo",
            data={"issued_on": date.today().isoformat()})

        assert resp.status_code == 403

    def test_404_fuera_de_alcance(self, client_as, caso, make_officer, make_program):
        """`se` ve TODO (jefa); un encargado acotado a OTRA carrera, aunque
        tenga el permiso de respaldo, no alcanza el proceso de `caso`."""
        ajena = make_program("Ingenieria Ajena al Respaldo")
        otro, _pos = make_officer([ajena], perm_codes=OFFICER_PERMS + (
            "titulatec.library_clearance.api.prior",))

        resp = client_as(otro).post(
            f"/titulatec/admin/processes/{caso['proc'].id}/no-adeudo-previo",
            data={"issued_on": date.today().isoformat()})

        assert resp.status_code == 404

    def test_fecha_futura_400(self, client_as, caso, se):
        resp = client_as(se).post(
            f"/titulatec/admin/processes/{caso['proc'].id}/no-adeudo-previo",
            data={"issued_on": (date.today() + timedelta(days=1)).isoformat()})

        assert resp.status_code == 400, resp.text[:300]
        assert "futura" in _msg(resp)
