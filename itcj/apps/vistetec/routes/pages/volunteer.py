"""Vistas de voluntario: dashboard, registro de prendas, citas."""
from flask import render_template
from itcj.core.utils.decorators import login_required, app_required
from itcj.apps.vistetec.routes.pages import volunteer_pages_bp


@volunteer_pages_bp.get('/dashboard')
@app_required('vistetec', roles=['volunteer', 'admin'])
def dashboard():
    """Dashboard del voluntario."""
    return render_template('vistetec/volunteer/dashboard.html',
                           title='Dashboard Voluntario')


@volunteer_pages_bp.get('/garment/new')
@app_required('vistetec', perms=['vistetec.garments.page.create'])
def garment_form():
    """Formulario para registrar nueva prenda."""
    return render_template('vistetec/volunteer/garment_form.html',
                           title='Registrar Prenda')


@volunteer_pages_bp.get('/garment/<int:garment_id>/edit')
@app_required('vistetec', perms=['vistetec.garments.page.edit'])
def garment_edit(garment_id):
    """Formulario para editar prenda existente."""
    return render_template('vistetec/volunteer/garment_form.html',
                           title='Editar Prenda',
                           garment_id=garment_id)


@volunteer_pages_bp.get('/appointments')
@app_required('vistetec', perms=['vistetec.appointments.page.manage'])
def appointments():
    """Gestión de citas del voluntario."""
    return render_template('vistetec/volunteer/appointments.html',
                           title='Gestión de Citas')


@volunteer_pages_bp.get('/donations/register')
@app_required('vistetec', perms=['vistetec.donations.page.register'])
def register_donation():
    """Formulario para registrar donación."""
    return render_template('vistetec/volunteer/register_donation.html',
                           title='Registrar Donación')
