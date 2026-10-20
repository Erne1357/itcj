"""Credencial inicial de los alumnos dados de alta por el importador de CSV.

BLOQUEADOR: `ImportService.import_rows` creaba el `User` sin `password_hash`, y
`auth_service.authenticate` (`core/services/auth_service.py:25`) rechaza el login
cuando ese campo es NULL. Peor: el reset del core esta PROHIBIDO para quien tiene
`control_number` (`core/api/users_admin.py:427`), asi que era un callejon sin
salida: 34 alumnos sembrados, 34 imposibilitados de entrar.

La politica correcta ya existia, pero solo en el alta manual
(`pages/admin.py::_add_student`): `hash_nip(control_number)` + `must_change_password`.
Estos tests la fijan como contrato del importador, que es el camino de alta masivo.
"""
from __future__ import annotations

from itcj2.apps.titulatec.services.import_service import ImportService
from itcj2.core.utils.security import hash_nip, verify_nip


def _row(control, name="ALUMNA INVENTADA", **extra):
    row = {"control_number": control, "full_name": name,
           "email": None, "program_id": None, "modality_id": None}
    row.update(extra)
    return row


def test_import_rows_deja_credencial_inicial_al_usuario_nuevo(
    db_session, titulatec_app, make_cohort,
):
    """Un alumno recien importado puede iniciar sesion con su numero de control."""
    from itcj2.core.models.user import User

    cohort = make_cohort()
    control = "99100001"

    summary = ImportService.import_rows(db_session, cohort, [_row(control)])

    assert summary["created_users"] == 1
    user = db_session.query(User).filter_by(control_number=control).one()
    assert user.password_hash is not None, (
        "el importador dejo password_hash NULL: auth_service rechaza el login"
    )
    assert verify_nip(control, user.password_hash), (
        "la credencial inicial debe ser el numero de control, igual que en el alta manual"
    )
    assert user.must_change_password is True


def test_import_rows_no_sobreescribe_la_password_de_un_usuario_existente(
    db_session, titulatec_app, make_cohort, make_user,
):
    """Merge por control_number: al que ya tenia password no se le toca."""
    control = "99100002"
    previo = make_user(control_number=control, username=control,
                       first_name="ALUMNO", last_name="PREEXISTENTE")
    previo.password_hash = hash_nip("una-password-que-el-alumno-ya-cambio")
    previo.must_change_password = False
    db_session.flush()
    hash_original = previo.password_hash

    summary = ImportService.import_rows(db_session, make_cohort(), [_row(control)])

    assert summary["matched_users"] == 1
    db_session.refresh(previo)
    assert previo.password_hash == hash_original
    assert previo.must_change_password is False


def test_import_rows_repara_al_usuario_existente_que_quedo_sin_hash(
    db_session, titulatec_app, make_cohort, make_user,
):
    """Auto-reparacion: re-importar a un alumno con password_hash NULL lo desbloquea.

    Es el caso de los 34 alumnos ya sembrados por el importador roto. NULL no es
    una password: no hay nada que sobreescribir, solo un usuario que no puede entrar.
    """
    control = "99100003"
    roto = make_user(control_number=control, username=control,
                     first_name="ALUMNA", last_name="SINHASH")
    assert roto.password_hash is None

    ImportService.import_rows(db_session, make_cohort(), [_row(control)])

    db_session.refresh(roto)
    assert roto.password_hash is not None
    assert verify_nip(control, roto.password_hash)
    assert roto.must_change_password is True


# ---------------------------------------------------------------------------
# Reparacion de los alumnos ya sembrados por el importador roto
# ---------------------------------------------------------------------------
def test_repair_missing_credentials_solo_toca_alumnos_de_titulatec_sin_hash(
    db_session, make_cohort, make_program, make_user, make_process,
):
    """Los 34 alumnos ya sembrados no van a re-importarse: se reparan aqui.

    El barrido esta acotado a quien tiene proceso en titulatec y `control_number`:
    ni un usuario de staff sin hash (que autentica por `username` y puede ser una
    cuenta deliberadamente sin contrasena) ni un alumno que SI tiene la suya.
    """
    cohort = make_cohort()
    program = make_program("Ingenieria Ficticia A")

    roto = make_user(control_number="99100011", username="99100011",
                     first_name="ALUMNA", last_name="ROTA")
    make_process(roto, cohort=cohort, program=program)

    sano = make_user(control_number="99100012", username="99100012",
                     first_name="ALUMNO", last_name="SANO")
    sano.password_hash = hash_nip("su-password-real")
    make_process(sano, cohort=cohort, program=program)

    ajeno = make_user(first_name="STAFF", last_name="SINPROCESO")  # sin control_number
    db_session.flush()
    hash_sano = sano.password_hash

    # `cohort_id` acota el barrido a los datos DE ESTE test: sin el, cuenta
    # tambien los alumnos rotos que ya viven en la BD de dev (hoy 34).
    n = ImportService.repair_missing_credentials(db_session, cohort_id=cohort.id)

    assert n == 1
    db_session.refresh(roto)
    db_session.refresh(sano)
    db_session.refresh(ajeno)
    assert verify_nip("99100011", roto.password_hash)
    assert roto.must_change_password is True
    assert sano.password_hash == hash_sano
    assert ajeno.password_hash is None


def test_repair_missing_credentials_es_idempotente(
    db_session, make_cohort, make_program, make_user, make_process,
):
    """Segunda corrida: 0 reparados y el hash de la primera intacto."""
    cohort = make_cohort()
    roto = make_user(control_number="99100013", username="99100013",
                     first_name="ALUMNA", last_name="ROTA")
    make_process(roto, cohort=cohort, program=make_program("Ingenieria Ficticia A"))

    assert ImportService.repair_missing_credentials(db_session, cohort_id=cohort.id) == 1
    db_session.refresh(roto)
    primero = roto.password_hash

    assert ImportService.repair_missing_credentials(db_session, cohort_id=cohort.id) == 0
    db_session.refresh(roto)
    assert roto.password_hash == primero
