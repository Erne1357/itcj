"""Fase 5 (revisión de sinodales), Task 8: recordatorios del plazo.

Spec 2026-10-22-titulatec-fase5-revision-sinodales §10 y D9:

- `due_soon` a 2 o menos días hábiles del vencimiento, `due_today` el día que
  vence (o el primer barrido después); solo a quien su voto cuenta y no votó la
  versión vigente; una vez por versión, sinodal y tipo (dedupe en BD);
- un día inhábil recorre el vencimiento y con él los dos avisos;
- nada con la conversación cerrada, el proceso fuera de `active` o el corte a
  T-soft en la fase 5 (`{"disabled": True}`);
- el correo sale tras el commit y una falla no desmarca el recordatorio.

Fechas fijas (el reloj real no entra: se pasa `today=`). La versión se sube el
lunes 2031-03-03 y vence el lunes 2031-03-17 (10 días hábiles).
"""
from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from itcj2.apps.titulatec.services import email_helper
from itcj2.apps.titulatec.services.phase_service import PhaseService
from itcj2.apps.titulatec.services.review_reminders import ReviewReminders
from itcj2.apps.titulatec.services.review_service import ReviewService
from tests.fastapi.titulatec.conftest import audit_query

pytestmark = pytest.mark.usefixtures("audit_mark")

SUBIDA = datetime(2031, 3, 3, 10, 0)           # lunes
VENCE = date(2031, 3, 17)                      # lunes, 10 días hábiles después
DOS_ANTES = date(2031, 3, 13)                  # jueves: faltan 2 hábiles (vie 14, lun 17)
TRES_ANTES = date(2031, 3, 12)                 # miércoles: faltan 3


@pytest.fixture()
def corte(monkeypatch):
    def _fijar(fase):
        monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: fase))
    return _fijar


@pytest.fixture(autouse=True)
def entorno(monkeypatch, patched_session_local, corte):
    from itcj2.config import get_settings

    monkeypatch.setattr(get_settings(), "TITULATEC_REVIEW_DAYS", 10)
    corte(9)
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
    """Caso con la versión 1 subida `SUBIDA`, commiteado."""
    def _build(**kw):
        c = make_review_case(**kw)
        c.versions[0].uploaded_at = SUBIDA
        db_session.commit()
        return c
    return _build


def _recordatorios(db, c=None) -> list:
    from itcj2.apps.titulatec.models import ReviewReminder, ReviewVersion

    db.flush()
    q = db.query(ReviewReminder)
    if c is not None:
        q = q.join(ReviewVersion, ReviewVersion.id == ReviewReminder.version_id).filter(
            ReviewVersion.process_id == c.process.id)
    return q.order_by(ReviewReminder.assignment_id, ReviewReminder.kind).all()


def _campana(db, user_id) -> list:
    from itcj2.core.models.notification import Notification

    db.flush()
    return (db.query(Notification)
            .filter_by(user_id=user_id, app_name="titulatec", type="REVIEW_REMINDER")
            .order_by(Notification.id).all())


def _para(env, c, rol) -> list:
    return [e for e in env.enviados if e["to"] == c.teachers[rol].email]


class TestPlazo:
    def test_a_dos_dias_habiles_avisa_due_soon_al_presidente_de_una_integral(
            self, db_session, caso, entorno):
        c = caso(signature_rule="president_only")

        out = ReviewReminders.run(db_session, today=DOS_ANTES)

        assert out == {"due_soon": 1, "due_today": 0}
        (aviso,) = _campana(db_session, c.teachers["president"].id)
        assert aviso.data == {"url": f"/titulatec/admin/revisiones/{c.process.id}",
                              "process_id": c.process.id}
        assert "vence el" in aviso.body
        # Los que su voto no cuenta no reciben nada.
        for rol in ("secretary", "vocal", "alternate"):
            assert _campana(db_session, c.teachers[rol].id) == []
        (correo,) = entorno.enviados
        assert correo["to"] == c.teachers["president"].email
        assert correo["template"] == "review_reminder.html"
        assert correo["que"] == "review_due_soon"
        assert correo["context"]["kind"] == "due_soon" and correo["context"]["version"] == 1
        assert "por vencer" in correo["subject"]

    def test_tres_dias_antes_todavia_no(self, db_session, caso, entorno):
        caso(signature_rule="president_only")
        assert ReviewReminders.run(db_session, today=TRES_ANTES) == {"due_soon": 0,
                                                                     "due_today": 0}
        assert entorno.enviados == []

    def test_el_dia_del_vencimiento_avisa_due_today(self, db_session, caso, entorno):
        c = caso(signature_rule="president_only")

        out = ReviewReminders.run(db_session, today=VENCE)

        assert out == {"due_soon": 0, "due_today": 1}
        (correo,) = entorno.enviados
        assert correo["que"] == "review_due_today"
        assert "Hoy vence" in correo["subject"]
        assert [r.kind for r in _recordatorios(db_session, c)] == ["due_today"]

    def test_vencido_el_primer_barrido_despues_manda_due_today(self, db_session, caso):
        caso(signature_rule="president_only")
        assert ReviewReminders.run(db_session, today=date(2031, 3, 20)) == {
            "due_soon": 0, "due_today": 1}

    def test_tesis_avisa_a_los_cuatro(self, db_session, caso, entorno):
        c = caso(signature_rule="all_synodals")

        out = ReviewReminders.run(db_session, today=DOS_ANTES)

        assert out == {"due_soon": 4, "due_today": 0}
        assert {e["to"] for e in entorno.enviados} == {t.email for t in c.teachers.values()}
        for t in c.teachers.values():
            assert len(_campana(db_session, t.id)) == 1

    def test_el_segundo_barrido_no_duplica(self, db_session, caso, entorno):
        c = caso(signature_rule="all_synodals")
        ReviewReminders.run(db_session, today=DOS_ANTES)

        out = ReviewReminders.run(db_session, today=DOS_ANTES)
        out2 = ReviewReminders.run(db_session, today=date(2031, 3, 14))

        assert out == out2 == {"due_soon": 0, "due_today": 0}
        assert len(entorno.enviados) == 4
        assert len(_recordatorios(db_session, c)) == 4

    def test_due_soon_y_luego_due_today_son_dos_avisos(self, db_session, caso, entorno):
        c = caso(signature_rule="president_only")

        ReviewReminders.run(db_session, today=DOS_ANTES)
        out = ReviewReminders.run(db_session, today=VENCE)

        assert out == {"due_soon": 0, "due_today": 1}
        assert [r.kind for r in _recordatorios(db_session, c)] == ["due_soon", "due_today"]
        assert len(_campana(db_session, c.teachers["president"].id)) == 2
        assert len(entorno.enviados) == 2

    def test_un_dia_inhabil_recorre_el_vencimiento(self, db_session, caso, entorno,
                                                    make_non_working_day):
        c = caso(signature_rule="president_only")
        make_non_working_day(date(2031, 3, 14))      # viernes: el plazo vence el martes 18
        db_session.commit()

        # El día que vencía sin el festivo: ahora solo falta 1 hábil -> due_soon.
        out = ReviewReminders.run(db_session, today=VENCE)
        assert out == {"due_soon": 1, "due_today": 0}
        # Y el día nuevo del vencimiento sí es due_today.
        out = ReviewReminders.run(db_session, today=date(2031, 3, 18))
        assert out == {"due_soon": 0, "due_today": 1}
        assert [r.kind for r in _recordatorios(db_session, c)] == ["due_soon", "due_today"]


class TestAQuien:
    def test_no_a_quien_ya_voto(self, db_session, caso, entorno):
        c = caso(signature_rule="all_synodals")
        ReviewService.vote(db_session, c.process, c.teachers["president"].id,
                           verdict="approved", comment=None, seen_version=1, confirm=False)
        entorno.enviados.clear()

        out = ReviewReminders.run(db_session, today=DOS_ANTES)

        assert out == {"due_soon": 3, "due_today": 0}
        assert _para(entorno, c, "president") == []
        assert _campana(db_session, c.teachers["president"].id) == []

    def test_un_voto_de_una_version_vieja_no_exime(self, db_session, caso, entorno):
        """Los votos son por versión: con la v2 vigente, quien votó la v1 debe
        votar de nuevo."""
        from itcj2.apps.titulatec.models import ReviewVersion

        c = caso(signature_rule="president_only")
        ReviewService.vote(db_session, c.process, c.teachers["president"].id,
                           verdict="changes_requested", comment="Ajusta", seen_version=1,
                           confirm=False)
        v2 = ReviewVersion(process_id=c.process.id, number=2, file_path=None,
                           original_name="v2.pdf", mime_type="application/pdf",
                           size_bytes=1, uploaded_by_id=c.student.id,
                           uploaded_at=datetime(2031, 3, 4, 10, 0))
        db_session.add(v2)
        db_session.commit()

        # Vence el 2031-03-18 (10 hábiles desde el martes 4); el jueves 13 faltan 3.
        assert ReviewReminders.run(db_session, today=date(2031, 3, 14)) == {
            "due_soon": 1, "due_today": 0}
        assert entorno.enviados[0]["context"]["version"] == 2

    def test_no_al_sinodal_sustituido(self, db_session, caso, entorno):
        c = caso(signature_rule="all_synodals")
        c.assignments["vocal"].is_active = False
        db_session.commit()

        assert ReviewReminders.run(db_session, today=DOS_ANTES) == {"due_soon": 3,
                                                                    "due_today": 0}
        assert _para(entorno, c, "vocal") == []

    def test_regla_desconocida_no_recuerda_nada(self, db_session, caso, entorno):
        caso(signature_rule="otra_regla")
        assert ReviewReminders.run(db_session, today=DOS_ANTES) == {"due_soon": 0,
                                                                    "due_today": 0}


class TestAlcance:
    def test_conversacion_cerrada_no_recuerda(self, db_session, caso, entorno):
        c = caso(signature_rule="president_only")
        c.chat.closed_at = datetime(2031, 3, 10)
        db_session.commit()
        assert ReviewReminders.run(db_session, today=VENCE) == {"due_soon": 0, "due_today": 0}
        assert entorno.enviados == []

    @pytest.mark.parametrize("estado", ["on_hold", "cancelled", "completed"])
    def test_proceso_fuera_de_active_no_recuerda(self, db_session, caso, entorno, estado):
        c = caso(signature_rule="president_only")
        c.process.status = estado
        db_session.commit()
        assert ReviewReminders.run(db_session, today=VENCE) == {"due_soon": 0, "due_today": 0}

    def test_sin_versiones_no_corre_plazo(self, db_session, make_review_case, entorno):
        make_review_case(signature_rule="president_only", versions=0)
        db_session.commit()
        assert ReviewReminders.run(db_session, today=VENCE) == {"due_soon": 0, "due_today": 0}

    def test_con_el_corte_en_la_5_esta_deshabilitado(self, db_session, caso, entorno, corte):
        c = caso(signature_rule="president_only")
        corte(5)
        assert ReviewReminders.run(db_session, today=VENCE) == {"disabled": True}
        assert entorno.enviados == [] and _recordatorios(db_session, c) == []

    def test_sin_fase_5_en_el_catalogo_falla_cerrado(self, db_session, caso, monkeypatch):
        caso(signature_rule="president_only")
        monkeypatch.setattr(PhaseService, "phase_number_for_code",
                            staticmethod(lambda db, code: None))
        assert ReviewReminders.run(db_session, today=VENCE) == {"disabled": True}


class TestCorreo:
    def test_una_falla_de_correo_queda_en_bitacora_y_no_desmarca(self, db_session, caso,
                                                                  entorno):
        c = caso(signature_rule="president_only")
        entorno.fallan.add(c.teachers["president"].email)

        out = ReviewReminders.run(db_session, today=DOS_ANTES)

        assert out == {"due_soon": 1, "due_today": 0}
        assert len(_recordatorios(db_session, c)) == 1
        (fila,) = audit_query(db_session).filter_by(action="review.mail_failed").all()
        assert fila.entity_id == c.teachers["president"].id
        assert fila.payload["kind"] == "review_due_soon"
        # El siguiente barrido no reintenta (ya está marcado).
        entorno.enviados.clear()
        assert ReviewReminders.run(db_session, today=DOS_ANTES)["due_soon"] == 0
        assert entorno.enviados == []

    def test_el_correo_sale_despues_del_commit(self, db_session, caso, monkeypatch, entorno):
        """El orden: marcar + avisar + commit, y SOLO entonces el correo."""
        caso(signature_rule="president_only")
        orden = []
        original = email_helper.deliver_detailed

        def _espia(**kw):
            orden.append("correo")
            return original(**kw)

        monkeypatch.setattr(email_helper, "deliver_detailed", _espia)
        real_commit = db_session.commit

        def _commit():
            orden.append("commit")
            return real_commit()

        monkeypatch.setattr(db_session, "commit", _commit)

        ReviewReminders.run(db_session, today=DOS_ANTES)

        assert orden == ["commit", "correo"]

    def test_el_barrido_no_hace_una_consulta_por_proceso(self, db_session, make_review_case,
                                                         entorno):
        """Lote: las consultas fijas del barrido no crecen con los procesos."""
        from sqlalchemy import event

        def _contar(n_casos):
            for _ in range(n_casos):
                c = make_review_case(signature_rule="president_only")
                c.versions[0].uploaded_at = SUBIDA
            db_session.commit()
            sentencias = []

            def _on(conn, cursor, statement, *a):
                if statement.lstrip().upper().startswith("SELECT"):
                    sentencias.append(statement)

            engine = db_session.get_bind()
            event.listen(engine, "before_cursor_execute", _on)
            try:
                # `today` lejos del plazo: solo cuenta la selección del lote.
                ReviewReminders.run(db_session, today=date(2031, 3, 4))
            finally:
                event.remove(engine, "before_cursor_execute", _on)
            return len(sentencias)

        uno = _contar(1)
        varios = _contar(3)
        assert varios <= uno + 1, (uno, varios)
