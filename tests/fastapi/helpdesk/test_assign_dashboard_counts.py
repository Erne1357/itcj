"""Tarjetas de la pestaña de asignación: cuentan con `total` del servidor.

`loadDashboardStats` pedía `getTickets({})` (primera página, 20 tickets) y contaba
sobre eso: «En Progreso» marcaba 3 con 22 en proceso. Ahora pide totales filtrados;
«Hoy» necesita que el API acepte `created_from`. Prefijo `aa9_`.
"""
import re
import time
from datetime import datetime
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient

import itcj2.models  # noqa: F401
from itcj2.apps.helpdesk.models.ticket import Ticket
from itcj2.config import get_settings
from itcj2.core.models.user import User
from itcj2.database import get_db
from itcj2.main import create_app

from ._catalog import ensure_helpdesk_category

JS = Path(__file__).resolve().parents[3] / "itcj2/apps/helpdesk/static/js/admin/assign_tickets.js"


@pytest.fixture()
def client(db_session):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _headers(user_id):
    now = int(time.time())
    token = jwt.encode({"sub": str(user_id), "role": "admin", "cn": None, "name": "T",
                        "iat": now, "exp": now + 3600},
                       get_settings().SECRET_KEY, algorithm="HS256")
    return {"Cookie": f"itcj_token={token}"}


def _ticket(db, user, number, created_at):
    cat = ensure_helpdesk_category(db, "aa9_cat", "DESARROLLO")
    t = Ticket(ticket_number=number, requester_id=user.id, area="DESARROLLO",
               category_id=cat.id, priority="MEDIA", title="aa9", status="PENDING",
               description="aa9 descripcion de prueba suficientemente larga.",
               created_by_id=user.id, updated_by_id=user.id, created_at=created_at)
    db.add(t)
    db.commit()
    return t


def test_created_from_filtra_y_da_total(client, db_session):
    u = User(first_name="aa9", last_name="aa9_req", is_active=True)
    db_session.add(u)
    db_session.commit()
    # Fechas en el futuro: ningún ticket real de la base de dev cae ahí.
    _ticket(db_session, u, "AA9-0001", datetime(2099, 1, 1, 23, 59))
    _ticket(db_session, u, "AA9-0002", datetime(2099, 1, 2, 0, 0))
    _ticket(db_session, u, "AA9-0003", datetime(2099, 1, 3, 9, 30))

    r = client.get("/api/help-desk/v2/tickets?created_from=2099-01-02&per_page=1",
                   headers=_headers(u.id))
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 2
    assert len(r.json()["tickets"]) == 1


def test_created_from_invalido_es_400(client, db_session):
    u = User(first_name="aa9", last_name="aa9_bad", is_active=True)
    db_session.add(u)
    db_session.commit()
    r = client.get("/api/help-desk/v2/tickets?created_from=ayer", headers=_headers(u.id))
    assert r.status_code == 400


def test_tarjetas_no_cuentan_sobre_una_pagina():
    body = re.search(r"async function loadDashboardStats\(\)(.*?)\n    }\n",
                     JS.read_text(encoding="utf-8"), re.S).group(1)
    assert "getTickets({})" not in body
    for filtro in ("status: 'PENDING', per_page: 1", "status: 'IN_PROGRESS', per_page: 1",
                   "created_from: today, per_page: 1"):
        assert filtro in body, filtro
    assert ".total" in body
