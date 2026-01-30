# routes/api/admin/reports.py
"""
Endpoints para generación de reportes.

Incluye:
- export_requests_xlsx: Exportar solicitudes a Excel con 2 hojas (Citas y Bajas)
"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Optional

import pandas as pd
from flask import Blueprint, jsonify, request, send_file
from sqlalchemy import or_, asc, desc
from sqlalchemy.orm import joinedload

from itcj.apps.agendatec.models import db
from itcj.apps.agendatec.models.appointment import Appointment
from itcj.apps.agendatec.models.request import Request as Req
from itcj.apps.agendatec.models.time_slot import TimeSlot
from itcj.core.models.coordinator import Coordinator
from itcj.core.models.program import Program
from itcj.core.models.program_coordinator import ProgramCoordinator
from itcj.core.models.user import User
from itcj.core.utils.decorators import api_app_required, api_auth_required

from .helpers import range_from_query

admin_reports_bp = Blueprint("admin_reports", __name__)


@admin_reports_bp.post("/reports/requests.xlsx")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.reports.api.generate"])
def export_requests_xlsx():
    """
    Exporta solicitudes a un archivo Excel con 2 hojas:
    - Citas: Solicitudes tipo APPOINTMENT ordenadas por día y slot (ASC)
    - Solicitudes de Baja: Solicitudes tipo DROP

    Query params:
        from, to: Rango de fechas
        type: Filtro por tipo (APPOINTMENT, DROP)
        status: Filtro por estado de solicitud
        appointment_status: Filtro por estado de cita
        program_id: Filtro por programa
        coordinator_id: Filtro por coordinador
        period_id: Filtro por período
        q: Búsqueda por nombre/control del alumno
        order_by: Campo de ordenamiento (created_at, slot_day, student_name, program)
        order_dir: Dirección del ordenamiento (asc, desc)

    Returns:
        Archivo Excel para descarga
    """
    start, end = range_from_query()
    req_type = request.args.get("type")
    status = request.args.get("status")
    appointment_status = request.args.get("appointment_status")
    program_id = request.args.get("program_id", type=int)
    coordinator_id = request.args.get("coordinator_id", type=int)
    period_id = request.args.get("period_id", type=int)
    q = request.args.get("q", "").strip()
    order_by = request.args.get("order_by", "created_at")
    order_dir = request.args.get("order_dir", "asc")

    # Base query con eager loading
    base_qry = (
        db.session.query(Req)
        .options(
            joinedload(Req.appointment).joinedload(Appointment.coordinator).joinedload(Coordinator.user),
            joinedload(Req.appointment).joinedload(Appointment.slot),
            joinedload(Req.program).joinedload(Program.program_coordinators).joinedload(ProgramCoordinator.coordinator).joinedload(Coordinator.user),
            joinedload(Req.student),
            joinedload(Req.period),
        )
        .filter(Req.created_at >= start, Req.created_at <= end)
    )

    # Aplicar filtros comunes
    if status:
        base_qry = base_qry.filter(Req.status == status)
    if program_id:
        base_qry = base_qry.filter(Req.program_id == program_id)
    if coordinator_id:
        base_qry = base_qry.join(Appointment, Appointment.request_id == Req.id, isouter=True).filter(
            Appointment.coordinator_id == coordinator_id
        )
    if period_id:
        base_qry = base_qry.filter(Req.period_id == period_id)
    if q:
        base_qry = base_qry.join(User, User.id == Req.student_id).filter(
            or_(User.control_number.ilike(f"%{q}%"), User.full_name.ilike(f"%{q}%"))
        )
    if appointment_status:
        base_qry = base_qry.join(Appointment, Appointment.request_id == Req.id, isouter=True).filter(
            Appointment.status == appointment_status
        )

    # Si se especifica un tipo, filtrar solo por ese tipo
    if req_type:
        base_qry = base_qry.filter(Req.type == req_type)

    # Obtener todas las solicitudes
    all_requests = base_qry.all()

    # Separar citas y bajas
    appointments_data = []
    drops_data = []

    for r in all_requests:
        student = r.student
        program = r.program
        period = r.period
        a = r.appointment

        # Determinar el coordinador
        coord_name = None
        if a and a.coordinator and a.coordinator.user:
            coord_name = a.coordinator.user.full_name
        elif program and program.program_coordinators:
            first_coord = program.program_coordinators[0] if program.program_coordinators else None
            if first_coord and first_coord.coordinator and first_coord.coordinator.user:
                coord_name = first_coord.coordinator.user.full_name

        if r.type == "APPOINTMENT" and a and a.slot:
            # Solo incluir si hay cita con slot ocupado
            slot = a.slot
            if slot.is_booked:
                appointments_data.append({
                    "ID": r.id,
                    "Día": slot.day.strftime("%Y-%m-%d") if slot.day else None,
                    "Horario": f"{slot.start_time.strftime('%H:%M')} - {slot.end_time.strftime('%H:%M')}" if slot.start_time and slot.end_time else None,
                    "HoraInicio": slot.start_time,
                    "Programa": program.name if program else None,
                    "Alumno": student.full_name if student else None,
                    "NoControl": student.control_number if student else None,
                    "Coordinador": coord_name,
                    "EstadoSolicitud": _translate_request_status(r.status),
                    "EstadoCita": _translate_appointment_status(a.status),
                    "Período": period.name if period else None,
                    "Descripción": r.description or "",
                    "ComentarioCoord": r.coordinator_comment or "",
                    "Creado": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else None,
                    "Actualizado": r.updated_at.strftime("%Y-%m-%d %H:%M") if r.updated_at else None,
                })
        elif r.type == "DROP":
            drops_data.append({
                "ID": r.id,
                "Programa": program.name if program else None,
                "Alumno": student.full_name if student else None,
                "NoControl": student.control_number if student else None,
                "Coordinador": coord_name,
                "Estado": _translate_request_status(r.status),
                "Período": period.name if period else None,
                "Descripción": r.description or "",
                "ComentarioCoord": r.coordinator_comment or "",
                "Creado": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else None,
                "Actualizado": r.updated_at.strftime("%Y-%m-%d %H:%M") if r.updated_at else None,
            })

    # Ordenar citas por día y hora de inicio (ASC por defecto)
    appointments_data.sort(key=lambda x: (x["Día"] or "", x["HoraInicio"] or ""))

    # Remover columna auxiliar de hora inicio antes de crear DataFrame
    for row in appointments_data:
        del row["HoraInicio"]

    # Ordenar bajas según parámetros
    if order_by == "student_name":
        drops_data.sort(key=lambda x: (x["Alumno"] or "").lower(), reverse=(order_dir == "desc"))
    elif order_by == "program":
        drops_data.sort(key=lambda x: (x["Programa"] or "").lower(), reverse=(order_dir == "desc"))
    else:
        drops_data.sort(key=lambda x: x["Creado"] or "", reverse=(order_dir == "desc"))

    # Crear DataFrames
    df_appointments = pd.DataFrame(appointments_data)
    df_drops = pd.DataFrame(drops_data)

    # Generar Excel con 2 hojas
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        workbook = writer.book

        # Formato de encabezados
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#4472C4',
            'font_color': 'white',
            'border': 1,
            'align': 'center',
            'valign': 'vcenter'
        })

        # Formato de celdas
        cell_format = workbook.add_format({
            'border': 1,
            'align': 'left',
            'valign': 'vcenter',
            'text_wrap': True
        })

        # Hoja 1: Citas
        if not df_appointments.empty:
            df_appointments.to_excel(writer, index=False, sheet_name="Citas", startrow=1, header=False)
            ws_citas = writer.sheets["Citas"]

            # Escribir encabezados con formato
            for col_num, value in enumerate(df_appointments.columns.values):
                ws_citas.write(0, col_num, value, header_format)

            # Ajustar anchos de columna
            ws_citas.set_column('A:A', 8)   # ID
            ws_citas.set_column('B:B', 12)  # Día
            ws_citas.set_column('C:C', 14)  # Horario
            ws_citas.set_column('D:D', 20)  # Programa
            ws_citas.set_column('E:E', 30)  # Alumno
            ws_citas.set_column('F:F', 12)  # NoControl
            ws_citas.set_column('G:G', 25)  # Coordinador
            ws_citas.set_column('H:H', 18)  # EstadoSolicitud
            ws_citas.set_column('I:I', 15)  # EstadoCita
            ws_citas.set_column('J:J', 15)  # Período
            ws_citas.set_column('K:K', 40)  # Descripción
            ws_citas.set_column('L:L', 40)  # ComentarioCoord
            ws_citas.set_column('M:M', 16)  # Creado
            ws_citas.set_column('N:N', 16)  # Actualizado

            # Congelar primera fila
            ws_citas.freeze_panes(1, 0)
        else:
            # Crear hoja vacía con encabezados
            empty_df = pd.DataFrame(columns=["ID", "Día", "Horario", "Programa", "Alumno", "NoControl",
                                             "Coordinador", "EstadoSolicitud", "EstadoCita", "Período",
                                             "Descripción", "ComentarioCoord", "Creado", "Actualizado"])
            empty_df.to_excel(writer, index=False, sheet_name="Citas")

        # Hoja 2: Solicitudes de Baja
        if not df_drops.empty:
            df_drops.to_excel(writer, index=False, sheet_name="Solicitudes de Baja", startrow=1, header=False)
            ws_bajas = writer.sheets["Solicitudes de Baja"]

            # Escribir encabezados con formato
            for col_num, value in enumerate(df_drops.columns.values):
                ws_bajas.write(0, col_num, value, header_format)

            # Ajustar anchos de columna
            ws_bajas.set_column('A:A', 8)   # ID
            ws_bajas.set_column('B:B', 20)  # Programa
            ws_bajas.set_column('C:C', 30)  # Alumno
            ws_bajas.set_column('D:D', 12)  # NoControl
            ws_bajas.set_column('E:E', 25)  # Coordinador
            ws_bajas.set_column('F:F', 18)  # Estado
            ws_bajas.set_column('G:G', 15)  # Período
            ws_bajas.set_column('H:H', 40)  # Descripción
            ws_bajas.set_column('I:I', 40)  # ComentarioCoord
            ws_bajas.set_column('J:J', 16)  # Creado
            ws_bajas.set_column('K:K', 16)  # Actualizado

            # Congelar primera fila
            ws_bajas.freeze_panes(1, 0)
        else:
            # Crear hoja vacía con encabezados
            empty_df = pd.DataFrame(columns=["ID", "Programa", "Alumno", "NoControl", "Coordinador",
                                             "Estado", "Período", "Descripción", "ComentarioCoord",
                                             "Creado", "Actualizado"])
            empty_df.to_excel(writer, index=False, sheet_name="Solicitudes de Baja")

    buf.seek(0)
    filename = f"reporte_agendatec_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )


def _translate_request_status(status: str) -> str:
    """Traduce el estado de solicitud a español."""
    translations = {
        "PENDING": "Pendiente",
        "RESOLVED_SUCCESS": "Resuelta",
        "RESOLVED_NOT_COMPLETED": "Atendida sin resolver",
        "NO_SHOW": "No asistió",
        "ATTENDED_OTHER_SLOT": "Asistió otro horario",
        "CANCELED": "Cancelada",
    }
    return translations.get(status, status)


def _translate_appointment_status(status: str) -> str:
    """Traduce el estado de cita a español."""
    translations = {
        "SCHEDULED": "Programada",
        "DONE": "Completada",
        "NO_SHOW": "No asistió",
        "CANCELED": "Cancelada",
    }
    return translations.get(status, status)
