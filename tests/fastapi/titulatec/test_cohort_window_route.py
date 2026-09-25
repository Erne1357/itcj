"""La ruta que abre y cierra la convocatoria. Es el único invocador de set_window.

`titulatec.cohort.api.update` lleva sembrado desde el primer DML y no gateaba
NADA. Aquí empieza a gatear, y con un solo código en la lista: `require_page_app`
la evalúa como OR (`dependencies.py:131`) y `pages/admin.py:16-29` documenta cómo
un `dashboard.*` de más ya abrió una vez las convocatorias al encargado de
carrera.

Regla de la casa: ninguna aserción negativa va sola. Cada 403 se empareja con la
jefa entrando al MISMO recurso.
"""
import re
from datetime import date, timedelta

import pytest

from tests.fastapi.titulatec.conftest import HEAD_PERMS

# La jefa de verdad tiene `cohort.api.update`; el set por defecto del harness no
# lo trae, así que se añade explícitamente para que el positivo pruebe el gate.
HEAD_CON_VENTANA = HEAD_PERMS + ("titulatec.cohort.api.update",)


@pytest.fixture()
def escenario(make_head, make_app_user_without_perms, make_cohort):
    jefa = make_head(perm_codes=HEAD_CON_VENTANA)
    sin_permiso = make_app_user_without_perms()
    cohort = make_cohort(status="draft")
    return {"jefa": jefa, "sin_permiso": sin_permiso, "cohort": cohort}


def _url(cohort) -> str:
    return f"/titulatec/admin/cohorts/{cohort.id}/ventana"


def test_la_jefa_abre_la_convocatoria_y_queda_escrita(escenario, client_as, db_session):
    cohort = escenario["cohort"]
    apertura = date.today()
    cierre = date.today() + timedelta(days=30)

    resp = client_as(escenario["jefa"]).post(
        _url(cohort),
        data={"status": "open", "opens_at": apertura.isoformat(),
              "closes_at": cierre.isoformat()},
        follow_redirects=False,
    )

    assert resp.status_code == 200
    assert 'id="cohort-window"' in resp.text, (
        "La respuesta debe ser el parcial re-renderizable; htmx swappea "
        "#cohort-window con outerHTML y necesita la raíz de vuelta."
    )
    db_session.refresh(cohort)
    assert cohort.status == "open"
    assert cohort.opens_at == apertura
    assert cohort.closes_at == cierre


def test_cerrar_desde_la_ruta_pausa_los_procesos(escenario, client_as, make_student,
                                                 make_process, db_session):
    """La prueba de que la ruta CABLEA set_window y no solo escribe columnas."""
    cohort = escenario["cohort"]
    cohort.status = "open"
    db_session.flush()
    proc = make_process(make_student(), cohort=cohort, status="active")

    resp = client_as(escenario["jefa"]).post(
        _url(cohort), data={"status": "closed", "opens_at": "", "closes_at": ""},
        follow_redirects=False,
    )

    assert resp.status_code == 200
    db_session.refresh(proc)
    assert proc.status == "on_hold"


def test_el_cierre_anterior_a_la_apertura_se_rechaza(escenario, client_as, db_session):
    cohort = escenario["cohort"]
    hoy = date.today()

    resp = client_as(escenario["jefa"]).post(
        _url(cohort),
        data={"status": "open", "opens_at": hoy.isoformat(),
              "closes_at": (hoy - timedelta(days=1)).isoformat()},
        follow_redirects=False,
    )

    assert resp.status_code == 400
    assert "X-Tt-Error" in resp.headers
    db_session.refresh(cohort)
    assert cohort.status == "draft", "Un rechazo no puede dejar la ventana a medias."


def test_el_mensaje_del_rechazo_llega_legible(escenario, client_as):
    """El `ValueError` de `set_window` es el texto que LEE la jefa, no un 400 mudo.

    Va percent-codificado (`_hdr`) porque los headers HTTP son latin-1;
    `titulatec-utils.js::decodeHeaderMsg` lo desanda antes del toast. Si la ruta
    se tragara la excepción y devolviera un 400 pelado —o un 500—, aquí se ve.
    """
    from urllib.parse import unquote

    hoy = date.today()
    resp = client_as(escenario["jefa"]).post(
        _url(escenario["cohort"]),
        data={"status": "open", "opens_at": hoy.isoformat(),
              "closes_at": (hoy - timedelta(days=1)).isoformat()},
        follow_redirects=False,
    )

    assert resp.status_code == 400
    assert unquote(resp.headers["X-Tt-Error"]) == (
        "El cierre no puede ser anterior a la apertura."
    )


def test_un_estado_inventado_se_rechaza(escenario, client_as, db_session):
    """El `<select>` ofrece tres estados; un POST a mano puede mandar cualquiera.

    `set_window` valida ANTES de escribir, así que la convocatoria no se mueve.
    """
    from urllib.parse import unquote

    cohort = escenario["cohort"]
    resp = client_as(escenario["jefa"]).post(
        _url(cohort), data={"status": "archivada", "opens_at": "", "closes_at": ""},
        follow_redirects=False,
    )

    assert resp.status_code == 400
    assert unquote(resp.headers["X-Tt-Error"]) == (
        "El estado debe ser borrador, abierta o cerrada."
    )
    db_session.refresh(cohort)
    assert cohort.status == "draft"


def test_una_convocatoria_inexistente_da_404(escenario, client_as):
    resp = client_as(escenario["jefa"]).post(
        "/titulatec/admin/cohorts/999999999/ventana",
        data={"status": "open", "opens_at": "", "closes_at": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 404


def test_sin_el_permiso_no_pasa_y_la_jefa_si(escenario, client_as):
    cohort = escenario["cohort"]
    datos = {"status": "closed", "opens_at": "", "closes_at": ""}

    r_sin = client_as(escenario["sin_permiso"]).post(_url(cohort), data=datos,
                                                     follow_redirects=False)
    r_jefa = client_as(escenario["jefa"]).post(_url(cohort), data=datos,
                                               follow_redirects=False)

    assert r_sin.status_code == 403, (
        "Solo `titulatec.cohort.api.update` abre esta ruta. Si es 200, revisa "
        "que no se haya colado un `dashboard.*` en la lista: es un OR."
    )
    assert r_jefa.status_code == 200


def test_el_encargado_de_carrera_no_abre_la_ventana_y_la_jefa_si(
        escenario, make_officer, make_program, client_as):
    """El incidente de `_COHORT_PERMS` (`pages/admin.py:16-29`), en su forma exacta.

    `require_page_app` evalúa `perms=[...]` como OR. El encargado de carrera SÍ
    tiene `titulatec.dashboard.school_services` (está en `OFFICER_PERMS`), que es
    justo el código que una vez se coló en la lista y dejó los `cohort.*`
    decorativos — hubo que deshacerlo en las rutas Y en el DML.

    `test_sin_el_permiso_no_pasa_y_la_jefa_si` NO cubre esto: su actor
    (`make_app_user_without_perms`) solo tiene un permiso inerte, así que un
    `dashboard.*` de más en la lista lo seguiría dejando fuera y el mutante
    sobreviviría. Medido: con `perms=[..., "titulatec.dashboard.school_services"]`
    la suite entera pasaba en verde sin este test. Por eso va aparte, con el
    actor que de verdad tiene el código peligroso.
    """
    encargado, _pos = make_officer([make_program("Ing. de prueba T17")])
    cohort = escenario["cohort"]
    datos = {"status": "closed", "opens_at": "", "closes_at": ""}

    r_enc = client_as(encargado).post(_url(cohort), data=datos, follow_redirects=False)
    r_jefa = client_as(escenario["jefa"]).post(_url(cohort), data=datos,
                                               follow_redirects=False)

    assert r_enc.status_code == 403, (
        "Se coló un `dashboard.*` en `perms`: la lista es un OR y el encargado "
        "de carrera tiene `titulatec.dashboard.school_services`."
    )
    assert r_jefa.status_code == 200


def test_el_anonimo_va_al_login(escenario, client):
    client.cookies.clear()
    resp = client.post(_url(escenario["cohort"]),
                       data={"status": "open", "opens_at": "", "closes_at": ""},
                       follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["location"] == "/itcj/login"


def test_el_detalle_muestra_el_editor_a_quien_puede_editar(escenario, client_as):
    """Sin esto la ventana solo se alcanza tecleando la URL del POST."""
    resp = client_as(escenario["jefa"]).get(
        f"/titulatec/admin/cohorts/{escenario['cohort'].id}?tab=resumen",
        follow_redirects=False,
    )

    assert resp.status_code == 200
    assert 'id="cohort-window"' in resp.text
    assert f"/titulatec/admin/cohorts/{escenario['cohort'].id}/ventana" in resp.text


def test_el_editor_precarga_las_fechas_que_ya_tiene_la_convocatoria(
        escenario, client_as, make_cohort, db_session):
    """`set_window` SIEMPRE escribe las DOS fechas con lo que reciba.

    No existe "conservar lo que había": un `<input>` vacío borra la fecha. Así
    que si el editor no llega precargado, la jefa que solo quería cambiar el
    estado se lleva por delante la ventana entera sin enterarse. Esta prueba fija
    la precarga, que es lo único que lo impide.
    """
    apertura = date.today() + timedelta(days=3)
    cierre = date.today() + timedelta(days=40)
    cohort = make_cohort(status="open", opens_at=apertura, closes_at=cierre)

    resp = client_as(escenario["jefa"]).get(
        f"/titulatec/admin/cohorts/{cohort.id}?tab=resumen", follow_redirects=False)

    assert resp.status_code == 200
    assert f'value="{apertura.isoformat()}"' in resp.text, (
        "El input de apertura llegó vacío: `<input type=\"date\">` solo acepta "
        "ISO y un formato distinto lo deja en blanco."
    )
    assert f'value="{cierre.isoformat()}"' in resp.text


def test_quien_solo_ve_la_convocatoria_no_recibe_el_formulario(
        make_app_user_without_perms, make_cohort, client_as):
    """El detalle es de `cohort.page.list`; el editor es de `cohort.api.update`.

    Actor con la primera y sin la segunda: entra al detalle (200) y ve la ventana
    en SOLO LECTURA. Si el `<form>` se le pinta, el gate del POST sería la única
    defensa y la UI estaría mintiendo. Rol propio y no `make_head`, porque
    `make_role` es idempotente POR NOMBRE y acumula permisos: una segunda jefa
    "sin update" heredaría el update de la primera.
    """
    mirona = make_app_user_without_perms(perm_codes=("titulatec.cohort.page.list",))
    cohort = make_cohort(status="draft")

    resp = client_as(mirona).get(f"/titulatec/admin/cohorts/{cohort.id}?tab=resumen",
                                 follow_redirects=False)

    assert resp.status_code == 200
    assert 'id="cohort-window"' in resp.text
    assert f"/titulatec/admin/cohorts/{cohort.id}/ventana" not in resp.text, (
        "Sin `cohort.api.update` no se pinta el formulario de la ventana."
    )


# ---------------------------------------------------------------------------
# Interruptor «Aprobación automática (SII)» (spec 2026-09-25 §3.5, S8). Vive en
# el panel de la ventana y lo gobierna el MISMO permiso. Solo existe en el modo
# `sii`: fuera de él ni se pinta ni un POST directo lo mueve. Una casilla sin
# marcar no viaja en el formulario, así que el panel manda además
# `sii_auto_present=1`: sin esa marca (un formulario viejo en caché) el
# interruptor NO se toca.
# ---------------------------------------------------------------------------
INTERRUPTOR = 'name="sii_auto_approve"'


@pytest.fixture()
def modo_sii(monkeypatch):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    monkeypatch.setattr(EnrollmentRequestService, "reviewer_mode",
                        staticmethod(lambda: "sii"))


def _resumen(client, cohort):
    return client.get(f"/titulatec/admin/cohorts/{cohort.id}?tab=resumen",
                      follow_redirects=False)


def test_en_modo_sii_el_panel_trae_el_interruptor_encendido_por_omision(
        escenario, client_as, modo_sii):
    resp = _resumen(client_as(escenario["jefa"]), escenario["cohort"])

    assert resp.status_code == 200
    ventana = resp.text.split('id="cohort-window"', 1)[1]
    assert "Aprobación automática (SII)" in ventana
    casilla = re.search(r'<input[^>]*name="sii_auto_approve"[^>]*>', ventana)
    assert casilla and "checked" in casilla.group(0)
    assert 'name="sii_auto_present"' in ventana


def test_fuera_del_modo_sii_no_hay_interruptor(escenario, client_as):
    resp = _resumen(client_as(escenario["jefa"]), escenario["cohort"])

    assert resp.status_code == 200
    assert 'id="cohort-window"' in resp.text
    assert INTERRUPTOR not in resp.text
    assert "Aprobación automática" not in resp.text


def test_apagar_el_interruptor_persiste_y_se_repinta_apagado(
        escenario, client_as, db_session, modo_sii):
    cohort = escenario["cohort"]

    resp = client_as(escenario["jefa"]).post(
        _url(cohort), data={"status": "open", "opens_at": "", "closes_at": "",
                            "sii_auto_present": "1"},
        follow_redirects=False)

    assert resp.status_code == 200
    db_session.refresh(cohort)
    assert cohort.sii_auto_approve is False
    assert cohort.status == "open", "la ventana se guarda en el mismo envío"
    casilla = re.search(r'<input[^>]*name="sii_auto_approve"[^>]*>', resp.text)
    assert casilla and "checked" not in casilla.group(0)


def test_encender_el_interruptor_persiste(escenario, client_as, db_session, modo_sii):
    cohort = escenario["cohort"]
    cohort.sii_auto_approve = False
    db_session.flush()

    resp = client_as(escenario["jefa"]).post(
        _url(cohort), data={"status": "draft", "opens_at": "", "closes_at": "",
                            "sii_auto_present": "1", "sii_auto_approve": "1"},
        follow_redirects=False)

    assert resp.status_code == 200
    db_session.refresh(cohort)
    assert cohort.sii_auto_approve is True


def test_sin_la_marca_del_panel_el_interruptor_no_se_toca(
        escenario, client_as, db_session, modo_sii):
    """Un formulario sin `sii_auto_present` (caché, POST a mano) no lo apaga."""
    cohort = escenario["cohort"]

    resp = client_as(escenario["jefa"]).post(
        _url(cohort), data={"status": "open", "opens_at": "", "closes_at": ""},
        follow_redirects=False)

    assert resp.status_code == 200
    db_session.refresh(cohort)
    assert cohort.sii_auto_approve is True


def test_fuera_del_modo_sii_un_post_directo_no_mueve_el_interruptor(
        escenario, client_as, db_session):
    cohort = escenario["cohort"]

    resp = client_as(escenario["jefa"]).post(
        _url(cohort), data={"status": "open", "opens_at": "", "closes_at": "",
                            "sii_auto_present": "1"},
        follow_redirects=False)

    assert resp.status_code == 200
    db_session.refresh(cohort)
    assert cohort.sii_auto_approve is True


def test_una_ventana_invalida_no_mueve_el_interruptor(
        escenario, client_as, db_session, modo_sii):
    cohort = escenario["cohort"]
    hoy = date.today()

    resp = client_as(escenario["jefa"]).post(
        _url(cohort), data={"status": "open", "opens_at": hoy.isoformat(),
                            "closes_at": (hoy - timedelta(days=1)).isoformat(),
                            "sii_auto_present": "1"},
        follow_redirects=False)

    assert resp.status_code == 400
    db_session.refresh(cohort)
    assert cohort.sii_auto_approve is True
    assert cohort.status == "draft"


def test_sin_el_permiso_el_interruptor_no_se_mueve_y_con_el_si(
        escenario, client_as, db_session, modo_sii):
    cohort = escenario["cohort"]
    datos = {"status": "draft", "opens_at": "", "closes_at": "", "sii_auto_present": "1"}

    r_sin = client_as(escenario["sin_permiso"]).post(_url(cohort), data=datos,
                                                     follow_redirects=False)
    db_session.refresh(cohort)
    tras_sin = cohort.sii_auto_approve
    r_jefa = client_as(escenario["jefa"]).post(_url(cohort), data=datos,
                                               follow_redirects=False)

    assert r_sin.status_code == 403
    assert tras_sin is True
    assert r_jefa.status_code == 200
    db_session.refresh(cohort)
    assert cohort.sii_auto_approve is False


def test_en_solo_lectura_el_estado_del_interruptor_se_ve_sin_casilla(
        make_app_user_without_perms, make_cohort, client_as, db_session, modo_sii):
    mirona = make_app_user_without_perms(perm_codes=("titulatec.cohort.page.list",))
    cohort = make_cohort(status="open")
    cohort.sii_auto_approve = False
    db_session.flush()

    resp = client_as(mirona).get(f"/titulatec/admin/cohorts/{cohort.id}?tab=resumen",
                                 follow_redirects=False)

    assert resp.status_code == 200
    ventana = resp.text.split('id="cohort-window"', 1)[1]
    assert INTERRUPTOR not in ventana
    texto = " ".join(re.sub(r"<[^>]+>", " ", ventana).split())
    assert "Aprobación automática (SII) apagada" in texto


def test_la_ventana_y_el_interruptor_se_confirman_en_un_solo_commit(
        escenario, client_as, db_session, modo_sii, monkeypatch):
    """Una sola transacción. Con un segundo commit solo para el interruptor, un
    fallo entre los dos dejaba la ventana guardada con un 500 y el interruptor
    sin mover. El interruptor viaja en el commit de `CohortService.set_window`."""
    cohort = escenario["cohort"]
    commits = []
    confirmar = db_session.commit

    def _cuenta():
        commits.append(cohort.sii_auto_approve)
        return confirmar()

    monkeypatch.setattr(db_session, "commit", _cuenta)

    resp = client_as(escenario["jefa"]).post(
        _url(cohort), data={"status": "open", "opens_at": "", "closes_at": "",
                            "sii_auto_present": "1"},
        follow_redirects=False)

    assert resp.status_code == 200
    assert commits == [False], "un commit, y el interruptor ya va apagado en él"
    db_session.refresh(cohort)
    assert cohort.status == "open"
    assert cohort.sii_auto_approve is False
