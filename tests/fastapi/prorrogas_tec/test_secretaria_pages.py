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


def test_lector_solo_ve_sus_pestanas(client_as, lector):
    page = client_as(lector).get(f"{BASE}/estadisticas").text
    assert f'href="{BASE}/estudiantes"' in page
    assert f'href="{BASE}/documentos"' not in page and f'href="{BASE}/configuracion"' not in page


@pytest.mark.parametrize("tab", ["documentos", "configuracion"])
def test_lector_no_abre_lo_que_no_le_toca(client_as, lector, tab):  # Review Focus 5
    assert client_as(lector).get(f"{BASE}/{tab}", follow_redirects=False).status_code == 403


def test_raiz_lleva_a_la_primera_pestana_permitida(client_as, make_user, make_role, grant):
    u = make_user()
    grant(u, make_role("solo_stats", ["prorrogas_tec.secretaria.page.estadisticas"]))
    r = client_as(u).get(BASE, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == f"{BASE}/estadisticas"


def test_admin_global_entra_sin_rol_en_la_app(client_as, make_user):
    c = client_as(make_user(first_name="GLOBAL", last_name="ADMIN"), role="admin")
    assert c.get(f"{BASE}/documentos").status_code == 200
    r = c.get("/prorrogas/", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == BASE


def test_raiz_sin_sesion_va_al_login(client):
    r = client.get(BASE, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/itcj/login"


def test_la_pagina_publica_los_permisos_del_usuario(client_as, lector):
    page = client_as(lector).get(f"{BASE}/estudiantes").text
    assert "prorrogas_tec.requests.api.read.all" in page and "prorrogas_tec.payments.api.record" not in page
