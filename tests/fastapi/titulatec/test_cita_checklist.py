"""El checklist de la cita sale de la BD, no de una constante.

`_COTEJO_CHECKLIST` (pages/student.py:884-893) era un duplicado byte a byte de
`CotejoRequirementService.DEFAULTS`: la jefa de Servicios Escolares podia editar
la lista por convocatoria y el alumno seguia viendo la fija. Cambio visible
aceptado por el usuario (D10).

Ademas fija el invariante de §5.3: el proceso que el alumno VE aqui es el mismo
que devuelve `ProcessService.creditable_process`, que es el que la encuesta
ACREDITA. `DocumentService.get_active_process` no sirve: no filtra por status.
"""
from __future__ import annotations

import pytest

import itcj2.models  # noqa: F401

from itcj2.apps.titulatec.services.process_service import ProcessService

URL = "/titulatec/student/cita"


@pytest.fixture()
def alumno_en_cita(db_session, seed_phase_defs, make_student, make_cohort, make_process):
    """Alumno en la fase 2 (la de la cita) con su convocatoria."""
    seed_phase_defs()
    cohort = make_cohort()
    student = make_student()
    process = make_process(student, cohort=cohort, current_phase=2)
    return {"student": student, "cohort": cohort, "process": process}


class TestCreditableProcess:
    def test_toma_el_activo(self, db_session, alumno_en_cita):
        esc = alumno_en_cita

        assert ProcessService.creditable_process(
            db_session, esc["student"].id).id == esc["process"].id

    def test_toma_tambien_on_hold(self, db_session, alumno_en_cita):
        esc = alumno_en_cita
        esc["process"].status = "on_hold"
        db_session.flush()

        assert ProcessService.creditable_process(
            db_session, esc["student"].id).id == esc["process"].id

    def test_ignora_completed_y_cancelled(self, db_session, alumno_en_cita):
        """El delta con `DocumentService.get_active_process`, que SI lo devolveria."""
        from itcj2.apps.titulatec.services.document_service import DocumentService

        esc = alumno_en_cita
        esc["process"].status = "completed"
        db_session.flush()

        assert ProcessService.creditable_process(db_session, esc["student"].id) is None
        assert DocumentService.get_active_process(
            db_session, esc["student"].id) is not None, (
            "si esto cambia, el aviso de la docstring de creditable_process ya "
            "no aplica y hay que reescribirlo")

    def test_sin_proceso_devuelve_none(self, db_session, make_student):
        assert ProcessService.creditable_process(db_session, make_student().id) is None

    def test_desempata_por_id_cuando_created_at_empata(self, db_session, alumno_en_cita,
                                                       make_cohort, make_process):
        """El orden tiene que ser TOTAL, no depender del plan de Postgres.

        `created_at` es `server_default NOW()` y en Postgres `now()` es la marca
        de la TRANSACCION: dos procesos dados de alta en la misma transaccion
        —justo lo que hace el importador de una convocatoria— traen el mismo
        `created_at` al milisegundo. Sin el desempate por `id` el ganador lo
        elige el plan de ejecucion y el credito de la encuesta puede aterrizar
        en un proceso distinto del que el alumno esta viendo.
        """
        esc = alumno_en_cita
        # UNIQUE(student_id, cohort_id): el segundo proceso necesita otra
        # convocatoria (y `make_cohort` levanta su propio periodo).
        segundo = make_process(esc["student"], cohort=make_cohort(), current_phase=1)
        db_session.flush()

        assert segundo.created_at == esc["process"].created_at, (
            "el empate es la premisa de esta prueba; si NOW() dejo de ser el de "
            "la transaccion hay que forzar el created_at a mano")
        assert segundo.id > esc["process"].id

        ganador = ProcessService.creditable_process(db_session, esc["student"].id)
        assert ganador.id == segundo.id


class TestChecklistEnLaPagina:
    def test_muestra_los_requisitos_de_su_convocatoria(self, db_session, alumno_en_cita,
                                                       client_as):
        from itcj2.apps.titulatec.services.cotejo_requirement_service import (
            CotejoRequirementService,
        )
        esc = alumno_en_cita
        CotejoRequirementService.create(db_session, esc["cohort"].id,
                                        label="Constancia inventada por la jefa",
                                        hint="Original y dos copias", icon="book")

        resp = client_as(esc["student"]).get(URL, follow_redirects=False)

        assert resp.status_code == 200, resp.text[:300]
        assert "Constancia inventada por la jefa" in resp.text
        assert "Original y dos copias" in resp.text

    def test_ya_no_pinta_la_lista_hardcodeada(self, db_session, alumno_en_cita, client_as):
        """Una convocatoria con UN requisito no puede mostrar los ocho de antes."""
        from itcj2.apps.titulatec.services.cotejo_requirement_service import (
            CotejoRequirementService,
        )
        esc = alumno_en_cita
        CotejoRequirementService.create(db_session, esc["cohort"].id, label="Unico",
                                        hint=None, icon=None)

        resp = client_as(esc["student"]).get(URL, follow_redirects=False)

        assert "Unico" in resp.text
        assert "Vigencia de derechos IMSS" not in resp.text

    def test_marca_lo_que_ya_cumplio(self, db_session, alumno_en_cita, client_as):
        from itcj2.apps.titulatec.services.cotejo_requirement_service import (
            CotejoRequirementService,
        )
        from itcj2.apps.titulatec.services.requirement_service import RequirementService

        esc = alumno_en_cita
        item = CotejoRequirementService.create(db_session, esc["cohort"].id,
                                               label="Actas de nacimiento",
                                               hint=None, icon=None)
        RequirementService.fulfill(db_session, esc["process"].id, item.id,
                                   source="officer", commit=False)

        resp = client_as(esc["student"]).get(URL, follow_redirects=False)

        assert "Listo" in resp.text

    def test_dispensado_se_ve_distinto_de_entregado(self, db_session, alumno_en_cita,
                                                    client_as):
        from itcj2.apps.titulatec.services.cotejo_requirement_service import (
            CotejoRequirementService,
        )
        from itcj2.apps.titulatec.services.requirement_service import RequirementService

        esc = alumno_en_cita
        item = CotejoRequirementService.create(db_session, esc["cohort"].id,
                                               label="e.Firma", hint=None, icon=None)
        RequirementService.fulfill(db_session, esc["process"].id, item.id,
                                   source="officer", status="waived", commit=False)

        resp = client_as(esc["student"]).get(URL, follow_redirects=False)

        assert "Dispensado" in resp.text

    def test_la_encuesta_trae_su_enlace_y_lo_pierde_al_cumplirse(self, db_session,
                                                                 alumno_en_cita, client_as):
        """El unico requisito que el alumno puede resolver desde aqui mismo.

        La convocatoria nace sin requisitos, asi que `list_or_seed` siembra los 8
        por defecto y solo uno trae `auto_source='graduate_survey'`. La URL es la
        del contrato (§3) y NO existe hasta la Tarea 12: entre esta tarea y
        aquella el enlace da 404 dentro de la rama, y se escribe ya a proposito.
        """
        from itcj2.apps.titulatec.services.requirement_service import RequirementService

        esc = alumno_en_cita

        resp = client_as(esc["student"]).get(URL, follow_redirects=False)
        assert "/titulatec/encuesta-egresados" in resp.text

        req = RequirementService.auto_requirement(db_session, esc["cohort"].id,
                                                  "graduate_survey")
        RequirementService.fulfill(db_session, esc["process"].id, req.id,
                                   source="survey", commit=False)

        resp = client_as(esc["student"]).get(URL, follow_redirects=False)
        assert "/titulatec/encuesta-egresados" not in resp.text, (
            "ya acreditada, la invitacion a contestarla sobra")

    def test_el_ctx_no_lleva_objetos_orm(self, db_session, alumno_en_cita):
        """La plantilla se pinta DESPUES del `db.close()` de la ruta.

        Si algo del contexto fuera una instancia del ORM, la plantilla tocaria
        un atributo posiblemente expirado —`list_with_status` puede commitear al
        sembrar— sobre un objeto ya desanclado y reventaria con
        `DetachedInstanceError`. En el harness eso NO se ve: el `_TestSession`
        de conftest ignora el `close()` para que el test siga vivo, asi que la
        sesion nunca se cierra de verdad y el fallo de produccion pasa en verde.
        Por eso el invariante se fija por la FORMA del contexto: diccionarios de
        valores planos, cero objetos mapeados.
        """
        from itcj2.apps.titulatec.pages.student import _checklist_ctx

        ctx = _checklist_ctx(db_session, alumno_en_cita["process"])

        assert ctx, "la convocatoria sin requisitos siembra los 8 por defecto"
        for it in ctx:
            assert isinstance(it, dict), f"{it!r} no es un dict plano"
            for campo, valor in it.items():
                assert not hasattr(valor, "_sa_instance_state"), (
                    f"'{campo}' lleva un objeto ORM hasta la plantilla")

    def test_la_constante_ya_no_existe_en_el_modulo(self):
        """Guarda contra el 'lo dejo por si acaso': el duplicado tiene que morir."""
        from itcj2.apps.titulatec.pages import student as student_pages

        assert not hasattr(student_pages, "_COTEJO_CHECKLIST")


class TestSinTramiteVivoNoHayPagina:
    """Sin proceso acreditable, `/student/cita` manda al dashboard.

    `_phase_guard_page` deja pasar el `None` a proposito, y con el selector viejo
    eso jamas ocurria: devolvia un proceso hubiera lo que hubiera, asi que la
    guarda siempre tenia algo que rechazar. `creditable_process` si puede no
    devolver ninguno, y sin este redirect el egresado aterrizaba en la pagina
    vacia leyendo que «Servicios Escolares aun no publica los requisitos de tu
    convocatoria», que para el es falso. Un solo contrato en todo el alumno:
    quien no tiene tramite vivo no tiene fase en curso y no le toca ninguna
    pagina, que es lo que ya hace `/student/documents`.
    """

    @pytest.mark.parametrize("status", ["completed", "cancelled"])
    def test_un_tramite_cerrado_no_abre_la_pagina(self, status, db_session, seed_phase_defs,
                                                  make_student, make_cohort, make_process,
                                                  client_as):
        seed_phase_defs()
        student = make_student()
        make_process(student, cohort=make_cohort(), current_phase=2, status=status)
        db_session.flush()

        resp = client_as(student).get(URL, follow_redirects=False)

        assert resp.status_code == 302, (
            f"[{status}] la pagina se pinto vacia en vez de redirigir")
        assert resp.headers["location"] == "/titulatec/student/dashboard"

    def test_sin_ningun_proceso_tampoco(self, db_session, seed_phase_defs, make_student,
                                        client_as):
        seed_phase_defs()

        resp = client_as(make_student()).get(URL, follow_redirects=False)

        assert resp.status_code == 302
        assert resp.headers["location"] == "/titulatec/student/dashboard"

    def test_on_hold_va_al_acordeon_de_su_fase(self, db_session, seed_phase_defs,
                                               make_student, make_cohort, make_process,
                                               client_as):
        """Otro redirect y por otro motivo: aqui SI hay proceso, pero congelado.

        `on_hold` es acreditable (D5: conserva folio, cohorte y rutas, y la
        encuesta puede darle credito) pero no accionable —`assert_student_can_act`
        exige `active`—, asi que lo atiende `_phase_guard_page` y manda al
        acordeon de SU fase, con `?fase=`. No lo pineaba ningun test.
        """
        seed_phase_defs()
        student = make_student()
        make_process(student, cohort=make_cohort(), current_phase=2, status="on_hold")
        db_session.flush()

        resp = client_as(student).get(URL, follow_redirects=False)

        assert resp.status_code == 302
        assert resp.headers["location"] == "/titulatec/student/dashboard?fase=2", (
            "un proceso congelado NO es un proceso ausente: conserva su fase y el "
            "redirect tiene que llevar al acordeon de esa fase")


class TestLaPaginaYSusBotonesHablanDelMismoProceso:
    """La cita que el alumno VE y la que sus botones tocan tienen que ser UNA.

    Si la pagina y sus dos POST resuelven el proceso por su cuenta, un alumno con
    un proceso `completed` MAS NUEVO que su `active` ve su cita bien y recibe 400
    al confirmarla, sin nada en pantalla que lo explique: callejon sin salida.

    Se prueba por COMPORTAMIENTO —abre y confirma— y no por que selector usa cada
    ruta, para que siga significando lo mismo si el selector se renombra o se
    muda de service.
    """

    @pytest.fixture()
    def con_un_completed_mas_nuevo(self, db_session, seed_phase_defs, make_student,
                                   make_cohort, make_process, make_appointment):
        """Su proceso vivo con cita agendada, y un tramite cerrado POSTERIOR.

        Escenario propio y no `alumno_en_cita` por los permisos: el `STUDENT_PERMS`
        de conftest solo trae `appointment.page.my`, y los dos POST exigen
        `appointment.api.confirm.own`. Sin el, la peticion muere en 403 antes de
        llegar a la guarda de fase, que es justo lo que se quiere medir.
        """
        from datetime import timedelta

        seed_phase_defs()
        student = make_student(perm_codes=(
            "titulatec.dashboard.student",
            "titulatec.process.page.my",
            "titulatec.process.api.read.own",
            "titulatec.appointment.page.my",
            "titulatec.appointment.api.confirm.own",
        ))
        cohort = make_cohort()
        process = make_process(student, cohort=cohort, current_phase=2)
        appt = make_appointment(process)
        # UNIQUE(student_id, cohort_id) obliga a otra convocatoria. Y el
        # `created_at` se adelanta A MANO: es `server_default NOW()`, que en
        # Postgres es la marca de la TRANSACCION, asi que las dos filas nacerian
        # empatadas y no habria un "mas nuevo" que provoque la discrepancia.
        posterior = make_process(student, cohort=make_cohort(),
                                 current_phase=8, status="completed")
        posterior.created_at = process.created_at + timedelta(days=1)
        db_session.flush()
        return {"student": student, "process": process, "appt": appt,
                "posterior": posterior}

    def test_el_escenario_es_de_verdad_ambiguo(self, db_session, con_un_completed_mas_nuevo):
        """Premisa: sin esto los dos tests de abajo pasarian por vacios."""
        from itcj2.apps.titulatec.services.document_service import DocumentService

        esc = con_un_completed_mas_nuevo
        assert DocumentService.get_active_process(
            db_session, esc["student"].id).id == esc["posterior"].id, (
            "el escenario deja de enfrentar a los dos selectores; si "
            "get_active_process se arreglo, este archivo necesita otro montaje")

    def test_ve_la_pagina_y_puede_confirmar_la_cita(self, db_session,
                                                    con_un_completed_mas_nuevo, client_as):
        from itcj2.apps.titulatec.models import ReviewAppointment

        esc = con_un_completed_mas_nuevo
        cli = client_as(esc["student"])

        assert cli.get(URL, follow_redirects=False).status_code == 200

        resp = cli.post(f"{URL}/confirmar", follow_redirects=False)

        assert resp.status_code == 200, (
            f"la pagina abre pero el boton no responde: "
            f"{resp.headers.get('X-Tt-Error')}")
        assert db_session.get(ReviewAppointment, esc["appt"].id).confirmed_at is not None

    def test_ve_la_pagina_y_puede_pedir_cambio_de_cita(self, db_session,
                                                       con_un_completed_mas_nuevo, client_as):
        from itcj2.apps.titulatec.models import ReviewAppointment

        esc = con_un_completed_mas_nuevo
        cli = client_as(esc["student"])

        resp = cli.post(f"{URL}/solicitar-cambio", data={"reason": "Choca con mi examen"},
                        follow_redirects=False)

        assert resp.status_code == 200, resp.headers.get("X-Tt-Error")
        assert db_session.get(ReviewAppointment,
                              esc["appt"].id).change_request == "Choca con mi examen"

    def test_la_pagina_ensena_el_folio_del_proceso_correcto_no_el_mas_nuevo(
        self, db_session, con_un_completed_mas_nuevo, client_as,
    ):
        """El hueco que las dos pruebas de arriba NO cubren (Tarea 15).

        Abrir en 200 y poder confirmar no prueba que la PAGINA hable del
        proceso correcto: `cita_confirm` resuelve su propio `process` con
        `ProcessService.creditable_process` de forma independiente de
        `_cita_card_ctx` (ver `pages/student.py`), asi que confirma bien
        AUNQUE `_cita_card_ctx` estuviera pintando los datos de `posterior`.
        Sin el ancla `#tt-cita-process[data-tt-process]` (Tarea 15,
        `cita.html`) no habia forma de ver esa diferencia desde HTTP.

        Verificado con mutacion (Tarea 15): revertir `_cita_card_ctx` a
        `DocumentService.get_active_process` deja en VERDE toda la suite de
        titulatec sin este test — 796 passed, incluidas las dos pruebas de
        arriba de esta misma clase. Este test es el que cierra ese hueco.
        """
        esc = con_un_completed_mas_nuevo

        resp = client_as(esc["student"]).get(URL, follow_redirects=False)

        assert resp.status_code == 200, resp.text[:300]
        assert 'data-tt-process="{}"'.format(esc["process"].folio) in resp.text
        assert esc["posterior"].folio not in resp.text
