"""Guarda de transicion de fase: un POST no puede completar ni corromper un proceso.

BLOQUEADOR reproducido en el contenedor antes de escribir estos tests:
`PhaseService.approve_phase` no validaba NADA sobre `phase_number`. La ruta
(`pages/admin.py:807-825`) pasaba el `n` de la URL tal cual, sin compararlo con
`process.current_phase` ni con `process.status`. Con `titulatec.process.api.approve_phase`
(que hoy tienen school_services, head y titulaciones) un solo POST bastaba para:

  * `n=8` desde `current_phase=1`  -> proceso `completed` saltandose 7 fases;
  * `n=99`                          -> proceso `completed` + `ProcessPhase` fantasma;
  * `n=0` desde `current_phase=5`   -> el proceso retrocede a la fase 1;
  * `n=-5` en `reject_phase`        -> `current_phase = -5` (fuera del dominio 0..8);
  * proceso ya `completed`          -> se reabre conservando `status='completed'`.

Contradice `docs/flows/00_state_machine.md:26-33` y la precondicion declarada en
`docs/flows/engine_approve_advance_phase.md` ("Proceso `active`; la fase a aprobar es
`current_phase`").

La guarda vive en el SERVICE (`PhaseService.assert_can_transition`), no solo en la ruta:
`approve_phase` tiene tres llamadores (`admin.py`, `documents.py` auto-avance) y el
siguiente los tendra tambien. La ruta la traduce al canal de error de la app
(400 + `X-Tt-Error`, igual que `officers.py:65-72`) y acota el path param.

REGLA DE ORO (heredada de la spec de scope): ninguna asercion negativa va sola. Cada
"no se pudo" viene acompanada del positivo del MISMO actor sobre la MISMA ruta, para que
una guarda que diga que no SIEMPRE —o unos fixtures rotos— salgan en rojo.
"""
from __future__ import annotations

import pytest

from tests.fastapi.titulatec.conftest import HEAD_PERMS

from itcj2.apps.titulatec.services.phase_service import PhaseService

# El actor de estas pruebas dictamina fases: los permisos de bandeja + los dos de accion.
PHASE_PERMS = HEAD_PERMS + (
    "titulatec.process.api.approve_phase",
    "titulatec.process.api.reject_phase",
)


def _url(process_id: int, n, action: str) -> str:
    return f"/titulatec/admin/processes/{process_id}/phase/{n}/{action}"


def _phases(db, process_id: int) -> dict[int, str]:
    from itcj2.apps.titulatec.models import ProcessPhase
    rows = db.query(ProcessPhase).filter_by(process_id=process_id).all()
    return {r.phase_number: r.status for r in rows}


@pytest.fixture()
def escenario(seed_phase_defs, make_program, make_cohort, make_student, make_process):
    """Catalogo de fases + un proceso `active` en la fase que pida el test."""
    def _build(current_phase=1, status="active"):
        seed_phase_defs()
        program = make_program("Ingenieria Ficticia A")
        cohort = make_cohort()
        student = make_student()
        proc = make_process(student, cohort=cohort, program=program,
                            current_phase=current_phase, status=status)
        return proc

    return _build


# ---------------------------------------------------------------------------
# Guarda en el service
# ---------------------------------------------------------------------------
class TestGuardaEnElService:
    def test_no_aprueba_una_fase_futura(self, db_session, escenario):
        """`n=8` desde la fase 1 completaba el proceso saltandose 7 fases."""
        proc = escenario(current_phase=1)

        with pytest.raises(ValueError):
            PhaseService.approve_phase(db_session, proc, 8, reviewer_id=proc.student_id)

        assert proc.current_phase == 1
        assert proc.status == "active"
        assert proc.completed_at is None
        assert _phases(db_session, proc.id)[8] == "pending"

    def test_no_aprueba_una_fase_fuera_del_catalogo(self, db_session, escenario):
        """`n=99` completaba el proceso y dejaba un `ProcessPhase` fantasma."""
        proc = escenario(current_phase=1)

        with pytest.raises(ValueError):
            PhaseService.approve_phase(db_session, proc, 99, reviewer_id=proc.student_id)

        assert proc.current_phase == 1
        assert proc.status == "active"
        assert 99 not in _phases(db_session, proc.id)

    def test_no_retrocede_a_una_fase_pasada(self, db_session, escenario):
        """`n=0` desde la fase 5 devolvia el proceso a la fase 1."""
        proc = escenario(current_phase=5)

        with pytest.raises(ValueError):
            PhaseService.approve_phase(db_session, proc, 0, reviewer_id=proc.student_id)

        assert proc.current_phase == 5
        assert _phases(db_session, proc.id)[1] == "approved"  # seguia aprobada, no reabierta

    def test_reject_no_acepta_una_fase_negativa(self, db_session, escenario):
        """`n=-5` dejaba `current_phase = -5`, fuera del dominio 0..8."""
        proc = escenario(current_phase=1)

        with pytest.raises(ValueError):
            PhaseService.reject_phase(db_session, proc, -5, reviewer_id=proc.student_id,
                                      reason="motivo")

        assert proc.current_phase == 1
        assert -5 not in _phases(db_session, proc.id)

    def test_no_reabre_un_proceso_completado(self, db_session, escenario):
        """Repro exacto: aprobar la fase 3 de un proceso `completed` lo dejaba en
        `current_phase=4` conservando `status='completed'` — un hibrido imposible."""
        proc = escenario(current_phase=8, status="completed")

        with pytest.raises(ValueError):
            PhaseService.approve_phase(db_session, proc, 3, reviewer_id=proc.student_id)

        assert proc.status == "completed"
        assert proc.current_phase == 8

    def test_un_proceso_completado_no_admite_ni_su_propia_fase(self, db_session, escenario):
        """Aisla la guarda de `status`: aqui `n == current_phase`, asi que la unica
        razon para negarlo es que el proceso ya no esta `active`."""
        proc = escenario(current_phase=8, status="completed")

        with pytest.raises(ValueError):
            PhaseService.approve_phase(db_session, proc, 8, reviewer_id=proc.student_id)

        assert proc.status == "completed"
        assert _phases(db_session, proc.id)[8] != "approved"

    def test_la_fase_actual_de_un_proceso_activo_si_avanza(self, db_session, escenario):
        """Positivo de control: la guarda no puede ser un 'no' universal."""
        proc = escenario(current_phase=1)

        out = PhaseService.approve_phase(db_session, proc, 1, reviewer_id=proc.student_id)

        assert out == {"next_phase": 2, "completed": False}
        assert proc.current_phase == 2
        assert _phases(db_session, proc.id)[1] == "approved"

    def test_el_rango_sale_del_catalogo_no_de_un_literal(self, db_session, seed_phase_defs):
        """La cota superior se deriva de `titulatec_phase_definitions`.

        Con el catalogo sembrado (0-8) la ultima fase es la 8; si manana se agrega
        la 9, la guarda y `_next_applicable` la aceptan sin tocar codigo.
        """
        seed_phase_defs()

        assert PhaseService.phase_range(db_session) == (0, 8)

    def test_el_importador_crea_una_fase_por_cada_una_del_catalogo(
        self, db_session, titulatec_app, seed_phase_defs, make_cohort,
    ):
        """Test de FIJACION, no de defecto: verde antes y despues del arreglo.

        El alta masiva creaba las `ProcessPhase` con un `range(9)` escrito a mano,
        el segundo literal del dominio 0..8. Ahora sale del mismo catalogo que la
        guarda; esto pin-ea que ambos sitios sigan de acuerdo.
        """
        from itcj2.apps.titulatec.models import ProcessPhase, TitulationProcess
        from itcj2.apps.titulatec.services.import_service import ImportService

        defs = seed_phase_defs()
        cohort = make_cohort()
        ImportService.import_rows(db_session, cohort, [{
            "control_number": "99400001", "full_name": "ALUMNA INVENTADA",
            "email": None, "program_id": None, "modality_id": None,
        }])

        proc = db_session.query(TitulationProcess).filter_by(cohort_id=cohort.id).one()
        numeros = sorted(p.phase_number for p in db_session.query(ProcessPhase)
                         .filter_by(process_id=proc.id).all())
        assert numeros == sorted(d.number for d in defs)


# ---------------------------------------------------------------------------
# Guarda vista desde la ruta (canal de error de la app)
# ---------------------------------------------------------------------------
class TestGuardaEnLaRuta:
    def test_aprobar_una_fase_futura_devuelve_400_y_no_toca_la_bd(
        self, client_as, make_head, db_session, escenario,
    ):
        head = make_head(perm_codes=PHASE_PERMS)
        proc = escenario(current_phase=1)

        resp = client_as(head).post(_url(proc.id, 8, "approve"))

        assert resp.status_code == 400, resp.text[:500]
        assert resp.headers.get("X-Tt-Error"), "el error debe viajar por el canal de la app"
        db_session.refresh(proc)
        assert proc.current_phase == 1
        assert proc.status == "active"

    def test_aprobar_una_fase_inexistente_devuelve_400_no_500(
        self, client_as, make_head, db_session, escenario,
    ):
        head = make_head(perm_codes=PHASE_PERMS)
        proc = escenario(current_phase=1)

        resp = client_as(head).post(_url(proc.id, 99, "approve"))

        assert resp.status_code == 400, resp.text[:500]
        # El mensaje nombra la fase pedida y el rango real, y va sin acentos: el
        # header lo escribe Starlette en latin-1 pero su TestClient lo lee como
        # UTF-8, y un byte >127 tumba el request entero (ver `_transition_error`).
        assert "99" in resp.headers.get("X-Tt-Error", "")
        # El header llega percent-codificado (`_hdr`): los valores de header son
        # latin-1 y un mensaje con acentos sin codificar llega roto al cliente.
        from urllib.parse import unquote
        assert "fuera de rango" in unquote(resp.headers.get("X-Tt-Error", ""))
        db_session.refresh(proc)
        assert proc.status == "active"
        assert 99 not in _phases(db_session, proc.id)

    def test_rechazar_con_fase_negativa_no_pasa_del_path_param(
        self, client_as, make_head, db_session, escenario,
    ):
        """El path param esta acotado: un negativo ni siquiera llega al handler."""
        head = make_head(perm_codes=PHASE_PERMS)
        proc = escenario(current_phase=1)

        resp = client_as(head).post(_url(proc.id, -5, "reject"), data={"reason": "x"})

        assert resp.status_code == 422, resp.text[:500]
        db_session.refresh(proc)
        assert proc.current_phase == 1
        assert -5 not in _phases(db_session, proc.id)

    def test_aprobar_un_proceso_completado_devuelve_400(
        self, client_as, make_head, db_session, escenario,
    ):
        head = make_head(perm_codes=PHASE_PERMS)
        proc = escenario(current_phase=8, status="completed")

        resp = client_as(head).post(_url(proc.id, 8, "approve"))

        assert resp.status_code == 400, resp.text[:500]
        db_session.refresh(proc)
        assert proc.status == "completed"

    def test_aprobar_la_fase_actual_sigue_devolviendo_el_parcial(
        self, client_as, make_head, db_session, escenario,
    ):
        """Positivo de la MISMA ruta: 200, parcial re-renderizado y fase avanzada."""
        head = make_head(perm_codes=PHASE_PERMS)
        proc = escenario(current_phase=1)

        resp = client_as(head).post(_url(proc.id, 1, "approve"))

        assert resp.status_code == 200, resp.text[:500]
        db_session.refresh(proc)
        assert proc.current_phase == 2
        assert _phases(db_session, proc.id)[1] == "approved"

    def test_rechazar_la_fase_actual_sigue_funcionando(
        self, client_as, make_head, db_session, escenario,
    ):
        head = make_head(perm_codes=PHASE_PERMS)
        proc = escenario(current_phase=1)

        resp = client_as(head).post(_url(proc.id, 1, "reject"),
                                    data={"reason": "Falta la firma del acta"})

        assert resp.status_code == 200, resp.text[:500]
        db_session.refresh(proc)
        assert proc.current_phase == 1
        assert _phases(db_session, proc.id)[1] == "rejected"


# ---------------------------------------------------------------------------
# El otro camino que avanza fases: el auto-avance del dictamen de documentos
# ---------------------------------------------------------------------------
DOC_REVIEW_PERMS = HEAD_PERMS + ("titulatec.document.api.approve",
                                 "titulatec.document.api.reject")


def test_el_autoavance_de_documentos_no_toca_un_proceso_no_activo(
    client_as, make_head, db_session, escenario, make_document, seed_document_types,
):
    """`documents.py:132-134` avanza la fase 1 mirando solo `current_phase == 1`.

    Es el OTRO camino que mueve fases. Sobre un proceso `cancelled` parado en la
    fase 1, aprobar el ultimo documento lo empujaba igual a la fase 2. Con la
    guarda en el service ese camino tiene que quedar filtrado ANTES de llamar a
    `approve_phase`: si no, el dictamen revienta con un 500 en vez de no hacer nada.
    """
    seed_document_types()
    head = make_head(perm_codes=DOC_REVIEW_PERMS)
    proc = escenario(current_phase=1, status="cancelled")
    make_document(proc, type_code="birth_certificate", review_status="approved")
    make_document(proc, type_code="high_school_cert", review_status="approved")
    make_document(proc, type_code="curp", review_status="pending")

    resp = client_as(head).post(
        f"/titulatec/admin/documents/{proc.id}/document/review",
        data={"type_code": "curp", "action": "approve"},
    )

    assert resp.status_code == 200, resp.text[:500]
    db_session.refresh(proc)
    assert proc.current_phase == 1, "un proceso no activo no debe avanzar de fase"
    assert proc.status == "cancelled"
