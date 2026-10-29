"""Acceso a la fila singleton `helpdesk_settings` (tolera que no exista)."""
from sqlalchemy.orm import Session

from itcj2.apps.helpdesk.models.helpdesk_settings import HelpdeskSettings

_FIELDS = ("auto_assign_enabled", "assignment_email_user_ids")


def get_settings(db: Session) -> HelpdeskSettings:
    row = db.get(HelpdeskSettings, 1)
    if row is None:
        # Defaults sin agregarlo a la sesion (CI: create_all, sin fila sembrada)
        return HelpdeskSettings(id=1, auto_assign_enabled=False, assignment_email_user_ids=[])
    return row


def update_settings(db: Session, *, user_id: int, **fields) -> HelpdeskSettings:
    """Crea la fila 1 si falta y asigna solo los campos conocidos. No commitea."""
    row = db.get(HelpdeskSettings, 1)
    if row is None:
        row = HelpdeskSettings(id=1, auto_assign_enabled=False, assignment_email_user_ids=[])
        db.add(row)
    for k, v in fields.items():
        if k in _FIELDS:
            setattr(row, k, v)
    row.updated_by_id = user_id
    db.flush()
    return row
