"""Fase 5 (revisión de sinodales), Task 9: «Mis revisiones» del docente.

Spec 2026-10-22-titulatec-fase5-revision-sinodales §7, §8.2 y §12, D1, D6, D7,
D10 y D13. Lo que se fija aquí, ruta por ruta (`pages/revisiones_admin.py`):

- menú «Mis revisiones» oculto con el corte en 3 (y en 5) y visible con 9;
  aterrizaje del docente (`titulatec_sinodal`) condicionado a permiso + fase;
- la bandeja (pestañas, búsqueda preservada) y la conversación con el
  encabezado mínimo de D13 (nunca teléfono, domicilio ni CURP);
- guarda de participante: el sustituido, un extraño, un jefe con todos los
  permisos y el propio alumno reciben 404 sin header en TODA ruta con
  `{process_id}`, y nada se escribe (cada 404 viene con el 200 del
  participante en la misma ruta);
- mensajes y adjuntos (validación = 200 con `X-Tt-Review-Keep`), votos,
  reconfirmación del voto que cierra (200 con el panel, nada escrito), cierre
  con `confirm=1`, versión cambiada (aviso, nada escrito);
- refresco incremental `?after=` (solo lo nuevo, estado fuera de banda) que se
  detiene al cerrarse;
- descargas solo de mensajes del proceso autorizado, con `nosniff`;
- corte a T-soft en la fase 5 o antes: 404 en páginas, parciales y archivos;
  400 en acciones.

Todo test fija el corte EXPLÍCITO (el comando corre con 3, como producción).
"""
from __future__ import annotations

import io
import os
import zipfile
from datetime import datetime
from types import SimpleNamespace

import lxml.html
import pytest

from itcj2.apps.titulatec.services import email_helper
from itcj2.apps.titulatec.services.phase_service import PhaseService
from itcj2.apps.titulatec.utils import storage

URL = "/titulatec/admin/revisiones"
BODY = URL + "/body"
PAGE_PERM = "titulatec.synodal.page.my_reviews"
DOCENTE_PERMS = (
    PAGE_PERM,
    "titulatec.chat.api.read",
    "titulatec.chat.api.send",
    "titulatec.chat.api.upload",
    "titulatec.synodal.api.vote",
)
_RUN = os.getpid()
ROLE_DOCENTE = f"tt_test_docente_rev_{_RUN}"
ROLE_SIN_PAGINA = f"tt_test_docente_rev_sinpag_{_RUN}"
ROLE_SIN_ADJUNTO = f"tt_test_docente_rev_sinadj_{_RUN}"
ROLE_JEFE = f"tt_test_jefe_rev_{_RUN}"
POLL_TRIGGER = "every 15s [document.visibilityState=='visible']"

PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
       b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")


def _zip(names: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, c in names.items():
            z.writestr(n, c)
    return buf.getvalue()


DOCX = _zip({"[Content_Types].xml": "<x/>", "word/document.xml": "<w/>"})


# ---------------------------------------------------------------------------
# Andamiaje
# ---------------------------------------------------------------------------
@pytest.fixture()
def corte(monkeypatch, seed_phase_defs):
    seed_phase_defs()

    def _fijar(fase):
        monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: fase))
    return _fijar


@pytest.fixture(autouse=True)
def entorno(monkeypatch, corte, tmp_path):
    """Corte en 9, raíz de archivos en `tmp_path` (donde `make_review_case`
    escribe sus PDFs) y correo parcheado."""
    corte(9)
    monkeypatch.setattr(storage, "_base", lambda: tmp_path)
    monkeypatch.setattr(email_helper, "deliver_detailed", lambda **kw: (True, None))
    return SimpleNamespace(base=tmp_path)


@pytest.fixture()
def esc(db_session, make_review_case, make_role, grant_user_role):
    """`make_review_case` con los 4 sinodales con los permisos del docente, y
    COMMIT: el motor hace `rollback` en sus negativas bajo el candado, y bajo
    `create_savepoint` eso borraría lo sembrado."""
    def _build(*, perms=DOCENTE_PERMS, role_name=ROLE_DOCENTE, **kw):
        c = make_review_case(**kw)
        rol = make_role(role_name, perms)
        for t in c.teachers.values():
            grant_user_role(t, rol)
        db_session.commit()
        c.url = f"{URL}/{c.process.id}"
        c.pres = c.teachers["president"]
        return c

    return _build


def _hdr(msg):
    from itcj2.apps.titulatec.pages.revisiones_admin import _hdr as real
    return real(msg)


def _subir(db, c, raw=PDF, name="proyecto.pdf"):
    """Una versión por el motor: deja su mensaje `version` en la conversación."""
    from itcj2.apps.titulatec.models import ChatMessage
    from itcj2.apps.titulatec.services.review_service import ReviewService

    v = ReviewService.upload_version(db, c.process, c.student.id, raw=raw, original_name=name)
    msg = (db.query(ChatMessage).filter_by(chat_id=c.chat.id, version_id=v.id).one())
    return v, msg


def _mensajes(db, c):
    from itcj2.apps.titulatec.models import ChatMessage
    return db.query(ChatMessage).filter_by(chat_id=c.chat.id).order_by(ChatMessage.id).all()


def _votos(db, c):
    from itcj2.apps.titulatec.models import ReviewVersion, ReviewVote
    return (db.query(ReviewVote).join(ReviewVersion, ReviewVersion.id == ReviewVote.version_id)
            .filter(ReviewVersion.process_id == c.process.id).all())


def _fase5(db, c):
    from itcj2.apps.titulatec.models import ProcessPhase
    n5 = PhaseService.phase_number_for_code(db, "synodal_review")
    db.expire_all()
    return (db.query(ProcessPhase.status)
            .filter_by(process_id=c.process.id, phase_number=n5).scalar())


def _chat(db, c):
    from itcj2.apps.titulatec.models import ProcessChat
    db.expire_all()
    return db.query(ProcessChat).filter_by(process_id=c.process.id).one()


def _sidebar(html: str) -> list[tuple[str, str]]:
    doc = lxml.html.fromstring(html)
    return [(a.get("hx-get"), " ".join(a.text_content().split()))
            for a in doc.xpath('//aside[@id="ttSide"]//a[@hx-get]')]


def _doc(html):
    return lxml.html.fromstring(html) if html.strip() else None


def _poll(html):
    """Los elementos que refrescan la conversación (con su `hx-trigger`)."""
    doc = _doc(html)
    if doc is None:
        return []
    return [e for e in doc.xpath('//*[@data-tt-review-poll]')
            if (e.get("hx-trigger") or "").startswith("every")]


# ---------------------------------------------------------------------------
# 1. Menú y aterrizaje
# ---------------------------------------------------------------------------
def test_fila_del_menu_y_su_guarda_de_fase():
    from itcj2.apps.titulatec.pages.nav import _ADMIN_NAV, _NAV_PHASE_GATE

    item = next(f for f in _ADMIN_NAV if f[0] == "Mis revisiones")
    assert item[1:] == ("bi-chat-square-text", URL, {PAGE_PERM})
    assert _NAV_PHASE_GATE[URL] == "synodal_review"


@pytest.mark.parametrize("cut,visible", [(3, False), (5, False), (9, True)])
def test_el_menu_sigue_al_corte(cut, visible, corte, db_session, esc):
    from itcj2.apps.titulatec.pages.nav import admin_nav_items

    c = esc()
    corte(cut)

    items = [(i["url"], i["label"]) for i in admin_nav_items(c.pres.id, db_session)]

    assert ((URL, "Mis revisiones") in items) is visible


def test_resolve_dashboard_url_del_docente():
    from itcj2.apps.titulatec.pages.nav import resolve_dashboard_url

    sinodal = {"titulatec_sinodal"}
    fase = {"synodal_review"}
    assert resolve_dashboard_url(sinodal, perms={PAGE_PERM}, operable=fase) == URL
    # Sin la fase operable, sin el permiso o sin `operable`: el de siempre.
    assert resolve_dashboard_url(sinodal, perms={PAGE_PERM},
                                 operable={"synodal_assignment"}) == "/titulatec/sinodal/"
    assert resolve_dashboard_url(sinodal, perms=set(), operable=fase) == "/titulatec/sinodal/"
    assert resolve_dashboard_url(sinodal, perms={PAGE_PERM}) == "/titulatec/sinodal/"
    # Un jefe que además es docente sigue en Sinodales (su fila va antes).
    assert resolve_dashboard_url(
        {"titulatec_vinculacion", "titulatec_sinodal"},
        perms={PAGE_PERM, "titulatec.synodal.page.list"},
        operable={"synodal_assignment", "synodal_review"}) == "/titulatec/admin/sinodales"


@pytest.mark.parametrize("cut,destino", [(3, "/titulatec/sinodal/"), (9, URL)])
def test_el_landing_del_docente_sigue_al_corte(cut, destino, corte, client_as, make_user,
                                               make_role, grant_user_role):
    corte(cut)
    docente = make_user(first_name="DOCENTE", last_name="LANDING")
    grant_user_role(docente, make_role("titulatec_sinodal", (PAGE_PERM,)))

    resp = client_as(docente).get("/titulatec/", follow_redirects=False)

    assert resp.status_code == 302, resp.text[:300]
    assert resp.headers["location"] == destino


# ---------------------------------------------------------------------------
# 2. La bandeja
# ---------------------------------------------------------------------------
def test_la_pagina_lista_mis_revisiones(esc, client_as):
    from tests.fastapi.titulatec.paging_asserts import assert_buscador_preservado

    c = esc()
    cli = client_as(c.pres)

    resp = cli.get(URL)

    assert resp.status_code == 200, resp.text[:500]
    assert (URL, "Mis revisiones") in _sidebar(resp.text)
    doc = assert_buscador_preservado(resp.text, input_id="tt-rev-q",
                                     filters_id="tt-rev-filters", q="")
    (fila,) = doc.xpath(f'//*[@id="tt-rev-row-{c.process.id}"]')
    assert c.student.control_number in fila.text_content()
    # Abrir la conversación es navegación admin: hx-select == hx-target -> outerHTML.
    assert fila.get("hx-get") == c.url
    assert fila.get("hx-target") == fila.get("hx-select") == "#tt-admin-content"
    assert fila.get("hx-swap") == "morph:outerHTML"
    assert doc.xpath('//*[@id="tt-rev-tab-por_revisar"]')[0].text_content().count("(1)") == 1

    otra = cli.get(BODY + "?tab=en_curso")
    assert otra.status_code == 200
    assert c.student.control_number not in otra.text


def test_sin_el_permiso_de_la_pagina_no_entra(esc, client_as, make_app_user_without_perms):
    c = esc(perms=DOCENTE_PERMS[1:], role_name=ROLE_SIN_PAGINA)
    ajeno = make_app_user_without_perms()

    assert client_as(ajeno).get(URL).status_code == 403
    assert client_as(ajeno).get(BODY).status_code == 403
    # Participante con los permisos del chat pero sin la pestaña: tampoco.
    assert client_as(c.pres).get(c.url).status_code == 403


# ---------------------------------------------------------------------------
# 3. La conversación (D13)
# ---------------------------------------------------------------------------
def test_encabezado_d13_sin_telefono_domicilio_ni_curp(esc, client_as, db_session):
    from itcj2.apps.titulatec.models import FormatB
    from itcj2.core.models.program import Program
    from itcj2.core.models.student_profile import StudentProfile

    c = esc()
    fb = db_session.get(FormatB, c.process.id)
    fb.phone, fb.mobile_phone = "6561112233", "6564445566"
    fb.street, fb.neighborhood, fb.postal_code = "Calle Inventada", "Colonia Ficticia", "39871"
    db_session.add(StudentProfile(user_id=c.student.id, phone="6567778899",
                                  curp="XEXX010101HNEXXXA4"))
    db_session.commit()

    resp = client_as(c.pres).get(c.url)

    assert resp.status_code == 200, resp.text[:500]
    head = lxml.html.fromstring(resp.text).xpath('//*[@id="tt-rev-head"]')[0].text_content()
    assert c.student.first_name in head and c.student.last_name in head
    assert c.student.control_number in head
    assert db_session.get(Program, c.process.program_id).name in head
    assert c.process.modality.name in head
    assert "Sistema de revision de prueba" in head
    for rol, etiqueta in (("secretary", "Secretario"), ("vocal", "Vocal"),
                          ("alternate", "Vocal Suplente")):
        assert c.teachers[rol].first_name in head and etiqueta in head
    for prohibido in ("6561112233", "6564445566", "6567778899", "Calle Inventada",
                      "Colonia Ficticia", "39871", "XEXX010101HNEXXXA4", "/document"):
        assert prohibido not in resp.text, prohibido


def test_sin_titulo_del_proyecto_pinta_guion(esc, client_as, db_session):
    from itcj2.apps.titulatec.models import FormatB

    c = esc()
    db_session.get(FormatB, c.process.id).project_name = None
    db_session.commit()

    resp = client_as(c.pres).get(c.url)

    assert resp.status_code == 200
    (dd,) = lxml.html.fromstring(resp.text).xpath('//*[@id="tt-rev-project"]')
    assert dd.text_content().strip() == "—"


def test_abrir_crea_la_conversacion_si_falta(esc, client_as, db_session):
    from itcj2.apps.titulatec.services.review_service import OPEN_CHAT_MSG

    c = esc()
    db_session.delete(c.chat)
    db_session.commit()

    resp = client_as(c.pres).get(c.url)

    assert resp.status_code == 200, resp.text[:500]
    chat = _chat(db_session, c)
    assert chat.closed_at is None
    assert OPEN_CHAT_MSG in resp.text


def test_abrir_marca_leido(esc, client_as, db_session):
    from itcj2.apps.titulatec.services.review_service import ReviewService

    c = esc()
    ReviewService.post_message(db_session, c.process, c.student.id, body="Buenas tardes")
    assert ReviewService.unread_counts(db_session, c.pres.id, [c.chat.id]) == {c.chat.id: 1}

    resp = client_as(c.pres).get(c.url)

    assert resp.status_code == 200
    assert "Buenas tardes" in resp.text
    assert ReviewService.unread_counts(db_session, c.pres.id, [c.chat.id]) == {c.chat.id: 0}


def test_la_conversacion_pinta_los_mensajes_como_tu_y_con_ligas_guardadas(esc, client_as,
                                                                          db_session):
    from itcj2.apps.titulatec.services.review_service import ReviewService

    c = esc(versions=0)
    _v, vmsg = _subir(db_session, c)
    ReviewService.post_message(db_session, c.process, c.pres.id, body="Mi observación")

    resp = client_as(c.pres).get(c.url)

    doc = lxml.html.fromstring(resp.text)
    (mia,) = [li for li in doc.xpath('//li[@data-tt-msg-id]') if "Mi observación" in
              li.text_content()]
    assert "is-mine" in mia.get("class") and "Tú" in mia.text_content()
    (liga,) = doc.xpath(f'//li[@id="tt-rv-msg-{vmsg.id}"]//a')
    assert liga.get("href") == f"{c.url}/archivo/{vmsg.id}"


# ---------------------------------------------------------------------------
# 4. Guarda de participante: 404 uniforme, nada escrito
# ---------------------------------------------------------------------------
@pytest.fixture()
def matriz(esc, db_session, make_user, make_role, grant_user_role):
    """Tesis (votar no cierra) con una versión subida y los actores negativos."""
    from itcj2.apps.titulatec.models import SynodalAssignment

    c = esc(signature_rule="all_synodals", versions=0)
    _v, vmsg = _subir(db_session, c)
    docente = make_role(ROLE_DOCENTE, DOCENTE_PERMS)

    # Sustituido: su asignación queda inactiva y entra otro docente.
    sustituido = c.teachers["secretary"]
    viejo = c.assignments["secretary"]
    viejo.is_active = False
    viejo.replaced_at = datetime(2026, 10, 20, 9, 0)
    db_session.flush()
    nuevo = make_user(first_name="NUEVO", last_name="SECRETARIO")
    grant_user_role(nuevo, docente)
    db_session.add(SynodalAssignment(process_id=c.process.id, user_id=nuevo.id,
                                     role="secretary", assigned_by_id=c.pres.id))
    extrano = make_user(first_name="EXTRANO", last_name="DOCENTE")
    grant_user_role(extrano, docente)
    jefe = make_user(first_name="JEFE", last_name="TODOPODEROSO")
    grant_user_role(jefe, make_role(ROLE_JEFE, DOCENTE_PERMS + (
        "titulatec.process.api.read.all", "titulatec.synodal.page.list",
        "titulatec.synodal.api.read", "titulatec.officers.api.manage")))
    grant_user_role(c.student, docente)          # el alumno, con permisos de docente
    db_session.commit()

    rutas = [
        ("conversacion", "GET", c.url, None),
        ("mensajes", "GET", f"{c.url}/mensajes?after=0", None),
        ("mensaje", "POST", f"{c.url}/mensaje", {"body": "Hola desde la matriz"}),
        ("voto", "POST", f"{c.url}/voto", {"verdict": "approved", "comment": "",
                                           "version": "1"}),
        ("archivo", "GET", f"{c.url}/archivo/{vmsg.id}", None),
    ]
    return SimpleNamespace(c=c, rutas=rutas, actores={
        "sustituido": sustituido, "extrano": extrano, "jefe": jefe, "alumno": c.student})


def _call(cli, method, url, form):
    return cli.get(url) if method == "GET" else cli.post(url, data=form or {})


@pytest.mark.parametrize("actor", ["sustituido", "extrano", "jefe", "alumno"])
def test_solo_los_sinodales_vigentes_entran(actor, matriz, client_as, db_session):
    from itcj2.apps.titulatec.models import ChatMessage

    m = matriz
    for alias, method, url, form in m.rutas:
        ok = _call(client_as(m.c.pres), method, url, form)
        assert ok.status_code == 200, f"[{alias}] positivo roto: {ok.text[:300]}"

    quien = m.actores[actor]

    def _suyos():
        return (db_session.query(ChatMessage)
                .filter_by(chat_id=m.c.chat.id, author_id=quien.id).count())

    antes = (len(_mensajes(db_session, m.c)), len(_votos(db_session, m.c)), _suyos())
    for alias, method, url, form in m.rutas:
        ko = _call(client_as(quien), method, url, form)
        assert ko.status_code == 404, f"[{alias}] {actor} respondió {ko.status_code}"
        assert not ko.headers.get("X-Tt-Error"), alias

    assert (len(_mensajes(db_session, m.c)), len(_votos(db_session, m.c)), _suyos()) == antes


def test_un_proceso_inexistente_es_el_mismo_404(esc, client_as):
    c = esc()

    resp = client_as(c.pres).get(f"{URL}/{c.process.id + 100000}")

    assert resp.status_code == 404
    assert not resp.headers.get("X-Tt-Error")


# ---------------------------------------------------------------------------
# 5. Mensajes y adjuntos
# ---------------------------------------------------------------------------
def test_enviar_mensaje_devuelve_lo_nuevo_desde_after(esc, client_as, db_session):
    from itcj2.apps.titulatec.services.review_service import ReviewService

    c = esc(versions=0)
    previo = ReviewService.post_message(db_session, c.process, c.student.id, body="Ya leí")
    del_vocal = ReviewService.post_message(db_session, c.process, c.teachers["vocal"].id,
                                           body="Mensaje del vocal")

    resp = client_as(c.pres).post(f"{c.url}/mensaje",
                                  data={"body": "Revisaré el capítulo 3", "after": str(previo.id)})

    assert resp.status_code == 200, resp.text[:500]
    assert resp.headers.get("X-Tt-Review-Keep") is None
    assert "Revisaré el capítulo 3" in resp.text
    assert "Mensaje del vocal" in resp.text             # lo que el cliente no tenía
    assert f'id="tt-rv-msg-{previo.id}"' not in resp.text
    ultimo = _mensajes(db_session, c)[-1]
    assert (ultimo.author_id, ultimo.body, ultimo.kind) == (c.pres.id, "Revisaré el capítulo 3",
                                                           "message")
    assert ReviewService.unread_counts(db_session, c.pres.id, [c.chat.id]) == {c.chat.id: 0}
    assert del_vocal.id < ultimo.id


def test_sin_after_devuelve_solo_el_mensaje_propio(esc, client_as, db_session):
    from itcj2.apps.titulatec.services.review_service import ReviewService

    c = esc(versions=0)
    ReviewService.post_message(db_session, c.process, c.teachers["vocal"].id, body="Del vocal")

    resp = client_as(c.pres).post(f"{c.url}/mensaje", data={"body": "Solo lo mío"})

    assert resp.status_code == 200
    assert "Solo lo mío" in resp.text and "Del vocal" not in resp.text


def test_enviar_adjunto_y_descargarlo(esc, client_as, db_session, entorno):
    c = esc(versions=0)
    cli = client_as(c.pres)

    resp = cli.post(f"{c.url}/mensaje", data={"body": "", "after": "0"},
                    files={"archivo": ("Revisión anotada.pdf", PDF, "application/pdf")})

    assert resp.status_code == 200, resp.text[:500]
    msg = _mensajes(db_session, c)[-1]
    assert msg.attachment_path and msg.attachment_name == "Revisión anotada.pdf"
    assert (entorno.base / msg.attachment_path).is_file()
    dl = cli.get(f"{c.url}/archivo/{msg.id}")
    assert dl.status_code == 200
    assert dl.content == PDF
    assert dl.headers["X-Content-Type-Options"] == "nosniff"
    assert dl.headers["Content-Disposition"].startswith("inline")
    assert dl.headers["content-type"].startswith("application/pdf")


def test_un_word_se_descarga_como_adjunto(esc, client_as, db_session):
    c = esc(versions=0)
    cli = client_as(c.pres)
    cli.post(f"{c.url}/mensaje", data={"body": "Te dejo el anotado"},
             files={"archivo": ("anotado.docx", DOCX, "application/octet-stream")})
    msg = _mensajes(db_session, c)[-1]

    dl = cli.get(f"{c.url}/archivo/{msg.id}")

    assert dl.status_code == 200
    assert dl.headers["Content-Disposition"].startswith("attachment")
    assert dl.headers["X-Content-Type-Options"] == "nosniff"


def test_un_input_de_archivo_vacio_no_es_adjunto(esc, client_as, db_session):
    c = esc(versions=0)

    resp = client_as(c.pres).post(f"{c.url}/mensaje", data={"body": "Sin archivo"},
                                  files={"archivo": ("", b"", "application/octet-stream")})

    assert resp.status_code == 200, resp.text[:500]
    msg = _mensajes(db_session, c)[-1]
    assert (msg.body, msg.attachment_path) == ("Sin archivo", None)


@pytest.mark.parametrize("datos,archivo,esperado", [
    ({"body": "   "}, None, "MESSAGE_EMPTY_MSG"),
    ({"body": "x" * 4001}, None, "MESSAGE_TOO_LONG_MSG"),
    ({"body": "Va mi Word"}, ("disfrazado.pdf", DOCX, "application/pdf"), None),
    ({"body": ""}, ("vacio.pdf", b"", "application/pdf"), None),
])
def test_validacion_del_mensaje_200_sin_escribir(datos, archivo, esperado, esc, client_as,
                                                 db_session, entorno):
    from itcj2.apps.titulatec.services import review_service as rs

    c = esc(versions=0)
    antes = len(_mensajes(db_session, c))

    kw = {"files": {"archivo": archivo}} if archivo else {}
    resp = client_as(c.pres).post(f"{c.url}/mensaje", data=datos, **kw)

    assert resp.status_code == 200, resp.text[:500]
    assert resp.headers.get("X-Tt-Review-Keep") == "1"
    (err,) = lxml.html.fromstring(resp.text).xpath('//*[@id="tt-rev-composer-error"]')
    assert err.get("hx-swap-oob")
    if esperado:
        assert getattr(rs, esperado) in err.text_content()
    else:
        assert err.text_content().strip()
    assert len(_mensajes(db_session, c)) == antes
    assert not list(entorno.base.rglob("m*_*"))


def test_adjuntar_exige_su_permiso(esc, client_as, db_session):
    c = esc(versions=0, perms=tuple(p for p in DOCENTE_PERMS if not p.endswith("upload")),
            role_name=ROLE_SIN_ADJUNTO)
    cli = client_as(c.pres)

    con = cli.post(f"{c.url}/mensaje", data={"body": "Con archivo"},
                   files={"archivo": ("a.pdf", PDF, "application/pdf")})
    sin = cli.post(f"{c.url}/mensaje", data={"body": "Sin archivo"})

    assert con.status_code == 403
    assert sin.status_code == 200
    assert [m.body for m in _mensajes(db_session, c)] == ["Sin archivo"]
    # Sin el permiso, el formulario no ofrece adjuntar.
    page = cli.get(c.url)
    assert not lxml.html.fromstring(page.text).xpath('//form[@id="tt-rev-composer"]//input[@type="file"]')


def test_escribir_en_una_revision_cerrada_es_400(esc, client_as, db_session):
    from itcj2.apps.titulatec.services.review_service import CLOSED_MSG

    c = esc()
    _chat(db_session, c).closed_at = datetime(2026, 10, 21, 9, 0)
    db_session.commit()

    resp = client_as(c.pres).post(f"{c.url}/mensaje", data={"body": "Tarde"})

    assert resp.status_code == 400
    assert resp.headers["X-Tt-Error"] == _hdr(CLOSED_MSG)


# ---------------------------------------------------------------------------
# 6. Votos
# ---------------------------------------------------------------------------
def test_votar_sin_cerrar(esc, client_as, db_session):
    c = esc(signature_rule="all_synodals", versions=0)
    _subir(db_session, c)

    resp = client_as(c.pres).post(f"{c.url}/voto", data={
        "verdict": "approved", "comment": "Bien estructurado", "version": "1"})

    assert resp.status_code == 200, resp.text[:500]
    assert resp.headers.get("X-Tt-Notice-Kind") == "success"
    (voto,) = _votos(db_session, c)
    assert (voto.user_id, voto.verdict, voto.comment) == (c.pres.id, "approved",
                                                          "Bien estructurado")
    doc = lxml.html.fromstring(resp.text)
    assert doc.xpath('//*[@id="tt-rev-conv"]')
    assert any("aprobó la versión 1" in li.text_content()
               for li in doc.xpath('//li[@data-tt-msg-id]'))
    assert _fase5(db_session, c) == "in_progress"


def test_pedir_cambios_sin_comentario_200_sin_escribir(esc, client_as, db_session):
    from itcj2.apps.titulatec.services.review_service import COMMENT_REQUIRED_MSG

    c = esc(versions=0)
    _subir(db_session, c)

    resp = client_as(c.pres).post(f"{c.url}/voto", data={
        "verdict": "changes_requested", "comment": "  ", "version": "1"})

    assert resp.status_code == 200
    (err,) = lxml.html.fromstring(resp.text).xpath('//*[@id="tt-rev-vote-error"]')
    assert COMMENT_REQUIRED_MSG in err.text_content()
    assert _votos(db_session, c) == []


def test_un_voto_que_no_cuenta_es_400(esc, client_as, db_session):
    from itcj2.apps.titulatec.services.review_service import NOT_COUNTING_MSG

    c = esc(versions=0)
    _subir(db_session, c)

    resp = client_as(c.teachers["secretary"]).post(f"{c.url}/voto", data={
        "verdict": "approved", "comment": "", "version": "1"})

    assert resp.status_code == 400
    assert resp.headers["X-Tt-Error"] == _hdr(NOT_COUNTING_MSG)
    assert _votos(db_session, c) == []


def test_reconfirmacion_200_con_el_panel_y_nada_escrito(esc, client_as, db_session):
    from itcj2.apps.titulatec.services.review_service import CONFIRM_CLOSE_MSG

    c = esc(versions=0)                    # integral: el Presidente cierra
    _subir(db_session, c)
    antes = len(_mensajes(db_session, c))

    resp = client_as(c.pres).post(f"{c.url}/voto", data={
        "verdict": "approved", "comment": "Listo para liberar", "version": "1"})

    assert resp.status_code == 200, resp.text[:500]
    doc = lxml.html.fromstring(resp.text)
    (panel,) = doc.xpath('//*[@id="tt-rev-confirm"]')
    assert CONFIRM_CLOSE_MSG in panel.text_content()
    valores = {i.get("name"): i.get("value") for i in panel.xpath('.//input')}
    assert valores["confirm"] == "1" and valores["version"] == "1"
    assert valores["verdict"] == "approved" and valores["comment"] == "Listo para liberar"
    assert _votos(db_session, c) == []
    assert len(_mensajes(db_session, c)) == antes
    assert _fase5(db_session, c) == "in_progress"
    assert _chat(db_session, c).closed_at is None


def test_el_formulario_del_que_cierra_lleva_la_confirmacion(esc, client_as, db_session):
    from itcj2.apps.titulatec.services.review_service import (
        CONFIRM_CLOSE_MSG,
        NOT_COUNTING_MSG,
    )

    c = esc(versions=0)
    _subir(db_session, c)

    doc = lxml.html.fromstring(client_as(c.pres).get(c.url).text)
    (aprobar,) = doc.xpath('//*[@id="tt-rev-vote-form"]//button[@value="approved"]')
    assert CONFIRM_CLOSE_MSG in aprobar.get("hx-confirm")
    assert aprobar.get("data-tt-confirm-ok")
    (conf,) = doc.xpath('//*[@id="tt-rev-vote-form"]//input[@name="confirm"]')
    assert conf.get("value") == "1"
    # El `hx-post` vive en cada botón y hereda `hx-disabled-elt` del formulario:
    # htmx lo resuelve desde el botón, y un `find …` ahí no encuentra nada y
    # truena sin mandar el voto (htmx 2.0.3, visto en Chromium).
    (form,) = doc.xpath('//*[@id="tt-rev-vote-form"]')
    assert not form.get("hx-disabled-elt", "").startswith("find")

    # El Secretario (integral) no vota: no hay formulario, solo el aviso.
    otro = client_as(c.teachers["secretary"]).get(c.url).text
    assert not lxml.html.fromstring(otro).xpath('//*[@id="tt-rev-vote-form"]')
    assert NOT_COUNTING_MSG in otro


def test_en_tesis_el_primer_voto_no_pide_confirmacion(esc, client_as, db_session):
    c = esc(signature_rule="all_synodals", versions=0)
    _subir(db_session, c)

    doc = lxml.html.fromstring(client_as(c.pres).get(c.url).text)

    (aprobar,) = doc.xpath('//*[@id="tt-rev-vote-form"]//button[@value="approved"]')
    assert not aprobar.get("hx-confirm")
    assert not doc.xpath('//*[@id="tt-rev-vote-form"]//input[@name="confirm"]')


def test_cierre_con_confirm(esc, client_as, db_session):
    c = esc(versions=0)
    _subir(db_session, c)

    resp = client_as(c.pres).post(f"{c.url}/voto", data={
        "verdict": "approved", "comment": "", "version": "1", "confirm": "1"})

    assert resp.status_code == 200, resp.text[:500]
    assert resp.headers.get("X-Tt-Notice-Kind") == "success"
    assert _fase5(db_session, c) == "approved"
    assert _chat(db_session, c).closed_at is not None
    doc = lxml.html.fromstring(resp.text)
    assert not _poll(resp.text)                          # deja de refrescar
    assert not doc.xpath('//*[@id="tt-rev-composer"]')
    assert not doc.xpath('//*[@id="tt-rev-vote-form"]')


def test_version_cambiada_avisa_y_no_escribe(esc, client_as, db_session):
    from itcj2.apps.titulatec.services.review_service import VERSION_CHANGED_MSG

    c = esc(versions=0)
    _subir(db_session, c)
    _subir(db_session, c, name="proyecto_v2.pdf")

    resp = client_as(c.pres).post(f"{c.url}/voto", data={
        "verdict": "changes_requested", "comment": "Falta el capítulo 4", "version": "1"})

    assert resp.status_code == 200, resp.text[:500]
    assert resp.headers["X-Tt-Notice"] == _hdr(VERSION_CHANGED_MSG)
    assert resp.headers["X-Tt-Notice-Kind"] == "warning"
    assert _votos(db_session, c) == []
    doc = lxml.html.fromstring(resp.text)
    (ver,) = doc.xpath('//*[@id="tt-rev-vote-form"]//input[@name="version"]')
    assert ver.get("value") == "2"
    (comentario,) = doc.xpath('//*[@id="tt-rev-vote-form"]//textarea[@name="comment"]')
    assert comentario.text_content() == "Falta el capítulo 4"


# ---------------------------------------------------------------------------
# 7. Refresco incremental
# ---------------------------------------------------------------------------
def test_refresco_trae_solo_lo_nuevo_y_se_detiene_al_cerrar(esc, client_as, db_session):
    from itcj2.apps.titulatec.services.review_service import ReviewService

    c = esc(versions=0)
    _v, vmsg = _subir(db_session, c)
    cli = client_as(c.pres)

    page = cli.get(c.url)
    (poll,) = _poll(page.text)
    assert poll.get("hx-trigger") == POLL_TRIGGER
    assert poll.get("hx-get") == f"{c.url}/mensajes"
    assert poll.get("hx-target") == poll.get("data-tt-review-poll") == "#tt-rv-list"
    assert poll.get("hx-swap") == "beforeend"

    nuevo = ReviewService.post_message(db_session, c.process, c.teachers["vocal"].id,
                                       body="Nuevo del vocal")
    resp = cli.get(f"{c.url}/mensajes?after={vmsg.id}")
    assert resp.status_code == 200
    doc = lxml.html.fromstring(resp.text)
    assert [li.get("data-tt-msg-id") for li in doc.xpath('//li[@data-tt-msg-id]')] == [
        str(nuevo.id)]
    (estado,) = doc.xpath('//*[@id="tt-rev-status-slot"]')
    assert estado.get("hx-swap-oob")
    assert ReviewService.unread_counts(db_session, c.pres.id, [c.chat.id]) == {c.chat.id: 0}

    nada = cli.get(f"{c.url}/mensajes?after={nuevo.id}")
    assert nada.status_code == 200 and not nada.text.strip()

    # Otro cierra la revisión (integral: el Presidente es yo; cierra el motor).
    ReviewService.vote(db_session, c.process, c.pres.id, verdict="approved", comment="",
                       seen_version=1, confirm=True)
    fin = cli.get(f"{c.url}/mensajes?after={nuevo.id}")
    assert fin.status_code == 200
    doc = lxml.html.fromstring(fin.text)
    assert doc.xpath('//li[@data-tt-msg-id]')
    (vivo,) = doc.xpath('//*[@id="tt-rev-live"]')
    assert vivo.get("hx-swap-oob")
    assert not _poll(fin.text)                           # el sondeo se reemplaza: se detiene
    assert not doc.xpath('//*[@id="tt-rev-composer"]')
    assert not _poll(cli.get(c.url).text)                # y la página ya no refresca


def test_refresco_sin_after_trae_todo(esc, client_as, db_session):
    c = esc(versions=0)
    _v, vmsg = _subir(db_session, c)

    resp = client_as(c.pres).get(f"{c.url}/mensajes")

    assert resp.status_code == 200
    assert f'id="tt-rv-msg-{vmsg.id}"' in resp.text


# ---------------------------------------------------------------------------
# 8. Descargas
# ---------------------------------------------------------------------------
def test_descarga_solo_de_mensajes_del_proceso(esc, client_as, db_session):
    from itcj2.apps.titulatec.services.review_service import ReviewService

    a = esc(versions=0)
    b = esc(versions=0)
    b.assignments["president"].user_id = a.pres.id     # el mismo docente en los dos
    db_session.commit()
    _va, msg_a = _subir(db_session, a)
    _vb, msg_b = _subir(db_session, b)
    texto = ReviewService.post_message(db_session, a.process, a.student.id, body="Sin archivo")
    cli = client_as(a.pres)

    propio = cli.get(f"{a.url}/archivo/{msg_a.id}")
    assert propio.status_code == 200 and propio.content == PDF
    assert propio.headers["X-Content-Type-Options"] == "nosniff"
    assert cli.get(f"{URL}/{b.process.id}/archivo/{msg_b.id}").status_code == 200

    assert cli.get(f"{a.url}/archivo/{msg_b.id}").status_code == 404      # de otro proceso
    assert cli.get(f"{a.url}/archivo/{texto.id}").status_code == 404      # sin archivo
    assert cli.get(f"{a.url}/archivo/{msg_b.id + 100000}").status_code == 404


# ---------------------------------------------------------------------------
# 9. Corte a T-soft: inerte
# ---------------------------------------------------------------------------
def test_con_el_corte_en_la_fase_5_todo_es_inerte(corte, esc, client_as, db_session):
    from itcj2.apps.titulatec.services.review_service import INERT_MSG

    c = esc(signature_rule="all_synodals", versions=0)
    _v, vmsg = _subir(db_session, c)
    cli = client_as(c.pres)
    gets = [URL, BODY, c.url, f"{c.url}/mensajes?after=0", f"{c.url}/archivo/{vmsg.id}"]
    for url in gets:                                      # positivo con el corte en 9
        assert cli.get(url).status_code == 200, url

    antes = (len(_mensajes(db_session, c)), len(_votos(db_session, c)))
    for cut in (3, 5):
        corte(cut)
        for url in gets:
            assert cli.get(url).status_code == 404, (cut, url)
        for url, datos in ((f"{c.url}/mensaje", {"body": "Hola"}),
                           (f"{c.url}/voto", {"verdict": "approved", "comment": "",
                                              "version": "1"})):
            resp = cli.post(url, data=datos)
            assert resp.status_code == 400, (cut, url)
            assert resp.headers["X-Tt-Error"] == _hdr(INERT_MSG)
    assert (len(_mensajes(db_session, c)), len(_votos(db_session, c))) == antes
