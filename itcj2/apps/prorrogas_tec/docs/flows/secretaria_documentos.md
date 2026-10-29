# Secretaría · Documentos (plantillas de los formatos)

> **Objetivo:** que la secretaria mantenga las plantillas `.docx` que el sistema llena para generar las cartas de cada prórroga, por año, y pueda verlas en PDF antes de usarlas.

| | |
|---|---|
| **Actores** | Secretaria (rol `secretaria`), admin de la app (rol `admin`) |
| **Permisos** | Página: `prorrogas_tec.secretaria.page.view` · API: `prorrogas_tec.templates.api.read`, `prorrogas_tec.templates.api.upload` |
| **Disparador** | Cambian el formato oficial o los funcionarios que firman, o empieza un año nuevo |
| **Precondiciones** | `init-prorrogas` corrido (siembra `04_insert_secretaria.sql`); LibreOffice en el contenedor para la vista previa |
| **Estado final** | La plantilla subida es la que se usa para ese formato en ese año (y en los siguientes hasta que se suba otra) |

## Ruta en la app (UI)

Escritorio → Prórrogas → (aterrizaje por rol) → `/prorrogas/secretaria` → pestaña **Documentos**.

## Pasos

| # | Actor | UI | Acción | Endpoint | Service · método | Efecto en BD / disco |
|---|---|---|---|---|---|---|
| 1 | Secretaria | Documentos | Ver plantillas del año | `GET /api/prorrogas/v2/templates` | `TemplateService.years`, `.active` | — |
| 2 | Secretaria | Tarjeta → **Descargar** | Bajar la plantilla en uso para editarla en Word | `GET …/templates/{id}/archivo` o `…/templates/sistema/{tipo}/archivo` | `TemplateService.abs_path` | — |
| 3 | Secretaria | **Subir plantilla para {año}** | Subir el `.docx` editado | `POST /api/prorrogas/v2/templates` (`doc_type`, `anio`, `archivo`) | `TemplateService.upload` | Fila en `prorrogas_templates`; archivo en `instance/apps/prorrogas_tec/templates/{año}/{tipo}-{sha12}.docx` |
| 4 | Secretaria | Tarjeta → **Vista previa** | Ver el formato lleno con datos de ejemplo | `GET …/templates/vista-previa/{tipo}.pdf?anio=` | `TemplateService.resolve` → `fill_docx` → `docx_to_pdf` | — |

**Cuál plantilla se usa** para un formato y un año: la más reciente de ese año; si no hay, la más reciente del año anterior más cercano; si no hay, la plantilla del sistema (`documents/defaults/`).

## Caminos alternos / errores ❗

| Código | Cuándo | HTTP |
|---|---|---|
| `extension_invalida` | El archivo no termina en `.docx` | 400 |
| `archivo_muy_grande` | Pasa de 5 MB | 400 |
| `docx_invalido` | No es un Word válido (p. ej. un PDF renombrado) | 400 |
| `placeholders_desconocidos` | Trae un marcador que no existe (`{{nombr}}`); lista en `desconocidos` | 400 |
| `placeholders_faltantes` | Le falta un marcador obligatorio; lista en `faltantes` | 400 |
| `tipo_invalido` / `anio_invalido` | Formato inexistente / año fuera de 2020–2100 | 400 (404 en vista previa y descarga) |
| `pdf_no_disponible` | LibreOffice no está o falló en la vista previa | 503 |

## Flujos relacionados

- Spec: `docs/superpowers/specs/2026-10-29-prorrogas-modulo1-design.md` §6.
- Plantillas del sistema: `tools/prorrogas/build_default_templates.py`.
