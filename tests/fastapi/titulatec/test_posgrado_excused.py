"""R-G llega a los CONTADORES, no solo a la elegibilidad (Ruling R11, revisión
final de la rama 2026-09-30, sobre `docs/superpowers/specs/2026-09-30-
titulatec-posgrado-design.md` §5, invariante 8).

Hallazgo corregido (revisión final, textual abreviado): R-G ya evitaba que un
posgrado con la fase 1 cerrada antes del despliegue se regresara de "Por
agendar" (`DocumentService.initial_docs_all_approved`) -- pero los 4 extras
dispensados seguían contando como "pendientes" en la bandeja de Documentos
(`pages/documents.py::_doc_row`, `pending`/`all_approved`), como "sin subir"
en el resumen del alumno (`initial_docs_summary`/`_docs_progress`), y como
"Falta" en el visor de cotejo y el expediente.

Contrato (Ruling R11):

1. UN SOLO predicado -- `DocumentService.excused_initial_docs(process,
   present_codes, *, initial_docs_phase)` -- decide la dispensa. Puro (sin
   `db`): el llamador resuelve `initial_docs_phase` (`PhaseService.
   phase_number_for_code(db, "initial_docs")`) una sola vez.
2. Pseudo-estado `excused` ("Se entrega en el cotejo" / "En cotejo"), igual
   que `missing` es pseudo-estado de la UI: NO es un valor de
   `Document.review_status`.
   - `initial_docs_summary`: cada extra dispensado sale `status="excused"`;
     `counts["excused"]`; `total`/`uploaded` cuentan SOLO lo exigible en
     línea (sin los dispensados).
   - Bandeja (`_doc_row`): los dispensados NO cuentan en `pending` ni impiden
     `all_approved`; píldora neutra "En cotejo" (`estado_pill`, `_macros.html`).
   - Tablero del alumno (`_docs_progress`/`phase_progress.html`): mismo
     estado "aprobado" de antes del despliegue + línea neutra "Se entrega en
     el cotejo" por cada dispensado.
   - Visor de cotejo y expediente: mismos 7 renglones, "Se entrega en el
     cotejo" en vez de "Falta" para los dispensados.

Este archivo fija el predicado y sus 4 consumidores. Las pruebas de perfil
"sano" (posgrado en fase 1, licenciatura, `initial_docs_all_approved`) ya
viven en `test_document_service_track.py`; este archivo es SOLO la dispensa
llegando a los contadores.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.fastapi.titulatec.conftest import INITIAL_DOC_TYPES, POSGRADO_DOC_TYPES

BASE = ("birth_certificate", "high_school_cert", "curp")
EXTRAS = ("professional_license", "degree_title", "postgrad_authorization", "efirma_sat")


@pytest.fixture()
def posgrado(seed_phase_defs, seed_document_types, make_program):
    """Siembra fases + los 7 tipos de documento y devuelve una carrera de
    posgrado (`level="maestria"`), lista para procesos con la fase 1 cerrada."""
    seed_phase_defs()
    seed_document_types(types=INITIAL_DOC_TYPES + POSGRADO_DOC_TYPES)
    return make_program("Maestria de Prueba R-G Excused", level="maestria")


# ---------------------------------------------------------------------------
# 1. El predicado en si -- puro, sin BD (invariante 8, Ruling R11 punto 1)
# ---------------------------------------------------------------------------
def test_excused_dispensa_los_faltantes_si_la_fase_ya_cerro():
    from itcj2.apps.titulatec.services.document_service import DocumentService

    proceso = SimpleNamespace(current_phase=2)
    dispensados = DocumentService.excused_initial_docs(
        proceso, frozenset({"professional_license"}), initial_docs_phase=1)

    # `professional_license` esta en `present_codes` (tiene fila): NUNCA se
    # dispensa, sea cual sea su estado -- solo los otros 3 (sin fila) salen.
    assert dispensados == frozenset(EXTRAS) - {"professional_license"}


def test_excused_nada_si_la_fase_sigue_abierta():
    from itcj2.apps.titulatec.services.document_service import DocumentService

    proceso = SimpleNamespace(current_phase=1)
    assert DocumentService.excused_initial_docs(
        proceso, frozenset(), initial_docs_phase=1) == frozenset()


def test_excused_nada_si_la_fase_es_justo_la_actual():
    """`current_phase == initial_docs_phase`: la fase 1 esta EN CURSO, no
    "ya paso" -- el borde exacto no debe dispensar nada."""
    from itcj2.apps.titulatec.services.document_service import DocumentService

    proceso = SimpleNamespace(current_phase=1)
    assert DocumentService.excused_initial_docs(
        proceso, frozenset(), initial_docs_phase=1) == frozenset()


def test_excused_nada_sin_catalogo_de_fases():
    from itcj2.apps.titulatec.services.document_service import DocumentService

    proceso = SimpleNamespace(current_phase=5)
    assert DocumentService.excused_initial_docs(
        proceso, frozenset(), initial_docs_phase=None) == frozenset()


def test_excused_nada_sin_proceso():
    from itcj2.apps.titulatec.services.document_service import DocumentService

    assert DocumentService.excused_initial_docs(
        None, frozenset(), initial_docs_phase=1) == frozenset()


# ---------------------------------------------------------------------------
# 2. `initial_docs_summary` -- total/uploaded/counts excluyen lo dispensado
# ---------------------------------------------------------------------------
def test_summary_fase_1_cerrada_dispensa_los_4_extras(
        db_session, posgrado, make_student, make_process, make_document):
    from itcj2.apps.titulatec.services.document_service import DocumentService

    proc = make_process(make_student(), program=posgrado, current_phase=2)
    for code in BASE:
        make_document(proc, type_code=code, review_status="approved")

    summary = DocumentService.initial_docs_summary(db_session, proc.id)

    assert summary["total"] == 3
    assert summary["uploaded"] == 3
    assert summary["counts"]["excused"] == 4
    assert summary["counts"]["missing"] == 0
    excusados = {it["code"] for it in summary["items"] if it["status"] == "excused"}
    assert excusados == set(EXTRAS)
    aprobados = {it["code"] for it in summary["items"] if it["status"] == "approved"}
    assert aprobados == set(BASE)


def test_summary_posgrado_en_fase_1_no_dispensa_nada(
        db_session, posgrado, make_student, make_process, make_document):
    """Posgrado con la fase 1 TODAVIA ABIERTA -> sigue exigiendo los 7, sin
    dispensados (mismo resultado que antes de esta rama)."""
    from itcj2.apps.titulatec.services.document_service import DocumentService

    proc = make_process(make_student(), program=posgrado, current_phase=1)
    for code in BASE:
        make_document(proc, type_code=code, review_status="approved")

    summary = DocumentService.initial_docs_summary(db_session, proc.id)

    assert summary["total"] == 7
    assert summary["counts"]["excused"] == 0
    assert summary["counts"]["missing"] == 4


def test_summary_extra_existente_rechazado_en_fase_2_no_se_dispensa(
        db_session, posgrado, make_student, make_process, make_document):
    """Un extra que SI tiene fila nunca se dispensa -- cuenta como hoy."""
    from itcj2.apps.titulatec.services.document_service import DocumentService

    proc = make_process(make_student(), program=posgrado, current_phase=2)
    for code in BASE:
        make_document(proc, type_code=code, review_status="approved")
    make_document(proc, type_code="professional_license", review_status="rejected")

    summary = DocumentService.initial_docs_summary(db_session, proc.id)

    assert summary["counts"]["excused"] == 3           # los otros 3 SI se dispensan
    assert summary["counts"]["rejected"] == 1
    assert summary["total"] == 4                        # 3 base + el rechazado (exigible)
    item = next(it for it in summary["items"] if it["code"] == "professional_license")
    assert item["status"] == "rejected"


def test_summary_licenciatura_identico_a_hoy(
        db_session, seed_phase_defs, seed_document_types, make_student, make_process,
        make_document):
    """Invariante 3: licenciatura no distingue perfil ni fase -- nunca hay
    `POSGRADO_EXTRA_DOCS` en su set, asi que `excused` siempre es 0."""
    from itcj2.apps.titulatec.services.document_service import DocumentService

    seed_phase_defs()
    seed_document_types()
    proc = make_process(make_student(), current_phase=2)   # fase 1 ya cerrada tambien
    for code in BASE:
        make_document(proc, type_code=code, review_status="approved")

    summary = DocumentService.initial_docs_summary(db_session, proc.id)

    assert summary["total"] == 3
    assert summary["counts"]["excused"] == 0


# ---------------------------------------------------------------------------
# 3. Bandeja de Documentos (`_doc_row`/`_body_ctx`) -- pending/all_approved/pildora
# ---------------------------------------------------------------------------
def test_bandeja_fase_1_cerrada_no_cuenta_pendientes_y_aprueba(
        db_session, posgrado, make_student, make_cohort, make_process, make_document):
    from itcj2.apps.titulatec.pages.documents import _doc_rows

    proc = make_process(make_student(), cohort=make_cohort(), program=posgrado,
                        current_phase=2)
    for code in BASE:
        make_document(proc, type_code=code, review_status="approved")

    (fila,) = _doc_rows(db_session, [proc])

    assert fila["pending"] == 0
    assert fila["all_approved"] is True
    excusados = {d["type_code"] for d in fila["docs"] if d["status"] == "excused"}
    assert excusados == set(EXTRAS)


def test_bandeja_fase_1_cerrada_sale_de_por_evaluar_y_entra_a_completos(
        db_session, posgrado, make_student, make_cohort, make_process, make_document,
        make_head):
    from itcj2.apps.titulatec.pages.documents import _body_ctx

    proc = make_process(make_student(), cohort=make_cohort(), program=posgrado,
                        current_phase=2)
    for code in BASE:
        make_document(proc, type_code=code, review_status="approved")
    jefa = make_head()

    por_evaluar = _body_ctx(db_session, user_id=jefa.id, status_filter="pending",
                            selected_id=None)
    completos = _body_ctx(db_session, user_id=jefa.id, status_filter="approved",
                          selected_id=None)

    assert proc.id not in {r["process_id"] for r in por_evaluar["rows"]}
    assert proc.id in {r["process_id"] for r in completos["rows"]}


def test_bandeja_html_pinta_la_pildora_en_cotejo(
        db_session, posgrado, make_student, make_cohort, make_process, make_document,
        make_head, client_as):
    proc = make_process(make_student(), cohort=make_cohort(), program=posgrado,
                        current_phase=2)
    for code in BASE:
        make_document(proc, type_code=code, review_status="approved")
    jefa = make_head()

    html = client_as(jefa).get(
        "/titulatec/admin/documents/body?selected=%d" % proc.id).text

    assert "En cotejo" in html


# ---------------------------------------------------------------------------
# 4. Tablero del alumno -- ni "sin subir" ni ambar; "Se entrega en el cotejo"
# ---------------------------------------------------------------------------
def test_dashboard_alumno_fase_1_cerrada_aprobado_y_dispensados(
        db_session, posgrado, make_student, make_process, make_document):
    from itcj2.apps.titulatec.pages.student import _phases_ctx

    proc = make_process(make_student(), program=posgrado, current_phase=2)
    for code in BASE:
        make_document(proc, type_code=code, review_status="approved")

    ctx = _phases_ctx(db_session, proc)
    card = next(c for c in ctx["phases"] if c["number"] == 1)
    prog = card["progress"]

    # Mismo estado "aprobado" que antes del despliegue: nada en ambar, nada
    # "sin subir" -- ni en el resumen ni en ningun item.
    assert prog["tone"] == "success"
    assert prog["label"] == "Los 3 documentos aprobados"
    estados = {it["code"]: it["status"] for it in prog["items"]}
    for code in BASE:
        assert estados[code] == "approved"
    for code in EXTRAS:
        assert estados[code] == "excused"


def test_dashboard_alumno_html_dice_se_entrega_en_el_cotejo(
        db_session, posgrado, make_student, make_process, make_document, client_as):
    student = make_student()
    proc = make_process(student, program=posgrado, current_phase=2)
    for code in BASE:
        make_document(proc, type_code=code, review_status="approved")

    html = client_as(student).get("/titulatec/student/dashboard").text

    # Minuscula a proposito: `phase_progress.html` sigue el mismo patron de
    # continuacion lowercase que sus hermanos ("· aprobado", "· sin subir") --
    # NO es la pildora independiente (esa SI va con mayuscula, ver bandeja/
    # visor/expediente).
    assert "se entrega en el cotejo" in html


# ---------------------------------------------------------------------------
# 5. Visor de cotejo -- "Se entrega en el cotejo" en vez de "Falta"
# ---------------------------------------------------------------------------
def test_visor_cotejo_fase_1_cerrada_rotula_se_entrega_en_el_cotejo(
        db_session, posgrado, make_student, make_cohort, make_process, make_document,
        make_appointment, make_head, client_as):
    from itcj2.apps.titulatec.pages.appointments import _detail_ctx

    proc = make_process(make_student(), cohort=make_cohort(), program=posgrado,
                        current_phase=2)
    for code in BASE:
        make_document(proc, type_code=code, review_status="approved")

    jefa = make_head()
    detail = _detail_ctx(db_session, proc.id, user_id=jefa.id)

    excusados = {d["type_code"] for d in detail["docs"] if d["excused"]}
    assert excusados == set(EXTRAS)
    for d in detail["docs"]:
        if d["type_code"] in BASE:
            assert d["excused"] is False

    make_appointment(proc)
    html = client_as(jefa).get(
        "/titulatec/admin/appointments/body?v=atender&selected=%d" % proc.id).text
    assert "Se entrega en el cotejo" in html
    assert html.count("Falta") == 0, "ningun renglon debe leer 'Falta' -- son dispensados"


# ---------------------------------------------------------------------------
# 6. Expediente -- mismo criterio, "Se entrega en el cotejo" en vez de "Falta"
# ---------------------------------------------------------------------------
def test_expediente_fase_1_cerrada_rotula_se_entrega_en_el_cotejo(
        db_session, posgrado, make_student, make_cohort, make_process, make_document,
        make_head, client_as):
    from itcj2.apps.titulatec.pages.admin import _detail_ctx

    proc = make_process(make_student(), cohort=make_cohort(), program=posgrado,
                        current_phase=2)
    for code in BASE:
        make_document(proc, type_code=code, review_status="approved")

    jefa = make_head()
    ctx = _detail_ctx(db_session, proc.id, user_id=jefa.id)

    excusados = {d["type_code"] for d in ctx["docs"] if d["excused"]}
    assert excusados == set(EXTRAS)

    html = client_as(jefa).get("/titulatec/admin/processes/%d?fase=1" % proc.id).text
    assert "Se entrega en el cotejo" in html
