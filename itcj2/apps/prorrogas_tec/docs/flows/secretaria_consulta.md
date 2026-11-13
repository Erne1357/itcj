# Secretaría · Consulta (buscar cualquier solicitud y ver su historial)

> **Objetivo:** que la secretaria (o el admin de la app, de solo lectura) encuentre cualquier solicitud, de cualquier semestre y estado, y vea sus datos, documentos e historial sin tocar nada.

| | |
|---|---|
| **Actores** | Secretaria (rol `secretaria`), admin de la app (rol `admin`, solo lectura) |
| **Permisos** | Página: `prorrogas_tec.secretaria.page.consulta` · API: `prorrogas_tec.requests.api.read.all` |
| **Disparador** | Alguien pregunta por una solicitud que ya no está en la lista de pendientes (decidida, cancelada, cerrada o importada del Excel) |
| **Precondiciones** | `init-prorrogas` corrido con `08_insert_plan5.sql` (siembra el permiso de la pestaña y lo da a `secretaria` y `admin`) |
| **Estado final** | Ninguno: la pestaña solo lee |

## Ruta en la app (UI)

Escritorio → Prórrogas → `/prorrogas/secretaria/consulta` → pestaña **Consulta**. Es la cuarta pestaña, después de Estadísticas y antes de Documentos y Configuración.

## Pasos

| # | Actor | UI | Acción | Endpoint | Service · método | Efecto en BD |
|---|---|---|---|---|---|---|
| 1 | Secretaria | Filtros | Elige estado (`pendiente`, `aceptada`, `rechazada`, `cancelada`, `cerrada_sin_plan`) y semestre; escribe nombre o No. de control (con una pausa de 300 ms) | `GET /api/prorrogas/v2/solicitudes/todas?estado=&semestre=&q=&page=&per_page=` | `RequestService.search` | — |
| 2 | Secretaria | Tabla | Ve 25 por página, la más nueva primero: No. de control, nombre y folio, carrera, semestre y estado; pagina con Anterior / Siguiente | (misma llamada) | — | — |
| 3 | Secretaria | Clic o Enter en una fila | Abre el detalle: datos (folio, estado, semestre, plazos, creada, decidida, motivo, comentario de la decisión), documentos (con "firmado" si aplica) e historial | `GET …/solicitudes/{id}` | `RequestService.request_out`, `StudentsService.historial` | — |
| 4 | Secretaria | Documentos del detalle | Abre el PDF en otra pestaña | `GET …/solicitudes/{id}/documentos/{doc}.pdf` | `DocumentService.read_pdf` | — |

Notas:

- `search` incluye las solicitudes históricas y las que no tienen semestre de core (importadas del Excel); la lista de semestres sale de las etiquetas distintas que existen.
- `q` busca por contiene en número de control y nombre; `%` y `_` se toman como texto, no como comodines. Acentos: no se ignoran (ver P7).
- El detalle no trae al alumno: nombre, control y carrera salen de la fila que se pulsó.
- El historial es el mismo que ve el expediente de Estudiantes (`StudentsService.historial`, más nuevo primero); si un evento trae `motivo`, se muestra debajo.
- La ruta `/todas` va antes de `/{request_id}` en el router para que no se tome como un id.
- Todo texto del servidor entra a la pantalla con `textContent`.

## Caminos alternos / errores ❗

La UI muestra `message` sobre la tabla.

| Código | Cuándo | HTTP |
|---|---|---|
| `estado_invalido` | `estado` no es uno de los cinco | 400 |
| `no_encontrada` | La solicitud o el documento no existen | 404 |
| (sin código) | Sin el permiso de lectura: la pestaña ni aparece en la nav; la API responde "No tienes permiso para esta acción." | 403 |
| (sin conexión) | El fetch falla: "Sin conexión con el servidor." | — |

`page` menor que 1 se toma como 1 y `per_page` se limita a 100.

## Flujos relacionados

- Decidir las pendientes: [secretaria_solicitudes.md](secretaria_solicitudes.md).
- Plan, recibos y cierre sin plan: [secretaria_estudiantes.md](secretaria_estudiantes.md).
- Cifras: [secretaria_estadisticas.md](secretaria_estadisticas.md).
