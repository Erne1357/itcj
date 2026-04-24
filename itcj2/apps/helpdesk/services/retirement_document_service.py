"""
Servicio de generación de documentos para solicitudes de baja de inventario.
Produce PDF con ReportLab (principal) y Excel con openpyxl (fallback).
"""
import io
import logging
import os

logger = logging.getLogger(__name__)

# ── Constantes institucionales ─────────────────────────────────────────────────

_DEPENDENCIA  = "SECRETARIA DE EDUCACION PUBLICA"
_ORGANISMO    = "TECNOLOGICO NACIONAL DE MEXICO"
_INSTITUCION  = "INSTITUTO TECNOLOGICO DE CD JUAREZ"
_CLAVE_CT     = "08DIT0014X"
_TITULO_DOC   = "SOLICITUD DE BAJA DE BIENES MUEBLES"

_STEP_TITLES = {
    1: "Jefe de Recursos Materiales y Servicios",
    2: "Subdirector de Servicios Administrativos",
    3: "Director",
}

_EXCEL_TEMPLATE = os.path.join(
    os.path.dirname(__file__),
    "..",
    "static",
    "data",
    "OFICIO PARA BAJAS-.xlsx",
)

_ITEMS_PER_PAGE = 15


class RetirementDocumentService:
    """Genera documentos oficiales para solicitudes de baja de inventario."""

    # ── PDF ────────────────────────────────────────────────────────────────────

    @staticmethod
    def generate_pdf(request) -> bytes:
        """
        Genera el PDF oficial de baja con ReportLab.
        Recibe el objeto InventoryRetirementRequest ya cargado (sin abrir DB).
        """
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import cm
            from reportlab.platypus import (
                SimpleDocTemplate, Table, TableStyle,
                Paragraph, Spacer, PageBreak, KeepTogether,
            )
        except ImportError as exc:
            logger.error(f"ReportLab no disponible: {exc}")
            raise RuntimeError("ReportLab no está instalado") from exc

        buffer = io.BytesIO()

        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            leftMargin=2 * cm,
            rightMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
        )

        styles = getSampleStyleSheet()

        # Estilos personalizados
        small_center = ParagraphStyle(
            "SmallCenter",
            parent=styles["Normal"],
            fontSize=8,
            alignment=1,  # CENTER
            spaceAfter=2,
        )
        bold_center = ParagraphStyle(
            "BoldCenter",
            parent=styles["Normal"],
            fontSize=10,
            alignment=1,
            fontName="Helvetica-Bold",
            spaceAfter=4,
        )
        title_style = ParagraphStyle(
            "TitleStyle",
            parent=styles["Normal"],
            fontSize=12,
            alignment=1,
            fontName="Helvetica-Bold",
            spaceBefore=4,
            spaceAfter=6,
        )
        label_style = ParagraphStyle(
            "LabelStyle",
            parent=styles["Normal"],
            fontSize=8,
            fontName="Helvetica-Bold",
        )
        value_style = ParagraphStyle(
            "ValueStyle",
            parent=styles["Normal"],
            fontSize=8,
        )
        sig_name_style = ParagraphStyle(
            "SigName",
            parent=styles["Normal"],
            fontSize=8,
            alignment=1,
            fontName="Helvetica-Bold",
        )
        sig_label_style = ParagraphStyle(
            "SigLabel",
            parent=styles["Normal"],
            fontSize=7,
            alignment=1,
        )
        sig_pending_style = ParagraphStyle(
            "SigPending",
            parent=styles["Normal"],
            fontSize=7,
            alignment=1,
            textColor=colors.grey,
        )
        sig_rejected_style = ParagraphStyle(
            "SigRejected",
            parent=styles["Normal"],
            fontSize=8,
            alignment=1,
            fontName="Helvetica-Bold",
            textColor=colors.red,
        )

        page_width = letter[0] - 4 * cm  # ancho útil

        story = []

        # ── 1. Encabezado ──────────────────────────────────────────────────────
        story.append(Paragraph(_DEPENDENCIA, small_center))
        story.append(Paragraph(_ORGANISMO, small_center))
        story.append(Paragraph(_INSTITUCION, bold_center))
        story.append(Spacer(1, 0.2 * cm))

        title_table = Table(
            [[Paragraph(_TITULO_DOC, title_style)]],
            colWidths=[page_width],
        )
        title_table.setStyle(TableStyle([
            ("BOX",       (0, 0), (-1, -1), 1, colors.black),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#E8E8E8")),
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(title_table)
        story.append(Spacer(1, 0.4 * cm))

        # ── 2. Datos generales ─────────────────────────────────────────────────
        fecha_str = (
            request.created_at.strftime("%d/%m/%Y")
            if request.created_at
            else "—"
        )
        solicitante = (
            request.requested_by.full_name
            if request.requested_by
            else "—"
        )

        general_data = [
            ["Folio:",           request.folio or "—",
             "Fecha:",           fecha_str],
            ["Área/Plantel:",    _INSTITUCION,
             "Clave CT:",        _CLAVE_CT],
            ["Causa de baja:",   request.reason or "—",
             "Solicitante:",     solicitante],
        ]

        col_w = page_width / 4
        gen_table = Table(
            [
                [
                    Paragraph(row[0], label_style),
                    Paragraph(str(row[1]), value_style),
                    Paragraph(row[2], label_style),
                    Paragraph(str(row[3]), value_style),
                ]
                for row in general_data
            ],
            colWidths=[col_w * 0.6, col_w * 1.4, col_w * 0.6, col_w * 1.4],
        )
        gen_table.setStyle(TableStyle([
            ("BOX",       (0, 0), (-1, -1), 0.5, colors.black),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("BACKGROUND", (0, 0), (-1, -1), colors.white),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (-1, -1), 4),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(gen_table)
        story.append(Spacer(1, 0.4 * cm))

        # ── 3. Tabla de equipos ────────────────────────────────────────────────
        all_items = list(request.items.all())

        story.append(Paragraph("RELACIÓN DE BIENES MUEBLES", bold_center))
        story.append(Spacer(1, 0.2 * cm))

        headers = ["No.", "No. Inventario", "Descripción", "Valor",
                   "Diagnóstico", "Desalojo", "Bodega", "Afectación"]

        col_widths = [
            page_width * 0.04,   # No.
            page_width * 0.14,   # No. Inventario
            page_width * 0.22,   # Descripción
            page_width * 0.09,   # Valor
            page_width * 0.27,   # Diagnóstico
            page_width * 0.08,   # Desalojo
            page_width * 0.08,   # Bodega
            page_width * 0.08,   # Afectación
        ]

        header_style = ParagraphStyle(
            "HeaderCell",
            parent=styles["Normal"],
            fontSize=7,
            fontName="Helvetica-Bold",
            alignment=1,
        )
        cell_style = ParagraphStyle(
            "BodyCell",
            parent=styles["Normal"],
            fontSize=7,
        )
        cell_center = ParagraphStyle(
            "BodyCellCenter",
            parent=styles["Normal"],
            fontSize=7,
            alignment=1,
        )

        header_row = [Paragraph(h, header_style) for h in headers]

        # Partir en páginas de _ITEMS_PER_PAGE
        chunks = [
            all_items[i: i + _ITEMS_PER_PAGE]
            for i in range(0, max(len(all_items), 1), _ITEMS_PER_PAGE)
        ]

        for chunk_idx, chunk in enumerate(chunks):
            rows = [header_row]
            for seq, ri in enumerate(chunk, start=chunk_idx * _ITEMS_PER_PAGE + 1):
                inv_item = ri.inventory_item
                inv_number = inv_item.inventory_number if inv_item else "—"
                descripcion = (
                    f"{inv_item.brand or ''} {inv_item.model or ''}".strip()
                    if inv_item
                    else "—"
                )
                valor = (
                    f"${ri.valor_unitario:,.2f}"
                    if ri.valor_unitario is not None
                    else ""
                )
                diagnostico = ri.item_notes or ""
                rows.append([
                    Paragraph(str(seq), cell_center),
                    Paragraph(inv_number, cell_style),
                    Paragraph(descripcion, cell_style),
                    Paragraph(valor, cell_center),
                    Paragraph(diagnostico, cell_style),
                    Paragraph("X" if ri.desalojo else "", cell_center),
                    Paragraph("X" if ri.bodega else "", cell_center),
                    Paragraph("X" if ri.afectacion else "", cell_center),
                ])

            items_table = Table(rows, colWidths=col_widths, repeatRows=1)
            items_table.setStyle(TableStyle([
                ("BOX",        (0, 0), (-1, -1), 0.75, colors.black),
                ("INNERGRID",  (0, 0), (-1, -1), 0.25, colors.grey),
                ("BACKGROUND", (0, 0), (7, 0), colors.HexColor("#D0D0D0")),
                ("TOPPADDING",    (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING",   (0, 0), (-1, -1), 3),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 3),
                ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ]))

            story.append(KeepTogether(items_table))

            if chunk_idx < len(chunks) - 1:
                story.append(PageBreak())

        story.append(Spacer(1, 0.6 * cm))

        # ── 4. Sección de firmas ───────────────────────────────────────────────
        story.append(Paragraph("AUTORIZACIONES", bold_center))
        story.append(Spacer(1, 0.3 * cm))

        # Indexar firmas por step
        sigs_by_step = {}
        for sig in request.signatures:
            sigs_by_step[sig.step] = sig

        sig_cells = []
        for step in (1, 2, 3):
            sig = sigs_by_step.get(step)
            fallback_title = _STEP_TITLES[step]

            if sig is None:
                # Sin registro de firma todavía
                cell_content = [
                    Paragraph("___________________________", sig_label_style),
                    Spacer(1, 0.15 * cm),
                    Paragraph(fallback_title, sig_name_style),
                    Paragraph("Pendiente de autorización", sig_pending_style),
                ]
            elif sig.action == "APPROVED":
                nombre = sig.signed_by.full_name if sig.signed_by else "—"
                cargo = sig.position_title or fallback_title
                fecha_firma = (
                    sig.signed_at.strftime("%d/%m/%Y")
                    if sig.signed_at
                    else "—"
                )
                cell_content = [
                    Paragraph(nombre, sig_name_style),
                    Paragraph(cargo, sig_label_style),
                    Paragraph(f"Fecha: {fecha_firma}", sig_label_style),
                    Spacer(1, 0.1 * cm),
                    Paragraph("APROBADO", ParagraphStyle(
                        "Approved",
                        parent=styles["Normal"],
                        fontSize=8,
                        alignment=1,
                        fontName="Helvetica-Bold",
                        textColor=colors.HexColor("#1a7a1a"),
                    )),
                ]
            elif sig.action == "REJECTED":
                cargo = sig.position_title or fallback_title
                cell_content = [
                    Paragraph(cargo, sig_name_style),
                    Spacer(1, 0.15 * cm),
                    Paragraph("RECHAZADO", sig_rejected_style),
                ]
            else:
                # Registro existe pero sin acción todavía
                cargo = sig.position_title or fallback_title
                cell_content = [
                    Paragraph("___________________________", sig_label_style),
                    Spacer(1, 0.15 * cm),
                    Paragraph(cargo, sig_name_style),
                    Paragraph("Pendiente de autorización", sig_pending_style),
                ]

            sig_cells.append(cell_content)

        sig_col_w = page_width / 3

        # Construir tabla de firmas: cada celda contiene una lista de flowables
        # ReportLab Table no acepta flowables directamente, usamos una sub-tabla
        def _make_sig_cell(content_list):
            """Empaqueta flowables en una sub-tabla de celda única."""
            rows = [[item] for item in content_list]
            t = Table(rows, colWidths=[sig_col_w - 0.6 * cm])
            t.setStyle(TableStyle([
                ("TOPPADDING",    (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING",   (0, 0), (-1, -1), 0),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
            ]))
            return t

        sig_table = Table(
            [[_make_sig_cell(sig_cells[0]),
              _make_sig_cell(sig_cells[1]),
              _make_sig_cell(sig_cells[2])]],
            colWidths=[sig_col_w, sig_col_w, sig_col_w],
        )
        sig_table.setStyle(TableStyle([
            ("BOX",       (0, 0), (-1, -1), 0.75, colors.black),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.black),
            ("TOPPADDING",    (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 20),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ]))

        story.append(KeepTogether(sig_table))

        # ── Pie de página con folio ────────────────────────────────────────────
        story.append(Spacer(1, 0.4 * cm))
        story.append(Paragraph(
            f"Folio: {request.folio}  |  {_CLAVE_CT}  |  Generado el "
            f"{__import__('datetime').datetime.now().strftime('%d/%m/%Y %H:%M')}",
            ParagraphStyle("Footer", parent=styles["Normal"], fontSize=7,
                           alignment=1, textColor=colors.grey),
        ))

        doc.build(story)
        return buffer.getvalue()

    # ── Excel ──────────────────────────────────────────────────────────────────

    @staticmethod
    def fill_excel_template(request) -> bytes:
        """
        Llena la plantilla Excel oficial de bajas y retorna bytes.
        Si la plantilla no existe, genera un Excel simple desde cero como fallback.
        Recibe el objeto InventoryRetirementRequest ya cargado (sin abrir DB).
        """
        try:
            import openpyxl
        except ImportError as exc:
            logger.error(f"openpyxl no disponible: {exc}")
            raise RuntimeError("openpyxl no está instalado") from exc

        template_path = os.path.normpath(_EXCEL_TEMPLATE)

        try:
            wb = openpyxl.load_workbook(template_path, keep_vba=False)
            ws = wb.active
            RetirementDocumentService._fill_worksheet(ws, request)
            logger.info(f"Excel generado desde plantilla para {request.folio}")
        except FileNotFoundError:
            logger.warning(
                f"Plantilla Excel no encontrada en {template_path}. "
                "Generando Excel simple."
            )
            wb = RetirementDocumentService._build_simple_excel(request)
        except Exception as exc:
            logger.error(f"Error cargando plantilla Excel: {exc}. Usando Excel simple.")
            wb = RetirementDocumentService._build_simple_excel(request)

        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    @staticmethod
    def _fill_worksheet(ws, request):
        """
        Rellena la hoja activa de la plantilla buscando celdas clave por contenido.
        Campos objetivo: FECHA, FOLIO, NOMBRE, SOLICITANTE, CAUSA, DEPENDENCIA, ORGANISMO.
        Agrega equipos a partir de la primera fila vacía después del encabezado de tabla.
        """
        fecha_str = (
            request.created_at.strftime("%d/%m/%Y")
            if request.created_at
            else ""
        )
        solicitante = request.requested_by.full_name if request.requested_by else ""

        # Mapa: fragmento a buscar (upper) → valor a insertar
        field_map = {
            "FECHA":       fecha_str,
            "FOLIO":       request.folio or "",
            "NOMBRE DEL RESPONSABLE": solicitante,
            "SOLICITANTE": solicitante,
            "CAUSA":       request.reason or "",
            "MOTIVO":      request.reason or "",
            "CLAVE CT":    _CLAVE_CT,
        }

        # Primera pasada: buscar etiquetas y rellenar celda adyacente o la misma
        for row in ws.iter_rows():
            for cell in row:
                if cell.value is None:
                    continue
                val_upper = str(cell.value).strip().upper()
                for keyword, replacement in field_map.items():
                    if keyword in val_upper and replacement:
                        # Intentar rellenar la celda de la derecha
                        next_cell = ws.cell(row=cell.row, column=cell.column + 1)
                        if next_cell.value is None or str(next_cell.value).strip() == "":
                            next_cell.value = replacement
                        else:
                            # La celda misma es el campo (tiene el valor como placeholder)
                            cell.value = replacement
                        break

        # Segunda pasada: encontrar primera fila con "No." o "INVENTARIO" en header
        # y a partir de la siguiente fila vacía insertar los equipos
        table_start_row = None
        for row in ws.iter_rows(max_col=10):
            for cell in row:
                if cell.value and "INVENTARIO" in str(cell.value).upper():
                    table_start_row = cell.row + 1
                    break
            if table_start_row:
                break

        if table_start_row is None:
            # No encontramos la tabla de inventario; intentar después de la mitad
            table_start_row = ws.max_row + 2

        all_items = list(request.items.all())
        for idx, ri in enumerate(all_items):
            inv_item = ri.inventory_item
            row_num = table_start_row + idx
            inv_number = inv_item.inventory_number if inv_item else ""
            descripcion = (
                f"{inv_item.brand or ''} {inv_item.model or ''}".strip()
                if inv_item
                else ""
            )
            valor = str(ri.valor_unitario) if ri.valor_unitario is not None else ""
            diagnostico = ri.item_notes or ""

            ws.cell(row=row_num, column=1).value = idx + 1
            ws.cell(row=row_num, column=2).value = inv_number
            ws.cell(row=row_num, column=3).value = descripcion
            ws.cell(row=row_num, column=4).value = valor
            ws.cell(row=row_num, column=5).value = diagnostico
            ws.cell(row=row_num, column=6).value = "X" if ri.desalojo else ""
            ws.cell(row=row_num, column=7).value = "X" if ri.bodega else ""
            ws.cell(row=row_num, column=8).value = "X" if ri.afectacion else ""

    @staticmethod
    def _build_simple_excel(request) -> object:
        """
        Genera un Excel básico desde cero cuando la plantilla no está disponible.
        Retorna un Workbook de openpyxl.
        """
        import openpyxl
        from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Baja de Bienes"

        thin = Side(style="thin")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        def hdr(text):
            return {
                "value": text,
                "font": Font(bold=True),
                "alignment": Alignment(horizontal="center", vertical="center", wrap_text=True),
                "fill": PatternFill("solid", fgColor="D0D0D0"),
                "border": border,
            }

        def cell_val(text):
            return {
                "value": text,
                "alignment": Alignment(vertical="top", wrap_text=True),
                "border": border,
            }

        def apply(cell, props):
            for attr, val in props.items():
                setattr(cell, attr, val)

        # Encabezado institucional
        row = 1
        ws.merge_cells(f"A{row}:H{row}")
        c = ws.cell(row=row, column=1, value=_DEPENDENCIA)
        c.font = Font(bold=True)
        c.alignment = Alignment(horizontal="center")
        row += 1

        ws.merge_cells(f"A{row}:H{row}")
        c = ws.cell(row=row, column=1, value=_ORGANISMO)
        c.font = Font(bold=True)
        c.alignment = Alignment(horizontal="center")
        row += 1

        ws.merge_cells(f"A{row}:H{row}")
        c = ws.cell(row=row, column=1, value=_INSTITUCION)
        c.font = Font(bold=True, size=12)
        c.alignment = Alignment(horizontal="center")
        row += 1

        ws.merge_cells(f"A{row}:H{row}")
        c = ws.cell(row=row, column=1, value=_TITULO_DOC)
        c.font = Font(bold=True, size=12)
        c.alignment = Alignment(horizontal="center")
        c.fill = PatternFill("solid", fgColor="E8E8E8")
        row += 2

        # Datos generales
        fecha_str = (
            request.created_at.strftime("%d/%m/%Y") if request.created_at else ""
        )
        solicitante = request.requested_by.full_name if request.requested_by else ""

        fields = [
            ("Folio:", request.folio or ""),
            ("Fecha:", fecha_str),
            ("Área/Plantel:", _INSTITUCION),
            ("Clave CT:", _CLAVE_CT),
            ("Causa de baja:", request.reason or ""),
            ("Solicitante:", solicitante),
        ]

        for label, value in fields:
            ws.cell(row=row, column=1, value=label).font = Font(bold=True)
            ws.merge_cells(f"B{row}:H{row}")
            ws.cell(row=row, column=2, value=value)
            row += 1

        row += 1

        # Encabezado tabla de equipos
        headers = [
            "No.", "No. Inventario", "Descripción", "Valor Unitario",
            "Diagnóstico", "Desalojo", "Bodega", "Afectación",
        ]
        col_widths = [5, 15, 30, 12, 35, 10, 10, 12]
        for col_idx, (h, w) in enumerate(zip(headers, col_widths), start=1):
            apply(ws.cell(row=row, column=col_idx), hdr(h))
            ws.column_dimensions[
                openpyxl.utils.get_column_letter(col_idx)
            ].width = w

        row += 1

        # Equipos
        all_items = list(request.items.all())
        for seq, ri in enumerate(all_items, start=1):
            inv_item = ri.inventory_item
            inv_number = inv_item.inventory_number if inv_item else ""
            descripcion = (
                f"{inv_item.brand or ''} {inv_item.model or ''}".strip()
                if inv_item else ""
            )
            valor = (
                f"{ri.valor_unitario:,.2f}"
                if ri.valor_unitario is not None
                else ""
            )
            diagnostico = ri.item_notes or ""

            row_data = [
                str(seq), inv_number, descripcion, valor, diagnostico,
                "X" if ri.desalojo else "",
                "X" if ri.bodega else "",
                "X" if ri.afectacion else "",
            ]
            for col_idx, val in enumerate(row_data, start=1):
                apply(ws.cell(row=row, column=col_idx), cell_val(val))
            row += 1

        row += 2

        # Firmas
        sigs_by_step = {}
        for sig in request.signatures:
            sigs_by_step[sig.step] = sig

        ws.merge_cells(f"A{row}:H{row}")
        c = ws.cell(row=row, column=1, value="AUTORIZACIONES")
        c.font = Font(bold=True)
        c.alignment = Alignment(horizontal="center")
        row += 1

        sig_headers = [_STEP_TITLES.get(s, f"Firmante {s}") for s in (1, 2, 3)]
        # 3 columnas de firma: A-B, C-E, F-H (aprox)
        sig_cols = [(1, 2), (3, 5), (6, 8)]

        for (start_col, end_col), step in zip(sig_cols, (1, 2, 3)):
            sig = sigs_by_step.get(step)
            cargo = (
                sig.position_title if sig and sig.position_title
                else _STEP_TITLES[step]
            )

            col_letter_start = openpyxl.utils.get_column_letter(start_col)
            col_letter_end = openpyxl.utils.get_column_letter(end_col)
            range_str = f"{col_letter_start}{row}:{col_letter_end}{row}"
            ws.merge_cells(range_str)
            c = ws.cell(row=row, column=start_col, value=cargo)
            c.font = Font(bold=True)
            c.alignment = Alignment(horizontal="center")

            range_str2 = f"{col_letter_start}{row + 1}:{col_letter_end}{row + 1}"
            ws.merge_cells(range_str2)

            if sig is None or sig.action is None:
                ws.cell(row=row + 1, column=start_col, value="Pendiente de autorización").alignment = Alignment(horizontal="center")
            elif sig.action == "APPROVED":
                nombre = sig.signed_by.full_name if sig.signed_by else "—"
                fecha_f = sig.signed_at.strftime("%d/%m/%Y") if sig.signed_at else "—"
                ws.cell(row=row + 1, column=start_col, value=f"{nombre}\n{fecha_f}").alignment = Alignment(
                    horizontal="center", wrap_text=True
                )
            elif sig.action == "REJECTED":
                c2 = ws.cell(row=row + 1, column=start_col, value="RECHAZADO")
                c2.font = Font(bold=True, color="FF0000")
                c2.alignment = Alignment(horizontal="center")

        return wb
