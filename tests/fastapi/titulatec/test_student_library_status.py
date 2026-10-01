"""No adeudo de biblioteca en las pantallas del egresado (Tarea 12, spec
`2026-10-01-titulatec-biblioteca-caja-design.md` §4.10/§4.3/§4.4.4, D4/D9/D17,
Ruling R12 de la revisión de la Tarea 5).

`LibraryClearanceService.summary_for_process` (Tarea 4) y `ClearanceGate`
(Tarea 5) ya resuelven el estado real del no adeudo; esta tarea solo lo PINTA
en tres sitios que antes no sabían que el no adeudo existía -- mismo patrón
que `test_student_survey_badge.py` para la encuesta de egresados:

* Home del alumno (`student/dashboard.html`, `_phases_ctx`): píldora en la
  fila del acordeón (desplegable Y actual) y en la tarjeta grande, más el
  bloque "No adeudo de biblioteca" con los 4 estados de spec §4.10 dentro del
  panel desplegable -- SOLO si la convocatoria exige el requisito
  (`ClearanceGate.library_required`).
* Mi cita (`student/cita.html`, `_checklist_ctx`): la fila `auto_source =
  'library_clearance'` cambia su "Listo"/"Dispensado" genérico por la MISMA
  píldora que el dashboard (sin desglose: spec §4.10 solo pide la píldora ahí).
* Ruling R12: con una cita VIGENTE el panel de "Mi cita" no debe prometer
  "podrás agendar" bajo la cita que ya tiene -- dice que su no adeudo debe
  quedar liberado para que Servicios Escolares pueda liberar su cotejo.

Los 4 (pseudo)estados y su píldora (`_macros.html::library_clearance_pill`):
`missing`/`pending` -> "En Biblioteca" | `awaiting_payment` -> "Por pagar en
Caja" | `cleared` (via `payment`/`no_charge`/`legacy`) -> "Liberado" |
`cleared` vía `prior` -> "Constancia previa".
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import lxml.html
import pytest

import itcj2.models  # noqa: F401

DASHBOARD = "/titulatec/student/dashboard"
CITA = "/titulatec/student/cita"

AUTO_SOURCE_LIBRARY = "library_clearance"

# Mensaje normal de `SelfBookingService.MENSAJES` para los dos motivos de
# biblioteca: el que Ruling R12 prohíbe repetir bajo una cita ya puesta.
_PROMETE_AGENDAR = "Podrás agendar en cuanto se libere tu no adeudo"


# ---------------------------------------------------------------------------
# Utilidades de lectura del HTML (propias del archivo: espejo de
# `test_student_survey_badge.py`, que tiene su propio contrato).
# ---------------------------------------------------------------------------
def _doc(resp):
    assert resp.status_code == 200, resp.text[:400]
    return lxml.html.fromstring(resp.text)


def _text(el) -> str:
    return " ".join(el.text_content().split())


def _phase_item(doc, n: int):
    """El `<div data-tt-phase="n">` del acordeón: fila desplegable O actual,
    con su panel (visible u oculto) SIEMPRE dentro, aunque `hidden` lo tape a
    los ojos: lxml lee el HTML servido, no lo que el CSS decide mostrar."""
    items = doc.xpath('//*[@data-tt-phase="%d"]' % n)
    assert items, "no existe la fase %d en el acordeon" % n
    return items[0]


def _hero(doc):
    return doc.xpath('//*[@id="tt-fase-actual"]')[0]


def _library_row(doc):
    """Fila 'No-adeudo de biblioteca' del checklist de Mi cita (`cita.html`)."""
    hits = doc.xpath('//div[contains(@class,"flex-grow-1")]'
                     '[contains(., "No-adeudo de biblioteca")]')
    assert hits, "no se encontro la fila del no adeudo en el checklist de Mi cita"
    return hits[0].getparent()


def _require_library(db_session, cohort):
    """Activa el candado de biblioteca en esa convocatoria: `CotejoRequirement`
    `auto_source='library_clearance'` ACTIVO. `ClearanceGate.library_required`
    nunca siembra (su propio docstring), así que el dashboard necesita la fila
    YA puesta -- a diferencia del checklist de "Mi cita", que SÍ la siembra
    (`RequirementService.list_with_status` -> `list_or_seed`)."""
    from itcj2.apps.titulatec.models import CotejoRequirement

    req = CotejoRequirement(cohort_id=cohort.id, label="No-adeudo de biblioteca",
                            icon="book", auto_source=AUTO_SOURCE_LIBRARY, order_index=4)
    db_session.add(req)
    db_session.flush()
    return req


# ===========================================================================
# Home — bloque ausente si la convocatoria no exige el no adeudo
# ===========================================================================
class TestDashboardSinRequisito:
    def test_sin_requisito_activo_el_bloque_no_existe(
        self, db_session, seed_phase_defs, make_student, make_cohort, make_process, client_as,
    ):
        seed_phase_defs()
        cohort = make_cohort()
        student = make_student()
        make_process(student, cohort=cohort, current_phase=0)

        doc = _doc(client_as(student).get(DASHBOARD))
        fila = _text(_phase_item(doc, 2))

        assert "No adeudo de biblioteca" not in fila
        assert "En Biblioteca" not in fila

    def test_phases_ctx_no_cuelga_library_sin_el_requisito(
        self, db_session, seed_phase_defs, make_student, make_cohort, make_process,
    ):
        from itcj2.apps.titulatec.pages.student import _phases_ctx

        seed_phase_defs()
        cohort = make_cohort()
        process = make_process(make_student(), cohort=cohort, current_phase=0)

        ctx = _phases_ctx(db_session, process)
        card = next(c for c in ctx["phases"] if c["code"] == "review_appointment")

        assert card["library"] is None


# ===========================================================================
# Home — acordeón: los 4 estados de spec §4.10 (fase 2 NO actual, "visible
# desde la fase 1")
# ===========================================================================
class TestDashboardBloque:

    @pytest.mark.parametrize("status", ["missing", "pending"])
    def test_en_revision_dice_que_el_centro_de_informacion_revisa(
        self, db_session, seed_phase_defs, make_student, make_cohort, make_process, client_as, status,
    ):
        seed_phase_defs()
        cohort = make_cohort()
        _require_library(db_session, cohort)
        student = make_student()
        make_process(student, cohort=cohort, current_phase=0,
                     library_clearance=(None if status == "missing" else "pending"))

        doc = _doc(client_as(student).get(DASHBOARD))
        fila = _text(_phase_item(doc, 2))

        assert "El Centro de Información está revisando tu adeudo" in fila
        assert "En Biblioteca" in fila   # la píldora

    def test_awaiting_payment_desglosa_el_total_y_pinta_la_nota(
        self, db_session, seed_phase_defs, make_student, make_cohort, make_process,
        make_library_clearance, client_as,
    ):
        seed_phase_defs()
        cohort = make_cohort()
        _require_library(db_session, cohort)
        student = make_student()
        process = make_process(student, cohort=cohort, current_phase=0, library_clearance=None)
        make_library_clearance(process, status="awaiting_payment",
                               debt_amount=Decimal("800.00"),
                               donation_amount=Decimal("200.00"),
                               total_amount=Decimal("1000.00"),
                               library_note="Trae tu credencial vigente.")

        doc = _doc(client_as(student).get(DASHBOARD))
        fila = _text(_phase_item(doc, 2))

        assert "Pasa a Caja (Recursos Financieros) a pagar $1,000.00" in fila
        assert "adeudo $800.00" in fila
        assert "donación voluntaria de libro $200.00" in fila
        assert "sin cita, con tu número de control" in fila
        assert "Trae tu credencial vigente." in fila
        assert "Por pagar en Caja" in fila   # la píldora

    def test_awaiting_payment_solo_donacion_omite_el_adeudo_del_desglose(
        self, db_session, seed_phase_defs, make_student, make_cohort, make_process,
        make_library_clearance, client_as,
    ):
        """Adeudo 0 con donación > 0 SIGUE pasando por Caja (D18: solo el
        total EN CERO -los dos montos- libera sin Caja); el desglose no
        inventa un "adeudo $0.00" que nadie cobra."""
        seed_phase_defs()
        cohort = make_cohort()
        _require_library(db_session, cohort)
        student = make_student()
        process = make_process(student, cohort=cohort, current_phase=0, library_clearance=None)
        make_library_clearance(process, status="awaiting_payment",
                               debt_amount=Decimal("0.00"),
                               donation_amount=Decimal("250.00"),
                               total_amount=Decimal("250.00"))

        doc = _doc(client_as(student).get(DASHBOARD))
        fila = _text(_phase_item(doc, 2))

        assert "Pasa a Caja (Recursos Financieros) a pagar $250.00" in fila
        assert "donación voluntaria de libro $250.00" in fila
        assert "adeudo $0.00" not in fila
        assert "adeudo $" not in fila

    @pytest.mark.parametrize("via", ["payment", "no_charge", "legacy"])
    def test_cleared_dice_liberado(
        self, db_session, seed_phase_defs, make_student, make_cohort, make_process,
        make_library_clearance, client_as, via,
    ):
        seed_phase_defs()
        cohort = make_cohort()
        _require_library(db_session, cohort)
        student = make_student()
        process = make_process(student, cohort=cohort, current_phase=0, library_clearance=None)
        make_library_clearance(process, status="cleared", cleared_via=via)

        doc = _doc(client_as(student).get(DASHBOARD))
        fila = _text(_phase_item(doc, 2))

        assert "Liberado" in fila
        assert "Constancia previa registrada" not in fila

    def test_cleared_prior_dice_llevala_a_tu_cotejo(
        self, db_session, seed_phase_defs, make_student, make_cohort, make_process,
        make_library_clearance, client_as,
    ):
        seed_phase_defs()
        cohort = make_cohort()
        _require_library(db_session, cohort)
        student = make_student()
        process = make_process(student, cohort=cohort, current_phase=0, library_clearance=None)
        make_library_clearance(process, status="cleared", cleared_via="prior",
                               prior_issued_on=date.today())

        doc = _doc(client_as(student).get(DASHBOARD))
        fila = _text(_phase_item(doc, 2))

        assert "Constancia previa registrada: llévala a tu cotejo" in fila
        assert "Constancia previa" in fila   # la píldora

    def test_la_nota_de_biblioteca_sale_escapada(
        self, db_session, seed_phase_defs, make_student, make_cohort, make_process,
        make_library_clearance, client_as,
    ):
        seed_phase_defs()
        cohort = make_cohort()
        _require_library(db_session, cohort)
        student = make_student()
        process = make_process(student, cohort=cohort, current_phase=0, library_clearance=None)
        make_library_clearance(process, status="awaiting_payment",
                               debt_amount=Decimal("100.00"), donation_amount=Decimal("0.00"),
                               total_amount=Decimal("100.00"),
                               library_note="<b>Trae</b> tu credencial")

        resp = client_as(student).get(DASHBOARD)

        assert resp.status_code == 200, resp.text[:400]
        assert "&lt;b&gt;Trae&lt;/b&gt; tu credencial" in resp.text
        assert "<b>Trae</b> tu credencial" not in resp.text


# ===========================================================================
# Home — tarjeta grande + fila actual: fase 2 ES la actual (solo la píldora,
# sin el bloque -- mismo contrato que la encuesta)
# ===========================================================================
class TestHomeTarjetaActual:
    def test_pildora_en_tarjeta_grande_y_en_fila_actual_sin_el_bloque(
        self, db_session, seed_phase_defs, make_student, make_cohort, make_process,
        make_library_clearance, client_as,
    ):
        seed_phase_defs()
        cohort = make_cohort()
        _require_library(db_session, cohort)
        student = make_student()
        process = make_process(student, cohort=cohort, current_phase=2, library_clearance=None)
        make_library_clearance(process, status="awaiting_payment",
                               debt_amount=Decimal("500.00"), donation_amount=Decimal("0.00"),
                               total_amount=Decimal("500.00"))

        doc = _doc(client_as(student).get(DASHBOARD))

        assert "Por pagar en Caja" in _text(_hero(doc)), "falta en la tarjeta grande"
        assert "Por pagar en Caja" in _text(_phase_item(doc, 2)), "falta en la fila actual"
        # La tarjeta grande solo ensena la pildora -- el desglose vive en el
        # panel desplegable (y en Mi cita), igual que la encuesta.
        assert "sin cita, con tu número de control" not in _text(_hero(doc))


# ===========================================================================
# Mi cita — la fila del checklist con `auto_source = 'library_clearance'`:
# la MISMA píldora, sin desglose (§4.10: "la fila del requisito con la misma
# píldora")
# ===========================================================================
class TestMiCitaChecklist:

    @pytest.mark.parametrize("status,pill", [
        ("missing", "En Biblioteca"),
        ("pending", "En Biblioteca"),
        ("awaiting_payment", "Por pagar en Caja"),
        ("cleared", "Liberado"),
    ])
    def test_la_fila_muestra_la_misma_pildora(
        self, db_session, seed_phase_defs, make_student, make_process,
        make_library_clearance, client_as, status, pill,
    ):
        seed_phase_defs()
        student = make_student()
        process = make_process(student, current_phase=2,
                               library_clearance=(None if status == "missing" else status))

        doc = _doc(client_as(student).get(CITA))
        fila = _library_row(doc)

        assert pill in _text(fila)

    def test_cleared_prior_muestra_constancia_previa(
        self, db_session, seed_phase_defs, make_student, make_process,
        make_library_clearance, client_as,
    ):
        seed_phase_defs()
        student = make_student()
        process = make_process(student, current_phase=2, library_clearance=None)
        make_library_clearance(process, status="cleared", cleared_via="prior",
                               prior_issued_on=date.today())

        doc = _doc(client_as(student).get(CITA))
        fila = _library_row(doc)

        assert "Constancia previa" in _text(fila)

    def test_mi_cita_no_repite_el_desglose_ni_la_nota(
        self, db_session, seed_phase_defs, make_student, make_process,
        make_library_clearance, client_as,
    ):
        """§4.10: "Mi cita" trae la MISMA píldora, no el bloque completo del
        dashboard -- sin desglose ni nota de Biblioteca en esta fila."""
        seed_phase_defs()
        student = make_student()
        process = make_process(student, current_phase=2, library_clearance=None)
        make_library_clearance(process, status="awaiting_payment",
                               debt_amount=Decimal("800.00"), donation_amount=Decimal("200.00"),
                               total_amount=Decimal("1000.00"),
                               library_note="Nota exclusiva del dashboard.")

        doc = _doc(client_as(student).get(CITA))
        fila = _text(_library_row(doc))

        assert "Nota exclusiva del dashboard." not in fila
        assert "sin cita, con tu número de control" not in fila


# ===========================================================================
# Ruling R12 — con cita vigente, el panel NO promete agendar
# ===========================================================================
class TestR12CitaVigenteNoPrometeAgendar:

    @pytest.fixture()
    def escenario(self, db_session, seed_phase_defs, make_student, make_cohort,
                  make_process, make_survey_review):
        """Convocatoria con el no adeudo exigido, encuesta YA liberada (para
        que el ÚNICO bloqueo de `ClearanceGate` sea el de biblioteca -- el
        orden de `blockers()` reporta la encuesta primero) y proceso en la
        fase de cotejo (2), activo, fase 2 SIN dictaminar."""
        seed_phase_defs()
        cohort = make_cohort()
        _require_library(db_session, cohort)
        student = make_student()
        process = make_process(student, cohort=cohort, current_phase=2,
                               library_clearance=None)
        make_survey_review(process, status="approved")
        return {"student": student, "process": process, "cohort": cohort}

    def test_con_cita_vigente_y_biblioteca_en_revision_no_promete_agendar(
        self, db_session, escenario, make_library_clearance, make_appointment, client_as,
    ):
        make_library_clearance(escenario["process"], status="pending")
        make_appointment(escenario["process"], status="scheduled")

        resp = client_as(escenario["student"]).get(CITA)

        assert resp.status_code == 200, resp.text[:400]
        assert _PROMETE_AGENDAR not in resp.text
        assert "Servicios Escolares pueda liberar tu cotejo" in resp.text

    def test_con_cita_vigente_y_pago_pendiente_tampoco_promete_agendar(
        self, db_session, escenario, make_library_clearance, make_appointment, client_as,
    ):
        make_library_clearance(escenario["process"], status="awaiting_payment",
                               debt_amount=Decimal("300.00"), donation_amount=Decimal("0.00"),
                               total_amount=Decimal("300.00"))
        make_appointment(escenario["process"], status="scheduled")

        resp = client_as(escenario["student"]).get(CITA)

        assert resp.status_code == 200, resp.text[:400]
        assert _PROMETE_AGENDAR not in resp.text
        assert "Servicios Escolares pueda liberar tu cotejo" in resp.text

    def test_con_cita_attended_tambien_aplica(
        self, db_session, escenario, make_library_clearance, make_appointment, client_as,
    ):
        """`current` incluye `attended` -- D17/R12 no se limita a
        scheduled/confirmed: una cita ya REALIZADA tampoco se iba a "re-agendar"."""
        make_library_clearance(escenario["process"], status="pending")
        make_appointment(escenario["process"], status="attended")

        resp = client_as(escenario["student"]).get(CITA)

        assert resp.status_code == 200, resp.text[:400]
        assert _PROMETE_AGENDAR not in resp.text

    def test_sin_cita_vigente_si_promete_agendar_normalmente(
        self, db_session, escenario, make_library_clearance, client_as,
    ):
        """Control: SIN cita vigente, el texto normal de `SelfBookingService.
        MENSAJES` sigue intacto -- el fix de R12 no toca ese camino."""
        make_library_clearance(escenario["process"], status="pending")

        resp = client_as(escenario["student"]).get(CITA)

        assert resp.status_code == 200, resp.text[:400]
        assert _PROMETE_AGENDAR in resp.text

    def test_con_cita_vigente_y_todo_liberado_no_cambia_nada(
        self, db_session, escenario, make_library_clearance, make_appointment, client_as,
    ):
        """Control: con cita vigente pero SIN bloqueo de biblioteca (no adeudo
        ya liberado) el motivo real es `tiene_cita`, que ya no pinta `message`
        -- el override de R12 no se dispara fuera de los dos motivos de
        biblioteca."""
        make_library_clearance(escenario["process"], status="cleared", cleared_via="payment")
        make_appointment(escenario["process"], status="scheduled")

        resp = client_as(escenario["student"]).get(CITA)

        assert resp.status_code == 200, resp.text[:400]
        assert _PROMETE_AGENDAR not in resp.text
        assert "Servicios Escolares pueda liberar tu cotejo" not in resp.text


# ===========================================================================
# Forma del contexto: dict plano, mismo invariante que el resto de la app
# ===========================================================================
class TestFormaDelContexto:
    def test_phases_ctx_cuelga_library_solo_en_review_appointment(
        self, db_session, seed_phase_defs, make_student, make_cohort, make_process,
    ):
        from itcj2.apps.titulatec.pages.student import _phases_ctx

        seed_phase_defs()
        cohort = make_cohort()
        _require_library(db_session, cohort)
        process = make_process(make_student(), cohort=cohort, current_phase=0,
                               library_clearance="pending")

        ctx = _phases_ctx(db_session, process)

        for card in ctx["phases"]:
            if card["code"] == "review_appointment":
                assert card["library"] is not None
                assert card["library"]["status"] == "pending"
                assert card["library"]["total_fmt"] == ""
                assert card["library"]["breakdown"] == ""
            else:
                assert card["library"] is None, (
                    f"la fase {card['number']} no deberia traer 'library'")

    def test_el_ctx_no_lleva_objetos_orm(
        self, db_session, seed_phase_defs, make_student, make_cohort, make_process,
        make_library_clearance,
    ):
        """Mismo invariante que `test_cita_checklist.py`: la plantilla se
        pinta DESPUES del `db.close()` de la ruta."""
        from itcj2.apps.titulatec.pages.student import _phases_ctx

        seed_phase_defs()
        cohort = make_cohort()
        _require_library(db_session, cohort)
        process = make_process(make_student(), cohort=cohort, current_phase=0,
                               library_clearance=None)
        make_library_clearance(process, status="awaiting_payment",
                               debt_amount=Decimal("100.00"), donation_amount=Decimal("0.00"),
                               total_amount=Decimal("100.00"))

        ctx = _phases_ctx(db_session, process)
        card = next(c for c in ctx["phases"] if c["code"] == "review_appointment")

        for valor in card["library"].values():
            assert not hasattr(valor, "_sa_instance_state"), (
                f"'library' trae un objeto ORM: {valor!r}")


# ===========================================================================
# El `needs` de la fase de cotejo (spec §4.3): ya no pide el no adeudo a mano
# ===========================================================================
class TestNeedsDeLaFaseDeCotejo:
    def test_el_needs_ya_no_dice_lleva_tu_no_adeudo_y_dice_el_texto_nuevo(
        self, db_session, seed_phase_defs, make_student, make_process, client_as,
    ):
        seed_phase_defs()
        student = make_student()
        make_process(student, current_phase=0)

        doc = _doc(client_as(student).get(DASHBOARD))
        fila = _text(_phase_item(doc, 2))

        assert "No-adeudo de biblioteca y comprobante de la encuesta" not in fila
        assert ("Las constancias de no adeudo y de la encuesta las envían las "
                "áreas a Servicios Escolares") in fila
        assert "si registraste una constancia previa, llévala" in fila
