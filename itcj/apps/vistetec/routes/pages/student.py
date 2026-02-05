"""Vistas de estudiante: catálogo y detalle de prendas."""
from flask import render_template
from itcj.core.utils.decorators import login_required, app_required
from itcj.apps.vistetec.routes.pages import student_pages_bp


@student_pages_bp.get('/catalog')
@app_required('vistetec', perms=['vistetec.catalog.page.view'])
def catalog():
    """Página principal del catálogo de prendas."""
    return render_template('vistetec/student/catalog.html', title='Catálogo')


@student_pages_bp.get('/catalog/<int:garment_id>')
@app_required('vistetec', perms=['vistetec.catalog.page.detail'])
def garment_detail(garment_id):
    """Detalle de una prenda del catálogo."""
    return render_template('vistetec/student/garment_detail.html',
                           title='Detalle de Prenda',
                           garment_id=garment_id)


@student_pages_bp.get('/my-appointments')
@app_required('vistetec', perms=['vistetec.appointments.page.my'])
def my_appointments():
    """Citas del estudiante."""
    return render_template('vistetec/student/my_appointments.html',
                           title='Mis Citas')


@student_pages_bp.get('/my-donations')
@app_required('vistetec', perms=['vistetec.donations.page.my'])
def my_donations():
    """Donaciones del estudiante."""
    return render_template('vistetec/student/my_donations.html',
                           title='Mis Donaciones')
