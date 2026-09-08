"""`StudentProfileService`: la fila PEREZOSA de `core_student_profile` (spec §3.1).

Los tres metodos del contrato §2 son `@staticmethod`, reciben `db` como primer
parametro y NINGUNO hace commit: T20 (`_convert`), T21 (`confirm_contact`) y T22
(`approve`) los llaman DENTRO de su propia transaccion y commitean ellos. Un
commit aqui partiria esa transaccion a la mitad.

Por que el «no commitea» se vigila con un espia y no mirando `db.dirty`/`db.new`:
el `flush()` que hacen los tres metodos ya vacia esas dos colecciones, y bajo el
`join_transaction_mode="create_savepoint"` del conftest un `commit()` de verdad
tampoco se nota en los datos (la transaccion externa se deshace igual al final).
Lo unico que prueba el invariante es contar las llamadas.

Este archivo se escribe ANTES de que exista la migracion: entre el Step 7 y el
Step 19 falla con `UndefinedTable`, y no pasa a verde hasta el Step 20.
"""
from __future__ import annotations

import uuid


def _control() -> str:
    return f"99{uuid.uuid4().hex[:6]}"


def test_get_or_create_es_idempotente(db_session, make_user):
    """Dos llamadas, una sola fila: el servicio no duplica el perfil."""
    from itcj2.core.models import StudentProfile
    from itcj2.core.services.student_profile_service import StudentProfileService

    user = make_user(control_number=_control())

    primero = StudentProfileService.get_or_create(db_session, user.id)
    segundo = StudentProfileService.get_or_create(db_session, user.id)

    assert primero is segundo
    assert primero.user_id == user.id
    assert db_session.query(StudentProfile).filter_by(user_id=user.id).count() == 1


def test_set_fields_crea_la_fila_perezosa_y_no_toca_core_users_email(
        db_session, make_user, make_program):
    """D12: el correo PERSONAL vive en el perfil; `core_users.email` no se toca.

    Y D17: escribir el correo personal NO lo da por verificado.
    """
    from itcj2.core.models import StudentProfile
    from itcj2.core.services.student_profile_service import StudentProfileService

    user = make_user(control_number=_control())
    correo_institucional = user.email
    prog = make_program("ING. EN SISTEMAS (PRUEBA SERVICIO PERFIL)")

    # La fila no existe todavia: la primera escritura es la que la crea (§3.1).
    assert db_session.get(StudentProfile, user.id) is None

    row = StudentProfileService.set_fields(
        db_session, user.id,
        contact_email="egresado.personal@example.invalid",
        phone="6561234567",
        has_efirma=True,
        program_id=prog.id,
        program_text="ING. EN SISTEMAS COMPUTACIONALES",
    )

    assert row.contact_email == "egresado.personal@example.invalid"
    assert row.phone == "6561234567"
    assert row.has_efirma is True
    assert row.program_id == prog.id
    assert row.contact_email_verified_at is None          # D17
    assert user.email == correo_institucional             # D12
    assert db_session.get(StudentProfile, user.id) is not None


def test_mark_contact_verified_sella_la_fecha(db_session, make_user):
    """Solo la liga de confirmacion pone `contact_email_verified_at` (D17)."""
    from itcj2.core.services.student_profile_service import StudentProfileService

    user = make_user(control_number=_control())
    row = StudentProfileService.set_fields(
        db_session, user.id, contact_email="egresado.personal@example.invalid")
    assert row.contact_email_verified_at is None

    sellado = StudentProfileService.mark_contact_verified(db_session, user.id)

    assert sellado.user_id == row.user_id
    assert sellado.contact_email_verified_at is not None


def test_ninguno_de_los_tres_metodos_commitea(db_session, make_user, monkeypatch):
    """El commit es del LLAMADOR (T20/T21/T22), nunca del servicio."""
    from itcj2.core.services.student_profile_service import StudentProfileService

    user = make_user(control_number=_control())
    commits = []
    # Atributo de INSTANCIA: tapa el metodo de la clase solo en esta sesion, y
    # `monkeypatch` lo retira al terminar la prueba.
    monkeypatch.setattr(db_session, "commit", lambda *a, **k: commits.append(1))

    StudentProfileService.get_or_create(db_session, user.id)
    StudentProfileService.set_fields(db_session, user.id, phone="6560000000")
    StudentProfileService.mark_contact_verified(db_session, user.id)

    assert commits == [], (
        "alguno de los tres metodos llamo a db.commit(): eso parte a la mitad la "
        "transaccion de T20 `_convert`, T21 `confirm_contact` y T22 `approve`"
    )
