# Secretaría · Estadísticas

> **Objetivo:** que la secretaria vea, por semestre, cuántas solicitudes hubo, cuántas se aceptaron, cuánto se prorrogó y si los estudiantes cumplieron sus pagos.

| | |
|---|---|
| **Actores** | Secretaria (rol `secretaria`), admin de la app (rol `admin`) |
| **Permisos** | `prorrogas_tec.stats.api.read` (sembrado en `07_insert_plan4.sql`; lo trae `init-prorrogas`) |
| **Disparador** | Abrir la pestaña **Estadísticas** |
| **Precondiciones** | Solicitudes en la base (de la app o del histórico: ver [historico_excel.md](historico_excel.md)) |
| **Estado final** | Solo lectura: no escribe nada |

## Ruta en la app (UI)

Escritorio → Prórrogas → pestaña **Estadísticas** (`static/js/secretaria/estadisticas.js`; las gráficas usan Chart.js 4.4.0). Todas las rutas cuelgan de `/api/prorrogas/v2/estadisticas` y piden el permiso de arriba.

## Rutas

| Ruta | Qué devuelve | Service · método |
|---|---|---|
| `GET …/estadisticas/semestres` | `{items:[{label, period_id}], actual}`: semestres de core con solicitudes y etiquetas que solo vienen del Excel (`period_id` nulo), del más nuevo al más viejo; `actual` = el vigente si tiene solicitudes, si no el más nuevo | `StatsService.semestres` |
| `GET …/estadisticas?semestre=` | El resumen de abajo; sin `semestre` suma todos | `StatsService.resumen` |
| `GET …/estadisticas/detalle.csv?semestre=` | `estadisticas-prorrogas.csv` (UTF-8 con BOM, para Excel): el detalle por carrera | `StatsService.csv` |

`semestre` es la etiqueta (`enero – junio 2026`). Las solicitudes `cancelada` nunca cuentan. **Hoy** = `db_now().date()`.

## Qué significa cada número

- **Solicitudes por carrera** (`por_carrera`, dona): todas las solicitudes del semestre agrupadas por `program_name` (`Sin carrera` si falta).
- **Aceptadas / rechazadas** (`aceptacion`): `pct_aceptadas` = aceptadas / (aceptadas + rechazadas), redondeado; las pendientes no entran, y es nulo si no hay decididas. Las del Excel son aceptadas.
- **Línea de tiempo** (`linea`): aceptadas y rechazadas por fecha de creación, por semana (inicio en lunes) y por mes.
- **KPIs** (`kpis`):
  - `pendientes` y `pendiente_mas_vieja_dias` (hoy menos la fecha de la más vieja);
  - `respuesta_promedio_dias`: promedio de `decided_at − created_at` en días, un decimal; solo las que tienen decisión (las del Excel no);
  - `monto_total`: suma de `total_amount`;
  - `plazos_promedio`: promedio, sobre las aceptadas, de `requested_terms` (app) o del número de parcialidades vigentes (Excel);
  - `replanteadas`: solicitudes con alguna parcialidad sustituida.
- **Cumplimiento** (`cumplimiento`): sobre las parcialidades **vigentes** (no sustituidas) cuya fecha ya pasó (`vencimiento < hoy`):
  - `vencidas`: cuántas son;
  - `a_tiempo`: se cubrieron en o antes de su fecha;
  - `tarde`: se cubrieron después;
  - `sin_pago`: aún no se cubren;
  - `estudiantes_sin_pago`: solicitudes con al menos una `sin_pago`;
  - `period_id`: el del semestre cuando existe en core; nulo para "Todos" o semestres solo de Excel. Con él, "Ver en Estudiantes" abre `/prorrogas/secretaria/estudiantes?period_id={period_id}&filtro=con_adeudo`; Estudiantes solo acepta un `period_id` de su lista y un filtro conocido (si no, usa los de siempre). Sin él, el botón no aparece.
- **Histórico** (`incluye_historico`): verdadero si alguna solicitud del alcance viene del Excel. La UI agrega en Cumplimiento: "Los pagos del histórico se registraron en su fecha de vencimiento."
- **Detalle por carrera** (`por_carrera` y CSV): solicitudes, % de aceptación (vacío si no hay decididas), monto prorrogado, vencidas, pagó a tiempo, pagó tarde, sin pago. En la UI, "Pagó en la nueva fecha" es `a_tiempo / vencidas` (— si no hay vencidas).

## Regla de cobertura FIFO (`account.cobertura`)

Los recibos vigentes (no anulados) se ordenan por fecha de pago y se **acumulan**. Cada parcialidad, en orden de número, tiene una meta acumulada (la suma de sus montos y los de las anteriores). La parcialidad se cubre en la fecha del **primer recibo cuyo acumulado alcanza esa meta**; si ninguno la alcanza, queda sin cubrir (`None`).

Después `a_tiempo` es `cubierta <= vencimiento`, `tarde` es `cubierta > vencimiento` y `sin_pago` es `None`. Así un pago adelantado cubre las parcialidades siguientes y un pago de menos no cubre nada de la parcialidad hasta completarla. Es la misma regla que usa Estudiantes para el estado de cada parcialidad ([secretaria_estudiantes.md](secretaria_estudiantes.md)).

Para el histórico, cada parcialidad pagada trae un recibo fechado en su vencimiento, y esos recibos se aplican por FIFO como cualquier otro. Si una parcialidad no pagada (bandera 0) va antes de una pagada (1), el recibo cubre la anterior (que sale `tarde`) y la que sale `sin_pago` es la posterior; el saldo es el mismo. `excel-limpiar` cuenta cuántas solicitudes están así.

## Límite conocido

El cálculo es en Python por semestre (`# shortcut` en `stats_service.py`): pasar a SQL si un semestre supera ~2000 solicitudes.
