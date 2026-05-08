"""
Limpieza de adjuntos vencidos para tickets de mantenimiento.

Ejecuta dos pasos en orden:
  1. set_auto_delete_on_resolved_tickets — asigna auto_delete_at a adjuntos de
     tickets terminados que aún no lo tienen.
  2. cleanup_expired_attachments — elimina físicamente los archivos con
     auto_delete_at <= now() y marca is_purged=True en la fila (la fila se conserva).

Ambas funciones son idempotentes; es seguro correr este script repetidamente.

Ejecutar vía cron (ejemplo diariamente a las 03:00):
  0 3 * * * cd /app && python -m itcj2.scripts.maint_attachment_cleanup >> /var/log/maint_cleanup.log 2>&1

La salida es JSON por stdout.
"""
import json
import sys


def main() -> int:
    from itcj2.database import SessionLocal
    from itcj2.apps.maint.services.attachment_cleanup import (
        set_auto_delete_on_resolved_tickets,
        cleanup_expired_attachments,
    )

    db = SessionLocal()
    try:
        marked = set_auto_delete_on_resolved_tickets(db)
        purged = cleanup_expired_attachments(db)
        result = {
            'attachments_marked_for_deletion': marked,
            'attachments_purged': purged,
        }
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
