"""Alumno: reemplazo de un documento pedido en la cita de cotejo (2026-10-15).

Spec `2026-10-15-titulatec-reemplazo-cotejo-design.md` §4.3 y §7.2. Cuando la
jefatura de Servicios Escolares pide reemplazar un documento de la fase 1 (el
proceso ya esta en la fase 2), el egresado puede volver a subir SOLO ese
documento: `/student/documents` se reabre en «modo reemplazo» (los demas, de
solo lectura), la subida se permite solo si `DocumentService.student_can_replace`,
borrar sigue negado y un aviso compartido aparece en el tablero y en «Mi cita».

Regla de oro del arbol: ninguna asercion negativa va sola; cada «no» trae el
positivo del MISMO actor sobre la MISMA ruta.
"""
from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from itcj2.core.utils.timezone import db_now
from tests.fastapi.titulatec.conftest import STUDENT_PERMS

DOCS = "/titulatec/student/documents"
DASH = "/titulatec/student/dashboard"
CITA = "/titulatec/student/cita"

DOC_TYPES = (
    ("birth_certificate", "Acta de nacimiento", 1),
    ("high_school_cert", "Certificado de bachillerato", 1),
    ("curp", "CURP certificada", 1),
    ("anexo_iii", "Anexo III firmado", 6),
)

PDF = ("acta.pdf", b"%PDF-1.4 documento de prueba", "application/pdf")
MOTIVO = "El acta esta ilegible, presenta una copia certificada reciente"


def _doc(db, process_id, code):
    from itcj2.apps.titulatec.models import Document
    db.expire_all()
    return db.query(Document).filter_by(process_id=process_id, type_code=code).first()


@pytest.fixture()
def escenario(db_session, seed_phase_defs, seed_document_types, make_program,
              make_cohort, make_student, make_process, make_document,
              tmp_path, monkeypatch):
    """Alumno con su proceso en la fase pedida y los 3 documentos iniciales.

    `abiertos` = {codigo: estado}: documentos con reemplazo abierto
    (`replacement_requested_at` no NULL) en ese estado. El resto queda
    `approved`. Los archivos tambien van a disco (bajo `tmp_path`).
    """
    def _build(current_phase=2, abiertos=None):
        monkeypatch.setattr("itcj2.apps.titulatec.utils.storage._base", lambda: tmp_path)
        seed_phase_defs()
        seed_document_types(DOC_TYPES)
        student = make_student(
            perm_codes=STUDENT_PERMS + ("titulatec.document.api.delete.own",))
        proc = make_process(student, cohort=make_cohort(),
                            program=make_program("Ingenieria Ficticia Reemplazo"),
                            current_phase=current_phase)
        abiertos = abiertos or {}
        for code, _name, _n in DOC_TYPES[:3]:
            estado = abiertos.get(code, "approved")
            doc = make_document(
                proc, type_code=code, phase_number=1, review_status=estado,
                note=(MOTIVO if estado == "rejected" else None),
                replacement_requested_at=(db_now() if code in abiertos else None))
            dest = tmp_path / doc.file_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"%PDF-1.4 documento de prueba")
        db_session.commit()
        return SimpleNamespace(student=student, process=proc)

    return _build


def _zonas_de_subida(html: str) -> set[str]:
    """Codigos con zona de subida (un `<input type=file>` con id `file-{code}`)."""
    return set(re.findall(r'id="file-([a-z_]+)"', html))


# ===========================================================================
# 1. Pagina Documentos
# ===========================================================================
class TestPaginaDocumentos:
    def test_fase_2_sin_reemplazo_redirige_como_hoy(self, escenario, client_as):
        esc = escenario(current_phase=2)

        resp = client_as(esc.student).get(DOCS, follow_redirects=False)

        assert resp.status_code == 302, resp.text[:300]
        assert resp.headers["location"] == DASH + "?fase=1"

    def test_fase_2_con_reemplazo_abre_el_modo_reemplazo(self, escenario, client_as):
        esc = escenario(current_phase=2, abiertos={"birth_certificate": "rejected"})

        resp = client_as(esc.student).get(DOCS, follow_redirects=False)

        assert resp.status_code == 200, resp.text[:300]
        html = resp.text
        assert "Reemplazo de documentos" in html
        assert MOTIVO in html
        assert "Subir documento de reemplazo" in html
        # Solo el documento abierto tiene zona de subida; ningun boton de borrar.
        assert _zonas_de_subida(html) == {"birth_certificate"}
        assert "hx-delete" not in html
        # Los demas siguen visibles, de solo lectura.
        assert 'id="slot-high_school_cert"' in html and 'id="slot-curp"' in html
        assert "Falta que subas el reemplazo de: Acta de nacimiento" in html

    def test_reemplazo_ya_subido_ofrece_cambiar_el_archivo(self, escenario, client_as):
        esc = escenario(current_phase=2, abiertos={"curp": "pending"})

        resp = client_as(esc.student).get(DOCS, follow_redirects=False)

        assert resp.status_code == 200, resp.text[:300]
        html = resp.text
        assert "Reemplazo enviado" in html and "Cambiar archivo" in html
        assert _zonas_de_subida(html) == {"curp"}
        assert "hx-delete" not in html
        assert "Tu reemplazo llegó a Servicios Escolares" in html

    def test_un_reemplazo_aprobado_ya_no_reabre_la_pagina(self, escenario, client_as,
                                                          db_session):
        """Aprobado, `student_can_replace` da False aunque la bandera siga."""
        esc = escenario(current_phase=2, abiertos={"curp": "approved"})

        resp = client_as(esc.student).get(DOCS, follow_redirects=False)

        assert resp.status_code == 302, resp.text[:300]

    def test_fase_1_sigue_en_modo_normal(self, escenario, client_as):
        esc = escenario(current_phase=1)

        resp = client_as(esc.student).get(DOCS, follow_redirects=False)

        assert resp.status_code == 200, resp.text[:300]
        html = resp.text
        assert "Documentos iniciales" in html and "Reemplazo de documentos" not in html
        assert _zonas_de_subida(html) == set()      # los 3 estan subidos y aprobados
        assert html.count("hx-delete") == 3          # modo normal: borrar sigue ahi


# ===========================================================================
# 2. Subir y borrar
# ===========================================================================
class TestSubirYBorrar:
    def test_sube_el_documento_abierto(self, escenario, client_as, db_session):
        esc = escenario(current_phase=2, abiertos={"birth_certificate": "rejected"})

        resp = client_as(esc.student).post(f"{DOCS}/birth_certificate", files={"archivo": PDF})

        assert resp.status_code == 200, resp.text[:300]
        assert not resp.headers.get("X-Tt-Error")
        doc = _doc(db_session, esc.process.id, "birth_certificate")
        assert doc.review_status == "pending"
        assert doc.replacement_requested_at is not None, "la bandera la limpia solo la aprobacion"
        assert doc.review_note is None
        html = resp.text
        # El slot conserva el modo reemplazo y el aviso del modo viaja por OOB.
        assert "Reemplazo enviado" in html and "hx-delete" not in html
        assert "Tu reemplazo llegó a Servicios Escolares" in html

    def test_no_sube_otro_documento_de_la_fase_1(self, escenario, client_as, db_session):
        esc = escenario(current_phase=2, abiertos={"birth_certificate": "rejected"})
        antes = _doc(db_session, esc.process.id, "curp").version

        resp = client_as(esc.student).post(f"{DOCS}/curp", files={"archivo": PDF})

        assert resp.status_code == 400, resp.text[:300]
        assert resp.headers.get("X-Tt-Error")
        doc = _doc(db_session, esc.process.id, "curp")
        assert doc.review_status == "approved" and doc.version == antes

    def test_no_sube_un_documento_de_otra_fase(self, escenario, client_as, db_session):
        esc = escenario(current_phase=2, abiertos={"birth_certificate": "rejected"})

        resp = client_as(esc.student).post(f"{DOCS}/anexo_iii", files={"archivo": PDF})

        assert resp.status_code == 400, resp.text[:300]
        assert _doc(db_session, esc.process.id, "anexo_iii") is None

    def test_sin_reemplazo_abierto_la_subida_sigue_negada(self, escenario, client_as):
        esc = escenario(current_phase=2)

        resp = client_as(esc.student).post(f"{DOCS}/birth_certificate", files={"archivo": PDF})

        assert resp.status_code == 400, resp.text[:300]

    def test_borrar_sigue_negado_aun_con_reemplazo_abierto(self, escenario, client_as,
                                                           db_session):
        esc = escenario(current_phase=2, abiertos={"birth_certificate": "rejected"})

        resp = client_as(esc.student).delete(f"{DOCS}/birth_certificate")

        assert resp.status_code == 400, resp.text[:300]
        assert resp.headers.get("X-Tt-Error")
        assert _doc(db_session, esc.process.id, "birth_certificate") is not None

    def test_fase_1_sube_y_borra_como_siempre(self, escenario, client_as, db_session):
        """Positivo del mismo par de rutas en el modo normal (sin excepcion)."""
        esc = escenario(current_phase=1)

        sube = client_as(esc.student).post(f"{DOCS}/curp", files={"archivo": PDF})
        assert sube.status_code == 200, sube.text[:300]
        assert "hx-delete" in sube.text            # modo normal: conserva el borrar
        borra = client_as(esc.student).delete(f"{DOCS}/curp")
        assert borra.status_code == 200, borra.text[:300]
        assert _doc(db_session, esc.process.id, "curp") is None


# ===========================================================================
# 3. Aviso en el tablero y en «Mi cita»
# ===========================================================================
class TestAviso:
    def test_tablero_con_motivo(self, escenario, client_as):
        esc = escenario(current_phase=2, abiertos={"birth_certificate": "rejected"})

        resp = client_as(esc.student).get(DASH)

        assert resp.status_code == 200, resp.text[:300]
        html = resp.text
        assert 'id="tt-replacement-notice"' in html
        assert "Acta de nacimiento" in html and MOTIVO in html
        assert 'href="/titulatec/student/documents"' in html and "Subir reemplazo" in html

    def test_tablero_en_revision(self, escenario, client_as):
        esc = escenario(current_phase=2, abiertos={"birth_certificate": "pending"})

        html = client_as(esc.student).get(DASH).text

        assert 'id="tt-replacement-notice"' in html
        assert "Tu reemplazo está en revisión" in html
        assert "Subir reemplazo" not in html

    def test_tablero_sin_reemplazo_no_pinta_el_aviso(self, escenario, client_as):
        esc = escenario(current_phase=2)

        html = client_as(esc.student).get(DASH).text

        assert "tt-replacement-notice" not in html

    def test_tablero_fase_1_no_pinta_el_aviso(self, escenario, client_as):
        esc = escenario(current_phase=1)

        html = client_as(esc.student).get(DASH).text

        assert "tt-replacement-notice" not in html

    def test_mi_cita_con_motivo_fuera_de_la_tarjeta(self, escenario, client_as):
        esc = escenario(current_phase=2, abiertos={"curp": "rejected"})

        resp = client_as(esc.student).get(CITA, follow_redirects=False)

        assert resp.status_code == 200, resp.text[:300]
        html = resp.text
        assert 'id="tt-replacement-notice"' in html and MOTIVO in html
        # FUERA de `#tt-cita-card`: el aviso empieza despues de que cierra la tarjeta.
        assert html.index('id="tt-cita-card"') < html.index('id="tt-replacement-notice"')
        tarjeta = html[html.index('id="tt-cita-card"'):html.index('id="tt-replacement-notice"')]
        assert "tt-replacement" not in tarjeta

    def test_mi_cita_en_revision(self, escenario, client_as):
        esc = escenario(current_phase=2, abiertos={"curp": "pending"})

        html = client_as(esc.student).get(CITA, follow_redirects=False).text

        assert "Tu reemplazo está en revisión" in html

    def test_mi_cita_sin_reemplazo_no_pinta_el_aviso(self, escenario, client_as):
        esc = escenario(current_phase=2)

        html = client_as(esc.student).get(CITA, follow_redirects=False).text

        assert "tt-replacement-notice" not in html
