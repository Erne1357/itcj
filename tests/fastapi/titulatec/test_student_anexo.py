"""Fase 6, tarea 4: pantalla del alumno `/titulatec/student/anexo` (spec §9.1).

Traduccion HTTP del motor (`test_anexo_door.py`, `test_anexo_service.py`): la
pagina, la vista previa del PDF (fase 6 v2: con marca de agua, nunca emite
folio), la subida del escaneo en dos saltos (solo con el Anexo «Listo para
recoger», `_listo`), el borrado y las guardas (corte en 3 = inerte; fase 5 =
redirect). Ruling R4: borrar el escaneo ya aprobado es 400, no 500, por las dos rutas.

Corte en 9 (la fase 6 operable) salvo las pruebas de inercia, que lo bajan a 3.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote

import pytest

from itcj2.apps.titulatec.models import Anexo, Document
from itcj2.apps.titulatec.services.anexo_service import AnexoService
from itcj2.apps.titulatec.services.phase_service import PhaseService
from itcj2.apps.titulatec.utils import storage
from tests.fastapi.titulatec.conftest import ROLE_STUDENT, STUDENT_PERMS

BASE = "/titulatec/student/anexo"
DASH = "/titulatec/student/dashboard"
TIPO = "anexo_iii"
PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
       b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
       b"trailer<</Root 1 0 R>>\n%%EOF\n")
ANEXO_PERMS = STUDENT_PERMS + (
    "titulatec.document.api.delete.own",
    "titulatec.anexo_iii.api.preview.own",
)


@pytest.fixture()
def corte(monkeypatch):
    def _fijar(fase):
        monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: fase))
    return _fijar


@pytest.fixture(autouse=True)
def entorno(corte, monkeypatch, patched_session_local, tmp_path):
    corte(9)
    monkeypatch.setattr(storage, "_base", lambda: tmp_path)
    return SimpleNamespace(base=tmp_path)


@pytest.fixture()
def caso(db_session, make_anexo_case, seed_document_types, make_role, make_user):
    def _build(**kw):
        seed_document_types([(TIPO, "Anexo III firmado", 6)])
        c = make_anexo_case(**kw)
        make_role(ROLE_STUDENT, ANEXO_PERMS)
        db_session.commit()
        return SimpleNamespace(**vars(c), revisor=make_user(first_name="TERE",
                                                            last_name="TITULACION"))
    return _build


def _listo(db, c):
    """Fase 6 v2: vinculacion lo marca «Listo para recoger» (sin eso el alumno
    no sube el escaneo; `mark_ready` se prueba en `test_anexo_entrega.py`)."""
    anexo = AnexoService.ensure_folio(db, c.process, c.coordinator.id)
    anexo.ready_at = datetime(2026, 3, 20, 9, 0)
    anexo.pickup_note = "Oficina de vinculacion"
    db.commit()


def _archivos(base: Path) -> set:
    return {p for p in base.rglob("*") if p.is_file()}


def _subir(client, contenido=PDF):
    return client.post(BASE + "/escaneo",
                       files={"archivo": ("anexo.pdf", contenido, "application/pdf")})


def _doc(db, c):
    db.expire_all()
    return db.query(Document).filter_by(process_id=c.process.id, type_code=TIPO).first()


def _folios(db, c):
    db.expire_all()
    return db.query(Anexo).filter_by(process_id=c.process.id).count()


def _espiar_commit_y_render(monkeypatch, db_session):
    """Fase 6 v2: la vista previa no escribe (sin `commit`) y pinta con
    WeasyPrint despues de cerrar la sesion. Registra el orden y sustituye el
    render por uno que no toca nada."""
    eventos = []
    real_commit = db_session.commit

    def commit():
        eventos.append("commit")
        return real_commit()

    def render(ctx):
        eventos.append("render")
        assert ctx["preview"] is True and ctx["folio"] is None
        return b"%PDF-espia"

    monkeypatch.setattr(db_session, "commit", commit)
    monkeypatch.setattr(AnexoService, "render", staticmethod(render))
    return eventos


class TestPagina:
    def test_integral_muestra_presidente_y_la_descarga(self, caso, client_as):
        c = caso()
        resp = client_as(c.student).get(BASE, follow_redirects=False)
        assert resp.status_code == 200, resp.text[:300]
        assert "Presidente" in resp.text
        assert BASE + "/pdf" in resp.text
        assert 'id="tt-anexo-body"' in resp.text

    def test_tesis_pide_a_los_4_sinodales(self, caso, client_as):
        c = caso(modality_code="thesis")
        assert "4 sinodales" in client_as(c.student).get(BASE).text

    def test_sin_folio_no_lo_muestra_y_con_folio_si(self, caso, client_as, db_session):
        c = caso()
        assert "AIII-" not in client_as(c.student).get(BASE).text
        AnexoService.ensure_folio(db_session, c.process, c.coordinator.id)
        db_session.commit()
        assert "AIII-" in client_as(c.student).get(BASE).text

    def test_ayuda_de_formato_sale_de_la_config(self, caso, client_as):
        c = caso()
        max_mb, upload_mb = storage.pdf_limits_mb()
        html = client_as(c.student).get(BASE).text
        assert f"{max_mb} MB" in html and f"{upload_mb} MB" in html

    def test_alumno_sin_proceso_va_al_tablero(self, make_student, make_role, client_as,
                                              seed_phase_defs):
        seed_phase_defs()
        alumno = make_student()
        make_role(ROLE_STUDENT, ANEXO_PERMS)
        resp = client_as(alumno).get(BASE, follow_redirects=False)
        assert resp.status_code == 302 and resp.headers["location"].startswith(DASH)

    def test_en_la_fase_5_redirige(self, caso, client_as, db_session):
        c = caso()
        c.process.current_phase = c.review_phase
        db_session.commit()
        resp = client_as(c.student).get(BASE, follow_redirects=False)
        assert resp.status_code == 302 and resp.headers["location"].startswith(DASH)

    def test_otro_alumno_ve_solo_lo_suyo(self, caso, client_as, db_session):
        a = caso()
        AnexoService.ensure_folio(db_session, a.process, a.coordinator.id)
        b = caso(modality_code="thesis")
        AnexoService.ensure_folio(db_session, b.process, b.coordinator.id)
        folio_a = AnexoService.get(db_session, a.process.id).folio
        folio_b = AnexoService.get(db_session, b.process.id).folio
        db_session.commit()
        assert folio_a != folio_b
        html_b = client_as(b.student).get(BASE).text
        assert folio_b in html_b and folio_a not in html_b
        html_a = client_as(a.student).get(BASE).text
        assert folio_a in html_a and folio_b not in html_a

    def test_corte_3_redirige_y_no_escribe(self, caso, client_as, corte, db_session):
        c = caso()
        corte(3)
        resp = client_as(c.student).get(BASE, follow_redirects=False)
        assert resp.status_code == 302 and resp.headers["location"].startswith(DASH)
        assert _folios(db_session, c) == 0

    def test_la_instruccion_dice_junta_las_firmas(self, caso, client_as):
        # Revision final, punto 5.
        html = client_as(caso().student).get(BASE).text
        assert "Descarga el Anexo III, junta las firmas y súbelo escaneado." in html
        assert "júntale" not in html

    @pytest.mark.parametrize("dano", ["regla_desconocida", "sin_modalidad"])
    def test_sin_regla_de_firma_pinta_texto_neutro(self, caso, client_as, db_session, dano):
        # Revision final, punto 12: `signers_text` sin regla daba 500.
        from itcj2.apps.titulatec.services.anexo_service import SIGNERS_FALLBACK_TEXT
        c = caso()
        if dano == "regla_desconocida":
            c.modality.signature_rule = "rara"
        else:
            c.process.modality = None       # el arnes no expira al commitear
        db_session.commit()
        resp = client_as(c.student).get(BASE, follow_redirects=False)
        assert resp.status_code == 200, resp.text[:300]
        assert SIGNERS_FALLBACK_TEXT in resp.text
        assert "Presidente" not in resp.text


class TestPdf:
    def test_vista_previa_sin_folio(self, caso, client_as, db_session):
        c = caso()
        cli = client_as(c.student)
        r1 = cli.get(BASE + "/pdf")
        r2 = cli.get(BASE + "/pdf")
        assert r1.status_code == 200 and r1.headers["content-type"] == "application/pdf"
        assert r1.content.startswith(b"%PDF")
        assert "inline" in r1.headers["content-disposition"]
        assert "_ANEXO_III_VISTA_PREVIA.pdf" in r1.headers["content-disposition"]
        assert r2.status_code == 200
        assert _folios(db_session, c) == 0, "el alumno nunca emite folio"

    def test_sin_proceso_el_mensaje_es_el_de_la_causa(self, make_student, make_role,
                                                      client_as, seed_phase_defs):
        seed_phase_defs()
        alumno = make_student()
        make_role(ROLE_STUDENT, ANEXO_PERMS)
        resp = client_as(alumno).get(BASE + "/pdf")
        assert resp.status_code == 400
        assert "proceso" in unquote(resp.headers["X-Tt-Error"])
        assert "todavia no se opera" not in unquote(resp.headers["X-Tt-Error"])

    def test_corte_3_es_400_y_no_numera(self, caso, client_as, corte, db_session):
        c = caso()
        corte(3)
        resp = client_as(c.student).get(BASE + "/pdf")
        assert resp.status_code == 400 and resp.headers.get("X-Tt-Error")
        assert _folios(db_session, c) == 0

    def test_pinta_sin_escribir(self, caso, client_as, db_session, monkeypatch):
        c = caso()
        eventos = _espiar_commit_y_render(monkeypatch, db_session)
        resp = client_as(c.student).get(BASE + "/pdf")
        assert resp.status_code == 200, resp.text[:300]
        assert resp.content == b"%PDF-espia"
        assert eventos == ["render"], eventos
        assert _folios(db_session, c) == 0


class TestSubida:
    def test_subir_pone_la_fase_en_revision(self, caso, client_as, db_session):
        c = caso()
        _listo(db_session, c)
        resp = _subir(client_as(c.student))
        assert resp.status_code == 200, resp.text[:300]
        assert "En revisión" in resp.text
        # Revision final, punto 3: el aviso de exito sale con tono de exito.
        assert unquote(resp.headers["X-Tt-Notice"]).startswith("Escaneo enviado")
        assert resp.headers["X-Tt-Notice-Kind"] == "success"
        assert _doc(db_session, c).review_status == "pending"
        assert "En revisión" in client_as(c.student).get(BASE).text

    def test_observado_muestra_motivo_y_permite_resubir(self, caso, client_as, db_session):
        c = caso()
        _listo(db_session, c)
        _subir(client_as(c.student))
        AnexoService.observe(db_session, c.process, c.revisor.id, reason="Falta la firma del vocal")
        db_session.commit()
        html = client_as(c.student).get(BASE).text
        assert "Falta la firma del vocal" in html
        assert 'type="file"' in html
        assert _subir(client_as(c.student)).status_code == 200

    def test_aprobado_ya_no_ofrece_subir(self, caso, client_as, db_session):
        c = caso()
        _listo(db_session, c)
        _subir(client_as(c.student))
        AnexoService.approve(db_session, c.process, c.revisor.id)
        db_session.commit()
        page = client_as(c.student).get(BASE, follow_redirects=False)
        assert page.status_code == 200
        assert 'type="file"' not in page.text
        assert "hx-delete" not in page.text
        resp = _subir(client_as(c.student))
        assert resp.status_code == 400 and resp.headers.get("X-Tt-Error")

    def test_archivo_invalido_repinta_con_error_y_no_escribe(self, caso, client_as, db_session,
                                                             entorno):
        c = caso()
        antes = _archivos(entorno.base)
        resp = client_as(c.student).post(
            BASE + "/escaneo", files={"archivo": ("x.txt", b"no es pdf", "text/plain")})
        assert resp.status_code == 200
        assert resp.headers.get("X-Tt-Error")
        assert _doc(db_session, c) is None
        assert _archivos(entorno.base) == antes

    def test_corte_3_post_es_400_sin_archivo(self, caso, client_as, corte, entorno):
        c = caso()
        corte(3)
        antes = _archivos(entorno.base)
        resp = _subir(client_as(c.student))
        assert resp.status_code == 400 and resp.headers.get("X-Tt-Error")
        assert _archivos(entorno.base) == antes

    def test_fuera_de_la_fase_6_es_400(self, caso, client_as, db_session):
        c = caso()
        c.process.current_phase = c.review_phase
        db_session.commit()
        resp = _subir(client_as(c.student))
        assert resp.status_code == 400 and resp.headers.get("X-Tt-Error")


class TestBorrado:
    def test_borra_el_pendiente_y_regresa_la_fase(self, caso, client_as, db_session):
        c = caso()
        _listo(db_session, c)
        _subir(client_as(c.student))
        resp = client_as(c.student).delete(BASE + "/escaneo")
        assert resp.status_code == 200, resp.text[:300]
        assert _doc(db_session, c) is None
        assert 'type="file"' in resp.text

    def test_borrar_el_aprobado_es_400_por_las_dos_rutas(self, caso, client_as, db_session):
        c = caso()
        _listo(db_session, c)
        _subir(client_as(c.student))
        AnexoService.approve(db_session, c.process, c.revisor.id)
        db_session.commit()
        r1 = client_as(c.student).delete(BASE + "/escaneo")
        r2 = client_as(c.student).delete("/titulatec/student/documents/" + TIPO)
        for r in (r1, r2):
            assert r.status_code == 400, r.status_code
            assert r.headers.get("X-Tt-Error")
        assert _doc(db_session, c) is not None

    def test_borrar_el_observado_por_la_ruta_generica_es_400(self, caso, client_as,
                                                             db_session, entorno):
        # Revision final, punto 7: la ruta generica no miraba el dictamen.
        from itcj2.apps.titulatec.services.document_service import DocumentService
        c = caso()
        _listo(db_session, c)
        _subir(client_as(c.student))
        AnexoService.observe(db_session, c.process, c.revisor.id, reason="Ilegible")
        db_session.commit()
        antes = _archivos(entorno.base)

        for url in ("/titulatec/student/documents/" + TIPO, BASE + "/escaneo"):
            resp = client_as(c.student).delete(url)
            assert resp.status_code == 400, (url, resp.status_code)
            assert (unquote(resp.headers["X-Tt-Error"])
                    == DocumentService.ANEXO_SCAN_REVIEWED_MSG), url
        doc = _doc(db_session, c)
        assert doc is not None and doc.review_status == "rejected"
        assert _archivos(entorno.base) == antes

    def test_corte_3_delete_es_400(self, caso, client_as, corte):
        c = caso()
        corte(3)
        resp = client_as(c.student).delete(BASE + "/escaneo")
        assert resp.status_code == 400


class TestTablero:
    def test_el_cta_aparece_solo_en_fase_6_operable(self, caso, client_as, corte):
        c = caso()
        assert BASE in client_as(c.student).get(DASH).text
        corte(3)
        assert BASE not in client_as(c.student).get(DASH).text

    def test_el_cta_no_aparece_en_la_fase_5(self, caso, client_as, db_session):
        c = caso()
        c.process.current_phase = c.review_phase
        db_session.commit()
        assert BASE not in client_as(c.student).get(DASH).text
