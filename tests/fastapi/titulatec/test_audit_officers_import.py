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
from tests.fastapi.titulatec.conftest import audit_query
from tests.fastapi.titulatec.test_import_scale import (  # noqa: F401  (fixtures)
    import_ctx, preserve_imports_dir)

# La bitácora de dev ya trae filas reales: solo las de ESTA prueba (`id > marca`).
pytestmark = pytest.mark.usefixtures("audit_mark")


@pytest.fixture(autouse=True)
def _sin_autoflush_como_produccion(db_session):
    """La sesión de producción NO autoflushea (`itcj2/database.py`,
    `sessionmaker(autoflush=False)`); la del arnés sí. Con autoflush, una
    consulta del service veía filas que solo había hecho `db.add` y la prueba
    pasaba donde producción registraba `program_ids: []` (revisión final I1).
    Las fábricas del conftest flushean a mano, así que no dependen de esto."""
    previo = db_session.autoflush
    db_session.autoflush = False
    yield
    db_session.autoflush = previo


def _acciones(db, action, **filtros):
    db.flush()
    return (audit_query(db)
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
                              commit=False, source="manual")
    fila = _acciones(db_session, "import.students_committed")[0]
    assert fila.payload["source"] == "manual"


@pytest.fixture()
def roles_egresado(db_session):
    """Apps y roles que `_sync_graduate_roles` necesita (idempotente)."""
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


@pytest.mark.parametrize("source,control", [("enrollment_request", "99100021"),
                                            ("self_service", "99100022")])
def test_altas_por_solicitud_no_dejan_resumen_de_importacion(
        db_session, titulatec_app, make_cohort, source, control):
    """La cuenta que crea una solicitud aprobada (`_create_account`,
    `enrollment_request`) y la activación por liga (`_convert`, `self_service`)
    ya dejan su rastro (`enrollment.approved`, espejo de
    `enrollment_self_service`). Un «Importó alumnos a una convocatoria» por cada
    alumno que abre su liga, firmado por «Público», sería falso e imborrable
    (revisión final I4): el resumen es solo de CSV y alta manual."""
    ImportService.import_rows(db_session, make_cohort(), [_fila(control)],
                              commit=False, source=source)
    assert _acciones(db_session, "import.students_committed") == []


def test_roles_synced_solo_para_cuentas_que_ya_existian(
        db_session, titulatec_app, make_cohort, make_user, roles_egresado):
    """Un CSV de 300 cuentas nuevas no deja 300 «Sincronizó los roles»: darle
    el rol a una cuenta que nace en el lote ES el alta, y sus ids van al
    resumen. Quitarle `student`/darle `graduate` a una cuenta que YA existía sí
    es un cambio de seguridad y lleva su fila."""
    from itcj2.core.models.user import User

    existente = make_user(control_number="99100024")
    ImportService.import_rows(db_session, make_cohort(),
                              [_fila("99100023"), _fila("99100024")], source="csv")
    nueva = db_session.query(User).filter_by(control_number="99100023").one()

    roles = _acciones(db_session, "import.roles_synced")
    assert [f.entity_id for f in roles] == [existente.id]
    (resumen,) = _acciones(db_session, "import.students_committed")
    assert resumen.payload["created_users"] == 1
    assert resumen.payload["created_user_ids"] == [nueva.id]


def test_cuenta_recien_creada_por_la_solicitud_no_deja_roles_synced(
        db_session, titulatec_app, make_cohort, make_user, roles_egresado):
    """`_create_account` crea la cuenta y, en la MISMA transacción, llama a
    `import_rows(source="enrollment_request")`: para la bitácora es una cuenta
    nueva (su rastro es `enrollment.approved`), no un cambio de roles."""
    user = make_user(control_number="99100025")
    ImportService.import_rows(db_session, make_cohort(), [_fila("99100025")],
                              commit=False, source="enrollment_request",
                              repair_credentials=False)
    assert _acciones(db_session, "import.roles_synced", entity_id=user.id) == []


def test_activacion_de_una_cuenta_existente_si_registra_sus_roles(
        db_session, titulatec_app, make_cohort, make_user, roles_egresado):
    """`_convert` (liga de una cuenta que YA existía, `self_service`): quitarle
    `student` en agendatec es lo que le importa a seguridad."""
    user = make_user(control_number="99100026")
    ImportService.import_rows(db_session, make_cohort(), [_fila("99100026")],
                              commit=False, source="self_service",
                              repair_credentials=False)
    (fila,) = _acciones(db_session, "import.roles_synced", entity_id=user.id)
    assert fila.payload["source"] == "self_service"
    assert fila.payload["granted"] == ["itcj", "titulatec"]


def test_import_rows_sin_filas_validas_no_deja_resumen(db_session, titulatec_app,
                                                        make_cohort):
    ImportService.import_rows(db_session, make_cohort(), [])
    assert _acciones(db_session, "import.students_committed") == []


def test_reparacion_de_credencial_no_filtra_el_hash(
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


# --------------------------------------------------------------------------
# Fallos a medias (positions_service commitea por persona)
# --------------------------------------------------------------------------
def _falla_en_la_segunda(monkeypatch):
    """`assign_user_to_position` real la 1.ª vez; ValueError la 2.ª."""
    from itcj2.apps.titulatec.services import officer_service as mod
    real = mod.positions_service.assign_user_to_position
    llamadas = {"n": 0}

    def _asigna(db, uid, pid, *a, **k):
        llamadas["n"] += 1
        if llamadas["n"] == 2:
            raise ValueError("falla simulada")
        return real(db, uid, pid, *a, **k)

    monkeypatch.setattr(mod.positions_service, "assign_user_to_position", _asigna)


def test_set_users_con_fallo_a_medias_registra_lo_que_quedo(
        db_session, depto, monkeypatch):
    a, b, c = depto["activa"], depto["otra"], depto["inactiva"]
    pos_id = OfficerService.create_officer(
        db_session, department_id=depto["dept"].id, assigned_role=ROLE_OFFICER,
        name="Enc", program_ids=set(), user_ids=set())
    _falla_en_la_segunda(monkeypatch)

    with pytest.raises(ValueError, match="falla simulada"):
        OfficerService.set_users(
            db_session, pos_id, {a.id, b.id, c.id},
            department_id=depto["dept"].id, assigned_role=ROLE_OFFICER)

    fila = _acciones(db_session, "officer.users_changed")[0]
    persistidos = OfficerService._active_user_ids(db_session, pos_id)
    assert len(persistidos) == 1  # solo la primera asignación alcanzó a persistir
    assert fila.after == {"user_ids": sorted(persistidos)}
    assert fila.payload["partial"] is True
    assert fila.payload["error"] == "ValueError"
    assert len(fila.payload["requested"]) == 3


def test_create_officer_con_fallo_a_medias_registra_lo_que_quedo(
        db_session, depto, monkeypatch):
    _falla_en_la_segunda(monkeypatch)
    with pytest.raises(ValueError, match="falla simulada"):
        OfficerService.create_officer(
            db_session, department_id=depto["dept"].id, assigned_role=ROLE_OFFICER,
            name="Enc parcial", program_ids=set(),
            user_ids={depto["activa"].id, depto["otra"].id})

    fila = _acciones(db_session, "officer.created")[0]
    assert fila.payload["partial"] is True and fila.payload["error"] == "ValueError"
    assert len(fila.after["user_ids"]) == 1  # no los 2 solicitados
    assert fila.subject_label == "Enc parcial"
    # Lo que se PIDIÓ, junto a lo que quedó (como `set_users`).
    assert fila.payload["requested"] == {
        "user_ids": sorted([depto["activa"].id, depto["otra"].id]),
        "program_ids": []}


def test_create_officer_con_carrera_invalida_cae_en_el_camino_parcial(
        db_session, depto):
    """Una carrera que no existe truena en el `flush` de las carreras, DENTRO
    del `try`: el puesto y las personas ya los commiteó `positions_service`, así
    que la fila del alta se escribe igual, marcada `partial`, con lo que quedó y
    lo que se pidió (antes el error salía en el `commit` final y la fila se
    perdía)."""
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        OfficerService.create_officer(
            db_session, department_id=depto["dept"].id, assigned_role=ROLE_OFFICER,
            name="Enc carrera invalida", program_ids={987654321},
            user_ids={depto["activa"].id})

    (fila,) = _acciones(db_session, "officer.created",
                        subject_label="Enc carrera invalida")
    assert fila.payload["partial"] is True
    assert fila.payload["error"] == "IntegrityError"
    assert fila.after == {"user_ids": [depto["activa"].id], "program_ids": []}
    assert fila.payload["requested"] == {"user_ids": [depto["activa"].id],
                                         "program_ids": [987654321]}


# --------------------------------------------------------------------------
# Ruta real del asistente de importación
# --------------------------------------------------------------------------
def test_ruta_import_commit_registra_el_mapeo_guardado(client_as, db_session,
                                                       import_ctx):
    from tests.fastapi.titulatec.test_import_scale import (
        _upload, csv_bytes, post_form, serialize_form)

    cohort = import_ctx["cohort"]
    client = client_as(import_ctx["head"])
    resp = _upload(client, cohort.id, csv_bytes(3))
    assert resp.status_code == 200
    resp = post_form(
        client, "/titulatec/admin/cohorts/{}/import/commit".format(cohort.id),
        serialize_form(resp.text))
    assert resp.status_code == 200, resp.text[:300]

    filas = _acciones(db_session, "import.mapping_saved")
    assert len(filas) == 1
    assert filas[0].actor_id == import_ctx["head"].id
    assert "control_number" in filas[0].after["mapping"]
