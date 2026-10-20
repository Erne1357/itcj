"""Badge de la solicitud de liberacion de GTV en las pantallas del egresado y en
el expediente de Servicios Escolares (Tarea 5, spec
`2026-09-15-titulatec-liberacion-gtv-design.md` SS6.1/SS6.2).

`SurveyReviewService.summary_for_process` (Tarea 2) ya resuelve el estatus real
de la solicitud; esta tarea solo lo PINTA en tres sitios que antes no sabian que
la encuesta existia:

* Home del alumno (`student/dashboard.html`, `_phases_ctx`): pildora en la fila
  del acordeon (desplegable Y actual) y en la tarjeta grande, mas el bloque
  "Encuesta de egresados" con motivo/liga dentro del panel desplegable.
* Mi cita (`student/cita.html`, `_checklist_ctx`): la fila `auto_source =
  'graduate_survey'` cambia su "Listo"/"Dispensado" generico por el estatus real.
* Expediente de Servicios Escolares (`admin.py::_detail_ctx` +
  `_exp_phase.html`): identico patron al panel de atender de la Tarea 4
  (`_appt_attend.html`), que ya esta en produccion.

Los 4 (pseudo)estados y su pildora (`_macros.html::survey_review_pill`,
Tarea 2): `missing` (pseudo, sin fila) -> "Encuesta pendiente" | `in_review` ->
"En revision" | `rejected` -> "Con observaciones" | `approved` -> "Liberada".
"""
from __future__ import annotations

import lxml.html
import pytest

import itcj2.models  # noqa: F401

DASHBOARD = "/titulatec/student/dashboard"
CITA = "/titulatec/student/cita"
SURVEY_URL = "/titulatec/encuesta-egresados"

# status -> texto de la pildora (`_macros.html::survey_review_pill`).
PILL_TEXT = {
    "missing": "Encuesta pendiente",
    "in_review": "En revisión",
    "rejected": "Con observaciones",
    "approved": "Liberada",
}


# ---------------------------------------------------------------------------
# Utilidades de lectura del HTML (propias del archivo: no se tocan los
# helpers de `test_student_dashboard_html.py`, que tiene su propio contrato).
# ---------------------------------------------------------------------------
def _doc(resp):
    assert resp.status_code == 200, resp.text[:400]
    return lxml.html.fromstring(resp.text)


def _text(el) -> str:
    return " ".join(el.text_content().split())


def _phase_item(doc, n: int):
    """El `<div data-tt-phase="n">` del acordeon: fila desplegable O actual,
    con su panel (visible u oculto) SIEMPRE dentro, aunque `hidden` lo tape a
    los ojos: lxml lee el HTML servido, no lo que el CSS decide mostrar."""
    items = doc.xpath('//*[@data-tt-phase="%d"]' % n)
    assert items, "no existe la fase %d en el acordeon" % n
    return items[0]


def _hero(doc):
    return doc.xpath('//*[@id="tt-fase-actual"]')[0]


def _survey_row(doc):
    """Fila 'Encuesta de egresados' del checklist de Mi cita (`cita.html`)."""
    hits = doc.xpath('//div[contains(@class,"flex-grow-1")]'
                     '[contains(., "Encuesta de egresados")]')
    assert hits, "no se encontro la fila de la encuesta en el checklist de Mi cita"
    return hits[0].getparent()


# ===========================================================================
# Home — acordeon: fase 2 NO actual ("visible desde la fase 0")
# ===========================================================================
class TestHomeAcordeon:

    @pytest.mark.parametrize("status", ["missing", "in_review", "rejected", "approved"])
    def test_la_fila_desplegable_muestra_estatus_y_liga_solo_en_missing(
        self, db_session, seed_phase_defs, make_student, make_process,
        make_survey_review, client_as, status,
    ):
        """Fase 2 en fase 0 (futura, ni siquiera empezada): la fila trae la
        pildora real, y la liga a la encuesta solo si de verdad no ha enviado
        nada (`missing`). El resto de la app no habilita nada hasta que
        llegues a la fase; esta es la excepcion deliberada (spec SS6.1)."""
        seed_phase_defs()
        student = make_student()
        process = make_process(student, current_phase=0)
        if status != "missing":
            make_survey_review(process, status=status)

        resp = client_as(student).get(DASHBOARD)
        doc = _doc(resp)
        fila = _text(_phase_item(doc, 2))

        assert PILL_TEXT[status] in fila
        if status == "missing":
            assert SURVEY_URL in resp.text
            assert "Contestar la encuesta" in resp.text
        else:
            assert SURVEY_URL not in resp.text

    def test_el_motivo_de_rechazo_sale_escapado(
        self, db_session, seed_phase_defs, make_student, make_process,
        make_survey_review, client_as,
    ):
        seed_phase_defs()
        student = make_student()
        process = make_process(student, current_phase=0)
        make_survey_review(process, status="rejected",
                           reason="<b>Falta</b> constancia de Servicio Social")

        resp = client_as(student).get(DASHBOARD)

        assert resp.status_code == 200, resp.text[:400]
        assert "&lt;b&gt;Falta&lt;/b&gt; constancia" in resp.text
        assert "<b>Falta</b> constancia" not in resp.text

    def test_fase_futura_conserva_el_texto_generico_y_agrega_la_encuesta(
        self, db_session, seed_phase_defs, make_student, make_process, client_as,
    ):
        """La excepcion es ADITIVA: el aviso de 'aun no te toca' sigue ahi, y
        la encuesta se agrega encima (no lo sustituye)."""
        seed_phase_defs()
        student = make_student()
        process = make_process(student, current_phase=0)

        doc = _doc(client_as(student).get(DASHBOARD))
        fila = _text(_phase_item(doc, 2))

        assert "Se habilitará cuando llegues a esta fase" in fila
        assert PILL_TEXT["missing"] in fila


# ===========================================================================
# Home — tarjeta grande + fila actual: fase 2 ES la actual
# ===========================================================================
class TestHomeTarjetaActual:

    @pytest.mark.parametrize("status", ["missing", "in_review", "rejected", "approved"])
    def test_pildora_en_tarjeta_grande_y_en_fila_actual(
        self, db_session, seed_phase_defs, make_student, make_process,
        make_survey_review, client_as, status,
    ):
        seed_phase_defs()
        student = make_student()
        process = make_process(student, current_phase=2)
        if status != "missing":
            make_survey_review(process, status=status)

        doc = _doc(client_as(student).get(DASHBOARD))

        assert PILL_TEXT[status] in _text(_hero(doc)), "falta en la tarjeta grande"
        assert PILL_TEXT[status] in _text(_phase_item(doc, 2)), "falta en la fila actual"

    def test_la_tarjeta_grande_no_trae_la_liga_ni_el_motivo(
        self, db_session, seed_phase_defs, make_student, make_process,
        make_survey_review, client_as,
    ):
        """La liga y el motivo viven en el panel desplegable (y en Mi cita);
        la tarjeta de la fase actual solo enseña la pildora."""
        seed_phase_defs()
        student = make_student()
        process = make_process(student, current_phase=2)
        make_survey_review(process, status="rejected", reason="Falta un sello")

        doc = _doc(client_as(student).get(DASHBOARD))
        hero_txt = _text(_hero(doc))

        assert SURVEY_URL not in hero_txt
        assert "Falta un sello" not in hero_txt


# ===========================================================================
# Mi cita — la fila del checklist con `auto_source = 'graduate_survey'`
# ===========================================================================
class TestMiCita:

    @pytest.mark.parametrize("status", ["missing", "in_review", "rejected", "approved"])
    def test_la_fila_muestra_estatus_y_la_liga_solo_en_missing(
        self, db_session, seed_phase_defs, make_student, make_process,
        make_survey_review, client_as, status,
    ):
        seed_phase_defs()
        student = make_student()
        process = make_process(student, current_phase=2)
        if status != "missing":
            make_survey_review(process, status=status)

        doc = _doc(client_as(student).get(CITA))
        fila = _survey_row(doc)

        assert PILL_TEXT[status] in _text(fila)
        tiene_liga = bool(fila.xpath('.//a[contains(@href, "encuesta-egresados")]'))
        assert tiene_liga == (status == "missing"), (
            f"status={status!r}: liga presente={tiene_liga}")

    def test_el_motivo_de_rechazo_sale_escapado(
        self, db_session, seed_phase_defs, make_student, make_process,
        make_survey_review, client_as,
    ):
        seed_phase_defs()
        student = make_student()
        process = make_process(student, current_phase=2)
        make_survey_review(process, status="rejected",
                           reason="<b>Falta</b> Servicio Social")

        resp = client_as(student).get(CITA)

        assert resp.status_code == 200, resp.text[:400]
        assert "&lt;b&gt;Falta&lt;/b&gt; Servicio Social" in resp.text
        assert "<b>Falta</b> Servicio Social" not in resp.text


# ===========================================================================
# Expediente (Servicios Escolares) — mismo patron que el panel de atender (T4)
# ===========================================================================
class TestExpediente:

    @pytest.fixture()
    def expediente(self, db_session, seed_phase_defs, seed_document_types,
                   make_program, make_cohort, make_student, make_process, make_head):
        from itcj2.apps.titulatec.models import CotejoRequirement

        seed_phase_defs()
        seed_document_types()
        cohort = make_cohort()
        process = make_process(make_student(), cohort=cohort,
                               program=make_program("Ingenieria del Badge"),
                               current_phase=2)
        req = CotejoRequirement(cohort_id=cohort.id, label="Encuesta de egresados",
                                icon="clipboard-check", auto_source="graduate_survey",
                                order_index=0)
        db_session.add(req)
        db_session.flush()
        oficial = make_head()
        return {"process": process, "cohort": cohort, "req": req, "oficial": oficial}

    @pytest.mark.parametrize("status", ["missing", "in_review", "rejected", "approved"])
    def test_la_fila_muestra_el_estatus_de_la_solicitud_de_gtv(
        self, db_session, expediente, make_survey_review, client_as, status,
    ):
        if status != "missing":
            make_survey_review(expediente["process"], status=status)

        resp = client_as(expediente["oficial"]).get(
            f"/titulatec/admin/processes/{expediente['process'].id}")

        assert resp.status_code == 200, resp.text[:400]
        assert PILL_TEXT[status] in resp.text
        assert "Lo acredita el sistema" not in resp.text, (
            "la fila de la encuesta ya no debe caer en el mensaje generico "
            "de los demas requisitos automaticos")

    def test_el_motivo_de_rechazo_sale_escapado(
        self, db_session, expediente, make_survey_review, client_as,
    ):
        make_survey_review(expediente["process"], status="rejected",
                           reason="<b>Falta</b> constancia")

        resp = client_as(expediente["oficial"]).get(
            f"/titulatec/admin/processes/{expediente['process'].id}")

        assert "&lt;b&gt;Falta&lt;/b&gt; constancia" in resp.text
        assert "<b>Falta</b> constancia" not in resp.text

    def test_liberada_ensena_quien_y_cuando(
        self, db_session, expediente, make_survey_review, client_as, make_head,
    ):
        gtv = make_head(first_name="GTV", last_name="FICTICIA")
        make_survey_review(expediente["process"], status="approved", reviewer=gtv)

        resp = client_as(expediente["oficial"]).get(
            f"/titulatec/admin/processes/{expediente['process'].id}")

        assert resp.status_code == 200, resp.text[:400]
        assert "Liberada por GTV" in resp.text


# ===========================================================================
# Forma del contexto: dict plano, mismo invariante que el resto de la app
# ===========================================================================
class TestFormaDelContexto:
    def test_phases_ctx_cuelga_survey_solo_en_review_appointment(
        self, db_session, seed_phase_defs, make_student, make_process,
    ):
        from itcj2.apps.titulatec.pages.student import _phases_ctx

        seed_phase_defs()
        process = make_process(make_student(), current_phase=0)

        ctx = _phases_ctx(db_session, process)

        for card in ctx["phases"]:
            if card["code"] == "review_appointment":
                assert card["survey"] is not None
                assert card["survey"]["status"] == "missing"
                assert card["survey"]["url"] == SURVEY_URL
            else:
                assert card["survey"] is None, (
                    f"la fase {card['number']} no deberia traer 'survey'")

    def test_el_ctx_no_lleva_objetos_orm(
        self, db_session, seed_phase_defs, make_student, make_process,
        make_survey_review,
    ):
        """Mismo invariante que `test_cita_checklist.py`: la plantilla se
        pinta DESPUES del `db.close()` de la ruta."""
        from itcj2.apps.titulatec.pages.student import _phases_ctx

        seed_phase_defs()
        process = make_process(make_student(), current_phase=0)
        make_survey_review(process, status="rejected", reason="x")

        ctx = _phases_ctx(db_session, process)
        card = next(c for c in ctx["phases"] if c["code"] == "review_appointment")

        for valor in card["survey"].values():
            assert not hasattr(valor, "_sa_instance_state"), (
                f"'survey' trae un objeto ORM: {valor!r}")


# ===========================================================================
# Historial: las 4 etiquetas nuevas de `_EVENT_LABELS`
# ===========================================================================
class TestHistorial:
    @pytest.mark.parametrize("event_type,etiqueta", [
        ("survey_review_submitted", "Enviaste la encuesta de egresados"),
        ("survey_review_approved", "Gestión Tecnológica y Vinculación liberó tu encuesta"),
        ("survey_review_rejected", "Gestión Tecnológica y Vinculación dejó observaciones"),
        ("survey_review_revoked", "Se revocó la liberación de tu encuesta"),
    ])
    def test_evento_trae_su_etiqueta(
        self, db_session, seed_phase_defs, make_student, make_process,
        event_type, etiqueta,
    ):
        from itcj2.apps.titulatec.models import ProcessEvent
        from itcj2.apps.titulatec.pages.student import _phases_ctx

        seed_phase_defs()
        process = make_process(make_student(), current_phase=2)
        db_session.add(ProcessEvent(process_id=process.id, event_type=event_type,
                                    phase_number=2))
        db_session.flush()

        ctx = _phases_ctx(db_session, process)
        card = next(c for c in ctx["phases"] if c["number"] == 2)

        assert [e["label"] for e in card["events"]] == [etiqueta]
