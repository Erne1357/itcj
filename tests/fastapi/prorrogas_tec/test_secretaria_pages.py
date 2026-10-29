import pytest

BASE = "/prorrogas/secretaria"


def test_anonimo_va_al_login(client):
    r = client.get(f"{BASE}/documentos", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/itcj/login"


def test_estudiante_recibe_403(client_as, estudiante):
    assert client_as(estudiante).get(f"{BASE}/documentos", follow_redirects=False).status_code == 403


def test_secretaria_ve_las_cuatro_pestanas_y_documentos(client_as, secretaria):
    r = client_as(secretaria).get(f"{BASE}/documentos")
    assert r.status_code == 200
    for label in ("Estadísticas", "QR y solicitudes", "Estudiantes", "Documentos", "Plantillas"):
        assert label in r.text


def test_raiz_de_secretaria_lleva_a_documentos(client_as, secretaria):
    r = client_as(secretaria).get(BASE, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == f"{BASE}/documentos"


@pytest.mark.parametrize("tab", ["estadisticas", "solicitudes", "estudiantes"])
def test_pestanas_pendientes_muestran_proximamente(client_as, secretaria, tab):
    r = client_as(secretaria).get(f"{BASE}/{tab}")
    assert r.status_code == 200 and "siguiente plan" in r.text


def test_pestana_desconocida_404(client_as, secretaria):
    assert client_as(secretaria).get(f"{BASE}/otra").status_code == 404


def test_aterrizaje_lleva_a_la_secretaria_a_su_vista(client_as, secretaria):
    r = client_as(secretaria).get("/prorrogas/", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == BASE
