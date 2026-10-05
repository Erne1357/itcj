"""Tests de `FolioBackfillService` y del comando `titulatec emitir-folios-previos`
(Tarea 3 del plan de folios; spec `2026-10-05-titulatec-folios-design.md` §3.4,
D5/D6, invariante 3).

Qué cubren:

* `candidates(db)`: las liberaciones VIGENTES sin folio vigente, de un proceso
  no `cancelled` -`SurveyReview` `approved` con `origin='prior'` (ancla
  `reviewed_at`) y `LibraryClearance` `cleared` con `cleared_via` `prior` o
  `legacy` (ancla `updated_at`)-; el semestre es el ANTERIOR al del ancla; el
  orden es `(ancla, tipo, id)`.
* `run(db, dry_run=)`: el conteo por `(tipo, semestre)`; en corrida real emite
  con `actor_id=None` y UN commit; en dry-run no escribe; idempotente.
* La CLI (`emitir-folios-previos`) y el paso nuevo de `activar-biblioteca-caja`
  se prueban en las dos últimas secciones.

La BD de dev es COMPARTIDA y trae datos reales (las previas importadas de
Forms, sin folio todavía): `candidates`/`run` las ven también. Por eso NADA de
aquí afirma conteos globales ni números absolutos: toda aserción filtra por las
filas que la prueba sembró (por `process_id`/`source_ref`) y los anclas caen en
años SINTÉTICOS (2090+), cuyos contadores no existen en la base real (el
renglón del contador muere con el rollback de `db_session`).
"""
from __future__ import annotations

import re
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from sqlalchemy import text

import itcj2.apps.titulatec.services.folio_backfill_service as fb_mod
from itcj2.apps.titulatec.models import (
    Certificate, LibraryClearance, SurveyReview, TitulationProcess,
)
from itcj2.apps.titulatec.services.certificate_service import CertificateService
from itcj2.apps.titulatec.services.folio_backfill_service import FolioBackfillService
from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService
from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService
from itcj2.cli.titulatec import (
    _emitir_folios_previos,
    emitir_folios_previos_command,
)

# Octubre de un año sintético: semestre `B` -> el folio cae en `2093A`.
OCT_2093 = datetime(2093, 10, 5, 9, 30, 0)

_SURVEY, _LIBRARY = "survey_release", "library_clearance"


# ---------------------------------------------------------------------------
# Siembra: filas como las dejaban el código y el SQL de ANTES de la Tarea 2
# (liberadas, previas o legado, y SIN constancia).
# ---------------------------------------------------------------------------
@pytest.fixture()
def sembrar(db_session, make_student, make_process):
    """Fábricas que insertan A MANO la fila liberada, sin pasar por los
    dueños (así quedan las previas registradas antes de la Tarea 2 y el
    legado del SQL de `tt20261001a`/la promoción D17): sin folio."""

    def _proceso(status="active"):
        return make_process(make_student(), status=status, library_clearance=None)

    def encuesta(*, anchor=OCT_2093, status="approved", origin="prior",
                 proceso="active"):
        proc = _proceso(proceso)
        fila = SurveyReview(
            process_id=proc.id, response_id=None, status=status, origin=origin,
            reviewed_at=anchor, submitted_at=anchor or OCT_2093,
            updated_at=anchor or OCT_2093,
        )
        db_session.add(fila)
        db_session.flush()
        return SimpleNamespace(
            proc=proc, fila=fila, kind=_SURVEY,
            ref=SurveyReviewService.certificate_ref(fila.id))

    def biblioteca(*, via="prior", anchor=OCT_2093, status="cleared", proceso="active"):
        proc = _proceso(proceso)
        fila = LibraryClearance(
            process_id=proc.id, status=status,
            cleared_via=via if status == "cleared" else None,
            updated_at=anchor,
        )
        db_session.add(fila)
        db_session.flush()
        return SimpleNamespace(
            proc=proc, fila=fila, kind=_LIBRARY,
            ref=LibraryClearanceService.certificate_ref(fila.id))

    return SimpleNamespace(encuesta=encuesta, biblioteca=biblioteca)


def _candidatos_de(db_session, *sembradas):
    """Los candidatos de `candidates()` que son de ESTAS filas, en el orden en
    que los devuelve (el resto -datos reales de la BD de dev- se ignora)."""
    refs = {s.ref for s in sembradas}
    return [c for c in FolioBackfillService.candidates(db_session)
            if c["source_ref"] in refs]


def _certs(db_session, *sembradas):
    return (db_session.query(Certificate)
            .filter(Certificate.source_ref.in_([s.ref for s in sembradas]))
            .order_by(Certificate.id).all())


def _emitir(db_session, s, *, semestre="2092B"):
    """Folio VIGENTE de `s`, emitido por el motor como lo haría un dueño."""
    proc = db_session.get(TitulationProcess, s.proc.id)
    return CertificateService.issue(
        db_session, kind=s.kind, process=proc, source_ref=s.ref,
        actor_id=None, semester=semestre)


def _solo_de(conteo, semestres):
    """El conteo sin las filas de los semestres REALES de la base de dev."""
    return {k: v for k, v in conteo.items() if k[1] in semestres}


# ---------------------------------------------------------------------------
# candidates()
# ---------------------------------------------------------------------------
class TestCandidates:
    def test_previas_y_legado_vigentes_sin_folio_son_candidatos(
            self, db_session, sembrar):
        gtv = sembrar.encuesta()
        previa = sembrar.biblioteca(via="prior")
        legado = sembrar.biblioteca(via="legacy")

        candidatos = _candidatos_de(db_session, gtv, previa, legado)

        assert {c["source_ref"] for c in candidatos} == {gtv.ref, previa.ref, legado.ref}
        por_ref = {c["source_ref"]: c for c in candidatos}
        assert por_ref[gtv.ref]["kind"] == _SURVEY
        assert por_ref[previa.ref]["kind"] == _LIBRARY
        assert por_ref[legado.ref]["kind"] == _LIBRARY
        for s in (gtv, previa, legado):
            c = por_ref[s.ref]
            assert set(c) == {"kind", "source_ref", "process_id", "anchor", "semester"}
            assert c["process_id"] == s.proc.id
            assert c["anchor"] == OCT_2093
            assert c["semester"] == "2093A"        # B de 2093 -> A de 2093

    def test_un_proceso_cancelado_no_es_candidato(self, db_session, sembrar):
        activo = sembrar.encuesta()
        cancelado_g = sembrar.encuesta(proceso="cancelled")
        cancelado_b = sembrar.biblioteca(via="prior", proceso="cancelled")
        cancelado_l = sembrar.biblioteca(via="legacy", proceso="cancelled")

        candidatos = _candidatos_de(db_session, activo, cancelado_g, cancelado_b,
                                    cancelado_l)

        assert [c["source_ref"] for c in candidatos] == [activo.ref]

    def test_solo_cuentan_las_liberaciones_vigentes_y_previas(
            self, db_session, sembrar):
        """Una liberación NORMAL (`submission`, `payment`, `no_charge`) la
        emiten los dueños al liberar: nunca es candidata, aunque aquí se haya
        sembrado sin folio. Tampoco lo que no está liberado."""
        previa = sembrar.encuesta()                                    # sí
        normal = sembrar.encuesta(origin="submission")                  # no
        en_revision = sembrar.encuesta(status="in_review")              # no
        observada = sembrar.encuesta(status="rejected")                 # no
        legado = sembrar.biblioteca(via="legacy")                       # sí
        por_pago = sembrar.biblioteca(via="payment")                    # no
        sin_cargo = sembrar.biblioteca(via="no_charge")                 # no
        pendiente = sembrar.biblioteca(status="pending")                # no
        en_caja = sembrar.biblioteca(status="awaiting_payment")         # no
        observado = sembrar.biblioteca(status="observed")               # no

        candidatos = _candidatos_de(
            db_session, previa, normal, en_revision, observada, legado, por_pago,
            sin_cargo, pendiente, en_caja, observado)

        assert {c["source_ref"] for c in candidatos} == {previa.ref, legado.ref}

    def test_con_folio_vigente_no_es_candidato_y_con_uno_anulado_si(
            self, db_session, sembrar):
        con_folio = sembrar.encuesta()
        _emitir(db_session, con_folio)
        anulado = sembrar.biblioteca(via="prior")
        _emitir(db_session, anulado)
        CertificateService.void(db_session, source_ref=anulado.ref,
                                actor_id=None, reason="prueba")
        sin_folio = sembrar.biblioteca(via="legacy")

        candidatos = _candidatos_de(db_session, con_folio, anulado, sin_folio)

        # Un folio ANULADO no cuenta como vigente: la liberación sigue vigente
        # y necesita uno nuevo. El que ya tiene uno vigente no se toca.
        assert {c["source_ref"] for c in candidatos} == {anulado.ref, sin_folio.ref}

    @pytest.mark.parametrize("ancla, semestre", [
        (datetime(2093, 10, 5, 9, 0), "2093A"),     # octubre: B de Y -> A de Y
        (datetime(2093, 7, 1, 0, 0), "2093A"),      # primer día de B
        (datetime(2093, 12, 31, 23, 59), "2093A"),
        (datetime(2093, 2, 10, 9, 0), "2092B"),     # febrero: A de Y -> B de Y-1
        (datetime(2093, 6, 30, 23, 59), "2092B"),   # último día de A
        (datetime(2093, 1, 1, 0, 0), "2092B"),
    ])
    def test_el_semestre_sale_del_ancla(self, db_session, sembrar, ancla, semestre):
        gtv = sembrar.encuesta(anchor=ancla)
        bib = sembrar.biblioteca(via="legacy", anchor=ancla)

        candidatos = _candidatos_de(db_session, gtv, bib)

        assert {c["source_ref"]: c["semester"] for c in candidatos} == {
            gtv.ref: semestre, bib.ref: semestre}
        assert all(c["anchor"] == ancla for c in candidatos)

    def test_sin_ancla_se_usa_db_now(self, db_session, sembrar, monkeypatch):
        """`reviewed_at` es NULL en una solicitud sin dictamen fechado (la
        columna lo permite): el ancla cae a `db_now()`, una vez por consulta.
        (`library_clearances.updated_at` es NOT NULL: allí no puede faltar.)"""
        ahora = datetime(2095, 3, 2, 8, 0, 0)
        monkeypatch.setattr(fb_mod, "db_now", lambda: ahora)
        gtv = sembrar.encuesta(anchor=None)

        (c,) = _candidatos_de(db_session, gtv)

        assert c["anchor"] == ahora
        assert c["semester"] == "2094B"                 # marzo: A de 2095 -> B de 2094

    def test_el_orden_es_ancla_tipo_id(self, db_session, sembrar):
        t1, t2 = datetime(2093, 9, 1, 8, 0), datetime(2093, 9, 2, 8, 0)
        # Insertadas a propósito en un orden que NO es el esperado.
        bib_a = sembrar.biblioteca(via="legacy", anchor=t2)
        gtv_b = sembrar.encuesta(anchor=t2)
        bib_c = sembrar.biblioteca(via="prior", anchor=t2)
        gtv_d = sembrar.encuesta(anchor=t1)
        bib_e = sembrar.biblioteca(via="prior", anchor=t1)

        candidatos = _candidatos_de(db_session, bib_a, gtv_b, bib_c, gtv_d, bib_e)

        # t1 antes que t2; dentro del mismo ancla, `library_clearance` antes de
        # `survey_release`; dentro del mismo tipo, por id de la fila.
        assert [c["source_ref"] for c in candidatos] == [
            bib_e.ref, gtv_d.ref, bib_a.ref, bib_c.ref, gtv_b.ref]

    def test_candidates_solo_lee(self, db_session, sembrar):
        gtv = sembrar.encuesta()
        db_session.flush()

        FolioBackfillService.candidates(db_session)

        assert not db_session.new and not db_session.dirty and not db_session.deleted
        assert _certs(db_session, gtv) == []

    def test_los_prefijos_de_source_ref_son_los_de_los_duenos(self):
        """El `NOT EXISTS` arma el `source_ref` en SQL con estos prefijos; si un
        dueño cambia su formato, el backfill emitiría duplicados en silencio."""
        for kind, dueno in ((_SURVEY, SurveyReviewService),
                            (_LIBRARY, LibraryClearanceService)):
            prefijo = fb_mod._REF_PREFIX[kind]
            assert dueno.certificate_ref(7) == f"{prefijo}7"
            assert dueno.certificate_ref(12345) == f"{prefijo}12345"


# ---------------------------------------------------------------------------
# run()
# ---------------------------------------------------------------------------
class TestRun:
    def _cinco(self, sembrar):
        """Cuatro candidatas -dos de encuesta con el ancla invertida respecto al
        id, una previa y un legado de biblioteca- y una previa del proceso
        `cancelled`, que NO debe salir."""
        t1, t2 = datetime(2093, 9, 1, 8, 0), datetime(2093, 9, 2, 8, 0)
        gtv_tarde = sembrar.encuesta(anchor=t2)          # id menor, ancla tardía
        gtv_temprana = sembrar.encuesta(anchor=t1)       # id mayor, ancla temprana
        previa = sembrar.biblioteca(via="prior", anchor=t1)
        legado = sembrar.biblioteca(via="legacy", anchor=t2)
        cancelada = sembrar.biblioteca(via="prior", anchor=t1, proceso="cancelled")
        return gtv_tarde, gtv_temprana, previa, legado, cancelada

    def test_dry_run_cuenta_y_no_escribe_nada(self, db_session, sembrar):
        gtv_tarde, gtv_temprana, previa, legado, cancelada = self._cinco(sembrar)
        todas = (gtv_tarde, gtv_temprana, previa, legado, cancelada)
        db_session.flush()
        contadores_antes = db_session.execute(
            text("SELECT COUNT(*) FROM titulatec_certificate_counters "
                        "WHERE semester = '2093A'")).scalar()

        conteo = FolioBackfillService.run(db_session, dry_run=True)

        assert _solo_de(conteo, {"2093A"}) == {(_SURVEY, "2093A"): 2,
                                               (_LIBRARY, "2093A"): 2}
        assert _certs(db_session, *todas) == []
        assert not db_session.new and not db_session.dirty
        assert db_session.execute(
            text("SELECT COUNT(*) FROM titulatec_certificate_counters "
                        "WHERE semester = '2093A'")).scalar() == contadores_antes

    def test_dry_run_no_commitea(self, db_session, sembrar, monkeypatch):
        self._cinco(sembrar)
        llamadas = []
        monkeypatch.setattr(db_session, "commit", lambda: llamadas.append(1))

        FolioBackfillService.run(db_session, dry_run=True)

        assert llamadas == []

    def test_corrida_real_emite_sin_emisor_y_en_el_orden_del_ancla(
            self, db_session, sembrar):
        gtv_tarde, gtv_temprana, previa, legado, cancelada = self._cinco(sembrar)

        conteo = FolioBackfillService.run(db_session, dry_run=False)

        assert _solo_de(conteo, {"2093A"}) == {(_SURVEY, "2093A"): 2,
                                               (_LIBRARY, "2093A"): 2}
        # Encuesta: el ancla temprana lleva el 0001 aunque su id sea mayor.
        (c_temprana,) = _certs(db_session, gtv_temprana)
        (c_tarde,) = _certs(db_session, gtv_tarde)
        assert c_temprana.number == "GTV-2093A-0001"
        assert c_tarde.number == "GTV-2093A-0002"
        # Biblioteca: la previa (t1) antes que el legado (t2).
        (c_previa,) = _certs(db_session, previa)
        (c_legado,) = _certs(db_session, legado)
        assert c_previa.number == "BIB-2093A-0001"
        assert c_legado.number == "BIB-2093A-0002"
        for cert, s in ((c_temprana, gtv_temprana), (c_tarde, gtv_tarde),
                        (c_previa, previa), (c_legado, legado)):
            assert cert.kind == s.kind
            assert cert.source_ref == s.ref
            assert cert.process_id == s.proc.id
            assert cert.issued_by_id is None              # sin emisor (CLI)
            assert cert.voided_at is None
            assert cert.batch_id is None
            assert cert.control_number == s.proc.student.control_number
        # El proceso `cancelled` no recibe folio.
        assert _certs(db_session, cancelada) == []

    def test_la_corrida_real_hace_un_solo_commit(self, db_session, sembrar, monkeypatch):
        self._cinco(sembrar)
        llamadas = []
        real = db_session.commit
        monkeypatch.setattr(db_session, "commit", lambda: (llamadas.append(1), real())[1])

        FolioBackfillService.run(db_session, dry_run=False)

        assert llamadas == [1]

    def test_si_una_emision_falla_no_se_commitea(self, db_session, sembrar, monkeypatch):
        self._cinco(sembrar)
        llamadas = []
        monkeypatch.setattr(db_session, "commit", lambda: llamadas.append(1))
        real_issue = CertificateService.issue
        emitidas = []

        def _falla_en_la_segunda(*args, **kwargs):
            if emitidas:
                raise RuntimeError("fallo de prueba")
            emitidas.append(1)
            return real_issue(*args, **kwargs)

        monkeypatch.setattr(CertificateService, "issue", staticmethod(_falla_en_la_segunda))

        with pytest.raises(RuntimeError, match="fallo de prueba"):
            FolioBackfillService.run(db_session, dry_run=False)

        assert llamadas == [], "una corrida a medias NO se commitea"

    def test_una_segunda_corrida_da_cero(self, db_session, sembrar):
        gtv_tarde, gtv_temprana, previa, legado, _cancelada = self._cinco(sembrar)
        primera = FolioBackfillService.run(db_session, dry_run=False)
        assert sum(primera.values()) >= 4
        numeros = {c.source_ref: c.number
                   for c in _certs(db_session, gtv_tarde, gtv_temprana, previa, legado)}

        segunda = FolioBackfillService.run(db_session, dry_run=False)
        en_seco = FolioBackfillService.run(db_session, dry_run=True)

        # La primera corrida folió TODO lo que había, sembrado o real: no
        # queda nada sin folio vigente, sea cual sea la base.
        assert sum(segunda.values()) == 0
        assert sum(en_seco.values()) == 0
        assert {c.source_ref: c.number
                for c in _certs(db_session, gtv_tarde, gtv_temprana, previa, legado)
                } == numeros, "los folios ya emitidos no cambian"

    def test_una_previa_con_folio_vigente_no_se_toca(self, db_session, sembrar):
        con_folio = sembrar.encuesta()
        original = _emitir(db_session, con_folio, semestre="2092B")
        numero, emitida = original.number, original.issued_at
        sin_folio = sembrar.encuesta()

        FolioBackfillService.run(db_session, dry_run=False)

        (cert,) = _certs(db_session, con_folio)
        assert (cert.number, cert.issued_at, cert.voided_at) == (numero, emitida, None)
        assert cert.number.startswith("GTV-2092B-")       # NO se re-folió a 2093A
        (nuevo,) = _certs(db_session, sin_folio)
        assert nuevo.number.startswith("GTV-2093A-")

    def test_un_folio_anulado_se_repone_con_uno_nuevo(self, db_session, sembrar):
        """Anular nunca libera el folio (invariante 2) y la liberación sigue
        vigente: el backfill saca uno NUEVO; el anulado queda como estaba."""
        previa = sembrar.biblioteca(via="prior")
        viejo = _emitir(db_session, previa, semestre="2092B")
        numero_viejo = viejo.number
        CertificateService.void(db_session, source_ref=previa.ref, actor_id=None,
                                reason="se anuló")

        FolioBackfillService.run(db_session, dry_run=False)

        certs = _certs(db_session, previa)
        assert len(certs) == 2
        anulado, vigente = certs
        assert anulado.number == numero_viejo and anulado.voided_at is not None
        assert vigente.voided_at is None
        assert vigente.number != numero_viejo
        assert vigente.number.startswith("BIB-2093A-")

    def test_el_semestre_del_folio_es_el_del_ancla_no_el_de_hoy(
            self, db_session, sembrar):
        febrero = sembrar.encuesta(anchor=datetime(2093, 2, 10, 9, 0))
        octubre = sembrar.encuesta(anchor=OCT_2093)

        FolioBackfillService.run(db_session, dry_run=False)

        (c_feb,) = _certs(db_session, febrero)
        (c_oct,) = _certs(db_session, octubre)
        assert re.fullmatch(r"GTV-2092B-\d{4}", c_feb.number), c_feb.number
        assert re.fullmatch(r"GTV-2093A-\d{4}", c_oct.number), c_oct.number
        # `issued_at` sigue siendo la hora real de emisión (hoy), no el ancla.
        assert c_feb.issued_at.year != 2093


# ---------------------------------------------------------------------------
# CLI: `titulatec emitir-folios-previos`
# ---------------------------------------------------------------------------
_CONTEO = {(_LIBRARY, "2026A"): 2, (_SURVEY, "2026A"): 372, (_SURVEY, "2026B"): 1}


def _cli(args, *, conteo=_CONTEO):
    """El comando con el service parchado (sin BD): devuelve el resultado y el
    mock de `run`."""
    with patch.object(FolioBackfillService, "run", return_value=dict(conteo)) as run:
        res = CliRunner().invoke(emitir_folios_previos_command, args)
    return res, run


class TestCli:
    def test_imprime_los_conteos_por_tipo_y_semestre(self):
        res, run = _cli([])

        assert res.exit_code == 0, res.output
        run.assert_called_once()
        assert run.call_args.kwargs == {"dry_run": False}
        assert "Folios emitidos: 375" in res.output
        assert "No adeudo (BIB) · 2026A: 2" in res.output
        assert "Encuesta (GTV) · 2026A: 372" in res.output
        assert "Encuesta (GTV) · 2026B: 1" in res.output
        assert "Dry-run" not in res.output

    def test_dry_run_lo_dice_y_pasa_dry_run_al_service(self):
        res, run = _cli(["--dry-run"])

        assert res.exit_code == 0, res.output
        assert run.call_args.kwargs == {"dry_run": True}
        assert "[dry-run] Folios por emitir: 375" in res.output
        assert "Encuesta (GTV) · 2026A: 372" in res.output
        assert "Dry-run: no se escribió nada." in res.output

    @pytest.mark.parametrize("args, marca", [([], ""), (["--dry-run"], "[dry-run] ")])
    def test_sin_nada_pendiente_lo_dice(self, args, marca):
        res, _run = _cli(args, conteo={})

        assert res.exit_code == 0, res.output
        assert f"{marca}No hay previas ni legado sin folio vigente: nada que emitir." \
            in res.output

    def test_de_punta_a_punta_contra_la_sesion_del_test(
            self, db_session, patched_session_local, sembrar):
        """Sin parchar el service: la CLI abre `SessionLocal()` (la del test),
        folía las filas sembradas y las cuenta en SU semestre. Los datos reales
        de la base también salen en el resumen: aquí solo se miran las líneas
        del semestre sintético."""
        sembrar.encuesta()
        sembrar.encuesta()
        sembrar.biblioteca(via="legacy")

        seco = CliRunner().invoke(emitir_folios_previos_command, ["--dry-run"])
        assert seco.exit_code == 0, seco.output
        assert "Encuesta (GTV) · 2093A: 2" in seco.output
        assert "No adeudo (BIB) · 2093A: 1" in seco.output
        assert db_session.query(Certificate).filter(
            Certificate.number.like("%-2093A-%")).count() == 0, "el dry-run no escribe"

        real = CliRunner().invoke(emitir_folios_previos_command, [])
        assert real.exit_code == 0, real.output
        assert "Encuesta (GTV) · 2093A: 2" in real.output
        assert "No adeudo (BIB) · 2093A: 1" in real.output
        folios = sorted(c.number for c in db_session.query(Certificate).filter(
            Certificate.number.like("%-2093A-%")))
        assert folios == ["BIB-2093A-0001", "GTV-2093A-0001", "GTV-2093A-0002"]

        otra = CliRunner().invoke(emitir_folios_previos_command, [])
        assert otra.exit_code == 0, otra.output
        assert "nada que emitir" in otra.output

    def test_el_helper_abre_su_propia_sesion_y_la_cierra(self):
        """`_emitir_folios_previos` abre `SessionLocal()` (import local: la
        convención del proyecto, que `patched_session_local` intercepta) y la
        cierra siempre; con error, la deshace."""
        sesion = SimpleNamespace(rollbacks=0, closed=False)
        sesion.rollback = lambda: setattr(sesion, "rollbacks", sesion.rollbacks + 1)
        sesion.close = lambda: setattr(sesion, "closed", True)

        with patch("itcj2.database.SessionLocal", lambda: sesion), \
                patch.object(FolioBackfillService, "run", return_value={}):
            assert _emitir_folios_previos(dry_run=True) == {}
        assert sesion.closed and sesion.rollbacks == 0

        sesion.closed = False
        with patch("itcj2.database.SessionLocal", lambda: sesion), \
                patch.object(FolioBackfillService, "run",
                             side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                _emitir_folios_previos(dry_run=False)
        assert sesion.closed and sesion.rollbacks == 1

