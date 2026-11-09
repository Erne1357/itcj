from urllib.parse import quote

API = "/api/prorrogas/v2/solicitudes"


def _ids(r):
    return [i["id"] for i in r.json()["items"]]


def test_filtra_por_estado(client_as, lector, make_aceptada, solicitud, db_session):
    rechazada = make_aceptada()
    rechazada.status = "rechazada"
    db_session.flush()
    ids = _ids(client_as(lector).get(f"{API}/todas?estado=rechazada&per_page=100"))
    assert rechazada.id in ids and solicitud.id not in ids


def test_incluye_historicas_sin_semestre(client_as, lector, make_historica):
    h = make_historica(control_number="99420999")
    r = client_as(lector).get(f"{API}/todas?q=99420999")
    assert _ids(r) == [h.id] and r.json()["items"][0]["semestre"] == "enero – junio 2089"


def test_filtra_por_semestre(client_as, lector, aceptada):
    r = client_as(lector).get(f"{API}/todas?semestre={quote('enero – junio 2091')}&per_page=100")
    assert aceptada.id in _ids(r) and "enero – junio 2091" in r.json()["semestres"]


def test_estado_invalido(client_as, lector):
    r = client_as(lector).get(f"{API}/todas?estado=xyz")
    assert r.status_code == 400 and r.json()["error"] == "estado_invalido"


def test_limites_de_paginacion(client_as, lector):
    assert client_as(lector).get(f"{API}/todas?per_page=500").json()["per_page"] == 100


def test_detalle_trae_historial(client_as, lector, aceptada, db_session):
    from itcj2.apps.prorrogas_tec.services.events import log_event
    log_event(db_session, event_type="solicitud_aceptada", request_id=aceptada.id)
    db_session.flush()
    assert client_as(lector).get(f"{API}/{aceptada.id}").json()["historial"][0]["tipo"] == "solicitud_aceptada"


def test_comodines_del_buscador_son_literales(client_as, lector, aceptada):
    for q in ("%", "_"):
        assert client_as(lector).get(f"{API}/todas?q={quote(q)}").json()["total"] == 0


def test_detalle_no_expone_rutas(client_as, lector, aceptada, db_session):
    aceptada.reference_path = "/disco/secreto/ref.pdf"
    db_session.flush()
    assert "/disco/secreto" not in client_as(lector).get(f"{API}/{aceptada.id}").text
