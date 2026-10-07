"""Titulación aterriza en Liberados y solo ve Liberados + el expediente (D1, D2).

Spec `2026-10-07-titulatec-liberados-biblioteca-helpdesk-design.md` §1.2 y §7
(D7, D8) y plan «C — Liberados y expediente». El rol `titulatec_titulacion`
(Departamento de Titulación) queda en el DML (Tarea B) con 16 permisos: pierde
`dashboard.titulaciones`, `process.page.list`, `process.page.detail`,
`document.page.list`, `document.api.read.all`, `format_b.api.read.all` y
`ceremony.page.list`, y gana `process.page.summary` (expediente RESUMIDO).
Conserva `process.api.read.all` (alcance «ALL» de Liberados) y los permisos de
dictamen, dormidos por el corte a T-soft.

Lo que estas pruebas fijan del lado de las PÁGINAS:

* La lista `/processes` ya no se abre con el OR amplio del expediente
  (`_PROCESS_VIEW_PERMS`): su guarda es `process.page.list`, el MISMO código que
  revela la pestaña «Procesos» del menú. Antes de cambiarla se revisó quién
  entraba (DML 03 + 15 y la BD de dev, copia de prod, 2026-10-07): admin,
  school_services, school_services_head, titulaciones y titulacion — los cinco
  con `process.page.list`; nadie entraba SOLO por detail/read.all/dashboard.*,
  ni por puesto (`core_position_app_perms`) ni directo (`core_user_app_perms`).
* Las URL directas a lo que Titulación ya no ve responden 403 (Review Focus 1).
* El expediente le responde 200 en vista RESUMIDA (D7): cabecera + fases
  anteriores al corte con nombre, estado y fecha; nada del desglose. Su
  «Regresar» vuelve a Liberados y no pinta enlaces a otras pestañas.
* Las sub-rutas del expediente que su set de permisos todavía pasaría (dictamen
  de fase, Formato B, revocar) le responden 403 sin escribir nada.

El actor de Titulación usa un rol SINTÉTICO con el contrato exacto de la Tarea
B, no el nombre real: `make_role` reusa por nombre y SUMA permisos, y en la BD
de dev el rol real puede traer todavía los 22 de antes del delta.
"""
from __future__ import annotations

import os
import re
from urllib.parse import quote

import pytest

# Contrato de la Tarea B (spec §7, D8): 22 - 7 + 1 = 16, EXACTO.
TITULACION_PERMS = (
    "titulatec.process.page.summary", "titulatec.process.api.read.all",
    "titulatec.process.api.approve_phase", "titulatec.process.api.reject_phase",
    "titulatec.process.api.cancel", "titulatec.process.api.hold",
    "titulatec.document.api.approve", "titulatec.document.api.reject",
    "titulatec.format_b.api.approve", "titulatec.format_b.api.reject",
    "titulatec.ceremony.api.create", "titulatec.ceremony.api.update",
    "titulatec.notifications.api.read.own", "titulatec.notifications.api.mark_read",
    "titulatec.handoff.page.list", "titulatec.handoff.api.export",
)
ROLE_TITULACION = f"tt_test_titulacion_b_{os.getpid()}"

LIBERADOS = "/titulatec/admin/liberados"
PROCESOS = "/titulatec/admin/processes"


@pytest.fixture()
def titulacion(make_user, make_role, make_position, bind_position_role, assign_position):
    """Jefa del Departamento de Titulación sintética, por PUESTO (como en prod)."""
    def _make():
        user = make_user(first_name="JEFA", last_name="TITULACION")
        role = make_role(ROLE_TITULACION, TITULACION_PERMS)
        pos = make_position(title="Departamento de Titulacion (prueba)")
        bind_position_role(pos, role)
        assign_position(user, pos)
        return user
    return _make


@pytest.fixture()
def liberado(seed_phase_defs, seed_document_types, make_program, make_cohort,
             make_student, make_process):
    """Un egresado YA liberado (fase 2 aprobada: `current_phase=3`)."""
    def _make(control="99710001"):
        seed_phase_defs()
        seed_document_types()
        prog = make_program("Ingenieria Titulacion Liberados")
        cohort = make_cohort()
        student = make_student(control_number=control, first_name="EGRESADO",
                               last_name="LIBERADO")
        proc = make_process(student, cohort=cohort, program=prog, current_phase=3)
        return {"proc": proc, "cohort": cohort, "program": prog, "student": student}
    return _make


def test_el_contrato_de_titulacion_son_16():
    assert len(set(TITULACION_PERMS)) == 16


def _back(html: str) -> tuple[str, str]:
    import html as _html
    m = re.search(r'id="exp-back"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', html, re.S)
    assert m, "no hay botón de regresar"
    return _html.unescape(m.group(1)), re.sub(r"<[^>]+>", "", m.group(2)).strip()


# ===========================================================================
# 1. La lista de Procesos tiene guarda propia
# ===========================================================================
@pytest.mark.parametrize("solo", [
    "titulatec.process.page.detail",
    "titulatec.process.api.read.all",
    "titulatec.dashboard.admin",
    "titulatec.dashboard.school_services",
    "titulatec.dashboard.titulaciones",
])
def test_la_lista_no_se_abre_con_un_codigo_del_expediente_solo(client_as, make_head, solo):
    """`_PROCESS_VIEW_PERMS` es OR y sigue siendo la guarda del EXPEDIENTE; la
    lista ya no lo comparte: ninguno de esos códigos, solo, la abre."""
    actor = make_head(perm_codes=(solo,))

    resp = client_as(actor).get(PROCESOS)

    assert resp.status_code == 403, f"{solo} abrió la lista"


def test_la_lista_se_abre_con_process_page_list(client_as, make_head):
    """Positivo de la misma ruta: el código que revela la pestaña la abre."""
    actor = make_head(perm_codes=("titulatec.process.page.list",
                                  "titulatec.process.api.read.all"))

    resp = client_as(actor).get(PROCESOS)

    assert resp.status_code == 200, resp.text[:500]


def test_la_guarda_de_la_lista_es_el_codigo_de_la_pestana():
    """Página abierta ⇔ pestaña visible: la guarda de la lista y el ítem
    «Procesos» de `_ADMIN_NAV` usan el MISMO conjunto."""
    from itcj2.apps.titulatec.pages.admin import _PROCESS_LIST_PERMS
    from itcj2.apps.titulatec.pages.nav import _ADMIN_NAV

    (need,) = [n for label, _i, _u, n in _ADMIN_NAV if label == "Procesos"]
    assert set(_PROCESS_LIST_PERMS) == need


# ===========================================================================
# 2. Titulación: 403 en lo que perdió, 200 en Liberados y el expediente
# ===========================================================================
@pytest.mark.parametrize("url", [
    PROCESOS,
    "/titulatec/admin/",
    "/titulatec/admin/documents",
    "/titulatec/admin/appointments",
])
def test_titulacion_no_entra_por_url_directa(client_as, titulacion, url):
    resp = client_as(titulacion()).get(url)

    assert resp.status_code == 403, f"{url} -> {resp.status_code}"


def test_titulacion_no_entra_a_la_convocatoria(client_as, titulacion, liberado):
    esc = liberado()

    resp = client_as(titulacion()).get(f"/titulatec/admin/cohorts/{esc['cohort'].id}")

    assert resp.status_code == 403, resp.status_code


def test_titulacion_ve_liberados_y_solo_esa_pestana_de_trabajo(client_as, titulacion, liberado):
    esc = liberado(control="99710002")

    resp = client_as(titulacion()).get(LIBERADOS)

    assert resp.status_code == 200, resp.text[:500]
    assert "99710002" in resp.text
    menu = re.search(r'<aside[^>]*id="ttSide".*?</aside>', resp.text, re.S).group(0)
    assert f'href="{LIBERADOS}"' in menu
    for prohibida in ('href="/titulatec/admin/"', f'href="{PROCESOS}"',
                      'href="/titulatec/admin/documents"'):
        assert prohibida not in menu, f"el menú ofrece {prohibida}"


def test_titulacion_abre_el_expediente_y_regresa_a_liberados(client_as, titulacion, liberado):
    """Sin `from`: el «Regresar» por omisión NO es Procesos (le respondería 403)."""
    esc = liberado()

    resp = client_as(titulacion()).get(f"{PROCESOS}/{esc['proc'].id}")

    assert resp.status_code == 200, resp.text[:500]
    assert _back(resp.text) == (LIBERADOS, "Liberados")


def test_el_expediente_de_titulacion_no_enlaza_pestanas_prohibidas(
    client_as, titulacion, liberado,
):
    """Convocatoria (`cohort.page.list`), Citas (`appointment.page.list` ∨
    dashboards) y «Dictaminar en la bandeja» (`document.page.list` ∨
    dashboards): las tres responderían 403."""
    esc = liberado()

    html = client_as(titulacion()).get(f"{PROCESOS}/{esc['proc'].id}").text

    for prohibido in ("/titulatec/admin/cohorts/", "/titulatec/admin/appointments",
                      'href="/titulatec/admin/documents'):
        assert prohibido not in html, f"el expediente enlaza {prohibido}"
    assert "Ver la convocatoria" not in html
    assert "Gestionar la cita" not in html
    assert "Dictaminar en la bandeja" not in html


def test_desde_liberados_el_expediente_regresa_con_los_filtros(
    client_as, titulacion, liberado,
):
    """«Ver expediente» lleva `from` con la URL canónica de Liberados y sus
    filtros; el expediente la devuelve tal cual en «Regresar»."""
    import html as _html
    esc = liberado(control="99710003")
    cli = client_as(titulacion())

    lista = cli.get(LIBERADOS, params={"q": "99710003",
                                       "program_id": str(esc["program"].id)}).text
    m = re.search(r'href="(/titulatec/admin/processes/%d\?from=[^"]*)"' % esc["proc"].id,
                  lista)
    assert m, "«Ver expediente» no manda `from`"
    exp = cli.get(_html.unescape(m.group(1)))

    assert exp.status_code == 200, exp.text[:500]
    url, etiqueta = _back(exp.text)
    assert etiqueta == "Liberados"
    assert url.startswith(LIBERADOS + "?")
    assert f"program_id={esc['program'].id}" in url
    assert "q=99710003" in url


def test_un_from_malicioso_cae_a_liberados_para_titulacion(client_as, titulacion, liberado):
    esc = liberado()

    html = client_as(titulacion()).get(
        f"{PROCESOS}/{esc['proc'].id}?from={quote('https://evil.example/x', safe='')}").text

    assert _back(html) == (LIBERADOS, "Liberados")


# ===========================================================================
# 2b. Vista RESUMIDA del expediente (D7)
# ===========================================================================
def _corte():
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    return PhaseService._handoff_phase()


@pytest.fixture()
def resumen(client_as, titulacion, liberado, db_session):
    """El expediente de un liberado visto por Titulación, con perfil (correo
    personal) y la fase 2 cerrada con fecha."""
    from datetime import datetime
    from itcj2.apps.titulatec.models import ProcessPhase
    from itcj2.core.models.student_profile import StudentProfile

    esc = liberado(control="99710010")
    db_session.add(StudentProfile(user_id=esc["student"].id,
                                  contact_email="egresado.personal@example.invalid"))
    fase2 = (db_session.query(ProcessPhase)
             .filter_by(process_id=esc["proc"].id, phase_number=2).one())
    fase2.completed_at = datetime(2026, 1, 20, 9, 5)
    db_session.flush()
    resp = client_as(titulacion()).get(f"{PROCESOS}/{esc['proc'].id}")
    assert resp.status_code == 200, resp.text[:500]
    return esc, resp.text


def test_resumen_trae_la_cabecera(resumen):
    esc, html = resumen
    assert 'id="exp-resumen"' in html
    assert esc["student"].full_name in html
    assert "99710010" in html
    assert esc["program"].name in html
    assert esc["cohort"].name in html
    assert "Sin elegir" in html                     # modalidad nula
    assert "egresado.personal@example.invalid" in html
    assert esc["student"].email not in html         # el personal gana


def test_resumen_lista_solo_las_fases_previas_al_corte(resumen):
    from tests.fastapi.titulatec.conftest import PHASE_DEFS
    _esc, html = resumen
    corte = _corte()
    for numero, _code, nombre, _owner in PHASE_DEFS:
        fila = re.search(r'<tr id="exp-res-fase-%d">.*?</tr>' % numero, html, re.S)
        if numero < corte:
            assert fila, f"falta la fase {numero}"
            assert nombre in fila.group(0)
            assert "Aprobado" in fila.group(0)
        else:
            assert not fila, f"la fase {numero} (>= corte) se ve"
            assert nombre not in html, f"«{nombre}» aparece en el resumen"
    fase2 = re.search(r'<tr id="exp-res-fase-2">.*?</tr>', html, re.S).group(0)
    assert "20 ene 2026" in fase2, "la fecha de cierre de la fase no se ve"


def test_resumen_sin_desglose(resumen):
    """Sin documentos ni visor, sin historial, sin correos, sin cita, sin
    biblioteca/encuesta, sin acciones ni enlaces a otras pestañas."""
    _esc, html = resumen
    for prohibido in ('id="exp-shell"', 'id="exp-fases"', 'id="exp-correos"',
                      'id="exp-otros"', 'id="exp-doc-frame"', "Requisitos de cotejo",
                      "Acta de nacimiento", "Mover de fase", "Revocar inscripción",
                      "hx-post", "/titulatec/admin/documents", "/titulatec/admin/cohorts",
                      "/titulatec/admin/appointments", "Todavía no tiene cita"):
        assert prohibido not in html, f"el resumen trae {prohibido!r}"


def test_resumen_regresa_a_liberados(resumen):
    _esc, html = resumen
    assert _back(html) == (LIBERADOS, "Liberados")


def test_con_page_detail_la_vista_sigue_completa(client_as, make_head, liberado):
    """`process.page.detail` (o lista/dashboards) gana a `page.summary`."""
    esc = liberado()
    actor = make_head(perm_codes=("titulatec.process.page.detail",
                                  "titulatec.process.page.summary",
                                  "titulatec.process.api.read.all"))

    html = client_as(actor).get(f"{PROCESOS}/{esc['proc'].id}").text

    assert 'id="exp-shell"' in html and 'id="exp-resumen"' not in html


def test_read_all_no_da_la_vista_completa(client_as, make_head, liberado):
    esc = liberado()
    actor = make_head(perm_codes=("titulatec.process.page.summary",
                                  "titulatec.process.api.read.all"))

    html = client_as(actor).get(f"{PROCESOS}/{esc['proc'].id}").text

    assert 'id="exp-resumen"' in html and 'id="exp-shell"' not in html


def test_read_all_solo_no_abre_el_expediente(client_as, make_head, liberado):
    """`read.all` es alcance de DATOS, no una página: la guarda del expediente
    es vista completa ∪ resumen."""
    esc = liberado()
    actor = make_head(perm_codes=("titulatec.process.api.read.all",))

    resp = client_as(actor).get(f"{PROCESOS}/{esc['proc'].id}")

    assert resp.status_code == 403


def test_la_vista_completa_es_el_set_pactado():
    """D7: completa SOLO con detail, lista o un dashboard; `read.all` no."""
    from itcj2.apps.titulatec.pages.admin import (
        _PROCESS_FULL_VIEW_PERMS, _PROCESS_VIEW_PERMS,
    )

    assert set(_PROCESS_FULL_VIEW_PERMS) == {
        "titulatec.process.page.detail", "titulatec.process.page.list",
        "titulatec.dashboard.admin", "titulatec.dashboard.school_services",
        "titulatec.dashboard.titulaciones",
    }
    assert set(_PROCESS_VIEW_PERMS) == set(_PROCESS_FULL_VIEW_PERMS) | {
        "titulatec.process.page.summary"}


# ===========================================================================
# 2c. Sub-rutas del expediente: 403 para quien solo tiene el resumen
# ===========================================================================
@pytest.mark.parametrize("ruta,form", [
    ("/phase/2/approve", {}),
    ("/phase/2/reject", {"reason": "prueba"}),
    ("/format-b/review", {"action": "approve"}),
    ("/cancelar", {"reason": "prueba"}),
    ("/requisitos/1", {"action": "mark"}),
    ("/no-adeudo-previo", {"issued_on": "2026-01-01"}),
    ("/no-adeudo-previo/deshacer", {"reason": "prueba"}),
])
def test_las_acciones_del_expediente_no_le_responden(client_as, titulacion, db_session,
                                                     seed_phase_defs, seed_document_types,
                                                     make_program, make_cohort,
                                                     make_student, make_process,
                                                     ruta, form):
    """Su set conserva `approve_phase`/`reject_phase`/`format_b.*`/`cancel`
    (dictamen dormido, D1): sin vista completa, ninguna acción del expediente
    -todas devuelven el expediente ENTERO- le responde ni escribe."""
    from itcj2.apps.titulatec.models import ProcessPhase, TitulationProcess
    seed_phase_defs()
    seed_document_types()
    alumno = make_student(control_number="99710020")
    proc = make_process(alumno, cohort=make_cohort(),
                        program=make_program("Ingenieria Titulacion Acciones"),
                        current_phase=2)

    resp = client_as(titulacion()).post(f"{PROCESOS}/{proc.id}{ruta}", data=form)

    assert resp.status_code in (403, 404), f"{ruta} -> {resp.status_code}"
    db_session.expire_all()
    assert db_session.get(TitulationProcess, proc.id).status == "active"
    assert (db_session.query(ProcessPhase)
            .filter_by(process_id=proc.id, phase_number=2).one().status) == "in_progress"


@pytest.mark.parametrize("url,form", [
    ("/titulatec/admin/appointments/{pid}/fase2/aprobar", {}),
    ("/titulatec/admin/appointments/{pid}/fase2/rechazar", {"reason": "prueba"}),
    ("/titulatec/admin/documents/{pid}/document/review",
     {"type_code": "birth_certificate", "action": "approve"}),
])
def test_las_acciones_de_otras_bandejas_no_le_responden(client_as, titulacion, db_session,
                                                        seed_phase_defs, seed_document_types,
                                                        make_program, make_cohort,
                                                        make_student, make_process,
                                                        url, form):
    """Mismo hueco que las acciones del expediente, en las bandejas de Citas y
    Documentos: su guarda es solo el permiso de dictamen (`approve_phase`,
    `reject_phase`, `document.api.*`), que Titulación conserva dormido (D1), y
    responden pantallas con desglose. Sin vista completa: 403 sin escribir."""
    from itcj2.apps.titulatec.models import ProcessPhase
    seed_phase_defs()
    seed_document_types()
    alumno = make_student(control_number="99710030")
    proc = make_process(alumno, cohort=make_cohort(),
                        program=make_program("Ingenieria Titulacion Bandejas"),
                        current_phase=2)

    resp = client_as(titulacion()).post(url.format(pid=proc.id), data=form)

    assert resp.status_code == 403, f"{url} -> {resp.status_code}"
    db_session.expire_all()
    assert (db_session.query(ProcessPhase)
            .filter_by(process_id=proc.id, phase_number=2).one().status) == "in_progress"


@pytest.mark.parametrize("url", [
    "/titulatec/admin/documents/{pid}/document/birth_certificate",
    "/titulatec/admin/appointments/{pid}/document/birth_certificate",
])
def test_los_archivos_del_expediente_no_le_responden(client_as, titulacion, liberado, url):
    """El visor exige `document.api.read.all`, que Titulación ya no tiene."""
    esc = liberado()

    resp = client_as(titulacion()).get(url.format(pid=esc["proc"].id))

    assert resp.status_code in (403, 404), resp.status_code


# ===========================================================================
# 3. Vocabulario (D5) en el expediente
# ===========================================================================
def test_la_bitacora_dice_que_biblioteca_activo_el_tramite():
    from itcj2.apps.titulatec.pages.admin import _EVENT_UI

    assert _EVENT_UI["library_reenabled"][0] == "Biblioteca activó su trámite"


def test_la_constancia_previa_habla_de_la_constancia_de_no_adeudo():
    import pathlib
    import itcj2.apps.titulatec as pkg

    src = (pathlib.Path(pkg.__file__).resolve().parent / "templates" / "titulatec"
           / "partials" / "processes" / "_exp_phase.html").read_text(encoding="utf-8")
    assert "trae su Constancia de no adeudo? Queda liberada sin pasar por Caja." in src
    assert "su constancia de no adeudo?" not in src


# ===========================================================================
# 4. Revisión final: el gemelo que faltaba (Solicitudes → «Revocar inscripción»)
# ===========================================================================
def test_titulacion_no_revoca_desde_solicitudes(client_as, titulacion, db_session,
                                                seed_phase_defs, make_program,
                                                make_cohort, make_student, make_process):
    """`revocar` se guardaba solo con `process.api.cancel`, que Titulación
    conserva dormido (D8), y su alcance es ALL por `read.all`: cancelaba el
    proceso y respondía la bandeja de Solicitudes entera, que ya no puede abrir.
    Ahora exige poder abrir la bandeja: 403 y el proceso sigue vivo."""
    from itcj2.apps.titulatec.models import EnrollmentRequest, TitulationProcess
    seed_phase_defs()
    prog = make_program("Ingenieria Titulacion Solicitudes")
    cohort = make_cohort(status="open")
    proc = make_process(make_student(control_number="99710040"), cohort=cohort,
                        program=prog, current_phase=1)
    req = EnrollmentRequest(
        cohort_id=cohort.id, control_number="99710040", first_name="EGRESADA",
        last_name="INSCRITA", middle_name=None, program_id=prog.id,
        program_text="Ingenieria", phone="6561234567",
        contact_email="inscrita@example.invalid", has_efirma=False, kind="unknown",
        status="converted", verify_send_count=0, converted_process_id=proc.id)
    db_session.add(req)
    db_session.flush()

    resp = client_as(titulacion()).post(
        f"/titulatec/admin/solicitudes/{req.id}/revocar",
        data={"reason": "prueba", "status": "converted", "cohort_id": ""},
        follow_redirects=False)

    assert resp.status_code == 403, resp.status_code
    db_session.expire_all()
    assert db_session.get(TitulationProcess, proc.id).status == "active"


def test_la_bitacora_del_egresado_no_promete_revision_al_activar():
    """«Activar» con adeudo sin pagar lo manda a Caja, no a revisión: el
    historial del egresado no debe decirle que espere a que Biblioteca revise."""
    from itcj2.apps.titulatec.pages.student import _EVENT_LABELS

    texto = _EVENT_LABELS["library_reenabled"]
    assert "Biblioteca activó tu trámite" in texto
    assert "revisar" not in texto
