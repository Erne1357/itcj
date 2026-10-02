"""Textos de los DML de `database/DML/titulatec/` que comparten las pruebas de
la CLI: `test_cli_mail_tasks.py` (el 17 de `mail_2026_09/`) y
`test_cli_biblioteca_caja.py` (el 23 de `biblioteca_2026_10/`, que copia
textos del 17).

`database/` está gitignored y nunca llega a CI: aquí no se lee nada al
importar; quien llame estas funciones va marcado `requires_dml`.
"""
import re

from itcj2.cli.titulatec import DML_TITULATEC, _DML_MAIL_2026_09_DIR

DML_17 = DML_TITULATEC / _DML_MAIL_2026_09_DIR / "17_insert_email_tasks.sql"


def unir_literales(sql: str) -> str:
    """Literales de SQL adyacentes (separados por un salto de línea) son UNA
    cadena: los une para comparar el texto completo contra su fuente."""
    return re.sub(r"'\s*\n\s*'", "", sql)


def periodica_de_recordatorios_del_17() -> str:
    """La descripción de 'TitulaTec: recordatorios por correo' que el DML 17
    siembra en `core_periodic_tasks` (el INSERT: name, task_name, cron,
    kwargs '{}', TRUE y luego la descripción)."""
    unido = unir_literales(DML_17.read_text(encoding="utf-8"))
    fila = re.search(r"'TitulaTec: recordatorios por correo',\s*'titulatec\.email_reminders',"
                     r"\s*'[^']*',\s*'\{\}',\s*TRUE,\s*'([^']*)'", unido)
    assert fila, "no se encontró la periódica de recordatorios en el DML 17"
    return fila.group(1)
