"""Fase 5 (revisión de sinodales), Task 8: avisos in-app y correos.

Spec 2026-10-22-titulatec-fase5-revision-sinodales §10 (D8):

- versión nueva -> los 4 sinodales vigentes, campana + correo directo después
  del commit; una falla queda en `review.mail_failed` y no revierte nada;
- mensajes y votos -> campana, a lo más un aviso de mensaje SIN LEER por
  conversación y usuario;
- cambios pedidos -> correo al alumno por la bandeja (`review_changes_requested`,
  agrupado por versión; obsoleto con una versión más nueva o con la fase 5
  aprobada);
- liberado -> `phase_approved` con la línea del Anexo III (solo la fase 5);
- con el corte a T-soft en la fase 5 o antes no sale nada.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from itcj2.apps.titulatec.services import email_helper
from itcj2.apps.titulatec.services.mail_compose import Composed, MailComposer, Obsolete
from itcj2.apps.titulatec.services.phase_service import PhaseService
from itcj2.apps.titulatec.services.review_notices import ReviewNotices
from itcj2.apps.titulatec.services.review_service import PHASE_CODE, ReviewService
from itcj2.apps.titulatec.services.student_mail import StudentMail
from itcj2.apps.titulatec.services.synodal_service import SynodalService
from itcj2.apps.titulatec.utils import storage
from tests.fastapi.titulatec.conftest import audit_query

pytestmark = pytest.mark.usefixtures("audit_mark")

PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
       b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")


# ---------------------------------------------------------------------------
# Andamiaje
# ---------------------------------------------------------------------------
@pytest.fixture()
def corte(monkeypatch):
    def _fijar(fase):
        monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: fase))
    return _fijar


@pytest.fixture(autouse=True)
def entorno(monkeypatch, patched_session_local, corte, tmp_path):
    """Corte en 9, archivos en `tmp_path`, correo encendido y `deliver_detailed`
    parcheado (`fallan` = ids de usuario cuyo correo debe fallar)."""
    from itcj2.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "TITULATEC_EMAIL_ENABLED", True)
    corte(9)
    monkeypatch.setattr(storage, "_base", lambda: tmp_path)
    env = SimpleNamespace(enviados=[], fallan=set())

    def _deliver(*, template, context, subject, to, que, link=None):
        env.enviados.append({"template": template, "to": to, "que": que,
                             "subject": subject, "context": context})
        if to in env.fallan:
            return False, "envio"
        return True, None

    monkeypatch.setattr(email_helper, "deliver_detailed", _deliver)
    return env


@pytest.fixture()
def caso(db_session, make_review_case):
    def _build(**kw):
        c = make_review_case(**kw)
        db_session.commit()
        return c
    return _build


def _campana(db, user_id, tipo=None, process_id=None) -> list:
    from itcj2.core.models.notification import Notification

    db.flush()
    q = db.query(Notification).filter_by(user_id=user_id, app_name="titulatec")
    if tipo:
        q = q.filter_by(type=tipo)
    filas = q.order_by(Notification.id).all()
    if process_id is not None:
        filas = [n for n in filas if (n.data or {}).get("process_id") == process_id]
    return filas


def _outbox(db, pid, kind="review_changes_requested") -> list:
    from itcj2.apps.titulatec.models import EmailOutbox

    db.flush()
    return (db.query(EmailOutbox).filter_by(process_id=pid, kind=kind)
            .order_by(EmailOutbox.id).all())


def _votar(db, c, role, verdict="approved", *, comment=None, confirm=False):
    numero = ReviewService.current_version(db, c.process.id).number
    return ReviewService.vote(db, c.process, c.teachers[role].id, verdict=verdict,
                              comment=comment, seen_version=numero, confirm=confirm)


def _subir(db, c, nombre="proyecto.pdf"):
    return ReviewService.upload_version(db, c.process, c.student.id, raw=PDF,
                                        original_name=nombre)


def _componer(db, c, filas):
    from itcj2.core.models.user import User

    return MailComposer.compose(db, filas, c.process, db.get(User, c.student.id))


def _html(composed) -> str:
    from itcj2.apps.titulatec.pages.nav import titulatec_templates

    return titulatec_templates.get_template(
        f"titulatec/email/{composed.template}").render(**composed.context)


def _texto(html: str) -> str:
    import lxml.html

    return " ".join(lxml.html.fromstring(html).text_content().split())


# ---------------------------------------------------------------------------
# Versión nueva -> sinodales
# ---------------------------------------------------------------------------
class TestVersionNueva:
    def test_avisa_a_los_4_sinodales_por_campana_y_correo(self, db_session, caso, entorno):
        c = caso(versions=0)

        v = _subir(db_session, c)

        assert len(entorno.enviados) == 4
        assert {e["template"] for e in entorno.enviados} == {"review_new_version.html"}
        assert {e["que"] for e in entorno.enviados} == {"review_version"}
        assert {e["to"] for e in entorno.enviados} == {t.email for t in c.teachers.values()}
        for t in c.teachers.values():
            (aviso,) = _campana(db_session, t.id, "REVIEW_VERSION")
            assert aviso.data == {"url": f"/titulatec/admin/revisiones/{c.process.id}",
                                  "process_id": c.process.id}
        ctx = entorno.enviados[0]["context"]
        assert ctx["version"] == v.number == 1
        assert ctx["alumno"].startswith("ALUMNO") and ctx["vence"]
        assert "/itcj/login?next=" in ctx["link"]
        assert _campana(db_session, c.student.id, "REVIEW_VERSION") == []

    def test_no_avisa_al_sinodal_sustituido(self, db_session, caso, entorno, make_teacher):
        c = caso(versions=0)
        viejo = c.assignments["vocal"]
        viejo.is_active = False
        db_session.commit()

        _subir(db_session, c)

        assert c.teachers["vocal"].email not in {e["to"] for e in entorno.enviados}
        assert len(entorno.enviados) == 3
        assert _campana(db_session, c.teachers["vocal"].id, "REVIEW_VERSION") == []

    def test_una_falla_deja_bitacora_y_no_revierte(self, db_session, caso, entorno):
        from itcj2.apps.titulatec.models import ReviewVersion

        c = caso(versions=0)
        malo = c.teachers["secretary"]
        entorno.fallan.add(malo.email)

        _subir(db_session, c)

        assert len(entorno.enviados) == 4
        assert db_session.query(ReviewVersion).filter_by(process_id=c.process.id).count() == 1
        filas = audit_query(db_session).filter_by(action="review.mail_failed").all()
        assert len(filas) == 1
        assert filas[0].process_id == c.process.id
        assert filas[0].entity_id == malo.id
        assert filas[0].payload["kind"] == "review_version"
        # La campana del que falló quedó igual.
        assert len(_campana(db_session, malo.id, "REVIEW_VERSION")) == 1

    def test_una_excepcion_del_correo_no_rompe_la_subida(self, db_session, caso, monkeypatch):
        c = caso(versions=0)

        def _boom(**_k):
            raise RuntimeError("graph caído")

        monkeypatch.setattr(email_helper, "deliver_detailed", _boom)

        v = _subir(db_session, c)

        assert v.number == 1
        assert len(audit_query(db_session).filter_by(action="review.mail_failed").all()) == 4

    def test_con_el_corte_en_la_fase_5_no_sale_nada(self, db_session, caso, entorno, corte):
        c = caso(versions=0)
        corte(5)

        ReviewNotices.send_version_notices(c.process.id, 12345)

        assert entorno.enviados == []
        assert _campana(db_session, c.teachers["president"].id) == []

    def test_proceso_o_version_inexistentes_no_lanzan(self, db_session, caso, entorno):
        c = caso(versions=0)
        ReviewNotices.send_version_notices(c.process.id, 99999999)
        ReviewNotices.send_version_notices(99999999, 99999999)
        assert entorno.enviados == []


# ---------------------------------------------------------------------------
# Mensajes y votos -> campana
# ---------------------------------------------------------------------------
class TestCampana:
    def test_mensaje_del_alumno_avisa_a_los_sinodales_una_sola_vez(self, db_session, caso):
        c = caso()

        ReviewService.post_message(db_session, c.process, c.student.id, body="Hola")
        ReviewService.post_message(db_session, c.process, c.student.id, body="¿Me ven?")

        for t in c.teachers.values():
            (aviso,) = _campana(db_session, t.id, "REVIEW_MESSAGE")
            assert aviso.data["url"] == f"/titulatec/admin/revisiones/{c.process.id}"
        assert _campana(db_session, c.student.id, "REVIEW_MESSAGE") == []

    def test_leido_el_aviso_el_siguiente_mensaje_vuelve_a_avisar(self, db_session, caso):
        c = caso()
        ReviewService.post_message(db_session, c.process, c.student.id, body="Uno")
        (aviso,) = _campana(db_session, c.teachers["president"].id, "REVIEW_MESSAGE")
        aviso.is_read = True
        aviso.read_at = datetime(2031, 1, 1)
        db_session.flush()

        ReviewService.post_message(db_session, c.process, c.student.id, body="Dos")

        assert len(_campana(db_session, c.teachers["president"].id, "REVIEW_MESSAGE")) == 2
        # Los demás seguían sin leer el primero: no se les duplicó.
        assert len(_campana(db_session, c.teachers["vocal"].id, "REVIEW_MESSAGE")) == 1

    def test_mensaje_de_un_sinodal_avisa_al_alumno_y_a_los_otros_sinodales(self, db_session, caso):
        c = caso()

        ReviewService.post_message(db_session, c.process, c.teachers["president"].id,
                                  body="Revisen el capítulo 2")

        (al_alumno,) = _campana(db_session, c.student.id, "REVIEW_MESSAGE")
        assert al_alumno.data["url"] == "/titulatec/student/revision"
        assert _campana(db_session, c.teachers["president"].id, "REVIEW_MESSAGE") == []
        for rol in ("secretary", "vocal", "alternate"):
            assert len(_campana(db_session, c.teachers[rol].id, "REVIEW_MESSAGE")) == 1

    def test_el_aviso_de_mensaje_de_otro_proceso_no_cuenta(self, db_session, caso):
        a, b = caso(), caso()
        ReviewService.post_message(db_session, a.process, a.student.id, body="Hola")
        # Un sinodal de `b` (otro usuario) no recibe nada de `a`.
        assert _campana(db_session, b.teachers["president"].id) == []

    def test_voto_avisa_al_alumno(self, db_session, caso):
        c = caso(signature_rule="all_synodals")

        _votar(db_session, c, "president", "approved")
        _votar(db_session, c, "secretary", "changes_requested", comment="Falta el marco teórico")

        avisos = _campana(db_session, c.student.id, "REVIEW_VOTE")
        assert len(avisos) == 2
        assert avisos[0].data == {"url": "/titulatec/student/revision",
                                  "process_id": c.process.id}
        assert "aprobó la versión 1" in avisos[0].body
        assert "pidió cambios en la versión 1" in avisos[1].body

    def test_un_aviso_que_falla_no_tumba_el_mensaje(self, db_session, caso, monkeypatch):
        from itcj2.apps.titulatec.models import ChatMessage
        from itcj2.core.services.notification_service import NotificationService

        c = caso()

        def _boom(*_a, **_k):
            raise RuntimeError("campana caída")

        monkeypatch.setattr(NotificationService, "create", staticmethod(_boom))

        ReviewService.post_message(db_session, c.process, c.student.id, body="Hola")

        assert db_session.query(ChatMessage).filter_by(chat_id=c.chat.id, kind="message").count() == 1

    def test_con_el_corte_no_se_escribe_nada(self, db_session, caso, corte):
        c = caso()
        corte(5)
        with pytest.raises(ValueError):
            ReviewService.post_message(db_session, c.process, c.student.id, body="Hola")
        assert _campana(db_session, c.teachers["president"].id) == []


# ---------------------------------------------------------------------------
# Cambios pedidos -> correo del alumno por la bandeja
# ---------------------------------------------------------------------------
class TestCambiosPedidos:
    def test_encola_una_fila_con_su_grupo(self, db_session, caso):
        c = caso(signature_rule="all_synodals")

        _votar(db_session, c, "secretary", "changes_requested", comment="Corrige la bibliografía")

        (fila,) = _outbox(db_session, c.process.id)
        assert fila.group_key == f"review:{c.process.id}:1"
        assert fila.user_id == c.student.id
        assert fila.payload == {"version": 1, "role_label": "Secretario",
                                "comment": "Corrige la bibliografía"}
        assert fila.status == "pending"

    def test_aprobar_no_encola_correo(self, db_session, caso):
        c = caso(signature_rule="all_synodals")
        _votar(db_session, c, "president", "approved", comment="Bien")
        assert _outbox(db_session, c.process.id) == []

    def test_dos_votos_de_la_misma_version_salen_en_un_solo_correo(self, db_session, caso):
        c = caso(signature_rule="all_synodals")
        _votar(db_session, c, "secretary", "changes_requested", comment="Falta la conclusión")
        _votar(db_session, c, "vocal", "changes_requested", comment="Revisa las tablas")

        filas = _outbox(db_session, c.process.id)
        assert len(filas) == 2
        assert len({f.group_key for f in filas}) == 1

        correo = _componer(db_session, c, filas)

        assert isinstance(correo, Composed)
        assert correo.subject == "[TitulaTec ITCJ] Tus sinodales pidieron cambios a tu proyecto"
        assert correo.template == "review_changes_requested.html"
        texto = _texto(_html(correo))
        assert "Falta la conclusión" in texto and "Revisa las tablas" in texto
        assert "Secretario" in texto and "Vocal" in texto
        assert correo.link.endswith("%2Ftitulatec%2Fstudent%2Frevision")
        assert correo.context["first_name"] == c.student.first_name

    def test_el_correo_escapa_las_observaciones(self, db_session, caso):
        c = caso(signature_rule="all_synodals")
        _votar(db_session, c, "secretary", "changes_requested", comment="<script>x</script>")
        correo = _componer(db_session, c, _outbox(db_session, c.process.id))
        html = _html(correo)
        assert "<script>x" not in html and "&lt;script&gt;" in html

    def test_obsoleto_si_ya_hay_una_version_mas_nueva(self, db_session, caso):
        c = caso(signature_rule="all_synodals")
        _votar(db_session, c, "secretary", "changes_requested", comment="Falta algo")
        filas = _outbox(db_session, c.process.id)

        _subir(db_session, c, "v2.pdf")

        res = _componer(db_session, c, filas)
        assert isinstance(res, Obsolete)
        assert "versión más nueva" in res.reason

    def test_obsoleto_si_la_fase_5_ya_se_aprobo(self, db_session, caso):
        c = caso(signature_rule="all_synodals")
        _votar(db_session, c, "secretary", "changes_requested", comment="Falta algo")
        filas = _outbox(db_session, c.process.id)
        for rol in ("president", "secretary", "vocal"):
            _votar(db_session, c, rol, "approved")
        assert _votar(db_session, c, "alternate", "approved", confirm=True)["closed"] is True

        res = _componer(db_session, c, filas)

        assert isinstance(res, Obsolete)
        assert "aprob" in res.reason

    def test_con_el_correo_apagado_no_encola_pero_si_avisa(self, db_session, caso, monkeypatch):
        from itcj2.config import get_settings

        monkeypatch.setattr(get_settings(), "TITULATEC_EMAIL_ENABLED", False)
        c = caso(signature_rule="all_synodals")

        _votar(db_session, c, "secretary", "changes_requested", comment="Falta algo")

        assert _outbox(db_session, c.process.id) == []
        assert len(_campana(db_session, c.student.id, "REVIEW_VOTE")) == 1

    def test_el_catalogo_conoce_el_kind(self):
        from itcj2.apps.titulatec.models.email_outbox import OUTBOX_KINDS

        assert "review_changes_requested" in OUTBOX_KINDS
        assert "review_changes_requested" in MailComposer.REGISTRY
        assert "review_changes_requested" in StudentMail.KIND_LABELS


# ---------------------------------------------------------------------------
# Liberado -> phase_approved
# ---------------------------------------------------------------------------
def _liberar(db, c):
    """Cierra la revisión por la puerta real y devuelve el `phase_approved`."""
    roles = ("president", "secretary", "vocal", "alternate")
    contados = ReviewService.counting_roles(ReviewService.rule_for(c.process))
    for rol in [r for r in roles if r in contados][:-1]:
        _votar(db, c, rol, "approved")
    _votar(db, c, [r for r in roles if r in contados][-1], "approved", confirm=True)
    return _outbox(db, c.process.id, "phase_approved")


class TestLiberado:
    def test_integral_trae_la_linea_del_anexo_iii_del_presidente(self, db_session, caso):
        c = caso(signature_rule="president_only")

        filas = _liberar(db_session, c)

        (fila,) = filas
        correo = _componer(db_session, c, filas)
        assert fila.payload["handoff"] is False
        assert correo.context["review_released"] is True
        assert correo.context["signature_text"] == "basta la firma del Presidente"
        texto = _texto(_html(correo))
        assert "Anexo III" in texto and "basta la firma del Presidente" in texto

    def test_tesis_trae_las_4_firmas(self, db_session, caso):
        c = caso(signature_rule="all_synodals")

        correo = _componer(db_session, c, _liberar(db_session, c))

        assert correo.context["signature_text"] == "se necesitan las firmas de tus 4 sinodales"
        assert "se necesitan las firmas de tus 4 sinodales" in _texto(_html(correo))

    def test_con_el_corte_en_la_6_es_el_traspaso_a_titulacion(self, db_session, caso, corte):
        corte(6)
        c = caso(signature_rule="president_only")

        (fila,) = _liberar(db_session, c)
        correo = _componer(db_session, c, [fila])

        assert fila.payload["handoff"] is True
        assert correo.subject == "[TitulaTec ITCJ] Tus sinodales liberaron tu proyecto"
        texto = _texto(_html(correo))
        assert "Tus sinodales liberaron tu proyecto" in texto
        assert "Departamento de Titulación" in texto
        assert "Servicios Escolares" not in texto
        assert "Anexo III" not in texto

    def test_otra_fase_no_lleva_la_linea(self, db_session, caso):
        """EGEL salta la 5 (3 -> 6): su `phase_approved` es el de siempre."""
        c = caso()
        n5 = PhaseService.phase_number_for_code(db_session, PHASE_CODE)
        StudentMail.phase_approved(db_session, c.process, phase_number=3,
                                   phase_name="Fase 03 · Formato B", next_phase=n5 + 1,
                                   next_name="Fase 06 · Anexo III", handoff=False)

        correo = _componer(db_session, c, _outbox(db_session, c.process.id, "phase_approved"))

        assert correo.context["review_released"] is False
        assert correo.context["signature_text"] is None
        assert "firma" not in _texto(_html(correo))


# ---------------------------------------------------------------------------
# Correo de la asignación (fase 4)
# ---------------------------------------------------------------------------
class TestSinodalAsignado:
    def _render(self, **extra):
        from itcj2.apps.titulatec.pages.nav import titulatec_templates

        ctx = {"kind": "assigned", "nombre": "Ana", "posicion": "Presidente",
               "alumno": "Beto", "control": "99", "carrera": "X", "opcion": "Y",
               "titulo": "Z", "link": "https://x/login", **extra}
        return _texto(titulatec_templates.get_template(
            "titulatec/email/synodal_assigned.html").render(**ctx))

    def test_con_la_fase_5_operable_invita_a_mis_revisiones(self):
        texto = self._render(revision=True, review_link="https://x/revisiones")
        assert "Mis revisiones" in texto

    def test_sin_la_fase_5_es_el_texto_de_antes(self):
        texto = self._render(revision=False, review_link=None)
        assert "Mis revisiones" not in texto
        assert "Entrar a TitulaTec" in texto

    def test_assign_pasa_la_bandera_segun_el_corte(self, db_session, caso, entorno, corte):
        c = caso(versions=0)
        for fase, esperado in ((9, True), (5, False)):
            corte(fase)
            entorno.enviados.clear()
            SynodalService.send_assignment_notices(
                c.process.id, [c.teachers["president"].id], kind="assigned")
            (envio,) = entorno.enviados
            assert envio["context"]["revision"] is esperado
            assert (envio["context"]["review_link"] is not None) is esperado
