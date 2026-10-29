from datetime import datetime, timedelta

import pytest

from itcj2.apps.prorrogas_tec.services import invitation_service as inv
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.core.services.authz_service import user_roles_in_app

T0 = datetime(2091, 2, 1, 9, 0)


def test_qr_valido_devuelve_quien_lo_emitio():
    out = inv.issue_qr(7, now=T0)
    assert out["path"].startswith("/prorrogas/unirse?t=") and inv.read_qr(out["token"], now=T0 + timedelta(minutes=4)) == 7


def test_qr_trae_los_segundos_que_le_quedan():  # el contador del navegador no depende de su reloj
    assert inv.issue_qr(7, now=T0)["ttl"] == 300


def test_qr_vencido_o_alterado():  # Review Focus 2
    token = inv.issue_qr(7, now=T0)["token"]
    with pytest.raises(ServiceError) as e:
        inv.read_qr(token, now=T0 + timedelta(minutes=6))
    assert e.value.code == "qr_expirado"
    with pytest.raises(ServiceError) as e:
        inv.read_qr(token[:-2] + "xx", now=T0)
    assert e.value.code == "qr_invalido"


def test_lookup_de_licenciatura_con_cuenta(db_session, make_user):
    make_user(control_number="99200001")
    out = inv.lookup(db_session, " 99200001 ")
    assert out["existe"] and out["correo_sugerido"] == "L99200001@cdjuarez.tecnm.mx"
    assert not out["requiere_datos"] and not out["requiere_correo"]


def test_lookup_de_doctorado_sin_cuenta(db_session):
    out = inv.lookup(db_session, "D99200002")
    assert not out["existe"] and out["requiere_datos"] and out["requiere_correo"]


def test_invitar_crea_cuenta_de_posgrado_sin_nip(db_session, secretaria, make_program, enviar_correo):
    prog = make_program("Doctorado de Prueba", "doctorado")
    invitacion, token, _ = inv.invite(db_session, raw_control="D99200003", email="persona@example.invalid",
                                   actor_id=secretaria.id, nombres="Ana", apellido_paterno="López", program_id=prog.id)
    assert invitacion.user_created and invitacion.user.password_hash is None
    assert enviar_correo.calls[0]["to"] == "persona@example.invalid" and enviar_correo.calls[0]["link"].endswith(token)


@pytest.mark.parametrize("kwargs, code", [
    ({"raw_control": "D99200004", "email": None}, "correo_requerido"),
    ({"raw_control": "D99200005", "email": "x@example.invalid"}, "datos_requeridos"),
    ({"raw_control": "123", "email": None}, "control_invalido"),
])
def test_invitaciones_invalidas(db_session, secretaria, enviar_correo, kwargs, code):
    with pytest.raises(ServiceError) as e:
        inv.invite(db_session, actor_id=secretaria.id, **kwargs)
    assert e.value.code == code


def test_consumir_une_da_el_rol_y_no_se_reusa(db_session, secretaria, make_user, enviar_correo):
    u = make_user(control_number="99200006")
    _, token, _ = inv.invite(db_session, raw_control="99200006", email=None, actor_id=secretaria.id)
    join = inv.consume_invitation(db_session, token, user_id=u.id)
    assert join.via == "invitacion" and "student" in user_roles_in_app(db_session, u.id, "prorrogas_tec")
    with pytest.raises(ServiceError) as e:
        inv.consume_invitation(db_session, token, user_id=u.id)
    assert e.value.code == "invitacion_usada"


def test_invitacion_abierta_por_otra_cuenta_no_se_consume(db_session, secretaria, make_user, enviar_correo):  # RF 5
    make_user(control_number="99200007")
    otro = make_user(control_number="99200008")
    invitacion, token, _ = inv.invite(db_session, raw_control="99200007", email=None, actor_id=secretaria.id)
    with pytest.raises(ServiceError) as e:
        inv.consume_invitation(db_session, token, user_id=otro.id)
    assert e.value.code == "invitacion_de_otra_cuenta" and invitacion.used_at is None


def test_nip_inicial(db_session, secretaria, make_program, enviar_correo):
    prog = make_program("Doctorado de Prueba", "doctorado")
    invitacion, token, _ = inv.invite(db_session, raw_control="D99200009", email="p@example.invalid",
                                   actor_id=secretaria.id, nombres="Luis", apellido_paterno="Paz", program_id=prog.id)
    with pytest.raises(ServiceError) as e:
        inv.set_initial_nip(db_session, token, "12a4", "12a4")
    assert e.value.code == "nip_invalido"
    with pytest.raises(ServiceError) as e:
        inv.set_initial_nip(db_session, token, "1234", "4321")
    assert e.value.code == "nip_no_coincide"
    inv.set_initial_nip(db_session, token, "1234", "1234")
    with pytest.raises(ServiceError) as e:
        inv.set_initial_nip(db_session, token, "9999", "9999")
    assert e.value.code == "cuenta_con_nip"


def test_invitacion_expirada_no_se_consume(db_session, secretaria, make_user, enviar_correo):
    u = make_user(control_number="99200011")
    inv_, token, _ = inv.invite(db_session, raw_control="99200011", email=None, actor_id=secretaria.id, now=T0)
    with pytest.raises(ServiceError) as e:
        inv.consume_invitation(db_session, token, user_id=u.id, now=T0 + timedelta(hours=49))
    assert e.value.code == "invitacion_expirada" and inv_.used_at is None


def test_api_qr_solo_para_la_secretaria(client_as, secretaria, estudiante):
    assert client_as(estudiante).post("/api/prorrogas/v2/invitaciones/qr").status_code == 403
    r = client_as(secretaria).post("/api/prorrogas/v2/invitaciones/qr")
    assert r.status_code == 200 and r.json()["path"].startswith("/prorrogas/unirse?t=")


def test_api_invitar_y_resumen_del_dia(client_as, secretaria, make_user, enviar_correo):
    make_user(control_number="99200010")
    c = client_as(secretaria)
    r = c.post("/api/prorrogas/v2/invitaciones", json={"control_number": "99200010"})
    assert r.status_code == 201 and r.json()["correo"] == "L99200010@cdjuarez.tecnm.mx" and r.json()["enviado"] is True
    assert c.get("/api/prorrogas/v2/invitaciones/hoy").json()["invitaciones_hoy"] >= 1


def test_api_invitar_sin_buzon_avisa_que_no_salio(client_as, secretaria, make_user, monkeypatch):
    from itcj2.apps.prorrogas_tec.services import notify
    monkeypatch.setattr(notify, "send_email", lambda **kw: False)
    make_user(control_number="99200013")
    r = client_as(secretaria).post("/api/prorrogas/v2/invitaciones", json={"control_number": "99200013"})
    assert r.status_code == 201 and r.json()["enviado"] is False


def test_se_unieron_hoy_cuenta_personas_no_filas(db_session, make_user):
    from itcj2.apps.prorrogas_tec.models.invitation import ProrrogaJoin
    from itcj2.core.utils.timezone import db_now
    antes = inv.today_summary(db_session)["se_unieron_hoy"]
    u = make_user(control_number="99200014")
    db_session.add_all([ProrrogaJoin(user_id=u.id, via="qr", joined_at=db_now()) for _ in range(2)])
    db_session.flush()
    assert inv.today_summary(db_session)["se_unieron_hoy"] == antes + 1


def test_qr_no_sirve_como_cookie_de_sesion_ni_al_reves():
    import jwt
    from itcj2.config import get_settings
    from itcj2.middleware import _decode_jwt

    assert _decode_jwt(inv.issue_qr(1)["token"]) is None
    sesion = jwt.encode({"sub": "1", "p": inv.QR_PURPOSE, "by": 1, "exp": int((T0 + timedelta(minutes=5)).timestamp())},
                        get_settings().SECRET_KEY, algorithm="HS256")
    with pytest.raises(ServiceError) as e:
        inv.read_qr(sesion, now=T0)
    assert e.value.code == "qr_invalido"


def test_reinvitar_revoca_la_invitacion_anterior(db_session, secretaria, make_program, enviar_correo):
    # La cuenta la creó la primera invitación; la segunda (correo corregido) aún deja crear el NIP.
    prog = make_program("Doctorado de Prueba", "doctorado")
    previa, primero, _ = inv.invite(db_session, raw_control="D99200012", email="mal@example.invalid",
                                 actor_id=secretaria.id, nombres="Ana", apellido_paterno="Paz", program_id=prog.id)
    u = previa.user
    otra, segundo, _ = inv.invite(db_session, raw_control="D99200012", email="bien@example.invalid", actor_id=secretaria.id)
    assert previa.user_created and not otra.user_created
    with pytest.raises(ServiceError) as e:
        inv.consume_invitation(db_session, primero, user_id=u.id)
    assert e.value.code == "invitacion_expirada"
    with pytest.raises(ServiceError) as e:
        inv.set_initial_nip(db_session, primero, "1234", "1234")
    assert e.value.code == "invitacion_expirada"
    inv.set_initial_nip(db_session, segundo, "1234", "1234")
    assert inv.consume_invitation(db_session, segundo, user_id=u.id).via == "invitacion"


def test_cuenta_existente_sin_nip_no_crea_nip_con_invitacion(db_session, secretaria, make_user, enviar_correo):
    # Spec 8.2: "Crea tu NIP" es solo para cuentas que nacieron de una invitación manual.
    u = make_user(control_number="99200015")
    _, token, _ = inv.invite(db_session, raw_control="99200015", email=None, actor_id=secretaria.id)
    assert not inv.can_set_initial_nip(db_session, u)
    with pytest.raises(ServiceError) as e:
        inv.set_initial_nip(db_session, token, "1234", "1234")
    assert e.value.code == "cuenta_sin_invitacion_de_alta" and e.value.status == 403
    db_session.refresh(u)
    assert u.password_hash is None


def test_invitar_no_manda_correo_si_no_se_guardo(db_session, secretaria, make_user, enviar_correo, monkeypatch):
    make_user(control_number="99200016")

    def commit_que_falla():
        raise RuntimeError("commit falló")

    monkeypatch.setattr(db_session, "commit", commit_que_falla)
    with pytest.raises(RuntimeError):
        inv.invite(db_session, raw_control="99200016", email=None, actor_id=secretaria.id)
    assert enviar_correo.calls == []  # ninguna liga a una invitación que no existe
