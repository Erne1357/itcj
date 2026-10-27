"""Pantallas del alumno en la revisión de sinodales (fase 5, Tarea 10).

Rutas bajo `/titulatec/student/revision` (sin `{process_id}`: el proceso es el del
alumno que pide), la tarjeta de la fase 5 del tablero y las reglas de la casa de
las plantillas nuevas. El motor vive en `test_review_service.py`; aquí se prueba
SU traducción HTTP: guardas (302/404 las lecturas, 400 las mutaciones), validación
de formulario (200 + error, nada escrito), solo lectura tras liberarse y que el
archivo solo sale de la conversación del propio alumno.

Corte a T-soft en 9 (la fase 5 operable) salvo en las pruebas de inercia, que lo
bajan a 3 (producción y CI).
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote

import lxml.html
import pytest

from itcj2.apps.titulatec.pages import student as student_pages
from itcj2.apps.titulatec.services import email_helper
from itcj2.apps.titulatec.services.phase_service import PhaseService
from itcj2.apps.titulatec.services.review_service import (
    CLOSED_MSG,
    MESSAGE_EMPTY_MSG,
    ReviewService,
)
from itcj2.apps.titulatec.utils import review_files, storage
from itcj2.core.utils.timezone import db_now
from tests.fastapi.titulatec.conftest import ROLE_STUDENT

BASE = "/titulatec/student/revision"
DASH = "/titulatec/student/dashboard"
PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<<>>\n%%EOF"
CHAT_PERMS = (
    "titulatec.chat.page.view",
    "titulatec.chat.api.read",
    "titulatec.chat.api.send",
    "titulatec.chat.api.upload",
)

ROOT = Path(__file__).resolve().parents[3] / "itcj2" / "apps" / "titulatec"


# ---------------------------------------------------------------------------
# Andamiaje
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def entorno(monkeypatch, patched_session_local, tmp_path):
    """Corte en 9, raíz de archivos en `tmp_path` (donde `make_review_case` escribe
    sus PDFs) y correo parcheado."""
    monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: 9))
    monkeypatch.setattr(storage, "_base", lambda: tmp_path)

    def _deliver(*, template, context, subject, to, que, link=None):
        return True, None

    monkeypatch.setattr(email_helper, "deliver_detailed", _deliver)
    return SimpleNamespace(base=tmp_path)


@pytest.fixture()
def corte(monkeypatch):
    def _fijar(fase):
        monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: fase))
    return _fijar


@pytest.fixture()
def caso(db_session, make_review_case, make_role):
    """Caso de la fase 5 con el alumno CON los permisos de chat (el rol `graduate`
    real los trae; `make_student` solo los de siempre) y todo confirmado: el motor
    hace `rollback` en sus negativas."""
    def _build(**kw):
        c = make_review_case(**kw)
        make_role(ROLE_STUDENT, CHAT_PERMS)
        db_session.commit()
        return c
    return _build


def _n5(db) -> int:
    return PhaseService.phase_number_for_code(db, "synodal_review")


def _archivos(base: Path) -> set:
    return {p for p in base.rglob("*") if p.is_file()}


def _docx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w:document/>")
    return buf.getvalue()


def _votar(db, c, rol, verdict, comment=None, confirm=False):
    numero = ReviewService.current_version(db, c.process.id).number
    return ReviewService.vote(db, c.process, c.teachers[rol].id, verdict=verdict,
                              comment=comment, seen_version=numero, confirm=confirm)


def _versiones(db, process_id):
    from itcj2.apps.titulatec.models import ReviewVersion
    db.expire_all()
    return (db.query(ReviewVersion).filter_by(process_id=process_id)
            .order_by(ReviewVersion.number).all())


def _mensajes(db, chat_id, **filtros):
    from itcj2.apps.titulatec.models import ChatMessage
    db.expire_all()
    return (db.query(ChatMessage).filter_by(chat_id=chat_id, **filtros)
            .order_by(ChatMessage.id).all())


# ---------------------------------------------------------------------------
# 1. Guardas de lectura: 302 en la página, 404 en parcial y archivo
# ---------------------------------------------------------------------------
class TestGuardasDeLectura:
    def test_la_pagina_con_conversacion_abre(self, caso, client_as):
        """Positivo del MISMO actor y la MISMA ruta de los negativos de abajo."""
        c = caso()

        resp = client_as(c.student).get(BASE, follow_redirects=False)

        assert resp.status_code == 200, resp.text[:300]
        assert 'data-tt-page="student_revision"' in resp.text

    def test_sin_conversacion_la_pagina_va_al_tablero_y_el_parcial_es_404(
        self, caso, client_as, db_session,
    ):
        c = caso()
        db_session.delete(c.chat)
        db_session.commit()

        pagina = client_as(c.student).get(BASE, follow_redirects=False)
        parcial = client_as(c.student).get(BASE + "/mensajes")
        archivo = client_as(c.student).get(BASE + "/archivo/1")

        assert pagina.status_code == 302
        assert pagina.headers["location"].startswith(DASH)
        assert parcial.status_code == 404
        assert archivo.status_code == 404
        assert "X-Tt-Error" not in parcial.headers

    def test_antes_de_la_fase_5_no_se_abre(self, caso, client_as, db_session):
        c = caso()
        c.process.current_phase = _n5(db_session) - 1
        db_session.commit()

        pagina = client_as(c.student).get(BASE, follow_redirects=False)
        parcial = client_as(c.student).get(BASE + "/mensajes")

        assert pagina.status_code == 302
        assert pagina.headers["location"] == DASH + "?fase=" + str(_n5(db_session))
        assert parcial.status_code == 404

    def test_sin_proceso_no_hay_conversacion(self, make_student, make_role, client_as,
                                             seed_phase_defs):
        seed_phase_defs()
        alumno = make_student()
        make_role(ROLE_STUDENT, CHAT_PERMS)

        pagina = client_as(alumno).get(BASE, follow_redirects=False)
        parcial = client_as(alumno).get(BASE + "/mensajes")

        assert pagina.status_code == 302
        assert parcial.status_code == 404

    def test_con_el_corte_en_3_queda_inerte(self, caso, client_as, corte):
        c = caso()
        assert client_as(c.student).get(BASE, follow_redirects=False).status_code == 200
        corte(3)

        pagina = client_as(c.student).get(BASE, follow_redirects=False)
        parcial = client_as(c.student).get(BASE + "/mensajes")
        mensaje = client_as(c.student).post(BASE + "/mensaje", data={"body": "hola"})
        version = client_as(c.student).post(BASE + "/version",
                                            files={"archivo": ("p.pdf", PDF, "application/pdf")})

        assert pagina.status_code == 302
        assert parcial.status_code == 404
        assert mensaje.status_code == 400 and mensaje.headers.get("X-Tt-Error")
        assert version.status_code == 400 and version.headers.get("X-Tt-Error")


# ---------------------------------------------------------------------------
# 2. La página: panel de estado, formularios y votos visibles
# ---------------------------------------------------------------------------
class TestPagina:
    def test_con_revision_abierta_trae_los_dos_formularios(self, caso, client_as):
        c = caso()

        html = client_as(c.student).get(BASE).text

        assert 'id="tt-rv-form-msg"' in html
        assert 'id="tt-rv-form-ver"' in html
        assert html.count('accept=".pdf,.doc,.docx"') == 2
        assert "Subir nueva versión" in html
        assert 'data-tt-review-poll="#tt-rv-list"' in html
        assert "every 15s" in html
        assert 'id="tt-rv-status"' in html and "Versión 1" in html

    def test_sin_versiones_pide_la_primera(self, caso, client_as):
        c = caso(versions=0)

        html = client_as(c.student).get(BASE).text

        assert "Sube la primera versión de tu proyecto" in html
        assert "Sin versiones todavía." in html
        assert "Subir nueva versión" not in html
        # El panel de subida nace abierto: es lo único que le toca hacer.
        (panel,) = lxml.html.fromstring(html).xpath('//*[@id="tt-rv-upload"]')
        assert panel.get("hidden") is None
        assert 'id="tt-rv-upload-open"' not in html

    def test_con_version_la_franja_ofrece_la_siguiente(self, caso, client_as):
        c = caso()

        doc = lxml.html.fromstring(client_as(c.student).get(BASE).text)

        (abrir,) = doc.xpath('//*[@id="tt-rv-upload-open"]')
        assert abrir.get("aria-label") == "Subir versión 2"
        assert abrir.get("data-tt-chat-toggle") == "tt-rv-upload"
        assert doc.xpath('//*[@id="tt-rv-upload"]')[0].get("hidden") is not None
        assert "Se sube como versión 2" in doc.xpath('//*[@id="tt-rv-ver-head"]')[0].text_content()

    def test_el_panel_muestra_los_votos_de_la_version_vigente(self, caso, client_as,
                                                              db_session):
        c = caso(signature_rule="all_synodals")
        _votar(db_session, c, "president", "approved")
        _votar(db_session, c, "secretary", "changes_requested", comment="Falta el marco teorico")

        html = client_as(c.student).get(BASE).text

        assert "Aprobó" in html and "Pidió cambios" in html
        assert "Sin votar" in html
        assert "Se necesita la aprobación de los 4 sinodales" in html
        assert "1 de 4 aprobaciones" in html
        assert "Falta el marco teorico" in html, "el comentario del voto va en el hilo"

    def test_pintar_la_conversacion_la_marca_leida(self, caso, client_as, db_session):
        c = caso()
        ReviewService.post_message(db_session, c.process, c.teachers["president"].id,
                                   body="Revisa el capitulo 2")
        assert ReviewService.unread_counts(db_session, c.student.id, [c.chat.id])[c.chat.id] >= 1

        client_as(c.student).get(BASE)

        db_session.expire_all()
        assert ReviewService.unread_counts(db_session, c.student.id, [c.chat.id])[c.chat.id] == 0


# ---------------------------------------------------------------------------
# 3. Subir una versión
# ---------------------------------------------------------------------------
class TestSubirVersion:
    def _subir(self, cli, nombre="proyecto.pdf", contenido=PDF, mime="application/pdf"):
        return cli.post(BASE + "/version", files={"archivo": (nombre, contenido, mime)})

    def test_una_version_valida_crea_el_numero_siguiente_y_el_mensaje(
        self, caso, client_as, db_session, entorno,
    ):
        c = caso(versions=1)

        resp = self._subir(client_as(c.student))

        assert resp.status_code == 200, resp.text[:300]
        assert [v.number for v in _versiones(db_session, c.process.id)] == [1, 2]
        mensajes = _mensajes(db_session, c.chat.id, kind="version")
        assert len(mensajes) == 1
        assert "Versión 2" in resp.text and 'data-tt-msg-id="%d"' % mensajes[0].id in resp.text
        assert "Versión 2 enviada" in unquote(resp.headers["X-Tt-Notice"])
        assert resp.headers["X-Tt-Notice-Kind"] == "success"
        nuevo = _versiones(db_session, c.process.id)[-1]
        assert (entorno.base / nuevo.file_path).is_file()

    def test_la_version_nueva_reinicia_los_votos_en_el_estado_de_la_respuesta(
        self, caso, client_as, db_session,
    ):
        c = caso(signature_rule="all_synodals")
        _votar(db_session, c, "president", "approved")

        resp = self._subir(client_as(c.student))

        assert 'hx-swap-oob="innerHTML"' in resp.text
        assert "0 de 4 aprobaciones" in resp.text
        assert 'id="tt-rv-err-ver"' in resp.text, "limpia el error del formulario fuera de banda"

    def test_un_docx_renombrado_pdf_da_200_con_error_y_no_escribe_nada(
        self, caso, client_as, db_session, entorno,
    ):
        c = caso()
        antes = _archivos(entorno.base)

        resp = self._subir(client_as(c.student), nombre="falso.pdf", contenido=_docx())

        assert resp.status_code == 200
        assert "no es un PDF o Word válido" in resp.text
        assert resp.headers["HX-Retarget"] == "#tt-rv-err-ver"
        assert resp.headers["HX-Reswap"] == "innerHTML"
        assert resp.headers["X-Tt-Review-Keep"] == "1"
        assert len(_versiones(db_session, c.process.id)) == 1
        assert _archivos(entorno.base) == antes

    def test_un_archivo_vacio_da_200_con_error_y_no_escribe_nada(
        self, caso, client_as, db_session, entorno,
    ):
        c = caso()
        antes = _archivos(entorno.base)

        resp = self._subir(client_as(c.student), contenido=b"")

        assert resp.status_code == 200
        assert "vacío" in resp.text
        assert resp.headers["X-Tt-Review-Keep"] == "1"
        assert len(_versiones(db_session, c.process.id)) == 1
        assert _archivos(entorno.base) == antes

    def test_un_archivo_sobre_el_limite_da_200_con_error_y_no_escribe_nada(
        self, caso, client_as, db_session, entorno, monkeypatch,
    ):
        c = caso()
        antes = _archivos(entorno.base)
        monkeypatch.setattr(review_files, "max_bytes", lambda: 10)

        resp = self._subir(client_as(c.student))

        assert resp.status_code == 200
        assert "El archivo supera" in resp.text
        assert len(_versiones(db_session, c.process.id)) == 1
        assert _archivos(entorno.base) == antes

    def test_sin_elegir_archivo_pide_elegirlo(self, caso, client_as, db_session):
        c = caso()

        resp = client_as(c.student).post(BASE + "/version", data={})

        assert resp.status_code == 200
        assert "Elige el archivo de tu proyecto" in resp.text
        assert resp.headers["HX-Retarget"] == "#tt-rv-err-ver"
        assert len(_versiones(db_session, c.process.id)) == 1

    def test_un_tipo_que_no_es_pdf_ni_word_da_200_con_error(self, caso, client_as, db_session):
        c = caso()

        resp = self._subir(client_as(c.student), nombre="notas.txt", contenido=b"hola",
                           mime="text/plain")

        assert resp.status_code == 200
        assert "Solo se aceptan archivos PDF o Word" in resp.text
        assert len(_versiones(db_session, c.process.id)) == 1


# ---------------------------------------------------------------------------
# 4. Mensajes
# ---------------------------------------------------------------------------
class TestMensajes:
    def test_un_mensaje_de_texto_se_pinta_escapado_y_se_guarda(self, caso, client_as,
                                                                db_session):
        c = caso()

        resp = client_as(c.student).post(BASE + "/mensaje", data={"body": "<b>hola</b> a todos"})

        assert resp.status_code == 200, resp.text[:300]
        assert "&lt;b&gt;hola&lt;/b&gt; a todos" in resp.text
        assert "<b>hola</b>" not in resp.text
        assert "tt-rv-msg--message" in resp.text and "is-mine" in resp.text
        guardados = _mensajes(db_session, c.chat.id, kind="message")
        assert [m.body for m in guardados] == ["<b>hola</b> a todos"]
        assert guardados[0].author_id == c.student.id

    def test_un_mensaje_con_adjunto_guarda_el_archivo_y_pinta_la_liga(
        self, caso, client_as, db_session, entorno,
    ):
        c = caso()

        resp = client_as(c.student).post(
            BASE + "/mensaje", data={"body": "Te dejo mi avance"},
            files={"archivo": ("avance.pdf", PDF, "application/pdf")})

        assert resp.status_code == 200, resp.text[:300]
        msg = _mensajes(db_session, c.chat.id, kind="message")[-1]
        assert msg.attachment_name == "avance.pdf"
        assert (entorno.base / msg.attachment_path).is_file()
        assert f'href="{BASE}/archivo/{msg.id}"' in resp.text

    def test_un_adjunto_solo_tambien_vale(self, caso, client_as, db_session):
        c = caso()

        resp = client_as(c.student).post(
            BASE + "/mensaje", files={"archivo": ("solo.pdf", PDF, "application/pdf")})

        assert resp.status_code == 200
        assert len(_mensajes(db_session, c.chat.id, kind="message")) == 1

    def test_un_mensaje_vacio_da_200_con_error_y_no_escribe(self, caso, client_as, db_session):
        c = caso()

        resp = client_as(c.student).post(BASE + "/mensaje", data={"body": "   "})

        assert resp.status_code == 200
        assert MESSAGE_EMPTY_MSG in resp.text
        assert resp.headers["HX-Retarget"] == "#tt-rv-err-msg"
        assert resp.headers["X-Tt-Review-Keep"] == "1"
        assert _mensajes(db_session, c.chat.id, kind="message") == []

    def test_un_mensaje_demasiado_largo_da_200_con_error(self, caso, client_as, db_session):
        c = caso()

        resp = client_as(c.student).post(BASE + "/mensaje", data={"body": "x" * 4001})

        assert resp.status_code == 200
        assert "4000" in resp.text
        assert _mensajes(db_session, c.chat.id, kind="message") == []

    def test_un_adjunto_malo_da_200_con_error_y_no_escribe(self, caso, client_as, db_session,
                                                           entorno):
        c = caso()
        antes = _archivos(entorno.base)

        resp = client_as(c.student).post(
            BASE + "/mensaje", data={"body": "mira"},
            files={"archivo": ("falso.pdf", _docx(), "application/pdf")})

        assert resp.status_code == 200
        assert "no es un PDF o Word válido" in resp.text
        assert _mensajes(db_session, c.chat.id, kind="message") == []
        assert _archivos(entorno.base) == antes

    def test_sin_el_permiso_de_adjuntar_no_sube_un_archivo(self, caso, client_as, make_role,
                                                           db_session):
        """El alumno con `send` pero sin `upload`: el texto pasa, el adjunto no."""
        from itcj2.core.models.permission import Permission
        from itcj2.core.models.role_permission import RolePermission
        from itcj2.core.services.authz_cache import invalidate_user_app

        c = caso()
        rol = make_role(ROLE_STUDENT, ())
        perm = (db_session.query(Permission)
                .filter_by(code="titulatec.chat.api.upload").one())
        db_session.query(RolePermission).filter_by(role_id=rol.id, perm_id=perm.id).delete()
        db_session.commit()
        invalidate_user_app(c.student.id, "titulatec")

        con_texto = client_as(c.student).post(BASE + "/mensaje", data={"body": "hola"})
        con_adjunto = client_as(c.student).post(
            BASE + "/mensaje", data={"body": "hola"},
            files={"archivo": ("a.pdf", PDF, "application/pdf")})

        assert con_texto.status_code == 200
        assert con_adjunto.status_code == 400 and con_adjunto.headers.get("X-Tt-Error")


# ---------------------------------------------------------------------------
# 5. Refresco (D10)
# ---------------------------------------------------------------------------
class TestRefresco:
    def test_solo_trae_lo_posterior_a_after_y_agrega_el_estado(self, caso, client_as,
                                                                db_session):
        c = caso()
        nuevo = ReviewService.post_message(db_session, c.process, c.teachers["president"].id,
                                           body="Listo, revisa el cap. 3")

        resp = client_as(c.student).get(BASE + "/mensajes", params={"after": nuevo.id - 1})

        assert resp.status_code == 200
        assert "Listo, revisa el cap. 3" in resp.text
        assert 'hx-swap-oob="innerHTML"' in resp.text and 'id="tt-rv-status"' in resp.text
        assert "Presidente" in resp.text

    def test_sin_novedades_no_trae_nada(self, caso, client_as, db_session):
        c = caso()
        nuevo = ReviewService.post_message(db_session, c.process, c.teachers["president"].id,
                                           body="uno")

        resp = client_as(c.student).get(BASE + "/mensajes", params={"after": nuevo.id})

        assert resp.status_code == 200
        assert resp.text.strip() == ""

    def test_un_after_basura_se_ignora_sin_reventar(self, caso, client_as):
        c = caso()

        resp = client_as(c.student).get(BASE + "/mensajes", params={"after": "no-es-un-numero"})

        assert resp.status_code == 200

    def test_el_refresco_marca_leido(self, caso, client_as, db_session):
        c = caso()
        nuevo = ReviewService.post_message(db_session, c.process, c.teachers["president"].id,
                                           body="hola")

        client_as(c.student).get(BASE + "/mensajes", params={"after": nuevo.id - 1})

        db_session.expire_all()
        assert ReviewService.unread_counts(db_session, c.student.id, [c.chat.id])[c.chat.id] == 0

    def test_al_cerrarse_detiene_el_sondeo_y_cambia_el_formulario_por_el_aviso(
        self, caso, client_as, db_session,
    ):
        c = caso()
        _votar(db_session, c, "president", "approved", confirm=True)

        resp = client_as(c.student).get(BASE + "/mensajes", params={"after": 0})

        assert resp.status_code == 200
        assert 'id="tt-rv-poll" hx-swap-oob="outerHTML" hidden' in resp.text
        assert 'id="tt-rv-actions"' in resp.text and "solo para consulta" in resp.text
        assert "tt-rv-form-msg" not in resp.text
        assert 'id="tt-rv-upload" class="tt-chat-upload" hx-swap-oob="true" hidden' in resp.text
        assert 'id="tt-rv-pin" class="tt-chat-pin" hx-swap-oob="true"' in resp.text


# ---------------------------------------------------------------------------
# 6. Liberado: solo consulta (D7)
# ---------------------------------------------------------------------------
class TestLiberado:
    def _liberar(self, db_session, c):
        _votar(db_session, c, "president", "approved", confirm=True)
        db_session.expire_all()
        assert c.chat.closed_at is not None

    def test_la_pagina_sigue_abierta_sin_formularios_ni_sondeo(self, caso, client_as,
                                                                db_session):
        c = caso()
        self._liberar(db_session, c)

        resp = client_as(c.student).get(BASE, follow_redirects=False)

        assert resp.status_code == 200, resp.text[:300]
        assert 'id="tt-rv-form-msg"' not in resp.text
        assert 'id="tt-rv-form-ver"' not in resp.text
        assert "data-tt-review-poll" not in resp.text
        assert "solo para consulta" in resp.text
        assert "Proyecto liberado" in resp.text
        assert "Proyecto liberado. Ya puedes pasar por tu Anexo III" in resp.text

    def test_los_posts_son_400_y_no_escriben(self, caso, client_as, db_session):
        c = caso()
        self._liberar(db_session, c)
        mensajes = len(_mensajes(db_session, c.chat.id))
        versiones = len(_versiones(db_session, c.process.id))

        m = client_as(c.student).post(BASE + "/mensaje", data={"body": "una mas"})
        v = client_as(c.student).post(BASE + "/version",
                                      files={"archivo": ("p.pdf", PDF, "application/pdf")})

        assert m.status_code == 400 and m.headers.get("X-Tt-Error")
        assert v.status_code == 400 and v.headers.get("X-Tt-Error")
        assert len(_mensajes(db_session, c.chat.id)) == mensajes
        assert len(_versiones(db_session, c.process.id)) == versiones

    def test_el_mensaje_de_cierre_del_servicio_no_se_filtra_como_error_de_formulario(
        self, caso, client_as, db_session,
    ):
        """Con la fase aún en curso pero la conversación cerrada a mano, el servicio dice
        `CLOSED_MSG`: eso es una guarda (400), no validación de formulario (200)."""
        c = caso()
        c.chat.closed_at = db_now()
        db_session.commit()

        resp = client_as(c.student).post(BASE + "/mensaje", data={"body": "hola"})

        assert resp.status_code == 400
        assert "HX-Retarget" not in resp.headers
        assert resp.headers["X-Tt-Error"]
        assert CLOSED_MSG.startswith("La revisi")


# ---------------------------------------------------------------------------
# 7. Archivos: solo los de la propia conversación
# ---------------------------------------------------------------------------
class TestArchivos:
    def _con_adjunto(self, db_session, c, nombre="nota.pdf", raw=PDF):
        return ReviewService.post_message(db_session, c.process, c.student.id, body="adjunto",
                                          raw=raw, original_name=nombre)

    def test_descarga_su_propio_pdf_inline(self, caso, client_as, db_session):
        c = caso()
        msg = self._con_adjunto(db_session, c)

        resp = client_as(c.student).get(f"{BASE}/archivo/{msg.id}")

        assert resp.status_code == 200
        assert resp.content == PDF
        assert resp.headers["content-disposition"].startswith("inline")
        assert resp.headers["x-content-type-options"] == "nosniff"

    def test_un_word_sale_como_adjunto_descargable(self, caso, client_as, db_session):
        c = caso()
        msg = self._con_adjunto(db_session, c, nombre="tesis.docx", raw=_docx())

        resp = client_as(c.student).get(f"{BASE}/archivo/{msg.id}")

        assert resp.status_code == 200
        assert resp.headers["content-disposition"].startswith("attachment")

    def test_descarga_el_archivo_de_una_version_por_su_mensaje(self, caso, client_as,
                                                                db_session):
        c = caso()
        ReviewService.upload_version(db_session, c.process, c.student.id, raw=PDF,
                                     original_name="v2.pdf")
        msg = _mensajes(db_session, c.chat.id, kind="version")[-1]

        resp = client_as(c.student).get(f"{BASE}/archivo/{msg.id}")

        assert resp.status_code == 200 and resp.content == PDF

    def test_el_mensaje_de_otro_proceso_es_404(self, caso, client_as, db_session):
        """Dos casos completos: el alumno A no baja el archivo de la conversación de B,
        ni por id directo (el mensaje se busca DENTRO de la conversación de A)."""
        a = caso()
        b = caso()
        ajeno = self._con_adjunto(db_session, b)
        propio = self._con_adjunto(db_session, a)

        ok = client_as(a.student).get(f"{BASE}/archivo/{propio.id}")
        ajena = client_as(a.student).get(f"{BASE}/archivo/{ajeno.id}")

        assert ok.status_code == 200
        assert ajena.status_code == 404
        assert "X-Tt-Error" not in ajena.headers

    def test_un_mensaje_sin_archivo_o_inexistente_es_404(self, caso, client_as, db_session):
        c = caso()
        texto = ReviewService.post_message(db_session, c.process, c.student.id, body="solo texto")

        assert client_as(c.student).get(f"{BASE}/archivo/{texto.id}").status_code == 404
        assert client_as(c.student).get(f"{BASE}/archivo/99999999").status_code == 404


# ---------------------------------------------------------------------------
# 8. Tarjeta de la fase 5 en el tablero
# ---------------------------------------------------------------------------
class TestTarjetaDelTablero:
    def _html(self, client_as, c):
        return client_as(c.student).get(DASH).text

    def test_sin_version_dice_que_suba_la_primera(self, caso, client_as):
        c = caso(versions=0)

        html = self._html(client_as, c)

        assert "Sube tu primera versión" in html
        assert f'href="{BASE}"' in html and "Abrir la conversación" in html

    def test_en_revision_cuenta_las_aprobaciones(self, caso, client_as, db_session):
        c = caso(signature_rule="all_synodals")
        _votar(db_session, c, "president", "approved")

        html = self._html(client_as, c)

        assert "En revisión: 1 de 4 aprobaciones" in html

    def test_te_pidieron_cambios(self, caso, client_as, db_session):
        c = caso(signature_rule="all_synodals")
        _votar(db_session, c, "vocal", "changes_requested", comment="Ajusta las conclusiones")

        assert "Te pidieron cambios" in self._html(client_as, c)

    def test_liberado_con_enlace_de_consulta(self, caso, client_as, db_session):
        c = caso()
        _votar(db_session, c, "president", "approved", confirm=True)

        html = self._html(client_as, c)

        assert "Liberado" in html
        assert "Consultar la conversación" in html and f'href="{BASE}"' in html

    def test_cuenta_los_nuevos_y_el_conteo_baja_al_leer(self, caso, client_as, db_session):
        c = caso()
        presidente = c.teachers["president"].id
        for texto in ("uno", "dos"):
            ReviewService.post_message(db_session, c.process, presidente, body=texto)
        # La apertura (`system`) también es «nueva» hasta que se lee la conversación.
        total = ReviewService.unread_counts(db_session, c.student.id, [c.chat.id])[c.chat.id]
        assert total >= 2

        antes = self._html(client_as, c)
        client_as(c.student).get(BASE)
        despues = self._html(client_as, c)

        assert f"{total} nuevos" in antes
        assert "data-tt-review-new" in antes
        assert "nuevos" not in despues.split("data-tt-review-card")[1].split("</div>")[0]

    def test_antes_de_la_fase_5_o_con_el_corte_en_3_no_hay_tarjeta_ni_cta(
        self, caso, db_session, corte,
    ):
        c = caso()
        ctx = student_pages._phases_ctx(db_session, c.process)
        tarjeta = next(p for p in ctx["phases"] if p["code"] == "synodal_review")
        assert tarjeta["review"] is not None and tarjeta["cta"] is not None

        c.process.current_phase = _n5(db_session) - 1
        db_session.commit()
        ctx = student_pages._phases_ctx(db_session, c.process)
        assert next(p for p in ctx["phases"] if p["code"] == "synodal_review")["review"] is None

        c.process.current_phase = _n5(db_session)
        db_session.commit()
        corte(3)
        ctx = student_pages._phases_ctx(db_session, c.process)
        tarjeta = next(p for p in ctx["phases"] if p["code"] == "synodal_review")
        assert tarjeta["review"] is None and tarjeta["cta"] is None

    def test_el_tablero_paga_una_sola_llamada_de_estado(self, caso, db_session, monkeypatch):
        c = caso()
        llamadas = []
        original = ReviewService.status_for_process

        def _contar(db, process_id, **kw):
            llamadas.append(process_id)
            return original(db, process_id, **kw)

        monkeypatch.setattr(ReviewService, "status_for_process", staticmethod(_contar))

        student_pages._phases_ctx(db_session, c.process)

        assert llamadas == [c.process.id]


class TestEstadoPuro:
    BASE = {"closed": False, "version": 1, "approvals": 0, "required": 1, "votes": []}

    def test_los_cuatro_textos(self):
        f = student_pages._review_state
        assert f({**self.BASE, "closed": True})[0] == "Liberado"
        assert f({**self.BASE, "version": None})[0] == "Sube tu primera versión"
        assert f({**self.BASE, "required": 4, "approvals": 2})[0] == "En revisión: 2 de 4 aprobaciones"
        assert f({**self.BASE})[0] == "En revisión: 0 de 1 aprobación"
        votos = [{"counts": True, "verdict": "changes_requested"}]
        assert f({**self.BASE, "votes": votos})[0] == "Te pidieron cambios"

    def test_un_voto_que_no_cuenta_no_pide_cambios(self):
        votos = [{"counts": False, "verdict": "changes_requested"}]
        assert student_pages._review_state({**self.BASE, "votes": votos})[0].startswith("En revisión")


# ---------------------------------------------------------------------------
# 8b. Revisión final (I1, I2, M7)
# ---------------------------------------------------------------------------
def _ids(html: str) -> list[int]:
    return [int(x) for x in re.findall(r'data-tt-msg-id="(\d+)"', html)]


class TestElPostTraeLoIntercalado:
    """I1: los dos formularios llevan `data-tt-review-poll` (el JS compartido les
    agrega `after`) y el POST usa la regla del docente: con `after` menor que el id
    nuevo devuelve TAMBIÉN lo que otros escribieron entre refrescos. Antes
    (`after_id = id propio - 1`) un mensaje ajeno de id menor nunca se pintaba y
    `mark_read` hasta el id propio lo daba por leído."""

    def test_los_dos_formularios_mandan_after(self, caso, client_as):
        import lxml.html

        c = caso()
        doc = lxml.html.fromstring(client_as(c.student).get(BASE).text)
        for form_id in ("tt-rv-form-msg", "tt-rv-form-ver"):
            (form,) = doc.xpath(f'//form[@id="{form_id}"]')
            assert form.get("data-tt-review-poll") == "#tt-rv-list", form_id

    def test_un_mensaje_ajeno_de_id_menor_llega_en_la_respuesta_del_post(
        self, caso, client_as, db_session,
    ):
        from itcj2.apps.titulatec.models import ChatMessage

        c = caso()
        previo = ReviewService.post_message(db_session, c.process, c.student.id,
                                            body="Ya lo tenía en pantalla")
        ajeno = ReviewService.post_message(db_session, c.process,
                                           c.teachers["president"].id,
                                           body="Llegó entre dos refrescos")

        resp = client_as(c.student).post(BASE + "/mensaje", data={
            "body": "Mi respuesta", "after": str(previo.id)})

        assert resp.status_code == 200, resp.text[:300]
        propio = _mensajes(db_session, c.chat.id, kind="message")[-1]
        assert propio.body == "Mi respuesta" and ajeno.id < propio.id
        assert _ids(resp.text) == [ajeno.id, propio.id]
        assert "Llegó entre dos refrescos" in resp.text
        # Nada queda leído sin haberse pintado: todo lo ajeno posterior a `after`
        # hasta la marca de leído viene en ESTA respuesta.
        ajenos = {m.id for m in db_session.query(ChatMessage)
                  .filter(ChatMessage.chat_id == c.chat.id, ChatMessage.id > previo.id,
                          ChatMessage.author_id != c.student.id)}
        assert ajenos and ajenos <= set(_ids(resp.text))
        assert ReviewService.unread_counts(db_session, c.student.id, [c.chat.id])[c.chat.id] == 0

    def test_la_version_tambien_trae_lo_intercalado(self, caso, client_as, db_session):
        c = caso()
        previo = ReviewService.post_message(db_session, c.process, c.student.id, body="Previo")
        ReviewService.post_message(db_session, c.process, c.teachers["vocal"].id,
                                   body="Observación del vocal")

        resp = client_as(c.student).post(
            BASE + "/version", data={"after": str(previo.id)},
            files={"archivo": ("v2.pdf", PDF, "application/pdf")})

        assert resp.status_code == 200, resp.text[:300]
        assert "Observación del vocal" in resp.text and "Versión 2" in resp.text
        assert previo.id not in _ids(resp.text)

    def test_sin_after_solo_trae_lo_propio(self, caso, client_as, db_session):
        """Misma regla que el docente: sin `after` (o uno mayor que el nuevo), solo
        el mensaje propio."""
        c = caso()
        ReviewService.post_message(db_session, c.process, c.teachers["vocal"].id, body="Del vocal")

        resp = client_as(c.student).post(BASE + "/mensaje", data={"body": "Solo lo mío",
                                                                 "after": "99999999"})

        assert "Solo lo mío" in resp.text and "Del vocal" not in resp.text


class TestNadaSeLeeAntesDeLasGuardas:
    """I2: tope solo-cabeceras (411/413) y luego dos saltos al hilo; el archivo
    no se lee (`request.form()` no se llama) si una guarda lo va a rechazar."""

    @pytest.fixture()
    def lecturas(self, monkeypatch):
        from starlette.requests import Request

        leidas = []
        original = Request.form

        def _form(self, *a, **kw):
            leidas.append(self.url.path)
            return original(self, *a, **kw)

        monkeypatch.setattr(Request, "form", _form)
        return leidas

    def _subir(self, cli):
        return cli.post(BASE + "/version", files={"archivo": ("p.pdf", PDF, "application/pdf")})

    def test_con_el_corte_en_3_no_lee_el_archivo(self, caso, client_as, corte, lecturas):
        c = caso()
        corte(3)

        version = self._subir(client_as(c.student))
        mensaje = client_as(c.student).post(BASE + "/mensaje", data={"body": "hola"})

        assert version.status_code == 400 and version.headers.get("X-Tt-Error")
        assert mensaje.status_code == 400
        assert lecturas == []

    def test_con_la_conversacion_cerrada_no_lee_el_archivo(self, caso, client_as, db_session,
                                                           lecturas):
        c = caso()
        c.chat.closed_at = db_now()
        db_session.commit()

        resp = self._subir(client_as(c.student))

        assert resp.status_code == 400
        assert unquote(resp.headers["X-Tt-Error"]) == CLOSED_MSG
        assert lecturas == []
        assert len(_versiones(db_session, c.process.id)) == 1

    def test_lo_valido_si_se_lee_una_sola_vez(self, caso, client_as, db_session, lecturas):
        c = caso()

        resp = self._subir(client_as(c.student))

        assert resp.status_code == 200, resp.text[:300]
        assert lecturas == [BASE + "/version"]
        assert len(_versiones(db_session, c.process.id)) == 2

    def test_un_cuerpo_declarado_sobre_el_tope_es_413(self, caso, client_as, db_session,
                                                      monkeypatch, lecturas):
        c = caso()
        monkeypatch.setattr(review_files, "max_body_bytes", lambda: 64)

        version = self._subir(client_as(c.student))
        mensaje = client_as(c.student).post(
            BASE + "/mensaje", data={"body": "mira"},
            files={"archivo": ("a.pdf", PDF, "application/pdf")})

        for resp in (version, mensaje):
            assert resp.status_code == 413
            assert "El archivo supera" in unquote(resp.headers["X-Tt-Error"])
        assert lecturas == []
        assert len(_versiones(db_session, c.process.id)) == 1
        assert _mensajes(db_session, c.chat.id, kind="message") == []

    def test_sin_content_length_es_411(self, caso, client_as, lecturas):
        """Un cuerpo `chunked` no declara tamaño: el tope no se podría aplicar
        antes de leerlo, así que se rechaza (mismo criterio que `public.py`)."""
        c = caso()

        resp = client_as(c.student).post(
            BASE + "/version", content=iter([b"--x\r\n"]),
            headers={"Content-Type": "multipart/form-data; boundary=x"})

        assert resp.status_code == 411 and resp.headers.get("X-Tt-Error")
        assert lecturas == []


class TestEncabezadoYCierre:
    """M7: (a) tras la primera subida el encabezado ya no pide «la primera»; (b) el
    refresco detiene el sondeo con la conversación ya no abierta aunque no haya
    mensajes nuevos (una pausa o revocación no deja mensaje)."""

    def test_tras_la_primera_version_el_encabezado_cambia_fuera_de_banda(self, caso,
                                                                         client_as):
        c = caso(versions=0)
        assert "Sube la primera versión de tu proyecto" in client_as(c.student).get(BASE).text

        resp = client_as(c.student).post(BASE + "/version",
                                         files={"archivo": ("v1.pdf", PDF, "application/pdf")})

        assert resp.status_code == 200, resp.text[:300]
        assert 'id="tt-rv-ver-head" class="tt-rvs-ver-head" hx-swap-oob="true"' in resp.text
        assert "Subir nueva versión" in resp.text
        assert "Sube la primera versión de tu proyecto" not in resp.text

    @pytest.mark.parametrize("estado", ["on_hold", "cancelled"])
    def test_sin_mensajes_nuevos_y_sin_conversacion_abierta_detiene_el_sondeo(
        self, caso, client_as, db_session, estado,
    ):
        c = caso()
        ultimo = ReviewService.post_message(db_session, c.process, c.teachers["president"].id,
                                            body="Último antes de la pausa")
        c.process.status = estado
        db_session.commit()

        resp = client_as(c.student).get(BASE + "/mensajes", params={"after": ultimo.id})

        assert resp.status_code == 200
        assert _ids(resp.text) == []
        assert 'id="tt-rv-poll" hx-swap-oob="outerHTML" hidden' in resp.text
        assert 'id="tt-rv-actions"' in resp.text and "solo para consulta" in resp.text
        assert "tt-rv-form-msg" not in resp.text


# ---------------------------------------------------------------------------
# 9. Reglas de la casa de lo nuevo
# ---------------------------------------------------------------------------
class TestReglasDeLaCasa:
    ARCHIVOS = [
        ROOT / "templates/titulatec/student/revision.html",
        *sorted((ROOT / "templates/titulatec/partials/student/revision").glob("*.html")),
        ROOT / "static/css/student/revision.css",
    ]

    def test_hay_archivos_que_revisar(self):
        assert len(self.ARCHIVOS) >= 8 and all(p.exists() for p in self.ARCHIVOS)

    def test_sin_script_inline_ni_style_inline_ni_dialogos_nativos(self):
        for p in self.ARCHIVOS:
            t = p.read_text(encoding="utf-8")
            assert "<script" not in t, p.name
            assert not re.search(r"""\sstyle\s*=""", t), p.name
            assert not re.search(r"\b(confirm|alert|prompt)\s*\(", t), p.name

    def test_el_css_usa_los_tokens_de_tipografia(self):
        css = (ROOT / "static/css/student/revision.css").read_text(encoding="utf-8")
        assert not re.search(r"font-size\s*:\s*[\d.]+(px|rem|em)", css)
        assert "var(--tt-fs-" in css

    def test_la_base_carga_los_dos_estaticos_compartidos(self):
        base = (ROOT / "templates/titulatec/student/base_student.html").read_text(encoding="utf-8")
        assert "css/review.css" in base and "js/shared/review-thread.js" in base

    def test_las_rutas_siguen_la_forma_canonica_y_no_llevan_process_id(self):
        from itcj2.apps.titulatec.pages.student import router

        propias = [r for r in router.routes if getattr(r, "path", "").startswith("/student/revision")]
        assert len(propias) == 5
        assert all("{process_id}" not in r.path for r in propias)
        assert {r.name for r in propias} == {
            "titulatec.pages.student.revision", "titulatec.pages.student.revision_messages",
            "titulatec.pages.student.revision_message", "titulatec.pages.student.revision_version",
            "titulatec.pages.student.revision_file",
        }
