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

import pathlib
import re
from datetime import date, datetime, timedelta

import itcj2.apps.titulatec as _tt_pkg

import pytest

from tests.fastapi.titulatec.conftest import OFFICER_PERMS

JS = (pathlib.Path(_tt_pkg.__file__).resolve().parent
      / "static" / "js" / "admin" / "expediente.js")

URL = "/titulatec/admin/processes"
# Enlace al expediente desde otra pestana, con su query de vuelta.
PAT = r'href="(/titulatec/admin/processes/%d\?[^"]*)"'


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _msg(resp) -> str:
    """El `X-Tt-Error` ya decodificado (el servidor lo percent-codifica)."""
    from urllib.parse import unquote
    return unquote(resp.headers.get("X-Tt-Error", ""))


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
def en_disco(monkeypatch):
    """Hace que todo `file_path` exista.

    `make_document` NO escribe en disco (lo dice su docstring), y el expediente
    resuelve `missing` mirando el disco de verdad: sin esto, cada documento de
    prueba sale como «Archivo perdido» y el visor nunca aparece.
    """
    from pathlib import Path
    from itcj2.apps.titulatec.utils import storage
    monkeypatch.setattr(storage, "abs_path", lambda _rel: Path("/app/pytest.ini"))


# El encargado del expediente ve y ADEMAS mueve de fase: es la unica accion que
# queda en esta pagina, y sin el permiso las pruebas de «mover de fase» darian
# 403 y pasarian por buenas negativas que no prueban nada.
EXPEDIENTE_PERMS = OFFICER_PERMS + (
    "titulatec.process.api.approve_phase",
    "titulatec.process.api.reject_phase",
)


@pytest.fixture()
def expediente(seed_phase_defs, seed_document_types, make_program, make_cohort,
               make_officer, make_student, make_process):
    """Un proceso en fase 2 con encargado que puede verlo y moverlo de fase."""
    def _build(current_phase=2, status="active"):
        seed_phase_defs()
        seed_document_types()
        prog = make_program("Ingenieria del Expediente")
        cohort = make_cohort()
        officer, _pos = make_officer([prog], perm_codes=EXPEDIENTE_PERMS)
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
                                                     make_document, en_disco):
    """Decision del usuario: aqui solo se ven. El dictamen vive en la bandeja de
    Documentos, que exige motivo al rechazar y auto-avanza la fase al aprobar el
    tercero; tener dos caminos con dos reglas era la razon de quitarlo.

    La asercion se acota AL PANEL DE LA FASE 1: buscar «action: approve» en toda
    la pagina la haria depender de si el alumno tiene Formato B enviado, que no
    tiene nada que ver con lo que este test afirma.
    """
    esc = expediente(current_phase=1)
    make_document(esc["proc"], type_code="birth_certificate")

    html = client_as(esc["officer"]).get(f"{URL}/{esc['proc'].id}?fase=1").text
    panel = html.split('id="exp-panel-1"')[1].split('id="exp-fase-2"')[0]

    assert "/document/birth_certificate" in panel, "no se puede abrir el documento"
    assert "review" not in panel, "quedo un camino de dictamen en el panel de la fase 1"
    assert '"action":"approve"' not in panel.replace(" ", "")
    assert "Dictaminar en la bandeja" in panel, (
        "se quito el dictamen sin dejar por donde se hace")


def test_un_archivo_perdido_lo_dice_en_vez_de_ofrecer_verlo(expediente, client_as,
                                                            make_document):
    """La fila existe en la base y el archivo no esta en disco. Ofrecer «Ver»
    manda a un 404; callarlo hace pensar que el alumno no subio nada."""
    esc = expediente(current_phase=1)
    make_document(esc["proc"], type_code="curp", file_path="no/existe/curp.pdf")

    html = client_as(esc["officer"]).get(f"{URL}/{esc['proc'].id}?fase=1").text
    panel = html.split('id="exp-panel-1"')[1].split('id="exp-fase-2"')[0]
    assert "Archivo perdido" in panel


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


def test_rechazar_una_fase_sin_motivo_no_pasa(expediente, client_as):
    """El alumno solo ve lo que se escribe aqui. «Fase rechazada» a secas lo
    manda a preguntar en ventanilla, que es el viaje que esta app viene a
    quitar. La bandeja de Documentos ya lo exigia; este era el otro camino.
    """
    esc = expediente(current_phase=2)
    cli = client_as(esc["officer"])
    url = f"{URL}/{esc['proc'].id}/phase/2/reject"

    vacio = cli.post(url, data={"reason": "   "})
    assert vacio.status_code == 400
    assert "motivo" in _msg(vacio)

    # La positiva del mismo actor sobre la MISMA ruta: sin ella, una guarda que
    # dijera que no SIEMPRE pasaria por buena.
    bueno = cli.post(url, data={"reason": "Falta la firma del asesor"})
    assert bueno.status_code == 200


def test_un_error_con_acentos_llega_legible(expediente, client_as, make_head):
    """Los headers HTTP son latin-1: un mensaje con acentos SIN percent-codificar
    llega al cliente como bytes que no son UTF-8 validos y revienta al
    decodificarlos. `pages/admin.py` escribia «Falta el número de control» a
    pelo desde que existe, y ninguna prueba pasaba por esa rama.

    Se prueba contra el alta manual porque es la rama con acento de verdad; el
    mensaje del rechazo de fase no lleva ninguno y no probaria nada.
    """
    esc = expediente()
    jefa = make_head()
    r = client_as(jefa).post(f"/titulatec/admin/cohorts/{esc['cohort'].id}/students",
                             data={"control_number": ""})
    assert r.status_code == 400
    assert _msg(r) == "Falta el número de control.", (
        "el mensaje llego roto: se perdio la codificacion del header")


def test_las_acciones_conservan_la_zona(expediente, client_as):
    """Aprobar una fase devuelve el expediente ENTERO. Si `fase`, `doc` y `from`
    no viajaran con la accion, al volver estarias en otra fase, con otro
    documento abierto y con el Regresar apuntando a Procesos."""
    from urllib.parse import quote
    esc = expediente(current_phase=2)
    origen = "/titulatec/admin/appointments?v=atender&date=2029-05-07"
    r = client_as(esc["officer"]).post(
        f"{URL}/{esc['proc'].id}/phase/2/reject?fase=1&from={quote(origen, safe='')}",
        data={"reason": "Falta el sello"})
    assert r.status_code == 200
    assert "hidden" not in re.search(r'id="exp-panel-1"[^>]*', r.text).group(0)
    assert "Citas de cotejo" in r.text


def test_el_modal_de_fase_vive_fuera_del_expediente(expediente, client_as):
    """Dentro de `#exp-shell` el dialogo salia CORTADO.

    Medido en Chromium a 1280x900: el `.modal-dialog` daba 1630 px de alto y su
    mitad inferior —el motivo y los dos botones— quedaba fuera de la ventana.

    La causa no es `.tt-admin` (que a >=992 no lleva transform, que es lo que
    dice el comentario de `base.html`), sino `#tt-admin-content`: tiene
    `tt-anim-in` con `animation-fill-mode: both`, asi que al terminar conserva
    `transform: matrix(1,0,0,1,0,0)`. Identidad, pero transform al fin, y eso
    crea bloque contenedor para los descendientes `position: fixed`: el
    `height:100%` del `.modal` pasaba a resolverse contra los 1686 px del
    contenido en vez de contra la ventana.
    """
    esc = expediente()
    html = client_as(esc["officer"]).get(f"{URL}/{esc['proc'].id}").text

    shell = html.split('id="exp-shell"')[1].split('{% endblock %}')[0]
    fin_shell = shell.rfind('id="exp-modal-fase"')
    assert 'id="exp-modal-fase"' in html, "desaparecio el modal de mover de fase"
    # El modal aparece DESPUES del cierre del contenedor del contenido admin.
    i_shell = html.index('id="exp-shell"')
    i_modal = html.index('id="exp-modal-fase"')
    i_cierre = html.index('id="tt-admin-content"')
    assert i_modal > i_shell, "orden inesperado"
    assert 'id="exp-modal-fase"' not in html[i_shell:html.index('id="exp-fases"')], (
        "el modal volvio a la cabecera del expediente")


def test_el_boton_le_pasa_al_modal_lo_que_necesita(expediente, client_as):
    """El modal no entra al swap, asi que no puede venir renderizado con la fase
    actual: se puebla al abrirlo desde los `data-*` del boton, que si se
    re-renderiza con cada accion."""
    from urllib.parse import quote
    esc = expediente(current_phase=2)
    origen = "/titulatec/admin/appointments?v=atender"
    html = client_as(esc["officer"]).get(
        f"{URL}/{esc['proc'].id}?fase=1&from={quote(origen, safe='')}").text

    boton = re.search(r'<button[^>]*id="exp-acciones"[^>]*>', html).group(0)
    for attr in ("data-tt-fase=", "data-tt-fase-nombre=", "data-tt-aprobar=", "data-tt-rechazar="):
        assert attr in boton, f"al modal le falta {attr}"
    assert "/phase/2/approve" in boton and "/phase/2/reject" in boton
    assert "fase=1" in boton, "las URL de accion pierden la zona"


def test_el_modal_se_cierra_solo_al_acertar():
    """Estructural. Si no, el modal se queda tapando un expediente que YA cambio
    detras, y hay que cerrarlo a mano para enterarse de que la accion funciono.
    Al fallar SI se queda abierto: el motivo escrito sigue ahi."""
    src = JS.read_text(encoding="utf-8")
    assert "htmx:afterRequest" in src
    assert "detail.successful" in src
    assert "bootstrap.Modal.getInstance" in src


def test_el_acordeon_recuerda_lo_desplegado():
    """Aprobar una fase devuelve el expediente ENTERO. Sin memoria, el revisor
    perdia en cada accion todo lo que habia desplegado para comparar."""
    src = JS.read_text(encoding="utf-8")
    assert "htmx:afterSettle" in src
    assert "abiertas" in src, "el estado del acordeon no vive en el modulo"
    # Solo el CODIGO: el encabezado del modulo nombra `data-tt-bound` justo para
    # explicar por que NO se usa, y una busqueda en texto plano se acusaba sola.
    codigo = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    codigo = re.sub(r"^\s*//.*$", "", codigo, flags=re.M)
    assert "data-tt-bound" not in codigo, (
        "guarda en el DOM: Idiomorph la borra y los listeners se duplican")


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
    """El `href` se compara DESESCAPADO: Jinja escribe `&amp;` en los atributos,
    que es HTML correcto y el navegador resuelve a `&`. Compararlo crudo haria
    fallar justo los origenes con mas de un filtro, que son los que importan."""
    import html as _html
    from urllib.parse import quote
    esc = expediente()
    pagina = client_as(esc["officer"]).get(
        f"{URL}/{esc['proc'].id}?from={quote(origen, safe='')}").text
    fila = re.search(r'id="exp-back"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', pagina, re.S)
    assert fila, "no hay boton de regresar"
    assert _html.unescape(fila.group(1)) == origen
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
    enlace = re.search(PAT % esc["proc"].id, html)
    assert enlace and "view%3Dboard" in enlace.group(1), (
        "el enlace no lleva la vista actual: volver caeria en la tabla")


def test_la_bandeja_de_documentos_enlaza(expediente, client_as, make_document):
    """Y entra directo a la fase 1, que es la que se estaba dictaminando."""
    esc = expediente(current_phase=1)
    make_document(esc["proc"], type_code="birth_certificate")
    html = client_as(esc["officer"]).get(
        f"/titulatec/admin/documents?selected={esc['proc'].id}").text
    enlace = re.search(PAT % esc["proc"].id, html)
    assert enlace, "la bandeja de Documentos no enlaza al expediente"
    assert "from=" in enlace.group(1) and "fase=1" in enlace.group(1)


def test_las_citas_enlazan(expediente, client_as, make_appointment, make_review_day):
    esc = expediente(current_phase=2)
    dia = date.today() + timedelta(days=7)
    make_review_day(esc["cohort"], day=dia)
    make_appointment(esc["proc"], when=datetime.combine(
        dia, datetime.min.time()).replace(hour=10))
    html = client_as(esc["officer"]).get(
        f"/titulatec/admin/appointments?v=atender&date={dia.isoformat()}"
        f"&selected={esc['proc'].id}").text
    enlace = re.search(PAT % esc["proc"].id, html)
    assert enlace, "la ficha de Atender no enlaza al expediente"
    assert dia.isoformat() in enlace.group(1), (
        "el enlace no lleva el dia: volver caeria en otra fecha")


def test_la_convocatoria_enlaza(expediente, client_as, make_head):
    esc = expediente()
    jefa = make_head()
    html = client_as(jefa).get(
        f"/titulatec/admin/cohorts/{esc['cohort'].id}?tab=alumnos").text
    enlace = re.search(PAT % esc["proc"].id, html)
    assert enlace, "la lista de alumnos de la convocatoria no enlaza al expediente"
    assert "from=" in enlace.group(1)


# ===========================================================================
# 5. Lo que se quito y lo que no puede crecer
# ===========================================================================
def test_la_ruta_de_dictamen_de_documentos_del_expediente_ya_no_existe():
    """Habia DOS endpoints para dictaminar el mismo documento, con reglas
    distintas: el de la bandeja de Documentos exige motivo al rechazar y
    auto-avanza la fase cuando quedan los tres aprobados; este no pedia motivo
    ni avanzaba nada. Queda el de la bandeja.

    El censo se hace sobre el router de paginas APLANADO: `create_app().routes`
    devuelve envoltorios de `include_router` sin `path` ni `name`, asi que una
    asercion negativa contra esa lista pasa SIEMPRE (verificado: 22 rutas, cero
    de titulatec). De ahi que la negativa venga con su positiva.
    """
    from itcj2.apps.titulatec.pages.router import titulatec_pages_router
    from tests.fastapi.titulatec.test_scope_guard import _rutas

    nombres = {getattr(r, "name", "") for r in _rutas(titulatec_pages_router)}
    assert "titulatec.pages.admin.process_detail" in nombres, (
        "el censo no ve las rutas del expediente: la negativa de abajo seria falsa")
    assert "titulatec.pages.admin.doc_review" not in nombres
    assert "titulatec.pages.documents.review" in nombres, (
        "se quito el dictamen del expediente Y el de la bandeja: nadie puede "
        "aprobar un documento")
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
