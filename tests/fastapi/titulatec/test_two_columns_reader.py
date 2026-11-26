"""Lector de texto `utils/two_columns.leer_dos_columnas` (spec 2026-11-26 §5): lo
usan la CLI (`cargar-promedios`, `cargar-nips`, que lo envuelven en
`ClickException`, `test_cli_promedios.py`) y la carga por archivo de la bandeja
«Promedios». Sin BD."""
from __future__ import annotations

import pytest

from itcj2.apps.titulatec.utils.two_columns import leer_dos_columnas

ALIAS = {"promedio", "promedio_final"}


@pytest.mark.parametrize("texto", [
    "control;promedio\n99000001;85,5\n",
    "control\tpromedio\n99000001\t85,5\n",
    "﻿No. Control,Promedio Final\n99000001,\"85,5\"\n",
    "Número de control;promedio\r\n99000001;85,5\r\n",
])
def test_separadores_bom_y_encabezados(texto):
    assert leer_dos_columnas(texto, "promedio", ALIAS) == [("99000001", "85,5")]


def test_salta_filas_vacias_y_rellena_celdas_cortas():
    texto = "promedio;control\n85;99000001\n;\n\n90\n"
    assert leer_dos_columnas(texto, "promedio", ALIAS) == [
        ("99000001", "85"), ("", "90")]


def test_estricto_pega_las_celdas_sobrantes():
    texto = "control,promedio\n99000001,85,5\n"
    assert leer_dos_columnas(texto, "promedio", ALIAS) == [("99000001", "85")]
    assert leer_dos_columnas(texto, "promedio", ALIAS, estricto=True) == [
        ("99000001", "85 5")]


@pytest.mark.parametrize("texto", ["", "control;nip\n99000001;1234\n", "promedio\n85\n"])
def test_sin_columnas_es_value_error(texto):
    with pytest.raises(ValueError, match="«control» y «promedio»"):
        leer_dos_columnas(texto, "promedio", ALIAS)


def test_csv_roto_es_value_error_y_no_500():
    """Comilla sin cerrar en un campo enorme: `csv.Error` sale como `ValueError`."""
    texto = 'control,promedio\n20110001,"' + "x" * 200_000 + "\n"

    with pytest.raises(ValueError, match="comillas sin cerrar"):
        leer_dos_columnas(texto, "promedio", {"promedio"})
