# Prórrogas · Plan 4: Histórico del Excel y Estadísticas — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Las prórrogas de 2024 a Ene–Jun 2026 que hoy viven en `Prórrogas.xlsx` entran a la app y la secretaria ve la pestaña **Estadísticas**.
- El Excel se **limpia**: sale un archivo normalizado con lo dudoso marcado para revisar.
- Una persona revisa lo marcado.
- El archivo limpio se **importa** a la base.
- La pestaña Estadísticas muestra el histórico junto con lo que llegue por la app.

**Architecture:** Un paquete nuevo `importacion/` con piezas puras y probadas por separado:
- normalizadores de fechas, importes, banderas, números de control y carreras;
- lectores de cada formato de hoja;
- escritura y lectura del archivo limpio;
- el importador.

Dos comandos de CLI los unen. Las estadísticas se calculan en Python sobre el semestre elegido, con la cobertura FIFO del Plan 3, y se pintan con Chart.js.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · PostgreSQL · Alembic (a mano) · openpyxl (ya en el repo) · click (CLI del repo) · `Decimal` · Chart.js 4.4.0 desde jsdelivr (ya lo usan Mantenimiento y HelpDesk) · Jinja2 + JS sin framework · pytest contra Postgres real.

**Spec:** [`docs/superpowers/specs/2026-10-29-prorrogas-modulo1-design.md`](../specs/2026-10-29-prorrogas-modulo1-design.md). Este plan cubre:
- **§17 completo**, que manda sobre §11;
- §3: el permiso `stats.api.read`;
- §5: cumplimiento;
- §8.1: la pestaña **Estadísticas**;
- la fila "Plan 4" de §14.

Se construye sobre los Planes 1–3, ya commiteados en `feature/core-prorrogas`.

## Global Constraints

**Herencia**

- Valen las Global Constraints de los Planes 1–3:
  - `require_perms` y `require_page_app`;
  - errores `{"error", "message", …}` en la raíz, rutas en `def`;
  - `db_now()`, migraciones a mano, DML en `.gitignore`;
  - paleta y tipografía del §8.1, textos en español;
  - XSS: todo texto de la API va al DOM por `textContent` o `createElement`;
  - dinero en `Decimal`: `parse_monto` y `money` (Plan 3).
- Ejecución en este equipo:
  - Un comando de Docker lleva `docker` como **primera palabra**: sin `cd … &&`, `VAR=`, `|`, `2>&1` ni redirecciones.
  - `PYTEST` = `docker compose -f docker/compose/docker-compose.dev.yml exec backend pytest <ruta> -q --tb=short -p no:cacheprovider -o addopts=`.
  - Alembic con `-c migrations/alembic.ini`, **antes** de la corrida en verde de Task 1.
  - Commits con la identidad `Deig0l` / `deigolsalazar@gmail.com` y la línea `Co-Authored-By`. Nunca `git add -A`.
  - CRLF en `itcj2/cli/prorrogas.py`, `docs/README.md` y `docs/PENDIENTES.md`.

**Datos reales**

- El Excel real (`instance/tmp/excel/prorrogas.xlsx`, en `.gitignore`) tiene nombres y números de control de estudiantes reales:
  - **Nunca** se copia a `tests/`, **nunca** se commitea y **nunca** se imprimen nombres en reportes ni en la terminal.
  - Las pruebas usan libros **sintéticos** armados con openpyxl.
- Ningún paso de este plan **escribe** el histórico real en la base. El `--dry-run` sí se corre. La importación real es un paso humano (H12) después de revisar.

**Valores del spec (§17)**

- **Hojas conocidas.** Cada nombre exacto tiene una etiqueta de semestre, que se escribe con `semestre_label` (`enero – junio 2026`), y un formato:

  | Hoja | Semestre | Formato |
  |---|---|---|
  | `Inscripción Enero - Junio 2026` | `enero – junio 2026` | `mensual` |
  | `Inscripción Agosto-Diciembre 25` | `agosto – diciembre 2025` | `mensual` |
  | `Inscripción Enero-Junio 2025` | `enero – junio 2025` | `mensual` |
  | `Prórrogas agosto-dic 2024` | `agosto – diciembre 2024` | `mensual` |
  | `Inscripción Agosto-Dic 2024` | `agosto – diciembre 2024` | `importe_unico` |
  | `Enero Junio 2024` | `enero – junio 2024` | `celda` |

  Una hoja que no está en la tabla va completa a Revisar (motivo `hoja desconocida`).
- **Formato `mensual`.** En la fila 1 vienen `FECHA`, `No. De Control`, `NOMBRE`, `CARRERA`. Por cada mes viene la terna `MES` · `IMPORTE` · (encabezado vacío = bandera). Las columnas se ubican **por encabezado**, nunca por posición.
- **Formato `celda`.** Encabezados `No. De Control`, `NOMBRE`, `CARRERA` y los meses. Cada celda de mes trae `DD de mes $X`, sin año: el año sale del semestre.
- **Formato `importe_unico`.** Encabezados `FECHA`, `No. De Control`, `NOMBRE`, `CARRERA`, `IMPORTE`. Es una prórroga de 1 pago, con vencimiento = `FECHA`.
- **Bandera de pagado:**
  - `1` o vacía → pagado;
  - `0` → no pagado;
  - cualquier otro valor → problema `bandera ilegible`.
- **Importes.** Se quitan `$` y espacios. Un separador seguido de **exactamente 2 dígitos al final** es el decimal; cualquier otro separador es de miles:
  - `$1,550,00` → 1550.00
  - `$3,.000.00` → 3000.00
  - `$1,500` → 1500.00
  - `$9,461.00` → 9461.00

  El resultado pasa por `parse_monto`. Lo que no cumple → problema `importe ilegible`.
- **Fechas.** Se aceptan:
  - `datetime` o `date`;
  - serial de Excel (número entre 20000 y 80000);
  - `12 de enero de 2026`, `12 de enero 2026` o `12 de enero`, más el año del semestre;
  - `14/01/2025` o `14/01/25`.

  Varias fechas en una celda se separan. Lo que no cumple → problema `fecha ilegible`.
- **Varios pagos en una celda.** Si el número de fechas es igual al de importes, se separan en parcialidades. Si no → problema `fechas e importes no cuadran`.
- **Número de control:**
  - un número se pasa a texto;
  - después de `strip().upper()` debe cumplir `^[A-Z]?\d{8}$`; si no → problema `número de control inválido`;
  - repetido en la misma hoja → problema `número de control repetido en la hoja`, en ambas.
- **Carreras.** Se normaliza el texto: minúsculas, sin acentos, `´` y `'` iguales, espacios colapsados. Luego se busca en la tabla de Task 2. Sin equivalencia → problema `carrera sin equivalencia`.
- **Archivo limpio**, hoja `Parcialidades`. Encabezados exactos, en este orden: `ref`, `semestre`, `fecha_solicitud`, `no_control`, `nombre`, `carrera`, `carrera_original`, `numero`, `vencimiento`, `monto`, `pagado`, `problema`, `valor_original`, `origen`.
  - Si algún dato de una solicitud tiene problema, **todas** sus filas salen igual, pero la fila del dato malo lleva `problema` y `valor_original`.
  - El importador **rechaza toda solicitud (`ref`) con algún `problema` no vacío**. Así nunca se importa una solicitud a medias.
  - La hoja `Revisar` es un resumen: `hoja`, `renglon`, `columna`, `valor`, `motivo`.
- **Importación:**
  - Todo entra con `origin='excel'`, `status='aceptada'`, `requested_terms=None`, `reason=None`, `email=None`.
  - `total_amount` = suma; `created_at` = `updated_at` = `fecha_solicitud` a las 00:00; `import_ref` = `ref`.
  - `period_id` es el semestre de core cuyo `period_label(p)` sea igual a `semestre`, o `None`.
  - `student_id` es el `User` con ese `control_number`, o `None`.
  - `program_name` y `program_level` salen de `core_programs` por nombre exacto; si la carrera no existe → error de esa solicitud.
  - Las parcialidades van de 1 a ≤ 6.
  - Cada parcialidad pagada genera un `ProrrogaPayment(origin='excel', folio=None, paid_on=vencimiento, amount=monto)`.
  - Es idempotente por `import_ref`. `--dry-run` valida y cuenta sin escribir.
- **Estadísticas (§17.4):**
  - El alcance es un semestre (por `period_label`) o todos. Se excluyen las `cancelada`.
  - **Cobertura FIFO** con fechas: los recibos vigentes, ordenados por (`paid_on`, `id`), se van sumando. Una parcialidad vigente queda cubierta en el `paid_on` del recibo con el que la suma alcanza su monto acumulado.
  - Las parcialidades con vencimiento < hoy se clasifican así:
    - cubierta el día del vencimiento o antes → `a_tiempo`;
    - cubierta después → `tarde`;
    - no cubierta → `sin_pago`.
- **Permiso nuevo** (`database/DML/prorrogas_tec/07_insert_plan4.sql`): `prorrogas_tec.stats.api.read` para secretaria y admin.

## Decisiones de este plan

1. **Un solo archivo limpio con la columna `problema`.** No van las filas buenas en una hoja y las malas en otra: así es imposible importar una solicitud con parcialidades de menos. La hoja `Revisar` es solo el resumen para la persona.
2. **La limpieza no toca la base.** Es pura y se prueba sin Postgres. Que la carrera exista en core y el semestre se resuelven al importar.
3. **La tabla de carreras es un dato** (`importacion/carreras.py`). Se arma con las variantes vistas en el Excel real. Si aparece una nueva, se agrega ahí.
4. **Se quita "próximamente".** Con Estadísticas ya no queda ninguna pestaña pendiente: se borran `_PENDIENTES`, la ruta `/{tab}` y `proximamente.html`.
5. **Las solicitudes de Excel sin semestre de core son de solo lectura.** El expediente las muestra sin plan editable, y `PlanService.confirm` responde 409 `sin_semestre`.

## Review Focus

1. **Volver a importar el mismo archivo no duplica nada.** La segunda corrida reporta todo como "ya existía".
   - Prueba: `test_importar_dos_veces_no_duplica` (Task 5).
2. **Un dato malo nunca deja una solicitud a medias.** Si una de tres parcialidades trae `Prórroga cancelada`, la solicitud entera queda fuera, con motivo, y las otras solicitudes sí entran.
   - Pruebas: `test_problema_en_una_parcialidad_marca_toda_la_solicitud` (Task 4) y `test_ref_con_problema_no_se_importa_y_dry_run_no_escribe` (Task 5).
3. **Una carrera desconocida no entra como texto suelto:** va a Revisar.
   - Prueba: `test_carrera_sin_equivalencia_es_problema` (Task 2).
4. **Una solicitud de Excel sin semestre de core** abierta por URL en el expediente o al confirmar plan no da 500.
   - Prueba: `test_historica_sin_semestre_es_de_solo_lectura` (Task 1).
5. **Cumplimiento con un recibo que cubre dos parcialidades, recibos anulados y pagos de Excel en la fecha** da `a_tiempo` y `tarde` correctos.
   - Prueba: `test_cobertura_fifo_con_fechas` (Task 6).

---

### Task 1: Esquema, permiso y solicitudes históricas seguras

**Files:**
- Create:
  - `migrations/versions/pr20261101a_prorrogas_historico.py` (`revision = "pr20261101a"`, `down_revision = "pr20261031a"`)
  - `database/DML/prorrogas_tec/07_insert_plan4.sql` (no se commitea)
- Modify:
  - `itcj2/apps/prorrogas_tec/models/plan.py`: el CHECK `ck_prorrogas_installments_number` pasa a `number BETWEEN 1 AND 6`
  - `itcj2/cli/prorrogas.py` (CRLF): `_DML_FILES` += `"07_insert_plan4.sql"` y una línea en el docstring
  - `services/students_service.py`: `expediente` con `period_id=None`
  - `services/plan_service.py`: `confirm` con `period_id=None`
  - `tests/fastapi/prorrogas_tec/conftest.py`: `SECRETARIA_PERMS` += `"prorrogas_tec.stats.api.read"`, fixture `make_historica`
- Test: `tests/fastapi/prorrogas_tec/test_historico_seguro.py`

**Interfaces:**
- Produces:
  - **Fixture `make_historica(periodo=None, control_number=None, parcialidades=(("1000.00", date(2025, 2, 1)),), pagadas=())`.** Crea una `ProrrogaRequest(origin="excel", status="aceptada", import_ref=f"T#{n}", requested_terms=None, period_id=periodo.id if periodo else None, period_label=period_label(periodo) if periodo else "enero – junio 2089", student_id=None, …)`. La etiqueta `enero – junio 2089` es sintética para que nunca se mezcle con el histórico real. Sus parcialidades vigentes llevan `total_amount` = suma. Cada índice de `pagadas` genera un `ProrrogaPayment(origin="excel", folio=None, paid_on=vencimiento)`. Hace flush y refresh y devuelve la solicitud.
  - **`StudentsService.expediente`.** Con `period_id is None`, `plan.puede_replantear` es `False` y `plan.fecha_limite` es `None`.
  - **`PlanService.confirm`.** Con `period_id is None` lanza `ServiceError("sin_semestre", "Esta prórroga histórica no tiene semestre en el sistema.", status=409)`, después del candado y antes de cualquier cambio.

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy.exc import IntegrityError

from itcj2.apps.prorrogas_tec.models.plan import ProrrogaInstallment
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.plan_service import PlanService
from itcj2.apps.prorrogas_tec.services.students_service import StudentsService


def test_excel_permite_hasta_seis_parcialidades(db_session, make_historica):
    req = make_historica(parcialidades=[("100.00", date(2025, 1, i + 1)) for i in range(6)])
    assert db_session.query(ProrrogaInstallment).filter_by(request_id=req.id).count() == 6
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(ProrrogaInstallment(request_id=req.id, number=7, amount=D("1"), due_date=date(2025, 7, 1)))
            db_session.flush()


def test_historica_sin_semestre_es_de_solo_lectura(db_session, make_historica, secretaria):  # Review Focus 4
    req = make_historica(pagadas=(0,))
    e = StudentsService.expediente(db_session, req.id, date(2026, 11, 1))
    assert e["plan"]["puede_replantear"] is False and e["plan"]["fecha_limite"] is None
    assert e["cuenta"]["situacion"] == "liquidada"
    with pytest.raises(ServiceError) as err:
        PlanService.confirm(db_session, req.id, secretaria.id, total=D("1000"),
                            parcialidades=[(D("1000"), date(2026, 12, 1))], now=date(2026, 11, 1))
    assert err.value.code == "sin_semestre" and err.value.status == 409


def test_api_expediente_historica_no_da_500(client_as, secretaria, make_historica):
    req = make_historica()
    assert client_as(secretaria).get(f"/api/prorrogas/v2/estudiantes/{req.id}").status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_historico_seguro.py`
Expected: FAIL. Falta la fixture `make_historica`; con ella, el CHECK rechaza 4..6 y `expediente` truena con `period_id=None`.

- [ ] **Step 3: Implement the migration, the CHECK, the guards, DML 07, the CLI line and the fixtures**

La migración hace drop y create de `ck_prorrogas_installments_number` con `BETWEEN 1 AND 6`. El `downgrade` lo regresa a `1 AND 3`. Después corre:

- `alembic -c migrations/alembic.ini upgrade head`
- `init-prorrogas` → 8/8

- [ ] **Step 4: Run the tests**

Run: `PYTEST tests/fastapi/prorrogas_tec`
Expected: PASS. Incluye `test_permissions_contract.py`.

- [ ] **Step 5: Commit**

```bash
git add migrations/versions/pr20261101a_prorrogas_historico.py itcj2/apps/prorrogas_tec/models/plan.py itcj2/cli/prorrogas.py itcj2/apps/prorrogas_tec/services/students_service.py itcj2/apps/prorrogas_tec/services/plan_service.py tests/fastapi/prorrogas_tec/conftest.py tests/fastapi/prorrogas_tec/test_historico_seguro.py
git commit -m "feat(prorrogas): parcialidades historicas hasta 6, permiso de estadisticas y solicitudes sin semestre de solo lectura"
```

---

### Task 2: Normalizadores y tabla de carreras (puros)

**Files:**
- Create:
  - `itcj2/apps/prorrogas_tec/importacion/__init__.py`
  - `importacion/normaliza.py`
  - `importacion/carreras.py`
- Test: `tests/fastapi/prorrogas_tec/test_importacion_normaliza.py`

**Interfaces:**
- Consumes: `parse_monto` (`services/formatting.py`) y `ServiceError`.
- Produces:
  - `class NoInterpretable(ValueError)`, con atributo `motivo: str`: el texto del problema de las Global Constraints.
  - `parse_fechas(raw, *, anio: int) -> list[date]`: devuelve una lista, a veces de varias fechas. `None` o vacío → `[]`. Si no entiende → `NoInterpretable("fecha ilegible")`.
  - `parse_importes(raw) -> list[Decimal]`: igual que la anterior; vacío → `[]`. Si no entiende → `NoInterpretable("importe ilegible")`.
  - `parse_bandera(raw) -> bool`.
  - `parse_control(raw) -> str`.
  - `mapear_carrera(texto: str) -> str`, que usa `carreras.EQUIVALENCIAS: dict[str, str]`. La clave es el texto normalizado y el valor, el nombre oficial de `core_programs`.
  - `normalizar(texto) -> str`: minúsculas, sin acentos, `´` y `'` iguales, espacios colapsados.
  - `MESES: dict[str, int]`, en español y en minúsculas.

`EQUIVALENCIAS` lleva **exactamente estas** variantes: son las vistas en el Excel real. El nombre oficial va a la derecha y la clave se guarda normalizada.

| Variantes | Nombre oficial |
|---|---|
| `Contador Público` | `Contador publico` |
| `Doctorado en Ciencias de la Ingeniería` | `Doctorado en Ciencias de la Ingeniería` |
| `Ingeniería Electromecánica` | `Electromecánica` |
| `Ingeniería Electrónica`, `Ingeniería en Electrónica` | `Electrónica` |
| `Ingeniería Eléctrica` | `Eléctrica` |
| `Ingeniería Industrial`, `Ingeniería Industrial (Curso de verano)` | `Ing. Industrial` |
| `Ingeniería Industrial EAD` | `Ing. Industrial EAD` |
| `Ingeniería Mecánica` | `Mecánica` |
| `Ingeniería en Ciberseguridad` | `Ciberseguridad` |
| `Ingeniería en Gestión Empresarial` | `Ing. Gestión Empresarial` |
| `Ingeniería en Gestión Empresarial EAD`, `Ingeniería en Gestión Empresaria EAD`, `Ingeniería en Gestíon Empresarial EAD` | `Ing. Gestión Empresarial EAD` |
| `Ingeniería en Logística` | `Ing. Logistica` |
| `Ingeniería en Mecatrónica` | `Mecatrónica` |
| `Ingeniería en Semiconductores` | `Semiconductores` |
| `Ingeniería en Sistemas Computacionales`, `Ingenierpia en Sistemas Computacionales` | `Ing. Sistemas computacionales` |
| `Ingeniería en Sistemas Computacionales EAD` | `Ing. Sistemas computacionales EAD` |
| `TIC'S`, `TIC´S`, `Ingeniería en TIC´S` | `Ing. Tics` |
| `Licenciatura en Administración`, `Licenciatura en Administración de Empresas` | `Lic. Administracion` |
| `Maestría en Ingeniería Administrativa` | `Maestría en Ingeniería Administrativa` |
| `Maestría en Ingeniería Industrial` | `Maestría en Ingeniería Industrial` |
| `Maestría en Negocios Internacionales` | `Maestría en Administración de Negocios Internacionales` |

La normalización ya cubre los dobles espacios, `Gestion` y `Gestíon`.

- [ ] **Step 1: Write the failing test**

```python
from datetime import date, datetime
from decimal import Decimal as D

import pytest

from itcj2.apps.prorrogas_tec.importacion.normaliza import (
    NoInterpretable, mapear_carrera, parse_bandera, parse_control, parse_fechas, parse_importes,
)


@pytest.mark.parametrize("raw, esperado", [
    (datetime(2026, 1, 23), [date(2026, 1, 23)]),
    ("12 de enero de 2026", [date(2026, 1, 12)]),
    ("13  de septiembre 2024", [date(2024, 9, 13)]),
    ("29 de febrero", [date(2024, 2, 29)]),
    ("14/01/2025, 20/01/25, 27/01/25", [date(2025, 1, 14), date(2025, 1, 20), date(2025, 1, 27)]),
    ("16 de agosto de 2024       30 de agosto de 2024", [date(2024, 8, 16), date(2024, 8, 30)]),
    (45679, [date(2025, 1, 22)]),
    (None, []),
])
def test_fechas(raw, esperado):
    assert parse_fechas(raw, anio=2024) == esperado


@pytest.mark.parametrize("raw, esperado", [
    (3150, [D("3150.00")]), ("$1,550,00", [D("1550.00")]), ("$3,.000.00", [D("3000.00")]),
    ("$1,500", [D("1500.00")]), ("$9,461.00", [D("9461.00")]),
    ("$1,100,00  $1,000,00   $1,000,00", [D("1100.00"), D("1000.00"), D("1000.00")]), (None, []),
])
def test_importes(raw, esperado):
    assert parse_importes(raw) == esperado


@pytest.mark.parametrize("raw, motivo", [("Prórroga cancelada", "importe ilegible"), ("ayer", "fecha ilegible")])
def test_no_interpretable(raw, motivo):
    with pytest.raises(NoInterpretable) as e:
        (parse_importes if motivo == "importe ilegible" else lambda r: parse_fechas(r, anio=2025))(raw)
    assert e.value.motivo == motivo


def test_bandera_y_control():
    assert parse_bandera(1) is True and parse_bandera(None) is True and parse_bandera("") is True
    assert parse_bandera(0) is False
    for malo in (-1, ".", " x"):
        with pytest.raises(NoInterpretable):
            parse_bandera(malo)
    assert parse_control(22111234) == "22111234" and parse_control(" d21111234 ") == "D21111234"
    with pytest.raises(NoInterpretable):
        parse_control(12345)


def test_carreras():
    assert mapear_carrera("Ingeniería  Industrial") == "Ing. Industrial"
    assert mapear_carrera("Ingeniería en Gestion Empresarial") == "Ing. Gestión Empresarial"
    assert mapear_carrera("TIC´S") == mapear_carrera("TIC'S") == "Ing. Tics"


def test_carrera_sin_equivalencia_es_problema():  # Review Focus 3
    with pytest.raises(NoInterpretable) as e:
        mapear_carrera("Ingeniería Espacial")
    assert e.value.motivo == "carrera sin equivalencia"
```

Una bandera `" "` (un espacio) cuenta como vacía y da pagado: `strip()` vacío = vacía. La de la prueba es `" x"`.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_importacion_normaliza.py`
Expected: FAIL con `ImportError`.

- [ ] **Step 3: Implement `normaliza.py` and `carreras.py`**

**Fechas.** Primero `datetime`/`date`. Luego el número: es serial si está entre 20000 y 80000, con base `date(1899, 12, 30)`. Luego, en el texto:
- busca todas las coincidencias de `(\d{1,2})\s+de\s+([a-záéíóú]+)(?:\s+(?:de\s+)?(\d{4}))?`;
- y las de `(\d{1,2})/(\d{1,2})/(\d{2,4})`, donde un año de 2 dígitos es 20xx.

Un texto no vacío sin ninguna coincidencia → `fecha ilegible`, por ejemplo `ayer`. Si quedan dígitos que ninguna de las dos reconoce → también `fecha ilegible`.

**Importes.** Tokens con `\$?\s*[\d.,]+`. Para cada token se aplica la regla del separador de las Global Constraints y luego `parse_monto(str)`. Si queda texto aparte de los tokens, `$` y espacios → `importe ilegible`. Un `ServiceError` de `parse_monto` también → `importe ilegible`.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_importacion_normaliza.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add itcj2/apps/prorrogas_tec/importacion tests/fastapi/prorrogas_tec/test_importacion_normaliza.py
git commit -m "feat(prorrogas): normalizadores de fechas, importes, banderas, controles y carreras del Excel"
```

---

### Task 3: Lectores de las hojas del Excel

**Files:**
- Create: `itcj2/apps/prorrogas_tec/importacion/hojas.py`
- Modify: `tests/fastapi/prorrogas_tec/conftest.py`: fixture `libro`
- Test: `tests/fastapi/prorrogas_tec/test_importacion_hojas.py`

**Interfaces:**
- Consumes: todo lo de Task 2.
- Produces:
  - **`@dataclass Parcialidad`**, con estos campos:
    - `vencimiento: date | None`
    - `monto: Decimal | None`
    - `pagado: bool | None`
    - `problema: str = ""`
    - `valor_original: str = ""`
    - `origen: str` (`"{hoja}!{celda}"`, p. ej. `Enero 2026!F3`)
  - **`@dataclass Solicitud`**, con estos campos:
    - `ref: str` (`"{hoja}#{renglón}"`)
    - `hoja`, `semestre: str`
    - `fecha_solicitud: date | None`
    - `no_control: str`, `nombre: str`
    - `carrera: str`, `carrera_original: str`
    - `parcialidades: list[Parcialidad]`
    - `problema: str = ""`: un problema de la solicitud entera (control, carrera, fecha de solicitud, repetido)
    - `tiene_problema` → `bool(self.problema) or any(p.problema for p in self.parcialidades)`
  - **`HOJAS: dict[str, tuple[str, str]]`**: la tabla de las Global Constraints (nombre de hoja → (semestre, formato)).
  - **`leer_libro(path) -> list[Solicitud]`**:
    - Abre con `load_workbook(path, data_only=True)` y recorre las hojas.
    - Una hoja desconocida da una `Solicitud` con `ref=f"{hoja}#0"` y `problema="hoja desconocida"`.
    - Un renglón sin número de control pero con pagos es continuación de la solicitud anterior.
    - Un renglón vacío, o con solo `No.`, se ignora.
    - El año para las fechas sin año es el de la etiqueta del semestre.
  - **Fixture `libro(hojas: dict[str, list[list]]) -> Path`**: arma un `.xlsx` sintético en `tmp_path` con openpyxl. La primera lista es el encabezado.

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from decimal import Decimal as D

from itcj2.apps.prorrogas_tec.importacion.hojas import leer_libro

ENC_2026 = ["No.", "FECHA", "No. De Control", "NOMBRE", "CARRERA", "ENERO", "IMPORTE", "", "FEBRERO", "IMPORTE", ""]


def test_mensual_con_continuacion_y_banderas(libro):
    ruta = libro({"Inscripción Enero - Junio 2026": [
        ENC_2026,
        [None, "12 de enero de 2026", 99110001, "Alumna Uno", "Contador Público", "16 de enero de 2026", 1000, 1,
         "06 de febrero de 2026", 1000, 0],
        [None, None, None, None, None, "26 de enero de 2026", 500, None],
    ]})
    s, = leer_libro(ruta)
    assert s.ref == "Inscripción Enero - Junio 2026#2" and s.semestre == "enero – junio 2026"
    assert s.carrera == "Contador publico" and s.no_control == "99110001"
    assert [(p.vencimiento, p.monto, p.pagado) for p in s.parcialidades] == [
        (date(2026, 1, 16), D("1000.00"), True), (date(2026, 2, 6), D("1000.00"), False),
        (date(2026, 1, 26), D("500.00"), True)]
    assert not s.tiene_problema


def test_celda_2024_sin_anio(libro):
    ruta = libro({"Enero Junio 2024": [
        ["No. De Control", "NOMBRE", "CARRERA", "ENERO", "FEBRERO"],
        [99110002, "Alumno Dos", "Ingeniería Industrial", "30 de enero $2,900.00", "29 de febrero $600.00"],
    ]})
    s, = leer_libro(ruta)
    assert [(p.vencimiento, p.monto, p.pagado) for p in s.parcialidades] == [
        (date(2024, 1, 30), D("2900.00"), True), (date(2024, 2, 29), D("600.00"), True)]


def test_importe_unico(libro):
    ruta = libro({"Inscripción Agosto-Dic 2024": [
        ["FECHA", "No. De Control", "NOMBRE", "CARRERA", "IMPORTE"],
        [date(2024, 8, 12), 99110003, "Alumno Tres", "Ingeniería en Gestión Empresarial EAD", "$3,.000.00"],
    ]})
    s, = leer_libro(ruta)
    assert s.semestre == "agosto – diciembre 2024" and s.carrera == "Ing. Gestión Empresarial EAD"
    assert [(p.vencimiento, p.monto, p.pagado) for p in s.parcialidades] == [(date(2024, 8, 12), D("3000.00"), True)]


def test_celda_doble_se_separa_si_cuadra_y_si_no_es_problema(libro):
    enc = ["No.", "FECHA", "No. De Control", "NOMBRE", "CARRERA", "ENERO", "IMPORTE", ""]
    ruta = libro({"Inscripción Enero-Junio 2025": [
        enc,
        [1, "14 de enero de 2025", 99110004, "A", "Contador Público", "14/01/2025, 20/01/25", "$1,100,00  $1,000,00", 1],
        [2, "14 de enero de 2025", 99110005, "B", "Contador Público", "16 de enero de 2025  30 de enero de 2025", 750, 1],
    ]})
    a, b = leer_libro(ruta)
    assert [p.monto for p in a.parcialidades] == [D("1100.00"), D("1000.00")] and not a.tiene_problema
    assert b.tiene_problema and b.parcialidades[0].problema == "fechas e importes no cuadran"


def test_controles_invalidos_y_repetidos_y_hoja_desconocida(libro):
    ruta = libro({
        "Inscripción Enero - Junio 2026": [ENC_2026,
            [None, "12 de enero de 2026", 12345, "A", "Contador Público", "16 de enero de 2026", 1000, 1],
            [None, "12 de enero de 2026", 99110006, "B", "Contador Público", "16 de enero de 2026", 1000, 1],
            [None, "12 de enero de 2026", 99110006, "C", "Contador Público", "16 de enero de 2026", 1000, 1]],
        "Otra cosa": [["X"], [1]],
    })
    sols = leer_libro(ruta)
    assert [s.problema for s in sols] == ["número de control inválido", "número de control repetido en la hoja",
                                          "número de control repetido en la hoja", "hoja desconocida"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_importacion_hojas.py`
Expected: FAIL con `ImportError`.

- [ ] **Step 3: Implement `hojas.py` and the `libro` fixture**

Cada `NoInterpretable` de una celda se guarda en la `Parcialidad`: `problema` y `valor_original = str(valor)`; ninguna se pierde. Si una celda de importe trae varios montos o una de fecha trae varias fechas, se separan con la regla de "Varios pagos en una celda".

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_importacion_hojas.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add itcj2/apps/prorrogas_tec/importacion/hojas.py tests/fastapi/prorrogas_tec/conftest.py tests/fastapi/prorrogas_tec/test_importacion_hojas.py
git commit -m "feat(prorrogas): lectores de las tres formas de hoja del Excel historico"
```

---

### Task 4: Archivo limpio (escribir, leer y validar) y comando `excel-limpiar`

**Files:**
- Create: `itcj2/apps/prorrogas_tec/importacion/limpio.py`
- Modify: `itcj2/cli/prorrogas.py` (CRLF): comando `excel-limpiar`
- Test: `tests/fastapi/prorrogas_tec/test_importacion_limpio.py`

**Interfaces:**
- Consumes: `leer_libro` y `Solicitud` (Task 3), y `parse_monto`.
- Produces:
  - **`ENCABEZADOS`**: la tupla exacta de las Global Constraints.
  - **`escribir_limpio(solicitudes: list[Solicitud], path) -> dict`.** Escribe las hojas `Parcialidades` y `Revisar`. Devuelve `{"solicitudes", "parcialidades", "con_problema"}`. `numero` se asigna ordenando las parcialidades por `vencimiento`; en empate, por orden de aparición, y las de vencimiento vacío al final. Así la cobertura FIFO sigue las fechas. En `Parcialidades` va:
    - una fila por parcialidad;
    - una fila sin datos de pago por cada solicitud sin parcialidades o con problema propio, con `numero` vacío;
    - el `problema` de la solicitud en todas sus filas.
  - **`@dataclass SolicitudLimpia`**: `ref`, `semestre`, `fecha_solicitud: date`, `no_control`, `nombre`, `carrera`, `parcialidades: list[tuple[int, date, Decimal, bool]]`.
  - **`leer_limpio(path) -> tuple[list[SolicitudLimpia], list[tuple[str, str]]]`.** Devuelve las válidas y los errores `(ref, motivo)`. Valida:
    - encabezados exactos (si no, `ValueError` con el encabezado esperado);
    - por `ref`: `problema` vacío en todas sus filas; mismos `semestre`, `fecha_solicitud`, `no_control`, `nombre` y `carrera`;
    - `numero` = 1..n seguido, con n ≤ 6; `vencimiento` fecha; `monto` por `parse_monto`; `pagado` ∈ {0, 1}; `no_control` según la regla.
  - **CLI `prorrogas excel-limpiar ORIGEN --salida LIMPIO`.** Imprime solo los conteos (solicitudes, parcialidades, con problema) y la ruta. **No imprime nombres.**

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from decimal import Decimal as D

from openpyxl import load_workbook

from itcj2.apps.prorrogas_tec.importacion.hojas import leer_libro
from itcj2.apps.prorrogas_tec.importacion.limpio import ENCABEZADOS, escribir_limpio, leer_limpio

ENC = ["No.", "FECHA", "No. De Control", "NOMBRE", "CARRERA", "ENERO", "IMPORTE", "", "FEBRERO", "IMPORTE", "",
       "MARZO", "IMPORTE", ""]


def _origen(libro):
    return libro({"Inscripción Enero - Junio 2026": [ENC,
        [None, "12 de enero de 2026", 99120001, "Buena", "Contador Público", "16 de enero de 2026", 1000, 1,
         "06 de febrero de 2026", 1000, 0],
        [None, "12 de enero de 2026", 99120002, "Mala", "Contador Público", "16 de enero de 2026", 1000, 1,
         "06 de febrero de 2026", "Prórroga cancelada", 1, "06 de marzo de 2026", 1000, 1]]})


def test_ida_y_vuelta(libro, tmp_path):
    salida = tmp_path / "limpio.xlsx"
    res = escribir_limpio(leer_libro(_origen(libro)), salida)
    assert res == {"solicitudes": 2, "parcialidades": 5, "con_problema": 1}
    wb = load_workbook(salida)
    assert [c.value for c in wb["Parcialidades"][1]] == list(ENCABEZADOS) and wb["Revisar"].max_row == 2
    validas, errores = leer_limpio(salida)
    buena, = validas
    assert buena.no_control == "99120001" and buena.parcialidades == [
        (1, date(2026, 1, 16), D("1000.00"), True), (2, date(2026, 2, 6), D("1000.00"), False)]
    assert [r for r, _ in errores] == ["Inscripción Enero - Junio 2026#3"]


def test_problema_en_una_parcialidad_marca_toda_la_solicitud(libro, tmp_path):  # Review Focus 2
    salida = tmp_path / "limpio.xlsx"
    escribir_limpio(leer_libro(_origen(libro)), salida)
    filas = [r for r in load_workbook(salida)["Parcialidades"].iter_rows(min_row=2, values_only=True)
             if r[0].endswith("#3")]
    assert len(filas) == 3 and sum(1 for r in filas if r[ENCABEZADOS.index("problema")]) == 1
    _, errores = leer_limpio(salida)
    assert errores[0][1].startswith("tiene datos por revisar")


def test_encabezados_cambiados_se_rechazan(tmp_path):
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active; ws.title = "Parcialidades"; ws.append(["ref", "otra"]); wb.save(tmp_path / "x.xlsx")
    import pytest
    with pytest.raises(ValueError):
        leer_limpio(tmp_path / "x.xlsx")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_importacion_limpio.py`
Expected: FAIL con `ImportError`.

- [ ] **Step 3: Implement `limpio.py` and the CLI command**

- Las fechas se escriben como fechas de Excel con `number_format = "DD/MM/YYYY"`.
- `monto` va como número con `'"$"#,##0.00'`.
- La primera fila queda congelada y con filtro.
- `Revisar` lleva una fila por cada problema.
- `leer_limpio` usa como motivo `"tiene datos por revisar: {problema}"` cuando hay problema.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_importacion_limpio.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add itcj2/apps/prorrogas_tec/importacion/limpio.py itcj2/cli/prorrogas.py tests/fastapi/prorrogas_tec/test_importacion_limpio.py
git commit -m "feat(prorrogas): archivo limpio con columna de problema y comando excel-limpiar"
```

---

### Task 5: Importador y comando `import-excel`

**Files:**
- Create: `itcj2/apps/prorrogas_tec/importacion/importador.py`
- Modify: `itcj2/cli/prorrogas.py` (CRLF): comando `import-excel`
- Test: `tests/fastapi/prorrogas_tec/test_importador.py`

**Interfaces:**
- Consumes:
  - `leer_limpio` y `SolicitudLimpia` (Task 4);
  - `period_label` (`services/periods.py`);
  - `User`, `Program` y `AcademicPeriod`;
  - los modelos de los Planes 2 y 3.
- Produces:
  - **`importar(db, solicitudes: list[SolicitudLimpia], *, dry_run: bool) -> dict`**, que devuelve `{"creadas", "ya_existian", "con_error": [(ref, motivo)], "sin_semestre_core", "sin_cuenta"}`. Errores por solicitud:
    - `carrera no existe en core`;
    - más de 6 parcialidades.

    Con `dry_run`: hace todo, luego `db.rollback()`, y devuelve los mismos conteos.
  - **CLI `prorrogas import-excel LIMPIO [--dry-run]`**:
    - Imprime los errores de `leer_limpio` y del importador por `ref` y motivo. **Sin nombres.**
    - Al final imprime los conteos.
    - Sin `--dry-run`, hace commit una vez al final.

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from decimal import Decimal as D

from itcj2.apps.prorrogas_tec.importacion.importador import importar
from itcj2.apps.prorrogas_tec.importacion.limpio import SolicitudLimpia
from itcj2.apps.prorrogas_tec.models.plan import ProrrogaInstallment, ProrrogaPayment
from itcj2.apps.prorrogas_tec.models.request import ProrrogaRequest


def _sol(ref="H#2", control="99130001", carrera="Contador publico", semestre="enero – junio 2025"):
    return SolicitudLimpia(ref=ref, semestre=semestre, fecha_solicitud=date(2025, 1, 13), no_control=control,
                           nombre="Alumna Histórica", carrera=carrera,
                           parcialidades=[(1, date(2025, 2, 1), D("1000.00"), True), (2, date(2025, 3, 1), D("550.00"), False)])


def test_importa_con_recibos_solo_de_lo_pagado(db_session, make_program):
    make_program("Contador publico", "licenciatura")
    res = importar(db_session, [_sol()], dry_run=False)
    assert res["creadas"] == 1 and res["sin_semestre_core"] == 1 and res["sin_cuenta"] == 1
    req = db_session.query(ProrrogaRequest).filter_by(import_ref="H#2").one()
    assert (req.origin, req.status, req.total_amount, req.period_id, req.requested_terms) == \
        ("excel", "aceptada", D("1550.00"), None, None)
    assert req.created_at.date() == date(2025, 1, 13) and req.program_level == "licenciatura"
    assert db_session.query(ProrrogaInstallment).filter_by(request_id=req.id).count() == 2
    pagos = db_session.query(ProrrogaPayment).filter_by(request_id=req.id).all()
    assert [(p.origin, p.folio, p.paid_on, p.amount) for p in pagos] == [("excel", None, date(2025, 2, 1), D("1000.00"))]


def test_importar_dos_veces_no_duplica(db_session, make_program):  # Review Focus 1
    make_program("Contador publico", "licenciatura")
    importar(db_session, [_sol()], dry_run=False)
    res = importar(db_session, [_sol()], dry_run=False)
    assert res["creadas"] == 0 and res["ya_existian"] == 1
    assert db_session.query(ProrrogaRequest).filter_by(import_ref="H#2").count() == 1


def test_liga_semestre_y_cuenta(db_session, make_program, make_user, periodo):
    from itcj2.apps.prorrogas_tec.services.periods import period_label
    make_program("Contador publico", "licenciatura")
    u = make_user(control_number="99130002")
    importar(db_session, [_sol(ref="H#3", control="99130002", semestre=period_label(periodo))], dry_run=False)
    req = db_session.query(ProrrogaRequest).filter_by(import_ref="H#3").one()
    assert req.period_id == periodo.id and req.student_id == u.id


def test_ref_con_problema_no_se_importa_y_dry_run_no_escribe(db_session, make_program):  # Review Focus 2
    make_program("Contador publico", "licenciatura")
    res = importar(db_session, [_sol(ref="H#4", carrera="Carrera Fantasma"), _sol(ref="H#5")], dry_run=True)
    assert res["creadas"] == 1 and res["con_error"] == [("H#4", "carrera no existe en core")]
    assert db_session.query(ProrrogaRequest).filter(ProrrogaRequest.import_ref.in_(["H#4", "H#5"])).count() == 0
```

`importar` hace `db.commit()` al final cuando no es `dry_run`. En la prueba, eso libera el savepoint (ver env-notes); es lo esperado.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_importador.py`
Expected: FAIL con `ImportError`.

- [ ] **Step 3: Implement `importador.py` and the CLI command**

- Los semestres de core se resuelven con un dict `{period_label(p): p.id}`.
- Los programas se buscan por `name` exacto.
- Las cuentas se buscan con una sola consulta `User.control_number.in_(...)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_importador.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add itcj2/apps/prorrogas_tec/importacion/importador.py itcj2/cli/prorrogas.py tests/fastapi/prorrogas_tec/test_importador.py
git commit -m "feat(prorrogas): importador idempotente del archivo limpio y comando import-excel"
```

---

### Task 6: Estadísticas (cobertura FIFO, servicio y API)

**Files:**
- Modify: `itcj2/apps/prorrogas_tec/services/account.py`: `cobertura`
- Create:
  - `services/stats_service.py`
  - `api/stats.py`
- Modify: `router.py` (`include_router(stats, prefix="/estadisticas")`)
- Test: `tests/fastapi/prorrogas_tec/test_stats.py`

**Interfaces:**
- Consumes: `account`, los modelos y `make_historica` (Task 1).
- Produces:
  - **`account.cobertura(installments: Sequence[tuple[int, Decimal, date]], recibos: Sequence[tuple[date, Decimal]]) -> list[date | None]`.** Es pura: devuelve, por cada parcialidad en orden de `number`, la fecha en que quedó cubierta, o `None`.
  - **`StatsService.semestres(db) -> dict`**: `{"items": [{"label", "period_id"}], "actual": label | None}`. Toma los `period_label` distintos de las solicitudes no canceladas, ordenados del más nuevo al más viejo con el `period_id` si existe. `actual` es la etiqueta de `period_for(hoy)` si está en `items`; si no, la primera.
  - **`StatsService.resumen(db, semestre: str | None, today: date) -> dict`**, con estas claves:
    - `"semestre"`, `"total"`;
    - `"por_carrera"`: una lista de `{"carrera", "solicitudes", "aceptadas", "rechazadas", "monto", "vencidas", "a_tiempo", "tarde", "sin_pago"}`;
    - `"aceptacion"`: `{"aceptadas", "rechazadas", "pct_aceptadas"}`;
    - `"linea"`: `{"semanal": [{"inicio", "aceptadas", "rechazadas"}], "mensual": [{"mes": "YYYY-MM", "aceptadas", "rechazadas"}]}`;
    - `"kpis"`: `{"pendientes", "pendiente_mas_vieja_dias", "respuesta_promedio_dias", "monto_total", "plazos_promedio", "replanteadas"}`;
    - `"cumplimiento"`: `{"vencidas", "a_tiempo", "tarde", "sin_pago", "estudiantes_sin_pago", "period_id"}`.

    Detalles:
    - El dinero va como cadena con `money()`.
    - La semana empieza en lunes.
    - `replanteadas` cuenta las solicitudes con alguna parcialidad sustituida.
    - `semestre=None` = todos.
  - **`StatsService.csv(db, semestre, today) -> str`**: CSV con BOM. Columnas `Carrera,Solicitudes,Aceptación (%),Monto prorrogado,Vencidas,Pagó a tiempo,Pagó tarde,Sin pago`.
  - **API** bajo `/api/prorrogas/v2/estadisticas`, todas con `prorrogas_tec.stats.api.read`:
    - `GET /semestres`
    - `GET ""` con `?semestre=`
    - `GET /detalle.csv` con `?semestre=`. Responde `text/csv; charset=utf-8` como adjunto `estadisticas-prorrogas.csv`.

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from decimal import Decimal as D

from itcj2.apps.prorrogas_tec.services.account import cobertura
from itcj2.apps.prorrogas_tec.services.stats_service import StatsService

PLAN = [(1, D("1000"), date(2025, 2, 1)), (2, D("1000"), date(2025, 3, 1)), (3, D("500"), date(2025, 4, 1))]


def test_cobertura_fifo_con_fechas():  # Review Focus 5
    recibos = [(date(2025, 1, 30), D("1500")), (date(2025, 3, 10), D("500"))]
    assert cobertura(PLAN, recibos) == [date(2025, 1, 30), date(2025, 3, 10), None]
    assert cobertura(PLAN, [(date(2025, 2, 1), D("2500"))]) == [date(2025, 2, 1)] * 3


def test_resumen_del_semestre(db_session, make_historica):
    a = make_historica(parcialidades=[("1000.00", date(2025, 2, 1)), ("1000.00", date(2025, 3, 1))], pagadas=(0,))
    make_historica(parcialidades=[("500.00", date(2025, 2, 15))], pagadas=(0,))
    r = StatsService.resumen(db_session, "enero – junio 2089", date(2096, 11, 1))
    c = r["cumplimiento"]
    assert (c["vencidas"], c["a_tiempo"], c["tarde"], c["sin_pago"], c["estudiantes_sin_pago"]) == (3, 2, 0, 1, 1)
    assert r["kpis"]["monto_total"] == "2500.00" and r["aceptacion"]["pct_aceptadas"] == 100
    assert r["total"] == 2 and a.period_label == "enero – junio 2089"


def test_api_permiso_y_csv(client_as, secretaria, estudiante, make_historica):
    make_historica()
    c = client_as(secretaria)
    assert c.get("/api/prorrogas/v2/estadisticas/semestres").status_code == 200
    csv = c.get("/api/prorrogas/v2/estadisticas/detalle.csv", params={"semestre": "enero – junio 2089"})
    assert csv.status_code == 200 and csv.content.startswith(b"\xef\xbb\xbfCarrera,")
    assert client_as(estudiante).get("/api/prorrogas/v2/estadisticas").status_code == 403
```

`make_historica` usa la etiqueta sintética `enero – junio 2089`: el semestre de la prueba solo tiene las solicitudes de la prueba, aunque ya se haya importado el histórico real.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_stats.py`
Expected: FAIL con `ImportError`.

- [ ] **Step 3: Implement `cobertura`, `stats_service.py`, `api/stats.py` and the mount**

`resumen` carga, en tres consultas:
1. las solicitudes del alcance (no canceladas);
2. sus parcialidades vigentes;
3. sus recibos no anulados con `paid_on`.

Calcula todo en Python con el comentario `# shortcut: cálculo en Python por semestre; pasar a SQL si un semestre supera ~2000 solicitudes`.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_stats.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add itcj2/apps/prorrogas_tec/services/account.py itcj2/apps/prorrogas_tec/services/stats_service.py itcj2/apps/prorrogas_tec/api/stats.py itcj2/apps/prorrogas_tec/router.py tests/fastapi/prorrogas_tec/test_stats.py
git commit -m "feat(prorrogas): estadisticas por semestre con cumplimiento FIFO y exportacion CSV"
```

---

### Task 7: Pestaña "Estadísticas"

**Files:**
- Modify:
  - `itcj2/apps/prorrogas_tec/pages/secretaria.py`: ruta `/estadisticas`; se quitan `_PENDIENTES`, la ruta `/{tab}` y su import de `HTTPException` si queda sin uso
  - `static/css/secretaria/base.css`
  - `tests/fastapi/prorrogas_tec/test_secretaria_pages.py`: se borra `test_pestanas_pendientes_muestran_proximamente` y se agrega la prueba nueva
- Create:
  - `templates/prorrogas_tec/secretaria/estadisticas.html`
  - `static/js/secretaria/estadisticas.js`
- Delete: `templates/prorrogas_tec/secretaria/proximamente.html` (`git rm`)
- Test: `tests/fastapi/prorrogas_tec/test_secretaria_pages.py`

**Interfaces:**
- Consumes: la API de Task 6 y la ruta `/prorrogas/secretaria/estudiantes` (Plan 3).
- Produces: la vista del diseño ("01 Estadísticas", `docs/design/prorrogas/secretaria-final.dc.html` líneas 14–150), adaptada:
  - **Encabezado:** selector de semestre, con "Todos" y los de `/semestres`; "{total} solicitudes"; botón **Exportar**, que descarga el CSV con un `Blob`.
  - **Tarjetas:**
    - **Solicitudes por carrera**: dona de Chart.js.
    - **Aceptadas / Rechazadas**: porcentaje y conteo.
    - **Línea de tiempo**: barras apiladas aceptadas/rechazadas, con un interruptor **Semanal | Mensual**.
    - **KPIs**: los seis de §17.4 con su texto.
    - **Cumplimiento de pago**: a tiempo, tarde y sin pago, en % y conteo. "Ver en Estudiantes" va a `/prorrogas/secretaria/estudiantes` cuando hay `period_id`.
    - **Detalle por carrera**: una tabla.
  - Chart.js 4.4.0 se carga desde `https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js` con `integrity="sha384-…"` (calculado del archivo exacto, como el QR del Plan 2) y `crossorigin="anonymous"`.
    - Si `Chart` no está definido, cada gráfica muestra sus números en texto.
    - Al cambiar de semestre, cada gráfica se destruye antes de crearla de nuevo.
  - Colores de la paleta §8.1. Ningún texto de la API entra por `innerHTML`.

- [ ] **Step 1: Update the page tests (failing)**

```python
def test_pestana_estadisticas(client_as, secretaria):
    page = client_as(secretaria).get(f"{BASE}/estadisticas").text
    for texto in ("Estadísticas de prórrogas", "Solicitudes por carrera", "Cumplimiento de pago",
                  "Detalle por carrera", "chart.js@4.4.0", "estadisticas.js"):
        assert texto in page


def test_ruta_desconocida_da_404(client_as, secretaria):
    assert client_as(secretaria).get(f"{BASE}/nada").status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_secretaria_pages.py`
Expected: FAIL.

- [ ] **Step 3: Implement the route, the template, the JS and the CSS; remove "próximamente"**

- [ ] **Step 4: Run the tests**

Run: `PYTEST tests/fastapi/prorrogas_tec`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git rm itcj2/apps/prorrogas_tec/templates/prorrogas_tec/secretaria/proximamente.html
git add itcj2/apps/prorrogas_tec/pages/secretaria.py itcj2/apps/prorrogas_tec/templates/prorrogas_tec/secretaria/estadisticas.html itcj2/apps/prorrogas_tec/static/js/secretaria/estadisticas.js itcj2/apps/prorrogas_tec/static/css/secretaria/base.css tests/fastapi/prorrogas_tec/test_secretaria_pages.py
git commit -m "feat(prorrogas): pestana Estadisticas con graficas, cumplimiento y detalle por carrera"
```

---

### Task 8: Documentación, limpieza del Excel real y simulacro de importación

**Files:**
- Create:
  - `itcj2/apps/prorrogas_tec/docs/flows/historico_excel.md`
  - `docs/flows/secretaria_estadisticas.md`
- Modify:
  - `docs/README.md` (CRLF): el mapa y el árbol desde `git ls-files`
  - `docs/PENDIENTES.md` (CRLF): P11 hecho por Task 1; H12, para correr la importación real después de revisar

**Interfaces:**
- Consumes: todo lo anterior.
- Produces: los documentos y el reporte del Excel real, solo con conteos.

- [ ] **Step 1: Write the docs**

**`historico_excel.md`**
- Los dos comandos y el formato del archivo limpio.
- Cómo revisar: corregir la fila y vaciar `problema`.
- La tabla de carreras y cómo agregar una variante.
- Qué se importa y qué no (§17.3).
- Un ejemplo con datos ficticios.

**`secretaria_estadisticas.md`**
- Las rutas, el permiso y la definición de cada número (§17.4).
- La regla de cobertura FIFO.

- [ ] **Step 2: Run the wide suite**

Run: `PYTEST tests/fastapi/prorrogas_tec tests/fastapi/core tests/fastapi/observability tests/fastapi/helpdesk`
Expected: PASS.

- [ ] **Step 3: Clean the real Excel and dry-run the import**

Corre:

1. `docker compose -f docker/compose/docker-compose.dev.yml exec backend python -m itcj2.cli.main prorrogas excel-limpiar instance/tmp/excel/prorrogas.xlsx --salida instance/tmp/excel/limpio.xlsx`
2. `docker compose -f docker/compose/docker-compose.dev.yml exec backend python -m itcj2.cli.main prorrogas import-excel instance/tmp/excel/limpio.xlsx --dry-run`

El reporte lleva solo conteos:
- solicitudes y parcialidades;
- cuántas con problema, agrupadas por motivo;
- cuántas se importarían, cuántas sin semestre de core y cuántas sin cuenta.

Ni nombres ni números de control. **No** se corre sin `--dry-run`: la importación real queda para el humano (H12).

- [ ] **Step 4: Commit**

```bash
git add itcj2/apps/prorrogas_tec/docs
git commit -m "docs(prorrogas): flujo del historico del Excel y de estadisticas"
```

---

## Después de este plan

- **H12 (para ti):**
  1. Abrir `instance/tmp/excel/limpio.xlsx` y corregir las filas con `problema`. Vaciar esa celda después de corregir.
  2. Correr `import-excel` primero con `--dry-run` y después sin él.
  3. Hacer lo mismo en producción, con el archivo limpio ya revisado.
- Con esto se cierran los cuatro planes del Módulo 1 (§14). Lo que sigue es la vista de **Jefes**: firma "Autoriza" del Director (§15.1).
