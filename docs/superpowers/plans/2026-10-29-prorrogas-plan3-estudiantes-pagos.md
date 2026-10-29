# Prórrogas · Plan 3: Estudiantes y pagos — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Una prórroga completa, de la aceptación a la liquidación, sin Excel.
- La secretaria arma el plan de pagos (o lo replantea) en la pestaña **Estudiantes**.
- El estudiante firma la carta compromiso en *Mi prórroga*.
- La secretaria registra o anula recibos de Caja.
- La situación se recalcula sola. "Recordar" avisa a quien debe.
- La lista de adeudos sale en un `.xlsx`. "Avisar desbloqueo" cierra el ciclo.

**Architecture:** Primero el esquema: parcialidades, recibos y las columnas de plan, bloqueo y recordatorio en la solicitud. Encima va un cálculo **puro** de la cuenta (FIFO y situación) que usan todos. Después, servicios pequeños por responsabilidad:

- lista y expediente
- plan
- recibos
- firma de la carta
- recordatorio, exportación y desbloqueo

Al final, la pestaña de la secretaria y *Mi prórroga*.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · PostgreSQL · Alembic (a mano) · `Decimal` / `Numeric(10,2)` · openpyxl (ya en el repo) · python-docx + LibreOffice (Plan 1) · Microsoft Graph (Plan 2) · Jinja2 + JS sin framework · pytest contra Postgres real.

**Spec:** [`docs/superpowers/specs/2026-10-29-prorrogas-modulo1-design.md`](../specs/2026-10-29-prorrogas-modulo1-design.md). Este plan cubre:

- §3: los permisos del Plan 3.
- §4: pasos 5–9.
- §5: monto, fechas, replantear, recibos, aplicación de pagos, situación y Recordar.
- §6: las cartas compromiso.
- §8: la pestaña **Estudiantes** y *Mi prórroga*.
- §9: las tablas de plan y recibos.
- **§16 completo** (decisiones del Plan 3).
- La fila "Plan 3" de §14.

Se construye sobre los Planes 1 y 2, ya commiteados en `feature/core-prorrogas`.

## Global Constraints

**Herencia**

- Valen las Global Constraints de los Planes 1 y 2:
  - rutas, `require_perms` y `require_page_app`
  - errores `{"error", "message", …}` en la raíz del JSON (`api/_common.py`: `error_response`, `service_error_response`)
  - rutas de PDF en `def`
  - `db_now()` (hora de Ciudad Juárez, naive)
  - migraciones a mano, DML en `.gitignore`
  - paleta y tipografía del §8.1, textos en español
  - XSS: todo texto de la API entra al DOM por `textContent` / `createElement`, nunca por `innerHTML`
  - avisos con `notify.notify_student`, que nunca lanza

**Cómo se ejecuta en este equipo**

- Un comando de Docker debe tener `docker` como **primera palabra**: sin `cd … &&`, `VAR=`, `|`, `2>&1` ni redirecciones. Si no, corre dentro del sandbox y falla con "permission denied … docker.sock".
- Pruebas: `docker compose -f docker/compose/docker-compose.dev.yml exec backend pytest <ruta> -q --tb=short -p no:cacheprovider -o addopts=`. En los pasos, `PYTEST` = eso sin la ruta.
- Alembic: `docker compose -f docker/compose/docker-compose.dev.yml exec backend alembic -c migrations/alembic.ini upgrade head`, **antes** de la corrida en verde de Task 1.
- Commits con `GIT_AUTHOR_NAME/EMAIL` y `GIT_COMMITTER_NAME/EMAIL` = `Deig0l` / `deigolsalazar@gmail.com` y la línea `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Nunca `git add -A` ni `git add .`.
- CRLF: `models/__init__.py`, `router.py` (copia de trabajo), `pages/router.py`, `itcj2/models/__init__.py`, `itcj2/cli/prorrogas.py`, `docs/README.md` y `docs/PENDIENTES.md`. Se editan conservando CRLF (`cat -A`).
- Las pruebas corren dentro de un SAVEPOINT (`join_transaction_mode="create_savepoint"`): un `commit()` de un servicio libera el savepoint y un `rollback()` descarta solo lo no commiteado.

**Valores del spec (§5, §16)**

- **Hoy** = `db_now().date()`. Todo servicio acepta `now=None` para las pruebas. `now` puede ser `date` o `datetime`: hoy = `now.date()` si es `datetime`, y las marcas de tiempo usan `datetime.combine(now, time())` si es `date`.
- **Dinero:**
  - `Decimal` en Python, `Numeric(10,2)` en la BD y cadenas con dos decimales en el JSON (`"3650.00"`).
  - La entrada se valida con `parse_monto(raw) -> Decimal` (Task 2): acepta número o cadena; rechaza NaN o infinito, más de 2 decimales, comas y ≤ 0 → `monto_invalido`.
  - El formato para personas es `pesos()` (Plan 1): `$3,650.00`.
- **Reparto por omisión:** `split_amount(total, n)` (Plan 1) da $3,650 en 3 → $1,217 · $1,217 · $1,216.
- **Situación**, calculada al leer:
  - `sin_plan`: aceptada sin plan.
  - `liquidada`: pagado ≥ total.
  - `atrasada`: alguna parcialidad vigente con fecha < hoy y no cubierta.
  - `al_corriente`: lo demás.
  - Los filtros de la vista: `todos`, `con_adeudo` (= `atrasada`), `al_corriente`, `sin_plan`, `liquidada`.
- **Aplicación FIFO:** los recibos vigentes cubren en orden la parcialidad vigente más vieja. Solo importa la **suma** de lo pagado, no el orden de los recibos.
- **Estado de una parcialidad**, en este orden:
  - `pagada` (cubierto = monto)
  - `vencida` (fecha < hoy y no cubierta)
  - `parcial` (0 < cubierto < monto)
  - `pendiente`
- **Plan:**
  - Total > 0, y **total = suma de las parcialidades vigentes**.
  - Entre 1 y 3 parcialidades vigentes.
  - Fechas estrictamente ascendentes, desde hoy y hasta el `end_date` del semestre de la solicitud.
- **Replantear (§16.3):**
  - Se conservan las parcialidades `pagada`. Las demás reciben `superseded_at`.
  - Las nuevas se numeran después de las conservadas. Conservadas + nuevas ≤ 3, y nuevas ≥ 1.
  - Total ≥ lo pagado.
  - Las fechas nuevas van después de la última conservada.
  - No se replantea una solicitud `liquidada`.
- **Carta compromiso:**
  - `carta_compromiso_{N}`, con N = parcialidades vigentes. Lista todas.
  - Extra: `monto_total`, y `pago{I}_monto` / `pago{I}_fecha` para I = 1…N.
  - Formatos: `pesos()` y `fecha_larga()`.
- **Firma (§16.4):**
  - Vuelve a llenar desde `doc.context` y con la **misma** plantilla del documento: la de `doc.template_id`, o la del sistema si es `None`.
  - La leyenda usa `context["nombre"]`.
  - Crea la versión siguiente y sustituye la anterior. No bloquea nada.
- **Recibos:**
  - Requieren plan.
  - Folio de Caja: `strip()`, de 1 a 40 caracteres, **único entre recibos vigentes de todas las solicitudes**. Un folio anulado se puede volver a usar.
  - Monto ≤ saldo (sin sobrepago).
  - `created_at.date()` de la solicitud ≤ fecha de pago ≤ hoy.
  - Anular pide motivo (5 a 500 caracteres después de `strip()`). Nunca se borra.
- **Recordar:** solo con plan y saldo > 0; una vez cada 24 h por solicitud (`last_reminded_at`).
- **Lista de bloqueo (§16.1):** las `atrasada` del semestre elegido al momento de exportar.
  - `.xlsx` con el encabezado, la línea del criterio y las 10 columnas de §16.1, con encabezados congelados y filtro.
  - Pone `block_exported_at` solo si estaba vacío.
- **Avisar desbloqueo (§16.2):** solo con `block_exported_at`, situación `liquidada` y `unblock_notified_at` vacío.
- **Eventos nuevos** (`services/events.py`, `EVENT_TYPES`): `plan_confirmado`, `recibo_registrado`, `recibo_anulado`, `documento_firmado`, `recordatorio_enviado`, `lista_bloqueo_exportada`, `desbloqueo_avisado`.
- **Avisos nuevos** (`notify_student`):
  - `carta_lista`: "Tu carta compromiso está lista para firmar".
  - `recordatorio`: "Recordatorio de pago de tu prórroga".
  - Liga `/prorrogas/estudiante` (absoluta en el correo, como en el Plan 2).
- **Códigos de error:**

  | Estado | Códigos |
  |---|---|
  | 404 | `no_encontrada`, `recibo_no_encontrado` |
  | 409 | `no_aceptada`, `ya_liquidada`, `sin_plan`, `folio_duplicado`, `ya_anulado`, `documento_no_vigente`, `no_firmable`, `ya_firmado`, `sin_saldo`, `ya_recordado`, `no_aplica` |
  | 400 | `monto_invalido`, `total_menor_que_pagado`, `plazos_invalidos`, `suma_no_cuadra`, `fechas_invalidas`, `folio_invalido`, `sobrepago`, `fecha_invalida`, `motivo_requerido` |
  | 503 | `pdf_no_disponible` |

  Más los `firma_*` del Plan 2.
- **Concurrencia:** todo servicio que cambia una solicitud o lee su saldo para decidir la bloquea primero con `.populate_existing().with_for_update()`: plan, recibo, firma, recordar y desbloqueo. Igual que `decide` en el Plan 2.

**Permisos nuevos** (`database/DML/prorrogas_tec/06_insert_plan3.sql`)

| Permiso | Rol |
|---|---|
| `prorrogas_tec.plans.api.manage` | secretaria, admin |
| `prorrogas_tec.payments.api.record` | secretaria, admin |
| `prorrogas_tec.payments.api.void` | secretaria, admin |
| `prorrogas_tec.students.api.remind` | secretaria, admin |
| `prorrogas_tec.students.api.export` | secretaria, admin |
| `prorrogas_tec.documents.api.sign.own` | student |

Leer la lista, el expediente y el reparto usa `prorrogas_tec.requests.api.read.all` (Plan 2).

## Decisiones de este plan (desviaciones del spec)

1. **Situación en memoria.** La lista calcula la cuenta de todas las aceptadas del semestre en Python y luego filtra y pagina. La escala es de cientos por semestre.
   - Se marca con `# shortcut: situación calculada en Python por semestre; pasar a SQL si un semestre supera ~2000 solicitudes`.
2. **"Imprimir" = abrir el PDF en una pestaña nueva** con la ruta de PDF del Plan 2. El navegador imprime; no hay impresión del lado del servidor.
3. **El reparto sugerido lo da el servidor** (`GET /estudiantes/reparto`), para no copiar `split_amount` en JS.
4. **Exportar adeudos es `POST`**, porque cambia `block_exported_at`. El JS arma la descarga con un `Blob`.
5. **La lista muestra las aceptadas de cualquier origen.** Las de Excel llegan en el Plan 4.
6. **`notify_student` gana `body` y `context` opcionales.** Las plantillas de correo pasan a un mapa `kind → plantilla`. Lo existente (aceptada/rechazada) no cambia.
7. **El lienzo de firma se mueve a `static/js/estudiante/firma.js`.** Lo comparten la solicitud y *Mi prórroga*.

## Review Focus

1. **Sobrepago por carrera:** dos recibos registrados a la vez deben dejar uno en 400 `sobrepago`, no los dos dentro.
   - Lo cubren el candado en `PaymentService.record` y `test_segundo_recibo_que_excede_el_saldo_es_sobrepago` (Task 5).
2. **Anular un recibo después de un replanteo:** la parcialidad conservada que cubría vuelve a quedar sin cubrir. La situación se recalcula (`atrasada` si su fecha pasó) y se puede replantear otra vez.
   - Lo cubren `test_anular_regresa_la_situacion` (Task 5) y `test_conservadas_vienen_de_la_cuenta_actual` (Task 4).
3. **Folio de Caja repetido:** el mismo folio en otra solicitud da 409. Después de anularlo, se puede volver a usar.
   - Lo cubre `test_folio_unico_entre_vigentes_y_reusable_tras_anular` (Task 5).
4. **Replantear con una parcialidad pagada a medias:** esa se sustituye y su dinero cubre la primera nueva. Un total menor a lo pagado o más de 3 parcialidades se rechazan.
   - Lo cubren `test_replantear_conserva_lo_pagado_y_reparte_lo_que_falta` y `test_replanteos_invalidos` (Task 4).
5. **Firmar una carta que un replanteo ya sustituyó** da 409 `documento_no_vigente`. La firma usa el contexto congelado aunque el nombre de la cuenta haya cambiado.
   - Lo cubren `test_firma_usa_el_contexto_congelado` y `test_carta_sustituida_no_se_firma` (Task 6).

---

### Task 1: Esquema de plan y recibos, eventos y permisos

**Files:**
- Create:
  - `migrations/versions/pr20261031a_prorrogas_pagos.py` (`revision = "pr20261031a"`, `down_revision = "pr20261030a"`)
  - `itcj2/apps/prorrogas_tec/models/plan.py`
  - `database/DML/prorrogas_tec/06_insert_plan3.sql` (no se commitea)
- Modify:
  - `itcj2/apps/prorrogas_tec/models/request.py`, `models/__init__.py` (CRLF)
  - `itcj2/models/__init__.py` (CRLF): importar los dos modelos nuevos
  - `services/events.py`
  - `itcj2/cli/prorrogas.py` (CRLF): `_DML_FILES` += `"06_insert_plan3.sql"`, y una línea en el docstring
  - `tests/fastapi/prorrogas_tec/conftest.py`
  - `tests/fastapi/prorrogas_tec/test_schema.py` (`NUEVAS` += `prorrogas_installments`, `prorrogas_payments`)
- Test: `tests/fastapi/prorrogas_tec/test_plan_schema.py`

**Interfaces:**
- Produces:
  - **`ProrrogaRequest`, columnas nuevas:**
    - `total_amount` `Numeric(10,2)`, nulo; con `CHECK total_amount IS NULL OR total_amount > 0` (`ck_prorrogas_requests_total`)
    - `plan_confirmed_at` (`DateTime`) y `plan_confirmed_by_id` (FK `core_users`, `SET NULL`)
    - `block_exported_at`, `unblock_notified_at` y `last_reminded_at` (`DateTime`)
  - **`ProrrogaInstallment`** (`prorrogas_installments`):
    - `id` `BigInteger`
    - `request_id` FK a `prorrogas_requests`, `CASCADE`, no nulo
    - `number` `SmallInteger`, con `CHECK 1..3`
    - `amount` `Numeric(10,2)`, con `CHECK > 0`
    - `due_date` `Date`
    - `created_at`, con `server_default NOW()`
    - `superseded_at`, nulo
    - Índice único parcial `uq_prorrogas_installments_vigente (request_id, number) WHERE superseded_at IS NULL`
  - **`ProrrogaPayment`** (`prorrogas_payments`):
    - `id`
    - `request_id` FK, `CASCADE`
    - `origin` `String(10)`, con `server_default 'app'` y `CHECK IN ('app','excel')`
    - `folio` `String(40)`, nulo (solo Excel)
    - `paid_on` `Date`
    - `amount` `Numeric(10,2)`, con `CHECK > 0`
    - `recorded_by_id` (`SET NULL`) y `recorded_at` (`NOW()`)
    - `voided_at`, `voided_by_id` (`SET NULL`) y `void_reason` `Text`
    - Índices `uq_prorrogas_payments_folio_vigente (folio) UNIQUE WHERE folio IS NOT NULL AND voided_at IS NULL` y `ix_prorrogas_payments_solicitud (request_id)`
  - `EVENT_TYPES` += los 7 eventos de las Global Constraints.
  - **Fixtures:**
    - `SECRETARIA_PERMS` += los 5 de secretaria y `STUDENT_PERMS` += `documents.api.sign.own`.
    - `make_aceptada(control_number=None) -> ProrrogaRequest`: alumno sintético más solicitud `aceptada` en `periodo`, con flush y refresh. Usa control `99410xxx` por secuencia, para no chocar con `solicitud` (`99400001`).
    - `aceptada`: `make_aceptada()`.

- [ ] **Step 1: Write the failing test**

```python
from datetime import date, datetime
from decimal import Decimal as D

import pytest
from sqlalchemy.exc import IntegrityError

from itcj2.apps.prorrogas_tec.models.plan import ProrrogaInstallment, ProrrogaPayment
from itcj2.apps.prorrogas_tec.services.events import EVENT_TYPES


def test_una_sola_parcialidad_vigente_por_numero(db_session, aceptada):
    db_session.add(ProrrogaInstallment(request_id=aceptada.id, number=1, amount=D("100.00"), due_date=date(2091, 2, 1)))
    db_session.flush()
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(ProrrogaInstallment(request_id=aceptada.id, number=1, amount=D("5.00"),
                                               due_date=date(2091, 3, 1)))
            db_session.flush()


def test_folio_unico_entre_vigentes(db_session, aceptada, make_aceptada):
    otra = make_aceptada()
    p = ProrrogaPayment(request_id=aceptada.id, folio="C-1", paid_on=date(2091, 2, 1), amount=D("10.00"))
    db_session.add(p)
    db_session.flush()
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(ProrrogaPayment(request_id=otra.id, folio="C-1", paid_on=date(2091, 2, 1), amount=D("10.00")))
            db_session.flush()
    p.voided_at = datetime(2091, 2, 2)
    db_session.flush()
    db_session.add(ProrrogaPayment(request_id=otra.id, folio="C-1", paid_on=date(2091, 2, 1), amount=D("10.00")))
    db_session.flush()


def test_eventos_del_plan_3():
    assert {"plan_confirmado", "recibo_registrado", "recibo_anulado", "documento_firmado",
            "recordatorio_enviado", "lista_bloqueo_exportada", "desbloqueo_avisado"} <= EVENT_TYPES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_plan_schema.py`
Expected: FAIL con `ImportError` (no existe `models/plan.py`).

- [ ] **Step 3: Implement the models, the migration, the events, the DML, the CLI line and the fixtures**

- La migración crea las dos tablas y agrega las 6 columnas y el CHECK de `prorrogas_requests`. Los nombres son idénticos a los de los modelos (el CI arma el esquema con `create_all`).
- El `downgrade` quita todo en orden inverso.
- El DML 06 copia la forma de `05_insert_plan2.sql`: `ON CONFLICT`, roles `secretaria`, `admin` y `student`, y `RAISE EXCEPTION` si falta la app o un rol.
- Corre `docker compose -f docker/compose/docker-compose.dev.yml exec backend alembic -c migrations/alembic.ini upgrade head`.
- Corre `docker compose -f docker/compose/docker-compose.dev.yml exec backend python -m itcj2.cli.main prorrogas init-prorrogas`. Debe decir 7/7.

- [ ] **Step 4: Run the tests**

Run: `PYTEST tests/fastapi/prorrogas_tec`
Expected: PASS. Incluye `test_schema.py` con las tablas nuevas y `test_permissions_contract.py`.

- [ ] **Step 5: Commit**

```bash
git add migrations/versions/pr20261031a_prorrogas_pagos.py itcj2/apps/prorrogas_tec/models/plan.py itcj2/apps/prorrogas_tec/models/request.py itcj2/apps/prorrogas_tec/models/__init__.py itcj2/models/__init__.py itcj2/apps/prorrogas_tec/services/events.py itcj2/cli/prorrogas.py tests/fastapi/prorrogas_tec/conftest.py tests/fastapi/prorrogas_tec/test_schema.py tests/fastapi/prorrogas_tec/test_plan_schema.py
git commit -m "feat(prorrogas): esquema de parcialidades y recibos, eventos y permisos del Plan 3"
```

---

### Task 2: La cuenta del estudiante (cálculo puro y carga)

**Files:**
- Create: `itcj2/apps/prorrogas_tec/services/account.py`
- Modify:
  - `services/formatting.py`: `parse_monto`
  - `tests/fastapi/prorrogas_tec/conftest.py`: `con_plan`
- Test: `tests/fastapi/prorrogas_tec/test_account.py`

**Interfaces:**
- Consumes: los modelos de Task 1.
- Produces:
  - `parse_monto(raw) -> Decimal` en `formatting.py`. Lanza `ServiceError("monto_invalido", …, status=400)`.
  - `@dataclass(frozen=True) Parcialidad(number: int, amount: Decimal, due_date: date, cubierto: Decimal, estado: str)`
  - `@dataclass(frozen=True) Cuenta`, con los campos:
    - `total: Decimal | None`
    - `pagado: Decimal`
    - `saldo: Decimal | None`
    - `parcialidades: tuple[Parcialidad, ...]`
    - `situacion: str`
    - `faltantes: int`: parcialidades con cubierto < monto
    - `vencida_desde: date | None`: la fecha más vieja `vencida`
    - `proxima: Parcialidad | None`: la primera no cubierta
  - `cuenta(total: Decimal | None, installments: Sequence[tuple[int, Decimal, date]], pagado: Decimal, today: date) -> Cuenta`. Es pura: no toca la BD.
  - `cuenta_json(c: Cuenta) -> dict`: `{"total", "pagado", "saldo", "situacion", "faltantes", "vencida_desde", "proxima", "parcialidades": [{"numero", "monto", "fecha", "cubierto", "estado"}]}`. Los montos van como cadenas con 2 decimales y las fechas en ISO. Lo usan Tasks 3, 6 y 9.
  - `load(db, req, today: date) -> Cuenta` y `load_many(db, reqs, today: date) -> dict[int, Cuenta]`. Leen solo las parcialidades vigentes y la suma de los recibos no anulados; `load_many` lo hace en 2 consultas en total.
  - **Fixture `con_plan(req, parcialidades: list[tuple[str, date]], pagos: list[str] = ())`:** inserta las parcialidades vigentes (numeradas 1…) y los recibos, pone `total_amount` = suma y hace flush. Devuelve `req`.
    - Los folios son `T-{n}` con el contador `_seq` del conftest: nunca se repiten, ni entre solicitudes ni dentro de una prueba.
    - Los recibos tienen `paid_on` = `created_at.date()` de la solicitud.

- [ ] **Step 1: Write the failing test**

```python
from datetime import date, datetime
from decimal import Decimal as D

import pytest

from itcj2.apps.prorrogas_tec.services.account import cuenta, load, load_many
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.formatting import parse_monto

PLAN = [(1, D("1217.00"), date(2091, 2, 1)), (2, D("1217.00"), date(2091, 3, 1)), (3, D("1216.00"), date(2091, 4, 1))]


def test_sin_plan():
    c = cuenta(None, [], D("0"), date(2091, 3, 1))
    assert c.situacion == "sin_plan" and c.saldo is None and c.faltantes == 0


def test_pago_parcial_cubre_en_orden_y_la_que_vence_hoy_no_atrasa():
    c = cuenta(D("3650.00"), PLAN, D("1500.00"), date(2091, 3, 1))
    assert [p.estado for p in c.parcialidades] == ["pagada", "parcial", "pendiente"]
    assert c.parcialidades[1].cubierto == D("283.00") and c.saldo == D("2150.00")
    assert c.situacion == "al_corriente" and c.faltantes == 2 and c.proxima.number == 2


def test_atrasada_desde_la_mas_vieja():
    c = cuenta(D("3650.00"), PLAN, D("0"), date(2091, 3, 2))
    assert [p.estado for p in c.parcialidades] == ["vencida", "vencida", "pendiente"]
    assert c.situacion == "atrasada" and c.vencida_desde == date(2091, 2, 1)


def test_dos_parcialidades_de_un_jalon_y_liquidada():
    assert [p.estado for p in cuenta(D("3650.00"), PLAN, D("2434.00"), date(2091, 3, 5)).parcialidades] == \
        ["pagada", "pagada", "pendiente"]
    c = cuenta(D("3650.00"), PLAN, D("3650.00"), date(2091, 5, 1))
    assert c.situacion == "liquidada" and c.faltantes == 0 and c.proxima is None


@pytest.mark.parametrize("raw", ["0", "-5", "12.345", "1,217", "abc", "NaN", None])
def test_monto_invalido(raw):
    with pytest.raises(ServiceError) as e:
        parse_monto(raw)
    assert e.value.code == "monto_invalido"


def test_parse_monto_acepta_numero_y_cadena():
    assert parse_monto("1217.5") == D("1217.50") and parse_monto(1217) == D("1217.00")


def test_load_many_ignora_sustituidas_y_anuladas(db_session, aceptada, make_aceptada, con_plan):
    con_plan(aceptada, [("1000.00", date(2020, 1, 1)), ("500.00", date(2091, 5, 1))], pagos=["1000.00", "200.00"])
    from itcj2.apps.prorrogas_tec.models.plan import ProrrogaPayment
    db_session.query(ProrrogaPayment).filter_by(request_id=aceptada.id, amount=D("200.00")).update(
        {"voided_at": datetime(2091, 1, 2)})
    otra = make_aceptada()
    hoy = date(2091, 3, 1)
    cuentas = load_many(db_session, [aceptada, otra], hoy)
    assert cuentas[aceptada.id].pagado == D("1000.00") and cuentas[otra.id].situacion == "sin_plan"
    assert load(db_session, aceptada, hoy) == cuentas[aceptada.id]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_account.py`
Expected: FAIL con `ImportError`.

- [ ] **Step 3: Implement `account.py`, `parse_monto` and `con_plan`**

`cuenta` reparte `pagado` en orden de `number`; el estado de cada parcialidad sigue el orden de las Global Constraints. `parse_monto` usa `Decimal(str(raw))`, revisa `is_finite()` y `as_tuple().exponent >= -2`, y devuelve `quantize(Decimal("0.01"))`.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_account.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add itcj2/apps/prorrogas_tec/services/account.py itcj2/apps/prorrogas_tec/services/formatting.py tests/fastapi/prorrogas_tec/conftest.py tests/fastapi/prorrogas_tec/test_account.py
git commit -m "feat(prorrogas): cuenta del estudiante con aplicacion FIFO y situacion"
```

---

### Task 3: Lista de Estudiantes y expediente (servicio y API de lectura)

**Files:**
- Create:
  - `itcj2/apps/prorrogas_tec/services/students_service.py`
  - `itcj2/apps/prorrogas_tec/api/students_admin.py`
- Modify: `router.py` (`include_router(students_admin, prefix="/estudiantes")`)
- Test: `tests/fastapi/prorrogas_tec/test_students_api.py`

**Interfaces:**
- Consumes: `account.load_many/load/cuenta_json` (Task 2), `RequestService.request_out` (Plan 2), `period_for` y `period_label` (Plan 2), `ProrrogaEvent`.
- Produces:
  - **`StudentsService.periodos(db, today) -> dict`:** `{"items": [{"id", "label"}], "actual": id | None}`.
    - `items` son los semestres que tienen al menos una solicitud `aceptada`, del más nuevo al más viejo.
    - `actual` es `period_for(today)` si está en `items`; si no, el primero.
  - **`StudentsService.listar(db, period_id, *, q=None, filtro="todos", page=1, per_page=25, today) -> dict`:**
    - Devuelve `{"items", "total", "page", "per_page", "conteos": {"todos", "con_adeudo", "al_corriente", "sin_plan", "liquidada"}}`.
    - Toma solo las `aceptada` del semestre.
    - `q` filtra por `control_number` o `student_name`, sin distinguir mayúsculas.
    - Ordena por `student_name`. `per_page` va de 1 a 100.
    - `conteos` se calcula antes del filtro de situación, pero después de `q`.
    - Cada `item`:
      - `{"id", "folio", "control", "nombre", "situacion", "faltantes", "vencida_desde"}`
      - `"pagos"`: el estado de cada parcialidad vigente
      - `"pagados"`: cuántas están `pagada`
      - `"puede_recordar"`: hay plan, saldo > 0 y no hubo recordatorio en las últimas 24 h
      - `"avisar_desbloqueo"`
  - **`StudentsService.expediente(db, request_id, today) -> dict`.** Lanza 404 `no_encontrada` si no existe o no está `aceptada`. Devuelve:
    - `"solicitud"`: `request_out`.
    - `"estudiante"`: `{"nombre", "control", "correo", "carrera"}`, de la copia congelada.
    - `"cuenta"`: `cuenta_json`.
    - `"recibos"`: todos, también los anulados, del más nuevo al más viejo. Cada uno trae `{"id", "folio", "fecha", "monto", "registrado", "anulado", "motivo_anulacion"}`.
    - `"carta"`: `{"doc_id", "tipo", "version", "firmada"}` de la `carta_compromiso_*` vigente, o `None`.
    - `"plan"`:
      - `"confirmado"`: ISO, o `None`.
      - `"puede_replantear"`: es `False` si está liquidada o si hoy > `end_date`.
      - `"conservadas"`: los números de las parcialidades `pagada`.
      - `"suma_conservadas"`: la suma de las conservadas, en cadena. Las nuevas deben sumar `total − suma_conservadas`.
      - `"max_nuevas"`: `3 − len(conservadas)`.
      - `"fecha_limite"`: el `end_date` del semestre, en ISO.
    - `"bloqueo"`: `{"exportada", "avisar_desbloqueo", "avisado"}`.
    - `"recordatorio"`: `{"ultimo", "puede"}`.
    - `"historial"`: los eventos de la solicitud, del más nuevo al más viejo, como `{"tipo", "fecha", "datos"}`.
  - **API** (`/api/prorrogas/v2/estudiantes`, todas con `requests.api.read.all`):
    - `GET /periodos`
    - `GET ""` con `period_id` (obligatorio), `q`, `filtro`, `page` y `per_page`. Un `filtro` fuera del conjunto da 400 `filtro_invalido`.
    - `GET /{request_id}` → expediente.

- [ ] **Step 1: Write the failing test**

```python
from datetime import date

API = "/api/prorrogas/v2/estudiantes"


def test_lista_con_situacion_pagos_y_conteos(client_as, secretaria, aceptada, make_aceptada, con_plan, periodo):
    con_plan(aceptada, [("1000.00", date(2020, 1, 1)), ("1000.00", date(2091, 5, 1))], pagos=["400.00"])
    al_dia = con_plan(make_aceptada(), [("500.00", date(2091, 5, 1))])
    r = client_as(secretaria).get(f"{API}?period_id={periodo.id}&per_page=100")
    assert r.status_code == 200
    filas = {i["id"]: i for i in r.json()["items"]}
    assert filas[aceptada.id]["situacion"] == "atrasada" and filas[aceptada.id]["pagos"] == ["vencida", "pendiente"]
    assert filas[al_dia.id]["situacion"] == "al_corriente" and filas[al_dia.id]["pagados"] == 0
    assert r.json()["conteos"]["con_adeudo"] >= 1
    solo = client_as(secretaria).get(f"{API}?period_id={periodo.id}&filtro=con_adeudo&per_page=100").json()["items"]
    assert aceptada.id in [i["id"] for i in solo] and al_dia.id not in [i["id"] for i in solo]


def test_busqueda_por_control(client_as, secretaria, aceptada, periodo):
    items = client_as(secretaria).get(f"{API}?period_id={periodo.id}&q={aceptada.control_number}").json()["items"]
    assert [i["id"] for i in items] == [aceptada.id]


def test_expediente(client_as, secretaria, aceptada, con_plan):
    con_plan(aceptada, [("1000.00", date(2091, 2, 1)), ("2000.00", date(2091, 4, 1))], pagos=["1000.00"])
    e = client_as(secretaria).get(f"{API}/{aceptada.id}").json()
    assert e["cuenta"]["saldo"] == "2000.00" and e["plan"]["conservadas"] == [1] and e["plan"]["max_nuevas"] == 2
    assert e["recibos"][0]["folio"].startswith("T-") and e["carta"] is None and e["bloqueo"]["avisar_desbloqueo"] is False


def test_pendiente_no_tiene_expediente_y_el_estudiante_no_entra(client_as, secretaria, estudiante, solicitud):
    assert client_as(secretaria).get(f"{API}/{solicitud.id}").status_code == 404
    assert client_as(estudiante).get(f"{API}/{solicitud.id}").status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_students_api.py`
Expected: FAIL (404: la ruta no existe).

- [ ] **Step 3: Implement the service, the API and the mount**

Primero se filtra por `q`, luego `load_many` para todo el semestre (con el comentario `shortcut:` de las Decisiones), luego se cuenta, se filtra por situación y se pagina.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_students_api.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add itcj2/apps/prorrogas_tec/services/students_service.py itcj2/apps/prorrogas_tec/api/students_admin.py itcj2/apps/prorrogas_tec/router.py tests/fastapi/prorrogas_tec/test_students_api.py
git commit -m "feat(prorrogas): lista de estudiantes por semestre y expediente"
```

---

### Task 4: Plan de pagos y replanteo (servicio y API)

**Files:**
- Create:
  - `itcj2/apps/prorrogas_tec/services/plan_service.py`
  - `templates/prorrogas_tec/email/carta_lista.html`
- Modify:
  - `services/notify.py`: mapa `kind → (título, plantilla)` y los parámetros `body=None, context=None`
  - `api/students_admin.py`
  - `tests/fastapi/prorrogas_tec/conftest.py`: la lambda de `avisos` acepta `**kw`
- Test: `tests/fastapi/prorrogas_tec/test_plan.py`

**Interfaces:**
- Consumes:
  - `account.load` (Task 2)
  - `DocumentService.generate(db, req, doc_type, *, actor_id, today, extra)` (Plan 2)
  - `split_amount`, `pesos` y `fecha_larga` (Plan 1)
  - `notify.notify_student`
- Produces:
  - **`notify_student(db, req, *, kind, link, body=None, context=None)`.** Los kinds `aceptada` y `rechazada` se comportan igual que antes. `carta_lista` lleva el cuerpo "Entra a Mi prórroga para firmarla." y la plantilla `carta_lista.html`.
  - **`PlanService.reparto(total, n: int) -> list[Decimal]`.** Valida `parse_monto` y que n esté entre 1 y 3 (`plazos_invalidos`).
  - **`PlanService.confirm(db, request_id, actor_id, *, total: Decimal, parcialidades: list[tuple[Decimal, date]], now=None) -> ProrrogaRequest`.** En este orden:
    1. Bloquea la solicitud.
    2. Valida en el orden de errores: `no_encontrada`, `no_aceptada`, `ya_liquidada`, `monto_invalido`, `total_menor_que_pagado`, `plazos_invalidos`, `suma_no_cuadra`, `fechas_invalidas`.
    3. Pone `superseded_at = now` a las vigentes no conservadas y crea las nuevas.
    4. Llena `total_amount`, `plan_confirmed_at/_by_id` y `updated_at`.
    5. Genera `carta_compromiso_{N}` y pone `superseded_at` a cualquier otra `carta_compromiso_*` vigente de otro N (`generate` solo sustituye las del mismo tipo).
    6. Registra `plan_confirmado`, con payload `{"total", "conservadas", "parcialidades": [{"numero", "monto", "fecha"}]}`.
    7. Hace commit.
    8. Llama `notify_student(kind="carta_lista", link="/prorrogas/estudiante")` y hace commit otra vez. Si ese commit falla, registra y hace rollback.
    - Si la carta da `pdf_no_disponible`: rollback y se propaga el 503.
  - **API:**
    - `GET /estudiantes/reparto?total=&n=` (`requests.api.read.all`) → `{"montos": ["1217.00", …]}`.
    - `POST /estudiantes/{id}/plan` (`plans.api.manage`), con JSON `{"total": str|num, "parcialidades": [{"monto": str|num, "fecha": "YYYY-MM-DD"}]}`. Responde con el expediente (Task 3).

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from decimal import Decimal as D

import pytest

from itcj2.apps.prorrogas_tec.models.plan import ProrrogaInstallment
from itcj2.apps.prorrogas_tec.services.document_service import DocumentService
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.plan_service import PlanService

pytestmark = pytest.mark.usefixtures("pdf_falso")
TRES = [(D("1217"), date(2091, 2, 1)), (D("1217"), date(2091, 3, 1)), (D("1216"), date(2091, 4, 1))]


def _cartas(db, req):
    return [d for d in DocumentService.current(db, req) if d.doc_type.startswith("carta_compromiso_")]


def test_primer_plan_genera_la_carta_y_avisa(db_session, aceptada, secretaria, avisos):
    req = PlanService.confirm(db_session, aceptada.id, secretaria.id, total=D("3650"), parcialidades=TRES,
                              now=date(2026, 11, 1))
    carta, = _cartas(db_session, req)
    assert carta.doc_type == "carta_compromiso_3" and carta.context["monto_total"] == "$3,650.00"
    assert carta.context["pago3_monto"] == "$1,216.00" and carta.context["pago1_fecha"] == "01 de febrero de 2091"
    assert req.total_amount == D("3650.00") and [a[0] for a in avisos.calls] == ["carta_lista"]


def test_reparto_por_omision():
    assert PlanService.reparto("3650", 3) == [D("1217"), D("1217"), D("1216")]


def test_replantear_conserva_lo_pagado_y_reparte_lo_que_falta(db_session, aceptada, secretaria, avisos, con_plan):
    con_plan(aceptada, [("1217.00", date(2091, 2, 1)), ("1217.00", date(2091, 3, 1)), ("1216.00", date(2091, 4, 1))],
             pagos=["1500.00"])  # la 1 pagada, la 2 a medias
    req = PlanService.confirm(db_session, aceptada.id, secretaria.id, total=D("3650"),
                              parcialidades=[(D("2433"), date(2091, 5, 1))], now=date(2026, 11, 1))
    vigentes = (db_session.query(ProrrogaInstallment).filter_by(request_id=req.id, superseded_at=None)
                .order_by(ProrrogaInstallment.number).all())
    assert [(v.number, v.amount) for v in vigentes] == [(1, D("1217.00")), (2, D("2433.00"))]
    assert db_session.query(ProrrogaInstallment).filter(ProrrogaInstallment.request_id == req.id,
                                                        ProrrogaInstallment.superseded_at.isnot(None)).count() == 2
    assert [d.doc_type for d in _cartas(db_session, req)] == ["carta_compromiso_2"]


def test_replanteo_sustituye_la_carta_anterior_aunque_cambie_n(db_session, aceptada, secretaria, avisos):
    PlanService.confirm(db_session, aceptada.id, secretaria.id, total=D("3650"), parcialidades=TRES,
                        now=date(2026, 11, 1))
    req = PlanService.confirm(db_session, aceptada.id, secretaria.id, total=D("3650"),
                              parcialidades=[(D("3650"), date(2091, 5, 1))], now=date(2026, 11, 1))
    assert [d.doc_type for d in _cartas(db_session, req)] == ["carta_compromiso_1"]


@pytest.mark.parametrize("total, nuevas, code", [
    (D("1000"), [(D("1000"), date(2091, 5, 1))], "total_menor_que_pagado"),       # pagado 1500
    (D("3650"), [(D("800"), date(2091, 5, 1)), (D("800"), date(2091, 5, 2)), (D("833"), date(2091, 5, 3))],
     "plazos_invalidos"),                                                          # 1 conservada + 3 nuevas
    (D("3650"), [(D("2000"), date(2091, 5, 1))], "suma_no_cuadra"),
    (D("3650"), [(D("2433"), date(2091, 1, 15))], "fechas_invalidas"),             # antes de la conservada
    (D("3650"), [(D("2433"), date(2091, 7, 1))], "fechas_invalidas"),              # después del fin de semestre
])
def test_replanteos_invalidos(db_session, aceptada, secretaria, avisos, con_plan, total, nuevas, code):
    con_plan(aceptada, [("1217.00", date(2091, 2, 1)), ("2433.00", date(2091, 3, 1))], pagos=["1500.00"])
    with pytest.raises(ServiceError) as e:
        PlanService.confirm(db_session, aceptada.id, secretaria.id, total=total, parcialidades=nuevas,
                            now=date(2026, 11, 1))
    assert e.value.code == code


def test_conservadas_vienen_de_la_cuenta_actual(db_session, aceptada, secretaria, avisos, con_plan):  # Review Focus 2
    con_plan(aceptada, [("1000.00", date(2091, 2, 1)), ("1000.00", date(2091, 3, 1))], pagos=[])
    req = PlanService.confirm(db_session, aceptada.id, secretaria.id, total=D("2000"),
                              parcialidades=[(D("2000"), date(2091, 4, 1))], now=date(2026, 11, 1))
    assert _cartas(db_session, req)[0].doc_type == "carta_compromiso_1"


def test_liquidada_no_se_replantea(db_session, aceptada, secretaria, con_plan):
    con_plan(aceptada, [("1000.00", date(2091, 2, 1))], pagos=["1000.00"])
    with pytest.raises(ServiceError) as e:
        PlanService.confirm(db_session, aceptada.id, secretaria.id, total=D("1000"),
                            parcialidades=[(D("1000"), date(2091, 4, 1))], now=date(2026, 11, 1))
    assert e.value.code == "ya_liquidada" and e.value.status == 409


def test_api_plan_y_permiso(client_as, secretaria, estudiante, aceptada, avisos):
    body = {"total": "3650", "parcialidades": [{"monto": "3650", "fecha": "2091-05-01"}]}
    r = client_as(secretaria).post(f"/api/prorrogas/v2/estudiantes/{aceptada.id}/plan", json=body)
    assert r.status_code == 200 and r.json()["carta"]["tipo"] == "carta_compromiso_1"
    assert client_as(estudiante).post(f"/api/prorrogas/v2/estudiantes/{aceptada.id}/plan", json=body).status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_plan.py`
Expected: FAIL con `ImportError`.

- [ ] **Step 3: Implement `plan_service.py`, the `notify` change, the email template, the routes and the `avisos` fixture**

Las conservadas salen de `account.load(...)` antes de cambiar nada. `now` puede llegar como `date` o como `datetime`: `today = now.date() if isinstance(now, datetime) else now`.

- [ ] **Step 4: Run the tests**

Run: `PYTEST tests/fastapi/prorrogas_tec`
Expected: PASS. Las pruebas de `notify` y de `decide` del Plan 2 siguen en verde.

- [ ] **Step 5: Commit**

```bash
git add itcj2/apps/prorrogas_tec/services/plan_service.py itcj2/apps/prorrogas_tec/services/notify.py itcj2/apps/prorrogas_tec/templates/prorrogas_tec/email/carta_lista.html itcj2/apps/prorrogas_tec/api/students_admin.py tests/fastapi/prorrogas_tec/conftest.py tests/fastapi/prorrogas_tec/test_plan.py
git commit -m "feat(prorrogas): plan de pagos y replanteo de lo que falta, con carta compromiso"
```

---

### Task 5: Recibos de Caja (registrar y anular)

**Files:**
- Create: `itcj2/apps/prorrogas_tec/services/payment_service.py`
- Modify: `api/students_admin.py`
- Test: `tests/fastapi/prorrogas_tec/test_payments.py`

**Interfaces:**
- Consumes: `account.load` y `parse_monto` (Task 2); `StudentsService.expediente` (Task 3).
- Produces:
  - **`PaymentService.record(db, request_id, actor_id, *, folio: str, paid_on: date, amount: Decimal, now=None) -> ProrrogaPayment`:**
    - Bloquea la solicitud.
    - Valida en este orden: `no_encontrada`, `no_aceptada`, `sin_plan`, `folio_invalido`, `monto_invalido`, `fecha_invalida`, `sobrepago`.
    - El folio repetido se revisa antes y además se atrapa el `IntegrityError` de `uq_prorrogas_payments_folio_vigente`: 409 `folio_duplicado`.
    - Registra `recibo_registrado`, con payload `{"folio", "monto", "fecha"}`, y hace commit.
  - **`PaymentService.void(db, payment_id, actor_id, *, motivo: str, now=None) -> ProrrogaPayment`:**
    - Bloquea el recibo y luego su solicitud.
    - Errores: `recibo_no_encontrado`, `ya_anulado`, `motivo_requerido`.
    - Registra `recibo_anulado` y hace commit.
  - **API**, ambas responden con el expediente:
    - `POST /estudiantes/{id}/recibos` (`payments.api.record`), con JSON `{"folio", "fecha", "monto"}`.
    - `POST /estudiantes/{id}/recibos/{payment_id}/anular` (`payments.api.void`), con JSON `{"motivo"}`. Si el recibo no es de esa solicitud: 404 `recibo_no_encontrado`.

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from decimal import Decimal as D

import pytest

from itcj2.apps.prorrogas_tec.services.account import load
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.payment_service import PaymentService

HOY = date(2091, 3, 10)


def _plan(con_plan, req):
    return con_plan(req, [("1000.00", date(2091, 2, 1)), ("1000.00", date(2091, 4, 1))])


def test_registrar_aplica_y_recalcula(db_session, aceptada, secretaria, con_plan):
    _plan(con_plan, aceptada)
    PaymentService.record(db_session, aceptada.id, secretaria.id, folio=" C-77 ", paid_on=date(2091, 3, 1),
                          amount=D("1000"), now=HOY)
    c = load(db_session, aceptada, HOY)
    assert c.pagado == D("1000.00") and c.situacion == "al_corriente"


def test_segundo_recibo_que_excede_el_saldo_es_sobrepago(db_session, aceptada, secretaria, con_plan):  # Review Focus 1
    _plan(con_plan, aceptada)
    PaymentService.record(db_session, aceptada.id, secretaria.id, folio="C-1", paid_on=HOY, amount=D("1500"), now=HOY)
    with pytest.raises(ServiceError) as e:
        PaymentService.record(db_session, aceptada.id, secretaria.id, folio="C-2", paid_on=HOY, amount=D("501"), now=HOY)
    assert e.value.code == "sobrepago"


def test_folio_unico_entre_vigentes_y_reusable_tras_anular(db_session, aceptada, make_aceptada, secretaria, con_plan):  # RF 3
    otra = _plan(con_plan, make_aceptada())
    _plan(con_plan, aceptada)
    p = PaymentService.record(db_session, aceptada.id, secretaria.id, folio="C-9", paid_on=HOY, amount=D("10"), now=HOY)
    with pytest.raises(ServiceError) as e:
        PaymentService.record(db_session, otra.id, secretaria.id, folio="C-9", paid_on=HOY, amount=D("10"), now=HOY)
    assert e.value.code == "folio_duplicado" and e.value.status == 409
    PaymentService.void(db_session, p.id, secretaria.id, motivo="Folio de otro alumno", now=HOY)
    PaymentService.record(db_session, otra.id, secretaria.id, folio="C-9", paid_on=HOY, amount=D("10"), now=HOY)


def test_anular_regresa_la_situacion(db_session, aceptada, secretaria, con_plan):  # Review Focus 2
    _plan(con_plan, aceptada)
    p = PaymentService.record(db_session, aceptada.id, secretaria.id, folio="C-3", paid_on=date(2091, 1, 20),
                              amount=D("1000"), now=HOY)
    PaymentService.void(db_session, p.id, secretaria.id, motivo="Monto equivocado", now=HOY)
    assert load(db_session, aceptada, HOY).situacion == "atrasada"
    with pytest.raises(ServiceError) as e:
        PaymentService.void(db_session, p.id, secretaria.id, motivo="otra vez", now=HOY)
    assert e.value.code == "ya_anulado"


@pytest.mark.parametrize("kw, code", [
    ({"folio": "  "}, "folio_invalido"), ({"folio": "X" * 41}, "folio_invalido"),
    ({"amount": D("0")}, "monto_invalido"), ({"paid_on": date(2091, 3, 11)}, "fecha_invalida"),
])
def test_recibo_invalido(db_session, aceptada, secretaria, con_plan, kw, code):
    _plan(con_plan, aceptada)
    datos = dict(folio="C-5", paid_on=HOY, amount=D("10"))
    datos.update(kw)
    with pytest.raises(ServiceError) as e:
        PaymentService.record(db_session, aceptada.id, secretaria.id, now=HOY, **datos)
    assert e.value.code == code


def test_sin_plan_no_hay_recibos(db_session, aceptada, secretaria):
    with pytest.raises(ServiceError) as e:
        PaymentService.record(db_session, aceptada.id, secretaria.id, folio="C-6", paid_on=HOY, amount=D("1"), now=HOY)
    assert e.value.code == "sin_plan"


def test_api_registrar_y_anular(client_as, secretaria, aceptada, con_plan):
    from itcj2.core.utils.timezone import db_now
    _plan(con_plan, aceptada)
    c = client_as(secretaria)
    e = c.post(f"/api/prorrogas/v2/estudiantes/{aceptada.id}/recibos",
               json={"folio": "C-8", "fecha": db_now().date().isoformat(), "monto": "250.50"}).json()
    rid = e["recibos"][0]["id"]
    assert e["cuenta"]["pagado"] == "250.50"
    e = c.post(f"/api/prorrogas/v2/estudiantes/{aceptada.id}/recibos/{rid}/anular", json={"motivo": "Duplicado"}).json()
    assert e["cuenta"]["pagado"] == "0.00" and e["recibos"][0]["anulado"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_payments.py`
Expected: FAIL con `ImportError`.

- [ ] **Step 3: Implement `payment_service.py` and the routes**

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_payments.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add itcj2/apps/prorrogas_tec/services/payment_service.py itcj2/apps/prorrogas_tec/api/students_admin.py tests/fastapi/prorrogas_tec/test_payments.py
git commit -m "feat(prorrogas): recibos de Caja con folio unico, sin sobrepago y anulacion"
```

---

### Task 6: Firma de la carta compromiso (servicio y API del estudiante)

**Files:**
- Modify:
  - `itcj2/apps/prorrogas_tec/services/document_service.py`: `sign`, y la parte de guardar versión pasa a un `_store` privado que usan `generate` y `sign`
  - `documents/values.py`: `leyenda(nombre, signed_at, folio)`, que usan `build_values` y `sign`
  - `api/student.py`
- Test: `tests/fastapi/prorrogas_tec/test_sign.py`

**Interfaces:**
- Consumes:
  - `parse_signature` y `SignatureInfo` (Plan 2)
  - `TemplateService.read_bytes` y `default_template_path` (Plan 1)
  - `account.load`, `cuenta_json` (Task 2) y `PlanService.confirm` (Task 4)
- Produces:
  - **`DocumentService.sign(db, doc, signature: SignatureInfo, *, actor_id) -> ProrrogaDocument`.** No hace commit. Pasos:
    1. `values = dict(doc.context)` con `firma_estudiante_leyenda = leyenda(doc.context["nombre"], signature.signed_at, doc.context["folio"])`.
    2. La plantilla es la de `doc.template_id` o la del sistema.
    3. Llena con la imagen de la firma y convierte.
    4. Guarda la versión siguiente firmada, con su `ProrrogaSignature`, y sustituye a `doc`.
    5. Registra `documento_firmado`.
    - Un error de conversión da 503 `pdf_no_disponible`.
  - **`POST /api/prorrogas/v2/estudiante/solicitudes/{id}/documentos/{doc_id}/firmar`** (`documents.api.sign.own`), con JSON `{"firma"}`:
    - Bloquea la solicitud.
    - Errores: 404 `no_encontrada` (ni la solicitud ni el documento son suyos); 409 `documento_no_vigente`, `no_firmable` (no es `carta_compromiso_*`) y `ya_firmado`; y los `firma_*` de `parse_signature`.
    - Hace commit y responde con `request_out`.
  - **`GET /estudiante/estado`**: cada solicitud gana:
    - `"cuenta"`: `cuenta_json`.
    - `"recibos"`: solo los vigentes, como `[{"folio", "fecha", "monto"}]`.
    - `"por_firmar"`: el `doc_id` de la carta vigente sin firma, o `None`.

- [ ] **Step 1: Write the failing test**

```python
import base64
from datetime import date
from decimal import Decimal as D

import pytest

from itcj2.apps.prorrogas_tec.services.document_service import DocumentService
from itcj2.apps.prorrogas_tec.services.plan_service import PlanService

pytestmark = pytest.mark.usefixtures("pdf_falso", "avisos")
URL = "/api/prorrogas/v2/estudiante/solicitudes/{rid}/documentos/{did}/firmar"


def _carta(db, req):
    return next(d for d in DocumentService.current(db, req) if d.doc_type.startswith("carta_compromiso_"))


def _plan(db, req, sec, total="1000"):
    PlanService.confirm(db, req.id, sec.id, total=D(total), parcialidades=[(D(total), date(2091, 5, 1))],
                        now=date(2026, 11, 1))
    return _carta(db, req)


def _firma(png):
    return {"firma": "data:image/png;base64," + base64.b64encode(png).decode()}


def test_firma_usa_el_contexto_congelado(db_session, client_as, aceptada, secretaria, grant, make_role, firma_png):  # RF 5
    from tests.fastapi.prorrogas_tec.conftest import STUDENT_PERMS
    from itcj2.core.models.user import User
    alumno = db_session.get(User, aceptada.student_id)
    grant(alumno, make_role("student", STUDENT_PERMS))
    carta = _plan(db_session, aceptada, secretaria)
    aceptada.student_name = "NOMBRE CAMBIADO"
    db_session.flush()
    r = client_as(alumno).post(URL.format(rid=aceptada.id, did=carta.id), json=_firma(firma_png))
    assert r.status_code == 200
    nueva = _carta(db_session, aceptada)
    assert nueva.version == carta.version + 1 and nueva.signed_at is not None
    assert nueva.context["nombre"] == carta.context["nombre"] != "NOMBRE CAMBIADO"
    assert carta.context["nombre"] in nueva.context["firma_estudiante_leyenda"]
    again = client_as(alumno).post(URL.format(rid=aceptada.id, did=nueva.id), json=_firma(firma_png))
    assert again.status_code == 409 and again.json()["error"] == "ya_firmado"


def test_carta_sustituida_no_se_firma(db_session, client_as, aceptada, secretaria, grant, make_role, firma_png):  # RF 5
    from tests.fastapi.prorrogas_tec.conftest import STUDENT_PERMS
    from itcj2.core.models.user import User
    alumno = db_session.get(User, aceptada.student_id)
    grant(alumno, make_role("student", STUDENT_PERMS))
    vieja = _plan(db_session, aceptada, secretaria)
    _plan(db_session, aceptada, secretaria, total="1200")          # replanteo: la vieja queda sustituida
    r = client_as(alumno).post(URL.format(rid=aceptada.id, did=vieja.id), json=_firma(firma_png))
    assert r.status_code == 409 and r.json()["error"] == "documento_no_vigente"


def test_estado_trae_cuenta_y_por_firmar(db_session, client_as, aceptada, secretaria, grant, make_role):
    from tests.fastapi.prorrogas_tec.conftest import STUDENT_PERMS
    from itcj2.core.models.user import User
    alumno = db_session.get(User, aceptada.student_id)
    grant(alumno, make_role("student", STUDENT_PERMS))
    carta = _plan(db_session, aceptada, secretaria)
    s = client_as(alumno).get("/api/prorrogas/v2/estudiante/estado").json()["solicitudes"][0]
    assert s["por_firmar"] == carta.id and s["cuenta"]["total"] == "1000.00" and s["recibos"] == []


def test_no_firma_lo_ajeno(db_session, client_as, aceptada, secretaria, estudiante, firma_png):
    carta = _plan(db_session, aceptada, secretaria)
    r = client_as(estudiante).post(URL.format(rid=aceptada.id, did=carta.id), json=_firma(firma_png))
    assert r.status_code == 404
```

`estudiante` ya tiene `STUDENT_PERMS` por Task 1, pero `aceptada` es de otro alumno: por eso el 404 prueba el filtro por dueño.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_sign.py`
Expected: FAIL (404: la ruta no existe).

- [ ] **Step 3: Implement `sign`, `_store`, `leyenda`, the route and the `estado` fields**

- [ ] **Step 4: Run the tests**

Run: `PYTEST tests/fastapi/prorrogas_tec`
Expected: PASS. `test_document_service.py` del Plan 2 sigue en verde después del refactor a `_store`.

- [ ] **Step 5: Commit**

```bash
git add itcj2/apps/prorrogas_tec/services/document_service.py itcj2/apps/prorrogas_tec/documents/values.py itcj2/apps/prorrogas_tec/api/student.py tests/fastapi/prorrogas_tec/test_sign.py
git commit -m "feat(prorrogas): el estudiante firma la carta compromiso con el contexto congelado"
```

---

### Task 7: Recordar, lista de adeudos (.xlsx) y avisar desbloqueo

**Files:**
- Modify:
  - `services/students_service.py`: `remind`, `export_adeudos`, `mark_unblock`
  - `api/students_admin.py`
- Create: `templates/prorrogas_tec/email/recordatorio.html`
- Test: `tests/fastapi/prorrogas_tec/test_students_actions.py`

**Interfaces:**
- Consumes: `account.load` y `load_many` (Task 2), `notify_student(..., body=, context=)` (Task 4), `pesos` y `fecha_larga`, y openpyxl.
- Produces:
  - **`StudentsService.remind(db, request_id, actor_id, *, now=None) -> ProrrogaRequest`:**
    - Bloquea la solicitud.
    - Errores: `no_encontrada`, `sin_plan`, `sin_saldo` y `ya_recordado` (si `last_reminded_at > now − 24 h`, con detalle `{"siguiente": ISO}`).
    - Pone `last_reminded_at = now`, registra `recordatorio_enviado` y hace commit.
    - Luego llama `notify_student(kind="recordatorio", link="/prorrogas/estudiante", body="Saldo {pesos}. Próximo pago: {fecha_larga} por {pesos}.", context={"saldo", "proxima_fecha", "proxima_monto"})` y hace commit otra vez.
  - **`StudentsService.export_adeudos(db, period_id, actor_id, *, now=None) -> tuple[bytes, str]`:**
    - Devuelve el `.xlsx` y el nombre de archivo `adeudos-prorrogas-{YYYYMMDD-HHMM}.xlsx`.
    - El libro tiene una hoja, "Adeudos":
      - Filas 1–5: título, semestre, "Exportado el {dd/mm/aaaa hh:mm}", el criterio de §16.1 con la fecha, y "Total de estudiantes: {n}".
      - Fila 7: los encabezados de §16.1, congelados en `A8` y con `auto_filter` en el rango.
      - Desde la fila 8: los datos. Los montos van como número con formato `"$#,##0.00"`; "Vencida desde" va como fecha.
      - Sin filas: una fila "Sin estudiantes con adeudo".
    - Pone `block_exported_at` solo a los incluidos que no lo tenían.
    - Registra `lista_bloqueo_exportada` (`request_id=None`, payload `{"period_id", "estudiantes"}`) y hace commit.
  - **`StudentsService.mark_unblock(db, request_id, actor_id, *, now=None)`:**
    - Bloquea la solicitud.
    - Si no aplica (§16.2): 409 `no_aplica`.
    - Pone `unblock_notified_at`, registra `desbloqueo_avisado` y hace commit.
  - **API:**
    - `POST /estudiantes/{id}/recordar` (`students.api.remind`) → expediente.
    - `POST /estudiantes/adeudos.xlsx` (`students.api.export`), con JSON `{"period_id"}`. Responde con el archivo, `media_type` `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` y `Content-Disposition: attachment`.
    - `POST /estudiantes/{id}/desbloqueo-avisado` (`students.api.export`) → expediente.

- [ ] **Step 1: Write the failing test**

```python
from datetime import date, datetime, timedelta
from io import BytesIO

import pytest
from openpyxl import load_workbook

from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.students_service import StudentsService

AHORA = datetime(2026, 11, 2, 10, 0)


def test_recordar_una_vez_al_dia(db_session, aceptada, secretaria, con_plan, avisos):
    con_plan(aceptada, [("1000.00", date(2020, 1, 1))])
    StudentsService.remind(db_session, aceptada.id, secretaria.id, now=AHORA)
    assert [a[0] for a in avisos.calls] == ["recordatorio"]
    with pytest.raises(ServiceError) as e:
        StudentsService.remind(db_session, aceptada.id, secretaria.id, now=AHORA + timedelta(hours=23))
    assert e.value.code == "ya_recordado"
    StudentsService.remind(db_session, aceptada.id, secretaria.id, now=AHORA + timedelta(hours=25))


def test_no_se_recuerda_sin_plan_ni_saldo(db_session, aceptada, make_aceptada, secretaria, con_plan, avisos):
    with pytest.raises(ServiceError) as e:
        StudentsService.remind(db_session, aceptada.id, secretaria.id, now=AHORA)
    assert e.value.code == "sin_plan"
    pagada = con_plan(make_aceptada(), [("10.00", date(2020, 1, 1))], pagos=["10.00"])
    with pytest.raises(ServiceError) as e:
        StudentsService.remind(db_session, pagada.id, secretaria.id, now=AHORA)
    assert e.value.code == "sin_saldo"


def test_excel_de_adeudos_se_explica_solo(db_session, aceptada, make_aceptada, secretaria, con_plan, periodo):
    con_plan(aceptada, [("1000.00", date(2020, 1, 1)), ("500.00", date(2091, 5, 1))], pagos=["200.00"])
    al_dia = con_plan(make_aceptada(), [("500.00", date(2091, 5, 1))])
    data, nombre = StudentsService.export_adeudos(db_session, periodo.id, secretaria.id, now=AHORA)
    ws = load_workbook(BytesIO(data)).active
    assert ws["A1"].value == "Lista de adeudos de prórrogas" and "02/11/2026" in ws["A3"].value
    assert "parcialidad vencida y no cubierta" in ws["A4"].value and ws.freeze_panes == "A8" and ws.auto_filter.ref
    assert [c.value for c in ws[7]][:3] == ["No. de control", "Nombre", "Carrera"]
    controles = [r[0].value for r in ws.iter_rows(min_row=8)]
    assert aceptada.control_number in controles and al_dia.control_number not in controles
    assert nombre.startswith("adeudos-prorrogas-") and nombre.endswith(".xlsx")
    primera = aceptada.block_exported_at
    StudentsService.export_adeudos(db_session, periodo.id, secretaria.id, now=AHORA + timedelta(days=3))
    db_session.refresh(aceptada)
    assert primera is not None and aceptada.block_exported_at == primera


def test_avisar_desbloqueo_solo_si_aplica(db_session, aceptada, secretaria, con_plan, periodo):
    con_plan(aceptada, [("1000.00", date(2020, 1, 1))])
    StudentsService.export_adeudos(db_session, periodo.id, secretaria.id, now=AHORA)
    with pytest.raises(ServiceError) as e:
        StudentsService.mark_unblock(db_session, aceptada.id, secretaria.id, now=AHORA)
    assert e.value.code == "no_aplica"                       # exportada pero aún debe
    from itcj2.apps.prorrogas_tec.models.plan import ProrrogaPayment
    db_session.add(ProrrogaPayment(request_id=aceptada.id, folio="Z-1", paid_on=date(2026, 11, 1),
                                   amount=1000))
    db_session.flush()
    StudentsService.mark_unblock(db_session, aceptada.id, secretaria.id, now=AHORA)
    assert aceptada.unblock_notified_at is not None


def test_api_exportar(client_as, secretaria, estudiante, periodo):
    r = client_as(secretaria).post("/api/prorrogas/v2/estudiantes/adeudos.xlsx", json={"period_id": periodo.id})
    assert r.status_code == 200 and r.content[:2] == b"PK" and "attachment" in r.headers["content-disposition"]
    assert client_as(estudiante).post("/api/prorrogas/v2/estudiantes/adeudos.xlsx",
                                      json={"period_id": periodo.id}).status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_students_actions.py`
Expected: FAIL con `AttributeError` (no existe `remind`).

- [ ] **Step 3: Implement `remind`, `export_adeudos`, `mark_unblock`, the email template and the routes**

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_students_actions.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add itcj2/apps/prorrogas_tec/services/students_service.py itcj2/apps/prorrogas_tec/api/students_admin.py itcj2/apps/prorrogas_tec/templates/prorrogas_tec/email/recordatorio.html tests/fastapi/prorrogas_tec/test_students_actions.py
git commit -m "feat(prorrogas): recordar, lista de adeudos en Excel y avisar desbloqueo"
```

---

### Task 8: Pestaña "Estudiantes" de la secretaria

**Files:**
- Modify:
  - `itcj2/apps/prorrogas_tec/pages/secretaria.py`: `estudiantes` sale de `_PENDIENTES`, con su ruta
  - `static/css/secretaria/base.css`
  - `tests/fastapi/prorrogas_tec/test_secretaria_pages.py`: "próximamente" queda solo con `["estadisticas"]`
- Create: `templates/prorrogas_tec/secretaria/estudiantes.html`, `static/js/secretaria/estudiantes.js`
- Test: `tests/fastapi/prorrogas_tec/test_secretaria_pages.py`

**Interfaces:**
- Consumes: todas las rutas de Tasks 3, 4, 5 y 7, y la ruta de PDF del Plan 2 (`/api/prorrogas/v2/solicitudes/{id}/documentos/{doc}.pdf`).
- Produces: la vista del diseño ("03 Estudiantes", `docs/design/prorrogas/secretaria-final.dc.html` líneas 266–305), adaptada:
  - **Barra:** selector de semestre (`/periodos`) y búsqueda "Buscar por nombre o No. de control" (con espera de 300 ms). Filtros Todos · Con adeudo · Al corriente · Sin plan · Liquidada, con sus `conteos`. Botón **Exportar adeudos**, que hace `POST`, arma un `Blob` y descarga con el nombre del `Content-Disposition`.
  - **Tabla:**
    - Columnas No. de control · Nombre · Pagos (un punto por parcialidad vigente, coloreado por estado, y "{pagados}/{n} pagados") · Faltantes · Contactar.
    - "Faltantes" muestra "Vencida desde {fecha}" si está atrasada, "{n} por pagar" si está al corriente, "Sin plan", o una palomita si está liquidada.
    - **Recordar** se desactiva si `!puede_recordar`. Un aviso "Avisar desbloqueo" sale en la fila cuando aplica.
    - Paginación de 25: "Mostrando {n} de {total}" y "Página {p} de {páginas}".
  - **Expediente** (panel lateral al hacer clic en una fila), con estas secciones:
    - Datos del estudiante y la cuenta: total, pagado, saldo y situación.
    - **Plan**:
      - Si no hay plan: total, número de parcialidades (1–3), montos sugeridos de `/reparto` (editables) y fechas (`min` = hoy, `max` = `fecha_limite`).
      - Si hay plan y `puede_replantear`: "Replantear lo que falta", con las conservadas en solo lectura y hasta `max_nuevas` nuevas.
      - Al confirmar: `POST /plan`, y se vuelve a pintar con el expediente que regresa.
    - **Recibos**: lista con los anulados tachados; formulario folio · fecha (`max` = hoy) · monto; **Anular**, que pide el motivo con `prompt()`.
    - **Documentos**: cada uno con "Ver / imprimir" (pestaña nueva) y el estado de firma. La carta sin firma dice "Firma pendiente".
    - **Historial**: los eventos con etiquetas en español.
    - **Avisar desbloqueo**, si aplica.
  - Cada acción desactiva su botón mientras corre, muestra el `message` de error de la API y vuelve a pintar con el expediente que responde.

- [ ] **Step 1: Update the page tests (failing)**

```python
def test_pestana_estudiantes(client_as, secretaria):
    page = client_as(secretaria).get(f"{BASE}/estudiantes").text
    for texto in ("Buscar por nombre o No. de control", "Exportar adeudos", "Con adeudo", "Liquidada",
                  "estudiantes.js"):
        assert texto in page
```

Además, `test_pestanas_pendientes_muestran_proximamente` queda parametrizado solo con `["estadisticas"]`.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_secretaria_pages.py`
Expected: FAIL (la pestaña dice "próximamente").

- [ ] **Step 3: Implement the route, the template, the JS and the CSS**

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_secretaria_pages.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add itcj2/apps/prorrogas_tec/pages/secretaria.py itcj2/apps/prorrogas_tec/templates/prorrogas_tec/secretaria/estudiantes.html itcj2/apps/prorrogas_tec/static/js/secretaria/estudiantes.js itcj2/apps/prorrogas_tec/static/css/secretaria/base.css tests/fastapi/prorrogas_tec/test_secretaria_pages.py
git commit -m "feat(prorrogas): pestana Estudiantes con expediente, plan, recibos y exportacion"
```

---

### Task 9: *Mi prórroga*: plan, recibos y firma de la carta

**Files:**
- Create: `itcj2/apps/prorrogas_tec/static/js/estudiante/firma.js`
- Modify:
  - `static/js/estudiante/solicitud.js`: usa `firma.js`
  - `static/js/estudiante/mi_prorroga.js`
  - `templates/prorrogas_tec/estudiante/mi_prorroga.html` y `solicitud.html`: cargan `firma.js` antes de su script
  - `static/css/estudiante/base.css`
- Test: `tests/fastapi/prorrogas_tec/test_student_pages.py`

**Interfaces:**
- Consumes: `GET /estudiante/estado` con `cuenta`, `recibos` y `por_firmar`, y `POST …/documentos/{doc_id}/firmar` (Task 6).
- Produces:
  - **`window.Firma.crear(canvas, onChange) -> {vacia(): bool, limpiar(): void, dataURL(): string}`.** Es la lógica que hoy vive en `solicitud.js`: Pointer Events, `setPointerCapture`, escala por `devicePixelRatio` y fondo transparente.
    - Además vuelve a dimensionar en `resize` mientras no hay trazos. Eso cierra D12 de PENDIENTES.
    - `solicitud.js` la usa sin cambiar su comportamiento.
  - **`mi_prorroga.js`** (en cada solicitud aceptada):
    - "Tu plan de pagos": cada parcialidad con monto, fecha y estado (Pagada, Parcial, Pendiente, Vencida), más total, pagado y saldo.
    - "Recibos registrados".
    - Si `por_firmar`: la sección **Firma tu carta compromiso**, con la liga al PDF, el lienzo de `Firma`, **Borrar**, la casilla obligatoria "Firmo este documento" y **Firmar**. Firmar se desactiva hasta que hay un trazo y la casilla está marcada, y también mientras corre. Al terminar se recarga el estado.
    - Si el plan está liquidado: "Prórroga liquidada".

- [ ] **Step 1: Write the failing test**

```python
def test_mi_prorroga_carga_el_lienzo_compartido(client_as, estudiante):
    c = client_as(estudiante)
    for url in ("/prorrogas/estudiante", "/prorrogas/estudiante/solicitud"):
        page = c.get(url).text
        assert "js/estudiante/firma.js" in page
    assert "Firma tu carta compromiso" in c.get("/prorrogas/estudiante").text
```

"Firma tu carta compromiso" va en la plantilla como sección oculta. El JS la muestra solo si `por_firmar`.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_student_pages.py`
Expected: FAIL.

- [ ] **Step 3: Extract `firma.js`, update `solicitud.js`, implement `mi_prorroga.js`, the templates and the CSS**

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_student_pages.py`
Expected: PASS (4 pruebas).

- [ ] **Step 5: Commit**

```bash
git add itcj2/apps/prorrogas_tec/static/js/estudiante itcj2/apps/prorrogas_tec/templates/prorrogas_tec/estudiante/mi_prorroga.html itcj2/apps/prorrogas_tec/templates/prorrogas_tec/estudiante/solicitud.html itcj2/apps/prorrogas_tec/static/css/estudiante/base.css tests/fastapi/prorrogas_tec/test_student_pages.py
git commit -m "feat(prorrogas): mi prorroga muestra el plan y los recibos, y firma la carta"
```

---

### Task 10: Documentación, suite completa y prueba de humo

**Files:**
- Create: `itcj2/apps/prorrogas_tec/docs/flows/secretaria_estudiantes.md`
- Modify:
  - `docs/flows/estudiante_solicitud.md`: plan, firma de la carta y recibos
  - `docs/README.md` (CRLF): el árbol y el mapa de flujos
  - `docs/PENDIENTES.md` (CRLF): D1 hecho por Task 6 y D12 hecho por Task 9, cada uno con su commit

**Interfaces:**
- Consumes: todo lo anterior.
- Produces: la documentación al día y la evidencia de la suite y del humo.

- [ ] **Step 1: Write the docs**

`secretaria_estudiantes.md` sigue la forma de `secretaria_documentos.md`: rutas, permisos, situación, reglas del plan y del replanteo, recibos, Recordar, el Excel y el desbloqueo, con la tabla de errores.

- [ ] **Step 2: Run the wide suite**

Run: `PYTEST tests/fastapi/prorrogas_tec tests/fastapi/core tests/fastapi/observability tests/fastapi/helpdesk`
Expected: PASS.

- [ ] **Step 3: Smoke test in the container**

Un script en `instance/tmp/smoke_prorrogas_plan3.py`, con httpx contra la app de desarrollo:

1. Usa un estudiante sintético nuevo: control `99xxxxxx` que no choque con las pruebas, correo `…@example.invalid`, y que se une por QR como en el Plan 2.
2. La secretaria acepta su solicitud y confirma un plan de 2 pagos dentro del semestre actual.
3. El estudiante firma la carta. `/estado` muestra la versión firmada y el PDF responde 200 con `%PDF`.
4. La secretaria registra un recibo por la mitad y luego otro por el saldo. La situación pasa a `liquidada`.
5. Exportar adeudos responde 200 con un `.xlsx`.

Reglas: no se crean ni se cambian semestres; si no hay semestre vigente, se detiene y se reporta. No se imprimen tokens ni NIP.

Al final, el script reporta todas las filas que creó.

- [ ] **Step 4: Commit**

```bash
git add itcj2/apps/prorrogas_tec/docs
git commit -m "docs(prorrogas): flujos de Estudiantes y pagos, y pendientes del Plan 3"
```

---

## Después de este plan

- **Plan 4, Estadísticas e histórico:**
  - la vista de Estadísticas: KPIs, cumplimiento por parcialidad (las sustituidas cuentan como atraso) y exportar CSV
  - la importación del Excel 2024–2026 (`origin='excel'`, recibos sin folio)
- **Para ti:** H4, la prueba en el celular, ahora incluye firmar la carta compromiso y registrar recibos.
