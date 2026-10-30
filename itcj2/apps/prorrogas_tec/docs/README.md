# Prórrogas (`prorrogas_tec`)

Solicitudes de **prórroga de pago** de inscripción: el alumno pide diferir el pago
en parcialidades dentro de una ventana de admisión, y administración las resuelve
y da seguimiento a cada parcialidad.

> **Estado: incompleta.** Esta app se desarrolló en un fork durante abril–junio de
> 2026 y se importó a este repo el 2026-09-01 como commit inicial. Lo que hay
> funciona y está cerrado con guards, pero faltan piezas. Antes de tocarla lee
> [PENDIENTES.md](PENDIENTES.md).

---

## Nombres: el desfase que hay que tener presente

| Cosa | Valor |
|---|---|
| Paquete Python | `itcj2/apps/prorrogas_tec/` |
| `core_apps.key` (app_key de los guards) | `prorrogas_tec` |
| URL de páginas | `/prorrogas/...` |
| URL de API | `/api/prorrogas/v2/...` |
| Prefijo de permisos | `prorrogas_tec.` |

Es el mismo patrón que `helpdesk` vs `/help-desk` (gotcha #12 de CLAUDE.md). Los
guards resuelven por **key**; el dashboard y los enlaces navegan por **URL**. No
cambies uno sin el otro.

---

## Mapa de piezas

```
itcj2/apps/prorrogas_tec/
├── router.py                   API: /api/prorrogas/v2 (programs, templates, invitaciones, estudiante, solicitudes)
├── api/
│   ├── _common.py              ServiceError → {"error", "message", …} en la raíz del JSON
│   ├── invitations.py          secretaría · QR, búsqueda por número de control, invitación manual, resumen del día
│   ├── programs.py             catálogo de carreras
│   ├── requests_admin.py       secretaría · pendientes, sus PDF y la decisión
│   ├── student.py              estudiante · estado (plan y recibos), solicitar, cancelar, bajar sus PDF, firmar la carta
│   ├── students_admin.py       secretaría · Estudiantes: lista, expediente, plan, recibos, recordar, adeudos.xlsx, desbloqueo
│   └── templates.py            secretaría · plantillas (listar, subir, descargar, vista previa)
├── models/                     prorrogas_requests · _documents · _signatures · _templates · _events · _invitations · _joins
│   ├── plan.py                 prorrogas_installments · prorrogas_payments (plan y recibos de Caja)
├── services/
│   ├── invitation_service.py   QR, invitación manual, unión y NIP inicial
│   ├── request_service.py      puerta de acceso, crear, cancelar y decidir solicitudes
│   ├── account.py              cuenta de una solicitud: pagado, saldo, estado de parcialidades y situación
│   ├── students_service.py     lista, expediente, recordar, adeudos.xlsx y aviso de desbloqueo
│   ├── plan_service.py         confirmar y replantear el plan de pagos (genera la carta compromiso)
│   ├── payment_service.py      registrar y anular recibos de Caja
│   ├── document_service.py     genera, versiona y guarda los PDF de una solicitud
│   ├── template_service.py     plantillas por año: subir, validar, resolver cuál usar
│   ├── docx_fill.py            llena marcadores {{x}} en .docx (aunque Word los parta)
│   ├── signature.py            firma PNG del estudiante, validada antes de estamparla
│   ├── notify.py               correo por Graph y aviso en la plataforma (nunca lanza)
│   ├── identity.py             número de control, correo institucional y folio
│   ├── periods.py              semestre (core_academic_periods) de un día
│   ├── formatting.py           fechas, montos y nombres como en las cartas reales
│   ├── storage.py              archivos (plantillas, PDF, firmas) bajo PRORROGAS_UPLOAD_PATH
│   ├── events.py               bitácora (prorrogas_events)
│   └── errors.py               ServiceError
├── documents/
│   ├── catalog.py              los 6 formatos y sus marcadores (spec §6.2)
│   ├── values.py               valores con que se llena cada formato
│   └── defaults/               plantillas del sistema (tools/prorrogas/build_default_templates.py)
├── pages/                      /prorrogas · router, landing, join (unirse y Crea tu NIP), secretaria, student
├── templates/prorrogas_tec/    email/ (invitacion, decision_*, carta_lista, recordatorio) · estudiante/ · secretaria/
├── static/                     servido por nginx en /static/prorrogas_tec/ (css/, js/, images/)
│                               js/secretaria/estudiantes.js · js/estudiante/firma.js (lienzo compartido)
└── docs/
    ├── README.md · PENDIENTES.md
    └── flows/                  secretaria_documentos · secretaria_solicitudes · secretaria_estudiantes · estudiante_solicitud
                                (UI → endpoint → service → BD de cada flujo)
```

### Modelo de datos

```
core_academic_periods ─1:1─ prorrogas_period_config   (ventana + fechas de pago)
                      ─1:N─ prorrogas_payments_options (catálogo de montos/planes)
                                     │
core_users ──1:N──> prorrogas_requests ──1:N──> prorrogas_payments
core_programs ─────────┘                        (una fila por parcialidad)

core_users ──1:N──> prorrogas_notifications   (buzón propio, NO core_notifications)
```

Dos ENUM de Postgres: `request_status_pg_enum` (PENDING/APPROVED/REJECTED) y
`payment_status_pg_enum` (PENDING/APPROVED/MIDDLE/NOPAID). Los modelos los
declaran con `create_type=False`, así que **los crea la migración**
(`p1r2o3r4g001`), no SQLAlchemy.

---

## Puesta en marcha

```bash
alembic upgrade head                                   # crea las 5 tablas + los 2 enums
python -m itcj2.cli.main prorrogas init-prorrogas      # app, permisos, roles, accesos
```

El CLI corre **solo** `database/DML/prorrogas_tec/` (4 scripts, todos idempotentes) y
hereda la invalidación del caché de authz de `execute_sql_file`.

`03_grant_prorrogas_access.sql` no es opcional: los guards usan `require_roles`, y
**ese no lo bypasea el admin global del JWT** (solo `require_perms` tiene
`allow_global_admin`). Sin esa corrida, un administrador de la plataforma recibe
403 en `/prorrogas/admin/*`.

---

## Renderizado de páginas

A diferencia de titulatec y directory —que tienen su propia instancia de
`Jinja2Templates`—, esta app usa el `render()` global de `itcj2/templates.py`.
Consecuencias que hay que respetar:

- Su directorio de templates está en el **searchpath global** (`itcj2/templates.py`).
  Si se saca de ahí, `render` deja de encontrar los `.html`.
- Los enlaces de la nav se resuelven contra **`ENDPOINT_MAP`**, no con `url_for` de
  FastAPI. Una página nueva necesita su entrada ahí o el enlace apunta a `#`.
