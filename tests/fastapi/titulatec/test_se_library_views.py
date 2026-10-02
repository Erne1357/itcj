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

Secciones 6-7 (Tarea 4 de `2026-10-02-titulatec-constancias-y-pendientes-
design.md` §3.4): la celda «Constancia» (`certificate_cell`, Tarea 3) junto a
las dos filas -encuesta y no adeudo- en estas MISMAS dos pantallas, y m42
(`triage-minors.md`): un proceso revocado con el no adeudo todavía
`missing`/`pending` -o `awaiting_payment`, Ruling R15, sin el sufijo «Por
cobrar»- pinta «Revocada», nunca «En Biblioteca» ni «Por pagar en Caja». De
la revisión final, en las mismas dos pantallas: una constancia vigente sin
lote de un revocado pinta la píldora «No se imprimirá» y la nota tenue
«inscripción revocada» (Rulings R13 y R18), ninguna ofrece «Constancia
previa…» a un revocado (M2) y las dos celdas salen de UNA llamada a
`print_status_map` por vista, a lo más 2 consultas de constancias (Rulings
R14 y R17, sección 9).
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import unquote

import pytest

import itcj2.models  # noqa: F401

from tests.fastapi.titulatec.conftest import HEAD_PERMS, OFFICER_PERMS

NOTIFY = "itcj2.apps.titulatec.services.notify.notify_student"

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

    def test_editar_con_un_caso_revocado_no_lo_cuenta_como_afectado(
        self, db_session, client_as, se, seed_phase_defs, seed_document_types,
        make_program, make_cohort, make_student, make_process,
    ):
        """m35 (triage-minors.md): el conteo de «afectados» debe filtrar los
        MISMOS estados admitidos que usa `LibraryClearanceService`
        (`ADMITTED_PROCESS_STATUSES`, importada de ese módulo -no
        duplicada-): un proceso REVOCADO con el monto YA congelado (se le
        registró el adeudo ANTES de revocarse) no es un caso vivo que
        Biblioteca vaya a corregir, así que no debe sumar al aviso -control
        positivo al lado (test anterior): un proceso admitido SÍ cuenta."""
        from itcj2.apps.titulatec.services.cotejo_requirement_service import (
            CotejoRequirementService,
        )
        from itcj2.apps.titulatec.services.library_clearance_service import (
            LibraryClearanceService,
        )

        seed_phase_defs()
        seed_document_types()
        prog = make_program("Ingenieria de la Donacion Revocada")
        cohort = make_cohort(book_donation_amount=Decimal("500.00"))
        CotejoRequirementService.seed_defaults(db_session, cohort.id, commit=False)
        db_session.flush()
        proc = make_process(make_student(), cohort=cohort, program=prog,
                            current_phase=2, library_clearance="pending")
        clearance = LibraryClearanceService.get_for_process(db_session, proc.id)
        LibraryClearanceService.register(db_session, clearance.id, se.id,
                                         debt_amount=Decimal("400.00"))
        assert clearance.donation_amount == Decimal("500.00")
        proc.status = "cancelled"          # se revocó DESPUÉS de congelar el monto
        db_session.flush()

        resp = client_as(se).post(
            f"/titulatec/admin/cohorts/{cohort.id}/donacion",
            data={"book_donation": "900.00"})

        assert resp.status_code == 200, resp.text[:300]
        db_session.refresh(cohort)
        assert cohort.book_donation_amount == Decimal("900.00")
        assert _notice(resp) == "Donación guardada.", (
            "un proceso revocado no debe aparecer en el aviso de afectados")
        assert resp.headers.get("X-Tt-Notice-Kind") == "success"

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


# ===========================================================================
# 5. Ruling R21 (I3 de la revisión final): un egresado que YA pasó su cotejo
#    (fase 2 aprobada) sin no adeudo liberado -el backfill lo saltó- muestra
#    «No aplica (cotejo ya liberado)» y NO ofrece «Constancia previa…»
# ===========================================================================
@pytest.fixture()
def cotejado(db_session, seed_phase_defs, seed_document_types, make_program, make_cohort,
             make_officer, make_student, make_process, make_appointment):
    """Convocatoria CON candado y un egresado en la fase 3 (la 2 quedó
    `approved`) SIN fila de no adeudo, con su cita `attended` vigente (así lo
    alcanza la ficha de atender)."""
    from itcj2.apps.titulatec.services.cotejo_requirement_service import (
        CotejoRequirementService,
    )

    seed_phase_defs()
    seed_document_types()
    prog = make_program("Ingenieria del Cotejo Ya Liberado")
    cohort = make_cohort(book_donation_amount=Decimal("800.00"))
    CotejoRequirementService.seed_defaults(db_session, cohort.id, commit=False)
    db_session.flush()
    officer, _pos = make_officer([prog])
    proc = make_process(make_student(), cohort=cohort, program=prog,
                        current_phase=3, library_clearance=None)
    make_appointment(proc, status="attended", is_current=True)
    return {"prog": prog, "cohort": cohort, "officer": officer, "proc": proc}


class TestYaPasoSuCotejo:
    NO_APLICA = "No aplica (cotejo ya liberado)"

    def test_el_expediente_dice_no_aplica_sin_constancia_previa(
            self, client_as, cotejado, se):
        resp = client_as(se).get(f"/titulatec/admin/processes/{cotejado['proc'].id}?fase=2")

        assert resp.status_code == 200, resp.text[:300]
        assert self.NO_APLICA in resp.text
        assert "En Biblioteca" not in resp.text
        assert "/no-adeudo-previo" not in resp.text, "no se ofrece «Constancia previa…»"

    def test_el_panel_de_atender_dice_no_aplica_sin_constancia_previa(
            self, client_as, cotejado, se):
        resp = client_as(se).get(
            f"/titulatec/admin/appointments/body?v=atender&selected={cotejado['proc'].id}")

        assert resp.status_code == 200, resp.text[:300]
        assert self.NO_APLICA in resp.text
        assert "En Biblioteca" not in resp.text
        assert "/no-adeudo-previo" not in resp.text, "no se ofrece «Constancia previa…»"

    def test_la_ruta_de_respaldo_lo_rechaza_aunque_la_llamen_a_mano(
            self, client_as, db_session, cotejado, se):
        from itcj2.apps.titulatec.services.library_clearance_service import (
            LibraryClearanceService,
        )

        resp = client_as(se).post(
            f"/titulatec/admin/processes/{cotejado['proc'].id}/no-adeudo-previo",
            data={"issued_on": date.today().isoformat()})

        assert resp.status_code == 400, resp.text[:300]
        assert _msg(resp) == ("Este egresado ya pasó su cotejo; no necesita trámite "
                              "de no adeudo.")
        fila = LibraryClearanceService.get_for_process(db_session, cotejado["proc"].id)
        assert fila is None or fila.status == "pending"


# ===========================================================================
# 6. Celda «Constancia» (Tarea 4, §3.4): el panel de atender y el expediente
#    pintan `certificate_cell` junto a CADA fila -encuesta y no adeudo-, la
#    MISMA fuente que las bandejas (`CertificateService.print_status_map`,
#    Tareas 2/3): impresa, sin imprimir, anulada tras imprimir y previa.
# ===========================================================================
def _atender(client_as, actor, proc_id):
    return client_as(actor).get(
        f"/titulatec/admin/appointments/body?v=atender&selected={proc_id}")


def _expediente(client_as, actor, proc_id):
    return client_as(actor).get(f"/titulatec/admin/processes/{proc_id}")


def _en_las_dos_vistas(client_as, actor, proc_id, *, contiene=(), no_contiene=()):
    """Pide atender y expediente y repite las MISMAS aserciones en los dos:
    comparten fuente (`summary_for_process` más la UNA llamada a
    `print_status_map` que cuelga `certificate`, Ruling R14) y macro
    (`certificate_cell`), así que un hueco en una y no en la otra sería un
    error de cableado de la plantilla, no de los datos."""
    for resp in (_atender(client_as, actor, proc_id), _expediente(client_as, actor, proc_id)):
        assert resp.status_code == 200, resp.text[:300]
        for texto in contiene:
            assert texto in resp.text, texto
        for texto in no_contiene:
            assert texto not in resp.text, texto


class TestCeldaDeConstanciaBiblioteca:
    def test_sin_imprimir_tras_pagar(self, client_as, db_session, caso):
        from itcj2.apps.titulatec.services.library_clearance_service import (
            LibraryClearanceService,
        )
        clearance = LibraryClearanceService.get_for_process(db_session, caso["proc"].id)
        with patch(NOTIFY):
            LibraryClearanceService.register_payment(
                db_session, clearance.id, caso["officer"].id, receipt_number="R-0001")

        _en_las_dos_vistas(client_as, caso["officer"], caso["proc"].id,
                           contiene=("Sin imprimir",), no_contiene=("Impresa",))

    def test_impresa_tras_el_lote(self, client_as, db_session, caso):
        from itcj2.apps.titulatec.services.certificate_service import CertificateService
        from itcj2.apps.titulatec.services.library_clearance_service import (
            LibraryClearanceService,
        )
        clearance = LibraryClearanceService.get_for_process(db_session, caso["proc"].id)
        with patch(NOTIFY):
            LibraryClearanceService.register_payment(
                db_session, clearance.id, caso["officer"].id, receipt_number="R-0002")
        batch = CertificateService.create_batch(
            db_session, kind="library_clearance", actor_id=caso["officer"].id)

        _en_las_dos_vistas(client_as, caso["officer"], caso["proc"].id,
                           contiene=("Impresa", f"lote #{batch.id}"))

    def test_anulada_tras_imprimir_avisa_retirar_el_papel(self, client_as, db_session, caso):
        from itcj2.apps.titulatec.services.certificate_service import CertificateService
        from itcj2.apps.titulatec.services.library_clearance_service import (
            LibraryClearanceService,
        )
        clearance = LibraryClearanceService.get_for_process(db_session, caso["proc"].id)
        with patch(NOTIFY):
            LibraryClearanceService.register_payment(
                db_session, clearance.id, caso["officer"].id, receipt_number="R-0003")
        CertificateService.create_batch(db_session, kind="library_clearance",
                                        actor_id=caso["officer"].id)
        with patch(NOTIFY):
            LibraryClearanceService.revert_payment(
                db_session, clearance.id, caso["officer"].id, "Pago duplicado")

        _en_las_dos_vistas(client_as, caso["officer"], caso["proc"].id,
                           contiene=("Anulada tras imprimir", "retira ese papel"),
                           no_contiene=("Sin imprimir",))

    def test_previa_no_tiene_folio(self, client_as, db_session, caso):
        from itcj2.apps.titulatec.services.library_clearance_service import (
            LibraryClearanceService,
        )
        clearance = LibraryClearanceService.get_for_process(db_session, caso["proc"].id)
        with patch(NOTIFY):
            LibraryClearanceService.register_prior(
                db_session, clearance.id, caso["officer"].id,
                issued_on=date.today() - timedelta(days=10), note="Papel de antes",
                by="library")

        _en_las_dos_vistas(client_as, caso["officer"], caso["proc"].id,
                           contiene=("Constancia previa (papel del egresado)",))

    def test_legado_no_muestra_nada(self, client_as, db_session, caso):
        """R5(b) (revisión de la Tarea 4): `via == 'legacy'` (backfill sin
        Biblioteca/Caja/SE detrás, D17) -- la celda no tiene nada que
        mostrar: ni folio, ni «Impresa»/«Sin imprimir»/«Anulada tras
        imprimir», ni el texto de constancia previa. Mismo criterio de
        ausencia que `test_library_inbox.py::
        test_columna_constancia_en_legado_no_muestra_nada` (la bandeja),
        aquí en las dos vistas de SE."""
        from itcj2.apps.titulatec.services.library_clearance_service import (
            LibraryClearanceService,
        )
        clearance = LibraryClearanceService.get_for_process(db_session, caso["proc"].id)
        clearance.status = "cleared"
        clearance.cleared_via = "legacy"
        db_session.flush()

        _en_las_dos_vistas(
            client_as, caso["officer"], caso["proc"].id,
            no_contiene=("BIB-", "Impresa", "Sin imprimir", "Anulada tras imprimir",
                        "Constancia previa (papel del egresado)"))


class TestCeldaDeConstanciaEncuesta:
    def test_sin_imprimir_tras_liberar(self, client_as, db_session, caso, make_survey_review):
        from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

        review = make_survey_review(caso["proc"], status="in_review")
        with patch(NOTIFY):
            SurveyReviewService.approve(db_session, review.id, caso["officer"].id)

        _en_las_dos_vistas(client_as, caso["officer"], caso["proc"].id,
                           contiene=("Sin imprimir",), no_contiene=("Impresa",))

    def test_impresa_tras_el_lote(self, client_as, db_session, caso, make_survey_review):
        from itcj2.apps.titulatec.services.certificate_service import CertificateService
        from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

        review = make_survey_review(caso["proc"], status="in_review")
        with patch(NOTIFY):
            SurveyReviewService.approve(db_session, review.id, caso["officer"].id)
        batch = CertificateService.create_batch(
            db_session, kind="survey_release", actor_id=caso["officer"].id)

        _en_las_dos_vistas(client_as, caso["officer"], caso["proc"].id,
                           contiene=("Impresa", f"lote #{batch.id}"))

    def test_anulada_tras_imprimir_avisa_retirar_el_papel(
            self, client_as, db_session, caso, make_survey_review):
        from itcj2.apps.titulatec.services.certificate_service import CertificateService
        from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

        review = make_survey_review(caso["proc"], status="in_review")
        with patch(NOTIFY):
            SurveyReviewService.approve(db_session, review.id, caso["officer"].id)
        CertificateService.create_batch(db_session, kind="survey_release",
                                        actor_id=caso["officer"].id)
        with patch(NOTIFY):
            SurveyReviewService.revoke(
                db_session, review.id, caso["officer"].id, "Aclaración de GTV")

        _en_las_dos_vistas(client_as, caso["officer"], caso["proc"].id,
                           contiene=("Anulada tras imprimir", "retira ese papel"),
                           no_contiene=("Sin imprimir",))

    def test_previa_no_tiene_folio(self, client_as, db_session, caso):
        from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

        with patch(NOTIFY):
            SurveyReviewService.register_prior(
                db_session, caso["proc"], issued_on=date.today() - timedelta(days=10),
                actor_id=caso["officer"].id)

        _en_las_dos_vistas(client_as, caso["officer"], caso["proc"].id,
                           contiene=("Constancia previa (papel del egresado)",))


# ===========================================================================
# 7. m42 (`triage-minors.md`): `library_clearance_pill` no mira
#    `TitulationProcess.status`, así que un proceso REVOCADO con el no adeudo
#    todavía `missing`/`pending` mostraba «En Biblioteca» como si el trámite
#    siguiera vivo -y, en `awaiting_payment`, «Por cobrar $X en Caja»
#    (Ruling R15)-. Las dos vistas tienen el proceso a la mano: deciden ELLAS
#    (no se toca la macro compartida -la usan +12 vistas-).
# ===========================================================================
@pytest.fixture()
def revocado(db_session, seed_phase_defs, seed_document_types, make_program, make_cohort,
            make_officer, make_student, make_process, make_appointment):
    """Proceso YA `cancelled` desde que nace, con su no adeudo `pending` y una
    cita `attended` vigente (alcanzable desde atender)."""
    from itcj2.apps.titulatec.services.cotejo_requirement_service import (
        CotejoRequirementService,
    )

    seed_phase_defs()
    seed_document_types()
    prog = make_program("Ingenieria de la Celda Revocada")
    cohort = make_cohort(book_donation_amount=Decimal("800.00"))
    CotejoRequirementService.seed_defaults(db_session, cohort.id, commit=False)
    db_session.flush()
    officer, _pos = make_officer([prog])
    proc = make_process(make_student(), cohort=cohort, program=prog, current_phase=2,
                        status="cancelled", library_clearance="pending")
    make_appointment(proc, status="attended", is_current=True)
    return {"prog": prog, "officer": officer, "proc": proc}


@pytest.fixture()
def revocado_sin_fila(db_session, seed_phase_defs, seed_document_types, make_program,
                      make_cohort, make_officer, make_student, make_process,
                      make_appointment):
    """R5(a) (revisión de la Tarea 4): mismo molde que `revocado`, pero SIN
    NINGUNA fila de `LibraryClearance` (alta durante el blue/green, antes de
    que exista la fila) -- `summary_for_process` da el pseudo-estado
    `missing`, que la plantilla trata igual que `pending`
    (`library.status in ('missing', 'pending')`), pero hasta ahora solo
    `revocado` (con fila `pending`) tenía prueba."""
    from itcj2.apps.titulatec.services.cotejo_requirement_service import (
        CotejoRequirementService,
    )

    seed_phase_defs()
    seed_document_types()
    prog = make_program("Ingenieria de la Celda Revocada Sin Fila")
    cohort = make_cohort(book_donation_amount=Decimal("800.00"))
    CotejoRequirementService.seed_defaults(db_session, cohort.id, commit=False)
    db_session.flush()
    officer, _pos = make_officer([prog])
    proc = make_process(make_student(), cohort=cohort, program=prog, current_phase=2,
                        status="cancelled", library_clearance=None)
    make_appointment(proc, status="attended", is_current=True)
    return {"prog": prog, "officer": officer, "proc": proc}


class TestProcesoRevocadoPildoraDeNoAdeudo:
    def test_pendiente_pinta_revocada_no_en_biblioteca(self, client_as, revocado):
        _en_las_dos_vistas(client_as, revocado["officer"], revocado["proc"].id,
                           contiene=("Revocada",), no_contiene=("En Biblioteca",))

    def test_pendiente_sin_fila_pinta_revocada_no_en_biblioteca(
            self, client_as, revocado_sin_fila):
        """R5(a): sin NINGUNA fila de `LibraryClearance` (pseudo-estado
        `missing`, no solo `pending`) el proceso revocado debe seguir
        pintando «Revocada», no «En Biblioteca» -- la prueba hermana de
        arriba cubre `pending`; `missing` es la otra mitad del
        `in ('missing', 'pending')` de la plantilla, sin prueba propia hasta
        ahora."""
        _en_las_dos_vistas(client_as, revocado_sin_fila["officer"],
                           revocado_sin_fila["proc"].id,
                           contiene=("Revocada",), no_contiene=("En Biblioteca",))

    def test_por_pagar_en_caja_pinta_revocada_sin_el_monto(self, client_as, db_session, caso):
        """Ruling R15 (M4 + P3 de la revisión final): la «Revocada» de m42
        cubre también `awaiting_payment`. Con la inscripción revocada y el no
        adeudo congelado en Caja, el renglón ya no dice «Por pagar en Caja —
        Por cobrar $1,200.00 en Caja»: Caja no lo cobraría
        (`register_payment` lo rechaza) y SE mandaría al egresado a una
        vuelta inútil. Sin el sufijo del monto. Aserciones acotadas al
        renglón del requisito en cada vista."""
        import lxml.html

        from itcj2.apps.titulatec.models import CotejoRequirement

        req = (db_session.query(CotejoRequirement)
               .filter_by(cohort_id=caso["cohort"].id, auto_source="library_clearance")
               .one())
        antes = _atender(client_as, caso["officer"], caso["proc"].id)
        assert "Por cobrar $1,200.00 en Caja" in " ".join(antes.text.split()), (
            "control positivo: vivo, el renglón sí dice el monto por cobrar")
        caso["proc"].status = "cancelled"
        db_session.flush()

        for resp in (_atender(client_as, caso["officer"], caso["proc"].id),
                     _expediente(client_as, caso["officer"], caso["proc"].id)):
            assert resp.status_code == 200, resp.text[:300]
            (fila,) = lxml.html.fromstring(resp.text).xpath(
                f'//*[@id="appt-req-{req.id}" or @id="exp-req-{req.id}"]')
            texto = " ".join(fila.text_content().split())
            assert "Revocada" in texto, texto
            assert "Por pagar en Caja" not in texto, texto
            assert "Por cobrar" not in texto, texto
            assert "$1,200.00" not in texto, texto

    def test_ninguna_vista_ofrece_constancia_previa_a_un_revocado(
            self, client_as, revocado, caso, se):
        """M2 (revisión final): el panel de atender ofrecía «Constancia
        previa…» a un proceso revocado -justo al lado de la «Revocada» de m42-
        y la ruta contestaba 400. Ahora pide lo mismo que el expediente
        (`pages/admin.py::_detail_ctx`): el permiso Y el proceso no
        `cancelled`. Control positivo: la MISMA actora sí ve el formulario en
        un proceso vivo (`caso`, por pagar en Caja)."""
        vivo = _atender(client_as, se, caso["proc"].id)
        assert vivo.status_code == 200, vivo.text[:300]
        assert "/no-adeudo-previo" in vivo.text, "control positivo: con permiso sí se ofrece"

        for resp in (_atender(client_as, se, revocado["proc"].id),
                     _expediente(client_as, se, revocado["proc"].id)):
            assert resp.status_code == 200, resp.text[:300]
            assert "Revocada" in resp.text
            assert "/no-adeudo-previo" not in resp.text, "no se ofrece «Constancia previa…»"

    def test_ya_liberado_antes_de_revocar_conserva_su_pildora_y_constancia(
            self, client_as, db_session, caso):
        """Review Focus #5: un no adeudo que YA se liberó (y su constancia ya
        se imprimió) ANTES de la revocación conserva su píldora «Liberado» y
        la celda sigue mostrando «Impresa» -revocar la inscripción no reescribe
        la historia del trámite que sí se completó."""
        from itcj2.apps.titulatec.services.certificate_service import CertificateService
        from itcj2.apps.titulatec.services.library_clearance_service import (
            LibraryClearanceService,
        )
        clearance = LibraryClearanceService.get_for_process(db_session, caso["proc"].id)
        with patch(NOTIFY):
            LibraryClearanceService.register_payment(
                db_session, clearance.id, caso["officer"].id, receipt_number="R-0004")
        CertificateService.create_batch(db_session, kind="library_clearance",
                                        actor_id=caso["officer"].id)
        caso["proc"].status = "cancelled"
        db_session.flush()

        _en_las_dos_vistas(client_as, caso["officer"], caso["proc"].id,
                           contiene=("Liberado", "Impresa"),
                           no_contiene=("Revocada", "En Biblioteca", "No se imprimirá"))

    def test_constancias_sin_imprimir_de_un_revocado_no_se_imprimiran(
            self, client_as, db_session, caso, make_survey_review):
        """Ruling R13 (P4 de la revisión final): las DOS constancias vigentes
        SIN lote -encuesta y no adeudo- de una inscripción revocada ya no
        entrarán a un lote (`_pending_criteria`, Ruling R26), así que cada
        celda pinta la píldora «No se imprimirá» con la nota tenue
        «inscripción revocada» fuera de ella (Ruling R18: la nota puede
        partirse en celular), nunca «Sin imprimir». Las dos vistas le pasan
        a la macro el estado del proceso (`revoked=`); con lote siguen
        «Impresa» (la prueba de arriba)."""
        import re
        from itcj2.apps.titulatec.services.library_clearance_service import (
            LibraryClearanceService,
        )
        from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

        clearance = LibraryClearanceService.get_for_process(db_session, caso["proc"].id)
        review = make_survey_review(caso["proc"], status="in_review")
        with patch(NOTIFY):
            LibraryClearanceService.register_payment(
                db_session, clearance.id, caso["officer"].id, receipt_number="R-0005")
            SurveyReviewService.approve(db_session, review.id, caso["officer"].id)
        caso["proc"].status = "cancelled"
        db_session.flush()

        for resp in (_atender(client_as, caso["officer"], caso["proc"].id),
                     _expediente(client_as, caso["officer"], caso["proc"].id)):
            assert resp.status_code == 200, resp.text[:300]
            assert len(re.findall(r'<i class="bi bi-slash-circle"></i>No se imprimirá\s*</span>',
                                  resp.text)) == 2
            assert resp.text.count(
                '<span class="small text-body-secondary">inscripción revocada</span>') == 2
            assert "Sin imprimir" not in resp.text


# ===========================================================================
# 8. Macro `certificate_cell`: respaldo final (Ruling R4, revisión de la
#    Tarea 3) -- un `info` dict sin folio vigente, sin `voided_printed` y ni
#    `prior` ni `legacy` es contractualmente imposible hoy (`print_status_map`
#    solo da folio vigente, `voided_printed` o `None`), pero el macro no debe
#    quedar en blanco si algún día pasa.
# ===========================================================================
def test_certificate_cell_nunca_queda_vacia():
    from itcj2.apps.titulatec.pages.nav import titulatec_templates

    tpl = titulatec_templates.env.from_string(
        '{% from "titulatec/_macros.html" import certificate_cell %}'
        '{{ certificate_cell(info) }}')
    html = " ".join(tpl.render(info={"number": None, "voided_printed": None}).split())

    assert html == "—"


def test_certificate_cell_revocada_solo_cambia_la_vigente_sin_lote():
    """Ruling R13: `revoked=True` cambia SOLO la vigente sin lote («Sin
    imprimir» ámbar -> píldora neutra «No se imprimirá» con la nota tenue
    «inscripción revocada» FUERA de ella, Ruling R18: la píldora no parte
    renglón y la nota sí). Una impresa sigue «Impresa» (el papel existe) y
    una anulada tras imprimir sigue pidiendo retirar el papel: las dos salen
    idénticas con o sin `revoked`."""
    from datetime import datetime

    from itcj2.apps.titulatec.pages.nav import titulatec_templates

    tpl = titulatec_templates.env.from_string(
        '{% from "titulatec/_macros.html" import certificate_cell %}'
        '{{ certificate_cell(info, revoked=revoked) }}')

    def _celda(info, revoked):
        return " ".join(tpl.render(info=info, revoked=revoked).split())

    lote = datetime(2031, 3, 10, 9, 0)
    sin_lote = {"number": "BIB-2031-0001", "printed": False, "batch_id": None,
                "batch_at": None, "voided_printed": None}
    impresa = {"number": "BIB-2031-0002", "printed": True, "batch_id": 7,
               "batch_at": lote, "voided_printed": None}
    anulada = {"number": None, "printed": False, "batch_id": None, "batch_at": None,
               "voided_printed": {"number": "BIB-2031-0003", "batch_id": 7,
                                  "batch_at": lote, "voided_at": lote,
                                  "void_reason": "x"}}

    revocada = _celda(sin_lote, True)
    assert "BIB-2031-0001" in revocada
    assert ('<span class="tt-pill tt-pill--neutral"><i class="bi bi-slash-circle"></i>'
            'No se imprimirá </span>') in revocada, revocada
    assert '<span class="small text-body-secondary">inscripción revocada</span>' in revocada
    assert "Sin imprimir" not in revocada and "tt-pill--amber" not in revocada
    assert "Sin imprimir" in _celda(sin_lote, False)
    for info in (impresa, anulada):
        assert _celda(info, True) == _celda(info, False)
        assert "No se imprimirá" not in _celda(info, True)


# ===========================================================================
# 9. Rulings R14 y R17 (M3 + P2 y N1 de la revisión final): UNA lectura de
#    constancias por vista de SE. Cada vista hace UNA llamada a
#    `print_status_map` con los refs de encuesta y no adeudo que EXISTAN y
#    cuelga `certificate` en cada resumen; los `summary_for_process` no
#    consultan constancias (también los usan el tablero del egresado, «Mi
#    cita» y las páginas públicas). Antes (Tarea 4) era una llamada por
#    resumen: hasta 4 consultas por vista; con el folio suelto del resumen de
#    biblioteca que R14 conservaba, hasta 3. Ahora, a lo más 2 (invariante 2).
# ===========================================================================
@pytest.fixture()
def espia(db_session, monkeypatch):
    """Espía de `CertificateService.print_status_map` (delega en la real) y
    de TODO el SQL que la sesión manda mientras dura la prueba."""
    from types import SimpleNamespace

    from sqlalchemy import event

    from itcj2.apps.titulatec.services.certificate_service import CertificateService

    original = CertificateService.print_status_map
    llamadas, sentencias = [], []

    def _espia(db, source_refs):
        llamadas.append(sorted(source_refs))
        return original(db, source_refs)

    def _antes(_conn, _cursor, statement, *_a):
        sentencias.append(statement)

    monkeypatch.setattr(CertificateService, "print_status_map", staticmethod(_espia))
    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", _antes)
    try:
        yield SimpleNamespace(llamadas=llamadas, sentencias=sentencias)
    finally:
        event.remove(bind, "before_cursor_execute", _antes)


def _por_vista(client_as, actor, proc_id, espia):
    """(nombre, llamadas, sentencias) de cada vista de SE, medidas por separado."""
    for vista in (_atender, _expediente):
        espia.llamadas.clear()
        espia.sentencias.clear()
        resp = vista(client_as, actor, proc_id)
        assert resp.status_code == 200, resp.text[:300]
        yield vista.__name__, list(espia.llamadas), list(espia.sentencias)


def _de_la_marca(sentencias):
    """Las consultas del estado de impresión: las únicas que tocan los lotes."""
    return [s for s in sentencias if "titulatec_certificate_batches" in s]


def _de_constancias(sentencias):
    return [s for s in sentencias if "titulatec_certificates" in s]


class TestUnaLecturaDeLaMarcaPorVista:
    def test_una_llamada_con_los_dos_refs_y_a_lo_mas_2_consultas(
            self, client_as, db_session, caso, make_survey_review, espia):
        """Encuesta en revisión y no adeudo por pagar: NINGUNO tiene
        constancia vigente, el peor caso de `print_status_map` (vigentes +
        anuladas con lote = 2 consultas). Por vista: UNA llamada con los dos
        refs, y a lo más 2 consultas sobre `titulatec_certificates` en TOTAL
        -las dos de la marca, que tocan los lotes; el resumen de biblioteca ya
        no busca su folio suelto, Ruling R17-."""
        from itcj2.apps.titulatec.services.library_clearance_service import (
            LibraryClearanceService,
        )

        review = make_survey_review(caso["proc"], status="in_review")
        clearance = LibraryClearanceService.get_for_process(db_session, caso["proc"].id)
        refs = sorted([f"survey_review:{review.id}", f"library_clearance:{clearance.id}"])

        for nombre, llamadas, sentencias in _por_vista(client_as, caso["officer"],
                                                       caso["proc"].id, espia):
            assert llamadas == [refs], nombre
            assert 1 <= len(_de_la_marca(sentencias)) <= 2, (nombre, _de_la_marca(sentencias))
            assert len(_de_constancias(sentencias)) <= 2, (nombre, _de_constancias(sentencias))

    def test_sin_solicitud_de_encuesta_solo_pide_el_no_adeudo(
            self, client_as, db_session, caso, espia):
        """El egresado no ha enviado la encuesta (pseudo-estado `missing`, sin
        `review_id`): su ref no existe y no se pide; la celda de la encuesta
        recibe `None` («—»)."""
        from itcj2.apps.titulatec.services.library_clearance_service import (
            LibraryClearanceService,
        )

        clearance = LibraryClearanceService.get_for_process(db_session, caso["proc"].id)

        for nombre, llamadas, _sentencias in _por_vista(client_as, caso["officer"],
                                                        caso["proc"].id, espia):
            assert llamadas == [[f"library_clearance:{clearance.id}"]], nombre

    def test_sin_solicitud_ni_fila_no_consulta_constancias(
            self, client_as, revocado_sin_fila, espia):
        """Ni solicitud de encuesta ni fila de no adeudo: la llamada va vacía
        (`print_status_map([])` no toca la base) y no hay folio que buscar,
        así que la vista no consulta constancias en absoluto."""
        for nombre, llamadas, sentencias in _por_vista(
                client_as, revocado_sin_fila["officer"], revocado_sin_fila["proc"].id, espia):
            assert llamadas == [[]], nombre
            assert not [s for s in sentencias if "titulatec_certificate" in s], nombre
