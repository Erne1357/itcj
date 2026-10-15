"""`titulatec init-titulatec`: siembra completa de la app (`SEED_FILES`) y sus verificaciones."""
import click

from itcj2.cli.titulatec._common import SEED_FILES, _run_sql_files, titulatec_cli
from itcj2.cli.titulatec.verificaciones import (
    _verify_computer_center,
    _verify_survey_2026_09,
    _verify_titulacion,
)


@titulatec_cli.command("init-titulatec")
def init_titulatec_command():
    """Inicializa la app de TitulaTec completamente.

    Ejecuta en orden los seeders de database/DML/titulatec/ (ver SEED_FILES).
    Idempotentes, pero el 03 revoca en cada corrida `cohort.*` a
    `titulatec_school_services` (las convocatorias son de la JEFATURA de
    Servicios Escolares, no del operativo) y todo lo de titulatec a `student`
    (el alumno es `graduate` desde 2026-09-15).

    Aborta si falta cualquier archivo: sembrar a medias deja la app en 404.

    El 10 (dentro de `survey_2026_09/`) también revoca en cada corrida
    `titulatec.survey.%` a la jefatura de Servicios Escolares: esa bandeja
    pasó a Gestión Tecnológica y Vinculación (GTV, rol `titulatec_tech_management`)
    desde 2026-09-15 (spec 2026-09-15-titulatec-liberacion-gtv).

    Al terminar VERIFICA contra la base con `_verify_survey_2026_09` —el mismo
    chequeo que ya traía `load-survey-2026-09`—: los 11 permisos del delta, los
    9 grants de GTV, el recorte de `titulatec.survey.%` a la jefatura, el
    puesto de ventanilla y sus exactamente 2 filas puesto→rol, y el formulario
    'egresados' abierto. Y con `_verify_titulacion` (spec
    2026-09-21-titulatec-dpto-titulacion): el departamento `titulacion`
    colgado de `prof_studies_div`, sus 2 puestos, los 2 permisos de la bandeja
    de liberados, el grant EXACTO del rol `titulatec_titulacion` (16 desde el
    2026-10-07: sin Bandeja, Procesos, Documentos, Actos protocolarios ni el
    expediente completo; con el resumido), Liberados en los dos roles de
    Servicios Escolares, sus
    exactamente 2 filas puesto→rol (y 1 la del rol viejo, `head_prof_studies_div`),
    y que `titulatec_titulaciones` tenga el reparto PLENO (25) que el usuario
    pidió al revertir el recorte D6/D7 — dictamen, ceremony y cohort incluidos,
    no solo supervisión. Y con `_verify_computer_center` (spec
    2026-09-24-titulatec-accesos-centro-computo): el rol
    `titulatec_computer_center` con EXACTAMENTE sus 4 permisos de la bandeja
    de Accesos, el mapeo puesto→rol con `head_comp_center` y
    `secretary_comp_center` (contiene al menos, igual que el resto de mapeos
    de este comando) y `head_comp_center` con el rol `admin` en titulatec.
    Acumula los problemas de LOS TRES verifies antes de abortar: un error del
    primero no debe esconder uno de los otros.

    Aborta si algo no aterrizó. Antes este comando no comprobaba nada: en una
    base destino sin `head_tech_management` o sin el departamento
    `tech_management`, los `INSERT ... SELECT` de grants insertan 0 filas y el
    comando salía en verde de todos modos — y el runbook de lanzamiento
    (`alembic upgrade head` → `init-titulatec` → asignar a la persona) nunca
    corre `load-survey-2026-09` por separado para atraparlo.

    Prerequisitos:
      - Tablas titulatec_* existen (alembic upgrade head).
      - 04 antes que 04b antes que 05: el mapeo puesto→rol necesita los
        puestos ya creados (incluidos `external_service_tech_management` de
        GTV y `head_titulacion`/`aux_titulacion` del Departamento de
        Titulación).
    """
    click.echo("🎓 Inicializando app de TitulaTec...")
    click.echo()
    try:
        _run_sql_files(SEED_FILES)
    except Exception as e:
        click.echo(f"\n💥 Error durante init-titulatec: {e}")
        raise

    problemas = _verify_survey_2026_09() + _verify_titulacion() + _verify_computer_center()
    if problemas:
        click.echo()
        for p in problemas:
            click.echo(click.style(f"ERROR: {p}", fg="red"), err=True)
        raise click.Abort()

    click.echo()
    click.echo("🎉 init-titulatec completado.")
