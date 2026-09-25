# Formato de las reglas de elegibilidad del SII

> Spec: `docs/superpowers/specs/2026-09-25-titulatec-elegibilidad-sii-design.md` §3.2.
> Código: `itcj2/apps/titulatec/services/sii/rules.py` (motor), `client.py` (conector).
> Ejemplo **sintético** completo y probado: `tests/fastapi/titulatec/sii_fixtures/`.

Las reglas **reales** NO viven en el repo: van en `database/SII/titulatec/` (gitignored, se
copian al servidor como el DML; la ruta la fija `TITULATEC_SII_RULES_DIR`). Este documento
describe el formato, que no es sensible.

```
database/SII/titulatec/
├── rules.toml          # declaración: consultas, reglas, credencial, identidad, hechos
├── queries/*.sql       # una consulta SELECT de solo lectura por archivo
└── fake_sii.json       # (opcional) filas del SII falso para dev/demo
```

Las reglas son **declarativas**: no hay código en estos archivos. Cambiar una regla es
editar el TOML/SQL, correr `titulatec sii-rules-validate` y `titulatec sii-check <control>`,
y subir `version` (queda registrada en cada consulta: así se sabe con qué reglas se decidió).

## `rules.toml`

```toml
version = "2026-10-01.1"          # obligatoria, ≤ 40 caracteres; se guarda en cada consulta

[[query]]                          # una o más
id = "alumno"                      # letras, dígitos y _
file = "queries/alumno.sql"        # relativa a la carpeta; no puede salir de ella
params = ["control_number"]        # en el orden de los `?` del SQL

[[rule]]                           # una o más; se evalúan en este orden
id = "existe"
query = "alumno"
criterion = { kind = "exists" }
message = "El número de control no existe en el SII."

[[rule]]
id = "creditos"
query = "alumno"
criterion = { kind = "gte", column = "creditos_aprobados", value_column = "creditos_carrera" }
message = "Le faltan créditos: {creditos_aprobados} de {creditos_carrera}."
ok_message = "Créditos completos ({creditos_aprobados})."   # opcional; default «Cumple.»

[credential]                       # opcional: de dónde sale el NIP
query = "nip"                      # consulta PROPIA (ver abajo)
column = "nip"

[identity]                         # opcional: datos para la cuenta y para comparar con el formulario
query = "alumno"
columns = { first_name = "nombre", last_name = "apellido_paterno", middle_name = "apellido_materno", entry_year = "anio_ingreso", program = "carrera" }

[facts]                            # opcional: lista BLANCA de columnas que se guardan para auditoría
query = "alumno"
columns = ["estatus", "creditos_aprobados", "creditos_carrera", "anio_ingreso"]
```

Claves desconocidas son **error** (atrapa typos como `mesage` o `critera`).

### Consultas

- Cada `[[query]]` se ejecuta **a lo más una vez** por evaluación, y la comparten todas sus
  reglas. Solo corren las que usa alguna regla, `[identity]` o `[facts]`.
- Parámetros **enlazados** con `?` (nunca interpolados). Permitidos: `control_number`,
  `curp`. El número de `?` debe coincidir con `params`.
- Las columnas se leen en **minúsculas** y el texto sin relleno a la derecha (los `CHAR` de
  Sybase). Escribe las columnas de las reglas en minúsculas; usa alias (`AS`) si hace falta.

### Criterios (`criterion.kind`, vocabulario cerrado)

| kind | Cumple si… | Claves |
|---|---|---|
| `exists` / `not_exists` | la consulta devuelve ≥ 1 / 0 filas | solo `kind` |
| `equals` / `not_equals` | `column` = / ≠ el valor | `column` + (`value` **o** `value_column`) |
| `gte` / `lte` | `column` ≥ / ≤ el valor | `column` + (`value` **o** `value_column`) |
| `in` / `not_in` | `column` está / no está en la lista | `column` + `value = [ … ]` |
| `truthy` / `falsy` | `column` es verdadero / falso | `column` |

- `mode = "all"` (default): la condición se cumple en **todas** las filas; `mode = "any"`:
  en **alguna**. No aplica a `exists`/`not_exists`.
- `value_column` compara contra otra columna de la **misma fila**.
- Números: se comparan como números aunque vengan como texto (`"260"` = `260`).
- Texto: sin espacios a los lados y **sin distinguir mayúsculas** (`"egresado"` = `"EGRESADO "`).
- Fechas: fecha contra fecha (`value = 2026-01-15` es una fecha TOML).
- Falso (`truthy`/`falsy`): `NULL`, `0`, `""`, `N`, `NO`, `F`, `FALSE`, `FALSO`. Todo lo
  demás es verdadero (`S`, `SI`, `1`, `X`…).

**Fail-closed** (nada se aprueba por omisión):

- Una comparación sobre **0 filas no cumple** (con `all` sería «verdad vacía»).
- **`NULL` no cumple ninguna comparación** (ni `not_equals`, como en SQL); sí es `falsy`.
- Una columna del criterio que la consulta **no devuelve**, o tipos que no se pueden comparar
  (texto contra número) → la evaluación entera queda en **`error`**, nunca `apt`.

### Mensajes

`message` es el motivo cuando la regla **falla**; `ok_message` (opcional) cuando cumple.
`{columna}` se sustituye con el valor de la **primera fila** de la consulta de la regla. Una
columna que no viene queda literal (`{columna}`) y sale como advertencia en `sii-check`.
Solo nombres simples: `{a.b}` o `{a[0]}` no se evalúan.

### Credencial (NIP)

- La consulta de `[credential]` **no corre al evaluar**: solo cuando se aprueba y hay que
  crear la cuenta (`RuleSet.fetch_credential`). El valor viaja en un `Secret` (`****`).
- Debe ser una consulta **propia**: el validador rechaza que alimente reglas, `[identity]` o
  `[facts]`, y que su columna aparezca en `[identity]`/`[facts]`.
- «Sin NIP» es **0 filas** o la columna en `NULL`/vacía. Si la consulta devuelve filas pero
  **no trae la columna declarada** en `column`, es un error de configuración
  (`SiiRulesError`, que nombra las columnas que sí vienen, nunca sus valores).
- Corre en modo **sensible**: si el SII la rechaza, el log y el error llevan solo el tipo y
  el SQLSTATE, nunca el texto del driver (un error de conversión, p. ej. con
  `CONVERT(INT, nip)`, lo trae con el valor de la fila).

### Veredicto

`apt` = todas las reglas cumplen · `not_apt` = alguna falla (cada falla trae su motivo) ·
`error` = el SII no respondió, la consulta es inválida o las reglas están mal escritas.
Solo `apt` puede aprobarse sola.

## `queries/*.sql`

Una sola sentencia de **solo lectura**. El validador (heurística; la defensa real es que el
usuario de BD del SII sea de solo lectura):

- ignora comentarios (`--`, `/* */`) y el contenido de `'…'`, `"…"` y `[…]`;
- exige que empiece con `SELECT` o `WITH`;
- rechaza `;` salvo uno al final;
- como en Sybase dos sentencias NO necesitan `;` entre ellas (`SELECT 1 DELETE FROM x`),
  rechaza palabras de escritura/DDL/control en cualquier parte: `INSERT`, `UPDATE`,
  `DELETE`, `MERGE`, `TRUNCATE`, `DROP`, `ALTER`, `CREATE`, `GRANT`, `REVOKE`, `EXEC`,
  `EXECUTE`, `CALL`, `INTO` (`SELECT … INTO` crea tablas), `SET`, `DECLARE`, `USE`, `BEGIN`,
  `COMMIT`, `ROLLBACK`, `WAITFOR`, `DUMP`, `LOAD`, `KILL`, `SHUTDOWN`, `DBCC`, etc.
  Si una columna de la tabla se llama así, escríbela entre corchetes (`[set]`) o comillas.

```sql
-- queries/alumno.sql  (ejemplo genérico; el esquema real lo define el área del SII)
SELECT a.nombre, a.apellido_paterno, a.apellido_materno, a.carrera,
       a.anio_ingreso, a.estatus, a.creditos_aprobados, a.creditos_carrera
  FROM alumnos a
 WHERE a.no_de_control = ?
```

## `fake_sii.json` (SII falso)

Con `TITULATEC_SII_BACKEND=fake` el conector lee `TITULATEC_SII_FAKE_FILE`:

```json
{
  "queries": {
    "alumno": {
      "20110001": [ {"nombre": "Ana", "estatus": "EGRESADO", "creditos_aprobados": 260, "creditos_carrera": 260} ],
      "20119999": {"error": "unavailable"}
    },
    "nip": { "20110001": [ {"nip": "0000"} ] }
  }
}
```

Llave = valor del parámetro (con varios: `valor1|valor2`). Lo que no aparece = 0 filas.
`{"error": "unavailable"}` simula el SII caído (reintentable) y `{"error": "query"}` una
consulta inválida.

## Comandos

```bash
python -m itcj2.cli.main titulatec sii-ping                        # ¿responde el SII?
python -m itcj2.cli.main titulatec sii-rules-validate [--dir RUTA] # ¿reglas válidas?
python -m itcj2.cli.main titulatec sii-check 20110001 [--cohort 3] # dry-run, NIP enmascarado
```

Ninguno escribe en la BD. `sii-check` sale con código 1 si el veredicto es `error` o si la
consulta de `[credential]` falla o no trae su columna.
