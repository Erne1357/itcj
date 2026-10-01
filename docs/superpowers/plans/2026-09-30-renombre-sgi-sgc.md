# Renombre adhoc → app `sgi`, módulo `sgc` — Plan de implementación

> **Para quien ejecute:** una tarea por commit, y cada tarea cierra con su comando de verificación.
> El plan da tareas, contratos, pistas y comandos; **no** trae el código escrito.

**Meta:** que la app de Calidad se llame **SGC** y viva dentro de la app registrada **`sgi`**, antes
de que ningún entorno tenga su esquema — hoy el renombre no tiene datos que migrar.

**Arquitectura:** UNA app registrada `sgi` (una fila en `core_apps`, un `/static/sgi/`, un bloque de
nginx) con `sgc`, y más adelante `buzon` y `encuestas`, como paquetes internos. Los permisos son
`sgi.sgc.*`. La separación entre módulos la hacen los permisos, no las apps.

**Rama:** `feature/sgc-integracion` (worktree `.claude/worktrees/feature+sgc-integracion`), sobre el
commit `e779c655` que ya integró la app en `main`.

**Spec / contexto previo:** `docs/superpowers/specs/2026-08-27-adhoc-auditoria-y-plan.md` (estado de
la app) y la memoria `project_sgi_suite_y_merge_sgc.md` (decisiones del ecosistema SGI).

## Constantes del renombre (valores exactos, no improvisar)

| Cosa | Antes | Después |
|---|---|---|
| Clave de app (`core_apps.key`) | `adhoc` | `sgi` |
| Nombre visible | `Calidad` | `SGC` (el ícono del escritorio dice `SGI`) |
| Paquete Python | `itcj2/apps/adhoc/` | `itcj2/apps/sgi/sgc/` |
| Router de API | `/api/adhoc/v2` | `/api/sgi/v2/sgc` |
| Páginas | `/adhoc/...` | `/sgi/sgc/...` |
| Permisos | `adhoc.{modulo}.{tipo}.{accion}` | `sgi.sgc.{modulo}.{tipo}.{accion}` |
| Tablas | `adhoc_*` (22) | `sgc_*` |
| Índices y constraints | los que llevan `adhoc` (53) | con `sgc` |
| Estáticos en disco | `apps/adhoc/static/` | `apps/sgi/static/sgc/` |
| Estáticos servidos | `/static/adhoc/...` | `/static/sgi/sgc/...` |
| Hoja y utils | `adhoc.css`, `adhoc-utils.js` | `sgi.css`, `sgi-utils.js` |
| Plantilla base | `templates/adhoc/base_adhoc.html` | `templates/sgi/base_sgi.html` |
| Caja del shell | `#adhoc-root` | `#sgi-root` |
| Namespace JS | `window.AdhocUtils` | `window.SgiUtils` |
| Tokens CSS | `--adhoc-*` | `--sgi-*` |
| Hooks de datos | `data-adhoc-*` | `data-sgi-*` |
| Uploads | `instance/apps/adhoc/` | `instance/apps/sgi/sgc/` |
| Settings | `ADHOC_UPLOAD_PATH`, `ADHOC_MAX_FILE_SIZE`, `ADHOC_ALLOWED_EXTENSIONS` | `SGC_*` |
| CLI | `itcj2/cli/adhoc.py`, grupo `adhoc` | `itcj2/cli/sgi.py`, grupo `sgi` |
| ETL | `scripts/adhoc_etl/` | `scripts/sgc_etl/` |
| Tests | `tests/fastapi/adhoc/`, `tests/e2e/adhoc/` | `tests/fastapi/sgc/`, `tests/e2e/sgc/` |
| DML nuevo | `database/DML/adhoc/` (se queda como histórico) | `database/DML/sgi/` |

**Las 3 reglas de sed** cubren el 100% del árbol versionado y son sensibles a mayúsculas:
`adhoc`→`sgc` (10562 ocurrencias), `Adhoc`→`Sgc` (2115), `ADHOC`→`SGC` (95). Las excepciones donde el
reemplazo es `sgi` y no `sgc` están en la tabla de arriba: clave de app, URLs, permisos, estáticos y
vocabulario del shell.

## Cómo se verifica cada tarea

La suite corre en un contenedor efímero contra una base construida como la de CI. Comando canónico
(desde el worktree; `--entrypoint python` es obligatorio o arranca el servidor, y `database/` necesita
su propio `-v` porque **Docker no sigue las junctions de Windows**):

```bash
MSYS_NO_PATHCONV=1 docker run --rm --network itcj_default --entrypoint python \
  -v "<worktree>:/app" -w /app -v "C:\Users\soporte\Desktop\ITCJ\database:/app/database:ro" \
  -e MIGRATE_DATABASE_URL="postgresql+psycopg2://postgres:password@postgres:5432/itcj_sgc_test" \
  -e DATABASE_URL="postgresql+psycopg2://postgres:password@postgres:5432/itcj_sgc_test" \
  -e REDIS_URL="redis://redis:6379/15" -e APP_ROLE=all \
  itcj-backend -m pytest <rutas> -q --tb=line -p no:cacheprovider
```

---

### Tarea 0 · Línea base

**Archivos:** ninguno.

- [ ] Correr la suite global y **anotar el número exacto** de pasan/saltados aquí. Sin ese número, al
      final no se puede demostrar que el renombre no perdió cobertura.
- [ ] Confirmar `git status` limpio y `git log -1` en `e779c655`.

**Cierre:** conteo de la línea base: `____ pasan / ____ saltados`.

---

### Tarea 1 · Mover el paquete Python

**Archivos:** `git mv itcj2/apps/adhoc itcj2/apps/sgi/sgc`; crear `itcj2/apps/sgi/__init__.py` (vacío);
`git mv itcj2/cli/adhoc.py itcj2/cli/sgi.py`.

**Contratos que consumen las tareas siguientes:**
- `itcj2.apps.sgi.sgc.router:sgc_router` — `APIRouter(prefix="/sgc")`, sin `/api`.
- `itcj2.apps.sgi.router:sgi_router` — `APIRouter(prefix="/api/sgi/v2")`, incluye `sgc_router`.
- `itcj2.apps.sgi.pages.router:sgi_pages_router` — `APIRouter(prefix="/sgi")`, incluye el de `sgc`
  con `prefix="/sgc"`.
- `itcj2.cli.sgi:sgi_cli` — grupo Click `sgi`, con `init-sgi`, `grant-incident-files`, `import-legacy`.

- [ ] Reescribir las **624** referencias dotted `itcj2.apps.adhoc` → `itcj2.apps.sgi.sgc`.
- [ ] Los sub-routers de páginas pierden el segmento `/adhoc` de sus rutas literales: ahora lo ponen
      los prefijos de los padres. Son rutas literales en 8 módulos de `pages/`.
- [ ] Verificar: `python -m compileall -q itcj2 asgi.py` y la suite del módulo en verde.

**Pista:** `pages/render.py` resuelve la carpeta de plantillas con `Path(__file__).parent`, así que la
mudanza no lo afecta; pero su `sv(path)` de un solo argumento usa la clave de manifest de la app, que
pasa a `sgi` con prefijo `sgc/` en la Tarea 4.

---

### Tarea 2 · Mover los tests y sus constantes de ruta

**Archivos:** `git mv tests/fastapi/adhoc tests/fastapi/sgc`; `git mv tests/e2e/adhoc tests/e2e/sgc`.

- [ ] Reescribir las **9 constantes `APP_ROOT`** que apuntan al layout plano
      (`parents[3] / "itcj2" / "apps" / "adhoc"`) → `"itcj2","apps","sgi","sgc"`. Están en
      `test_pages_base.py`, `test_pages_dashboard.py`, `test_pages_documents.py`,
      `test_pages_incidents_programs.py`, `test_pages_indicators.py`, `test_pages_panel.py`,
      `test_pages_reports.py` y `test_template_conventions.py`.
- [ ] Verificar: la suite del módulo en su ruta nueva, con el mismo conteo que la Tarea 0.

---

### Tarea 3 · Vocabulario del front y las 13 reglas de lint

**Archivos:** `apps/sgi/static/**`, `apps/sgi/templates/sgi/**`,
`tests/fastapi/sgc/test_template_conventions.py`.

- [ ] Renombrar la caja del shell, el namespace JS, los tokens, los hooks `data-*`, la hoja y el
      utils según la tabla de constantes. **El id de la caja y el namespace son contrato del shell:**
      si un `<script>` o `<section>` pierde su id estable, idiomorph reescribe el `src` y el módulo no
      corre (memoria `project_adhoc_shell_contract`).
- [ ] Actualizar las reglas del lint que fijan el vocabulario por nombre: `adhoc.css` (3 sitios),
      `var(--adhoc-z-`, `td[data-adhoc-cell="title"]`, `data-adhoc-page-info`, `js/adhoc-utils.js` y
      `#adhoc-root` con `hx-boost`.
- [ ] Actualizar el par `_ULTIMO_BUMP`: la huella cambia porque cambian nombres y contenido de los
      CSS/JS. El propio fallo imprime el par nuevo.
- [ ] Verificar: `pytest tests/fastapi/sgc/test_template_conventions.py -q` en verde.

---

### Tarea 4 · Estáticos: un solo árbol por app

**Archivos:** `apps/sgi/static/sgc/**` (mover desde `apps/sgi/sgc/static/`),
`docker/scripts/generate-static-manifest.sh`, `docker/nginx/nginx.{dev,prod}.conf`,
`docker/compose/docker-compose.{dev,prod}.yml`.

- [ ] Mover el árbol de estáticos del módulo a `apps/sgi/static/sgc/`, para que `buzon` y `encuestas`
      compartan el mismo bloque de nginx y la misma llave de manifest.
- [ ] Reescribir los href literales `/static/adhoc/...` → `/static/sgi/sgc/...` (las plantillas no
      usan `url_for`: usan ruta literal + `sv()`).
- [ ] Manifest: la llave pasa de `adhoc` a `sgi`, apuntando a `itcj2/apps/sgi/static`.
- [ ] nginx dev y prod: el `location /static/adhoc/` pasa a `/static/sgi/` con su `alias`.
- [ ] compose dev y prod: el volumen pasa a `../../itcj2/apps/sgi/static:/www/static/sgi:ro`.

**Trampa:** estos **4 archivos de deploy no los cubre ningún test**. Una location olvidada no da
error: `location /` proxea al backend, que no monta estáticos, y las 30 páginas salen **sin CSS ni JS
solo en el entorno donde falte la línea**. Verificación manual: `grep -c "static/sgi"` en los cuatro.

---

### Tarea 5 · Migraciones: las dos se reescriben, no se añade un rename

**Archivos:** `migrations/versions/23004eb05186_adhoc_initial_schema.py` y
`migrations/versions/b9b4d846ec2d_adhoc_acuses_*.py` (renombrar también los dos archivos).

- [ ] Reescribir los **22 `create_table`** y los **53 nombres** de índice/constraint.
- [ ] NO añadir una migración de rename: estas dos son una hoja que nada encadena y ninguna base las
      tiene aplicadas (verificado el 2026-09-30: dev tiene 0 tablas `adhoc_*`). Un rename en vivo
      serían ~186 `ALTER` contando el `downgrade` espejo.
- [ ] Mantener `down_revision = 'tt20260929a'` y el comentario que explica el repunte.
- [ ] Verificar en una base vacía: `alembic upgrade head`, luego `alembic downgrade -2`, y que
      `alembic heads` devuelva **una** cabeza.

---

### Tarea 6 · Permisos y DML nuevo

**Archivos:** crear `database/DML/sgi/init/*.sql` (gitignored, subcarpeta propia); `itcj2/cli/sgi.py`.

- [ ] Generar los seeders nuevos desde los de `database/DML/adhoc/init/`: los **85 códigos**
      `adhoc.x.y` → `sgi.sgc.x.y`, la fila de `core_apps` con `key='sgi'`, y la matriz rol→permiso
      (columna `perm_id`, no `permission_id`).
- [ ] **No tocar `database/DML/adhoc/`**: queda como histórico de lo que ya se cargó en algún entorno.
- [ ] Si alguna base llegó a tener la fila `adhoc`, el cambio es `UPDATE core_apps SET key='sgi'`,
      **nunca** un INSERT nuevo: el `ON CONFLICT (key) DO UPDATE` de los seeders crearía una app
      duplicada y dejaría los 85 permisos colgando del `app_id` viejo. Es el único punto donde el
      renombre rompe autorización en silencio.
- [ ] Verificar: `python -m itcj2.cli.main sgi init-sgi` contra un clon desechable y contar permisos:
      82 del init + 3 de `grant-incident-files` = 85.

---

### Tarea 7 · ETL: regenerar, no sedear

**Archivos:** `git mv scripts/adhoc_etl scripts/sgc_etl`; salida en `database/DML/sgi/legacy_import/`.

- [ ] Renombrar los prefijos de tabla en los builders y regenerar los 15 `.sql` desde
      `build/adhoc_legacy/` con `transform.py`.
- [ ] **Prohibido sedear `database/DML/adhoc/legacy_import/`**: los archivos 08, 11 y 12 tienen ~44
      ocurrencias en variantes de caso (`aDhOC`, `AdhoC`, …) **dentro de texto de hallazgos de
      auditoría ISO de 2017**. Es el nombre propio del sistema del proveedor en actas históricas: un
      sed las falsifica.
- [ ] `deploy_files.py`: destino `instance/apps/sgi/sgc`. Su `prune()` solo informa salvo `--prune`.
- [ ] Verificar con `python -m itcj2.cli.main sgi import-legacy --dry-run` contra un clon de dev. Ese
      camino ya está probado end-to-end y **aguanta PgBouncer** en modo transacción.

---

### Tarea 8 · Uploads en disco

**Archivos:** `itcj2/config.py` (los tres settings), `instance/apps/adhoc` → `instance/apps/sgi/sgc`.

- [ ] Mover los **535 MB** (1,080 archivos). Las filas guardan ruta **relativa**: no hay UPDATE de
      base que hacer.
- [ ] `instance/` está gitignored y el `git reset --hard` de `docker/scripts/deploy.sh` no lo toca: el
      movimiento se hace en el host, una vez por entorno.
- [ ] Verificar: abrir un adjunto de incidencia y uno de comentario en la app.

---

### Tarea 9 · Registro de la app en el core

**Archivos:** `itcj2/routers.py`, `itcj2/main.py`, `itcj2/observability/route.py`,
`itcj2/models/__init__.py`, `itcj2/cli/main.py`, `tests/fastapi/conftest.py`,
`tests/fastapi/core/test_seed_cubre_las_apps.py`, `itcj2/core/static/js/dashboard/dashboard.js`,
`itcj2/core/templates/core/dashboard/dashboard.html`.

- [ ] `main.py`: los tres mapas (`_APP_BY_PREFIX` con `/sgi`, `_APP_TEMPLATE`, `_APP_HOME`) **y** la
      rama de `_render_error_page`. Media entrada —string sin rama— no cae a la plantilla del core: el
      `except` se traga el `TemplateNotFound` y el error sale en **JSON crudo**.
- [ ] `conftest.py`: la clave sembrada pasa a `sgi`. El guard `test_seed_cubre_las_apps.py` falla si se
      olvida, porque recorre el código buscando `require_*("clave")`.
- [ ] `observability/route.py`: `APP_KEYS` cambia `adhoc` por `sgi`. **Ojo al techo de cardinalidad:**
      `test_cardinalidad.py` deja margen para ~148 pares ruta/método y este módulo aporta 91. El
      renombre no suma rutas, pero `buzon` y `encuestas` sí lo van a romper; la palanca es el tope,
      los buckets de duración o la retención, y es decisión aparte.
- [ ] `dashboard.js`: el item pasa a `{ id: 'sgi', name: 'SGI', icon: 'clipboard-check' }` y su
      `getAppConfig` apunta a `/sgi/`. Retirar la entrada muerta `app_prueba`, que tiene
      `http://localhost:8090` hardcodeado y en prod rompe.
- [ ] `/sgi/` sin módulo: por ahora redirige a `/sgi/sgc/`. El hub con tarjetas por módulo es trabajo
      aparte, cuando exista el segundo módulo.

---

### Tarea 10 · Cierre

- [ ] Suite global en **las dos bases**: la limpia estilo CI y un clon de dev. El arnés miente de tres
      formas distintas y una sola base no lo revela.
- [ ] Comparar con el conteo de la Tarea 0: mismo número de tests, ni uno perdido.
- [ ] `grep -rn adhoc itcj2 tests scripts migrations docker` debe devolver **cero**, salvo comentarios
      históricos que se decida conservar.
- [ ] E2E (`tests/e2e/sgc`, 12 specs) cuando la rama esté desplegada en el stack de :8080.
- [ ] `/graphify --update` más los dos scripts de seeders, o el grafo queda sin permisos ni roles.
- [ ] Actualizar `itcj2/apps/sgi/sgc/CLAUDE.md` (719 líneas, gitignored) y la memoria del proyecto.

## Lo que NO entra en este plan

- El hub `/sgi/` con tarjetas por módulo, y las tarjetas de módulo del panel móvil.
- Buzón de quejas y Encuestas de satisfacción: cada uno con su propio ciclo.
- El corte a producción: depende de volver a extraer el legado del SQL Server del proveedor.
