"""Fase 6, tarea 6: Departamento -- pestana «En Anexo III», PDF desde Sinodales
y aviso de liberacion a vinculacion (spec fase 6 §4 D2/D7, §5 C5, §9.3, §10).

Corte explicito en cada prueba: `corte(9)` opera la fase 6; `corte(6)` la deja
inerte (la pestana de Sinodales sigue viva, la fase 4 se opera).
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import lxml.html
import pytest

from itcj2.apps.titulatec.models import Anexo
from itcj2.apps.titulatec.services import email_helper
from itcj2.apps.titulatec.services.anexo_service import AnexoService
from itcj2.apps.titulatec.services.phase_service import PhaseService

URL = "/titulatec/admin/sinodales"
BODY = URL + "/body"
PAGE_PERM = "titulatec.synodal.page.list"
READ_PERM = "titulatec.synodal.api.read"
GEN_PERM = "titulatec.anexo_iii.api.generate"
PERMS = (PAGE_PERM, READ_PERM, GEN_PERM)
ROLE = f"tt_test_sin_anexo_{os.getpid()}"
ROLE_DOCENTE = f"tt_test_sin_anexo_doc_{os.getpid()}"
VOTE_PERMS = ("titulatec.synodal.page.my_reviews", "titulatec.chat.api.read",
              "titulatec.chat.api.send", "titulatec.chat.api.upload",
              "titulatec.synodal.api.vote")
PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
       b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")


@pytest.fixture()
def corte(monkeypatch, seed_phase_defs):
    seed_phase_defs()

    def _fijar(fase):
        monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: fase))
    _fijar(9)
    return _fijar


@pytest.fixture(autouse=True)
def entorno(monkeypatch, tmp_path):
    from itcj2.apps.titulatec.utils import storage
    monkeypatch.setattr(storage, "_base", lambda: tmp_path)
    monkeypatch.setattr(email_helper, "deliver_detailed", lambda **kw: (True, None))


@pytest.fixture()
def esc(db_session, corte, make_anexo_case, make_role, grant_user_role, client_as):
    def caso(**kw):
        c = make_anexo_case(**kw)
        rol = make_role(ROLE, PERMS)
        grant_user_role(c.head, rol)
        grant_user_role(c.coordinator, rol)
        db_session.commit()
        return c
    return SimpleNamespace(caso=caso, client_as=client_as)


def _html(resp):
    return lxml.html.fromstring(resp.text)


def _filas(resp):
    return [int(n.get("data-process"))
            for n in _html(resp).xpath('//*[@id="tt-sin-list"]//*[@data-process]')]


def _avisos(db, user, tipo="ANEXO_READY"):
    from itcj2.core.models.notification import Notification
    db.expire_all()
    return (db.query(Notification)
            .filter_by(user_id=user.id, app_name="titulatec", type=tipo).all())


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
# Pestana
# ---------------------------------------------------------------------------
def test_la_pestana_lista_los_procesos_en_fase_6_y_los_cuenta(esc):
    c = esc.caso()
    cli = esc.client_as(c.head)

    resp = cli.get(BODY, params={"tab": "anexo"})
    assert resp.status_code == 200, resp.text[:400]
    assert c.process.id in _filas(resp)
    (boton,) = _html(resp).xpath('//*[@id="tt-sin-tab-anexo"]')
    assert "En Anexo III" in boton.text_content()
    assert c.process.id not in _filas(cli.get(BODY, params={"tab": "pending"}))
    assert c.process.id not in _filas(cli.get(BODY, params={"tab": "assigned"}))


def test_el_detalle_ofrece_el_pdf_del_anexo(esc, db_session):
    """UI ronda 2 (V4): mientras el panel muestra el paso 1 «Imprimir Anexo III»
    (en preparación, reimpresión o por recoger) el PDF sale de ahí y «Descargar
    Anexo III» no se repite con otra etiqueta; en Titulación (solo lectura) la
    liga vuelve a «Sinodales vigentes»."""
    c = esc.caso()
    cli = esc.client_as(c.head)
    pdf = f"{URL}/{c.process.id}/anexo.pdf"
    h = _html(cli.get(BODY, params={"tab": "anexo", "selected": c.process.id}))
    assert [a.get("href") for a in h.xpath('//a[@id="tt-sin-anexo-print"]')] == [pdf]
    assert not h.xpath('//a[@id="tt-sin-anexo"]')
    _fase(db_session, c, "in_review")
    h = _html(cli.get(BODY, params={"tab": "anexo", "etapa": "titulacion",
                                    "selected": c.process.id}))
    assert [a.get("href") for a in h.xpath('//a[@id="tt-sin-anexo"]')] == [pdf]
    assert not h.xpath('//a[@id="tt-sin-anexo-print"]')


def test_corte_6_sin_pestana_y_sin_filas(esc, corte):
    c = esc.caso()
    cli = esc.client_as(c.head)
    corte(6)
    resp = cli.get(BODY, params={"tab": "anexo"})
    assert resp.status_code == 200
    assert not _html(resp).xpath('//*[@id="tt-sin-tab-anexo"]')
    assert c.process.id not in _filas(resp)
    assert not _html(resp).xpath('//a[@id="tt-sin-anexo"]')


def test_en_anexo_iii_es_fifo_por_inicio_de_la_fase_6_con_semaforo(esc, db_session,
                                                                  monkeypatch):
    """Revision final, punto 8: «En Anexo III» ordena por `started_at` de la
    fase 6 (mas antiguo primero) y trae el nivel de espera en dias habiles con
    el calendario de dias inhabiles, como «Por asignar»."""
    from datetime import date, datetime

    from itcj2.apps.titulatec.models import ProcessPhase, ProgramDepartment
    from itcj2.apps.titulatec.services import synodal_inbox_service as mod
    from itcj2.apps.titulatec.services.non_working_day_service import NonWorkingDayService
    from itcj2.apps.titulatec.utils.business_days import business_days_between

    a = esc.caso()
    b = esc.caso()
    db_session.get(ProgramDepartment, b.process.program_id).department_id = a.department.id

    def fase(c, n):
        return (db_session.query(ProcessPhase)
                .filter_by(process_id=c.process.id, phase_number=n).one())

    n4 = PhaseService.phase_number_for_code(db_session, "synodal_assignment")
    # Orden viejo (fin de la fase 4, el mas reciente primero) daria [a, b].
    fase(a, n4).completed_at = datetime(2026, 10, 1, 9, 0)
    fase(b, n4).completed_at = datetime(2026, 9, 1, 9, 0)
    fase(a, a.anexo_phase).started_at = datetime(2026, 10, 5, 9, 0)
    fase(b, b.anexo_phase).started_at = datetime(2026, 9, 28, 9, 0)    # el mas antiguo
    db_session.commit()

    feriados = frozenset({date(2026, 10, 6)})
    monkeypatch.setattr(mod, "db_now", lambda: datetime(2026, 10, 9, 12, 0))
    monkeypatch.setattr(NonWorkingDayService, "holidays", staticmethod(lambda db: feriados))

    datos = mod.SynodalInboxService.list(db_session, a.head.id, tab="anexo")
    filas = [r for r in datos["rows"] if r["process_id"] in (a.process.id, b.process.id)]
    assert [r["process_id"] for r in filas] == [b.process.id, a.process.id]
    for r, inicio in zip(filas, (date(2026, 9, 28), date(2026, 10, 5))):
        dias = business_days_between(inicio, date(2026, 10, 9), holidays=feriados)
        assert dias != business_days_between(inicio, date(2026, 10, 9), holidays=frozenset())
        assert r["waited_days"] == dias
        assert r["wait_level"] == mod.SynodalInboxService._wait_level(dias)

    # La pestana pinta el semaforo.
    resp = esc.client_as(a.head).get(BODY, params={"tab": "anexo"})
    assert _html(resp).xpath('//*[@id="tt-sin-row-%d"]//*[contains(@class,"tt-sin-wait")]'
                             % b.process.id)


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def test_pdf_desde_sinodales_mismo_folio_en_cada_descarga(esc, db_session):
    c = esc.caso()
    cli = esc.client_as(c.head)

    resp = cli.get(f"{URL}/{c.process.id}/anexo.pdf")
    assert resp.status_code == 200, resp.text[:300]
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")
    db_session.expire_all()
    primero = db_session.query(Anexo).filter_by(process_id=c.process.id).one().folio

    assert cli.get(f"{URL}/{c.process.id}/anexo.pdf").status_code == 200
    db_session.expire_all()
    assert db_session.query(Anexo).filter_by(process_id=c.process.id).one().folio == primero


def test_pdf_desde_sinodales_se_pinta_despues_del_commit(esc, db_session, monkeypatch):
    c = esc.caso()
    eventos = _espiar_commit_y_render(monkeypatch, db_session)
    _pinto_despues_del_commit(eventos, esc.client_as(c.head).get(f"{URL}/{c.process.id}/anexo.pdf"))
    db_session.expire_all()
    assert db_session.query(Anexo).filter_by(process_id=c.process.id).count() == 1


def test_pdf_de_otro_departamento_404(esc, db_session, make_department,
                                      make_academic_head, client_as):
    c = esc.caso()
    otro = make_department(name="Otro depto anexo sinodales")
    jefe_otro = make_academic_head(otro, kind="head", perms=PERMS)
    db_session.commit()

    assert esc.client_as(c.head).get(f"{URL}/{c.process.id}/anexo.pdf").status_code == 200
    assert client_as(jefe_otro).get(f"{URL}/{c.process.id}/anexo.pdf").status_code == 404


def test_pdf_sin_leer_sinodales_403(esc, db_session, make_academic_head, client_as):
    c = esc.caso()
    # Misma coordinacion (alcance), pero su rol genera el Anexo sin leer sinodales.
    solo = make_academic_head(c.department, kind="coord", perms=(PAGE_PERM, GEN_PERM))
    db_session.commit()

    assert esc.client_as(c.head).get(f"{URL}/{c.process.id}/anexo.pdf").status_code == 200
    assert client_as(solo).get(f"{URL}/{c.process.id}/anexo.pdf").status_code == 403


def _texto_pdf(raw: bytes) -> str:
    import io
    from pypdf import PdfReader
    return " ".join((pg.extract_text() or "") for pg in PdfReader(io.BytesIO(raw)).pages)


def test_la_vista_previa_del_alumno_no_emite_folio_y_nace_cuando_vinculacion_imprime(
        esc, db_session, make_role, patched_session_local):
    """E2: el alumno solo ve una vista previa; el folio nace cuando vinculacion
    imprime el oficial."""
    import re
    from tests.fastapi.titulatec.test_student_anexo import ANEXO_PERMS, ROLE_STUDENT

    c = esc.caso()
    make_role(ROLE_STUDENT, ANEXO_PERMS)
    db_session.commit()

    resp = esc.client_as(c.student).get("/titulatec/student/anexo/pdf")
    assert resp.status_code == 200, resp.text[:300]
    db_session.expire_all()
    assert db_session.query(Anexo).filter_by(process_id=c.process.id).count() == 0

    resp = esc.client_as(c.head).get(f"{URL}/{c.process.id}/anexo.pdf")
    assert resp.status_code == 200, resp.text[:300]
    db_session.expire_all()
    (fila,) = db_session.query(Anexo).filter_by(process_id=c.process.id).all()
    assert fila.folio in re.sub(r"\s+", "", _texto_pdf(resp.content))


def test_pdf_corte_3_es_400_y_no_numera(esc, corte, db_session):
    c = esc.caso()
    cli = esc.client_as(c.head)
    corte(3)
    resp = cli.get(f"{URL}/{c.process.id}/anexo.pdf")
    assert resp.status_code == 400 and resp.headers.get("X-Tt-Error")
    assert db_session.query(Anexo).filter_by(process_id=c.process.id).count() == 0


def test_corte_3_sin_pestana_ni_filas(esc, corte):
    c = esc.caso()
    cli = esc.client_as(c.head)
    corte(3)
    resp = cli.get(BODY, params={"tab": "anexo"})
    assert resp.status_code == 200
    assert not _html(resp).xpath('//*[@id="tt-sin-tab-anexo"]')
    assert c.process.id not in _filas(resp)


def test_pdf_corte_6_es_400(esc, corte):
    c = esc.caso()
    cli = esc.client_as(c.head)
    corte(6)
    resp = cli.get(f"{URL}/{c.process.id}/anexo.pdf")
    assert resp.status_code == 400
    assert resp.headers.get("X-Tt-Error")


# ---------------------------------------------------------------------------
# Aviso de liberacion
# ---------------------------------------------------------------------------
@pytest.fixture()
def liberacion(db_session, corte, make_review_case, make_role, grant_user_role,
               make_academic_head, client_as):
    from itcj2.apps.titulatec.models import ProgramDepartment
    from itcj2.apps.titulatec.services.review_service import ReviewService
    from itcj2.core.models.department import Department
    from itcj2.core.models.position import Position, UserPosition
    from itcj2.core.models.user import User

    def _build(*, con_coord=True):
        c = make_review_case(versions=0)
        rol = make_role(ROLE_DOCENTE, VOTE_PERMS)
        for t in c.teachers.values():
            grant_user_role(t, rol)
        depto = db_session.get(Department, db_session.get(
            ProgramDepartment, c.process.program_id).department_id)
        c.coord = make_academic_head(depto, kind="coord") if con_coord else None
        c.head = (db_session.query(User).join(UserPosition, UserPosition.user_id == User.id)
                  .join(Position, Position.id == UserPosition.position_id)
                  .filter(Position.code == f"head_{depto.code}").first())
        ReviewService.upload_version(db_session, c.process, c.student.id, raw=PDF,
                                     original_name="p.pdf")
        c.pres = c.teachers["president"]
        db_session.commit()
        return c

    def _cerrar(c):
        return client_as(c.pres).post(
            f"/titulatec/admin/revisiones/{c.process.id}/voto",
            data={"verdict": "approved", "comment": "", "version": "1", "confirm": "1"})
    return SimpleNamespace(build=_build, cerrar=_cerrar)


def test_liberar_avisa_una_vez_al_coordinador(liberacion, db_session):
    c = liberacion.build()
    resp = liberacion.cerrar(c)
    assert resp.status_code == 200, resp.text[:300]

    avisos = _avisos(db_session, c.coord)
    assert len(avisos) == 1
    a = avisos[0]
    assert a.title == AnexoService.RELEASE_TITLE
    assert a.data["process_id"] == c.process.id
    assert a.data["url"] == f"/titulatec/admin/sinodales?tab=anexo&selected={c.process.id}"
    assert c.student.control_number in (a.body or "")
    assert _avisos(db_session, c.head) == []


def test_vacante_el_aviso_va_al_jefe(liberacion, db_session):
    c = liberacion.build(con_coord=False)
    assert liberacion.cerrar(c).status_code == 200
    assert len(_avisos(db_session, c.head)) == 1


def test_corte_6_no_hay_aviso(liberacion, db_session, corte):
    c = liberacion.build()
    corte(6)
    AnexoService.notify_release(c.process.id)
    assert _avisos(db_session, c.coord) == []
    corte(9)
    AnexoService.notify_release(c.process.id)
    assert len(_avisos(db_session, c.coord)) == 1


def test_corte_3_notify_release_no_escribe(liberacion, db_session, corte):
    c = liberacion.build()
    corte(3)
    AnexoService.notify_release(c.process.id)
    assert _avisos(db_session, c.coord) == [] and _avisos(db_session, c.head) == []


def test_un_fallo_del_aviso_no_rompe_el_voto(liberacion, db_session, monkeypatch):
    c = liberacion.build()

    def _boom(process_id):
        raise RuntimeError("sin redis")
    monkeypatch.setattr(AnexoService, "notify_release", staticmethod(_boom))
    resp = liberacion.cerrar(c)
    assert resp.status_code == 200
    assert resp.headers.get("X-Tt-Notice-Kind") == "success"


# ---------------------------------------------------------------------------
# Fase 6 v2 (Task 4): sub-filtros por etapa, panel de pasos y «marcar listo»
# ---------------------------------------------------------------------------
PREPARE_PERM = "titulatec.anexo_iii.api.prepare"
ROLE_PREP = f"tt_test_sin_anexo_prep_{os.getpid()}"
NOTA = "Oficina de Vinculacion, lunes a viernes de 9:00 a 14:00"

@pytest.fixture()
def prep(db_session, esc, make_role, grant_user_role):
    """Casos del mismo departamento + rol con `prepare` para el jefe del primero."""
    from itcj2.apps.titulatec.models import ProgramDepartment

    def _casos(n=1):
        cs = [esc.caso() for _ in range(n)]
        for c in cs[1:]:
            db_session.get(ProgramDepartment, c.process.program_id).department_id = cs[0].department.id
        rol = make_role(ROLE_PREP, PERMS + (PREPARE_PERM,))
        grant_user_role(cs[0].head, rol)
        db_session.commit()
        return cs
    return _casos


def _listo(db, c, nota=NOTA):
    from datetime import datetime
    a = AnexoService.ensure_folio(db, c.process, c.head.id)
    a.ready_at, a.pickup_note = datetime(2026, 10, 5, 9, 0), nota
    db.commit()


def _fase(db, c, estado):
    from itcj2.apps.titulatec.models import ProcessPhase
    (f,) = db.query(ProcessPhase).filter_by(process_id=c.process.id,
                                            phase_number=c.anexo_phase).all()
    f.status = estado
    db.commit()


def test_subfiltros_por_etapa_con_conteos_y_filas(prep, esc, db_session):
    from datetime import datetime
    pre, rec, tit, rep = prep(4)
    _listo(db_session, rec)
    _fase(db_session, tit, "in_review")
    a = AnexoService.ensure_folio(db_session, rep.process, rep.head.id)
    a.reprint_reason, a.reprint_requested_at = "Falta el sello", datetime(2026, 10, 6, 9, 0)
    db_session.commit()
    cli = esc.client_as(pre.head)

    def ver(etapa):
        return cli.get(BODY, params={"tab": "anexo", "etapa": etapa})

    assert set(_filas(cli.get(BODY, params={"tab": "anexo"}))) == {pre.process.id, rep.process.id}
    assert _filas(ver("recoger")) == [rec.process.id]
    assert _filas(ver("titulacion")) == [tit.process.id]
    h = _html(ver("preparar"))
    for k, n in (("preparar", 2), ("recoger", 1), ("titulacion", 1)):
        (b,) = h.xpath(f'//*[@id="tt-sin-etapa-{k}"]')
        assert f"({n})" in b.text_content()
    # Reimpresion: pildora de etapa y motivo visible en la fila.
    (fila,) = h.xpath(f'//*[@id="tt-sin-row-{rep.process.id}"]')
    assert "Reimpresión" in fila.text_content() and "Falta el sello" in fila.text_content()


def test_los_conteos_de_etapa_suman_el_de_la_pestana(prep, esc, db_session):
    from itcj2.apps.titulatec.services.synodal_inbox_service import SynodalInboxService
    a, b, c = prep(3)
    _listo(db_session, b)
    _fase(db_session, c, "in_review")
    datos = SynodalInboxService.list(db_session, a.head.id, tab="anexo")
    assert sum(datos["etapa_counts"].values()) == datos["counts"]["anexo"]


def test_fifo_de_recoger_es_por_ready_at(prep, esc, db_session):
    from datetime import datetime
    x, y = prep(2)
    _listo(db_session, x)
    _listo(db_session, y)
    db_session.query(Anexo).filter_by(process_id=x.process.id).one().ready_at = datetime(2026, 10, 8, 9, 0)
    db_session.query(Anexo).filter_by(process_id=y.process.id).one().ready_at = datetime(2026, 10, 1, 9, 0)
    db_session.commit()
    resp = esc.client_as(x.head).get(BODY, params={"tab": "anexo", "etapa": "recoger"})
    assert _filas(resp) == [y.process.id, x.process.id]


def test_detalle_con_pasos_y_nota_precargada(prep, esc, db_session):
    c, otro = prep(2)
    _listo(db_session, otro, "Ventanilla 3, de 10 a 12")
    resp = esc.client_as(c.head).get(BODY, params={"tab": "anexo", "selected": c.process.id})
    h = _html(resp)
    assert [li.get("id") for li in h.xpath('//*[@id="tt-sin-anexo-steps"]/li')] == [
        "tt-sin-step-1", "tt-sin-step-2", "tt-sin-step-3"]
    assert h.xpath('//a[@id="tt-sin-anexo-print"]')
    (nota,) = h.xpath('//*[@id="tt-sin-anexo-note"]')
    assert nota.text_content().strip() == "Ventanilla 3, de 10 a 12"     # la del mismo departamento
    assert h.xpath('//input[@name="expected_stage"]')[0].get("value") == "preparing"


def test_detalle_listo_dice_cambiar_lugar_y_horario(prep, esc, db_session):
    (c,) = prep(1)
    _listo(db_session, c)
    resp = esc.client_as(c.head).get(BODY, params={"tab": "anexo", "etapa": "recoger",
                                                    "selected": c.process.id})
    h = _html(resp)
    assert "Cambiar lugar u horario" in h.xpath('//*[@id="tt-sin-step-3"]')[0].text_content()
    assert NOTA in h.xpath('//*[@id="tt-sin-anexo-ready-info"]')[0].text_content()


def test_detalle_en_titulacion_es_de_solo_lectura(prep, esc, db_session):
    (c,) = prep(1)
    _fase(db_session, c, "in_review")
    resp = esc.client_as(c.head).get(BODY, params={"tab": "anexo", "etapa": "titulacion",
                                                    "selected": c.process.id})
    h = _html(resp)
    assert h.xpath('//*[@id="tt-sin-anexo-readonly"]') and not h.xpath('//form[@id="tt-sin-anexo-form"]')


def test_textos_largos_no_rompen_el_panel(prep, esc, db_session):
    from itcj2.apps.titulatec.models import FormatB
    (c,) = prep(1)
    db_session.get(FormatB, c.process.id).project_name = "P" * 230
    _listo(db_session, c, "N" * 300)
    resp = esc.client_as(c.head).get(BODY, params={"tab": "anexo", "etapa": "recoger",
                                                    "selected": c.process.id})
    assert resp.status_code == 200 and "N" * 300 in resp.text and "P" * 230 in resp.text


def test_marcar_listo_feliz(prep, esc, db_session, monkeypatch):
    (c,) = prep(1)
    avisados = []
    monkeypatch.setattr(AnexoService, "notify_ready", staticmethod(avisados.append))
    resp = esc.client_as(c.head).post(
        f"{URL}/{c.process.id}/anexo/listo",
        data={"note": f"  {NOTA} ", "tab": "anexo", "etapa": "preparar",
              "expected_stage": "preparing"})
    assert resp.status_code == 200, resp.text[:300]
    assert resp.headers.get("X-Tt-Notice") and resp.headers.get("X-Tt-Notice-Kind") == "success"
    db_session.expire_all()
    a = db_session.query(Anexo).filter_by(process_id=c.process.id).one()
    assert a.ready_at is not None and a.pickup_note == NOTA and a.folio
    assert avisados == [c.process.id]
    assert c.process.id in _filas(resp)          # abre en «Por recoger»
    assert _html(resp).xpath('//*[@id="tt-sin-etapa-recoger"][@aria-pressed="true"]')


def test_remarcar_con_la_misma_nota_dice_sin_cambios(prep, esc, db_session, monkeypatch):
    from urllib.parse import unquote
    (c,) = prep(1)
    _listo(db_session, c)
    monkeypatch.setattr(AnexoService, "notify_ready", staticmethod(lambda pid: None))
    resp = esc.client_as(c.head).post(
        f"{URL}/{c.process.id}/anexo/listo",
        data={"note": NOTA, "tab": "anexo", "etapa": "recoger", "expected_stage": "ready"})
    assert resp.status_code == 200, resp.text[:300]
    aviso = unquote(resp.headers.get("X-Tt-Notice", ""))
    assert aviso.startswith("Sin cambios") and "actualizó" not in aviso


def test_marcar_listo_con_la_etapa_cambiada_200_con_aviso(prep, esc, db_session):
    (c,) = prep(1)
    _fase(db_session, c, "in_review")                # Titulacion ya lo tiene
    resp = esc.client_as(c.head).post(
        f"{URL}/{c.process.id}/anexo/listo",
        data={"note": NOTA, "tab": "anexo", "etapa": "preparar", "expected_stage": "preparing"})
    assert resp.status_code == 200, resp.text[:300]
    assert resp.headers.get("X-Tt-Notice") and resp.headers.get("X-Tt-Notice-Kind") == "warning"
    h = _html(resp)
    assert h.xpath('//*[@id="tt-sin-anexo-panel"]')          # panel re-pintado, ya en Titulacion
    assert h.xpath('//*[@id="tt-sin-anexo-readonly"]') and not h.xpath('//form[@id="tt-sin-anexo-form"]')
    db_session.expire_all()
    a = db_session.query(Anexo).filter_by(process_id=c.process.id).first()
    assert a is None or (a.ready_at is None and a.pickup_note is None)


def test_marcar_listo_nota_vacia_200_con_error_en_el_form(prep, esc, db_session):
    (c,) = prep(1)
    resp = esc.client_as(c.head).post(
        f"{URL}/{c.process.id}/anexo/listo",
        data={"note": "   ", "tab": "anexo", "etapa": "preparar", "expected_stage": "preparing"})
    assert resp.status_code == 200
    assert _html(resp).xpath('//*[@id="tt-sin-anexo-error"]')
    db_session.expire_all()
    a = db_session.query(Anexo).filter_by(process_id=c.process.id).first()
    assert a is None or a.ready_at is None


def test_marcar_listo_otro_departamento_404(prep, esc, db_session, make_department,
                                            make_academic_head, client_as):
    (c,) = prep(1)
    otro = make_department(name="Otro depto listo anexo")
    jefe = make_academic_head(otro, kind="head", perms=PERMS + (PREPARE_PERM,))
    db_session.commit()
    r = client_as(jefe).post(f"{URL}/{c.process.id}/anexo/listo", data={"note": NOTA})
    assert r.status_code == 404


def test_marcar_listo_sin_prepare_403(prep, esc, db_session, make_academic_head, client_as):
    (c,) = prep(1)
    solo = make_academic_head(c.department, kind="coord", perms=PERMS)
    db_session.commit()
    r = client_as(solo).post(f"{URL}/{c.process.id}/anexo/listo", data={"note": NOTA})
    assert r.status_code == 403
    db_session.expire_all()
    assert db_session.query(Anexo).filter_by(process_id=c.process.id).count() == 0


def test_marcar_listo_con_corte_3_no_escribe(prep, esc, corte, db_session):
    (c,) = prep(1)
    cli = esc.client_as(c.head)
    corte(3)
    r = cli.post(f"{URL}/{c.process.id}/anexo/listo", data={"note": NOTA})
    assert r.status_code == 400 and r.headers.get("X-Tt-Error")
    assert db_session.query(Anexo).filter_by(process_id=c.process.id).count() == 0
    assert not _html(cli.get(BODY, params={"tab": "anexo", "selected": c.process.id})
                     ).xpath('//*[@id="tt-sin-anexo-panel"]')


def test_ya_en_titulacion_no_se_puede_marcar_listo(prep, esc, db_session):
    (c,) = prep(1)
    _fase(db_session, c, "in_review")
    r = esc.client_as(c.head).post(f"{URL}/{c.process.id}/anexo/listo", data={"note": NOTA})
    assert r.status_code == 400 and r.headers.get("X-Tt-Error")


def test_marcar_listo_con_aviso_fallido_dice_la_verdad(prep, esc, db_session, monkeypatch):
    (c,) = prep(1)

    def _boom(process_id):
        raise RuntimeError("sin redis")
    monkeypatch.setattr(AnexoService, "notify_ready", staticmethod(_boom))
    resp = esc.client_as(c.head).post(
        f"{URL}/{c.process.id}/anexo/listo",
        data={"note": NOTA, "tab": "anexo", "etapa": "preparar", "expected_stage": "preparing"})
    assert resp.status_code == 200
    assert resp.headers.get("X-Tt-Notice-Kind") == "warning"
    assert "no%20se%20pudo%20avisar" in resp.headers["X-Tt-Notice"]
    db_session.expire_all()
    assert db_session.query(Anexo).filter_by(process_id=c.process.id).one().ready_at is not None
