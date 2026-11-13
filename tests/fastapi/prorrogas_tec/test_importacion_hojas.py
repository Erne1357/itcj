from datetime import date
from decimal import Decimal as D

import pytest

from itcj2.apps.prorrogas_tec.importacion.hojas import leer_libro

ENC_2026 = ["No.", "FECHA", "No. De Control", "NOMBRE", "CARRERA", "ENERO", "IMPORTE", "", "FEBRERO", "IMPORTE", ""]


def test_mensual_con_continuacion_y_banderas(libro):
    ruta = libro({"Inscripción Enero - Junio 2026": [
        ENC_2026,
        [None, "12 de enero de 2026", 99110001, "Alumna Uno", "Contador Público", "16 de enero de 2026", 1000, 1,
         "06 de febrero de 2026", 1000, 0],
        [None, None, None, None, None, "26 de enero de 2026", 500, None],
    ]})
    s, = leer_libro(ruta)
    assert s.ref == "Inscripción Enero - Junio 2026#2" and s.semestre == "enero – junio 2026"
    assert s.carrera == "Contador publico" and s.no_control == "99110001"
    assert [(p.vencimiento, p.monto, p.pagado) for p in s.parcialidades] == [
        (date(2026, 1, 16), D("1000.00"), True), (date(2026, 2, 6), D("1000.00"), False),
        (date(2026, 1, 26), D("500.00"), True)]
    assert not s.tiene_problema


def test_celda_2024_sin_anio(libro):
    ruta = libro({"Enero Junio 2024": [
        ["No. De Control", "NOMBRE", "CARRERA", "ENERO", "FEBRERO"],
        [99110002, "Alumno Dos", "Ingeniería Industrial", "30 de enero $2,900.00", "29 de febrero $600.00"],
    ]})
    s, = leer_libro(ruta)
    assert [(p.vencimiento, p.monto, p.pagado) for p in s.parcialidades] == [
        (date(2024, 1, 30), D("2900.00"), True), (date(2024, 2, 29), D("600.00"), True)]


def test_importe_unico(libro):
    ruta = libro({"Inscripción Agosto-Dic 2024": [
        ["FECHA", "No. De Control", "NOMBRE", "CARRERA", "IMPORTE"],
        [date(2024, 8, 12), 99110003, "Alumno Tres", "Ingeniería en Gestión Empresarial EAD", "$3,.000.00"],
    ]})
    s, = leer_libro(ruta)
    assert s.semestre == "agosto – diciembre 2024" and s.carrera == "Ing. Gestión Empresarial EAD"
    assert [(p.vencimiento, p.monto, p.pagado) for p in s.parcialidades] == [(date(2024, 8, 12), D("3000.00"), True)]


def test_celda_doble_se_separa_si_cuadra_y_si_no_es_problema(libro):
    enc = ["No.", "FECHA", "No. De Control", "NOMBRE", "CARRERA", "ENERO", "IMPORTE", ""]
    ruta = libro({"Inscripción Enero-Junio 2025": [
        enc,
        [1, "14 de enero de 2025", 99110004, "A", "Contador Público", "14/01/2025, 20/01/25", "$1,100,00  $1,000,00", 1],
        [2, "14 de enero de 2025", 99110005, "B", "Contador Público", "16 de enero de 2025  30 de enero de 2025", 750, 1],
    ]})
    a, b = leer_libro(ruta)
    assert [p.monto for p in a.parcialidades] == [D("1100.00"), D("1000.00")] and not a.tiene_problema
    assert b.tiene_problema and b.parcialidades[0].problema == "fechas e importes no cuadran"


def test_controles_invalidos_y_repetidos_y_hoja_desconocida(libro):
    ruta = libro({
        "Inscripción Enero - Junio 2026": [ENC_2026,
            [None, "12 de enero de 2026", 12345, "A", "Contador Público", "16 de enero de 2026", 1000, 1],
            [None, "12 de enero de 2026", 99110006, "B", "Contador Público", "16 de enero de 2026", 1000, 1],
            [None, "12 de enero de 2026", 99110006, "C", "Contador Público", "16 de enero de 2026", 1000, 1]],
        "Otra cosa": [["X"], [1]],
    })
    sols = leer_libro(ruta)
    assert [s.problema for s in sols] == ["número de control inválido", "número de control repetido en la hoja",
                                          "número de control repetido en la hoja", "hoja desconocida"]


def test_continuacion_sin_estudiante_previo(libro):
    ruta = libro({"Inscripción Enero - Junio 2026": [
        ENC_2026,
        [None, None, None, None, None, "16 de enero de 2026", 1000, 1],
    ]})
    s, = leer_libro(ruta)
    assert s.problema == "renglón sin estudiante" and s.ref == "Inscripción Enero - Junio 2026#2"
    assert [(p.vencimiento, p.monto) for p in s.parcialidades] == [(date(2026, 1, 16), D("1000.00"))]


def test_parcialidad_sin_importe(libro):
    ruta = libro({"Inscripción Enero - Junio 2026": [
        ENC_2026,
        [None, "12 de enero de 2026", 99110007, "D", "Contador Público", "16 de enero de 2026", None, 1],
    ]})
    s, = leer_libro(ruta)
    p, = s.parcialidades
    assert (p.problema, p.origen, p.valor_original) == (
        "parcialidad sin importe", "Inscripción Enero - Junio 2026!F2", "16 de enero de 2026 |  | 1")
    assert (p.vencimiento, p.monto, p.pagado) == (None, None, None) and s.tiene_problema


def test_dato_que_no_se_lee_no_se_pierde(libro):
    # un renglón sin control con nombre es continuación, pero el nombre suelto va a revisión
    ruta = libro({"Inscripción Enero - Junio 2026": [
        ENC_2026 + ["NOTAS"],
        [None, "12 de enero de 2026", 99110008, "E", "Contador Público", "16 de enero de 2026", 1000, 1,
         None, None, None, "pagó en caja"],
        [None, None, None, "F", None, "26 de enero de 2026", 500, 1],
    ]})
    s, = leer_libro(ruta)
    assert [(p.problema, p.valor_original, p.origen) for p in s.parcialidades if p.problema] == [
        ("dato sin interpretar", "pagó en caja", "Inscripción Enero - Junio 2026!L2"),
        ("dato sin interpretar", "F", "Inscripción Enero - Junio 2026!D3")]


H_2025 = "Inscripción Enero-Junio 2025"
ENC_2025 = (["No.", "FECHA", "No. De Control", "NOMBRE", "CARRERA"]
            + [c for m in ("ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO") for c in (m, "IMPORTE", "")]
            + ["", "", ""])


def test_bandera_sola_con_texto_es_problema_y_con_0_o_1_no(libro):
    ruta = libro({H_2025: [
        ENC_2025,
        [1, "14 de enero de 2025", 99110009, "G", "Contador Público", None, None, "cancelada", None, None, 1],
        [2, "14 de enero de 2025", 99110010, "H", "Contador Público", None, None, 0, None, None, 1],
    ]})
    g, h = leer_libro(ruta)
    assert [(p.problema, p.valor_original, p.origen) for p in g.parcialidades] == [
        ("bandera ilegible", " |  | cancelada", f"{H_2025}!F2")]
    assert h.parcialidades == [] and not h.tiene_problema


@pytest.mark.parametrize("hueco", [[None], [2]])  # renglón en blanco, o solo con No.
def test_pago_despues_de_un_hueco_no_se_pega_al_alumno_de_arriba(libro, hueco):
    ruta = libro({H_2025: [
        ENC_2025,
        [1, "14 de enero de 2025", 99110011, "I", "Contador Público", "16 de enero de 2025", 1000, 1],
        hueco,
        [3, None, None, None, None, "30 de enero de 2025", 500, 1],
    ]})
    a, b = leer_libro(ruta)
    assert [p.vencimiento for p in a.parcialidades] == [date(2025, 1, 16)] and not a.tiene_problema
    assert b.problema == "renglón sin estudiante" and b.ref == f"{H_2025}#4"
    assert [p.vencimiento for p in b.parcialidades] == [date(2025, 1, 30)]


def test_columnas_finales_sin_encabezado_y_vacias_no_marcan_nada(libro):
    fila = [1, "14 de enero de 2025", 99110012, "J", "Contador Público"] + [None] * 15 + [
        "16 de junio de 2025", 1000, 1, "", "", ""]
    s, = leer_libro(libro({H_2025: [ENC_2025, fila]}))
    assert [(p.vencimiento, p.monto) for p in s.parcialidades] == [(date(2025, 6, 16), D("1000.00"))]
    assert not s.tiene_problema


def test_celda_con_dos_pagos_separados_por_espacio(libro):
    ruta = libro({"Enero Junio 2024": [
        ["No. De Control", "NOMBRE", "CARRERA", "ENERO"],
        [99110013, "K", "Ingeniería Industrial", "3 de enero $1,000.00   20 de enero $500.00"],
    ]})
    s, = leer_libro(ruta)
    assert [(p.vencimiento, p.monto) for p in s.parcialidades] == [
        (date(2024, 1, 3), D("1000.00")), (date(2024, 1, 20), D("500.00"))]
    assert s.fecha_solicitud == date(2024, 1, 3) and not s.tiene_problema


def test_repetido_conserva_el_problema_que_ya_tenia(libro):
    ruta = libro({H_2025: [
        ENC_2025,
        [1, "14 de enero de 2025", 99110014, "L", "Carrera Rara", "16 de enero de 2025", 1000, 1],
        [2, "14 de enero de 2025", 99110014, "M", "Contador Público", "16 de enero de 2025", 1000, 1],
    ]})
    assert [s.problema for s in leer_libro(ruta)] == ["carrera sin equivalencia",
                                                      "número de control repetido en la hoja"]


def test_fecha_fuera_del_semestre(libro):  # M2
    ruta = libro({"Inscripción Agosto-Diciembre 25": [
        ["No.", "FECHA", "No. De Control", "NOMBRE", "CARRERA", "AGOSTO", "IMPORTE", ""],
        [1, "12 de agosto de 2025", 99110015, "N", "Contador Público", "15 de enero", 1000, 1],  # enero de 2025
        [2, "12 de agosto de 2027", 99110016, "O", "Contador Público", "15 de agosto de 2025", 1000, 1],
    ]})
    a, b = leer_libro(ruta)
    assert [(p.problema, p.valor_original) for p in a.parcialidades] == [
        ("fecha fuera del semestre", "15 de enero | 1000 | 1")]
    assert b.problema == "fecha fuera del semestre" and not b.parcialidades[0].problema


def test_importe_sospechoso(libro):  # M2
    ruta = libro({"Inscripción Enero - Junio 2026": [
        ENC_2026,
        [None, "12 de enero de 2026", 99110017, "P", "Contador Público", "16 de enero de 2026", "$1,55", 1,
         "06 de febrero de 2026", 1000, 1],
    ]})
    s, = leer_libro(ruta)
    assert [p.problema for p in s.parcialidades] == ["importe sospechoso", ""]
