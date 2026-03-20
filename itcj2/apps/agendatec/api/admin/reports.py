"""
Admin Reports API v2 — Exportación de reportes Excel.
Fuente: itcj/apps/agendatec/routes/api/admin/reports.py
"""
import logging
import re
from datetime import datetime
from io import BytesIO
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.agendatec.helpers import parse_range_from_params
from itcj2.apps.agendatec.models.appointment import Appointment
from itcj2.apps.agendatec.models.request import Request as Req
from itcj2.apps.agendatec.models.time_slot import TimeSlot
from itcj2.core.models.coordinator import Coordinator
from itcj2.core.models.program import Program
from itcj2.core.models.program_coordinator import ProgramCoordinator
from itcj2.core.models.user import User

router = APIRouter(tags=["agendatec-admin-reports"])
logger = logging.getLogger(__name__)

ReportPerm = require_perms("agendatec", ["agendatec.reports.api.generate"])

_DEFAULT_CITAS_COLS = [
    "ID", "Día", "Horario", "Programa", "Alumno", "NoControl",
    "Coordinador", "EstadoSolicitud", "EstadoCita", "Período",
    "Descripción", "ComentarioCoord", "Creado", "Actualizado",
]
_DEFAULT_BAJAS_COLS = [
    "ID", "Programa", "Alumno", "NoControl", "Coordinador",
    "Estado", "Período", "Descripción", "ComentarioCoord",
    "Creado", "Actualizado",
]
_COL_WIDTHS = {
    "ID": 8, "Día": 12, "Horario": 14, "Programa": 22, "Alumno": 32,
    "NoControl": 13, "Coordinador": 26, "EstadoSolicitud": 20, "EstadoCita": 16,
    "Período": 16, "Descripción": 45, "ComentarioCoord": 45, "Creado": 17,
    "Actualizado": 17, "Estado": 20,
}


def _translate_request_status(status: str) -> str:
    return {
        "PENDING": "Pendiente",
        "RESOLVED_SUCCESS": "Resuelta",
        "RESOLVED_NOT_COMPLETED": "Atendida sin resolver",
        "NO_SHOW": "No asistió",
        "ATTENDED_OTHER_SLOT": "Asistió otro horario",
        "CANCELED": "Cancelada",
    }.get(status, status)


def _translate_appointment_status(status: str) -> str:
    return {
        "SCHEDULED": "Programada",
        "DONE": "Completada",
        "NO_SHOW": "No asistió",
        "CANCELED": "Cancelada",
    }.get(status, status)


# ==================== POST /reports/requests.xlsx ====================

@router.post("/reports/requests.xlsx")
def export_requests_xlsx(
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    appointment_status: Optional[str] = Query(None),
    program_id: Optional[str] = Query(None),
    coordinator_id: Optional[str] = Query(None),
    period_id: Optional[int] = Query(None),
    q: str = Query(""),
    order_by: str = Query("created_at"),
    order_dir: str = Query("asc"),
    citas_cols: str = Query(""),
    bajas_cols: str = Query(""),
    citas_summary: str = Query("total,coordinator"),
    bajas_summary: str = Query("total"),
    filename: str = Query(""),
    user: dict = ReportPerm,
    db: DbSession = None,
):
    """Exporta solicitudes a Excel con 2 hojas: Citas y Solicitudes de Baja."""
    start, end = parse_range_from_params(from_, to)

    # Parsear parámetros multi-valor
    statuses = [s.strip() for s in status.split(",") if s.strip()] if status else []
    apt_statuses = [s.strip() for s in appointment_status.split(",") if s.strip()] if appointment_status else []
    prog_ids = [int(p) for p in program_id.split(",") if p.strip().isdigit()] if program_id else []
    coord_ids = [int(c) for c in coordinator_id.split(",") if c.strip().isdigit()] if coordinator_id else []

    # Parsear opciones de columnas
    valid_citas = [c.strip() for c in citas_cols.split(",") if c.strip() in _DEFAULT_CITAS_COLS] if citas_cols else _DEFAULT_CITAS_COLS
    valid_bajas = [c.strip() for c in bajas_cols.split(",") if c.strip() in _DEFAULT_BAJAS_COLS] if bajas_cols else _DEFAULT_BAJAS_COLS
    if not valid_citas:
        valid_citas = _DEFAULT_CITAS_COLS
    if not valid_bajas:
        valid_bajas = _DEFAULT_BAJAS_COLS

    # Parsear opciones de resumen
    valid_summary_opts = {"total", "coordinator", "program"}
    citas_summary_opts = [s.strip() for s in citas_summary.split(",") if s.strip() in valid_summary_opts]
    bajas_summary_opts = [s.strip() for s in bajas_summary.split(",") if s.strip() in valid_summary_opts]

    # Query base
    base_qry = (
        db.query(Req)
        .options(
            joinedload(Req.appointment).joinedload(Appointment.coordinator).joinedload(Coordinator.user),
            joinedload(Req.appointment).joinedload(Appointment.slot),
            joinedload(Req.program).joinedload(Program.program_coordinators)
                .joinedload(ProgramCoordinator.coordinator).joinedload(Coordinator.user),
            joinedload(Req.student),
            joinedload(Req.period),
        )
        .filter(Req.created_at >= start, Req.created_at <= end)
    )

    if statuses:
        base_qry = base_qry.filter(Req.status.in_(statuses) if len(statuses) > 1 else Req.status == statuses[0])
    if prog_ids:
        base_qry = base_qry.filter(Req.program_id.in_(prog_ids) if len(prog_ids) > 1 else Req.program_id == prog_ids[0])
    if coord_ids:
        base_qry = base_qry.join(Appointment, Appointment.request_id == Req.id, isouter=True)
        base_qry = base_qry.filter(Appointment.coordinator_id.in_(coord_ids) if len(coord_ids) > 1 else Appointment.coordinator_id == coord_ids[0])
    if period_id:
        base_qry = base_qry.filter(Req.period_id == period_id)
    if q.strip():
        terms = [t.strip() for t in q.split(",") if t.strip()]
        if terms:
            base_qry = base_qry.join(User, User.id == Req.student_id)
            conditions = []
            for term in terms:
                conditions.append(User.control_number.ilike(f"%{term}%"))
                conditions.append(User.full_name.ilike(f"%{term}%"))
            base_qry = base_qry.filter(or_(*conditions))
    if apt_statuses and not coord_ids:
        base_qry = base_qry.join(Appointment, Appointment.request_id == Req.id, isouter=True)
    if apt_statuses:
        base_qry = base_qry.filter(Appointment.status.in_(apt_statuses) if len(apt_statuses) > 1 else Appointment.status == apt_statuses[0])
    if type:
        base_qry = base_qry.filter(Req.type == type)

    all_requests = base_qry.all()

    appointments_data = []
    drops_data = []

    for r in all_requests:
        student = r.student
        program = r.program
        period = r.period
        a = r.appointment

        coord_name = None
        if a and a.coordinator and a.coordinator.user:
            coord_name = a.coordinator.user.full_name
        elif program and program.program_coordinators:
            first = program.program_coordinators[0] if program.program_coordinators else None
            if first and first.coordinator and first.coordinator.user:
                coord_name = first.coordinator.user.full_name

        if r.type == "APPOINTMENT" and a and a.slot and a.slot.is_booked:
            slot = a.slot
            appointments_data.append({
                "ID": r.id,
                "Día": slot.day.strftime("%Y-%m-%d") if slot.day else None,
                "Horario": f"{slot.start_time.strftime('%H:%M')} - {slot.end_time.strftime('%H:%M')}" if slot.start_time else None,
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

    appointments_data.sort(key=lambda x: (x["Día"] or "", x["HoraInicio"] or ""))
    for row in appointments_data:
        del row["HoraInicio"]

    if order_by == "student_name":
        drops_data.sort(key=lambda x: (x["Alumno"] or "").lower(), reverse=(order_dir == "desc"))
    elif order_by == "program":
        drops_data.sort(key=lambda x: (x["Programa"] or "").lower(), reverse=(order_dir == "desc"))
    else:
        drops_data.sort(key=lambda x: x["Creado"] or "", reverse=(order_dir == "desc"))

    df_appointments = pd.DataFrame(appointments_data)
    df_drops = pd.DataFrame(drops_data)

    if not df_appointments.empty:
        cols = [c for c in valid_citas if c in df_appointments.columns]
        if cols:
            df_appointments = df_appointments[cols]
    if not df_drops.empty:
        cols = [c for c in valid_bajas if c in df_drops.columns]
        if cols:
            df_drops = df_drops[cols]

    buf = BytesIO()
    _write_excel(buf, df_appointments, df_drops, valid_citas, valid_bajas,
                 citas_summary_opts, bajas_summary_opts)
    buf.seek(0)

    safe_name = re.sub(r'[<>:"/\\|?*]', '_', filename) if filename else ""
    dl_name = f"{safe_name}.xlsx" if safe_name else f"reporte_agendatec_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{dl_name}"'},
    )


# ---------------------------------------------------------------------------
# Excel builder
# ---------------------------------------------------------------------------

def _write_excel(buf, df_appointments, df_drops, citas_cols, bajas_cols,
                 citas_summary_opts, bajas_summary_opts):
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        wb = writer.book

        # Formatos base
        header_fmt = wb.add_format({
            'bold': True, 'bg_color': '#2F5496', 'font_color': 'white',
            'border': 1, 'align': 'center', 'valign': 'vcenter',
            'font_size': 11, 'text_wrap': True,
        })
        cell_even = wb.add_format({
            'border': 1, 'align': 'left', 'valign': 'vcenter',
            'text_wrap': True, 'font_size': 10, 'bg_color': '#FFFFFF',
        })
        cell_odd = wb.add_format({
            'border': 1, 'align': 'left', 'valign': 'vcenter',
            'text_wrap': True, 'font_size': 10, 'bg_color': '#F2F2F2',
        })
        id_even = wb.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10, 'bg_color': '#FFFFFF', 'bold': True})
        id_odd  = wb.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10, 'bg_color': '#F2F2F2', 'bold': True})
        dt_even = wb.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10, 'bg_color': '#FFFFFF'})
        dt_odd  = wb.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10, 'bg_color': '#F2F2F2'})

        def _mk(bg_e, bg_o, fc_e='#000000', fc_o='#000000'):
            return (
                wb.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10, 'bg_color': bg_e, 'font_color': fc_e, 'bold': True}),
                wb.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10, 'bg_color': bg_o, 'font_color': fc_o, 'bold': True}),
            )

        status_fmts = {
            'Resuelta':              _mk('#C6EFCE', '#A9D8B8', '#006100', '#006100'),
            'Atendida sin resolver': _mk('#E2EFDA', '#D4E7C5', '#375623', '#375623'),
            'No asistió':           _mk('#FFC7CE', '#FFAAB5', '#9C0006', '#9C0006'),
            'Asistió otro horario': _mk('#BDD7EE', '#9BC2E6', '#1F4E79', '#1F4E79'),
            'Pendiente':             _mk('#D9D9D9', '#BFBFBF', '#404040', '#404040'),
            'Cancelada':             _mk('#404040', '#2D2D2D', '#FFFFFF', '#FFFFFF'),
        }
        cita_fmts = {
            'Programada': _mk('#DDEBF7', '#BDD7EE', '#1F4E79', '#1F4E79'),
            'Completada': _mk('#C6EFCE', '#A9D8B8', '#006100', '#006100'),
            'No asistió': _mk('#FCE4D6', '#F8CBAD', '#974706', '#974706'),
            'Cancelada':  _mk('#FFC7CE', '#FFAAB5', '#9C0006', '#9C0006'),
        }

        def get_fmt(col, val, idx):
            is_odd = idx % 2 == 1
            if col in ('EstadoSolicitud', 'Estado'):
                f = status_fmts.get(val)
                if f:
                    return f[1] if is_odd else f[0]
            elif col == 'EstadoCita':
                f = cita_fmts.get(val)
                if f:
                    return f[1] if is_odd else f[0]
            elif col == 'ID':
                return id_odd if is_odd else id_even
            elif col in ('Día', 'Horario', 'Creado', 'Actualizado'):
                return dt_odd if is_odd else dt_even
            return cell_odd if is_odd else cell_even

        def write_sheet(ws, df, cols):
            for ci, cn in enumerate(cols):
                ws.write(0, ci, cn, header_fmt)
                ws.set_column(ci, ci, _COL_WIDTHS.get(cn, 15))
            for ri, row in df.iterrows():
                for ci, cn in enumerate(cols):
                    ws.write(ri + 1, ci, row.get(cn, ''), get_fmt(cn, row.get(cn, ''), ri))
            ws.freeze_panes(1, 0)
            ws.set_row(0, 22)
            if len(df) > 0:
                ws.autofilter(0, 0, len(df), len(cols) - 1)

        # Formatos de resumen
        sum_hdr   = wb.add_format({'bold': True, 'bg_color': '#1F4E79', 'font_color': 'white', 'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10})
        sum_sub   = wb.add_format({'bold': True, 'bg_color': '#2F5496', 'font_color': 'white', 'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 9})
        sum_day   = wb.add_format({'bold': True, 'bg_color': '#D6DCE4', 'font_color': '#1F4E79', 'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10})
        sum_cell  = wb.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10, 'bg_color': '#FFFFFF'})
        sum_tot   = wb.add_format({'bold': True, 'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10, 'bg_color': '#E2EFDA', 'font_color': '#375623'})
        sum_grand = wb.add_format({'bold': True, 'border': 2, 'align': 'center', 'valign': 'vcenter', 'font_size': 11, 'bg_color': '#2F5496', 'font_color': 'white'})
        sum_sec   = wb.add_format({'bold': True, 'bg_color': '#4472C4', 'font_color': 'white', 'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10})

        estados = ['Resuelta', 'Atendida sin resolver', 'No asistió', 'Asistió otro horario', 'Pendiente', 'Cancelada']

        def write_citas_summary(ws, df, sc, opts):
            if df.empty or 'Día' not in df.columns or 'EstadoSolicitud' not in df.columns or not opts:
                return
            ncols = len(estados) + 2
            ws.merge_range(0, sc, 0, sc + ncols - 1, 'RESUMEN POR DÍA', sum_hdr)

            def _write_hdrs(row, c0):
                ws.write(row, c0, 'Día', sum_sub); ws.set_column(c0, c0, 12)
                for i, e in enumerate(estados):
                    ws.write(row, c0 + 1 + i, e[:15], sum_sub); ws.set_column(c0 + 1 + i, c0 + 1 + i, 10)
                ws.write(row, c0 + len(estados) + 1, 'Total', sum_sub)
                ws.set_column(c0 + len(estados) + 1, c0 + len(estados) + 1, 8)

            def _write_data(df_s, sr, c0):
                dias = sorted([d for d in df_s['Día'].unique() if d])
                row = sr
                totals = {e: 0 for e in estados}
                gran = 0
                for dia in dias:
                    dfd = df_s[df_s['Día'] == dia]
                    ws.write(row, c0, dia, sum_day)
                    td = 0
                    for i, e in enumerate(estados):
                        cnt = len(dfd[dfd['EstadoSolicitud'] == e])
                        f = status_fmts.get(e, (sum_cell, sum_cell))[0] if cnt > 0 else sum_cell
                        ws.write(row, c0 + 1 + i, cnt if cnt > 0 else '', f)
                        totals[e] += cnt; td += cnt
                    ws.write(row, c0 + len(estados) + 1, td, sum_tot)
                    gran += td; row += 1
                ws.write(row, c0, 'TOTAL', sum_grand)
                for i, e in enumerate(estados):
                    ws.write(row, c0 + 1 + i, totals[e], sum_grand)
                ws.write(row, c0 + len(estados) + 1, gran, sum_grand)
                return row + 1

            cr = 1
            if 'total' in opts:
                ws.merge_range(cr, sc, cr, sc + ncols - 1, 'TOTAL GENERAL', sum_sec); cr += 1
                _write_hdrs(cr, sc); cr += 1
                cr = _write_data(df, cr, sc) + 1

            if 'coordinator' in opts and 'Coordinador' in df.columns:
                for coord in sorted(set(c for c in df['Coordinador'].unique() if c)):
                    dfc = df[df['Coordinador'] == coord]
                    if dfc.empty: continue
                    ws.merge_range(cr, sc, cr, sc + ncols - 1, f"Coordinador: {coord}", sum_sec); cr += 1
                    _write_hdrs(cr, sc); cr += 1
                    cr = _write_data(dfc, cr, sc) + 1

            if 'program' in opts and 'Programa' in df.columns:
                for prog in sorted(set(p for p in df['Programa'].unique() if p)):
                    dfp = df[df['Programa'] == prog]
                    if dfp.empty: continue
                    ws.merge_range(cr, sc, cr, sc + ncols - 1, f"Carrera: {prog}", sum_sec); cr += 1
                    _write_hdrs(cr, sc); cr += 1
                    cr = _write_data(dfp, cr, sc) + 1

        def write_bajas_summary(ws, df, sc, opts):
            if df.empty or 'Estado' not in df.columns or not opts:
                return
            ws.merge_range(0, sc, 0, sc + 1, 'RESUMEN DE BAJAS', sum_hdr)

            def _block(sr, c0, df_s, title=None):
                row = sr
                if title:
                    ws.merge_range(row, c0, row, c0 + 1, title, sum_sec); row += 1
                ws.write(row, c0, 'Estado', sum_sub); ws.write(row, c0 + 1, 'Cantidad', sum_sub)
                ws.set_column(c0, c0, 22); ws.set_column(c0 + 1, c0 + 1, 10); row += 1
                total = 0
                for e in estados:
                    cnt = len(df_s[df_s['Estado'] == e])
                    if cnt > 0:
                        f = status_fmts.get(e, (sum_cell, sum_cell))[0]
                        ws.write(row, c0, e, f); ws.write(row, c0 + 1, cnt, f)
                        total += cnt; row += 1
                ws.write(row, c0, 'TOTAL', sum_grand); ws.write(row, c0 + 1, total, sum_grand)
                return row + 2

            cr = 1
            if 'total' in opts:
                cr = _block(cr, sc, df, 'TOTAL GENERAL')
            if 'program' in opts and 'Programa' in df.columns:
                for p in sorted(set(x for x in df['Programa'].unique() if x)):
                    cr = _block(cr, sc, df[df['Programa'] == p], f"Carrera: {p}")
            if 'coordinator' in opts and 'Coordinador' in df.columns:
                for c in sorted(set(x for x in df['Coordinador'].unique() if x)):
                    cr = _block(cr, sc, df[df['Coordinador'] == c], f"Coordinador: {c}")

        # Hoja Citas
        if not df_appointments.empty:
            ws_citas = wb.add_worksheet("Citas")
            writer.sheets["Citas"] = ws_citas
            cols_c = [c for c in citas_cols if c in df_appointments.columns]
            write_sheet(ws_citas, df_appointments[cols_c], cols_c)
            write_citas_summary(ws_citas, df_appointments, len(cols_c) + 2, citas_summary_opts)
        else:
            pd.DataFrame(columns=citas_cols).to_excel(writer, index=False, sheet_name="Citas")

        # Hoja Bajas
        if not df_drops.empty:
            ws_bajas = wb.add_worksheet("Solicitudes de Baja")
            writer.sheets["Solicitudes de Baja"] = ws_bajas
            cols_b = [c for c in bajas_cols if c in df_drops.columns]
            write_sheet(ws_bajas, df_drops[cols_b], cols_b)
            write_bajas_summary(ws_bajas, df_drops, len(cols_b) + 2, bajas_summary_opts)
        else:
            pd.DataFrame(columns=bajas_cols).to_excel(writer, index=False, sheet_name="Solicitudes de Baja")
