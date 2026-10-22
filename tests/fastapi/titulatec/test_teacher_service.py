"""Fase 4 (sinodales), tarea 4: `TeacherService` — catálogo de docentes y cuentas.

Spec 2026-10-21 §8 (catálogo de docentes) y §16b R-B (reutilizar cuentas) y R-G
(inerte con el corte <= fase 4). Lo que se fija aquí:

- crear una cuenta nueva: `DEFAULT_PASSWORD` (verificable con el verificador de
  hash), `must_change_password`, rol `staff` en `itcj`, puesto `docente_{depto}`
  vigente y perfil;
- usuario único por persona (D3): correo existente bloquea; la misma persona en
  dos departamentos es UN usuario con DOS puestos y UN perfil (RF1);
- reutilizar (R-B): inactiva o sin primer acceso -> reactiva + restablece;
  con acceso previo -> la contraseña no se toca; correo vacío se escribe, otro
  correo no se pisa; nombre coincidente exige «Es otra persona»;
- quitar con asignaciones vigentes en carreras del depto se bloquea (RF2);
- el correo de acceso falla y el alta persiste (RF5);
- la contraseña jamás aparece en la bitácora, los eventos ni el log.

Datos sintéticos: dominio institucional de PRUEBA (`TITULATEC_TEACHER_EMAIL_DOMAINS`
parcheado) y nombres con el contador del conftest, para no chocar con el
personal real de la base de dev.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

import pytest

from itcj2.apps.titulatec.models import TeacherProfile
from itcj2.apps.titulatec.services import email_helper
from itcj2.apps.titulatec.services.teacher_service import (
    ALREADY_TEACHER_MSG, CONFLICT_MSG, DEGREE_MSG, EMAIL_REQUIRED_MSG, EMAIL_TAKEN_MSG,
    FIRST_NAME_MSG, HAS_ASSIGNMENTS_MSG, INACTIVE_ACCOUNT_MSG, INERT_MSG, LAST_NAME_MSG,
    LICENSE_MSG, NAME_MATCH_MSG, NO_POSITION_MSG, NOT_TEACHER_MSG, POSITION_PREFIX,
    PRIVILEGED_RESET_MSG, RESET_INACTIVE_MSG, RESET_NOT_ALLOWED_MSG, STUDENT_ACCOUNT_MSG,
    EmailTakenError, NameMatchError, TeacherService,
)
from itcj2.core.models.position import Position, UserPosition
from itcj2.core.models.user import User
from itcj2.core.models.user_app_role import UserAppRole
from itcj2.core.utils.security import DEFAULT_PASSWORD, hash_nip, verify_nip
from itcj2.core.utils.timezone import db_now
from tests.fastapi.titulatec.conftest import _n, audit_query

pytestmark = pytest.mark.usefixtures("audit_mark")

DOMINIO = "docentes-tt.invalid"


# ---------------------------------------------------------------------------
# Andamiaje
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _corte_y_dominio(monkeypatch, seed_phase_defs):
    """Corte explícito en 9 (la fase 4 se opera aquí) y dominio de prueba.

    El comando de pruebas corre con `TITULATEC_HANDOFF_PHASE=3`: sin el corte
    explícito todo el catálogo estaría inerte (R-G). Las pruebas del corte
    vuelven a parchearlo a 3."""
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    from itcj2.config import get_settings

    seed_phase_defs()
    monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: 9))
    monkeypatch.setattr(get_settings(), "TITULATEC_TEACHER_EMAIL_DOMAINS",
                        f"{DOMINIO}, Otro-Dominio.invalid ,")


@pytest.fixture()
def staff_itcj(db_session):
    """App `itcj` y rol `staff` (en CI la base nace sin el rol)."""
    from itcj2.core.models.app import App
    from itcj2.core.models.role import Role

    app = db_session.query(App).filter_by(key="itcj").first()
    if app is None:
        app = App(key="itcj", name="Plataforma ITCJ", is_active=True,
                  visible_to_students=False, mobile_enabled=True)
        db_session.add(app)
    role = db_session.query(Role).filter_by(name="staff").first()
    if role is None:
        role = Role(name="staff")
        db_session.add(role)
    db_session.flush()
    return app, role


@pytest.fixture()
def depto(make_department, make_position, staff_itcj):
    """Departamento con su puesto `docente_{code}` (lo que siembra el DML)."""
    def _make(name="Depto docentes prueba"):
        dept = make_department(name=name)
        make_position(code=f"{POSITION_PREFIX}{dept.code}", title=f"Docente · {name}",
                      department=dept)
        return dept
    return _make


@pytest.fixture()
def actor(make_user):
    return make_user(first_name="JEFE", last_name="DEPTO")


def _correo(prefijo="docente"):
    return f"{prefijo}.tt{_n()}@{DOMINIO}"


def _crear(db, actor, dept, **kw):
    """`create_and_add` con datos sintéticos únicos (nombre con contador: nunca
    coincide con el personal real de dev)."""
    n = _n()
    datos = dict(first_name=f"Nombre{n}", last_name="Ficticio", middle_name="Prueba",
                 email=_correo(), academic_degree="Maestra en Ciencias",
                 professional_license="12345678")
    datos.update(kw)
    return TeacherService.create_and_add(db, actor.id, dept.id, **datos)


def _staff_en_itcj(db, user_id, staff_itcj) -> bool:
    app, role = staff_itcj
    return db.query(UserAppRole).filter_by(
        user_id=user_id, app_id=app.id, role_id=role.id).first() is not None


def _rol_en_app(db, user, app_key, role_name):
    """`UserAppRole` directo (crea el rol dentro de la transacción si falta)."""
    from itcj2.core.models.app import App
    from itcj2.core.models.role import Role

    app = db.query(App).filter_by(key=app_key).one()
    role = db.query(Role).filter_by(name=role_name).first()
    if role is None:
        role = Role(name=role_name)
        db.add(role)
        db.flush()
    db.add(UserAppRole(user_id=user.id, app_id=app.id, role_id=role.id))
    db.flush()


def _candado_de_correo_tomado(db, correo) -> bool:
    """¿Esta transacción tiene el candado del correo? Lo pregunta OTRA conexión
    con `pg_try_advisory_xact_lock` (no espera) y suelta lo que haya tomado."""
    from sqlalchemy import text

    with db.get_bind().engine.connect() as otra:
        libre = otra.execute(text(
            "SELECT pg_try_advisory_xact_lock(hashtext('tt:teacher-email:' || lower(:e)))"),
            {"e": correo}).scalar()
        otra.rollback()
    return not libre


def _hash_y_epoca(db, user):
    """Credencial y estado TAL COMO están en la BD (la época la sube un UPDATE crudo)."""
    db.flush()
    db.refresh(user)
    return user.password_hash, user.must_change_password, user.session_epoch, user.is_active


def _puestos_vigentes(db, user_id) -> set[str]:
    from itcj2.core.services.authz_service import _active_position_filter
    return {code for (code,) in db.query(Position.code)
            .join(UserPosition, UserPosition.position_id == Position.id)
            .filter(UserPosition.user_id == user_id, _active_position_filter()).all()}


def _volcado_de_bitacora(db) -> str:
    filas = audit_query(db).all()
    return json.dumps([[f.action, f.subject_label, f.reason, f.before, f.after, f.payload]
                       for f in filas], ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Crear una cuenta nueva
# ---------------------------------------------------------------------------
def test_crear_deja_la_cuenta_con_la_contrasena_temporal_staff_puesto_y_perfil(
        db_session, depto, actor, staff_itcj):
    dept = depto()
    correo = _correo()
    apellido = f"lópez{_n()}"
    res = _crear(db_session, actor, dept, email=correo.upper(), first_name="  maría  josé ",
                 last_name=apellido, middle_name="")
    assert res == {"user_id": res["user_id"], "access_email_needed": True}
    assert DEFAULT_PASSWORD not in repr(res)

    u = db_session.get(User, res["user_id"])
    assert verify_nip(DEFAULT_PASSWORD, u.password_hash)
    assert u.must_change_password is True and u.is_active is True
    assert u.email == correo                       # minúsculas
    assert u.username == correo.split("@")[0]      # parte local
    assert (u.first_name, u.last_name, u.middle_name) == ("MARÍA JOSÉ", apellido.upper(), None)
    assert u.control_number is None and u.last_login is None
    assert u.role_id == staff_itcj[1].id           # rol global de personal, como el core
    assert _staff_en_itcj(db_session, u.id, staff_itcj)
    assert _puestos_vigentes(db_session, u.id) == {f"{POSITION_PREFIX}{dept.code}"}
    assert TeacherService.is_teacher_of(db_session, u.id, dept.id)
    prof = db_session.get(TeacherProfile, u.id)
    assert (prof.academic_degree, prof.professional_license) == ("Maestra en Ciencias", "12345678")
    assert prof.updated_by_id == actor.id

    fila = audit_query(db_session).filter_by(action="teacher.created").one()
    assert fila.actor_id == actor.id and fila.entity_type == "user" and fila.entity_id == u.id
    assert fila.payload["department_id"] == dept.id


def test_crear_con_correo_existente_se_bloquea_sin_distinguir_mayusculas(
        db_session, depto, actor, make_user):
    dept = depto()
    correo = _correo()
    previo = make_user(email=correo.upper())
    with pytest.raises(EmailTakenError) as err:
        _crear(db_session, actor, dept, email=f"  {correo}  ")
    assert str(err.value) == EMAIL_TAKEN_MSG
    assert isinstance(err.value, ValueError)
    assert [c["user_id"] for c in err.value.candidates] == [previo.id]
    assert db_session.query(User).filter(User.username == correo.split("@")[0]).count() == 0


def test_crear_busca_dueños_del_correo_bajo_su_candado(db_session, depto, actor):
    """`core_users.email` no es UNIQUE: dos altas con el mismo correo se
    serializan con `pg_advisory_xact_lock` antes de buscar dueños."""
    dept = depto()
    correo = _correo()
    assert not _candado_de_correo_tomado(db_session, correo)
    _crear(db_session, actor, dept, email=correo.upper())
    assert _candado_de_correo_tomado(db_session, correo)


def test_el_correo_que_choca_con_un_alumno_lo_marca_como_alumno(db_session, depto, actor,
                                                               make_student):
    dept = depto()
    correo = _correo()
    alumno = make_student()
    alumno.email = correo
    db_session.flush()
    with pytest.raises(EmailTakenError) as err:
        _crear(db_session, actor, dept, email=correo)
    (cand,) = err.value.candidates
    assert cand["user_id"] == alumno.id and cand["is_student"] is True


@pytest.mark.parametrize("local", ["20111234", "l20111234", "C99112233"])
def test_crear_rechaza_un_usuario_con_forma_de_numero_de_control(db_session, depto, actor, local):
    """El login manda 8 dígitos (o letra + 8) al camino de alumnos: con ese
    usuario el docente nunca podría entrar."""
    dept = depto()
    with pytest.raises(ValueError) as err:
        _crear(db_session, actor, dept, email=f"{local}@{DOMINIO}")
    assert local.lower() in str(err.value) and "número de control" in str(err.value)
    assert db_session.query(User).filter(User.email == f"{local.lower()}@{DOMINIO}").count() == 0


@pytest.mark.parametrize("forma", [
    lambda n: f"9{n:08d}",          # 9 dígitos
    lambda n: f"doc{n:08d}",        # letras + 8 dígitos
    lambda n: f"{n:08d}x",          # 8 dígitos + letra al final
])
def test_usuarios_parecidos_a_un_control_que_no_lo_son_se_aceptan(db_session, depto, actor,
                                                                  forma):
    dept = depto()
    local = forma(_n())                # único por corrida: nunca choca con otra prueba
    res = _crear(db_session, actor, dept, email=f"{local}@{DOMINIO}")
    assert db_session.get(User, res["user_id"]).username == local


def test_crear_con_usuario_ocupado_se_rechaza_con_mensaje_claro(db_session, depto, actor, make_user):
    dept = depto()
    local = f"choque{_n()}"
    make_user(username=local.upper())
    with pytest.raises(ValueError, match=local):
        _crear(db_session, actor, dept, email=f"{local}@{DOMINIO}")
    assert db_session.query(User).filter(User.email == f"{local}@{DOMINIO}").count() == 0


@pytest.mark.parametrize("correo", [
    "alguien@gmail.com",
    f"alguien@sub.{DOMINIO}",
    f"alguien@{DOMINIO}.evil.com",
    "sin-arroba",
    f"@{DOMINIO}",
    f"dos@@{DOMINIO}",
    f"con espacio@{DOMINIO}",
])
def test_dominio_o_forma_invalida_se_rechaza(db_session, depto, actor, correo):
    dept = depto()
    with pytest.raises(ValueError):
        _crear(db_session, actor, dept, email=correo)


def test_acepta_cualquiera_de_los_dominios_configurados(db_session, depto, actor):
    dept = depto()
    res = _crear(db_session, actor, dept, email=f"otra.tt{_n()}@otro-dominio.invalid")
    assert db_session.get(User, res["user_id"]).email.endswith("@otro-dominio.invalid")


def test_dominios_permitidos_salen_de_la_configuracion(monkeypatch):
    from itcj2.config import Settings, get_settings
    assert Settings.model_fields["TITULATEC_TEACHER_EMAIL_DOMAINS"].default == "cdjuarez.tecnm.mx"
    assert TeacherService.allowed_email_domains() == (DOMINIO, "otro-dominio.invalid")
    monkeypatch.setattr(get_settings(), "TITULATEC_TEACHER_EMAIL_DOMAINS", " ")
    assert TeacherService.allowed_email_domains() == ()


@pytest.mark.parametrize("campo, valor, mensaje", [
    ("academic_degree", "M", DEGREE_MSG),
    ("academic_degree", "x" * 151, DEGREE_MSG),
    ("academic_degree", "   ", DEGREE_MSG),
    ("professional_license", "1234", LICENSE_MSG),
    ("professional_license", "1234567890123", LICENSE_MSG),
    ("professional_license", "12a45678", LICENSE_MSG),
    ("professional_license", "", LICENSE_MSG),
    ("first_name", "  ", FIRST_NAME_MSG),
    ("last_name", "", LAST_NAME_MSG),
])
def test_validaciones_de_alta(db_session, depto, actor, campo, valor, mensaje):
    dept = depto()
    with pytest.raises(ValueError) as err:
        _crear(db_session, actor, dept, **{campo: valor})
    assert str(err.value) == mensaje


def test_grado_y_cedula_en_los_bordes_se_aceptan(db_session, depto, actor):
    dept = depto()
    res = _crear(db_session, actor, dept, academic_degree="Dr", professional_license=" 12345 ")
    prof = db_session.get(TeacherProfile, res["user_id"])
    assert (prof.academic_degree, prof.professional_license) == ("Dr", "12345")
    res = _crear(db_session, actor, dept, academic_degree="x" * 150,
                 professional_license="123456789012")
    assert db_session.get(TeacherProfile, res["user_id"]).professional_license == "123456789012"


def test_nombre_coincidente_exige_confirmar_que_es_otra_persona(db_session, depto, actor, make_user):
    dept = depto()
    apellido = f"COINCIDE{_n()}"
    previo = make_user(first_name="ANA", last_name=apellido)
    correo = _correo()
    with pytest.raises(NameMatchError) as err:
        _crear(db_session, actor, dept, first_name="Ána", last_name=apellido.lower(),
               email=correo)
    assert str(err.value) == NAME_MATCH_MSG
    assert [c["user_id"] for c in err.value.candidates] == [previo.id]
    assert db_session.query(User).filter(User.email == correo).count() == 0

    res = _crear(db_session, actor, dept, first_name="Ána", last_name=apellido.lower(),
                 email=correo, confirm_other_person=True)
    assert res["user_id"] != previo.id
    fila = audit_query(db_session).filter_by(action="teacher.created").one()
    assert fila.payload["confirmed_other_person"] is True
    assert fila.payload["name_matches"] == [previo.id]


def test_un_alumno_con_el_mismo_nombre_no_cuenta_como_coincidencia(
        db_session, depto, actor, make_student):
    dept = depto()
    apellido = f"ALUMNO{_n()}"
    make_student(first_name="LUIS", last_name=apellido)
    res = _crear(db_session, actor, dept, first_name="Luis", last_name=apellido)
    assert res["access_email_needed"] is True


def test_sin_puesto_docente_el_alta_falla_con_mensaje_del_dml(db_session, make_department, actor,
                                                             staff_itcj):
    dept = make_department()
    with pytest.raises(ValueError) as err:
        _crear(db_session, actor, dept)
    assert str(err.value) == NO_POSITION_MSG
    with pytest.raises(ValueError):
        TeacherService.position_for(db_session, dept.id)
    assert TeacherService.roster(db_session, dept.id) == []


# ---------------------------------------------------------------------------
# Usuario único por persona (RF1) y reutilizar cuentas (R-B)
# ---------------------------------------------------------------------------
def test_la_misma_persona_en_dos_departamentos_es_un_usuario_con_dos_puestos(
        db_session, depto, actor, staff_itcj):
    a, b = depto(name="Depto A"), depto(name="Depto B")
    correo = _correo()
    res = _crear(db_session, actor, a, email=correo)
    uid = res["user_id"]
    res_b = TeacherService.add_existing(db_session, actor.id, b.id, uid,
                                        academic_degree="Doctora en Ciencias",
                                        professional_license="87654321")
    assert res_b["user_id"] == uid
    assert db_session.query(User).filter(User.email == correo).count() == 1
    assert _puestos_vigentes(db_session, uid) == {f"{POSITION_PREFIX}{a.code}",
                                                  f"{POSITION_PREFIX}{b.code}"}
    assert db_session.query(TeacherProfile).filter_by(user_id=uid).count() == 1
    # El perfil es uno solo: la corrección se ve en los dos departamentos.
    assert db_session.get(TeacherProfile, uid).academic_degree == "Doctora en Ciencias"
    app, role = staff_itcj
    assert db_session.query(UserAppRole).filter_by(user_id=uid, app_id=app.id,
                                                   role_id=role.id).count() == 1
    cand = TeacherService.search_candidates(db_session, correo)
    assert cand[0]["user_id"] == uid and cand[0]["already_in"] == sorted([a.id, b.id])


@pytest.mark.parametrize("ya_entro", [False, True])
def test_una_cuenta_inactiva_sin_privilegios_no_se_reactiva(
        db_session, depto, actor, make_user, staff_itcj, ya_entro):
    """Enmienda de seguridad de R-B: el departamento nunca reactiva."""
    dept = depto()
    u = make_user(first_name=f"INACTIVA{_n()}", last_name="FICTICIA", is_active=False)
    u.password_hash = hash_nip("clave-propia-123")
    u.last_login = datetime(2025, 1, 15, 9, 0) if ya_entro else None
    antes = _hash_y_epoca(db_session, u)

    with pytest.raises(ValueError) as err:
        TeacherService.add_existing(db_session, actor.id, dept.id, u.id,
                                    academic_degree="Ingeniero", professional_license="5550001")
    assert str(err.value) == INACTIVE_ACCOUNT_MSG
    assert "administrador" in str(err.value)
    assert _hash_y_epoca(db_session, u) == antes          # hash, cambio, época, inactiva
    assert not TeacherService.is_teacher_of(db_session, u.id, dept.id)
    assert not _staff_en_itcj(db_session, u.id, staff_itcj)
    assert not audit_query(db_session).filter_by(action="teacher.added").count()


# --- Cuentas con privilegios: el departamento nunca toca su credencial -------
@pytest.fixture()
def cuenta_admin_itcj(db_session, make_user, staff_itcj):
    """Activa, nunca entró, con `admin` en `itcj` (p. ej. alguien de Cómputo)."""
    u = make_user(first_name=f"ADMINISTRA{_n()}", last_name="FICTICIA")
    u.password_hash = hash_nip("clave-del-admin-1")
    _rol_en_app(db_session, u, "itcj", "admin")
    return u


def test_cuenta_con_admin_en_itcj_se_agrega_sin_tocar_la_credencial(
        db_session, depto, actor, cuenta_admin_itcj, staff_itcj):
    dept = depto()
    u = cuenta_admin_itcj
    antes = _hash_y_epoca(db_session, u)
    assert TeacherService.has_privileges(db_session, u.id)

    res = TeacherService.add_existing(db_session, actor.id, dept.id, u.id,
                                      academic_degree="Ingeniero", professional_license="5550021")
    assert res == {"user_id": u.id, "access_email_needed": False}
    assert _hash_y_epoca(db_session, u) == antes
    assert not verify_nip(DEFAULT_PASSWORD, u.password_hash)
    assert TeacherService.is_teacher_of(db_session, u.id, dept.id)
    assert _staff_en_itcj(db_session, u.id, staff_itcj)
    fila = audit_query(db_session).filter_by(action="teacher.added").one()
    assert fila.payload["privileged_account"] is True
    assert fila.payload["credential_reset"] is False


def test_la_misma_cuenta_privilegiada_inactiva_se_rechaza(
        db_session, depto, actor, cuenta_admin_itcj):
    dept = depto()
    u = cuenta_admin_itcj
    u.is_active = False
    antes = _hash_y_epoca(db_session, u)
    with pytest.raises(ValueError) as err:
        TeacherService.add_existing(db_session, actor.id, dept.id, u.id,
                                    academic_degree="Ingeniero", professional_license="5550022")
    assert str(err.value) == INACTIVE_ACCOUNT_MSG
    assert _hash_y_epoca(db_session, u) == antes
    assert not TeacherService.is_teacher_of(db_session, u.id, dept.id)


def test_cuenta_con_puesto_vigente_no_docente_no_toca_la_credencial(
        db_session, depto, actor, make_user, make_position, assign_position):
    dept = depto()
    u = make_user(first_name=f"JEFATURA{_n()}", last_name="FICTICIA")
    u.password_hash = hash_nip("clave-de-jefatura-1")
    assign_position(u, make_position(title="Jefatura ajena de prueba"),
                    start_date=db_now().date() - timedelta(days=1))
    antes = _hash_y_epoca(db_session, u)

    res = TeacherService.add_existing(db_session, actor.id, dept.id, u.id,
                                      academic_degree="Ingeniero", professional_license="5550023")
    assert res["access_email_needed"] is False
    assert _hash_y_epoca(db_session, u) == antes
    assert TeacherService.is_teacher_of(db_session, u.id, dept.id)


def test_cuenta_con_rol_global_distinto_de_staff_no_toca_la_credencial(
        db_session, depto, actor, make_user):
    dept = depto()
    u = make_user(first_name=f"GLOBAL{_n()}", last_name="FICTICIA", global_role="admin")
    antes = _hash_y_epoca(db_session, u)
    res = TeacherService.add_existing(db_session, actor.id, dept.id, u.id,
                                      academic_degree="Ingeniero", professional_license="5550024")
    assert res["access_email_needed"] is False
    assert _hash_y_epoca(db_session, u) == antes


def test_que_cuenta_como_privilegio(db_session, depto, actor, make_user, make_position,
                                    assign_position, staff_itcj, titulatec_app):
    """La definición de la enmienda: rol global no-staff, otro rol de app, un
    puesto ACTIVO que no sea `docente_*` (sin ventana de fechas: falla cerrado)
    o un permiso directo (pruebas propias abajo)."""
    hoy = db_now().date()
    limpia = make_user(global_role="staff")
    _rol_en_app(db_session, limpia, "itcj", "staff")
    otro_depto = depto(name="Depto privilegios")
    TeacherService.add_existing(db_session, actor.id, otro_depto.id, limpia.id,
                                academic_degree="Maestro", professional_license="5550025")
    cerrado = make_user()
    assign_position(cerrado, make_position(), start_date=hoy - timedelta(days=30),
                    end_date=hoy - timedelta(days=2), is_active=False)
    for u in (limpia, cerrado, make_user()):
        assert TeacherService.has_privileges(db_session, u.id) is False, u.id

    en_titulatec = make_user()
    _rol_en_app(db_session, en_titulatec, "titulatec", f"tt_test_rol_{_n()}")
    con_puesto = make_user()
    assign_position(con_puesto, make_position(), start_date=hoy - timedelta(days=1))
    # `is_active` con la fecha de fin ya pasada (nadie lo cerró): también cuenta.
    vencido_sin_cerrar = make_user()
    assign_position(vencido_sin_cerrar, make_position(), start_date=hoy - timedelta(days=30),
                    end_date=hoy - timedelta(days=2))
    for u in (en_titulatec, con_puesto, vencido_sin_cerrar, make_user(global_role="admin")):
        assert TeacherService.has_privileges(db_session, u.id) is True, u.id
    assert TeacherService.has_privileges(db_session, 9_999_999_999) is True   # falla cerrado


def test_un_puesto_no_docente_con_inicio_futuro_ya_cuenta_como_privilegio(
        db_session, depto, actor, make_user, make_position, assign_position):
    """Falla cerrado: la jefatura asignada que empieza la semana próxima ya hace
    privilegiada la cuenta, así que el departamento no le deja hoy la contraseña
    conocida de la plataforma."""
    dept = depto()
    u = make_user(first_name=f"FUTURA{_n()}", last_name="JEFATURA")
    u.password_hash = hash_nip("clave-de-la-futura-1")
    assign_position(u, make_position(title="Jefatura que empieza después"),
                    start_date=db_now().date() + timedelta(days=7))
    antes = _hash_y_epoca(db_session, u)
    assert TeacherService.has_privileges(db_session, u.id) is True

    res = TeacherService.add_existing(db_session, actor.id, dept.id, u.id,
                                      academic_degree="Ingeniera", professional_license="5550030")
    assert res["access_email_needed"] is False
    assert _hash_y_epoca(db_session, u) == antes
    with pytest.raises(ValueError) as err:
        TeacherService.reset_access(db_session, actor.id, dept.id, u.id)
    assert str(err.value) == PRIVILEGED_RESET_MSG


@pytest.mark.parametrize("allow", [True, False])
def test_un_permiso_directo_de_usuario_cuenta_como_privilegio(
        db_session, depto, actor, make_user, make_perms, titulatec_app, allow):
    """`core_user_app_perms` en cualquier app; también una fila `allow = false`
    (falla cerrado: quien tiene permisos a mano lo administra alguien más)."""
    from itcj2.core.models.user_app_perm import UserAppPerm

    dept = depto()
    u = make_user(first_name=f"PERMISO{_n()}", last_name="FICTICIA")
    u.password_hash = hash_nip("clave-con-permiso-1")
    perm = make_perms(["titulatec.process.page.list"])["titulatec.process.page.list"]
    db_session.add(UserAppPerm(user_id=u.id, app_id=titulatec_app.id, perm_id=perm.id,
                               allow=allow))
    antes = _hash_y_epoca(db_session, u)
    assert TeacherService.has_privileges(db_session, u.id) is True

    res = TeacherService.add_existing(db_session, actor.id, dept.id, u.id,
                                      academic_degree="Ingeniero", professional_license="5550028")
    assert res["access_email_needed"] is False
    assert _hash_y_epoca(db_session, u) == antes
    assert TeacherService.is_teacher_of(db_session, u.id, dept.id)


def test_un_permiso_directo_en_el_puesto_docente_cuenta_como_privilegio(
        db_session, depto, actor, make_user, make_perms, titulatec_app, assign_position):
    """`core_position_app_perms` en un puesto que la persona ocupa, aunque sea
    su propio `docente_*` (el modelo lo permite): ya no se le toca la credencial
    ni desde ese depto ni desde otro."""
    from itcj2.core.models.position import PositionAppPerm

    dept, otro = depto(name="Depto con permiso de puesto"), depto(name="Depto sin permiso")
    uid = _crear(db_session, actor, dept)["user_id"]
    assert TeacherService.has_privileges(db_session, uid) is False
    pos = TeacherService.position_for(db_session, dept.id)
    perm = make_perms(["titulatec.process.page.list"])["titulatec.process.page.list"]
    db_session.add(PositionAppPerm(position_id=pos.id, app_id=titulatec_app.id,
                                   perm_id=perm.id, allow=True))
    db_session.flush()
    assert TeacherService.has_privileges(db_session, uid) is True

    u = db_session.get(User, uid)
    antes = _hash_y_epoca(db_session, u)
    with pytest.raises(ValueError) as err:
        TeacherService.reset_access(db_session, actor.id, dept.id, uid)
    assert str(err.value) == PRIVILEGED_RESET_MSG
    res = TeacherService.add_existing(db_session, actor.id, otro.id, uid,
                                      academic_degree="Maestro", professional_license="5550029")
    assert res["access_email_needed"] is False
    assert _hash_y_epoca(db_session, u) == antes

    # Solo cuentan los puestos que ocupa con `is_active`; con fecha futura sí
    # cuenta (falla cerrado), cerrado no.
    hoy = db_now().date()
    futuro, cerrado = make_user(), make_user()
    assign_position(futuro, pos, start_date=hoy + timedelta(days=5))
    assign_position(cerrado, pos, start_date=hoy - timedelta(days=30), is_active=False)
    assert TeacherService.has_privileges(db_session, futuro.id) is True
    assert TeacherService.has_privileges(db_session, cerrado.id) is False


def test_reutilizar_una_cuenta_sin_privilegios_ni_primer_acceso_restablece(
        db_session, depto, actor, make_user, staff_itcj):
    """El caso feliz de R-B sigue igual: activa, sin privilegios, nunca entró."""
    dept = depto()
    u = make_user(first_name=f"SINACCESO{_n()}", last_name="FICTICIA")
    u.password_hash = hash_nip("clave-de-alta-1")
    _, _, epoca, _ = _hash_y_epoca(db_session, u)
    res = TeacherService.add_existing(db_session, actor.id, dept.id, u.id,
                                      academic_degree="Ingeniera", professional_license="5550002")
    assert res == {"user_id": u.id, "access_email_needed": True}
    hash_, cambio, epoca_nueva, activa = _hash_y_epoca(db_session, u)
    assert verify_nip(DEFAULT_PASSWORD, hash_) and cambio is True and activa is True
    assert epoca_nueva == epoca + 1                     # revoca sesiones vivas
    assert _staff_en_itcj(db_session, u.id, staff_itcj)
    fila = audit_query(db_session).filter_by(action="teacher.added").one()
    assert fila.payload["privileged_account"] is False
    assert fila.payload["credential_reset"] is True


def test_reutilizar_una_cuenta_con_acceso_previo_no_toca_la_contrasena(
        db_session, depto, actor, make_user, staff_itcj):
    dept = depto()
    u = make_user(first_name=f"ACTIVA{_n()}", last_name="FICTICIA")
    hash_previo = hash_nip("clave-propia-456")
    u.password_hash = hash_previo
    u.last_login = datetime(2026, 9, 1, 10, 0)
    db_session.flush()
    epoca = u.session_epoch

    res = TeacherService.add_existing(db_session, actor.id, dept.id, u.id,
                                      academic_degree="Maestro", professional_license="5550003")
    assert res == {"user_id": u.id, "access_email_needed": False}
    db_session.refresh(u)
    assert u.password_hash == hash_previo
    assert u.must_change_password is False and u.session_epoch == epoca
    assert _staff_en_itcj(db_session, u.id, staff_itcj)
    assert TeacherService.is_teacher_of(db_session, u.id, dept.id)
    assert audit_query(db_session).filter_by(action="teacher.added").one() \
        .payload["credential_reset"] is False


def test_reutilizar_una_cuenta_que_ya_tiene_staff_no_lo_duplica(
        db_session, depto, actor, make_user, staff_itcj):
    dept = depto()
    app, role = staff_itcj
    u = make_user()
    db_session.add(UserAppRole(user_id=u.id, app_id=app.id, role_id=role.id))
    db_session.flush()
    TeacherService.add_existing(db_session, actor.id, dept.id, u.id,
                                academic_degree="Maestro", professional_license="5550004")
    assert db_session.query(UserAppRole).filter_by(user_id=u.id, app_id=app.id).count() == 1
    assert audit_query(db_session).filter_by(action="teacher.added").one() \
        .payload["staff_role_granted"] is False


def test_cuenta_sin_correo_recibe_el_institucional(db_session, depto, actor, make_user):
    dept = depto()
    u = make_user()
    u.email = None
    db_session.flush()
    correo = _correo()
    with pytest.raises(ValueError) as err:
        TeacherService.add_existing(db_session, actor.id, dept.id, u.id,
                                    academic_degree="Maestro", professional_license="5550005")
    assert str(err.value) == EMAIL_REQUIRED_MSG
    with pytest.raises(ValueError):
        TeacherService.add_existing(db_session, actor.id, dept.id, u.id,
                                    academic_degree="Maestro", professional_license="5550005",
                                    institutional_email="alguien@gmail.com")
    TeacherService.add_existing(db_session, actor.id, dept.id, u.id,
                                academic_degree="Maestro", professional_license="5550005",
                                institutional_email=correo.upper())
    assert db_session.get(User, u.id).email == correo
    assert audit_query(db_session).filter_by(action="teacher.added").one() \
        .payload["email_written"] is True
    # Escribir el correo fue bajo el candado del correo (no hay índice único).
    assert _candado_de_correo_tomado(db_session, correo)
    assert not _candado_de_correo_tomado(db_session, _correo())


def test_cuenta_sin_correo_no_toma_uno_ajeno(db_session, depto, actor, make_user):
    dept = depto()
    correo = _correo()
    make_user(email=correo)
    u = make_user()
    u.email = "  "
    db_session.flush()
    with pytest.raises(EmailTakenError):
        TeacherService.add_existing(db_session, actor.id, dept.id, u.id,
                                    academic_degree="Maestro", professional_license="5550006",
                                    institutional_email=correo)


def test_cuenta_con_otro_correo_no_se_sobrescribe(db_session, depto, actor, make_user):
    dept = depto()
    u = make_user(email="personal.tt@example.invalid")
    TeacherService.add_existing(db_session, actor.id, dept.id, u.id,
                                academic_degree="Maestro", professional_license="5550007",
                                institutional_email=_correo())
    assert db_session.get(User, u.id).email == "personal.tt@example.invalid"
    assert audit_query(db_session).filter_by(action="teacher.added").one() \
        .payload["email_written"] is False


def test_una_cuenta_de_alumno_no_se_reutiliza_ni_aparece_en_la_busqueda(
        db_session, depto, actor, make_student):
    dept = depto()
    apellido = f"EGRESADO{_n()}"
    alumno = make_student(first_name="PEDRO", last_name=apellido)
    hash_previo = alumno.password_hash
    with pytest.raises(ValueError) as err:
        TeacherService.add_existing(db_session, actor.id, dept.id, alumno.id,
                                    academic_degree="Ingeniero", professional_license="5550008")
    assert str(err.value) == STUDENT_ACCOUNT_MSG
    assert alumno.password_hash == hash_previo
    assert TeacherService.search_candidates(db_session, f"pedro {apellido}") == []


def test_agregar_dos_veces_al_mismo_departamento_se_rechaza(db_session, depto, actor):
    dept = depto()
    uid = _crear(db_session, actor, dept)["user_id"]
    with pytest.raises(ValueError) as err:
        TeacherService.add_existing(db_session, actor.id, dept.id, uid,
                                    academic_degree="Maestro", professional_license="5550009")
    assert str(err.value) == ALREADY_TEACHER_MSG


def test_un_choque_de_unicidad_concurrente_sale_como_conflicto(db_session, depto, actor,
                                                              monkeypatch):
    """Dos altas a la vez: la segunda no vio la fila de la primera al validar y
    choca con `uq_active_user_position_new`. Sale un `ValueError` legible, no
    un `IntegrityError` crudo, y no queda nada a medias. Tampoco lo encadena:
    su sentencia y parámetros (hash, correo) no viajan en el error."""
    dept = depto()
    uid = _crear(db_session, actor, dept)["user_id"]
    db_session.commit()        # checkpoint: el rollback del servicio no se lleva el alta
    monkeypatch.setattr(TeacherService, "_locked_links", staticmethod(lambda *a, **k: []))
    with pytest.raises(ValueError) as err:
        TeacherService.add_existing(db_session, actor.id, dept.id, uid,
                                    academic_degree="Maestro", professional_license="5550020")
    assert str(err.value) == CONFLICT_MSG
    assert err.value.__cause__ is None and err.value.__suppress_context__ is True
    assert not audit_query(db_session).filter_by(action="teacher.added").count()


def test_la_cuenta_se_bloquea_con_for_no_key_update(db_session, depto, actor, make_user):
    """Convención de `ProcessService.cancel`: no bloquear las llaves foráneas."""
    from sqlalchemy import event

    dept = depto()
    u = make_user()
    sentencias = []

    def _anota(conn, cursor, statement, *args):
        sentencias.append(statement)

    conn = db_session.connection()
    event.listen(conn, "before_cursor_execute", _anota)
    try:
        TeacherService.add_existing(db_session, actor.id, dept.id, u.id,
                                    academic_degree="Maestro", professional_license="5550026")
    finally:
        event.remove(conn, "before_cursor_execute", _anota)
    de_la_cuenta = [s for s in sentencias if "FROM core_users" in s and "FOR " in s]
    assert de_la_cuenta and all("FOR NO KEY UPDATE" in s for s in de_la_cuenta)


def test_cuenta_inexistente(db_session, depto, actor):
    dept = depto()
    with pytest.raises(ValueError):
        TeacherService.add_existing(db_session, actor.id, dept.id, 9_999_999_999,
                                    academic_degree="Maestro", professional_license="5550010")


# ---------------------------------------------------------------------------
# Quitar del departamento (RF2)
# ---------------------------------------------------------------------------
@pytest.fixture()
def proceso_del_depto(make_program, make_program_department, make_student, make_process):
    def _make(dept, *, status="active"):
        prog = make_program(f"Carrera docentes {_n()}")
        make_program_department(prog, dept)
        return make_process(make_student(), program=prog, current_phase=5, status=status)
    return _make


def test_quitar_con_asignaciones_vigentes_se_bloquea(db_session, depto, actor, proceso_del_depto,
                                                     make_synodals):
    dept = depto()
    uid = _crear(db_session, actor, dept)["user_id"]
    docente = db_session.get(User, uid)
    make_synodals(proceso_del_depto(dept), {"vocal": docente}, assigned_by=actor)

    with pytest.raises(ValueError) as err:
        TeacherService.remove_from_department(db_session, actor.id, dept.id, uid)
    assert str(err.value) == HAS_ASSIGNMENTS_MSG
    assert TeacherService.is_teacher_of(db_session, uid, dept.id)
    assert not audit_query(db_session).filter_by(action="teacher.removed").count()


def test_quitar_sin_asignaciones_vigentes_en_el_depto_termina_el_puesto(
        db_session, depto, actor, proceso_del_depto, make_synodals):
    dept, otro = depto(name="Depto propio"), depto(name="Depto ajeno")
    uid = _crear(db_session, actor, dept)["user_id"]
    docente = db_session.get(User, uid)
    # Lo que NO bloquea: un proceso de una carrera de otro depto, una asignación
    # ya sustituida y un proceso revocado.
    make_synodals(proceso_del_depto(otro), {"president": docente}, assigned_by=actor)
    sustituida = make_synodals(proceso_del_depto(dept), {"secretary": docente},
                               assigned_by=actor)[0]
    sustituida.is_active = False
    make_synodals(proceso_del_depto(dept, status="cancelled"), {"vocal": docente},
                  assigned_by=actor)
    db_session.flush()

    TeacherService.remove_from_department(db_session, actor.id, dept.id, uid)
    assert not TeacherService.is_teacher_of(db_session, uid, dept.id)
    assert db_session.get(User, uid) is not None             # nunca borra al usuario
    assert db_session.get(TeacherProfile, uid) is not None   # ni su perfil
    link = (db_session.query(UserPosition).join(Position)
            .filter(UserPosition.user_id == uid,
                    Position.code == f"{POSITION_PREFIX}{dept.code}").one())
    assert link.is_active is False and link.end_date is not None
    fila = audit_query(db_session).filter_by(action="teacher.removed").one()
    assert fila.entity_id == uid and fila.payload["department_id"] == dept.id

    # Y se le puede volver a agregar (índice único parcial sobre is_active).
    res = TeacherService.add_existing(db_session, actor.id, dept.id, uid,
                                      academic_degree="Maestro", professional_license="5550011")
    assert res["user_id"] == uid and TeacherService.is_teacher_of(db_session, uid, dept.id)


def test_quitar_a_quien_no_es_docente_del_depto(db_session, depto, actor, make_user):
    dept = depto()
    with pytest.raises(ValueError) as err:
        TeacherService.remove_from_department(db_session, actor.id, dept.id, make_user().id)
    assert str(err.value) == NOT_TEACHER_MSG


# ---------------------------------------------------------------------------
# Puesto vigente
# ---------------------------------------------------------------------------
def test_is_teacher_of_solo_cuenta_el_puesto_vigente(db_session, depto, make_user, make_position,
                                                     assign_position):
    dept = depto()
    pos = make_position(code=f"{POSITION_PREFIX}{dept.code}")
    hoy = db_now().date()
    vigente, vencido, inactivo, futuro = (make_user() for _ in range(4))
    assign_position(vigente, pos, start_date=hoy - timedelta(days=1))
    assign_position(vencido, pos, start_date=hoy - timedelta(days=30),
                    end_date=hoy - timedelta(days=2))
    assign_position(inactivo, pos, start_date=hoy - timedelta(days=1), is_active=False)
    assign_position(futuro, pos, start_date=hoy + timedelta(days=5))
    assert TeacherService.is_teacher_of(db_session, vigente.id, dept.id)
    assert TeacherService.is_teacher_of(db_session, vigente.id, dept.id, lock=True)
    for u in (vencido, inactivo, futuro):
        assert not TeacherService.is_teacher_of(db_session, u.id, dept.id)


def test_un_puesto_vencido_pero_marcado_activo_no_impide_volver_a_agregar(
        db_session, depto, actor, make_user, make_position, assign_position):
    dept = depto()
    pos = make_position(code=f"{POSITION_PREFIX}{dept.code}")
    hoy = db_now().date()
    u = make_user()
    viejo = assign_position(u, pos, start_date=hoy - timedelta(days=30),
                            end_date=hoy - timedelta(days=2))
    TeacherService.add_existing(db_session, actor.id, dept.id, u.id,
                                academic_degree="Maestro", professional_license="5550012")
    assert viejo.is_active is False
    assert TeacherService.is_teacher_of(db_session, u.id, dept.id)


# ---------------------------------------------------------------------------
# Un solo reloj para la vigencia del puesto (CI run 39696762339, 2026-10-21)
# ---------------------------------------------------------------------------
@pytest.fixture()
def reloj_app_un_dia_atras(db_session, monkeypatch):
    """`db_now()` un día ATRÁS del `CURRENT_DATE` de la BD, a cualquier hora.

    Es lo que pasa en CI: su Postgres corre en UTC, así que de 18:00 a 24:00 de
    Juárez el `CURRENT_DATE` de la BD ya es mañana mientras `db_now()` (APP_TZ)
    sigue en hoy. El puesto nace con el `CURRENT_DATE` de la BD (`default` de
    `UserPosition.start_date`) y `is_teacher_of`/`roster`/el gate lo juzgan con
    ese mismo reloj (`_active_position_filter`); si alta y baja lo juzgaran con
    `db_now()`, el docente recién dado de alta «aún no empieza». Fijarlo aquí
    hace que la prueba falle (o pase) igual a cualquier hora, no solo en la
    ventana nocturna. Devuelve el día de la BD."""
    from sqlalchemy import func, select

    from itcj2.core.utils import timezone

    hoy_bd = db_session.execute(select(func.current_date())).scalar_one()
    monkeypatch.setattr(timezone, "db_now",
                        lambda: datetime.combine(hoy_bd - timedelta(days=1),
                                                 datetime.min.time()).replace(hour=20))
    return hoy_bd


def test_alta_y_baja_juzgan_la_vigencia_con_el_reloj_de_la_bd(db_session, depto, actor,
                                                               reloj_app_un_dia_atras):
    hoy_bd = reloj_app_un_dia_atras
    dept = depto()
    uid = _crear(db_session, actor, dept)["user_id"]
    assert TeacherService.is_teacher_of(db_session, uid, dept.id)

    # Agregarlo otra vez al mismo depto: ya es docente HOY (no un puesto «futuro»).
    with pytest.raises(ValueError) as err:
        TeacherService.add_existing(db_session, actor.id, dept.id, uid,
                                    academic_degree="Maestro", professional_license="5550030")
    assert str(err.value) == ALREADY_TEACHER_MSG

    # Quitarlo: lo encuentra vigente y cierra el puesto con el MISMO día con que
    # nació (nunca un `end_date` anterior a su `start_date`).
    TeacherService.remove_from_department(db_session, actor.id, dept.id, uid)
    link = (db_session.query(UserPosition).join(Position)
            .filter(UserPosition.user_id == uid,
                    Position.code == f"{POSITION_PREFIX}{dept.code}").one())
    assert link.is_active is False
    assert link.start_date == hoy_bd and link.end_date == hoy_bd
    assert not TeacherService.is_teacher_of(db_session, uid, dept.id)


# ---------------------------------------------------------------------------
# Lista del departamento y búsqueda
# ---------------------------------------------------------------------------
def test_roster_estados_y_asignaciones_vigentes(db_session, depto, actor, make_user,
                                                proceso_del_depto, make_synodals):
    dept = depto()
    apellido = f"LISTA{_n()}"
    activo = make_user(first_name="ACTIVO", last_name=apellido)
    activo.last_login = datetime(2026, 9, 1, 10, 0)
    pendiente = make_user(first_name="PENDIENTE", last_name=apellido)
    db_session.flush()
    for u in (activo, pendiente):
        TeacherService.add_existing(db_session, actor.id, dept.id, u.id,
                                    academic_degree="Maestro", professional_license="5550013")
    inactivo = _crear(db_session, actor, dept, first_name="INACTIVO", last_name=apellido)["user_id"]
    db_session.get(User, inactivo).is_active = False
    quitado = _crear(db_session, actor, dept, first_name="QUITADO", last_name=apellido)["user_id"]
    TeacherService.remove_from_department(db_session, actor.id, dept.id, quitado)
    make_synodals(proceso_del_depto(dept), {"president": activo}, assigned_by=actor)
    make_synodals(proceso_del_depto(dept), {"vocal": activo}, assigned_by=actor)
    db_session.flush()

    filas = {r["user_id"]: r for r in TeacherService.roster(db_session, dept.id)}
    assert set(filas) == {activo.id, pendiente.id, inactivo}
    assert filas[activo.id]["account_status"] == "active"
    assert filas[activo.id]["active_assignments"] == 2
    assert filas[pendiente.id]["account_status"] == "pending_first_login"
    assert filas[inactivo]["account_status"] == "inactive"
    assert filas[pendiente.id]["active_assignments"] == 0
    fila = filas[activo.id]
    # Orden natural (nombre(s), paterno, materno), como Sinodales, el
    # expediente y el oficio (hallazgo 16); la LISTA sigue ordenada por apellido.
    assert fila["name"] == f"ACTIVO {apellido}" and fila["email"] == activo.email
    assert (fila["academic_degree"], fila["professional_license"]) == ("Maestro", "5550013")
    assert TeacherService.active_assignment_counts(db_session, [activo.id, pendiente.id]) == {
        activo.id: 2, pendiente.id: 0}
    assert TeacherService.active_assignment_counts(db_session, []) == {}


def test_busqueda_por_correo_usuario_y_nombre(db_session, depto, actor, make_user):
    dept = depto()
    apellido = f"BUSCADO{_n()}"
    correo = _correo("rocio.busca")
    u = make_user(first_name="ROCÍO", last_name=apellido, middle_name="PÉREZ",
                  email=correo, username=f"rbusca{_n()}")
    inactiva = make_user(first_name="ROCIO", last_name=apellido, is_active=False)
    inactiva.last_login = datetime(2025, 1, 1)
    db_session.flush()
    TeacherService.add_existing(db_session, actor.id, dept.id, u.id,
                                academic_degree="Maestra", professional_license="5550014")

    exacto = TeacherService.search_candidates(db_session, correo.upper())
    assert exacto[0]["user_id"] == u.id
    assert exacto[0]["already_in"] == [dept.id]
    assert exacto[0]["has_logged_in"] is False and exacto[0]["is_active"] is True
    assert exacto[0]["is_student"] is False
    assert exacto[0]["academic_degree"] == "Maestra"
    assert [c["user_id"] for c in TeacherService.search_candidates(db_session, u.username)] == [u.id]
    # Por palabras, en cualquier orden y sin acentos.
    ids = [c["user_id"] for c in TeacherService.search_candidates(db_session,
                                                                 f"{apellido.lower()} rocio")]
    assert set(ids) == {u.id, inactiva.id}
    otra = next(c for c in TeacherService.search_candidates(db_session, f"rocio {apellido}")
                if c["user_id"] == inactiva.id)
    assert otra["is_active"] is False and otra["has_logged_in"] is True and otra["already_in"] == []
    assert TeacherService.search_candidates(db_session, "   ") == []
    assert len(TeacherService.search_candidates(db_session, apellido, limit=1)) == 1


def test_el_plegado_de_nombres_es_igual_en_python_y_en_sql(db_session):
    """La coincidencia de nombre (R-B) compara en SQL lo que la búsqueda pliega
    en Python: si divergen, «Pérez» y «PEREZ» dejarían de ser la misma persona."""
    from sqlalchemy import literal

    from itcj2.apps.titulatec.services import teacher_service as ts

    assert len(ts._SQL_ACCENTS) == len(ts._SQL_PLAIN)
    muestra = "  ÁÉÍÓÚ  áéíóú ÑñÜü àÈ âÇ  Pérez   GÓMEZ "
    assert db_session.query(ts._fold_sql(literal(muestra))).scalar() == ts._fold(muestra)
    assert ts._fold(muestra) == "aeiou aeiou nnuu ae ac perez gomez"


def test_busqueda_escapa_comodines(db_session):
    """Un `%` tecleado es un `%` literal, no «todo el personal»."""
    assert TeacherService.search_candidates(db_session, "%") == []


# ---------------------------------------------------------------------------
# Editar perfil
# ---------------------------------------------------------------------------
def test_editar_grado_y_cedula_con_bitacora(db_session, depto, actor, monkeypatch):
    dept = depto()
    uid = _crear(db_session, actor, dept)["user_id"]
    TeacherService.update_profile(db_session, actor.id, dept.id, uid,
                                  academic_degree="Doctor en Física",
                                  professional_license="99887766")
    prof = db_session.get(TeacherProfile, uid)
    assert (prof.academic_degree, prof.professional_license) == ("Doctor en Física", "99887766")
    assert prof.updated_by_id == actor.id and prof.updated_at is not None
    fila = audit_query(db_session).filter_by(action="teacher.profile_updated").one()
    assert fila.before == {"academic_degree": "Maestra en Ciencias",
                           "professional_license": "12345678"}
    assert fila.after == {"academic_degree": "Doctor en Física",
                          "professional_license": "99887766"}

    # Sin cambios: sin fila nueva, pero la transacción se cierra (suelta el
    # FOR UPDATE del perfil) con un commit, no queda abierta.
    real, commits = db_session.commit, []
    monkeypatch.setattr(db_session, "commit", lambda: (commits.append(1), real())[1])
    TeacherService.update_profile(db_session, actor.id, dept.id, uid,
                                  academic_degree="Doctor en Física",
                                  professional_license="99887766")
    assert commits == [1]
    assert audit_query(db_session).filter_by(action="teacher.profile_updated").count() == 1
    with pytest.raises(ValueError):
        TeacherService.update_profile(db_session, actor.id, dept.id, uid, academic_degree="D",
                                      professional_license="99887766")


def test_editar_perfil_desde_un_depto_donde_no_es_docente(db_session, depto, actor):
    dept, otro = depto(name="Depto del docente"), depto(name="Depto ajeno al docente")
    uid = _crear(db_session, actor, dept)["user_id"]
    with pytest.raises(ValueError) as err:
        TeacherService.update_profile(db_session, actor.id, otro.id, uid,
                                      academic_degree="Doctor", professional_license="12345")
    assert str(err.value) == NOT_TEACHER_MSG
    assert db_session.get(TeacherProfile, uid).academic_degree == "Maestra en Ciencias"


def test_editar_perfil_de_quien_no_tiene(db_session, depto, actor, make_user, make_position,
                                         assign_position):
    dept = depto()
    u = make_user()
    with pytest.raises(ValueError) as err:
        TeacherService.update_profile(db_session, actor.id, dept.id, u.id,
                                      academic_degree="Maestro", professional_license="12345")
    assert str(err.value) == NOT_TEACHER_MSG
    # Docente vigente pero sin perfil (puesto dado a mano): tampoco.
    assign_position(u, make_position(code=f"{POSITION_PREFIX}{dept.code}"),
                    start_date=db_now().date() - timedelta(days=1))
    with pytest.raises(ValueError):
        TeacherService.update_profile(db_session, actor.id, dept.id, u.id,
                                      academic_degree="Maestro", professional_license="12345")


# ---------------------------------------------------------------------------
# Reenviar acceso
# ---------------------------------------------------------------------------
def test_reenviar_acceso_solo_sin_primer_acceso(db_session, depto, actor):
    dept = depto()
    uid = _crear(db_session, actor, dept)["user_id"]
    u = db_session.get(User, uid)
    u.password_hash = hash_nip("otra-cosa-789")
    u.must_change_password = False
    db_session.flush()

    TeacherService.reset_access(db_session, actor.id, dept.id, uid)
    assert verify_nip(DEFAULT_PASSWORD, u.password_hash) and u.must_change_password is True
    assert audit_query(db_session).filter_by(action="teacher.access_reset").one().entity_id == uid

    u.last_login = datetime(2026, 10, 1, 8, 0)
    db_session.flush()
    with pytest.raises(ValueError) as err:
        TeacherService.reset_access(db_session, actor.id, dept.id, uid)
    assert str(err.value) == RESET_NOT_ALLOWED_MSG


def test_reenviar_acceso_a_cuenta_inactiva_o_ajena_se_rechaza(db_session, depto, actor, make_user,
                                                              make_student):
    dept, otro = depto(name="Depto reenvio"), depto(name="Depto reenvio ajeno")
    uid = _crear(db_session, actor, dept)["user_id"]
    # Desde un departamento donde no es docente: no.
    with pytest.raises(ValueError) as err:
        TeacherService.reset_access(db_session, actor.id, otro.id, uid)
    assert str(err.value) == NOT_TEACHER_MSG
    db_session.get(User, uid).is_active = False
    db_session.flush()
    with pytest.raises(ValueError) as err:
        TeacherService.reset_access(db_session, actor.id, dept.id, uid)
    assert str(err.value) == RESET_INACTIVE_MSG
    # Una cuenta que no es docente del departamento: nada que restablecer aquí.
    with pytest.raises(ValueError) as err:
        TeacherService.reset_access(db_session, actor.id, dept.id, make_user().id)
    assert str(err.value) == NOT_TEACHER_MSG
    with pytest.raises(ValueError) as err:
        TeacherService.reset_access(db_session, actor.id, dept.id, make_student().id)
    assert str(err.value) == STUDENT_ACCOUNT_MSG


def test_reenviar_acceso_a_una_cuenta_con_privilegios_se_rechaza(
        db_session, depto, actor, cuenta_admin_itcj, patched_session_local, monkeypatch):
    """Misma regla que al agregar: la credencial de una cuenta con privilegios
    no la toca el departamento, ni aunque nunca haya entrado. Y el correo no
    le manda la contraseña temporal aunque su hash ya fuera el de omisión."""
    dept = depto()
    u = cuenta_admin_itcj
    TeacherService.add_existing(db_session, actor.id, dept.id, u.id,
                                academic_degree="Ingeniero", professional_license="5550027")
    antes = _hash_y_epoca(db_session, u)
    with pytest.raises(ValueError) as err:
        TeacherService.reset_access(db_session, actor.id, dept.id, u.id)
    assert str(err.value) == PRIVILEGED_RESET_MSG
    assert _hash_y_epoca(db_session, u) == antes
    assert not audit_query(db_session).filter_by(action="teacher.access_reset").count()

    llamadas = []
    monkeypatch.setattr(email_helper, "deliver_detailed",
                        lambda **kw: llamadas.append(kw) or (True, None))
    u.password_hash = hash_nip(DEFAULT_PASSWORD)
    u.must_change_password = True
    db_session.flush()
    assert TeacherService.send_access_email(u.id) == (False, "cuenta_con_privilegios")
    assert llamadas == []


# ---------------------------------------------------------------------------
# Correo de acceso (RF5) y la contraseña fuera de toda salida
# ---------------------------------------------------------------------------
def test_correo_de_acceso_lleva_usuario_contrasena_temporal_y_liga(
        db_session, depto, actor, patched_session_local, monkeypatch):
    dept = depto()
    correo = _correo()
    uid = _crear(db_session, actor, dept, email=correo)["user_id"]
    enviados = []
    monkeypatch.setattr(email_helper, "_acquire_token", lambda que: "token-de-prueba")
    monkeypatch.setattr(email_helper, "_send",
                        lambda token, subject, html, recipients:
                        enviados.append((subject, html, recipients)) or True)

    assert TeacherService.send_access_email(uid) == (True, None)
    (asunto, html, para), = enviados
    assert para == [correo]
    assert "TitulaTec" in asunto
    assert correo.split("@")[0] in html            # usuario
    assert DEFAULT_PASSWORD in html                # la contraseña temporal SOLO viaja aquí
    assert "/itcj/login" in html
    assert "cambiar" in html.lower()


def test_correo_falla_y_el_alta_persiste(db_session, depto, actor, patched_session_local,
                                         monkeypatch):
    dept = depto()
    correo = _correo()
    llamadas = []
    monkeypatch.setattr(email_helper, "deliver_detailed",
                        lambda **kw: llamadas.append(kw) or (False, "envio"))
    uid = _crear(db_session, actor, dept, email=correo)["user_id"]

    assert TeacherService.send_access_email(uid) == (False, "envio")
    (kw,) = llamadas
    assert kw["to"] == correo and kw["template"] == "teacher_access.html"
    u = db_session.get(User, uid)
    assert u is not None and u.is_active
    assert TeacherService.is_teacher_of(db_session, uid, dept.id)
    # «Reenviar acceso» sigue disponible.
    TeacherService.reset_access(db_session, actor.id, dept.id, uid)
    assert TeacherService.send_access_email(uid) == (False, "envio")


def test_el_correo_no_sale_si_la_contrasena_ya_no_es_la_temporal(
        db_session, depto, actor, patched_session_local, monkeypatch):
    dept = depto()
    uid = _crear(db_session, actor, dept)["user_id"]
    llamadas = []
    monkeypatch.setattr(email_helper, "deliver_detailed",
                        lambda **kw: llamadas.append(kw) or (True, None))
    u = db_session.get(User, uid)
    u.password_hash = hash_nip("ya-la-cambio-1")
    db_session.flush()
    assert TeacherService.send_access_email(uid) == (False, "sin_credencial_temporal")
    u.password_hash = hash_nip(DEFAULT_PASSWORD)
    u.is_active = False
    db_session.flush()
    assert TeacherService.send_access_email(uid) == (False, "cuenta_inactiva")
    assert TeacherService.send_access_email(9_999_999_999) == (False, "sin_cuenta")
    assert llamadas == []


def test_la_contrasena_no_aparece_en_bitacora_eventos_ni_log(
        db_session, depto, actor, make_user, patched_session_local, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="itcj2")
    monkeypatch.setattr(email_helper, "deliver_detailed", lambda **kw: (False, "envio"))
    a, b = depto(name="Depto log A"), depto(name="Depto log B")
    uid = _crear(db_session, actor, a)["user_id"]
    TeacherService.add_existing(db_session, actor.id, b.id, uid,
                                academic_degree="Maestro", professional_license="5550015")
    sin_acceso = make_user()           # activa, sin privilegios, nunca entró: se restablece
    TeacherService.add_existing(db_session, actor.id, a.id, sin_acceso.id,
                                academic_degree="Maestro", professional_license="5550016")
    TeacherService.reset_access(db_session, actor.id, a.id, uid)
    TeacherService.update_profile(db_session, actor.id, a.id, uid, academic_degree="Doctor",
                                  professional_license="5550017")
    TeacherService.send_access_email(uid)
    db_session.flush()

    volcado = _volcado_de_bitacora(db_session)
    acciones = {f.action for f in audit_query(db_session).all()}
    assert {"teacher.created", "teacher.added", "teacher.access_reset",
            "teacher.profile_updated"} <= acciones
    assert DEFAULT_PASSWORD not in volcado
    assert db_session.get(User, uid).password_hash not in volcado
    assert DEFAULT_PASSWORD not in caplog.text


# ---------------------------------------------------------------------------
# R-G: con el corte <= fase 4 el catálogo es inerte
# ---------------------------------------------------------------------------
def test_con_el_corte_en_3_ninguna_accion_escribe(db_session, depto, actor, make_user,
                                                 patched_session_local, monkeypatch):
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    dept = depto()
    uid = _crear(db_session, actor, dept)["user_id"]
    otro = make_user()
    llamadas = []
    monkeypatch.setattr(email_helper, "deliver_detailed",
                        lambda **kw: llamadas.append(kw) or (True, None))
    monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: 3))
    assert TeacherService.operable(db_session) is False

    acciones = [
        lambda: _crear(db_session, actor, dept),
        lambda: TeacherService.add_existing(db_session, actor.id, dept.id, otro.id,
                                            academic_degree="Maestro",
                                            professional_license="5550018"),
        lambda: TeacherService.update_profile(db_session, actor.id, dept.id, uid,
                                              academic_degree="Doctor",
                                              professional_license="5550019"),
        lambda: TeacherService.remove_from_department(db_session, actor.id, dept.id, uid),
        lambda: TeacherService.reset_access(db_session, actor.id, dept.id, uid),
    ]
    for accion in acciones:
        with pytest.raises(ValueError) as err:
            accion()
        assert str(err.value) == INERT_MSG
    assert TeacherService.send_access_email(uid) == (False, "inerte")
    assert llamadas == []
    assert TeacherService.is_teacher_of(db_session, uid, dept.id)
    assert not TeacherService.is_teacher_of(db_session, otro.id, dept.id)


def test_con_el_corte_en_4_tambien_es_inerte_y_en_5_opera(db_session, monkeypatch):
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: 4))
    assert TeacherService.operable(db_session) is False
    monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: 5))
    assert TeacherService.operable(db_session) is True
