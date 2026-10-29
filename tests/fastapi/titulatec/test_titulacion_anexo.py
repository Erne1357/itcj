"""Fase 6, tarea 5: vista «Anexo III» de la pestaña Titulación (spec §9.2, D3).

Rutas `/titulatec/admin/titulacion/anexo*`: página con las dos vistas, parcial,
Aprobar / Observar (con `expected_version`, R5), escaneo, Anexo generado y
presencia. Corte explícito en cada prueba: `corte(9)` opera la fase 6;
`corte(3)` es producción y deja la vista inerte.
"""
from __future__ import annotations

import os
from datetime import datetime
from types import SimpleNamespace
from urllib.parse import unquote

import lxml.html
import pytest

from itcj2.apps.titulatec.models import Document, ProcessEvent, ProcessPhase
from itcj2.apps.titulatec.services.anexo_service import AnexoService
from itcj2.apps.titulatec.services.document_service import DocumentService
from itcj2.apps.titulatec.services.phase_service import PhaseService
from itcj2.apps.titulatec.services.review_presence import ReviewPresence

URL = "/titulatec/admin/titulacion"
ANX = URL + "/anexo"
PAGE_PERM = "titulatec.titulacion.page.list"
REVIEW_PERM = "titulatec.anexo_iii.api.review"
ROLE = f"tt_test_anexo_rutas_{os.getpid()}"
ROLE_SOLO_PAGINA = f"tt_test_anexo_pagina_{os.getpid()}"
TIPO = "anexo_iii"
PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
       b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
       b"trailer<</Root 1 0 R>>\n%%EOF\n")


@pytest.fixture(autouse=True)
def presencia(monkeypatch):
    marcas = {}

    def touch(kind, pid, uid, name):
        marcas.setdefault((kind, pid), {})[uid] = name

    monkeypatch.setattr(ReviewPresence, "touch", staticmethod(touch))
    monkeypatch.setattr(ReviewPresence, "clear", staticmethod(lambda *a: None))
    monkeypatch.setattr(ReviewPresence, "viewers", staticmethod(lambda *a, **k: {}))
    return marcas


@pytest.fixture()
def corte(monkeypatch):
    def _fijar(fase):
        monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: fase))
    return _fijar


@pytest.fixture()
def esc(db_session, corte, make_anexo_case, seed_document_types, make_user, make_role,
        make_position, bind_position_role, link_programs, assign_position, tmp_path,
        monkeypatch, client_as):
    corte(9)
    monkeypatch.setattr("itcj2.apps.titulatec.utils.storage._base", lambda: tmp_path)
    seed_document_types([(TIPO, "Anexo III firmado", 6)])

    def caso(*, subido=True, modality_code="integral_residencias"):
        c = make_anexo_case(modality_code=modality_code)
        anexo = AnexoService.ensure_folio(db_session, c.process, c.coordinator.id)
        # Fase 6 v2: sin «listo» el alumno no sube el escaneo.
        anexo.ready_at = datetime(2026, 3, 20, 9, 0)
        anexo.pickup_note = "Oficina de vinculación, lunes 9 a 13"
        db_session.flush()
        if subido:
            DocumentService.save(db_session, c.process, TIPO, raw=PDF,
                                 original_name="anexo.pdf", content_type="application/pdf",
                                 uploaded_by_id=c.student.id)
        db_session.commit()
        return c

    def revisor(*cs, perms=(PAGE_PERM, REVIEW_PERM), rol=ROLE):
        user = make_user(first_name="TERE", last_name="TITULACION")
        pos = make_position(title="Titulacion anexo rutas")
        bind_position_role(pos, make_role(rol, perms))
        link_programs(pos, [c.process.program_id for c in cs])
        assign_position(user, pos)
        db_session.commit()
        return user

    return SimpleNamespace(caso=caso, revisor=revisor, client_as=client_as)


def _html(resp):
    return lxml.html.fromstring(resp.text)


def _hdr(resp, name):
    return unquote(resp.headers.get(name, ""))


def _fase(db, c):
    db.expire_all()
    return (db.query(ProcessPhase)
            .filter_by(process_id=c.process.id, phase_number=c.anexo_phase).one())


def _doc(db, c):
    db.expire_all()
    return db.query(Document).filter_by(process_id=c.process.id, type_code=TIPO).one()


def _post(cli, c, accion, doc_version, **extra):
    data = {"tab": "pending", "version": str(doc_version), **extra}
    return cli.post(f"{ANX}/{c.process.id}/{accion}", data=data)


def _espiar_commit_y_render(monkeypatch, db_session):
    """Revision final, punto 9: la ruta hace `commit` (suelta el bloqueo del
    proceso) ANTES de pintar con WeasyPrint. Registra el orden y sustituye el
    render por uno que no toca nada."""
    eventos = []
    real_commit = db_session.commit

    def commit():
        eventos.append("commit")
        return real_commit()

    def render(ctx):
        eventos.append("render")
        assert ctx["folio"].startswith("AIII-")
        return b"%PDF-espia"

    monkeypatch.setattr(db_session, "commit", commit)
    monkeypatch.setattr(AnexoService, "render", staticmethod(render))
    return eventos


def _pinto_despues_del_commit(eventos, resp):
    assert resp.status_code == 200, resp.text[:300]
    assert resp.content == b"%PDF-espia"
    assert eventos[-1] == "render" and eventos.count("render") == 1
    assert "commit" in eventos[:-1], eventos


# ---------------------------------------------------------------------------
def test_la_pagina_ofrece_las_dos_vistas_y_la_bandeja_lista_el_caso(esc):
    c = esc.caso()
    cli = esc.client_as(esc.revisor(c))

    pagina = cli.get(URL)
    assert pagina.status_code == 200, pagina.text[:400]
    assert _html(pagina).xpath('//a[@id="tt-tit-view-anexo"]')

    resp = cli.get(ANX, params={"selected": c.process.id})
    assert resp.status_code == 200, resp.text[:400]
    doc = _html(resp)
    assert doc.xpath('//*[@id="tt-anx-row-%d"]' % c.process.id)
    assert doc.xpath('//*[@id="tt-anx-detail"]')
    firmas = [" ".join(li.text_content().split())
              for li in doc.xpath('//li[@data-tt-anx-signer]')]
    assert firmas == ["Jefe(a) del departamento académico", "Presidente"]
    assert doc.xpath('//*[@id="tt-anx-viewer"]')
    assert doc.xpath('//a[@id="tt-tit-view-format_b"]')   # la liga de vuelta
    assert doc.xpath('//*[@id="tt-anx-approve"]') and doc.xpath('//*[@id="tt-anx-observe"]')


def test_el_item_del_menu_sigue_activo_en_la_vista_anexo(esc):
    c = esc.caso()
    resp = esc.client_as(esc.revisor(c)).get(ANX)
    activo = _html(resp).xpath('//aside[@id="ttSide"]//a[contains(@class,"active")]')
    # El `active` del menú lo pone el servidor por prefijo de URL (y shell.js en el cliente).
    assert [" ".join(a.text_content().split()) for a in activo] == ["Titulación"]


def test_corte_3_no_hay_vista_ni_acciones(esc, corte, db_session):
    c = esc.caso()
    cli = esc.client_as(esc.revisor(c))
    corte(3)

    pagina = cli.get(URL)
    assert pagina.status_code == 200
    assert not _html(pagina).xpath('//*[@id="tt-tit-view-anexo"]')

    cuerpo = cli.get(ANX + "/body")
    assert cuerpo.status_code == 200
    assert _html(cuerpo).xpath('//*[@id="tt-anx-handoff"]')
    assert not _html(cuerpo).xpath('//*[@id="tt-anx-row-%d"]' % c.process.id)

    assert _post(cli, c, "aprobar", 1).status_code == 400
    assert _post(cli, c, "observar", 1, reason="x").status_code == 400
    assert cli.get(f"{ANX}/{c.process.id}/escaneo").status_code == 404
    assert cli.get(f"{ANX}/{c.process.id}/anexo.pdf").status_code == 404
    assert _fase(db_session, c).status == "in_review"


def test_sin_permiso_de_revision_403(esc):
    c = esc.caso()
    cli = esc.client_as(esc.revisor(c, perms=(PAGE_PERM,), rol=ROLE_SOLO_PAGINA))
    pagina = cli.get(URL)
    assert pagina.status_code == 200
    assert not _html(pagina).xpath('//*[@id="tt-tit-view-anexo"]')
    assert cli.get(ANX + "/body").status_code == 403
    assert _post(cli, c, "aprobar", 1).status_code == 403
    assert _post(cli, c, "observar", 1, reason="x").status_code == 403
    assert cli.get(f"{ANX}/{c.process.id}/escaneo").status_code == 403


def test_fuera_de_alcance_404(esc, db_session):
    mio = esc.caso()
    ajeno = esc.caso()
    cli = esc.client_as(esc.revisor(mio))
    assert _post(cli, ajeno, "aprobar", 1).status_code == 404
    assert _post(cli, ajeno, "observar", 1, reason="x").status_code == 404
    assert cli.post(f"{ANX}/{ajeno.process.id}/viendo").status_code == 404
    assert cli.get(f"{ANX}/{ajeno.process.id}/escaneo").status_code == 404
    assert cli.get(f"{ANX}/{ajeno.process.id}/anexo.pdf").status_code == 404
    assert _fase(db_session, ajeno).status == "in_review"


def test_aprobar_pasa_a_la_fase_siguiente_y_ofrece_el_siguiente(esc, db_session):
    uno = esc.caso()
    dos = esc.caso()
    cli = esc.client_as(esc.revisor(uno, dos))
    v = _doc(db_session, uno).version

    resp = _post(cli, uno, "aprobar", v)

    assert resp.status_code == 200, resp.text[:400]
    assert "aprobado" in _hdr(resp, "X-Tt-Notice").lower()
    assert resp.headers["X-Tt-Notice-Kind"] == "success"
    assert _fase(db_session, uno).status == "approved"
    assert _doc(db_session, uno).review_status == "approved"
    db_session.expire_all()
    assert uno.process.current_phase > uno.anexo_phase
    assert _html(resp).xpath('//*[@id="tt-anx-detail"][@data-process="%d"]' % dos.process.id)


def test_observar_sin_motivo_repinta_con_el_error_y_no_escribe(esc, db_session):
    c = esc.caso()
    cli = esc.client_as(esc.revisor(c))
    v = _doc(db_session, c).version

    resp = _post(cli, c, "observar", v, reason="   ", selected=str(c.process.id))

    assert resp.status_code == 200
    assert _html(resp).xpath('//*[@id="tt-anx-error"]')
    assert "X-Tt-Notice" not in resp.headers
    assert _fase(db_session, c).status == "in_review"
    assert _doc(db_session, c).review_status == "pending"


def test_observar_con_motivo(esc, db_session):
    c = esc.caso()
    cli = esc.client_as(esc.revisor(c))
    v = _doc(db_session, c).version

    resp = _post(cli, c, "observar", v, reason="Falta la firma del Presidente")

    assert resp.status_code == 200, resp.text[:400]
    assert _hdr(resp, "X-Tt-Notice")
    assert _fase(db_session, c).status == "rejected"
    doc = _doc(db_session, c)
    assert doc.review_status == "rejected" and doc.review_note == "Falta la firma del Presidente"


@pytest.mark.parametrize("accion,extra", [("aprobar", {}), ("observar", {"reason": "motivo"})])
def test_version_vieja_avisa_y_no_escribe(esc, db_session, accion, extra):
    c = esc.caso()
    cli = esc.client_as(esc.revisor(c))
    v = _doc(db_session, c).version

    resp = _post(cli, c, accion, v - 1, **extra)

    assert resp.status_code == 200, resp.text[:400]
    assert resp.headers["X-Tt-Notice-Kind"] == "warning"
    assert "otro escaneo" in _hdr(resp, "X-Tt-Notice")
    assert _fase(db_session, c).status == "in_review"
    assert _doc(db_session, c).review_status == "pending"


def test_dictamen_sin_version_tambien_avisa(esc, db_session):
    c = esc.caso()
    cli = esc.client_as(esc.revisor(c))
    resp = cli.post(f"{ANX}/{c.process.id}/aprobar", data={"tab": "pending"})
    assert resp.status_code == 200
    assert resp.headers["X-Tt-Notice-Kind"] == "warning"
    # Mensaje propio del caso mal formado (no «el alumno subió otro escaneo»).
    assert "No se pudo confirmar" in _hdr(resp, "X-Tt-Notice")
    assert "otro escaneo" not in _hdr(resp, "X-Tt-Notice")
    assert _fase(db_session, c).status == "in_review"
    ilegible = cli.post(f"{ANX}/{c.process.id}/observar",
                        data={"tab": "pending", "version": "abc", "reason": "x"})
    assert "No se pudo confirmar" in _hdr(ilegible, "X-Tt-Notice")
    assert _fase(db_session, c).status == "in_review"


def test_sin_escaneo_no_se_puede_dictaminar(esc):
    c = esc.caso(subido=False)
    cli = esc.client_as(esc.revisor(c))
    resp = _post(cli, c, "aprobar", 1)
    assert resp.status_code == 400
    assert _hdr(resp, "X-Tt-Error")


def test_escaneo_y_anexo_generado(esc):
    c = esc.caso()
    cli = esc.client_as(esc.revisor(c))

    escaneo = cli.get(f"{ANX}/{c.process.id}/escaneo")
    assert escaneo.status_code == 200
    assert escaneo.headers["content-type"].startswith("application/pdf")
    assert escaneo.headers["x-content-type-options"] == "nosniff"
    assert escaneo.headers["content-disposition"].startswith("inline")

    pdf = cli.get(f"{ANX}/{c.process.id}/anexo.pdf")
    assert pdf.status_code == 200, pdf.text[:300]
    assert pdf.content.startswith(b"%PDF")


def test_anexo_generado_se_pinta_despues_del_commit(esc, db_session, monkeypatch):
    c = esc.caso()
    cli = esc.client_as(esc.revisor(c))
    eventos = _espiar_commit_y_render(monkeypatch, db_session)
    _pinto_despues_del_commit(eventos, cli.get(f"{ANX}/{c.process.id}/anexo.pdf"))


def test_escaneo_inexistente_404(esc):
    c = esc.caso(subido=False)
    cli = esc.client_as(esc.revisor(c))
    assert cli.get(f"{ANX}/{c.process.id}/escaneo").status_code == 404


def test_latido_de_presencia(esc, presencia):
    c = esc.caso()
    cli = esc.client_as(esc.revisor(c))
    assert cli.post(f"{ANX}/{c.process.id}/viendo").status_code == 204
    assert ("anexo_iii", c.process.id) in presencia


def test_latido_con_corte_3_no_marca_presencia(esc, corte, presencia):
    c = esc.caso()
    cli = esc.client_as(esc.revisor(c))
    corte(3)
    assert cli.post(f"{ANX}/{c.process.id}/viendo").status_code == 204
    assert ("anexo_iii", c.process.id) not in presencia


def test_escaneo_con_ruta_fuera_de_la_raiz_404(esc, db_session):
    c = esc.caso()
    cli = esc.client_as(esc.revisor(c))
    doc = _doc(db_session, c)
    doc.file_path = "../../etc/passwd"
    db_session.commit()
    assert cli.get(f"{ANX}/{c.process.id}/escaneo").status_code == 404


def test_el_boton_observar_exige_el_motivo_antes_del_confirm():
    from pathlib import Path
    import itcj2.apps.titulatec as pkg

    js = (Path(pkg.__file__).resolve().parent / "static" / "js" / "admin" / "titulacion.js")
    texto = js.read_text(encoding="utf-8")
    assert "#tt-anx-observe" in texto and "tt-anx-reason" in texto


# ---------------------------------------------------------------------------
# Revision final, punto 1: fechas del detalle (enviado y dictamen)
# ---------------------------------------------------------------------------
def _fechar(db, c, event_type, *cuando, phase_number=None):
    """Fija `created_at` de los eventos `event_type` del proceso, en orden de id
    (en el arnes todo `NOW()` es la misma hora de la transaccion)."""
    q = db.query(ProcessEvent).filter_by(process_id=c.process.id, event_type=event_type)
    if phase_number is not None:
        q = q.filter_by(phase_number=phase_number)
    eventos = q.order_by(ProcessEvent.id).all()
    assert len(eventos) == len(cuando), [e.id for e in eventos]
    for ev, t in zip(eventos, cuando):
        ev.created_at = t
    db.commit()


def _texto(resp):
    assert resp.status_code == 200, resp.text[:400]
    return " ".join(_html(resp).text_content().split())


def _resubir(db, c):
    # Fase 6 v2: solo se sube en «Por recoger»/«Observado»; la fase en curso
    # deja pasar la guarda y `sync_phase` la vuelve a «Por revisar».
    _fase(db, c).status = "in_progress"
    db.flush()
    DocumentService.save(db, c.process, TIPO, raw=PDF, original_name="anexo-v2.pdf",
                         content_type="application/pdf", uploaded_by_id=c.student.id)
    db.commit()


def test_observado_fecha_la_ultima_subida_y_la_observacion(esc, db_session):
    c = esc.caso()
    _resubir(db_session, c)
    _fechar(db_session, c, "document_uploaded",
            datetime(2026, 10, 1, 9, 15), datetime(2026, 10, 2, 16, 40))
    rev = esc.revisor(c)
    AnexoService.observe(db_session, c.process, rev.id, reason="Falta una firma")
    db_session.commit()
    _fechar(db_session, c, "phase_rejected", datetime(2026, 10, 3, 11, 5),
            phase_number=c.anexo_phase)

    texto = _texto(esc.client_as(rev).get(
        ANX + "/body", params={"tab": "observed", "selected": c.process.id}))
    assert "Escaneo subido el 2 de octubre a las 16:40 (versión 2)" in texto
    assert "Observado el 3 de octubre a las 11:05" in texto


def test_aprobado_fecha_la_aprobacion_de_la_fase(esc, db_session):
    c = esc.caso()
    _resubir(db_session, c)
    _fechar(db_session, c, "document_uploaded",
            datetime(2026, 10, 1, 9, 15), datetime(2026, 10, 2, 16, 40))
    rev = esc.revisor(c)
    AnexoService.approve(db_session, c.process, rev.id)
    db_session.commit()
    fase = _fase(db_session, c)
    fase.completed_at = datetime(2026, 10, 4, 13, 20)
    db_session.commit()

    texto = _texto(esc.client_as(rev).get(
        ANX + "/body", params={"tab": "approved", "selected": c.process.id}))
    assert "Escaneo subido el 2 de octubre a las 16:40 (versión 2)" in texto
    assert "Aprobado el 4 de octubre a las 13:20" in texto


def test_la_lista_fecha_la_subida_con_la_misma_fuente(esc, db_session):
    c = esc.caso()
    _resubir(db_session, c)
    _fechar(db_session, c, "document_uploaded",
            datetime(2026, 10, 1, 9, 15), datetime(2026, 10, 2, 16, 40))
    resp = esc.client_as(esc.revisor(c)).get(ANX + "/body", params={"tab": "pending"})
    (pill,) = _html(resp).xpath('//*[@id="tt-anx-row-%d"]//*[contains(@class,"tt-tit-wait")]'
                                % c.process.id)
    assert "subido el 2 de octubre a las 16:40" in pill.get("title")


# ---------------------------------------------------------------------------
# Revision final, punto 11: tras una resubida se ve lo que se pidio antes
# ---------------------------------------------------------------------------
def test_resubido_muestra_la_observacion_anterior(esc, db_session):
    c = esc.caso()
    rev = esc.revisor(c)
    AnexoService.observe(db_session, c.process, rev.id, reason="Falta la firma del vocal")
    db_session.commit()
    _resubir(db_session, c)
    assert _doc(db_session, c).version == 2 and _fase(db_session, c).status == "in_review"

    resp = esc.client_as(rev).get(ANX + "/body",
                                  params={"tab": "pending", "selected": c.process.id})
    assert resp.status_code == 200, resp.text[:400]
    (nota,) = _html(resp).xpath('//*[@id="tt-anx-prevobs"]')
    texto = " ".join(nota.text_content().split())
    assert "Observación anterior" in texto and "Falta la firma del vocal" in texto


def test_primera_entrega_y_observado_vigente_sin_observacion_anterior(esc, db_session):
    c = esc.caso()
    rev = esc.revisor(c)
    cli = esc.client_as(rev)
    primera = cli.get(ANX + "/body", params={"tab": "pending", "selected": c.process.id})
    assert not _html(primera).xpath('//*[@id="tt-anx-prevobs"]')

    AnexoService.observe(db_session, c.process, rev.id, reason="Falta la firma del vocal")
    db_session.commit()
    observado = cli.get(ANX + "/body", params={"tab": "observed", "selected": c.process.id})
    # El motivo vigente ya se pinta en el escaneo: no se repite como «anterior».
    assert not _html(observado).xpath('//*[@id="tt-anx-prevobs"]')
    assert _html(observado).xpath('//*[@id="tt-anx-prevnote"]')


# ---------------------------------------------------------------------------
# Revision final, punto 13: UNA funcion arma el nombre en Titulacion
# ---------------------------------------------------------------------------
def test_un_solo_armado_del_nombre_del_alumno():
    import inspect
    from itcj2.apps.titulatec.pages import _titulacion_shared, titulacion_anexo

    persona = SimpleNamespace(first_name="ANA", last_name="PEREZ", middle_name="GOMEZ")
    assert _titulacion_shared.nombre(persona) == "ANA PEREZ GOMEZ"   # orden natural
    assert _titulacion_shared.nombre(None) == ""
    # Nadie más lo arma a mano: el detalle del Anexo III y los avisos a vinculación (liberación y reimpresión).
    for fn in (titulacion_anexo._detail_ctx, AnexoService._notify_vinculacion):
        fuente = inspect.getsource(fn)
        assert "middle_name" not in fuente, fn.__qualname__
        assert "nombre(" in fuente, fn.__qualname__


def test_el_detalle_usa_el_nombre_compartido(esc, db_session):
    from itcj2.apps.titulatec.pages._titulacion_shared import nombre
    c = esc.caso()
    c.student.middle_name = "MATERNO"
    db_session.commit()
    resp = esc.client_as(esc.revisor(c)).get(
        ANX + "/body", params={"tab": "pending", "selected": c.process.id})
    (h2,) = _html(resp).xpath('//*[@id="tt-anx-detail"]//h2')
    assert " ".join(h2.text_content().split()) == nombre(c.student)
    assert nombre(c.student).endswith("MATERNO")


# ---------------------------------------------------------------------------
# Revision final, punto 4: el kicker de la pagina sale del catalogo
# ---------------------------------------------------------------------------
def _kicker(resp):
    assert resp.status_code == 200, resp.text[:400]
    (k,) = _html(resp).xpath('//header[contains(@class,"tt-tit-header")]'
                             '/span[contains(@class,"tt-kicker")]')
    return " ".join(k.text_content().split())


def test_el_kicker_de_cada_vista_es_su_fase_del_catalogo(esc, db_session):
    from pathlib import Path
    import itcj2.apps.titulatec as pkg

    c = esc.caso()
    cli = esc.client_as(esc.revisor(c))
    n3 = PhaseService.phase_number_for_code(db_session, "format_b")
    assert _kicker(cli.get(URL)) == f"Fase {n3:02d} · Departamento de Titulación"
    assert _kicker(cli.get(ANX)) == f"Fase {c.anexo_phase:02d} · Departamento de Titulación"
    plantilla = (Path(pkg.__file__).resolve().parent / "templates" / "titulatec" / "admin"
                 / "titulacion.html").read_text(encoding="utf-8")
    assert "Fase 03" not in plantilla


# ---------------------------------------------------------------------------
# Fase 6 v2: etapa en «Sin enviar», casilla de reimpresión, detalle
# ---------------------------------------------------------------------------
AYUDA = ("Úsala si el problema está en el documento impreso: datos, firma del jefe o sello. "
         "Si solo falta una firma de sinodal o el escaneo no se lee, déjala sin marcar.")


def test_sin_enviar_pinta_la_pildora_de_etapa(esc):
    c = esc.caso(subido=False)
    cli = esc.client_as(esc.revisor(c))
    h = _html(cli.get(ANX + "/body", params={"tab": "unsent"}))
    pil = h.xpath(f'//*[@id="tt-anx-row-{c.process.id}"]//*[@data-tt-anx-stage]')
    assert [p.get("data-tt-anx-stage") for p in pil] == ["ready"]
    assert "Por recoger" in pil[0].text_content()
    assert "desde" in h.xpath(f'//*[@id="tt-anx-row-{c.process.id}"]')[0].text_content()


def test_el_detalle_ofrece_la_casilla_desmarcada_con_su_ayuda(esc):
    c = esc.caso()
    cli = esc.client_as(esc.revisor(c))
    h = _html(cli.get(ANX + "/body", params={"selected": c.process.id}))
    chk = h.xpath('//input[@id="tt-anx-reprint-chk"]')
    assert len(chk) == 1 and chk[0].get("name") == "reimpresion" and chk[0].get("checked") is None
    assert "Requiere reimpresión (regresa a vinculación)" in h.text_content()
    assert " ".join(h.xpath('//*[@id="tt-anx-reprint-help"]')[0].text_content().split()) == AYUDA
    assert "Oficina de vinculación, lunes 9 a 13" in h.xpath('//*[@id="tt-anx-pickup"]')[0].text_content()


def test_observar_con_reimpresion_regresa_a_vinculacion(esc, db_session, monkeypatch):
    avisos = []
    monkeypatch.setattr(AnexoService, "notify_reprint", staticmethod(avisos.append))
    c = esc.caso()
    cli = esc.client_as(esc.revisor(c))
    resp = _post(cli, c, "observar", 1, reason="El sello salió ilegible", reimpresion="1")
    assert resp.status_code == 200, resp.text[:300]
    assert avisos == [c.process.id]
    db_session.expire_all()
    assert AnexoService.stage(db_session, c.process) == "reprint"
    assert AnexoService.get(db_session, c.process.id).reprint_reason == "El sello salió ilegible"
    assert _fase(db_session, c).status == "rejected"


def test_observar_sin_casilla_no_pide_reimpresion(esc, db_session, monkeypatch):
    avisos = []
    monkeypatch.setattr(AnexoService, "notify_reprint", staticmethod(avisos.append))
    c = esc.caso()
    cli = esc.client_as(esc.revisor(c))
    assert _post(cli, c, "observar", 1, reason="No se lee").status_code == 200
    assert avisos == []
    db_session.expire_all()
    assert AnexoService.stage(db_session, c.process) == "observed"


def test_falla_del_aviso_de_reimpresion_no_tumba_la_observacion(esc, db_session, monkeypatch):
    def boom(pid):
        raise RuntimeError("redis caido")
    monkeypatch.setattr(AnexoService, "notify_reprint", staticmethod(boom))
    c = esc.caso()
    cli = esc.client_as(esc.revisor(c))
    assert _post(cli, c, "observar", 1, reason="Falta sello", reimpresion="1").status_code == 200
    db_session.expire_all()
    assert AnexoService.stage(db_session, c.process) == "reprint"


def test_motivo_vacio_conserva_la_casilla_marcada(esc):
    c = esc.caso()
    cli = esc.client_as(esc.revisor(c))
    resp = _post(cli, c, "observar", 1, reason="  ", reimpresion="1")
    assert resp.status_code == 200
    chk = _html(resp).xpath('//input[@id="tt-anx-reprint-chk"]')
    assert chk and chk[0].get("checked") is not None


def test_observar_con_reimpresion_y_version_vieja_no_escribe(esc, db_session, monkeypatch):
    avisos = []
    monkeypatch.setattr(AnexoService, "notify_reprint", staticmethod(avisos.append))
    c = esc.caso()
    cli = esc.client_as(esc.revisor(c))
    resp = _post(cli, c, "observar", 99, reason="x", reimpresion="1")
    assert resp.status_code == 200 and avisos == []
    db_session.expire_all()
    assert AnexoService.stage(db_session, c.process) == "in_review"


def test_detalle_en_reimpresion_muestra_etapa_y_motivo(esc):
    c = esc.caso()
    cli = esc.client_as(esc.revisor(c))
    _post(cli, c, "observar", 1, reason="Datos del alumno mal impresos", reimpresion="1")
    h = _html(cli.get(ANX + "/body", params={"tab": "observed", "selected": c.process.id}))
    assert h.xpath('//*[@id="tt-anx-stage"]//*[@data-tt-anx-stage="reprint"]')
    assert "Datos del alumno mal impresos" in h.xpath('//*[@id="tt-anx-reprint"]')[0].text_content()
    assert not h.xpath('//*[@id="tt-anx-review"]')   # sin escaneo vigente no se dictamina


def test_corte_3_no_alcanza_la_reimpresion(esc, corte, db_session):
    c = esc.caso()
    cli = esc.client_as(esc.revisor(c))
    corte(3)
    resp = _post(cli, c, "observar", 1, reason="x", reimpresion="1")
    assert resp.status_code == 400
    db_session.expire_all()
    assert AnexoService.get(db_session, c.process.id).reprint_requested_at is None
