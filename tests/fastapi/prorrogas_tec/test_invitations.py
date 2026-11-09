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
    assert not out["requiere_correo"] and "requiere_datos" not in out


def test_lookup_de_doctorado_sin_cuenta(db_session):
    out = inv.lookup(db_session, "D99200002")
    assert not out["existe"] and out["requiere_correo"] and "requiere_datos" not in out


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


def test_invitar_no_manda_correo_si_no_se_guardo(db_session, secretaria, make_user, enviar_correo, monkeypatch):
    make_user(control_number="99200016")

    def commit_que_falla():
        raise RuntimeError("commit falló")

    monkeypatch.setattr(db_session, "commit", commit_que_falla)
    with pytest.raises(RuntimeError):
        inv.invite(db_session, raw_control="99200016", email=None, actor_id=secretaria.id)
    assert enviar_correo.calls == []  # ninguna liga a una invitación que no existe


def test_reinvitar_revoca_la_invitacion_anterior(db_session, secretaria, make_user, enviar_correo):
    u = make_user(control_number="99200012")
    _, primero, _ = inv.invite(db_session, raw_control="99200012", email="mal@example.invalid", actor_id=secretaria.id)
    _, segundo, _ = inv.invite(db_session, raw_control="99200012", email="bien@example.invalid", actor_id=secretaria.id)
    with pytest.raises(ServiceError) as e:
        inv.consume_invitation(db_session, primero, user_id=u.id)
    assert e.value.code == "invitacion_expirada"
    assert inv.consume_invitation(db_session, segundo, user_id=u.id).via == "invitacion"
