# itcj/apps/helpdesk/routes/pages/department_head.py
from flask import render_template, g, abort,redirect,url_for
from itcj.core.utils.decorators import app_required
from itcj.core.services import positions_service
from . import department_pages_bp

@department_pages_bp.get('/')
@app_required('helpdesk', positions=['department_head'])
def tickets():
    """Vista de tickets del departamento"""
    # Obtener el departamento del cual el usuario es jefe
    user_id = int(g.current_user['sub'])
    
    # Usar el servicio para obtener el departamento que maneja
    managed_department = positions_service.get_user_primary_managed_department(user_id)
    
    if not managed_department:
        abort(403, "No tienes un departamento asignado como jefe")
    
    department = managed_department['department']
    position = managed_department['position']
    
    return render_template('department_head/dashboard.html', 
                         title=f"Departamento - {department['name']}", 
                         department=department,
                         position=position,
                         assignment=managed_department['assignment'],
                         active_page='dashboard')

@department_pages_bp.get('/inventory')
@app_required('helpdesk', perms=['helpdesk.inventory.view_own_dept'])
def inventory():
    """Vista de inventario del departamento"""
    return redirect(url_for('helpdesk_pages.inventory_pages.items_list'))

@department_pages_bp.get('/tickets/<int:ticket_id>')
@app_required('helpdesk', perms=['helpdesk.tickets.department.read'])
def ticket_detail(ticket_id):
    """Vista de detalle de ticket del departamento"""
    # Obtener el departamento del cual el usuario es jefe
    user_id = int(g.current_user['sub'])
    
    # Usar el servicio para obtener el departamento que maneja
    managed_department = positions_service.get_user_primary_managed_department(user_id)
    
    if not managed_department:
        abort(403, "No tienes un departamento asignado como jefe")
    
    # TODO: Verificar que el ticket pertenece al departamento del usuario
    # ticket = TicketService.get_department_ticket(ticket_id, managed_department['department']['id'])
    # if not ticket:
    #     abort(404, "Ticket no encontrado en tu departamento")
    
    department = managed_department['department']
    position = managed_department['position']
    
    return render_template('department_head/ticket_detail.html', 
                         title=f"Ticket #{ticket_id}",
                         ticket_id=ticket_id,
                         department=department,
                         position=position,
                         assignment=managed_department['assignment'],
                         active_page='tickets')

@department_pages_bp.get('/reports')
@app_required('helpdesk', perms=['helpdesk.dashboard.department'])
def reports():
    """Vista de reportes del departamento"""
    # Obtener el departamento del cual el usuario es jefe
    user_id = int(g.current_user['sub'])
    
    # Usar el servicio para obtener el departamento que maneja
    managed_department = positions_service.get_user_primary_managed_department(user_id)
    
    if not managed_department:
        abort(403, "No tienes un departamento asignado como jefe")
    
    department = managed_department['department']
    position = managed_department['position']
    
    return render_template('department_head/reports.html', 
                         title=f"Reportes - {department['name']}", 
                         department=department,
                         position=position,
                         assignment=managed_department['assignment'],
                         active_page='reports')