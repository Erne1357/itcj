"""El oficial marca y desmarca requisitos de cotejo desde el expediente (§5.4).

Sin esta ruta el checklist es de solo lectura: nadie puede acreditar lo que el
alumno lleva fisicamente a la ventanilla, y la fase 2 —que desde la tarea
anterior mira los cumplimientos— quedaria trabada para todo el mundo.

PERMISO NUEVO: `titulatec.process.api.requirement.mark`. Se siembra en el DML
de delta, asi que aqui se crea con las fabricas del harness (`make_head` ->
`make_role` -> `make_perms`), que insertan la fila de `core_permissions` DENTRO
de la transaccion del test. Depender del DML seria depender de `database/`, que
esta gitignored y nunca llega a CI.
"""
from __future__ import annotations

from urllib.parse import unquote

import pytest

import itcj2.models  # noqa: F401

MARK = "titulatec.process.api.requirement.mark"
READ_ALL = "titulatec.process.api.read.all"     # -> officer_programs() == "ALL"
APPROVE = "titulatec.process.api.approve_phase"
MARK_PERMS = (READ_ALL, "titulatec.process.page.detail", MARK)


def _msg(resp) -> str:
    return unquote(resp.headers.get("X-Tt-Error", ""))


def _fulfillment(db, process_id, rid):
    from itcj2.apps.titulatec.models import RequirementFulfillment
    return (db.query(RequirementFulfillment)
            .filter_by(process_id=process_id, requirement_id=rid).first())


def _events(db, process_id, tipo):
    from itcj2.apps.titulatec.models import ProcessEvent
    return (db.query(ProcessEvent)
            .filter_by(process_id=process_id, event_type=tipo).all())


@pytest.fixture()
def esc(db_session, seed_phase_defs, seed_document_types, make_head, make_student,
        make_cohort, make_process, make_perms, make_role, make_program):
    """Expediente listo + un oficial CON el permiso nuevo.

    `make_perms` y `make_role` entran explicitos en la firma para dejar dicho de
    donde sale la fila de `core_permissions`: `make_head(perm_codes=...)` los
    encadena por dentro.

    El proceso lleva CARRERA a proposito. `scope_service.process_in_scope`
    resuelve `program_id IS NULL` ANTES de mirar `read.all` (`scope_service.py:
    131-132`): sin carrera, solo quien tenga `titulatec.officers.api.manage` ve
    el cubo «Sin carrera» y `assert_process_in_scope` contestaria 404 a TODOS,
    incluido el actor legitimo. Es el patron de `test_phase_guard.py:60-65`.
    """
    from itcj2.apps.titulatec.models import CotejoRequirement

    seed_phase_defs()
    seed_document_types()
    cohort = make_cohort()
    process = make_process(make_student(), cohort=cohort,
                           program=make_program("Ingenieria Ficticia A"),
                           current_phase=2)
    make_perms((MARK,))                      # el codigo existe en esta transaccion
    oficial = make_head(perm_codes=MARK_PERMS)

    def _req(label="Actas de nacimiento", auto_source=None, order_index=0):
        row = CotejoRequirement(cohort_id=cohort.id, label=label,
                                icon="check2-square", auto_source=auto_source,
                                order_index=order_index)
        db_session.add(row)
        db_session.flush()
        return row

    return {"cohort": cohort, "process": process, "oficial": oficial, "req": _req}


def _url(process_id, rid):
    return f"/titulatec/admin/processes/{process_id}/requisitos/{rid}"


class TestMarcado:
    def test_marca_y_deja_bitacora(self, db_session, esc, client_as):
        proc, req = esc["process"], esc["req"]()

        resp = client_as(esc["oficial"]).post(_url(proc.id, req.id),
                                              data={"action": "mark",
                                                    "note": "Traia originales"},
                                              follow_redirects=False)

        assert resp.status_code == 200, resp.text[:300]
        fila = _fulfillment(db_session, proc.id, req.id)
        assert fila is not None
        assert fila.status == "fulfilled"
        assert fila.source == "officer"
        assert fila.checked_by_id == esc["oficial"].id
        assert fila.note == "Traia originales"
        assert len(_events(db_session, proc.id, "requirement_fulfilled")) == 1

    def test_waive_registra_la_dispensa(self, db_session, esc, client_as):
        proc, req = esc["process"], esc["req"]()

        resp = client_as(esc["oficial"]).post(_url(proc.id, req.id),
                                              data={"action": "waive",
                                                    "note": "Tramite del SAT caido"},
                                              follow_redirects=False)

        assert resp.status_code == 200, resp.text[:300]
        assert _fulfillment(db_session, proc.id, req.id).status == "waived"

    def test_unmark_borra_y_deja_bitacora(self, db_session, esc, client_as):
        proc, req = esc["process"], esc["req"]()
        cli = client_as(esc["oficial"])
        cli.post(_url(proc.id, req.id), data={"action": "mark"},
                 follow_redirects=False)

        resp = cli.post(_url(proc.id, req.id), data={"action": "unmark"},
                        follow_redirects=False)

        assert resp.status_code == 200, resp.text[:300]
        assert _fulfillment(db_session, proc.id, req.id) is None
        assert len(_events(db_session, proc.id, "requirement_unfulfilled")) == 1

    def test_el_cuerpo_devuelto_trae_el_checklist_ya_marcado(self, esc, client_as):
        """El swap tiene que traer la palomita: si no, el oficial marca a ciegas."""
        proc, req = esc["process"], esc["req"]()

        resp = client_as(esc["oficial"]).post(_url(proc.id, req.id),
                                              data={"action": "mark"},
                                              follow_redirects=False)

        assert resp.status_code == 200
        assert req.label in resp.text
        assert "Desmarcar" in resp.text
        assert "Requisito acreditado" in resp.text

    def test_devuelve_el_cuerpo_del_expediente(self, esc, client_as):
        """Mismo contrato de swap que aprobar/rechazar fase (`_render_detail_body`)."""
        proc, req = esc["process"], esc["req"]()

        resp = client_as(esc["oficial"]).post(_url(proc.id, req.id),
                                              data={"action": "mark"},
                                              follow_redirects=False)

        assert resp.status_code == 200
        assert proc.folio in resp.text


class TestNegativas:
    def test_no_se_marca_a_mano_un_requisito_automatico(self, db_session, esc, client_as):
        proc = esc["process"]
        req = esc["req"](label="Encuesta de egresados", auto_source="graduate_survey")

        resp = client_as(esc["oficial"]).post(_url(proc.id, req.id),
                                              data={"action": "mark"},
                                              follow_redirects=False)

        assert resp.status_code == 400, resp.text[:300]
        assert "sistema" in _msg(resp).lower()
        assert _fulfillment(db_session, proc.id, req.id) is None

    def test_requisito_de_otra_convocatoria(self, db_session, esc, client_as,
                                            make_cohort):
        from itcj2.apps.titulatec.models import CotejoRequirement

        otra = make_cohort()
        ajeno = CotejoRequirement(cohort_id=otra.id, label="Ajeno", icon="book")
        db_session.add(ajeno)
        db_session.flush()
        proc = esc["process"]

        resp = client_as(esc["oficial"]).post(_url(proc.id, ajeno.id),
                                              data={"action": "mark"},
                                              follow_redirects=False)

        assert resp.status_code == 400, resp.text[:300]
        assert _fulfillment(db_session, proc.id, ajeno.id) is None

    def test_proceso_fuera_de_alcance_da_404_uniforme(self, db_session, esc, client_as,
                                                      make_officer, make_program,
                                                      make_perms):
        """404, no 403: el id es secuencial y un 403 seria un contador del padron."""
        make_perms((MARK,))
        otro_prog = make_program(name="Ing. Ajena")
        ajeno, _pos = make_officer([otro_prog], perm_codes=(MARK,))
        proc, req = esc["process"], esc["req"]()

        resp = client_as(ajeno).post(_url(proc.id, req.id), data={"action": "mark"},
                                     follow_redirects=False)

        assert resp.status_code == 404, resp.text[:300]
        assert "X-Tt-Error" not in resp.headers
        assert _fulfillment(db_session, proc.id, req.id) is None


class TestAutorizacion:
    def test_sin_el_permiso_nuevo_no_pasa(self, esc, client_as,
                                          make_app_user_without_perms):
        """El par negativo/positivo sobre el MISMO recurso."""
        proc, req = esc["process"], esc["req"]()
        # NO usar make_head aqui: comparte ROLE_HEAD con el `oficial` de `esc`
        # y make_role solo ANADE permisos, nunca revoca (conftest.py:265-286).
        sin_permiso = make_app_user_without_perms(
            (READ_ALL, "titulatec.process.page.detail"))

        r_no = client_as(sin_permiso).post(_url(proc.id, req.id),
                                           data={"action": "mark"},
                                           follow_redirects=False)
        r_si = client_as(esc["oficial"]).post(_url(proc.id, req.id),
                                              data={"action": "mark"},
                                              follow_redirects=False)

        assert r_no.status_code == 403, (
            f"la ruta contesto {r_no.status_code} a quien NO tiene "
            f"{MARK}. Si es 200, alguien amplio la lista de permisos.")
        assert r_si.status_code == 200, r_si.text[:300]

    def test_el_anonimo_va_al_login(self, esc, client):
        proc, req = esc["process"], esc["req"]()
        client.cookies.clear()

        resp = client.post(_url(proc.id, req.id), data={"action": "mark"},
                           follow_redirects=False)

        assert resp.status_code == 302
        assert "/itcj/login" in resp.headers["location"]


class TestLaPuertaDeLaFase2:
    def test_marcados_los_manuales_la_fase_2_ya_se_aprueba(self, db_session, esc,
                                                           client_as, make_head):
        """Esta ruta es el UNICO camino que abre la guarda de la Tarea 7.

        `make_head` reusa ROLE_HEAD y `make_role` solo ANADE permisos, asi que
        este actor acumula MARK_PERMS + `approve_phase` y el `oficial` de `esc`
        gana `approve_phase` de rebote: ninguna prueba de este archivo afirma
        que NO lo tenga, asi que el efecto es inocuo y queda dicho aqui.

        El requisito con `auto_source` NO se puede marcar por la ruta (400): lo
        acredita el sistema, y aqui se simula ese camino llamando al service,
        que es lo que hara `SurveyService._credit`.
        """
        from itcj2.apps.titulatec.models import CotejoRequirement
        from itcj2.apps.titulatec.services.cotejo_requirement_service import (
            CotejoRequirementService,
        )
        from itcj2.apps.titulatec.services.requirement_service import RequirementService

        proc = esc["process"]
        CotejoRequirementService.seed_defaults(db_session, esc["cohort"].id,
                                               commit=False)
        manuales = (db_session.query(CotejoRequirement)
                    .filter(CotejoRequirement.cohort_id == esc["cohort"].id,
                            CotejoRequirement.is_active.is_(True),
                            CotejoRequirement.auto_source.is_(None))
                    .order_by(CotejoRequirement.order_index)
                    .all())
        assert len(manuales) == 7, (
            "la lista por defecto de la Tarea 4 son 8 requisitos, 1 automatico")

        cli = client_as(make_head(perm_codes=MARK_PERMS + (APPROVE,)))
        aprobar = f"/titulatec/admin/processes/{proc.id}/phase/2/approve"

        antes = cli.post(aprobar, follow_redirects=False)
        assert antes.status_code == 400, (
            "la guarda de la fase 2 (Tarea 7) no esta puesta: sin ella esta "
            "prueba no demuestra nada")

        for r in manuales:
            marcado = cli.post(_url(proc.id, r.id), data={"action": "mark"},
                               follow_redirects=False)
            assert marcado.status_code == 200, marcado.text[:200]

        auto = (db_session.query(CotejoRequirement)
                .filter_by(cohort_id=esc["cohort"].id,
                           auto_source="graduate_survey")
                .first())
        RequirementService.fulfill(db_session, proc.id, auto.id, source="system",
                                   external_ref="survey_response:1")

        despues = cli.post(aprobar, follow_redirects=False)
        assert despues.status_code == 200, _msg(despues) or despues.text[:300]


class TestChecklistEnElExpediente:
    """§5.4 y criterio 3: la palomita se ve Y se pone DESDE el expediente."""

    def _get(self, cli, proc):
        return cli.get(f"/titulatec/admin/processes/{proc.id}",
                       follow_redirects=False)

    def test_el_expediente_pinta_el_checklist_con_su_control(self, esc, client_as):
        proc, req = esc["process"], esc["req"]()

        resp = self._get(client_as(esc["oficial"]), proc)

        assert resp.status_code == 200, resp.text[:300]
        assert req.label in resp.text
        assert f"/requisitos/{req.id}" in resp.text

    def test_sin_el_permiso_el_checklist_es_de_solo_lectura(
            self, esc, client_as, make_app_user_without_perms):
        """Ve la lista, no los botones: un control que 403ea es peor que no estar."""
        proc, req = esc["process"], esc["req"]()
        mirON = make_app_user_without_perms(
            (READ_ALL, "titulatec.process.page.detail"))

        resp = self._get(client_as(mirON), proc)

        assert resp.status_code == 200, resp.text[:300]
        assert req.label in resp.text
        assert "/requisitos/" not in resp.text

    def test_un_requisito_automatico_se_pinta_sin_control(self, esc, client_as):
        proc = esc["process"]
        manual = esc["req"](label="Actas de nacimiento", order_index=0)
        auto = esc["req"](label="Encuesta de egresados",
                          auto_source="graduate_survey", order_index=1)

        resp = self._get(client_as(esc["oficial"]), proc)

        assert resp.status_code == 200, resp.text[:300]
        assert auto.label in resp.text
        assert f"/requisitos/{manual.id}" in resp.text
        assert f"/requisitos/{auto.id}" not in resp.text

    def test_un_requisito_no_encuesta_se_pinta_con_el_mensaje_generico(
            self, db_session, esc, client_as):
        """El "lo acredita el sistema" generico sigue vivo para OTROS
        `auto_source`; solo `graduate_survey` cambia de mensaje (Tarea 5,
        spec 2026-09-15-titulatec-liberacion-gtv D3)."""
        from itcj2.apps.titulatec.models import CotejoRequirement

        proc = esc["process"]
        otro = CotejoRequirement(cohort_id=esc["cohort"].id, label="Otro automatico",
                                 icon="check2-square", auto_source="other_source",
                                 order_index=0)
        db_session.add(otro)
        db_session.flush()

        resp = self._get(client_as(esc["oficial"]), proc)

        assert resp.status_code == 200, resp.text[:300]
        assert "Lo acredita el sistema" in resp.text

    def test_la_encuesta_se_pinta_con_el_estatus_de_gtv_no_generico(
            self, db_session, esc, client_as):
        """La fila `graduate_survey` sustituye "Lo acredita el sistema" por el
        estatus real de la solicitud de liberacion de GTV (D3)."""
        proc = esc["process"]
        esc["req"](label="Encuesta de egresados", auto_source="graduate_survey",
                  order_index=1)

        resp = self._get(client_as(esc["oficial"]), proc)

        assert resp.status_code == 200, resp.text[:300]
        assert "Encuesta pendiente" in resp.text, (
            "sin SurveyReview el pseudo-estado es 'missing' -> 'Encuesta pendiente'")
        assert "Lo acredita el sistema (graduate_survey)" not in resp.text

    def test_ver_el_expediente_no_siembra_requisitos(self, db_session, esc, client_as):
        """Un GET no CONFIGURA nada.

        `RequirementService.list_with_status` enruta a `list_or_seed` ->
        `seed_defaults(commit=True)`: leer el expediente de una convocatoria sin
        lista habria commiteado ocho filas de configuracion como efecto lateral
        de mirar. La siembra es del alta de la convocatoria y de la encuesta, no
        de una visita del oficial.
        """
        from itcj2.apps.titulatec.models import CotejoRequirement

        proc = esc["process"]                 # su convocatoria NO tiene lista
        cohort_id = esc["cohort"].id
        assert db_session.query(CotejoRequirement).filter_by(
            cohort_id=cohort_id).count() == 0, (
            "el escenario debe empezar sin requisitos configurados")

        resp = self._get(client_as(esc["oficial"]), proc)

        assert resp.status_code == 200, resp.text[:300]
        assert db_session.query(CotejoRequirement).filter_by(
            cohort_id=cohort_id).count() == 0, (
            "ver un expediente SEMBRO la lista de requisitos de la convocatoria")
        assert "no tiene requisitos configurados" in resp.text


class TestFormaDelContexto:
    """El contexto va PLANO, y esto lo afirma por FORMA, no por sintoma.

    `conftest.py::_TestSession.close()` es un no-op deliberado, asi que la
    sesion que abre una ruta nunca se cierra de verdad y los objetos ORM nunca
    se desanclan: una plantilla alimentada con instancias del ORM renderiza
    VERDE aqui y lanza `DetachedInstanceError` en produccion, donde
    `process_detail` renderiza DESPUES de su `db.close()`. Ninguna prueba de
    render puede ver esa diferencia; por eso se mira el contexto.
    """

    def test_los_requisitos_del_contexto_son_dicts_planos(self, db_session, esc):
        from itcj2.apps.titulatec.pages.admin import _detail_ctx

        proc = esc["process"]
        esc["req"](label="Actas de nacimiento")
        esc["req"](label="Encuesta de egresados", auto_source="graduate_survey",
                   order_index=1)

        ctx = _detail_ctx(db_session, proc.id, user_id=esc["oficial"].id)

        assert ctx["requisitos"], "el contexto no trae los requisitos"
        for fila in ctx["requisitos"]:
            assert isinstance(fila, dict), (
                f"fila del ORM en el contexto: {fila!r}. La plantilla la leeria "
                "DESPUES del db.close() de `process_detail`.")
            for clave, valor in fila.items():
                assert not hasattr(valor, "_sa_instance_state"), (
                    f"requisitos[]['{clave}'] es un objeto ORM ({valor!r}): en "
                    "produccion lanzaria DetachedInstanceError al renderizar")
