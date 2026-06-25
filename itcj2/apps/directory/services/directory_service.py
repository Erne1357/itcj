"""Lógica del directorio de extensiones (unifica puestos + extras)."""
import logging

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _position_row(position, holder_name):
    return {
        "source": "position",
        "department_id": position.department_id,
        "department": position.department.name if position.department else "—",
        "title": position.title,
        "holder": holder_name or "",
        "extension": position.phone_extension or "",
        "notes": position.phone_notes or "",
        "position_id": position.id,
        "entry_id": None,
    }


def _entry_row(entry):
    return {
        "source": "entry",
        "department_id": entry.department_id,
        "department": entry.department.name if entry.department else "—",
        "title": entry.label,
        "holder": entry.holder_name or "",
        "extension": entry.extension,
        "notes": entry.notes or "",
        "position_id": entry.position_id,
        "entry_id": entry.id,
    }


def group_by_department(rows):
    """Agrupa filas por departamento; ordena grupos por nombre y filas por extensión."""
    groups = {}
    for r in rows:
        groups.setdefault((r["department_id"], r["department"]), []).append(r)
    out = []
    for (dep_id, dep_name) in sorted(groups, key=lambda k: (k[1] or "").lower()):
        group_rows = sorted(groups[(dep_id, dep_name)], key=lambda x: x["extension"])
        out.append({"department_id": dep_id, "department": dep_name, "rows": group_rows})
    return out


def list_directory(db: Session, *, q=None, department_id=None, source="all"):
    """Lista unificada agrupada por departamento: puestos con extensión + extras."""
    from itcj2.core.models.position import Position, UserPosition
    from itcj2.apps.directory.models import DirectoryEntry

    rows = []

    if source in ("all", "position"):
        pos_query = db.query(Position).filter(
            Position.phone_extension.isnot(None),
            Position.is_active == True,  # noqa: E712
        )
        if department_id:
            pos_query = pos_query.filter(Position.department_id == department_id)
        for pos in pos_query.all():
            assignment = (
                db.query(UserPosition)
                .filter_by(position_id=pos.id, is_active=True)
                .first()
            )
            holder = ""
            if assignment and assignment.user:
                holder = assignment.user.full_name
            rows.append(_position_row(pos, holder))

    if source in ("all", "entry"):
        ent_query = db.query(DirectoryEntry).filter(DirectoryEntry.is_active == True)  # noqa: E712
        if department_id:
            ent_query = ent_query.filter(DirectoryEntry.department_id == department_id)
        for ent in ent_query.all():
            rows.append(_entry_row(ent))

    if q:
        ql = q.strip().lower()
        rows = [
            r for r in rows
            if ql in f"{r['title']} {r['holder']} {r['extension']} {r['notes']} {r['department']}".lower()
        ]

    return group_by_department(rows)


def set_position_extension(db: Session, position_id, extension, notes, by_user_id):
    """Escribe la extensión/notas de un puesto en core_positions (fuente única)."""
    from itcj2.core.models.position import Position
    pos = db.get(Position, position_id)
    if not pos:
        raise ValueError(f"El puesto {position_id} no existe")
    pos.phone_extension = (extension or "").strip() or None
    pos.phone_notes = (notes or "").strip() or None
    db.commit()
    db.refresh(pos)
    return pos


def create_entry(db: Session, *, department_id, label, extension, position_id=None, holder_name=None, notes=None, by_user_id=None):
    from itcj2.core.models.department import Department
    from itcj2.apps.directory.models import DirectoryEntry
    if not db.get(Department, department_id):
        raise ValueError(f"El departamento {department_id} no existe")
    entry = DirectoryEntry(
        department_id=department_id,
        position_id=position_id,
        label=(label or "").strip(),
        holder_name=(holder_name or "").strip() or None,
        extension=(extension or "").strip(),
        notes=(notes or "").strip() or None,
        created_by_id=by_user_id,
    )
    if not entry.label:
        raise ValueError("La etiqueta es obligatoria")
    if not entry.extension:
        raise ValueError("La extensión es obligatoria")
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def update_entry(db: Session, entry_id, *, label=None, extension=None, position_id=None, holder_name=None, notes=None):
    from itcj2.apps.directory.models import DirectoryEntry
    entry = db.get(DirectoryEntry, entry_id)
    if not entry:
        raise ValueError(f"La entrada {entry_id} no existe")
    if label is not None:
        entry.label = label.strip()
    if extension is not None:
        entry.extension = extension.strip()
    if holder_name is not None:
        entry.holder_name = holder_name.strip() or None
    if notes is not None:
        entry.notes = notes.strip() or None
    entry.position_id = position_id
    db.commit()
    db.refresh(entry)
    return entry


def delete_entry(db: Session, entry_id):
    from itcj2.apps.directory.models import DirectoryEntry
    entry = db.get(DirectoryEntry, entry_id)
    if not entry:
        raise ValueError(f"La entrada {entry_id} no existe")
    db.delete(entry)
    db.commit()
