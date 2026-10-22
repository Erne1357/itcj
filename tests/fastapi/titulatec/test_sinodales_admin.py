"""Pestaña admin «Sinodales» (fase 4, spec §9 y §12; Task 8).

La pantalla del departamento académico: bandeja FIFO de los egresados en la
fase 4, asignar a los 4 sinodales (aprueba la fase 4 y el proceso pasa a la 5),
sustituir a uno con motivo y descargar el oficio en PDF.

- Corte a T-soft EXPLÍCITO en cada prueba: `corte(9)` opera la fase 4;
  `corte(3)` es producción y deja la pestaña sin acciones (R-G).
- El correo de los avisos a los sinodales se parchea
  (`email_helper.deliver_detailed`); los avisos abren su propia sesión, que el
  `client` ya ata a la del test.
- El oficio se prueba con `OficioService.render_pdf` parcheado (ruling R1: el
  PDF real lo cubre `test_oficio_service.py` y la verificación final).
- Cada prueba siembra sus departamentos: el jefe solo ve los suyos, así las
  listas son exactas aunque la base de dev traiga procesos reales.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote

import lxml.html
import pytest

import itcj2.apps.titulatec as _tt_pkg
from itcj2.apps.titulatec.services import email_helper
from itcj2.apps.titulatec.services.phase_service import PhaseService
from itcj2.apps.titulatec.services.synodal_service import (
    INERT_MSG, OUT_OF_SCOPE_MSG, REASON_MSG, REPEATED_MSG,
)
from tests.fastapi.titulatec.conftest import _n

APP = Path(_tt_pkg.__file__).resolve().parent
TEMPLATES = APP / "templates" / "titulatec"
PARCIALES = TEMPLATES / "partials" / "sinodales"
JS = APP / "static" / "js" / "admin" / "sinodales.js"
CSS = APP / "static" / "css" / "admin" / "sinodales.css"
BASE_ADMIN = TEMPLATES / "admin" / "base_admin.html"

URL = "/titulatec/admin/sinodales"
BODY = URL + "/body"
VINCULACION = "/titulatec/vinculacion/"

PAGE_PERM = "titulatec.synodal.page.list"
ASSIGN_PERM = "titulatec.synodal.api.assign"
REPLACE_PERM = "titulatec.synodal.api.replace"
READ_PERM = "titulatec.synodal.api.read"
READ_ALL = "titulatec.process.api.read.all"
SIN_PERMS = (PAGE_PERM, ASSIGN_PERM, REPLACE_PERM, READ_PERM)
ROLES = ("president", "secretary", "vocal", "alternate")

_RUN = os.getpid()
ROLE_DIVISION = f"tt_test_sinodales_division_{_RUN}"
ROLE_TITULACION = f"tt_test_sinodales_titulacion_{_RUN}"

PROYECTO = "Sistema de control de inventarios"
T0 = datetime(2026, 10, 1, 9, 0)
PDF_FALSO = b"%PDF-1.4 oficio de prueba"


# ---------------------------------------------------------------------------
# Dobles y escenario
# ---------------------------------------------------------------------------
@pytest.fixture()
def corte(monkeypatch):
    """Fija el corte a T-soft. `corte(9)` lo apaga; `corte(3)` es producción."""
    def _fijar(fase):
        monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: fase))
    return _fijar


@pytest.fixture(autouse=True)
def correos(monkeypatch):
    """Correo parcheado: registra cada envío y nunca sale a la red."""
    enviados = []

    def _deliver(*, template, context, subject, to, que, link=None):
        enviados.append({"template": template, "to": to, "que": que})
        return True, None

    monkeypatch.setattr(email_helper, "deliver_detailed", _deliver)
    return enviados


@pytest.fixture()
def pdf_falso(monkeypatch):
    """`OficioService.render_pdf` parcheado (ruling R1); registra los procesos."""
    from itcj2.apps.titulatec.services.oficio_service import OficioService

    llamadas = []

    def _render(db, process):
        llamadas.append(process.id)
        return PDF_FALSO

    monkeypatch.setattr(OficioService, "render_pdf", staticmethod(_render))
    return llamadas


@pytest.fixture()
def esc(db_session, corte, seed_phase_defs, make_program, make_department,
        make_program_department, make_academic_head, make_teacher, make_user,
        make_student, make_process, make_modality, make_format_b, make_cohort,
        make_synodals):
    """Departamento con su carrera, su jefe (permisos de Sinodales) y 5
    docentes con perfil completo + 1 sin cédula; otro departamento con su
    carrera y su jefe; fábrica de procesos con el Formato B aprobado."""
    def _build(cut=9):
        from itcj2.apps.titulatec.models import ProcessPhase

        corte(cut)
        seed_phase_defs()
        n = _n()
        depto = make_department(name=f"Depto UI sinodales {n}")
        otro = make_department(name=f"Otro depto UI sinodales {n}")
        programa = make_program(f"Ingenieria UI Sinodales {n}")
        ajena = make_program(f"Ingenieria UI Sinodales Ajena {n}")
        make_program_department(programa, depto, official_name="Ingeniería Oficial UI")
        make_program_department(ajena, otro)
        jefe = make_academic_head(depto, kind="head", perms=SIN_PERMS)
        jefe_otro = make_academic_head(otro, kind="head", perms=SIN_PERMS)
        docentes = [make_teacher(depto, user=make_user(first_name=f"DOCENTE{i}",
                                                       last_name=f"UI{n}"))
                    for i in range(5)]
        sin_cedula = make_teacher(depto, user=make_user(first_name="SINCEDULA",
                                                        last_name=f"UI{n}"),
                                  professional_license="   ")
        modalidad = make_modality(name=f"Tesis UI {n}")
        modalidad.option_label = "Tesis Profesional"
        db_session.flush()
        cohorte = make_cohort()

        def proceso(nombre, *, program=programa, phase=4, started=T0, synodals=False):
            alumno = make_student(first_name=nombre, last_name="PRUEBA")
            proc = make_process(alumno, cohort=cohorte, program=program, modality=modalidad,
                                current_phase=phase)
            fase4 = (db_session.query(ProcessPhase)
                     .filter_by(process_id=proc.id, phase_number=4).one())
            fase4.started_at = started
            make_format_b(proc, status="approved", modality=modalidad, submission_count=1,
                          project_name=PROYECTO, approved_at=T0 - timedelta(days=3))
            if synodals:
                make_synodals(proc, dict(zip(ROLES, docentes)), assigned_by=jefe)
            return proc

        return SimpleNamespace(depto=depto, otro=otro, programa=programa, ajena=ajena,
                               jefe=jefe, jefe_otro=jefe_otro, docentes=docentes,
                               sin_cedula=sin_cedula, modalidad=modalidad, proceso=proceso)
    return _build


@pytest.fixture()
def division(make_user, make_role, grant_user_role):
    """Jefatura de la División / admin (R-D): `read.all` + los de Sinodales."""
    def _make():
        user = make_user(first_name="DIVISION", last_name="ESTUDIOS")
        grant_user_role(user, make_role(ROLE_DIVISION, SIN_PERMS + (READ_ALL,)))
        return user
    return _make


def _html(resp):
    return lxml.html.fromstring(resp.text)


def _hdr(resp, name):
    return unquote(resp.headers.get(name, ""))


def _detalle(resp):
    nodos = _html(resp).xpath('//*[@id="tt-sin-detail"]')
    return nodos[0] if nodos else None


def _filas(resp):
    return [int(n.get("data-process"))
            for n in _html(resp).xpath('//*[@id="tt-sin-list"]//*[@data-process]')]


def _sidebar(html: str) -> list[tuple[str, str]]:
    doc = lxml.html.fromstring(html)
    return [(a.get("hx-get"), " ".join(a.text_content().split()))
            for a in doc.xpath('//aside[@id="ttSide"]//a[@hx-get]')]


def _vigentes(db, pid) -> dict:
    from itcj2.apps.titulatec.models import SynodalAssignment
    db.expire_all()
    return {r: u for r, u in db.query(SynodalAssignment.role, SynodalAssignment.user_id)
            .filter(SynodalAssignment.process_id == pid,
                    SynodalAssignment.is_active.is_(True)).all()}


def _form_asignar(docentes, **extra):
    datos = {f"{r}_id": str(d.id) for r, d in zip(ROLES, docentes)}
    datos.update({"tab": "pending", "q": "", "carrera": "", "depto": "", "page": ""})
    datos.update(extra)
    return datos


# ---------------------------------------------------------------------------
# 1. Acceso, menú y aterrizaje
# ---------------------------------------------------------------------------
def test_el_jefe_ve_la_pestana_y_su_item_del_menu(esc, client_as):
    from itcj2.apps.titulatec.pages.nav import _ADMIN_NAV

    e = esc()

    resp = client_as(e.jefe).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    assert (URL, "Sinodales") in _sidebar(resp.text)
    item = next(f for f in _ADMIN_NAV if f[0] == "Sinodales")
    assert item[1:] == ("bi-people", URL, {PAGE_PERM})
    etiquetas = [fila[0] for fila in _ADMIN_NAV]
    assert etiquetas.index("Sinodales") > etiquetas.index("Titulación")


def test_sin_el_permiso_de_la_pagina_no_entra(esc, client_as, make_app_user_without_perms):
    esc()
    ajeno = make_app_user_without_perms()

    assert client_as(ajeno).get(URL).status_code == 403
    assert client_as(ajeno).get(BODY).status_code == 403


def test_el_item_sinodales_del_menu_no_anida_el_contenedor(esc, client_as):
    from tests.fastapi.titulatec.test_admin_nav_swap import _simulate_swap, _xpath_for

    e = esc()
    cli = client_as(e.jefe)

    viva = cli.get(URL)
    assert viva.status_code == 200, viva.text[:500]
    (item,) = lxml.html.fromstring(viva.text).xpath(
        '//aside[@id="ttSide"]//a[@hx-get="%s"]' % URL)
    target, select, swap = item.get("hx-target"), item.get("hx-select"), item.get("hx-swap")

    resp = cli.get(URL, headers={"HX-Request": "true", "HX-Target": target.lstrip("#")})
    assert resp.status_code == 200
    arbol = _simulate_swap(viva.text, resp.text, target, select, swap)

    assert len(arbol.xpath(_xpath_for(target))) == 1
    assert arbol.xpath('//*[@id="tt-sin-body"]')


def test_aterrizaje_de_vinculacion_condicional_al_permiso():
    """Permiso Y fase operable (ruling R5): sin `operable` falla cerrado."""
    from itcj2.apps.titulatec.pages.nav import resolve_dashboard_url

    fase = {"synodal_assignment"}
    assert resolve_dashboard_url({"titulatec_vinculacion"}, perms={PAGE_PERM},
                                 operable=fase) == URL
    assert resolve_dashboard_url({"titulatec_vinculacion"}, perms=set(),
                                 operable=fase) == VINCULACION
    assert resolve_dashboard_url({"titulatec_vinculacion"}, perms={PAGE_PERM}) == VINCULACION
    # `perms=None` (otros llamadores): el aterrizaje de siempre.
    assert resolve_dashboard_url({"titulatec_vinculacion"}) == VINCULACION
    # Los roles que van antes no cambian aunque tengan el permiso.
    assert resolve_dashboard_url({"titulatec_titulaciones", "titulatec_vinculacion"},
                                 perms={PAGE_PERM}, operable=fase) == "/titulatec/admin/"
    assert resolve_dashboard_url({"titulatec_sinodal"}, perms={PAGE_PERM},
                                 operable=fase) == "/titulatec/sinodal/"


def _rol_vinculacion_real(db_session, make_role, *, con_permiso):
    """El rol REAL `titulatec_vinculacion` (el landing resuelve por nombre). La
    base de dev ya trae el permiso: se pone o se quita dentro del savepoint."""
    from itcj2.core.models.permission import Permission
    from itcj2.core.models.role_permission import RolePermission

    rol = make_role("titulatec_vinculacion", (PAGE_PERM,) if con_permiso else ())
    if not con_permiso:
        ids = [pid for (pid,) in db_session.query(Permission.id)
               .filter(Permission.code == PAGE_PERM).all()]
        if ids:
            db_session.query(RolePermission).filter(
                RolePermission.role_id == rol.id, RolePermission.perm_id.in_(ids),
            ).delete(synchronize_session=False)
            db_session.flush()
    return rol


@pytest.mark.parametrize("con_permiso,destino", [(True, URL), (False, VINCULACION)])
def test_el_landing_de_vinculacion_depende_del_permiso(
        con_permiso, destino, db_session, client_as, make_user, make_role, grant_user_role,
        corte, seed_phase_defs):
    # Con la fase 4 operable; con el corte en 3 lo cubre `test_nav_phase_gate.py`.
    corte(9)
    seed_phase_defs()
    rol = _rol_vinculacion_real(db_session, make_role, con_permiso=con_permiso)
    user = make_user(first_name="COORD", last_name="VINCULACION")
    grant_user_role(user, rol)

    resp = client_as(user).get("/titulatec/", follow_redirects=False)

    assert resp.status_code == 302, resp.text[:300]
    assert resp.headers["location"] == destino


# ---------------------------------------------------------------------------
# 2. Bandeja y detalle
# ---------------------------------------------------------------------------
def test_por_asignar_es_fifo_con_posicion_y_semaforo(esc, client_as):
    e = esc()
    nuevo = e.proceso("NUEVO", started=T0 + timedelta(days=2))
    viejo = e.proceso("VIEJO", started=T0)
    e.proceso("ASIGNADO", phase=5, synodals=True)

    resp = client_as(e.jefe).get(BODY, params={"tab": "pending"})

    assert resp.status_code == 200, resp.text[:500]
    assert _filas(resp) == [viejo.id, nuevo.id]
    doc = _html(resp)
    fila = doc.xpath('//*[@id="tt-sin-row-%d"]' % viejo.id)[0]
    assert " ".join(fila.text_content().split()).startswith("1 ")
    assert doc.xpath('//*[@id="tt-sin-row-%d"]//*[contains(@class,"tt-sin-wait--")]'
                     % viejo.id)
    pestana = " ".join(doc.xpath('//*[@id="tt-sin-tab-pending"]')[0].text_content().split())
    assert "(2)" in pestana
    asignados = " ".join(doc.xpath('//*[@id="tt-sin-tab-assigned"]')[0].text_content().split())
    assert "(1)" in asignados


def test_el_detalle_muestra_datos_y_selects_con_perfiles_completos(esc, client_as):
    e = esc()
    e.proceso("OCUPADO", phase=5, synodals=True)        # docentes 0-3 con 1 asignación
    p = e.proceso("ANA")

    resp = client_as(e.jefe).get(BODY, params={"tab": "pending", "selected": p.id})

    assert resp.status_code == 200, resp.text[:500]
    det = _detalle(resp)
    assert det is not None and int(det.get("data-process")) == p.id
    texto = " ".join(det.text_content().split())
    assert "ANA" in texto and p.student.control_number in texto
    assert "Tesis Profesional" in texto and PROYECTO in texto
    assert e.programa.name in texto
    sel = _html(resp).xpath('//*[@id="tt-sin-sel-president"]')[0]
    valores = [o.get("value") for o in sel.xpath(".//option") if o.get("value")]
    assert set(valores) == {str(d.id) for d in e.docentes}
    assert str(e.sin_cedula.id) not in valores
    textos = {o.get("value"): " ".join(o.text_content().split())
              for o in sel.xpath(".//option")}
    assert "1 asignación vigente" in textos[str(e.docentes[0].id)]
    assert "sin asignaciones vigentes" in textos[str(e.docentes[4].id)]
    for rol in ROLES:
        assert _html(resp).xpath('//*[@id="tt-sin-sel-%s"]' % rol)
    form = _html(resp).xpath('//form[@id="tt-sin-assign"]')[0]
    assert form.get("hx-post") == f"{URL}/{p.id}/asignar"
    assert form.get("hx-confirm") and form.get("data-tt-confirm-ok")


def test_un_docente_con_la_cuenta_desactivada_no_se_ofrece(esc, client_as, db_session):
    """Hallazgo 3: ni para asignar ni para sustituir (el servicio lo vuelve a
    exigir: `INACTIVE_TEACHER_MSG`)."""
    e = esc()
    e.docentes[4].is_active = False
    db_session.flush()
    p = e.proceso("ANA")
    asignado = e.proceso("BETO", phase=5, synodals=True)

    resp = client_as(e.jefe).get(BODY, params={"tab": "pending", "selected": p.id})
    sel = _html(resp).xpath('//*[@id="tt-sin-sel-president"]')[0]
    valores = {o.get("value") for o in sel.xpath(".//option") if o.get("value")}
    assert valores == {str(d.id) for d in e.docentes[:4]}

    resp = client_as(e.jefe).get(BODY, params={"tab": "assigned", "selected": asignado.id})
    assert not _html(resp).xpath('//*[@id="tt-sin-new-vocal"]//option[@value="%s"]'
                                 % e.docentes[4].id)


def test_la_tabla_de_vigentes_se_apila_en_tarjetas_con_etiquetas(esc, client_as):
    """Hallazgo 15 (navegador, 360 px): la tabla de los 4 recortaba Grado y
    Cédula y encimaba «Sustituir». Cada celda lleva su `data-label` y la hoja
    apila las filas como tarjetas cuando el detalle es angosto."""
    e = esc()
    p = e.proceso("ANA", phase=5, synodals=True)

    resp = client_as(e.jefe).get(BODY, params={"tab": "assigned", "selected": p.id})

    tabla = _html(resp).xpath('//table[@id="tt-sin-synodals"]')[0]
    assert "tt-sin-table--stack" in tabla.get("class")
    for fila in tabla.xpath(".//tbody/tr"):
        etiquetas = [td.get("data-label") for td in fila.xpath("./td")]
        assert etiquetas[:4] == ["Posición", "Nombre", "Grado académico", "Cédula"]
    css = re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.S)
    assert re.search(r"@container\s+tt-sin-detail\s*\(max-width:", css)
    assert "attr(data-label)" in css
    assert re.search(r"\.tt-sin-detail-col\s*\{[^}]*container:\s*tt-sin-detail", css)


def test_otro_departamento_no_ve_el_proceso_ni_su_detalle(esc, client_as):
    e = esc()
    p = e.proceso("ANA")

    resp = client_as(e.jefe_otro).get(BODY, params={"tab": "pending", "selected": p.id})

    assert resp.status_code == 200
    assert p.id not in _filas(resp)
    assert _detalle(resp) is None


def test_la_division_ve_todos_los_departamentos_con_selector(esc, client_as, division):
    e = esc()
    a = e.proceso("PROPIO")
    b = e.proceso("AJENO", program=e.ajena)
    cli = client_as(division())

    resp = cli.get(BODY, params={"tab": "pending", "depto": e.depto.id})

    assert resp.status_code == 200, resp.text[:500]
    assert _filas(resp) == [a.id]
    opciones = {o.get("value") for o in _html(resp).xpath('//*[@id="tt-sin-depto"]//option')}
    assert {str(e.depto.id), str(e.otro.id)} <= opciones
    assert _filas(cli.get(BODY, params={"tab": "pending", "depto": e.otro.id})) == [b.id]


def test_un_solo_departamento_no_pinta_el_selector(esc, client_as):
    e = esc()

    resp = client_as(e.jefe).get(BODY)

    assert resp.status_code == 200
    assert not _html(resp).xpath('//*[@id="tt-sin-depto"]')


def test_sin_departamento_a_cargo_la_pestana_lo_dice(esc, client_as, make_officer):
    e = esc()
    encargado, _pos = make_officer([e.programa], perm_codes=SIN_PERMS)

    resp = client_as(encargado).get(URL)

    assert resp.status_code == 200
    assert _html(resp).xpath('//*[@id="tt-sin-no-dept"]')


# ---------------------------------------------------------------------------
# 3. Asignar
# ---------------------------------------------------------------------------
def test_asignar_pasa_a_asignados_y_activa_la_fase_5(esc, client_as, db_session, correos):
    from itcj2.apps.titulatec.models import ProcessPhase, TitulationProcess

    e = esc()
    p = e.proceso("ANA")

    resp = client_as(e.jefe).post(f"{URL}/{p.id}/asignar", data=_form_asignar(e.docentes))

    assert resp.status_code == 200, resp.text[:500]
    assert "Sinodales registrados" in _hdr(resp, "X-Tt-Notice")
    assert resp.headers.get("X-Tt-Notice-Kind") == "success"
    assert _vigentes(db_session, p.id) == {r: d.id for r, d in zip(ROLES, e.docentes)}
    proc = db_session.get(TitulationProcess, p.id)
    assert proc.current_phase == 5
    fase5 = (db_session.query(ProcessPhase)
             .filter_by(process_id=p.id, phase_number=5).one())
    assert fase5.status == "in_progress"
    # Re-pinta «Asignados» con el proceso abierto: la tabla de los 4 y el oficio.
    det = _detalle(resp)
    assert det is not None and int(det.get("data-process")) == p.id
    doc = _html(resp)
    assert doc.xpath('//*[@id="tt-sin-tab-assigned"][@aria-current="true"]')
    assert len(doc.xpath('//*[@id="tt-sin-synodals"]//tbody/tr')) == 4
    assert doc.xpath('//a[@id="tt-sin-oficio"]')[0].get("href") == f"{URL}/{p.id}/oficio.pdf"
    assert not doc.xpath('//form[@id="tt-sin-assign"]')
    assert len(correos) == 4


def test_asignar_repetidos_da_400_y_no_escribe(esc, client_as, db_session):
    e = esc()
    p = e.proceso("ANA")
    repetidos = [e.docentes[0], e.docentes[0], e.docentes[1], e.docentes[2]]

    resp = client_as(e.jefe).post(f"{URL}/{p.id}/asignar", data=_form_asignar(repetidos))

    assert resp.status_code == 400
    assert _hdr(resp, "X-Tt-Error") == REPEATED_MSG
    assert _vigentes(db_session, p.id) == {}


def test_asignar_fuera_de_alcance_responde_404(esc, client_as, db_session):
    e = esc()
    ajeno = e.proceso("AJENO", program=e.ajena)
    propio = e.proceso("PROPIO")
    cli = client_as(e.jefe)

    assert cli.post(f"{URL}/{ajeno.id}/asignar",
                    data=_form_asignar(e.docentes)).status_code == 404
    assert _vigentes(db_session, ajeno.id) == {}
    # Regla de oro: el mismo actor sí alcanza un proceso de su departamento.
    assert cli.post(f"{URL}/{propio.id}/asignar",
                    data=_form_asignar(e.docentes)).status_code == 200


def test_asignar_sin_operar_el_departamento_da_400(esc, client_as, db_session, make_officer):
    """En alcance (puesto de Escolares con la carrera) pero sin operar el
    departamento académico: `can_operate` lo rechaza antes del servicio."""
    e = esc()
    p = e.proceso("ANA")
    encargado, _pos = make_officer([e.programa], perm_codes=SIN_PERMS)

    resp = client_as(encargado).post(f"{URL}/{p.id}/asignar", data=_form_asignar(e.docentes))

    assert resp.status_code == 400
    assert _hdr(resp, "X-Tt-Error") == OUT_OF_SCOPE_MSG
    assert _vigentes(db_session, p.id) == {}


def test_asignar_sin_poder_abrir_la_bandeja_es_403(esc, client_as, db_session,
                                                   make_user, make_role, grant_user_role):
    """El permiso de la acción solo no basta: hay que poder abrir la pestaña."""
    e = esc()
    p = e.proceso("ANA")
    solo_accion = make_user(first_name="SOLO", last_name="ACCION")
    grant_user_role(solo_accion, make_role(f"tt_test_sin_accion_{_RUN}",
                                           (ASSIGN_PERM, READ_ALL)))

    resp = client_as(solo_accion).post(f"{URL}/{p.id}/asignar",
                                       data=_form_asignar(e.docentes))

    assert resp.status_code == 403
    assert _vigentes(db_session, p.id) == {}


def test_read_all_sin_los_permisos_de_accion_no_ve_botones_y_el_post_es_403(
        esc, client_as, db_session, make_user, make_role, grant_user_role):
    """`can_operate` solo mide el ALCANCE: con `process.api.read.all` (la jefa de
    Escolares, la División) es True para cualquier departamento mapeado. Sin
    `synodal.api.assign` / `.replace` no hay «Registrar» ni «Sustituir», y la
    ruta lo rechaza en el gate (403), antes de escribir."""
    e = esc()
    p = e.proceso("ANA")
    asignado = e.proceso("OTRA", phase=5, synodals=True)
    lector = make_user(first_name="JEFA", last_name="ESCOLARES")
    grant_user_role(lector, make_role(f"tt_test_sin_lector_{_RUN}",
                                      (PAGE_PERM, READ_PERM, READ_ALL)))
    cli = client_as(lector)

    pendiente = cli.get(BODY, params={"tab": "pending", "selected": p.id,
                                      "depto": e.depto.id})
    assert pendiente.status_code == 200, pendiente.text[:500]
    assert _detalle(pendiente) is not None
    assert not _html(pendiente).xpath('//form[@id="tt-sin-assign"]')

    vista = cli.get(BODY, params={"tab": "assigned", "selected": asignado.id,
                                  "depto": e.depto.id})
    assert _detalle(vista) is not None
    assert not _html(vista).xpath('//*[@data-tt-sin-toggle]')
    assert not _html(vista).xpath('//form[starts-with(@id,"tt-sin-replace-")]')
    assert _html(vista).xpath('//a[@id="tt-sin-oficio"]')

    assert cli.post(f"{URL}/{p.id}/asignar",
                    data=_form_asignar(e.docentes)).status_code == 403
    assert cli.post(f"{URL}/{asignado.id}/sustituir", data={
        "role": "vocal", "new_user_id": str(e.docentes[4].id),
        "reason": "Motivo"}).status_code == 403
    assert _vigentes(db_session, p.id) == {}
    assert _vigentes(db_session, asignado.id)["vocal"] == e.docentes[2].id


# ---------------------------------------------------------------------------
# 4. Sustituir
# ---------------------------------------------------------------------------
def test_sustituir_sin_motivo_da_400(esc, client_as, db_session):
    e = esc()
    p = e.proceso("ANA", phase=5, synodals=True)

    resp = client_as(e.jefe).post(f"{URL}/{p.id}/sustituir", data={
        "role": "vocal", "new_user_id": str(e.docentes[4].id), "reason": "   ",
        "tab": "assigned"})

    assert resp.status_code == 400
    assert _hdr(resp, "X-Tt-Error") == REASON_MSG
    assert _vigentes(db_session, p.id)["vocal"] == e.docentes[2].id


def test_sustituir_con_motivo_cambia_al_sinodal_y_muestra_el_historial(
        esc, client_as, db_session, correos):
    e = esc()
    p = e.proceso("ANA", phase=5, synodals=True)

    resp = client_as(e.jefe).post(f"{URL}/{p.id}/sustituir", data={
        "role": "vocal", "new_user_id": str(e.docentes[4].id),
        "reason": "Licencia medica", "tab": "assigned", "q": "", "carrera": "",
        "depto": "", "page": ""})

    assert resp.status_code == 200, resp.text[:500]
    assert "Vocal" in _hdr(resp, "X-Tt-Notice")
    assert _vigentes(db_session, p.id)["vocal"] == e.docentes[4].id
    historial = _html(resp).xpath('//*[@id="tt-sin-history"]')
    assert historial and "Licencia medica" in historial[0].text_content()
    assert len(correos) == 2                            # entrante y saliente


def test_el_formulario_de_sustituir_no_ofrece_a_los_vigentes(esc, client_as):
    e = esc()
    p = e.proceso("ANA", phase=5, synodals=True)

    resp = client_as(e.jefe).get(BODY, params={"tab": "assigned", "selected": p.id})

    assert resp.status_code == 200, resp.text[:500]
    sel = _html(resp).xpath('//*[@id="tt-sin-new-vocal"]')[0]
    valores = {o.get("value") for o in sel.xpath(".//option") if o.get("value")}
    assert valores == {str(e.docentes[4].id)}
    form = _html(resp).xpath('//form[@id="tt-sin-replace-vocal"]')[0]
    assert form.get("hx-post") == f"{URL}/{p.id}/sustituir"
    assert form.get("hidden") is not None


# ---------------------------------------------------------------------------
# 5. Oficio
# ---------------------------------------------------------------------------
def test_el_oficio_sale_en_pdf_inline(esc, client_as, pdf_falso):
    e = esc()
    p = e.proceso("ANA", phase=5, synodals=True)

    resp = client_as(e.jefe).get(f"{URL}/{p.id}/oficio.pdf")

    assert resp.status_code == 200, resp.text[:300]
    assert resp.headers["content-type"].startswith("application/pdf")
    assert resp.content == PDF_FALSO
    disp = resp.headers["content-disposition"]
    assert disp.startswith("inline")
    assert f'{p.student.control_number}_OFICIO_SINODALES.pdf' in disp
    assert pdf_falso == [p.id]


def test_el_oficio_real_se_genera_con_weasyprint(esc, client_as):
    """Sin parche: `OficioService` (Task 6) arma el PDF de verdad."""
    e = esc()
    p = e.proceso("ANA", phase=5, synodals=True)

    resp = client_as(e.jefe).get(f"{URL}/{p.id}/oficio.pdf")

    assert resp.status_code == 200, resp.text[:300]
    assert resp.content.startswith(b"%PDF")
    assert resp.headers["content-disposition"].startswith("inline")


def test_el_oficio_sin_sinodales_es_404(esc, client_as, pdf_falso):
    e = esc()
    p = e.proceso("ANA")

    assert client_as(e.jefe).get(f"{URL}/{p.id}/oficio.pdf").status_code == 404
    assert pdf_falso == []


def test_el_oficio_fuera_de_alcance_es_404(esc, client_as, pdf_falso):
    e = esc()
    ajeno = e.proceso("AJENO", program=e.ajena, phase=5, synodals=True)
    propio = e.proceso("PROPIO", phase=5, synodals=True)
    cli = client_as(e.jefe)

    assert cli.get(f"{URL}/{ajeno.id}/oficio.pdf").status_code == 404
    assert cli.get(f"{URL}/{propio.id}/oficio.pdf").status_code == 200


def test_titulacion_descarga_el_oficio_solo_con_synodal_api_read(
        esc, client_as, pdf_falso, make_user, make_role, grant_user_role):
    """R-E: el Departamento de Titulación baja el oficio con `synodal.api.read`
    sin abrir la pestaña Sinodales."""
    e = esc()
    p = e.proceso("ANA", phase=5, synodals=True)
    titulacion = make_user(first_name="AUX", last_name="TITULACION")
    grant_user_role(titulacion, make_role(ROLE_TITULACION, (READ_PERM, READ_ALL)))
    cli = client_as(titulacion)

    assert cli.get(f"{URL}/{p.id}/oficio.pdf").status_code == 200
    assert cli.get(URL).status_code == 403


# ---------------------------------------------------------------------------
# 6. Corte a T-soft (R-G)
# ---------------------------------------------------------------------------
def test_con_el_corte_en_3_no_hay_acciones(esc, client_as, db_session, pdf_falso):
    e = esc(cut=3)
    p = e.proceso("ANA")
    asignado = e.proceso("OTRA", phase=5, synodals=True)
    cli = client_as(e.jefe)

    pagina = cli.get(URL, params={"selected": p.id})

    assert pagina.status_code == 200
    assert _html(pagina).xpath('//*[@id="tt-sin-handoff"]')
    assert not _html(pagina).xpath('//form[@id="tt-sin-assign"]')

    resp = cli.post(f"{URL}/{p.id}/asignar", data=_form_asignar(e.docentes))
    assert resp.status_code == 400
    assert _hdr(resp, "X-Tt-Error") == INERT_MSG
    assert _vigentes(db_session, p.id) == {}

    sust = cli.post(f"{URL}/{asignado.id}/sustituir", data={
        "role": "vocal", "new_user_id": str(e.docentes[4].id), "reason": "Motivo"})
    assert sust.status_code == 400
    assert _hdr(sust, "X-Tt-Error") == INERT_MSG
    assert cli.get(f"{URL}/{asignado.id}/oficio.pdf").status_code == 404
    assert pdf_falso == []


# ---------------------------------------------------------------------------
# 7. Estáticos y contrato del frontend
# ---------------------------------------------------------------------------
def test_base_admin_carga_el_js_y_la_hoja_una_vez(esc, client_as):
    e = esc()

    html = client_as(e.jefe).get(URL).text

    assert html.count("/static/titulatec/js/admin/sinodales.js?v=") == 1
    assert html.count("/static/titulatec/css/admin/sinodales.css?v=") == 1
    base = BASE_ADMIN.read_text(encoding="utf-8")
    assert "sv('js/admin/sinodales.js')" in base and "sv('css/admin/sinodales.css')" in base
    pagina = (TEMPLATES / "admin" / "sinodales.html").read_text(encoding="utf-8")
    assert "sinodales.js" not in pagina and "sinodales.css" not in pagina


def test_parciales_sin_script_ni_style_inline():
    plantillas = [TEMPLATES / "admin" / "sinodales.html", *sorted(PARCIALES.glob("*.html"))]
    assert len(plantillas) >= 4
    for tpl in plantillas:
        fuente = tpl.read_text(encoding="utf-8")
        assert "<script" not in fuente, tpl.name
        assert re.search(r"\sstyle=", fuente) is None, tpl.name


def test_js_morph_safe_y_sin_dialogos_nativos():
    js = JS.read_text(encoding="utf-8")

    assert js.lstrip().startswith("/*") and "(function () {" in js
    for gancho in ("htmx:afterSettle", "DOMContentLoaded", "htmx:historyRestore",
                   "window.TitulaTecSinodales"):
        assert gancho in js, gancho
    for nativo in ("confirm(", "alert(", "prompt("):
        assert not re.search(r"(?<![\w.])" + re.escape(nativo), js), nativo
    assert "innerHTML" not in js
    assert "\r\n" not in JS.read_bytes().decode("utf-8")


def test_css_comentarios_cerrados_llaves_balanceadas_y_tokens():
    css = CSS.read_text(encoding="utf-8")
    sin_comentarios = re.sub(r"/\*.*?\*/", "", css, flags=re.S)

    assert "*/" not in sin_comentarios and "/*" not in sin_comentarios
    assert sin_comentarios.count("{") == sin_comentarios.count("}")
    assert "#tt-sin-body" in css
    tamanos = re.findall(r"font-size\s*:\s*([^;}]+)", sin_comentarios)
    assert tamanos and all(t.strip().startswith("var(--tt-fs-") for t in tamanos), tamanos


# ---------------------------------------------------------------------------
# 8. Fase 5 (spec 2026-10-22 §8.3, D1): estado de la revision, nunca la conversacion
# ---------------------------------------------------------------------------
MENSAJE_SECRETO = "TEXTO-PRIVADO-SINODALES-T11"


def _con_chat(db_session, proc, docentes, *, votos=None, version=True):
    from itcj2.apps.titulatec.models import (
        ChatMessage, ProcessChat, ReviewVersion, ReviewVote, SynodalAssignment,
    )
    chat = ProcessChat(process_id=proc.id)
    db_session.add(chat)
    db_session.flush()
    if not version:
        return
    v = ReviewVersion(process_id=proc.id, number=1, file_path="/tmp/t11.pdf",
                      original_name="proyecto-t11.pdf", mime_type="application/pdf",
                      size_bytes=10, uploaded_by_id=proc.student_id)
    db_session.add(v)
    db_session.flush()
    db_session.add(ChatMessage(chat_id=chat.id, author_id=proc.student_id,
                               body=MENSAJE_SECRETO, version_id=v.id))
    for rol, veredicto in (votos or {}).items():
        asg = (db_session.query(SynodalAssignment)
               .filter_by(process_id=proc.id, role=rol, is_active=True).one())
        db_session.add(ReviewVote(version_id=v.id, assignment_id=asg.id,
                                  user_id=asg.user_id, verdict=veredicto))
    db_session.flush()


def test_proceso_en_fase_5_muestra_quien_no_ha_votado_sin_la_conversacion(
    esc, client_as, db_session,
):
    e = esc()
    e.modalidad.signature_rule = "all_synodals"
    db_session.flush()
    p = e.proceso("REVISA", phase=5, synodals=True)
    _con_chat(db_session, p, e.docentes, votos={"president": "approved"})

    resp = client_as(e.jefe).get(URL, params={"tab": "assigned", "selected": p.id})

    assert resp.status_code == 200, resp.text[:500]
    det = _detalle(resp)
    assert det is not None and det.xpath('.//*[@id="tt-rv-status"]')
    assert "Aprobó" in resp.text and "Sin votar" in resp.text
    # La sustitucion sigue ofrecida junto al estado.
    assert det.xpath('.//*[@id="tt-sin-synodals"]')
    assert MENSAJE_SECRETO not in resp.text and "proyecto-t11.pdf" not in resp.text
    assert "/titulatec/admin/revisiones" not in resp.text
    assert "/titulatec/student/revision" not in resp.text


def test_proceso_en_fase_5_sin_conversacion_dice_sin_versiones(esc, client_as):
    e = esc()
    p = e.proceso("REVISA", phase=5, synodals=True)

    resp = client_as(e.jefe).get(URL, params={"tab": "assigned", "selected": p.id})

    assert "Sin versiones todavía" in resp.text


def test_proceso_en_fase_4_no_pinta_el_estado_de_la_revision(esc, client_as):
    e = esc()
    p = e.proceso("ANA")

    resp = client_as(e.jefe).get(URL, params={"tab": "pending", "selected": p.id})

    assert 'id="tt-rv-status"' not in resp.text


def test_fase_5_con_el_corte_en_3_no_pinta_el_estado(esc, client_as, db_session):
    e = esc(cut=3)
    p = e.proceso("REVISA", phase=5, synodals=True)
    _con_chat(db_session, p, e.docentes)

    resp = client_as(e.jefe).get(URL, params={"tab": "assigned", "selected": p.id})

    assert 'id="tt-rv-status"' not in resp.text and MENSAJE_SECRETO not in resp.text
