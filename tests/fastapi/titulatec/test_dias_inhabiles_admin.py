"""Pestaña admin «Días inhábiles» (spec 2026-10-22 fase 5 §9.1, Task 3).

- Año sintético (2091) para no chocar con filas reales de la base de dev.
- Sin guarda de fase: el calendario es de toda la app (no hay `corte` aquí).
"""
from __future__ import annotations

import os
from datetime import date
from urllib.parse import unquote

import lxml.html
import pytest

from itcj2.apps.titulatec.models.non_working_day import NonWorkingDay
from tests.fastapi.titulatec.conftest import audit_query

pytestmark = pytest.mark.usefixtures("audit_mark")

URL = "/titulatec/admin/dias-inhabiles"
PAGE_PERM = "titulatec.non_working_day.page.list"
MANAGE_PERM = "titulatec.non_working_day.api.manage"
ANIO = 2091   # 1 ene 2091 = lunes

_RUN = os.getpid()
ROLE_ADMIN = f"tt_test_dias_admin_{_RUN}"
ROLE_LECTOR = f"tt_test_dias_lector_{_RUN}"


@pytest.fixture()
def esc(db_session, make_user, make_role, grant_user_role):
    admin = make_user(first_name="ADMIN", last_name="DIAS")
    grant_user_role(admin, make_role(ROLE_ADMIN, (PAGE_PERM, MANAGE_PERM)))
    lector = make_user(first_name="LECTOR", last_name="DIAS")
    grant_user_role(lector, make_role(ROLE_LECTOR, (PAGE_PERM,)))
    otro = make_user(first_name="OTRO", last_name="DIAS")
    return type("E", (), dict(admin=admin, lector=lector, otro=otro))


def _hdr(resp, name):
    return unquote(resp.headers.get(name, ""))


def _dias(db, anio=ANIO):
    db.expire_all()
    return [r.day for r in db.query(NonWorkingDay)
            .filter(NonWorkingDay.day >= date(anio, 1, 1), NonWorkingDay.day <= date(anio, 12, 31))
            .order_by(NonWorkingDay.day).all()]


# ---------------------------------------------------------------------------
# Acceso y menú
# ---------------------------------------------------------------------------
def test_sin_permiso_es_403(esc, client_as):
    assert client_as(esc.otro).get(URL).status_code == 403
    assert client_as(esc.otro).get(f"{URL}/body").status_code == 403


def test_admin_ve_la_pantalla_y_el_item_del_menu(esc, client_as):
    resp = client_as(esc.admin).get(f"{URL}?anio={ANIO}")
    assert resp.status_code == 200, resp.text[:400]
    doc = lxml.html.fromstring(resp.text)
    items = [(a.get("hx-get"), " ".join(a.text_content().split()))
             for a in doc.xpath('//aside[@id="ttSide"]//a[@hx-get]')]
    assert (URL, "Días inhábiles") in items
    assert doc.xpath('//*[@id="tt-dias-add"]')
    assert doc.xpath('//*[@id="tt-dias-empty"]')


def test_la_pantalla_no_trae_scripts_inline(esc, client_as):
    html = client_as(esc.admin).get(f"{URL}?anio={ANIO}").text
    cuerpo = html.split('id="tt-dias-body"', 1)[1].split("</main>", 1)[0]
    assert "<script" not in cuerpo


def test_sin_guarda_de_fase_responde_con_el_corte_en_3(esc, client_as, monkeypatch):
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: 3))
    assert client_as(esc.admin).get(f"{URL}?anio={ANIO}").status_code == 200


# ---------------------------------------------------------------------------
# Listado por año
# ---------------------------------------------------------------------------
def test_lista_solo_el_anio_pedido_y_navega(esc, client_as, db_session):
    for d in (date(ANIO, 3, 4), date(ANIO + 1, 1, 2)):
        db_session.add(NonWorkingDay(day=d, description=f"Dia {d.year}", created_by_id=esc.admin.id))
    db_session.flush()
    resp = client_as(esc.admin).get(f"{URL}/body?anio={ANIO}")
    assert resp.status_code == 200
    doc = lxml.html.fromstring(resp.text)
    filas = doc.xpath('//div[@id="tt-dias-list"]/div')
    assert len(filas) == 1
    texto = " ".join(filas[0].text_content().split())
    assert f"4 mar {ANIO}" in texto and f"Dia {ANIO}" in texto
    assert doc.xpath('//*[@id="tt-dias-prev"]') and doc.xpath('//*[@id="tt-dias-next"]')
    assert f"anio={ANIO + 1}" in doc.xpath('//*[@id="tt-dias-next"]/@hx-get')[0]


def test_anio_basura_cae_al_actual(esc, client_as):
    from itcj2.core.utils.timezone import db_now
    resp = client_as(esc.admin).get(f"{URL}/body?anio=abc")
    assert resp.status_code == 200
    doc = lxml.html.fromstring(resp.text)
    assert doc.xpath('//*[@id="tt-dias-year"]')[0].text_content().strip() == str(db_now().date().year)


# ---------------------------------------------------------------------------
# Alta
# ---------------------------------------------------------------------------
def test_alta_de_rango_cuenta_solo_habiles(esc, client_as, db_session):
    # Lun 5 a dom 11 de marzo de 2091: 5 hábiles y 2 de fin de semana.
    resp = client_as(esc.admin).post(URL + "/agregar", data={
        "anio": str(ANIO), "start": f"{ANIO}-03-05", "end": f"{ANIO}-03-11",
        "description": "Semana de prueba"})
    assert resp.status_code == 200, resp.text[:400]
    assert _hdr(resp, "X-Tt-Notice").startswith("Se registraron 5 días inhábiles")
    assert _dias(db_session) == [date(ANIO, 3, d) for d in (5, 6, 7, 8, 9)]
    reg = audit_query(db_session).filter_by(action="non_working_day.added").all()
    assert len(reg) == 1 and reg[0].actor_id == esc.admin.id
    doc = lxml.html.fromstring(resp.text)
    assert len(doc.xpath('//div[@id="tt-dias-list"]/div')) == 5


def test_alta_de_un_dia_sin_fin_usa_el_mismo_dia(esc, client_as, db_session):
    resp = client_as(esc.admin).post(URL + "/agregar", data={
        "anio": str(ANIO), "start": f"{ANIO}-05-01", "end": "", "description": "Dia del trabajo"})
    assert resp.status_code == 200
    assert _hdr(resp, "X-Tt-Notice").startswith("Se registraron 1 día inhábil")
    assert _dias(db_session) == [date(ANIO, 5, 1)]


def test_error_de_validacion_da_200_con_mensaje_y_conserva_lo_tecleado(esc, client_as, db_session):
    resp = client_as(esc.admin).post(URL + "/agregar", data={
        "anio": str(ANIO), "start": f"{ANIO}-03-10", "end": f"{ANIO}-03-05",
        "description": "Al reves"})
    assert resp.status_code == 200
    assert not resp.headers.get("X-Tt-Notice")
    doc = lxml.html.fromstring(resp.text)
    assert "posterior" in doc.xpath('//*[@id="tt-dias-error"]')[0].text_content()
    assert doc.xpath('//input[@name="description"]/@value') == ["Al reves"]
    assert _dias(db_session) == []


def test_fechas_vacias_o_ilegibles_dan_200_con_mensaje(esc, client_as, db_session):
    for start in ("", "no-es-fecha"):
        resp = client_as(esc.admin).post(URL + "/agregar", data={
            "anio": str(ANIO), "start": start, "end": "", "description": "X"})
        assert resp.status_code == 200
        assert lxml.html.fromstring(resp.text).xpath('//*[@id="tt-dias-error"]')
    assert _dias(db_session) == []


def test_descripcion_vacia_da_200_con_mensaje(esc, client_as, db_session):
    resp = client_as(esc.admin).post(URL + "/agregar", data={
        "anio": str(ANIO), "start": f"{ANIO}-03-05", "end": "", "description": "   "})
    assert resp.status_code == 200
    assert "descripción" in lxml.html.fromstring(resp.text).xpath(
        '//*[@id="tt-dias-error"]')[0].text_content()
    assert _dias(db_session) == []


# ---------------------------------------------------------------------------
# Baja
# ---------------------------------------------------------------------------
def _sembrar(db, admin, dias):
    for d in dias:
        db.add(NonWorkingDay(day=d, description="Sembrado", created_by_id=admin.id))
    db.flush()


def test_quitar_un_dia(esc, client_as, db_session):
    _sembrar(db_session, esc.admin, [date(ANIO, 3, 5), date(ANIO, 3, 6)])
    resp = client_as(esc.admin).post(URL + "/quitar", data={"anio": str(ANIO), "start": f"{ANIO}-03-05"})
    assert resp.status_code == 200
    assert _hdr(resp, "X-Tt-Notice") == "Se quitaron 1 día inhábil."
    assert _dias(db_session) == [date(ANIO, 3, 6)]
    assert audit_query(db_session).filter_by(action="non_working_day.removed").count() == 1


def test_quitar_un_rango(esc, client_as, db_session):
    _sembrar(db_session, esc.admin, [date(ANIO, 3, d) for d in (5, 6, 7, 8)])
    resp = client_as(esc.admin).post(URL + "/quitar", data={
        "anio": str(ANIO), "start": f"{ANIO}-03-05", "end": f"{ANIO}-03-07"})
    assert _hdr(resp, "X-Tt-Notice") == "Se quitaron 3 días inhábiles."
    assert _dias(db_session) == [date(ANIO, 3, 8)]


def test_el_formulario_de_rango_manda_su_modo(esc, client_as, db_session):
    _sembrar(db_session, esc.admin, [date(ANIO, 3, 5)])
    doc = lxml.html.fromstring(client_as(esc.admin).get(f"{URL}?anio={ANIO}").text)
    assert doc.xpath('//form[@id="tt-dias-remove"]//input[@name="mode"]/@value') == ["range"]
    # La X de una fila (un día suelto) no lleva modo: sigue siendo `end = start`.
    assert not doc.xpath('//form[@class="tt-dias-rm"]//input[@name="mode"]')


def test_quitar_un_rango_sin_al_da_200_con_mensaje_y_no_borra(esc, client_as, db_session):
    """M5 (revisión final): con «Al» vacío el servidor tomaba `end = start` y quitaba
    UN día tras una confirmación que hablaba de un rango."""
    _sembrar(db_session, esc.admin, [date(ANIO, 3, 5), date(ANIO, 3, 6)])

    resp = client_as(esc.admin).post(URL + "/quitar", data={
        "anio": str(ANIO), "mode": "range", "start": f"{ANIO}-03-05", "end": ""})

    assert resp.status_code == 200
    assert not resp.headers.get("X-Tt-Notice")
    (error,) = lxml.html.fromstring(resp.text).xpath('//*[@id="tt-dias-error"]')
    assert "la de fin del rango" in error.text_content()
    assert _dias(db_session) == [date(ANIO, 3, 5), date(ANIO, 3, 6)]
    assert audit_query(db_session).filter_by(action="non_working_day.removed").count() == 0


def test_quitar_un_rango_completo_con_modo(esc, client_as, db_session):
    _sembrar(db_session, esc.admin, [date(ANIO, 3, 5), date(ANIO, 3, 6)])

    resp = client_as(esc.admin).post(URL + "/quitar", data={
        "anio": str(ANIO), "mode": "range", "start": f"{ANIO}-03-05", "end": f"{ANIO}-03-06"})

    assert _hdr(resp, "X-Tt-Notice") == "Se quitaron 2 días inhábiles."
    assert _dias(db_session) == []


def test_quitar_un_rango_invalido_da_200_con_mensaje(esc, client_as, db_session):
    _sembrar(db_session, esc.admin, [date(ANIO, 3, 5)])
    resp = client_as(esc.admin).post(URL + "/quitar", data={
        "anio": str(ANIO), "start": f"{ANIO}-03-09", "end": f"{ANIO}-03-05"})
    assert resp.status_code == 200
    assert lxml.html.fromstring(resp.text).xpath('//*[@id="tt-dias-error"]')
    assert _dias(db_session) == [date(ANIO, 3, 5)]


# ---------------------------------------------------------------------------
# Solo lectura
# ---------------------------------------------------------------------------
def test_sin_api_manage_no_ve_formularios_y_el_post_da_400(esc, client_as, db_session):
    _sembrar(db_session, esc.admin, [date(ANIO, 3, 5)])
    cliente = client_as(esc.lector)
    resp = cliente.get(f"{URL}?anio={ANIO}")
    assert resp.status_code == 200
    doc = lxml.html.fromstring(resp.text)
    assert doc.xpath('//div[@id="tt-dias-list"]/div')          # ve la lista
    assert not doc.xpath('//*[@id="tt-dias-add"]')
    assert not doc.xpath('//*[@id="tt-dias-remove"]')
    assert not doc.xpath('//form[contains(@hx-post, "quitar")]')

    r1 = cliente.post(URL + "/agregar", data={
        "anio": str(ANIO), "start": f"{ANIO}-04-01", "description": "No"})
    r2 = cliente.post(URL + "/quitar", data={"anio": str(ANIO), "start": f"{ANIO}-03-05"})
    for r in (r1, r2):
        assert r.status_code == 400
        assert _hdr(r, "X-Tt-Error")
    assert _dias(db_session) == [date(ANIO, 3, 5)]


def test_usuario_sin_permiso_no_puede_postear(esc, client_as):
    assert client_as(esc.otro).post(URL + "/agregar", data={
        "start": f"{ANIO}-04-01", "description": "No"}).status_code == 403
