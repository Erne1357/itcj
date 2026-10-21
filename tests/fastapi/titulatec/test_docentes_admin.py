"""Pestaña admin «Docentes» (spec 2026-10-21 fase 4 §8 y §16b R-B/R-G, Task 7).

- Corte a T-soft EXPLÍCITO: `corte(9)` opera la fase 4; `corte(3)` es producción
  y deja la pestaña inerte (R-G).
- El jefe de departamento opera SOLO su departamento (`manageable_departments`);
  uno ajeno es 403 aunque esté mapeado.
- La contraseña temporal nunca aparece en el HTML ni en los headers de una
  respuesta; solo viaja por el correo de acceso (aquí, un doble de `deliver_detailed`).
"""
from __future__ import annotations

import ast
from pathlib import Path
from urllib.parse import unquote

import lxml.html
import pytest

import itcj2.apps.titulatec as _tt_pkg
from itcj2.apps.titulatec.services import email_helper
from itcj2.apps.titulatec.services.phase_service import PhaseService
from itcj2.apps.titulatec.services.teacher_service import (
    INACTIVE_ACCOUNT_MSG, INERT_MSG, POSITION_PREFIX, RESET_NOT_ALLOWED_MSG,
    TeacherService,
)
from itcj2.core.models.user import User
from itcj2.core.utils.security import DEFAULT_PASSWORD
from itcj2.core.utils.timezone import db_now
from tests.fastapi.titulatec.conftest import _n

pytestmark = pytest.mark.usefixtures("audit_mark")

APP = Path(_tt_pkg.__file__).resolve().parent
PAGES = APP / "pages"
URL = "/titulatec/admin/docentes"
BODY = URL + "/body"
BUSCAR = URL + "/buscar"
DOMINIO = "docentes-ui.invalid"

PAGE_PERM = "titulatec.teacher.page.list"
MANAGE_PERM = "titulatec.teacher.api.manage"
HEAD_PERMS = (PAGE_PERM, MANAGE_PERM)


# ---------------------------------------------------------------------------
# Andamiaje
# ---------------------------------------------------------------------------
@pytest.fixture()
def corte(monkeypatch):
    def _fijar(fase):
        monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: fase))
    return _fijar


@pytest.fixture(autouse=True)
def _base(monkeypatch, seed_phase_defs, corte):
    from itcj2.config import get_settings

    seed_phase_defs()
    corte(9)
    monkeypatch.setattr(get_settings(), "TITULATEC_TEACHER_EMAIL_DOMAINS", DOMINIO)


@pytest.fixture(autouse=True)
def staff_itcj(db_session):
    """App `itcj` y rol `staff` (en CI la base nace sin el rol)."""
    from itcj2.core.models.app import App
    from itcj2.core.models.role import Role

    app = db_session.query(App).filter_by(key="itcj").first()
    if app is None:
        db_session.add(App(key="itcj", name="Plataforma ITCJ", is_active=True,
                           visible_to_students=False, mobile_enabled=True))
    if db_session.query(Role).filter_by(name="staff").first() is None:
        db_session.add(Role(name="staff"))
    db_session.flush()


@pytest.fixture()
def correos(monkeypatch):
    """Doble de `deliver_detailed`: guarda lo enviado y responde `resultado`."""
    class _Doble:
        enviados: list = []
        resultado = (True, None)

    doble = _Doble()
    doble.enviados = []

    def _falso(**kw):
        doble.enviados.append(kw)
        return doble.resultado

    monkeypatch.setattr(email_helper, "deliver_detailed", _falso)
    return doble


@pytest.fixture()
def esc(db_session, make_department, make_program, make_program_department,
        make_position, make_academic_head):
    """Departamento propio (con carrera mapeada y puesto docente), otro ajeno
    también mapeado y un jefe del primero con los permisos de la pestaña."""
    def _build():
        n = _n()
        dept = make_department(name=f"Depto docentes UI {n}")
        ajeno = make_department(name=f"Depto ajeno UI {n}")
        for d, nombre in ((dept, "propia"), (ajeno, "ajena")):
            make_program_department(make_program(f"Carrera {nombre} docentes UI {n}"), d)
            make_position(code=f"{POSITION_PREFIX}{d.code}", title="Docente", department=d)
        jefe = make_academic_head(dept, perms=HEAD_PERMS)
        return dept, ajeno, jefe
    return _build


def _html(resp):
    return lxml.html.fromstring(resp.text)


def _aviso(resp) -> str:
    return unquote(resp.headers.get("X-Tt-Notice", ""))


def _error(resp) -> str:
    return unquote(resp.headers.get("X-Tt-Error", ""))


def _correo(prefijo="docente"):
    return f"{prefijo}.ui{_n()}@{DOMINIO}"


def _alta(dept, **kw):
    n = _n()
    datos = dict(dept=str(dept.id), first_name=f"Nombre{n}", last_name="Ficticio",
                 middle_name="Prueba", email=_correo(), academic_degree="Maestra en Ciencias",
                 professional_license="12345678")
    datos.update(kw)
    return datos


def _usuario_por_correo(db, correo):
    return db.query(User).filter(User.email == correo).first()


def _sin_contrasena(resp):
    assert DEFAULT_PASSWORD not in resp.text
    assert all(DEFAULT_PASSWORD not in f"{k}: {unquote(v)}" for k, v in resp.headers.items())


# ---------------------------------------------------------------------------
# Acceso y alcance
# ---------------------------------------------------------------------------
def test_la_pagina_lista_los_docentes_del_departamento(client_as, esc, make_teacher):
    dept, _ajeno, jefe = esc()
    docente = make_teacher(dept)
    resp = client_as(jefe).get(URL)
    assert resp.status_code == 200, resp.text[:400]
    doc = _html(resp)
    assert doc.xpath(f"//li[@id='tt-doc-row-{docente.id}']")
    assert "Cédula 10837613" in resp.text
    assert doc.xpath("//*[@id='tt-doc-add']")          # tiene el permiso de gestión


def test_sin_el_permiso_de_la_pestana_es_403(client_as, esc, make_user):
    esc()
    assert client_as(make_user()).get(URL).status_code == 403
    assert client_as(make_user()).get(BODY).status_code == 403


def test_solo_ver_no_ofrece_ni_permite_acciones(client_as, esc, make_user, make_role,
                                                make_position, bind_position_role,
                                                assign_position, db_session):
    dept, _ajeno, _jefe = esc()
    # Rol propio: el de `make_academic_head` es compartido y ya trae el permiso de gestión.
    rol = make_role(f"tt_test_docentes_lector_{_n()}", (PAGE_PERM,))
    pos = make_position(code=f"coord_vinculacion_{dept.code}", title="Coordinación", department=dept)
    bind_position_role(pos, rol)
    lector = make_user(first_name="LECTOR", last_name="DOCENTES")
    assign_position(lector, pos)
    resp = client_as(lector).get(URL)
    assert resp.status_code == 200
    assert not _html(resp).xpath("//*[@id='tt-doc-add']")
    antes = db_session.query(User).count()
    assert client_as(lector).post(URL + "/crear", data=_alta(dept)).status_code == 403
    assert client_as(lector).get(BUSCAR, params={"dept": dept.id, "q": "ab"}).status_code == 403
    assert db_session.query(User).count() == antes


def test_departamento_ajeno_es_403_sin_escribir(client_as, esc, correos, db_session):
    dept, ajeno, jefe = esc()
    cli = client_as(jefe)
    assert cli.get(URL, params={"dept": ajeno.id}).status_code == 403
    assert cli.get(BODY, params={"dept": ajeno.id}).status_code == 403
    datos = _alta(ajeno)
    assert cli.post(URL + "/crear", data=datos).status_code == 403
    assert cli.post(URL + "/quitar", data={"dept": str(ajeno.id), "user_id": "1"}).status_code == 403
    assert _usuario_por_correo(db_session, datos["email"]) is None
    assert correos.enviados == []


def test_una_accion_sin_departamento_explicito_es_403(client_as, esc, correos, db_session):
    _dept, _ajeno, jefe = esc()
    datos = _alta(_dept)
    datos.pop("dept")
    assert client_as(jefe).post(URL + "/crear", data=datos).status_code == 403
    assert _usuario_por_correo(db_session, datos["email"]) is None


def test_el_selector_lista_todos_los_departamentos_mapeados_al_admin_global(
        client_as, esc, make_user, make_role, make_position, bind_position_role, assign_position):
    dept, ajeno, _jefe = esc()
    rol = make_role(f"tt_test_docentes_all_{_n()}",
                    HEAD_PERMS + ("titulatec.process.api.read.all",))
    pos = make_position(title="División de pruebas")
    bind_position_role(pos, rol)
    div = make_user()
    assign_position(div, pos)
    doc = _html(client_as(div).get(URL))
    valores = {o.get("value") for o in doc.xpath("//select[@id='tt-doc-dept']/option")}
    assert {str(dept.id), str(ajeno.id)} <= valores
    assert client_as(div).get(URL, params={"dept": ajeno.id}).status_code == 200


def test_el_menu_trae_docentes_por_permiso(client_as, esc, make_user):
    _dept, _ajeno, jefe = esc()
    html = _html(client_as(jefe).get(URL))
    (link,) = html.xpath(f"//aside[@id='ttSide']//a[@hx-get='{URL}']")
    assert link.xpath(".//i[contains(@class,'bi-person-badge')]")
    assert "Docentes" in link.text_content()


# ---------------------------------------------------------------------------
# Crear
# ---------------------------------------------------------------------------
def test_crear_feliz_aparece_en_la_lista_y_manda_el_acceso(
        client_as, esc, correos, db_session):
    dept, _ajeno, jefe = esc()
    datos = _alta(dept)
    resp = client_as(jefe).post(URL + "/crear", data=datos)
    assert resp.status_code == 200, resp.text[:500]
    assert resp.headers["X-Tt-Notice-Kind"] == "success"
    assert "Docente creado" in _aviso(resp)
    nuevo = _usuario_por_correo(db_session, datos["email"])
    assert nuevo is not None
    assert _html(resp).xpath(f"//li[@id='tt-doc-row-{nuevo.id}']")
    assert len(correos.enviados) == 1
    _sin_contrasena(resp)


def test_correo_fallido_avisa_con_warning_y_la_cuenta_queda_creada(
        client_as, esc, correos, db_session):
    dept, _ajeno, jefe = esc()
    correos.resultado = (False, "envio")
    datos = _alta(dept)
    resp = client_as(jefe).post(URL + "/crear", data=datos)
    assert resp.status_code == 200
    assert resp.headers["X-Tt-Notice-Kind"] == "warning"
    assert "Reenviar acceso" in _aviso(resp)
    nuevo = _usuario_por_correo(db_session, datos["email"])
    assert nuevo is not None
    assert _html(resp).xpath(f"//li[@id='tt-doc-row-{nuevo.id}']")
    _sin_contrasena(resp)


def test_correo_existente_bloquea_y_muestra_la_cuenta(client_as, esc, correos, make_user,
                                                      db_session):
    dept, _ajeno, jefe = esc()
    correo = _correo()
    dueno = make_user(first_name="DUENO", last_name="CORREO", email=correo)
    usuarios = db_session.query(User).count()
    resp = client_as(jefe).post(URL + "/crear", data=_alta(dept, email=correo.upper()))
    assert resp.status_code == 200
    assert "X-Tt-Notice" not in resp.headers
    doc = _html(resp)
    assert doc.xpath("//*[@id='tt-doc-error']")
    assert doc.xpath(f"//li[@id='tt-doc-cand-{dueno.id}']")
    assert not doc.xpath("//input[@name='confirm_other_person']")   # no es caso de nombre
    assert db_session.query(User).count() == usuarios
    assert correos.enviados == []


def test_nombre_coincidente_exige_confirmar_que_es_otra_persona(
        client_as, esc, correos, make_user, db_session):
    dept, _ajeno, jefe = esc()
    n = _n()
    homonimo = make_user(first_name=f"Homonimo{n}", last_name="Repetido", username=f"hom{n}")
    datos = _alta(dept, first_name=f"Homonimo{n}", last_name="Repetido")
    resp = client_as(jefe).post(URL + "/crear", data=datos)
    assert resp.status_code == 200
    doc = _html(resp)
    assert doc.xpath("//input[@type='checkbox' and @name='confirm_other_person']")
    assert doc.xpath(f"//li[@id='tt-doc-cand-{homonimo.id}']")
    assert _usuario_por_correo(db_session, datos["email"]) is None
    # El formulario conserva lo capturado.
    assert doc.xpath(f"//form[@id='tt-doc-create']//input[@name='email'][@value='{datos['email']}']")

    resp = client_as(jefe).post(URL + "/crear", data={**datos, "confirm_other_person": "1"})
    assert resp.status_code == 200 and "Docente creado" in _aviso(resp)
    assert _usuario_por_correo(db_session, datos["email"]) is not None


def test_validacion_del_formulario_repinta_con_200_y_el_mensaje(client_as, esc, correos,
                                                                db_session):
    dept, _ajeno, jefe = esc()
    datos = _alta(dept, professional_license="12")
    resp = client_as(jefe).post(URL + "/crear", data=datos)
    assert resp.status_code == 200
    assert "cédula" in _html(resp).xpath("string(//*[@id='tt-doc-error'])").lower()
    assert _usuario_por_correo(db_session, datos["email"]) is None


# ---------------------------------------------------------------------------
# Buscar y agregar una cuenta existente
# ---------------------------------------------------------------------------
def test_la_busqueda_marca_alumno_desactivada_y_ya_del_departamento(
        client_as, esc, make_user, make_teacher):
    dept, _ajeno, jefe = esc()
    n = _n()
    alumno = make_user(first_name=f"Buscable{n}", last_name="Alumno",
                       control_number=f"99{n:06d}"[-8:])
    inactivo = make_user(first_name=f"Buscable{n}", last_name="Inactivo", is_active=False)
    docente = make_teacher(dept, user=make_user(first_name=f"Buscable{n}", last_name="Docente"))
    libre = make_user(first_name=f"Buscable{n}", last_name="Libre")
    resp = client_as(jefe).get(BUSCAR, params={"dept": dept.id, "q": f"Buscable{n}"})
    assert resp.status_code == 200
    doc = _html(resp)

    def fila(u):
        return doc.xpath(f"//li[@id='tt-doc-cand-{u.id}']")[0]

    # El alumno se encuentra por nombre solo si el servicio lo devuelve (no lo
    # lista: se excluye); lo que importa es que NUNCA ofrezca agregarlo.
    assert not doc.xpath(f"//li[@id='tt-doc-cand-{alumno.id}']//form")
    assert not fila(inactivo).xpath(".//form")
    assert "reactive" in fila(inactivo).text_content()
    assert not fila(docente).xpath(".//form")
    assert "Ya es docente" in fila(docente).text_content()
    assert fila(libre).xpath(".//form")


def test_agregar_cuenta_sin_primer_acceso_manda_el_acceso(client_as, esc, correos,
                                                          make_user, db_session):
    dept, _ajeno, jefe = esc()
    u = make_user(first_name="EXISTENTE", last_name="SINACCESO", email=_correo())
    resp = client_as(jefe).post(URL + "/agregar", data={
        "dept": str(dept.id), "user_id": str(u.id),
        "academic_degree": "Ingeniero en Sistemas", "professional_license": "1234567"})
    assert resp.status_code == 200, resp.text[:400]
    assert "Docente agregado" in _aviso(resp)
    assert _html(resp).xpath(f"//li[@id='tt-doc-row-{u.id}']")
    assert len(correos.enviados) == 1
    _sin_contrasena(resp)


def test_agregar_cuenta_con_privilegios_no_toca_la_credencial_ni_manda_correo(
        client_as, esc, correos, make_user, db_session):
    dept, _ajeno, jefe = esc()
    u = make_user(first_name="PRIVILEGIADA", last_name="CUENTA", email=_correo(),
                  global_role="admin")
    hash_antes = u.password_hash
    resp = client_as(jefe).post(URL + "/agregar", data={
        "dept": str(dept.id), "user_id": str(u.id),
        "academic_degree": "Doctora en Ciencias", "professional_license": "7654321"})
    assert resp.status_code == 200
    assert resp.headers["X-Tt-Notice-Kind"] == "success"
    assert correos.enviados == []
    db_session.refresh(u)
    assert u.password_hash == hash_antes
    # Ni «Reenviar acceso» en su fila: la cuenta tiene otros accesos.
    assert not _html(resp).xpath(f"//li[@id='tt-doc-row-{u.id}']//form[@hx-post='{URL}/reenviar']")


def test_agregar_cuenta_inactiva_se_rechaza_sin_reactivar(client_as, esc, correos,
                                                          make_user, db_session):
    dept, _ajeno, jefe = esc()
    u = make_user(first_name="INACTIVA", last_name="CUENTA", email=_correo(), is_active=False)
    resp = client_as(jefe).post(URL + "/agregar", data={
        "dept": str(dept.id), "user_id": str(u.id),
        "academic_degree": "Ingeniero", "professional_license": "1234567"})
    assert resp.status_code == 200
    assert INACTIVE_ACCOUNT_MSG in _html(resp).xpath("string(//*[@id='tt-doc-error'])")
    db_session.refresh(u)
    assert u.is_active is False
    assert correos.enviados == []


# ---------------------------------------------------------------------------
# Editar, quitar y reenviar
# ---------------------------------------------------------------------------
def test_editar_cambia_grado_y_cedula(client_as, esc, make_teacher):
    dept, _ajeno, jefe = esc()
    docente = make_teacher(dept)
    resp = client_as(jefe).post(URL + "/editar", data={
        "dept": str(dept.id), "user_id": str(docente.id),
        "academic_degree": "Doctor en Pruebas", "professional_license": "99887766"})
    assert resp.status_code == 200 and "Perfil actualizado" in _aviso(resp)
    assert "Doctor en Pruebas" in resp.text and "99887766" in resp.text


def test_quitar_termina_el_puesto_y_la_cuenta_sigue(client_as, esc, make_teacher, db_session):
    dept, _ajeno, jefe = esc()
    docente = make_teacher(dept)
    resp = client_as(jefe).post(URL + "/quitar", data={
        "dept": str(dept.id), "user_id": str(docente.id)})
    assert resp.status_code == 200 and "Se quitó" in _aviso(resp)
    assert not _html(resp).xpath(f"//li[@id='tt-doc-row-{docente.id}']")
    assert db_session.get(User, docente.id).is_active is True


def test_quitar_a_quien_no_es_del_departamento_es_400(client_as, esc, make_user):
    dept, _ajeno, jefe = esc()
    resp = client_as(jefe).post(URL + "/quitar", data={
        "dept": str(dept.id), "user_id": str(make_user().id)})
    assert resp.status_code == 400 and _error(resp)


def test_reenviar_acceso_solo_para_quien_nunca_entro(client_as, esc, correos, make_teacher,
                                                     make_user, db_session):
    dept, _ajeno, jefe = esc()
    pendiente = make_teacher(dept, user=make_user(first_name="PENDIENTE", last_name="ACCESO"))
    entro = make_teacher(dept, user=make_user(first_name="YA", last_name="ENTRO"))
    entro.last_login = db_now()
    db_session.flush()
    cli = client_as(jefe)
    html = _html(cli.get(URL))
    assert html.xpath(f"//li[@id='tt-doc-row-{pendiente.id}']//form[@hx-post='{URL}/reenviar']")
    assert not html.xpath(f"//li[@id='tt-doc-row-{entro.id}']//form[@hx-post='{URL}/reenviar']")

    resp = cli.post(URL + "/reenviar", data={"dept": str(dept.id), "user_id": str(entro.id)})
    assert resp.status_code == 400 and _error(resp) == RESET_NOT_ALLOWED_MSG
    assert correos.enviados == []

    resp = cli.post(URL + "/reenviar", data={"dept": str(dept.id), "user_id": str(pendiente.id)})
    assert resp.status_code == 200 and "Acceso restablecido" in _aviso(resp)
    assert len(correos.enviados) == 1
    _sin_contrasena(resp)


def test_reenviar_se_oculta_en_una_cuenta_con_privilegios(client_as, esc, make_teacher,
                                                          make_user):
    dept, _ajeno, jefe = esc()
    jefa = make_teacher(dept, user=make_user(first_name="CON", last_name="PRIVILEGIOS",
                                             global_role="admin"))
    html = _html(client_as(jefe).get(URL))
    assert html.xpath(f"//li[@id='tt-doc-row-{jefa.id}']")
    assert not html.xpath(f"//li[@id='tt-doc-row-{jefa.id}']//form[@hx-post='{URL}/reenviar']")


# ---------------------------------------------------------------------------
# Corte (R-G) y convenciones
# ---------------------------------------------------------------------------
def test_con_el_corte_en_3_la_pestana_es_inerte_y_rechaza_acciones(
        client_as, esc, corte, correos, make_teacher, db_session):
    dept, _ajeno, jefe = esc()
    docente = make_teacher(dept)
    corte(3)
    cli = client_as(jefe)
    pagina = cli.get(URL)
    assert pagina.status_code == 200
    doc = _html(pagina)
    assert doc.xpath("//*[@id='tt-doc-inert']")
    assert not doc.xpath("//*[@id='tt-doc-add']") and not doc.xpath("//form[@hx-post]")
    datos = _alta(dept)
    resp = cli.post(URL + "/crear", data=datos)
    assert resp.status_code == 400 and _error(resp) == INERT_MSG
    resp = cli.post(URL + "/quitar", data={"dept": str(dept.id), "user_id": str(docente.id)})
    assert resp.status_code == 400
    assert _usuario_por_correo(db_session, datos["email"]) is None
    assert TeacherService.is_teacher_of(db_session, docente.id, dept.id)
    assert correos.enviados == []


def test_el_modulo_sigue_la_forma_canonica_y_no_tiene_rutas_con_process_id():
    fuente = (PAGES / "docentes_admin.py").read_text(encoding="utf-8")
    tree = ast.parse(fuente)
    rutas = [f for f in ast.walk(tree)
             if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
             and any(isinstance(d, ast.Call) and getattr(d.func, "attr", "") in
                     {"get", "post"} for d in f.decorator_list)]
    assert len(rutas) == 8
    assert "{process_id}" not in fuente
    assert "utcnow(" not in fuente
    for f in rutas:
        if isinstance(f, ast.AsyncFunctionDef):
            ultima = f.body[-1]
            assert isinstance(ultima, ast.Return) and isinstance(ultima.value, ast.Await)


def test_las_plantillas_no_llevan_script_ni_dialogos_nativos():
    carpeta = APP / "templates" / "titulatec"
    archivos = [carpeta / "admin" / "docentes.html", *(carpeta / "partials" / "docentes").glob("*.html")]
    assert len(archivos) == 3
    for ruta in archivos:
        texto = ruta.read_text(encoding="utf-8")
        assert "<script" not in texto and "<style" not in texto and "style=" not in texto, ruta.name
        assert "DEFAULT_PASSWORD" not in texto


def test_el_js_y_el_css_no_usan_dialogos_nativos_ni_tamanos_literales():
    js = (APP / "static" / "js" / "admin" / "docentes.js").read_text(encoding="utf-8")
    for prohibido in ("confirm(", "alert(", "prompt("):
        assert prohibido not in js.replace("hx-confirm", "")
    css = (APP / "static" / "css" / "admin" / "docentes.css").read_text(encoding="utf-8")
    import re
    assert not re.findall(r"font-size:\s*[\d.]+(?:px|rem|em)", css)
