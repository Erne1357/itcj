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
apps/prorrogas_tec/
├── router.py                 API: /api/prorrogas/v2 (periods, request, request2, programs)
├── helpers.py                require_admission_open()
├── models/                   5 tablas prorrogas_*
├── schemas/                  Pydantic v2 (periods, requests, payments)
├── services/
│   ├── period_service.py     ventana de admisión + config por período
│   └── request_service.py    lectura de solicitudes
├── api/
│   ├── periods.py            admin · CRUD de la ventana de admisión
│   ├── requests.py           admin · solicitudes y pagos
│   ├── programs.py           catálogo de carreras
│   ├── student/requests.py   alumno · mine / create / cancel
│   └── admin/request.py      ⚠ NO montado — ver PENDIENTES
├── pages/                    /prorrogas · landing, student, admin
├── static/                   servido por nginx en /static/prorrogas_tec/
└── templates/prorrogas_tec/
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
