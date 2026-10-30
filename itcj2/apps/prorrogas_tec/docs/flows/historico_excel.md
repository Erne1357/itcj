# Histórico del Excel (limpiar, revisar e importar)

> **Objetivo:** llevar a la base las prórrogas que la secretaria llevaba en el Excel (2024 a 2026) para que cuenten en Estadísticas y, cuando el semestre existe en core, aparezcan en Estudiantes.

| | |
|---|---|
| **Actores** | Quien administra el sistema (corre los comandos) y quien revisa el archivo limpio |
| **Permisos** | Ninguno: son comandos de consola, no rutas |
| **Disparador** | Hay un Excel histórico nuevo o corregido |
| **Precondiciones** | Migraciones al día; `init-prorrogas` corrido; el archivo original en `instance/tmp/excel/` (ignorado por git: trae nombres y números de control reales) |
| **Estado final** | Solicitudes `origin='excel'`, `aceptada`, con sus parcialidades y recibos de lo pagado |

Spec: §17 de `docs/superpowers/specs/2026-10-29-prorrogas-modulo1-design.md`. Esta página manda sobre §11.

## Los dos comandos

Siempre dentro del contenedor `backend` (o con `docker compose -f docker/compose/docker-compose.dev.yml exec backend` por delante). Ninguno imprime nombres ni números de control.

1. **Limpiar** (no toca la base ni el original):

   ```
   python -m itcj2.cli.main prorrogas excel-limpiar ORIGEN.xlsx --salida LIMPIO.xlsx
   ```

   Imprime `Solicitudes: N · Parcialidades: N · Con problema: N`, una línea `motivo: N` por cada motivo de problema y la ruta del archivo. Una hoja que no está en la tabla de hojas conocidas va completa a Revisar (`hoja desconocida`).

2. **Importar**:

   ```
   python -m itcj2.cli.main prorrogas import-excel LIMPIO.xlsx [--dry-run]
   ```

   Con `--dry-run` valida y cuenta sin escribir (el resumen empieza con `SIMULACRO —`). Imprime un `{ref}: {motivo}` por cada solicitud que no valida y el resumen `Creadas · Ya existían · Con error · Sin semestre en core · Sin cuenta`. Si falta la hoja o los encabezados no coinciden, no importa nada.

## El archivo limpio

**Parcialidades** (una fila por parcialidad). Encabezados exactos, en este orden:

| Columna | Qué lleva |
|---|---|
| `ref` | `{hoja}#{renglón}` de la primera fila del estudiante; agrupa las parcialidades de una solicitud y es la llave de idempotencia |
| `semestre` | Etiqueta como `semestre_label`: `enero – junio 2025` |
| `fecha_solicitud` | Fecha de la solicitud |
| `no_control` | `^[A-Za-z]?\d{8}$` |
| `nombre` | Nombre del estudiante |
| `carrera` | Nombre oficial de `core_programs` |
| `carrera_original` | Como venía en el Excel |
| `numero` | 1, 2, … sin huecos (máximo 6) |
| `vencimiento` | Fecha de la parcialidad |
| `monto` | Importe de la parcialidad |
| `pagado` | `1` pagada, `0` no |
| `problema` | Motivo si la fila no se pudo interpretar; vacío si está bien |
| `valor_original` | Texto original de la celda, para revisar |
| `origen` | Hoja, renglón y columna de donde salió |

**Revisar** (solo para consulta): `hoja`, `renglon`, `columna`, `valor`, `motivo`. Es la guía de lo que hay que corregir; el importador no la lee.

## Cómo se revisa

1. Abrir el `.xlsx` limpio y filtrar `Parcialidades` por `problema` no vacío; `Revisar` dice de dónde salió cada caso.
2. Corregir los valores en la fila (fecha, monto, carrera, número de control, `pagado`…).
3. **Vaciar `problema`** en cada fila corregida.
4. **Conservar `ref`** en todas las filas. Un renglón con datos pero sin `ref` hace que el importador rechace el archivo completo, porque no sabría a qué solicitud pertenece.
5. Volver a correr `import-excel --dry-run` hasta que no queden errores. Las solicitudes con error se omiten completas (nunca a medias); el resto se importa.

## Carreras: agregar una variante

La tabla está en `importacion/carreras.py` (`_TABLA`). Cada renglón es `(variantes escritas en el Excel, nombre oficial de core_programs)`. Comparar es sin acentos ni mayúsculas. Una variante nueva es agregar su texto a la tupla del renglón que corresponde (una línea) y volver a correr `excel-limpiar`.

## Qué se importa y qué no (§17.3)

- Cada solicitud nace con `origin='excel'`, `status='aceptada'`, `requested_terms` vacío, `total_amount` = suma de las parcialidades y `created_at` = `fecha_solicitud`.
- **Semestre:** se liga `period_id` solo si la etiqueta coincide con un semestre que ya existe en core. Si no, queda solo `period_label` y la solicitud cuenta únicamente para Estadísticas (no sale en Estudiantes ni en la lista de adeudos). No se crean semestres.
- `student_id` se liga por número de control cuando la cuenta existe; si no, queda vacío. Nombre, carrera y control se copian del archivo; el correo queda vacío.
- **Parcialidades:** hasta 6 para `origin='excel'` (los planes de la app siguen con máximo 3).
- **Recibos:** solo para las parcialidades pagadas; uno por parcialidad, `origin='excel'`, sin folio, con `paid_on` = vencimiento y el monto de la parcialidad. Lo no pagado no genera recibo.
- **Idempotente por `ref`:** una solicitud cuyo `ref` ya existe no se vuelve a crear (cuenta como "ya existía"); se puede correr de nuevo sin duplicar.
- Una solicitud de Excel sin `period_id` nunca rompe el expediente ni la lista (se trata como de solo lectura). Las que sí tienen semestre en core aceptan recibos tardíos y entran a la lista de adeudos; no se replantean.

## Ejemplo (datos ficticios)

Fila de `Parcialidades` ya corregida, de una solicitud en dos pagos:

| ref | semestre | fecha_solicitud | no_control | nombre | carrera | numero | vencimiento | monto | pagado | problema |
|---|---|---|---|---|---|---|---|---|---|---|
| `Hoja Demo#7` | `enero – junio 2026` | 12/01/2026 | 20000001 | Ana Ejemplo Pérez | Ing. Industrial | 1 | 20/01/2026 | $1,500.00 | 1 | |
| `Hoja Demo#7` | `enero – junio 2026` | 12/01/2026 | 20000001 | Ana Ejemplo Pérez | Ing. Industrial | 2 | 20/02/2026 | $1,500.00 | 0 | |

Resultado: una solicitud aceptada de $3,000.00 con dos parcialidades y un recibo de $1,500.00 fechado el 20/01/2026. Si el semestre existe en core, `import-excel` la cuenta como creada; si no, también suma a "Sin semestre en core".
