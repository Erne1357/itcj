from datetime import timedelta

from itcj2.apps.prorrogas_tec.models.invitation import ProrrogaJoin
from itcj2.apps.prorrogas_tec.services import invitation_service as inv
from itcj2.core.utils.timezone import db_now


LOGIN_ABC = "/itcj/login?next=%2Fprorrogas%2Funirse%3Ft%3Dabc"


def test_sin_sesion_va_directo_al_login_con_next(client):
    for r in (client.get("/prorrogas/unirse?t=abc", follow_redirects=False),
              client.post("/prorrogas/unirse", data={"t": "abc"}, follow_redirects=False)):
        assert r.status_code == 302 and r.headers["location"] == LOGIN_ABC
        assert r.headers["referrer-policy"] == "no-referrer"


def test_qr_valido_pregunta_y_al_aceptar_une(client_as, secretaria, make_user, db_session):
    u = make_user(control_number="99300001")
    token = inv.issue_qr(secretaria.id)["token"]
    c = client_as(u)
    r = c.get(f"/prorrogas/unirse?t={token}", follow_redirects=False)
    assert r.status_code == 200 and "Aceptar y continuar" in r.text and "99300001" in r.text
    assert r.headers["referrer-policy"] == "no-referrer"
    assert db_session.query(ProrrogaJoin).filter_by(user_id=u.id).count() == 0  # ver la pregunta no une
    r = c.post("/prorrogas/unirse", data={"t": token}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/prorrogas/estudiante/solicitud"
    assert db_session.query(ProrrogaJoin).filter_by(user_id=u.id, via="qr").count() == 1


def test_qr_vencido_muestra_mensaje_y_no_une(client_as, secretaria, make_user, db_session):  # Review Focus 2
    u = make_user(control_number="99300002")
    token = inv.issue_qr(secretaria.id, now=db_now() - timedelta(minutes=10))["token"]
    c = client_as(u)
    for r in (c.get(f"/prorrogas/unirse?t={token}", follow_redirects=False),
              c.post("/prorrogas/unirse", data={"t": token}, follow_redirects=False)):
        assert r.status_code == 410 and "Pide un código QR nuevo" in r.text
        assert r.headers["referrer-policy"] == "no-referrer"
    assert db_session.query(ProrrogaJoin).filter_by(user_id=u.id).count() == 0


def test_invitacion_abierta_con_otra_cuenta(client_as, secretaria, make_user, enviar_correo, db_session):  # RF 5
    make_user(control_number="99300004")
    otro = make_user(control_number="99300005")
    invitacion, token, _ = inv.invite(db_session, raw_control="99300004", email=None, actor_id=secretaria.id)
    r = client_as(otro).get(f"/prorrogas/unirse/invitacion/{token}", follow_redirects=False)
    assert r.status_code == 403 and invitacion.used_at is None


def test_invitacion_vencida_con_nip_muestra_410_sin_sesion(client, secretaria, make_user, enviar_correo, db_session):
    from itcj2.core.utils.security import hash_nip
    u = make_user(control_number="99300007")
    u.password_hash = hash_nip("1234")
    _, token, _ = inv.invite(db_session, raw_control="99300007", email=None, actor_id=secretaria.id,
                          now=db_now() - timedelta(hours=49))
    r = client.get(f"/prorrogas/unirse/invitacion/{token}", follow_redirects=False)
    assert r.status_code == 410


def test_invitacion_usada_da_409(client, client_as, secretaria, make_user, enviar_correo, db_session):
    u = make_user(control_number="99300008")
    _, token, _ = inv.invite(db_session, raw_control="99300008", email=None, actor_id=secretaria.id)
    inv.consume_invitation(db_session, token, user_id=u.id)
    assert client.get(f"/prorrogas/unirse/invitacion/{token}", follow_redirects=False).status_code == 409


def test_invitacion_desconocida_da_404(client):
    assert client.get("/prorrogas/unirse/invitacion/nope", follow_redirects=False).status_code == 404


def test_cuenta_sin_numero_de_control_no_se_une_por_qr(client_as, secretaria, make_user, db_session):
    u = make_user()  # cuenta de personal: sin número de control
    token = inv.issue_qr(secretaria.id)["token"]
    c = client_as(u)
    for r in (c.get(f"/prorrogas/unirse?t={token}", follow_redirects=False),
              c.post("/prorrogas/unirse", data={"t": token}, follow_redirects=False)):
        assert r.status_code == 403 and "Esta cuenta no es de estudiante." in r.text
    assert db_session.query(ProrrogaJoin).filter_by(user_id=u.id).count() == 0


def test_invitacion_con_sesion_pregunta_y_al_aceptar_une(client_as, secretaria, make_user, enviar_correo, db_session):
    u = make_user(control_number="99300011")
    _, token, _ = inv.invite(db_session, raw_control="99300011", email=None, actor_id=secretaria.id)
    c, url = client_as(u), f"/prorrogas/unirse/invitacion/{token}"
    r = c.get(url, follow_redirects=False)
    assert r.status_code == 200 and "Aceptar y continuar" in r.text and "99300011" in r.text
    assert db_session.query(ProrrogaJoin).filter_by(user_id=u.id).count() == 0  # ver la pregunta no une
    r = c.post(url, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/prorrogas/estudiante/solicitud"
    assert db_session.query(ProrrogaJoin).filter_by(user_id=u.id, via="invitacion").count() == 1


def test_cuenta_sin_nip_va_a_centro_de_computo(client, secretaria, make_user, enviar_correo, db_session):
    make_user(control_number="99300009")
    _, token, _ = inv.invite(db_session, raw_control="99300009", email=None, actor_id=secretaria.id)
    r = client.get(f"/prorrogas/unirse/invitacion/{token}", follow_redirects=False)
    assert r.status_code == 403 and "Centro de Cómputo" in r.text


def test_post_de_invitacion_sin_sesion_va_al_login_y_no_une(client, secretaria, make_user, enviar_correo, db_session):
    u = make_user(control_number="99300012")
    invitacion, token, _ = inv.invite(db_session, raw_control="99300012", email=None, actor_id=secretaria.id)
    r = client.post(f"/prorrogas/unirse/invitacion/{token}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("/itcj/login?next=")
    assert invitacion.used_at is None and db_session.query(ProrrogaJoin).filter_by(user_id=u.id).count() == 0


def test_post_de_invitacion_con_otra_cuenta_da_403_y_no_une(client_as, secretaria, make_user, enviar_correo, db_session):
    u = make_user(control_number="99300013")
    otro = make_user(control_number="99300014")
    invitacion, token, _ = inv.invite(db_session, raw_control="99300013", email=None, actor_id=secretaria.id)
    r = client_as(otro).post(f"/prorrogas/unirse/invitacion/{token}", follow_redirects=False)
    assert r.status_code == 403 and invitacion.used_at is None
    assert db_session.query(ProrrogaJoin).filter(ProrrogaJoin.user_id.in_([u.id, otro.id])).count() == 0
