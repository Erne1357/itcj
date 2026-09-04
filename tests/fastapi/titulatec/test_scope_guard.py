"""IDOR de carrera: ninguna ruta con `{process_id}` acotaba el proceso al alcance del actor.

BLOQUEADOR reproducido en el contenedor antes de escribir estos tests. `scope_service`
existia y funcionaba, pero se consultaba en **5 call sites, los 5 de listado**
(`admin.py`, `appointments.py` x3, `documents.py`). Las 13 rutas que reciben un
`{process_id}` por path no lo consultaban en absoluto, asi que un encargado de la carrera
A, con solo cambiar el entero de la URL (`titulatec_processes.id` es secuencial), podia:

  * abrir el detalle de un proceso de la carrera B (folio, nombre, control, correo);
  * aprobar o rechazar sus documentos y sus fases;
  * agendar, reagendar y marcar asistencia de su cita de cotejo;
  * **descargar** su acta de nacimiento, su certificado de bachillerato y su CURP
    (`FileResponse`, con `?download=1`).

Mas una fuga de solo-lectura que no lleva el id en el path: el `?selected=` de la agenda
(`appointments.py`), que iba crudo a `_detail_ctx` y devolvia la ficha completa de
cualquier alumno del padron.

Diseno aplicado (spec `docs/superpowers/specs/2026-09-01-titulatec-scope-carrera-design.md`):
un unico predicado en `scope_service` (`process_in_scope`) y su envoltorio de ruta
(`assert_process_in_scope`), que devuelve **404** —no 403— porque un 403 confirmaria que
el id existe y convertiria la ruta en un contador del padron.

REGLA DE ORO: ninguna asercion negativa va sola. Cada 404 viene con el 200 del MISMO
actor sobre la MISMA ruta, para que una guarda que diga que no SIEMPRE —o unos fixtures
rotos— salgan en rojo.
"""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from tests.fastapi.titulatec.conftest import HEAD_PERMS, OFFICER_PERMS

# El encargado de estas pruebas puede ESCRIBIR (es lo que hace grave el IDOR), pero
# sigue SIN `process.api.read.all`: eso es lo unico que lo mantiene acotado a sus
# carreras. Tampoco lleva `officers.api.manage`, que es la llave del cubo "Sin carrera".
SCOPED_PERMS = OFFICER_PERMS + (
    "titulatec.document.api.approve",
    "titulatec.document.api.reject",
    "titulatec.format_b.api.approve",
    "titulatec.format_b.api.reject",
    "titulatec.process.api.approve_phase",
    "titulatec.process.api.reject_phase",
    "titulatec.appointment.api.create",
    "titulatec.appointment.api.reschedule",
    "titulatec.appointment.api.update",
    "titulatec.appointment.api.mark_attended",
)

# La jefa ve todo (`read.all`) y ademas repara datos (`officers.api.manage`).
HEAD_WRITE_PERMS = HEAD_PERMS + SCOPED_PERMS

_DAY = (date.today() + timedelta(days=7)).isoformat()
_INITIAL_DOCS = ("birth_certificate", "high_school_cert", "curp")

# (alias, metodo, plantilla de URL, form). Las 13 rutas con `{process_id}`.
ROUTES = [
    ("process_detail", "GET",
     "/titulatec/admin/processes/{pid}", None),
    ("admin_fb_review", "POST",
     "/titulatec/admin/processes/{pid}/format-b/review", {"action": "approve"}),
    ("phase_approve", "POST",
     "/titulatec/admin/processes/{pid}/phase/1/approve", {}),
    ("phase_reject", "POST",
     "/titulatec/admin/processes/{pid}/phase/1/reject", {"reason": "faltan datos"}),
    ("appt_schedule", "POST",
     "/titulatec/admin/appointments/{pid}/schedule",
     {"appt_date": _DAY, "appt_time": "10:00"}),
    ("appt_reschedule", "POST",
     "/titulatec/admin/appointments/{pid}/reschedule",
     {"appt_date": _DAY, "appt_time": "11:00"}),
    ("appt_start", "POST", "/titulatec/admin/appointments/{pid}/start", {}),
    ("appt_attended", "POST", "/titulatec/admin/appointments/{pid}/attended", {}),
    ("appt_no_show", "POST", "/titulatec/admin/appointments/{pid}/no-show", {}),
    ("appt_document", "GET",
     "/titulatec/admin/appointments/{pid}/document/curp", None),
    ("doc_review", "POST",
     "/titulatec/admin/documents/{pid}/document/review",
     {"type_code": "curp", "action": "approve"}),
    ("doc_file", "GET",
     "/titulatec/admin/documents/{pid}/document/curp?download=1", None),
]
ROUTE_IDS = [r[0] for r in ROUTES]


def _call(cli, method, url, form):
    return cli.get(url) if method == "GET" else cli.post(url, data=form or {})


@pytest.fixture()
def escenario(seed_phase_defs, seed_document_types, make_program, make_cohort,
              make_review_day, make_review_window, make_student, make_process,
              make_document, make_appointment, make_officer, make_head,
              tmp_path, monkeypatch):
    """Tres procesos gemelos —carrera A, carrera B y SIN carrera— y dos actores.

    Los tres traen los 3 documentos iniciales **en disco** a proposito: si el
    archivo no existiera, las dos rutas de `FileResponse` devolverian 404 por
    "no existe el archivo" y el test negativo pasaria por la razon equivocada,
    tapando justo la fuga mas grave (descarga de acta/CURP ajenas).
    """
    def _build():
        monkeypatch.setattr("itcj2.apps.titulatec.utils.storage._base", lambda: tmp_path)
        seed_phase_defs()
        seed_document_types()
        prog_a = make_program("Ingenieria Ficticia A")
        prog_b = make_program("Ingenieria Ficticia B")
        cohort = make_cohort()
        dia = make_review_day(cohort, day=date.fromisoformat(_DAY))
        officer, officer_pos = make_officer([prog_a], perm_codes=SCOPED_PERMS)
        head = make_head(perm_codes=HEAD_WRITE_PERMS)
        # Desde el rediseno de franjas, agendar exige una VENTANA: la hora ya no
        # es texto libre. Se abre una por actor porque cada encargado configura
        # las suyas (el dueno es el usuario, no el puesto).
        for actor in (officer, head):
            make_review_window(dia, actor, start="09:00", end="14:00",
                               slot=30, cap=4)

        procs, students = {}, {}
        for key, program, control in (("a", prog_a, "99000301"),
                                      ("b", prog_b, "99000302"),
                                      ("null", None, "99000303")):
            student = make_student(control_number=control,
                                   first_name="ALUMNO", last_name="SCOPE" + key.upper())
            proc = make_process(student, cohort=cohort, program=program, current_phase=1)
            for code in _INITIAL_DOCS:
                doc = make_document(proc, type_code=code, review_status="pending")
                dest = tmp_path / doc.file_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(b"%PDF-1.4 documento de prueba")
            make_appointment(proc)
            procs[key] = proc
            students[key] = student

        return SimpleNamespace(
            cohort=cohort, programs={"a": prog_a, "b": prog_b},
            officer=officer, officer_position=officer_pos, head=head,
            proc_a=procs["a"], proc_b=procs["b"], proc_null=procs["null"],
            students=students,
        )

    return _build


# ---------------------------------------------------------------------------
# Matriz ruta x actor: las 13 rutas con {process_id}
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("alias,method,tmpl,form", ROUTES, ids=ROUTE_IDS)
def test_encargado_no_alcanza_un_proceso_de_otra_carrera(
    alias, method, tmpl, form, escenario, client_as,
):
    """Mismo actor, misma ruta: 200 sobre SU carrera, 404 sobre la ajena."""
    esc = escenario()
    cli = client_as(esc.officer)

    ok = _call(cli, method, tmpl.format(pid=esc.proc_a.id), form)
    assert ok.status_code == 200, "[" + alias + "] positivo roto: " + ok.text[:300]

    ko = _call(cli, method, tmpl.format(pid=esc.proc_b.id), form)
    assert ko.status_code == 404, "[" + alias + "] IDOR: la carrera ajena respondio " + str(ko.status_code)


@pytest.mark.parametrize("alias,method,tmpl,form", ROUTES, ids=ROUTE_IDS)
def test_proceso_sin_carrera_fuera_de_alcance_del_encargado(
    alias, method, tmpl, form, escenario, client_as,
):
    """`program_id IS NULL` no cae en el alcance de nadie salvo quien repara datos.

    En SQL `program_id IN (...)` con NULL ya evalua a UNKNOWN, asi que los listados
    lo excluian por accidente. El predicado lo cierra a proposito (C2).
    """
    esc = escenario()

    ko = _call(client_as(esc.officer), method, tmpl.format(pid=esc.proc_null.id), form)
    assert ko.status_code == 404, "[" + alias + "] proceso sin carrera visible para el encargado"


@pytest.mark.parametrize("alias,method,tmpl,form", ROUTES, ids=ROUTE_IDS)
def test_el_guard_no_estorba_a_la_jefa(alias, method, tmpl, form, escenario, client_as):
    """Scope "ALL": las tres carreras (incluida la vacia) siguen abiertas para el jefe."""
    esc = escenario()
    cli = client_as(esc.head)

    for etiqueta, proc in (("A", esc.proc_a), ("B", esc.proc_b), ("sin carrera", esc.proc_null)):
        resp = _call(cli, method, tmpl.format(pid=proc.id), form)
        assert resp.status_code == 200, "[" + alias + "] la jefa perdio el proceso " + etiqueta


def test_id_inexistente_responde_igual_que_uno_ajeno(escenario, client_as):
    """404 uniforme: "no existe" y "existe pero no es tuyo" deben ser indistinguibles."""
    esc = escenario()
    cli = client_as(esc.officer)

    ajeno = cli.get("/titulatec/admin/processes/" + str(esc.proc_b.id))
    fantasma = cli.get("/titulatec/admin/processes/" + str(esc.proc_b.id + 10000))

    assert ajeno.status_code == fantasma.status_code == 404
    assert not ajeno.headers.get("X-Tt-Error"), "el 404 no debe llevar oraculo en el header"


# ---------------------------------------------------------------------------
# El guard corta ANTES de escribir
# ---------------------------------------------------------------------------
class TestSinEfectosColaterales:
    def test_no_dictamina_el_documento_ajeno(self, escenario, client_as, db_session):
        from itcj2.apps.titulatec.services.document_service import DocumentService

        esc = escenario()
        resp = client_as(esc.officer).post(
            "/titulatec/admin/documents/" + str(esc.proc_b.id) + "/document/review",
            data={"type_code": "curp", "action": "approve"})

        assert resp.status_code == 404
        doc = DocumentService.get_document(db_session, esc.proc_b.id, "curp")
        assert doc.review_status == "pending"

    def test_no_avanza_la_fase_ajena(self, escenario, client_as, db_session):
        esc = escenario()
        resp = client_as(esc.officer).post(
            "/titulatec/admin/processes/" + str(esc.proc_b.id) + "/phase/1/approve")

        assert resp.status_code == 404
        db_session.refresh(esc.proc_b)
        assert esc.proc_b.current_phase == 1

    def test_no_reagenda_la_cita_ajena(self, escenario, client_as, db_session):
        from itcj2.apps.titulatec.services.appointment_service import AppointmentService

        esc = escenario()
        antes = AppointmentService.get_for_process(db_session, esc.proc_b.id).scheduled_at
        resp = client_as(esc.officer).post(
            "/titulatec/admin/appointments/" + str(esc.proc_b.id) + "/reschedule",
            data={"appt_date": _DAY, "appt_time": "23:00"})

        assert resp.status_code == 404
        db_session.expire_all()
        assert AppointmentService.get_for_process(db_session, esc.proc_b.id).scheduled_at == antes

    def test_no_sirve_el_archivo_ajeno(self, escenario, client_as):
        """La fuga mas grave: acta de nacimiento / CURP de cualquier alumno."""
        esc = escenario()
        cli = client_as(esc.officer)

        propio = cli.get("/titulatec/admin/documents/" + str(esc.proc_a.id) + "/document/curp?download=1")
        ajeno = cli.get("/titulatec/admin/documents/" + str(esc.proc_b.id) + "/document/curp?download=1")

        assert propio.status_code == 200
        assert "attachment" in propio.headers.get("Content-Disposition", "")
        assert propio.content.startswith(b"%PDF")
        assert ajeno.status_code == 404
        assert not ajeno.content.startswith(b"%PDF")


# ---------------------------------------------------------------------------
# La fuga por querystring: ?selected=
# ---------------------------------------------------------------------------
class TestSelectedQuerystring:
    """`?selected=` es un FILTRO, nunca una AMPLIACION del alcance."""

    @pytest.mark.parametrize("url", ["/titulatec/admin/appointments",
                                     "/titulatec/admin/appointments/body"])
    def test_selected_ajeno_no_filtra_la_ficha_del_alumno(self, url, escenario, client_as):
        esc = escenario()
        cli = client_as(esc.officer)

        propio = cli.get(url + "?selected=" + str(esc.proc_a.id))
        assert propio.status_code == 200
        assert esc.students["a"].control_number in propio.text, "el detalle propio desaparecio"

        ajeno = cli.get(url + "?selected=" + str(esc.proc_b.id))
        assert ajeno.status_code == 200, "un selected fuera de alcance no rompe la pagina"
        assert esc.students["b"].control_number not in ajeno.text
        assert esc.students["b"].email not in ajeno.text
        assert esc.proc_b.folio not in ajeno.text

    def test_selected_de_proceso_sin_carrera_tampoco(self, escenario, client_as):
        esc = escenario()
        resp = client_as(esc.officer).get(
            "/titulatec/admin/appointments/body?selected=" + str(esc.proc_null.id))

        assert resp.status_code == 200
        assert esc.students["null"].control_number not in resp.text


# ---------------------------------------------------------------------------
# El cubo "Sin carrera": lo abre quien repara datos, no cualquiera con read.all
# ---------------------------------------------------------------------------
class TestProcesoSinCarrera:
    @pytest.fixture()
    def titulaciones(self, make_user, make_role, make_position, assign_position,
                     bind_position_role):
        """Actor con `process.api.read.all` pero SIN `officers.api.manage`.

        Rol propio (`tt_test_titulaciones`) y no el de la jefa: `make_role` es
        idempotente por NOMBRE, asi que reusar `tt_test_head` le regalaria
        `officers.api.manage` y el negativo de este bloque seria falso.
        """
        def _make():
            user = make_user(first_name="TITULACIONES", last_name="FICTICIA")
            role = make_role("tt_test_titulaciones", (
                "titulatec.dashboard.titulaciones",
                "titulatec.process.page.list",
                "titulatec.process.page.detail",
                "titulatec.process.api.read.all",
                "titulatec.document.api.read.all",
            ))
            pos = make_position(title="Titulaciones de prueba")
            bind_position_role(pos, role)
            assign_position(user, pos)
            return user

        return _make

    def test_la_jefa_si_ve_el_proceso_sin_carrera(self, escenario, client_as):
        esc = escenario()
        resp = client_as(esc.head).get("/titulatec/admin/processes/" + str(esc.proc_null.id))

        assert resp.status_code == 200
        assert esc.students["null"].control_number in resp.text

    def test_read_all_no_abre_el_cubo_sin_carrera(self, escenario, client_as, titulaciones):
        """`read.all` lo tienen dos roles; el cubo es cola de reparacion del jefe (C3)."""
        esc = escenario()
        cli = client_as(titulaciones())

        assert cli.get("/titulatec/admin/processes/" + str(esc.proc_a.id)).status_code == 200
        assert cli.get("/titulatec/admin/processes/" + str(esc.proc_null.id)).status_code == 404


# ---------------------------------------------------------------------------
# `_program_ids_for_user`: de donde salen las carreras del alcance
# ---------------------------------------------------------------------------
class TestProgramIdsForUser:
    """El ancla del alcance es el PUESTO VIGENTE que otorga ESTA app."""

    @pytest.fixture()
    def puesto_con_carrera(self, make_user, make_role, make_position, make_program,
                           link_programs):
        def _make(role_name="tt_test_scope"):
            user = make_user(first_name="ENCARGADO", last_name="SCOPE")
            prog = make_program("Ingenieria Ficticia A")
            pos = make_position(title="Puesto con carrera")
            link_programs(pos, [prog])
            role = make_role(role_name, OFFICER_PERMS)
            return SimpleNamespace(user=user, program=prog, position=pos, role=role)

        return _make

    def test_puesto_vigente_aporta_sus_carreras(self, db_session, puesto_con_carrera,
                                                bind_position_role, assign_position):
        from itcj2.apps.titulatec.services.scope_service import _program_ids_for_user

        p = puesto_con_carrera()
        bind_position_role(p.position, p.role)
        assign_position(p.user, p.position)

        assert _program_ids_for_user(db_session, p.user.id) == {p.program.id}

    def test_userposition_vencida_no_aporta(self, db_session, puesto_con_carrera,
                                            bind_position_role, assign_position):
        """`is_active` seguia en True; solo `end_date` decia que ya no ocupa el puesto."""
        from itcj2.apps.titulatec.services.scope_service import _program_ids_for_user

        p = puesto_con_carrera()
        bind_position_role(p.position, p.role)
        assign_position(p.user, p.position,
                        start_date=date.today() - timedelta(days=30),
                        end_date=date.today() - timedelta(days=1))

        assert _program_ids_for_user(db_session, p.user.id) == set()

    def test_userposition_futura_no_aporta(self, db_session, puesto_con_carrera,
                                           bind_position_role, assign_position):
        from itcj2.apps.titulatec.services.scope_service import _program_ids_for_user

        p = puesto_con_carrera()
        bind_position_role(p.position, p.role)
        assign_position(p.user, p.position, start_date=date.today() + timedelta(days=1))

        assert _program_ids_for_user(db_session, p.user.id) == set()

    def test_puesto_desactivado_no_aporta(self, db_session, puesto_con_carrera,
                                          bind_position_role, assign_position):
        from itcj2.apps.titulatec.services.scope_service import _program_ids_for_user

        p = puesto_con_carrera()
        bind_position_role(p.position, p.role)
        assign_position(p.user, p.position)
        p.position.is_active = False
        db_session.flush()

        assert _program_ids_for_user(db_session, p.user.id) == set()

    def test_puesto_de_otra_app_no_aporta(self, db_session, puesto_con_carrera,
                                          assign_position, titulatec_app):
        """El docstring decia "los puestos titulatec"; el join no tocaba App.

        `core_program_positions` es tabla CORE: cualquier puesto de otra app con
        carreras asignadas ampliaba el alcance en TitulaTec.
        """
        from itcj2.core.models.app import App
        from itcj2.core.models.position import PositionAppRole
        from itcj2.apps.titulatec.services.scope_service import _program_ids_for_user

        p = puesto_con_carrera()
        otra = db_session.query(App).filter_by(key="helpdesk").first()
        assert otra is not None, "falta core_apps('helpdesk') en el seed de referencia"
        db_session.add(PositionAppRole(position_id=p.position.id, app_id=otra.id,
                                       role_id=p.role.id))
        db_session.flush()
        assign_position(p.user, p.position)

        assert _program_ids_for_user(db_session, p.user.id) == set()

    def test_puesto_que_otorga_la_app_por_permiso_directo_si_aporta(
        self, db_session, puesto_con_carrera, assign_position, titulatec_app, make_perms,
    ):
        """El scope es el GEMELO del gate: `has_any_assignment` acepta `PositionAppPerm`.

        Si el gate deja entrar por esa via y el scope la ignora, el usuario entra a
        la app y ve todo vacio sin explicacion.
        """
        from itcj2.core.models.position import PositionAppPerm
        from itcj2.apps.titulatec.services.scope_service import _program_ids_for_user

        p = puesto_con_carrera()
        perm = make_perms(["titulatec.process.page.list"])["titulatec.process.page.list"]
        db_session.add(PositionAppPerm(position_id=p.position.id, app_id=titulatec_app.id,
                                       perm_id=perm.id, allow=True))
        db_session.flush()
        assign_position(p.user, p.position)

        assert _program_ids_for_user(db_session, p.user.id) == {p.program.id}

    def test_rol_directo_al_usuario_no_tiene_ancla(self, db_session, make_student,
                                                   titulatec_app):
        """Grant directo (`core_user_app_roles`) = sin puesto = sin carreras."""
        from itcj2.apps.titulatec.services.scope_service import _program_ids_for_user

        alumno = make_student()

        assert _program_ids_for_user(db_session, alumno.id) == set()


# ---------------------------------------------------------------------------
# Anti-regresion estructural: ninguna ruta nueva nace sin guard
# ---------------------------------------------------------------------------
def _rutas(router):
    """Aplana el router de paginas.

    `include_router` no copia las rutas: deja un envoltorio (`_IncludedRouter`)
    que guarda el sub-router en `original_router`. Iterar `.routes` a secas
    devuelve 7 envoltorios sin `path` y el test pasaria revisando CERO rutas.
    """
    for route in getattr(router, "routes", []):
        sub = getattr(route, "original_router", None) or getattr(route, "routes", None)
        if sub is not None:
            yield from _rutas(sub if hasattr(sub, "routes") else route)
        elif hasattr(route, "endpoint"):
            yield route


def test_toda_ruta_con_process_id_invoca_el_guard():
    """Ergonomia como control: el guard devuelve el proceso, olvidarlo cuesta mas codigo.

    Reemplaza al parametro de scope en los services, cuyo modo de fallo seria
    ABIERTO (un default `None` = "sin restriccion"). Este test falla en rojo ante
    cualquier ruta nueva que reciba un `{process_id}` y no llame al guard.
    """
    import inspect

    from itcj2.apps.titulatec.pages.router import titulatec_pages_router

    sin_guard = []
    revisadas = 0
    for route in _rutas(titulatec_pages_router):
        path = getattr(route, "path", "")
        if "{process_id}" not in path:
            continue
        revisadas += 1
        src = inspect.getsource(route.endpoint)
        if "assert_process_in_scope" not in src:
            sin_guard.append(str(sorted(getattr(route, "methods", []))) + " " + path)

    assert revisadas == 14, (
        "Cambio el inventario de rutas con {process_id}: ahora son %d.\n"
        "Si acabas de ANADIR una ruta, ponle `assert_process_in_scope` como PRIMERA\n"
        "sentencia del try y sube este numero. Si la quitaste, bajalo.\n"
        "OJO: este censo solo ve rutas que llevan el id EN LA RUTA. Una ruta que\n"
        "reciba ids en el CUERPO (p. ej. el reparto masivo) le es invisible y tiene\n"
        "que validar cada id contra `process_in_scope` por su cuenta." % revisadas)
    assert not sin_guard, "rutas con process_id sin guard de carrera:\n" + "\n".join(sin_guard)


def test_las_rutas_del_alumno_no_aceptan_ids_de_proceso():
    """Invariante: el alumno resuelve SU proceso por `user['sub']`, nunca por la URL.

    Mientras se cumpla, un solo guard cubre proceso, cita y documento. El dia que
    aparezca `{appointment_id}` hara falta un segundo guard que delegue en este.
    """
    from itcj2.apps.titulatec.pages.student import router as student_router

    ofensivas = [
        r.path for r in student_router.routes
        if any(tok in getattr(r, "path", "")
               for tok in ("{process_id}", "{appointment_id}", "{document_id}"))
    ]
    assert not ofensivas, "rutas de alumno con id de entidad en el path: " + str(ofensivas)
