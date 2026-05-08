"""
SLA overdue check para tickets de mantenimiento.

Detecta tickets abiertos vencidos (due_at < now) y envía notificaciones
TICKET_OVERDUE a los técnicos activos y dispatchers/admins de la app maint.
Los tickets ya alertados en las últimas 24 h se omiten (re-alerta diaria).

Ejecutar vía cron (ejemplo cada 15 minutos):
  */15 * * * * cd /app && python -m itcj2.scripts.maint_sla_check >> /var/log/maint_sla.log 2>&1

La salida es JSON por stdout para facilitar el parsing en pipelines de monitoreo.
"""
import json
import sys


def main() -> int:
    from itcj2.database import SessionLocal
    from itcj2.apps.maint.services.sla_service import run_overdue_check

    db = SessionLocal()
    try:
        result = run_overdue_check(db)
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
