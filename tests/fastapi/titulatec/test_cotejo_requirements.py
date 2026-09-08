"""DEFAULTS con identidad estable, borrado con guarda, y la convocatoria en draft.

Tres cosas que estaban a medio cablear:

1. `DEFAULTS` no tenia `code` ni `auto_source`, asi que nada podia decir "este
   requisito lo acredita la encuesta". Es la UNICA fuente de `auto_source`.
2. `delete()` devolvia `bool` y borraba a ciegas. Bajo el `ON DELETE RESTRICT`
   de `titulatec_requirement_fulfillments` eso revienta con un IntegrityError
   crudo en cuanto un alumno ya cumplio el requisito.
3. Toda convocatoria nacia `status='open'` con fechas NULL, asi que el predicado
   de "convocatoria publica abierta" era verdadero para TODAS. Ahora nace
   `draft` y la abre el editor de ventana.
"""
from __future__ import annotations

import pytest

import itcj2.models  # noqa: F401

from itcj2.apps.titulatec.services.cotejo_requirement_service import (
    CotejoRequirementService, DEFAULTS,
)

AUTO_SURVEY = "graduate_survey"


class TestDefaults:
    def test_son_5_tuplas_con_code_y_auto_source(self):
        assert all(len(t) == 5 for t in DEFAULTS), (
            "DEFAULTS pasa a (icon, label, hint, code, auto_source): `code` da "
            "identidad estable y `auto_source` marca lo que acredita el sistema."
        )

    def test_solo_la_encuesta_trae_auto_source(self):
        autos = {code: auto for (_i, _l, _h, code, auto) in DEFAULTS if auto}

        assert autos == {AUTO_SURVEY: AUTO_SURVEY}

    def test_todos_los_codes_son_unicos_y_no_vacios(self):
        codes = [code for (_i, _l, _h, code, _a) in DEFAULTS]

        assert all(codes) and len(set(codes)) == len(codes)


class TestSeedDefaults:
    def test_siembra_code_y_auto_source(self, db_session, make_cohort):
        cohort = make_cohort()

        n = CotejoRequirementService.seed_defaults(db_session, cohort.id, commit=False)

        filas = CotejoRequirementService.list(db_session, cohort.id)
        assert n == len(DEFAULTS) == len(filas)
        encuesta = [r for r in filas if r.auto_source == AUTO_SURVEY]
        assert len(encuesta) == 1
        assert encuesta[0].code == AUTO_SURVEY

    def test_sin_commit_no_commitea(self, db_session, make_cohort, monkeypatch):
        cohort = make_cohort()
        monkeypatch.setattr(
            db_session, "commit",
            lambda: pytest.fail("seed_defaults(commit=False) no debe commitear"))

        CotejoRequirementService.seed_defaults(db_session, cohort.id, commit=False)

    def test_es_idempotente(self, db_session, make_cohort):
        cohort = make_cohort()
        CotejoRequirementService.seed_defaults(db_session, cohort.id, commit=False)

        assert CotejoRequirementService.seed_defaults(
            db_session, cohort.id, commit=False) == 0


class TestDelete:
    def test_borra_si_nadie_lo_cumplio(self, db_session, make_cohort):
        cohort = make_cohort()
        item = CotejoRequirementService.create(db_session, cohort.id, label="Sobra",
                                               hint=None, icon=None)

        ok, motivo = CotejoRequirementService.delete(db_session, item.id, cohort.id)

        assert (ok, motivo) == (True, "ok")
        assert CotejoRequirementService.list(db_session, cohort.id) == []

    def test_se_niega_si_alguien_ya_lo_cumplio(self, db_session, make_cohort,
                                               make_student, make_process):
        from itcj2.apps.titulatec.services.requirement_service import RequirementService

        cohort = make_cohort()
        item = CotejoRequirementService.create(db_session, cohort.id, label="Actas",
                                               hint=None, icon=None)
        process = make_process(make_student(), cohort=cohort, current_phase=2)
        RequirementService.fulfill(db_session, process.id, item.id,
                                   source="officer", commit=False)

        ok, motivo = CotejoRequirementService.delete(db_session, item.id, cohort.id)

        assert ok is False
        assert motivo == "fulfilled:1"
        assert [r.id for r in CotejoRequirementService.list(db_session, cohort.id)] == [item.id]

    def test_inexistente(self, db_session, make_cohort):
        cohort = make_cohort()

        assert CotejoRequirementService.delete(db_session, 987654321, cohort.id) == (
            False, "not_found")


class TestCohortCreate:
    def test_nace_en_draft_y_con_su_lista_de_requisitos(
            self, db_session, client_as, make_head, make_period):
        """Una convocatoria no puede ser publica en el instante en que se crea."""
        from itcj2.apps.titulatec.models import Cohort

        jefa = make_head(perm_codes=("titulatec.cohort.api.create",))
        periodo = make_period()

        resp = client_as(jefa).post("/titulatec/admin/cohorts",
                                    data={"period_id": periodo.id},
                                    follow_redirects=False)

        assert resp.status_code == 303, resp.text[:300]
        cohort = db_session.query(Cohort).filter_by(period_id=periodo.id).one()
        assert cohort.status == "draft"
        assert len(CotejoRequirementService.list(db_session, cohort.id)) == len(DEFAULTS)
