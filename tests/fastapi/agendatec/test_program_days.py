"""Días ofrecidos al alumno: filtro por carrera + candado de modalidad EAD.

Dos reglas distintas viven aquí y conviene no confundirlas:

1. **Filtro por carrera (permanente).** Un día solo se ofrece si el coordinador
   configuró horarios para ESA carrera y queda al menos uno libre. Antes se
   pintaban los días del período tal cual y el alumno los abría para
   encontrarlos vacíos.

2. **Candado de modalidad (temporal, `config/ead_day_gate.py`).** En el período
   20263 el sábado 29-ago es exclusivo de EAD y los días entre semana son
   exclusivos del resto. Cuando ese módulo se retire, los tests marcados
   `EAD_GATE` se van con él; los del filtro por carrera se quedan.

El invariante que sostiene todo: **la lista de días y la lista de horarios de un
día dicen lo mismo**. Un día visible cuyo `/slots` sale vacío es exactamente el
síntoma que esto arregla, así que cada test del listado tiene su espejo en el
detalle.
"""
from datetime import date, time
from unittest.mock import patch

import pytest

from itcj2.apps.agendatec.helpers import app_dt
from tests.conftest import make_jwt

# Días del escenario. `EAD_DAY` es el sábado que la institución reservó a EAD;
# `WEEKDAY` es un día entre semana del mismo período.
WEEKDAY = date(2026, 8, 26)
EAD_DAY = date(2026, 8, 29)
PAST_DAY = date(2026, 8, 20)

NOW = app_dt(date(2026, 8, 21), time(8, 0))


@pytest.fixture()
def frozen_now():
    """Congela `now_app` para que "día pasado" y "slot futuro" no dependan del reloj.

    Hay que parchear CADA módulo que importó `now_app` por nombre: `from ...
    import now_app` copia la referencia. `request_service` lo importa dentro de
    la función, así que ahí basta con el origen.
    """
    with patch("itcj2.apps.agendatec.helpers.now_app", return_value=NOW), \
         patch("itcj2.apps.agendatec.api.availability.now_app", return_value=NOW):
        yield


@pytest.fixture()
def ead_ctx(make_program, make_coordinator, make_period, headers_for):
    """Un coordinador con dos carreras —una EAD y otra no— y ambos días abiertos.

    Los dos días están habilitados en el período: la separación NO viene del
    período sino de la carrera, que es justo lo que se está probando.
    """
    def _make(days=(WEEKDAY, EAD_DAY)):
        normal = make_program("Ing. Industrial")
        ead = make_program("Ing. Industrial EAD")
        coord, user = make_coordinator([normal.id, ead.id])
        period = make_period(days=days)
        return {
            "coord": coord,
            "user": user,
            "normal": normal,
            "ead": ead,
            "period": period,
            "headers": headers_for(user, role="staff"),
        }

    return _make


def _student_headers(student):
    return {"Cookie": f"itcj_token={make_jwt(user_id=student.id, role='student')}"}


def _days_for(client, program_id, headers, expect=200):
    resp = client.get(
        f"/api/agendatec/v2/availability/program/{program_id}/days",
        headers=headers,
    )
    assert resp.status_code == expect, resp.text
    return resp.json()


def _slots_for(client, program_id, day, headers):
    resp = client.get(
        f"/api/agendatec/v2/availability/program/{program_id}/slots?day={day}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


# ===========================================================================
# Filtro por carrera (permanente)
# ===========================================================================
def test_only_days_with_configured_slots_for_that_program(
    client, ead_ctx, make_grid, make_student, frozen_now
):
    """El día que el coordinador no configuró para esa carrera no se ofrece."""
    ctx = ead_ctx()
    # Solo se configura el día entre semana, y solo para la carrera normal.
    make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10,
              [ctx["normal"].id], day=WEEKDAY)
    alum = make_student("20991000")

    data = _days_for(client, ctx["normal"].id, _student_headers(alum))
    assert data["days"] == [str(WEEKDAY)]
    # El período SÍ tiene los dos días: la exclusión es por carrera, no por período.
    assert data["enabled_days"] == [str(WEEKDAY), str(EAD_DAY)]


def test_day_scoped_to_another_program_is_not_offered(
    client, ead_ctx, make_grid, make_student, frozen_now
):
    """La rejilla existe ese día, pero su scope excluye a esta carrera."""
    ctx = ead_ctx()
    make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10,
              [ctx["ead"].id], day=WEEKDAY)
    alum = make_student("20991001")

    # La carrera normal no está en el scope de esa rejilla.
    assert _days_for(client, ctx["normal"].id, _student_headers(alum))["days"] == []


def test_fully_booked_day_disappears_from_the_strip(
    client, db_session, ead_ctx, make_grid, make_student, frozen_now
):
    """Sin horarios libres no hay nada que elegir: el día no se ofrece.

    Es la mitad de `lista = detalle` que justifica filtrar por `is_booked` y no
    solo por "el coordinador configuró algo".
    """
    ctx = ead_ctx()
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10,
                         [ctx["normal"].id], day=WEEKDAY)
    for s in slots:
        s.is_booked = True
    db_session.flush()
    alum = make_student("20991002")

    headers = _student_headers(alum)
    assert _days_for(client, ctx["normal"].id, headers)["days"] == []
    # Espejo en el detalle: si el día hubiera aparecido, saldría vacío.
    assert _slots_for(client, ctx["normal"].id, WEEKDAY, headers) == []


def test_past_days_are_not_offered(
    client, ead_ctx, make_grid, make_student, frozen_now
):
    """Un día ya pasado se descarta aunque tenga horarios libres configurados."""
    ctx = ead_ctx(days=(PAST_DAY, WEEKDAY))
    make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10,
              [ctx["normal"].id], day=PAST_DAY)
    make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10,
              [ctx["normal"].id], day=WEEKDAY)
    alum = make_student("20991003")

    assert _days_for(client, ctx["normal"].id, _student_headers(alum))["days"] == [str(WEEKDAY)]


def test_program_without_coordinator_gets_no_days(
    client, ead_ctx, make_program, make_student, frozen_now
):
    ctx = ead_ctx()
    huerfana = make_program("Carrera Sin Coordinador")
    alum = make_student("20991004")

    assert _days_for(client, huerfana.id, _student_headers(alum))["days"] == []


def test_unknown_program_is_404(client, ead_ctx, make_student, frozen_now):
    ead_ctx()
    alum = make_student("20991005")
    _days_for(client, 999_999, _student_headers(alum), expect=404)


# ===========================================================================
# EAD_GATE — candado de modalidad (temporal, retirar tras el período 20263)
# ===========================================================================
def test_ead_program_only_sees_the_ead_day(
    client, ead_ctx, make_grid, make_student, frozen_now
):
    """Aunque su coordinador configure los dos días, EAD solo ve el sábado."""
    ctx = ead_ctx()
    for d in (WEEKDAY, EAD_DAY):
        make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10,
                  [ctx["normal"].id, ctx["ead"].id], day=d)
    alum = make_student("20991006")

    assert _days_for(client, ctx["ead"].id, _student_headers(alum))["days"] == [str(EAD_DAY)]


def test_non_ead_program_never_sees_the_ead_day(
    client, ead_ctx, make_grid, make_student, frozen_now
):
    """Simétrico: el sábado es exclusivo de EAD, no "también de EAD"."""
    ctx = ead_ctx()
    for d in (WEEKDAY, EAD_DAY):
        make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10,
                  [ctx["normal"].id, ctx["ead"].id], day=d)
    alum = make_student("20991007")

    assert _days_for(client, ctx["normal"].id, _student_headers(alum))["days"] == [str(WEEKDAY)]


@pytest.mark.parametrize("program_key,day", [("normal", EAD_DAY), ("ead", WEEKDAY)])
def test_slots_endpoint_mirrors_the_gate(
    client, ead_ctx, make_grid, make_student, frozen_now, program_key, day
):
    """Ocultar el botón sería cosmético si el detalle siguiera devolviendo chips."""
    ctx = ead_ctx()
    for d in (WEEKDAY, EAD_DAY):
        make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10,
                  [ctx["normal"].id, ctx["ead"].id], day=d)
    alum = make_student("2099100" + ("8" if program_key == "normal" else "9"))

    assert _slots_for(client, ctx[program_key].id, day, _student_headers(alum)) == []


def test_booking_the_wrong_day_is_rejected_server_side(
    client, ead_ctx, make_grid, make_student, frozen_now, patched_session_local
):
    """Un POST armado a mano contra el día prohibido topa con la misma regla.

    `patched_session_local` es obligatorio aquí y no en los tests de listado:
    `require_admission_open` (helpers.py:326) abre su PROPIA `SessionLocal()` y
    por tanto no ve el periodo que `make_period` creó dentro del savepoint. Sin
    el parche, el resultado depende de qué tenga la BD por debajo — en la de dev
    hay un periodo ACTIVE real y el test pasaba por accidente; en la BD limpia
    del CI no hay ninguno y devuelve 503 no_active_period.
    """
    ctx = ead_ctx()
    _, ead_slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10,
                             [ctx["normal"].id, ctx["ead"].id], day=EAD_DAY)
    alum = make_student("20991010")

    resp = client.post(
        "/api/agendatec/v2/requests",
        headers=_student_headers(alum),
        json={
            "type": "APPOINTMENT",
            "program_id": ctx["normal"].id,   # carrera NO-EAD en el día de EAD
            "slot_id": ead_slots[0].id,
            "description": "Alta de materia",
        },
    )
    assert resp.status_code == 400, resp.text
    # El handler de errores del proyecto mete el `detail` del HTTPException bajo
    # la clave "error", y aquí ese detail ya es un dict: sale anidado.
    assert resp.json()["error"]["error"] == "day_not_allowed_for_program"


def test_booking_the_right_day_still_works(
    client, ead_ctx, make_grid, make_student, frozen_now, patched_session_local
):
    """El candado no puede bloquear al que sí tiene derecho a ese día.

    Ver la nota sobre `patched_session_local` en el test anterior.
    """
    ctx = ead_ctx()
    _, ead_slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10,
                             [ctx["normal"].id, ctx["ead"].id], day=EAD_DAY)
    alum = make_student("20991011")

    resp = client.post(
        "/api/agendatec/v2/requests",
        headers=_student_headers(alum),
        json={
            "type": "APPOINTMENT",
            "program_id": ctx["ead"].id,
            "slot_id": ead_slots[0].id,
            "description": "Alta de materia",
        },
    )
    assert resp.status_code == 201, resp.text


# ===========================================================================
# EAD_GATE — la regla pura, sin BD
# ===========================================================================
@pytest.mark.parametrize("name,expected", [
    ("Ing. Sistemas computacionales EAD", True),
    ("Ing. Gestión Empresarial EAD", True),
    ("Lic. Administración EAD", True),
    ("Ing. Industrial EAD", True),
    ("Ing. Industrial", False),
    ("Ing. Sistemas computacionales CAMPUS II", False),
    # No basta con terminar en esas 3 letras pegadas a otra cosa.
    ("Ing. en Materiales SEAD", False),
    ("", False),
    (None, False),
])
def test_is_ead_program(name, expected):
    from itcj2.apps.agendatec.config.ead_day_gate import is_ead_program
    assert is_ead_program(name) is expected


def test_gate_does_not_opine_about_other_days():
    """Fuera del sábado reservado, el candado deja decidir a la configuración."""
    from itcj2.apps.agendatec.config.ead_day_gate import day_allowed_for_program
    otro = date(2026, 8, 27)
    assert day_allowed_for_program(otro, "Ing. Industrial") is True
    # …salvo para EAD, cuyo acceso está acotado a sus días exclusivos.
    assert day_allowed_for_program(otro, "Ing. Industrial EAD") is False
