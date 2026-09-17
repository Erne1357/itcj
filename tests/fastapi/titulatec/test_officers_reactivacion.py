"""Encargados: nombrar a una cuenta INACTIVA la reactiva (2026-09-17).

EL BLOQUEADOR, reproducido en la BD de dev antes de escribir esto. En Servicios
Escolares hay 11 usuarios y **9 tienen `core_users.is_active = false`**: son los
`aux_school_services`, dados de alta en una campana de inventario de helpdesk y
desactivados desde entonces. La pestana los listaba junto a los activos, sin
ninguna marca.

`auth_service.py:45` filtra `is_active=True` al iniciar sesion, asi que nombrar
encargado a uno de ellos producia un **encargado muerto**: salia en la lista,
tenia el rol `titulatec_school_services` y su alcance por carrera, y no podia
entrar. Nada en la pantalla lo delataba.

Ahora `OfficerService.activate_users` reactiva esas cuentas y les restablece la
contrasena a `DEFAULT_PASSWORD`, y la UI lo dice antes (aviso en el formulario)
y despues (tarjeta con los nombres). Que el reseteo no deje una credencial
conocida lo garantiza `core/api/users.py::password_state`, que compara el hash
contra `DEFAULT_PASSWORD` y fuerza el cambio al entrar.

LO QUE ESTOS TESTS PROTEGEN, en orden de gravedad:

  1. Que se active SOLO a quien esta en el departamento del jefe. Esta es la
     frontera que impide que un permiso de titulatec toque identidad del core a
     lo ancho del instituto.
  2. Que una cuenta YA activa no se toque. Sin esto, editar un encargado para
     agregarle una carrera le habria reseteado la contrasena a todos sus
     ocupantes.
  3. Que el alta y la edicion efectivamente la llamen, y que el resultado se
     vea en pantalla.

Todo el organigrama es sintetico y vive dentro del savepoint de `db_session`.
"""
from __future__ import annotations

import pytest

from tests.fastapi.titulatec.conftest import HEAD_PERMS, ROLE_HEAD, ROLE_OFFICER, OFFICER_PERMS

from itcj2.apps.titulatec.services.officer_service import OfficerService

CREATE_URL = "/titulatec/admin/officers"


def _url(position_id: int) -> str:
    return f"/titulatec/admin/officers/{position_id}"


def _recargar(db, user):
    db.refresh(user)
    return user


def _es_default(user) -> bool:
    from itcj2.core.utils.security import DEFAULT_PASSWORD, verify_nip
    return verify_nip(DEFAULT_PASSWORD, user.password_hash or "")


@pytest.fixture()
def escenario(make_department, make_position, make_user, make_role,
              bind_position_role, assign_position, make_program, titulatec_app,
              db_session):
    """Un departamento con jefa, una cuenta ACTIVA y dos INACTIVAS, mas una ajena.

    La ajena reproduce a los 9 de Servicios Escolares pero en OTRO departamento:
    es la que nunca debe activarse por esta via.
    """
    def _build():
        d1 = make_department(name="Servicios Escolares (ficticio)")
        d2 = make_department(name="Mantenimiento (ficticio)")
        rol_head = make_role(ROLE_HEAD, HEAD_PERMS)
        make_role(ROLE_OFFICER, OFFICER_PERMS)

        pos_head = make_position(code=f"head_{d1.code}",
                                 title="Jefatura ficticia D1", department=d1)
        bind_position_role(pos_head, rol_head)
        jefa = make_user(first_name="JEFA", last_name="FICTICIA")
        assign_position(jefa, pos_head)

        # Personal del depto: uno activo y dos con la cuenta apagada.
        pos_aux = make_position(code=f"aux_{d1.code}",
                                title="Auxiliar ficticio D1", department=d1)
        activa = make_user(first_name="ACTIVA", last_name="DEUNO", is_active=True)
        inactiva1 = make_user(first_name="APAGADA", last_name="UNO", is_active=False)
        inactiva2 = make_user(first_name="APAGADA", last_name="DOS", is_active=False)
        for u in (activa, inactiva1, inactiva2):
            assign_position(u, pos_aux)

        # Cuenta apagada de OTRO departamento: el jefe de D1 no la ve ni la toca.
        pos_aux_d2 = make_position(code=f"aux_{d2.code}",
                                   title="Auxiliar ficticio D2", department=d2)
        ajena = make_user(first_name="APAGADA", last_name="AJENA", is_active=False)
        assign_position(ajena, pos_aux_d2)

        carrera = make_program("Ingenieria Ficticia Encargados")
        db_session.flush()
        return {"d1": d1, "d2": d2, "jefa": jefa, "activa": activa,
                "inactiva1": inactiva1, "inactiva2": inactiva2, "ajena": ajena,
                "carrera": carrera}
    return _build


# ---------------------------------------------------------------------------
# Servicio
# ---------------------------------------------------------------------------
def test_activate_users_reactiva_y_restablece_la_contrasena(escenario, db_session):
    e = escenario()

    tocados = OfficerService.activate_users(
        db_session, {e["inactiva1"].id, e["inactiva2"].id},
        department_id=e["d1"].id, actor_id=e["jefa"].id)

    assert {t["id"] for t in tocados} == {e["inactiva1"].id, e["inactiva2"].id}
    for u in (e["inactiva1"], e["inactiva2"]):
        _recargar(db_session, u)
        assert u.is_active is True
        assert _es_default(u), "la cuenta quedo sin la contrasena por defecto"
        assert u.must_change_password is True, (
            "sin la bandera, la columna dice lo contrario que el hash"
        )


def test_activate_users_no_toca_a_quien_ya_estaba_activo(escenario, db_session):
    """Editar un encargado no puede resetearle la contrasena a sus ocupantes."""
    e = escenario()
    from itcj2.core.utils.security import hash_nip
    e["activa"].password_hash = hash_nip("suya-propia-2026")
    db_session.flush()
    antes = e["activa"].password_hash

    tocados = OfficerService.activate_users(
        db_session, {e["activa"].id}, department_id=e["d1"].id)

    assert tocados == []
    _recargar(db_session, e["activa"])
    assert e["activa"].password_hash == antes, "le cambiaron la contrasena sin motivo"
    assert not _es_default(e["activa"])


def test_activate_users_ignora_a_quien_no_es_del_departamento(escenario, db_session):
    """LA frontera: un permiso de titulatec no activa cuentas de todo el instituto."""
    e = escenario()

    tocados = OfficerService.activate_users(
        db_session, {e["ajena"].id, e["inactiva1"].id}, department_id=e["d1"].id)

    # La positiva viaja con la negativa: el del propio depto SI se activa, para
    # que el test no pase por no haber hecho nada.
    assert [t["id"] for t in tocados] == [e["inactiva1"].id]
    _recargar(db_session, e["ajena"])
    assert e["ajena"].is_active is False, "se activo una cuenta de otro departamento"
    _recargar(db_session, e["inactiva1"])
    assert e["inactiva1"].is_active is True


def test_activate_users_sin_departamento_no_escribe_nada(escenario, db_session):
    e = escenario()
    with pytest.raises(ValueError):
        OfficerService.activate_users(db_session, {e["inactiva1"].id}, department_id=None)
    _recargar(db_session, e["inactiva1"])
    assert e["inactiva1"].is_active is False


def test_activate_users_con_conjunto_vacio_no_hace_commit(escenario, db_session):
    e = escenario()
    assert OfficerService.activate_users(db_session, set(), department_id=e["d1"].id) == []


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
def test_el_alta_reactiva_y_lo_dice_en_pantalla(escenario, client_as, db_session):
    e = escenario()
    cli = client_as(e["jefa"])

    resp = cli.post(CREATE_URL, data={
        "name": "Encargado de prueba",
        "user_ids": [str(e["inactiva1"].id), str(e["activa"].id)],
        "program_ids": [str(e["carrera"].id)],
    }, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    _recargar(db_session, e["inactiva1"])
    assert e["inactiva1"].is_active is True
    # Y la pantalla lo confirma nombrando la cuenta, no con un "3 cuentas" mudo.
    assert 'data-tt-officers="reactivated"' in resp.text
    # `User.full_name` es "APELLIDO NOMBRE" (`core/models/user.py:87`).
    assert e["inactiva1"].full_name in resp.text
    assert "1 cuenta reactivada" in resp.text, "el plural no concuerda"


def test_el_alta_de_solo_cuentas_activas_no_pinta_la_tarjeta(escenario, client_as):
    e = escenario()
    cli = client_as(e["jefa"])

    resp = cli.post(CREATE_URL, data={
        "name": "Encargado sin reactivaciones",
        "user_ids": [str(e["activa"].id)],
        "program_ids": [str(e["carrera"].id)],
    }, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert 'data-tt-officers="reactivated"' not in resp.text


def test_la_edicion_tambien_reactiva(escenario, client_as, db_session):
    """La ruta de editar existia sin UI desde siempre; ahora la usa la tarjeta."""
    e = escenario()
    cli = client_as(e["jefa"])
    pos_id = OfficerService.create_officer(
        db_session, department_id=e["d1"].id, assigned_role="titulatec_school_services",
        name="Encargado a editar", program_ids={e["carrera"].id},
        user_ids={e["activa"].id})
    db_session.flush()

    resp = cli.post(_url(pos_id), data={
        "user_ids": [str(e["activa"].id), str(e["inactiva2"].id)],
        "program_ids": [str(e["carrera"].id)],
    }, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    _recargar(db_session, e["inactiva2"])
    assert e["inactiva2"].is_active is True
    assert 'data-tt-officers="reactivated"' in resp.text


def test_un_puesto_ajeno_devuelve_404_sin_reactivar_a_nadie(escenario, client_as,
                                                            make_position, db_session):
    """La guarda de propiedad va ANTES de escribir en `core_users`."""
    e = escenario()
    ajeno = make_position(code=f"se_officer_{e['d2'].code}",
                          title="Encargado de otro depto", department=e["d2"])
    db_session.flush()
    cli = client_as(e["jefa"])

    resp = cli.post(_url(ajeno.id), data={
        "user_ids": [str(e["inactiva1"].id)],
        "program_ids": [],
    }, follow_redirects=False)

    assert resp.status_code == 404
    _recargar(db_session, e["inactiva1"])
    assert e["inactiva1"].is_active is False, (
        "se reactivo una cuenta al pasar por una ruta que termina en 404"
    )


def test_el_selector_marca_las_cuentas_inactivas(escenario, client_as):
    """Sin la marca, el jefe no sabe a quien le esta dando acceso."""
    e = escenario()
    cuerpo = client_as(e["jefa"]).get(CREATE_URL, follow_redirects=False).text

    assert 'data-tt-picker-inactive="1"' in cuerpo
    assert "Inactiva" in cuerpo
    # Y el aviso previo al boton existe, aunque nazca oculto.
    assert 'data-tt-officers="warn"' in cuerpo
    assert "tecno#2K" in cuerpo


# ---------------------------------------------------------------------------
# Marcado del redisenio: lo que no puede volver
# ---------------------------------------------------------------------------
def test_el_selector_ya_no_es_un_select_multiple(escenario, client_as):
    """`<select multiple size="3">` mostraba 3 de 11 usuarios y de 25 carreras,
    exigia Ctrl+click y cortaba el cuarto nombre por la mitad."""
    e = escenario()
    cuerpo = client_as(e["jefa"]).get(CREATE_URL, follow_redirects=False).text

    assert "<select" not in cuerpo, "volvio el selector nativo"
    assert 'data-tt-picker' in cuerpo
    assert 'type="checkbox"' in cuerpo


def test_la_tarjeta_separa_usuarios_de_carreras_con_rotulo(escenario, client_as,
                                                           db_session):
    """Antes iban revueltos en la misma fila de pastillas, distinguidos solo por
    color."""
    e = escenario()
    OfficerService.create_officer(
        db_session, department_id=e["d1"].id, assigned_role="titulatec_school_services",
        name="Encargado con rotulos", program_ids={e["carrera"].id},
        user_ids={e["activa"].id})
    db_session.flush()

    cuerpo = client_as(e["jefa"]).get(CREATE_URL, follow_redirects=False).text

    assert "<dt>Usuarios</dt>" in cuerpo
    assert "<dt>Carreras</dt>" in cuerpo


def test_cada_encargado_trae_su_formulario_de_edicion(escenario, client_as, db_session):
    """La ruta `POST /admin/officers/{id}` existia y tenia tests, pero NINGUNA
    plantilla la llamaba: no habia forma de corregir una asignacion."""
    e = escenario()
    pos_id = OfficerService.create_officer(
        db_session, department_id=e["d1"].id, assigned_role="titulatec_school_services",
        name="Encargado editable", program_ids=set(), user_ids=set())
    db_session.flush()

    cuerpo = client_as(e["jefa"]).get(CREATE_URL, follow_redirects=False).text

    assert f'hx-post="/titulatec/admin/officers/{pos_id}"' in cuerpo
    assert f'id="officer-edit-{pos_id}"' in cuerpo
    assert 'data-tt-officers="edit"' in cuerpo


def test_la_pantalla_no_usa_css_ni_js_inline():
    """Regla del proyecto. La cabecera vieja traia `style=` en el h1 y el lede."""
    from pathlib import Path

    import itcj2

    tpl = Path(itcj2.__file__).resolve().parent / "apps" / "titulatec" / "templates" / "titulatec"
    import re

    for ruta in (tpl / "admin" / "officers.html",
                 tpl / "partials" / "officers_body.html"):
        # Sin los comentarios `{# ... #}`: ahi es donde se EXPLICA que el
        # `style=` inline esta prohibido, y contarlo haria fallar al documento
        # por documentarse.
        texto = re.sub(r"{#.*?#}", " ", ruta.read_text(encoding="utf-8"), flags=re.S)
        assert "style=" not in texto, f"CSS inline en {ruta.name}"
        assert "<script" not in texto, f"JS inline en {ruta.name}"
