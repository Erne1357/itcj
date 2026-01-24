# routes/api/admin/helpers.py
"""
Funciones helper compartidas para endpoints de administración.

Este módulo contiene funciones de utilidad que son usadas por
múltiples endpoints del módulo admin.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from flask import request

from itcj.apps.agendatec.config import (
    REQUEST_ATTENDED_STATES,
    REQUEST_EXCLUDE_STATES,
)
from itcj.apps.agendatec.models import db
from itcj.apps.agendatec.models.request import Request as Req
from itcj.apps.agendatec.models.survey_dispatches import SurveyDispatch
from itcj.core.models.user import User
from itcj.core.utils.email_tools import student_email
from sqlalchemy import and_

# Alias de constantes para compatibilidad
ATTENDED_STATES = REQUEST_ATTENDED_STATES
EXCLUDE_STATES = REQUEST_EXCLUDE_STATES


def parse_dt(s: Optional[str], default: Optional[datetime] = None) -> datetime:
    """
    Parsea una cadena de fecha/hora en formato ISO.

    Args:
        s: Cadena en formato 'YYYY-MM-DD' o ISO completo
        default: Valor por defecto si s es None o inválido

    Returns:
        datetime parseado o el valor default
    """
    if s:
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            pass
    return default or datetime.now()


def range_from_query() -> tuple[datetime, datetime]:
    """
    Extrae rango de fechas desde query params 'from' y 'to'.

    Returns:
        Tupla (start, end) con datetimes. Si no se especifica,
        usa los últimos 7 días como default.
    """
    qf = request.args.get("from")
    qt = request.args.get("to")
    end = parse_dt(qt, datetime.now())
    start = parse_dt(qf, end - timedelta(days=7))
    # Normaliza para incluir el día completo si vino solo fecha
    if qf and len(qf) == 10:
        start = datetime.combine(start.date(), datetime.min.time())
    if qt and len(qt) == 10:
        end = datetime.combine(end.date(), datetime.max.time())
    return start, end


def paginate(query, default_limit: int = 20, max_limit: int = 100) -> tuple:
    """
    Aplica paginación a una query SQLAlchemy.

    Args:
        query: Query SQLAlchemy a paginar
        default_limit: Límite por defecto de resultados
        max_limit: Límite máximo permitido

    Returns:
        Tupla (items, total) con los elementos paginados y el total.
    """
    try:
        limit = min(int(request.args.get("limit", default_limit)), max_limit)
    except ValueError:
        limit = default_limit
    try:
        offset = int(request.args.get("offset", 0))
    except ValueError:
        offset = 0
    total = query.order_by(None).count()
    items = query.limit(limit).offset(offset).all()
    return items, total


def add_query_params(url: str, **params) -> str:
    """
    Agrega o mezcla query params a una URL.

    Args:
        url: URL base
        **params: Parámetros a agregar

    Returns:
        URL con los parámetros agregados
    """
    pr = urlparse(url)
    q = dict(parse_qsl(pr.query))
    q.update({k: v for k, v in params.items() if v is not None})
    new_q = urlencode(q)
    return urlunparse((pr.scheme, pr.netloc, pr.path, pr.params, new_q, pr.fragment))


def student_email_from_user(u: User) -> Optional[str]:
    """
    Genera el correo electrónico de un estudiante basado en sus datos.

    Reglas:
    - Si username contiene @ -> usar directamente
    - Si username existe (sin @) -> username@EMAIL_DOMAIN
    - Si hay control_number -> L{control_number}@EMAIL_DOMAIN

    Args:
        u: Objeto User

    Returns:
        Email del estudiante o None si no se puede generar
    """
    domain = os.getenv("EMAIL_DOMAIN", "").strip()
    # Si no hay dominio y SENDER_UPN existe, usar el dominio del remitente
    if not domain:
        sender = os.getenv("MAIL_SENDER_UPN", "")
        if "@" in sender:
            domain = sender.split("@", 1)[1].strip().lower()

    if u.username:
        un = u.username.strip()
        if "@" in un:
            return un.lower()
        if domain:
            return f"{un.lower()}@{domain}"
    if u.control_number and domain:
        cn = u.control_number.strip().upper()
        if not cn.startswith("L"):
            cn = "L" + cn
        return f"{cn.lower()}@{domain}"
    return None


def student_identifier(u: User) -> str:
    """
    Identificador para pasar al Forms (param 'cn'): usa control_number si existe;
    si no, usa username.
    """
    return (getattr(u, "control_number", None) or getattr(u, "username", "") or "").strip()


def find_recipients(
    start: datetime,
    end: datetime,
    campaign_code: str,
    skip_already_sent: bool = True,
    limit: int = 500,
    offset: int = 0
) -> list[tuple[User, Req, str]]:
    """
    Busca destinatarios para envío de encuestas.

    Retorna [(user, request, email)] para enviar encuesta.
    Regla: cualquier Req cuyo estado NO esté en CANCELED/NO_SHOW y que
    pertenezca a un coordinador (ligado a programa).

    Args:
        start: Fecha de inicio del rango
        end: Fecha de fin del rango
        campaign_code: Código de la campaña de encuesta
        skip_already_sent: Si True, excluye usuarios que ya recibieron esta campaña
        limit: Máximo de resultados
        offset: Desplazamiento para paginación

    Returns:
        Lista de tuplas (User, Request, email)
    """
    q = (
        db.session.query(User, Req)
        .join(User, User.id == Req.user_id)
        .filter(Req.status.notin_(EXCLUDE_STATES))
        .filter(and_(Req.updated_at >= start, Req.updated_at <= end))
    )

    if skip_already_sent:
        q = q.outerjoin(
            SurveyDispatch,
            and_(
                SurveyDispatch.campaign_code == campaign_code,
                SurveyDispatch.user_id == User.id,
            ),
        ).filter(SurveyDispatch.id.is_(None))

    q = q.order_by(User.full_name.asc()).limit(limit).offset(offset)

    rows = q.all()
    out = []
    for u, r in rows:
        em = student_email(u)
        if not em:
            continue
        out.append((u, r, em))
    return out


def get_dialect_name() -> str:
    """
    Obtiene el nombre del dialecto de base de datos actual.

    Returns:
        Nombre del dialecto (ej: 'postgresql', 'sqlite')
    """
    try:
        bind = db.session.get_bind()
    except Exception:
        bind = None
    try:
        eng = bind or db.engine
    except Exception:
        eng = None
    return (eng and eng.dialect and eng.dialect.name) or ""
