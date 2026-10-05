"""El visor de Documentos es un módulo estático morph-safe (2026-10-05).

Antes el controlador vivía inline al final de `partials/documents_body.html`:
corría antes de `bootstrap.bundle` (`base.html`) y antes de que existiera
`#tt-doc-modal` (declarado en `admin/documents.html`), y al llegar por el menú
lateral (morph de `#tt-admin-content`) el modal ni se traía. «Expandir» nunca
enganchaba. Ahora:

- `static/js/admin/doc-viewer.js` se carga UNA vez desde `admin/base_admin.html`
  (después de Bootstrap, que viene de `base.html`) y se re-inicia tras cada
  swap (`htmx:afterSettle`) leyendo el DOM nuevo.
- `#tt-doc-modal` vive en el `{% block modals %}` de `base_admin.html`: existe
  en toda vista admin y no entra al morph.
- `documents_body.html` queda sin `<script>`; lo que el JS necesita va en
  `data-*` (`data-phase-closed`, `data-closes`, `data-status`...).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import itcj2.apps.titulatec as _tt_pkg

APP = Path(_tt_pkg.__file__).resolve().parent
TEMPLATES = APP / "templates" / "titulatec"
JS = APP / "static" / "js" / "admin" / "doc-viewer.js"

REVIEW_PERMS = ("titulatec.document.api.approve", "titulatec.document.api.reject")


@pytest.fixture()
def proceso(seed_phase_defs, seed_document_types, make_cohort, make_student,
            make_process, make_document):
    """Proceso en la fase 1 con el último documento por aprobar (escenario de
    la feature 2026-10-04: ese documento lleva `data-closes="1"`)."""
    def _nuevo(statuses=("approved", "approved", "pending"), current_phase=1):
        seed_phase_defs()
        seed_document_types()
        proc = make_process(make_student(), cohort=make_cohort(),
                            current_phase=current_phase)
        for code, st in zip(("birth_certificate", "high_school_cert", "curp"), statuses):
            make_document(proc, type_code=code, review_status=st)
        return proc
    return _nuevo


def test_documents_body_sin_script_inline(client_as, make_head, proceso):
    from tests.fastapi.titulatec.conftest import HEAD_PERMS

    proc = proceso()
    html = client_as(make_head(perm_codes=HEAD_PERMS + REVIEW_PERMS)).get(
        "/titulatec/admin/documents/body?selected=%d" % proc.id).text

    assert 'id="tt-doc-review"' in html, "el detalle debe pintarse"
    assert "<script" not in html.lower()


def test_base_admin_carga_doc_viewer_y_declara_modal(client_as, make_head):
    resp = client_as(make_head()).get("/titulatec/admin/")
    assert resp.status_code == 200, resp.text[:300]
    html = resp.text

    assert "/static/titulatec/js/admin/doc-viewer.js?v=" in html
    assert html.count('id="tt-doc-modal"') == 1
    # Después de los demás módulos admin (y por tanto de Bootstrap, que va antes
    # del `{% block scripts %}`).
    assert html.index("js/admin/doc-viewer.js") > html.index("js/admin/officers.js")
    assert html.index("js/admin/doc-viewer.js") > html.index("bootstrap.bundle")
    # El modal vive a nivel <body>, fuera del contenedor que entra al morph.
    contenido = html.split('id="tt-admin-content"', 1)[1].split("</main>", 1)[0]
    assert 'id="tt-doc-modal"' not in contenido


def test_documents_page_no_duplica_el_modal(client_as, make_head, proceso):
    proc = proceso()
    html = client_as(make_head()).get(
        "/titulatec/admin/documents?selected=%d" % proc.id).text

    assert html.count('id="tt-doc-modal"') == 1
    src = (TEMPLATES / "admin" / "documents.html").read_text(encoding="utf-8")
    assert "tt-doc-modal" not in src


def test_doc_viewer_modulo_morph_safe():
    assert JS.exists(), "falta static/js/admin/doc-viewer.js"
    js = JS.read_text(encoding="utf-8")

    assert "window.TitulaTecDocViewer" in js
    assert "htmx:afterSettle" in js
    assert "DOMContentLoaded" in js
    assert "data-tt-bound" in js
    for nativo in ("confirm(", "alert(", "prompt("):
        assert not re.search(r"(?<![\w.])" + re.escape(nativo), js), nativo
    # Comportamiento de 2026-10-04 conservado.
    for pieza in ("applyReviewState", "hx-confirm", "data-tt-confirm-ok",
                  "phaseClosed", "closes", "pdfjs-dist@3.11.174/build/pdf.min.js",
                  "pdfjs-dist@3.11.174/build/pdf.worker.min.js",
                  "hidden.bs.modal", "devicePixelRatio"):
        assert pieza in js, pieza
    # Sin CRLF.
    assert "\r\n" not in JS.read_bytes().decode("utf-8")


def test_parciales_y_js_muertos_eliminados():
    assert not (APP / "static" / "js" / "partials" / "doc-viewer.js").exists()
    assert not (TEMPLATES / "partials" / "documents" / "_doc_viewer.html").exists()
    assert not (TEMPLATES / "partials" / "documents" / "_doc_modal.html").exists()
    for tpl in TEMPLATES.rglob("*.html"):
        src = tpl.read_text(encoding="utf-8")
        for muerto in ("_doc_viewer", "_doc_modal", "partials/doc-viewer.js"):
            assert muerto not in src, "%s menciona %s" % (tpl.name, muerto)


def test_picks_llevan_data_closes_y_status(client_as, make_head, proceso):
    from tests.fastapi.titulatec.conftest import HEAD_PERMS

    proc = proceso()
    html = client_as(make_head(perm_codes=HEAD_PERMS + REVIEW_PERMS)).get(
        "/titulatec/admin/documents/body?selected=%d" % proc.id).text

    picks = re.findall(r'<button[^>]*class="[^"]*tt-docpick[^"]*"[^>]*>', html)
    assert len(picks) == 3
    for p in picks:
        for attr in ("data-type=", "data-url=", "data-name=", "data-mime=",
                     "data-status=", "data-closes="):
            assert attr in p, attr
    assert html.count('data-closes="1"') == 1
    assert 'data-phase-closed="0"' in html


def test_el_modal_de_la_base_trae_el_dictamen_fuera_de_documentos(client_as, make_head):
    """Llegando a Documentos por el menú lateral el modal es el que se pintó en
    OTRA vista (no entra al morph): sin `can_review_docs` en ese contexto, los
    botones deben estar y el módulo los muestra solo si el form inline existe."""
    html = client_as(make_head()).get("/titulatec/admin/").text
    modal = html.split('id="tt-doc-modal"', 1)[1]
    assert 'id="tt-modal-approve"' in modal
    assert 'id="tt-modal-reject"' in modal
    assert 'id="tt-modal-note"' in modal
    js = JS.read_text(encoding="utf-8") if JS.exists() else ""
    assert "tt-modal-actions" in js


def test_las_vistas_admin_que_pisan_modals_conservan_el_de_la_base():
    """Una vista que redefine `{% block modals %}` sin `super()` borra el
    `#tt-doc-modal` de la base, y como el modal no entra al morph, llegar a
    Documentos desde ella por el menú lateral lo dejaría sin modal."""
    for tpl in (TEMPLATES / "admin").rglob("*.html"):
        if tpl.name == "base_admin.html":
            continue
        src = tpl.read_text(encoding="utf-8")
        if "{% block modals %}" in src:
            cuerpo = src.split("{% block modals %}", 1)[1].split("{% endblock %}", 1)[0]
            assert "super()" in cuerpo, tpl.name
