"""Guarda de fase del ALUMNO: no puede ejecutar una fase que no le toca.

BLOQUEADOR reproducido en dev antes de escribir estos tests. Las 13 rutas de
`pages/student.py` estaban gateadas SOLO por permiso, y el rol `student` tiene
los 21 permisos de la app: **ni una sola comprobacion de `current_phase` en todo
el archivo**. Con el alumno 90200034 parado en la FASE 1::

    GET  /student/formato-b        -> 200   (es de la fase 3; ademas CREA el FormatB)
    POST /student/formato-b/step/1 -> 200   (guarda datos)
    POST /student/formato-b/step/3 -> 200   (fase 3 'in_review' + FormatB 'submitted')

...y el proceso entraba en la cola de Titulaciones sin haber pasado las fases 1 y
2. Hacia atras era peor: el alumno 90200001, en fase 2 con la fase 1 YA APROBADA::

    POST   /student/phase/1/submit -> 204   (la fase 1 vuelve de 'approved' a 'in_review')
    DELETE /student/documents/curp -> 200   (borra un documento APROBADO de una fase cerrada)

Eso reabre una fase cerrada, la reinyecta en la cola de Servicios Escolares y
destruye evidencia ya dictaminada (`DocumentService.delete` llama tambien a
`storage.delete_document_file`).

Dos agujeros mas de la misma familia, que no estaban en el reporte y salen del
inventario propio (ver `TestTipoDeDocumentoDeOtraFase`): `POST/DELETE
/student/documents/{type_code}` resuelven el `DocumentType` **sin mirar su
`phase_number`**, asi que un alumno de la fase 1 podia subir y borrar
`anexo_iii` (fase 6), `ine` / `residency_proof` (fase 7) o `final_project` /
`presentation` (fase 8).

CONTRADICE lo que la UI promete en el acordeon del dashboard
(`student/dashboard.html:219,221`): "Fase cerrada - ya no requiere accion" y
"Se habilitara cuando llegues a esta fase". El acordeon cumple (`_cta_for` no
emite CTA fuera de la fase actual); el backend no lo respaldaba.

DISENO (decision del usuario, 2026-09-02)
-----------------------------------------
"Las fases siguientes: informacion detallada para que puedan ver con anterioridad
que es, pero sin poder ejecutar el paso. Las anteriores: completadas, INMUTABLES."

La guarda es la GEMELA de `PhaseService.assert_can_transition` (el camino del
admin, fijado por `test_phase_guard.py`): mismo sitio (el service), misma forma
(`_error() -> can_*() / assert_*()`), mismas tres reglas — la fase existe, el
proceso esta `active`, y solo se actua sobre `current_phase`.

Dos traducciones HTTP, porque las rutas del alumno son de dos naturalezas:

  * **mutaciones y parciales HTMX** -> `400 + X-Tt-Error` (canal de error de la
    app: `documents.html:54-56` ya lo convierte en toast). 400 y no 409 porque
    los 14 `X-Tt-Error` del arbol viajan en 400 —incluida la guarda gemela del
    admin— mientras que el 409 pelado ya significa otra cosa en ESTAS MISMAS
    rutas ("no tienes proceso": `student.py:643,735,762,899`).
  * **paginas completas** -> `302` a `/titulatec/student/dashboard?fase={N}`.
    El alumno que llega por un enlace viejo (una notificacion en BD, un
    marcador) tiene que aterrizar donde SE LE EXPLICA la fase, que es justo lo
    que el acordeon hace y con cero acciones. Un 404 seria un callejon sin
    salida y ademas mentiria (la pagina existe; no es su turno). Mismo mecanismo
    y mismo 302 que ya usa `/student/fase/{n}` por la misma razon.

REGLA DE ORO (heredada de las specs de scope y de fase): ninguna asercion
negativa va sola. Cada "no se pudo" viene con el positivo del MISMO actor sobre
la MISMA ruta, para que una guarda que diga que no SIEMPRE —o unos fixtures
rotos— salgan en rojo.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from itcj2.apps.titulatec.services.phase_service import PhaseService

# Los 21 permisos REALES del rol `student` en titulatec (verificados en BD contra
# `database/DML/titulatec/03_insert_role_permissions.sql`). El actor de estas
# pruebas los lleva TODOS a proposito: si algo le sale negado, tiene que ser la
# guarda de fase y nunca un permiso que falta.
STUDENT_ALL_PERMS = (
    "titulatec.appointment.api.confirm.own",
    "titulatec.appointment.page.my",
    "titulatec.ceremony.api.upload.own",
    "titulatec.ceremony.page.my",
    "titulatec.chat.api.read",
    "titulatec.chat.api.send",
    "titulatec.chat.api.upload",
    "titulatec.chat.page.view",
    "titulatec.dashboard.student",
    "titulatec.document.api.delete.own",
    "titulatec.document.api.read.own",
    "titulatec.document.api.upload.own",
    "titulatec.format_b.api.read.own",
    "titulatec.format_b.api.save",
    "titulatec.format_b.api.submit",
    "titulatec.format_b.page.fill",
    "titulatec.notifications.api.mark_read",
    "titulatec.notifications.api.read.own",
    "titulatec.process.api.advance",
    "titulatec.process.api.read.own",
    "titulatec.process.page.my",
)

# Catalogo de tipos de documento con fases DE VERDAD distintas: sin `anexo_iii`
# (fase 6) el agujero de "subir un documento de otra fase" no se puede probar.
DOC_TYPES = (
    ("birth_certificate", "Acta de nacimiento", 1),
    ("high_school_cert", "Certificado de bachillerato", 1),
    ("curp", "CURP certificada", 1),
    ("anexo_iii", "Anexo III firmado", 6),
    ("final_project", "Trabajo final", 8),
)

INITIAL_DOCS = ("birth_certificate", "high_school_cert", "curp")
TODOS_APROBADOS = tuple((c, "approved") for c in INITIAL_DOCS)

PDF = ("acta.pdf", b"%PDF-1.4 documento de prueba", "application/pdf")

DASH = "/titulatec/student/dashboard"


def _phases(db, process_id: int) -> dict[int, str]:
    from itcj2.apps.titulatec.models import ProcessPhase
    db.expire_all()
    return {r.phase_number: r.status for r in
            db.query(ProcessPhase).filter_by(process_id=process_id).all()}


def _format_b(db, process_id: int):
    from itcj2.apps.titulatec.models import FormatB
    db.expire_all()
    return db.query(FormatB).filter_by(process_id=process_id).first()


def _docs(db, process_id: int) -> dict[str, str]:
    from itcj2.apps.titulatec.models import Document
    db.expire_all()
    return {d.type_code: d.review_status for d in
            db.query(Document).filter_by(process_id=process_id).all()}


@pytest.fixture()
def escenario(db_session, seed_phase_defs, seed_document_types, make_program,
              make_cohort, make_student, make_process, make_document,
              make_appointment, tmp_path, monkeypatch):
    """Un alumno con los 21 permisos y su proceso en la fase que pida el test.

    Los documentos se escriben TAMBIEN en disco (bajo `tmp_path`) porque el
    borrado pasa por `storage.delete_document_file`: si el fichero no existiera,
    el test de "no borra evidencia" pasaria por la razon equivocada.
    """
    def _build(current_phase=1, status="active", docs=(), appt_status=None,
               phase_overrides=None):
        monkeypatch.setattr("itcj2.apps.titulatec.utils.storage._base", lambda: tmp_path)
        seed_phase_defs()
        seed_document_types(DOC_TYPES)
        program = make_program("Ingenieria Ficticia A")
        cohort = make_cohort()
        student = make_student(perm_codes=STUDENT_ALL_PERMS)
        proc = make_process(student, cohort=cohort, program=program,
                            current_phase=current_phase, status=status)

        phase_de = {code: n for code, _name, n in DOC_TYPES}
        for code, review_status in docs:
            doc = make_document(proc, type_code=code, phase_number=phase_de[code],
                                review_status=review_status)
            dest = tmp_path / doc.file_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"%PDF-1.4 documento de prueba")

        appt = make_appointment(proc, status=appt_status) if appt_status else None

        if phase_overrides:
            from itcj2.apps.titulatec.models import ProcessPhase
            for n, st in phase_overrides.items():
                ph = (db_session.query(ProcessPhase)
                      .filter_by(process_id=proc.id, phase_number=n).one())
                ph.status = st
            db_session.flush()

        return SimpleNamespace(student=student, process=proc, appt=appt, files=tmp_path)

    return _build


# ===========================================================================
# 1. Los 4 exploits del reporte, uno por test
# ===========================================================================
class TestExploitsReportados:
    def test_e1_no_abre_el_formato_b_de_una_fase_futura(self, escenario, client_as,
                                                        db_session):
        """`GET /formato-b` desde la fase 1 respondia 200 **y creaba el FormatB**.

        Esa fila es una escritura desde un GET (`FormatBService.get_or_create`
        hace `db.commit()`), asi que el simple hecho de abrir la pagina ya dejaba
        rastro de una fase que el alumno no toca.
        """
        esc = escenario(current_phase=1)

        resp = client_as(esc.student).get("/titulatec/student/formato-b",
                                          follow_redirects=False)

        assert resp.status_code == 302, resp.text[:300]
        assert resp.headers["location"] == DASH + "?fase=3"
        assert _format_b(db_session, esc.process.id) is None, \
            "un GET a una fase futura no debe crear el FormatB"

    def test_e2_no_guarda_un_paso_del_formato_b_de_una_fase_futura(
        self, escenario, client_as, db_session,
    ):
        """`POST /formato-b/step/1` desde la fase 1 guardaba datos de la fase 3."""
        esc = escenario(current_phase=1)

        resp = client_as(esc.student).post("/titulatec/student/formato-b/step/1",
                                           data={"first_name": "INVENTADO"})

        assert resp.status_code == 400, resp.text[:300]
        assert resp.headers.get("X-Tt-Error"), "el error debe viajar por el canal de la app"
        assert _format_b(db_session, esc.process.id) is None

    def test_e3_no_envia_el_formato_b_desde_la_fase_1(self, escenario, client_as,
                                                      db_session):
        """El peor: `POST /formato-b/step/3` metia el proceso en la cola de
        Titulaciones (fase 3 'in_review' + FormatB 'submitted') con
        `current_phase=1`, sin haber pasado las fases 1 y 2."""
        esc = escenario(current_phase=1)

        resp = client_as(esc.student).post("/titulatec/student/formato-b/step/3",
                                           data={"project_name": "Proyecto inventado"})

        assert resp.status_code == 400, resp.text[:300]
        db_session.refresh(esc.process)
        assert esc.process.current_phase == 1
        assert _phases(db_session, esc.process.id)[3] == "pending", \
            "la fase 3 no puede entrar en revision desde la fase 1"
        assert _format_b(db_session, esc.process.id) is None

    def test_e4_no_reabre_una_fase_ya_aprobada(self, escenario, client_as, db_session):
        """`POST /phase/1/submit` desde la fase 2 devolvia la fase 1 de
        'approved' a 'in_review' y la reinyectaba en la cola de Servicios
        Escolares."""
        esc = escenario(current_phase=2, docs=TODOS_APROBADOS)
        assert _phases(db_session, esc.process.id)[1] == "approved"

        resp = client_as(esc.student).post("/titulatec/student/phase/1/submit")

        assert resp.status_code == 400, resp.text[:300]
        assert resp.headers.get("X-Tt-Error")
        db_session.refresh(esc.process)
        assert esc.process.current_phase == 2
        assert _phases(db_session, esc.process.id)[1] == "approved", \
            "una fase cerrada no se reabre"

    def test_e5_no_borra_un_documento_de_una_fase_cerrada(self, escenario, client_as,
                                                          db_session):
        """`DELETE /documents/curp` desde la fase 2 borraba la fila **y el
        fichero** de un documento ya dictaminado como aprobado."""
        esc = escenario(current_phase=2, docs=TODOS_APROBADOS)
        fichero = esc.files / f"tt-test/{esc.process.id}/curp.pdf"
        assert fichero.exists(), "fixture rota: el fichero deberia existir"

        resp = client_as(esc.student).delete("/titulatec/student/documents/curp")

        assert resp.status_code == 400, resp.text[:300]
        assert _docs(db_session, esc.process.id).get("curp") == "approved"
        assert fichero.exists(), "la evidencia dictaminada no se destruye"


# ===========================================================================
# 2. El resto del inventario: toda ruta del alumno atada a una fase
# ===========================================================================
class TestPaginasDeOtraFaseRedirigen:
    """Paginas completas -> 302 al acordeon, que SI explica la fase."""

    @pytest.mark.parametrize("url,fase,en", [
        ("/titulatec/student/documents", 1, 3),   # fase 1 vista desde la 3 (pasada)
        ("/titulatec/student/cita", 2, 1),        # fase 2 vista desde la 1 (futura)
        ("/titulatec/student/formato-b", 3, 1),   # fase 3 vista desde la 1 (futura)
        ("/titulatec/student/documents", 1, 2),   # fase 1 vista desde la 2 (pasada)
        ("/titulatec/student/cita", 2, 3),        # fase 2 vista desde la 3 (pasada)
    ])
    def test_redirige_al_acordeon_de_esa_fase(self, url, fase, en, escenario, client_as):
        esc = escenario(current_phase=en)

        resp = client_as(esc.student).get(url, follow_redirects=False)

        assert resp.status_code == 302, resp.text[:300]
        assert resp.headers["location"] == DASH + "?fase=" + str(fase)

    @pytest.mark.parametrize("url,en", [
        ("/titulatec/student/documents", 1),
        ("/titulatec/student/cita", 2),
        ("/titulatec/student/formato-b", 3),
    ])
    def test_la_pagina_de_la_fase_en_curso_sigue_abierta(self, url, en, escenario,
                                                         client_as):
        """Positivo de la MISMA ruta: la guarda no puede ser un 'no' universal."""
        esc = escenario(current_phase=en)

        resp = client_as(esc.student).get(url, follow_redirects=False)

        assert resp.status_code == 200, resp.text[:300]

    def test_sin_proceso_la_pagina_sigue_mostrando_su_estado_vacio(
        self, seed_phase_defs, seed_document_types, make_student, client_as,
    ):
        """Contrato previo intacto: sin proceso no hay fase que guardar."""
        seed_phase_defs()
        seed_document_types(DOC_TYPES)
        alumno = make_student(perm_codes=STUDENT_ALL_PERMS)

        resp = client_as(alumno).get("/titulatec/student/formato-b",
                                     follow_redirects=False)

        assert resp.status_code == 200
        assert "Sin proceso activo" in resp.text


class TestParcialesYMutacionesDeOtraFase:
    """Parciales HTMX y mutaciones -> 400 + X-Tt-Error (nunca un redirect: htmx
    lo seguiria y meteria el dashboard entero dentro de un fragmento)."""

    # (alias, metodo, url, kwargs de request, fase de la ruta)
    ACCIONES = [
        ("fb_step_get", "GET", "/titulatec/student/formato-b/step/2", {}, 3),
        ("fb_step_save", "POST", "/titulatec/student/formato-b/step/1",
         {"data": {"first_name": "X"}}, 3),
        ("fb_submit", "POST", "/titulatec/student/formato-b/step/3",
         {"data": {"project_name": "X"}}, 3),
        ("doc_upload", "POST", "/titulatec/student/documents/curp",
         {"files": {"archivo": PDF}}, 1),
        ("doc_delete", "DELETE", "/titulatec/student/documents/curp", {}, 1),
        ("phase1_submit", "POST", "/titulatec/student/phase/1/submit", {}, 1),
        ("cita_confirm", "POST", "/titulatec/student/cita/confirmar", {}, 2),
        ("cita_change", "POST", "/titulatec/student/cita/solicitar-cambio",
         {"data": {"reason": "no puedo"}}, 2),
    ]
    IDS = [a[0] for a in ACCIONES]

    @staticmethod
    def _call(cli, method, url, kwargs):
        return getattr(cli, method.lower())(url, **kwargs)

    @pytest.mark.parametrize("alias,method,url,kwargs,fase", ACCIONES, ids=IDS)
    def test_una_fase_futura_no_se_ejecuta(self, alias, method, url, kwargs, fase,
                                           escenario, client_as):
        """Se ejecuta desde la fase 0 (convocatoria): las 3 son futuras."""
        esc = escenario(current_phase=0, docs=TODOS_APROBADOS, appt_status="scheduled")

        resp = self._call(client_as(esc.student), method, url, kwargs)

        assert resp.status_code == 400, "[" + alias + "] " + resp.text[:300]
        assert resp.headers.get("X-Tt-Error"), "[" + alias + "] sin canal de error"

    @pytest.mark.parametrize("alias,method,url,kwargs,fase", ACCIONES, ids=IDS)
    def test_una_fase_ya_cerrada_es_inmutable(self, alias, method, url, kwargs, fase,
                                              escenario, client_as):
        """Se ejecuta desde la fase 4: las fases 1, 2 y 3 quedaron atras."""
        esc = escenario(current_phase=4, docs=TODOS_APROBADOS, appt_status="attended")

        resp = self._call(client_as(esc.student), method, url, kwargs)

        assert resp.status_code == 400, "[" + alias + "] " + resp.text[:300]
        assert resp.headers.get("X-Tt-Error"), "[" + alias + "] sin canal de error"

    @pytest.mark.parametrize("alias,method,url,kwargs,fase", ACCIONES, ids=IDS)
    def test_la_fase_en_curso_si_se_ejecuta(self, alias, method, url, kwargs, fase,
                                            escenario, client_as):
        """Positivo de la MISMA ruta y el MISMO actor, con el proceso en su fase."""
        esc = escenario(current_phase=fase, docs=TODOS_APROBADOS,
                        appt_status="scheduled")

        resp = self._call(client_as(esc.student), method, url, kwargs)

        assert resp.status_code in (200, 204), "[" + alias + "] " + resp.text[:300]


class TestProcesoQueYaNoAdmiteCambios:
    """Tercera regla de la gemela: `process.status != 'active'` cierra todo."""

    @pytest.mark.parametrize("status", ["completed", "cancelled", "on_hold"])
    def test_ninguna_accion_del_alumno_toca_un_proceso_no_activo(
        self, status, escenario, client_as, db_session,
    ):
        esc = escenario(current_phase=1, status=status, docs=TODOS_APROBADOS)

        resp = client_as(esc.student).post("/titulatec/student/phase/1/submit")

        assert resp.status_code == 400, resp.text[:300]
        assert status in resp.headers.get("X-Tt-Error", "")
        assert _phases(db_session, esc.process.id)[1] == "in_progress"

    def test_la_pagina_de_un_proceso_no_activo_manda_al_acordeon(self, escenario,
                                                                 client_as):
        esc = escenario(current_phase=1, status="cancelled")

        resp = client_as(esc.student).get("/titulatec/student/documents",
                                          follow_redirects=False)

        assert resp.status_code == 302
        assert resp.headers["location"] == DASH + "?fase=1"


class TestTipoDeDocumentoDeOtraFase:
    """Agujero propio del inventario, no del reporte.

    `POST/DELETE /student/documents/{type_code}` resolvian el `DocumentType`
    **sin mirar su `phase_number`**: la fase que se guarda es la del TIPO
    (`DocumentService.save` -> `phase_number=dtype.phase_number`), asi que un
    alumno en la fase 1 podia sembrar y borrar documentos de las fases 6, 7 y 8.
    """

    def test_no_sube_un_documento_de_la_fase_6_estando_en_la_1(self, escenario,
                                                               client_as, db_session):
        esc = escenario(current_phase=1)

        resp = client_as(esc.student).post("/titulatec/student/documents/anexo_iii",
                                           files={"archivo": PDF})

        assert resp.status_code == 400, resp.text[:300]
        assert "anexo_iii" not in _docs(db_session, esc.process.id)

    def test_no_borra_un_documento_de_la_fase_8_estando_en_la_1(self, escenario,
                                                                client_as, db_session):
        esc = escenario(current_phase=1, docs=(("final_project", "approved"),))

        resp = client_as(esc.student).delete("/titulatec/student/documents/final_project")

        assert resp.status_code == 400, resp.text[:300]
        assert _docs(db_session, esc.process.id).get("final_project") == "approved"

    def test_el_documento_de_la_fase_en_curso_si_se_sube(self, escenario, client_as,
                                                         db_session):
        """Positivo del MISMO par de rutas: el tipo de la fase actual pasa."""
        esc = escenario(current_phase=1)

        resp = client_as(esc.student).post("/titulatec/student/documents/curp",
                                           files={"archivo": PDF})

        assert resp.status_code == 200, resp.text[:300]
        assert _docs(db_session, esc.process.id).get("curp") == "pending"

    def test_un_tipo_inexistente_sigue_dando_404(self, escenario, client_as):
        """El 404 de "ese tipo no existe" es anterior a la guarda y no cambia."""
        esc = escenario(current_phase=1)

        resp = client_as(esc.student).post("/titulatec/student/documents/no_existe",
                                           files={"archivo": PDF})

        assert resp.status_code == 404


# ===========================================================================
# 3. Los dos casos legitimos que la guarda NO puede romper
# ===========================================================================
class TestFaseRechazada:
    """`rejected` con `current_phase` apuntando a esa fase es un caso VALIDO.

    `PhaseService.reject_phase` deja `ph.status='rejected'` y
    `process.current_phase = phase_number` (`phase_service.py:209-213`): el
    alumno TIENE que poder corregir y reenviar. Si la guarda mirara el `status`
    de la fase en vez de `current_phase`, aqui se cerraria la puerta al unico
    camino de correccion que tiene el proceso.
    """

    def test_reenvia_la_fase_1_rechazada(self, escenario, client_as, db_session):
        esc = escenario(current_phase=1, docs=TODOS_APROBADOS,
                        phase_overrides={1: "rejected"})

        subida = client_as(esc.student).post("/titulatec/student/documents/curp",
                                             files={"archivo": PDF})
        reenvio = client_as(esc.student).post("/titulatec/student/phase/1/submit")

        assert subida.status_code == 200, subida.text[:300]
        assert reenvio.status_code == 204, reenvio.text[:300]
        assert _phases(db_session, esc.process.id)[1] == "in_review"

    def test_corrige_y_reenvia_el_formato_b_rechazado(self, escenario, client_as,
                                                      db_session):
        esc = escenario(current_phase=3, phase_overrides={3: "rejected"})

        pagina = client_as(esc.student).get("/titulatec/student/formato-b",
                                            follow_redirects=False)
        guardado = client_as(esc.student).post("/titulatec/student/formato-b/step/1",
                                               data={"first_name": "CORREGIDO"})
        envio = client_as(esc.student).post("/titulatec/student/formato-b/step/3",
                                            data={"project_name": "Proyecto corregido"})

        assert pagina.status_code == 200, pagina.text[:300]
        assert guardado.status_code == 200, guardado.text[:300]
        assert envio.status_code == 200, envio.text[:300]
        assert _phases(db_session, esc.process.id)[3] == "in_review"
        assert _format_b(db_session, esc.process.id).status == "submitted"


class TestLaCitaSigueViva:
    """La cita es de la fase 2 y debe seguir funcionando cuando esa es la actual."""

    def test_confirma_su_cita_en_la_fase_2(self, escenario, client_as, db_session):
        esc = escenario(current_phase=2, appt_status="scheduled")

        resp = client_as(esc.student).post("/titulatec/student/cita/confirmar")

        assert resp.status_code == 200, resp.text[:300]
        db_session.refresh(esc.appt)
        assert esc.appt.status == "confirmed"
        assert esc.appt.confirmed_at is not None

    def test_solicita_cambio_de_cita_en_la_fase_2(self, escenario, client_as, db_session):
        from itcj2.apps.titulatec.services.appointment_service import AppointmentService

        esc = escenario(current_phase=2, appt_status="scheduled")

        resp = client_as(esc.student).post("/titulatec/student/cita/solicitar-cambio",
                                           data={"reason": "tengo examen ese dia"})

        assert resp.status_code == 200, resp.text[:300]
        db_session.refresh(esc.appt)
        assert esc.appt.change_request == "tengo examen ese dia"

    def test_no_confirma_la_cita_desde_la_fase_1(self, escenario, client_as, db_session):
        """El negativo del MISMO par: la cita existe pero aun no es su fase."""
        esc = escenario(current_phase=1, appt_status="scheduled")

        resp = client_as(esc.student).post("/titulatec/student/cita/confirmar")

        assert resp.status_code == 400, resp.text[:300]
        db_session.refresh(esc.appt)
        assert esc.appt.status == "scheduled"
        assert esc.appt.confirmed_at is None


# ===========================================================================
# 4. La guarda vista desde el service (gemela de TestGuardaEnElService)
# ===========================================================================
class TestGuardaEnElService:
    def test_la_fase_en_curso_pasa(self, db_session, escenario):
        esc = escenario(current_phase=2)

        assert PhaseService.assert_student_can_act(db_session, esc.process, 2) == 2
        assert PhaseService.can_student_act(db_session, esc.process, 2) is True

    def test_una_fase_futura_no_pasa(self, db_session, escenario):
        esc = escenario(current_phase=1)

        with pytest.raises(ValueError):
            PhaseService.assert_student_can_act(db_session, esc.process, 3)
        assert PhaseService.can_student_act(db_session, esc.process, 3) is False

    def test_una_fase_pasada_no_pasa(self, db_session, escenario):
        esc = escenario(current_phase=3)

        with pytest.raises(ValueError):
            PhaseService.assert_student_can_act(db_session, esc.process, 1)

    def test_un_proceso_no_activo_no_pasa_ni_en_su_fase(self, db_session, escenario):
        esc = escenario(current_phase=8, status="completed")

        with pytest.raises(ValueError):
            PhaseService.assert_student_can_act(db_session, esc.process, 8)

    def test_una_fase_fuera_del_catalogo_no_pasa(self, db_session, escenario):
        esc = escenario(current_phase=1)

        with pytest.raises(ValueError):
            PhaseService.assert_student_can_act(db_session, esc.process, 99)

    def test_sin_numero_de_fase_falla_cerrado(self, db_session, escenario):
        """`DocumentType.phase_number` es nullable: un tipo sin fase no habilita nada."""
        esc = escenario(current_phase=1)

        assert PhaseService.can_student_act(db_session, esc.process, None) is False

    def test_el_numero_de_fase_sale_del_catalogo_no_de_un_literal(self, db_session,
                                                                  escenario):
        escenario(current_phase=1)

        assert PhaseService.phase_number_for_code(db_session, "initial_docs") == 1
        assert PhaseService.phase_number_for_code(db_session, "review_appointment") == 2
        assert PhaseService.phase_number_for_code(db_session, "format_b") == 3
        assert PhaseService.phase_number_for_code(db_session, "no_existe") is None

    def test_los_mensajes_son_ascii(self, db_session, escenario):
        """Van por `X-Tt-Error`, y Starlette lo escribe latin-1 pero su TestClient
        lo lee UTF-8: un byte >127 tumba el request entero (mismo motivo que
        `PhaseService._transition_error`)."""
        esc = escenario(current_phase=1, status="cancelled")

        mensajes = []
        for n in (0, 1, 3, 99, None):
            try:
                PhaseService.assert_student_can_act(db_session, esc.process, n)
            except ValueError as exc:
                mensajes.append(str(exc))

        assert mensajes, "ninguna de las cinco entradas fue rechazada"
        for msg in mensajes:
            assert msg.isascii(), "mensaje con byte >127: " + repr(msg)


# ===========================================================================
# 5. Anti-regresion estructural: ninguna ruta nueva del alumno nace sin guarda
# ===========================================================================
# Las 3 rutas del alumno que NO estan atadas a una fase, con el porque:
#   - dashboard: es el acordeon informativo de las 9 fases (el destino del 302).
#   - perfil:    identidad + resumen del proceso, sin accion de fase.
#   - fase/{n}:  compat de notificaciones viejas; ya redirige al acordeon.
RUTAS_SIN_FASE = {
    ("GET", "/student/dashboard"),
    ("GET", "/student/perfil"),
    ("GET", "/student/fase/{n}"),
}


def test_toda_ruta_del_alumno_atada_a_una_fase_invoca_la_guarda():
    """Falla en rojo ante cualquier ruta nueva del alumno que no decida.

    O lleva la guarda (`_phase_guard` / `_phase_guard_page`), o entra a
    `RUTAS_SIN_FASE` con su justificacion escrita. No hay tercera opcion: el
    modo de fallo del olvido seria ABIERTO, que es exactamente el defecto que
    estos tests documentan.
    """
    import inspect

    from itcj2.apps.titulatec.pages.student import router as student_router

    sin_guarda, revisadas = [], 0
    for route in student_router.routes:
        path = getattr(route, "path", "")
        for method in sorted(getattr(route, "methods", []) or []):
            if method in ("HEAD", "OPTIONS"):
                continue
            revisadas += 1
            if (method, path) in RUTAS_SIN_FASE:
                continue
            if "_phase_guard" not in inspect.getsource(route.endpoint):
                sin_guarda.append(method + " " + path)

    assert revisadas == 13, "cambio el inventario de rutas del alumno: " + str(revisadas)
    assert not sin_guarda, ("rutas del alumno sin guarda de fase:\n"
                            + "\n".join(sin_guarda))
