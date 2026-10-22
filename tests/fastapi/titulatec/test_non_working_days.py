"""Calendario de dias inhabiles (fase 5, Task 2): `NonWorkingDayService`.

Spec 2026-10-22-titulatec-fase5-revision-sinodales §9. La bitacora es
inmutable y la BD de dev compartida: se consulta con `audit_query`.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from itcj2.apps.titulatec.models import NonWorkingDay
from itcj2.apps.titulatec.services.non_working_day_service import NonWorkingDayService as S
from tests.fastapi.titulatec.conftest import audit_query

pytestmark = pytest.mark.usefixtures("audit_mark")

# Año sintetico: la base de dev puede traer dias reales de 2026.
LUN = date(2091, 3, 5)            # 2091-03-05 es lunes
assert LUN.weekday() == 0


def _filas(db, ini, fin):
    return (db.query(NonWorkingDay)
            .filter(NonWorkingDay.day >= ini, NonWorkingDay.day <= fin)
            .order_by(NonWorkingDay.day).all())


def _bitacora(db, accion):
    return audit_query(db).filter_by(action=accion).all()


def test_holidays_vacio_y_con_filas(db_session, make_non_working_day):
    base = S.holidays(db_session)
    assert isinstance(base, frozenset)
    make_non_working_day(LUN, "Prueba")
    assert LUN in S.holidays(db_session)


def test_add_range_salta_fin_de_semana_y_repetidos(db_session, make_user):
    actor = make_user()
    S.add_range(db_session, actor.id, start=LUN + timedelta(days=1),
                end=LUN + timedelta(days=1), description="Previo")      # martes
    r = S.add_range(db_session, actor.id, start=LUN, end=LUN + timedelta(days=7),
                    description="  Vacaciones  ")
    # lun..lun siguiente: 6 habiles (lun, mar, mie, jue, vie, lun), 2 de fin de semana
    assert r == {"added": 5, "weekend": 2, "existing": 1}
    filas = _filas(db_session, LUN, LUN + timedelta(days=7))
    assert len(filas) == 6
    assert {f.day.weekday() for f in filas} <= {0, 1, 2, 3, 4}
    assert all(f.created_by_id == actor.id for f in filas)
    assert "Vacaciones" in {f.description for f in filas}      # strip()
    martes = _filas(db_session, LUN + timedelta(days=1), LUN + timedelta(days=1))[0]
    assert martes.description == "Previo"                      # el repetido no se pisa


@pytest.mark.parametrize("ini,fin,desc", [
    (LUN + timedelta(days=3), LUN, "x"),                       # invertido
    (LUN, LUN + timedelta(days=120), "x"),                     # 121 dias
    (LUN, LUN, ""),                                            # descripcion vacia
    (LUN, LUN, "   "),
    (LUN, LUN, "x" * 151),
    (None, LUN, "x"),
])
def test_add_range_rechaza_sin_escribir(db_session, make_user, ini, fin, desc):
    actor = make_user()
    antes = db_session.query(NonWorkingDay).count()
    marca = len(_bitacora(db_session, "non_working_day.added"))
    with pytest.raises(ValueError) as e:
        S.add_range(db_session, actor.id, start=ini, end=fin, description=desc)
    assert str(e.value)
    assert db_session.query(NonWorkingDay).count() == antes
    assert len(_bitacora(db_session, "non_working_day.added")) == marca


def test_add_range_acepta_exactamente_120_dias_y_deja_una_fila_de_bitacora(db_session, make_user):
    actor = make_user()
    fin = LUN + timedelta(days=S.MAX_RANGE_DAYS - 1)
    r = S.add_range(db_session, actor.id, start=LUN, end=fin, description="Largo")
    assert r["added"] + r["weekend"] + r["existing"] == S.MAX_RANGE_DAYS
    filas = _bitacora(db_session, "non_working_day.added")
    assert len(filas) == 1
    p = filas[0].payload
    assert p["start"] == LUN.isoformat() and p["end"] == fin.isoformat()
    assert p["added"] == r["added"] and p["description"] == "Largo"
    assert filas[0].module == "calendar"


def test_remove_range_y_list_year(db_session, make_user):
    actor = make_user()
    S.add_range(db_session, actor.id, start=LUN, end=LUN + timedelta(days=4),
                description="Semana")
    lista = S.list_year(db_session, 2091)
    assert [x["day"] for x in lista] == sorted(x["day"] for x in lista)
    assert {"id", "day", "description"} == set(lista[0])
    assert len([x for x in lista if LUN <= x["day"] <= LUN + timedelta(days=4)]) == 5
    n = S.remove_range(db_session, actor.id, start=LUN, end=LUN + timedelta(days=1))
    assert n == 2
    assert len(_filas(db_session, LUN, LUN + timedelta(days=4))) == 3
    filas = _bitacora(db_session, "non_working_day.removed")
    assert len(filas) == 1 and filas[0].payload["removed"] == 2
    with pytest.raises(ValueError):
        S.remove_range(db_session, actor.id, start=LUN + timedelta(days=3), end=LUN)
