# Prórrogas · Plan 2: Invitación, solicitud y decisión — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un estudiante entra por el QR (o por una invitación por correo), llena su solicitud en el celular y la firma; la secretaria la revisa en **QR y solicitudes** y la acepta o rechaza, el sistema genera la carta y le avisa por correo y en la plataforma.

**Architecture:** Primero se retira el código y las tablas del fork y se crea el esquema nuevo (solicitudes, documentos, firmas, invitaciones, uniones y bitácora). Encima van, de abajo hacia arriba:

1. Reglas de dominio puras: semestre por fecha, correo institucional, folio y bitácora.
2. Un servicio de documentos que congela los valores, llena la plantilla del Plan 1 y guarda el PDF.
3. Avisos: correo por Graph y notificación en la plataforma.
4. Servicios de invitación, solicitud y decisión.
5. Sus APIs, las páginas del estudiante y la pestaña de la secretaría.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · PostgreSQL · Alembic (a mano) · PyJWT · Pillow · python-docx + LibreOffice (Plan 1) · Microsoft Graph · Jinja2 + JS sin framework · `qrcode-generator@1.4.4` (jsdelivr) · pytest contra Postgres real.

**Spec:** [`docs/superpowers/specs/2026-10-29-prorrogas-modulo1-design.md`](../specs/2026-10-29-prorrogas-modulo1-design.md). Este plan cubre:

- §3: los permisos del Plan 2.
- §4: pasos 1–4.
- §5: semestre, una solicitud abierta, correo, invitaciones y cuentas nuevas.
- §6: formato de solicitud y cartas de aceptación y rechazo.
- §7: firma.
- §8: la pestaña **QR y solicitudes** y el lado del estudiante.
- §9: las tablas sin plan de pagos.
- §10 y §12.
- La fila "Plan 2" de §14.

Se construye sobre el Plan 1, ya commiteado en `feature/core-prorrogas`.

## Global Constraints

**Herencia del Plan 1**

- Valen todas las Global Constraints del Plan 1: rutas, `require_perms` y `require_page_app`, errores con `{"error", "message", …}` en la raíz del JSON, rutas de PDF en `def`, `db_now()`, migraciones a mano, DML en `.gitignore`, paleta y tipografía, textos en español y la línea `Co-Authored-By`.

**Cómo se ejecuta en este equipo** (resoluciones del ledger del Plan 1)

- Los comandos de Docker van solos, sin `|`, `&&` ni `cd`: el sandbox solo deja salir a `docker …` como primera palabra.
- Las pruebas corren con `docker compose -f docker/compose/docker-compose.dev.yml exec backend pytest <ruta> -q --tb=short -p no:cacheprovider -o addopts=`. En los pasos, `PYTEST` = eso sin la ruta.
- Alembic se corre como `docker compose -f docker/compose/docker-compose.dev.yml exec backend alembic -c migrations/alembic.ini upgrade head`, **antes** de la corrida en verde de una tarea que cambia el esquema.
- Los commits se hacen con `GIT_AUTHOR_NAME/EMAIL` y `GIT_COMMITTER_NAME/EMAIL` = `Deig0l` / `deigolsalazar@gmail.com`. Nunca `git add -A` ni `git add .`.
- Varios archivos del fork son CRLF: se editan conservando CRLF.

**Valores del spec**

- Estados de una solicitud: `pendiente`, `aceptada`, `rechazada`, `cancelada`. Los abiertos son `pendiente` y `aceptada`. El origen es `app` o `excel`.
- Folio: `PR-{id:05d}`.
- Semestre: el de `core_academic_periods` con `start_date ≤ hoy ≤ end_date` y estado distinto de `ARCHIVED`. Si hay varios, el de `start_date` más reciente. La etiqueta sale de `semestre_label(start, end)` del Plan 1.
- Número de control: `^[A-Za-z]?\d{8}$`, normalizado con `strip().upper()`.
- Correo institucional:
  - `^\d{8}$` → `L{control}@{MAIL_STUDENT_DOMAIN}`
  - `^M\d{8}$` → `{control}@{MAIL_STUDENT_DOMAIN}`
  - cualquier otro formato → `None` (la secretaria lo captura)
- QR: JWT HS256 firmado con `get_settings().SECRET_KEY`, con claims `p="prorrogas_join"`, `by=<id secretaria>`, `exp` a 5 min y `jti`. Es multiuso.
- Invitación manual: `secrets.token_urlsafe(32)`. Se guarda solo su sha256. Vale 48 h y es de un solo uso.
- NIP inicial: exactamente 4 dígitos (`^\d{4}$`, como TitulaTec).
- Solicitud: plazos de 1 a 3; motivo de 20 a 1000 caracteres después de `strip()`.
- Firma: PNG en base64 o como data URL, de hasta 200 000 bytes y 2000×2000 px, y no en blanco (canal alfa con contenido).
- **Puerta de acceso** (decisión de este plan, ver "Decisiones"): para crear una solicitud el estudiante necesita una unión (`prorrogas_joins`) dentro del semestre actual y **posterior** a su última solicitud de ese semestre.
- Correo: Graph con `app_key="prorrogas_tec"` y buzón `agendatec@cdjuarez.tecnm.mx` (lo conecta el humano en `/itcj/config/email`). Nunca rompe la operación. Fuera de producción, el enlace se escribe en el log.
- Liga absoluta en correos: `get_settings().DOMAIN`.
- Avisos en la plataforma: `NotificationService.create(db, user_id, "prorrogas_tec", type, title, body, data={"url": …, "request_id": …})`.

**Permisos nuevos** (en `database/DML/prorrogas_tec/05_insert_plan2.sql`)

| Permiso | Rol |
|---|---|
| `prorrogas_tec.invitations.api.create` | secretaria, admin |
| `prorrogas_tec.requests.api.read.all` | secretaria, admin |
| `prorrogas_tec.requests.api.decide` | secretaria, admin |
| `prorrogas_tec.student.page.view` | student |
| `prorrogas_tec.requests.api.create.own` | student |
| `prorrogas_tec.requests.api.read.own` | student |
| `prorrogas_tec.requests.api.cancel.own` | student |

## Decisiones de este plan (desviaciones del spec)

1. **QR en el navegador.** Se dibuja con `qrcode-generator@1.4.4` desde jsdelivr (el repo ya carga Bootstrap de ahí), no con `segno`. Así no hay dependencia de Python nueva ni hay que reconstruir la imagen. Task 10 corrige §10 del spec.
2. **Puerta de acceso por unión, no por rol.** `03_grant_prorrogas_access.sql` copia el rol `student` de AgendaTec a la app, así que casi todo alumno ya tiene el rol. Lo que garantiza que "se pide en persona" es la unión por QR o invitación. Además, Task 5 quita esa copia de alumnos del `03`.
3. **Las invitaciones no llevan `used_by_id`.** La invitación ya está atada a `user_id`: solo esa cuenta puede usarla.
4. **Estas tablas no tienen plan de pagos.** `total_amount`, `plan_confirmed_*`, `block_*` y `last_reminded_at` llegan con el Plan 3, con sus tablas.

## Review Focus

1. **Doble envío** de la solicitud (doble clic, dos pestañas): debe quedar una sola. La segunda recibe 409 `solicitud_abierta`. → Task 1 (índice) y Task 7.
2. **QR vencido o alterado:** página clara de "pide un código nuevo", sin unir al estudiante. → Task 5 y Task 6.
3. **Firma en blanco o enorme:** 400 `firma_vacia` o `firma_muy_grande`, no un PDF con firma vacía. → Task 7.
4. **Dos decisiones** sobre la misma solicitud (dos pestañas, dos secretarias): la segunda recibe 409 `ya_resuelta` y hay una sola carta. → Task 9.
5. **Enlace de invitación abierto con otra cuenta:** 403, y la invitación no se consume. → Task 5 y Task 6.

---

### Task 1: Retirar el código del fork y crear el esquema nuevo

**Files:**
- Create:
  - `itcj2/apps/prorrogas_tec/models/request.py` (reescrito: `ProrrogaRequest`)
  - `models/document.py`, `models/signature.py`, `models/invitation.py`, `models/event.py`
  - `migrations/versions/pr20261030a_prorrogas_esquema.py`
- Delete:
  - `itcj2/apps/prorrogas_tec/` → `helpers.py`, `utils/`, `schemas/`
  - `services/period_service.py`, `services/request_service.py`
  - `api/periods.py`, `api/requests.py`, `api/student/`, `api/admin/`
  - `pages/admin.py`, `pages/student.py`, `pages/nav.py`
  - `models/prorrogas_period_config.py`, `models/prorrogas_notifications.py`, `models/payment_options.py`, `models/payments.py`
  - `templates/prorrogas_tec/base.html`, `templates/prorrogas_tec/admin/`, `templates/prorrogas_tec/student/`
  - `static/css/admin/`, `static/css/student/`, `static/js/admin/`, `static/js/student/`, `static/js/toast.js`, `static/images/help-desk.png`
- Modify:
  - `models/__init__.py`, `itcj2/models/__init__.py:63-66`
  - `itcj2/core/models/academic_period.py:49-57` (quita `prorrogas_config`)
  - `itcj2/templates.py:364-384` (quita las entradas de Prórrogas de `ENDPOINT_MAP`)
  - `itcj2/apps/prorrogas_tec/router.py` (solo `programs` y `templates`)
  - `pages/router.py` (sin `admin` ni `student`)
  - `pages/landing.py` (`student` → `/prorrogas/estudiante`)
  - `api/programs.py` (quita los imports que no usa)
  - `tests/fastapi/prorrogas_tec/conftest.py`
- Test: `tests/fastapi/prorrogas_tec/test_schema.py`

**Interfaces:**
- Produces (modelos, todas las columnas del spec §9 menos las del Plan 3):
  - **`ProrrogaRequest`** (`prorrogas_requests`):
    - `id` BigInteger PK
    - `origin` String(10), por omisión `'app'`, con CHECK `IN ('app','excel')`
    - `import_ref` String(80), único, nulo
    - `student_id` BigInteger → `core_users`, RESTRICT, nulo, con CHECK `origin='excel' OR student_id IS NOT NULL`
    - `period_id` Integer → `core_academic_periods`, RESTRICT, nulo; `period_label` String(60), nulo
    - `status` String(20), por omisión `'pendiente'`, con CHECK `IN (…4 estados)`
    - `requested_terms` SmallInteger, nulo, con CHECK `BETWEEN 1 AND 3`
    - `reason` Text
    - `control_number` Text no nulo; `student_name` Text no nulo; `program_name` Text; `program_level` String(20); `email` Text
    - `decided_by_id` → `core_users`, SET NULL; `decided_at` DateTime; `decision_comment` Text
    - `created_at` y `updated_at` DateTime con `NOW()`
    - Índice único parcial `uq_prorrogas_requests_abierta (student_id, period_id) WHERE status IN ('pendiente','aceptada') AND origin = 'app'`
    - Índice `ix_prorrogas_requests_estado (status, created_at)`
    - Constantes del módulo: `STATUSES`, `OPEN_STATUSES`
  - **`ProrrogaDocument`** (`prorrogas_documents`):
    - `id` BigInteger PK
    - `request_id` → `prorrogas_requests`, CASCADE, no nulo
    - `doc_type` String(40); `version` SmallInteger
    - `template_id` → `prorrogas_templates`, SET NULL
    - `context` JSON no nulo; `file_path` Text; `sha256` String(64)
    - `generated_by_id` → `core_users`, SET NULL; `generated_at` con `NOW()`
    - `signed_at`, `superseded_at` DateTime, nulos
    - UNIQUE `(request_id, doc_type, version)`
  - **`ProrrogaSignature`** (`prorrogas_signatures`):
    - `id` BigInteger PK
    - `document_id` → `prorrogas_documents`, CASCADE, no nulo
    - `signer_id` → `core_users`, RESTRICT, no nulo
    - `image_path` Text; `signed_at` DateTime no nulo; `ip` String(64); `user_agent` Text; `pdf_sha256` String(64)
  - **`ProrrogaInvitation`** (`prorrogas_invitations`):
    - `id` BigInteger PK
    - `control_number` Text; `email` Text
    - `user_id` → `core_users`, CASCADE, no nulo
    - `token_sha256` String(64), único
    - `expires_at` DateTime
    - `created_by_id` → `core_users`, SET NULL
    - `user_created` Boolean, por omisión false
    - `created_at` con `NOW()`; `used_at` DateTime, nulo
  - **`ProrrogaJoin`** (`prorrogas_joins`):
    - `id` BigInteger PK
    - `user_id` → `core_users`, CASCADE
    - `via` String(12) con CHECK `IN ('qr','invitacion')`
    - `invitation_id` → `prorrogas_invitations`, SET NULL
    - `issued_by_id` → `core_users`, SET NULL
    - `joined_at` DateTime no nulo
    - Índice `(user_id, joined_at)`
  - **`ProrrogaEvent`** (`prorrogas_events`):
    - `id` BigInteger PK
    - `request_id` → `prorrogas_requests`, CASCADE, nulo
    - `actor_id` → `core_users`, SET NULL
    - `event_type` String(40); `payload` JSON no nulo, por omisión `{}`
    - `created_at` con `NOW()`
    - Índice `(request_id, created_at)`
- Fixtures nuevas en conftest:
  - `periodo(db_session) -> AcademicPeriod`: código único de 6 caracteres `f"T{n:05d}"`, nombre `f"Prórrogas prueba {n}"`, `start_date=date(2091,1,10)`, `end_date=date(2091,6,20)`, `status="INACTIVE"`.
  - `make_program(db_session) -> Callable[[str, str], Program]`: por nombre, idempotente, como en TitulaTec.
- Migración `pr20261030a` (`down_revision = "pr20261029a"`):
  - `upgrade`: `DROP TABLE IF EXISTS prorrogas_payments, prorrogas_requests, prorrogas_payments_options, prorrogas_notifications, prorrogas_period_config CASCADE`, luego `DROP TYPE IF EXISTS request_status_pg_enum, payment_status_pg_enum`, luego crea las 6 tablas.
  - `downgrade`: tira las 6 tablas y **no** restaura las del fork. Se documenta en el docstring ("CON PÉRDIDA; la rama no está en producción").

- [ ] **Step 1: Write the failing test**

```python
import pytest
from sqlalchemy.exc import IntegrityError

import itcj2.models  # noqa: F401
from itcj2.models.base import Base

NUEVAS = {"prorrogas_templates", "prorrogas_requests", "prorrogas_documents", "prorrogas_signatures",
          "prorrogas_invitations", "prorrogas_joins", "prorrogas_events"}


def test_las_tablas_de_prorrogas_son_las_del_spec():
    assert {t for t in Base.metadata.tables if t.startswith("prorrogas_")} == NUEVAS


def _solicitud(user, periodo, **kw):
    from itcj2.apps.prorrogas_tec.models.request import ProrrogaRequest
    return ProrrogaRequest(student_id=user.id, period_id=periodo.id, control_number="99100001",
                           student_name="PRUEBA", requested_terms=1, **kw)


def test_una_sola_solicitud_abierta_por_semestre(db_session, make_user, periodo):  # Review Focus 1
    u = make_user(control_number="99100001")
    db_session.add(_solicitud(u, periodo))
    db_session.flush()
    db_session.add(_solicitud(u, periodo))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_una_rechazada_no_cuenta_como_abierta(db_session, make_user, periodo):
    u = make_user(control_number="99100002")
    db_session.add(_solicitud(u, periodo, status="rechazada"))
    db_session.add(_solicitud(u, periodo))
    db_session.flush()


def test_estado_desconocido_lo_rechaza_la_bd(db_session, make_user, periodo):
    db_session.add(_solicitud(make_user(control_number="99100003"), periodo, status="otro"))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("url", ["/prorrogas/admin/home", "/prorrogas/admin/periods", "/prorrogas/student/home",
                                 "/api/prorrogas/v2/periods/", "/api/prorrogas/v2/request2/mine"])
def test_las_rutas_del_fork_ya_no_existen(client, url):
    assert client.get(url, follow_redirects=False).status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_schema.py`
Expected: FAIL. Siguen las tablas viejas en `Base.metadata`, todavía no existe `ProrrogaRequest` y las rutas del fork responden distinto de 404.

- [ ] **Step 3: Implement the models, the migration, the deletions and the registry updates**

Después de borrar, `grep -rn -E "Request_pro|Payments_pro|ProrrogasPeriodConfig|Payments_options|prorrogas_tec\.(helpers|utils|schemas)|render_prorrogas_tec" itcj2 tests migrations` debe salir vacío.

- [ ] **Step 4: Apply the migration and run the tests**

Run: `docker compose -f docker/compose/docker-compose.dev.yml exec backend alembic -c migrations/alembic.ini upgrade head`
Expected: `Running upgrade pr20261029a -> pr20261030a`.

Run: `PYTEST tests/fastapi/prorrogas_tec tests/fastapi/core/test_desktop_registry.py tests/fastapi/core/test_desktop_shell.py`
Expected: PASS. Esto incluye las pruebas del Plan 1.

- [ ] **Step 5: Commit**

```bash
git add -u itcj2/apps/prorrogas_tec itcj2/core/models/academic_period.py itcj2/templates.py itcj2/models/__init__.py
git add itcj2/apps/prorrogas_tec/models migrations/versions/pr20261030a_prorrogas_esquema.py tests/fastapi/prorrogas_tec/conftest.py tests/fastapi/prorrogas_tec/test_schema.py
git commit -m "feat(prorrogas): esquema nuevo de solicitudes y retiro del codigo del fork"
```

---

### Task 2: Reglas de dominio (semestre, correo, folio, bitácora)

**Files:**
- Create:
  - `itcj2/apps/prorrogas_tec/services/periods.py`
  - `services/identity.py`
  - `services/events.py`
  - `services/errors.py`
- Test: `tests/fastapi/prorrogas_tec/test_domain_rules.py`

**Interfaces:**
- Consumes: `semestre_label` (Plan 1); `ProrrogaEvent` (Task 1).
- Produces:
  - `period_for(db, day: date) -> AcademicPeriod | None`
  - `period_label(p: AcademicPeriod) -> str`
  - `normalize_control(raw: str) -> str`: lanza `ValueError` si no cumple el formato.
  - `institutional_email(control: str) -> str | None`
  - `folio(request_id: int) -> str`
  - `EVENT_TYPES = frozenset({"solicitud_creada", "solicitud_cancelada", "solicitud_aceptada", "solicitud_rechazada", "documento_generado", "invitacion_enviada"})`
  - `log_event(db, *, event_type: str, request_id: int | None = None, actor_id: int | None = None, payload: dict | None = None) -> ProrrogaEvent`: solo `db.add`. Lanza `ValueError` si el tipo no está en el conjunto.
  - `class ServiceError(ValueError)`: `__init__(self, code: str, message: str, status: int = 400, **detail)`, con atributos `code`, `message`, `status`, `detail`.

- [ ] **Step 1: Write the failing test**

```python
from datetime import date

import pytest

from itcj2.apps.prorrogas_tec.services.events import log_event
from itcj2.apps.prorrogas_tec.services.identity import folio, institutional_email, normalize_control
from itcj2.apps.prorrogas_tec.services.periods import period_for, period_label


def test_semestre_que_contiene_el_dia(db_session, periodo):
    assert period_for(db_session, date(2091, 2, 1)).id == periodo.id
    assert period_for(db_session, date(2091, 7, 1)) is None


def test_etiqueta_del_semestre(periodo):
    assert period_label(periodo) == "enero – junio 2091"


def test_correo_institucional():
    assert institutional_email("22111670") == "L22111670@cdjuarez.tecnm.mx"
    assert institutional_email("M23111966") == "M23111966@cdjuarez.tecnm.mx"
    assert institutional_email("D80060093") is None and institutional_email("B20410631") is None


def test_normaliza_y_valida_el_numero_de_control():
    assert normalize_control(" m23111966 ") == "M23111966"
    for malo in ("123", "AB12345678", ""):
        with pytest.raises(ValueError):
            normalize_control(malo)


def test_folio():
    assert folio(12) == "PR-00012"


def test_la_bitacora_rechaza_tipos_desconocidos(db_session):
    with pytest.raises(ValueError):
        log_event(db_session, event_type="inventado")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_domain_rules.py`
Expected: FAIL con `ModuleNotFoundError`.

- [ ] **Step 3: Implement the four modules**

El dominio de correo es `itcj2.core.utils.email_tools.MAIL_STUDENT_DOMAIN`.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_domain_rules.py`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add itcj2/apps/prorrogas_tec/services/periods.py itcj2/apps/prorrogas_tec/services/identity.py itcj2/apps/prorrogas_tec/services/events.py itcj2/apps/prorrogas_tec/services/errors.py tests/fastapi/prorrogas_tec/test_domain_rules.py
git commit -m "feat(prorrogas): reglas de semestre, correo institucional, folio y bitacora"
```

---

### Task 3: Generación de documentos con valores congelados y firma

**Files:**
- Create:
  - `itcj2/apps/prorrogas_tec/services/storage.py`
  - `documents/values.py`
  - `services/document_service.py`
- Modify:
  - `services/template_service.py`: usa `storage._base`, `storage.write_atomic` y `storage.abs_path`; se borran sus copias privadas.
  - `itcj2/core/utils/docx_pdf.py`: cada llamada a LibreOffice usa su propio perfil (`-env:UserInstallation=file://{tmpdir}/lo-profile`). Así dos estudiantes que envían a la vez no chocan por el perfil compartido. Viene de la revisión final del Plan 1.
  - `tests/fastapi/prorrogas_tec/conftest.py`: `almacen` ahora parcha `services.storage._base`; nuevas fixtures `solicitud` y `pdf_falso`.
- Test:
  - `tests/fastapi/prorrogas_tec/test_document_service.py`
  - `tests/fastapi/prorrogas_tec/test_docx_pdf.py` (prueba del perfil)

**Interfaces:**
- Consumes:
  - De Plan 1: `fill_docx`, `TemplateService.resolve`, `docx_pdf.docx_to_pdf` (llamado como atributo del módulo), `DOC_TYPES`, `fecha_corta`.
  - De Task 2: `folio`, `log_event`.
- Produces:
  - **`storage.py`**: `_base() -> Path`, `abs_path(rel: str) -> Path`, `write_atomic(rel: str, data: bytes) -> Path`.
  - **`values.py`**:
    - `@dataclass(frozen=True) class SignatureInfo`, con campos `png: bytes`, `signer_id: int`, `signed_at: datetime`, `ip: str | None` y `user_agent: str | None`.
    - `build_values(req, doc_type: str, *, today: date, extra: Mapping[str, str] | None = None, signature: SignatureInfo | None = None) -> tuple[dict[str, str], dict[str, bytes]]`. Da un valor a **cada** marcador permitido del tipo:
      - `fecha` = `fecha_corta(today)`; `folio`; `nombre` = `student_name`; `no_control`
      - `carrera` = `program_name or ""`; `semestre` = `period_label or ""`; `correo` = `email or ""`
      - `plazos_solicitados` = `str(requested_terms)`; `motivo` = `reason`; `fecha_solicitud` = `fecha_corta(created_at.date())`
      - `comentario` y `motivo_rechazo` salen de `extra`
      - `firma_estudiante`: va en `images` si hay firma; si no, en `values` como `""`
      - `firma_estudiante_leyenda` = `f"Firmado electrónicamente por {student_name} el {signed_at:%d/%m/%Y %H:%M} · folio {folio}"`, o `""` sin firma
      - cualquier otro permitido = `""`
  - **`DocumentService`**:
    - `generate(db, req, doc_type: str, *, actor_id: int | None, today: date, extra=None, signature: SignatureInfo | None = None) -> ProrrogaDocument`:
      - versión = 1 + la máxima de `(req, doc_type)`; las anteriores reciben `superseded_at`
      - la plantilla se resuelve para `today.year`
      - el PDF se guarda en `documentos/{req.id}/{doc_type}-v{version}.pdf`
      - `context` = los valores (sin imágenes)
      - con firma: guarda `documentos/{req.id}/firma-{doc_type}-v{version}.png`, crea el `ProrrogaSignature` con `pdf_sha256` y pone `signed_at` en el documento
      - registra `log_event("documento_generado")`
      - si `docx_pdf.docx_to_pdf` lanza algo de `docx_pdf.CONVERSION_ERRORS` (Plan 1, revisión final), lanza `ServiceError("pdf_no_disponible", "No se pudo generar el PDF. Intenta de nuevo en un momento.", status=503)` y no escribe nada
      - **No hace commit.**
    - Texto libre (`motivo`, `comentario`, `motivo_rechazo`): `build_values` quita los caracteres de control que XML no admite y junta los saltos de línea y espacios repetidos en un solo espacio.
    - `read_pdf(doc) -> bytes`
    - `current(db, req) -> list[ProrrogaDocument]`: los que tienen `superseded_at IS NULL`, ordenados por `generated_at`.
- Fixtures:
  - `solicitud(db_session, make_user, periodo) -> ProrrogaRequest`: estudiante `99400001` y solicitud `pendiente`, 2 plazos, motivo de 30 caracteres, `program_name="Ingeniería en Sistemas Computacionales"`, `period_label="enero – junio 2091"`, `email="L99400001@cdjuarez.tecnm.mx"`; con flush.
  - `pdf_falso(monkeypatch)`: parcha `itcj2.core.utils.docx_pdf.docx_to_pdf` y guarda `{"placeholders": find_placeholders(data), "kind": kind}` en `.calls`. Devuelve `b"%PDF-1.4 fake"`. **No es autouse.**

- [ ] **Step 1: Write the failing test**

```python
from datetime import date, datetime

import pytest

from itcj2.apps.prorrogas_tec.documents.catalog import sample_signature_png
from itcj2.apps.prorrogas_tec.documents.values import SignatureInfo
from itcj2.apps.prorrogas_tec.models.signature import ProrrogaSignature
from itcj2.apps.prorrogas_tec.services.document_service import DocumentService
from itcj2.core.utils import docx_pdf

HOY = date(2091, 2, 1)


def _firma(req):
    return SignatureInfo(png=sample_signature_png(), signer_id=req.student_id,
                         signed_at=datetime(2091, 2, 1, 10, 42), ip="10.0.0.1", user_agent="pytest")


def test_formato_de_solicitud_firmado(db_session, solicitud, pdf_falso):
    doc = DocumentService.generate(db_session, solicitud, "formato_solicitud", actor_id=solicitud.student_id,
                                   today=HOY, signature=_firma(solicitud))
    assert doc.version == 1 and doc.signed_at == datetime(2091, 2, 1, 10, 42)
    assert doc.context["folio"] == f"PR-{solicitud.id:05d}" and doc.context["semestre"] == "enero – junio 2091"
    assert doc.context["firma_estudiante_leyenda"].startswith("Firmado electrónicamente por")
    assert pdf_falso.calls[-1] == {"placeholders": set(), "kind": "prorrogas_documento"}
    assert DocumentService.read_pdf(doc) == b"%PDF-1.4 fake"
    sig = db_session.query(ProrrogaSignature).filter_by(document_id=doc.id).one()
    assert sig.pdf_sha256 == doc.sha256 and sig.ip == "10.0.0.1"


def test_sin_firma_la_leyenda_queda_vacia(db_session, solicitud, pdf_falso):
    doc = DocumentService.generate(db_session, solicitud, "formato_solicitud", actor_id=None, today=HOY)
    assert doc.context["firma_estudiante_leyenda"] == "" and doc.signed_at is None


def test_una_nueva_version_sustituye_a_la_anterior(db_session, solicitud, pdf_falso):
    v1 = DocumentService.generate(db_session, solicitud, "carta_aceptacion", actor_id=None, today=HOY)
    v2 = DocumentService.generate(db_session, solicitud, "carta_aceptacion", actor_id=None, today=HOY)
    assert (v1.version, v2.version) == (1, 2) and v1.superseded_at is not None
    assert [d.id for d in DocumentService.current(db_session, solicitud)] == [v2.id]


def test_el_texto_libre_se_limpia(db_session, solicitud, pdf_falso):
    solicitud.reason = "Línea 1\nLínea 2\x07   fin"
    doc = DocumentService.generate(db_session, solicitud, "formato_solicitud", actor_id=None, today=HOY)
    assert doc.context["motivo"] == "Línea 1 Línea 2 fin"


def test_sin_pdf_lanza_pdf_no_disponible(db_session, solicitud, monkeypatch):
    import subprocess
    from itcj2.apps.prorrogas_tec.services.errors import ServiceError

    def boom(data, *, kind):
        raise subprocess.TimeoutExpired(["soffice"], 60)

    monkeypatch.setattr(docx_pdf, "docx_to_pdf", boom)
    with pytest.raises(ServiceError) as e:
        DocumentService.generate(db_session, solicitud, "carta_aceptacion", actor_id=None, today=HOY)
    assert e.value.code == "pdf_no_disponible" and e.value.status == 503


@pytest.mark.skipif(docx_pdf.find_libreoffice() is None, reason="sin LibreOffice")
def test_pdf_real_de_la_carta_de_rechazo(db_session, solicitud):
    doc = DocumentService.generate(db_session, solicitud, "carta_rechazo", actor_id=None, today=HOY,
                                   extra={"motivo_rechazo": "Falta el comprobante de ingresos."})
    assert DocumentService.read_pdf(doc).startswith(b"%PDF")
```

Y en `test_docx_pdf.py`:

```python
def test_cada_conversion_usa_su_propio_perfil(monkeypatch):
    from types import SimpleNamespace
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        outdir = cmd[cmd.index("--outdir") + 1]
        with open(f"{outdir}/document.pdf", "wb") as f:
            f.write(b"%PDF-1.4")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(docx_pdf, "find_libreoffice", lambda: "soffice")
    monkeypatch.setattr(docx_pdf.subprocess, "run", fake_run)
    docx_pdf.docx_to_pdf(b"x", kind="prorrogas_documento")
    assert any(a.startswith("-env:UserInstallation=file://") for a in seen["cmd"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_document_service.py tests/fastapi/prorrogas_tec/test_docx_pdf.py`
Expected: FAIL. Falta el módulo (`ModuleNotFoundError`) y el comando de LibreOffice no lleva perfil propio.

- [ ] **Step 3: Implement `storage.py`, `values.py`, `document_service.py` and the per-call profile; switch `template_service` and `almacen` to `storage`**

Después de agregar el perfil, corre `PYTEST tests/fastapi/observability/test_work_sites_helpdesk.py`: las pruebas de helpdesk deben seguir en verde.

- [ ] **Step 4: Run the tests**

Run: `PYTEST tests/fastapi/prorrogas_tec`
Expected: PASS. Las del Plan 1 siguen en verde con el `almacen` nuevo.

- [ ] **Step 5: Commit**

```bash
git add itcj2/apps/prorrogas_tec/services/storage.py itcj2/apps/prorrogas_tec/documents/values.py itcj2/apps/prorrogas_tec/services/document_service.py itcj2/apps/prorrogas_tec/services/template_service.py tests/fastapi/prorrogas_tec/conftest.py tests/fastapi/prorrogas_tec/test_document_service.py
git commit -m "feat(prorrogas): documentos con valores congelados, PDF guardado y firma"
```

---

### Task 4: Avisos (correo por Graph y notificación en la plataforma)

**Files:**
- Create:
  - `itcj2/apps/prorrogas_tec/services/notify.py`
  - `templates/prorrogas_tec/email/_base_email.html`, `invitacion.html`, `decision_aceptada.html`, `decision_rechazada.html`
- Modify: `tests/fastapi/prorrogas_tec/conftest.py` (fixtures `enviar_correo` y `avisos`)
- Test: `tests/fastapi/prorrogas_tec/test_notify.py`

**Interfaces:**
- Produces:
  - `send_email(*, template: str, context: dict, subject: str, to: str | None, link: str | None = None) -> bool`:
    - El token sale de `msgraph_mail.acquire_token_silent("prorrogas_tec")`, llamado como atributo del módulo.
    - Renderiza con `itcj2.templates.templates.env.get_template(f"prorrogas_tec/email/{template}")` y envía con `msgraph_mail.graph_send_mail`.
    - Fuera de producción (`FLASK_ENV != "production"`), escribe `[PRORROGAS-LINK] {to} -> {link}` en el log.
    - Nunca lanza.
  - `notify_student(db, req, *, kind: str, link: str) -> None`, con `kind ∈ {"aceptada", "rechazada"}`:
    - Crea la notificación en la plataforma con `type=f"prorroga_{kind}"` y `data={"url": link, "request_id": req.id}`.
    - Llama a `send_email` con `template=f"decision_{kind}.html"` y `to=req.email`.
    - Nunca lanza.
  - Títulos y asuntos exactos:
    - aceptada: `"Tu prórroga fue aceptada"`; cuerpo: `"Acude a la Subdirección Académica para acordar el monto y las fechas de tus pagos."`
    - rechazada: `"Tu solicitud de prórroga no fue autorizada"`; cuerpo: `decision_comment[:200]`
  - Asunto de la invitación: `"Invitación al módulo de Prórrogas"`.
  - Fixtures de conftest:
    - `enviar_correo`: parcha `notify.send_email` y guarda los kwargs en `.calls`; devuelve `True`.
    - `avisos`: parcha `notify.notify_student` y guarda `(kind, req.id, link)` en `.calls`.
    - Las dos parchan el atributo del módulo `services.notify`; los consumidores deben llamar `notify.send_email(...)` y `notify.notify_student(...)`.

- [ ] **Step 1: Write the failing test**

```python
from types import SimpleNamespace

from itcj2.apps.prorrogas_tec.services import notify
from itcj2.core.models.notification import Notification
from itcj2.core.utils import msgraph_mail


def test_sin_cuenta_de_correo_no_truena(monkeypatch):
    monkeypatch.setattr(msgraph_mail, "acquire_token_silent", lambda app: None)
    assert notify.send_email(template="decision_aceptada.html", context={"folio": "PR-00001", "link": "x"},
                             subject="s", to="a@example.invalid") is False


def test_envia_con_graph_y_lleva_la_liga(monkeypatch):
    sent = {}
    monkeypatch.setattr(msgraph_mail, "acquire_token_silent", lambda app: "tok")

    def fake_send(token, subject, html, to, *a, **k):
        sent.update(subject=subject, html=html, to=to)
        return SimpleNamespace(status_code=202, text="")

    monkeypatch.setattr(msgraph_mail, "graph_send_mail", fake_send)
    ok = notify.send_email(template="invitacion.html", context={"link": "https://x/prorrogas/unirse/invitacion/abc"},
                           subject="Invitación al módulo de Prórrogas", to="L99000000@cdjuarez.tecnm.mx")
    assert ok and sent["to"] == ["L99000000@cdjuarez.tecnm.mx"] and "unirse/invitacion/abc" in sent["html"]


def test_el_aviso_en_la_plataforma_sale_aunque_falle_el_correo(db_session, solicitud, monkeypatch):
    monkeypatch.setattr(msgraph_mail, "acquire_token_silent", lambda app: None)
    notify.notify_student(db_session, solicitud, kind="aceptada", link="/prorrogas/estudiante")
    n = db_session.query(Notification).filter_by(user_id=solicitud.student_id, app_name="prorrogas_tec").one()
    assert n.type == "prorroga_aceptada" and n.title == "Tu prórroga fue aceptada"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_notify.py`
Expected: FAIL con `ImportError` (no existe `services.notify`).

- [ ] **Step 3: Implement `notify.py`, the email templates and the two fixtures**

Las plantillas de correo usan HTML simple con la paleta. Cada una lleva un botón con `{{ link }}`, el folio cuando aplica y la firma "Subdirección Académica · ITCJ".

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_notify.py`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add itcj2/apps/prorrogas_tec/services/notify.py itcj2/apps/prorrogas_tec/templates/prorrogas_tec/email tests/fastapi/prorrogas_tec/conftest.py tests/fastapi/prorrogas_tec/test_notify.py
git commit -m "feat(prorrogas): avisos por correo (Graph) y en la plataforma"
```

---

### Task 5: Invitaciones (servicio y API de la secretaria)

**Files:**
- Create:
  - `itcj2/apps/prorrogas_tec/services/invitation_service.py`
  - `api/invitations.py`
  - `api/_common.py`
- Modify:
  - `router.py` (`prefix="/invitaciones"`)
  - `api/templates.py` (usa `_common.error_response`; borra su `_error`)
  - `tests/fastapi/prorrogas_tec/conftest.py` (`SECRETARIA_PERMS` += `prorrogas_tec.invitations.api.create`)
- Create (gitignored): `database/DML/prorrogas_tec/05_insert_plan2.sql`. Contiene los permisos y asignaciones de la tabla de Global Constraints; tasks 7 y 9 no le agregan nada más.
- Modify (gitignored):
  - `database/DML/prorrogas_tec/03_grant_prorrogas_access.sql`: quita el bloque que copia el rol `student` de AgendaTec (Decisión 2).
  - `itcj2/cli/prorrogas.py`: agrega `"05_insert_plan2.sql"`.
- Test: `tests/fastapi/prorrogas_tec/test_invitations.py`

**Interfaces:**
- Consumes:
  - De Task 2: `normalize_control`, `institutional_email`, `log_event`, `ServiceError`.
  - De Task 4: `notify.send_email`.
  - Del repo: `authz_service.grant_role`, `hash_nip`, `email_tools.normalize_email` e `is_valid_email`, `StudentProfileService.set_fields`.
- Produces:
  - **`api/_common.py`**: `error_response(status: int, code: str, message: str, **detail) -> JSONResponse`.
  - **Constantes**: `QR_TTL = timedelta(minutes=5)`, `INVITATION_TTL = timedelta(hours=48)`, `QR_PURPOSE = "prorrogas_join"`.
  - **QR**:
    - `issue_qr(secretary_id: int, *, now: datetime | None = None) -> dict`, que devuelve `{"token", "path": "/prorrogas/unirse?t=<token>", "expires_at": iso}`.
    - `read_qr(token: str, *, now: datetime | None = None) -> int`: devuelve el id de quien lo emitió. Lanza `ServiceError("qr_expirado", status=410)` o `ServiceError("qr_invalido", status=400)`.
  - **`lookup(db, raw_control: str) -> dict`**, que devuelve `{"control_number", "existe", "nombre", "correo_sugerido", "requiere_datos", "requiere_correo"}`.
  - **`invite(db, *, raw_control, email, actor_id, nombres=None, apellido_paterno=None, apellido_materno=None, program_id=None, now=None) -> tuple[ProrrogaInvitation, str]`**, que devuelve la invitación y el token crudo:
    - **Correo** (spec §5), en este orden:
      1. el que capturó la secretaria
      2. el institucional (licenciatura y maestría)
      3. el `email` de la cuenta, si ya existe (caso de doctorado y reingreso)

      Si no hay ninguno, `correo_requerido`; si es inválido, `correo_invalido`. `lookup` usa el mismo orden (sin el primero) para `correo_sugerido`, y `requiere_correo` es verdadero cuando no hay ninguno.
    - **Cuenta nueva:** si el número de control no tiene cuenta, se exigen `nombres`, `apellido_paterno` y `program_id` (si falta alguno, `datos_requeridos`; si la carrera no existe, `carrera_invalida`).
      - La cuenta se crea con rol global `student`, nombres en mayúsculas, el correo y sin `password_hash`.
      - En el perfil se registra `program_id`.
      - La invitación queda con `user_created=True`.
    - Envía `notify.send_email(template="invitacion.html", link=f"{DOMAIN}/prorrogas/unirse/invitacion/{token}")`, registra `invitacion_enviada` y hace commit.
  - **`invitation_for_token(db, raw_token: str) -> ProrrogaInvitation | None`**
  - **`consume_invitation(db, raw_token, *, user_id, now=None) -> ProrrogaJoin`**: se valida en este orden, y ninguno de los errores marca la invitación como usada:
    1. `invitacion_invalida` (404)
    2. `invitacion_usada` (409)
    3. `invitacion_expirada` (410)
    4. `invitacion_de_otra_cuenta` (403)
  - **`join(db, user_id, *, via, issued_by_id, invitation_id=None, now=None) -> ProrrogaJoin`**: le da el rol `student` en `prorrogas_tec`, crea la unión y hace commit.
  - **`set_initial_nip(db, raw_token, nip, nip2) -> None`**: errores, en orden:
    - los de una invitación inválida, usada o expirada
    - `cuenta_con_nip` (409) si la cuenta ya tiene NIP
    - `nip_invalido` si no son 4 dígitos
    - `nip_no_coincide` si `nip != nip2`
  - **`today_summary(db, *, now=None) -> dict`**, que devuelve `{"se_unieron_hoy", "invitaciones_hoy", "ultimas": [{"correo", "hora": "HH:MM"} ×≤3]}`.
  - **API** (`api/invitations.py`), todo con `require_perms("prorrogas_tec", ["prorrogas_tec.invitations.api.create"])`:
    - `POST /api/prorrogas/v2/invitaciones/qr` → `issue_qr`
    - `GET /api/prorrogas/v2/invitaciones/alumno?control=` → `lookup`
    - `POST /api/prorrogas/v2/invitaciones` (JSON con `control_number`, `correo`, `nombres`, `apellido_paterno`, `apellido_materno`, `program_id`) → 201 `{"id", "correo", "expira"}`
    - `GET /api/prorrogas/v2/invitaciones/hoy` → `today_summary`
    - Los `ServiceError` salen como `error_response(e.status, e.code, e.message, **e.detail)`.

- [ ] **Step 1: Write the failing test**

```python
from datetime import datetime, timedelta

import pytest

from itcj2.apps.prorrogas_tec.services import invitation_service as inv
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.core.services.authz_service import user_roles_in_app

T0 = datetime(2091, 2, 1, 9, 0)


def test_qr_valido_devuelve_quien_lo_emitio():
    out = inv.issue_qr(7, now=T0)
    assert out["path"].startswith("/prorrogas/unirse?t=") and inv.read_qr(out["token"], now=T0 + timedelta(minutes=4)) == 7


def test_qr_vencido_o_alterado():  # Review Focus 2
    token = inv.issue_qr(7, now=T0)["token"]
    with pytest.raises(ServiceError) as e:
        inv.read_qr(token, now=T0 + timedelta(minutes=6))
    assert e.value.code == "qr_expirado"
    with pytest.raises(ServiceError) as e:
        inv.read_qr(token[:-2] + "xx", now=T0)
    assert e.value.code == "qr_invalido"


def test_lookup_de_licenciatura_con_cuenta(db_session, make_user):
    make_user(control_number="99200001")
    out = inv.lookup(db_session, " 99200001 ")
    assert out["existe"] and out["correo_sugerido"] == "L99200001@cdjuarez.tecnm.mx"
    assert not out["requiere_datos"] and not out["requiere_correo"]


def test_lookup_de_doctorado_sin_cuenta(db_session):
    out = inv.lookup(db_session, "D99200002")
    assert not out["existe"] and out["requiere_datos"] and out["requiere_correo"]


def test_invitar_crea_cuenta_de_posgrado_sin_nip(db_session, secretaria, make_program, enviar_correo):
    prog = make_program("Doctorado de Prueba", "doctorado")
    invitacion, token = inv.invite(db_session, raw_control="D99200003", email="persona@example.invalid",
                                   actor_id=secretaria.id, nombres="Ana", apellido_paterno="López", program_id=prog.id)
    assert invitacion.user_created and invitacion.user.password_hash is None
    assert enviar_correo.calls[0]["to"] == "persona@example.invalid" and enviar_correo.calls[0]["link"].endswith(token)


@pytest.mark.parametrize("kwargs, code", [
    ({"raw_control": "D99200004", "email": None}, "correo_requerido"),
    ({"raw_control": "D99200005", "email": "x@example.invalid"}, "datos_requeridos"),
    ({"raw_control": "123", "email": None}, "control_invalido"),
])
def test_invitaciones_invalidas(db_session, secretaria, enviar_correo, kwargs, code):
    with pytest.raises(ServiceError) as e:
        inv.invite(db_session, actor_id=secretaria.id, **kwargs)
    assert e.value.code == code


def test_consumir_une_da_el_rol_y_no_se_reusa(db_session, secretaria, make_user, enviar_correo):
    u = make_user(control_number="99200006")
    _, token = inv.invite(db_session, raw_control="99200006", email=None, actor_id=secretaria.id)
    join = inv.consume_invitation(db_session, token, user_id=u.id)
    assert join.via == "invitacion" and "student" in user_roles_in_app(db_session, u.id, "prorrogas_tec")
    with pytest.raises(ServiceError) as e:
        inv.consume_invitation(db_session, token, user_id=u.id)
    assert e.value.code == "invitacion_usada"


def test_invitacion_abierta_por_otra_cuenta_no_se_consume(db_session, secretaria, make_user, enviar_correo):  # RF 5
    make_user(control_number="99200007")
    otro = make_user(control_number="99200008")
    invitacion, token = inv.invite(db_session, raw_control="99200007", email=None, actor_id=secretaria.id)
    with pytest.raises(ServiceError) as e:
        inv.consume_invitation(db_session, token, user_id=otro.id)
    assert e.value.code == "invitacion_de_otra_cuenta" and invitacion.used_at is None


def test_nip_inicial(db_session, secretaria, make_program, enviar_correo):
    prog = make_program("Doctorado de Prueba", "doctorado")
    invitacion, token = inv.invite(db_session, raw_control="D99200009", email="p@example.invalid",
                                   actor_id=secretaria.id, nombres="Luis", apellido_paterno="Paz", program_id=prog.id)
    with pytest.raises(ServiceError) as e:
        inv.set_initial_nip(db_session, token, "12a4", "12a4")
    assert e.value.code == "nip_invalido"
    inv.set_initial_nip(db_session, token, "1234", "1234")
    with pytest.raises(ServiceError) as e:
        inv.set_initial_nip(db_session, token, "9999", "9999")
    assert e.value.code == "cuenta_con_nip"


def test_api_qr_solo_para_la_secretaria(client_as, secretaria, estudiante):
    assert client_as(estudiante).post("/api/prorrogas/v2/invitaciones/qr").status_code == 403
    r = client_as(secretaria).post("/api/prorrogas/v2/invitaciones/qr")
    assert r.status_code == 200 and r.json()["path"].startswith("/prorrogas/unirse?t=")


def test_api_invitar_y_resumen_del_dia(client_as, secretaria, make_user, enviar_correo):
    make_user(control_number="99200010")
    c = client_as(secretaria)
    r = c.post("/api/prorrogas/v2/invitaciones", json={"control_number": "99200010"})
    assert r.status_code == 201 and r.json()["correo"] == "L99200010@cdjuarez.tecnm.mx"
    assert c.get("/api/prorrogas/v2/invitaciones/hoy").json()["invitaciones_hoy"] >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_invitations.py`
Expected: FAIL con `ImportError`.

- [ ] **Step 3: Implement the service, `_common.py`, the API, the router mount, the SQL changes and the CLI entry**

Run: `docker compose -f docker/compose/docker-compose.dev.yml exec backend python -m itcj2.cli.main prorrogas init-prorrogas`
Expected: `6/6 archivos ejecutados`.

- [ ] **Step 4: Run the tests**

Run: `PYTEST tests/fastapi/prorrogas_tec`
Expected: PASS. Incluye `test_permissions_contract.py`, que ahora ve los códigos nuevos.

- [ ] **Step 5: Commit** (sin los `.sql`)

```bash
git add itcj2/apps/prorrogas_tec/services/invitation_service.py itcj2/apps/prorrogas_tec/api/invitations.py itcj2/apps/prorrogas_tec/api/_common.py itcj2/apps/prorrogas_tec/api/templates.py itcj2/apps/prorrogas_tec/router.py itcj2/cli/prorrogas.py tests/fastapi/prorrogas_tec/conftest.py tests/fastapi/prorrogas_tec/test_invitations.py
git commit -m "feat(prorrogas): invitaciones por QR y por correo, con alta de cuentas de posgrado"
```

---

### Task 6: Unirse (QR, invitación y "Crea tu NIP")

**Files:**
- Create:
  - `itcj2/apps/prorrogas_tec/pages/join.py`
  - `templates/prorrogas_tec/estudiante/_base.html`, `estudiante/unirse_error.html`, `estudiante/crea_nip.html`
  - `static/css/estudiante/base.css`
- Modify: `pages/router.py`
- Test: `tests/fastapi/prorrogas_tec/test_join_pages.py`

**Interfaces:**
- Consumes: de Task 5, `read_qr`, `join`, `invitation_for_token`, `consume_invitation`, `set_initial_nip` y `ServiceError`.
- Produces: estas rutas, sin `require_page_app`, porque quien se une todavía no tiene el rol. La sesión se lee de `request.state.current_user`.
  - **`GET /prorrogas/unirse?t=`**:
    - Sin sesión → 302 a `/itcj/login?next=` + `quote(f"/prorrogas/unirse?t={t}", safe="")`.
    - Con sesión: `read_qr` y `join(via="qr", issued_by_id=<emisor>)`, luego 302 a `/prorrogas/estudiante/solicitud`.
    - Si el QR no sirve, muestra `unirse_error.html` con el código de estado del error y el texto "Este código ya no es válido. Pide un código nuevo en la Subdirección Académica."
  - **`GET /prorrogas/unirse/invitacion/{token}`**:
    - Invitación inválida, usada o expirada → `unirse_error.html`, con el estado del error.
    - Cuenta sin NIP → `crea_nip.html` (200).
    - Sin sesión → 302 al login con `next`.
    - Con sesión → `consume_invitation`, luego 302 a `/prorrogas/estudiante/solicitud`. Si es de otra cuenta, `unirse_error.html` con 403.
  - **`POST /prorrogas/unirse/invitacion/{token}`** (formulario con `nip` y `nip2`):
    - `set_initial_nip`, luego 302 a `/itcj/login?next=<la misma URL>`.
    - Con error, vuelve a mostrar `crea_nip.html` con el mensaje y 400.
  - `estudiante/_base.html` es una página completa pensada para celular, con la paleta y las fuentes del Plan 1. No tiene pestañas: una barra con "Prórrogas" y el nombre del estudiante.

- [ ] **Step 1: Write the failing test**

```python
from datetime import timedelta

from itcj2.apps.prorrogas_tec.models.invitation import ProrrogaJoin
from itcj2.apps.prorrogas_tec.services import invitation_service as inv
from itcj2.core.utils.timezone import db_now


def test_sin_sesion_va_al_login_con_next(client):
    r = client.get("/prorrogas/unirse?t=abc", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/itcj/login?next=%2Fprorrogas%2Funirse%3Ft%3Dabc"


def test_qr_valido_une_y_lleva_a_la_solicitud(client_as, secretaria, make_user, db_session):
    u = make_user(control_number="99300001")
    token = inv.issue_qr(secretaria.id)["token"]
    r = client_as(u).get(f"/prorrogas/unirse?t={token}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/prorrogas/estudiante/solicitud"
    assert db_session.query(ProrrogaJoin).filter_by(user_id=u.id, via="qr").count() == 1


def test_qr_vencido_muestra_mensaje_y_no_une(client_as, secretaria, make_user, db_session):  # Review Focus 2
    u = make_user(control_number="99300002")
    token = inv.issue_qr(secretaria.id, now=db_now() - timedelta(minutes=10))["token"]
    r = client_as(u).get(f"/prorrogas/unirse?t={token}", follow_redirects=False)
    assert r.status_code == 410 and "Pide un código nuevo" in r.text
    assert db_session.query(ProrrogaJoin).filter_by(user_id=u.id).count() == 0


def test_invitacion_de_cuenta_nueva_pide_crear_nip_y_luego_login(client, secretaria, make_program, enviar_correo, db_session):
    prog = make_program("Doctorado de Prueba", "doctorado")
    invitacion, token = inv.invite(db_session, raw_control="D99300003", email="n@example.invalid",
                                   actor_id=secretaria.id, nombres="Eva", apellido_paterno="Ruiz", program_id=prog.id)
    url = f"/prorrogas/unirse/invitacion/{token}"
    assert "Crea tu NIP" in client.get(url).text
    r = client.post(url, data={"nip": "4321", "nip2": "4321"}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("/itcj/login?next=")
    db_session.refresh(invitacion.user)
    assert invitacion.user.password_hash


def test_invitacion_abierta_con_otra_cuenta(client_as, secretaria, make_user, enviar_correo, db_session):  # RF 5
    make_user(control_number="99300004")
    otro = make_user(control_number="99300005")
    invitacion, token = inv.invite(db_session, raw_control="99300004", email=None, actor_id=secretaria.id)
    r = client_as(otro).get(f"/prorrogas/unirse/invitacion/{token}", follow_redirects=False)
    assert r.status_code == 403 and invitacion.used_at is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_join_pages.py`
Expected: FAIL (404 en `/prorrogas/unirse`).

- [ ] **Step 3: Implement `join.py`, the templates and the CSS; mount the router**

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_join_pages.py`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add itcj2/apps/prorrogas_tec/pages/join.py itcj2/apps/prorrogas_tec/pages/router.py itcj2/apps/prorrogas_tec/templates/prorrogas_tec/estudiante itcj2/apps/prorrogas_tec/static/css/estudiante tests/fastapi/prorrogas_tec/test_join_pages.py
git commit -m "feat(prorrogas): unirse al modulo por QR o invitacion, y NIP inicial"
```

---

### Task 7: Solicitud del estudiante (servicio y API)

**Files:**
- Create:
  - `itcj2/apps/prorrogas_tec/services/signature.py`
  - `services/request_service.py`
  - `api/student.py`
- Modify:
  - `router.py` (`prefix="/estudiante"`)
  - `tests/fastapi/prorrogas_tec/conftest.py`
- Test: `tests/fastapi/prorrogas_tec/test_student_requests.py`

**Interfaces:**
- Consumes:
  - De Task 2: `period_for`, `period_label`, `institutional_email`, `log_event`, `ServiceError`.
  - De Task 3: `DocumentService.generate` y `current`, `SignatureInfo`.
  - De Plan 1: `nombre_oficial`.
- Produces:
  - **`parse_signature(raw: str) -> bytes`**: acepta una data URL `data:image/png;base64,…` o base64 directo. Errores, en orden: `firma_invalida`, `firma_muy_grande` (más de 200 000 bytes decodificados o más de 2000 px por lado) y `firma_vacia` (`img.getchannel("A").getbbox() is None`).
  - **`RequestService`**:
    - Constantes: `MOTIVO_MIN = 20`, `MOTIVO_MAX = 1000`.
    - `access(db, user_id, *, now=None) -> tuple[AcademicPeriod | None, str | None]`: devuelve el semestre y el código que impide solicitar, uno de `no_hay_semestre`, `solicitud_abierta` o `sin_acceso`.
      - La puerta de unión: hace falta una `ProrrogaJoin` con `joined_at` dentro del semestre y posterior al `created_at` de la última solicitud del usuario en ese semestre.
    - `create(db, student: User, *, plazos: int, motivo: str, program_id: int, firma: bytes, ip: str | None, user_agent: str | None, now=None) -> ProrrogaRequest`:
      - **Validaciones, en orden:**
        - `plazos_invalidos`
        - `motivo_invalido`
        - `carrera_invalida`
        - los errores de `access`: 409 para `no_hay_semestre` y `solicitud_abierta`; 403 para `sin_acceso`
      - **Copia congelada:** `student_name = nombre_oficial(...)`, programa y nivel, `email = student.email or institutional_email(control)`, `period_id` y `period_label`.
      - Hace flush y genera el `formato_solicitud` firmado. Si la generación lanza `pdf_no_disponible`, hace rollback y lo propaga (503): la solicitud no queda creada y el estudiante puede volver a intentarlo.
      - Registra `solicitud_creada` y hace commit.
      - Si el commit choca con `IntegrityError` contra el índice único, devuelve `solicitud_abierta` (409).
    - `cancel(db, request_id, student_id, *, now=None) -> ProrrogaRequest`: solo la propia y en `pendiente` (si no, `no_cancelable` 409 o `no_encontrada` 404). Registra `solicitud_cancelada`.
    - `mine(db, student_id) -> list[ProrrogaRequest]`: de la más reciente a la más vieja.
    - `request_out(db, req) -> dict`: `{"id", "folio", "estado", "plazos", "motivo", "semestre", "creada", "decidida", "comentario", "documentos": [{"id", "tipo", "label", "version", "firmado"}]}` con `DocumentService.current`.
  - **API** (`api/student.py`, bajo `/api/prorrogas/v2/estudiante`):
    - `GET /estado` (`requests.api.read.own`) → `{"puede_solicitar", "motivo", "semestre", "program_id" (del perfil), "solicitudes": [request_out…]}`
    - `POST /solicitudes` (`requests.api.create.own`, JSON con `plazos`, `motivo`, `program_id` y `firma`) → 201 `{"id", "folio"}`. IP: `request.client.host`, salvo que el repo traiga `core/utils/client_ip.client_ip(request)`, que entonces se usa.
    - `POST /solicitudes/{id}/cancelar` (`requests.api.cancel.own`)
    - `GET /solicitudes/{id}/documentos/{doc_id}.pdf` (`requests.api.read.own`): solo documentos propios; si no, 404 `no_encontrada`. Se sirve inline.
- Fixtures de conftest:
  - `STUDENT_PERMS` con los 4 permisos del rol student, que se le dan a `estudiante`.
  - `periodo_hoy`: semestre con `start_date = hoy - 1 día` y `end_date = hoy + 60 días`. Es el de inicio más reciente, así que `period_for` lo elige aunque haya uno real.
  - `alumno_unido(db_session, estudiante, periodo_hoy)`: crea `ProrrogaJoin(via="qr", joined_at=db_now() - timedelta(minutes=1))` y devuelve al estudiante.
  - `firma_png`: `sample_signature_png()`.

- [ ] **Step 1: Write the failing test**

```python
import base64
from io import BytesIO

import pytest
from PIL import Image

from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.request_service import RequestService
from itcj2.apps.prorrogas_tec.services.signature import parse_signature

pytestmark = pytest.mark.usefixtures("pdf_falso")
MOTIVO = "El pago de nómina de mis padres se retrasó este mes."


def _crear(db, alumno, prog, firma, **kw):
    datos = dict(plazos=2, motivo=MOTIVO, program_id=prog.id, firma=firma, ip="10.0.0.2", user_agent="pytest")
    datos.update(kw)
    return RequestService.create(db, alumno, **datos)


def test_crea_solicitud_con_formato_firmado(db_session, alumno_unido, make_program, firma_png):
    req = _crear(db_session, alumno_unido, make_program("Ingeniería de Prueba", "licenciatura"), firma_png)
    out = RequestService.request_out(db_session, req)
    assert out["estado"] == "pendiente" and out["documentos"][0]["tipo"] == "formato_solicitud"
    assert out["documentos"][0]["firmado"] is True and req.period_label


def test_doble_envio_solo_crea_una(db_session, alumno_unido, make_program, firma_png):  # Review Focus 1
    prog = make_program("Ingeniería de Prueba", "licenciatura")
    _crear(db_session, alumno_unido, prog, firma_png)
    with pytest.raises(ServiceError) as e:
        _crear(db_session, alumno_unido, prog, firma_png)
    assert e.value.code == "solicitud_abierta" and e.value.status == 409


def test_sin_union_no_puede_solicitar(db_session, estudiante, periodo_hoy, make_program, firma_png):
    with pytest.raises(ServiceError) as e:
        _crear(db_session, estudiante, make_program("Ingeniería de Prueba", "licenciatura"), firma_png)
    assert e.value.code == "sin_acceso"


def test_tras_cancelar_hay_que_unirse_otra_vez(db_session, alumno_unido, make_program, firma_png):
    prog = make_program("Ingeniería de Prueba", "licenciatura")
    req = _crear(db_session, alumno_unido, prog, firma_png)
    RequestService.cancel(db_session, req.id, alumno_unido.id)
    with pytest.raises(ServiceError) as e:
        _crear(db_session, alumno_unido, prog, firma_png)
    assert e.value.code == "sin_acceso"


@pytest.mark.parametrize("kw, code", [({"plazos": 4}, "plazos_invalidos"), ({"motivo": "corto"}, "motivo_invalido")])
def test_datos_invalidos(db_session, alumno_unido, make_program, firma_png, kw, code):
    with pytest.raises(ServiceError) as e:
        _crear(db_session, alumno_unido, make_program("Ingeniería de Prueba", "licenciatura"), firma_png, **kw)
    assert e.value.code == code


def _png(size, color):
    buf = BytesIO()
    Image.new("RGBA", size, color).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def test_firma_vacia_o_enorme():  # Review Focus 3
    with pytest.raises(ServiceError) as e:
        parse_signature("data:image/png;base64," + _png((600, 180), (0, 0, 0, 0)))
    assert e.value.code == "firma_vacia"
    with pytest.raises(ServiceError) as e:
        parse_signature(_png((2500, 100), (0, 0, 0, 255)))
    assert e.value.code == "firma_muy_grande"
    with pytest.raises(ServiceError) as e:
        parse_signature("no-es-base64!!")
    assert e.value.code == "firma_invalida"


def test_api_crear_ver_y_no_ver_lo_ajeno(client_as, alumno_unido, make_user, make_program, firma_png):
    prog = make_program("Ingeniería de Prueba", "licenciatura")
    c = client_as(alumno_unido)
    firma = "data:image/png;base64," + base64.b64encode(firma_png).decode()
    r = c.post("/api/prorrogas/v2/estudiante/solicitudes",
               json={"plazos": 2, "motivo": MOTIVO, "program_id": prog.id, "firma": firma})
    assert r.status_code == 201 and r.json()["folio"].startswith("PR-")
    estado = c.get("/api/prorrogas/v2/estudiante/estado").json()
    assert estado["puede_solicitar"] is False and estado["motivo"] == "solicitud_abierta"
    doc = estado["solicitudes"][0]["documentos"][0]
    assert c.get(f"/api/prorrogas/v2/estudiante/solicitudes/{r.json()['id']}/documentos/{doc['id']}.pdf").status_code == 200
    ajeno = make_user(control_number="99500009")
    assert client_as(ajeno).get(
        f"/api/prorrogas/v2/estudiante/solicitudes/{r.json()['id']}/documentos/{doc['id']}.pdf").status_code in (403, 404)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_student_requests.py`
Expected: FAIL con `ImportError`.

- [ ] **Step 3: Implement `signature.py`, `request_service.py`, `api/student.py` and the fixtures; mount the router**

- [ ] **Step 4: Run the tests**

Run: `PYTEST tests/fastapi/prorrogas_tec`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add itcj2/apps/prorrogas_tec/services/signature.py itcj2/apps/prorrogas_tec/services/request_service.py itcj2/apps/prorrogas_tec/api/student.py itcj2/apps/prorrogas_tec/router.py tests/fastapi/prorrogas_tec/conftest.py tests/fastapi/prorrogas_tec/test_student_requests.py
git commit -m "feat(prorrogas): solicitud del estudiante con firma, una por semestre y solo tras unirse"
```

---

### Task 8: Páginas del estudiante (Mi prórroga y Solicitud con firma)

**Files:**
- Create:
  - `itcj2/apps/prorrogas_tec/pages/student.py` (nuevo)
  - `templates/prorrogas_tec/estudiante/mi_prorroga.html`, `estudiante/solicitud.html`
  - `static/js/estudiante/mi_prorroga.js`, `static/js/estudiante/solicitud.js`
- Modify: `pages/router.py`, `static/css/estudiante/base.css`
- Test: `tests/fastapi/prorrogas_tec/test_student_pages.py`

**Interfaces:**
- Consumes: la API de Task 7 y `GET /api/prorrogas/v2/programs`, que ya existe.
- Produces:
  - **Router:** `APIRouter(prefix="/estudiante", dependencies=[Depends(require_page_app("prorrogas_tec", perms=["prorrogas_tec.student.page.view"]))])`.
  - **Rutas:** `GET ""` (`prorrogas_tec.pages.estudiante.home`) → `mi_prorroga.html`; `GET "/solicitud"` (`…solicitud`) → `solicitud.html`.
  - **`mi_prorroga.js`** consulta `/estado` y muestra:
    - "Pide tu acceso en la Subdirección Académica" si el motivo es `sin_acceso`
    - un botón "Solicitar prórroga" si puede solicitar
    - el folio, el estado, el comentario de la secretaria, los documentos (ligas al PDF) y "Cancelar" si está pendiente
  - **`solicitud.js`**:
    - El formulario tiene: carrera (select de `/programs`, con la del perfil preseleccionada), plazos (1–3), motivo (contador de 20 a 1000) y **firma**.
    - La firma es un `<canvas>` con eventos de puntero que funciona con el dedo; trae "Borrar" y una casilla obligatoria "Firmo este documento".
    - Envía `canvas.toDataURL("image/png")`.
    - Al terminar, redirige a `/prorrogas/estudiante`. Si hay un error 4xx, muestra el `message`.

- [ ] **Step 1: Write the failing test**

```python
def test_anonimo_va_al_login(client):
    r = client.get("/prorrogas/estudiante", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/itcj/login"


def test_estudiante_ve_mi_prorroga_y_la_solicitud(client_as, estudiante):
    c = client_as(estudiante)
    assert "Mi prórroga" in c.get("/prorrogas/estudiante").text
    page = c.get("/prorrogas/estudiante/solicitud").text
    assert "Firmo este documento" in page and "<canvas" in page


def test_la_secretaria_no_entra_a_la_vista_del_estudiante(client_as, secretaria):
    assert client_as(secretaria).get("/prorrogas/estudiante", follow_redirects=False).status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_student_pages.py`
Expected: FAIL (404).

- [ ] **Step 3: Implement the router, the templates, the JS and the CSS; mount the router**

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_student_pages.py`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add itcj2/apps/prorrogas_tec/pages/student.py itcj2/apps/prorrogas_tec/pages/router.py itcj2/apps/prorrogas_tec/templates/prorrogas_tec/estudiante itcj2/apps/prorrogas_tec/static/js/estudiante itcj2/apps/prorrogas_tec/static/css/estudiante tests/fastapi/prorrogas_tec/test_student_pages.py
git commit -m "feat(prorrogas): vista del estudiante con solicitud y firma en pantalla"
```

---

### Task 9: Decisión de la secretaria (servicio y API)

**Files:**
- Modify:
  - `itcj2/apps/prorrogas_tec/services/request_service.py`
  - `tests/fastapi/prorrogas_tec/conftest.py` (`SECRETARIA_PERMS` += `requests.api.read.all` y `requests.api.decide`)
- Create: `itcj2/apps/prorrogas_tec/api/requests_admin.py`
- Modify: `router.py` (`prefix="/solicitudes"`)
- Test: `tests/fastapi/prorrogas_tec/test_decision.py`

**Interfaces:**
- Consumes: de Task 3, `DocumentService.generate`; de Task 4, `notify.notify_student`; de Task 7, `RequestService.request_out`.
- Produces:
  - **`RequestService.decide(db, request_id: int, actor_id: int, *, aceptar: bool, comentario: str | None, now=None) -> ProrrogaRequest`**:
    - Bloquea la fila con `.populate_existing().with_for_update()`.
    - Errores: `no_encontrada` (404); `ya_resuelta` (409) si no está `pendiente`; `motivo_requerido` (400) si es rechazo sin comentario; `comentario_muy_largo` (400) si pasa de 1000 caracteres.
    - Guarda `status`, `decided_by_id`, `decided_at` y `decision_comment`.
    - Genera `carta_aceptacion` (con `extra={"comentario": …}`) o `carta_rechazo` (con `extra={"motivo_rechazo": …}`).
    - Registra el evento y hace commit. Si la carta lanza `pdf_no_disponible`, hace rollback y lo propaga (503): la solicitud sigue `pendiente` y la secretaria puede reintentar.
    - **Después** del commit llama a `notify.notify_student(db, req, kind="aceptada"|"rechazada", link="/prorrogas/estudiante")`.
  - **`RequestService.pending(db) -> list[ProrrogaRequest]`**: de la más reciente a la más vieja.
  - **API** (`api/requests_admin.py`, bajo `/api/prorrogas/v2/solicitudes`):
    - `GET ""` (`requests.api.read.all`) → `{"items": [{"id", "folio", "nombre", "control", "correo", "recibida", "plazos", "documento_id"}]}` con las pendientes; `documento_id` es el del `formato_solicitud` vigente.
    - `GET /{id}` (`read.all`) → `request_out`
    - `GET /{id}/documentos/{doc_id}.pdf` (`read.all`) → PDF inline
    - `POST /{id}/decision` (`requests.api.decide`, JSON con `aceptar` y `comentario`) → `request_out`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.request_service import RequestService
from itcj2.apps.prorrogas_tec.services.document_service import DocumentService

pytestmark = pytest.mark.usefixtures("pdf_falso")


def test_aceptar_genera_la_carta_y_avisa(db_session, solicitud, secretaria, avisos):
    req = RequestService.decide(db_session, solicitud.id, secretaria.id, aceptar=True, comentario="")
    assert req.status == "aceptada" and req.decided_by_id == secretaria.id
    assert [d.doc_type for d in DocumentService.current(db_session, req)] == ["carta_aceptacion"]
    assert avisos.calls == [("aceptada", req.id, "/prorrogas/estudiante")]


def test_rechazar_requiere_motivo_y_lo_pone_en_la_carta(db_session, solicitud, secretaria, avisos):
    with pytest.raises(ServiceError) as e:
        RequestService.decide(db_session, solicitud.id, secretaria.id, aceptar=False, comentario="  ")
    assert e.value.code == "motivo_requerido"
    req = RequestService.decide(db_session, solicitud.id, secretaria.id, aceptar=False, comentario="Falta el comprobante.")
    carta = DocumentService.current(db_session, req)[0]
    assert carta.doc_type == "carta_rechazo" and carta.context["motivo_rechazo"] == "Falta el comprobante."


def test_no_se_resuelve_dos_veces(db_session, solicitud, secretaria, avisos):  # Review Focus 4
    RequestService.decide(db_session, solicitud.id, secretaria.id, aceptar=True, comentario="")
    with pytest.raises(ServiceError) as e:
        RequestService.decide(db_session, solicitud.id, secretaria.id, aceptar=False, comentario="otra")
    assert e.value.code == "ya_resuelta" and e.value.status == 409
    assert len(DocumentService.current(db_session, solicitud)) == 1 and len(avisos.calls) == 1


def test_api_lista_pendientes_y_decide(client_as, secretaria, solicitud, avisos):
    c = client_as(secretaria)
    ids = [i["id"] for i in c.get("/api/prorrogas/v2/solicitudes").json()["items"]]
    assert solicitud.id in ids
    r = c.post(f"/api/prorrogas/v2/solicitudes/{solicitud.id}/decision", json={"aceptar": True, "comentario": ""})
    assert r.status_code == 200 and r.json()["estado"] == "aceptada"
    assert c.post(f"/api/prorrogas/v2/solicitudes/{solicitud.id}/decision",
                  json={"aceptar": True, "comentario": ""}).status_code == 409


def test_api_el_estudiante_no_decide(client_as, estudiante, solicitud):
    assert client_as(estudiante).post(f"/api/prorrogas/v2/solicitudes/{solicitud.id}/decision",
                                      json={"aceptar": True, "comentario": ""}).status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_decision.py`
Expected: FAIL (no existe `RequestService.decide`).

- [ ] **Step 3: Implement `decide`, `pending`, the API and the mount**

- [ ] **Step 4: Run the tests**

Run: `PYTEST tests/fastapi/prorrogas_tec`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add itcj2/apps/prorrogas_tec/services/request_service.py itcj2/apps/prorrogas_tec/api/requests_admin.py itcj2/apps/prorrogas_tec/router.py tests/fastapi/prorrogas_tec/conftest.py tests/fastapi/prorrogas_tec/test_decision.py
git commit -m "feat(prorrogas): la secretaria acepta o rechaza, con carta y aviso al estudiante"
```

---

### Task 10: Pestaña "QR y solicitudes", documentación y cierre

**Files:**
- Modify:
  - `itcj2/apps/prorrogas_tec/pages/secretaria.py`: `solicitudes` sale de `_PENDIENTES`; `GET ""` redirige a `/prorrogas/secretaria/solicitudes`.
  - `static/css/secretaria/base.css`
  - `tests/fastapi/prorrogas_tec/test_secretaria_pages.py`: la raíz ahora lleva a `/solicitudes`; `solicitudes` sale de la lista de "próximamente".
- Create:
  - `templates/prorrogas_tec/secretaria/solicitudes.html`, `static/js/secretaria/solicitudes.js`
  - `itcj2/apps/prorrogas_tec/docs/flows/secretaria_solicitudes.md`, `docs/flows/estudiante_solicitud.md`
- Modify (docs):
  - `itcj2/apps/prorrogas_tec/docs/README.md` (mapa)
  - `itcj2/apps/prorrogas_tec/docs/PENDIENTES.md`: los puntos 1–9 quedan resueltos u obsoletos, cada uno con una línea de por qué.
  - `docs/superpowers/specs/2026-10-29-prorrogas-modulo1-design.md`: §10, la línea del QR pasa a "qrcode-generator@1.4.4 desde jsdelivr, en el navegador".
- Test: `tests/fastapi/prorrogas_tec/test_secretaria_pages.py`

**Interfaces:**
- Consumes: las APIs de Task 5 (`/invitaciones/qr`, `/alumno`, `/hoy`, `POST /invitaciones`) y de Task 9 (`/solicitudes`, `/{id}`, `/{id}/documentos/{doc}.pdf`, `/{id}/decision`).
- Produces: la vista del diseño ("02 QR y solicitudes"), con tres partes:
  - **Panel de acceso** con dos modos, **Código QR** y **Sin celular**:
    - QR: dibujado con `qrcode(0, "M")` de `https://cdn.jsdelivr.net/npm/qrcode-generator@1.4.4/qrcode.js` sobre `location.origin + path`, con "Expira en mm:ss", regeneración automática al vencer y el botón **Regenerar código**.
    - Sin celular: número de control → `GET /alumno` → muestra los campos que hagan falta (correo; nombre, apellidos y carrera si no hay cuenta) → **Enviar invitación**.
    - Contadores "Se unieron hoy" e "Invitaciones manuales" con las últimas 3.
  - **Tabla de pendientes** con nombre y control, correo, recibida y plazos solicitados, y "Haz clic sobre una fila para revisar".
  - **Modal de revisión** con un `<iframe>` del PDF del formato de solicitud, los datos, un comentario (obligatorio si se rechaza) y **Rechazar** / **Aceptar prórroga**. Al terminar, muestra un aviso y quita la fila.

- [ ] **Step 1: Update the page tests (failing)**

```python
def test_raiz_de_secretaria_lleva_a_solicitudes(client_as, secretaria):
    r = client_as(secretaria).get(BASE, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == f"{BASE}/solicitudes"


def test_pestana_qr_y_solicitudes(client_as, secretaria):
    page = client_as(secretaria).get(f"{BASE}/solicitudes").text
    for texto in ("Código QR", "Invitar manualmente", "Regenerar código", "qrcode-generator@1.4.4", "Aceptar prórroga"):
        assert texto in page
```

Además, `test_pestanas_pendientes_muestran_proximamente` queda parametrizado solo con `["estadisticas", "estudiantes"]`, y se borra `test_raiz_de_secretaria_lleva_a_documentos`.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_secretaria_pages.py`
Expected: FAIL (la raíz sigue en `/documentos` y la pestaña dice "próximamente").

- [ ] **Step 3: Implement the template, the JS, the CSS and the route change; write the docs**

- [ ] **Step 4: Run the whole suite and a real smoke test**

Run: `PYTEST tests/fastapi/prorrogas_tec tests/fastapi/core tests/fastapi/observability tests/fastapi/helpdesk`
Expected: PASS, salvo el fallo previo conocido de `test_json_logging`. Si `services/request_service.py` del fork ya no existe, ese también debe pasar: si sigue en rojo, investiga.

Después, una prueba de humo dentro del contenedor (`python -c` con `httpx`, como en el Plan 1):

1. Entrar como `secretaria.prorrogas` y emitir un QR.
2. Entrar como un alumno de prueba y abrir `/prorrogas/unirse?t=…`.
3. Crear la solicitud con `sample_signature_png`.
4. Volver como la secretaria y aceptarla.
5. Comprobar que el estudiante ve la carta de aceptación.

- [ ] **Step 5: Commit**

```bash
git add itcj2/apps/prorrogas_tec/pages/secretaria.py itcj2/apps/prorrogas_tec/templates/prorrogas_tec/secretaria/solicitudes.html itcj2/apps/prorrogas_tec/static/js/secretaria/solicitudes.js itcj2/apps/prorrogas_tec/static/css/secretaria/base.css itcj2/apps/prorrogas_tec/docs tests/fastapi/prorrogas_tec/test_secretaria_pages.py docs/superpowers/specs/2026-10-29-prorrogas-modulo1-design.md
git commit -m "feat(prorrogas): pestana QR y solicitudes de la secretaria"
```

---

## Después de este plan

- **Para que lleguen los correos:** conectar el buzón `agendatec@cdjuarez.tecnm.mx` para la app **Prórrogas** en `/itcj/config/email`. Lo hace un humano: es un inicio de sesión OAuth. Sin eso, las decisiones y las invitaciones funcionan igual, pero solo con aviso en la plataforma, y en desarrollo el enlace se escribe en el log.
- **Plan 3, Estudiantes y pagos:**
  - plan de pagos
  - carta compromiso y su firma (`DocumentService` gana `sign`)
  - recibos de Caja, situación, Recordar, y la lista de bloqueo con los avisos de desbloqueo
