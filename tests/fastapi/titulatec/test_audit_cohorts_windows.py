"""Bitacora (`source='action'`) de convocatorias, dias de cotejo, requisitos y
espacios de cotejo (spec 2026-10-07 §5, filas «cohorts» y «windows»).

La red ORM ya escribe filas `source='data'`; aqui solo se mira lo SEMANTICO:
quien, que y el antes/despues de lo que importa. Ninguna de estas acciones
pertenece a un proceso: `process_id` queda nulo.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from itcj2.core.utils.timezone import db_now


def _filas(db, action, entity_id=None):
    from itcj2.apps.titulatec.models.audit_log import TitulatecAuditLog as A
    q = db.query(A).filter(A.source == "action", A.action == action)
    if entity_id is not None:
        q = q.filter(A.entity_id == entity_id)
    return q.order_by(A.id).all()


def _una(db, action, entity_id):
    filas = _filas(db, action, entity_id)
    assert len(filas) == 1, f"{action}: {len(filas)} filas"
    fila = filas[0]
    assert fila.process_id is None
    return fila


@pytest.fixture()
def cohorte(make_cohort):
    return make_cohort(status="draft")


class TestCohorte:
    def test_set_window_registra_antes_despues_y_conteos(
            self, db_session, cohorte, make_user):
        from itcj2.apps.titulatec.services.cohort_service import CohortService
        actor = make_user()
        abre = db_now().replace(hour=0, minute=0, second=0, microsecond=0)
        cierra = abre + timedelta(days=9, hours=23)

        res = CohortService.set_window(db_session, cohorte.id, opens_at=abre,
                                       closes_at=cierra, status="open",
                                       actor_id=actor.id)

        fila = _una(db_session, "cohort.window_changed", cohorte.id)
        assert fila.actor_id == actor.id
        assert fila.after["status"] == "open"
        assert fila.before["status"] == "draft"
        assert fila.payload == {"paused": res["paused"], "resumed": res["resumed"]}

    def test_set_book_donation_guarda_montos_como_cadena(
            self, db_session, make_cohort):
        from itcj2.apps.titulatec.services.cohort_service import CohortService
        c = make_cohort(book_donation_amount=Decimal("100.00"))

        res = CohortService.set_book_donation(db_session, c.id,
                                              amount=Decimal("250.50"))

        fila = _una(db_session, "cohort.donation_changed", c.id)
        assert fila.before == {"book_donation_amount": "100.00"}
        assert fila.after == {"book_donation_amount": "250.50"}
        assert fila.payload == {"affected": res["affected"]}

    def test_dia_de_cotejo_se_habilita_y_se_cierra(
            self, db_session, cohorte, make_user):
        from itcj2.apps.titulatec.services.review_day_service import ReviewDayService
        actor = make_user()
        dia = date.today() + timedelta(days=11)

        assert ReviewDayService.toggle(db_session, cohorte.id, dia, actor.id) is True
        assert ReviewDayService.toggle(db_session, cohorte.id, dia, actor.id) is False

        filas = _filas(db_session, "cohort.review_day_toggled", cohorte.id)
        assert len(filas) == 2
        assert filas[0].after == {"is_closed": False}
        assert filas[1].before == {"is_closed": False}
        assert filas[1].after == {"is_closed": True}
        assert all(f.actor_id == actor.id and f.process_id is None for f in filas)

    def test_alta_de_convocatoria_desde_la_pagina(
            self, db_session, client_as, make_head, make_period):
        from itcj2.apps.titulatec.models import Cohort
        jefa = make_head(perm_codes=("titulatec.cohort.api.create",))
        periodo = make_period()

        resp = client_as(jefa).post(
            "/titulatec/admin/cohorts",
            data={"period_id": periodo.id, "opens_date": "2031-03-10",
                  "closes_date": "2031-03-20", "book_donation": "150"},
            follow_redirects=False)

        assert resp.status_code == 303, resp.text[:300]
        c = db_session.query(Cohort).filter_by(period_id=periodo.id).one()
        fila = _una(db_session, "cohort.created", c.id)
        assert fila.actor_id == jefa.id
        assert fila.after["status"] == "draft"
        assert fila.after["book_donation_amount"] == "150.00"


class TestRequisitos:
    def test_crear_editar_y_borrar(self, db_session, cohorte):
        from itcj2.apps.titulatec.services.cotejo_requirement_service import (
            CotejoRequirementService as S,
        )
        item = S.create(db_session, cohorte.id, label="Credencial", hint=None,
                        icon=None)
        creado = _una(db_session, "cohort.requirement_created", item.id)
        assert creado.after["label"] == "Credencial"

        S.update(db_session, item.id, cohorte.id, label="Credencial INE")
        edit = _una(db_session, "cohort.requirement_updated", item.id)
        assert edit.before == {"label": "Credencial"}
        assert edit.after == {"label": "Credencial INE"}

        iid = item.id
        assert S.delete(db_session, iid, cohorte.id) == (True, "ok")
        borrado = _una(db_session, "cohort.requirement_deleted", iid)
        assert borrado.before["label"] == "Credencial INE"

    def test_no_registra_si_no_hay_nada_que_borrar(self, db_session, cohorte):
        from itcj2.apps.titulatec.services.cotejo_requirement_service import (
            CotejoRequirementService as S,
        )
        assert S.delete(db_session, 99999999, cohorte.id) == (False, "not_found")
        assert _filas(db_session, "cohort.requirement_deleted", 99999999) == []


class TestEspacios:
    @pytest.fixture()
    def esc(self, db_session, cohorte, make_review_day, make_user):
        return {"dia": make_review_day(cohorte),
                "dia2": make_review_day(cohorte, date.today() + timedelta(days=9)),
                "dueno": make_user()}

    def test_create_many_registra_un_created_por_espacio(self, db_session, esc):
        from itcj2.apps.titulatec.services.review_window_service import (
            ReviewWindowService as S,
        )
        creados, _ = S.create_many(
            db_session, [esc["dia"].id, esc["dia2"].id], esc["dueno"].id,
            start_time="09:00", end_time="11:00", slot_minutes=30, capacity=2,
            actor_id=esc["dueno"].id)

        assert len(creados) == 2
        for w in creados:
            fila = _una(db_session, "window.created", w.id)
            assert fila.actor_id == esc["dueno"].id
            assert fila.after["capacity"] == 2
            assert fila.after["start_time"] == "09:00:00"

    def test_update_registra_solo_lo_que_cambio(self, db_session, esc,
                                                make_review_window):
        from itcj2.apps.titulatec.services.review_window_service import (
            ReviewWindowService as S,
        )
        w = make_review_window(esc["dia"], esc["dueno"], cap=1)

        S.update(db_session, w, start_time=w.start_time, end_time=w.end_time,
                 slot_minutes=w.slot_minutes, capacity=3, location="Edif. B")

        fila = _una(db_session, "window.updated", w.id)
        assert fila.before == {"capacity": 1, "location": None}
        assert fila.after == {"capacity": 3, "location": "Edif. B"}

    def test_pausa_y_reanuda(self, db_session, esc, make_review_window):
        from itcj2.apps.titulatec.services.review_window_service import (
            ReviewWindowService as S,
        )
        w = make_review_window(esc["dia"], esc["dueno"])
        S.toggle_pause(db_session, w)
        S.toggle_pause(db_session, w)

        p = _una(db_session, "window.paused", w.id)
        r = _una(db_session, "window.resumed", w.id)
        assert (p.before, p.after) == ({"status": "open"}, {"status": "paused"})
        assert (r.before, r.after) == ({"status": "paused"}, {"status": "open"})

    def test_abrir_lugares(self, db_session, esc, make_review_window):
        from itcj2.apps.titulatec.services.review_window_service import (
            ReviewWindowService as S,
        )
        w = make_review_window(esc["dia"], esc["dueno"], cap=10,
                               visibility="walkin")
        S.add_places(db_session, w, 5)

        fila = _una(db_session, "window.places_added", w.id)
        assert fila.before == {"capacity": 10}
        assert fila.after == {"capacity": 15}
        assert fila.payload == {"added": 5}

    def test_borrar_guarda_la_foto_previa(self, db_session, esc, make_review_window):
        from itcj2.apps.titulatec.services.review_window_service import (
            ReviewWindowService as S,
        )
        w = make_review_window(esc["dia"], esc["dueno"], cap=4, location="Sala 1")
        wid = w.id
        S.delete(db_session, w)

        fila = _una(db_session, "window.deleted", wid)
        assert fila.before["capacity"] == 4
        assert fila.before["location"] == "Sala 1"

    def test_copiar_registra_copied_y_no_created(self, db_session, esc,
                                                 make_review_window):
        from itcj2.apps.titulatec.services.review_window_service import (
            ReviewWindowService as S,
        )
        w = make_review_window(esc["dia"], esc["dueno"], cap=2)
        creados, _ = S.copy_to_days(db_session, w, [esc["dia2"].id])

        assert len(creados) == 1
        fila = _una(db_session, "window.copied", creados[0].id)
        assert fila.payload == {"source_window_id": w.id}
        assert _filas(db_session, "window.created", creados[0].id) == []
