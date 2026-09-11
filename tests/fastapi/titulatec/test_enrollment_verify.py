"""Verificación de la liga de inscripción y conversión a proceso (§6.9).

`import_rows` HACE COMMIT POR SU CUENTA (`import_service.py:543`), así que todo
lo que pueda invalidar la conversión se revisa ANTES de llamarlo, y lo que se
comprueba DESPUÉS es la existencia del proceso, nunca un contador.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta


def _solo_esta_convocatoria(db_session, cohort):
    """Deja `cohort` como la ÚNICA abierta (ver test_enrollment_public.py)."""
    from itcj2.apps.titulatec.models import Cohort
    (db_session.query(Cohort)
     .filter(Cohort.id != cohort.id)
     .update({Cohort.status: "closed"}, synchronize_session=False))
    db_session.flush()


def _make_req(db_session, cohort, *, control, kind, status="unverified", **kw):
    """Solicitud + su token en claro. Devuelve `(req, token)`.

    Se construye a mano en vez de llamar a `create()` para que la prueba tenga el
    texto claro del token sin depender de Redis.
    """
    from itcj2.apps.titulatec.models import EnrollmentRequest
    from itcj2.apps.titulatec.services.enrollment_request_service import VERIFY_TTL_HOURS

    token = secrets.token_urlsafe(32)
    row = EnrollmentRequest(
        cohort_id=cohort.id,
        control_number=control,
        first_name="ALUMNA", last_name="INVENTADA", middle_name=None,
        program_id=None, program_text=None,
        phone="6561234567", contact_email="alguien@example.invalid",
        has_efirma=False, kind=kind, status=status,
        verify_token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        verify_expires_at=datetime.now() + timedelta(hours=VERIFY_TTL_HOURS),
        verify_sent_at=datetime.now(), verify_send_count=1,
        verify_sent_to="alguien@example.invalid",
    )
    for k, v in kw.items():
        setattr(row, k, v)
    db_session.add(row)
    db_session.flush()
    return row, token


def test_import_rows_con_repair_credentials_false_no_pone_el_control_de_contrasena(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app,
):
    """Criterio 11: nadie queda con la contraseña igual a su número de control.

    Ojo con el orden de argumentos: `verify_nip(nip, nip_hash)`.
    """
    from itcj2.core.utils.security import verify_nip
    from itcj2.apps.titulatec.services.import_service import ImportService

    seed_phase_defs()
    cohort = make_cohort(status="open")
    user = make_user(control_number="99770001", username="99770001")
    user.password_hash = None
    db_session.flush()

    ImportService.import_rows(
        db_session, cohort,
        [{"control_number": "99770001", "full_name": "INVENTADA ALUMNA",
          "email": None, "program_id": None, "modality_id": None}],
        actor_id=None, source="self_service", repair_credentials=False,
    )

    db_session.refresh(user)
    assert not verify_nip("99770001", user.password_hash)


def test_import_rows_conserva_el_comportamiento_de_hoy_por_omision(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app,
):
    """Los dos parámetros nuevos nacen con el valor de hoy: `admin.py` no se toca."""
    from itcj2.core.utils.security import verify_nip
    from itcj2.apps.titulatec.services.import_service import ImportService

    seed_phase_defs()
    cohort = make_cohort(status="open")
    user = make_user(control_number="99770002", username="99770002")
    user.password_hash = None
    db_session.flush()

    summary = ImportService.import_rows(
        db_session, cohort,
        [{"control_number": "99770002", "full_name": "INVENTADA ALUMNA",
          "email": None, "program_id": None, "modality_id": None}],
        actor_id=None, source="csv",
    )

    db_session.refresh(user)
    assert verify_nip("99770002", user.password_hash)
    assert summary["repaired_users"] == 1
