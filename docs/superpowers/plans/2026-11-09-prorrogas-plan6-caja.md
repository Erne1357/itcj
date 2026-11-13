# Prórrogas · Plan 6: Caja (puntos 22 a 26) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dar a Caja su pestaña dentro de Prórrogas para buscar alumnos y cobrar el pago más próximo, sacar a la secretaria del cobro y dejar que el alumno suba su recibo escaneado.

**Architecture:** Todo vive en `itcj2/apps/prorrogas_tec`. Dos servicios nuevos (`CajaService` para lista y detalle, `ReceiptScanService` para el PDF del alumno) y `PaymentService` gana `settle_next`, que calcula el monto y reutiliza `record`. La vista es una pestaña más de `/prorrogas/secretaria`, con su `caja.js`. Hay una sola migración, al inicio, y una sola semilla, al final.

**Tech Stack:** FastAPI, SQLAlchemy 2, Postgres, Alembic, Jinja, JS sin framework, pytest contra el Postgres de dev dentro de un savepoint.

**Spec:** `docs/superpowers/specs/2026-11-09-prorrogas-caja-design.md`. Diseño: `.superpowers/sdd/caja/Caja.dc.html` y `TopNav.dc.html` (solo datos inventados; el selector "Ver estado" y los datos de muestra no van al producto).

## Global Constraints

**Decisiones del usuario**
- Caja es el único rol que marca pagos. Pago completo, sin abonos, en orden, con el folio de su recibo, obligatorio y único. Solo se anula el último, con motivo.
- Rol propio dentro de Prórrogas, solo con la pestaña Estudiantes. No toca TitulaTec.
- La búsqueda abarca todos los semestres por omisión; hay filtro por semestre.
- Las históricas del Excel **sin semestre** quedan fuera de Caja. Las históricas **con semestre** aparecen y se cobran.
- Caja cobra aunque el alumno no haya firmado su carta compromiso.
- Recibo escaneado: subirlo es obligatorio, validarlo no. Solo PDF, hasta 5 MB. La secretaria tiene un botón opcional para avisar una inconsistencia, con motivo, por correo y notificación.
- Caja también ve la referencia bancaria, solo lectura.
- El rol Jefe sigue pospuesto (H22): no se crea ni se menciona en pantallas.
- En Caja solo aparecen solicitudes `aceptada`.
- Si un pago quedó cubierto a medias por recibos anteriores o del Excel, Caja cobra solo lo que falta.
- El modal de la secretaria pierde el cobro y gana el estado del recibo y el botón de avisar, con su estilo actual.

**Seguridad y datos**
- `database/`, `instance/tmp/excel/` e `instance/tmp/prorrogas_ejemplos/` tienen datos reales: nunca hagas grep ni lectura sobre ellos. Excluye `database/` de todo grep.
- Solo puedes correr pytest (PYT). Nunca `alembic`, `init-prorrogas`, `import-excel`, ni scripts que abran una sesión de base de datos.
- Un paso marcado **GATE** NO es de los implementadores: lo corre el controlador. Sáltalo y dilo en tu reporte. Si una prueba falla porque falta una migración o una semilla, no la apliques: repórtalo como BLOCKED.
- No toques otras apps. En `APP/static/css/secretaria/base.css`, el bloque "Ancho completo" sigue siendo el último. No cambies `itcj2/core/utils/docx_pdf.py` ni `sv()`.

**Git y comandos**
- Nunca `git add -A` ni `git add .`: agrega las rutas de **Files**. Nunca agregues `reports/`, `research_notes/`, `.superpowers/`, `database/` ni dotfiles. No hagas push, merge, rebase, reset ni checkout de ramas.
- No escribas en comandos de shell ni en mensajes de commit las palabras que el bloqueo de permisos rechaza (lista en `.superpowers/sdd/2026-11-08-prorrogas-plan5-proceso-completo/constraints.md`).
- **COMMIT** significa, desde `/home/deigol/repos/itcj`:
  ```bash
  git add -- <rutas de Files>
  GIT_AUTHOR_NAME=Deig0l GIT_AUTHOR_EMAIL=deigolsalazar@gmail.com GIT_COMMITTER_NAME=Deig0l GIT_COMMITTER_EMAIL=deigolsalazar@gmail.com git commit -m "<mensaje>" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
  ```
- **PYT \<ruta\>** significa (la palabra `docker` va primero, sin `cd` ni tuberías, con las rutas `T/` escritas completas):
  ```bash
  docker compose -f /home/deigol/repos/itcj/docker/compose/docker-compose.dev.yml exec backend python -m pytest <ruta> -q --no-header --tb=short -p no:cacheprovider -W ignore
  ```
- Trabaja en `/home/deigol/repos/itcj`, rama `feature/core-prorrogas`, sin worktree. Si PYT da permission denied dos veces, responde NEEDS_CONTEXT con "listo para pruebas" y no hagas commit.
- Rutas cortas: `APP/` = `itcj2/apps/prorrogas_tec/`; `T/` = `tests/fastapi/prorrogas_tec/`; `TPL/` = `APP/templates/prorrogas_tec/`; `JS/` = `APP/static/js/`.

**Pruebas**
- Corren contra el Postgres de dev, con datos reales, dentro de un savepoint. Usa controles de la serie `99xxxxxx`, fechas 2091 y folios `ZZ-…`. No asumas tablas vacías: toda lista de Caja lleva `semestre=periodo.id` o un `q` de la serie 99. Nunca imprimas nombres ni controles reales.
- Un servicio que lanza `ServiceError` hace rollback: lo que la prueba use después del error debe venir de un commit anterior.
- Falla conocida: un error `uq_users_control_number` con el control 99000001 viene del alumno de prueba de dev. Reintenta y dilo en el reporte.

**Código y pantallas**
- Copy en español, sin cambiar el tono de cada pantalla. Texto del servidor en JS, siempre con `textContent`.
- Sin pruebas de JS en el repo. Cada pantalla termina con prueba de página y `node --check <archivo>` si node existe; la revisión en navegador es del controlador, al final.
- La vista de Caja reutiliza `_base.html`, `require_tab` y las clases y tokens de secretaría, y va responsiva a 390 px como el canvas.
- Cambio mínimo que resuelva la tarea por completo. Comenta solo el porqué que el código no muestra.

## Review Focus

1. Dos cajeras, o un doble clic, saldan el mismo pago: no hay doble cobro y la segunda ve `pago_cambio` (Task 2).
2. El folio se escribe con minúsculas o espacios, o coincide con uno viejo capturado en minúsculas: se rechaza como duplicado (Task 2).
3. El nombre real se guarda con apellidos primero: buscar "Andrea Salgado" encuentra a "SALGADO RUIZ ANDREA" (Task 4).
4. El último recibo vigente vino del Excel y no tiene folio: la fila se ve, dice "Histórico" y se puede anular (Task 5).
5. Un recibo del alumno que no es PDF, pasa de 5 MB, es de otra persona o ya no está en disco: 400 o 404, nunca 500 (Task 3).

---

## Bloque 0 · Base

### Task 1: Esquema en una sola migración (**GATE**)

**Files:**
- Create: `migrations/versions/pr20261109b_prorrogas_caja.py`
- Modify: `APP/models/plan.py`
- Test: `T/test_schema.py`

**Interfaces:**
- Produces: `ProrrogaInstallment.receipt_path: Text`, `ProrrogaInstallment.receipt_uploaded_at: DateTime`.

- [ ] **Step 1: Prueba.** Al final de `T/test_schema.py`:

```python
def test_columnas_de_caja():
    assert {"receipt_path", "receipt_uploaded_at"} <= set(Base.metadata.tables["prorrogas_installments"].c.keys())
```

- [ ] **Step 2:** `PYT T/test_schema.py::test_columnas_de_caja`. Esperado: FALLA.
- [ ] **Step 3: Modelo.** Después de `last_reminder_days`: `receipt_path = Column(Text)` y `receipt_uploaded_at = Column(DateTime)`. Corrige el docstring de `ProrrogaPayment`: el recibo lo captura Caja (app) o llega del Excel (folio).
- [ ] **Step 4: Migración** a mano, con la forma de `pr20261109a`: `revision="pr20261109b"`, `down_revision="pr20261109a"`. Upgrade: los dos `op.add_column("prorrogas_installments", ...)`. Downgrade: los dos `op.drop_column`. El docstring explica que el recibo cuelga de la parcialidad, no del recibo de Caja, para sobrevivir a una anulación.
- [ ] **Step 5:** `PYT T/test_schema.py::test_columnas_de_caja`. Esperado: PASA. **Solo esa**: sin la migración aplicada, toda consulta a `prorrogas_installments` falla.
- [ ] **Step 6:** **COMMIT** `feat(prorrogas): columnas del recibo escaneado en la parcialidad`
- [ ] **Step 7: GATE (controlador).** Aplica y comprueba:

```bash
docker compose -f /home/deigol/repos/itcj/docker/compose/docker-compose.dev.yml exec backend alembic -c migrations/alembic.ini upgrade head
```

Luego `PYT T/`. Esperado: todo pasa.

### Task 2: Cobrar el pago más próximo y anular solo el último (punto 24)

Los recibos viejos y las pruebas siguen usando `PaymentService.record`: solo desaparece su ruta (Task 8).

**Files:**
- Modify: `APP/services/payment_service.py`
- Test: `T/conftest.py`, `T/test_payments.py`

**Interfaces:**
- Produces:
  - `PaymentService.settle_next(db, request_id: int, actor_id: int, *, numero: int, folio: str, paid_on: date, now: date | datetime | None = None) -> ProrrogaPayment`.
  - `PaymentService.record` guarda el folio con `strip().upper()`.
  - Errores `pago_cambio` y `no_es_el_ultimo` (409).
  - En `conftest.py`: `CAJA_PERMS`, fixtures `cajero` y `secretaria_sin_cobro`; `SECRETARIA_PERMS` sin los dos códigos `payments.api.*`.

- [ ] **Step 1: Fixtures.** Quita de `SECRETARIA_PERMS` los códigos `prorrogas_tec.payments.api.record` y `.void`. Agrega:

```python
CAJA_PERMS = [
    "prorrogas_tec.secretaria.page.caja", "prorrogas_tec.caja.api.read",
    "prorrogas_tec.payments.api.record", "prorrogas_tec.payments.api.void",
]


@pytest.fixture()
def cajero(make_user, make_role, grant):
    user = make_user(first_name="CAJERA", last_name="PRUEBA")
    grant(user, make_role("caja", CAJA_PERMS))
    return user


@pytest.fixture()
def secretaria_sin_cobro(make_user, make_role, grant):
    user = make_user(first_name="SECRETARIA", last_name="SINCOBRO")
    # No uses "secretaria": hasta aplicar la semilla 09, el rol real de dev todavía cobra.
    grant(user, make_role("secretaria_prueba", SECRETARIA_PERMS))
    return user
```

- [ ] **Step 2: Pruebas.** En `T/test_payments.py`:

```python
def _saldar(db, req, actor, numero, folio, dia=HOY):
    return PaymentService.settle_next(db, req.id, actor.id, numero=numero, folio=folio, paid_on=dia, now=HOY)


def test_saldar_cobra_el_siguiente_completo(db_session, aceptada, cajero, con_plan):
    _plan(con_plan, aceptada)
    pago = _saldar(db_session, aceptada, cajero, 1, " zz-100 ")
    assert (pago.folio, pago.amount, pago.recorded_by_id) == ("ZZ-100", D("1000.00"), cajero.id)
    assert load(db_session, aceptada, HOY).proxima.number == 2


def test_saldar_cobra_solo_lo_que_falta(db_session, aceptada, cajero, con_plan):
    con_plan(aceptada, [("1000.00", date(2091, 2, 1)), ("1000.00", date(2091, 4, 1))], pagos=["400.00"])
    assert _saldar(db_session, aceptada, cajero, 1, "ZZ-101").amount == D("600.00")


def test_saldar_dos_veces_no_cobra_doble(db_session, aceptada, cajero, con_plan):  # Review Focus 1
    _plan(con_plan, aceptada)
    _saldar(db_session, aceptada, cajero, 1, "ZZ-102")
    with pytest.raises(ServiceError) as e:
        _saldar(db_session, aceptada, cajero, 1, "ZZ-103")
    assert (e.value.code, e.value.status) == ("pago_cambio", 409)
    assert load(db_session, aceptada, HOY).pagado == D("1000.00")


@pytest.mark.parametrize("numero", [2, 9])
def test_saldar_fuera_de_orden(db_session, aceptada, cajero, con_plan, numero):
    _plan(con_plan, aceptada)
    with pytest.raises(ServiceError) as e:
        _saldar(db_session, aceptada, cajero, numero, "ZZ-104")
    assert e.value.code == "pago_cambio"


def test_saldar_sin_plan(db_session, aceptada, cajero):
    with pytest.raises(ServiceError) as e:
        _saldar(db_session, aceptada, cajero, 1, "ZZ-105")
    assert e.value.code == "sin_plan"


def test_folio_duplicado_sin_distinguir_mayusculas(db_session, aceptada, make_aceptada, cajero, con_plan):  # Review Focus 2
    from itcj2.apps.prorrogas_tec.models.plan import ProrrogaPayment
    otra = _plan(con_plan, make_aceptada())
    _plan(con_plan, aceptada)
    db_session.add(ProrrogaPayment(request_id=otra.id, folio="zz-dup", paid_on=HOY, amount=D("1")))  # captura vieja
    db_session.flush()
    with pytest.raises(ServiceError) as e:
        _saldar(db_session, aceptada, cajero, 1, " ZZ-DUP ")
    assert (e.value.code, e.value.message) == ("folio_duplicado", "Ese folio ya está registrado.")


def test_cobra_aunque_no_haya_firmado(db_session, aceptada, cajero, con_plan):
    from itcj2.apps.prorrogas_tec.models.document import ProrrogaDocument
    _plan(con_plan, aceptada)
    db_session.add(ProrrogaDocument(request_id=aceptada.id, doc_type="carta_compromiso_2", version=1, context={},
                                    file_path="x.pdf", sha256="0" * 64))
    db_session.flush()
    assert _saldar(db_session, aceptada, cajero, 1, "ZZ-106").amount == D("1000.00")


@pytest.mark.parametrize("dia1, dia2, ultimo", [
    (date(2091, 3, 1), date(2091, 3, 2), 1),
    (date(2091, 3, 5), date(2091, 3, 1), 0),  # capturado después, pero pagado antes
    (date(2091, 3, 1), date(2091, 3, 1), 1),  # misma fecha: gana el id mayor
])
def test_solo_se_anula_el_ultimo(db_session, aceptada, cajero, con_plan, dia1, dia2, ultimo):
    _plan(con_plan, aceptada)
    pagos = [_saldar(db_session, aceptada, cajero, 1, "ZZ-110", dia=dia1),
             _saldar(db_session, aceptada, cajero, 2, "ZZ-111", dia=dia2)]
    with pytest.raises(ServiceError) as e:
        PaymentService.void(db_session, pagos[1 - ultimo].id, cajero.id, motivo="Se capturó mal", now=HOY)
    assert (e.value.code, e.value.status) == ("no_es_el_ultimo", 409)
    PaymentService.void(db_session, pagos[ultimo].id, cajero.id, motivo="Se capturó mal", now=HOY)
    PaymentService.void(db_session, pagos[1 - ultimo].id, cajero.id, motivo="Se capturó mal", now=HOY)
    assert load(db_session, aceptada, HOY).pagado == D("0")
```

- [ ] **Step 3:** `PYT T/test_payments.py`. Esperado: FALLAN las nuevas.
- [ ] **Step 4: `record`.** `folio = (folio or "").strip().upper()`. El duplicado se busca con `func.upper(ProrrogaPayment.folio) == folio`. `_folio_duplicado` dice `"Ese folio ya está registrado."`.
- [ ] **Step 5: `settle_next`.** Mismo candado que `record`; solicitud inexistente: `no_encontrada` (404). Dentro del `try` (cualquier error: rollback y relanza): `no_aceptada`, `_exigir_semestre`, `c = account.load(db, req, today)`, `c.total is None`: `sin_plan`. `c.proxima is None or c.proxima.number != numero`: `ServiceError("pago_cambio", "Ese pago ya no es el siguiente por cobrar. Revisa el detalle.", status=409)`. Termina con `return PaymentService.record(db, request_id, actor_id, folio=folio, paid_on=paid_on, amount=c.proxima.amount - c.proxima.cubierto, now=now)`: la transacción conserva el candado, así que `record` valida sin carrera.
- [ ] **Step 6: `void`.** Tras `ya_anulado` y antes del motivo: el último vigente de la solicitud es el de mayor `paid_on` y luego mayor `id`; si no es este, `ServiceError("no_es_el_ultimo", "Solo se puede anular el último recibo vigente.", status=409)`.
- [ ] **Step 7:** `PYT T/`. Esperado: todo pasa. `test_students_actions.py`, `test_historico_seguro.py` y `test_plan.py:128` no cambian: cada uno anula el único recibo de su solicitud.
- [ ] **Step 8:** **COMMIT** `feat(prorrogas): saldar el pago mas proximo y anular solo el ultimo recibo`

### Task 3: Recibo escaneado del alumno (punto 26)

**Files:**
- Create: `APP/services/receipt_scan_service.py`
- Modify: `APP/services/reference_service.py`, `APP/services/events.py`, `APP/api/_common.py`, `APP/api/student.py`
- Test: `T/test_recibo_escaneado.py`

**Interfaces:**
- Produces:
  - `reference_service.validar_pdf(data: bytes, invalido: str, muy_grande: str, nombre: str) -> None` (mensajes `f"{nombre} debe ser un PDF."` y `f"{nombre} no puede pasar de 5 MB."`).
  - `ReceiptScanService.save(db, req, numero: int, data: bytes, actor_id: int, *, now: datetime | None = None) -> ProrrogaInstallment`. No hace commit.
  - `ReceiptScanService.read(db, req, numero: int) -> bytes`: `ServiceError("sin_recibo", ..., status=404)` si no hay fila, ruta o archivo.
  - `ReceiptScanService.subidos(db, request_id: int) -> dict[int, str]`: `{numero: iso}` de las parcialidades vigentes con recibo.
  - `_common.recibo_pdf_response(db, req: ProrrogaRequest | None, numero: int) -> Response`: el PDF inline (`filename="recibo.pdf"`) o `error_response(404, "no_encontrada", "No se encontró el recibo.")`.
  - `POST /estudiante/solicitudes/{id}/parcialidades/{numero}/recibo` (multipart `archivo`, permiso `_CREATE`), `GET .../recibo.pdf` (`_READ`).
  - `cuenta.parcialidades[].recibo_subido: str | None` en `_con_cuenta`.

- [ ] **Step 1: Pruebas** (`T/test_recibo_escaneado.py`):

```python
import hashlib
from datetime import date
from io import BytesIO

import pytest

from itcj2.apps.prorrogas_tec.models.event import ProrrogaEvent
from itcj2.apps.prorrogas_tec.models.plan import ProrrogaInstallment, ProrrogaPayment
from itcj2.apps.prorrogas_tec.services.payment_service import PaymentService
from tests.fastapi.prorrogas_tec.conftest import STUDENT_PERMS

API = "/api/prorrogas/v2/estudiante/solicitudes"
PDF = b"%PDF-1.4 recibo de prueba"


@pytest.fixture()
def duena(db_session, aceptada, grant, make_role):
    from itcj2.core.models.user import User
    u = db_session.get(User, aceptada.student_id)
    grant(u, make_role("student", STUDENT_PERMS))
    return u


@pytest.fixture()
def cubierta(aceptada, con_plan):
    return con_plan(aceptada, [("1000.00", date(2091, 5, 1)), ("1000.00", date(2091, 6, 1))], pagos=["1000.00"])


def _subir(c, rid, numero=1, data=PDF):
    return c.post(f"{API}/{rid}/parcialidades/{numero}/recibo",
                  files={"archivo": ("mi recibo.pdf", BytesIO(data), "application/pdf")})


def test_sube_lee_y_reemplaza(client_as, duena, cubierta, db_session):
    c = client_as(duena)
    r = _subir(c, cubierta.id)
    assert r.status_code == 200 and r.json()["cuenta"]["parcialidades"][0]["recibo_subido"]
    assert r.json()["cuenta"]["parcialidades"][1]["recibo_subido"] is None
    i = db_session.query(ProrrogaInstallment).filter_by(request_id=cubierta.id, number=1).one()
    sha = hashlib.sha256(PDF).hexdigest()[:12]
    assert i.receipt_path == f"recibos/{cubierta.period_id}/{cubierta.id}-1-{sha}.pdf"
    assert db_session.query(ProrrogaEvent).filter_by(request_id=cubierta.id, event_type="recibo_subido").one().payload == {"numero": 1}
    assert c.get(f"{API}/{cubierta.id}/parcialidades/1/recibo.pdf").content == PDF
    assert _subir(c, cubierta.id, data=b"%PDF-1.4 otro").status_code == 200
    assert c.get(f"{API}/{cubierta.id}/parcialidades/1/recibo.pdf").content == b"%PDF-1.4 otro"


@pytest.mark.parametrize("data, code", [
    (b"", "recibo_invalido"),
    (b"MZ no soy un pdf", "recibo_invalido"),
    (b"%PDF-" + b"0" * (5 * 1024 * 1024), "recibo_muy_grande"),
])
def test_archivo_rechazado(client_as, duena, cubierta, data, code):  # Review Focus 5
    r = _subir(client_as(duena), cubierta.id, data=data)
    assert r.status_code == 400 and r.json()["error"] == code


def test_recibo_ajeno_no_existe(client_as, estudiante, cubierta):  # Review Focus 5
    c = client_as(estudiante)
    assert _subir(c, cubierta.id).status_code == 404
    assert c.get(f"{API}/{cubierta.id}/parcialidades/1/recibo.pdf").status_code == 404


@pytest.mark.parametrize("numero", [2, 9])
def test_solo_si_esta_cubierta(client_as, duena, cubierta, numero):
    r = _subir(client_as(duena), cubierta.id, numero=numero)
    assert r.status_code == 409 and r.json()["error"] == "recibo_no_aplica"


def test_historica_sin_semestre_no_aplica(client_as, duena, db_session, make_historica):
    h = make_historica(control_number="99430020", pagadas=(0,))
    h.student_id = duena.id
    db_session.flush()
    assert _subir(client_as(duena), h.id).json()["error"] == "recibo_no_aplica"


def test_se_lee_tras_anular_pero_no_se_sube(client_as, duena, cubierta, db_session):
    c = client_as(duena)
    _subir(c, cubierta.id)
    pago = db_session.query(ProrrogaPayment).filter_by(request_id=cubierta.id).one()
    PaymentService.void(db_session, pago.id, duena.id, motivo="Se capturó mal", now=date(2091, 3, 1))
    assert c.get(f"{API}/{cubierta.id}/parcialidades/1/recibo.pdf").content == PDF
    assert _subir(c, cubierta.id).json()["error"] == "recibo_no_aplica"


def test_sin_recibo_o_archivo_borrado_es_404(client_as, duena, cubierta, db_session):  # Review Focus 5
    c = client_as(duena)
    assert c.get(f"{API}/{cubierta.id}/parcialidades/1/recibo.pdf").status_code == 404
    i = db_session.query(ProrrogaInstallment).filter_by(request_id=cubierta.id, number=1).one()
    i.receipt_path = "recibos/0/no-existe.pdf"
    db_session.flush()
    assert c.get(f"{API}/{cubierta.id}/parcialidades/1/recibo.pdf").status_code == 404
```

- [ ] **Step 2:** `PYT T/test_recibo_escaneado.py`. Esperado: FALLAN.
- [ ] **Step 3: Validación.** Extrae las dos comprobaciones de `ReferenceService.save` a `validar_pdf` y llámala con `("referencia_invalida", "referencia_muy_grande", "La referencia")`. `EVENT_TYPES` suma `"recibo_subido"`.
- [ ] **Step 4: Servicio.** `save`: primero `validar_pdf(data, "recibo_invalido", "recibo_muy_grande", "El recibo")`. Con `account.load(db, req, today)`, si `req.period_id is None`, o no existe la parcialidad `numero`, o su `estado != "pagada"`: `ServiceError("recibo_no_aplica", "Ese pago aún no está cubierto: no lleva recibo.", status=409)`. La ruta es `recibos/{period_id}/{request_id}-{numero}-{sha12}.pdf`, nunca con el nombre del archivo. Guarda con `storage.write_atomic`, llena `receipt_path` y `receipt_uploaded_at` de la parcialidad vigente (`superseded_at IS NULL`), `log_event(... "recibo_subido", payload={"numero": numero})`, `db.flush()`. `subidos` filtra por vigente y `receipt_uploaded_at IS NOT NULL`.
- [ ] **Step 5: API.** `recibo_pdf_response` atrapa `ServiceError`. `subir_recibo` copia a `subir_referencia` (`_propia(lock=True)`, lee `MAX_BYTES + 1`, 404 si es ajena, responde `_con_cuenta`). `bajar_recibo` es `recibo_pdf_response(db, _propia(db, request_id, uid), numero)`. `_con_cuenta` agrega `p["recibo_subido"] = subidos.get(p["numero"])` a cada parcialidad.
- [ ] **Step 6:** `PYT T/`. Esperado: todo pasa.
- [ ] **Step 7:** **COMMIT** `feat(prorrogas): el alumno sube el recibo escaneado de cada pago cubierto`

---

## Bloque 1 · Datos de Caja

### Task 4: Por cobrar y búsqueda (punto 22)

**Files:**
- Create: `APP/services/caja_service.py`
- Test: `T/test_caja.py`

**Interfaces:**
- Produces:
  - `CajaService.POR_PAGINA = 8`, `CajaService.MAX_RESULTADOS = 50`.
  - `CajaService.solicitud(db, request_id: int) -> ProrrogaRequest | None`: `None` si está fuera del universo.
  - `CajaService.listar(db, *, q: str | None = None, semestre: int | None = None, filtro: str = "todos", orden: str = "urgente", page: int = 1, today: date) -> dict` con `{"items", "total", "page", "per_page", "conteos"}`; `conteos` es `None` al buscar.
  - Cada item: `{"id", "control", "nombre", "semestre", "folio", "situacion", "siguiente"}`, con `siguiente = {"fecha", "monto", "faltan"} | None`.
  - Códigos `filtro_invalido`, `orden_invalido` (400).

- [ ] **Step 1: Pruebas** (`T/test_caja.py`):

```python
from datetime import date

import pytest

from itcj2.apps.prorrogas_tec.services.caja_service import CajaService
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.identity import folio

HOY = date(2091, 3, 10)
VENCIDO = [("1000.00", date(2091, 2, 1)), ("1000.00", date(2091, 5, 1))]
AL_DIA = [("500.00", date(2091, 4, 1))]


def _lista(db, periodo, **kw):
    return CajaService.listar(db, semestre=periodo.id, today=HOY, **kw)


def _ids(d):
    return [i["id"] for i in d["items"]]


def test_por_cobrar_deja_fuera_sin_plan_y_liquidadas(db_session, periodo, aceptada, make_aceptada, con_plan):
    con_plan(make_aceptada(), AL_DIA, ["500.00"])
    debe = con_plan(make_aceptada(), AL_DIA)
    d = _lista(db_session, periodo)
    assert _ids(d) == [debe.id] and d["total"] == 1
    assert d["conteos"] == {"todos": 1, "con_adeudo": 0, "al_corriente": 1}


@pytest.mark.parametrize("filtro, cuales", [("todos", {"v", "c"}), ("con_adeudo", {"v"}), ("al_corriente", {"c"})])
def test_pestanas(db_session, periodo, make_aceptada, con_plan, filtro, cuales):
    filas = {"v": con_plan(make_aceptada(), VENCIDO), "c": con_plan(make_aceptada(), AL_DIA)}
    assert set(_ids(_lista(db_session, periodo, filtro=filtro))) == {filas[k].id for k in cuales}


@pytest.mark.parametrize("orden, esperado", [
    ("urgente", ["vencido", "pronto", "tarde"]), ("proximo", ["vencido", "pronto", "tarde"]),
    ("saldo", ["tarde", "vencido", "pronto"]), ("nombre", ["pronto", "tarde", "vencido"]),
])
def test_orden(db_session, periodo, make_aceptada, con_plan, orden, esperado):
    filas = {"vencido": ("ZÚÑIGA PRUEBA UNO", "300.00", date(2091, 2, 1)),
             "pronto": ("ÁLVAREZ PRUEBA DOS", "100.00", date(2091, 4, 1)),
             "tarde": ("BENÍTEZ PRUEBA TRES", "900.00", date(2091, 5, 1))}
    ids = {}
    for k, (nombre, monto, dia) in filas.items():
        r = con_plan(make_aceptada(), [(monto, dia)])
        r.student_name, ids[k] = nombre, r.id
    assert _ids(_lista(db_session, periodo, orden=orden)) == [ids[k] for k in esperado]


def test_ocho_por_pagina(db_session, periodo, make_aceptada, con_plan):
    for _ in range(9):
        con_plan(make_aceptada(), AL_DIA)
    uno, dos = _lista(db_session, periodo), _lista(db_session, periodo, page=2)
    assert (len(uno["items"]), len(dos["items"]), uno["total"], uno["per_page"]) == (8, 1, 9, 8)


def test_fila(db_session, periodo, make_aceptada, con_plan):
    r = con_plan(make_aceptada("99430006"), VENCIDO, ["400.00"])
    assert _lista(db_session, periodo)["items"][0] == {
        "id": r.id, "control": "99430006", "nombre": "ESTUDIANTE PRUEBA", "semestre": "enero – junio 2091",
        "folio": folio(r), "situacion": "atrasada", "siguiente": {"fecha": "2091-02-01", "monto": "600.00", "faltan": 2}}


def test_busqueda_abarca_sin_plan_y_liquidadas(db_session, periodo, make_aceptada, con_plan):
    sin_plan = make_aceptada("99430001")
    liquidada = con_plan(make_aceptada("99430002"), AL_DIA, ["500.00"])
    d = _lista(db_session, periodo, q="9943000")
    assert set(_ids(d)) == {sin_plan.id, liquidada.id} and d["conteos"] is None
    assert {i["situacion"]: i["siguiente"] for i in d["items"]} == {"sin_plan": None, "liquidada": None}


@pytest.mark.parametrize("q", ["nuñez", "NUNEZ", "núñez", "Jose  Nunez", "jose salas"])
def test_busqueda_sin_acentos_mayusculas_ni_orden(db_session, periodo, make_aceptada, q):  # Review Focus 3
    r = make_aceptada("99430003")
    r.student_name = "NÚÑEZ SALAS JOSÉ"
    assert _ids(_lista(db_session, periodo, q=q)) == [r.id]


def test_busqueda_abarca_todos_los_semestres_o_el_elegido(db_session, periodo, make_historica):
    from itcj2.core.models.academic_period import AcademicPeriod
    otro = AcademicPeriod(code="T90001", name="Prórrogas prueba 2", start_date=date(2092, 1, 10),
                          end_date=date(2092, 6, 20), status="INACTIVE")
    db_session.add(otro)
    db_session.flush()
    h = make_historica(periodo=otro, control_number="99430004")
    assert _ids(CajaService.listar(db_session, q="99430004", today=HOY)) == [h.id]
    assert _ids(_lista(db_session, periodo, q="99430004")) == []


def test_historica_sin_semestre_queda_fuera(db_session, make_historica):
    make_historica(control_number="99430005", pagadas=())
    assert CajaService.listar(db_session, q="99430005", today=HOY)["items"] == []


def test_historica_con_semestre_se_cobra(db_session, periodo, make_historica):
    h = make_historica(periodo=periodo)
    assert _ids(_lista(db_session, periodo, filtro="con_adeudo")) == [h.id]


@pytest.mark.parametrize("estado", ["pendiente", "rechazada", "cancelada", "cerrada_sin_plan"])
def test_solo_aceptadas(db_session, periodo, aceptada, con_plan, estado):
    con_plan(aceptada, AL_DIA)
    aceptada.status = estado
    db_session.flush()
    assert _lista(db_session, periodo, q=aceptada.control_number)["items"] == []


def test_busqueda_maximo_cincuenta(db_session, periodo, make_aceptada, monkeypatch):
    assert CajaService.MAX_RESULTADOS == 50
    monkeypatch.setattr(CajaService, "MAX_RESULTADOS", 2)
    for i in range(3):
        make_aceptada(f"9943010{i}")
    d = _lista(db_session, periodo, q="9943010")
    assert len(d["items"]) == 2 and d["total"] == 3


@pytest.mark.parametrize("kw, code", [({"filtro": "x"}, "filtro_invalido"), ({"orden": "x"}, "orden_invalido")])
def test_parametros_invalidos(db_session, periodo, kw, code):
    with pytest.raises(ServiceError) as e:
        _lista(db_session, periodo, **kw)
    assert (e.value.code, e.value.status) == (code, 400)
```

- [ ] **Step 2:** `PYT T/test_caja.py`. Esperado: FALLAN.
- [ ] **Step 3: `listar`.** Universo: `status == "aceptada"` y `period_id IS NOT NULL`, más el `semestre` si llega. Cuentas con `account.load_many`, con el comentario `# shortcut: cuentas en Python sobre todo el universo; pasar a SQL si supera ~2000 solicitudes`. Acentos y mayúsculas con `importacion.normaliza.normalizar`.
  - **Con texto** (`q.strip()`): coincide si el `q` normalizado está en el control, o si **cada palabra** está en el nombre, porque los nombres se guardan con apellidos primero. Orden por nombre normalizado e id. `total` son todas las coincidencias, `items` hasta `MAX_RESULTADOS`, `page=1`, `conteos=None`.
  - **Sin texto:** se queda con las que tienen `c.proxima`. `con_adeudo` es `c.proxima.due_date < today` y `al_corriente` el resto. `conteos` no depende de `filtro`. Claves de orden: `urgente` y `proximo` `(proxima.due_date, nombre, id)` (una vencida siempre tiene fecha menor que una al corriente, así que las dos opciones coinciden: dilo en un comentario), `saldo` `(-saldo, nombre, id)`, `nombre` `(nombre, id)`. `page` se limita a `[1, última]`.
  - `siguiente` es `None` sin `c.proxima`; si no, `{"fecha": iso, "monto": money(amount - cubierto), "faltan": c.faltantes}`. `situacion` es `c.situacion`, `semestre` es `req.period_label`.
- [ ] **Step 4:** `PYT T/test_caja.py`. Esperado: pasan.
- [ ] **Step 5:** **COMMIT** `feat(prorrogas): lista por cobrar y busqueda de Caja`

### Task 5: Detalle de Caja (punto 23)

**Files:**
- Modify: `APP/services/caja_service.py`
- Test: `T/test_caja.py`

**Interfaces:**
- Consumes: `ReceiptScanService.subidos` (Task 3), `account.cobertura`.
- Produces: `CajaService.detalle(db, request_id: int, today: date) -> dict`:

```text
{"id", "folio", "nombre", "control", "carrera", "semestre", "situacion", "referencia": bool,
 "total": str|None, "pagado": str, "saldo": str|None,
 "pagos": [{"numero", "fecha", "monto", "a_cobrar", "estado", "dias_vencido": int, "siguiente": bool,
            "anulable": bool, "recibo": {"id", "folio", "fecha"}|None, "recibo_subido": str|None}]}
```

- [ ] **Step 1: Pruebas** (agrega a `T/test_caja.py`):

```python
def _pagos(db, req):
    return CajaService.detalle(db, req.id, HOY)["pagos"]


def test_detalle_sin_plan(db_session, aceptada):
    d = CajaService.detalle(db_session, aceptada.id, HOY)
    assert (d["situacion"], d["pagos"], d["total"], d["referencia"]) == ("sin_plan", [], None, False)


def test_detalle_marca_el_siguiente_y_el_ultimo(db_session, aceptada, cajero, con_plan):
    from itcj2.apps.prorrogas_tec.services.payment_service import PaymentService
    con_plan(aceptada, [("1000.00", date(2091, 2, 1)), ("1000.00", date(2091, 4, 1)), ("500.00", date(2091, 5, 1))])
    PaymentService.settle_next(db_session, aceptada.id, cajero.id, numero=1, folio="ZZ-300", paid_on=HOY, now=HOY)
    uno, dos, tres = _pagos(db_session, aceptada)
    assert (uno["estado"], uno["a_cobrar"], uno["recibo"]["folio"], uno["recibo"]["fecha"], uno["anulable"]) == (
        "pagada", "0.00", "ZZ-300", "2091-03-10", True)
    assert (dos["siguiente"], dos["a_cobrar"], dos["anulable"], tres["siguiente"]) == (True, "1000.00", False, False)
    d = CajaService.detalle(db_session, aceptada.id, HOY)
    assert (d["total"], d["pagado"], d["saldo"]) == ("2500.00", "1000.00", "1500.00")


def test_detalle_un_recibo_de_dos_pagos_solo_se_anula_en_el_ultimo(db_session, aceptada, con_plan):
    con_plan(aceptada, [("500.00", date(2091, 4, 1)), ("500.00", date(2091, 5, 1))], pagos=["1000.00"])
    assert [p["anulable"] for p in _pagos(db_session, aceptada)] == [False, True]


def test_detalle_vencido_cuenta_los_dias(db_session, aceptada, con_plan):
    con_plan(aceptada, [("1000.00", date(2091, 3, 1))])
    p, = _pagos(db_session, aceptada)
    assert (p["estado"], p["dias_vencido"], p["siguiente"]) == ("vencida", 9, True)


def test_detalle_a_medias_cobra_lo_que_falta(db_session, aceptada, con_plan):
    con_plan(aceptada, [("1000.00", date(2091, 4, 1))], pagos=["400.00"])
    p, = _pagos(db_session, aceptada)
    assert (p["estado"], p["monto"], p["a_cobrar"], p["recibo"], p["anulable"]) == ("parcial", "1000.00", "600.00", None, False)


def test_detalle_recibo_del_excel_sin_folio(db_session, periodo, make_historica):  # Review Focus 4
    p, = _pagos(db_session, make_historica(periodo=periodo, pagadas=(0,)))
    assert p["recibo"]["folio"] is None and p["anulable"] is True


def test_detalle_trae_el_recibo_escaneado(db_session, aceptada, con_plan):
    from datetime import datetime
    from itcj2.apps.prorrogas_tec.models.plan import ProrrogaInstallment
    con_plan(aceptada, [("1000.00", date(2091, 4, 1))])
    i = db_session.query(ProrrogaInstallment).filter_by(request_id=aceptada.id, number=1).one()
    i.receipt_path, i.receipt_uploaded_at = "recibos/x.pdf", datetime(2091, 3, 1, 9, 0)
    db_session.flush()
    assert _pagos(db_session, aceptada)[0]["recibo_subido"] == "2091-03-01T09:00:00"


def test_detalle_fuera_de_caja_es_404(db_session, make_historica, solicitud):
    for rid in (make_historica().id, solicitud.id):
        with pytest.raises(ServiceError) as e:
            CajaService.detalle(db_session, rid, HOY)
        assert (e.value.code, e.value.status) == ("no_encontrada", 404)
```

- [ ] **Step 2:** `PYT T/test_caja.py`. Esperado: FALLAN las nuevas.
- [ ] **Step 3: `detalle`.** `solicitud()` nula: `ServiceError("no_encontrada", "No se encontró la solicitud.", status=404)`. Los recibos vigentes se ordenan por `(paid_on, id)` y se pasan como `(paid_on, amount, pago)` a `account.cobertura`: es el mismo orden de `void`. `recibo` sale de esa cobertura. `anulable` solo en la parcialidad de mayor número cuyo recibo es el último vigente. `a_cobrar = money(amount - cubierto)`. `dias_vencido = (today - due_date).days` si `estado == "vencida"`, si no 0. `siguiente = c.proxima is not None and c.proxima.number == numero`. `referencia = bool(req.reference_path)`.
- [ ] **Step 4:** `PYT T/test_caja.py`. Esperado: pasan.
- [ ] **Step 5:** **COMMIT** `feat(prorrogas): detalle de Caja con el pago siguiente y el recibo anulable`

### Task 6: API de Caja (puntos 22, 23 y 25)

**Files:**
- Create: `APP/api/caja.py`
- Modify: `APP/router.py`, `APP/api/_common.py`, `APP/api/students_admin.py`
- Test: `T/test_caja_api.py`

**Interfaces:**
- Consumes: `CajaService`, `PaymentService.settle_next`, `PaymentService.void`, `StudentsService.periodos`, `recibo_pdf_response`.
- Produces (bajo `/api/prorrogas/v2/caja`, tags `prorrogas_tec-caja`, nombres `prorrogas_tec.api.caja.*`):

| Ruta | Permiso | Responde |
|---|---|---|
| `GET ""` `?q&semestre:int&filtro&orden&page` | `prorrogas_tec.caja.api.read` | `CajaService.listar` |
| `GET /semestres` (antes de `/{request_id}`) | igual | `{"items": StudentsService.periodos(db, hoy)["items"]}` |
| `GET /{request_id}` | igual | `CajaService.detalle` |
| `GET /{request_id}/referencia.pdf` | igual | `referencia_pdf_response(CajaService.solicitud(...))` |
| `GET /{request_id}/parcialidades/{numero}/recibo.pdf` | igual | `recibo_pdf_response(db, CajaService.solicitud(...), numero)` |
| `POST /{request_id}/saldar` `{numero: int, folio: str, fecha: date}` | `prorrogas_tec.payments.api.record` | detalle |
| `POST /{request_id}/recibos/{payment_id}/anular` `{motivo: str}` | `prorrogas_tec.payments.api.void` | detalle |

  `_common.referencia_pdf_response(req: ProrrogaRequest | None) -> Response`, movida de `students_admin.referencia`.

- [ ] **Step 1: Pruebas** (`T/test_caja_api.py`):

```python
from datetime import date

import pytest

from itcj2.apps.prorrogas_tec.models.plan import ProrrogaPayment
from itcj2.core.utils.timezone import db_now

API = "/api/prorrogas/v2/caja"
PLAN = [("1000.00", date(2091, 5, 1))]


def _hoy():
    return db_now().date().isoformat()


def test_lista_y_semestres(client_as, cajero, periodo, aceptada, con_plan):
    con_plan(aceptada, PLAN)
    c = client_as(cajero)
    assert c.get(f"{API}?semestre={periodo.id}").json()["items"][0]["id"] == aceptada.id
    assert periodo.id in [s["id"] for s in c.get(f"{API}/semestres").json()["items"]]


def test_saldar_y_anular(client_as, cajero, aceptada, con_plan):
    con_plan(aceptada, PLAN)
    c = client_as(cajero)
    d = c.post(f"{API}/{aceptada.id}/saldar", json={"numero": 1, "folio": "zz-200", "fecha": _hoy()}).json()
    assert d["situacion"] == "liquidada" and d["pagos"][0]["recibo"]["folio"] == "ZZ-200"
    rid = d["pagos"][0]["recibo"]["id"]
    d = c.post(f"{API}/{aceptada.id}/recibos/{rid}/anular", json={"motivo": "Se capturó mal"}).json()
    assert d["situacion"] == "al_corriente" and d["pagos"][0]["recibo"] is None


def test_saldar_fuera_de_orden_da_409(client_as, cajero, aceptada, con_plan):
    con_plan(aceptada, [("1000.00", date(2091, 2, 1)), ("1000.00", date(2091, 5, 1))])
    r = client_as(cajero).post(f"{API}/{aceptada.id}/saldar", json={"numero": 2, "folio": "ZZ-201", "fecha": _hoy()})
    assert r.status_code == 409 and r.json()["error"] == "pago_cambio"


def test_anular_recibo_de_otra_solicitud_es_404(client_as, cajero, db_session, aceptada, make_aceptada, con_plan):
    con_plan(aceptada, PLAN)
    otra = con_plan(make_aceptada(), PLAN, pagos=["1000.00"])
    pago = db_session.query(ProrrogaPayment).filter_by(request_id=otra.id).one()
    r = client_as(cajero).post(f"{API}/{aceptada.id}/recibos/{pago.id}/anular", json={"motivo": "Se capturó mal"})
    assert r.status_code == 404 and r.json()["error"] == "recibo_no_encontrado"


def test_fuera_de_caja_es_404(client_as, cajero, make_historica):
    h = make_historica()
    c = client_as(cajero)
    for ruta in (f"/{h.id}", f"/{h.id}/referencia.pdf", f"/{h.id}/parcialidades/1/recibo.pdf"):
        assert c.get(API + ruta).status_code == 404


def test_caja_abre_referencia_y_recibo(client_as, cajero, db_session, aceptada, con_plan):
    from itcj2.apps.prorrogas_tec.models.plan import ProrrogaInstallment
    from itcj2.apps.prorrogas_tec.services import storage
    from itcj2.apps.prorrogas_tec.services.reference_service import ReferenceService
    con_plan(aceptada, PLAN)
    c = client_as(cajero)
    assert c.get(f"{API}/{aceptada.id}/referencia.pdf").status_code == 404
    ReferenceService.save(db_session, aceptada, b"%PDF-1.4 r", aceptada.student_id)
    assert c.get(f"{API}/{aceptada.id}/referencia.pdf").content == b"%PDF-1.4 r"
    i = db_session.query(ProrrogaInstallment).filter_by(request_id=aceptada.id, number=1).one()
    i.receipt_path = f"recibos/0/{aceptada.id}-1-abc.pdf"
    storage.write_atomic(i.receipt_path, b"%PDF-1.4 s")
    db_session.flush()
    assert c.get(f"{API}/{aceptada.id}/parcialidades/1/recibo.pdf").content == b"%PDF-1.4 s"


@pytest.mark.parametrize("quien", ["secretaria_sin_cobro", "lector", "estudiante"])
@pytest.mark.parametrize("metodo, ruta, cuerpo", [
    ("get", "", None), ("get", "/{id}", None), ("get", "/{id}/referencia.pdf", None),
    ("get", "/{id}/parcialidades/1/recibo.pdf", None),
    ("post", "/{id}/saldar", {"numero": 1, "folio": "ZZ-202", "fecha": "2091-01-20"}),
    ("post", "/{id}/recibos/1/anular", {"motivo": "Se capturó mal"}),
])
def test_solo_caja_entra(request, client_as, aceptada, quien, metodo, ruta, cuerpo):
    c = client_as(request.getfixturevalue(quien))
    kw = {"json": cuerpo} if cuerpo else {}
    assert getattr(c, metodo)(API + ruta.format(id=aceptada.id), **kw).status_code == 403


def test_admin_global_cobra(client_as, make_user, aceptada, con_plan):
    con_plan(aceptada, PLAN)
    c = client_as(make_user(first_name="GLOBAL", last_name="ADMIN"), role="admin")
    assert c.post(f"{API}/{aceptada.id}/saldar", json={"numero": 1, "folio": "ZZ-203", "fecha": _hoy()}).status_code == 200
```

- [ ] **Step 2:** `PYT T/test_caja_api.py`. Esperado: FALLAN.
- [ ] **Step 3: Rutas.** Con la forma de `students_admin.py`: en un `ServiceError`, `db.rollback()` y `_err(e)`. `saldar` llama `settle_next(db, id, actor, numero=body.numero, folio=body.folio, paid_on=body.fecha)`; `anular` llama `PaymentService.void(db, payment_id, actor, motivo=body.motivo, request_id=request_id)`. Ambas devuelven `CajaService.detalle(db, request_id, db_now().date())`. Monta el router: `include_router(caja, prefix="/caja")`. `students_admin.referencia` pasa a usar `referencia_pdf_response(db.get(ProrrogaRequest, request_id))`.
- [ ] **Step 4:** `PYT T/`. Esperado: todo pasa de Global Constraints.
- [ ] **Step 5:** **COMMIT** `feat(prorrogas): API de Caja para buscar, saldar y anular`

---

## Bloque 2 · Pantallas de alumno y secretaria

### Task 7: Mi prórroga pide el recibo de cada pago cubierto (punto 26)

**Files:**
- Modify: `JS/estudiante/mi_prorroga.js`, `APP/static/css/estudiante/base.css`
- Test: `T/test_student_pages.py`

**Interfaces:**
- Consumes: `cuenta.parcialidades[].recibo_subido`, rutas de la Task 3.

- [ ] **Step 1: Prueba.**

```python
def test_mi_prorroga_pide_el_recibo_de_cada_pago():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[3] / "itcj2/apps/prorrogas_tec/static/js/estudiante/mi_prorroga.js").read_text(encoding="utf-8")
    for texto in ("Falta subir recibo", "Recibo subido el ", "Ver recibo", "Reemplazar", "/recibo.pdf"):
        assert texto in js
```

- [ ] **Step 2:** `PYT T/test_student_pages.py`. Esperado: FALLA.
- [ ] **Step 3: Pantalla.** `planDePagos(c)` pasa a `planDePagos(s)` (con `const c = s.cuenta`; actualiza su llamada en `solicitud`). A cada `pay-main` con `estado === "pagada"` agrégale `reciboPago(s, p)`, un `div.pay-recibo`:
  - Sin recibo: `el("span", "Falta subir recibo", "badge t-warn")` y `<label class="btn-text">Subir PDF<input type="file" accept="application/pdf" hidden></label>`.
  - Con recibo: `el("span", "Recibo subido el " + fecha(p.recibo_subido.slice(0, 10)), "hint")`, `<a class="btn-text" target="_blank" rel="noopener">Ver recibo</a>` a `.../parcialidades/{numero}/recibo.pdf` y el mismo `<label>` con el texto `Reemplazar`.
  - Al cambiar el archivo: el `fetch` de `seccionReferencia` contra `.../parcialidades/{numero}/recibo`; si sale bien, `cargar()`; si no, `<p class="error">` con `d.message || "No se pudo subir el recibo."`. Nada de esto bloquea el resto de la pantalla.
  - CSS, junto a `.pay-main`: `.pay-recibo { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 10px; margin-top: 4px; }`.
- [ ] **Step 4:** `PYT T/test_student_pages.py` y `node --check itcj2/apps/prorrogas_tec/static/js/estudiante/mi_prorroga.js`. Esperado: pasan.
- [ ] **Step 5:** **COMMIT** `feat(prorrogas): Mi prorroga pide y muestra el recibo de cada pago cubierto`

### Task 8: La secretaria deja de cobrar (punto 25)

**Files:**
- Modify: `APP/api/students_admin.py`, `JS/secretaria/estudiantes.js`, `APP/static/css/secretaria/base.css`
- Test: `T/test_payments.py`, `T/test_secretaria_pages.py`

**Interfaces:**
- Removes: `POST /estudiantes/{id}/recibos`, `POST /estudiantes/{id}/recibos/{payment_id}/anular`, `ReciboIn`, `AnularIn`, `_RECORD`, `_VOID` y el import de `PaymentService`.

- [ ] **Step 1: Pruebas.** En `T/test_payments.py` borra `test_api_registrar_y_anular` (la sustituye `test_saldar_y_anular` de la Task 6). En `T/test_secretaria_pages.py`, en el parametrizado de `test_lector_no_escribe`, cambia la fila de `/recibos` por:

```python
    ("/api/prorrogas/v2/caja/{id}/saldar", {"numero": 1, "folio": "ZZ-X", "fecha": "2091-01-20"}),
```

Y agrega:

```python
@pytest.mark.parametrize("ruta", ["/recibos", "/recibos/1/anular"])
def test_la_secretaria_ya_no_tiene_rutas_de_cobro(client_as, secretaria, aceptada, ruta):
    assert client_as(secretaria).post(f"/api/prorrogas/v2/estudiantes/{aceptada.id}{ruta}", json={}).status_code == 404


def test_estudiantes_js_ya_no_cobra():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[3] / "itcj2/apps/prorrogas_tec/static/js/secretaria/estudiantes.js").read_text(encoding="utf-8")
    for texto in ("/recibos", "Registrar recibo", "payments.api", "shortcut: la secretaria"):
        assert texto not in js
```

- [ ] **Step 2:** `PYT T/test_secretaria_pages.py`. Esperado: FALLAN.
- [ ] **Step 3: API.** Borra lo listado en **Removes**.
- [ ] **Step 4: Pantalla.** En `estudiantes.js`, `recibosCard` deja solo la lista "Recibos de Caja" (folio o "Histórico", fecha, monto, y `Anulado: motivo`): sin botón `Anular`, sin formulario, sin el comentario `shortcut:`. Borra `field()`, que queda sin uso. Quedan `input()` y `todayIso()`, que usa `planForm`.
- [ ] **Step 5: CSS.** Borra `.est-recibo-form`, `.est-modal .est-recibo-form .sec-btn` y sus dos líneas dentro de `@media (max-width: 900px)` y `@media (max-width: 760px)`.
- [ ] **Step 6:** `PYT T/`. Esperado: todo pasa. `T/test_students_api.py` no cambia: el expediente sigue trayendo `recibos` y `recibo`.
- [ ] **Step 7:** **COMMIT** `feat(prorrogas): la secretaria ya no registra ni anula recibos`

### Task 9: La secretaria ve el recibo y avisa una inconsistencia (punto 26)

**Files:**
- Create: `TPL/email/recibo_inconsistente.html`
- Modify: `APP/services/students_service.py`, `APP/services/notify.py`, `APP/services/events.py`, `APP/api/students_admin.py`, `JS/secretaria/estudiantes.js`, `APP/static/css/secretaria/base.css`
- Test: `T/test_students_actions.py`, `T/test_secretaria_pages.py`

**Interfaces:**
- Consumes: `ReceiptScanService.subidos`, `recibo_pdf_response`.
- Produces:
  - `StudentsService.report_receipt_issue(db, request_id: int, actor_id: int, numero: int, motivo: str) -> ProrrogaRequest`.
  - `expediente`: `cuenta.parcialidades[].recibo_subido`.
  - `GET /estudiantes/{id}/parcialidades/{numero}/recibo.pdf` con `_READ`; `POST /estudiantes/{id}/parcialidades/{numero}/avisar-inconsistencia` `{motivo}` con `_REMIND`, responde el expediente.
  - Evento y aviso `recibo_inconsistente`.
- Permisos en `estudiantes.js`, tabla de la Task 16 del Plan 5 ya corregida:

| Condición | Qué se oculta |
|---|---|
| `prorrogas_tec.plans.api.manage` | `planForm`, `Modificar plan`, cierre sin plan |
| `prorrogas_tec.students.api.remind` | Recordar (fila y modal), Recordar firma y referencia, **`Avisar inconsistencia`** |
| `prorrogas_tec.students.api.export` | `#estExport`, `Avisar desbloqueo` |

  La fila de `payments.api.record` / `.void` desaparece con la Task 8. `Ver recibo` no depende de un permiso extra: quien abre la pestaña ya puede leer.

- [ ] **Step 1: Pruebas.** En `T/test_secretaria_pages.py`, agrega al parametrizado de `test_lector_no_escribe`:

```python
    ("/api/prorrogas/v2/estudiantes/{id}/parcialidades/1/avisar-inconsistencia", {"motivo": "Motivo de prueba larga"}),
```

Y al final de `T/test_students_actions.py`:

```python
MOTIVO_AVISO = "El folio no coincide con el de Caja."


def _con_recibo(db, req):
    from itcj2.apps.prorrogas_tec.models.plan import ProrrogaInstallment
    from itcj2.apps.prorrogas_tec.services import storage
    i = db.query(ProrrogaInstallment).filter_by(request_id=req.id, number=1).one()
    i.receipt_path, i.receipt_uploaded_at = f"recibos/0/{req.id}-1-abc.pdf", datetime(2091, 3, 1, 9, 0)
    storage.write_atomic(i.receipt_path, b"%PDF-1.4 x")
    db.flush()


def test_la_secretaria_ve_y_abre_el_recibo(client_as, secretaria, db_session, aceptada, con_plan):
    con_plan(aceptada, [("1000.00", date(2091, 5, 1))])
    c = client_as(secretaria)
    assert c.get(f"{API}/{aceptada.id}/parcialidades/1/recibo.pdf").status_code == 404
    _con_recibo(db_session, aceptada)
    assert c.get(f"{API}/{aceptada.id}").json()["cuenta"]["parcialidades"][0]["recibo_subido"] == "2091-03-01T09:00:00"
    assert c.get(f"{API}/{aceptada.id}/parcialidades/1/recibo.pdf").content == b"%PDF-1.4 x"


def test_avisar_inconsistencia(db_session, aceptada, secretaria, con_plan, enviar_correo):
    from itcj2.apps.prorrogas_tec.models.event import ProrrogaEvent
    from itcj2.core.models.notification import Notification
    from itcj2.templates import templates
    con_plan(aceptada, [("1000.00", date(2091, 5, 1))])
    _con_recibo(db_session, aceptada)
    StudentsService.report_receipt_issue(db_session, aceptada.id, secretaria.id, 1, f"  {MOTIVO_AVISO}  ")
    ev = db_session.query(ProrrogaEvent).filter_by(request_id=aceptada.id, event_type="recibo_inconsistente").one()
    assert ev.payload == {"numero": 1, "motivo": MOTIVO_AVISO} and ev.actor_id == secretaria.id
    n = db_session.query(Notification).filter_by(user_id=aceptada.student_id, type="prorroga_recibo_inconsistente").one()
    assert n.title == "Revisa el recibo que subiste" and n.body == f"Pago 1: {MOTIVO_AVISO}"
    envio = enviar_correo.calls[0]
    assert envio["subject"] == n.title
    html = templates.env.get_template("prorrogas_tec/email/recibo_inconsistente.html").render(**envio["context"])
    assert MOTIVO_AVISO in html


@pytest.mark.parametrize("motivo", ["muy corto", "x" * 501])
def test_motivo_del_aviso_invalido(db_session, aceptada, secretaria, motivo):
    with pytest.raises(ServiceError) as e:
        StudentsService.report_receipt_issue(db_session, aceptada.id, secretaria.id, 1, motivo)
    assert (e.value.code, e.value.status) == ("motivo_invalido", 400)


def test_sin_recibo_no_se_avisa(db_session, aceptada, secretaria, con_plan, enviar_correo):
    con_plan(aceptada, [("1000.00", date(2091, 5, 1))])
    with pytest.raises(ServiceError) as e:
        StudentsService.report_receipt_issue(db_session, aceptada.id, secretaria.id, 1, MOTIVO_AVISO)
    assert (e.value.code, e.value.status) == ("no_aplica", 409) and enviar_correo.calls == []


def test_aviso_cuyo_correo_no_sale_se_guarda_y_lo_dice(client_as, secretaria, db_session, aceptada, con_plan, monkeypatch):
    from itcj2.apps.prorrogas_tec.services import notify
    monkeypatch.setattr(notify, "send_email", lambda **k: False)
    con_plan(aceptada, [("1000.00", date(2091, 5, 1))])
    _con_recibo(db_session, aceptada)
    r = client_as(secretaria).post(f"{API}/{aceptada.id}/parcialidades/1/avisar-inconsistencia", json={"motivo": MOTIVO_AVISO})
    assert r.status_code == 200 and r.json()["correo_enviado"] is False
```

- [ ] **Step 2:** `PYT T/test_students_actions.py T/test_secretaria_pages.py`. Esperado: FALLAN las nuevas.
- [ ] **Step 3: Servicio.** `motivo` sin espacios a los lados y de 10 a 500 caracteres: si no, `ServiceError("motivo_invalido", "El motivo debe tener entre 10 y 500 caracteres.", 400)`. Solicitud inexistente o no `aceptada`: `no_encontrada` (404). `numero` fuera de `ReceiptScanService.subidos`: `ServiceError("no_aplica", "El alumno aún no sube ese recibo.", status=409)`. Luego `log_event` con `{"numero": numero, "motivo": motivo}`, `notify.notify_student(db, req, kind="recibo_inconsistente", link="/prorrogas/estudiante", body=f"Pago {numero}: {motivo}", context={"numero": numero, "motivo": motivo})` y `db.commit()`, con rollback si falla. No hace falta candado ni reintento: si el correo no sale, el expediente responde `correo_enviado: false` y el modal ya lo avisa con `apply`.
- [ ] **Step 4: Aviso.** `EVENT_TYPES` suma `"recibo_inconsistente"`. `_AVISOS["recibo_inconsistente"] = ("Revisa el recibo que subiste", "recibo_inconsistente.html")`. Plantilla:

```html
{% extends "prorrogas_tec/email/_base_email.html" %}
{% block cuerpo %}
<p>La secretaría revisó el recibo que subiste del <strong>pago {{ numero }}</strong> de la prórroga <strong>{{ folio }}</strong> y encontró algo que no coincide:</p>
<p><strong>Motivo:</strong> {{ motivo }}</p>
<p>Si hace falta, súbelo de nuevo en Mi prórroga.</p>
{% endblock %}
{% block boton %}Ir a Mi prórroga{% endblock %}
```

- [ ] **Step 5: API y expediente.** En `expediente`, tras la cobertura: `parc["recibo_subido"] = subidos.get(parc["numero"])`. Las dos rutas de **Produces**, con la forma de las vecinas.
- [ ] **Step 6: Pantalla.** En `estudiantes.js`, `pagoRow(q, n, sid)` (`planPane` le pasa `x.solicitud.id`) agrega, solo si `q.estado === "pagada"` o hay `q.recibo_subido`, una fila `div.est-pago-scan`:
  - Con `q.recibo_subido`: `Recibo subido el {fmtDate}`, `<a class="est-ver" target="_blank" rel="noopener">Ver recibo</a>` a `${API}${EST}/${sid}/parcialidades/${q.numero}/recibo.pdf` y, con `can(REMIND)`, el botón `Avisar inconsistencia`.
  - Sin recibo y pagada: `Falta subir recibo`.
  - El botón pone `ui.avisando = q.numero` y repinta. Con eso, debajo: `<textarea maxlength="500" rows="2" placeholder="¿Qué no coincide? (mínimo 10 caracteres)">`, botones `Enviar aviso` y `Cancelar`. Enviar llama `apply(await api(`${EST}/${sid}/parcialidades/${q.numero}/avisar-inconsistencia`, { body: { motivo } }), "Aviso enviado.")` y limpia `ui.avisando`. `openPanel` también lo limpia al cambiar de alumno.
  - `HIST` suma `recibo_subido: "Recibo subido por el alumno"` y `recibo_inconsistente: "Aviso de inconsistencia del recibo"`. `detalle` devuelve `Pago ${d.numero}` y `Pago ${d.numero} · ${d.motivo}`. `PUNTO`: `azul` y `naranja`.
  - CSS, junto a `.est-pago`: `.est-pago-scan { grid-column: 1 / -1; display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px; font-size: 13px; color: var(--m-muted); }` y `.est-pago-scan textarea { flex: 1 1 100%; padding: 8px 10px; border: 1.5px solid rgba(26, 19, 14, .18); border-radius: 8px; font: inherit; }`.
- [ ] **Step 7:** `PYT T/` y `node --check itcj2/apps/prorrogas_tec/static/js/secretaria/estudiantes.js`. Esperado: todo pasa.
- [ ] **Step 8:** **COMMIT** `feat(prorrogas): la secretaria abre el recibo del alumno y avisa una inconsistencia`

---

## Bloque 3 · Pestaña de Caja

### Task 10: Pestaña, barra y lista (puntos 22 y 23)

**Files:**
- Create: `TPL/secretaria/caja.html`, `JS/secretaria/caja.js`
- Modify: `APP/pages/secretaria.py`, `APP/pages/landing.py`, `TPL/secretaria/_base.html`, `APP/static/css/secretaria/base.css`
- Test: `T/test_secretaria_pages.py`

**Interfaces:**
- Consumes: `GET /caja`, `GET /caja/semestres` (Tasks 4 y 6).
- Produces: `/prorrogas/secretaria/caja`, contexto `rol_usuario: str`, `TPL/secretaria/caja.html` con los `id` de abajo, y en `caja.js` las funciones `api`, `el`, `show`, `fmtDate`, `cents`, `money`, `pesos` copiadas de `estudiantes.js`, `SITUACION` y `loadList()`.

- [ ] **Step 1: Pruebas** (`T/test_secretaria_pages.py`). Agrega `"caja"` al parametrizado de `test_lector_no_abre_lo_que_no_le_toca` y:

```python
def test_pestana_caja(client_as, cajero):
    page = client_as(cajero).get(f"{BASE}/caja").text
    for texto in ("Busca al alumno o elígelo de la lista para cobrar su siguiente pago.", "No. de control o nombre",
                  "Todos los semestres", "Por cobrar", "Ordenar por", "Más urgente", "Próximo pago", "Saldo mayor",
                  "Nombre (A–Z)", "Con adeudo", "Al corriente", "No hay alumnos en este filtro.",
                  "No encontramos a ese alumno.", "debe acudir a Centro de Cómputo", "caja.js"):
        assert texto in page


def test_cajero_solo_ve_su_pestana_rotulada_estudiantes(client_as, cajero):
    page = client_as(cajero).get(f"{BASE}/caja").text
    assert f'href="{BASE}/caja"' in page and f'href="{BASE}/estudiantes"' not in page
    assert "<span>Estudiantes</span>" in page and "<span>Caja</span>" not in page
    assert '<div class="sec-user-role">Caja</div>' in page and "sec-topnav-one" in page
    assert "prorrogas_tec.payments.api.record" in page


def test_admin_global_ve_las_dos_y_la_de_caja_se_rotula_caja(client_as, make_user):
    page = client_as(make_user(first_name="GLOBAL", last_name="ADMIN"), role="admin").get(f"{BASE}/caja").text
    assert "<span>Caja</span>" in page and "<span>Estudiantes</span>" in page and f'href="{BASE}/estudiantes"' in page


def test_cajero_entra_directo_a_su_pestana(client_as, cajero):
    c = client_as(cajero)
    r = c.get("/prorrogas/", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == BASE
    r = c.get(BASE, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == f"{BASE}/caja"


def test_secretaria_no_ve_caja_y_conserva_su_rotulo(client_as, secretaria):
    c = client_as(secretaria)
    assert c.get(f"{BASE}/caja", follow_redirects=False).status_code == 403
    page = c.get(f"{BASE}/estudiantes").text
    assert f'href="{BASE}/caja"' not in page and "Secretaría · Subdirección Académica" in page
```

- [ ] **Step 2:** `PYT T/test_secretaria_pages.py`. Esperado: FALLAN.
- [ ] **Step 3: Páginas.** En `secretaria.py`:
  - `TABS` suma `("caja", "Caja", "prorrogas_tec.secretaria.page.caja")` tras Estudiantes. `_HOME_ORDER` lo suma al final.
  - `_contexto`: si `estudiantes` no está entre las visibles, la de `caja` se rotula `"Estudiantes"`. `rol_usuario` es `"Caja"` si la única visible es `caja`; si no, `"Secretaría · Subdirección Académica"`.
  - `secretaria_caja = _tab("caja", "caja", "Prórrogas · Caja")` y la línea en el docstring.
  - En `landing.py`: `("caja", "/prorrogas/secretaria")` en `_ROLE_HOME`, después de `admin`.
- [ ] **Step 4: Barra.** En `_base.html`: `<header class="sec-topnav{% if tabs|length == 1 %} sec-topnav-one{% endif %}">`, `{% elif key in ('estudiantes', 'caja') %}` para el ícono y `{{ rol_usuario }}` en `.sec-user-role`. En `base.css`, el corte de `.sec-topnav` pasa de 1020 a 1120 px (el admin global ve siete pestañas) y, dentro de ese `@media`: `.sec-topnav-one { grid-template-columns: 1fr auto; height: 56px; } .sec-topnav-one .sec-tabs { display: none; } .sec-topnav-one .sec-user { display: block; }` (canvas, líneas 28 a 31).
- [ ] **Step 5: Plantilla** `TPL/secretaria/caja.html`. Los `<svg>` salen de las líneas del canvas que se indican:

```html
{% extends "prorrogas_tec/secretaria/_base.html" %}
{% block content %}
  <section class="caj" data-api="/api/prorrogas/v2">
    <div>
      <h1 class="sec-h1">Estudiantes</h1>
      <p class="caj-sub">Busca al alumno o elígelo de la lista para cobrar su siguiente pago.</p>
    </div>
    <div class="caj-bar">
      <label class="caj-field caj-field-q">
        <span>No. de control o nombre</span>
        <span class="caj-q" id="cajQBox">
          {# svg de la línea 44 #}
          <input id="cajQ" placeholder="Ej. 21430117 o Andrea Salgado" maxlength="80" autocomplete="off">
          <button type="button" id="cajQBorrar" aria-label="Borrar búsqueda" hidden>{# svg de la línea 46 #}</button>
        </span>
      </label>
      <label class="caj-field caj-field-sem">
        <span>Semestre</span>
        <select id="cajSem"><option value="">Todos los semestres</option></select>
      </label>
    </div>
    <div class="est-error" id="cajError" role="alert" hidden></div>
    <div class="caj-listhead" id="cajListHead">
      <div class="caj-listtop">
        <div><h2>Por cobrar</h2><div class="caj-count" id="cajCuenta"></div></div>
        <label class="caj-orden">Ordenar por
          <select id="cajOrden">
            <option value="urgente">Más urgente</option>
            <option value="proximo">Próximo pago</option>
            <option value="saldo">Saldo mayor</option>
            <option value="nombre">Nombre (A–Z)</option>
          </select>
        </label>
      </div>
      <div class="caj-tabs" id="cajFiltros" role="tablist" aria-label="Situación">
        <button type="button" role="tab" data-f="todos" aria-selected="true">Todos<b></b></button>
        <button type="button" role="tab" data-f="con_adeudo" aria-selected="false">Con adeudo<b></b></button>
        <button type="button" role="tab" data-f="al_corriente" aria-selected="false">Al corriente<b></b></button>
      </div>
    </div>
    <div class="caj-vacio" id="cajVacio" hidden>No hay alumnos en este filtro.</div>
    <div class="caj-none" id="cajNone" role="status" hidden>
      <span>{# svg de la línea 62 #}</span>
      <div><b>No encontramos a ese alumno.</b><p>Si no está en el sistema, debe acudir a Centro de Cómputo.</p></div>
    </div>
    <div class="caj-res" id="cajRes" hidden>
      <div class="caj-count" id="cajResN" hidden></div>
      <div class="caj-tabla">
        <div class="caj-fila caj-fila-head" aria-hidden="true"><span>No. de control</span><span>Nombre</span><span>Semestre</span><span>Folio de prórroga</span><span>Siguiente pago</span><span>Situación</span></div>
        <div id="cajFilas" aria-live="polite"></div>
        <nav class="caj-pags" id="cajPags" aria-label="Páginas" hidden>
          <span id="cajRango"></span>
          <div>
            <button type="button" id="cajPrev" aria-label="Página anterior">{# svg de la línea 111 #}<span>Anterior</span></button>
            <span id="cajNums"></span>
            <button type="button" id="cajNext" aria-label="Página siguiente">{# svg de la línea 115 #}<span>Siguiente</span></button>
          </div>
        </nav>
      </div>
    </div>
  </section>
{% endblock %}
{% block scripts %}
  <script src="{{ url_for('static', filename='prorrogas_tec/js/secretaria/caja.js') }}?v={{ sv('prorrogas_tec', 'js/secretaria/caja.js') }}"></script>
{% endblock %}
```

- [ ] **Step 6: `caja.js`, lista.** Arranca como `estudiantes.js` (`.caj`, `API = root.dataset.api`, `perms`, `can`). Estado `st = { q: "", semestre: "", filtro: "todos", orden: "urgente", page: 1, openId: null }`, con guardia de secuencia como `listSeq`.
  - Al cargar: llena `#cajSem` con `/caja/semestres` (`{id, label}`) y llama `loadList()`, que omite `q` y `semestre` si están vacíos. `#cajQ` espera 300 ms; `#cajSem`, `#cajOrden` y las pestañas regresan a `page = 1`.
  - `#cajQBorrar` y el borde azul de `#cajQBox` (`.has-text`) aparecen con texto; `#cajSem` lleva `.is-set` si hay semestre.
  - **Sin texto:** `#cajListHead` visible. `#cajCuenta` dice `${n} ${n === 1 ? "alumno" : "alumnos"} con pagos pendientes` con `conteos.todos`. Cada pestaña muestra su conteo en `<b>`. Sin filas, `#cajVacio`. `#cajPags` solo si hay más de una página: `#cajRango` es `${desde}–${hasta} de ${total}`; `#cajNums` trae la página actual ±3.
  - **Con texto:** `#cajListHead` y `#cajPags` ocultos. `#cajResN` es `1 resultado` o `${n} resultados`, y si `total > items.length`, `${items.length} de ${total} resultados`. Sin filas, `#cajNone`.
  - `rowFor(e)` es un `<button class="caj-fila">` con seis `<span>`: `.caj-c`, `.caj-nom`, `.caj-s`, `.caj-f`, `.caj-nx` (dos líneas) y `.caj-st` con `est-badge est-badge-{tono}`. `SITUACION` es la de `estudiantes.js`. Primera línea de `.caj-nx`: `Sin plan` si `situacion === "sin_plan"`, `fmtDate(siguiente.fecha)` si hay `siguiente`, `—` si no. Segunda línea: `${pesos(monto)} · falta 1 pago` o `· faltan ${faltan} pagos`; sin plan, vacía; liquidada, `Sin pagos pendientes`. La fila abierta lleva `.is-open`.
- [ ] **Step 7: CSS.** Bloque `/* ── Caja ── */` **antes** del comentario "Ancho completo", con los valores inline del canvas pasados a clases y tokens (`#1A130E` = `--ink`, `#F7F7F2` = `--paper`, `#652F2A` = `--wine`, `#6799E0` = `--blue`, `#F27340` = `--orange`, `#c4541f` = `--alert`, `rgba(26,19,14,.1)` = `--line`):

| Clases | Canvas |
|---|---|
| `.caj`, `.caj-sub` | 34 a 37 |
| `.caj-bar`, `.caj-field`, `.caj-field-q`, `.caj-field-sem`, `.caj-q`, `.caj-q.has-text`, `#cajSem.is-set` | 40 a 54 |
| `.caj-vacio`, `.caj-none` | 57 a 64 |
| `.caj-listhead`, `.caj-listtop`, `.caj-orden`, `.caj-count`, `.caj-tabs` (`button`, `[aria-selected="true"]`, `b`) | 68 a 87 |
| `.caj-res`, `.caj-tabla`, `.caj-fila`, `.caj-fila-head` y los `span` | 92 a 104 |
| `.caj-pags` | 108 a 118 |

  Con `max-width: 900px`, la tabla pasa a tarjetas (canvas 123 a 127): `.caj-fila-head` y `.caj-f` ocultos, `.caj-tabla` sin fondo ni borde, cada `.caj-fila` con fondo blanco y borde; arriba nombre y pastilla, en medio control · semestre, abajo fecha a la izquierda y monto a la derecha. `.caj-pags` como canvas 130 a 134: `Anterior` y `Siguiente` con texto, sin `svg` ni `#cajNums`. Con `max-width: 760px`: `.caj .sec-h1 { font-size: 26px; }`. Dentro del bloque "Ancho completo", que sigue al final: `body.sec .sec-main > .caj { flex: 1; padding: 28px 40px; background: var(--paper); }` y, en su `@media (max-width: 760px)`, `body.sec .sec-main > .caj { padding: 20px 16px 28px; }`.
- [ ] **Step 8:** `PYT T/` y `node --check itcj2/apps/prorrogas_tec/static/js/secretaria/caja.js`. Esperado: todo pasa.
- [ ] **Step 9:** **COMMIT** `feat(prorrogas): pestana de Caja con lista por cobrar y busqueda`

### Task 11: Modal de Caja: detalle, saldar y anular (puntos 23 y 24)

**Files:**
- Modify: `TPL/secretaria/caja.html`, `JS/secretaria/caja.js`, `APP/static/css/secretaria/base.css`
- Test: `T/test_secretaria_pages.py`

**Interfaces:**
- Consumes: `GET /caja/{id}`, `POST /caja/{id}/saldar`, `POST /caja/{id}/recibos/{rid}/anular`, los PDF (Task 6), y la forma JSON de la Task 5.

- [ ] **Step 1: Pruebas.**

```python
def test_modal_de_caja(client_as, cajero):
    page = client_as(cajero).get(f"{BASE}/caja").text
    for texto in ('id="cajDialog"', "Folio de prórroga", 'aria-label="Copiar folio de prórroga"'):
        assert texto in page


def test_caja_js_trae_el_copy_del_diseno():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[3] / "itcj2/apps/prorrogas_tec/static/js/secretaria/caja.js").read_text(encoding="utf-8")
    for texto in ("Aún no se puede cobrar", "Se cobra igual, sin recargo.", "Se cobra después de ",
                  "El alumno ya subió un recibo el ", "Pago completo, sin abonos.", "Captura el folio del recibo de Caja.",
                  "Elige la fecha de pago.", "La fecha no puede ser futura.", "La prórroga quedó liquidada.",
                  "Escribe el motivo de la anulación.", "se conserva: sirve para verificar el folio correcto.",
                  "Ver recibo del alumno para comparar", "Abrir PDF", "Sin referencia"):
        assert texto in js
```

- [ ] **Step 2:** `PYT T/test_secretaria_pages.py`. Esperado: FALLAN.
- [ ] **Step 3: Plantilla.** Antes de `{% endblock %}` del contenido (los `<template>` traen los `svg` de esas líneas del canvas):

```html
  <dialog class="est-modal caj-modal" id="cajDialog" aria-label="Detalle del alumno">
    <div class="caj-m-head">
      <div class="caj-m-who">
        <div class="est-m-title"><h2 id="cajNombre"></h2><span class="est-badge" id="cajBadge"></span></div>
        <div class="est-m-sub"><span class="est-chip" id="cajControl"></span><span id="cajCarrera"></span><span aria-hidden="true">·</span><span id="cajSemestre"></span></div>
      </div>
      <div class="caj-m-acc">
        <div class="caj-folio">
          <div><small>Folio de prórroga</small><b id="cajFolio"></b></div>
          <button type="button" class="est-ico-btn" id="cajCopiar" aria-label="Copiar folio de prórroga" title="Copiar folio">{# svg de la línea 159 #}</button>
        </div>
        <button type="button" class="sol-x" id="cajCerrar" aria-label="Cerrar" title="Cerrar (Esc)">{# svg de la línea 161 #}</button>
      </div>
    </div>
    <div class="caj-m-body" id="cajBody"></div>
    <div class="sec-toast" id="cajToast" role="status" aria-live="polite" hidden></div>
  </dialog>
  <template id="tplOk">{# línea 169 #}</template>
  <template id="tplCal">{# línea 177 #}</template>
  <template id="tplLock">{# línea 239 #}</template>
  <template id="tplDoc">{# línea 269 #}</template>
  <template id="tplDocTxt">{# línea 288 #}</template>
```

- [ ] **Step 4: `caja.js`, modal.** Copia de `estudiantes.js` `toast` (con `cajDialog` y `cajToast`), `todayIso`, `busy`, `button`, `plural` e `icon`. Las filas de la lista abren con `openPanel(id)`. `ui = { x: null, form: null, anul: null, notice: null, just: null }`, todo en `null` al abrir otro alumno. Guardia `openSeq`. `showModal`; cierra con Esc, con la ✕ y con clic en el fondo. Copiar: `navigator.clipboard.writeText` y toast `Folio ${folio} copiado`. `paint()` rellena `#cajBody` en este orden:
  1. Aviso `ui.notice` (`.caj-notice.is-ok` o `.is-anul`, ícono `tplOk`, botón `Cerrar aviso`).
  2. Sin plan (`pagos` vacío): tarjeta con `tplCal`, **Aún no se puede cobrar** y `Su prórroga está aceptada, pero Secretaría todavía no arma su plan de pagos. Pídele al alumno que regrese cuando el plan esté listo.`
  3. Con plan: `.caj-sums` con `Total`, `Pagado` y `Saldo`. El saldo va en `--alert` si `situacion === "atrasada"`, en `--wine` si es 0, y en `--ink` si no.
  4. `.caj-cols`: columna de pagos (`Pagos` + tarjetas) y tarjeta de **Referencia bancaria**. Con `referencia`: `<a target="_blank" rel="noopener">Abrir PDF</a>` a `/caja/{id}/referencia.pdf` y `La subió el alumno. Solo lectura.` Sin ella: `Sin referencia` y `El alumno aún no la sube.`

  Cada tarjeta `.caj-pago` lleva `Pago {i}/{n}` (siempre, también `1/1`), `Fecha límite {fecha}`, monto (`monto` si `pagada`, si no `a_cobrar`) y pastilla: `Pagado`; `Vencido · {plural(dias_vencido, "día")}` si `vencida`; `Pendiente` si `pendiente` o `parcial`. Y además:

| Condición | Se pinta |
|---|---|
| `pagada` | `Folio de Caja {recibo.folio \|\| "Histórico"} · {fecha}`, `Recibo subido el {fecha}` o `Falta subir recibo` con su punto de color, y `Anular` si `anulable && can(VOID) && !ui.form && !ui.anul` |
| `siguiente`, sin formulario abierto, `can(RECORD)` | botón `Saldar pago`; si `vencida`, nota `Se cobra igual, sin recargo.` |
| sin cubrir y no `siguiente` | `Se cobra después de Pago {k}/{n}.`, con `k` = el `numero` que tiene `siguiente` |
| sin cubrir con `recibo_subido` | `El alumno ya subió un recibo el {fecha}.` y enlace `Ver recibo` a `/caja/{id}/parcialidades/{numero}/recibo.pdf` |

  `RECORD` y `VOID` son `prorrogas_tec.payments.api.record` y `.void`.

  **Saldar** (canvas 234 a 260): título `Saldar Pago {i}/{n}`; `Monto` fijo con `tplLock` y `Pago completo, sin abonos.`; `Folio del recibo de Caja` con `placeholder="Ej. C-10302"` y `maxlength="40"`; `Fecha de pago` con `.cfg-date` (reutiliza `.cfg-date-txt`, `.cfg-err`, `.cfg-hint`, ícono `tplCal`), `max` = hoy, valor inicial hoy, hint `Hoy` o `No puede ser una fecha futura.`; botones `Cancelar` y `Confirmar pago`.
  - Validación en el cliente: `Captura el folio del recibo de Caja.`, `Elige la fecha de pago.`, `La fecha no puede ser futura.`, cada error junto a su campo, con `aria-invalid`.
  - Respuesta: `folio_duplicado` y `folio_invalido` van junto al folio, `fecha_invalida` junto a la fecha, con `r.data.message`. Cualquier otro error (`pago_cambio` incluido): recarga el detalle y lo muestra en el aviso.
  - Al salir bien: `ui.just = numero`, aviso `Pago {i}/{n} saldado con el folio {recibo.folio}.` más ` La prórroga quedó liquidada.` si `situacion === "liquidada"`, y `loadList()`.

  **Anular** (canvas 264 a 278): `Anular recibo {folio || "Histórico"}`; `Pago {i}/{n} vuelve a quedar sin cubrir y se podrá saldar de nuevo.` y, con `recibo_subido`, `El recibo que subió el alumno se conserva: sirve para verificar el folio correcto.` más el enlace `Ver recibo del alumno para comparar`; `Motivo de la anulación` (`rows="2"`, `placeholder="Ej. Se capturó mal el folio"`); `Cancelar` y `Anular recibo`.
  - Motivo vacío: `Escribe el motivo de la anulación.`. `motivo_requerido` va bajo el campo; otro error, recarga y aviso.
  - Al salir bien: aviso `.is-anul` `Recibo {folio} anulado. Pago {i}/{n} vuelve a estar {estado === "vencida" ? "vencido" : "pendiente"}.` y `loadList()`.

  Toda escritura pasa por `busy` (deshabilita el botón: doble clic).
- [ ] **Step 5: CSS** en el bloque de Caja, con la misma regla de tokens:

| Clases | Canvas |
|---|---|
| `.caj-modal` (`height: min(720px, calc(100vh - 32px))`), `.caj-m-head`, `.caj-m-who`, `.caj-m-acc`, `.caj-folio`, `.caj-m-body` | 143 a 165 |
| `.caj-notice`, `.is-ok`, `.is-anul` | 168 a 172, 460 |
| `.caj-sinplan` | 176 a 179 |
| `.caj-sums` | 183 a 190, 411 y 412 |
| `.caj-cols`, `.caj-pagos`, `.caj-pago` (`.is-paid`, `.is-venc`, `.is-next`, `.is-just`), `.caj-pill` | 193 a 207, 419, 423 y 424 |
| `.caj-paid`, `.caj-dot`, `.caj-anular-btn` | 210 a 215, 426 |
| `.caj-saldar-row`, `.caj-later`, `.caj-scan` | 219 a 231 |
| `.caj-form`, `.caj-form-grid`, `.caj-lock`, `.caj-confirm` | 234 a 260 |
| `.caj-anul`, `.caj-anul-ok` | 264 a 278 |
| `.caj-ref`, `.caj-ref-vacia` | 285 a 295 |

  Con `max-width: 760px`: `.caj-m-head` y `.caj-m-body` llevan los paddings móviles del canvas (línea 479: `16px` y `0 16px 24px`) y `Saldar pago` ocupa todo el ancho (`btnFlex`). `.est-modal` ya es pantalla completa ahí.
- [ ] **Step 6:** `PYT T/` y `node --check itcj2/apps/prorrogas_tec/static/js/secretaria/caja.js`. Esperado: todo pasa.
- [ ] **Step 7:** **COMMIT** `feat(prorrogas): detalle de Caja con saldar y anular`

---

## Bloque 4 · Cierre

### Task 12: Documentación

**Files:**
- Create: `APP/docs/flows/caja.md`
- Modify: `APP/docs/flows/secretaria_estudiantes.md`, `APP/docs/flows/estudiante_solicitud.md`, `APP/docs/README.md`, `APP/docs/PENDIENTES.md`
- Test: ninguno (solo documentos)

**Interfaces:** ninguna.

- [ ] **Step 1: `caja.md`,** con el formato de `secretaria_consulta.md`: objetivo; tabla (actores `caja` y admin global; permisos `secretaria.page.caja`, `caja.api.read`, `payments.api.record`, `payments.api.void`; precondición `09_insert_caja.sql`); ruta `/prorrogas/secretaria/caja`; pasos con endpoint, método y efecto (buscar, lista Por cobrar, detalle, saldar, anular, referencia, recibo); universo y regla "solo el último"; errores `pago_cambio`, `no_es_el_ultimo`, `folio_duplicado`, `folio_invalido`, `fecha_invalida`, `motivo_requerido`, `sin_plan`, `sin_semestre`, `no_aceptada`, `no_encontrada`, `recibo_no_encontrado`, `filtro_invalido`, `orden_invalido`.
- [ ] **Step 2: Flujos existentes.** En `secretaria_estudiantes.md`: quita `payments.api.*` de la tabla, borra los pasos 6 y 7 y su mención en la nota de "Los pasos 5 a 8 y 10" (renumera), y en "Reglas de los recibos" di que los captura Caja ([caja.md](caja.md)). Agrega `Ver recibo` y `Avisar inconsistencia` como pasos, y `motivo_invalido`/`no_aplica` a errores. En `estudiante_solicitud.md`: paso nuevo de recibo escaneado, campo `recibo_subido` y errores `recibo_invalido`, `recibo_muy_grande`, `recibo_no_aplica`.
- [ ] **Step 3: README.** En `README.md`: fila `caja` en "Qué ve cada rol" (`Estudiantes (la de Caja)` | buscar, ver detalle y referencia, saldar, anular el último, ver recibo escaneado); en `secretaria` cambia "recibos" por "ve pagos y recibos, avisa inconsistencias"; `caja.py`, `caja_service.py` y `receipt_scan_service.py` en el mapa; `caja` en la lista de `flows/`; `payment_service.py` dice "saldar el pago siguiente y anular el último".
- [ ] **Step 4: PENDIENTES** por reemplazo exacto:

```bash
python3 - <<'PY'
from pathlib import Path

p = Path("/home/deigol/repos/itcj/itcj2/apps/prorrogas_tec/docs/PENDIENTES.md")
t = p.read_text(encoding="utf-8")
H27 = ("| H27 | Antes de llevar Caja a producción (2026-11-09) | Sin esto no existen las columnas, el rol ni los permisos de Caja, "
       "y la secretaria conservaría el permiso de cobro | Aplicar `pr20261109b`, copiar `database/DML/prorrogas_tec/09_insert_caja.sql` "
       "al servidor (está fuera de git), correr `init-prorrogas` y asignar el rol `caja` a quienes cobran |\n")
R2 = ("| R2 | Un recibo viejo que cubre un pago a medias y es el último vigente no tiene botón Anular en Caja (2026-11-09) | "
      "Solo pasa con capturas anteriores a Caja o del Excel; Caja no puede corregirlo desde su pantalla | "
      "Si aparece, mostrar `Anular` también en la fila parcial |\n")
cambios = [
    ("Diseñar la vista de Caja; crear su rol y permisos en Prórrogas (sin tocar TitulaTec) y quitarle a la secretaria `payments.api.record/void` |",
     "**[hecho 2026-11-09]** Pestaña de Caja ([flujo](flows/caja.md)), rol `caja` con sus permisos y la secretaria ya no cobra (`09_insert_caja.sql`) |"),
    ("**[hecho 2026-11-09]** en parte. Subida y almacenamiento", "**[hecho 2026-11-09]** Subida y almacenamiento"),
    (" Falta: que Caja la vea, porque su vista no existe (H20) |", " Caja la abre desde su detalle (solo lectura) |"),
    ("| H22 | Rol Jefe de solo lectura (2026-11-09) |", H27 + "| H22 | Rol Jefe de solo lectura (2026-11-09) |"),
    ("\n\n## Técnicos (diferidos de las revisiones del Plan 3, 2026-10-29)", "\n" + R2 + "\n## Técnicos (diferidos de las revisiones del Plan 3, 2026-10-29)"),
]
for viejo, nuevo in cambios:
    assert t.count(viejo) == 1, viejo
    t = t.replace(viejo, nuevo)
p.write_text(t, encoding="utf-8")
PY
```

  Esperado: termina sin `AssertionError`.
- [ ] **Step 5:** `git diff --stat -- itcj2/apps/prorrogas_tec/docs/PENDIENTES.md`. Esperado: solo ese archivo, con 3 filas cambiadas y 2 nuevas.
- [ ] **Step 6:** **COMMIT** `docs(prorrogas): flujo de Caja y cierre de H20 y H21`

### Task 13: Semilla y cierre (**GATE**)

**Files:**
- Modify: `itcj2/cli/prorrogas.py`
- Fuera de git: `database/DML/prorrogas_tec/09_insert_caja.sql`

**Interfaces:**
- Produces: rol `caja`, permisos `prorrogas_tec.secretaria.page.caja` y `prorrogas_tec.caja.api.read`.

- [ ] **Step 1: CLI.** Agrega `"09_insert_caja.sql"` al final de `_DML_FILES` y las líneas de `08` y `09` al docstring de `init_prorrogas_command`.
- [ ] **Step 2:** `PYT T/`. Esperado: todo pasa.
- [ ] **Step 3:** **COMMIT** (sin `database/`) `feat(prorrogas): init-prorrogas carga la semilla de Caja`
- [ ] **Step 4: GATE (controlador).** La semilla `database/DML/prorrogas_tec/09_insert_caja.sql` la deja escrita el controlador antes de la Task 1, sin aplicarla, para que la prueba de contrato siga verde. Su contenido:

```sql
-- ============================================
-- PRÓRROGAS — Caja (puntos 22 a 26). Idempotente.
-- Va al final de _DML_FILES: 06 le vuelve a dar a secretaria los permisos de cobro en cada corrida.
-- admin no recibe nada: 08 le deja solo sus seis códigos.
-- ============================================
DO $$
DECLARE
    v_app_id          INTEGER;
    v_role_caja       INTEGER;
    v_role_secretaria INTEGER;
BEGIN
    SELECT id INTO v_app_id FROM core_apps WHERE key = 'prorrogas_tec';
    SELECT id INTO v_role_secretaria FROM core_roles WHERE name = 'secretaria';
    IF v_app_id IS NULL OR v_role_secretaria IS NULL THEN
        RAISE EXCEPTION 'Faltan la app prorrogas_tec o el rol secretaria (00 y 04)';
    END IF;

    INSERT INTO core_roles (name) VALUES ('caja') ON CONFLICT (name) DO NOTHING;
    SELECT id INTO v_role_caja FROM core_roles WHERE name = 'caja';

    INSERT INTO core_permissions (app_id, code, name, description) VALUES
    (v_app_id, 'prorrogas_tec.secretaria.page.caja', 'Pestaña de Caja', 'Ver la pestaña de Caja para buscar alumnos y cobrar'),
    (v_app_id, 'prorrogas_tec.caja.api.read', 'Caja: lectura', 'Lista y detalle de Caja, referencia y recibo escaneado')
    ON CONFLICT (app_id, code) DO NOTHING;

    INSERT INTO core_role_permissions (role_id, perm_id)
    SELECT v_role_caja, p.id
    FROM core_permissions p
    WHERE p.app_id = v_app_id AND p.code IN (
        'prorrogas_tec.secretaria.page.caja',
        'prorrogas_tec.caja.api.read',
        'prorrogas_tec.payments.api.record',
        'prorrogas_tec.payments.api.void'
    )
    ON CONFLICT DO NOTHING;

    DELETE FROM core_role_permissions
    WHERE role_id = v_role_secretaria
      AND perm_id IN (
        SELECT id FROM core_permissions
        WHERE app_id = v_app_id AND code IN (
            'prorrogas_tec.payments.api.record',
            'prorrogas_tec.payments.api.void'
        )
    );
END $$;
```

- [ ] **Step 5: GATE (controlador). Aplícala** y confirma:

```bash
docker compose -f /home/deigol/repos/itcj/docker/compose/docker-compose.dev.yml exec backend python -m itcj2.cli.main prorrogas init-prorrogas
docker compose -f /home/deigol/repos/itcj/docker/compose/docker-compose.dev.yml exec backend python -c "from sqlalchemy import text; from itcj2.database import SessionLocal; d=SessionLocal(); print(d.execute(text(\"select r.name, count(*) from core_role_permissions rp join core_roles r on r.id=rp.role_id join core_permissions p on p.id=rp.perm_id join core_apps a on a.id=p.app_id where a.key='prorrogas_tec' and r.name in ('caja','admin') group by 1 order by 1\")).all(), d.execute(text(\"select count(*) from core_role_permissions rp join core_roles r on r.id=rp.role_id join core_permissions p on p.id=rp.perm_id where r.name='secretaria' and p.code in ('prorrogas_tec.payments.api.record','prorrogas_tec.payments.api.void')\")).scalar())"
```

  Esperado: `[('admin', 6), ('caja', 4)] 0`.
- [ ] **Step 6: Suite (controlador).** `PYT T/`. Esperado: todo pasa. `PYT tests/fastapi/core`. Si falla por algo ajeno a este plan, repórtalo sin arreglarlo.
- [ ] **Step 7: Revisión final en navegador (controlador),** con sus propios datos de prueba, en escritorio y a 390 px: Caja (Por cobrar, filtros, orden, paginación, búsqueda, no encontrado, sin plan, pendiente, vencido, saldar con errores, liquidar, anular, referencia), barra sin scroll horizontal a 1130 y 1020 px con las siete pestañas del admin global, Mi prórroga (subir y reemplazar) y el modal de la secretaria (ver recibo, avisar). Sin datos reales en capturas ni artefactos.
