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
    # Se le dan los permisos de secretaria a mano: la prueba no depende de lo que tenga el admin real en la base.
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


@pytest.mark.parametrize("tab", ["documentos", "configuracion", "caja"])
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


@pytest.mark.parametrize("ruta, cuerpo", [
    ("/api/prorrogas/v2/estudiantes/{id}/plan", {"total": "1000", "parcialidades": []}),
    ("/api/prorrogas/v2/caja/{id}/saldar", {"numero": 1, "folio": "ZZ-X", "fecha": "2091-01-20"}),
    ("/api/prorrogas/v2/estudiantes/{id}/recordar", {}),
    ("/api/prorrogas/v2/solicitudes/{id}/decision", {"aceptar": False, "comentario": "x"}),
    ("/api/prorrogas/v2/invitaciones/qr", None),
    ("/api/prorrogas/v2/estudiantes/{id}/recordar-pendiente", {"que": "firma"}),
    ("/api/prorrogas/v2/estudiantes/{id}/cerrar-sin-plan", {"motivo": "Sin referencia a tiempo."}),
    ("/api/prorrogas/v2/estudiantes/adeudos.xlsx", {"period_id": 1}),
    ("/api/prorrogas/v2/estudiantes/{id}/desbloqueo-avisado", {}),
    ("/api/prorrogas/v2/caja/{id}/recibos/1/anular", {"motivo": "Capturado por error."}),
    ("/api/prorrogas/v2/estudiantes/{id}/parcialidades/1/avisar-inconsistencia", {"motivo": "Motivo de prueba larga"}),
])
def test_lector_no_escribe(client_as, lector, aceptada, ruta, cuerpo):  # Review Focus 5
    assert client_as(lector).post(ruta.format(id=aceptada.id), json=cuerpo).status_code == 403


def test_sin_lectura_no_baja_la_referencia(client_as, estudiante, aceptada):
    assert client_as(estudiante).get(f"/api/prorrogas/v2/estudiantes/{aceptada.id}/referencia.pdf").status_code == 403


def test_lector_si_consulta(client_as, lector, aceptada):
    assert client_as(lector).get(f"/api/prorrogas/v2/estudiantes/{aceptada.id}").status_code == 200


def test_pestana_consulta(client_as, lector):
    page = client_as(lector).get(f"{BASE}/consulta").text
    for texto in ("Consulta", "consulta.js"):
        assert texto in page


@pytest.mark.parametrize("ruta", ["/recibos", "/recibos/1/anular"])
def test_la_secretaria_ya_no_tiene_rutas_de_cobro(client_as, secretaria, aceptada, ruta):
    assert client_as(secretaria).post(f"/api/prorrogas/v2/estudiantes/{aceptada.id}{ruta}", json={}).status_code == 404


def test_estudiantes_js_ya_no_cobra():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[3] / "itcj2/apps/prorrogas_tec/static/js/secretaria/estudiantes.js").read_text(encoding="utf-8")
    for texto in ("/recibos", "Registrar recibo", "payments.api", "shortcut: la secretaria"):
        assert texto not in js


def test_pestana_caja(client_as, cajero):
    page = client_as(cajero).get(f"{BASE}/caja").text
    for texto in ("Busca al alumno o elígelo de la lista para cobrar su siguiente pago.", "No. de control o nombre",
                  "Todos los semestres", "Por cobrar", "Ordenar por", "Más urgente", "Próximo pago", "Saldo mayor",
                  "Nombre (A–Z)", "Con adeudo", "Al corriente", "No hay alumnos en este filtro.",
                  "No encontramos a ese alumno.", "debe acudir a Centro de Cómputo", "caja.js"):
        assert texto in page


def test_cajero_solo_ve_su_pestana_rotulada_estudiantes(client_as, cajero):
    page = client_as(cajero).get(f"{BASE}/caja").text
    assert f'href="{BASE}/caja"' in page and f'href="{BASE}/estudiantes"' not in page
    assert "<span>Estudiantes</span>" in page and "<span>Caja</span>" not in page
    assert '<div class="sec-user-role">Caja</div>' in page and "sec-topnav-one" in page
    assert "prorrogas_tec.payments.api.record" in page


def test_admin_global_ve_las_dos_y_la_de_caja_se_rotula_caja(client_as, make_user):
    page = client_as(make_user(first_name="GLOBAL", last_name="ADMIN"), role="admin").get(f"{BASE}/caja").text
    assert "<span>Caja</span>" in page and "<span>Estudiantes</span>" in page and f'href="{BASE}/estudiantes"' in page


def test_cajero_entra_directo_a_su_pestana(client_as, cajero):
    c = client_as(cajero)
    r = c.get("/prorrogas/", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == BASE
    r = c.get(BASE, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == f"{BASE}/caja"


def test_secretaria_no_ve_caja_y_conserva_su_rotulo(client_as, secretaria):
    c = client_as(secretaria)
    assert c.get(f"{BASE}/caja", follow_redirects=False).status_code == 403
    page = c.get(f"{BASE}/estudiantes").text
    assert f'href="{BASE}/caja"' not in page and "Secretaría · Subdirección Académica" in page
