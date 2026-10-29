# Prórrogas · Plan 1: Base de secretaría y Documentos — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** La secretaria entra a su vista de cuatro pestañas y administra las plantillas `.docx` de los 6 formatos: las sube por año, las descarga y las ve en PDF con datos de ejemplo. Todo descansa sobre un motor docx→PDF que reutilizan los planes 2–4.

**Architecture:** Se construye por capas, de abajo hacia arriba:

1. Funciones puras: formato de fechas, montos y nombres, y llenado de `.docx` con python-docx sin perder el formato aunque Word parta un marcador en varios fragmentos.
2. Conversión a PDF con LibreOffice, movida de helpdesk a core.
3. Catálogo cerrado de formatos con sus marcadores.
4. Servicio de plantillas, con archivos en `instance/apps/prorrogas_tec` y resolución año → año anterior → sistema.
5. API `/api/prorrogas/v2/templates` y páginas Jinja con la barra superior del diseño.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · PostgreSQL · Alembic (migraciones a mano) · python-docx · Pillow · LibreOffice headless · Jinja2 + JS sin framework · pytest contra Postgres real.

**Spec:** [`docs/superpowers/specs/2026-10-29-prorrogas-modulo1-design.md`](../specs/2026-10-29-prorrogas-modulo1-design.md). Este plan cubre §3 (permisos del Plan 1), §6, §8.1 (barra superior y Documentos), §13 y la fila "Plan 1" de §14. Diseño visual: `docs/design/prorrogas/secretaria-final.dc.html`.

## Global Constraints

**Rutas y permisos**

- App key `prorrogas_tec`. Páginas bajo `/prorrogas`, API bajo `/api/prorrogas/v2`. Las rutas de página se llaman `prorrogas_tec.pages.secretaria.*`.
- Permisos de este plan, exactos:
  - `prorrogas_tec.secretaria.page.view`
  - `prorrogas_tec.templates.api.read`
  - `prorrogas_tec.templates.api.upload`
- Los tres se asignan a los roles `secretaria` (nuevo) y `admin`.
- Las API usan `require_perms("prorrogas_tec", [...])`. Las páginas usan `Depends(require_page_app("prorrogas_tec", perms=[...]))`, que no tiene bypass de admin global.

**Documentos**

- Formatos, en este orden fijo: `formato_solicitud`, `carta_aceptacion`, `carta_rechazo`, `carta_compromiso_1`, `carta_compromiso_2`, `carta_compromiso_3`.
- Los marcadores siguen el regex `\{\{\s*([a-z0-9_]+)\s*\}\}`. Qué marcadores son permitidos y cuáles obligatorios: spec §6.2.
- Plantillas: solo `.docx`, de hasta `5_242_880` bytes, año de 2020 a 2100.
- Las rutas que generan PDF son `def`, no `async def` (LibreOffice bloquea).

**Convenciones**

- Un error de la API responde `{"error": <código>, "message": <español>, ...detalle}` con los códigos fijados en Task 6 y Task 7.
- El reloj es `itcj2.core.utils.timezone.db_now()` (Ciudad Juárez, naive).
- Sin dependencias nuevas en este plan.
- Migración escrita a mano: `revision = "pr20261029a"`, `down_revision = "53cfd4188f65"`.
- `database/DML/` está en `.gitignore`. El SQL nuevo se crea en el árbol de trabajo y **no** se commitea; sí se commitea su registro en `itcj2/cli/prorrogas.py`.
- Diseño:
  - Colores: `#1A130E` tinta, `#F7F7F2` papel, `#652F2A` vino, `#6799E0` azul, `#F27340` naranja, `#c4541f` alerta, fondo `#e9e6e0`.
  - Fuentes: Roboto (títulos), Open Sans (texto), IBM Plex Mono (cifras).
- Textos de la interfaz en español.

**Pruebas y commits**

- Las pruebas corren **dentro** del contenedor `backend`. En los pasos, `PYTEST` significa `docker compose -f docker/compose/docker-compose.dev.yml exec backend pytest`.
- El sandbox de Claude no alcanza Docker. Quien ejecute el plan necesita acceso a Docker o pedirle al humano que corra los comandos (`! …`).
- Cada commit termina con la línea `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Word parte un marcador en varios fragmentos.** Es lo normal cuando la secretaria edita (`{{nom` + `bre}}`). Debe encontrarse y rellenarse conservando el formato. → Task 2.
2. **Marcadores en encabezado, pie o tablas** (membrete, bloque de firmas). Deben rellenarse igual que en el cuerpo. → Task 2.
3. **Un PDF o `.doc` renombrado a `.docx`.** Debe responder 400 `docx_invalido`, no 500. → Task 6 (servicio) y Task 7 (API).
4. **Una errata en un marcador** (`{{nombr}}`). Debe rechazarse diciendo exactamente cuál. → Task 6 y Task 7.
5. **LibreOffice ausente o que falla** en la vista previa. Debe responder 503 `pdf_no_disponible` con mensaje, no 500. → Task 7.

---

### Task 1: Formato de fechas, montos y nombres

**Files:**
- Create: `itcj2/apps/prorrogas_tec/services/formatting.py`
- Create: `tests/fastapi/prorrogas_tec/__init__.py` (vacío, como en `tests/fastapi/titulatec/`)
- Test: `tests/fastapi/prorrogas_tec/test_formatting.py`

**Interfaces:**
- Produces:
  - `MESES: tuple[str, ...]` (`"enero"` … `"diciembre"`)
  - `fecha_corta(d: date) -> str`
  - `fecha_larga(d: date) -> str`
  - `pesos(amount: Decimal) -> str`
  - `nombre_oficial(first_name: str, last_name: str, middle_name: str | None) -> str`
  - `semestre_label(start: date, end: date) -> str`
  - `split_amount(total: Decimal, n: int) -> list[Decimal]`

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from decimal import Decimal
import pytest
from itcj2.apps.prorrogas_tec.services.formatting import (
    fecha_corta, fecha_larga, nombre_oficial, pesos, semestre_label, split_amount,
)

def test_fecha_corta_como_en_las_cartas():
    assert fecha_corta(date(2026, 1, 13)) == "13/enero/2026"
    assert fecha_corta(date(2026, 2, 3)) == "03/febrero/2026"

def test_fecha_larga_como_en_las_cartas():
    assert fecha_larga(date(2026, 2, 26)) == "26 de febrero de 2026"
    assert fecha_larga(date(2026, 2, 3)) == "03 de febrero de 2026"

def test_pesos_con_miles_y_centavos():
    assert pesos(Decimal("3150")) == "$3,150.00"
    assert pesos(Decimal("1216")) == "$1,216.00"
    assert pesos(Decimal("500.5")) == "$500.50"

def test_nombre_oficial_apellidos_primero_en_mayusculas():
    assert nombre_oficial("Itzel  Guadalupe", "Payán", "Flores") == "PAYÁN FLORES ITZEL GUADALUPE"
    assert nombre_oficial("Roberto", "Cárdenas", None) == "CÁRDENAS ROBERTO"

def test_semestre_label():
    assert semestre_label(date(2026, 1, 26), date(2026, 6, 12)) == "enero – junio 2026"
    assert semestre_label(date(2026, 8, 17), date(2027, 1, 8)) == "agosto 2026 – enero 2027"

def test_split_amount_pesos_enteros_con_sobrante_a_los_primeros():
    assert split_amount(Decimal("3650"), 3) == [Decimal("1217"), Decimal("1217"), Decimal("1216")]
    assert split_amount(Decimal("3150"), 2) == [Decimal("1575"), Decimal("1575")]
    assert split_amount(Decimal("6400"), 1) == [Decimal("6400")]
    assert split_amount(Decimal("1000.50"), 2) == [Decimal("500"), Decimal("500.50")]
    assert sum(split_amount(Decimal("3651"), 3)) == Decimal("3651")

@pytest.mark.parametrize("total, n", [(Decimal("100"), 0), (Decimal("100"), 4), (Decimal("0"), 1)])
def test_split_amount_rechaza_entradas_fuera_de_rango(total, n):
    with pytest.raises(ValueError):
        split_amount(total, n)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_formatting.py -v`
Expected: FAIL with `ModuleNotFoundError: ... services.formatting`

- [ ] **Step 3: Implement the six functions in `itcj2/apps/prorrogas_tec/services/formatting.py`**

- `fecha_corta` → `f"{d.day:02d}/{MESES[d.month-1]}/{d.year}"`.
- `fecha_larga` → `f"{d.day:02d} de {mes} de {año}"`.
- `pesos` → `f"${amount:,.2f}"`.
- `nombre_oficial` une apellido paterno, materno y nombre(s), colapsa los espacios y pasa a mayúsculas.
- `semestre_label`: si el inicio y el fin son del mismo año, `"{m1} – {m2} {año}"`; si no, `"{m1} {a1} – {m2} {a2}"`. El guion es el en dash (U+2013) con espacios.
- `split_amount`: lanza `ValueError` si `n ∉ 1..3` o `total <= 0`. Para repartir:
  1. `enteros = int(total)`, `centavos = total - enteros`.
  2. Las primeras `enteros % n` partes valen `enteros // n + 1` y el resto `enteros // n`.
  3. La última parte además suma los `centavos`.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_formatting.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add itcj2/apps/prorrogas_tec/services/formatting.py tests/fastapi/prorrogas_tec/__init__.py tests/fastapi/prorrogas_tec/test_formatting.py
git commit -m "feat(prorrogas): formato de fechas, montos y nombres de las cartas"
```

---

### Task 2: Motor de llenado de `.docx`

**Files:**
- Create: `itcj2/apps/prorrogas_tec/services/docx_fill.py`
- Test: `tests/fastapi/prorrogas_tec/test_docx_fill.py`

**Interfaces:**
- Produces:
  - `PLACEHOLDER_RE: re.Pattern[str]`
  - `class InvalidDocx(ValueError)`: lo lanza cualquier función si `docx.Document(BytesIO(data))` falla.
  - `class MissingValues(KeyError)` con atributo `names: frozenset[str]`.
  - `iter_paragraphs(doc: docx.document.Document) -> Iterator[docx.text.paragraph.Paragraph]`: todos los `w:p` del cuerpo (incluye tablas y cuadros de texto, vía `element.iter(qn("w:p"))`) y de cada encabezado y pie que no esté ligado al anterior (`header`, `footer`, `first_page_*`, `even_page_*`).
  - `find_placeholders(docx: bytes) -> set[str]`
  - `fill_docx(docx: bytes, values: Mapping[str, str], images: Mapping[str, bytes] | None = None, *, image_height_cm: float = 1.6) -> bytes`
  - `replace_literals(docx: bytes, mapping: Mapping[str, str]) -> tuple[bytes, dict[str, int]]`: aplica las claves en orden y cuenta los reemplazos de cada una.

- [ ] **Step 1: Write the failing test**

```python
from io import BytesIO
import pytest
from docx import Document
from PIL import Image
from itcj2.apps.prorrogas_tec.services.docx_fill import (
    InvalidDocx, MissingValues, fill_docx, find_placeholders, iter_paragraphs, replace_literals,
)

def _docx(build) -> bytes:
    d = Document(); build(d); buf = BytesIO(); d.save(buf); return buf.getvalue()

def _text(data: bytes) -> str:
    return "\n".join(p.text for p in iter_paragraphs(Document(BytesIO(data))))

def _png() -> bytes:
    buf = BytesIO(); Image.new("RGBA", (40, 12), (0, 0, 0, 255)).save(buf, "PNG"); return buf.getvalue()

def test_encuentra_marcadores_partidos_entre_runs():  # Review Focus 1
    def build(d):
        p = d.add_paragraph(); p.add_run("Alumno: {{nom"); p.add_run("bre}} y {{ no_control }}")
    assert find_placeholders(_docx(build)) == {"nombre", "no_control"}

def test_rellena_marcador_partido_con_el_formato_del_primer_run():  # Review Focus 1
    def build(d):
        p = d.add_paragraph(); p.add_run("Hola "); r = p.add_run("{{nom"); r.bold = True; p.add_run("bre}}!")
    out = fill_docx(_docx(build), {"nombre": "ANA"})
    para = Document(BytesIO(out)).paragraphs[0]
    assert para.text == "Hola ANA!"
    assert [r.text for r in para.runs if r.bold] == ["ANA"]

def test_rellena_en_tablas_encabezados_y_pies():  # Review Focus 2
    def build(d):
        d.add_table(rows=1, cols=1).cell(0, 0).text = "{{carrera}}"
        d.sections[0].header.paragraphs[0].text = "{{fecha}}"
        d.sections[0].footer.paragraphs[0].text = "{{folio}}"
    out = fill_docx(_docx(build), {"carrera": "ISC", "fecha": "13/enero/2026", "folio": "PR-00001"})
    text = _text(out)
    assert "{{" not in text and {"ISC", "13/enero/2026", "PR-00001"} <= set(text.split("\n"))

def test_faltan_valores_lanza_missing_values_con_los_nombres():
    data = _docx(lambda d: d.add_paragraph("{{a}} {{b}}"))
    with pytest.raises(MissingValues) as e:
        fill_docx(data, {"a": "1"})
    assert e.value.names == frozenset({"b"})

def test_marcador_de_imagen_inserta_la_imagen_y_quita_el_texto():
    out = fill_docx(_docx(lambda d: d.add_paragraph("{{firma_estudiante}}")), {}, images={"firma_estudiante": _png()})
    doc = Document(BytesIO(out))
    assert doc.paragraphs[0].text == "" and len(doc.inline_shapes) == 1

def test_marcador_de_imagen_con_texto_vacio_lo_borra():
    out = fill_docx(_docx(lambda d: d.add_paragraph("Firma: {{firma_estudiante}}")), {"firma_estudiante": ""})
    assert _text(out) == "Firma: "

def test_bytes_que_no_son_docx_lanzan_invalid_docx():  # Review Focus 3
    with pytest.raises(InvalidDocx):
        find_placeholders(b"%PDF-1.7 no soy un docx")

def test_replace_literals_cuenta_y_cruza_runs():
    def build(d):
        p = d.add_paragraph(); p.add_run("PAYAN FLO"); p.add_run("RES ITZEL y PAYAN FLORES ITZEL")
    out, counts = replace_literals(_docx(build), {"PAYAN FLORES ITZEL": "{{nombre}}", "NO EXISTE": "x"})
    assert counts == {"PAYAN FLORES ITZEL": 2, "NO EXISTE": 0}
    assert _text(out) == "{{nombre}} y {{nombre}}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_docx_fill.py -v`
Expected: FAIL with `ModuleNotFoundError: ... services.docx_fill`

- [ ] **Step 3: Implement `docx_fill.py`**

`fill_docx` y `replace_literals` comparten un único reemplazo de tramos por párrafo. La firma no lo determina, así que este es el algoritmo:

```
para cada párrafo p de iter_paragraphs(doc):
    runs  = los w:r de p, en orden (incluye los que están dentro de w:hyperlink)
    texts = [concatenación de los w:t de cada run]
    full  = "".join(texts)
    matches = [(inicio, fin, reemplazo)] sobre `full`   # regex de marcadores o literales; sin traslapes
    para (inicio, fin, repl) en orden INVERSO:
        (rs, os) = run y desplazamiento de `inicio`; (re_, oe) = los de `fin`
        si rs == re_: texts[rs] = texts[rs][:os] + repl + texts[rs][oe:]
        si no:        texts[rs] = texts[rs][:os] + repl
                      texts[k] = "" para rs < k < re_
                      texts[re_] = texts[re_][oe:]
    reescribir: en cada run, el primer w:t recibe texts[i] (xml:space="preserve") y se borran los demás w:t
```

- El formato del reemplazo es el del run donde empieza el marcador.
- En `fill_docx`:
  - `faltantes = encontrados - set(values) - set(images or {})`. Si no está vacío, lanza `MissingValues`.
  - Un marcador que está en `images` se reemplaza por `""`. Luego, en el run donde empezaba, se llama a `Run(run_el, p).add_picture(BytesIO(png), height=Cm(image_height_cm))`.
  - Un marcador de imagen que solo aparece en `values` se trata como texto.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_docx_fill.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add itcj2/apps/prorrogas_tec/services/docx_fill.py tests/fastapi/prorrogas_tec/test_docx_fill.py
git commit -m "feat(prorrogas): llenado de plantillas docx con marcadores partidos por Word"
```

---

### Task 3: Conversión `.docx` → PDF en core

**Files:**
- Create: `itcj2/core/utils/docx_pdf.py`
- Modify: `itcj2/apps/helpdesk/services/document_service.py:342-412`. `_find_libreoffice_cmd` se elimina y `_convert_docx_to_pdf` se vuelve un envoltorio.
- Modify: `itcj2/observability/work.py:93-104` (`DOCUMENT_KIND_ENGINE` gana `"prorrogas_documento": "libreoffice"`).
- Modify: `tests/fastapi/observability/test_work_metrics.py:119`. El dict literal gana el mismo par.
- Modify: `tests/fastapi/observability/test_work_sites_helpdesk.py:46,50,78,84,106,111,124,129`. Cambian los objetivos de los parches (Step 3).
- Test: `tests/fastapi/prorrogas_tec/test_docx_pdf.py`

**Interfaces:**
- Produces:
  - `class PdfConversionError(RuntimeError)`
  - `find_libreoffice() -> str | None`
  - `docx_to_pdf(docx: bytes, *, kind: str) -> bytes`
  - El `kind` de Prórrogas es `"prorrogas_documento"`.
- Helpdesk conserva `_convert_docx_to_pdf(docx_buffer: BytesIO, kind: str) -> BytesIO`: importa `from itcj2.core.utils.docx_pdf import docx_to_pdf` y devuelve `BytesIO(docx_to_pdf(docx_buffer.read(), kind=kind))`.

- [ ] **Step 1: Write the failing test**

```python
from io import BytesIO
import pytest
from docx import Document
from itcj2.core.utils import docx_pdf
from itcj2.core.utils.docx_pdf import PdfConversionError

def test_sin_libreoffice_lanza_pdf_conversion_error(monkeypatch):
    monkeypatch.setattr(docx_pdf, "find_libreoffice", lambda: None)
    with pytest.raises(PdfConversionError, match="LibreOffice no está instalado"):
        docx_pdf.docx_to_pdf(b"x", kind="prorrogas_documento")

def test_helpdesk_delega_en_core(monkeypatch):
    from itcj2.apps.helpdesk.services import document_service
    monkeypatch.setattr(document_service, "docx_to_pdf", lambda data, *, kind: b"%PDF-" + kind.encode())
    assert document_service._convert_docx_to_pdf(BytesIO(b"docx"), "solicitud").read() == b"%PDF-solicitud"

@pytest.mark.skipif(docx_pdf.find_libreoffice() is None, reason="sin LibreOffice")
def test_convierte_un_docx_real():
    d = Document(); d.add_paragraph("hola"); buf = BytesIO(); d.save(buf)
    assert docx_pdf.docx_to_pdf(buf.getvalue(), kind="prorrogas_documento").startswith(b"%PDF")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_docx_pdf.py -v`
Expected: FAIL with `ModuleNotFoundError: ... core.utils.docx_pdf`

- [ ] **Step 3: Move the body of `_convert_docx_to_pdf` to `docx_to_pdf`**

- Copia el cuerpo **literal**: los mismos tres mensajes de error, el mismo `with measured(kind, "libreoffice")`, `timeout=60` y el mismo `logger.error(... kind=%s, returncode=%s ...)`.
- El único cambio de tipo: donde el original lanzaba `RuntimeError`, el nuevo lanza `PdfConversionError`. Al ser subclase, helpdesk no nota la diferencia.
- `subprocess.TimeoutExpired` se propaga igual que antes.
- En `test_work_sites_helpdesk.py`:
  - Cambia `monkeypatch.setattr(document_service, "_find_libreoffice_cmd", …)` por `monkeypatch.setattr(docx_pdf, "find_libreoffice", …)`.
  - Cambia `document_service.subprocess` por `docx_pdf.subprocess`.
  - Cambia el filtro de log `document_service.logger.name` por `docx_pdf.logger.name`.
  - Agrega `from itcj2.core.utils import docx_pdf`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_docx_pdf.py tests/fastapi/observability -q`
Expected: PASS. Pasan `test_work_sites_helpdesk.py`, `test_work_metrics.py` y `test_cardinalidad.py`. La prueba real se salta solo si el contenedor no tiene LibreOffice.

- [ ] **Step 5: Commit**

```bash
git add itcj2/core/utils/docx_pdf.py itcj2/apps/helpdesk/services/document_service.py itcj2/observability/work.py tests/fastapi/observability/test_work_metrics.py tests/fastapi/observability/test_work_sites_helpdesk.py tests/fastapi/prorrogas_tec/test_docx_pdf.py
git commit -m "refactor(core): conversion docx->pdf compartida en core; helpdesk delega"
```

---

### Task 4: Catálogo de formatos y datos de ejemplo

**Files:**
- Create: `itcj2/apps/prorrogas_tec/documents/__init__.py` (vacío)
- Create: `itcj2/apps/prorrogas_tec/documents/catalog.py`
- Test: `tests/fastapi/prorrogas_tec/test_catalog.py`

**Interfaces:**
- Consumes: `fecha_corta`, `fecha_larga`, `pesos`, `split_amount` (Task 1).
- Produces:
  - `@dataclass(frozen=True) class DocType`, con campos `code: str`, `label: str`, `required: frozenset[str]`, `allowed: frozenset[str]` e `images: frozenset[str]`.
  - `COMMON_FIELDS: frozenset[str]`
  - `DOC_TYPES: dict[str, DocType]`, en el orden de Global Constraints.
  - `default_template_path(code: str) -> Path`, que apunta a `documents/defaults/{code}.docx`.
  - `sample_signature_png() -> bytes`
  - `sample_values(code: str, *, today: date | None = None) -> tuple[dict[str, str], dict[str, bytes]]`
- Etiquetas exactas: `"Formato de solicitud"`, `"Carta de aceptación"`, `"Carta de rechazo"`, `"Carta compromiso · 1 pago"`, `"Carta compromiso · 2 pagos"`, `"Carta compromiso · 3 pagos"`.
- Los conjuntos de cada formato son los de spec §6.2.

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from io import BytesIO
import pytest
from PIL import Image
from itcj2.apps.prorrogas_tec.documents.catalog import (
    COMMON_FIELDS, DOC_TYPES, sample_signature_png, sample_values,
)

def test_hay_seis_formatos_en_orden():
    assert list(DOC_TYPES) == ["formato_solicitud", "carta_aceptacion", "carta_rechazo",
                               "carta_compromiso_1", "carta_compromiso_2", "carta_compromiso_3"]

@pytest.mark.parametrize("code", list(DOC_TYPES))
def test_obligatorios_imagenes_y_comunes_son_permitidos(code):
    t = DOC_TYPES[code]
    assert t.required <= t.allowed and t.images <= t.allowed and COMMON_FIELDS <= t.allowed

def test_compromiso_de_dos_pagos():
    t = DOC_TYPES["carta_compromiso_2"]
    assert {"pago1_monto", "pago1_fecha", "pago2_monto", "pago2_fecha", "firma_estudiante"} <= t.required
    assert "pago3_fecha" not in t.allowed

def test_compromiso_de_un_pago_no_exige_el_monto_del_pago():
    t = DOC_TYPES["carta_compromiso_1"]
    assert "pago1_fecha" in t.required and "pago1_monto" in t.allowed - t.required

def test_rechazo_exige_motivo():
    assert DOC_TYPES["carta_rechazo"].required == frozenset({"nombre", "no_control", "motivo_rechazo"})

@pytest.mark.parametrize("code", list(DOC_TYPES))
def test_los_datos_de_ejemplo_cubren_todo_lo_permitido(code):
    values, images = sample_values(code, today=date(2026, 1, 13))
    assert DOC_TYPES[code].allowed <= set(values) | set(images)

def test_ejemplo_de_tres_pagos_reparte_3650():
    values, _ = sample_values("carta_compromiso_3", today=date(2026, 1, 13))
    assert [values[f"pago{i}_monto"] for i in (1, 2, 3)] == ["$1,217.00", "$1,217.00", "$1,216.00"]
    assert values["pago1_fecha"] == "13 de febrero de 2026" and values["fecha"] == "13/enero/2026"

def test_la_firma_de_ejemplo_es_un_png():
    assert Image.open(BytesIO(sample_signature_png())).format == "PNG"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_catalog.py -v`
Expected: FAIL with `ModuleNotFoundError: ... documents.catalog`

- [ ] **Step 3: Implement `catalog.py`**

**Valores de ejemplo fijos:**

| Marcador | Valor |
|---|---|
| `nombre` | `"ESTUDIANTE DE EJEMPLO"` |
| `no_control` | `"99000000"` |
| `carrera` | `"Ingeniería en Sistemas Computacionales"` |
| `semestre` | `"enero – junio 2026"` |
| `folio` | `"PR-00000"` |
| `fecha` y `fecha_solicitud` | `fecha_corta(today or db_now().date())` |
| `plazos_solicitados` | `"3"` |
| `motivo` | `"Motivo de ejemplo: el pago de nómina se retrasó este mes."` |
| `correo` | `"L99000000@cdjuarez.tecnm.mx"` |
| `comentario` | `"Comentario de ejemplo."` |
| `motivo_rechazo` | `"Motivo de ejemplo del rechazo."` |
| `monto_total` | `pesos(Decimal("3650"))` |
| `pagoI_monto` | `split_amount(Decimal("3650"), N)`, formateado con `pesos` |
| `pagoI_fecha` | `fecha_larga` de `date(2026,2,13)`, `date(2026,2,27)`, `date(2026,3,27)` |
| `firma_estudiante_leyenda` | `"Firmado electrónicamente por ESTUDIANTE DE EJEMPLO el {dd/mm/aaaa} 10:42 · folio PR-00000"` |
| `firma_estudiante` | va en `images` |

**Firma de ejemplo:** `sample_signature_png` es un RGBA de 600×180 transparente con una polilínea `#1A130E` de 6 px.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_catalog.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add itcj2/apps/prorrogas_tec/documents/__init__.py itcj2/apps/prorrogas_tec/documents/catalog.py tests/fastapi/prorrogas_tec/test_catalog.py
git commit -m "feat(prorrogas): catalogo de los 6 formatos y datos de ejemplo"
```

---

### Task 5: Plantillas del sistema (a partir de las cartas reales)

**Files:**
- Create: `tools/prorrogas/build_default_templates.py`
- Create (generados por el script y commiteados): `itcj2/apps/prorrogas_tec/documents/defaults/{formato_solicitud,carta_aceptacion,carta_rechazo,carta_compromiso_1,carta_compromiso_2,carta_compromiso_3}.docx`
- Test: `tests/fastapi/prorrogas_tec/test_default_templates.py`

**Interfaces:**
- Consumes:
  - De Task 2: `replace_literals`, `find_placeholders`, `fill_docx`, `iter_paragraphs`.
  - De Task 4: `DOC_TYPES`, `default_template_path`, `sample_values`.
- Produces: los 6 `.docx` en `documents/defaults/`, que `default_template_path(code)` encuentra.

- [ ] **Step 1: Write the failing test**

```python
import pytest
from io import BytesIO
from docx import Document
from itcj2.apps.prorrogas_tec.documents.catalog import DOC_TYPES, default_template_path, sample_values
from itcj2.apps.prorrogas_tec.services.docx_fill import fill_docx, find_placeholders, iter_paragraphs

PII = ["PAYAN", "ITZEL", "22111670", "HERNANDEZ SOLANO", "24112010", "CARDENAS ALMANZA", "M23111966"]

@pytest.mark.parametrize("code", list(DOC_TYPES))
def test_plantilla_del_sistema_tiene_los_marcadores_correctos(code):
    found = find_placeholders(default_template_path(code).read_bytes())
    assert DOC_TYPES[code].required <= found <= DOC_TYPES[code].allowed

@pytest.mark.parametrize("code", list(DOC_TYPES))
def test_plantilla_del_sistema_no_trae_datos_de_estudiantes_reales(code):
    doc = Document(BytesIO(default_template_path(code).read_bytes()))
    text = "\n".join(p.text for p in iter_paragraphs(doc)).upper()
    assert not [s for s in PII if s in text]

@pytest.mark.parametrize("code", list(DOC_TYPES))
def test_plantilla_del_sistema_se_llena_con_los_datos_de_ejemplo(code):
    out = fill_docx(default_template_path(code).read_bytes(), *sample_values(code))
    assert find_placeholders(out) == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_default_templates.py -v`
Expected: FAIL with `FileNotFoundError` (todavía no existe `defaults/`).

- [ ] **Step 3: Copy the real letters to a git-ignored folder the container can see**

Run (en el host WSL, desde la raíz del repo):
`mkdir -p instance/tmp/prorrogas_ejemplos && cp "/mnt/c/Users/Deigo/Desktop/Prorrogas/Antecedentes/"*.docx instance/tmp/prorrogas_ejemplos/`

Expected: 3 archivos en `instance/tmp/prorrogas_ejemplos/` (`instance/` está en `.gitignore`).

- [ ] **Step 4: Write `tools/prorrogas/build_default_templates.py --source DIR --out DIR`**

**Fuentes** (nombres exactos; el de 3 pagos lleva un espacio antes de `.docx`):

- `carta_compromiso_1` ← `Prórroga un pago 2026.docx`
- `carta_compromiso_2` ← `Prórroga en dos exhibiciones 2026.docx`
- `carta_compromiso_3` ← `Prórroga tres pagos 2026 .docx`

**Reemplazos literales** con `replace_literals`, en este orden. Si alguna clave cuenta 0, el script imprime cuáles y sale con código 1.

| Formato | Texto real | Marcador |
|---|---|---|
| 1 pago | `03/febrero/2026` | `{{fecha}}` |
| 1 pago | `$6,400.00` | `{{monto_total}}` |
| 1 pago | `enero – junio 2026` | `{{semestre}}` |
| 1 pago | `CARDENAS ALMANZA ROBERTO` | `{{nombre}}` |
| 1 pago | `M23111966` | `{{no_control}}` |
| 1 pago | `de la maestría de Ingeniería Administrativa` | `de la carrera de {{carrera}}` |
| 1 pago | `03 de febrero de 2026` | `{{pago1_fecha}}` |
| 2 pagos | `13/enero/2026` | `{{fecha}}` |
| 2 pagos | `$3,150.00` | `{{monto_total}}` |
| 2 pagos | `como concepto de inscripción para el estudiante` | `como concepto de inscripción para el semestre {{semestre}}, para el (la) estudiante` |
| 2 pagos | `PAYAN FLORES ITZEL GUADALUPE` | `{{nombre}}` |
| 2 pagos | `22111670` | `{{no_control}}` |
| 2 pagos | `Licenciatura en Administración` | `{{carrera}}` |
| 2 pagos | `$1,575.00 a efectuarse el día 26 de febrero de 2026` | `{{pago1_monto}} a efectuarse el día {{pago1_fecha}}` |
| 2 pagos | `$1,575.00 a efectuarse el día 23 de abril de 2026` | `{{pago2_monto}} a efectuarse el día {{pago2_fecha}}` |
| 3 pagos | `03/febrero/2026` | `{{fecha}}` |
| 3 pagos | `$3,650.00` | `{{monto_total}}` |
| 3 pagos | `enero – junio 2026` | `{{semestre}}` |
| 3 pagos | `HERNANDEZ SOLANO JOSE ESAU` | `{{nombre}}` |
| 3 pagos | `24112010` | `{{no_control}}` |
| 3 pagos | `Ingeniería en Sistemas Computacionales EAD` | `{{carrera}}` |
| 3 pagos | `$1,217.00 a efectuarse el día 13 de febrero de 2026` | `{{pago1_monto}} a efectuarse el día {{pago1_fecha}}` |
| 3 pagos | `$1,217.00 a efectuarse el día 27 de febrero de 2026` | `{{pago2_monto}} a efectuarse el día {{pago2_fecha}}` |
| 3 pagos | `$1,216.00 a efectuarse el día 27 de marzo de 2026` | `{{pago3_monto}} a efectuarse el día {{pago3_fecha}}` |

**Firma en las tres cartas compromiso:**

- Inserta un párrafo nuevo `{{firma_estudiante}}` justo antes del **único** párrafo cuyo texto (sin espacios a los lados) es `{{nombre}}`, que es el del bloque de firmas. Copia el `w:pPr` de ese párrafo.
- Inserta `{{firma_estudiante_leyenda}}` justo después del único párrafo cuyo texto es `ESTUDIANTE`. Copia su `w:pPr` y usa letra de 7 pt.
- Si alguna coincidencia no es exactamente una, el script sale con 1.

**Formatos nuevos** (`carta_aceptacion`, `carta_rechazo`, `formato_solicitud`):

1. Parte de `Prórroga un pago 2026.docx` **original**.
2. Borra los elementos del cuerpo desde el párrafo que contiene `Ciudad Juárez, Chihuahua` hasta el final, excepto el `w:sectPr`. Lo anterior a esa línea (membrete en el cuerpo, si lo hay) y los encabezados se conservan.
3. Agrega las líneas de spec §6.4, **copiadas exactamente**, cada una como párrafo de estilo Normal, con un párrafo vacío entre líneas.
4. Alineación: la 1.ª línea a la derecha; desde `A T E N T A M E N T E` hasta el final, centrado; el resto, justificado.

**Validación final:** para cada salida, `DOC_TYPES[c].required <= find_placeholders(out) <= DOC_TYPES[c].allowed`; si no se cumple, sale con 1. Por cada archivo escrito imprime `OK <code>`.

- [ ] **Step 5: Run the builder**

Run: `docker compose -f docker/compose/docker-compose.dev.yml exec backend python tools/prorrogas/build_default_templates.py --source instance/tmp/prorrogas_ejemplos --out itcj2/apps/prorrogas_tec/documents/defaults`
Expected: 6 líneas `OK <code>` y código de salida 0.

- [ ] **Step 6: Visual check (human)**

Abre los 6 `.docx` en Word o LibreOffice y revisa:

- El membrete está intacto.
- En las cartas compromiso, `{{firma_estudiante}}` queda sobre el nombre del estudiante y la columna del Director no se desalinea.

Si la tabla de firmas se ve desalineada, ajústala a mano en Word y guarda sobre el mismo archivo. Las pruebas de Step 7 siguen siendo el criterio.

- [ ] **Step 7: Run test to verify it passes**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_default_templates.py -v`
Expected: PASS (18 tests)

- [ ] **Step 8: Commit**

```bash
git add tools/prorrogas/build_default_templates.py itcj2/apps/prorrogas_tec/documents/defaults tests/fastapi/prorrogas_tec/test_default_templates.py
git commit -m "feat(prorrogas): plantillas del sistema derivadas de las cartas reales"
```

---

### Task 6: Modelo, migración y servicio de plantillas

**Files:**
- Create: `itcj2/apps/prorrogas_tec/models/template.py`
- Modify: `itcj2/apps/prorrogas_tec/models/__init__.py` (exporta `ProrrogaTemplate` y lo agrega a `__all__`)
- Modify: `itcj2/models/__init__.py:63-65` (importa `ProrrogaTemplate`)
- Modify: `itcj2/config.py:~475` (`PRORROGAS_UPLOAD_PATH: str = os.path.join(os.path.abspath("instance"), "apps", "prorrogas_tec")`, junto a `TITULATEC_UPLOAD_PATH`)
- Create: `migrations/versions/pr20261029a_prorrogas_templates.py`
- Create: `itcj2/apps/prorrogas_tec/services/template_service.py`
- Create: `tests/fastapi/prorrogas_tec/conftest.py`
- Test: `tests/fastapi/prorrogas_tec/test_template_service.py`

**Interfaces:**
- Consumes:
  - De Task 2: `find_placeholders`, `InvalidDocx`.
  - De Task 4: `DOC_TYPES`, `default_template_path`.
- Produces:
  - Modelo `ProrrogaTemplate`, tabla `prorrogas_templates`, con estas columnas:
    - `id: Integer`, llave primaria.
    - `doc_type: String(40)`, no nulo.
    - `year: SmallInteger`, no nulo.
    - `original_name: Text`, no nulo.
    - `file_path: Text`, no nulo, relativo a la base.
    - `size_bytes: Integer`, no nulo.
    - `sha256: String(64)`, no nulo.
    - `placeholders: JSON`, no nulo; lista ordenada.
    - `uploaded_by_id: BigInteger`, FK a `core_users.id` con `ON DELETE SET NULL`, nulo permitido.
    - `uploaded_at: DateTime`, no nulo, `server_default NOW()`.
  - Restricciones de la tabla: `CheckConstraint("year BETWEEN 2020 AND 2100", name="ck_prorrogas_templates_year")` e `Index("ix_prorrogas_templates_tipo_anio", "doc_type", "year", "uploaded_at")`. Deben declararse igual en el modelo y en la migración.
  - En `template_service.py`:
    - `MAX_TEMPLATE_BYTES = 5 * 1024 * 1024` y `YEAR_MIN, YEAR_MAX = 2020, 2100`.
    - `class TemplateError(ValueError)` con `__init__(self, code: str, message: str, **detail)` y atributos `.code`, `.message` y `.detail: dict`.
    - `_base() -> Path`, que devuelve `Path(get_settings().PRORROGAS_UPLOAD_PATH)`. Las pruebas lo parchan, como `titulatec/utils/storage._base`.
  - `class TemplateService`, solo con `@staticmethod` y `db` como primer parámetro:
    - `upload(db, *, doc_type: str, year: int, filename: str, data: bytes, actor_id: int | None) -> ProrrogaTemplate`: hace commit.
    - `active(db, doc_type: str, year: int) -> ProrrogaTemplate | None`: la más reciente del año. Si no hay, la más reciente del año anterior más cercano (`year < y`, ordenada por `year desc, uploaded_at desc, id desc`).
    - `resolve(db, doc_type: str, year: int) -> tuple[bytes, ProrrogaTemplate | None]`: los bytes de `active()`, o los de `default_template_path` con `None`.
    - `years(db, *, current_year: int) -> list[int]`: los años con plantillas más `current_year`, en orden descendente y sin repetidos.
    - `read_bytes(t: ProrrogaTemplate) -> bytes`
    - `abs_path(rel: str) -> Path`: `safe_join(_base(), rel)`.
  - Fixtures de `conftest.py`:
    - `almacen(tmp_path, monkeypatch) -> Path`: autouse; parcha `template_service._base` para que devuelva `tmp_path / "prorrogas_tec"`.
    - `make_user(db_session)`: la misma fábrica de `tests/fastapi/titulatec/conftest.py:549-582`, con username `pr_test_{n}`.
    - `docx_con() -> Callable[..., bytes]`: un `.docx` con un párrafo por cada línea recibida.

Validación de `upload`, en este orden:

| # | Código | Mensaje |
|---|---|---|
| 1 | `tipo_invalido` | `"El tipo de documento no existe."` |
| 2 | `anio_invalido` | `"El año debe estar entre 2020 y 2100."` |
| 3 | `extension_invalida` (si el nombre no termina en `.docx`, sin distinguir mayúsculas) | `"Solo se aceptan archivos de Word (.docx)."` |
| 4 | `archivo_muy_grande` (si `len(data) > MAX`) | `"El archivo pasa de 5 MB."` |
| 5 | `docx_invalido` | `"El archivo no es un documento de Word válido."` |
| 6 | `placeholders_desconocidos` (detalle `desconocidos=[ordenados]`) | `"La plantilla tiene marcadores que no existen: {a, b}."` |
| 7 | `placeholders_faltantes` (detalle `faltantes=[ordenados]`) | `"A la plantilla le faltan marcadores obligatorios: {a, b}."` |

Después de validar:

1. Escribe el archivo de forma atómica (temporal en la misma carpeta + `os.replace`) en `templates/{year}/{doc_type}-{sha256[:12]}.docx`.
2. Inserta el renglón y hace commit.

- [ ] **Step 1: Write the failing test**

```python
import hashlib
import pytest
from itcj2.apps.prorrogas_tec.documents.catalog import default_template_path
from itcj2.apps.prorrogas_tec.services.template_service import MAX_TEMPLATE_BYTES, TemplateError, TemplateService

RECHAZO_OK = ("{{nombre}}", "{{no_control}}", "{{motivo_rechazo}}")

def _up(db, docx, *, doc_type="carta_rechazo", year=2026, filename="rechazo.docx", actor=None):
    return TemplateService.upload(db, doc_type=doc_type, year=year, filename=filename, data=docx, actor_id=actor)

def test_sube_plantilla_valida(db_session, docx_con, almacen, make_user):
    data = docx_con(*RECHAZO_OK)
    t = _up(db_session, data, actor=make_user().id)
    assert t.placeholders == ["motivo_rechazo", "no_control", "nombre"]
    assert t.sha256 == hashlib.sha256(data).hexdigest() and t.size_bytes == len(data)
    assert TemplateService.abs_path(t.file_path).read_bytes() == data
    assert t.file_path.startswith("templates/2026/carta_rechazo-")

@pytest.mark.parametrize("kwargs, data, code", [
    ({"filename": "x.docx"}, b"%PDF-1.7 no soy docx", "docx_invalido"),   # Review Focus 3
    ({"filename": "x.pdf"}, b"%PDF-1.7", "extension_invalida"),
    ({"doc_type": "otro"}, b"", "tipo_invalido"),
    ({"year": 1999}, b"", "anio_invalido"),
])
def test_rechaza_entradas_invalidas(db_session, kwargs, data, code):
    with pytest.raises(TemplateError) as e:
        _up(db_session, data, **kwargs)
    assert e.value.code == code

def test_rechaza_archivo_muy_grande_antes_de_abrirlo(db_session):
    with pytest.raises(TemplateError) as e:
        _up(db_session, b"0" * (MAX_TEMPLATE_BYTES + 1))
    assert e.value.code == "archivo_muy_grande"

def test_rechaza_errata_en_marcador(db_session, docx_con):  # Review Focus 4
    with pytest.raises(TemplateError) as e:
        _up(db_session, docx_con(*RECHAZO_OK, "{{nombr}}"))
    assert e.value.code == "placeholders_desconocidos" and e.value.detail["desconocidos"] == ["nombr"]

def test_rechaza_si_faltan_obligatorios(db_session, docx_con):
    with pytest.raises(TemplateError) as e:
        _up(db_session, docx_con("{{nombre}}", "{{no_control}}"))
    assert e.value.code == "placeholders_faltantes" and e.value.detail["faltantes"] == ["motivo_rechazo"]

# Años 2089–2095 a propósito: las pruebas corren contra la BD de dev dentro de un
# savepoint, y ahí puede haber plantillas reales COMMITEADAS de 2024–2027.
def test_resolve_anio_luego_anterior_luego_sistema(db_session, docx_con):
    data, t = TemplateService.resolve(db_session, "carta_rechazo", 2090)
    assert t is None and data == default_template_path("carta_rechazo").read_bytes()
    _up(db_session, docx_con(*RECHAZO_OK, "a"), year=2091)               # un año POSTERIOR no aplica
    assert TemplateService.resolve(db_session, "carta_rechazo", 2090)[1] is None
    v2089 = _up(db_session, docx_con(*RECHAZO_OK, "b"), year=2089)
    assert TemplateService.resolve(db_session, "carta_rechazo", 2090)[1].id == v2089.id
    _up(db_session, docx_con(*RECHAZO_OK, "c"), year=2090)
    newest = _up(db_session, docx_con(*RECHAZO_OK, "d"), year=2090)     # mismo NOW(): desempata el id
    assert TemplateService.resolve(db_session, "carta_rechazo", 2090)[1].id == newest.id

def test_years_incluye_el_actual_y_ordena_desc(db_session, docx_con):
    _up(db_session, docx_con(*RECHAZO_OK), year=2093)
    ys = TemplateService.years(db_session, current_year=2095)
    assert ys[0] == 2095 and 2093 in ys and ys == sorted(set(ys), reverse=True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_template_service.py -v`
Expected: FAIL with `ModuleNotFoundError: ... services.template_service`

- [ ] **Step 3: Implement the model, config, migration, service and fixtures**

- La migración solo crea la tabla, el CHECK y el índice. `downgrade` los tira.
- El docstring de la migración sigue el formato de `migrations/versions/tt20261015a_*.py`: qué agrega, qué pierde el downgrade y `Revision ID / Revises / Create Date`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_template_service.py -v`
Expected: PASS (10 tests)

Run: `docker compose -f docker/compose/docker-compose.dev.yml exec backend alembic upgrade head`
Expected: aplica `pr20261029a` sin errores. `alembic heads` muestra una sola cabeza.

- [ ] **Step 5: Commit**

```bash
git add itcj2/apps/prorrogas_tec/models/template.py itcj2/apps/prorrogas_tec/models/__init__.py itcj2/models/__init__.py itcj2/config.py migrations/versions/pr20261029a_prorrogas_templates.py itcj2/apps/prorrogas_tec/services/template_service.py tests/fastapi/prorrogas_tec/conftest.py tests/fastapi/prorrogas_tec/test_template_service.py
git commit -m "feat(prorrogas): plantillas por anio con validacion de marcadores"
```

---

### Task 7: Permisos y API de plantillas

**Files:**
- Create (gitignored, no se commitea): `database/DML/prorrogas_tec/04_insert_secretaria.sql`
- Modify: `itcj2/cli/prorrogas.py:9-14` (agrega `"04_insert_secretaria.sql"` a `_DML_FILES` y a la docstring del comando)
- Create: `itcj2/apps/prorrogas_tec/api/templates.py`
- Modify: `itcj2/apps/prorrogas_tec/router.py` (`include_router(templates_router, prefix="/templates")`)
- Modify: `tests/fastapi/prorrogas_tec/conftest.py`
- Test: `tests/fastapi/prorrogas_tec/test_templates_api.py`

**Interfaces:**
- Consumes:
  - De Task 6: `TemplateService.*`, `TemplateError`.
  - De Task 4: `DOC_TYPES`, `default_template_path`, `sample_values`.
  - De Task 2: `fill_docx`.
  - De Task 3: `docx_pdf.docx_to_pdf`, `PdfConversionError`. Se importa como `from itcj2.core.utils import docx_pdf` y se llama `docx_pdf.docx_to_pdf(...)`, para que las pruebas parchen `itcj2.core.utils.docx_pdf.docx_to_pdf`.
- Produces:
  - **`04_insert_secretaria.sql`**, idempotente, al estilo de `01`/`02`:
    1. `INSERT INTO core_roles (name) VALUES ('secretaria') ON CONFLICT (name) DO NOTHING` (`core_roles.name` es UNIQUE).
    2. Los tres permisos del plan con `ON CONFLICT (app_id, code) DO NOTHING`.
    3. Los asigna a `secretaria` y a `admin`.
  - **Endpoints.** Todos van bajo `/api/prorrogas/v2/templates` y todos son `def`:

    | Método y ruta | Permiso | Respuesta |
    |---|---|---|
    | `GET ""` | `templates.api.read` | 200 con `{"tipos": [...], "anios": [...]}` (forma abajo) |
    | `POST ""` (multipart: `doc_type`, `anio`, `archivo`) | `templates.api.upload` | 201 `{"id", "doc_type", "anio", "original_name", "placeholders"}`. Error de validación: 400 con `{"error": e.code, "message": e.message, **e.detail}` |
    | `GET "/{template_id}/archivo"` | `templates.api.read` | El `.docx` como adjunto, con el nombre original. Si no existe: 404 `plantilla_no_encontrada` |
    | `GET "/sistema/{doc_type}/archivo"` | `templates.api.read` | La plantilla del sistema como `{doc_type}.docx`. Tipo desconocido: 404 `tipo_invalido` |
    | `GET "/vista-previa/{doc_type}.pdf?anio="` | `templates.api.read` | `resolve` → `fill_docx(*sample_values)` → `docx_to_pdf(kind="prorrogas_documento")` → `application/pdf` inline. Errores abajo |

  - **Forma del `GET ""`:**
    - `"tipos"`: `[{"code", "label", "obligatorios": [...], "permitidos": [...]}]`, 6 elementos en orden.
    - `"anios"`: `[{"anio": int, "plantillas": [...]}]`. Los años salen de `years(current_year=db_now().year)`.
    - Cada `"plantillas"` trae 6 elementos `{"doc_type", "label", "origen", "plantilla"}`. `"origen"` vale `"subida"`, `"heredada"` o `"sistema"`. `"plantilla"` es `null` o `{"id", "anio", "original_name", "uploaded_at", "size_bytes"}`.
    - `origen` se calcula con `active()`: `subida` si `t.year == anio`, `heredada` si `t.year < anio`, `sistema` si no hay.
  - **Errores de la vista previa:** `anio` toma el año actual por omisión.
    - Tipo desconocido → 404 `tipo_invalido`.
    - `anio` fuera de rango → 400 `anio_invalido`.
    - `PdfConversionError` → 503 `{"error": "pdf_no_disponible", "message": "No se pudo generar el PDF. Intenta de nuevo o descarga la plantilla."}`.
  - **Constante:** `DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"`.
  - **Fixtures nuevos en `conftest.py`:**
    - Copiados de `tests/fastapi/titulatec/conftest.py`: `_TestSession` (líneas 414+), `patched_session_local` y `client`.
    - `prorrogas_app(db_session) -> App`: key `prorrogas_tec`, idempotente.
    - `make_role(name: str, perm_codes: Iterable[str] = ()) -> Role`: crea los permisos bajo `prorrogas_app`.
    - `grant(user, role) -> None`: crea un `UserAppRole` en `prorrogas_app` e invalida el caché de authz.
    - `client_as(client)`: `_as(user)` pone la cookie `itcj_token` con `make_jwt(user_id=user.id, role="", name=user.full_name, cn=user.control_number)`.
    - `secretaria() -> User`: rol `"secretaria"` con `SECRETARIA_PERMS = ["prorrogas_tec.secretaria.page.view", "prorrogas_tec.templates.api.read", "prorrogas_tec.templates.api.upload"]`.
    - `estudiante() -> User`: rol `"student"`, sin permisos de plantillas, con `control_number` `"99xxxxxx"`.

- [ ] **Step 1: Write the failing test**

```python
import pytest
from itcj2.apps.prorrogas_tec.documents.catalog import default_template_path
from itcj2.apps.prorrogas_tec.services.docx_fill import find_placeholders
from itcj2.core.utils.docx_pdf import PdfConversionError
from itcj2.core.utils.timezone import db_now

API = "/api/prorrogas/v2/templates"
RECHAZO_OK = ("{{nombre}}", "{{no_control}}", "{{motivo_rechazo}}")
ANIO = 2090  # sin plantillas reales en la BD de dev (ver test_template_service.py)

def _post(c, data, filename="rechazo.docx", doc_type="carta_rechazo", anio=ANIO):
    return c.post(API, data={"doc_type": doc_type, "anio": str(anio)}, files={"archivo": (filename, data)})

def test_anonimo_recibe_401(client):
    assert client.get(API).status_code == 401

def test_estudiante_recibe_403(client_as, estudiante):
    assert client_as(estudiante).get(API).status_code == 403

def test_lista_seis_tipos_y_el_anio_actual(client_as, secretaria):
    body = client_as(secretaria).get(API).json()
    assert [t["code"] for t in body["tipos"]][0] == "formato_solicitud" and len(body["tipos"]) == 6
    assert db_now().year in [a["anio"] for a in body["anios"]]
    for a in body["anios"]:
        assert len(a["plantillas"]) == 6
        assert {p["origen"] for p in a["plantillas"]} <= {"subida", "heredada", "sistema"}

def test_subir_la_vuelve_activa_para_su_anio(client_as, secretaria, docx_con):
    c = client_as(secretaria)
    r = _post(c, docx_con(*RECHAZO_OK))
    assert r.status_code == 201 and r.json()["placeholders"] == ["motivo_rechazo", "no_control", "nombre"]
    anio = next(a for a in c.get(API).json()["anios"] if a["anio"] == ANIO)
    rechazo = next(p for p in anio["plantillas"] if p["doc_type"] == "carta_rechazo")
    assert rechazo["origen"] == "subida" and rechazo["plantilla"]["id"] == r.json()["id"]

@pytest.mark.parametrize("lines, filename, code", [
    ((), "x.docx", "docx_invalido"),                              # Review Focus 3 (bytes de PDF)
    (RECHAZO_OK + ("{{nombr}}",), "x.docx", "placeholders_desconocidos"),  # Review Focus 4
])
def test_subida_invalida_responde_400_con_codigo(client_as, secretaria, docx_con, lines, filename, code):
    data = b"%PDF-1.7" if not lines else docx_con(*lines)
    r = _post(client_as(secretaria), data, filename=filename)
    assert r.status_code == 400 and r.json()["error"] == code
    if code == "placeholders_desconocidos":
        assert r.json()["desconocidos"] == ["nombr"]

def test_estudiante_no_puede_subir(client_as, estudiante, docx_con):
    assert _post(client_as(estudiante), docx_con(*RECHAZO_OK)).status_code == 403

def test_descarga_subida_y_del_sistema(client_as, secretaria, docx_con):
    c = client_as(secretaria)
    data = docx_con(*RECHAZO_OK)
    tid = _post(c, data).json()["id"]
    r = c.get(f"{API}/{tid}/archivo")
    assert r.status_code == 200 and r.content == data and "wordprocessingml" in r.headers["content-type"]
    r = c.get(f"{API}/sistema/carta_rechazo/archivo")
    assert r.status_code == 200 and r.content == default_template_path("carta_rechazo").read_bytes()
    assert c.get(f"{API}/999999/archivo").status_code == 404

def test_vista_previa_devuelve_pdf_sin_marcadores(client_as, secretaria, monkeypatch):
    seen = {}
    def fake(data, *, kind):
        seen["placeholders"] = find_placeholders(data); seen["kind"] = kind; return b"%PDF-1.4 fake"
    monkeypatch.setattr("itcj2.core.utils.docx_pdf.docx_to_pdf", fake)
    r = client_as(secretaria).get(f"{API}/vista-previa/carta_compromiso_3.pdf?anio={ANIO}")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert seen == {"placeholders": set(), "kind": "prorrogas_documento"}

def test_vista_previa_sin_libreoffice_responde_503(client_as, secretaria, monkeypatch):  # Review Focus 5
    def boom(data, *, kind): raise PdfConversionError("LibreOffice no está instalado.")
    monkeypatch.setattr("itcj2.core.utils.docx_pdf.docx_to_pdf", boom)
    r = client_as(secretaria).get(f"{API}/vista-previa/carta_rechazo.pdf?anio={ANIO}")
    assert r.status_code == 503 and r.json()["error"] == "pdf_no_disponible"

def test_vista_previa_tipo_desconocido_404(client_as, secretaria):
    assert client_as(secretaria).get(f"{API}/vista-previa/otro.pdf").status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_templates_api.py -v`
Expected: FAIL. Las rutas no existen (404 donde se espera 401/403/200), o faltan fixtures.

- [ ] **Step 3: Implement the SQL, the CLI entry, `api/templates.py`, the router mount and the fixtures**

Run (siembra en dev): `docker compose -f docker/compose/docker-compose.dev.yml exec backend python -m itcj2.cli.main prorrogas init-prorrogas`
Expected: `OK: 04_insert_secretaria.sql` además de los 4 anteriores.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_templates_api.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit** (sin el `.sql`, que está en `.gitignore`)

```bash
git add itcj2/cli/prorrogas.py itcj2/apps/prorrogas_tec/api/templates.py itcj2/apps/prorrogas_tec/router.py tests/fastapi/prorrogas_tec/conftest.py tests/fastapi/prorrogas_tec/test_templates_api.py
git commit -m "feat(prorrogas): API de plantillas (listar, subir, descargar, vista previa)"
```

---

### Task 8: Vista de secretaría (barra + Documentos), aterrizaje y contrato de permisos

**Files:**
- Create: `itcj2/apps/prorrogas_tec/pages/secretaria.py`
- Modify: `itcj2/apps/prorrogas_tec/pages/router.py` (`include_router(secretaria_router)`)
- Modify: `itcj2/apps/prorrogas_tec/pages/landing.py:19-41`
- Create: `itcj2/apps/prorrogas_tec/templates/prorrogas_tec/secretaria/_base.html`, `documentos.html`, `proximamente.html`
- Create: `itcj2/apps/prorrogas_tec/static/css/secretaria/base.css`, `itcj2/apps/prorrogas_tec/static/js/secretaria/documentos.js`
- Create: `itcj2/apps/prorrogas_tec/docs/flows/secretaria_documentos.md`
- Modify: `itcj2/apps/prorrogas_tec/docs/README.md` ("Mapa de piezas": agrega `documents/`, `services/docx_fill.py`, `services/template_service.py`, `pages/secretaria.py`, `api/templates.py`)
- Test: `tests/fastapi/prorrogas_tec/test_secretaria_pages.py`, `tests/fastapi/prorrogas_tec/test_permissions_contract.py`

**Interfaces:**
- Consumes: los fixtures de Task 7 y `GET /api/prorrogas/v2/templates` con su forma.
- Produces:
  - **Constantes de `pages/secretaria.py`:**
    - `TABS = (("estadisticas", "Estadísticas"), ("solicitudes", "QR y solicitudes"), ("estudiantes", "Estudiantes"), ("documentos", "Documentos"))`
    - `_VIEW = ["prorrogas_tec.secretaria.page.view"]`
  - **Router:** `APIRouter(prefix="/secretaria", dependencies=[Depends(require_page_app("prorrogas_tec", perms=_VIEW))])`.
  - **Rutas:**
    - `GET ""` (`prorrogas_tec.pages.secretaria.home`) → 302 a `/prorrogas/secretaria/documentos`. Cuando haya Estadísticas, apuntará ahí.
    - `GET "/documentos"` (`…documentos`) → `render(request, "prorrogas_tec/secretaria/documentos.html", {"tabs": TABS, "active": "documentos"})`.
    - `GET "/{tab}"` (`…proximamente`) → `proximamente.html` para `estadisticas|solicitudes|estudiantes`. Cualquier otro valor: 404.
  - **Aterrizaje:** `landing.home` calcula el *conjunto* de roles del usuario (`user_roles_in_app`) y elige así:
    1. `"secretaria"` en roles → `/prorrogas/secretaria`
    2. si no, `"admin"` → `/prorrogas/admin/home`
    3. si no, `/prorrogas/student/home`
  - **`_base.html`** es una página completa: no extiende `prorrogas_tec/base.html`, que trae Bootstrap y otra barra.
    - Carga Google Fonts (Roboto 400/500/700, Open Sans 400/500/600/700, IBM Plex Mono 400/500) y `secretaria/base.css` con `url_for('static', filename='prorrogas_tec/css/secretaria/base.css')` y `?v={{ sv('prorrogas_tec', 'css/secretaria/base.css') }}`.
    - **Barra superior** (copiada de `TopNav`): 60 px de alto, fondo `#1A130E`.
      - A la izquierda, el ícono `core/images/app-icons/prorrogas_tec.webp` y "Prórrogas" en Roboto 500 17 px.
      - Al centro, las pestañas de `TABS` en Open Sans 500 15 px. La activa va en `#F7F7F2` con `box-shadow: inset 0 -4px 0 #F27340`; las demás, en `rgba(247,247,242,.58)`.
      - A la derecha, `current_user.name` y "Secretaría · Subdirección Académica".
    - Define las variables CSS de la paleta de Global Constraints.
  - **`documentos.html` + `documentos.js`**:
    - Título "Plantillas" y chips de año (de `anios`).
    - Para el año elegido, los 6 formatos con su etiqueta, una insignia de origen y tres acciones:
      - Insignias: "Subida · {fecha}", "Heredada de {año}" o "Plantilla del sistema".
      - **Vista previa**: abre `/api/prorrogas/v2/templates/vista-previa/{code}.pdf?anio={año}` en una pestaña nueva.
      - **Descargar**: baja la subida o la del sistema.
      - **Subir nueva**: abre un diálogo con tipo preseleccionado y archivo `.docx`, hace POST, recarga la lista y muestra un aviso. Si responde 400, muestra `message` y la lista de `desconocidos` o `faltantes`.
    - Botón principal **"Subir plantilla para {año}"**: el mismo diálogo, con selector de tipo.
    - Panel **"Marcadores de este formato"**: `obligatorios` en negritas y el resto de `permitidos`, cada uno como `{{codigo}}` listo para copiar.
  - **`proximamente.html`**: la misma barra con la pestaña activa y el texto "Esta sección llega en el siguiente plan."
  - **`test_permissions_contract.py`**:
    - Junta todo literal `str` (vía `ast`) de `itcj2/apps/prorrogas_tec/{api,pages}/**/*.py` que cumpla `^prorrogas_tec\.[a-z_]+\.(api|page)\.[a-z_.]+$`.
    - Comprueba que cada uno aparece entre comillas en algún `database/DML/prorrogas_tec/*.sql`.
    - Usa `pytest.mark.skipif` si la carpeta no existe, como en CI.

- [ ] **Step 1: Write the failing tests**

```python
# tests/fastapi/prorrogas_tec/test_secretaria_pages.py
import pytest

BASE = "/prorrogas/secretaria"

def test_anonimo_va_al_login(client):
    r = client.get(f"{BASE}/documentos", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/itcj/login"

def test_estudiante_recibe_403(client_as, estudiante):
    assert client_as(estudiante).get(f"{BASE}/documentos", follow_redirects=False).status_code == 403

def test_secretaria_ve_las_cuatro_pestanas_y_documentos(client_as, secretaria):
    r = client_as(secretaria).get(f"{BASE}/documentos")
    assert r.status_code == 200
    for label in ("Estadísticas", "QR y solicitudes", "Estudiantes", "Documentos", "Plantillas"):
        assert label in r.text

def test_raiz_de_secretaria_lleva_a_documentos(client_as, secretaria):
    r = client_as(secretaria).get(BASE, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == f"{BASE}/documentos"

@pytest.mark.parametrize("tab", ["estadisticas", "solicitudes", "estudiantes"])
def test_pestanas_pendientes_muestran_proximamente(client_as, secretaria, tab):
    r = client_as(secretaria).get(f"{BASE}/{tab}")
    assert r.status_code == 200 and "siguiente plan" in r.text

def test_pestana_desconocida_404(client_as, secretaria):
    assert client_as(secretaria).get(f"{BASE}/otra").status_code == 404

def test_aterrizaje_lleva_a_la_secretaria_a_su_vista(client_as, secretaria):
    r = client_as(secretaria).get("/prorrogas/", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == BASE
```

```python
# tests/fastapi/prorrogas_tec/test_permissions_contract.py
import ast, re
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parents[3]
APP = REPO / "itcj2" / "apps" / "prorrogas_tec"
DML = REPO / "database" / "DML" / "prorrogas_tec"
CODE_RE = re.compile(r"^prorrogas_tec\.[a-z_]+\.(api|page)\.[a-z_.]+$")

def _codes_in_code() -> set[str]:
    out = set()
    for f in [*APP.glob("api/**/*.py"), *APP.glob("pages/**/*.py")]:
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and CODE_RE.match(node.value):
                out.add(node.value)
    return out

@pytest.mark.skipif(not DML.exists(), reason="database/ esta en .gitignore (CI)")
def test_todo_permiso_que_exige_el_codigo_esta_sembrado():
    sembrados = set(re.findall(r"'(prorrogas_tec\.[a-z_.]+)'", "\n".join(p.read_text(encoding="utf-8") for p in DML.glob("*.sql"))))
    assert _codes_in_code() - sembrados == set()

def test_el_censo_no_esta_vacio():
    assert "prorrogas_tec.secretaria.page.view" in _codes_in_code()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTEST tests/fastapi/prorrogas_tec/test_secretaria_pages.py tests/fastapi/prorrogas_tec/test_permissions_contract.py -v`
Expected: FAIL. `/prorrogas/secretaria/*` responde 404 y el censo no encuentra `prorrogas_tec.secretaria.page.view`.

- [ ] **Step 3: Implement the pages, the templates, the static files, the landing change and the docs**

**`docs/flows/secretaria_documentos.md`** sigue `itcj2/apps/titulatec/docs/flows/_TEMPLATE.md`:

- objetivo
- tabla de actores, permisos y disparador
- ruta en la UI
- pasos: subir, vista previa y descargar, cada uno con su endpoint y su efecto en BD/disco
- caminos de error: los códigos de Task 6 y Task 7

- [ ] **Step 4: Run the whole app suite**

Run: `PYTEST tests/fastapi/prorrogas_tec -q`
Expected: todo PASS (las conversiones reales pueden saltarse si no hay LibreOffice).

Run: `PYTEST tests/fastapi/core/test_desktop_registry.py tests/fastapi/core/test_desktop_shell.py tests/fastapi/observability -q`
Expected: PASS (no se rompió el escritorio ni la observabilidad).

- [ ] **Step 5: Manual check in the browser**

1. Reasigna la cuenta de prueba `secretaria.prorrogas` al rol `secretaria`: corre el script de alta de la cuenta con `APP_ROLE = "secretaria"`.
2. Entra en http://localhost:8080 y abre Prórrogas. Debe llevarte a **Documentos** con la barra del diseño.
3. Sube un `.docx` con una errata: debe salir el mensaje con el marcador desconocido.
4. Sube uno válido: debe aparecer como "Subida".
5. Abre la vista previa: debe salir un PDF con "ESTUDIANTE DE EJEMPLO".

- [ ] **Step 6: Commit**

```bash
git add itcj2/apps/prorrogas_tec/pages itcj2/apps/prorrogas_tec/templates/prorrogas_tec/secretaria itcj2/apps/prorrogas_tec/static/css/secretaria itcj2/apps/prorrogas_tec/static/js/secretaria itcj2/apps/prorrogas_tec/docs tests/fastapi/prorrogas_tec/test_secretaria_pages.py tests/fastapi/prorrogas_tec/test_permissions_contract.py
git commit -m "feat(prorrogas): vista de secretaria con Documentos y contrato de permisos"
```

---

## Después de este plan

Los planes 2–4 (spec §14) se escriben sobre este mismo spec cuando el Plan 1 esté revisado:

- **Plan 2:** invitación, solicitud y decisión.
- **Plan 3:** Estudiantes y pagos.
- **Plan 4:** Estadísticas e histórico.

Lo que dejan listo las piezas de este plan:

- `formatting`, `docx_fill`, `docx_pdf`, `DOC_TYPES` y `TemplateService.resolve` son la base de la generación de documentos de los planes 2 y 3.
- El shell de la secretaría ya trae las cuatro pestañas.
