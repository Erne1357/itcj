#!/usr/bin/env python3
"""
Comandos Flask para AgendaTec - Inicialización de períodos académicos
"""
import click
from flask import current_app
from flask.cli import with_appcontext
from datetime import date, datetime
from zoneinfo import ZoneInfo
from itcj.core.extensions import db
from itcj.core.models.academic_period import AcademicPeriod
from itcj.apps.agendatec.models.period_enabled_day import PeriodEnabledDay
from itcj.apps.agendatec.models.request import Request


@click.command('seed-periods')
@with_appcontext
def seed_periods_command():
    """
    Crea períodos académicos iniciales y migra solicitudes existentes.

    Crea dos períodos:
    1. Ago-Dic 2025 (INACTIVE) - migra todas las solicitudes existentes aquí
    2. Ene-Jun 2026 (ACTIVE) - período activo para nuevas solicitudes

    Configura días habilitados: 25, 26, 27 de agosto para el primer período.
    """
    click.echo('🗓️  Iniciando creación de períodos académicos...\n')

    tz = ZoneInfo("America/Ciudad_Juarez")

    # Verificar si ya existen períodos
    existing_count = db.session.query(AcademicPeriod).count()
    if existing_count > 0:
        click.echo(f'⚠️  Ya existen {existing_count} período(s) en la base de datos.')
        if not click.confirm('¿Deseas continuar de todas formas?'):
            click.echo('❌ Operación cancelada.')
            return

    try:
        # ==================== PERÍODO 1: Ago-Dic 2025 ====================
        click.echo('📅 Creando período: Ago-Dic 2025')

        period1 = AcademicPeriod(
            name="Ago-Dic 2025",
            start_date=date(2025, 8, 19),
            end_date=date(2025, 12, 13),
            student_admission_deadline=datetime(2025, 8, 27, 18, 0, 0, tzinfo=tz),
            status="INACTIVE"
        )
        db.session.add(period1)
        db.session.flush()  # Para obtener el ID

        # Configurar días habilitados para Ago-Dic 2025
        enabled_days_p1 = [
            date(2025, 8, 25),
            date(2025, 8, 26),
            date(2025, 8, 27)
        ]

        for day in enabled_days_p1:
            enabled_day = PeriodEnabledDay(period_id=period1.id, day=day)
            db.session.add(enabled_day)

        click.echo(f'   ✓ Período creado (ID: {period1.id})')
        click.echo(f'   ✓ Días habilitados: {", ".join(d.strftime("%d-%b") for d in enabled_days_p1)}')

        # Migrar solicitudes existentes a este período
        requests_to_migrate = db.session.query(Request).filter(Request.period_id == None).all()

        if requests_to_migrate:
            click.echo(f'\n📦 Migrando {len(requests_to_migrate)} solicitudes existentes...')
            for req in requests_to_migrate:
                req.period_id = period1.id
            click.echo(f'   ✓ Solicitudes migradas al período "Ago-Dic 2025"')
        else:
            click.echo('   ℹ️  No hay solicitudes sin período para migrar')

        # ==================== PERÍODO 2: Ene-Jun 2026 ====================
        click.echo('\n📅 Creando período: Ene-Jun 2026')

        period2 = AcademicPeriod(
            name="Ene-Jun 2026",
            start_date=date(2026, 1, 19),
            end_date=date(2026, 6, 12),
            student_admission_deadline=datetime(2026, 1, 27, 18, 0, 0, tzinfo=tz),
            status="ACTIVE"
        )
        db.session.add(period2)
        db.session.flush()

        # Configurar días habilitados para Ene-Jun 2026 (ejemplo: 26, 27, 28 de enero)
        enabled_days_p2 = [
            date(2026, 1, 26),
            date(2026, 1, 27),
            date(2026, 1, 28)
        ]

        for day in enabled_days_p2:
            enabled_day = PeriodEnabledDay(period_id=period2.id, day=day)
            db.session.add(enabled_day)

        click.echo(f'   ✓ Período creado (ID: {period2.id}) - ACTIVO')
        click.echo(f'   ✓ Días habilitados: {", ".join(d.strftime("%d-%b") for d in enabled_days_p2)}')

        # Commit de todos los cambios
        db.session.commit()

        click.echo('\n' + '='*60)
        click.echo('✅ Períodos académicos creados exitosamente')
        click.echo('='*60)
        click.echo(f'\n📊 Resumen:')
        click.echo(f'   • Período INACTIVO: "Ago-Dic 2025" (ID: {period1.id})')
        click.echo(f'     - Solicitudes migradas: {len(requests_to_migrate)}')
        click.echo(f'     - Días habilitados: {len(enabled_days_p1)}')
        click.echo(f'   • Período ACTIVO: "Ene-Jun 2026" (ID: {period2.id})')
        click.echo(f'     - Días habilitados: {len(enabled_days_p2)}')
        click.echo('\n💡 Notas importantes:')
        click.echo('   1. El período "Ene-Jun 2026" está ACTIVO para nuevas solicitudes')
        click.echo('   2. Todas las solicitudes antiguas se asignaron a "Ago-Dic 2025"')
        click.echo('   3. Puedes modificar los días habilitados desde la interfaz admin')
        click.echo('   4. Solo puede haber UN período ACTIVO a la vez')

    except Exception as e:
        db.session.rollback()
        click.echo(f'\n❌ Error al crear períodos: {str(e)}')
        raise


@click.command('activate-period')
@click.argument('period_id', type=int)
@with_appcontext
def activate_period_command(period_id):
    """
    Activa un período académico específico (desactiva el actual).

    Uso: flask activate-period <period_id>
    """
    from itcj.core.services.period_service import activate_period as activate_service

    click.echo(f'🔄 Activando período ID: {period_id}...')

    try:
        # Usar el servicio de activación
        period = activate_service(period_id)

        if period:
            click.echo(f'✅ Período "{period.name}" activado correctamente')
            click.echo(f'   • ID: {period.id}')
            click.echo(f'   • Rango: {period.start_date} a {period.end_date}')
            click.echo(f'   • Admisión hasta: {period.student_admission_deadline}')
        else:
            click.echo(f'❌ No se pudo activar el período ID: {period_id}')

    except Exception as e:
        click.echo(f'❌ Error: {str(e)}')
        raise


@click.command('list-periods')
@with_appcontext
def list_periods_command():
    """Lista todos los períodos académicos."""
    click.echo('📋 Períodos Académicos:\n')

    periods = db.session.query(AcademicPeriod).order_by(AcademicPeriod.start_date.desc()).all()

    if not periods:
        click.echo('   ℹ️  No hay períodos registrados')
        click.echo('   💡 Ejecuta: flask seed-periods')
        return

    for p in periods:
        status_emoji = {
            'ACTIVE': '🟢',
            'INACTIVE': '⚪',
            'ARCHIVED': '📦'
        }.get(p.status, '❓')

        enabled_days_count = db.session.query(PeriodEnabledDay).filter_by(period_id=p.id).count()
        requests_count = db.session.query(Request).filter_by(period_id=p.id).count()

        click.echo(f'{status_emoji} {p.name} (ID: {p.id})')
        click.echo(f'   Estado: {p.status}')
        click.echo(f'   Rango: {p.start_date} → {p.end_date}')
        click.echo(f'   Admisión hasta: {p.student_admission_deadline}')
        click.echo(f'   Días habilitados: {enabled_days_count}')
        click.echo(f'   Solicitudes: {requests_count}')
        click.echo()


def register_agendatec_commands(app):
    """Registra todos los comandos de AgendaTec en la aplicación Flask."""
    app.cli.add_command(seed_periods_command)
    app.cli.add_command(activate_period_command)
    app.cli.add_command(list_periods_command)
