"""Pestaña admin «Titulación» (spec 2026-10-21 fase 3 §8, Task 6).

La pantalla de trabajo del Departamento de Titulación: bandeja FIFO del
Formato B (master-detail), observaciones por campo, aprobar, corregir el
registro (nombre y carrera), visor de los documentos de la fase 1 y «quién lo
está revisando».

- Corte a T-soft EXPLÍCITO en cada prueba (Ruling R7): `corte(9)` opera la
  fase 3; `corte(3)` es producción y debe dejar la pestaña sin acciones.
- La presencia vive en Redis; aquí se reemplaza por un doble en memoria
  (fakeredis no está instalado) que respeta la firma de `ReviewPresence`.
- El revisor de los flujos está ACOTADO por puesto a la carrera de prueba (sin
  `process.api.read.all`): así la cola FIFO solo ve lo que siembra cada prueba
  y no los Formatos B reales de la base de dev. La prueba del menú usa el
  alcance «ALL» del rol real.
"""
from __future__ import annotations

import os
import re
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote

import lxml.html
import pytest

import itcj2.apps.titulatec as _tt_pkg
from itcj2.apps.titulatec.services.phase_service import PhaseService
from itcj2.apps.titulatec.services.review_presence import ReviewPresence
from itcj2.core.utils.timezone import db_now
from tests.fastapi.titulatec.conftest import OFFICER_PERMS

APP = Path(_tt_pkg.__file__).resolve().parent
TEMPLATES = APP / "templates" / "titulatec"
PARCIALES = TEMPLATES / "partials" / "titulacion"
JS = APP / "static" / "js" / "admin" / "titulacion.js"
CSS = APP / "static" / "css" / "admin" / "titulacion.css"
BASE_ADMIN = TEMPLATES / "admin" / "base_admin.html"

URL = "/titulatec/admin/titulacion"
BODY = URL + "/body"
LIBERADOS = "/titulatec/admin/liberados"

PAGE_PERM = "titulatec.titulacion.page.list"
READ_PERM = "titulatec.format_b.api.read.all"
CORRECT_PERM = "titulatec.format_b.api.correct_registry"
FASE2_PERMS = (PAGE_PERM, READ_PERM, CORRECT_PERM)
DEPTO_PERMS = FASE2_PERMS + ("titulatec.format_b.api.approve", "titulatec.format_b.api.reject")

# Roles FICTICIOS con sufijo por proceso (mismo motivo que en conftest.py).
_RUN = os.getpid()
ROLE_DEPTO = f"tt_test_titulacion_{_RUN}"
ROLE_DEPTO_ALL = f"tt_test_titulacion_all_{_RUN}"
ROLE_LECTOR = f"tt_test_titulacion_lector_{_RUN}"

_CAMPOS = dict(
    gender="female", age=24, mobile_phone="6561234567", postal_code="32000",
    neighborhood="Centro", street="Av. Juarez", ext_number="123",
    study_plan="ISIC-2010-224", admission_date=date(2018, 8, 1),
    graduation_date=date(2023, 6, 1), project_name="Sistema de inventarios",
)


# ---------------------------------------------------------------------------
# Dobles y escenario
# ---------------------------------------------------------------------------
class _Presencia:
    """Doble de `ReviewPresence` en memoria: `{(kind, pid): {uid: nombre}}`."""

    def __init__(self):
        self.marcas: dict[tuple[str, int], dict[int, str]] = {}
        self.borradas: list[tuple[str, int, int]] = []

    def touch(self, kind, process_id, user_id, name):
        self.marcas.setdefault((kind, int(process_id)), {})[int(user_id)] = name

    def clear(self, kind, process_id, user_id):
        self.borradas.append((kind, int(process_id), int(user_id)))
        self.marcas.get((kind, int(process_id)), {}).pop(int(user_id), None)

    def viewers(self, kind, process_ids, exclude_user_id):
        out = {}
        for pid in process_ids:
            otros = [n for uid, n in self.marcas.get((kind, int(pid)), {}).items()
                     if uid != int(exclude_user_id)]
            if otros:
                out[int(pid)] = sorted(otros)
        return out


@pytest.fixture(autouse=True)
def presencia(monkeypatch):
    doble = _Presencia()
    monkeypatch.setattr(ReviewPresence, "touch", staticmethod(doble.touch))
    monkeypatch.setattr(ReviewPresence, "clear", staticmethod(doble.clear))
    monkeypatch.setattr(ReviewPresence, "viewers", staticmethod(doble.viewers))
    return doble


@pytest.fixture()
def corte(monkeypatch):
    """Fija el corte a T-soft (R7). `corte(9)` lo apaga; `corte(3)` es prod."""
    def _fijar(fase):
        monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: fase))
    return _fijar


@pytest.fixture()
def esc(db_session, corte, seed_phase_defs, seed_document_types, make_program,
        make_modality, make_cohort, make_student, make_process, make_format_b,
        make_user, make_role, make_position, bind_position_role, link_programs,
        assign_position):
    """Carrera de prueba, modalidad con sinodales, revisores acotados por puesto
    y una fábrica de Formatos B enviados (`dias` = antigüedad del envío)."""
    def _build(cut=9):
        corte(cut)
        seed_phase_defs()
        seed_document_types()
        programa = make_program("Ingenieria Ficticia Titulacion T6")
        hermana = make_program("Ingenieria Ficticia Titulacion T6 B")
        posgrado = make_program("Maestria Ficticia Titulacion T6", level="maestria")
        residencias = make_modality(name="Residencias de prueba T6", requires_synodals=True)
        cohorte = make_cohort()
        rol = make_role(ROLE_DEPTO, DEPTO_PERMS)

        def revisor(nombre, programas=None):
            user = make_user(first_name=nombre, last_name="TITULACION")
            pos = make_position(title="Titulacion de prueba")
            bind_position_role(pos, rol)
            link_programs(pos, programas or [programa])
            assign_position(user, pos)
            return user

        def enviado(nombre, *, dias=1, ronda=1, status="submitted", programa_=None,
                    phase=3, sin_modalidad=False, **campos):
            alumno = make_student(first_name=nombre, last_name="PRUEBA")
            prog = programa_ or programa
            proc = make_process(alumno, cohort=cohorte, program=prog, current_phase=phase)
            datos = dict(_CAMPOS)
            datos.update(campos)
            make_format_b(
                proc, status=status, submission_count=ronda,
                modality=None if sin_modalidad else residencias,
                submitted_at=(db_now() - timedelta(days=dias)) if status != "draft" else None,
                first_name=nombre, last_name="PRUEBA",
                control_number=alumno.control_number, program_id=prog.id,
                titulation_type=residencias.name, **datos)
            return proc

        return SimpleNamespace(programa=programa, hermana=hermana, posgrado=posgrado,
                               residencias=residencias, cohorte=cohorte,
                               revisor=revisor, enviado=enviado)
    return _build


def _fb(db, pid):
    from itcj2.apps.titulatec.models import FormatB
    db.expire_all()
    return db.get(FormatB, pid)


def _html(resp):
    return lxml.html.fromstring(resp.text)


def _detalle(resp):
    nodos = _html(resp).xpath('//*[@id="tt-tit-detail"]')
    return nodos[0] if nodos else None


def _hdr(resp, name):
    return unquote(resp.headers.get(name, ""))


def _sidebar(html: str) -> list[tuple[str, str]]:
    doc = lxml.html.fromstring(html)
    return [(a.get("hx-get"), " ".join(a.text_content().split()))
            for a in doc.xpath('//aside[@id="ttSide"]//a[@hx-get]')]


# ---------------------------------------------------------------------------
# 1. Acceso, menú y aterrizaje
# ---------------------------------------------------------------------------
def test_el_depto_ve_la_pestana_y_su_item_del_menu(esc, client_as, make_user, make_role,
                                                   grant_user_role):
    """Con el alcance ALL del rol real (`process.api.read.all`): 200 y el ítem
    «Titulación» justo después de «Citas de cotejo»."""
    from itcj2.apps.titulatec.pages.nav import _ADMIN_NAV

    esc()
    depto = make_user(first_name="JEFA", last_name="TITULACION")
    grant_user_role(depto, make_role(ROLE_DEPTO_ALL,
                                     DEPTO_PERMS + ("titulatec.process.api.read.all",)))

    resp = client_as(depto).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    assert (URL, "Titulación") in _sidebar(resp.text)
    etiquetas = [fila[0] for fila in _ADMIN_NAV]
    assert etiquetas.index("Titulación") == etiquetas.index("Citas de cotejo") + 1
    item = next(f for f in _ADMIN_NAV if f[0] == "Titulación")
    assert item[1:] == ("bi-journal-check", URL, {PAGE_PERM})


def test_un_encargado_de_escolares_no_entra(esc, client_as, make_officer):
    e = esc()
    depto = e.revisor("LUISA")
    encargado, _pos = make_officer([e.programa], perm_codes=OFFICER_PERMS)

    assert client_as(depto).get(URL).status_code == 200
    assert client_as(encargado).get(URL).status_code == 403
    assert client_as(encargado).get(BODY).status_code == 403


def test_sin_lectura_del_formato_b_la_pagina_avisa_y_el_parcial_es_403(
        esc, client_as, make_user, make_role, grant_user_role):
    """`GET ""` solo exige la página (spec §8.4); el parcial exige además
    `format_b.api.read.all`."""
    esc()
    lector = make_user(first_name="SOLO", last_name="PAGINA")
    grant_user_role(lector, make_role(ROLE_LECTOR, (PAGE_PERM,)))
    cli = client_as(lector)

    pagina = cli.get(URL)

    assert pagina.status_code == 200, pagina.text[:300]
    assert _html(pagina).xpath('//*[@id="tt-tit-no-read"]')
    assert not _html(pagina).xpath('//*[@id="tt-tit-filters"]')
    assert cli.get(BODY).status_code == 403


def test_el_item_titulacion_del_menu_no_anida_el_contenedor(
        esc, client_as, make_user, make_role, grant_user_role):
    from tests.fastapi.titulatec.test_admin_nav_swap import _simulate_swap, _xpath_for

    esc()
    depto = make_user(first_name="JEFA", last_name="TITULACION")
    grant_user_role(depto, make_role(ROLE_DEPTO_ALL,
                                     DEPTO_PERMS + ("titulatec.process.api.read.all",)))
    cli = client_as(depto)

    viva = cli.get(URL)
    assert viva.status_code == 200, viva.text[:500]
    (item,) = lxml.html.fromstring(viva.text).xpath(
        '//aside[@id="ttSide"]//a[@hx-get="%s"]' % URL)
    target, select, swap = item.get("hx-target"), item.get("hx-select"), item.get("hx-swap")

    resp = cli.get(URL, headers={"HX-Request": "true", "HX-Target": target.lstrip("#")})
    assert resp.status_code == 200
    arbol = _simulate_swap(viva.text, resp.text, target, select, swap)

    iguales = arbol.xpath(_xpath_for(target))
    assert len(iguales) == 1, "tras el swap hay %d %s" % (len(iguales), target)
    assert arbol.xpath('//*[@id="tt-tit-body"]')


def test_aterrizaje_de_titulacion_condicional_al_permiso():
    from itcj2.apps.titulatec.pages.nav import resolve_dashboard_url

    assert resolve_dashboard_url({"titulatec_titulacion"}, perms={PAGE_PERM}) == URL
    assert resolve_dashboard_url({"titulatec_titulacion"}, perms=set()) == LIBERADOS
    # R5: sin `perms` (otros llamadores) conserva Liberados.
    assert resolve_dashboard_url({"titulatec_titulacion"}) == LIBERADOS
    # La División y admin siguen en la Bandeja aunque tengan el permiso.
    assert resolve_dashboard_url({"titulatec_titulaciones"}, perms={PAGE_PERM}) == "/titulatec/admin/"
    assert resolve_dashboard_url({"titulatec_titulaciones", "titulatec_titulacion"},
                                 perms={PAGE_PERM}) == "/titulatec/admin/"
    assert resolve_dashboard_url({"admin"}, perms={PAGE_PERM}) == "/titulatec/admin/"


def _rol_titulacion_real(db_session, make_role, *, con_permiso):
    """El rol REAL `titulatec_titulacion` (el landing resuelve por nombre). La base
    de dev ya puede traer el permiso (`init-titulatec-fase-2`): se pone o se
    quita dentro del savepoint de la prueba."""
    from itcj2.core.models.permission import Permission
    from itcj2.core.models.role_permission import RolePermission

    rol = make_role("titulatec_titulacion", (PAGE_PERM,) if con_permiso else ())
    if not con_permiso:
        ids = [pid for (pid,) in db_session.query(Permission.id)
               .filter(Permission.code == PAGE_PERM).all()]
        if ids:
            db_session.query(RolePermission).filter(
                RolePermission.role_id == rol.id, RolePermission.perm_id.in_(ids),
            ).delete(synchronize_session=False)
            db_session.flush()
    return rol


@pytest.mark.parametrize("con_permiso,destino", [(True, URL), (False, LIBERADOS)])
def test_el_landing_de_titulacion_depende_del_permiso(
        con_permiso, destino, db_session, client_as, make_user, make_role, grant_user_role):
    rol = _rol_titulacion_real(db_session, make_role, con_permiso=con_permiso)
    user = make_user(first_name="AUX", last_name="TITULACION")
    grant_user_role(user, rol)

    resp = client_as(user).get("/titulatec/", follow_redirects=False)

    assert resp.status_code == 302, resp.text[:300]
    assert resp.headers["location"] == destino


# ---------------------------------------------------------------------------
# 2. La bandeja y el detalle
# ---------------------------------------------------------------------------
def test_por_revisar_es_fifo_con_posicion_espera_y_reenvio(esc, client_as):
    e = esc()
    a = e.revisor("LUISA")
    viejo = e.enviado("UNO", dias=6)
    medio = e.enviado("DOS", dias=3, ronda=2)
    nuevo = e.enviado("TRES", dias=0)
    e.enviado("BORRADOR", status="draft")

    resp = client_as(a).get(BODY, params={"tab": "pending"})

    assert resp.status_code == 200, resp.text[:500]
    doc = _html(resp)
    ids = [int(n.get("data-process"))
           for n in doc.xpath('//*[@id="tt-tit-list"]//*[@data-process]')]
    assert ids == [viejo.id, medio.id, nuevo.id]
    fila = doc.xpath('//*[@id="tt-tit-row-%d"]' % medio.id)[0]
    texto = " ".join(fila.text_content().split())
    assert texto.startswith("2 ")
    assert "Reenvío (ronda 2)" in texto
    # Semáforo de espera en días hábiles: el de 6 días naturales es ámbar o rojo.
    assert doc.xpath('//*[@id="tt-tit-row-%d"]//*[contains(@class,"tt-tit-wait--")]' % viejo.id)
    # Contador de la pestaña sobre el conjunto filtrado.
    assert "(3)" in " ".join(doc.xpath('//*[@id="tt-tit-tab-pending"]')[0].text_content().split())
    # Sin selección: detalle vacío.
    assert _detalle(resp) is None


def test_el_detalle_muestra_todos_los_campos_y_marca_el_registro(esc, client_as,
                                                                 make_document):
    e = esc()
    a = e.revisor("LUISA")
    p = e.enviado("ANA", dias=1)
    make_document(p, type_code="birth_certificate")
    make_document(p, type_code="curp")

    resp = client_as(a).get(BODY, params={"tab": "pending", "selected": p.id})

    det = _detalle(resp)
    assert det is not None and int(det.get("data-process")) == p.id
    texto = " ".join(det.text_content().split())
    for valor in ("32000", "Centro", "Av. Juarez", "Mujer", "Residencias de prueba T6",
                  "Sistema de inventarios", "Ingenieria Ficticia Titulacion T6"):
        assert valor in texto, valor
    # Registro: etiqueta «del registro», sin bandera; los editables sí la llevan.
    registro = det.xpath('.//*[@data-field][@data-registry="1"]')
    assert {n.get("data-field") for n in registro} == {
        "first_name", "last_name", "middle_name", "control_number", "program_id"}
    for n in registro:
        assert "del registro" in n.text_content()
        assert not n.xpath('.//*[contains(@class,"tt-tit-flag")]')
    banderas = det.xpath('.//button[contains(@class,"tt-tit-flag")]')
    assert {b.get("data-field") for b in banderas} >= {"postal_code", "street", "modality_id"}
    assert det.xpath('.//textarea[@name="note__postal_code"]')
    # Lápiz «Corregir» (permiso correct_registry) y el form inline del registro.
    assert det.xpath('.//*[@data-tt-tit-toggle="tt-tit-registro"]')
    assert det.xpath('.//form[@id="tt-tit-registro"]//textarea[@name="reason"]')
    # Documentos de la fase 1 con el visor existente (TitulaTecDocViewer).
    picks = det.xpath('.//*[@id="tt-doc-review"]//button[contains(@class,"tt-docpick")]')
    urls = {b.get("data-url") for b in picks}
    assert f"{URL}/formato-b/{p.id}/documento/birth_certificate" in urls
    assert f"{URL}/formato-b/{p.id}/documento/curp" in urls
    # Acciones y latido de presencia.
    assert det.xpath('.//*[@id="tt-tit-approve"]') and det.xpath('.//*[@id="tt-tit-observe"]')
    (latido,) = det.xpath('.//*[@id="tt-tit-beat"]')
    assert latido.get("hx-post") == f"{URL}/formato-b/{p.id}/viendo"
    assert latido.get("hx-trigger") == "every 60s"


def test_en_la_ronda_2_se_ve_la_observacion_anterior_y_el_antes_ahora(esc, client_as):
    e = esc()
    a = e.revisor("LUISA")
    p = e.enviado("ANA", dias=1, ronda=2, review_observations={
        "general": "Revisa tu domicilio.",
        "fields": {"postal_code": {"note": "El C.P. no existe", "value": "3200"},
                   "street": {"note": "Falta la calle", "value": "Av. Juarez"}},
        "reviewer_id": a.id, "at": "2026-10-20T10:00:00"})

    det = _detalle(client_as(a).get(BODY, params={"selected": p.id}))

    cp = det.xpath('.//*[@data-field="postal_code"]')[0]
    texto_cp = " ".join(cp.text_content().split())
    assert "El C.P. no existe" in texto_cp
    assert "3200" in texto_cp and "32000" in texto_cp
    calle = " ".join(det.xpath('.//*[@data-field="street"]')[0].text_content().split())
    assert "Falta la calle" in calle and "Sin cambio" in calle
    assert "Revisa tu domicilio." in " ".join(det.text_content().split())


def test_selected_sin_pestana_abre_la_pestana_de_su_estado(esc, client_as):
    """La liga «Abrir en Titulación» del expediente manda solo `?selected=`."""
    e = esc()
    a = e.revisor("LUISA")
    aprobado = e.enviado("ANA", status="approved", phase=4)

    resp = client_as(a).get(URL, params={"selected": aprobado.id})

    assert resp.status_code == 200
    det = _detalle(resp)
    assert det is not None and int(det.get("data-process")) == aprobado.id
    assert _html(resp).xpath('//*[@id="tt-tit-tab-approved"][@aria-current="true"]')
    # Aprobado: solo lectura.
    assert not det.xpath('.//*[@id="tt-tit-approve"]')
    assert not det.xpath('.//*[@id="tt-tit-beat"]')


def test_selected_de_otra_carrera_no_filtra_el_detalle(esc, client_as):
    e = esc()
    a = e.revisor("LUISA")
    ajeno = e.enviado("AJENO", programa_=e.hermana)

    resp = client_as(a).get(BODY, params={"tab": "pending", "selected": ajeno.id})

    assert resp.status_code == 200
    assert _detalle(resp) is None
    assert "AJENO" not in resp.text


# ---------------------------------------------------------------------------
# 3. Dictamen
# ---------------------------------------------------------------------------
def test_observar_con_dos_notas_regresa_al_alumno_y_pinta_el_siguiente(
        esc, client_as, db_session, presencia):
    e = esc()
    a = e.revisor("LUISA")
    p1 = e.enviado("UNO", dias=5)
    p2 = e.enviado("DOS", dias=3)

    resp = client_as(a).post(f"{URL}/formato-b/{p1.id}/observar", data={
        "general_note": "", "note__postal_code": "El C.P. no corresponde",
        "note__street": "Falta el número exterior", "note__neighborhood": "",
        "tab": "pending", "page": "1", "q": "", "carrera": ""})

    assert resp.status_code == 200, resp.text[:500]
    fb = _fb(db_session, p1.id)
    assert fb.status == "rejected"
    assert set(fb.review_observations["fields"]) == {"postal_code", "street"}
    det = _detalle(resp)
    assert det is not None and int(det.get("data-process")) == p2.id
    assert _hdr(resp, "X-Tt-Notice") and resp.headers.get("X-Tt-Notice-Kind") == "success"
    assert ("format_b", p1.id, a.id) in presencia.borradas


def test_el_siguiente_salta_el_que_otro_tiene_abierto(esc, client_as, presencia):
    e = esc()
    a = e.revisor("LUISA")
    b = e.revisor("BETO")
    p1 = e.enviado("UNO", dias=5)
    p2 = e.enviado("DOS", dias=3)
    p3 = e.enviado("TRES", dias=1)
    presencia.touch("format_b", p2.id, b.id, "BETO TITULACION")

    resp = client_as(a).post(f"{URL}/formato-b/{p1.id}/aprobar", data={"tab": "pending"})

    assert resp.status_code == 200, resp.text[:500]
    assert int(_detalle(resp).get("data-process")) == p3.id


def test_aprobar_avanza_a_la_fase_4_y_aprobar_de_nuevo_da_400(esc, client_as, db_session):
    e = esc()
    a = e.revisor("LUISA")
    p = e.enviado("ANA", dias=2)
    cli = client_as(a)

    resp = cli.post(f"{URL}/formato-b/{p.id}/aprobar", data={"tab": "pending"})

    assert resp.status_code == 200, resp.text[:500]
    assert _fb(db_session, p.id).status == "approved"
    db_session.refresh(p)
    assert p.current_phase == 4
    assert "04" in _hdr(resp, "X-Tt-Notice")
    # Sin más pendientes: detalle vacío.
    assert _detalle(resp) is None

    otra = cli.post(f"{URL}/formato-b/{p.id}/aprobar", data={"tab": "pending"})

    assert otra.status_code == 400
    assert "ya fue dictaminado" in _hdr(otra, "X-Tt-Error")


def test_sin_tipo_de_titulacion_no_se_ofrece_aprobar(esc, client_as, db_session):
    """Un Formato B sin modalidad (enviado antes de la columna) solo se observa:
    sin «Aprobar» y con el aviso del service; forzarlo da 400."""
    from itcj2.apps.titulatec.services.format_b_service import NO_MODALITY_MSG

    e = esc()
    a = e.revisor("LUISA")
    p = e.enviado("ANA", sin_modalidad=True)
    cli = client_as(a)

    det = _detalle(cli.get(BODY, params={"selected": p.id}))

    assert not det.xpath('.//*[@id="tt-tit-approve"]')
    assert det.xpath('.//*[@id="tt-tit-observe"]')
    assert NO_MODALITY_MSG in " ".join(det.text_content().split())
    forzado = cli.post(f"{URL}/formato-b/{p.id}/aprobar", data={"tab": "pending"})
    assert forzado.status_code == 400
    assert _hdr(forzado, "X-Tt-Error") == NO_MODALITY_MSG
    assert _fb(db_session, p.id).status == "submitted"


def test_observar_sin_ninguna_nota_da_400_y_no_escribe(esc, client_as, db_session):
    e = esc()
    a = e.revisor("LUISA")
    p = e.enviado("ANA")

    resp = client_as(a).post(f"{URL}/formato-b/{p.id}/observar",
                             data={"general_note": " ", "note__street": ""})

    assert resp.status_code == 400
    assert "al menos una observación" in _hdr(resp, "X-Tt-Error")
    assert _fb(db_session, p.id).status == "submitted"


def test_registro_sin_motivo_da_400_y_con_motivo_corrige(esc, client_as, db_session):
    from itcj2.apps.titulatec.models import TitulationProcess
    from itcj2.core.models.user import User

    e = esc()
    a = e.revisor("LUISA", programas=[e.programa, e.hermana])
    p = e.enviado("ANA")
    cli = client_as(a)
    datos = {"first_name": "ANA MARIA", "last_name": "PRUEBA", "middle_name": "LOPEZ",
             "program_id": str(e.hermana.id), "tab": "pending"}

    sin = cli.post(f"{URL}/formato-b/{p.id}/registro", data={**datos, "reason": ""})

    assert sin.status_code == 400
    assert "motivo" in _hdr(sin, "X-Tt-Error")

    con = cli.post(f"{URL}/formato-b/{p.id}/registro",
                   data={**datos, "reason": "El acta dice ANA MARIA"})

    assert con.status_code == 200, con.text[:500]
    assert _hdr(con, "X-Tt-Notice")
    db_session.expire_all()
    proc = db_session.get(TitulationProcess, p.id)
    alumno = db_session.get(User, proc.student_id)
    assert (alumno.first_name, alumno.middle_name) == ("ANA MARIA", "LOPEZ")
    assert proc.program_id == e.hermana.id
    fb = _fb(db_session, p.id)
    assert fb.status == "submitted" and fb.first_name == "ANA MARIA"


def test_el_select_de_carreras_del_registro_solo_ofrece_el_mismo_nivel(esc, client_as):
    e = esc()
    a = e.revisor("LUISA")
    p = e.enviado("ANA")

    det = _detalle(client_as(a).get(BODY, params={"selected": p.id}))

    opciones = {o.get("value") for o in
                det.xpath('.//form[@id="tt-tit-registro"]//select[@name="program_id"]/option')}
    assert str(e.programa.id) in opciones and str(e.hermana.id) in opciones
    assert str(e.posgrado.id) not in opciones


def test_programs_same_level_vive_en_track_service(esc, db_session):
    """El nivel solo lo lee `TrackService` (invariante 2 del posgrado)."""
    from itcj2.apps.titulatec.services.track_service import TrackService

    e = esc()

    mismas = {p.id for p in TrackService.programs_same_level(db_session, e.programa.id)}
    posgrado = {p.id for p in TrackService.programs_same_level(db_session, e.posgrado.id)}

    assert {e.programa.id, e.hermana.id} <= mismas and e.posgrado.id not in mismas
    assert e.posgrado.id in posgrado and e.programa.id not in posgrado
    assert TrackService.programs_same_level(db_session, None) == []


# ---------------------------------------------------------------------------
# 4. Documentos de la fase 1
# ---------------------------------------------------------------------------
def test_el_documento_solo_sirve_tipos_de_la_fase_1(esc, client_as, make_document,
                                                     seed_document_types, tmp_path,
                                                     monkeypatch):
    monkeypatch.setattr("itcj2.apps.titulatec.utils.storage._base", lambda: tmp_path)
    e = esc()
    seed_document_types(types=(("tt_test_anexo_t6", "Anexo III de prueba", 6),))
    a = e.revisor("LUISA")
    p = e.enviado("ANA")
    for code, fase in (("curp", 1), ("tt_test_anexo_t6", 6)):
        doc = make_document(p, type_code=code, phase_number=fase)
        dest = tmp_path / doc.file_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"%PDF-1.4 documento de prueba")
    cli = client_as(a)

    ok = cli.get(f"{URL}/formato-b/{p.id}/documento/curp")
    otra = cli.get(f"{URL}/formato-b/{p.id}/documento/tt_test_anexo_t6")

    assert ok.status_code == 200
    assert ok.headers["content-disposition"].startswith("inline")
    assert otra.status_code == 404


# ---------------------------------------------------------------------------
# 5. Alcance (guarda) y corte a T-soft
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("metodo,sufijo,form", [
    ("POST", "aprobar", {}),
    ("POST", "observar", {"general_note": "Revisa"}),
    ("POST", "viendo", None),
    ("POST", "registro", {"first_name": "X", "last_name": "Y", "reason": "z"}),
    ("GET", "documento/curp", None),
])
def test_proceso_fuera_de_alcance_responde_404(metodo, sufijo, form, esc, client_as,
                                              db_session):
    e = esc()
    a = e.revisor("LUISA")
    ajeno = e.enviado("AJENO", programa_=e.hermana)
    propio = e.enviado("PROPIO")
    cli = client_as(a)

    def _llamar(pid):
        url = f"{URL}/formato-b/{pid}/{sufijo}"
        return cli.get(url) if metodo == "GET" else cli.post(url, data=form or {})

    assert _llamar(ajeno.id).status_code == 404
    assert _fb(db_session, ajeno.id).status == "submitted"
    # Regla de oro: el mismo actor sí alcanza un proceso de su carrera.
    if sufijo == "viendo":
        assert _llamar(propio.id).status_code == 204


def test_con_el_corte_en_3_no_hay_acciones_y_el_post_se_bloquea(esc, client_as,
                                                                 db_session):
    e = esc(cut=3)
    a = e.revisor("LUISA")
    p = e.enviado("ANA")
    cli = client_as(a)

    pagina = cli.get(URL, params={"selected": p.id})

    assert pagina.status_code == 200
    assert _html(pagina).xpath('//*[@id="tt-tit-handoff"]')
    assert not _html(pagina).xpath('//*[@id="tt-tit-approve"]')
    assert "T-soft" in pagina.text

    resp = cli.post(f"{URL}/formato-b/{p.id}/aprobar", data={"tab": "pending"})

    assert resp.status_code == 400
    assert _hdr(resp, "X-Tt-Error") == PhaseService.HANDOFF_MSG
    assert _fb(db_session, p.id).status == "submitted"


# ---------------------------------------------------------------------------
# 6. Presencia
# ---------------------------------------------------------------------------
def test_viendo_responde_204_y_otro_revisor_ve_la_insignia(esc, client_as, presencia):
    e = esc()
    a = e.revisor("LUISA")
    b = e.revisor("BETO")
    p = e.enviado("ANA")

    resp = client_as(a).post(f"{URL}/formato-b/{p.id}/viendo")

    assert resp.status_code == 204
    assert presencia.marcas[("format_b", p.id)] == {a.id: "LUISA TITULACION"}

    fila_b = _html(client_as(b).get(BODY, params={"tab": "pending"})).xpath(
        '//*[@id="tt-tit-row-%d"]' % p.id)[0]
    assert "LUISA TITULACION lo está revisando" in " ".join(fila_b.text_content().split())

    fila_a = _html(client_as(a).get(BODY, params={"tab": "pending"})).xpath(
        '//*[@id="tt-tit-row-%d"]' % p.id)[0]
    assert "lo está revisando" not in fila_a.text_content()


def test_abrir_el_detalle_marca_la_presencia(esc, client_as, presencia):
    e = esc()
    a = e.revisor("LUISA")
    p = e.enviado("ANA")

    client_as(a).get(BODY, params={"tab": "pending", "selected": p.id})

    assert a.id in presencia.marcas.get(("format_b", p.id), {})


# ---------------------------------------------------------------------------
# 7. Estáticos y contrato del frontend
# ---------------------------------------------------------------------------
def test_base_admin_carga_el_js_y_la_hoja_una_vez(esc, client_as):
    e = esc()
    a = e.revisor("LUISA")

    html = client_as(a).get(URL).text

    assert html.count("/static/titulatec/js/admin/titulacion.js?v=") == 1
    assert html.count("/static/titulatec/css/admin/titulacion.css?v=") == 1
    assert html.index("js/admin/titulacion.js") > html.index("js/admin/doc-viewer.js")
    base = BASE_ADMIN.read_text(encoding="utf-8")
    assert "sv('js/admin/titulacion.js')" in base and "sv('css/admin/titulacion.css')" in base
    pagina = (TEMPLATES / "admin" / "titulacion.html").read_text(encoding="utf-8")
    assert "titulacion.js" not in pagina and "titulacion.css" not in pagina


def test_parciales_sin_script_ni_style_inline():
    plantillas = [TEMPLATES / "admin" / "titulacion.html", *sorted(PARCIALES.glob("*.html"))]
    assert len(plantillas) == 5
    for tpl in plantillas:
        fuente = re.sub(r"\{#.*?#\}", "", tpl.read_text(encoding="utf-8"), flags=re.S)
        assert "<script" not in fuente, tpl.name
        assert re.search(r"\sstyle=", fuente) is None, tpl.name


def test_js_morph_safe_y_sin_dialogos_nativos():
    js = JS.read_text(encoding="utf-8")

    assert js.lstrip().startswith("/*") and "(function () {" in js
    for gancho in ("htmx:afterSettle", "DOMContentLoaded", "htmx:historyRestore",
                   "htmx:afterRequest", "window.TitulaTecTitulacion"):
        assert gancho in js, gancho
    for nativo in ("confirm(", "alert(", "prompt("):
        assert not re.search(r"(?<![\w.])" + re.escape(nativo), js), nativo
    assert "innerHTML" not in js
    assert "\r\n" not in JS.read_bytes().decode("utf-8")


def test_css_comentarios_cerrados_y_llaves_balanceadas():
    css = CSS.read_text(encoding="utf-8")
    sin_comentarios = re.sub(r"/\*.*?\*/", "", css, flags=re.S)

    assert "*/" not in sin_comentarios and "/*" not in sin_comentarios
    assert sin_comentarios.count("{") == sin_comentarios.count("}")
    assert "#tt-tit-body" in css


# ---------------------------------------------------------------------------
# 7. Ronda final: documento con corte, siguiente filtrado
# ---------------------------------------------------------------------------
def test_con_el_corte_en_3_el_documento_no_se_sirve(esc, client_as, make_document,
                                                     tmp_path, monkeypatch):
    """Producción (corte 3): ni el acta ni la CURP salen por URL directa."""
    monkeypatch.setattr("itcj2.apps.titulatec.utils.storage._base", lambda: tmp_path)
    e = esc(cut=3)
    a = e.revisor("LUISA")
    p = e.enviado("ANA")
    doc = make_document(p, type_code="curp", phase_number=1)
    dest = tmp_path / doc.file_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"%PDF-1.4 documento de prueba")

    resp = client_as(a).get(f"{URL}/formato-b/{p.id}/documento/curp")

    assert resp.status_code == 404


def test_el_siguiente_respeta_el_filtro_de_carrera(esc, client_as, db_session):
    """Con un filtro de carrera activo el siguiente es de ESA carrera: antes era
    de toda la cola y el detalle salía vacío."""
    e = esc()
    a = e.revisor("LUISA", programas=[e.programa, e.hermana])
    p1 = e.enviado("UNO", dias=9)
    otra = e.enviado("OTRA", dias=7, programa_=e.hermana)
    p3 = e.enviado("TRES", dias=3)

    resp = client_as(a).post(f"{URL}/formato-b/{p1.id}/aprobar", data={
        "tab": "pending", "carrera": str(e.programa.id), "q": "", "page": ""})

    assert resp.status_code == 200, resp.text[:500]
    det = _detalle(resp)
    assert det is not None and int(det.get("data-process")) == p3.id
    assert otra.id != p3.id


def test_el_siguiente_respeta_la_busqueda(esc, client_as):
    e = esc()
    a = e.revisor("LUISA")
    p1 = e.enviado("UNO", dias=9)
    e.enviado("DOS", dias=7)
    p3 = e.enviado("TRES", dias=3)

    resp = client_as(a).post(f"{URL}/formato-b/{p1.id}/aprobar", data={
        "tab": "pending", "q": "TRES", "carrera": "", "page": ""})

    assert resp.status_code == 200, resp.text[:500]
    assert int(_detalle(resp).get("data-process")) == p3.id


# ---------------------------------------------------------------------------
# R-E (spec fase 4 §16b): sinodales asignados y oficio en el detalle aprobado
# ---------------------------------------------------------------------------
def _aprobado_con_sinodales(e, db_session, make_department, make_teacher, make_synodals,
                            con_sinodales=True):
    p = e.enviado("RAUL", status="approved", phase=4)
    if con_sinodales:
        dept = make_department(name="Depto Titulacion T10")
        docs = {r: make_teacher(dept) for r in ("president", "secretary", "vocal", "alternate")}
        make_synodals(p, docs, e.revisor("ASIGNA"))
    return p


def test_formato_b_aprobado_muestra_sinodales_y_oficio_solo_con_el_permiso(
    esc, client_as, db_session, make_role, make_user, make_position, bind_position_role,
    link_programs, assign_position, make_department, make_teacher, make_synodals,
):
    e = esc()
    p = _aprobado_con_sinodales(e, db_session, make_department, make_teacher, make_synodals)
    a = e.revisor("LUISA")

    resp = client_as(a).get(BODY, params={"tab": "approved", "selected": p.id})
    det = _detalle(resp)
    assert det is not None
    bloque = det.xpath('.//*[@id="tt-tit-sinodales"]')
    assert bloque, "falta el bloque «Sinodales asignados»"
    texto = " ".join(bloque[0].text_content().split())
    for rol in ("Presidente", "Secretario", "Vocal", "Vocal Suplente"):
        assert rol in texto, rol
    assert not det.xpath('.//a[@data-tt-oficio]'), "sin synodal.api.read no hay oficio"

    # Con el permiso: el mismo revisor + synodal.api.read.
    rol = make_role(f"{ROLE_DEPTO}_oficio", DEPTO_PERMS + ("titulatec.synodal.api.read",))
    user = make_user(first_name="OFICIAL", last_name="TITULACION")
    pos = make_position(title="Titulacion con oficio T10")
    bind_position_role(pos, rol)
    link_programs(pos, [e.programa])
    assign_position(user, pos)

    resp2 = client_as(user).get(BODY, params={"tab": "approved", "selected": p.id})
    ligas = _detalle(resp2).xpath('.//a[@data-tt-oficio]')
    assert [l.get("href") for l in ligas] == [f"/titulatec/admin/sinodales/{p.id}/oficio.pdf"]


def test_formato_b_pendiente_no_muestra_el_bloque_de_sinodales(esc, client_as):
    e = esc()
    a = e.revisor("LUISA")
    p = e.enviado("ANA")
    det = _detalle(client_as(a).get(BODY, params={"tab": "pending", "selected": p.id}))
    assert det is not None and not det.xpath('.//*[@id="tt-tit-sinodales"]')
