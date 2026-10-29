def test_anonimo_va_al_login(client):
    r = client.get("/prorrogas/estudiante", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/itcj/login"


def test_estudiante_ve_mi_prorroga_y_la_solicitud(client_as, estudiante):
    c = client_as(estudiante)
    assert "Mi prórroga" in c.get("/prorrogas/estudiante").text
    page = c.get("/prorrogas/estudiante/solicitud").text
    assert "Firmo este documento" in page and "<canvas" in page
    assert '<option value="">Elige tu carrera</option>' in page  # nada preseleccionado a ciegas


def test_la_secretaria_no_entra_a_la_vista_del_estudiante(client_as, secretaria):
    assert client_as(secretaria).get("/prorrogas/estudiante", follow_redirects=False).status_code == 403
