# routes/api/admin/reports.py
"""
Endpoints para generación de reportes.

Incluye:
- export_requests_xlsx: Exportar solicitudes a Excel con 2 hojas (Citas y Bajas)
"""
from __future__ import annotations

import re
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
        status: Filtro por estado de solicitud (múltiples separados por coma)
        appointment_status: Filtro por estado de cita (múltiples separados por coma)
        program_id: Filtro por programa (múltiples separados por coma)
        coordinator_id: Filtro por coordinador (múltiples separados por coma)
        period_id: Filtro por período
        q: Búsqueda por nombre/control del alumno
        order_by: Campo de ordenamiento (created_at, slot_day, student_name, program)
        order_dir: Dirección del ordenamiento (asc, desc)
        citas_cols: Columnas a incluir en hoja de Citas (separadas por coma, en orden)
        bajas_cols: Columnas a incluir en hoja de Bajas (separadas por coma, en orden)
        filename: Nombre personalizado del archivo (sin extensión)

    Returns:
        Archivo Excel para descarga
    """
    start, end = range_from_query()
    req_type = request.args.get("type")
    q = request.args.get("q", "").strip()
    order_by = request.args.get("order_by", "created_at")
    order_dir = request.args.get("order_dir", "asc")
    custom_filename = request.args.get("filename", "").strip()
    period_id = request.args.get("period_id", type=int)

    # Parámetros que soportan múltiples valores (separados por coma)
    status_param = request.args.get("status", "")
    appointment_status_param = request.args.get("appointment_status", "")
    program_id_param = request.args.get("program_id", "")
    coordinator_id_param = request.args.get("coordinator_id", "")

    # Parsear múltiples valores
    statuses = [s.strip() for s in status_param.split(",") if s.strip()] if status_param else []
    appointment_statuses = [s.strip() for s in appointment_status_param.split(",") if s.strip()] if appointment_status_param else []
    program_ids = [int(p.strip()) for p in program_id_param.split(",") if p.strip().isdigit()] if program_id_param else []
    coordinator_ids = [int(c.strip()) for c in coordinator_id_param.split(",") if c.strip().isdigit()] if coordinator_id_param else []

    # Columnas personalizadas (si no se especifican, usar todas)
    citas_cols_param = request.args.get("citas_cols", "")
    bajas_cols_param = request.args.get("bajas_cols", "")

    # Configuración de resúmenes
    citas_summary_param = request.args.get("citas_summary", "total,coordinator")  # default
    bajas_summary_param = request.args.get("bajas_summary", "total")  # default

    # Parsear opciones de resumen
    citas_summary_options = [s.strip() for s in citas_summary_param.split(",") if s.strip()] if citas_summary_param else []
    bajas_summary_options = [s.strip() for s in bajas_summary_param.split(",") if s.strip()] if bajas_summary_param else []

    # Validar opciones de resumen
    valid_citas_summary = ['total', 'coordinator', 'program']
    valid_bajas_summary = ['total', 'program', 'coordinator']
    citas_summary_options = [o for o in citas_summary_options if o in valid_citas_summary]
    bajas_summary_options = [o for o in bajas_summary_options if o in valid_bajas_summary]

    # Columnas por defecto para citas
    default_citas_cols = ["ID", "Día", "Horario", "Programa", "Alumno", "NoControl",
                          "Coordinador", "EstadoSolicitud", "EstadoCita", "Período",
                          "Descripción", "ComentarioCoord", "Creado", "Actualizado"]
    # Columnas por defecto para bajas
    default_bajas_cols = ["ID", "Programa", "Alumno", "NoControl", "Coordinador",
                          "Estado", "Período", "Descripción", "ComentarioCoord",
                          "Creado", "Actualizado"]

    # Parsear columnas seleccionadas
    citas_cols = [c.strip() for c in citas_cols_param.split(",") if c.strip()] if citas_cols_param else default_citas_cols
    bajas_cols = [c.strip() for c in bajas_cols_param.split(",") if c.strip()] if bajas_cols_param else default_bajas_cols

    # Validar que las columnas existan
    citas_cols = [c for c in citas_cols if c in default_citas_cols]
    bajas_cols = [c for c in bajas_cols if c in default_bajas_cols]

    # Si después de validar no hay columnas, usar las por defecto
    if not citas_cols:
        citas_cols = default_citas_cols
    if not bajas_cols:
        bajas_cols = default_bajas_cols

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
    # Filtro por múltiples estados de solicitud
    if statuses:
        if len(statuses) == 1:
            base_qry = base_qry.filter(Req.status == statuses[0])
        else:
            base_qry = base_qry.filter(Req.status.in_(statuses))

    # Filtro por múltiples programas
    if program_ids:
        if len(program_ids) == 1:
            base_qry = base_qry.filter(Req.program_id == program_ids[0])
        else:
            base_qry = base_qry.filter(Req.program_id.in_(program_ids))

    # Filtro por múltiples coordinadores
    if coordinator_ids:
        base_qry = base_qry.join(Appointment, Appointment.request_id == Req.id, isouter=True)
        if len(coordinator_ids) == 1:
            base_qry = base_qry.filter(Appointment.coordinator_id == coordinator_ids[0])
        else:
            base_qry = base_qry.filter(Appointment.coordinator_id.in_(coordinator_ids))

    if period_id:
        base_qry = base_qry.filter(Req.period_id == period_id)

    if q:
        # Soportar búsqueda de múltiples valores separados por coma
        search_terms = [term.strip() for term in q.split(",") if term.strip()]
        if search_terms:
            base_qry = base_qry.join(User, User.id == Req.student_id)
            if len(search_terms) == 1:
                # Búsqueda simple (una sola palabra)
                term = search_terms[0]
                base_qry = base_qry.filter(
                    or_(User.control_number.ilike(f"%{term}%"), User.full_name.ilike(f"%{term}%"))
                )
            else:
                # Búsqueda múltiple (varios términos, cualquiera coincide)
                conditions = []
                for term in search_terms:
                    conditions.append(User.control_number.ilike(f"%{term}%"))
                    conditions.append(User.full_name.ilike(f"%{term}%"))
                base_qry = base_qry.filter(or_(*conditions))

    # Filtro por múltiples estados de cita
    if appointment_statuses:
        # Solo hacer join si no se hizo antes (por coordinator_ids)
        if not coordinator_ids:
            base_qry = base_qry.join(Appointment, Appointment.request_id == Req.id, isouter=True)
        if len(appointment_statuses) == 1:
            base_qry = base_qry.filter(Appointment.status == appointment_statuses[0])
        else:
            base_qry = base_qry.filter(Appointment.status.in_(appointment_statuses))

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

    # Crear DataFrames con columnas seleccionadas y en orden
    df_appointments = pd.DataFrame(appointments_data)
    df_drops = pd.DataFrame(drops_data)

    # Filtrar y reordenar columnas según configuración
    if not df_appointments.empty:
        # Filtrar solo columnas que existen en el DataFrame
        valid_citas_cols = [c for c in citas_cols if c in df_appointments.columns]
        if valid_citas_cols:
            df_appointments = df_appointments[valid_citas_cols]

    if not df_drops.empty:
        valid_bajas_cols = [c for c in bajas_cols if c in df_drops.columns]
        if valid_bajas_cols:
            df_drops = df_drops[valid_bajas_cols]

    # Mapeo de anchos de columna por nombre
    col_widths = {
        "ID": 8, "Día": 12, "Horario": 14, "Programa": 22, "Alumno": 32,
        "NoControl": 13, "Coordinador": 26, "EstadoSolicitud": 20, "EstadoCita": 16,
        "Período": 16, "Descripción": 45, "ComentarioCoord": 45, "Creado": 17,
        "Actualizado": 17, "Estado": 20
    }

    # Generar Excel con 2 hojas
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        workbook = writer.book

        # ==================== FORMATOS ====================

        # Formato de encabezados
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#2F5496',
            'font_color': 'white',
            'border': 1,
            'align': 'center',
            'valign': 'vcenter',
            'font_size': 11,
            'text_wrap': True
        })

        # Formato base para celdas (fila par - blanca)
        cell_format_even = workbook.add_format({
            'border': 1,
            'align': 'left',
            'valign': 'vcenter',
            'text_wrap': True,
            'font_size': 10,
            'bg_color': '#FFFFFF'
        })

        # Formato para filas impares (gris claro - zebra)
        cell_format_odd = workbook.add_format({
            'border': 1,
            'align': 'left',
            'valign': 'vcenter',
            'text_wrap': True,
            'font_size': 10,
            'bg_color': '#F2F2F2'
        })

        # Formato para ID (centrado)
        id_format_even = workbook.add_format({
            'border': 1, 'align': 'center', 'valign': 'vcenter',
            'font_size': 10, 'bg_color': '#FFFFFF', 'bold': True
        })
        id_format_odd = workbook.add_format({
            'border': 1, 'align': 'center', 'valign': 'vcenter',
            'font_size': 10, 'bg_color': '#F2F2F2', 'bold': True
        })

        # Formato para fechas (centrado)
        date_format_even = workbook.add_format({
            'border': 1, 'align': 'center', 'valign': 'vcenter',
            'font_size': 10, 'bg_color': '#FFFFFF'
        })
        date_format_odd = workbook.add_format({
            'border': 1, 'align': 'center', 'valign': 'vcenter',
            'font_size': 10, 'bg_color': '#F2F2F2'
        })

        # ==================== COLORES PARA ESTADOS DE SOLICITUD ====================
        # Resuelta: Verde
        status_resuelta_even = workbook.add_format({
            'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10,
            'bg_color': '#C6EFCE', 'font_color': '#006100', 'bold': True
        })
        status_resuelta_odd = workbook.add_format({
            'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10,
            'bg_color': '#A9D8B8', 'font_color': '#006100', 'bold': True
        })

        # Atendida sin resolver: Verde clarito
        status_atendida_even = workbook.add_format({
            'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10,
            'bg_color': '#E2EFDA', 'font_color': '#375623', 'bold': True
        })
        status_atendida_odd = workbook.add_format({
            'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10,
            'bg_color': '#D4E7C5', 'font_color': '#375623', 'bold': True
        })

        # No asistió: Rojo
        status_noshow_even = workbook.add_format({
            'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10,
            'bg_color': '#FFC7CE', 'font_color': '#9C0006', 'bold': True
        })
        status_noshow_odd = workbook.add_format({
            'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10,
            'bg_color': '#FFAAB5', 'font_color': '#9C0006', 'bold': True
        })

        # Otro horario: Azul cielo
        status_otro_even = workbook.add_format({
            'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10,
            'bg_color': '#BDD7EE', 'font_color': '#1F4E79', 'bold': True
        })
        status_otro_odd = workbook.add_format({
            'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10,
            'bg_color': '#9BC2E6', 'font_color': '#1F4E79', 'bold': True
        })

        # Pendiente: Gris
        status_pendiente_even = workbook.add_format({
            'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10,
            'bg_color': '#D9D9D9', 'font_color': '#404040', 'bold': True
        })
        status_pendiente_odd = workbook.add_format({
            'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10,
            'bg_color': '#BFBFBF', 'font_color': '#404040', 'bold': True
        })

        # Cancelada: Negro con letras blancas
        status_cancelada_even = workbook.add_format({
            'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10,
            'bg_color': '#404040', 'font_color': '#FFFFFF', 'bold': True
        })
        status_cancelada_odd = workbook.add_format({
            'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10,
            'bg_color': '#2D2D2D', 'font_color': '#FFFFFF', 'bold': True
        })

        # ==================== COLORES PARA ESTADOS DE CITA ====================
        # Programada: Azul
        cita_programada_even = workbook.add_format({
            'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10,
            'bg_color': '#DDEBF7', 'font_color': '#1F4E79', 'bold': True
        })
        cita_programada_odd = workbook.add_format({
            'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10,
            'bg_color': '#BDD7EE', 'font_color': '#1F4E79', 'bold': True
        })

        # Completada: Verde
        cita_completada_even = workbook.add_format({
            'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10,
            'bg_color': '#C6EFCE', 'font_color': '#006100', 'bold': True
        })
        cita_completada_odd = workbook.add_format({
            'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10,
            'bg_color': '#A9D8B8', 'font_color': '#006100', 'bold': True
        })

        # No asistió (cita): Naranja
        cita_noshow_even = workbook.add_format({
            'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10,
            'bg_color': '#FCE4D6', 'font_color': '#974706', 'bold': True
        })
        cita_noshow_odd = workbook.add_format({
            'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10,
            'bg_color': '#F8CBAD', 'font_color': '#974706', 'bold': True
        })

        # Cancelada (cita): Rojo oscuro
        cita_cancelada_even = workbook.add_format({
            'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10,
            'bg_color': '#FFC7CE', 'font_color': '#9C0006', 'bold': True
        })
        cita_cancelada_odd = workbook.add_format({
            'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10,
            'bg_color': '#FFAAB5', 'font_color': '#9C0006', 'bold': True
        })

        # Mapeo de estados de solicitud a formatos
        status_formats = {
            'Resuelta': (status_resuelta_even, status_resuelta_odd),
            'Atendida sin resolver': (status_atendida_even, status_atendida_odd),
            'No asistió': (status_noshow_even, status_noshow_odd),
            'Asistió otro horario': (status_otro_even, status_otro_odd),
            'Pendiente': (status_pendiente_even, status_pendiente_odd),
            'Cancelada': (status_cancelada_even, status_cancelada_odd),
        }

        # Mapeo de estados de cita a formatos
        cita_formats = {
            'Programada': (cita_programada_even, cita_programada_odd),
            'Completada': (cita_completada_even, cita_completada_odd),
            'No asistió': (cita_noshow_even, cita_noshow_odd),
            'Cancelada': (cita_cancelada_even, cita_cancelada_odd),
        }

        def get_cell_format(col_name, value, row_idx):
            """Retorna el formato apropiado según columna, valor y fila (zebra)"""
            is_odd = row_idx % 2 == 1

            if col_name == 'EstadoSolicitud' or col_name == 'Estado':
                formats = status_formats.get(value)
                if formats:
                    return formats[1] if is_odd else formats[0]
            elif col_name == 'EstadoCita':
                formats = cita_formats.get(value)
                if formats:
                    return formats[1] if is_odd else formats[0]
            elif col_name == 'ID':
                return id_format_odd if is_odd else id_format_even
            elif col_name in ['Día', 'Horario', 'Creado', 'Actualizado']:
                return date_format_odd if is_odd else date_format_even

            return cell_format_odd if is_odd else cell_format_even

        def write_styled_sheet(worksheet, df, columns):
            """Escribe una hoja con estilos aplicados"""
            # Escribir encabezados
            for col_num, col_name in enumerate(columns):
                worksheet.write(0, col_num, col_name, header_format)
                width = col_widths.get(col_name, 15)
                worksheet.set_column(col_num, col_num, width)

            # Escribir datos con formato
            for row_idx, row in df.iterrows():
                for col_num, col_name in enumerate(columns):
                    value = row.get(col_name, '')
                    cell_fmt = get_cell_format(col_name, value, row_idx)
                    worksheet.write(row_idx + 1, col_num, value, cell_fmt)

            # Congelar primera fila
            worksheet.freeze_panes(1, 0)

            # Establecer altura de fila para encabezados
            worksheet.set_row(0, 22)

            # Filtros automáticos
            if len(df) > 0:
                worksheet.autofilter(0, 0, len(df), len(columns) - 1)

        # ==================== FORMATOS PARA RESUMEN ====================
        summary_header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#1F4E79',
            'font_color': 'white',
            'border': 1,
            'align': 'center',
            'valign': 'vcenter',
            'font_size': 10
        })

        summary_subheader_format = workbook.add_format({
            'bold': True,
            'bg_color': '#2F5496',
            'font_color': 'white',
            'border': 1,
            'align': 'center',
            'valign': 'vcenter',
            'font_size': 9
        })

        summary_day_format = workbook.add_format({
            'bold': True,
            'bg_color': '#D6DCE4',
            'font_color': '#1F4E79',
            'border': 1,
            'align': 'center',
            'valign': 'vcenter',
            'font_size': 10
        })

        summary_cell_format = workbook.add_format({
            'border': 1,
            'align': 'center',
            'valign': 'vcenter',
            'font_size': 10,
            'bg_color': '#FFFFFF'
        })

        summary_total_format = workbook.add_format({
            'bold': True,
            'border': 1,
            'align': 'center',
            'valign': 'vcenter',
            'font_size': 10,
            'bg_color': '#E2EFDA',
            'font_color': '#375623'
        })

        summary_grand_total_format = workbook.add_format({
            'bold': True,
            'border': 2,
            'align': 'center',
            'valign': 'vcenter',
            'font_size': 11,
            'bg_color': '#2F5496',
            'font_color': 'white'
        })

        # Lista de estados para el resumen
        estados_solicitud = ['Resuelta', 'Atendida sin resolver', 'No asistió', 'Asistió otro horario', 'Pendiente', 'Cancelada']

        # Formato para nombre de coordinador (celda grande a la izquierda)
        coord_name_format = workbook.add_format({
            'bold': True,
            'bg_color': '#1F4E79',
            'font_color': 'white',
            'border': 2,
            'align': 'center',
            'valign': 'vcenter',
            'font_size': 11,
            'text_wrap': True,
            'rotation': 90
        })

        coord_section_header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#4472C4',
            'font_color': 'white',
            'border': 1,
            'align': 'center',
            'valign': 'vcenter',
            'font_size': 10
        })

        def write_citas_summary(worksheet, df, start_col, summary_options):
            """Escribe el resumen por día para citas según las opciones seleccionadas"""
            if df.empty or 'Día' not in df.columns or 'EstadoSolicitud' not in df.columns:
                return

            if not summary_options:
                return  # No escribir resumen si no hay opciones seleccionadas

            has_coordinator = 'Coordinador' in df.columns
            has_program = 'Programa' in df.columns
            num_status_cols = len(estados_solicitud)
            total_width = num_status_cols + 2  # Día + estados + Total

            # Título del resumen
            worksheet.merge_range(0, start_col, 0, start_col + total_width - 1,
                                  'RESUMEN POR DÍA', summary_header_format)

            # Función auxiliar para escribir encabezados de sección
            def write_section_headers(row, col_start):
                worksheet.write(row, col_start, 'Día', summary_subheader_format)
                worksheet.set_column(col_start, col_start, 12)
                for idx, estado in enumerate(estados_solicitud):
                    col = col_start + 1 + idx
                    nombre_corto = estado[:12] + '...' if len(estado) > 15 else estado
                    worksheet.write(row, col, nombre_corto, summary_subheader_format)
                    worksheet.set_column(col, col, 10)
                worksheet.write(row, col_start + num_status_cols + 1, 'Total', summary_subheader_format)
                worksheet.set_column(col_start + num_status_cols + 1, col_start + num_status_cols + 1, 8)

            # Función auxiliar para escribir datos de una sección (Total, coordinador o programa)
            def write_section_data(df_section, start_row, col_start):
                dias = df_section['Día'].unique()
                dias_ordenados = sorted([d for d in dias if d], key=lambda x: x if x else '')

                row = start_row
                totales_por_estado = {estado: 0 for estado in estados_solicitud}
                gran_total = 0

                for dia in dias_ordenados:
                    df_dia = df_section[df_section['Día'] == dia]
                    worksheet.write(row, col_start, dia, summary_day_format)

                    total_dia = 0
                    for idx, estado in enumerate(estados_solicitud):
                        count = len(df_dia[df_dia['EstadoSolicitud'] == estado])
                        col = col_start + 1 + idx
                        if count > 0:
                            fmt = status_formats.get(estado, (summary_cell_format, summary_cell_format))[0]
                            worksheet.write(row, col, count, fmt)
                        else:
                            worksheet.write(row, col, '', summary_cell_format)
                        totales_por_estado[estado] += count
                        total_dia += count

                    worksheet.write(row, col_start + num_status_cols + 1, total_dia, summary_total_format)
                    gran_total += total_dia
                    row += 1

                # Fila de totales de sección
                worksheet.write(row, col_start, 'TOTAL', summary_grand_total_format)
                for idx, estado in enumerate(estados_solicitud):
                    col = col_start + 1 + idx
                    worksheet.write(row, col, totales_por_estado[estado], summary_grand_total_format)
                worksheet.write(row, col_start + num_status_cols + 1, gran_total, summary_grand_total_format)

                return row + 1  # Retorna la siguiente fila disponible

            current_row = 1

            # ==================== SECCIÓN TOTAL GENERAL ====================
            if 'total' in summary_options:
                worksheet.merge_range(current_row, start_col, current_row, start_col + total_width - 1,
                                      'TOTAL GENERAL', coord_section_header_format)
                current_row += 1

                write_section_headers(current_row, start_col)
                current_row += 1

                current_row = write_section_data(df, current_row, start_col)
                current_row += 1  # Espacio entre secciones

            # ==================== SECCIONES POR COORDINADOR ====================
            if 'coordinator' in summary_options and has_coordinator:
                coordinadores = df['Coordinador'].unique()
                coordinadores_ordenados = sorted([c for c in coordinadores if c], key=lambda x: x if x else '')

                for coord in coordinadores_ordenados:
                    df_coord = df[df['Coordinador'] == coord]
                    if df_coord.empty:
                        continue

                    dias_coord = df_coord['Día'].unique()
                    num_dias = len([d for d in dias_coord if d])
                    if num_dias == 0:
                        continue

                    # Nombre del coordinador como título de sección
                    worksheet.merge_range(current_row, start_col, current_row, start_col + total_width - 1,
                                          f"Coordinador: {coord}", coord_section_header_format)
                    current_row += 1

                    write_section_headers(current_row, start_col)
                    current_row += 1

                    current_row = write_section_data(df_coord, current_row, start_col)
                    current_row += 1  # Espacio entre coordinadores

            # ==================== SECCIONES POR PROGRAMA/CARRERA ====================
            if 'program' in summary_options and has_program:
                programas = df['Programa'].unique()
                programas_ordenados = sorted([p for p in programas if p], key=lambda x: x if x else '')

                for programa in programas_ordenados:
                    df_programa = df[df['Programa'] == programa]
                    if df_programa.empty:
                        continue

                    dias_prog = df_programa['Día'].unique()
                    num_dias = len([d for d in dias_prog if d])
                    if num_dias == 0:
                        continue

                    # Nombre del programa como título de sección
                    worksheet.merge_range(current_row, start_col, current_row, start_col + total_width - 1,
                                          f"Carrera: {programa}", coord_section_header_format)
                    current_row += 1

                    write_section_headers(current_row, start_col)
                    current_row += 1

                    current_row = write_section_data(df_programa, current_row, start_col)
                    current_row += 1  # Espacio entre programas

        def write_bajas_summary(worksheet, df, start_col, summary_options):
            """Escribe el resumen general para bajas según las opciones seleccionadas"""
            if df.empty or 'Estado' not in df.columns:
                return

            if not summary_options:
                return  # No escribir resumen si no hay opciones seleccionadas

            has_program = 'Programa' in df.columns
            has_coordinator = 'Coordinador' in df.columns

            # Función auxiliar para escribir un bloque de resumen por estado
            def write_status_summary(start_row, col_start, df_section, section_title=None):
                row = start_row

                # Título de sección si se proporciona
                if section_title:
                    worksheet.merge_range(row, col_start, row, col_start + 1, section_title, coord_section_header_format)
                    row += 1

                # Encabezados
                worksheet.write(row, col_start, 'Estado', summary_subheader_format)
                worksheet.write(row, col_start + 1, 'Cantidad', summary_subheader_format)
                worksheet.set_column(col_start, col_start, 22)
                worksheet.set_column(col_start + 1, col_start + 1, 10)
                row += 1

                total = 0
                for estado in estados_solicitud:
                    count = len(df_section[df_section['Estado'] == estado])
                    if count > 0:
                        fmt = status_formats.get(estado, (summary_cell_format, summary_cell_format))[0]
                        worksheet.write(row, col_start, estado, fmt)
                        worksheet.write(row, col_start + 1, count, fmt)
                        total += count
                        row += 1

                # Total
                worksheet.write(row, col_start, 'TOTAL', summary_grand_total_format)
                worksheet.write(row, col_start + 1, total, summary_grand_total_format)

                return row + 2  # Retorna siguiente fila disponible con espacio

            # Título del resumen
            worksheet.merge_range(0, start_col, 0, start_col + 1, 'RESUMEN DE BAJAS', summary_header_format)

            current_row = 1

            # ==================== TOTAL GENERAL ====================
            if 'total' in summary_options:
                current_row = write_status_summary(current_row, start_col, df, 'TOTAL GENERAL')

            # ==================== POR PROGRAMA/CARRERA ====================
            if 'program' in summary_options and has_program:
                programas = df['Programa'].unique()
                programas_ordenados = sorted([p for p in programas if p], key=lambda x: x if x else '')

                for programa in programas_ordenados:
                    df_programa = df[df['Programa'] == programa]
                    if df_programa.empty:
                        continue
                    current_row = write_status_summary(current_row, start_col, df_programa, f"Carrera: {programa}")

            # ==================== POR COORDINADOR ====================
            if 'coordinator' in summary_options and has_coordinator:
                coordinadores = df['Coordinador'].unique()
                coordinadores_ordenados = sorted([c for c in coordinadores if c], key=lambda x: x if x else '')

                for coord in coordinadores_ordenados:
                    df_coord = df[df['Coordinador'] == coord]
                    if df_coord.empty:
                        continue
                    current_row = write_status_summary(current_row, start_col, df_coord, f"Coordinador: {coord}")

        # ==================== HOJA 1: CITAS ====================
        if not df_appointments.empty:
            worksheet_citas = workbook.add_worksheet("Citas")
            writer.sheets["Citas"] = worksheet_citas
            columns_citas = [c for c in citas_cols if c in df_appointments.columns]
            write_styled_sheet(worksheet_citas, df_appointments[columns_citas], columns_citas)

            # Agregar resumen a la derecha (2 columnas de espacio)
            summary_start_col = len(columns_citas) + 2
            write_citas_summary(worksheet_citas, df_appointments, summary_start_col, citas_summary_options)
        else:
            empty_df = pd.DataFrame(columns=citas_cols)
            empty_df.to_excel(writer, index=False, sheet_name="Citas")

        # ==================== HOJA 2: SOLICITUDES DE BAJA ====================
        if not df_drops.empty:
            worksheet_bajas = workbook.add_worksheet("Solicitudes de Baja")
            writer.sheets["Solicitudes de Baja"] = worksheet_bajas
            columns_bajas = [c for c in bajas_cols if c in df_drops.columns]
            write_styled_sheet(worksheet_bajas, df_drops[columns_bajas], columns_bajas)

            # Agregar resumen a la derecha (2 columnas de espacio)
            summary_start_col = len(columns_bajas) + 2
            write_bajas_summary(worksheet_bajas, df_drops, summary_start_col, bajas_summary_options)
        else:
            empty_df = pd.DataFrame(columns=bajas_cols)
            empty_df.to_excel(writer, index=False, sheet_name="Solicitudes de Baja")

    buf.seek(0)
    # Usar nombre personalizado si se proporciona, sino generar uno automático
    if custom_filename:
        # Sanitizar el nombre de archivo (remover caracteres no válidos)
        safe_filename = re.sub(r'[<>:"/\\|?*]', '_', custom_filename)
        filename = f"{safe_filename}.xlsx"
    else:
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
