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


def test_el_detalle_ofrece_el_pdf_del_anexo(esc):
    c = esc.caso()
    resp = esc.client_as(c.head).get(BODY, params={"tab": "anexo", "selected": c.process.id})
    ligas = _html(resp).xpath('//a[@id="tt-sin-anexo"]')
    assert ligas and ligas[0].get("href") == f"{URL}/{c.process.id}/anexo.pdf"


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


@pytest.mark.parametrize("alumno_primero", [True, False])
def test_mismo_folio_para_el_alumno_y_vinculacion(esc, db_session, make_role,
                                                  alumno_primero, patched_session_local):
    import re
    from tests.fastapi.titulatec.test_student_anexo import ANEXO_PERMS, ROLE_STUDENT

    c = esc.caso()
    make_role(ROLE_STUDENT, ANEXO_PERMS)
    db_session.commit()
    # `client_as` devuelve el MISMO cliente: se cambia de actor justo antes de pedir.
    urls = [(c.student, "/titulatec/student/anexo/pdf"),
            (c.head, f"{URL}/{c.process.id}/anexo.pdf")]
    if not alumno_primero:
        urls.reverse()

    textos = []
    for actor, url in urls:
        resp = esc.client_as(actor).get(url)
        assert resp.status_code == 200, (url, resp.text[:300])
        textos.append(_texto_pdf(resp.content))

    db_session.expire_all()
    filas = db_session.query(Anexo).filter_by(process_id=c.process.id).all()
    assert len(filas) == 1
    folio = filas[0].folio
    assert all(folio in re.sub(r"\s+", "", t) for t in textos), (folio, textos)


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
    assert a.title == "Proyecto liberado: Anexo III"
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
