"""Vistas admin con el set de posgrado (spec 2026-09-30-titulatec-posgrado-
design.md §4.4, regla R-G §5, invariantes §6; Tarea 4).

`DocumentService`/`TrackService` (Tareas 2-3) ya saben que un egresado de
POSGRADO sube 7 documentos en la fase 1 (los 3 de siempre + 4 extras) en vez
de 3. Lo que fija este archivo es que las TRES vistas admin -- bandeja de
Documentos (`pages/documents.py`), visor de cotejo (`pages/appointments.py`)
y expediente (`pages/admin.py`) -- consuman ese servicio en vez de sus
literales `_INITIAL_DOC_TYPES` (3 códigos, sin perfil), y que la píldora
"Posgrado" (`_macros.html::track_pill`) aparezca SOLO junto a un proceso de
posgrado.

Lo que NO se toca aquí (Tarea 5): `pages/student.py` y sus templates --
siguen con su propio literal hasta esa tarea.
"""
from __future__ import annotations

from sqlalchemy import event

from tests.fastapi.titulatec.conftest import HEAD_PERMS, INITIAL_DOC_TYPES, POSGRADO_DOC_TYPES

ALL_CODES = [c for c, _, _ in INITIAL_DOC_TYPES] + [c for c, _, _ in POSGRADO_DOC_TYPES]
POSGRADO_CODES = [c for c, _, _ in POSGRADO_DOC_TYPES]


class _Contador:
    """Cuenta las sentencias SQL reales que pasan por la conexion del test.

    Copia reducida de `test_documents_inbox.py::_Contador` (mismo patron de
    medicion que usa esa suite): un `event.listen` sobre `before_cursor_execute`
    no se comparte entre modulos de test sin un import cruzado fragil, asi que
    este archivo se queda con su propia copia minima.
    """

    def __init__(self, conexion):
        self.conexion = conexion
        self.sentencias = []

    def __enter__(self):
        event.listen(self.conexion, "before_cursor_execute", self._ver)
        return self

    def __exit__(self, *exc):
        event.remove(self.conexion, "before_cursor_execute", self._ver)
        return False

    def _ver(self, conn, cursor, statement, params, context, executemany):
        self.sentencias.append(" ".join(statement.split()))

    def tocan(self, tabla):
        return [s for s in self.sentencias if tabla in s]


# ---------------------------------------------------------------------------
# 1 - Bandeja de Documentos: perfiles mezclados, 3/7/3, pildora solo en posgrado
# ---------------------------------------------------------------------------
def test_bandeja_perfiles_mezclados_3_7_3_y_pildora_solo_en_posgrado(
        db_session, seed_document_types, make_program, make_cohort, make_student,
        make_process, make_document, make_head, client_as):
    from itcj2.apps.titulatec.pages.documents import _doc_rows

    seed_document_types(types=INITIAL_DOC_TYPES + POSGRADO_DOC_TYPES)
    lic = make_program("Ingenieria Bandeja Mixta T4")
    pos = make_program("Maestria Bandeja Mixta T4", level="maestria")
    cohort = make_cohort()

    proc_lic = make_process(make_student(), cohort=cohort, program=lic)
    proc_pos = make_process(make_student(), cohort=cohort, program=pos)
    proc_sin = make_process(make_student(), cohort=cohort, program=None)
    # Al menos un archivo por fila: `_body_ctx` oculta la fila sin ninguno
    # (`any(d["has_file"] ...)`, `documents.py:175`).
    for proc in (proc_lic, proc_pos, proc_sin):
        make_document(proc, type_code="birth_certificate")

    filas = {f["process_id"]: f
             for f in _doc_rows(db_session, [proc_lic, proc_pos, proc_sin])}

    assert len(filas[proc_lic.id]["docs"]) == 3
    assert len(filas[proc_pos.id]["docs"]) == 7
    assert len(filas[proc_sin.id]["docs"]) == 3          # sin carrera -> licenciatura
    assert filas[proc_lic.id]["track"] == "licenciatura"
    assert filas[proc_pos.id]["track"] == "posgrado"
    assert filas[proc_sin.id]["track"] == "licenciatura"
    # El código de posgrado no se cuela en la fila de licenciatura ni viceversa.
    assert {d["type_code"] for d in filas[proc_lic.id]["docs"]} == set(
        c for c, _, _ in INITIAL_DOC_TYPES)
    assert {d["type_code"] for d in filas[proc_pos.id]["docs"]} == set(ALL_CODES)
    # "por evaluar" suma por el SET DE CADA FILA, no un 3 fijo.
    assert filas[proc_lic.id]["pending"] == 3
    assert filas[proc_pos.id]["pending"] == 7
    assert filas[proc_sin.id]["pending"] == 3

    # HTML: la jefa (read.all + officers.api.manage) ve las 3 filas -- incluida
    # la de "sin carrera" -- y la píldora "Posgrado" (tono violeta) sale
    # EXACTAMENTE una vez, junto al proceso de posgrado.
    jefa = make_head()
    html = client_as(jefa).get("/titulatec/admin/documents/body").text
    assert html.count("tt-pill tt-pill--violet") == 1
    assert "Posgrado" in html


def test_bandeja_licenciatura_sola_no_cambia_de_texto(
        db_session, seed_document_types, make_program, make_cohort, make_student,
        make_process, make_document):
    """Control: sin ningún proceso de posgrado en la bandeja, `_doc_row` sigue
    devolviendo EXACTAMENTE los 3 códigos de siempre, en el mismo orden."""
    from itcj2.apps.titulatec.pages.documents import _doc_rows

    seed_document_types()
    lic = make_program("Ingenieria Bandeja Sola T4")
    cohort = make_cohort()
    proc = make_process(make_student(), cohort=cohort, program=lic)
    make_document(proc, type_code="birth_certificate")

    (fila,) = _doc_rows(db_session, [proc])
    assert [d["type_code"] for d in fila["docs"]] == [
        "birth_certificate", "high_school_cert", "curp"]
    assert fila["track"] == "licenciatura"


def test_banner_de_aprobados_cuenta_el_set_del_perfil_no_un_3_fijo(
        db_session, seed_document_types, make_program, make_cohort, make_student,
        make_process, make_document, make_head, client_as):
    """Controller ruling R6 (fix previo a revision, Tarea 4):
    `documents_body.html:133` -- el banner de exito del panel de detalle --
    cuenta el set PROPIO de la fila (`detail.docs`), no un "3" fijo.
    Licenciatura sigue viendo exactamente "Los 3 aprobados"; un posgrado con
    los 7 aprobados ve "Los 7 aprobados"."""
    seed_document_types(types=INITIAL_DOC_TYPES + POSGRADO_DOC_TYPES)
    lic = make_program("Ingenieria Banner Aprobados T4")
    pos = make_program("Maestria Banner Aprobados T4", level="maestria")
    cohort = make_cohort()

    proc_lic = make_process(make_student(), cohort=cohort, program=lic)
    for code, _, _ in INITIAL_DOC_TYPES:
        make_document(proc_lic, type_code=code, review_status="approved")

    proc_pos = make_process(make_student(), cohort=cohort, program=pos)
    for code in ALL_CODES:
        make_document(proc_pos, type_code=code, review_status="approved")

    jefa = make_head()
    html_lic = client_as(jefa).get(
        "/titulatec/admin/documents/body?selected=%d" % proc_lic.id).text
    assert "Los 3 aprobados" in html_lic
    assert "Los 7 aprobados" not in html_lic

    html_pos = client_as(jefa).get(
        "/titulatec/admin/documents/body?selected=%d" % proc_pos.id).text
    assert "Los 7 aprobados" in html_pos
    assert "Los 3 aprobados" not in html_pos


# ---------------------------------------------------------------------------
# 2 - Presupuesto de consultas: perfiles mezclados agregan a lo sumo 1
# ---------------------------------------------------------------------------
def test_presupuesto_de_consultas_con_perfiles_mezclados(
        db_session, seed_document_types, make_program, make_cohort, make_student,
        make_process, make_document, make_head):
    """Mismo contador que `test_documents_inbox.py::
    test_el_contexto_completo_lee_titulatec_en_3_consultas` (~linea 159):
    solo tablas `titulatec_`, para no contar el coste de autorizacion. La
    linea base homogenea (solo licenciatura) mide 3; con perfiles mezclados
    el presupuesto es esa linea base + 1 como MAXIMO.
    """
    from itcj2.apps.titulatec.pages.documents import _body_ctx

    seed_document_types(types=INITIAL_DOC_TYPES + POSGRADO_DOC_TYPES)
    lic = make_program("Ingenieria Presupuesto T4")
    pos = make_program("Maestria Presupuesto T4", level="maestria")
    cohort = make_cohort()
    jefa = make_head()

    procs = []
    for programa in (lic, lic, pos):
        proc = make_process(make_student(), cohort=cohort, program=programa)
        make_document(proc, type_code="birth_certificate")
        procs.append(proc)

    with _Contador(db_session.get_bind()) as c:
        ctx = _body_ctx(db_session, user_id=jefa.id, status_filter=None, selected_id=None)

    vistos = {r["process_id"] for r in ctx["rows"]}
    assert {p.id for p in procs} <= vistos
    assert len(c.tocan("titulatec_")) <= 4, "\n".join(c.tocan("titulatec_"))


# ---------------------------------------------------------------------------
# 3 - Dictamen: los 3 base no avanzan un posgrado; el 7.o si
# ---------------------------------------------------------------------------
def test_dictamen_de_posgrado_no_avanza_con_los_3_base_pero_si_con_los_7(
        db_session, seed_phase_defs, seed_document_types, make_program, make_cohort,
        make_student, make_process, make_document, make_head, client_as):
    from itcj2.apps.titulatec.models import TitulationProcess

    seed_phase_defs()
    seed_document_types(types=INITIAL_DOC_TYPES + POSGRADO_DOC_TYPES)
    pos = make_program("Maestria Dictamen T4", level="maestria")
    cohort = make_cohort()
    proc = make_process(make_student(), cohort=cohort, program=pos, current_phase=1)
    for code in ALL_CODES:
        make_document(proc, type_code=code, review_status="pending")

    jefa = make_head(perm_codes=HEAD_PERMS + ("titulatec.document.api.approve",
                                              "titulatec.document.api.reject"))
    client = client_as(jefa)

    for code in ALL_CODES[:3]:                       # los 3 base
        resp = client.post(
            "/titulatec/admin/documents/%d/document/review" % proc.id,
            data={"type_code": code, "action": "approve"})
        assert resp.status_code == 200, resp.text[:400]

    db_session.expire_all()
    assert db_session.get(TitulationProcess, proc.id).current_phase == 1, (
        "los 3 base de un posgrado NO deben mover la fase")

    for code in ALL_CODES[3:]:                        # los 4 extras
        resp = client.post(
            "/titulatec/admin/documents/%d/document/review" % proc.id,
            data={"type_code": code, "action": "approve"})
        assert resp.status_code == 200, resp.text[:400]

    db_session.expire_all()
    assert db_session.get(TitulationProcess, proc.id).current_phase == 2, (
        "con los 7 aprobados el posgrado si debe auto-avanzar a fase 2"
    )


# ---------------------------------------------------------------------------
# 4 - Visor de cotejo: lista los 7 (con los faltantes marcados) y la pildora
# ---------------------------------------------------------------------------
def test_visor_de_cotejo_posgrado_lista_los_7_con_faltantes_y_trae_la_pildora(
        db_session, seed_document_types, make_program, make_cohort, make_student,
        make_process, make_document, make_head):
    from itcj2.apps.titulatec.pages.appointments import _detail_ctx

    seed_document_types(types=INITIAL_DOC_TYPES + POSGRADO_DOC_TYPES)
    pos = make_program("Maestria Visor Cotejo T4", level="maestria")
    cohort = make_cohort()
    proc = make_process(make_student(), cohort=cohort, program=pos)
    make_document(proc, type_code="birth_certificate", review_status="approved")
    # Los otros 6 se quedan SIN subir -> deben listarse igual, marcados como
    # faltantes (spec §5: "sus 4 faltantes SE MUESTRAN... pero no bloquean").

    jefa = make_head()
    detail = _detail_ctx(db_session, proc.id, user_id=jefa.id)

    assert detail is not None
    assert detail["track"] == "posgrado"
    assert len(detail["docs"]) == 7
    assert {d["type_code"] for d in detail["docs"]} == set(ALL_CODES)
    subidos = {d["type_code"] for d in detail["docs"] if d["doc"] is not None}
    assert subidos == {"birth_certificate"}
    faltantes = {d["type_code"] for d in detail["docs"] if d["doc"] is None}
    assert faltantes == set(POSGRADO_CODES) | {"high_school_cert", "curp"}


def test_visor_de_cotejo_licenciatura_no_lleva_pildora(
        db_session, seed_document_types, make_program, make_cohort, make_student,
        make_process, make_head):
    from itcj2.apps.titulatec.pages.appointments import _detail_ctx

    seed_document_types()
    lic = make_program("Ingenieria Visor Cotejo T4")
    cohort = make_cohort()
    proc = make_process(make_student(), cohort=cohort, program=lic)

    jefa = make_head()
    detail = _detail_ctx(db_session, proc.id, user_id=jefa.id)

    assert detail["track"] == "licenciatura"
    assert len(detail["docs"]) == 3


# ---------------------------------------------------------------------------
# 5 - Expediente: 7 documentos y pildora en la cabecera; licenciatura sin ella
# ---------------------------------------------------------------------------
def test_expediente_de_posgrado_trae_los_7_documentos_y_pildora_en_la_cabecera(
        db_session, seed_phase_defs, seed_document_types, make_program, make_cohort,
        make_student, make_process, make_head, client_as):
    from itcj2.apps.titulatec.pages.admin import _detail_ctx

    seed_phase_defs()
    seed_document_types(types=INITIAL_DOC_TYPES + POSGRADO_DOC_TYPES)
    pos = make_program("Maestria Expediente T4", level="maestria")
    cohort = make_cohort()
    proc = make_process(make_student(), cohort=cohort, program=pos)

    jefa = make_head()
    ctx = _detail_ctx(db_session, proc.id, user_id=jefa.id)
    assert ctx is not None
    assert ctx["track"] == "posgrado"
    assert len(ctx["docs"]) == 7
    assert {d["type_code"] for d in ctx["docs"]} == set(ALL_CODES)

    html = client_as(jefa).get("/titulatec/admin/processes/%d" % proc.id).text
    assert "tt-pill tt-pill--violet" in html
    assert "Posgrado" in html
    # Nombre de uno de los 4 extras, tal como lo siembra el catalogo de
    # prueba (`POSGRADO_DOC_TYPES`, conftest.py) -- confirma que el expediente
    # trae el CATALOGO correcto, no solo el conteo.
    assert "Oficios de autorizaci" in html


def test_expediente_de_licenciatura_no_lleva_pildora(
        db_session, seed_phase_defs, seed_document_types, make_program, make_cohort,
        make_student, make_process, make_head, client_as):
    from itcj2.apps.titulatec.pages.admin import _detail_ctx

    seed_phase_defs()
    seed_document_types()
    lic = make_program("Ingenieria Expediente T4")
    cohort = make_cohort()
    proc = make_process(make_student(), cohort=cohort, program=lic)

    jefa = make_head()
    ctx = _detail_ctx(db_session, proc.id, user_id=jefa.id)
    assert ctx["track"] == "licenciatura"
    assert len(ctx["docs"]) == 3

    html = client_as(jefa).get("/titulatec/admin/processes/%d" % proc.id).text
    assert "tt-pill--violet" not in html


def test_expediente_proceso_sin_carrera_se_comporta_como_licenciatura(
        db_session, seed_phase_defs, seed_document_types, make_cohort, make_student,
        make_process, make_head):
    """Review Focus #1: sin `program_id`, el expediente resuelve licenciatura
    (3 documentos, sin píldora), igual que la bandeja y el visor."""
    from itcj2.apps.titulatec.pages.admin import _detail_ctx

    seed_phase_defs()
    seed_document_types()
    cohort = make_cohort()
    proc = make_process(make_student(), cohort=cohort, program=None)

    jefa = make_head()
    ctx = _detail_ctx(db_session, proc.id, user_id=jefa.id)
    assert ctx["track"] == "licenciatura"
    assert len(ctx["docs"]) == 3
