from datetime import date

import pytest

from itcj2.apps.prorrogas_tec.services.caja_service import CajaService
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.identity import folio

HOY = date(2091, 3, 10)
VENCIDO = [("1000.00", date(2091, 2, 1)), ("1000.00", date(2091, 5, 1))]
AL_DIA = [("500.00", date(2091, 4, 1))]


def _lista(db, periodo, **kw):
    return CajaService.listar(db, semestre=periodo.id, today=HOY, **kw)


def _ids(d):
    return [i["id"] for i in d["items"]]


def test_por_cobrar_deja_fuera_sin_plan_y_liquidadas(db_session, periodo, aceptada, make_aceptada, con_plan):
    con_plan(make_aceptada(), AL_DIA, ["500.00"])
    debe = con_plan(make_aceptada(), AL_DIA)
    d = _lista(db_session, periodo)
    assert _ids(d) == [debe.id] and d["total"] == 1
    assert d["conteos"] == {"todos": 1, "con_adeudo": 0, "al_corriente": 1}


@pytest.mark.parametrize("filtro, cuales", [("todos", {"v", "c"}), ("con_adeudo", {"v"}), ("al_corriente", {"c"})])
def test_pestanas(db_session, periodo, make_aceptada, con_plan, filtro, cuales):
    filas = {"v": con_plan(make_aceptada(), VENCIDO), "c": con_plan(make_aceptada(), AL_DIA)}
    assert set(_ids(_lista(db_session, periodo, filtro=filtro))) == {filas[k].id for k in cuales}


@pytest.mark.parametrize("orden, esperado", [
    ("urgente", ["vencido", "pronto", "tarde"]), ("proximo", ["vencido", "pronto", "tarde"]),
    ("saldo", ["tarde", "vencido", "pronto"]), ("nombre", ["pronto", "tarde", "vencido"]),
])
def test_orden(db_session, periodo, make_aceptada, con_plan, orden, esperado):
    filas = {"vencido": ("ZÚÑIGA PRUEBA UNO", "300.00", date(2091, 2, 1)),
             "pronto": ("ÁLVAREZ PRUEBA DOS", "100.00", date(2091, 4, 1)),
             "tarde": ("BENÍTEZ PRUEBA TRES", "900.00", date(2091, 5, 1))}
    ids = {}
    for k, (nombre, monto, dia) in filas.items():
        r = con_plan(make_aceptada(), [(monto, dia)])
        r.student_name, ids[k] = nombre, r.id
    assert _ids(_lista(db_session, periodo, orden=orden)) == [ids[k] for k in esperado]


def test_ocho_por_pagina(db_session, periodo, make_aceptada, con_plan):
    for _ in range(9):
        con_plan(make_aceptada(), AL_DIA)
    uno, dos = _lista(db_session, periodo), _lista(db_session, periodo, page=2)
    assert (len(uno["items"]), len(dos["items"]), uno["total"], uno["per_page"]) == (8, 1, 9, 8)


def test_fila(db_session, periodo, make_aceptada, con_plan):
    r = con_plan(make_aceptada("99430006"), VENCIDO, ["400.00"])
    assert _lista(db_session, periodo)["items"][0] == {
        "id": r.id, "control": "99430006", "nombre": "ESTUDIANTE PRUEBA", "semestre": "enero – junio 2091",
        "folio": folio(r), "situacion": "atrasada", "siguiente": {"fecha": "2091-02-01", "monto": "600.00", "faltan": 2}}


def test_busqueda_abarca_sin_plan_y_liquidadas(db_session, periodo, make_aceptada, con_plan):
    sin_plan = make_aceptada("99430001")
    liquidada = con_plan(make_aceptada("99430002"), AL_DIA, ["500.00"])
    d = _lista(db_session, periodo, q="9943000")
    assert set(_ids(d)) == {sin_plan.id, liquidada.id} and d["conteos"] is None
    assert {i["situacion"]: i["siguiente"] for i in d["items"]} == {"sin_plan": None, "liquidada": None}


@pytest.mark.parametrize("q", ["nuñez", "NUNEZ", "núñez", "Jose  Nunez", "jose salas"])
def test_busqueda_sin_acentos_mayusculas_ni_orden(db_session, periodo, make_aceptada, q):  # Review Focus 3
    r = make_aceptada("99430003")
    r.student_name = "NÚÑEZ SALAS JOSÉ"
    assert _ids(_lista(db_session, periodo, q=q)) == [r.id]


def test_busqueda_abarca_todos_los_semestres_o_el_elegido(db_session, periodo, make_historica):
    from itcj2.core.models.academic_period import AcademicPeriod
    otro = AcademicPeriod(code="T90001", name="Prórrogas prueba 2", start_date=date(2092, 1, 10),
                          end_date=date(2092, 6, 20), status="INACTIVE")
    db_session.add(otro)
    db_session.flush()
    h = make_historica(periodo=otro, control_number="99430004")
    assert _ids(CajaService.listar(db_session, q="99430004", today=HOY)) == [h.id]
    assert _ids(_lista(db_session, periodo, q="99430004")) == []


def test_historica_sin_semestre_queda_fuera(db_session, make_historica):
    make_historica(control_number="99430005", pagadas=())
    assert CajaService.listar(db_session, q="99430005", today=HOY)["items"] == []


def test_historica_con_semestre_se_cobra(db_session, periodo, make_historica):
    h = make_historica(periodo=periodo)
    assert _ids(_lista(db_session, periodo, filtro="con_adeudo")) == [h.id]


@pytest.mark.parametrize("estado", ["pendiente", "rechazada", "cancelada", "cerrada_sin_plan"])
def test_solo_aceptadas(db_session, periodo, aceptada, con_plan, estado):
    con_plan(aceptada, AL_DIA)
    aceptada.status = estado
    db_session.flush()
    assert _lista(db_session, periodo, q=aceptada.control_number)["items"] == []


def test_busqueda_maximo_cincuenta(db_session, periodo, make_aceptada, monkeypatch):
    assert CajaService.MAX_RESULTADOS == 50
    monkeypatch.setattr(CajaService, "MAX_RESULTADOS", 2)
    for i in range(3):
        make_aceptada(f"9943010{i}")
    d = _lista(db_session, periodo, q="9943010")
    assert len(d["items"]) == 2 and d["total"] == 3


@pytest.mark.parametrize("kw, code", [({"filtro": "x"}, "filtro_invalido"), ({"orden": "x"}, "orden_invalido")])
def test_parametros_invalidos(db_session, periodo, kw, code):
    with pytest.raises(ServiceError) as e:
        _lista(db_session, periodo, **kw)
    assert (e.value.code, e.value.status) == (code, 400)
