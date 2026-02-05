"""Vistas administrativas de VisteTec."""
from flask import render_template
from itcj.core.utils.decorators import app_required
from itcj.apps.vistetec.routes.pages import admin_pages_bp


@admin_pages_bp.get('/dashboard')
@app_required('vistetec', roles=['admin'])
def dashboard():
    """Dashboard administrativo."""
    return render_template('vistetec/admin/dashboard.html',
                           title='Dashboard Admin')


@admin_pages_bp.get('/garments')
@app_required('vistetec', perms=['vistetec.garments.page.list'])
def garments():
    """Lista completa de prendas (todos los estados)."""
    return render_template('vistetec/admin/garments.html',
                           title='Gestión de Prendas')


@admin_pages_bp.get('/pantry')
@app_required('vistetec', perms=['vistetec.pantry.page.dashboard'])
def pantry():
    """Dashboard de despensa."""
    return render_template('vistetec/admin/pantry.html',
                           title='Despensa')


@admin_pages_bp.get('/campaigns')
@app_required('vistetec', perms=['vistetec.pantry.page.campaigns'])
def campaigns():
    """Gestión de campañas."""
    return render_template('vistetec/admin/campaigns.html',
                           title='Campañas')


@admin_pages_bp.get('/reports')
@app_required('vistetec', perms=['vistetec.reports.page.reports'])
def reports():
    """Reportes y estadísticas."""
    return render_template('vistetec/admin/reports.html',
                           title='Reportes')
