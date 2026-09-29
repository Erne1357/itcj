"""Documentos del alumno: píldora propia, fecha de envío y aviso de estado al
pie (`#tt-docs-status`, spec 2026-09-28 §4 A3/A4, plan
titulatec-correos-notificaciones, Tarea 2).

Retirado «Enviar a revisión» (Tarea 1): subir YA es enviar. Lo que se fija
aquí es que la pantalla lo diga sin ambigüedad:

1. Píldora del alumno (`doc_pill_alumno`, `_macros.html`) -- DISTINTA de
   `estado_pill` (la del personal, que sigue diciendo "Pendiente"/"En
   revisión"): `pending` -> "Enviado · en revisión", `approved` -> "Aprobado",
   `rejected` -> "Necesita corrección".
2. "Enviado el {fecha}" bajo el nombre del archivo: última
   `ProcessEvent(document_uploaded)` de ese tipo (`DocumentService.last_uploads`,
   extraído de `pages/documents.py::_last_uploads`), respaldo
   `Document.created_at`.
3. Aviso al pie, prioridad rechazados > faltantes > aprobados > enviados
   (spec A4), re-pintado por `hx-swap-oob` en cada subida/borrado -- también
   en la subida con error (200 + `X-Tt-Error`).
4. La bandeja del PERSONAL no se toca: sigue usando `estado_pill`.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from tests.fastapi.titulatec.test_documents_fifo import _evento_subida
from tests.fastapi.titulatec.test_student_mail import perfil  # noqa: F401 (fixture reusada)

PDF = ("documento.pdf", b"%PDF-1.4 documento de prueba", "application/pdf")

# Mismo set que `test_initial_phase_sync.py::STUDENT_PERMS`: el default de
# `conftest.py` no trae `.delete.own`, y aquí se necesitan las tres rutas.
STUDENT_PERMS = (
    "titulatec.dashboard.student",
    "titulatec.document.api.read.own",
    "titulatec.document.api.upload.own",
    "titulatec.document.api.delete.own",
)


@pytest.fixture()
def esc(db_session, seed_phase_defs, seed_document_types, make_cohort, make_student,
        make_process, tmp_path, monkeypatch):
    """Alumno con proceso en fase 1, listo para subir/borrar por HTTP."""
    def _build(current_phase=1, status="active"):
        monkeypatch.setattr("itcj2.apps.titulatec.utils.storage._base", lambda: tmp_path)
        seed_phase_defs()
        seed_document_types()
        student = make_student(perm_codes=STUDENT_PERMS)
        proc = make_process(student, cohort=make_cohort(),
                            current_phase=current_phase, status=status)
        return student, proc
    return _build


# ===========================================================================
# 1. Píldora propia del alumno (A3)
# ===========================================================================
def test_pildora_enviado_en_revision_para_pendiente(esc, client_as):
    student, proc = esc()

    resp = client_as(student).post("/titulatec/student/documents/birth_certificate",
                                   files={"archivo": PDF})

    assert resp.status_code == 200, resp.text[:300]
    html = client_as(student).get("/titulatec/student/documents").text
    assert "Enviado · en revisión" in html


def test_pildora_aprobado(esc, client_as, make_document):
    student, proc = esc()
    make_document(proc, type_code="birth_certificate", review_status="approved")

    html = client_as(student).get("/titulatec/student/documents").text

    assert "Aprobado" in html


def test_pildora_necesita_correccion(esc, client_as, make_document):
    student, proc = esc()
    make_document(proc, type_code="birth_certificate", review_status="rejected")

    html = client_as(student).get("/titulatec/student/documents").text

    assert "Necesita corrección" in html


# ===========================================================================
# 2. "Enviado el ..." = la ULTIMA subida real (A3)
# ===========================================================================
def test_fecha_de_envio_es_la_ultima_subida(esc, client_as, make_document, db_session):
    from itcj2.apps.titulatec.utils.dates_es import dia_mes_hora

    student, proc = esc()
    make_document(proc, type_code="birth_certificate")
    t1 = datetime(2026, 1, 5, 9, 0)
    t2 = datetime(2026, 1, 7, 16, 30)
    _evento_subida(db_session, proc, "birth_certificate", t1)
    _evento_subida(db_session, proc, "birth_certificate", t2)

    html = client_as(student).get("/titulatec/student/documents").text

    assert f"Enviado el {dia_mes_hora(t2)}" in html
    assert f"Enviado el {dia_mes_hora(t1)}" not in html


# ===========================================================================
# 3. Aviso al pie: contenido por estado y prioridad (A4)
# ===========================================================================
def test_aviso_faltan_nombra_los_documentos(esc, client_as, make_document):
    student, proc = esc()
    make_document(proc, type_code="birth_certificate")   # faltan 2

    html = client_as(student).get("/titulatec/student/documents").text

    assert "Te faltan 2" in html
    assert "Certificado de bachillerato" in html
    assert "CURP certificada" in html


def test_aviso_falta_uno_en_singular(esc, client_as, make_document):
    """B6: con un solo faltante el aviso dice «Te falta 1: …», no «Te faltan 1»."""
    student, proc = esc()
    make_document(proc, type_code="birth_certificate")
    make_document(proc, type_code="high_school_cert")          # falta solo la CURP

    html = client_as(student).get("/titulatec/student/documents").text

    assert "Te falta 1: CURP certificada." in html
    assert "Te faltan" not in html


def test_aviso_enviados_muestra_el_correo_personal(esc, client_as, make_document, perfil):
    student, proc = esc()
    for code in ("birth_certificate", "high_school_cert", "curp"):
        make_document(proc, type_code=code)
    perfil(student.id, "alumno.personal@example.invalid")

    html = client_as(student).get("/titulatec/student/documents").text

    assert "en revisión" in html
    assert "alumno.personal@example.invalid" in html
    assert "Te avisaremos a" in html


def test_aviso_enviados_sin_correo_personal_no_inventa(esc, client_as, make_document):
    student, proc = esc()
    for code in ("birth_certificate", "high_school_cert", "curp"):
        make_document(proc, type_code=code)

    html = client_as(student).get("/titulatec/student/documents").text

    assert "Te avisaremos aquí en la app." in html
    assert "Te avisaremos a " not in html
    assert "@" not in html.split('id="tt-docs-status"', 1)[1].split("</div>", 1)[0]


def test_aviso_aprobados_invita_a_agendar_la_cita(esc, client_as, make_document):
    """Los 4 estados del aviso son mutuamente excluyentes (A4): "aprobado" NO
    lo ejercita ningun test del Step 1 del brief (todos los demas si), y es un
    branch real de `_docs_status.html` -- se cubre aqui para no dejarlo a
    ciegas."""
    student, proc = esc()
    for code in ("birth_certificate", "high_school_cert", "curp"):
        make_document(proc, type_code=code, review_status="approved")

    html = client_as(student).get("/titulatec/student/documents").text

    assert "¡Tus documentos fueron aprobados!" in html
    assert 'href="/titulatec/student/cita"' in html
    assert "Te faltan" not in html
    assert "Corrige los documentos marcados" not in html


def test_aviso_rechazado_gana_a_faltantes(esc, client_as, make_document):
    student, proc = esc()
    make_document(proc, type_code="birth_certificate", review_status="rejected")
    # high_school_cert y curp quedan "missing": si "faltan" ganara, ambos
    # avisos coexistirian en el texto y este test no discriminaria nada.

    html = client_as(student).get("/titulatec/student/documents").text

    assert "Corrige los documentos marcados" in html
    assert "Te faltan" not in html


# ===========================================================================
# 4. El aviso viaja OOB en subir/borrar -- tambien con error (A4)
#
# B7 (ronda final): la región viva (`#tt-docs-status`, `role="status"`
# `aria-live="polite"`) es un envoltorio ESTABLE que el OOB no reemplaza; lo
# que viaja es su contenido, la tarjeta `#tt-docs-status-card`. Si el OOB
# reemplazara la región viva entera, el lector de pantalla no anunciaría el
# cambio (la región «nueva» no estaba en el DOM cuando cambió).
# ===========================================================================
def _tarjeta_oob(texto):
    """Atributos de la tarjeta del aviso (`#tt-docs-status-card`), o `None`."""
    import re

    m = re.search(r'<div id="tt-docs-status-card"([^>]*)>', texto)
    return m.group(1) if m else None


def _assert_viaja_solo_la_tarjeta(texto):
    """La respuesta trae la tarjeta con `hx-swap-oob="true"` y NO la región
    viva: esa se queda en la página."""
    tarjeta = _tarjeta_oob(texto)
    assert tarjeta is not None, "la respuesta no trae la tarjeta del aviso"
    assert 'hx-swap-oob="true"' in tarjeta
    assert 'id="tt-docs-status"' not in texto, "el OOB no debe reemplazar la región viva"
    assert 'role="status"' not in texto


def test_la_region_viva_es_estable_y_envuelve_la_tarjeta(esc, client_as):
    """Carga completa: `#tt-docs-status` lleva `role="status"` y
    `aria-live="polite"`, sin `hx-swap-oob`, y adentro la tarjeta con id propio
    (sin `role`: una región viva dentro de otra se anunciaría dos veces)."""
    import re

    student, proc = esc()

    html = client_as(student).get("/titulatec/student/documents").text

    region = re.search(r'<div id="tt-docs-status"([^>]*)>\s*<div id="tt-docs-status-card"'
                       r'([^>]*)>', html)
    assert region, "la tarjeta tiene que vivir DENTRO de la región viva"
    envoltorio, tarjeta = region.groups()
    assert 'role="status"' in envoltorio and 'aria-live="polite"' in envoltorio
    assert "hx-swap-oob" not in envoltorio + tarjeta
    assert "role=" not in tarjeta


def test_subir_devuelve_el_aviso_oob(esc, client_as):
    student, proc = esc()

    resp = client_as(student).post("/titulatec/student/documents/birth_certificate",
                                   files={"archivo": PDF})

    assert resp.status_code == 200, resp.text[:300]
    _assert_viaja_solo_la_tarjeta(resp.text)
    assert "Te faltan 2" in resp.text


def test_borrar_devuelve_el_aviso_oob(esc, client_as):
    student, proc = esc()
    cli = client_as(student)
    for code in ("birth_certificate", "high_school_cert", "curp"):
        resp = cli.post(f"/titulatec/student/documents/{code}", files={"archivo": PDF})
        assert resp.status_code == 200, resp.text[:300]

    resp = cli.delete("/titulatec/student/documents/curp")

    assert resp.status_code == 200, resp.text[:300]
    _assert_viaja_solo_la_tarjeta(resp.text)
    assert "Te falta 1: CURP certificada." in resp.text          # singular (B6)


def test_subida_con_error_tambien_trae_el_aviso(esc, client_as, monkeypatch):
    """Mismo truco que `test_document_files_routes.py::test_mas_del_maximo...`:
    un tope minusculo hace que CUALQUIER PDF se rechace ANTES de leer el
    cuerpo (`check_pdf_upload_size`), sin tocar la compresion real."""
    from itcj2.config import get_settings

    student, proc = esc()
    monkeypatch.setattr(get_settings(), "TITULATEC_MAX_PDF_UPLOAD_SIZE", 1)

    resp = client_as(student).post("/titulatec/student/documents/birth_certificate",
                                   files={"archivo": PDF})

    assert resp.status_code == 200, resp.text[:300]
    assert "X-Tt-Error" in resp.headers
    _assert_viaja_solo_la_tarjeta(resp.text)


# ===========================================================================
# 5. La bandeja del PERSONAL no cambia (sigue usando `estado_pill`)
# ===========================================================================
def test_la_bandeja_del_personal_sigue_diciendo_pendiente(
    client_as, make_head, seed_document_types, make_cohort, make_student,
    make_process, make_document,
):
    seed_document_types()
    student = make_student()
    proc = make_process(student, cohort=make_cohort())
    make_document(proc, type_code="birth_certificate")   # review_status="pending"
    jefa = make_head()

    html = client_as(jefa).get(
        "/titulatec/admin/documents/body?status=&selected=%d" % proc.id).text

    assert "Pendiente" in html
    assert "Enviado · en revisión" not in html


# ===========================================================================
# 6. `DocumentService.last_uploads` == el `_last_uploads` de la bandeja
# ===========================================================================
def test_last_uploads_es_equivalente_al_de_la_bandeja(
    db_session, seed_document_types, make_cohort, make_student, make_process, make_document,
):
    from itcj2.apps.titulatec.pages.documents import _last_uploads
    from itcj2.apps.titulatec.services.document_service import DocumentService

    seed_document_types()
    student = make_student()
    proc = make_process(student, cohort=make_cohort())
    make_document(proc, type_code="birth_certificate")
    _evento_subida(db_session, proc, "birth_certificate", datetime(2026, 1, 1, 10, 0))
    _evento_subida(db_session, proc, "birth_certificate", datetime(2026, 1, 2, 11, 0))

    viejo = _last_uploads(db_session, [proc.id])
    nuevo = DocumentService.last_uploads(db_session, [proc.id])

    assert viejo == nuevo
    assert viejo[(proc.id, "birth_certificate")] == datetime(2026, 1, 2, 11, 0)


# ===========================================================================
# 7. Contrato de la app: sin <script>/on*= NUEVOS en las plantillas tocadas
# ===========================================================================
def test_sin_script_inline_en_las_plantillas_tocadas():
    """Barre las 4 plantillas de esta tarea. El único `on[a-z]+=` que
    sobrevive es el PREEXISTENTE de `document_slot.html`
    (`onclick="event.stopPropagation()"` x2, en los inputs de archivo ocultos,
    ajeno a esta tarea) -- nada nuevo se agrega en ninguna de las 4."""
    import re
    from pathlib import Path

    import itcj2.apps.titulatec as _tt_pkg

    base = Path(_tt_pkg.__file__).resolve().parent / "templates" / "titulatec"
    archivos = {
        base / "_macros.html": 0,
        base / "partials" / "document_slot.html": 2,
        base / "partials" / "student" / "_docs_status.html": 0,
        base / "student" / "documents.html": 0,
    }
    for path, permitidos in archivos.items():
        texto = path.read_text(encoding="utf-8")
        assert "<script" not in texto.lower(), f"{path.name}: <script> inline"
        hallados = re.findall(r'\son[a-z]+\s*=\s*"([^"]*)"', texto, flags=re.I)
        if permitidos:
            assert hallados == ["event.stopPropagation()"] * permitidos, (path.name, hallados)
        else:
            assert not hallados, f"{path.name}: on*= inline nuevo: {hallados}"


# ===========================================================================
# 8. Fix round 1 (ruling 11): el correo largo no puede romper el ancho
# ===========================================================================
def test_el_correo_largo_en_el_aviso_puede_partirse(esc, client_as, make_document, perfil):
    """Hallazgo del revisor: un correo personal largo y sin espacios (p. ej.
    «nombre.apellido.segundoapellido2005@hotmail.com») dentro de
    `#tt-docs-status` (`.tt-cita-why`/`.tt-cita-why p`) puede empujar el ancho
    a 360px y romper el invariante duro `scrollWidth <= innerWidth`, porque
    `titulatec.css:1910-1912` no traía `overflow-wrap: anywhere` -- a
    diferencia de `.tt-reqinfo-vista`/`.tt-reqinfo-body` (`:1827-1828`) y
    `.tt-sii-rules li span`/`.tt-sii-line` (`:2288`/`:2297`), que SÍ la
    aplican a contenido de largo variable.

    Arreglo: una regla ACOTADA a `#tt-docs-status` (no a `.tt-cita-why`
    global -- la usan `cita_card.html`/`_cita_panel.html` con contenido corto
    y controlado). Dos partes: (a) la regla existe en el CSS con el selector
    correcto (patrón de `test_documents_inbox.py::
    test_la_primitiva_del_indicador_existe_en_el_css`); (b) el correo largo
    de verdad llega íntegro dentro del aviso servido (el navegador es quien
    verifica el invariante visual a 360px, no este test)."""
    import re
    from pathlib import Path

    import itcj2.apps.titulatec as _tt_pkg

    css_path = (Path(_tt_pkg.__file__).resolve().parent / "static" / "css" / "titulatec.css")
    css = css_path.read_text(encoding="utf-8")

    regla = re.search(r'#tt-docs-status\s+\.tt-cita-why\s+p\s*\{([^}]*)\}', css)
    assert regla, "falta la regla `#tt-docs-status .tt-cita-why p { ... }` en titulatec.css"
    assert "overflow-wrap: anywhere" in regla.group(1), (
        "`#tt-docs-status .tt-cita-why p` no trae `overflow-wrap: anywhere`")
    # Acotada: la clase GLOBAL `.tt-cita-why` (la usan `cita_card.html`/
    # `_cita_panel.html`, contenido corto y controlado) debe seguir BYTE A BYTE
    # como antes de este arreglo -- ninguna de sus 3 reglas gana `overflow-wrap`.
    bloque_global = (
        '.tt-cita-why { display: flex; align-items: flex-start; gap: 10px; min-width: 0; }\n'
        '.tt-cita-why i { flex: 0 0 auto; margin-top: 2px; color: var(--tt-amber-ink); }\n'
        '.tt-cita-why p { font-size: var(--tt-fs-200); color: var(--tt-text-2); min-width: 0; }'
    )
    assert bloque_global in css, (
        "`.tt-cita-why` global cambió: este arreglo debe ser ACOTADO a #tt-docs-status, "
        "sin tocar la clase que usan cita_card.html/_cita_panel.html")

    student, proc = esc()
    for code in ("birth_certificate", "high_school_cert", "curp"):
        make_document(proc, type_code=code)
    correo_largo = "nombre.apellido.segundoapellido2005@hotmail.com"
    perfil(student.id, correo_largo)

    html = client_as(student).get("/titulatec/student/documents").text

    aviso = html.split('id="tt-docs-status"', 1)[1]
    assert correo_largo in aviso
