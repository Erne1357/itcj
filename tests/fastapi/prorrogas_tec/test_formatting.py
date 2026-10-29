from datetime import date
from decimal import Decimal

import pytest

from itcj2.apps.prorrogas_tec.services.formatting import (
    fecha_corta, fecha_larga, nombre_oficial, pesos, semestre_label, split_amount,
)


def test_fecha_corta_como_en_las_cartas():
    assert fecha_corta(date(2026, 1, 13)) == "13/enero/2026"
    assert fecha_corta(date(2026, 2, 3)) == "03/febrero/2026"


def test_fecha_larga_como_en_las_cartas():
    assert fecha_larga(date(2026, 2, 26)) == "26 de febrero de 2026"
    assert fecha_larga(date(2026, 2, 3)) == "03 de febrero de 2026"


def test_pesos_con_miles_y_centavos():
    assert pesos(Decimal("3150")) == "$3,150.00"
    assert pesos(Decimal("1216")) == "$1,216.00"
    assert pesos(Decimal("500.5")) == "$500.50"


def test_nombre_oficial_apellidos_primero_en_mayusculas():
    assert nombre_oficial("Itzel  Guadalupe", "Payán", "Flores") == "PAYÁN FLORES ITZEL GUADALUPE"
    assert nombre_oficial("Roberto", "Cárdenas", None) == "CÁRDENAS ROBERTO"


def test_semestre_label():
    assert semestre_label(date(2026, 1, 26), date(2026, 6, 12)) == "enero – junio 2026"
    assert semestre_label(date(2026, 8, 17), date(2027, 1, 8)) == "agosto 2026 – enero 2027"


def test_split_amount_pesos_enteros_con_sobrante_a_los_primeros():
    assert split_amount(Decimal("3650"), 3) == [Decimal("1217"), Decimal("1217"), Decimal("1216")]
    assert split_amount(Decimal("3150"), 2) == [Decimal("1575"), Decimal("1575")]
    assert split_amount(Decimal("6400"), 1) == [Decimal("6400")]
    assert split_amount(Decimal("1000.50"), 2) == [Decimal("500"), Decimal("500.50")]
    assert sum(split_amount(Decimal("3651"), 3)) == Decimal("3651")


@pytest.mark.parametrize("total, n", [(Decimal("100"), 0), (Decimal("100"), 4), (Decimal("0"), 1)])
def test_split_amount_rechaza_entradas_fuera_de_rango(total, n):
    with pytest.raises(ValueError):
        split_amount(total, n)
