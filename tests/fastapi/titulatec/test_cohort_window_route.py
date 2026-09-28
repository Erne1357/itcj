"""La ruta que abre y cierra la convocatoria. Es el único invocador de set_window.

`titulatec.cohort.api.update` lleva sembrado desde el primer DML y no gateaba
NADA. Aquí empieza a gatear, y con un solo código en la lista: `require_page_app`
la evalúa como OR (`dependencies.py:131`) y `pages/admin.py:16-29` documenta cómo
un `dashboard.*` de más ya abrió una vez las convocatorias al encargado de
carrera.

Regla de la casa: ninguna aserción negativa va sola. Cada 403 se empareja con la
jefa entrando al MISMO recurso.
"""
from datetime import datetime, time, timedelta
from html.parser import HTMLParser

import pytest

from itcj2.core.utils.timezone import db_now

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


def _hoy():
    """Hoy como FECHA en el reloj de la ventana (`db_now`, hora local)."""
    return db_now().date()


def _ventana(cohort) -> dict:
    """Lo que el editor manda precargado: fecha + hora de cada extremo, armado
    con el MISMO `_window_ctx` que pinta el formulario (hora de omisión = vacía,
    Ruling R14)."""
    from itcj2.apps.titulatec.pages.admin import _window_ctx

    w = _window_ctx(None, cohort, can_edit=True)["window"]
    return {k: w[k] for k in ("opens_date", "opens_time", "closes_date", "closes_time")}


def _form(apertura, cierre, *, h_abre="", h_cierra="") -> dict:
    """El POST del formulario nuevo: fecha ISO + hora `HH:MM` (vacía = omisión)."""
    return {"opens_date": apertura.isoformat(), "opens_time": h_abre,
            "closes_date": cierre.isoformat(), "closes_time": h_cierra}


class _Campos(HTMLParser):
    """`name → atributos` de los `<input>` y el estado elegido del `<select>`
    de la ventana: lo que el navegador mandaría si la jefa pulsa «Guardar» sin
    tocar nada."""

    def __init__(self):
        super().__init__()
        self.inputs: dict[str, dict] = {}
        self.status = None
        self._en_status = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "input" and a.get("name"):
            self.inputs[a["name"]] = a
        elif tag == "select":
            self._en_status = a.get("name") == "status"
        elif tag == "option" and self._en_status and "selected" in a:
            self.status = a["value"]

    def handle_endtag(self, tag):
        if tag == "select":
            self._en_status = False


def _campos_de_la_ventana(html: str) -> _Campos:
    parser = _Campos()
    parser.feed(html.split('id="cohort-window"', 1)[1])
    return parser


def test_la_jefa_abre_la_convocatoria_y_queda_escrita(escenario, client_as, db_session):
    """Horas vacías: la apertura queda a las 00:00 y el cierre a las 23:59:59
    — D8/D9."""
    cohort = escenario["cohort"]
    apertura = _hoy()
    cierre = _hoy() + timedelta(days=30)

    resp = client_as(escenario["jefa"]).post(
        _url(cohort),
        data={"status": "open", **_form(apertura, cierre)},
        follow_redirects=False,
    )

    assert resp.status_code == 200
    assert 'id="cohort-window"' in resp.text, (
        "La respuesta debe ser el parcial re-renderizable; htmx swappea "
        "#cohort-window con outerHTML y necesita la raíz de vuelta."
    )
    db_session.refresh(cohort)
    assert cohort.status == "open"
    assert cohort.opens_at == datetime.combine(apertura, time(0, 0))
    assert cohort.closes_at == datetime.combine(cierre, time(23, 59, 59))


def test_la_hora_del_formulario_se_guarda_tal_cual(escenario, client_as, db_session):
    """09:30 y 18:00 se guardan EXACTAMENTE así: ni se redondean al día ni caen
    a la hora de omisión."""
    cohort = escenario["cohort"]
    apertura = _hoy() + timedelta(days=2)
    cierre = _hoy() + timedelta(days=20)

    resp = client_as(escenario["jefa"]).post(
        _url(cohort),
        data={"status": "draft",
              **_form(apertura, cierre, h_abre="09:30", h_cierra="18:00")},
        follow_redirects=False,
    )

    assert resp.status_code == 200
    db_session.refresh(cohort)
    assert cohort.opens_at == datetime.combine(apertura, time(9, 30))
    assert cohort.closes_at == datetime.combine(cierre, time(18, 0))


def test_los_nombres_viejos_del_formulario_siguen_funcionando(escenario, client_as,
                                                             db_session):
    """Un formulario en caché (anterior a la hora) manda `opens_at`/`closes_at`
    como FECHA: se leen como la fecha del extremo, con la hora de omisión, en
    vez de reventar con «obligatorios»."""
    cohort = escenario["cohort"]
    apertura = _hoy()
    cierre = _hoy() + timedelta(days=10)

    resp = client_as(escenario["jefa"]).post(
        _url(cohort),
        data={"status": "open", "opens_at": apertura.isoformat(),
              "closes_at": cierre.isoformat()},
        follow_redirects=False,
    )

    assert resp.status_code == 200
    db_session.refresh(cohort)
    assert cohort.status == "open"
    assert cohort.opens_at == datetime.combine(apertura, time(0, 0))
    assert cohort.closes_at == datetime.combine(cierre, time(23, 59, 59))


def test_cerrar_desde_la_ruta_pausa_los_procesos(escenario, client_as, make_student,
                                                 make_process, db_session):
    """La prueba de que la ruta CABLEA set_window y no solo escribe columnas."""
    cohort = escenario["cohort"]
    cohort.status = "open"
    db_session.flush()
    proc = make_process(make_student(), cohort=cohort, status="active")

    resp = client_as(escenario["jefa"]).post(
        _url(cohort), data={"status": "closed", **_ventana(cohort)},
        follow_redirects=False,
    )

    assert resp.status_code == 200
    db_session.refresh(proc)
    assert proc.status == "on_hold"


def test_el_cierre_anterior_a_la_apertura_se_rechaza(escenario, client_as, db_session):
    cohort = escenario["cohort"]
    hoy = _hoy()

    resp = client_as(escenario["jefa"]).post(
        _url(cohort),
        data={"status": "open", **_form(hoy, hoy - timedelta(days=1))},
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

    hoy = _hoy()
    resp = client_as(escenario["jefa"]).post(
        _url(escenario["cohort"]),
        data={"status": "open", **_form(hoy, hoy - timedelta(days=1))},
        follow_redirects=False,
    )

    assert resp.status_code == 400
    assert unquote(resp.headers["X-Tt-Error"]) == (
        "El cierre tiene que ser posterior a la apertura."
    )


def test_el_mismo_dia_con_el_cierre_antes_que_la_apertura_se_rechaza(
        escenario, client_as, db_session):
    """Con hora, «posterior» se mide al minuto: el mismo día de 18:00 a 09:00
    no es una ventana, aunque las FECHAS coincidan."""
    from urllib.parse import unquote

    cohort = escenario["cohort"]
    antes = (cohort.opens_at, cohort.closes_at, cohort.status)
    dia = _hoy() + timedelta(days=4)

    resp = client_as(escenario["jefa"]).post(
        _url(cohort),
        data={"status": "open", **_form(dia, dia, h_abre="18:00", h_cierra="09:00")},
        follow_redirects=False,
    )

    assert resp.status_code == 400
    assert unquote(resp.headers["X-Tt-Error"]) == (
        "El cierre tiene que ser posterior a la apertura."
    )
    db_session.refresh(cohort)
    assert (cohort.opens_at, cohort.closes_at, cohort.status) == antes


@pytest.mark.parametrize("datos", [
    {"opens_date": "2031-03-10", "closes_date": ""},
    {"opens_date": "", "closes_date": "2031-03-20"},
    {"opens_date": "", "opens_time": "09:00", "closes_date": "", "closes_time": "18:00"},
    {"opens_date": "2031-03-10", "closes_date": "20/03/2031"},     # basura
    {"opens_date": "2031-03-10", "closes_date": "2031-03-20",
     "closes_time": "25:00"},                                     # hora basura
    {"closes_date": "2031-03-20"},                                 # campo ausente
], ids=["sin-cierre", "sin-apertura", "solo-horas", "cierre-basura", "hora-basura",
        "sin-campo"])
def test_sin_apertura_o_sin_cierre_es_400_y_no_escribe(escenario, client_as, db_session,
                                                      datos):
    """D9: NOT NULL. Un extremo vacío o ilegible ya no significa «sin tope»:
    400 con el texto que lee la jefa, y la convocatoria no se mueve."""
    from urllib.parse import unquote

    cohort = escenario["cohort"]
    antes = (cohort.opens_at, cohort.closes_at, cohort.status)

    resp = client_as(escenario["jefa"]).post(
        _url(cohort), data={"status": "open", **datos}, follow_redirects=False)

    assert resp.status_code == 400
    assert unquote(resp.headers["X-Tt-Error"]) == (
        "La apertura y el cierre son obligatorios.")
    db_session.refresh(cohort)
    assert (cohort.opens_at, cohort.closes_at, cohort.status) == antes


def test_un_mismo_dia_es_una_ventana_valida(escenario, client_as, db_session):
    """Apertura y cierre el mismo día = de 00:00 a 23:59:59: el cierre SÍ es
    posterior. Rechazar la igualdad de instantes no puede romper esto."""
    cohort = escenario["cohort"]
    dia = _hoy() + timedelta(days=3)

    resp = client_as(escenario["jefa"]).post(
        _url(cohort), data={"status": "draft", **_form(dia, dia)},
        follow_redirects=False)

    assert resp.status_code == 200
    db_session.refresh(cohort)
    assert cohort.opens_at == datetime.combine(dia, time(0, 0))
    assert cohort.closes_at == datetime.combine(dia, time(23, 59, 59))


def test_un_estado_inventado_se_rechaza(escenario, client_as, db_session):
    """El `<select>` ofrece tres estados; un POST a mano puede mandar cualquiera.

    `set_window` valida ANTES de escribir, así que la convocatoria no se mueve.
    """
    from urllib.parse import unquote

    cohort = escenario["cohort"]
    resp = client_as(escenario["jefa"]).post(
        _url(cohort), data={"status": "archivada", **_ventana(cohort)},
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
        data={"status": "open", "opens_date": "", "closes_date": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 404


def test_sin_el_permiso_no_pasa_y_la_jefa_si(escenario, client_as):
    cohort = escenario["cohort"]
    datos = {"status": "closed", **_ventana(cohort)}

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
    datos = {"status": "closed", **_ventana(cohort)}

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
                       data={"status": "open", "opens_date": "", "closes_date": ""},
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

    No existe "conservar lo que había": desde que la ventana es NOT NULL un
    `<input>` vacío ya no la borra (400), pero si el editor no llega precargado
    la jefa que solo quería cambiar el estado tiene que volver a teclear la
    ventana entera —y la teclea de memoria—. Esta prueba fija la precarga.
    """
    apertura = datetime.combine(_hoy() + timedelta(days=3), time(9, 30))
    cierre = datetime.combine(_hoy() + timedelta(days=40), time(23, 59, 59))
    cohort = make_cohort(status="open", opens_at=apertura, closes_at=cierre)

    resp = client_as(escenario["jefa"]).get(
        f"/titulatec/admin/cohorts/{cohort.id}?tab=resumen", follow_redirects=False)

    assert resp.status_code == 200
    campos = _campos_de_la_ventana(resp.text).inputs
    assert campos["opens_date"]["value"] == apertura.date().isoformat(), (
        "El input de apertura llegó vacío: `<input type=\"date\">` solo acepta "
        "`YYYY-MM-DD` y un ISO con hora lo deja en blanco."
    )
    assert campos["opens_time"]["value"] == "09:30"
    assert campos["closes_date"]["value"] == cierre.date().isoformat()
    assert campos["closes_time"].get("value", "") == "", (
        "El cierre por omisión (23:59:59) no se precarga como «23:59»: "
        "re-guardar lo movería a 23:59:00 (Ruling R14)."
    )


def test_el_panel_pide_fecha_obligatoria_y_hora_opcional(escenario, client_as):
    """Spec §B4: por extremo, `<input type="date">` obligatorio + `<input
    type="time">` opcional con su ayuda «vacío = 00:00» / «vacío = 23:59»."""
    resp = client_as(escenario["jefa"]).get(
        f"/titulatec/admin/cohorts/{escenario['cohort'].id}?tab=resumen",
        follow_redirects=False)

    assert resp.status_code == 200
    campos = _campos_de_la_ventana(resp.text).inputs
    for extremo in ("opens", "closes"):
        fecha, hora = campos[f"{extremo}_date"], campos[f"{extremo}_time"]
        assert fecha["type"] == "date" and "required" in fecha, extremo
        assert hora["type"] == "time" and "required" not in hora, extremo
    assert "opens_at" not in campos and "closes_at" not in campos, (
        "el formulario ya postea `*_date`/`*_time`; los nombres viejos son "
        "solo respaldo de la ruta")
    ventana = resp.text.split('id="cohort-window"', 1)[1]
    assert "vacío = 00:00" in ventana
    assert "vacío = 23:59" in ventana


@pytest.mark.parametrize("apertura,cierre", [
    (datetime(2031, 3, 10, 9, 30), datetime(2031, 3, 20, 18, 0)),
    (datetime(2031, 3, 10, 0, 0), datetime(2031, 3, 20, 23, 59, 59)),
], ids=["con-hora", "por-omision"])
def test_re_guardar_sin_tocar_conserva_la_ventana(escenario, client_as, make_cohort,
                                                 db_session, apertura, cierre):
    """El ida y vuelta real: lo que pinta el formulario, re-enviado tal cual, no
    mueve ningún extremo. En particular el cierre por omisión sigue a las
    23:59:59 (Review Focus 3): si el input de hora se precargara «23:59», el
    segundo guardado le quitaría el último minuto a la convocatoria."""
    cohort = make_cohort(status="draft", opens_at=apertura, closes_at=cierre)
    c = client_as(escenario["jefa"])

    pagina = c.get(f"/titulatec/admin/cohorts/{cohort.id}?tab=resumen",
                   follow_redirects=False)
    campos = _campos_de_la_ventana(pagina.text)
    datos = {nombre: attrs.get("value", "") for nombre, attrs in campos.inputs.items()}
    datos["status"] = campos.status

    resp = c.post(_url(cohort), data=datos, follow_redirects=False)

    assert resp.status_code == 200, resp.headers.get("X-Tt-Error")
    db_session.refresh(cohort)
    assert (cohort.opens_at, cohort.closes_at, cohort.status) == (
        apertura, cierre, "draft")


def test_la_cabecera_del_detalle_muestra_fecha_y_hora(escenario, client_as, make_cohort):
    """«Apertura dd/mm/aaaa hh:mm»; el cierre por omisión (23:59:59) se lee 23:59."""
    cohort = make_cohort(status="open", opens_at=datetime(2031, 3, 10, 9, 30),
                         closes_at=datetime(2031, 3, 20, 23, 59, 59))

    resp = client_as(escenario["jefa"]).get(
        f"/titulatec/admin/cohorts/{cohort.id}?tab=alumnos", follow_redirects=False)

    assert resp.status_code == 200
    cabecera = resp.text.split('id="cohort-pane"', 1)[0]
    assert "10/03/2031 09:30" in cabecera
    assert "20/03/2031 23:59" in cabecera
    assert "2031-03-10" not in cabecera, "ya no se recorta el ISO a 10 caracteres"


# ---------------------------------------------------------------------------
# _parse_window_dt y el contexto del editor (lo que consume la Task 10)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("fecha,hora,default,esperado", [
    ("2031-03-10", "", time(0, 0), datetime(2031, 3, 10, 0, 0)),
    ("2031-03-10", None, time(0, 0), datetime(2031, 3, 10, 0, 0)),
    ("2031-03-20", "", time(23, 59, 59), datetime(2031, 3, 20, 23, 59, 59)),
    ("2031-03-20", "  ", time(23, 59, 59), datetime(2031, 3, 20, 23, 59, 59)),
    (" 2031-03-10 ", "09:30", time(0, 0), datetime(2031, 3, 10, 9, 30)),
    ("2031-03-20", "18:00", time(23, 59, 59), datetime(2031, 3, 20, 18, 0)),
    # Fecha obligatoria: vacía o basura → None.
    ("", "09:30", time(0, 0), None),
    (None, None, time(0, 0), None),
    ("10/03/2031", "", time(0, 0), None),
    ("2031-02-30", "", time(0, 0), None),
    # Hora opcional, pero si viene tiene que ser HH:MM.
    ("2031-03-10", "9h", time(0, 0), None),
    ("2031-03-10", "25:00", time(0, 0), None),
])
def test_parse_window_dt(fecha, hora, default, esperado):
    from itcj2.apps.titulatec.pages.admin import _parse_window_dt

    assert _parse_window_dt(fecha, hora, default=default) == esperado


def test_los_defaults_de_hora_son_00_00_y_23_59_59():
    from itcj2.apps.titulatec.pages.admin import (
        _CLOSES_DEFAULT_TIME, _OPENS_DEFAULT_TIME,
    )

    assert _OPENS_DEFAULT_TIME == time(0, 0)
    assert _CLOSES_DEFAULT_TIME == time(23, 59, 59)


def test_window_ctx_da_fecha_y_hora_por_extremo_y_ya_no_las_claves_viejas(make_cohort):
    """Ruling R1 (cierre en la Task 10): la plantilla lee
    `opens_date/opens_time/closes_date/closes_time` y la lectura
    `opens_label/closes_label` («dd/mm/aaaa hh:mm»); las claves de transición
    `opens_at`/`closes_at` (solo fecha) salen del contexto.

    La hora que coincide con el valor por omisión va VACÍA: el cierre guardado
    a las 23:59:59 no cabe en un `<input type="time">` de minutos, y precargarlo
    como «23:59» haría que re-guardar la ventana sin tocarla moviera el cierre
    a 23:59:00 (se perdería el último minuto, Review Focus 3). Vacío = «vacío =
    23:59» del formulario, que vuelve a 23:59:59."""
    from itcj2.apps.titulatec.pages.admin import _window_ctx

    con_hora = make_cohort(status="open", opens_at=datetime(2031, 3, 10, 9, 30),
                           closes_at=datetime(2031, 3, 20, 18, 0))
    por_omision = make_cohort(status="open", opens_at=datetime(2031, 3, 10, 0, 0),
                              closes_at=datetime(2031, 3, 20, 23, 59, 59))

    w = _window_ctx(None, con_hora, can_edit=True)["window"]
    assert "opens_at" not in w and "closes_at" not in w
    assert (w["opens_date"], w["opens_time"]) == ("2031-03-10", "09:30")
    assert (w["closes_date"], w["closes_time"]) == ("2031-03-20", "18:00")
    assert (w["opens_label"], w["closes_label"]) == ("10/03/2031 09:30",
                                                     "20/03/2031 18:00")

    w = _window_ctx(None, por_omision, can_edit=True)["window"]
    assert (w["opens_date"], w["opens_time"]) == ("2031-03-10", "")
    assert (w["closes_date"], w["closes_time"]) == ("2031-03-20", "")
    assert (w["opens_label"], w["closes_label"]) == ("10/03/2031 00:00",
                                                     "20/03/2031 23:59")


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


def test_la_lectura_de_la_ventana_dice_fecha_y_hora(make_app_user_without_perms,
                                                   make_cohort, client_as):
    """Quien solo ve la convocatoria lee cada extremo como «dd/mm/aaaa hh:mm»;
    el cierre por omisión (23:59:59) se lee 23:59."""
    mirona = make_app_user_without_perms(perm_codes=("titulatec.cohort.page.list",))
    cohort = make_cohort(status="open", opens_at=datetime(2031, 3, 10, 9, 30),
                         closes_at=datetime(2031, 3, 20, 23, 59, 59))

    resp = client_as(mirona).get(f"/titulatec/admin/cohorts/{cohort.id}?tab=resumen",
                                 follow_redirects=False)

    assert resp.status_code == 200
    ventana = resp.text.split('id="cohort-window"', 1)[1]
    assert "10/03/2031 09:30" in ventana
    assert "20/03/2031 23:59" in ventana
    assert "2031-03-10" not in ventana, "la lectura ya no es la fecha ISO"


def test_el_panel_ya_no_ofrece_aprobacion_automatica(
        escenario, client_as, db_session, modo_sii):
    """Spec 2026-09-27 §A3 (D2): el interruptor «Aprobación automática (SII)» se
    retiró junto con la automática. Ni se pinta en el modo `sii`, ni un POST que
    aún lo mande (formulario viejo en caché) mueve la columna, que queda en la
    BD como legado sin uso."""
    from urllib.parse import unquote

    cohort = escenario["cohort"]
    c = client_as(escenario["jefa"])

    resp = c.get(f"/titulatec/admin/cohorts/{cohort.id}?tab=resumen",
                 follow_redirects=False)

    assert resp.status_code == 200
    ventana = resp.text.split('id="cohort-window"', 1)[1]
    assert "Aprobación automática" not in ventana
    assert "sii_auto" not in ventana

    resp = c.post(_url(cohort),
                  data={"status": "open", **_ventana(cohort),
                        "sii_auto_present": "1", "sii_auto_approve": "0"},
                  follow_redirects=False)

    assert resp.status_code == 200
    assert "Aprobación automática" not in resp.text
    assert "automática" not in unquote(resp.headers.get("X-Tt-Notice", ""))
    db_session.refresh(cohort)
    assert cohort.status == "open", "la ventana sí se guarda"
    assert cohort.sii_auto_approve is True, "la columna legado ya no la mueve nadie"
