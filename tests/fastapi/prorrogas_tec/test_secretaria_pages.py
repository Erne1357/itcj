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


def test_raiz_de_secretaria_lleva_a_solicitudes(client_as, secretaria):
    r = client_as(secretaria).get(BASE, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == f"{BASE}/solicitudes"


def test_pestana_qr_y_solicitudes(client_as, secretaria):
    page = client_as(secretaria).get(f"{BASE}/solicitudes").text
    for texto in ("Código QR", "Invitar manualmente", "Regenerar código", "qrcode-generator@1.4.4", 'integrity="sha384-',
                  "Aceptar prórroga"):
        assert texto in page


def test_pestana_estadisticas(client_as, secretaria):
    page = client_as(secretaria).get(f"{BASE}/estadisticas").text
    for texto in ("Estadísticas de prórrogas", "Solicitudes por carrera", "Cumplimiento de pago",
                  "Detalle por carrera", "chart.js@4.4.0", "estadisticas.js"):
        assert texto in page


def test_ruta_desconocida_da_404(client_as, secretaria):
    assert client_as(secretaria).get(f"{BASE}/nada").status_code == 404


def test_pestana_estudiantes(client_as, secretaria):
    page = client_as(secretaria).get(f"{BASE}/estudiantes").text
    for texto in ("Buscar por nombre o No. de control", "Exportar adeudos", "Con adeudo", "Liquidada",
                  "estudiantes.js"):
        assert texto in page


def test_aterrizaje_lleva_a_la_secretaria_a_su_vista(client_as, secretaria):
    r = client_as(secretaria).get("/prorrogas/", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == BASE


def test_aterrizaje_lleva_al_admin_a_la_vista_nueva_no_a_la_del_fork(client_as, make_user, make_role, grant):
    # El admin de la app tiene los mismos permisos que la secretaria (04_insert_secretaria.sql);
    # /prorrogas/admin/* es la vista vieja del fork que el Plan 2 elimina (spec §12).
    from tests.fastapi.prorrogas_tec.conftest import SECRETARIA_PERMS

    admin = make_user(first_name="ADMIN", last_name="PRUEBA")
    grant(admin, make_role("admin", SECRETARIA_PERMS))
    r = client_as(admin).get("/prorrogas/", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == BASE
