"""Notificaciones de agendatec: que se creen, que lleven URL, que no se dupliquen.

Contexto del bug original: `create_notification()` (itcj2/core/utils/notify.py)
declara `db=None` como último kwarg y tres call sites lo omitían. Eso hacía que
`NotificationService.create` ejecutara `db.add(...)` sobre `None`, el
`AttributeError` quedaba tragado por el `try/except` circundante, y el endpoint
devolvía 200 sin haber creado nada. El alumno nunca se enteraba de que su
solicitud fue resuelta, cancelada o marcada no-asistió.
"""
from datetime import time

import pytest

from itcj2.core.models.notification import Notification


@pytest.fixture()
def scenario(coord_setup, make_grid, make_user, make_booking):
    """Coordinador con una cita reservada por un alumno."""
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, ctx["program_ids"])
    student = make_user(first_name="ALUM", last_name="NOTIF", control_number="20990100")
    req, ap = make_booking(slots[0], student, ctx["program_ids"][0], ctx["period"].id)
    ctx.update(student=student, request=req, appointment=ap, slots=slots)
    return ctx


def _notifs(db, student_id, type_=None):
    q = db.query(Notification).filter_by(user_id=student_id)
    if type_:
        q = q.filter_by(type=type_)
    return q.all()


# ---------------------------------------------------------------------------
# El bug principal: la notificación no se creaba
# ---------------------------------------------------------------------------
def test_coord_status_change_creates_exactly_one_notification(client, db_session, scenario):
    """PATCH /coord/requests/{id}/status debe dejar UNA fila en core_notifications.

    Antes dejaba cero: create_notification() se llamaba sin db=.
    Y al arreglarlo hay que cuidar no dejar dos: el endpoint es `async def`, así
    que NotificationService.broadcast_websocket SÍ encuentra event loop y ya
    agenda el push; un `await push_notification()` extra lo duplicaría.
    """
    resp = client.patch(
        f"/api/agendatec/v2/coord/requests/{scenario['request'].id}/status",
        json={"status": "RESOLVED_SUCCESS", "coordinator_comment": "atendido"},
        headers=scenario["headers"],
    )
    assert resp.status_code == 200, resp.text

    notifs = _notifs(db_session, scenario["student"].id, "REQUEST_STATUS_CHANGED")
    assert len(notifs) == 1, f"se esperaba exactamente 1 notificación, hay {len(notifs)}"
    assert notifs[0].app_name == "agendatec"


def test_coord_status_change_notification_carries_url(client, db_session, scenario):
    """Sin data['url'], action_url es null y el click no navega a ningún lado."""
    client.patch(
        f"/api/agendatec/v2/coord/requests/{scenario['request'].id}/status",
        json={"status": "RESOLVED_SUCCESS"},
        headers=scenario["headers"],
    )
    n = _notifs(db_session, scenario["student"].id, "REQUEST_STATUS_CHANGED")[0]
    assert n.data.get("url") == "/agendatec/student/requests"
    assert n.to_dict()["action_url"] == "/agendatec/student/requests"


def test_notification_links_back_to_the_request(client, db_session, scenario):
    client.patch(
        f"/api/agendatec/v2/coord/requests/{scenario['request'].id}/status",
        json={"status": "NO_SHOW"},
        headers=scenario["headers"],
    )
    n = _notifs(db_session, scenario["student"].id, "REQUEST_STATUS_CHANGED")[0]
    assert n.source_request_id == scenario["request"].id
    assert n.data.get("request_id") == scenario["request"].id
    assert n.data.get("status") == "NO_SHOW"


# ---------------------------------------------------------------------------
# El wrapper deprecado no debe volver a fallar en silencio
# ---------------------------------------------------------------------------
def test_create_notification_without_db_fails_loudly():
    """Olvidar db= debe reventar en la cara, no perderse en un except.

    Es la regresión que permitió que el bug viviera tanto tiempo.
    """
    from itcj2.core.utils.notify import create_notification

    with pytest.raises(ValueError, match="db"):
        create_notification(
            user_id=1, type="SYSTEM", title="x", body=None, data={},
        )


# ---------------------------------------------------------------------------
# La ruta admin tenía los mismos bugs, más imports a un paquete inexistente
# ---------------------------------------------------------------------------
def test_admin_create_drop_notifies_the_student(client, db_session, coord_setup,
                                                make_user, auth_headers):
    """POST /admin/requests/create (DROP) debe notificar al alumno.

    Tenía tres defectos a la vez: faltaba db=, el import apuntaba a
    itcj2.core.sockets (paquete inexistente) y broadcast_drop_created se
    llamaba con la firma legacy de 3 argumentos. Los tres quedaban tragados
    por el try/except.
    """
    ctx = coord_setup(n_programs=1)
    student = make_user(first_name="ALTA", last_name="ADMIN", control_number="20990200")

    resp = client.post("/api/agendatec/v2/admin/requests/create", headers=auth_headers, json={
        "type": "DROP",
        "student_id": student.id,
        "program_id": ctx["program_ids"][0],
        "description": "baja por admin",
    })
    assert resp.status_code == 200, resp.text

    notifs = _notifs(db_session, student.id, "DROP_CREATED")
    assert len(notifs) == 1
    assert notifs[0].data.get("url") == "/agendatec/student/requests"


def test_admin_create_appointment_notifies_the_student(client, db_session, coord_setup,
                                                       make_grid, make_user, auth_headers):
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(11, 0), time(12, 0), 10, ctx["program_ids"])
    student = make_user(first_name="CITA", last_name="ADMIN", control_number="20990201")

    resp = client.post("/api/agendatec/v2/admin/requests/create", headers=auth_headers, json={
        "type": "APPOINTMENT",
        "student_id": student.id,
        "program_id": ctx["program_ids"][0],
        "slot_id": slots[0].id,
        "description": "cita por admin",
    })
    assert resp.status_code == 200, resp.text

    notifs = _notifs(db_session, student.id, "APPOINTMENT_CREATED")
    assert len(notifs) == 1
    assert notifs[0].data.get("url") == "/agendatec/student/requests"
    assert notifs[0].source_appointment_id is not None


# ---------------------------------------------------------------------------
# Filtro por app
# ---------------------------------------------------------------------------
def test_mark_all_read_only_affects_agendatec(client, db_session, scenario):
    """Abrir agendatec no debe borrar los badges de helpdesk ni vistetec."""
    from itcj2.core.services.notification_service import NotificationService

    student = scenario["student"]
    NotificationService.create(db=db_session, user_id=student.id, app_name="agendatec",
                               type="SYSTEM", title="de agendatec", body=None, data={})
    NotificationService.create(db=db_session, user_id=student.id, app_name="helpdesk",
                               type="SYSTEM", title="de helpdesk", body=None, data={})
    db_session.flush()

    from tests.conftest import make_jwt
    student_headers = {"Cookie": f"itcj_token={make_jwt(user_id=student.id, role='student')}"}

    resp = client.patch("/api/agendatec/v2/notifications/read-all", headers=student_headers)
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    helpdesk = (db_session.query(Notification)
                .filter_by(user_id=student.id, app_name="helpdesk").one())
    assert helpdesk.is_read is False, "la notificación de helpdesk no debía marcarse"

    agendatec = (db_session.query(Notification)
                 .filter_by(user_id=student.id, app_name="agendatec", type="SYSTEM").one())
    assert agendatec.is_read is True


def test_list_only_returns_agendatec_notifications(client, db_session, scenario):
    from itcj2.core.services.notification_service import NotificationService

    student = scenario["student"]
    NotificationService.create(db=db_session, user_id=student.id, app_name="agendatec",
                               type="SYSTEM", title="de agendatec", body=None, data={})
    NotificationService.create(db=db_session, user_id=student.id, app_name="helpdesk",
                               type="SYSTEM", title="de helpdesk", body=None, data={})
    db_session.flush()

    from tests.conftest import make_jwt
    student_headers = {"Cookie": f"itcj_token={make_jwt(user_id=student.id, role='student')}"}

    resp = client.get("/api/agendatec/v2/notifications", headers=student_headers)
    assert resp.status_code == 200, resp.text
    titles = [i["title"] for i in resp.json()["items"]]
    assert "de agendatec" in titles
    assert "de helpdesk" not in titles


# ---------------------------------------------------------------------------
# TODAS las notificaciones deben llevar URL
# ---------------------------------------------------------------------------
def test_every_notification_call_site_passes_the_url():
    """Ningún sitio que cree notificaciones puede olvidar data["url"].

    Es un test ESTRUCTURAL a propósito: cubrir cada flujo con un test de
    integración deja huecos silenciosos — así se coló "Cita agendada" sin URL.
    Sin url, action_url es null y el click solo marca como leída sin navegar.
    """
    import ast
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[3] / "itcj2" / "apps" / "agendatec"
    fallas = []

    for archivo in raiz.rglob("*.py"):
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.Call):
                continue
            fn = nodo.func
            nombre = getattr(fn, "attr", None) or getattr(fn, "id", None)
            if nombre not in ("create", "create_notification"):
                continue
            # NotificationService.create / create_notification
            if nombre == "create":
                duenio = getattr(fn, "value", None)
                if getattr(duenio, "id", None) != "NotificationService":
                    continue

            kwargs = {k.arg: k.value for k in nodo.keywords}
            data = kwargs.get("data")
            ubic = f"{archivo.relative_to(raiz.parent.parent.parent)}:{nodo.lineno}"

            if data is None:
                fallas.append(f"{ubic} — sin argumento data=")
                continue
            if not isinstance(data, ast.Dict):
                continue   # se arma en una variable: no se puede verificar aquí
            claves = [k.value for k in data.keys if isinstance(k, ast.Constant)]
            if "url" not in claves:
                fallas.append(f"{ubic} — data sin clave 'url'")

    assert not fallas, "Notificaciones sin URL de destino:\n  " + "\n  ".join(fallas)
