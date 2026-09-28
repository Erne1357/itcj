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

from datetime import datetime
from html.parser import HTMLParser

import pytest
from sqlalchemy.exc import IntegrityError

import itcj2.models  # noqa: F401

from itcj2.apps.titulatec.services.cotejo_requirement_service import (
    CotejoRequirementService, DEFAULTS,
)
from itcj2.apps.titulatec.utils.rich_text import (
    MAX_INFO_HTML_LEN, InfoHtmlTooLong, sanitize_info_html,
)

from tests.fastapi.titulatec.conftest import HEAD_PERMS

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


# El alta pide la ventana (spec 2026-09-27 §B2): fecha obligatoria + hora
# opcional por extremo, igual que el panel. Hora vacía = 00:00 / 23:59:59.
VENTANA_ALTA = {"opens_date": "2031-03-10", "opens_time": "09:30",
                "closes_date": "2031-03-20", "closes_time": ""}
AVISO_VENTANA = "Indica apertura y cierre (el cierre después de la apertura)."


class _InputsDelAlta(HTMLParser):
    """`name → atributos` de los `<input>` del formulario de alta."""

    def __init__(self):
        super().__init__()
        self.inputs: dict[str, dict] = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "input" and a.get("name"):
            self.inputs[a["name"]] = a


class TestCohortCreate:
    def test_nace_en_draft_con_su_ventana_y_su_lista_de_requisitos(
            self, db_session, client_as, make_head, make_period):
        """Una convocatoria no puede ser publica en el instante en que se crea,
        y nace con la ventana que se tecleó —09:30 tal cual; el cierre sin hora,
        a las 23:59:59—, no con una inventada."""
        from itcj2.apps.titulatec.models import Cohort

        jefa = make_head(perm_codes=("titulatec.cohort.api.create",))
        periodo = make_period()

        resp = client_as(jefa).post("/titulatec/admin/cohorts",
                                    data={"period_id": periodo.id, **VENTANA_ALTA},
                                    follow_redirects=False)

        assert resp.status_code == 303, resp.text[:300]
        assert resp.headers["location"] == "/titulatec/admin/cohorts"
        cohort = db_session.query(Cohort).filter_by(period_id=periodo.id).one()
        assert cohort.status == "draft"
        assert cohort.opens_at == datetime(2031, 3, 10, 9, 30)
        assert cohort.closes_at == datetime(2031, 3, 20, 23, 59, 59)
        assert len(CotejoRequirementService.list(db_session, cohort.id)) == len(DEFAULTS)

    @pytest.mark.parametrize("ventana", [
        {},
        {"opens_date": "2031-03-10", "closes_date": ""},
        {"opens_date": "", "closes_date": "2031-03-20"},
        {"opens_date": "10/03/2031", "closes_date": "2031-03-20"},
        {"opens_date": "2031-03-10", "opens_time": "9h", "closes_date": "2031-03-20"},
        {"opens_date": "2031-03-20", "closes_date": "2031-03-10"},
        {"opens_date": "2031-03-10", "opens_time": "18:00",
         "closes_date": "2031-03-10", "closes_time": "18:00"},
    ], ids=["sin-fechas", "sin-cierre", "sin-apertura", "fecha-basura", "hora-basura",
            "cierre-antes", "cierre-igual"])
    def test_sin_ventana_valida_no_crea_nada_y_vuelve_con_el_aviso(
            self, db_session, client_as, make_head, make_period, ventana):
        """Fechas faltantes o ilegibles, o un cierre que no es POSTERIOR a la
        apertura: 303 a `?error=ventana` y cero convocatorias nuevas —ni la del
        período, ni ninguna otra—. Ya no hay ventana provisional."""
        from itcj2.apps.titulatec.models import Cohort

        jefa = make_head(perm_codes=("titulatec.cohort.api.create",))
        periodo = make_period()
        antes = db_session.query(Cohort).count()

        resp = client_as(jefa).post("/titulatec/admin/cohorts",
                                    data={"period_id": periodo.id, **ventana},
                                    follow_redirects=False)

        assert resp.status_code == 303, resp.text[:300]
        assert resp.headers["location"] == "/titulatec/admin/cohorts?error=ventana"
        assert db_session.query(Cohort).filter_by(period_id=periodo.id).count() == 0
        assert db_session.query(Cohort).count() == antes

    def test_la_lista_pinta_el_aviso_solo_con_el_error_de_ventana(
            self, client_as, make_head, make_period):
        jefa = make_head(perm_codes=HEAD_PERMS + ("titulatec.cohort.api.create",))
        make_period()          # un período libre: la página ofrece el alta
        c = client_as(jefa)

        con_error = c.get("/titulatec/admin/cohorts?error=ventana",
                          follow_redirects=False)
        sin_error = c.get("/titulatec/admin/cohorts", follow_redirects=False)
        otro_error = c.get("/titulatec/admin/cohorts?error=otro",
                           follow_redirects=False)

        assert con_error.status_code == sin_error.status_code == 200
        assert AVISO_VENTANA in con_error.text
        assert AVISO_VENTANA not in sin_error.text
        assert AVISO_VENTANA not in otro_error.text

    def test_el_formulario_de_alta_pide_fecha_y_hora_de_cada_extremo(
            self, client_as, make_head, make_period):
        """Mismo contrato que el panel de ventana: `<input type="date">`
        obligatorio + `<input type="time">` opcional, con su ayuda."""
        jefa = make_head(perm_codes=HEAD_PERMS + ("titulatec.cohort.api.create",))
        make_period()

        resp = client_as(jefa).get("/titulatec/admin/cohorts", follow_redirects=False)

        assert resp.status_code == 200
        alta = resp.text.split('id="new-cohort"', 1)[1]
        parser = _InputsDelAlta()
        parser.feed(alta)
        campos = parser.inputs
        for extremo in ("opens", "closes"):
            fecha, hora = campos[f"{extremo}_date"], campos[f"{extremo}_time"]
            assert fecha["type"] == "date" and "required" in fecha, extremo
            assert hora["type"] == "time" and "required" not in hora, extremo
        assert "vacío = 00:00" in alta
        assert "vacío = 23:59" in alta

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
                                    data={"period_id": periodo.id, **VENTANA_ALTA},
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
