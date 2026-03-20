"""
Admin Surveys API v2 — Envío de encuestas por correo.
Fuente: itcj/apps/agendatec/routes/api/admin/surveys.py
"""
import logging
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.agendatec.helpers import parse_range_from_params
from itcj2.apps.agendatec.models.request import Request as Req
from itcj2.core.models.user import User
from itcj2.core.utils.email_tools import student_email
from itcj2.core.utils.msgraph_mail import acquire_token_silent, graph_send_mail

router = APIRouter(tags=["agendatec-admin-surveys"])
logger = logging.getLogger(__name__)

SurveyPerm = require_perms("agendatec", ["agendatec.surveys.api.send"])

_SURVEY_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;font-family:Arial,Helvetica,sans-serif;background-color:#f4f4f5;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"
         style="background-color:#f4f4f5;padding:40px 20px;">
    <tr>
      <td align="center">
        <table role="presentation" width="600" cellspacing="0" cellpadding="0" border="0"
               style="background-color:#ffffff;border-radius:8px;border:1px solid #e5e7eb;">
          <tr>
            <td align="center" style="background-color:#1e3a5f;padding:32px 40px;">
              <table role="presentation" cellspacing="0" cellpadding="0" border="0">
                <tr>
                  <td align="center">
                    <img src="https://img.icons8.com/emoji/48/graduation-cap-emoji.png"
                         alt="Graduación" width="48" height="48" style="display:block;">
                  </td>
                </tr>
                <tr>
                  <td align="center" style="padding-top:12px;">
                    <h1 style="margin:0;color:#ffffff;font-size:24px;font-weight:bold;font-family:Arial,Helvetica,sans-serif;">
                      AgendaTec
                    </h1>
                  </td>
                </tr>
                <tr>
                  <td align="center" style="padding-top:8px;">
                    <p style="margin:0;color:#93c5fd;font-size:14px;font-family:Arial,Helvetica,sans-serif;">
                      Instituto Tecnológico de Ciudad Juárez
                    </p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:40px;">
              <h2 style="margin:0 0 16px 0;color:#1f2937;font-size:22px;font-weight:bold;">¡Hola! 👋</h2>
              <p style="margin:0 0 16px 0;color:#4b5563;font-size:16px;line-height:24px;">
                Recientemente realizaste un trámite a través de <strong>AgendaTec</strong>.
                Tu opinión es muy importante para nosotros y nos ayuda a mejorar continuamente nuestros servicios.
              </p>
              <p style="margin:0 0 32px 0;color:#4b5563;font-size:16px;line-height:24px;">
                ¿Podrías tomarte <strong>menos de 1 minuto</strong> para responder una breve encuesta sobre tu experiencia?
              </p>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                <tr>
                  <td align="center" style="padding:8px 0 32px 0;">
                    <a href="{forms_url}" target="_blank"
                       style="display:inline-block;background-color:#2563eb;color:#ffffff;
                              text-decoration:none;padding:16px 40px;border-radius:8px;
                              font-size:16px;font-weight:bold;font-family:Arial,Helvetica,sans-serif;
                              border:2px solid #1d4ed8;">
                      📝 Responder Encuesta
                    </a>
                  </td>
                </tr>
              </table>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                <tr>
                  <td style="background-color:#eff6ff;border-left:4px solid #2563eb;padding:16px 20px;">
                    <p style="margin:0;color:#1e40af;font-size:14px;line-height:22px;">
                      <strong>💡 ¿Por qué es importante?</strong><br>
                      Tus comentarios nos permiten identificar áreas de mejora y brindarte un mejor servicio.
                    </p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="background-color:#f9fafb;padding:24px 40px;border-top:1px solid #e5e7eb;">
              <p style="margin:0 0 8px 0;color:#6b7280;font-size:13px;text-align:center;">
                ¡Gracias por tu tiempo y colaboración! 🙏
              </p>
              <p style="margin:0;color:#9ca3af;font-size:12px;text-align:center;">
                Este correo fue enviado automáticamente por AgendaTec.<br>
                Instituto Tecnológico de Ciudad Juárez © {year}
              </p>
            </td>
          </tr>
        </table>
        <table role="presentation" width="600" cellspacing="0" cellpadding="0" border="0">
          <tr>
            <td align="center" style="padding:24px 20px;">
              <p style="margin:0;color:#6b7280;font-size:12px;">
                ¿El botón no funciona? Copia y pega este enlace en tu navegador:
              </p>
              <p style="margin:8px 0 0 0;">
                <a href="{forms_url}" style="color:#2563eb;font-size:12px;word-break:break-all;">{forms_url}</a>
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


# ==================== POST /surveys/send ====================

@router.post("/surveys/send")
def send_surveys(
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    test: str = Query("0"),
    user: dict = SurveyPerm,
    db: DbSession = None,
):
    """Envía correos de encuesta a estudiantes atendidos."""
    token = acquire_token_silent("agendatec")
    if not token:
        raise HTTPException(
            status_code=401,
            detail={"error": "no_ms_session", "message": "Inicia sesión en la pestaña 'Conexión Outlook'."},
        )

    start, end = parse_range_from_params(from_, to)
    is_test = test in ("1", "true", "yes")

    if is_test:
        targets = ["l21111182@cdjuarez.tecnm.mx"]
    else:
        rows = (
            db.query(User)
            .join(Req, Req.student_id == User.id)
            .filter(
                Req.status.notin_(["PENDING", "CANCELED", "NO_SHOW"]),
                Req.updated_at >= start,
                Req.updated_at <= end,
            )
            .order_by(Req.updated_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        targets = [r for r in (student_email(e) for e in rows if e) if r]

    if not targets:
        return {"ok": True, "sent": 0, "detail": "Sin destinatarios"}

    forms_url = os.getenv("SURVEY_FORMS_URL", "https://forms.office.com/r/xxxxx")
    subject = "📋 Tu opinión nos importa | AgendaTec"
    html = _SURVEY_HTML_TEMPLATE.format(forms_url=forms_url, year=datetime.now().year)

    sent, errors = 0, []
    for addr in targets:
        r = graph_send_mail(token, subject, html, [addr])
        if r.status_code in (200, 202):
            sent += 1
        else:
            errors.append({"to": addr, "status": r.status_code, "body": r.text})

    return {"ok": True, "sent": sent, "errors": errors, "total_targets": len(targets)}
