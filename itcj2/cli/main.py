#!/usr/bin/env python3
"""
Entry point principal del CLI de itcj2.

Uso:
    python -m itcj2.cli.main [COMMAND] [ARGS...]

Comandos disponibles:
    core init-db, core reset-db, core check-db, core init-themes, core execute-sql
    helpdesk load-inventory-csv
    agendatec seed-periods, agendatec activate-period, agendatec list-periods,
              agendatec import-students, agendatec sync-students-agendatec
    vistetec init-vistetec
"""
import click

from itcj2.cli.core import core_cli
from itcj2.cli.helpdesk import helpdesk_cli
from itcj2.cli.agendatec import agendatec_cli
from itcj2.cli.vistetec import vistetec_cli


def _register_all_models():
    """Importa todos los modelos para que SQLAlchemy resuelva todas las relationships."""
    import itcj2.core.models  # noqa: F401
    import itcj2.apps.helpdesk.models  # noqa: F401
    import itcj2.apps.agendatec.models  # noqa: F401
    import itcj2.apps.vistetec.models  # noqa: F401


@click.group()
def cli():
    """CLI de administración para la plataforma ITCJ (FastAPI)."""
    _register_all_models()


cli.add_command(core_cli)
cli.add_command(helpdesk_cli)
cli.add_command(agendatec_cli)
cli.add_command(vistetec_cli)


if __name__ == "__main__":
    cli()
