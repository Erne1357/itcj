"""Tests de `PriorClearanceService` y de `SurveyReviewService.register_prior`:
constancias previas (D9, spec `2026-10-01-titulatec-biblioteca-caja-design.md`
§4.12). Un egresado que YA traía, de ANTES de este sistema, su liberación de
encuesta o su no adeudo de biblioteca -otro semestre, en papel, en el sistema
legado-.

Dos caminos, un mismo servicio:

* `SurveyReviewService.register_prior` -- único escritor de `SurveyReview`
  (§5 invariante 1), gemelo de `LibraryClearanceService.register_prior`
  (Tarea 4): crea DIRECTO una solicitud `approved`/`origin='prior'`, sin
  encuesta real detrás (`response_id=None`), sin commit (lo da el llamador) y
  SIN emitir la constancia `survey_release` (el egresado trae su papel).
* `PriorClearanceService` -- decide, por número de control, si una fila
  `PriorClearance` se aplica YA (hay proceso abierto) o se DIFIERE (upsert,
  sin proceso todavía); `apply_pending` la llama `ImportService.import_rows`
  justo después de `LibraryClearanceService.open_for_process` al dar de alta
  un proceso nuevo. `import_rows` es el motor de la CLI `titulatec
  import-prior-clearances`: clasifica cada fila del CSV en una de las 6 llaves
  de `IMPORT_BUCKETS` sin escribir nada en `dry_run=True`.

Vigencia (D9, Review Focus #7): `issued_on` obligatoria, no futura y
`>= hoy - PRIOR_VALIDITY_DAYS` (365 días; exactamente 365 vale, 366 vencida) --
el MISMO límite de `LibraryClearanceService.PRIOR_VALIDITY_DAYS`, reusado de
allá.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest

import itcj2.models  # noqa: F401

NOTIFY = "itcj2.apps.titulatec.services.notify.notify_student"
HOY_FIJO = datetime(2026, 10, 1, 10, 0, 0)

_MODULOS_RELOJ = (
    "itcj2.apps.titulatec.services.library_clearance_service",
    "itcj2.apps.titulatec.services.survey_review_service",
    "itcj2.apps.titulatec.services.prior_clearance_service",
)


# ---------------------------------------------------------------------------
# Ayudantes
# ---------------------------------------------------------------------------
def _events(db, process_id, tipo):
    from itcj2.apps.titulatec.models import ProcessEvent
    return (db.query(ProcessEvent)
            .filter_by(process_id=process_id, event_type=tipo)
            .order_by(ProcessEvent.id).all())


def _fulfillment(db, process_id, requirement_id):
    from itcj2.apps.titulatec.models import RequirementFulfillment
    return (db.query(RequirementFulfillment)
            .filter_by(process_id=process_id, requirement_id=requirement_id).first())


def _graduate_req(db, cohort_id):
    from itcj2.apps.titulatec.models import CotejoRequirement
    return (db.query(CotejoRequirement)
            .filter_by(cohort_id=cohort_id, auto_source="graduate_survey").first())


def _library_req(db, cohort_id):
    from itcj2.apps.titulatec.models import CotejoRequirement
    return (db.query(CotejoRequirement)
            .filter_by(cohort_id=cohort_id, auto_source="library_clearance").first())


def _prior(db, *, kind, control, issued_on, note=None, source="test.csv",
          applied_process=None):
    from itcj2.apps.titulatec.models import PriorClearance
    from itcj2.core.utils.timezone import db_now

    row = PriorClearance(
        kind=kind, control_number=control, issued_on=issued_on, note=note,
        source=source,
        applied_process_id=getattr(applied_process, "id", applied_process),
        applied_at=(db_now() if applied_process is not None else None),
    )
    db.add(row)
    db.flush()
    return row


def _certs(db, source_ref):
    from itcj2.apps.titulatec.models import Certificate
    return db.query(Certificate).filter_by(source_ref=source_ref).all()


@pytest.fixture()
def reloj(monkeypatch):
    """`db_now()` fijo en HOY_FIJO en los TRES módulos que lo usan para las
    reglas de vigencia D9: el servicio dueño de cada transición y el
    orquestador (`prior_clearance_service`, para `today=None`)."""
    for modulo in _MODULOS_RELOJ:
        monkeypatch.setattr(f"{modulo}.db_now", lambda: HOY_FIJO)
    return HOY_FIJO.date()


@pytest.fixture()
def proceso(db_session, make_student, make_process, make_cohort):
    """Fábrica: convocatoria + egresado + proceso en fase 1, SIN fila de
    biblioteca por omisión (las pruebas de encuesta no la necesitan)."""
    def _make(*, control_number=None, process_status="active", current_phase=1,
              library_clearance=None, cohort=None):
        cohort = cohort or make_cohort()
        student = make_student(control_number=control_number)
        return make_process(student, cohort=cohort, current_phase=current_phase,
                            status=process_status, library_clearance=library_clearance)
    return _make


def _svc():
    from itcj2.apps.titulatec.services.prior_clearance_service import PriorClearanceService
    return PriorClearanceService


def _review_svc():
    from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService
    return SurveyReviewService


def _library_svc():
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService
    return LibraryClearanceService


# ---------------------------------------------------------------------------
# SurveyReviewService.register_prior
# ---------------------------------------------------------------------------
class TestSurveyRegisterPrior:
    def test_crea_la_solicitud_aprobada_sin_respuesta_detras(
            self, db_session, proceso, reloj):
        proc = proceso()

        with patch(NOTIFY) as aviso:
            review = _review_svc().register_prior(
                db_session, proc, issued_on=reloj - timedelta(days=10),
                note="  Trae su papel  ")

        assert review.process_id == proc.id
        assert review.response_id is None
        assert review.status == "approved"
        assert review.origin == "prior"
        assert review.prior_issued_on == reloj - timedelta(days=10)
        assert aviso.called

    def test_no_hace_commit_el_llamador_es_dueno(self, db_session, proceso, reloj,
                                                 monkeypatch):
        proc = proceso()
        monkeypatch.setattr(db_session, "commit",
                            lambda: pytest.fail("register_prior no debe commitear"))

        with patch(NOTIFY):
            review = _review_svc().register_prior(
                db_session, proc, issued_on=reloj, note=None)

        assert review.id is not None    # sí hizo flush

    def test_acredita_graduate_survey_con_external_ref_survey_prior(
            self, db_session, proceso, reloj):
        proc = proceso()

        with patch(NOTIFY):
            review = _review_svc().register_prior(
                db_session, proc, issued_on=reloj, note=None)

        requisito = _graduate_req(db_session, proc.cohort_id)
        assert requisito is not None
        cumplido = _fulfillment(db_session, proc.id, requisito.id)
        assert cumplido is not None
        assert cumplido.external_ref == f"survey_prior:{review.id}"

    def test_no_emite_constancia_de_encuesta(self, db_session, proceso, reloj):
        proc = proceso()

        with patch(NOTIFY):
            review = _review_svc().register_prior(
                db_session, proc, issued_on=reloj, note=None)

        assert _certs(db_session, f"survey_review:{review.id}") == []

    def test_escribe_el_evento_survey_review_prior(self, db_session, proceso, reloj):
        proc = proceso()

        with patch(NOTIFY):
            review = _review_svc().register_prior(
                db_session, proc, issued_on=reloj - timedelta(days=5),
                note="Nota de SE")

        evs = _events(db_session, proc.id, "survey_review_prior")
        assert len(evs) == 1
        assert evs[0].payload["review_id"] == review.id
        assert evs[0].payload["note"] == "Nota de SE"

    def test_llama_a_studentmail_survey_result_con_origin_prior(
            self, db_session, proceso, reloj):
        proc = proceso()

        with patch(NOTIFY), \
             patch("itcj2.apps.titulatec.services.student_mail.StudentMail.survey_result"
                   ) as correo:
            _review_svc().register_prior(db_session, proc, issued_on=reloj, note=None)

        correo.assert_called_once()
        assert correo.call_args.kwargs["result"] == "approved"
        assert correo.call_args.kwargs["origin"] == "prior"

    @pytest.mark.parametrize("dias, valida", [
        (0, True),
        (365, True),            # D9: exactamente 365 días vale
        (366, False),            # 366: vencida
        (-1, False),              # futura
    ])
    def test_vigencia(self, db_session, proceso, reloj, dias, valida):
        proc = proceso()
        fecha = reloj - timedelta(days=dias)
        if valida:
            with patch(NOTIFY):
                review = _review_svc().register_prior(
                    db_session, proc, issued_on=fecha, note=None)
            assert review.prior_issued_on == fecha
            return
        with pytest.raises(ValueError) as exc:
            _review_svc().register_prior(db_session, proc, issued_on=fecha, note=None)
        if dias > 0:
            assert "vencida" in str(exc.value) or "venció" in str(exc.value)
        else:
            assert "futura" in str(exc.value)
        assert _review_svc().get_for_process(db_session, proc.id) is None

    def test_sin_fecha(self, db_session, proceso, reloj):
        proc = proceso()
        with pytest.raises(ValueError):
            _review_svc().register_prior(db_session, proc, issued_on=None, note=None)
        assert _review_svc().get_for_process(db_session, proc.id) is None

    def test_proceso_con_solicitud_existente_no_duplica(
            self, db_session, proceso, make_survey_review, reloj):
        proc = proceso()
        make_survey_review(proc, status="in_review")

        with pytest.raises(ValueError) as exc:
            _review_svc().register_prior(db_session, proc, issued_on=reloj, note=None)
        assert "ya existe" in str(exc.value).lower()

    @pytest.mark.parametrize("estado", ["cancelled", "completed"])
    def test_proceso_no_admitido(self, db_session, proceso, reloj, estado):
        proc = proceso(process_status=estado)
        with pytest.raises(ValueError):
            _review_svc().register_prior(db_session, proc, issued_on=reloj, note=None)
        assert _review_svc().get_for_process(db_session, proc.id) is None

    def test_proceso_en_pausa_si_admite(self, db_session, proceso, reloj):
        proc = proceso(process_status="on_hold")
        with patch(NOTIFY):
            review = _review_svc().register_prior(
                db_session, proc, issued_on=reloj, note=None)
        assert review.status == "approved"


# ---------------------------------------------------------------------------
# PriorClearanceService.apply_pending
# ---------------------------------------------------------------------------
class TestApplyPending:
    def test_aplica_la_de_encuesta_pendiente(self, db_session, proceso, reloj):
        proc = proceso(control_number="99600001")
        _prior(db_session, kind="survey", control="99600001",
              issued_on=reloj - timedelta(days=20))

        with patch(NOTIFY):
            aplicadas = _svc().apply_pending(db_session, proc, "99600001")

        assert aplicadas == ["survey"]
        review = _review_svc().get_for_process(db_session, proc.id)
        assert review is not None
        assert review.origin == "prior"

    def test_aplica_la_de_biblioteca_pendiente(self, db_session, proceso, reloj):
        proc = proceso(control_number="99600002", library_clearance="pending")
        _prior(db_session, kind="library", control="99600002",
              issued_on=reloj - timedelta(days=5))

        with patch(NOTIFY):
            aplicadas = _svc().apply_pending(db_session, proc, "99600002")

        assert aplicadas == ["library"]
        clearance = _library_svc().get_for_process(db_session, proc.id)
        assert clearance.status == "cleared"
        assert clearance.cleared_via == "prior"

    def test_aplica_las_dos_a_la_vez(self, db_session, proceso, reloj):
        proc = proceso(control_number="99600003", library_clearance="pending")
        _prior(db_session, kind="survey", control="99600003", issued_on=reloj)
        _prior(db_session, kind="library", control="99600003", issued_on=reloj)

        with patch(NOTIFY):
            aplicadas = _svc().apply_pending(db_session, proc, "99600003")

        assert set(aplicadas) == {"survey", "library"}

    def test_marca_applied_process_id_y_applied_at(self, db_session, proceso, reloj):
        from itcj2.apps.titulatec.models import PriorClearance

        proc = proceso(control_number="99600004")
        previa = _prior(db_session, kind="survey", control="99600004", issued_on=reloj)

        with patch(NOTIFY):
            _svc().apply_pending(db_session, proc, "99600004")

        db_session.refresh(previa)
        assert previa.applied_process_id == proc.id
        assert previa.applied_at is not None

    def test_sin_constancias_pendientes_no_hace_nada(self, db_session, proceso):
        proc = proceso(control_number="99600005")
        assert _svc().apply_pending(db_session, proc, "99600005") == []

    def test_no_reaplica_una_ya_aplicada(self, db_session, make_student, make_process,
                                         make_cohort, reloj):
        """Una `PriorClearance` ya consumida por OTRO proceso no se vuelve a
        tocar (invariante: `applied_process_id` se fija una sola vez). MISMO
        alumno, DOS procesos (otra convocatoria) -- `control_number` es
        UNIQUE en `core_users`, así que el segundo proceso cuelga del mismo
        estudiante, no de uno nuevo con el mismo control."""
        student = make_student(control_number="99600006")
        proc_viejo = make_process(student, cohort=make_cohort(), library_clearance=None)
        _prior(db_session, kind="survey", control="99600006", issued_on=reloj)

        with patch(NOTIFY):
            primera = _svc().apply_pending(db_session, proc_viejo, "99600006")
        assert primera == ["survey"]

        proc_nuevo = make_process(student, cohort=make_cohort(), library_clearance=None)
        with patch(NOTIFY):
            aplicadas = _svc().apply_pending(db_session, proc_nuevo, "99600006")

        assert aplicadas == []
        assert _review_svc().get_for_process(db_session, proc_nuevo.id) is None

    def test_sin_control_number_no_hace_nada(self, db_session, proceso):
        proc = proceso()
        assert _svc().apply_pending(db_session, proc, "") == []
        assert _svc().apply_pending(db_session, proc, None) == []


# ---------------------------------------------------------------------------
# PriorClearanceService.import_rows (motor de la CLI)
# ---------------------------------------------------------------------------
class TestImportRowsSurvey:
    def test_aplicada_con_proceso_abierto(self, db_session, proceso, reloj):
        proc = proceso(control_number="99700001")

        with patch(NOTIFY):
            resultado = _svc().import_rows(
                db_session, kind="survey", source="t.csv",
                rows=[{"control_number": "99700001",
                      "issued_on": (reloj - timedelta(days=1)).isoformat()}])

        assert [f["control_number"] for f in resultado["applied"]] == ["99700001"]
        assert resultado["deferred"] == resultado["already"] == resultado["conflicts"] == []
        assert resultado["expired"] == resultado["invalid"] == []
        review = _review_svc().get_for_process(db_session, proc.id)
        assert review is not None and review.origin == "prior"

    def test_diferida_sin_proceso_y_aplicada_al_importar_el_proceso(
            self, db_session, make_cohort, reloj):
        """El caso completo de D9: sin proceso todavía -> se difiere; al dar
        de alta el proceso via `ImportService.import_rows`, el gancho de la
        Tarea 6 (`apply_pending`, después del de la Tarea 4) la aplica sola."""
        cohort = make_cohort()

        with patch(NOTIFY):
            resultado = _svc().import_rows(
                db_session, kind="survey", source="t.csv",
                rows=[{"control_number": "99700099", "issued_on": reloj.isoformat()}])
        assert [f["control_number"] for f in resultado["deferred"]] == ["99700099"]
        db_session.commit()

        from itcj2.apps.titulatec.services.import_service import ImportService
        with patch(NOTIFY):
            ImportService.import_rows(
                db_session, cohort,
                rows=[{"control_number": "99700099", "full_name": "ALUMNO DIFERIDO",
                      "email": None, "program_id": None, "modality_id": None}],
                source="csv", commit=False)

        from itcj2.apps.titulatec.models import TitulationProcess
        from itcj2.core.models.user import User
        user = db_session.query(User).filter_by(control_number="99700099").first()
        proc = (db_session.query(TitulationProcess)
               .filter_by(student_id=user.id, cohort_id=cohort.id).first())
        review = _review_svc().get_for_process(db_session, proc.id)
        assert review is not None
        assert review.origin == "prior"

    def test_ya_liberada(self, db_session, proceso, make_survey_review, reloj):
        proc = proceso(control_number="99700002")
        make_survey_review(proc, status="approved")

        resultado = _svc().import_rows(
            db_session, kind="survey", source="t.csv",
            rows=[{"control_number": "99700002", "issued_on": reloj.isoformat()}])

        assert [f["control_number"] for f in resultado["already"]] == ["99700002"]
        assert resultado["applied"] == []

    @pytest.mark.parametrize("estado", ["in_review", "rejected"])
    def test_conflicto_con_solicitud_del_semestre(
            self, db_session, proceso, make_survey_review, reloj, estado):
        proc = proceso(control_number="99700003")
        make_survey_review(proc, status=estado)

        resultado = _svc().import_rows(
            db_session, kind="survey", source="t.csv",
            rows=[{"control_number": "99700003", "issued_on": reloj.isoformat()}])

        assert [f["control_number"] for f in resultado["conflicts"]] == ["99700003"]
        review = _review_svc().get_for_process(db_session, proc.id)
        assert review.status == estado          # intacta: la CLI no decide por GTV

    def test_vencida(self, db_session, proceso, reloj):
        proc = proceso(control_number="99700004")

        resultado = _svc().import_rows(
            db_session, kind="survey", source="t.csv",
            rows=[{"control_number": "99700004",
                  "issued_on": (reloj - timedelta(days=366)).isoformat()}])

        assert [f["control_number"] for f in resultado["expired"]] == ["99700004"]
        assert _review_svc().get_for_process(db_session, proc.id) is None

    @pytest.mark.parametrize("control, fecha", [
        ("123", "2026-01-01"),            # control inválido
        ("99700005", None),               # sin fecha
        ("99700005", "no-es-fecha"),      # fecha no parseable
        ("99700005", "2099-01-01"),       # fecha futura
    ])
    def test_invalida(self, db_session, reloj, control, fecha):
        resultado = _svc().import_rows(
            db_session, kind="survey", source="t.csv",
            rows=[{"control_number": control, "issued_on": fecha}])

        assert len(resultado["invalid"]) == 1
        assert resultado["applied"] == resultado["deferred"] == []

    def test_dry_run_no_escribe_nada(self, db_session, proceso, reloj):
        from itcj2.apps.titulatec.models import PriorClearance

        proc = proceso(control_number="99700006")
        antes = db_session.query(PriorClearance).count()

        resultado = _svc().import_rows(
            db_session, kind="survey", source="t.csv", dry_run=True,
            rows=[{"control_number": "99700006", "issued_on": reloj.isoformat()},
                 {"control_number": "99700007", "issued_on": reloj.isoformat()}])

        assert [f["control_number"] for f in resultado["applied"]] == ["99700006"]
        assert [f["control_number"] for f in resultado["deferred"]] == ["99700007"]
        assert not db_session.new and not db_session.dirty and not db_session.deleted
        assert db_session.query(PriorClearance).count() == antes
        assert _review_svc().get_for_process(db_session, proc.id) is None


class TestImportRowsLibrary:
    def test_aplicada_con_proceso_abierto(self, db_session, proceso, reloj):
        proc = proceso(control_number="99700010", library_clearance="pending")

        resultado = _svc().import_rows(
            db_session, kind="library", source="t.csv",
            rows=[{"control_number": "99700010", "issued_on": reloj.isoformat()}])

        assert [f["control_number"] for f in resultado["applied"]] == ["99700010"]
        clearance = _library_svc().get_for_process(db_session, proc.id)
        assert clearance.status == "cleared" and clearance.cleared_via == "prior"

    def test_ya_liberada(self, db_session, proceso, reloj):
        proceso(control_number="99700011", library_clearance="cleared")

        resultado = _svc().import_rows(
            db_session, kind="library", source="t.csv",
            rows=[{"control_number": "99700011", "issued_on": reloj.isoformat()}])

        assert [f["control_number"] for f in resultado["already"]] == ["99700011"]

    def test_diferida_sin_proceso(self, db_session, reloj):
        resultado = _svc().import_rows(
            db_session, kind="library", source="t.csv",
            rows=[{"control_number": "99700012", "issued_on": reloj.isoformat()}])

        assert [f["control_number"] for f in resultado["deferred"]] == ["99700012"]
        from itcj2.apps.titulatec.models import PriorClearance
        fila = (db_session.query(PriorClearance)
               .filter_by(kind="library", control_number="99700012").first())
        assert fila is not None and fila.applied_process_id is None

    def test_dry_run_con_proceso_abierto_no_crea_la_fila_de_biblioteca(
            self, db_session, proceso, reloj):
        """`open_for_process` INSERTA si falta: en dry-run no se debe llamar."""
        from itcj2.apps.titulatec.models import LibraryClearance

        proc = proceso(control_number="99700013", library_clearance=None)
        assert _library_svc().get_for_process(db_session, proc.id) is None

        resultado = _svc().import_rows(
            db_session, kind="library", source="t.csv", dry_run=True,
            rows=[{"control_number": "99700013", "issued_on": reloj.isoformat()}])

        assert [f["control_number"] for f in resultado["applied"]] == ["99700013"]
        assert db_session.query(LibraryClearance).filter_by(process_id=proc.id).first() is None


class TestImportRowsGeneral:
    def test_tipo_desconocido(self, db_session):
        with pytest.raises(ValueError):
            _svc().import_rows(db_session, kind="otro", source="t.csv", rows=[])

    def test_today_inyectable(self, db_session, proceso):
        """`today` se puede fijar sin parchear `db_now` (clasificación), aun
        con un proceso abierto esperando -la fecha vencida se clasifica
        ANTES de buscar el proceso."""
        proceso(control_number="99700020")
        hoy = date(2027, 1, 1)

        resultado = _svc().import_rows(
            db_session, kind="survey", source="t.csv", today=hoy,
            rows=[{"control_number": "99700020",
                  "issued_on": (hoy - timedelta(days=366)).isoformat()}])

        assert [f["control_number"] for f in resultado["expired"]] == ["99700020"]
        assert resultado["applied"] == []
