from datetime import timedelta

from itcj2.apps.prorrogas_tec.models.invitation import ProrrogaJoin
from itcj2.apps.prorrogas_tec.services import invitation_service as inv
from itcj2.core.utils.timezone import db_now


def test_sin_sesion_va_al_login_con_next(client):
    r = client.get("/prorrogas/unirse?t=abc", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/itcj/login?next=%2Fprorrogas%2Funirse%3Ft%3Dabc"
    assert r.headers["referrer-policy"] == "no-referrer"


def test_qr_valido_une_y_lleva_a_la_solicitud(client_as, secretaria, make_user, db_session):
    u = make_user(control_number="99300001")
    token = inv.issue_qr(secretaria.id)["token"]
    r = client_as(u).get(f"/prorrogas/unirse?t={token}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/prorrogas/estudiante/solicitud"
    assert db_session.query(ProrrogaJoin).filter_by(user_id=u.id, via="qr").count() == 1


def test_qr_vencido_muestra_mensaje_y_no_une(client_as, secretaria, make_user, db_session):  # Review Focus 2
    u = make_user(control_number="99300002")
    token = inv.issue_qr(secretaria.id, now=db_now() - timedelta(minutes=10))["token"]
    r = client_as(u).get(f"/prorrogas/unirse?t={token}", follow_redirects=False)
    assert r.status_code == 410 and "Pide un código nuevo" in r.text
    assert r.headers["referrer-policy"] == "no-referrer"
    assert db_session.query(ProrrogaJoin).filter_by(user_id=u.id).count() == 0


def test_invitacion_de_cuenta_nueva_pide_crear_nip_y_luego_login(client, secretaria, make_program, enviar_correo, db_session):
    prog = make_program("Doctorado de Prueba", "doctorado")
    invitacion, token = inv.invite(db_session, raw_control="D99300003", email="n@example.invalid",
                                   actor_id=secretaria.id, nombres="Eva", apellido_paterno="Ruiz", program_id=prog.id)
    url = f"/prorrogas/unirse/invitacion/{token}"
    r = client.get(url)
    assert "Crea tu NIP" in r.text and r.headers["referrer-policy"] == "no-referrer"
    assert "D99300003" not in r.text
    r = client.post(url, data={"nip": "4321", "nip2": "4321"}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("/itcj/login?next=")
    db_session.refresh(invitacion.user)
    assert invitacion.user.password_hash


def test_nip_distinto_vuelve_a_mostrar_el_formulario(client, secretaria, make_program, enviar_correo, db_session):
    prog = make_program("Doctorado de Prueba", "doctorado")
    _, token = inv.invite(db_session, raw_control="D99300006", email="m@example.invalid",
                          actor_id=secretaria.id, nombres="Eva", apellido_paterno="Ruiz", program_id=prog.id)
    r = client.post(f"/prorrogas/unirse/invitacion/{token}", data={"nip": "4321", "nip2": "1234"})
    assert r.status_code == 400 and "Crea tu NIP" in r.text and "no coinciden" in r.text


def test_invitacion_abierta_con_otra_cuenta(client_as, secretaria, make_user, enviar_correo, db_session):  # RF 5
    make_user(control_number="99300004")
    otro = make_user(control_number="99300005")
    invitacion, token = inv.invite(db_session, raw_control="99300004", email=None, actor_id=secretaria.id)
    r = client_as(otro).get(f"/prorrogas/unirse/invitacion/{token}", follow_redirects=False)
    assert r.status_code == 403 and invitacion.used_at is None
