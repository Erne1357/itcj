# routes/api/admin/surveys.py
"""
Endpoints para envío de encuestas.

Incluye:
- send_surveys: Envío de encuestas por correo
"""
from __future__ import annotations

import os

from flask import Blueprint, jsonify, request

from itcj.apps.agendatec.models import db
from itcj.apps.agendatec.models.request import Request as Req
from itcj.core.models.user import User
from itcj.core.utils.decorators import api_app_required, api_auth_required
from itcj.core.utils.email_tools import student_email
from itcj.core.utils.msgraph_mail import acquire_token_silent, graph_send_mail

from .helpers import range_from_query

admin_surveys_bp = Blueprint("admin_surveys", __name__)


@admin_surveys_bp.post("/surveys/send")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.surveys.api.send"])
def send_surveys():
    """
    Envía correos de encuesta a estudiantes atendidos.

    Query params:
        from, to: Rango de fechas para buscar estudiantes
        limit: Máximo de destinatarios (default 200)
        offset: Desplazamiento para paginación
        test: Si es 1/true/yes, envía solo al correo de prueba

    Returns:
        JSON con sent (cantidad enviados), errors y total_targets
    """
    # Token MSAL
    token = acquire_token_silent()
    if not token:
        return jsonify({
            "error": "no_ms_session",
            "message": "Inicia sesión en la pestaña 'Conexión Outlook'."
        }), 401

    # Filtros
    start, end = range_from_query()
    limit = request.args.get("limit", type=int) or 200
    offset = request.args.get("offset", type=int) or 0
    is_test = request.args.get("test", "0") in ("1", "true", "yes")

    # Destinatarios
    targets = []
    if is_test:
        targets = ["jefatura_cc@cdjuarez.tecnm.mx"]
    else:
        q = (
            db.session.query(User)
            .join(Req, Req.student_id == User.id)
            .filter(
                Req.status.notin_(["PENDING", "CANCELED", "NO_SHOW"]),
                Req.updated_at >= start,
                Req.updated_at <= end,
            )
            .order_by(Req.updated_at.desc())
            .limit(limit).offset(offset)
        )
        rows = [student_email(e) for e in q.all() if e]
        targets = [r for r in rows if r]

    if not targets:
        return jsonify({"ok": True, "sent": 0, "detail": "Sin destinatarios"}), 200

    # Contenido del correo
    forms_url = os.getenv("SURVEY_FORMS_URL", "https://forms.office.com/r/xxxxx")
    subject = "Encuesta de satisfacción AgendaTec"
    html = f"""
      <p>¡Hola! 👋</p>
      <p>Si recientemente realizaste un trámite en AgendaTec, para nosotros es muy importante 
      tu opinión en la mejora de nuestros servicios, apóyanos respondiendo está breve encuesta.</p>
      <p>Por favor, responde esta encuesta rápida (menos de 1 minuto):<br>
      <a href="{forms_url}">{forms_url}</a></p>
      <p>¡Gracias!</p>
    """

    # Enviar en lotes pequeños
    sent, errors = 0, []
    for addr in targets:
        r = graph_send_mail(token, subject, html, [addr])
        if r.status_code in (202, 200):
            sent += 1
        else:
            errors.append({"to": addr, "status": r.status_code, "body": r.text})

    return jsonify({"ok": True, "sent": sent, "errors": errors, "total_targets": len(targets)})
