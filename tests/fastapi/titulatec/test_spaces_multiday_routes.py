"""Rutas de espacios: crear/copiar en varios días y el editor sin horario.

Tarea 4 del plan 2026-09-29-titulatec-cotejo-espacios (spec §3.2, §5, D3, D9).
`test_window_visibility.py` ya cubre el editor de UN espacio (los tres modos,
la línea derivada, el alcance); este archivo cubre lo que esa tarea NO tenía:
`space_save` con `w=nuevo` creando en VARIOS días a la vez, `space_copy`
exigiendo `dias`, y que el `capacity` efectivo que persiste cada modo es el
correcto (`capacity_total` en sin horario, `capacity` con franjas).
"""
from datetime import date
from urllib.parse import unquote

import pytest

from tests.fastapi.titulatec.conftest import OFFICER_PERMS

_ESPACIO_PERM = "titulatec.review_window.api.manage"

_D1 = date(2029, 7, 2)   # lun
_D2 = date(2029, 7, 3)   # mar
_D3 = date(2029, 7, 4)   # mié
_D4 = date(2029, 7, 5)   # jue


@pytest.fixture()
def dias4(make_program, make_cohort, make_review_day, make_officer):
    """Un encargado con 4 días de cotejo habilitados, sin ningún espacio aún."""
    prog = make_program("Ingeniería de Varios Días (rutas)")
    cohort = make_cohort()
    dias = {d: make_review_day(cohort, day=d) for d in (_D1, _D2, _D3, _D4)}
    officer, pos = make_officer([prog], perm_codes=OFFICER_PERMS + (_ESPACIO_PERM,))
    return {"prog": prog, "cohort": cohort, "dias": dias, "off": officer, "pos": pos}


def _aviso(resp):
    """`(mensaje, kind)` ya decodificado; `("", "")` si no hubo aviso."""
    return (unquote(resp.headers.get("X-Tt-Notice", "")),
            resp.headers.get("X-Tt-Notice-Kind", ""))


def _form(**kw):
    base = {"start_time": "09:00", "end_time": "14:00", "slot_minutes": "30",
            "capacity": "1", "capacity_total": "", "location": "",
            "visibility": "private"}
    base.update(kw)
    return base


def _url_nuevo(day):
    return ("/titulatec/admin/appointments/espacios/nuevo?v=espacios&date=%s"
            % day.isoformat())


def _url_copiar(window_id, day):
    return ("/titulatec/admin/appointments/espacios/%d/copiar?v=espacios&date=%s"
            % (window_id, day.isoformat()))


def _windows_de(db_session, review_day_id):
    from itcj2.apps.titulatec.models import ReviewWindow
    return (db_session.query(ReviewWindow)
            .filter_by(review_day_id=review_day_id).all())


class TestCrearEnVariosDias:
    """`space_save` con `w=nuevo` y `dias` (D9, spec §5)."""

    def test_crea_en_los_dias_elegidos_y_el_aviso_nombra_los_saltados(
            self, dias4, client_as, db_session, make_review_window):
        esc = dias4
        # El dueño YA tiene algo el miércoles que se encima con el 09:00-14:00
        # que se va a crear en los cuatro días.
        make_review_window(esc["dias"][_D3], esc["off"], start="10:00", end="12:00",
                           position=esc["pos"])

        resp = client_as(esc["off"]).post(
            _url_nuevo(_D1),
            data=_form(dias=[_D2.isoformat(), _D3.isoformat(), _D4.isoformat()]))

        assert resp.status_code == 200, resp.text[:300]
        mensaje, kind = _aviso(resp)
        assert mensaje == ("Espacio creado en 3 días. Se saltó 1 porque se "
                           "encima con otro espacio tuyo: mié 04.")
        assert kind == "warning"

        db_session.expire_all()
        # Se creó el día de la URL más los dos que no chocaban.
        for d in (_D1, _D2, _D4):
            filas = _windows_de(db_session, esc["dias"][d].id)
            assert len(filas) == 1, f"no se creó el espacio en {d}"
            assert filas[0].owner_user_id == esc["off"].id

        # El miércoles se saltó: sigue con SOLO el espacio original (10:00-12:00).
        filas_mie = _windows_de(db_session, esc["dias"][_D3].id)
        assert len(filas_mie) == 1
        assert filas_mie[0].start_time.strftime("%H:%M") == "10:00"

    def test_sin_dias_extra_crea_solo_en_el_dia_de_la_url(
            self, dias4, client_as, db_session):
        """La negativa: sin marcar ningún día de más, el comportamiento de
        siempre (un espacio, en el día abierto) sigue intacto."""
        esc = dias4

        resp = client_as(esc["off"]).post(_url_nuevo(_D1), data=_form())

        assert resp.status_code == 200, resp.text[:300]
        mensaje, kind = _aviso(resp)
        assert mensaje == "Espacio creado en 1 día."
        assert kind == "success"

        db_session.expire_all()
        assert len(_windows_de(db_session, esc["dias"][_D1].id)) == 1
        for d in (_D2, _D3, _D4):
            assert _windows_de(db_session, esc["dias"][d].id) == []


class TestCapacidadEfectiva:
    """`capacity` efectiva = `capacity_total` en sin horario, `capacity` si no
    (D3, spec §3.2, Pistas)."""

    def test_walkin_guarda_capacity_total(self, dias4, client_as, db_session):
        esc = dias4

        resp = client_as(esc["off"]).post(
            _url_nuevo(_D1),
            data=_form(visibility="walkin", capacity="1", capacity_total="7"))

        assert resp.status_code == 200, resp.text[:300]
        db_session.expire_all()
        filas = _windows_de(db_session, esc["dias"][_D1].id)
        assert len(filas) == 1
        assert filas[0].capacity == 7
        assert filas[0].visibility == "walkin"

    def test_bookable_guarda_capacity(self, dias4, client_as, db_session):
        esc = dias4

        resp = client_as(esc["off"]).post(
            _url_nuevo(_D1),
            data=_form(visibility="bookable", capacity="4", capacity_total="999"))

        assert resp.status_code == 200, resp.text[:300]
        db_session.expire_all()
        filas = _windows_de(db_session, esc["dias"][_D1].id)
        assert len(filas) == 1
        assert filas[0].capacity == 4
        assert filas[0].visibility == "bookable"


class TestCopiarConDias:
    """`space_copy` exige `dias` (D9, spec §5)."""

    def test_copiar_sin_dias_responde_400(self, dias4, client_as, db_session,
                                          make_review_window):
        esc = dias4
        w = make_review_window(esc["dias"][_D1], esc["off"], start="09:00",
                               end="14:00", position=esc["pos"])

        resp = client_as(esc["off"]).post(_url_copiar(w.id, _D1))

        assert resp.status_code == 400
        assert unquote(resp.headers.get("X-Tt-Error", "")) == "Elige al menos un día."
        assert _windows_de(db_session, esc["dias"][_D2].id) == []

    def test_copiar_con_dias_crea_solo_en_los_elegidos(
            self, dias4, client_as, db_session, make_review_window):
        esc = dias4
        w = make_review_window(esc["dias"][_D1], esc["off"], start="09:00",
                               end="14:00", position=esc["pos"])

        resp = client_as(esc["off"]).post(
            _url_copiar(w.id, _D1), data={"dias": [_D2.isoformat()]})

        assert resp.status_code == 200, resp.text[:300]
        mensaje, kind = _aviso(resp)
        assert mensaje == "Horario copiado a 1 día."
        assert kind == "success"

        db_session.expire_all()
        assert len(_windows_de(db_session, esc["dias"][_D2].id)) == 1
        # _D3/_D4 no se marcaron: copiar ya no toca "todos los días libres".
        assert _windows_de(db_session, esc["dias"][_D3].id) == []
        assert _windows_de(db_session, esc["dias"][_D4].id) == []

    def test_copiar_una_ventana_ajena_responde_404(
            self, dias4, client_as, db_session, make_officer, make_review_window):
        esc = dias4
        w = make_review_window(esc["dias"][_D1], esc["off"], start="09:00",
                               end="14:00", position=esc["pos"])
        ajeno, _ = make_officer([esc["prog"]], perm_codes=OFFICER_PERMS + (_ESPACIO_PERM,),
                                first_name="OTRO", last_name="ENCARGADO")

        resp = client_as(ajeno).post(
            _url_copiar(w.id, _D1), data={"dias": [_D2.isoformat()]})

        assert resp.status_code == 404
        db_session.expire_all()
        assert _windows_de(db_session, esc["dias"][_D2].id) == []


class TestMarcadoDelEditor:
    """El fieldset de crear y el `<details>` de copiar nunca salen a la vez:
    uno es del espacio NUEVO, el otro de uno YA guardado."""

    def test_editor_nuevo_ofrece_tambien_en_estos_dias_no_copiar(
            self, dias4, client_as):
        esc = dias4
        html = client_as(esc["off"]).get(
            "/titulatec/admin/appointments?v=espacios&date=%s&w=nuevo" % _D1.isoformat()
        ).text

        assert "También en estos días" in html
        assert 'name="dias"' in html
        assert "data-tt-check-all" in html
        assert "Copiar a otros días" not in html

    def test_editor_existente_ofrece_copiar_no_tambien_en_estos_dias(
            self, dias4, client_as, make_review_window):
        esc = dias4
        w = make_review_window(esc["dias"][_D1], esc["off"], start="09:00",
                               end="14:00", position=esc["pos"])

        html = client_as(esc["off"]).get(
            "/titulatec/admin/appointments?v=espacios&date=%s&w=%d"
            % (_D1.isoformat(), w.id)
        ).text

        assert "Copiar a otros días" in html
        assert 'name="dias"' in html
        assert "data-tt-check-all" in html
        assert "También en estos días" not in html
