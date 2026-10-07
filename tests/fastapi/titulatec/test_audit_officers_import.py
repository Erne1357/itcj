"""Bitácora (Task 6): encargados y alumnos importados dejan acción explícita.

Las cuentas, los puestos y las carreras del encargado viven en tablas de CORE
(`core_users`, `core_user_positions`, `core_program_positions`): la red ORM de
titulatec no las ve, así que estas filas `source='action'` son el único rastro de
quién reactivó una cuenta (con restablecimiento de contraseña), quién dio de alta
a un encargado o quién otorgó el rol de egresado.

Regla D9: jamás una contraseña, un hash o un NIP en la bitácora. Se prueba
recorriendo TODA la fila serializada.
"""
from __future__ import annotations

import json

import pytest

from tests.fastapi.titulatec.conftest import OFFICER_PERMS, ROLE_OFFICER

from itcj2.apps.titulatec.models.audit_log import TitulatecAuditLog
from itcj2.apps.titulatec.services.import_service import ImportService
from itcj2.apps.titulatec.services.officer_service import OfficerService


def _acciones(db, action, **filtros):
    db.flush()
    return (db.query(TitulatecAuditLog)
            .filter_by(source="action", action=action, **filtros)
            .order_by(TitulatecAuditLog.id).all())


def _volcado(row) -> str:
    """Toda la fila como texto, para barrer secretos."""
    return json.dumps({
        "subject": row.subject_label, "reason": row.reason, "before": row.before,
        "after": row.after, "payload": row.payload,
    }, default=str, ensure_ascii=False)


def _fila(control, name="ALUMNA INVENTADA", email=None):
    return {"control_number": control, "full_name": name,
            "email": email, "program_id": None, "modality_id": None}


@pytest.fixture()
def depto(make_department, make_position, make_user, make_role, assign_position,
          titulatec_app):
    """Departamento con dos personas (una inactiva) y el rol de encargado."""
    d = make_department(name="Depto auditoría (ficticio)")
    base = make_position(department=d)
    activa = make_user(first_name="ACTIVA")
    inactiva = make_user(first_name="INACTIVA", is_active=False)
    otra = make_user(first_name="OTRA")
    for u in (activa, inactiva, otra):
        assign_position(u, base)
    make_role(ROLE_OFFICER, OFFICER_PERMS)
    return {"dept": d, "activa": activa, "inactiva": inactiva, "otra": otra}


# --------------------------------------------------------------------------
# Encargados
# --------------------------------------------------------------------------
def test_activar_cuentas_registra_ids_y_nunca_la_contrasena(db_session, depto):
    inactiva = depto["inactiva"]
    tocados = OfficerService.activate_users(
        db_session, {inactiva.id, depto["activa"].id},
        department_id=depto["dept"].id, actor_id=depto["otra"].id)
    assert [t["id"] for t in tocados] == [inactiva.id]

    filas = _acciones(db_session, "officer.account_reactivated")
    assert len(filas) == 1
    fila = filas[0]
    assert fila.actor_id == depto["otra"].id
    assert fila.payload["user_ids"] == [inactiva.id]
    assert fila.payload["credential_reset"] is True

    # D9: ni el hash guardado en la cuenta ni la contraseña por omisión.
    from itcj2.core.utils.security import DEFAULT_PASSWORD
    db_session.refresh(inactiva)
    texto = _volcado(fila)
    assert DEFAULT_PASSWORD not in texto
    assert inactiva.password_hash not in texto
    assert "$" not in texto.replace("$$", "")  # ningún hash tipo scrypt/bcrypt


def test_activar_cuentas_ya_activas_no_deja_fila(db_session, depto):
    OfficerService.activate_users(
        db_session, {depto["activa"].id}, department_id=depto["dept"].id)
    assert _acciones(db_session, "officer.account_reactivated") == []


def test_crear_encargado_deja_una_sola_fila_con_lo_que_quedo(db_session, depto,
                                                              make_program):
    p1, p2 = make_program(name="Carrera A"), make_program(name="Carrera B")
    pos_id = OfficerService.create_officer(
        db_session, department_id=depto["dept"].id, assigned_role=ROLE_OFFICER,
        name="Encargado de prueba", program_ids={p1.id, p2.id},
        user_ids={depto["activa"].id})

    creadas = _acciones(db_session, "officer.created")
    assert len(creadas) == 1
    fila = creadas[0]
    assert fila.entity_type == "position" and fila.entity_id == pos_id
    assert fila.after == {"user_ids": [depto["activa"].id],
                          "program_ids": sorted([p1.id, p2.id])}
    assert fila.payload["assigned_role"] == ROLE_OFFICER
    # El alta no debe duplicarse como «cambió las carreras».
    assert _acciones(db_session, "officer.programs_changed") == []


def test_set_users_registra_antes_y_despues(db_session, depto):
    pos_id = OfficerService.create_officer(
        db_session, department_id=depto["dept"].id, assigned_role=ROLE_OFFICER,
        name="Enc", program_ids=set(), user_ids={depto["activa"].id})
    OfficerService.set_users(
        db_session, pos_id, {depto["otra"].id},
        department_id=depto["dept"].id, assigned_role=ROLE_OFFICER)

    fila = _acciones(db_session, "officer.users_changed")[0]
    assert fila.before == {"user_ids": [depto["activa"].id]}
    assert fila.after == {"user_ids": [depto["otra"].id]}
    assert fila.payload["added"] == [depto["otra"].id]
    assert fila.payload["removed"] == [depto["activa"].id]


def test_set_users_sin_cambios_no_deja_fila(db_session, depto):
    pos_id = OfficerService.create_officer(
        db_session, department_id=depto["dept"].id, assigned_role=ROLE_OFFICER,
        name="Enc", program_ids=set(), user_ids={depto["activa"].id})
    OfficerService.set_users(
        db_session, pos_id, {depto["activa"].id},
        department_id=depto["dept"].id, assigned_role=ROLE_OFFICER)
    assert _acciones(db_session, "officer.users_changed") == []


def test_set_programs_registra_antes_y_despues(db_session, depto, make_program):
    p1, p2 = make_program(name="Carrera A"), make_program(name="Carrera B")
    pos_id = OfficerService.create_officer(
        db_session, department_id=depto["dept"].id, assigned_role=ROLE_OFFICER,
        name="Enc", program_ids={p1.id}, user_ids=set())
    OfficerService.set_programs(db_session, pos_id, {p2.id})

    fila = _acciones(db_session, "officer.programs_changed")[0]
    assert fila.before == {"program_ids": [p1.id]}
    assert fila.after == {"program_ids": [p2.id]}

    # Mismo conjunto otra vez: sin fila nueva.
    OfficerService.set_programs(db_session, pos_id, {p2.id})
    assert len(_acciones(db_session, "officer.programs_changed")) == 1


def test_baja_del_encargado_registra_a_quienes_lo_ocupaban(db_session, depto):
    pos_id = OfficerService.create_officer(
        db_session, department_id=depto["dept"].id, assigned_role=ROLE_OFFICER,
        name="Enc baja", program_ids=set(), user_ids={depto["activa"].id})
    OfficerService.deactivate_officer(db_session, pos_id)

    fila = _acciones(db_session, "officer.deactivated")[0]
    assert fila.entity_id == pos_id
    assert fila.before == {"user_ids": [depto["activa"].id]}
    assert fila.subject_label == "Enc baja"


def test_baja_de_puesto_inexistente_no_deja_fila(db_session, depto):
    OfficerService.deactivate_officer(db_session, 987654321)
    assert _acciones(db_session, "officer.deactivated") == []


# --------------------------------------------------------------------------
# Importación
# --------------------------------------------------------------------------
def test_import_rows_deja_un_resumen_por_llamada(db_session, titulatec_app,
                                                  make_cohort, make_user):
    cohort = make_cohort()
    existente = make_user(control_number="99100002")
    ImportService.import_rows(
        db_session, cohort,
        [_fila("99100001"), _fila(existente.control_number), _fila("")],
        source="csv")

    filas = _acciones(db_session, "import.students_committed")
    assert len(filas) == 1
    fila = filas[0]
    assert fila.entity_id == cohort.id
    assert fila.payload["source"] == "csv"
    assert fila.payload["created_users"] == 1
    assert fila.payload["merged_users"] == 1
    assert fila.payload["skipped"] == 1
    assert fila.payload["processes_created"] == 2


def test_import_rows_con_commit_false_registra_en_la_misma_sesion(
        db_session, titulatec_app, make_cohort):
    ImportService.import_rows(db_session, make_cohort(), [_fila("99100003")],
                              commit=False, source="enrollment")
    fila = _acciones(db_session, "import.students_committed")[0]
    assert fila.payload["source"] == "enrollment"


def test_import_rows_sin_filas_validas_no_deja_resumen(db_session, titulatec_app,
                                                        make_cohort):
    ImportService.import_rows(db_session, make_cohort(), [])
    assert _acciones(db_session, "import.students_committed") == []


def test_reparacion_de_credencial_no_filtra_el_hash_ni_el_control(
        db_session, titulatec_app, make_cohort, make_user):
    cohort = make_cohort()
    user = make_user(control_number="99100004")
    assert user.password_hash is None
    ImportService.import_rows(db_session, cohort, [_fila("99100004")])

    fila = _acciones(db_session, "import.credential_set", entity_id=user.id)[0]
    assert fila.payload["bulk"] is False
    db_session.refresh(user)
    assert user.password_hash and user.password_hash not in _volcado(fila)
    # La contraseña inicial ES el número de control: no se declara cómo se arma.
    assert "hash" not in _volcado(fila).lower()


def test_correo_nuevo_de_cuenta_existente_registra_antes_y_despues(
        db_session, titulatec_app, make_cohort, make_user):
    user = make_user(control_number="99100005")
    user.email = None
    db_session.flush()
    ImportService.import_rows(
        db_session, make_cohort(),
        [_fila("99100005", email="nuevo@example.invalid")])

    fila = _acciones(db_session, "import.user_email_changed")[0]
    assert fila.before == {"email": None}
    assert fila.after == {"email": "nuevo@example.invalid"}
    assert fila.entity_id == user.id


def test_roles_de_egresado_registran_otorgados_y_revocados(
        db_session, titulatec_app, make_cohort, make_user):
    from itcj2.core.models.app import App
    from itcj2.core.models.role import Role

    for key in ("itcj", "agendatec"):
        if db_session.query(App).filter_by(key=key).first() is None:
            db_session.add(App(key=key, name=key, is_active=True,
                               visible_to_students=True, mobile_enabled=True))
    for name in ("graduate", "student"):
        if db_session.query(Role).filter_by(name=name).first() is None:
            db_session.add(Role(name=name))
    db_session.flush()

    user = make_user(control_number="99100006")
    ImportService.import_rows(db_session, make_cohort(), [_fila("99100006")])

    fila = _acciones(db_session, "import.roles_synced", entity_id=user.id)[0]
    assert fila.payload["role"] == "graduate"
    assert fila.payload["granted"] == ["itcj", "titulatec"]
    assert fila.payload["revoked"] == []


def test_reparar_credenciales_en_lote_marca_bulk(db_session, titulatec_app,
                                                  make_cohort, make_user,
                                                  make_process):
    cohort = make_cohort()
    user = make_user(control_number="99100007")
    make_process(user, cohort=cohort)
    assert user.password_hash is None

    n = ImportService.repair_missing_credentials(db_session, cohort_id=cohort.id)
    assert n == 1
    fila = _acciones(db_session, "import.credential_set", entity_id=user.id)[0]
    assert fila.payload["bulk"] is True
    assert fila.payload["cohort_id"] == cohort.id
    db_session.refresh(user)
    assert user.password_hash not in _volcado(fila)


def test_guardar_mapeo_registra_solo_con_sesion(db_session, tmp_path, monkeypatch):
    import itcj2.apps.titulatec.services.import_service as mod
    monkeypatch.setattr(mod, "_mapping_store", lambda: tmp_path / "_mapping.json")

    ImportService.save_mapping({"control_number": "No. control"})
    assert _acciones(db_session, "import.mapping_saved") == []

    ImportService.save_mapping({"control_number": "No. control"}, db=db_session)
    fila = _acciones(db_session, "import.mapping_saved")[0]
    assert fila.after == {"mapping": {"control_number": "No. control"}}
