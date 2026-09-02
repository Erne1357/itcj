"""Citas de cotejo: el alcance por carrera y el contrato de la vista de 3 zonas.

Por que existe este archivo
---------------------------
El rediseno de la agenda (2026-09-02) pliega `/calendar` y `/day` dentro de
`/body` y hace que UNA sola peticion resuelva CINCO consultas distintas:
`list_for_day`, `list_appointments`, `counts_by_day`, `list_pending_processes` y
`agenda_process_ids`. Las cinco tienen `allowed_program_ids: set | None = None`,
o sea **default ABIERTO**: olvidar pasarlo en una sola de ellas no rompe nada, no
lanza, no sale en los logs — simplemente le ensena a un encargado alumnos de
carreras ajenas. Es el peor fallo posible de este cambio, y por eso hay aqui un
test por superficie MAS un regresor estructural que lee el codigo fuente.

Y una regresion propia del rediseno: `?selected=` ya no se resuelve contra las
filas de la vista sino contra el universo acotado completo. Si alguien lo
estrechara al dia, abrir a un alumno de "Por agendar" (que por definicion no
tiene cita) dejaria de funcionar, igual que abrir a uno cuya cita cae otro dia.

REGLA DE ORO (heredada de test_scope_guard.py): ninguna asercion negativa va
sola. Cada "el encargado no ve X" viene con "la jefa SI ve X" sobre la MISMA
ruta, para que unos fixtures rotos salgan en rojo en vez de en verde.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

import itcj2.apps.titulatec as _tt_pkg

TEMPLATES = Path(_tt_pkg.__file__).resolve().parent / "templates" / "titulatec"

def _sin_comentarios(txt: str) -> str:
    """Quita los `{# ... #}` de Jinja: los regresores estructurales leen MARKUP,
    y un comentario que explica lo que se quito haria pasar (o fallar) al test
    por lo que dice la prosa."""
    return re.sub(r"\{#.*?#\}", "", txt, flags=re.S)


URL = "/titulatec/admin/appointments"
BODY = "/titulatec/admin/appointments/body"

_INITIAL_DOCS = ("birth_certificate", "high_school_cert", "curp")

# Dia de cotejo fijo y futuro: el mes tiene que ser estable para el calendario,
# y `_default_month` aterriza en el mes del proximo dia habilitado.
_D1 = date(2029, 5, 7)
_D2 = date(2029, 5, 8)


@pytest.fixture()
def agenda(seed_phase_defs, seed_document_types, make_program, make_cohort,
           make_review_day, make_student, make_process, make_document,
           make_appointment, make_officer, make_head):
    """Dos carreras, dos dias de cotejo, cuatro procesos y dos actores.

        proc_a1  carrera A · cita el dia 1       -> el encargado SI lo ve
        proc_b1  carrera B · cita el dia 1       -> el encargado NO lo ve
        proc_a2  carrera A · cita el dia 2       -> sirve para el deep link cruzado
        proc_ap  carrera A · SIN cita, 3 docs aprobados -> cae en "Por agendar"
        proc_bp  carrera B · SIN cita, 3 docs aprobados -> "Por agendar" del jefe
    """
    def _build():
        seed_phase_defs()
        seed_document_types()
        prog_a = make_program("Ingenieria Ficticia A")
        prog_b = make_program("Ingenieria Ficticia B")
        cohort = make_cohort()
        make_review_day(cohort, day=_D1)
        make_review_day(cohort, day=_D2)
        officer, officer_pos = make_officer([prog_a])
        head = make_head()

        procs, students = {}, {}
        plan = [
            ("a1", prog_a, "99000401", _D1, 9),
            ("b1", prog_b, "99000402", _D1, 10),
            ("a2", prog_a, "99000403", _D2, 11),
            ("ap", prog_a, "99000404", None, None),
            ("bp", prog_b, "99000405", None, None),
        ]
        for key, program, control, day, hour in plan:
            st = make_student(control_number=control, last_name="ALUMNO" + key.upper())
            proc = make_process(st, cohort=cohort, program=program, current_phase=2)
            students[key] = st
            procs[key] = proc
            for code in _INITIAL_DOCS:
                make_document(proc, type_code=code, review_status="approved")
            if day is not None:
                make_appointment(proc, when=datetime.combine(day, datetime.min.time()).replace(hour=hour))
        return {"officer": officer, "officer_position": officer_pos, "head": head,
                "programs": {"a": prog_a, "b": prog_b}, "cohort": cohort,
                "procs": procs, "students": students}

    return _build


# ---------------------------------------------------------------------------
# 1. La lista del dia
# ---------------------------------------------------------------------------
class TestListaDelDia:
    def test_el_encargado_solo_ve_su_carrera_en_el_dia(self, agenda, client_as):
        """`list_for_day` tiene default ABIERTO: sin `allowed_program_ids` el
        encargado veria la agenda entera del dia sin ningun sintoma."""
        esc = agenda()

        propio = client_as(esc["officer"]).get(URL + "?date=" + _D1.isoformat())
        assert propio.status_code == 200, propio.text[:400]
        assert esc["students"]["a1"].control_number in propio.text, "perdio su propia cita"
        assert esc["students"]["b1"].control_number not in propio.text

        # Control positivo sobre la MISMA ruta: la jefa si ve las dos.
        jefa = client_as(esc["head"]).get(URL + "?date=" + _D1.isoformat())
        assert jefa.status_code == 200
        assert esc["students"]["a1"].control_number in jefa.text
        assert esc["students"]["b1"].control_number in jefa.text

    def test_el_parcial_body_acota_igual_que_la_pagina(self, agenda, client_as):
        """La pagina y el parcial comparten `_shell_ctx`; si divergieran, la
        primera carga acotaria y el primer swap dejaria de hacerlo."""
        esc = agenda()
        cli = client_as(esc["officer"])

        pagina = cli.get(URL + "?date=" + _D1.isoformat())
        parcial = cli.get(BODY + "?date=" + _D1.isoformat())

        assert parcial.status_code == 200
        for resp in (pagina, parcial):
            assert esc["students"]["a1"].control_number in resp.text
            assert esc["students"]["b1"].control_number not in resp.text

    def test_una_fecha_basura_no_revienta_la_pagina(self, agenda, client_as):
        """El `?date=` viaja en la URL: tiene que degradar, no dar 500."""
        esc = agenda()
        resp = client_as(esc["officer"]).get(URL + "?date=maniana")
        assert resp.status_code == 200
        assert 'id="appt-shell"' in resp.text


# ---------------------------------------------------------------------------
# 2. El calendario
# ---------------------------------------------------------------------------
class TestCalendario:
    def test_los_conteos_del_calendario_estan_acotados(self, agenda, client_as, db_session):
        """`counts_by_day` es la otra consulta con default abierto. Se verifica
        por el servicio (el HTML solo trae el numero, que no distingue de quien)."""
        from itcj2.apps.titulatec.services.appointment_service import AppointmentService

        esc = agenda()
        start = datetime.combine(_D1.replace(day=1), datetime.min.time())
        end = start + timedelta(days=40)

        abierto = AppointmentService.counts_by_day(db_session, start, end)
        acotado = AppointmentService.counts_by_day(
            db_session, start, end, allowed_program_ids={esc["programs"]["a"].id})

        assert abierto.get(_D1, 0) >= 2, "el escenario deberia dejar 2 citas ese dia"
        assert acotado.get(_D1, 0) == 1, "el conteo no se acoto a la carrera"
        assert AppointmentService.counts_by_day(db_session, start, end,
                                                allowed_program_ids=set()) == {}

    def test_el_rotulo_del_mes_va_en_espanol(self, agenda, client_as):
        """`calendar.month_name` sale en el locale del proceso (C en el
        contenedor) y escribia "May 2029" en una UI en espanol."""
        esc = agenda()
        resp = client_as(esc["head"]).get(URL + "?month=2029-05")

        assert resp.status_code == 200
        assert "Mayo 2029" in resp.text
        assert "May 2029" not in resp.text

    def test_el_calendario_aterriza_donde_hay_trabajo(self, agenda, client_as):
        """Sin `?month=`, si la convocatoria no tiene dias en el mes de hoy se
        aterriza en el mes del proximo dia habilitado. Sin esto, abrir Citas
        fuera de la semana de cotejo daba un mes vacio y ninguna pista — el mismo
        callejon sin salida por el que se elimino el boton "Del dia"."""
        esc = agenda()
        resp = client_as(esc["head"]).get(URL)

        assert resp.status_code == 200
        assert "Mayo 2029" in resp.text


# ---------------------------------------------------------------------------
# 3. "Por agendar" (zona B)
# ---------------------------------------------------------------------------
class TestPorAgendar:
    def test_esta_en_las_tres_vistas_y_acotado(self, agenda, client_as):
        """Fijo al lado del calendario: no puede vivir solo en la pestana Lista
        (antes desde el calendario no habia forma de llegar a un alumno sin cita)."""
        esc = agenda()
        for qs in ("", "?date=" + _D1.isoformat(), "?view=list"):
            propio = client_as(esc["officer"]).get(URL + qs)
            assert 'id="appt-pending"' in propio.text, "falta 'Por agendar' en " + (qs or "/")
            assert esc["students"]["ap"].control_number in propio.text, qs
            assert esc["students"]["bp"].control_number not in propio.text, qs

            jefa = client_as(esc["head"]).get(URL + qs)
            assert esc["students"]["bp"].control_number in jefa.text, qs

    def test_se_ve_tambien_con_cero_pendientes(self, seed_phase_defs, seed_document_types,
                                               make_officer, client_as):
        """Con `{% if pending %}` la seccion desaparecia justo cuando el
        encargado necesitaba saber que no le queda nada.

        El actor es un encargado SIN carreras (alcance vacio = fail-closed), no
        la jefa: esta suite corre dentro de una transaccion sobre la BD de dev,
        asi que un actor con `read.all` ve tambien los procesos que ya estaban
        ahi y el conteo nunca seria 0.
        """
        seed_phase_defs()
        seed_document_types()
        officer, _pos = make_officer([])
        resp = client_as(officer).get(URL)

        assert resp.status_code == 200
        assert 'id="appt-pending"' in resp.text
        assert 'id="appt-pending-count">0<' in resp.text
        assert "Nadie pendiente de agendar" in resp.text

    def test_el_contador_no_lo_tocan_los_filtros_de_la_lista(self, agenda, client_as):
        """Contrato declarado: los filtros de la zona A filtran la zona A. "Por
        agendar" es la cola de trabajo del encargado y su contador es estable."""
        esc = agenda()
        cli = client_as(esc["head"])

        libre = cli.get(URL + "?view=list")
        filtrado = cli.get(URL + "?view=list&program_id=" + str(esc["programs"]["a"].id))

        for resp in (libre, filtrado):
            assert esc["students"]["ap"].control_number in resp.text
            assert esc["students"]["bp"].control_number in resp.text


# ---------------------------------------------------------------------------
# 4. El detalle: `?selected=` sigue siendo un FILTRO, no una ampliacion
# ---------------------------------------------------------------------------
class TestDetalle:
    def test_abre_a_un_alumno_cuya_cita_es_de_OTRO_dia(self, agenda, client_as):
        """La regresion que el rediseno podia introducir: si `visible_ids` se
        estrechara a las filas del dia, este deep link dejaria de abrir la ficha."""
        esc = agenda()
        resp = client_as(esc["officer"]).get(
            URL + "?date=" + _D1.isoformat() + "&selected=" + str(esc["procs"]["a2"].id))

        assert resp.status_code == 200
        assert esc["students"]["a2"].control_number in resp.text
        assert 'id="appt-detail"' in resp.text

    def test_abre_a_un_alumno_de_por_agendar_que_no_tiene_cita(self, agenda, client_as):
        """Un pendiente no esta en NINGUNA lista de citas: si el universo se
        calculara solo sobre la agenda, "Por agendar" no podria abrirse."""
        esc = agenda()
        resp = client_as(esc["officer"]).get(
            URL + "?selected=" + str(esc["procs"]["ap"].id))

        assert resp.status_code == 200
        assert esc["students"]["ap"].control_number in resp.text
        assert "Agendar cita de cotejo" in resp.text

    @pytest.mark.parametrize("url", [URL, BODY])
    def test_un_selected_ajeno_no_filtra_la_ficha(self, url, agenda, client_as):
        """El IDOR que se cerro: `?selected=` crudo devolvia nombre, control,
        correo y las `view_url` de los 3 documentos de cualquier alumno."""
        esc = agenda()
        cli = client_as(esc["officer"])

        propio = cli.get(url + "?selected=" + str(esc["procs"]["a1"].id))
        assert propio.status_code == 200
        assert esc["students"]["a1"].control_number in propio.text, "perdio su propia ficha"

        ajeno = cli.get(url + "?selected=" + str(esc["procs"]["b1"].id))
        assert ajeno.status_code == 200, "un selected fuera de alcance no rompe la pagina"
        assert esc["students"]["b1"].control_number not in ajeno.text
        assert esc["students"]["b1"].email not in ajeno.text
        assert esc["procs"]["b1"].folio not in ajeno.text
        # y el id ajeno no queda pegado en los hx-get del parcial
        assert "selected=" + str(esc["procs"]["b1"].id) not in ajeno.text

        # Control positivo: la jefa SI la abre, misma ruta y mismo proceso.
        jefa = client_as(esc["head"]).get(url + "?selected=" + str(esc["procs"]["b1"].id))
        assert esc["students"]["b1"].control_number in jefa.text


# ---------------------------------------------------------------------------
# 5. El universo del `?selected=` (servicio)
# ---------------------------------------------------------------------------
class TestAgendaProcessIds:
    def test_acota_por_carrera_y_el_set_vacio_cierra(self, agenda, db_session):
        from itcj2.apps.titulatec.services.appointment_service import AppointmentService

        esc = agenda()
        todos = AppointmentService.agenda_process_ids(db_session)
        solo_a = AppointmentService.agenda_process_ids(
            db_session, allowed_program_ids={esc["programs"]["a"].id})

        assert esc["procs"]["a1"].id in todos and esc["procs"]["b1"].id in todos
        assert esc["procs"]["a1"].id in solo_a
        assert esc["procs"]["b1"].id not in solo_a
        # Fail-closed: sin carreras asignadas no se ve nada.
        assert AppointmentService.agenda_process_ids(
            db_session, allowed_program_ids=set()) == set()

    def test_no_incluye_a_los_que_no_tienen_cita(self, agenda, db_session):
        """Es el universo de la AGENDA; los pendientes los aporta la otra mitad."""
        from itcj2.apps.titulatec.services.appointment_service import AppointmentService

        esc = agenda()
        assert esc["procs"]["ap"].id not in AppointmentService.agenda_process_ids(db_session)


# ---------------------------------------------------------------------------
# 6. Regresores estructurales (leen el codigo, no la respuesta)
# ---------------------------------------------------------------------------
def test_toda_consulta_de_listado_recibe_el_alcance():
    """Las 5 consultas de `_shell_ctx` tienen default ABIERTO: olvidar una
    filtra de menos EN SILENCIO. Este test se cae si aparece una llamada nueva
    sin `allowed_program_ids`."""
    import inspect

    from itcj2.apps.titulatec.pages import appointments as mod

    src = inspect.getsource(mod._shell_ctx)
    sin_alcance = []
    for metodo in ("list_for_day", "list_appointments", "counts_by_day",
                   "list_pending_processes", "agenda_process_ids"):
        # `counts_by_day` vive en `_calendar_ctx`, al que `_shell_ctx` delega.
        cuerpo = src if metodo != "counts_by_day" else inspect.getsource(mod._calendar_ctx)
        for llamada in re.findall(re.escape(metodo) + r"\((?:[^()]|\([^()]*\))*\)", cuerpo):
            if "allowed_program_ids" not in llamada and "allowed" not in llamada:
                sin_alcance.append(metodo + ": " + " ".join(llamada.split()))
    assert not sin_alcance, ("consultas de listado sin acotar por carrera:\n"
                             + "\n".join(sin_alcance))


def test_el_indicador_no_entra_al_nodo_que_se_reemplaza():
    """`#appt-skel` tiene que quedar FUERA de `#appt-shell`: el swap es
    `morph:outerHTML` sobre el shell, asi que un indicador dentro se destruiria
    estando visible y el `.tt-ind-host` perderia el ancla de posicionamiento a
    media peticion."""
    html = (TEMPLATES / "admin" / "appointments.html").read_text(encoding="utf-8")
    shell = (TEMPLATES / "partials" / "appointments_body.html").read_text(encoding="utf-8")

    assert 'id="appt-skel"' in html and "tt-ind--overlay" in html
    assert 'class="tt-ind-host"' in html
    assert "appt-skel" not in shell, "el indicador se mudo dentro del shell"
    # y sigue sin reservar alto: nada de `style=` que gane al fundido
    assert re.search(r'id="appt-skel"[^>]*style=', html) is None


def test_el_segmento_tiene_dos_opciones_y_ninguna_es_del_dia():
    """Decision del usuario: "Del dia" sale. Sin fecha aterrizaba en HOY, que
    fuera de la semana de cotejo son 0 citas."""
    shell = _sin_comentarios(
        (TEMPLATES / "partials" / "appointments_body.html").read_text(encoding="utf-8"))

    segs = re.findall(r'class="seg\{\{', shell)
    assert len(segs) == 2, "el segmento deberia tener 2 opciones, tiene %d" % len(segs)
    assert "Del día" not in shell and "Del dia" not in shell
    assert "aria-current" in shell, "el activo del segmento no se anuncia"


def test_los_parciales_de_citas_no_llevan_js_ni_css_inline():
    """Regla del proyecto: cero `<script>` y cero `style=` nuevos en templates.
    El parcial traia 12 lineas de `<script>` con dos funciones globales y ocho
    `style=` inline; hoy todo vive en `js/admin/appointments.js` y `titulatec.css`."""
    ofensores = []
    archivos = [TEMPLATES / "admin" / "appointments.html",
                TEMPLATES / "partials" / "appointments_body.html",
                TEMPLATES / "partials" / "appointments_calendar.html",
                TEMPLATES / "partials" / "appointments_day.html",
                TEMPLATES / "partials" / "appointments_list.html",
                TEMPLATES / "partials" / "appointments" / "_appt_pending.html",
                TEMPLATES / "partials" / "appointments" / "_appt_detail.html"]
    for path in archivos:
        sin_comentarios = _sin_comentarios(path.read_text(encoding="utf-8"))
        if "<script" in sin_comentarios:
            ofensores.append(str(path.name) + ": <script> inline")
        if re.search(r"\sstyle=", sin_comentarios):
            ofensores.append(str(path.name) + ": style= inline")
        if "onclick=" in sin_comentarios:
            ofensores.append(str(path.name) + ": onclick= inline")
    assert not ofensores, "\n".join(ofensores)


def test_la_navegacion_de_citas_empuja_la_url_de_pagina_no_la_del_parcial():
    """`hx-push-url="true"` empuja la URL PEDIDA. Si los enlaces apuntaran a
    `/body`, la barra de direcciones acabaria con el parcial desnudo y F5
    devolveria un fragmento sin `<head>`."""
    macros = _sin_comentarios(
        (TEMPLATES / "partials" / "appointments" / "_appt_macros.html").read_text(encoding="utf-8"))

    assert 'hx-push-url="true"' in macros
    assert "/body" not in macros, "el contrato de navegacion apunta al parcial"
    # Invariante de la app: `hx-select == hx-target` OBLIGA a `outerHTML`, o el
    # nodo recortado entra dentro de si mismo. `test_admin_nav_swap.py` barre las
    # PLANTILLAS, y estos atributos salen de un macro (sin `<tag` delante), asi
    # que su censo no los ve: se fijan aqui.
    assert 'hx-target="#appt-shell"' in macros
    assert 'hx-select="#appt-shell"' in macros
    assert 'hx-swap="morph:outerHTML"' in macros


@pytest.mark.parametrize("nombre", ["appointments_body.html", "appointments_calendar.html",
                                    "appointments_day.html", "appointments_list.html"])
def test_ningun_parcial_de_citas_apunta_al_viejo_appt_body(nombre):
    """`#appt-body` y las rutas `/calendar` y `/day` desaparecieron al plegarse
    en `/body`. Un `hx-target` huerfano no falla: no hace NADA, en silencio."""
    sin_comentarios = _sin_comentarios((TEMPLATES / "partials" / nombre).read_text(encoding="utf-8"))

    assert "#appt-body" not in sin_comentarios
    assert "appointments/calendar" not in sin_comentarios
    assert "appointments/day" not in sin_comentarios
