"""Cumplimientos de requisitos de cotejo por proceso (`RequirementService`).

La otra mitad de `titulatec_cotejo_requirements`: la tabla de la lista existia
desde la migracion `e8368b899ed1`, pero no habia donde anotar QUIEN ya cumplio
que. Sin esta pieza el checklist del alumno era una constante hardcodeada y el
dictamen de la fase 2 no podia mirar nada.

Regla de la casa: toda escritura deja `ProcessEvent`. Los asertos sobre la
bitacora no son decoracion — es lo unico que queda cuando alguien desmarca.
"""
from __future__ import annotations

from datetime import datetime

import pytest

import itcj2.models  # noqa: F401

from itcj2.apps.titulatec.services.requirement_service import RequirementService

AUTO_SURVEY = "graduate_survey"


def _req(db, cohort, *, label="Encuesta de egresados", icon="clipboard-check",
         hint=None, code=None, auto_source=None, is_required=True,
         is_active=True, order_index=0):
    """Un `CotejoRequirement` de esa convocatoria, escrito a mano."""
    from itcj2.apps.titulatec.models import CotejoRequirement
    row = CotejoRequirement(
        cohort_id=cohort.id, label=label, icon=icon, hint=hint, code=code,
        auto_source=auto_source, is_required=is_required, is_active=is_active,
        order_index=order_index,
    )
    db.add(row)
    db.flush()
    return row


def _events(db, process_id, tipo):
    from itcj2.apps.titulatec.models import ProcessEvent
    return (db.query(ProcessEvent)
            .filter_by(process_id=process_id, event_type=tipo)
            .order_by(ProcessEvent.id).all())


@pytest.fixture()
def escenario(db_session, make_student, make_process, make_cohort, make_user):
    """Una convocatoria con requisitos, un alumno con proceso y un oficial."""
    cohort = make_cohort()
    process = make_process(make_student(), cohort=cohort, current_phase=2)
    oficial = make_user(first_name="OFICIAL", last_name="DE PRUEBA")
    return {"cohort": cohort, "process": process, "oficial": oficial}


@pytest.fixture()
def commits(db_session, monkeypatch):
    """Cuenta los `commit()` de la sesion, dejandolos correr de verdad.

    Sin esto `commit=False` es INDEMOSTRABLE, y esa es la trampa del harness:
    `db_session` usa `join_transaction_mode="create_savepoint"`
    (`tests/fastapi/conftest.py:130-152`), asi que un `commit()` del service solo
    libera un SAVEPOINT y el test sigue viendo todas las filas pase lo que pase
    con la bandera. Contar las llamadas es lo unico que distingue las dos ramas.
    """
    llamadas = []
    real = db_session.commit

    def _spy():
        llamadas.append(1)
        real()

    monkeypatch.setattr(db_session, "commit", _spy)
    return llamadas


class TestListWithStatus:
    def test_marca_lo_cumplido_y_deja_lo_pendiente(self, db_session, escenario):
        cohort, process = escenario["cohort"], escenario["process"]
        uno = _req(db_session, cohort, label="Actas de nacimiento", order_index=0)
        _req(db_session, cohort, label="12 fotografias", order_index=1)

        RequirementService.fulfill(db_session, process.id, uno.id, source="officer",
                                   checked_by_id=escenario["oficial"].id, commit=False)

        filas = RequirementService.list_with_status(db_session, process.id)

        assert [f["requirement"].label for f in filas] == [
            "Actas de nacimiento", "12 fotografias"]
        assert filas[0]["is_done"] is True
        assert filas[0]["fulfillment"].source == "officer"
        assert filas[1]["is_done"] is False
        assert filas[1]["fulfillment"] is None

    def test_proceso_inexistente_devuelve_lista_vacia(self, db_session):
        assert RequirementService.list_with_status(db_session, 987654321) == []

    def test_siembra_si_la_convocatoria_no_tiene_lista(self, db_session, escenario):
        """La rama `list_or_seed` NO es teorica: hoy en dev
        `SELECT count(*) FROM titulatec_cotejo_requirements` da 0, asi que TODA
        convocatoria existente la toma en la primera visita de un alumno. Con un
        `list` pelado el checklist saldria vacio y sin nada que acreditar.
        """
        from itcj2.apps.titulatec.services.cotejo_requirement_service import DEFAULTS

        filas = RequirementService.list_with_status(db_session, escenario["process"].id)

        assert len(filas) == len(DEFAULTS)
        assert [f["is_done"] for f in filas] == [False] * len(DEFAULTS)

    def test_oculta_los_requisitos_desactivados(self, db_session, escenario):
        """`is_active=False` es la via SOPORTADA para retirar un requisito (el
        borrado esta bloqueado por el FK RESTRICT). Si `list_with_status` no
        filtrara, el alumno seguiria viendo lo que Servicios Escolares ya retiro
        y los dos lectores —este y `missing_required`— se irian separando.
        """
        cohort, process = escenario["cohort"], escenario["process"]
        vivo = _req(db_session, cohort, label="Vigente", order_index=0)
        _req(db_session, cohort, label="Retirado", is_active=False, order_index=1)

        filas = RequirementService.list_with_status(db_session, process.id)

        assert [f["requirement"].id for f in filas] == [vivo.id]


class TestFulfill:
    def test_escribe_snapshot_y_evento(self, db_session, escenario):
        req = _req(db_session, escenario["cohort"], label="Encuesta de egresados",
                   code=AUTO_SURVEY, auto_source=AUTO_SURVEY)
        process = escenario["process"]

        fila = RequirementService.fulfill(
            db_session, process.id, req.id, source="self_service",
            external_ref="survey_response:42", commit=False)

        assert fila.status == "fulfilled"
        assert fila.requirement_code == AUTO_SURVEY
        assert fila.label_snapshot == "Encuesta de egresados"
        assert fila.external_ref == "survey_response:42"
        assert fila.fulfilled_at is not None
        eventos = _events(db_session, process.id, "requirement_fulfilled")
        assert len(eventos) == 1
        assert eventos[0].phase_number == 2
        assert eventos[0].payload["requirement_id"] == req.id

    def test_es_idempotente_y_no_duplica_el_evento(self, db_session, escenario):
        req = _req(db_session, escenario["cohort"])
        process = escenario["process"]

        a = RequirementService.fulfill(db_session, process.id, req.id,
                                       source="officer", commit=False)
        b = RequirementService.fulfill(db_session, process.id, req.id,
                                       source="officer", commit=False)

        assert a.id == b.id
        assert len(_events(db_session, process.id, "requirement_fulfilled")) == 1

    def test_cambiar_a_waived_reescribe_la_fila_y_deja_evento(self, db_session, escenario):
        req = _req(db_session, escenario["cohort"])
        process = escenario["process"]
        RequirementService.fulfill(db_session, process.id, req.id,
                                   source="officer", commit=False)

        fila = RequirementService.fulfill(db_session, process.id, req.id,
                                          source="officer", status="waived",
                                          note="Caso legitimo", commit=False)

        assert fila.status == "waived"
        assert fila.note == "Caso legitimo"
        assert len(_events(db_session, process.id, "requirement_fulfilled")) == 2

    def test_repetir_con_nota_nueva_la_guarda_y_deja_evento(self, db_session, escenario):
        """El `mark` del encargado manda `note` en CADA envio.

        Con el corto-circuito por estado, corregir la nota de algo ya marcado se
        perdia entero: sin dato, sin evento y sin error — el renglon se
        re-renderizaba igualito y nadie se enteraba.
        """
        req = _req(db_session, escenario["cohort"])
        process = escenario["process"]
        RequirementService.fulfill(db_session, process.id, req.id,
                                   source="officer", commit=False)

        fila = RequirementService.fulfill(
            db_session, process.id, req.id, source="officer",
            note="Trajo copia simple, se acepta", commit=False)

        assert fila.note == "Trajo copia simple, se acepta"
        assert fila.status == "fulfilled"
        eventos = _events(db_session, process.id, "requirement_fulfilled")
        assert len(eventos) == 2
        assert eventos[-1].payload["note"] == "Trajo copia simple, se acepta"

    def test_repetir_sin_nota_no_borra_la_que_ya_estaba(self, db_session, escenario):
        """`None` es "no lo mando", no "borralo"."""
        req = _req(db_session, escenario["cohort"])
        process = escenario["process"]
        RequirementService.fulfill(db_session, process.id, req.id, source="officer",
                                   note="Dispensa autorizada", commit=False)

        fila = RequirementService.fulfill(db_session, process.id, req.id,
                                          source="officer", commit=False)

        assert fila.note == "Dispensa autorizada"
        assert len(_events(db_session, process.id, "requirement_fulfilled")) == 1

    def test_repetir_con_external_ref_nuevo_lo_guarda(self, db_session, escenario):
        req = _req(db_session, escenario["cohort"], code=AUTO_SURVEY,
                   auto_source=AUTO_SURVEY)
        process = escenario["process"]
        RequirementService.fulfill(db_session, process.id, req.id,
                                   source="officer", commit=False)

        fila = RequirementService.fulfill(db_session, process.id, req.id,
                                          source="self_service",
                                          external_ref="survey_response:7",
                                          commit=False)

        assert fila.external_ref == "survey_response:7"
        assert len(_events(db_session, process.id, "requirement_fulfilled")) == 2

    def test_cambiar_de_estado_resella_la_fecha(self, db_session, escenario, monkeypatch):
        """`fulfilled_at` es "cuando quedo acreditado ASI".

        La UI del encargado muestra esa fecha: dejar la del dia en que se marco
        como traido junto a la palabra "dispensado" seria mentir sobre cuando se
        autorizo la dispensa.
        """
        from itcj2.apps.titulatec.services import requirement_service as mod

        req = _req(db_session, escenario["cohort"])
        process = escenario["process"]
        marcado = datetime(2026, 3, 1, 9, 0, 0)
        dispensado = datetime(2026, 4, 2, 10, 30, 0)

        monkeypatch.setattr(mod, "db_now", lambda: marcado)
        RequirementService.fulfill(db_session, process.id, req.id,
                                   source="officer", commit=False)
        monkeypatch.setattr(mod, "db_now", lambda: dispensado)
        fila = RequirementService.fulfill(db_session, process.id, req.id,
                                          source="officer", status="waived",
                                          note="Caso legitimo", commit=False)

        assert fila.fulfilled_at == dispensado

    def test_corregir_la_nota_no_mueve_la_fecha(self, db_session, escenario, monkeypatch):
        """Corregir una nota no vuelve a acreditar nada: la fecha se queda."""
        from itcj2.apps.titulatec.services import requirement_service as mod

        req = _req(db_session, escenario["cohort"])
        process = escenario["process"]
        marcado = datetime(2026, 3, 1, 9, 0, 0)

        monkeypatch.setattr(mod, "db_now", lambda: marcado)
        RequirementService.fulfill(db_session, process.id, req.id,
                                   source="officer", commit=False)
        monkeypatch.setattr(mod, "db_now", lambda: datetime(2026, 4, 2, 10, 30, 0))
        fila = RequirementService.fulfill(db_session, process.id, req.id,
                                          source="officer", note="Se corrige",
                                          commit=False)

        assert fila.fulfilled_at == marcado


class TestUnfulfill:
    def test_borra_la_fila_y_deja_el_evento(self, db_session, escenario):
        from itcj2.apps.titulatec.models import RequirementFulfillment

        req = _req(db_session, escenario["cohort"], label="No-adeudo de biblioteca")
        process = escenario["process"]
        RequirementService.fulfill(db_session, process.id, req.id,
                                   source="officer", commit=False)

        ok = RequirementService.unfulfill(db_session, process.id, req.id,
                                          actor_id=escenario["oficial"].id, commit=False)

        assert ok is True
        assert db_session.query(RequirementFulfillment).filter_by(
            process_id=process.id, requirement_id=req.id).first() is None
        eventos = _events(db_session, process.id, "requirement_unfulfilled")
        assert len(eventos) == 1
        assert eventos[0].payload["label"] == "No-adeudo de biblioteca"

    def test_sin_fila_devuelve_false_y_no_escribe_evento(self, db_session, escenario):
        req = _req(db_session, escenario["cohort"])
        process = escenario["process"]

        ok = RequirementService.unfulfill(db_session, process.id, req.id,
                                          actor_id=escenario["oficial"].id, commit=False)

        assert ok is False
        assert _events(db_session, process.id, "requirement_unfulfilled") == []


class TestContratoDeCommit:
    """La bandera `commit` de `fulfill`/`unfulfill`, medida por llamadas reales.

    El envio de la encuesta escribe respuesta, respuestas y cumplimiento en UNA
    transaccion. Si alguien "simplifica" estos metodos para commitear siempre,
    esas tres escrituras se parten en dos transacciones y un fallo a media
    operacion deja un requisito acreditado sin respuesta que lo respalde. El
    savepoint del harness esconde por completo esa diferencia (ver la fixture
    `commits`), asi que sin contar los commits nadie se enteraria.
    """

    def test_fulfill_con_commit_false_no_commitea(self, db_session, escenario, commits):
        req = _req(db_session, escenario["cohort"])

        RequirementService.fulfill(db_session, escenario["process"].id, req.id,
                                   source="self_service", commit=False)

        assert commits == []

    def test_fulfill_con_commit_true_si_commitea(self, db_session, escenario, commits):
        req = _req(db_session, escenario["cohort"])

        RequirementService.fulfill(db_session, escenario["process"].id, req.id,
                                   source="officer", commit=True)

        assert len(commits) == 1

    def test_unfulfill_con_commit_false_no_commitea(self, db_session, escenario, commits):
        req = _req(db_session, escenario["cohort"])
        process = escenario["process"]
        RequirementService.fulfill(db_session, process.id, req.id,
                                   source="officer", commit=False)

        RequirementService.unfulfill(db_session, process.id, req.id,
                                     actor_id=escenario["oficial"].id, commit=False)

        assert commits == []

    def test_unfulfill_con_commit_true_si_commitea(self, db_session, escenario, commits):
        req = _req(db_session, escenario["cohort"])
        process = escenario["process"]
        RequirementService.fulfill(db_session, process.id, req.id,
                                   source="officer", commit=False)

        RequirementService.unfulfill(db_session, process.id, req.id,
                                     actor_id=escenario["oficial"].id, commit=True)

        assert len(commits) == 1

    def test_unfulfill_sin_fila_no_commitea_aunque_se_lo_pidan(
            self, db_session, escenario, commits):
        """No hubo nada que borrar: no hay transaccion que cerrar."""
        req = _req(db_session, escenario["cohort"])

        ok = RequirementService.unfulfill(db_session, escenario["process"].id, req.id,
                                          actor_id=escenario["oficial"].id, commit=True)

        assert ok is False
        assert commits == []


class TestMissingRequired:
    def test_ignora_opcionales_e_inactivos(self, db_session, escenario):
        cohort, process = escenario["cohort"], escenario["process"]
        obligatorio = _req(db_session, cohort, label="Obligatorio", order_index=0)
        _req(db_session, cohort, label="Opcional", is_required=False, order_index=1)
        _req(db_session, cohort, label="Retirado", is_active=False, order_index=2)

        faltan = RequirementService.missing_required(db_session, process.id)

        assert [r.id for r in faltan] == [obligatorio.id]

    def test_waived_cuenta_como_cumplido(self, db_session, escenario):
        req = _req(db_session, escenario["cohort"], label="Vigencia IMSS")
        process = escenario["process"]
        RequirementService.fulfill(db_session, process.id, req.id, source="officer",
                                   status="waived", commit=False)

        assert RequirementService.missing_required(db_session, process.id) == []

    def test_rejected_no_cuenta_como_cumplido(self, db_session, escenario):
        req = _req(db_session, escenario["cohort"], label="e.Firma")
        process = escenario["process"]
        RequirementService.fulfill(db_session, process.id, req.id, source="officer",
                                   status="rejected", commit=False)

        assert [r.id for r in
                RequirementService.missing_required(db_session, process.id)] == [req.id]


class TestAutoRequirement:
    def test_encuentra_el_de_la_encuesta(self, db_session, escenario):
        cohort = escenario["cohort"]
        _req(db_session, cohort, label="Actas", order_index=0)
        encuesta = _req(db_session, cohort, label="Encuesta de egresados",
                        code=AUTO_SURVEY, auto_source=AUTO_SURVEY, order_index=1)

        hallado = RequirementService.auto_requirement(db_session, cohort.id, AUTO_SURVEY)

        assert hallado is not None and hallado.id == encuesta.id

    def test_none_si_la_convocatoria_ya_tiene_lista_sin_ese_auto_source(
            self, db_session, escenario):
        cohort = escenario["cohort"]
        _req(db_session, cohort, label="Actas", order_index=0)

        assert RequirementService.auto_requirement(db_session, cohort.id, AUTO_SURVEY) is None

    def test_siembra_los_defaults_si_la_convocatoria_esta_vacia(self, db_session, make_cohort):
        from itcj2.apps.titulatec.services.cotejo_requirement_service import (
            CotejoRequirementService, DEFAULTS,
        )

        cohort = make_cohort()

        RequirementService.auto_requirement(db_session, cohort.id, AUTO_SURVEY)

        assert len(CotejoRequirementService.list(db_session, cohort.id)) == len(DEFAULTS)

    def test_no_commitea(self, db_session, make_cohort, monkeypatch):
        """§4.4 exige UN solo commit al enviar la encuesta.

        Si el seed-or-la-lista commiteara aqui, la respuesta a medio escribir se
        quedaria en la BD aunque el cumplimiento fallara despues.
        """
        cohort = make_cohort()
        monkeypatch.setattr(
            db_session, "commit",
            lambda: pytest.fail("auto_requirement no debe commitear"))

        RequirementService.auto_requirement(db_session, cohort.id, AUTO_SURVEY)
