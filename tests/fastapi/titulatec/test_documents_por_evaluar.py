"""Bandeja de Documentos: «por evaluar» = archivo SUBIDO esperando dictamen (2026-10-09).

Antes, `_doc_states` contaba igual un documento `pending` (subido, espera al
revisor) que uno `missing` (el alumno no lo ha subido: espera al ALUMNO). De ahí
salían tres síntomas que se vieron con datos de producción (alumno 21111134:
CURP aprobada, certificado rechazado y SIN acta):

  * la fila decía «1» y caía en «Por evaluar», pero al abrirla no había ningún
    archivo pendiente (el faltante no se pinta);
  * el contador «N por evaluar» sumaba los faltantes (147 contra 134 reales);
  * una fila con 1 archivo pendiente y 2 sin subir decía «3».

Ahora `pending` cuenta solo lo subido sin dictaminar y `missing` cuenta lo que
falta subir; el detalle pinta los faltantes como «Sin enviar».
"""
from __future__ import annotations

import pytest

CODIGOS = ["birth_certificate", "high_school_cert", "curp"]


@pytest.fixture()
def alumno(seed_document_types, make_program, make_cohort, make_student,
           make_process, make_document):
    """Proceso con un estado por código; un código ausente queda sin subir."""
    seed_document_types()
    programa = make_program("Ingenieria Ficticia Por Evaluar")
    cohorte = make_cohort()

    def _nuevo(**estados):
        proc = make_process(make_student(), cohort=cohorte, program=programa)
        for code, estado in estados.items():
            make_document(proc, type_code=code, review_status=estado)
        return proc

    return _nuevo


def _ctx(db_session, jefa, status_filter, selected=None):
    from itcj2.apps.titulatec.pages.documents import _body_ctx
    return _body_ctx(db_session, user_id=jefa.id, status_filter=status_filter,
                     selected_id=selected, per_page=10000)


def _ids(ctx, *procs):
    mios = {p.id for p in procs}
    return [r["process_id"] for r in ctx["page"].items if r["process_id"] in mios]


def test_el_caso_21111134_no_cuenta_nada_por_evaluar(db_session, alumno):
    """Aprobado + rechazado + sin subir: nada espera al revisor."""
    from itcj2.apps.titulatec.pages.documents import _doc_states

    proc = alumno(curp="approved", high_school_cert="rejected")
    (fila,) = _doc_states(db_session, [proc])

    assert fila["pending"] == 0
    assert fila["missing"] == 1
    assert fila["all_approved"] is False


def test_un_pendiente_y_dos_sin_subir_dice_uno_por_evaluar(db_session, alumno):
    from itcj2.apps.titulatec.pages.documents import _doc_states

    proc = alumno(birth_certificate="pending")
    (fila,) = _doc_states(db_session, [proc])

    assert fila["pending"] == 1
    assert fila["missing"] == 2


def test_sin_nada_que_evaluar_no_sale_en_por_evaluar_pero_si_en_todos(
        db_session, alumno, make_head):
    solo_faltantes = alumno(curp="approved", high_school_cert="rejected")
    con_pendiente = alumno(curp="pending")
    jefa = make_head()

    assert _ids(_ctx(db_session, jefa, "pending"), solo_faltantes, con_pendiente) == [
        con_pendiente.id]
    assert set(_ids(_ctx(db_session, jefa, ""), solo_faltantes, con_pendiente)) == {
        solo_faltantes.id, con_pendiente.id}


def test_el_contador_solo_suma_archivos_subidos(db_session, alumno, make_head):
    """`total_pending` es el universo filtrado: se mide la DIFERENCIA que aportan
    los procesos del test (la base de dev ya trae los suyos)."""
    jefa = make_head()
    antes = _ctx(db_session, jefa, "pending")["total_pending"]

    alumno(birth_certificate="pending")                      # 1 por evaluar + 2 sin subir
    alumno(curp="approved", high_school_cert="rejected")     # 0 por evaluar + 1 sin subir
    alumno(curp="pending", high_school_cert="pending",
           birth_certificate="pending")                      # 3 por evaluar

    assert _ctx(db_session, jefa, "pending")["total_pending"] - antes == 4


def test_el_detalle_pinta_el_faltante_como_sin_enviar(client_as, make_head, alumno):
    proc = alumno(curp="approved", high_school_cert="rejected")

    html = client_as(make_head()).get(
        "/titulatec/admin/documents/body?status=&selected=%d" % proc.id).text

    assert "Sin enviar" in html
    assert "Acta de nacimiento" in html


def test_estado_pill_de_un_faltante_dice_sin_enviar():
    from itcj2.apps.titulatec.pages.nav import titulatec_templates

    macros = titulatec_templates.env.get_template("titulatec/_macros.html").module
    assert "Sin enviar" in str(macros.estado_pill("missing"))
