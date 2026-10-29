from datetime import date

API = "/api/prorrogas/v2/estudiantes"


def test_lista_con_situacion_pagos_y_conteos(client_as, secretaria, aceptada, make_aceptada, con_plan, periodo):
    con_plan(aceptada, [("1000.00", date(2020, 1, 1)), ("1000.00", date(2091, 5, 1))], pagos=["400.00"])
    al_dia = con_plan(make_aceptada(), [("500.00", date(2091, 5, 1))])
    r = client_as(secretaria).get(f"{API}?period_id={periodo.id}&per_page=100")
    assert r.status_code == 200
    filas = {i["id"]: i for i in r.json()["items"]}
    assert filas[aceptada.id]["situacion"] == "atrasada" and filas[aceptada.id]["pagos"] == ["vencida", "pendiente"]
    assert filas[al_dia.id]["situacion"] == "al_corriente" and filas[al_dia.id]["pagados"] == 0
    assert r.json()["conteos"]["con_adeudo"] >= 1
    solo = client_as(secretaria).get(f"{API}?period_id={periodo.id}&filtro=con_adeudo&per_page=100").json()["items"]
    assert aceptada.id in [i["id"] for i in solo] and al_dia.id not in [i["id"] for i in solo]


def test_busqueda_por_control(client_as, secretaria, aceptada, periodo):
    items = client_as(secretaria).get(f"{API}?period_id={periodo.id}&q={aceptada.control_number}").json()["items"]
    assert [i["id"] for i in items] == [aceptada.id]


def test_expediente(client_as, secretaria, aceptada, con_plan):
    con_plan(aceptada, [("1000.00", date(2091, 2, 1)), ("2000.00", date(2091, 4, 1))], pagos=["1000.00"])
    e = client_as(secretaria).get(f"{API}/{aceptada.id}").json()
    assert e["cuenta"]["saldo"] == "2000.00" and e["plan"]["conservadas"] == [1] and e["plan"]["max_nuevas"] == 2
    assert e["recibos"][0]["folio"].startswith("T-") and e["carta"] is None and e["bloqueo"]["avisar_desbloqueo"] is False


def test_pendiente_no_tiene_expediente_y_el_estudiante_no_entra(client_as, secretaria, estudiante, solicitud):
    assert client_as(secretaria).get(f"{API}/{solicitud.id}").status_code == 404
    assert client_as(estudiante).get(f"{API}/{solicitud.id}").status_code == 403
