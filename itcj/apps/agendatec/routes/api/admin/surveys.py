# routes/api/admin/surveys.py
"""
Endpoints para envío de encuestas.

Incluye:
- send_surveys: Envío de encuestas por correo
"""
from __future__ import annotations

import os
from datetime import datetime

from flask import Blueprint, jsonify, request

from itcj.apps.agendatec.models import db
from itcj.apps.agendatec.models.request import Request as Req
from itcj.core.models.user import User
from itcj.core.utils.decorators import api_app_required, api_auth_required
from itcj.core.utils.email_tools import student_email
from itcj.apps.agendatec.utils.msgraph_mail import acquire_token_silent, graph_send_mail

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
        targets = ["l21111182@cdjuarez.tecnm.mx"]
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

    # Contenido del correo - Diseño profesional
    forms_url = os.getenv("SURVEY_FORMS_URL", "https://forms.office.com/r/xxxxx")
    subject = "📋 Tu opinión nos importa | AgendaTec"
    html = f"""
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; font-family: Arial, Helvetica, sans-serif; background-color: #f4f4f5;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color: #f4f4f5; padding: 40px 20px;">
    <tr>
      <td align="center">
        <table role="presentation" width="600" cellspacing="0" cellpadding="0" border="0" style="background-color: #ffffff; border-radius: 8px; border: 1px solid #e5e7eb;">
          <!-- Header -->
          <tr>
            <td align="center" style="background-color: #1e3a5f; padding: 32px 40px;">
              <table role="presentation" cellspacing="0" cellpadding="0" border="0">
                <tr>
                  <td align="center">
                    <img src="https://img.icons8.com/emoji/48/graduation-cap-emoji.png" alt="🎓" width="48" height="48" style="display: block;">
                  </td>
                </tr>
                <tr>
                  <td align="center" style="padding-top: 12px;">
                    <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: bold; font-family: Arial, Helvetica, sans-serif;">
                      AgendaTec
                    </h1>
                  </td>
                </tr>
                <tr>
                  <td align="center" style="padding-top: 8px;">
                    <p style="margin: 0; color: #93c5fd; font-size: 14px; font-family: Arial, Helvetica, sans-serif;">
                      Instituto Tecnológico de Ciudad Juárez
                    </p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          
          <!-- Contenido principal -->
          <tr>
            <td style="padding: 40px;">
              <h2 style="margin: 0 0 16px 0; color: #1f2937; font-size: 22px; font-weight: bold; font-family: Arial, Helvetica, sans-serif;">
                ¡Hola! 👋
              </h2>
              
              <p style="margin: 0 0 16px 0; color: #4b5563; font-size: 16px; line-height: 24px; font-family: Arial, Helvetica, sans-serif;">
                Recientemente realizaste un trámite a través de <strong>AgendaTec</strong>. 
                Tu opinión es muy importante para nosotros y nos ayuda a mejorar continuamente 
                nuestros servicios.
              </p>
              
              <p style="margin: 0 0 32px 0; color: #4b5563; font-size: 16px; line-height: 24px; font-family: Arial, Helvetica, sans-serif;">
                ¿Podrías tomarte <strong>menos de 1 minuto</strong> para responder una breve encuesta 
                sobre tu experiencia?
              </p>
              
              <!-- Botón CTA -->
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                <tr>
                  <td align="center" style="padding: 8px 0 32px 0;">
                    <!--[if mso]>
                    <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" href="{forms_url}" style="height:50px;v-text-anchor:middle;width:250px;" arcsize="16%" strokecolor="#1d4ed8" fillcolor="#2563eb">
                      <w:anchorlock/>
                      <center style="color:#ffffff;font-family:Arial,sans-serif;font-size:16px;font-weight:bold;">📝 Responder Encuesta</center>
                    </v:roundrect>
                    <![endif]-->
                    <!--[if !mso]><!-->
                    <a href="{forms_url}" 
                       target="_blank"
                       style="display: inline-block; background-color: #2563eb; 
                              color: #ffffff; text-decoration: none; padding: 16px 40px; 
                              border-radius: 8px; font-size: 16px; font-weight: bold; 
                              font-family: Arial, Helvetica, sans-serif;
                              border: 2px solid #1d4ed8;">
                      📝 Responder Encuesta
                    </a>
                    <!--<![endif]-->
                  </td>
                </tr>
              </table>
              
              <!-- Info adicional -->
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                <tr>
                  <td style="background-color: #eff6ff; border-left: 4px solid #2563eb; padding: 16px 20px;">
                    <p style="margin: 0; color: #1e40af; font-size: 14px; line-height: 22px; font-family: Arial, Helvetica, sans-serif;">
                      <strong>💡 ¿Por qué es importante?</strong><br>
                      Tus comentarios nos permiten identificar áreas de mejora y brindarte 
                      un mejor servicio en el futuro.
                    </p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          
          <!-- Footer -->
          <tr>
            <td style="background-color: #f9fafb; padding: 24px 40px; border-top: 1px solid #e5e7eb;">
              <p style="margin: 0 0 8px 0; color: #6b7280; font-size: 13px; text-align: center; font-family: Arial, Helvetica, sans-serif;">
                ¡Gracias por tu tiempo y colaboración! 🙏
              </p>
              <p style="margin: 0; color: #9ca3af; font-size: 12px; text-align: center; font-family: Arial, Helvetica, sans-serif;">
                Este correo fue enviado automáticamente por AgendaTec.<br>
                Instituto Tecnológico de Ciudad Juárez © {datetime.now().year}
              </p>
            </td>
          </tr>
        </table>
        
        <!-- Link alternativo -->
        <table role="presentation" width="600" cellspacing="0" cellpadding="0" border="0">
          <tr>
            <td align="center" style="padding: 24px 20px;">
              <p style="margin: 0; color: #6b7280; font-size: 12px; font-family: Arial, Helvetica, sans-serif;">
                ¿El botón no funciona? Copia y pega este enlace en tu navegador:
              </p>
              <p style="margin: 8px 0 0 0;">
                <a href="{forms_url}" style="color: #2563eb; font-size: 12px; word-break: break-all; font-family: Arial, Helvetica, sans-serif;">{forms_url}</a>
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
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
