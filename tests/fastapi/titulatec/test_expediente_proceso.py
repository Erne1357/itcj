"""El expediente del alumno: `/titulatec/admin/processes/{id}`.

Antes esta pagina era una pila de cuatro tarjetas que decia **como esta** el
proceso y no **que paso**. `ProcessEvent` guardaba once tipos de suceso con
actor y payload desde que existen `phase_service` y `appointment_service`, y
ninguna pantalla del personal leia uno solo.

Este archivo cubre las tres partes del rediseno:

1. **La bitacora que faltaba.** `DocumentService` no escribia ningun evento, asi
   que subir, aprobar, rechazar y borrar un documento no dejaban rastro. Con el
   archivo sobreescribiendose en disco (nombre fijo por tipo), eso significaba
   que de un documento rechazado y vuelto a subir no quedaba absolutamente nada.
2. **El expediente.** Acordeon de las 9 fases, con el historial de cada una,
   los documentos de SOLO LECTURA (el dictamen vive en la bandeja de Documentos,
   que si exige motivo al rechazar) y el menu Acciones para mover de fase.
3. **La vuelta.** La pagina se alcanza desde cuatro pestanas y hasta hoy no
   tenia salida: se volvia por el menu lateral, perdiendo filtro, dia y alumno.

Decisiones del usuario (2026-09-03) que estos tests fijan:

* Historial de documentos = bitacora; se abre la version vigente, no las viejas.
* De la fase 3 en adelante NO se toca: el bloque de Formato B se traslada literal.
* «Mover de fase» vive en el menu Acciones de la cabecera.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import pytest

URL = "/titulatec/admin/processes"


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _events(db, process_id, tipo=None):
    from itcj2.apps.titulatec.models import ProcessEvent
    q = db.query(ProcessEvent).filter_by(process_id=process_id)
    if tipo:
        q = q.filter_by(event_type=tipo)
    return q.order_by(ProcessEvent.id).all()


@pytest.fixture()
def sin_disco(monkeypatch):
    """`DocumentService.save` sin tocar el disco.

    Se parchea `storage.save_document`, no `DocumentService`: lo que se prueba es
    que el servicio escribe el evento, y para eso el guardado real de bytes es
    ruido (necesitaria `TITULATEC_UPLOAD_PATH` y un PDF de verdad).
    """
    from itcj2.apps.titulatec.utils import storage

    def _fake(*, raw, original_name, content_type, period_code, control_number,
              type_code, file_kind):
        return {"file_path": f"tt-test/{control_number}/{type_code}.pdf",
                "original_name": original_name, "mime_type": "application/pdf",
                "size_bytes": len(raw)}

    monkeypatch.setattr(storage, "save_document", _fake)
    return _fake


@pytest.fixture()
def expediente(seed_phase_defs, seed_document_types, make_program, make_cohort,
               make_officer, make_student, make_process):
    """Un proceso en fase 2 con encargado que puede verlo."""
    def _build(current_phase=2, status="active"):
        seed_phase_defs()
        seed_document_types()
        prog = make_program("Ingenieria del Expediente")
        cohort = make_cohort()
        officer, _pos = make_officer([prog])
        student = make_student(first_name="ANA", last_name="EXPEDIENTE")
        proc = make_process(student, cohort=cohort, program=prog,
                            current_phase=current_phase, status=status)
        return {"officer": officer, "student": student, "proc": proc,
                "program": prog, "cohort": cohort}
    return _build


# ===========================================================================
# 1. La bitacora de documentos (no existia ninguna)
# ===========================================================================
def test_subir_un_documento_deja_evento(db_session, expediente, sin_disco):
    """Sin esto, «subio el acta el 3 y la volvio a subir el 5» no se puede saber:
    la fila se pisa a si misma y el archivo en disco tambien."""
    from itcj2.apps.titulatec.services.document_service import DocumentService
    esc = expediente()

    DocumentService.save(db_session, esc["proc"], "birth_certificate",
                         raw=b"%PDF-1.4 x", original_name="acta.pdf",
                         content_type="application/pdf",
                         uploaded_by_id=esc["student"].id)

    evs = _events(db_session, esc["proc"].id, "document_uploaded")
    assert len(evs) == 1, "subir un documento no dejo rastro"
    ev = evs[0]
    assert ev.phase_number == 1, "el evento tiene que colgar de la fase del TIPO"
    assert ev.actor_id == esc["student"].id
    assert ev.payload["type_code"] == "birth_certificate"
    assert ev.payload["original_name"] == "acta.pdf"
    assert ev.payload["version"] == 1


def test_resubir_cuenta_la_version(db_session, expediente, sin_disco):
    """La version es lo unico que distingue las dos entradas: el archivo de la
    primera ya no existe cuando llega la segunda."""
    from itcj2.apps.titulatec.services.document_service import DocumentService
    esc = expediente()
    for _ in range(2):
        DocumentService.save(db_session, esc["proc"], "curp",
                             raw=b"%PDF-1.4 x", original_name="curp.pdf",
                             content_type="application/pdf",
                             uploaded_by_id=esc["student"].id)

    versiones = [e.payload["version"] for e in _events(db_session, esc["proc"].id,
                                                       "document_uploaded")]
    assert versiones == [1, 2]


def test_dictaminar_deja_evento_con_el_motivo(db_session, expediente, make_document):
    """El motivo del rechazo vive hoy en `review_note`, que la siguiente revision
    PISA. Sin evento, el historial no puede decir por que se rechazo la vez
    anterior."""
    from itcj2.apps.titulatec.services.document_service import DocumentService
    esc = expediente()
    make_document(esc["proc"], type_code="curp")

    DocumentService.review(db_session, esc["proc"].id, "curp", status="rejected",
                           note="Falta el sello", reviewer_id=esc["officer"].id)
    DocumentService.review(db_session, esc["proc"].id, "curp", status="approved",
                           note=None, reviewer_id=esc["officer"].id)

    rech = _events(db_session, esc["proc"].id, "document_rejected")
    apro = _events(db_session, esc["proc"].id, "document_approved")
    assert len(rech) == 1 and len(apro) == 1
    assert rech[0].payload["note"] == "Falta el sello", (
        "el motivo se perdio: `review_note` ya vale lo de la aprobacion")
    assert rech[0].phase_number == 1
    assert apro[0].actor_id == esc["officer"].id


def test_borrar_un_documento_deja_evento(db_session, expediente, make_document,
                                         monkeypatch):
    """El alumno puede borrar el suyo. Un hueco en el expediente sin explicacion
    se lee como «nunca lo subio»."""
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.utils import storage
    monkeypatch.setattr(storage, "delete_document_file", lambda _p: None)
    esc = expediente()
    make_document(esc["proc"], type_code="high_school_cert")

    DocumentService.delete(db_session, esc["proc"].id, "high_school_cert",
                           actor_id=esc["student"].id)

    evs = _events(db_session, esc["proc"].id, "document_deleted")
    assert len(evs) == 1
    assert evs[0].payload["type_code"] == "high_school_cert"
    assert evs[0].actor_id == esc["student"].id


def test_el_alta_del_alumno_deja_evento(db_session, seed_phase_defs, make_cohort,
                                        make_program, make_head):
    """La fase 0 es «Convocatoria» y su unico suceso es el alta. Sin este evento
    el expediente empieza en blanco y no dice ni como entro el alumno."""
    from itcj2.apps.titulatec.models import TitulationProcess
    from itcj2.apps.titulatec.services.import_service import ImportService
    seed_phase_defs()
    cohort = make_cohort()
    prog = make_program("Ingenieria del Alta")
    jefa = make_head()

    ImportService.import_rows(db_session, cohort, [{
        "control_number": "29990001", "full_name": "BRENDA ALTA PRUEBA",
        "email": None, "program_id": prog.id, "modality_id": None,
    }], actor_id=jefa.id, source="csv")

    proc = (db_session.query(TitulationProcess)
            .filter_by(cohort_id=cohort.id).order_by(TitulationProcess.id.desc()).first())
    evs = _events(db_session, proc.id, "process_created")
    assert len(evs) == 1, "dar de alta a un alumno no dejo rastro"
    assert evs[0].phase_number == 0
    assert evs[0].actor_id == jefa.id
    assert evs[0].payload["source"] == "csv"
    assert evs[0].payload["folio"] == proc.folio


# ===========================================================================
# 2. El expediente: acordeon de fases con su historial
# ===========================================================================
def test_estan_las_nueve_fases(expediente, client_as):
    esc = expediente()
    html = client_as(esc["officer"]).get(f"{URL}/{esc['proc'].id}").text
    filas = re.findall(r'data-tt-phase="(\d)"', html)
    assert sorted(set(filas)) == [str(n) for n in range(9)], f"fases: {filas}"


def test_la_fase_actual_llega_abierta(expediente, client_as):
    """En una pagina de nueve desplegables, la que importa al abrir es en la que
    esta el alumno; obligar a buscarla y pulsarla es trabajo regalado."""
    esc = expediente(current_phase=2)
    html = client_as(esc["officer"]).get(f"{URL}/{esc['proc'].id}").text
    panel = re.search(r'id="exp-panel-2"[^>]*', html).group(0)
    assert "hidden" not in panel, "la fase actual llego cerrada"
    otro = re.search(r'id="exp-panel-5"[^>]*', html).group(0)
    assert "hidden" in otro


def test_el_deep_link_de_fase_abre_esa(expediente, client_as):
    """`?fase=N` es lo que hace enlazable un punto concreto del expediente."""
    esc = expediente(current_phase=2)
    html = client_as(esc["officer"]).get(f"{URL}/{esc['proc'].id}?fase=1").text
    assert "hidden" not in re.search(r'id="exp-panel-1"[^>]*', html).group(0)


def test_una_fase_fuera_de_rango_no_rompe(expediente, client_as):
    """`?fase=99` y `?fase=abc` llegan de un enlace viejo o de un dedo torpe."""
    esc = expediente()
    for crudo in ("99", "-3", "abc", ""):
        r = client_as(esc["officer"]).get(f"{URL}/{esc['proc'].id}?fase={crudo}")
        assert r.status_code == 200, f"?fase={crudo} rompio la pagina"


def test_el_historial_de_la_cita_sale_en_su_fase(expediente, client_as, db_session,
                                                 make_appointment):
    """Lo que el usuario pidio con nombre propio: «si falto o se reagendo, que
    salga un historial»."""
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    esc = expediente(current_phase=2)
    appt = make_appointment(esc["proc"], status="scheduled")
    AppointmentService.mark_no_show(db_session, appt, esc["officer"].id)

    html = client_as(esc["officer"]).get(f"{URL}/{esc['proc'].id}?fase=2").text
    panel = html.split('id="exp-panel-2"')[1].split('id="exp-panel-3"')[0]
    assert "No se present" in panel, "la falta no aparece en el historial de la cita"


def test_el_historial_nombra_a_quien_lo_hizo(expediente, client_as, db_session,
                                             make_appointment):
    """«Rechazada» sin autor obliga a preguntar por el pasillo quien fue."""
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    esc = expediente(current_phase=2)
    appt = make_appointment(esc["proc"])
    AppointmentService.mark_no_show(db_session, appt, esc["officer"].id)

    html = client_as(esc["officer"]).get(f"{URL}/{esc['proc'].id}?fase=2").text
    assert esc["officer"].full_name.split()[0] in html


def test_los_documentos_se_ven_pero_no_se_dictaminan(expediente, client_as,
                                                     make_document):
    """Decision del usuario: aqui solo se ven. El dictamen vive en la bandeja de
    Documentos, que exige motivo al rechazar y auto-avanza la fase; tener dos
    caminos con dos reglas era la razon de quitarlo."""
    esc = expediente(current_phase=1)
    make_document(esc["proc"], type_code="birth_certificate")

    html = client_as(esc["officer"]).get(f"{URL}/{esc['proc'].id}?fase=1").text
    assert "/document/" in html, "no se puede abrir el documento"
    assert "documents/birth_certificate/review" not in html
    assert '"action":"approve"' not in html.replace(" ", ""), (
        "quedo un boton de dictamen de documento en el expediente")


def test_las_fases_sin_implementar_lo_dicen(expediente, client_as):
    """Sinodales y ceremonia tienen modelo y nada mas. Pintar un panel vacio se
    lee como «no ha pasado nada» en vez de «esto todavia no existe»."""
    esc = expediente()
    html = client_as(esc["officer"]).get(f"{URL}/{esc['proc'].id}?fase=5").text
    panel = html.split('id="exp-panel-5"')[1].split("</section>")[0]
    assert "todav" in panel.lower() or "no est" in panel.lower()


def test_el_menu_de_acciones_solo_esta_si_el_proceso_vive(expediente, client_as):
    esc = expediente(status="active")
    html = client_as(esc["officer"]).get(f"{URL}/{esc['proc'].id}").text
    assert 'id="exp-acciones"' in html

    esc2 = expediente(status="cancelled")
    html2 = client_as(esc2["officer"]).get(f"{URL}/{esc2['proc'].id}").text
    assert 'id="exp-acciones"' not in html2


def test_mover_de_fase_no_usa_confirm_nativo(expediente, client_as):
    """Regla del proyecto: nada de `confirm()`/`alert()`. El motivo del rechazo
    ademas no cabe en un `confirm`."""
    esc = expediente()
    html = client_as(esc["officer"]).get(f"{URL}/{esc['proc'].id}").text
    assert "confirm(" not in html and "alert(" not in html


# ===========================================================================
# 3. La vuelta al sitio del que se vino
# ===========================================================================
@pytest.mark.parametrize("origen,etiqueta", [
    ("/titulatec/admin/documents?status=pending", "Documentos"),
    ("/titulatec/admin/appointments?v=atender&date=2029-05-07", "Citas de cotejo"),
    ("/titulatec/admin/cohorts/3", "Convocatoria"),
    ("/titulatec/admin/processes?view=board&stuck=1", "Procesos"),
])
def test_regresar_vuelve_al_origen_con_sus_filtros(expediente, client_as, origen, etiqueta):
    from urllib.parse import quote
    esc = expediente()
    html = client_as(esc["officer"]).get(
        f"{URL}/{esc['proc'].id}?from={quote(origen, safe='')}").text
    fila = re.search(r'id="exp-back"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', html, re.S)
    assert fila, "no hay boton de regresar"
    assert fila.group(1) == origen
    assert etiqueta in fila.group(2)


@pytest.mark.parametrize("malicioso", [
    "https://evil.example/x",
    "//evil.example/x",
    "/itcj/dashboard",
    "javascript:alert(1)",
    "/titulatec/admin/../../../etc/passwd",
])
def test_un_regreso_fuera_de_la_app_cae_a_procesos(expediente, client_as, malicioso):
    """`?from=` es una URL que llega del cliente y se pinta en un `href`: sin
    validar, es un redirector abierto con la marca de la escuela."""
    from urllib.parse import quote
    esc = expediente()
    html = client_as(esc["officer"]).get(
        f"{URL}/{esc['proc'].id}?from={quote(malicioso, safe='')}").text
    href = re.search(r'id="exp-back"[^>]*href="([^"]*)"', html).group(1)
    assert href == "/titulatec/admin/processes", f"acepto {malicioso!r}"


def test_sin_from_regresa_a_procesos(expediente, client_as):
    esc = expediente()
    html = client_as(esc["officer"]).get(f"{URL}/{esc['proc'].id}").text
    href = re.search(r'id="exp-back"[^>]*href="([^"]*)"', html).group(1)
    assert href == "/titulatec/admin/processes"


# ===========================================================================
# 4. Las cuatro pestanas enlazan al expediente
# ===========================================================================
def test_la_bandeja_de_procesos_enlaza_con_su_filtro(expediente, client_as):
    esc = expediente()
    html = client_as(esc["officer"]).get("/titulatec/admin/processes?view=board").text
    assert f"/titulatec/admin/processes/{esc['proc'].id}?from=" in html


def test_la_bandeja_de_documentos_enlaza(expediente, client_as, make_document):
    esc = expediente(current_phase=1)
    make_document(esc["proc"], type_code="birth_certificate")
    html = client_as(esc["officer"]).get(
        f"/titulatec/admin/documents?selected={esc['proc'].id}").text
    assert f"/titulatec/admin/processes/{esc['proc'].id}?from=" in html


def test_las_citas_enlazan(expediente, client_as, make_appointment, make_review_day):
    esc = expediente(current_phase=2)
    dia = date.today() + timedelta(days=7)
    make_review_day(esc["cohort"], day=dia)
    make_appointment(esc["proc"], when=datetime.combine(
        dia, datetime.min.time()).replace(hour=10))
    html = client_as(esc["officer"]).get(
        f"/titulatec/admin/appointments?v=atender&date={dia.isoformat()}"
        f"&selected={esc['proc'].id}").text
    assert f"/titulatec/admin/processes/{esc['proc'].id}?from=" in html


def test_la_convocatoria_enlaza(expediente, client_as, make_head):
    esc = expediente()
    jefa = make_head()
    html = client_as(jefa).get(f"/titulatec/admin/cohorts/{esc['cohort'].id}").text
    assert f"/titulatec/admin/processes/{esc['proc'].id}?from=" in html


# ===========================================================================
# 5. Lo que se quito y lo que no puede crecer
# ===========================================================================
def test_la_ruta_de_dictamen_de_documentos_del_expediente_ya_no_existe():
    """Habia DOS endpoints para dictaminar el mismo documento, con reglas
    distintas: el de la bandeja exige motivo al rechazar, este no lo pedia.
    """
    from itcj2.main import create_app
    rutas = {getattr(r, "name", "") for r in create_app().routes}
    assert "titulatec.pages.admin.doc_review" not in rutas


def test_el_expediente_no_hace_una_consulta_por_documento(expediente, client_as,
                                                          make_document, db_session):
    """`_detail_ctx` consultaba `DocumentType` UNA VEZ POR CODIGO. Con el
    historial encima, un N+1 aqui se multiplica por fase."""
    from sqlalchemy import event

    esc = expediente(current_phase=1)
    cli = client_as(esc["officer"])
    url = f"{URL}/{esc['proc'].id}"

    def _contar():
        n = [0]
        motor = db_session.get_bind()

        def _hook(*_a, **_k):
            n[0] += 1

        event.listen(motor, "before_cursor_execute", _hook)
        try:
            cli.get(url)
        finally:
            event.remove(motor, "before_cursor_execute", _hook)
        return n[0]

    _contar()                                   # calienta el cache de authz
    con_uno = _contar()
    for code in ("birth_certificate", "high_school_cert", "curp"):
        make_document(esc["proc"], type_code=code)
    con_tres = _contar()

    assert con_tres <= con_uno, (
        f"la pagina crece con los documentos: {con_uno} -> {con_tres} consultas")
