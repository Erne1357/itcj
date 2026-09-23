"""Rol `graduate` (egresado) para todo alumno que da de alta `import_rows` (2026-09-15).

Por qué existe
--------------
Hasta 2026-09 el alumno de titulación RECICLABA el rol global `student`: el
mismo que AgendaTec exige literalmente (`apps/agendatec/pages/student.py:27`) y
que es el `core_users.role_id` de miles de cuentas. Los permisos de TitulaTec
colgaban de ese rol, así que "ser alumno de AgendaTec" y "estar titulándose"
eran indistinguibles para el backbone de autorización.

`import_rows` es el ÚNICO punto de alta de roles de TitulaTec: lo usan el CSV,
el alta manual, la aprobación de una cuenta nueva y la liga de activación. Por
eso el contrato vive aquí y no en cada llamador:

- asegura `graduate` en las apps `itcj` y `titulatec`;
- revoca `student` en `itcj`, `titulatec` y `agendatec` (la app que no exista en
  la BD se salta en silencio);
- `core_users.role_id` pasa a `graduate` SOLO si era `student` o NULL: nunca
  degrada otro rol global (`staff`);
- el caché de authz se invalida DESPUÉS del commit; con `commit=False` los pares
  viajan en el summary y los tira el llamador tras su propio commit.

Los roles `student` y `graduate` son los REALES a propósito (a diferencia de los
`tt_test_*` del conftest): el contrato es justo sobre esos dos nombres. El CI los
tiene porque `tests/fastapi/conftest.py` los siembra.
"""
from __future__ import annotations

import os

import pytest

from itcj2.apps.titulatec.services.import_service import ImportService


def _row(control, name="ALUMNA INVENTADA"):
    return {"control_number": control, "full_name": name,
            "email": None, "program_id": None, "modality_id": None}


def _role(db_session, name):
    from itcj2.core.models.role import Role

    role = db_session.query(Role).filter_by(name=name).first()
    if role is None:
        role = Role(name=name)
        db_session.add(role)
        db_session.flush()
    return role


def _app(db_session, key):
    """App por clave, creada DENTRO de la transacción si falta (en CI solo existe `itcj`)."""
    from itcj2.core.models.app import App

    app = db_session.query(App).filter_by(key=key).first()
    if app is None:
        app = App(key=key, name=key, is_active=True,
                  visible_to_students=True, mobile_enabled=True)
        db_session.add(app)
        db_session.flush()
    return app


def _dar_rol(db_session, user, app, role):
    from itcj2.core.models.user_app_role import UserAppRole

    db_session.add(UserAppRole(user_id=user.id, app_id=app.id, role_id=role.id))
    db_session.flush()


def _roles_por_app(db_session, user):
    """`{app_key: {rol}}` de las filas DIRECTAS del usuario (`core_user_app_roles`)."""
    from itcj2.core.models.app import App
    from itcj2.core.models.role import Role
    from itcj2.core.models.user_app_role import UserAppRole

    filas = (db_session.query(App.key, Role.name)
             .join(UserAppRole, UserAppRole.app_id == App.id)
             .join(Role, Role.id == UserAppRole.role_id)
             .filter(UserAppRole.user_id == user.id).all())
    out: dict[str, set[str]] = {}
    for key, name in filas:
        out.setdefault(key, set()).add(name)
    return out


def _usuario(db_session, control):
    from itcj2.core.models.user import User

    return db_session.query(User).filter_by(control_number=control).one()


# ---------------------------------------------------------------------------
# Alta de roles
# ---------------------------------------------------------------------------
def test_una_cuenta_nueva_nace_graduate_en_itcj_y_en_titulatec(
    db_session, titulatec_app, make_cohort,
):
    graduate = _role(db_session, "graduate")

    ImportService.import_rows(db_session, make_cohort(), [_row("99150001")])

    user = _usuario(db_session, "99150001")
    assert user.role_id == graduate.id, "el alias legado de la cuenta nueva es graduate"
    assert _roles_por_app(db_session, user) == {
        "itcj": {"graduate"}, "titulatec": {"graduate"}}


@pytest.mark.parametrize("rol_global", ["student", None], ids=["student", "sin-rol"])
def test_una_cuenta_existente_pasa_de_student_a_graduate(
    db_session, titulatec_app, make_cohort, make_user, rol_global,
):
    student = _role(db_session, "student")
    graduate = _role(db_session, "graduate")
    itcj = _app(db_session, "itcj")
    user = make_user(control_number="99150002", username="99150002",
                     global_role=rol_global)
    _dar_rol(db_session, user, titulatec_app, student)
    _dar_rol(db_session, user, itcj, student)

    ImportService.import_rows(db_session, make_cohort(), [_row("99150002")])

    db_session.refresh(user)
    assert user.role_id == graduate.id
    assert _roles_por_app(db_session, user) == {
        "itcj": {"graduate"}, "titulatec": {"graduate"}}


def test_una_cuenta_staff_conserva_su_rol_global(
    db_session, titulatec_app, make_cohort, make_user,
):
    """El alias legado solo se reescribe desde `student` o NULL: pisar `staff`
    le cambiaría el `role` del JWT en el siguiente refresco de sesión."""
    staff = _role(db_session, "staff")
    user = make_user(control_number="99150003", username="99150003", global_role="staff")

    ImportService.import_rows(db_session, make_cohort(), [_row("99150003")])

    db_session.refresh(user)
    assert user.role_id == staff.id
    roles = _roles_por_app(db_session, user)
    assert "graduate" in roles["itcj"] and "graduate" in roles["titulatec"]


def test_se_revoca_student_en_agendatec_y_nada_mas(
    db_session, titulatec_app, make_cohort, make_user,
):
    """AgendaTec exige LITERALMENTE `student`: un egresado deja de verla. Otro rol
    que tenga ahí se queda."""
    student = _role(db_session, "student")
    otro = _role(db_session, f"tt_test_agenda_{os.getpid()}")
    agendatec = _app(db_session, "agendatec")
    user = make_user(control_number="99150004", username="99150004", global_role="student")
    _dar_rol(db_session, user, agendatec, student)
    _dar_rol(db_session, user, agendatec, otro)

    summary = ImportService.import_rows(db_session, make_cohort(), [_row("99150004")])

    assert _roles_por_app(db_session, user)["agendatec"] == {otro.name}
    assert (user.id, "agendatec") in summary["authz_touched"]


def test_una_app_que_no_existe_se_salta_en_silencio(
    db_session, titulatec_app, make_cohort, monkeypatch,
):
    from itcj2.apps.titulatec.services import import_service

    monkeypatch.setattr(import_service, "STUDENT_REVOKE_APP_KEYS",
                        (*import_service.STUDENT_REVOKE_APP_KEYS, "tt_app_que_no_existe"))

    summary = ImportService.import_rows(db_session, make_cohort(), [_row("99150005")])

    assert summary["processes_created"] == 1


def test_es_idempotente(db_session, titulatec_app, make_cohort):
    """Re-importar (o abrir la liga dos veces) no duplica filas ni vuelve a tirar
    el caché de nadie."""
    from itcj2.core.models.user_app_role import UserAppRole

    cohort = make_cohort()
    ImportService.import_rows(db_session, cohort, [_row("99150006")])
    user = _usuario(db_session, "99150006")
    filas = db_session.query(UserAppRole).filter_by(user_id=user.id).count()

    summary = ImportService.import_rows(db_session, cohort, [_row("99150006")])

    assert db_session.query(UserAppRole).filter_by(user_id=user.id).count() == filas
    assert summary["authz_touched"] == []


def test_el_mismo_control_dos_veces_en_un_lote_no_revienta(
    db_session, titulatec_app, make_cohort,
):
    summary = ImportService.import_rows(
        db_session, make_cohort(), [_row("99150007"), _row("99150007")])

    user = _usuario(db_session, "99150007")
    assert _roles_por_app(db_session, user) == {
        "itcj": {"graduate"}, "titulatec": {"graduate"}}
    assert summary["created_users"] == 1 and summary["matched_users"] == 1


def test_sin_el_rol_graduate_falla_con_un_error_claro(
    db_session, titulatec_app, make_cohort, monkeypatch,
):
    from fastapi import HTTPException
    from itcj2.apps.titulatec.services import import_service

    monkeypatch.setattr(import_service, "GRADUATE_ROLE", "tt_rol_que_no_existe")

    with pytest.raises(HTTPException) as exc:
        ImportService.import_rows(db_session, make_cohort(), [_row("99150008")])

    assert exc.value.status_code == 400
    assert exc.value.detail == "Rol 'tt_rol_que_no_existe' no existe."


# ---------------------------------------------------------------------------
# Caché de authz: SIEMPRE después del commit
# ---------------------------------------------------------------------------
def test_con_commit_el_cache_se_tira_despues_del_commit(
    db_session, titulatec_app, make_cohort, monkeypatch,
):
    """Si se tirara antes, una lectura concurrente lo repoblaría con el estado
    viejo y esa entrada viviría el TTL completo (300 s)."""
    from itcj2.core.services import authz_cache

    cohort = make_cohort()
    orden = []
    commit_real = db_session.commit

    def _commit():
        orden.append("commit")
        return commit_real()

    monkeypatch.setattr(db_session, "commit", _commit)
    monkeypatch.setattr(authz_cache, "invalidate_user_app",
                        lambda user_id, app_key: orden.append((user_id, app_key)))

    ImportService.import_rows(db_session, cohort, [_row("99150009")])

    user = _usuario(db_session, "99150009")
    assert orden[0] == "commit" and orden.count("commit") == 1, orden
    assert sorted(orden[1:]) == [(user.id, "itcj"), (user.id, "titulatec")]


def test_la_lectura_cacheada_ve_el_rol_nuevo(
    db_session, titulatec_app, make_cohort, make_user,
):
    """Punta a punta contra Redis: el "no" cacheado antes del alta no sobrevive."""
    from itcj2.core.services.authz_cache import cached_roles

    user = make_user(control_number="99150010", username="99150010")
    assert cached_roles(db_session, user.id, "titulatec") == set()
    assert cached_roles(db_session, user.id, "itcj") == set()

    ImportService.import_rows(db_session, make_cohort(), [_row("99150010")])

    assert "graduate" in cached_roles(db_session, user.id, "titulatec")
    assert "graduate" in cached_roles(db_session, user.id, "itcj")


def test_con_commit_false_la_invalidacion_es_del_llamador(
    db_session, titulatec_app, make_cohort, monkeypatch,
):
    """`approve()` y `verify()` son dueños de su transacción: `import_rows` solo
    hace `flush`, así que todavía no hay nada commiteado que anunciar. Deja los
    pares en el summary y el llamador llama a `invalidate_authz` tras su commit."""
    from itcj2.core.services import authz_cache

    llamadas = []
    monkeypatch.setattr(authz_cache, "invalidate_user_app",
                        lambda user_id, app_key: llamadas.append((user_id, app_key)))

    summary = ImportService.import_rows(db_session, make_cohort(), [_row("99150011")],
                                        commit=False)

    user = _usuario(db_session, "99150011")
    assert llamadas == []
    assert sorted(summary["authz_touched"]) == [(user.id, "itcj"), (user.id, "titulatec")]

    ImportService.invalidate_authz(summary["authz_touched"])
    assert sorted(llamadas) == [(user.id, "itcj"), (user.id, "titulatec")]


def test_invalidate_authz_tolera_que_no_haya_pares():
    """Los tests de `approve`/`verify` sustituyen `import_rows` por dobles que
    devuelven `{"processes_created": 0}`, sin la llave: nada de eso revienta."""
    ImportService.invalidate_authz(None)
    ImportService.invalidate_authz([])
