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
4. `info_html` (2026-09-15): la «Informacion para el alumno» con formato. El
   servicio la guarda SANITIZADA, vaciar el editor la borra, excederse del tope
   no escribe nada y el candado del requisito automatico sigue en pie.
"""
from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

import itcj2.models  # noqa: F401

from itcj2.apps.titulatec.services.cotejo_requirement_service import (
    CotejoRequirementService, DEFAULTS,
)
from itcj2.apps.titulatec.utils.rich_text import (
    MAX_INFO_HTML_LEN, InfoHtmlTooLong, sanitize_info_html,
)

AUTO_SURVEY = "graduate_survey"

# Copia APROBADA por el usuario (diseno 2026-09-15). Se fija aqui a proposito y no
# se importa del servicio: cambiarla es una decision de producto, no un refactor.
INFO_ACTA = ("<p>Debe ser el <strong>mismo documento que subiste en TitulaTec</strong> "
             "(fase 1). Llévalo en original.</p>")
INFO_CURP = ("<p>Debe ser la <strong>misma CURP certificada que subiste en TitulaTec"
             "</strong> (fase 1), impresa.</p>")


class TestDefaults:
    def test_son_6_tuplas_con_code_auto_source_e_info(self):
        assert all(len(t) == 6 for t in DEFAULTS), (
            "DEFAULTS es (icon, label, hint, code, auto_source, info_html): `code` "
            "da identidad estable, `auto_source` marca lo que acredita el sistema "
            "e `info_html` es la informacion enriquecida por defecto."
        )

    def test_solo_la_encuesta_trae_auto_source(self):
        autos = {code: auto for (_i, _l, _h, code, auto, _info) in DEFAULTS if auto}

        assert autos == {AUTO_SURVEY: AUTO_SURVEY}

    def test_todos_los_codes_son_unicos_y_no_vacios(self):
        codes = [code for (_i, _l, _h, code, _a, _info) in DEFAULTS]

        assert all(codes) and len(set(codes)) == len(codes)


class TestInfoPorDefecto:
    def test_solo_acta_y_curp_traen_informacion_y_es_la_aprobada(self):
        infos = {code: info for (_i, _l, _h, code, _a, info) in DEFAULTS if info}

        assert infos == {"birth_certificates": INFO_ACTA, "curp": INFO_CURP}, (
            "los demas —biblioteca incluida— quedan vacios a proposito: Servicios "
            "Escolares escribe los datos reales, no se siembran placeholders")

    def test_la_informacion_por_defecto_ya_es_canonica(self):
        """Si no lo fuera, lo sembrado y lo que ve el alumno (re-sanitizado al
        pintar) serian dos cadenas distintas."""
        for (_i, _l, _h, code, _a, info) in DEFAULTS:
            if info:
                assert sanitize_info_html(info) == info, code

    def test_seed_defaults_siembra_la_informacion(self, db_session, make_cohort):
        cohort = make_cohort()

        CotejoRequirementService.seed_defaults(db_session, cohort.id, commit=False)

        con_info = {r.code: r.info_html
                    for r in CotejoRequirementService.list(db_session, cohort.id)
                    if r.info_html}
        assert con_info == {"birth_certificates": INFO_ACTA, "curp": INFO_CURP}


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
        """Sin la guarda esto NO es un `(False, ...)`: es un 500 en la cara del usuario.

        El `except` no es defensivo ni afloja la prueba —por el camino bueno
        `delete()` vuelve antes de tocar la tabla y nunca se ejecuta—: convierte
        el `IntegrityError` que la FK `ON DELETE RESTRICT` escupe cuando se quita
        la guarda en una asercion sobre el valor devuelto. Asi, quien rompa esto
        lee "falta la guarda" en vez de un traceback de Postgres.
        """
        from itcj2.apps.titulatec.services.requirement_service import RequirementService

        cohort = make_cohort()
        item = CotejoRequirementService.create(db_session, cohort.id, label="Actas",
                                               hint=None, icon=None)
        process = make_process(make_student(), cohort=cohort, current_phase=2)
        RequirementService.fulfill(db_session, process.id, item.id,
                                   source="officer", commit=False)

        try:
            resultado = CotejoRequirementService.delete(db_session, item.id, cohort.id)
        except IntegrityError:
            db_session.rollback()   # deja la sesion usable para las aserciones
            resultado = ("BORRO A CIEGAS -> IntegrityError de la FK "
                         "titulatec_requirement_fulfillments.requirement_id")

        assert resultado == (False, "fulfilled:1"), (
            "`delete()` debe CONTAR los cumplimientos antes del `db.delete` y "
            "negarse. La FK es ON DELETE RESTRICT a proposito (borrar la lista "
            "no puede destruir el credito de quien ya cumplio), asi que sin esa "
            "guarda la UI recibe un IntegrityError crudo, es decir un 500."
        )
        assert [r.id for r in CotejoRequirementService.list(db_session, cohort.id)] == [item.id], (
            "El requisito cumplido sobrevive al intento de borrado."
        )

    def test_inexistente(self, db_session, make_cohort):
        cohort = make_cohort()

        assert CotejoRequirementService.delete(db_session, 987654321, cohort.id) == (
            False, "not_found")


class TestUpdateCandadoAutomatico:
    """El requisito automatico (`auto_source`) no puede volverse opcional ni
    inactivo desde el editor (D9): si se pudiera, `RequirementService.
    missing_required` (que solo mira `is_active=TRUE AND is_required=TRUE`)
    dejaria de exigirlo y la guarda de la fase 2 se desarma en silencio.
    """

    def test_el_automatico_ignora_is_required_e_is_active_en_false(
            self, db_session, make_cohort):
        cohort = make_cohort()
        CotejoRequirementService.seed_defaults(db_session, cohort.id, commit=False)
        encuesta = [r for r in CotejoRequirementService.list(db_session, cohort.id)
                    if r.auto_source == AUTO_SURVEY][0]

        item = CotejoRequirementService.update(
            db_session, encuesta.id, cohort.id,
            is_required=False, is_active=False, label="Encuesta (editada)",
            hint="nuevo hint", icon="stars")

        assert (item.is_required, item.is_active) == (True, True), (
            "un requisito con auto_source debe quedar SIEMPRE required+active, "
            "sin importar lo que llegue del formulario"
        )
        assert (item.label, item.hint, item.icon) == (
            "Encuesta (editada)", "nuevo hint", "stars"), (
            "label/hint/icon si deben seguir siendo editables en el automatico"
        )

    def test_un_requisito_normal_si_puede_quedar_opcional_e_inactivo(
            self, db_session, make_cohort):
        cohort = make_cohort()
        item = CotejoRequirementService.create(db_session, cohort.id, label="Normal",
                                               hint=None, icon=None)

        item = CotejoRequirementService.update(
            db_session, item.id, cohort.id, is_required=False, is_active=False)

        assert (item.is_required, item.is_active) == (False, False), (
            "el candado es SOLO para auto_source: un requisito normal sigue "
            "pudiendo quedar opcional e inactivo"
        )


class TestInfoHtmlEnEscritura:
    """El servicio es la primera de las DOS sanitizaciones (la otra es al pintar)."""

    SUCIO = ('<p onclick="alert(1)">Trae <strong>original</strong>'
             '<script>alert(2)</script> <a href="javascript:alert(3)">x</a> '
             '<a href="https://www.itcj.edu.mx">itcj</a></p><img src=x onerror=alert(4)>')

    @staticmethod
    def _assert_limpio(valor):
        assert valor is not None
        for veneno in ("<script", "onclick", "onerror", "javascript:", "<img"):
            assert veneno not in valor.lower(), veneno
        assert "<strong>original</strong>" in valor
        assert 'href="https://www.itcj.edu.mx"' in valor

    def test_create_guarda_sanitizado(self, db_session, make_cohort):
        cohort = make_cohort()

        item = CotejoRequirementService.create(db_session, cohort.id, label="Actas",
                                               hint=None, icon=None, info_html=self.SUCIO)

        db_session.refresh(item)
        self._assert_limpio(item.info_html)

    def test_create_sin_informacion_queda_null(self, db_session, make_cohort):
        cohort = make_cohort()

        item = CotejoRequirementService.create(db_session, cohort.id, label="Actas",
                                               hint=None, icon=None)

        assert item.info_html is None

    def test_update_guarda_sanitizado(self, db_session, make_cohort):
        cohort = make_cohort()
        item = CotejoRequirementService.create(db_session, cohort.id, label="Actas",
                                               hint=None, icon=None)

        item = CotejoRequirementService.update(db_session, item.id, cohort.id,
                                               info_html=self.SUCIO)

        db_session.refresh(item)
        self._assert_limpio(item.info_html)

    def test_update_sin_la_llave_no_toca_la_informacion(self, db_session, make_cohort):
        """Un formulario viejo (o cualquier llamador) que no manda `info_html` no la borra."""
        cohort = make_cohort()
        item = CotejoRequirementService.create(db_session, cohort.id, label="Actas",
                                               hint=None, icon=None,
                                               info_html="<p>previa</p>")

        CotejoRequirementService.update(db_session, item.id, cohort.id, label="Renombrado")

        db_session.refresh(item)
        assert (item.label, item.info_html) == ("Renombrado", "<p>previa</p>")

    @pytest.mark.parametrize("vacio", [None, "", "<p><br></p>", "   "])
    def test_update_con_vacio_borra_la_informacion(self, db_session, make_cohort, vacio):
        """A diferencia de `hint`, aqui `None` SI se escribe: vaciar el editor es
        exactamente la jefa quitando la informacion."""
        cohort = make_cohort()
        item = CotejoRequirementService.create(db_session, cohort.id, label="Actas",
                                               hint=None, icon=None,
                                               info_html="<p>previa</p>")

        CotejoRequirementService.update(db_session, item.id, cohort.id, info_html=vacio)

        db_session.refresh(item)
        assert item.info_html is None

    def test_el_automatico_conserva_el_candado_y_si_admite_informacion(
            self, db_session, make_cohort):
        cohort = make_cohort()
        CotejoRequirementService.seed_defaults(db_session, cohort.id, commit=False)
        encuesta = [r for r in CotejoRequirementService.list(db_session, cohort.id)
                    if r.auto_source == AUTO_SURVEY][0]

        item = CotejoRequirementService.update(
            db_session, encuesta.id, cohort.id, is_required=False, is_active=False,
            info_html='<p>Contesta <em>antes</em> <script>x()</script></p>')

        assert (item.is_required, item.is_active) == (True, True), (
            "la informacion no puede ser la puerta trasera del candado D9")
        assert item.info_html == "<p>Contesta <em>antes</em> </p>"

    def test_update_demasiado_largo_no_escribe_nada(self, db_session, make_cohort):
        """Se sanitiza ANTES de cualquier `setattr`: nada queda a medias en la sesion."""
        cohort = make_cohort()
        item = CotejoRequirementService.create(db_session, cohort.id, label="Original",
                                               hint=None, icon=None,
                                               info_html="<p>previa</p>")

        with pytest.raises(InfoHtmlTooLong):
            CotejoRequirementService.update(
                db_session, item.id, cohort.id, label="Cambiado",
                info_html="<p>" + "a" * MAX_INFO_HTML_LEN + "</p>")

        assert not db_session.dirty, "quedaron cambios a medias en la sesion"
        assert (item.label, item.info_html) == ("Original", "<p>previa</p>")

    def test_create_demasiado_largo_no_crea(self, db_session, make_cohort):
        cohort = make_cohort()

        with pytest.raises(InfoHtmlTooLong):
            CotejoRequirementService.create(db_session, cohort.id, label="X", hint=None,
                                            icon=None,
                                            info_html="a" * (MAX_INFO_HTML_LEN + 1))

        assert CotejoRequirementService.list(db_session, cohort.id, active_only=False) == []

    def test_to_dict_incluye_info_html(self, db_session, make_cohort):
        cohort = make_cohort()
        item = CotejoRequirementService.create(db_session, cohort.id, label="Actas",
                                               hint=None, icon=None,
                                               info_html="<p>hola</p>")

        assert item.to_dict()["info_html"] == "<p>hola</p>"


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

    def test_la_ruta_es_duena_de_la_transaccion_y_seed_no_commitea(
            self, db_session, client_as, make_head, make_period, monkeypatch):
        """Quien cierra la transaccion es `cohort_create`, no `seed_defaults`.

        El test de arriba NO ve esto: hoy no hay ni una sentencia entre el
        `seed_defaults` y el `commit()` final, asi que con `commit=True` el
        estado final en BD es identico —el commit del callee persiste todo y el
        del caller es un no-op— y los 511 tests de la app siguen verdes. La
        atomicidad se sostiene por accidente del hueco vacio, no por estructura.

        En cuanto alguien meta algo en ese hueco (otra consulta, una
        notificacion, una validacion mas), un fallo ahi dejaria COMMITEADA una
        convocatoria a medias: el `Cohort(status='draft')` y sus 8 requisitos en
        disco, todo lo posterior revertido y un 500 para el usuario. Datos
        huerfanos en silencio, no un crash. Por eso aqui no se fija el estado
        final sino QUIEN llama a `commit()`.
        """
        import sys

        jefa = make_head(perm_codes=("titulatec.cohort.api.create",))
        periodo = make_period()

        commit_real = db_session.commit
        pilas: list[list[str]] = []

        def commit_espiado():
            pila, marco = [], sys._getframe(1)
            while marco is not None:
                pila.append(marco.f_code.co_name)
                marco = marco.f_back
            pilas.append(pila)
            return commit_real()

        # Mismo idiom que `test_sin_commit_no_commitea`: el handler recibe un
        # proxy de ESTA sesion (`_TestSession.__getattr__`), asi que el parche
        # sobre la instancia lo alcanza.
        monkeypatch.setattr(db_session, "commit", commit_espiado)

        resp = client_as(jefa).post("/titulatec/admin/cohorts",
                                    data={"period_id": periodo.id},
                                    follow_redirects=False)

        assert resp.status_code == 303, resp.text[:300]
        assert [p for p in pilas if "seed_defaults" in p] == [], (
            "`seed_defaults` commiteo por su cuenta dentro de `cohort_create`. "
            "Debe llamarse con commit=False: la ruta es la duena de la "
            "transaccion, y devolverle esa frontera al callee hace que un fallo "
            "posterior deje media convocatoria persistida."
        )
        # Contraparte positiva: si nadie commiteara, la asercion de arriba
        # pasaria vacia y no probaria nada.
        assert [p for p in pilas if "cohort_create" in p], (
            "Nadie commiteo la creacion de la convocatoria; el espia no vio la "
            "transaccion que se pretende fijar."
        )
