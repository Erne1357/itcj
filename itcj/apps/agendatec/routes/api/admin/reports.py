# routes/api/admin/reports.py
"""
Endpoints para generación de reportes.

Incluye:
- export_requests_xlsx: Exportar solicitudes a Excel
"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Optional

import pandas as pd
from flask import Blueprint, jsonify, request, send_file
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from itcj.apps.agendatec.models import db
from itcj.apps.agendatec.models.appointment import Appointment
from itcj.apps.agendatec.models.request import Request as Req
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
    Exporta solicitudes a un archivo Excel.

    Query params:
        from, to: Rango de fechas
        status: Filtro por estado
        program_id: Filtro por programa
        coordinator_id: Filtro por coordinador
        period_id: Filtro por período
        q: Búsqueda por nombre/control del alumno

    Returns:
        Archivo Excel para descarga
    """
    start, end = range_from_query()
    status = request.args.get("status")
    program_id = request.args.get("program_id", type=int)
    coordinator_id = request.args.get("coordinator_id", type=int)
    period_id = request.args.get("period_id", type=int)
    q = request.args.get("q", "").strip()

    qry = (
        db.session.query(Req)
        .options(
            joinedload(Req.appointment).joinedload(Appointment.coordinator).joinedload(Coordinator.user),
            joinedload(Req.program).joinedload(Program.program_coordinators).joinedload(ProgramCoordinator.coordinator).joinedload(Coordinator.user),
            joinedload(Req.student),
        )
        .filter(Req.created_at >= start, Req.created_at <= end)
        .order_by(Req.created_at.desc())
    )
    if status:
        qry = qry.filter(Req.status == status)
    if program_id:
        qry = qry.filter(Req.program_id == program_id)
    if coordinator_id:
        qry = qry.join(Appointment, Appointment.request_id == Req.id).filter(
            Appointment.coordinator_id == coordinator_id
        )
    if period_id:
        qry = qry.filter(Req.period_id == period_id)
    if q:
        qry = qry.join(User, User.id == Req.student_id).filter(
            or_(User.control_number.ilike(f"%{q}%"), User.full_name.ilike(f"%{q}%"))
        )

    rows = []
    for r in qry.all():
        a = r.appointment
        coord_name = None

        if a and a.coordinator and a.coordinator.user:
            coord_name = a.coordinator.user.full_name
        elif r.program and r.program.program_coordinators:
            first_coord = r.program.program_coordinators[0] if r.program.program_coordinators else None
            if first_coord and first_coord.coordinator and first_coord.coordinator.user:
                coord_name = first_coord.coordinator.user.full_name

        rows.append(
            {
                "ID": r.id,
                "Tipo": r.type,
                "Estado": r.status,
                "Programa": r.program.name if r.program else None,
                "Alumno": r.student.full_name if r.student else None,
                "NoControl": r.student.control_number if r.student else None,
                "Coord": coord_name,
                "CitaID": a.id if a else None,
                "CitaStatus": a.status if a else None,
                "Creado": r.created_at.isoformat() if r.created_at else None,
                "Actualizado": r.updated_at.isoformat() if r.updated_at else None,
            }
        )

    df = pd.DataFrame(rows)
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Solicitudes")
    buf.seek(0)
    filename = f"solicitudes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )
