"""Bandeja «Promedios» (`pages/averages_admin.py`, spec 2026-11-26 §6-§8, parte páginas).

El servicio (bandeja por vista, pasar/regresar, capturar, archivo) ya lo cubre
`test_average_queue_service.py`; aquí se fija la RUTA: un solo código por ruta, qué ve
cada vista (CC: todo y dos pestañas; SE: solo lo pasado y de sus carreras, sin
pestañas), los avisos `X-Tt-Notice` / `X-Tt-Error` y la carga por archivo.

La base de dev comparte filas reales: toda consulta de CC se acota con `q=TAG`.
"""
from __future__ import annotations

import functools
import os
import re
from urllib.parse import unquote

import pytest

import itcj2.models  # noqa: F401
from tests.fastapi.titulatec.paging_asserts import assert_buscador_preservado

pytestmark = pytest.mark.usefixtures("audit_mark")

URL = "/titulatec/admin/promedios"
TAG = f"PROMP{os.getpid()}"
LIST = "titulatec.average.page.list"
CAPTURE = "titulatec.average.api.capture"
REQUEST = "titulatec.average.api.request"


@pytest.fixture(autouse=True)
def _catalogo(seed_phase_defs):
    seed_phase_defs()


@pytest.fixture()
def carrera(make_program):
    return make_program(f"Ingenieria Promedios Pagina {TAG}")


@pytest.fixture()
def otra_carrera(make_program):
    return make_program(f"Ingenieria Otra Pagina {TAG}")


@pytest.fixture()
def make_actor(make_user, make_role, grant_user_role):
    """Actor con SOLO los códigos dados, en un rol propio por juego de códigos."""
    def _make(perm_codes, last_name="COMPUTO"):
        user = make_user(first_name="CENTRO", last_name=last_name)
        nombre = "tt_test_avgp_" + "_".join(sorted(c.rsplit(".", 1)[1] for c in perm_codes))
        grant_user_role(user, make_role(nombre, perm_codes))
        return user

    return _make


@pytest.fixture()
def cc(make_actor):
    return make_actor((LIST, CAPTURE, REQUEST))


@pytest.fixture()
def expediente(db_session, make_student, make_process, make_cohort, carrera):
    """Proceso SIN promedio de un alumno con apellido `TAG`."""
    def _make(*, program=carrera, fase=1, control=None):
        alumno = make_student(control_number=control, last_name=TAG)
        proc = make_process(alumno, cohort=make_cohort(), program=program, current_phase=fase)
        db_session.commit()      # checkpoint: el rollback de la ruta no se lleva el fixture
        return proc

    return _make


def _control(db, proc):
    from itcj2.core.models.user import User
    return db.get(User, proc.student_id).control_number


def _pasar(db, proc, actor):
    from itcj2.apps.titulatec.services.average_queue_service import AverageQueueService
    AverageQueueService.request_school_services(db, proc.id, actor_id=actor.id)


def _error(resp):
    return unquote(resp.headers.get("X-Tt-Error", ""))


def _aviso(resp):
    return unquote(resp.headers.get("X-Tt-Notice", ""))


def _plano(html):
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def _ids_de_fila(html):
    return set(re.findall(r'<tr id="tt-avg-(\d+)"', html))


def _vista(html):
    """Solo el contenido de la página (encabezado + parcial), sin el cascarón."""
    ini = html.index('class="tt-kicker">Expedientes')
    fin = min(i for i in (html.find(m, ini) for m in ('<script', 'id="tt-modal', '<aside', '</main>'))
              if i != -1)
    return html[ini:fin]


def _csv(*filas, sep=";", cabecera=("control", "promedio")):
    return "\r\n".join(sep.join(f) for f in (cabecera, *filas)) + "\r\n"


# ---------------------------------------------------------------------------
# Acceso y menú
# ---------------------------------------------------------------------------
def test_sin_el_permiso_de_la_bandeja_no_entra(client_as, make_head):
    assert client_as(make_head()).get(URL).status_code == 403
    assert client_as(make_head()).get(f"{URL}/body").status_code == 403


def test_el_menu_muestra_promedios_solo_con_page_list(client_as, make_head, cc):
    sin_permiso = client_as(make_head()).get("/titulatec/admin/documents")
    assert sin_permiso.status_code == 200, sin_permiso.text[:500]
    assert f'"{URL}"' not in sin_permiso.text

    con_permiso = client_as(cc).get(URL)
    assert con_permiso.status_code == 200, con_permiso.text[:500]
    assert f'hx-get="{URL}"' in con_permiso.text
    assert "Promedios" in con_permiso.text
    assert "bi-123" in con_permiso.text


def test_cada_ruta_exige_un_solo_codigo():
    from itcj2.apps.titulatec.pages import averages_admin

    assert averages_admin._LIST == [LIST]
    assert averages_admin._CAPTURE == [CAPTURE]
    assert averages_admin._REQUEST == [REQUEST]


# Cada POST con el ÚNICO código que debe exigir; la vista sola no basta.
_RUTAS_POST = [
    ("guardar", CAPTURE, {"promedio": "85"}),
    ("pasar-a-escolares", REQUEST, {}),
    ("regresar", REQUEST, {}),
]


@pytest.mark.parametrize("accion,codigo,data", _RUTAS_POST, ids=[r[0] for r in _RUTAS_POST])
def test_cada_post_exige_su_codigo(client_as, db_session, make_actor, expediente,
                                   accion, codigo, data):
    proc = expediente()
    otros = tuple(c for c in (LIST, CAPTURE, REQUEST) if c != codigo)
    resp = client_as(make_actor(otros, last_name="SINCODIGO")).post(
        f"{URL}/{proc.id}/{accion}", data=data)

    assert resp.status_code == 403, (accion, resp.status_code)
    db_session.refresh(proc)
    assert proc.final_average is None and proc.average_requested_at is None

    # Con SOLO su código pasa el gate: nunca 403.
    solo = make_actor((codigo,), last_name="SOLOSUYO")
    resp = client_as(solo).post(f"{URL}/{proc.id}/{accion}", data=data)
    assert resp.status_code != 403, (accion, codigo)


def test_el_archivo_exige_capturar(client_as, make_actor):
    sin = make_actor((LIST, REQUEST), last_name="SINCAPTURA")
    resp = client_as(sin).post(f"{URL}/archivo",
                               files={"archivo": ("a.csv", _csv(), "text/csv")})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Qué ve cada vista
# ---------------------------------------------------------------------------
def test_cc_ve_todo_en_dos_pestanas(client_as, db_session, expediente, cc,
                                    carrera, otra_carrera):
    uno = expediente(program=carrera)
    dos = expediente(program=otra_carrera)
    pasado = expediente(program=carrera)
    _pasar(db_session, pasado, cc)

    resp = client_as(cc).get(f"{URL}?q={TAG}")

    assert resp.status_code == 200, resp.text[:500]
    assert _ids_de_fila(resp.text) == {str(uno.id), str(dos.id)}
    assert "Por capturar (2)" in resp.text and "Con Escolares (1)" in resp.text
    assert 'aria-current="true"' in resp.text
    assert "Expedientes · Promedio oficial" in resp.text
    assert _vista(resp.text).count('class="tt-kicker"') == 1

    resp = client_as(cc).get(f"{URL}/body?tab=requested&q={TAG}")
    assert _ids_de_fila(resp.text) == {str(pasado.id)}
    assert "Pasado a Escolares el" in resp.text
    assert "Regresar a Por capturar" in resp.text and "No lo tengo" not in resp.text

    # Una pestaña desconocida cae en la primera.
    resp = client_as(cc).get(f"{URL}/body?tab=zzz&q={TAG}")
    assert _ids_de_fila(resp.text) == {str(uno.id), str(dos.id)}


def test_la_fila_liberada_lleva_su_pastilla(client_as, expediente, cc):
    liberado = expediente(fase=3)

    resp = client_as(cc).get(f"{URL}/body?q={TAG}")

    assert f'id="tt-avg-{liberado.id}"' in resp.text
    assert "En Liberados" in resp.text


def test_se_solo_ve_lo_pasado_y_de_sus_carreras_sin_pestanas(
        client_as, db_session, expediente, cc, make_officer, carrera, otra_carrera):
    por_capturar = expediente(program=carrera)
    pasado = expediente(program=carrera)
    ajeno = expediente(program=otra_carrera)
    for p in (pasado, ajeno):
        _pasar(db_session, p, cc)
    officer, _pos = make_officer([carrera], perm_codes=(LIST, CAPTURE))

    resp = client_as(officer).get(f"{URL}?q={TAG}")

    assert resp.status_code == 200, resp.text[:500]
    assert _ids_de_fila(resp.text) == {str(pasado.id)}
    assert str(por_capturar.id) not in resp.text and str(ajeno.id) not in resp.text
    assert "Por capturar" not in resp.text and "tt-avg-tab-" not in resp.text
    assert "No lo tengo" not in resp.text and "Regresar a Por capturar" not in resp.text
    assert "Captúralo del expediente físico." in resp.text


def test_se_sin_carreras_ve_el_aviso(client_as, make_officer):
    officer, _pos = make_officer([], perm_codes=(LIST, CAPTURE))

    resp = client_as(officer).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    assert "No tienes carreras asignadas" in _plano(resp.text)
    assert 'id="tt-avg-no-programs"' in resp.text and "<table" not in resp.text


def test_vacios_por_vista(client_as, make_officer, cc, carrera):
    # q=TAG no coincide con nada en `Sin resultados`; los vacíos usan un filtro vacío
    # solo en SE (sembrada propia), así que para CC se acota con la pestaña.
    officer, _pos = make_officer([carrera], perm_codes=(LIST, CAPTURE))
    se = client_as(officer).get(f"{URL}/body")
    assert "Centro de Cómputo no te ha pasado ningún promedio de tus carreras." in _plano(se.text)

    sin = client_as(cc).get(f"{URL}/body?q=ZZZ-no-existe-{TAG}")
    assert 'id="tt-avg-no-results"' in sin.text and "Sin resultados para" in sin.text


# ---------------------------------------------------------------------------
# Capturar
# ---------------------------------------------------------------------------
def test_capturar_guarda_saca_la_fila_y_avisa(client_as, db_session, expediente, cc):
    proc = expediente()
    otro = expediente()
    control = _control(db_session, proc)

    resp = client_as(cc).post(
        f"{URL}/{proc.id}/guardar",
        data={"promedio": "86,44", "tab": "pending", "q": TAG, "page": "1"})

    assert resp.status_code == 200, resp.text[:500]
    assert _aviso(resp) == f"Promedio 86.44 guardado · {control}"
    assert resp.headers["X-Tt-Notice-Kind"] == "success"
    assert _ids_de_fila(resp.text) == {str(otro.id)}
    db_session.refresh(proc)
    assert str(proc.final_average) == "86.44"


def test_capturar_fuera_de_rango_es_400_con_x_tt_error(client_as, db_session, expediente, cc):
    proc = expediente()

    resp = client_as(cc).post(f"{URL}/{proc.id}/guardar", data={"promedio": "69"})

    assert resp.status_code == 400, resp.text[:300]
    assert "70" in _error(resp) and "100" in _error(resp)
    db_session.refresh(proc)
    assert proc.final_average is None


def test_capturar_texto_ilegible_es_400(client_as, db_session, expediente, cc):
    proc = expediente()

    resp = client_as(cc).post(f"{URL}/{proc.id}/guardar", data={"promedio": "abc"})

    assert resp.status_code == 400 and _error(resp)
    db_session.refresh(proc)
    assert proc.final_average is None


def test_capturar_fuera_de_la_bandeja_es_404(client_as, db_session, expediente, make_officer,
                                             carrera):
    por_capturar = expediente()     # CC no lo ha pasado: SE no lo ve
    officer, _pos = make_officer([carrera], perm_codes=(LIST, CAPTURE))

    resp = client_as(officer).post(f"{URL}/{por_capturar.id}/guardar", data={"promedio": "85"})

    assert resp.status_code == 404
    db_session.refresh(por_capturar)
    assert por_capturar.final_average is None


def test_se_captura_lo_que_cc_le_paso(client_as, db_session, expediente, cc, make_officer,
                                      carrera):
    pasado = expediente()
    _pasar(db_session, pasado, cc)
    officer, _pos = make_officer([carrera], perm_codes=(LIST, CAPTURE))

    resp = client_as(officer).post(f"{URL}/{pasado.id}/guardar", data={"promedio": "90.5"})

    assert resp.status_code == 200, resp.text[:500]
    db_session.refresh(pasado)
    assert str(pasado.final_average) == "90.50"


# ---------------------------------------------------------------------------
# Pasar / regresar
# ---------------------------------------------------------------------------
def test_pasar_y_regresar_mueven_de_pestana(client_as, db_session, expediente, cc):
    proc = expediente()
    control_form = {"tab": "pending", "q": TAG, "page": "1"}

    resp = client_as(cc).post(f"{URL}/{proc.id}/pasar-a-escolares", data=control_form)

    assert resp.status_code == 200, resp.text[:500]
    assert str(proc.id) not in _ids_de_fila(resp.text)
    assert "Por capturar (0)" in resp.text and "Con Escolares (1)" in resp.text
    db_session.refresh(proc)
    assert proc.average_requested_at is not None and proc.average_requested_by_id == cc.id

    resp = client_as(cc).post(f"{URL}/{proc.id}/regresar",
                              data={**control_form, "tab": "requested"})

    assert resp.status_code == 200, resp.text[:500]
    assert "Por capturar (1)" in resp.text and "Con Escolares (0)" in resp.text
    db_session.refresh(proc)
    assert proc.average_requested_at is None


def test_pasar_con_promedio_es_400(client_as, db_session, expediente, cc):
    proc = expediente()
    proc.final_average = 88
    db_session.commit()

    resp = client_as(cc).post(f"{URL}/{proc.id}/pasar-a-escolares", data={})

    assert resp.status_code == 400 and "Ya tiene promedio" in _error(resp)


def test_pasar_inexistente_es_404(client_as, cc):
    assert client_as(cc).post(f"{URL}/987654321/pasar-a-escolares", data={}).status_code == 404


# ---------------------------------------------------------------------------
# Carga por archivo
# ---------------------------------------------------------------------------
def _subir(client, actor, contenido, nombre="promedios.csv", data=None):
    cuerpo = contenido if isinstance(contenido, bytes) else contenido.encode("utf-8")
    return client(actor).post(f"{URL}/archivo", data=data or {"tab": "pending", "q": TAG},
                              files={"archivo": (nombre, cuerpo, "text/csv")})


def test_archivo_resume_por_grupo(client_as, db_session, expediente, cc):
    uno = expediente()
    dos = expediente()
    c1, c2 = _control(db_session, uno), _control(db_session, dos)

    resp = _subir(client_as, cc, _csv((c1, "91.25"), (c2, "50"), ("99999999", "80"),
                                      ("abc", "80")))

    assert resp.status_code == 200, resp.text[:500]
    plano = _plano(resp.text)
    assert "Aplicados a su proceso: 1" in plano
    assert "Fuera de rango (70-100): 1" in plano
    assert "No está en tu bandeja: 1" in plano
    assert "Formato inválido: 1" in plano
    assert "Duplicados: 0" in plano
    assert 'id="tt-avg-result"' in resp.text and "promedios.csv" in plano
    assert _aviso(resp) == "1 de 4 fila(s) aplicadas."
    db_session.refresh(uno)
    db_session.refresh(dos)
    assert str(uno.final_average) == "91.25" and dos.final_average is None
    assert _ids_de_fila(resp.text) == {str(dos.id)}


def test_archivo_latin1_se_lee(client_as, db_session, expediente, cc):
    proc = expediente()
    texto = _csv((_control(db_session, proc), "88,5"), cabecera=("Número de control", "Promedio"))

    resp = _subir(client_as, cc, texto.encode("latin-1"))

    assert resp.status_code == 200, resp.text[:500]
    assert "Aplicados a su proceso: 1" in _plano(resp.text)
    db_session.refresh(proc)
    assert str(proc.final_average) == "88.50"


def test_archivo_de_se_solo_aplica_a_su_bandeja(client_as, db_session, expediente, cc,
                                                make_officer, carrera, otra_carrera):
    mio = expediente(program=carrera)
    ajeno = expediente(program=otra_carrera)
    sin_pasar = expediente(program=carrera)
    for p in (mio, ajeno):
        _pasar(db_session, p, cc)
    officer, _pos = make_officer([carrera], perm_codes=(LIST, CAPTURE))

    resp = _subir(client_as, officer, _csv(*[(_control(db_session, p), "80")
                                            for p in (mio, ajeno, sin_pasar)]),
                  data={"tab": "requested", "q": ""})

    assert resp.status_code == 200, resp.text[:500]
    plano = _plano(resp.text)
    assert "Aplicados a su proceso: 1" in plano and "No está en tu bandeja: 2" in plano
    for p in (ajeno, sin_pasar):
        db_session.refresh(p)
        assert p.final_average is None


def test_archivo_grande_se_rechaza(client_as, cc):
    resp = _subir(client_as, cc, b"control;promedio\n" + b"x" * (1024 * 1024 + 1))

    assert resp.status_code == 400
    assert "1 MB" in _error(resp)


def test_archivo_sin_columnas_o_sin_archivo_es_400(client_as, cc):
    resp = _subir(client_as, cc, "a;b\n1;2\n")
    assert resp.status_code == 400 and "control" in _error(resp)

    resp = _subir(client_as, cc, "control;promedio\n")
    assert resp.status_code == 400 and _error(resp)

    resp = client_as(cc).post(f"{URL}/archivo", data={"tab": "pending"})
    assert resp.status_code == 400 and "archivo" in _error(resp).lower()


# ---------------------------------------------------------------------------
# Parcial: búsqueda y paginación
# ---------------------------------------------------------------------------
def test_el_buscador_se_conserva_y_filtra_por_control(client_as, db_session, expediente, cc):
    uno = expediente()
    expediente()
    control = _control(db_session, uno)

    resp = client_as(cc).get(f"{URL}/body?q={control}")

    assert _ids_de_fila(resp.text) == {str(uno.id)}
    assert_buscador_preservado(resp.text, input_id="tt-avg-q", filters_id="tt-avg-filters",
                               q=control)
    assert resp.text.count('id="tt-avg-body"') == 1


def test_el_parcial_pagina(client_as, monkeypatch, expediente, cc):
    from itcj2.apps.titulatec.pages import averages_admin

    monkeypatch.setattr(averages_admin, "_body_ctx",
                        functools.partial(averages_admin._body_ctx, per_page=2))
    for _ in range(3):
        expediente()

    p1 = client_as(cc).get(f"{URL}/body?q={TAG}")
    p2 = client_as(cc).get(f"{URL}/body?q={TAG}&page=2")

    assert len(_ids_de_fila(p1.text)) == 2 and len(_ids_de_fila(p2.text)) == 1
    assert 'id="tt-avg-pager"' in p1.text
    assert "hx-include=\"#tt-avg-filters\"" in p1.text
    assert not _ids_de_fila(p1.text) & _ids_de_fila(p2.text)


def test_la_pagina_no_lleva_js_ni_css_en_linea(client_as, expediente, cc):
    expediente()

    cuerpo = _vista(client_as(cc).get(f"{URL}?q={TAG}").text)

    assert "<script" not in cuerpo and "<style" not in cuerpo and " style=" not in cuerpo
    assert "confirm(" not in cuerpo and "onclick=" not in cuerpo
