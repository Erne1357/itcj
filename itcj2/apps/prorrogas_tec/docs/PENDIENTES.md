# Prórrogas · Pendientes

Lista viva de lo que le falta a la app. Lo más nuevo va primero.

---

# Módulo 1 (vista de secretaría) · pendientes vivos

Se actualiza conforme avanza el módulo. Spec: `docs/superpowers/specs/2026-10-29-prorrogas-modulo1-design.md`.
Cuando un punto se resuelve o deja de aplicar, se quita de la lista; el historial queda en git.

## Para ti (requieren a una persona)

| # | Pendiente | Por qué importa | Qué hacer |
|---|---|---|---|
| H2 | Conectar el buzón `agendatec@cdjuarez.tecnm.mx` para la app **Prórrogas** | Sin eso, una invitación manual no le llega a nadie: no tiene aviso en la plataforma (la pantalla avisa que el correo no salió). Solo las decisiones dejan además un aviso en la plataforma | `/itcj/config/email` → app Prórrogas → iniciar sesión con la cuenta (OAuth). En dev, Microsoft rechaza el `MS_CLIENT_SECRET` actual (`AADSTS7000215`, 2026-11-09), con cualquier cuenta: para probar, registrar una app propia con la URI `http://localhost:8080/itcj/config/email/auth/callback` y el permiso delegado `Mail.Send`, y poner su ID y secreto en el `.env` de dev. En producción, validar sus credenciales antes de conectar el buzón |
| H4 | Probar en un celular el recorrido del alumno | 2026-11-10: el botón de atrás de la barra y la firma (que "Borrar" ya no se selecciona solo) se probaron en un iPhone real. Del resto no hay registro de que se haya corrido en un teléfono: QR → iniciar sesión → regresar a unirse → **Aceptar y continuar** (que alcancen los 5 min del QR); trazar la firma con el dedo (y girar el teléfono); cada estado de *Mi prórroga* (sin solicitud, pendiente con cancelar, aceptada sin plan, carta por firmar con plan de pagos, rechazada); y en la secretaría, el modal con el PDF, Aceptar/Rechazar y que la lista se refresque sola | Usar los alumnos de *Solo de desarrollo* y abrir la secretaría por el túnel para que el QR llegue al teléfono. Liga de invitación en desarrollo: log del backend (`[PRORROGAS-LINK]`). Recargar con Ctrl+F5 |
| H8 | Probar en el navegador lo que falta del expediente | La lista, el detalle, los recibos y los avisos ya se recorrieron con datos ficticios (2026-11-09); no hay registro de que se haya probado armar o rehacer un plan, exportar adeudos ni firmar la carta en *Mi prórroga* | Con `secretaria.prueba` y un alumno de prueba; recargar con Ctrl+F5 |
| H12 | Revisar el archivo limpio e importar el histórico | Al 2026-10-29, ya con los arreglos de la revisión final, `instance/tmp/excel/limpio2.xlsx` trae 432 solicitudes y 774 parcialidades. El simulacro dio 392 que se crearían y 40 con error (no se importan hasta corregirlas). 173 se ligan a un semestre de core (ago–dic 2025 y ene–jun 2026) y 219 quedan sin semestre (ene–jun 2024, ago–dic 2024 y ene–jun 2025; solo cuentan para Estadísticas). 82 no tienen cuenta de estudiante. Las cifras cambian al corregir el archivo. Guía completa en `docs/flows/historico_excel.md` | 1) Usar `limpio2.xlsx`; `limpio.xlsx` es de antes de los arreglos y se puede borrar si no lo habías corregido. 2) Corregir a mano las filas con `problema` (la hoja Revisar es la guía) y quién pagó (`pagado`, 0 o 1; en el original la bandera vacía cuenta como pagada). Las 3 de modalidad mixta son EAD (decidido 2026-11-09): `ref` #35 va a `Ing. Industrial EAD`; #36 y #58, a `Ing. Gestión Empresarial EAD`. Vaciar `problema` en cada fila corregida, sin tocar `ref`. Las de `dato sin interpretar` se borran. 3) En desarrollo ya se importaron las 392 sin problema (2026-10-29); al terminar de corregir, volver a correr `import-excel` con `--dry-run` y luego sin él (las ya importadas se saltan, así que una corrección en esas 392 no llega a desarrollo: primero hay que borrar las `origin='excel'` de desarrollo). 4) En producción: `alembic -c migrations/alembic.ini upgrade head` (migración `pr20261101a`), copiar `database/DML/prorrogas_tec/07_insert_plan4.sql`, correr `init-prorrogas` y luego `import-excel` con el archivo ya revisado |
| H14 | Probar en el navegador lo del Plan 4 | Nadie ha visto en un navegador la pestaña Estadísticas (gráficas, cumplimiento, CSV, "Ver en Estudiantes") ni el expediente de una solicitud importada (recibos "Histórico", solo lectura si no tiene semestre) | El histórico ya está importado en desarrollo; recargar con Ctrl+F5 |
| H23 | Antes de llevar el Plan 5 a producción (2026-11-09) | Sin esto no existen las columnas y permisos nuevos, la tarea de recordatorios ni las fuentes de las cartas | En el servidor: copiar toda `database/DML/prorrogas_tec/` (está fuera de git e `init-prorrogas` se detiene si falta un archivo del 00 al 09), correr `alembic -c migrations/alembic.ini upgrade head` (migración `pr20261109a`), correr `init-prorrogas` y reconstruir la imagen del backend (fuentes, 7d24b433). Antes de la migración, contar los duplicados de `origin='app'` por `(student_id, period_id)`: la regla vieja permitía otra solicitud tras cancelar y el índice nuevo fallaría |
| H24 | Comparar el acomodo de las cartas con las fuentes nuevas (2026-11-09) | La imagen ahora trae Noto Sans y Montserrat: las cartas pueden acomodarse distinto. Lo más delicado: la firma del estudiante sobre su nombre no debe desalinear la columna del Director en las cartas compromiso | Generar una carta de cada tipo con datos de ejemplo y comparar con las de antes (`instance/tmp/preview/`). Si algo se ve mal, corregir el `.docx` en `documents/defaults/` con Word |
| H25 | Recordatorios automáticos: dev apagado, producción activo (2026-11-09) | La tarea `prorrogas.payment_reminders` (5, 1 y 0 días, d55b40bd) quedó con `is_active=false` en `core_periodic_tasks` en dev; la semilla la deja activa en producción. Si en dev se conecta el buzón (H2) y se activa, enviaría correos reales | Dejarla apagada en dev; en producción confirmar que está activa tras `init-prorrogas` |
| H26 | Reiniciar el worker de Celery (2026-11-09) | El worker solo registra las tareas al arrancar; sin reinicio no conoce `prorrogas.payment_reminders` | Reiniciar el worker (y el beat si corre aparte) después de reconstruir la imagen |
| H27 | Antes de llevar Caja a producción (2026-11-09) | Sin esto no existen las columnas, el rol ni los permisos de Caja. `init-prorrogas` aplica la semilla y crea el rol `caja`; desde ese momento la secretaria ya no cobra, y hasta asignar el rol nadie puede cobrar salvo el admin global | En el servidor: copiar `database/DML/prorrogas_tec/09_insert_caja.sql` (está fuera de git); `alembic upgrade head` (`pr20261109b`); correr `init-prorrogas` en una ventana sin cobros; y asignar el rol `caja` a la persona de Caja de inmediato |
| H28 | Medir en producción el presupuesto de métricas (2026-11-10; tope subido a 23.300 sin medir el 2026-11-13) | Cada ruta (método + dirección) le cuesta 20 series a Prometheus (14 de tiempos de respuesta y 6 de códigos HTTP), y el disco de Prometheus es uno solo para todo el monitoreo: si ITCJ se pasa, se pierde historia de Postgres, Redis y los servidores. Por eso `tests/fastapi/observability/test_cardinalidad.py::test_projected_series_fit_the_budget` pone un tope de 20.000. Con Prórrogas hay 916 rutas → 20.104 series: se pasa por 104 (unas 6 rutas). Prórrogas trae unas 58 rutas (~1.160 series); sin ellas, ~18.950. Es una proyección de peor caso (cada ruta con 6 códigos distintos). En CI, ya mezclado con `main`, dio 924 rutas → 20.264. Para el merge se subió `MAX_SERIES_PER_TARGET` a 23.300 (2026-11-13) sin medir: falta confirmar que el disco de Prometheus lo aguanta | En orden, según el propio test: 1) medir en el Prometheus de producción las series reales de ITCJ (`count({__name__=~"itcj_.*"})` y `prometheus_tsdb_head_series`); 2) si hay holgura de disco (`df -h`), subir `--storage.tsdb.retention.size` en `platform/docker-compose.yml` y luego `MAX_SERIES_PER_TARGET`; 3) solo al final, recortar `DURATION_BUCKETS`. Nunca agrupar las rutas por app |
| H22 | Rol Jefe de solo lectura (2026-11-09) | Se pospuso por decisión tuya. El Plan 5 deja al `admin` de la app en solo lectura, pero no crea el rol `jefe` ni lo liga a puestos; Director, Subdirector Académico y Subdirectores siguen sin un acceso de consulta | Al retomarlo: crear `jefe` con los permisos de lectura del `admin`, confirmar los puestos (candidatos: `director`, `head_sub_academic`, `head_sub_planning`, `subdirector_admin_services`) y agregarlo a `_ROLE_HOME` |

## Técnicos (diferidos de la revisión final del Plan 1, 2026-10-29)

| # | Pendiente | Efecto | Arreglo propuesto |
|---|---|---|---|
| T1 | Documentos no ofrece el año siguiente, y el año que se selecciona por omisión es el más nuevo, no el actual | En diciembre no se puede preparar el membrete del año que entra desde la pantalla (la API sí lo acepta) | `TemplateService.years` incluye `año actual + 1`; `documentos.js` selecciona el año actual |
| T2 | Si el archivo de una plantilla falta en disco, descargarla, verla o generar con ella da 500 | Pasa tras una restauración o un borrado manual de `instance/` | Mapear `FileNotFoundError` a 404 `plantilla_no_encontrada` y registrarlo en el log |
| T3 | No hay tope de descompresión al abrir un `.docx` subido | Un `.docx` de 5 MB puede crecer a gigas en memoria (solo lo suben roles de confianza) | Sumar `ZipFile(...).infolist()` y rechazar si pasa de un tope antes de `docx.Document()` |
| T4 | `InvalidDocx` solo cubre abrir el archivo; un error al recorrerlo da 500 al subir | Un `.docx` raro (p. ej. un encabezado que apunta a una parte que no existe) da error genérico | Envolver todo el escaneo de `find_placeholders` / `find_malformed` |
| T6 | Las plantillas del sistema conservan en sus metadatos (`docProps/core.xml`) los nombres "olivia" e "Iliana Esmeralda Sagarnaga Razcón" | Nombres de personal dentro de archivos del repo | El builder también limpia `author` y `last_modified_by`; regenerar y commitear los 6 `.docx` |
| T7 | Vista previa con `anio=0` usa el año actual en vez de rechazarlo | Menor | `if anio is None` en `api/templates.py` |
| T8 | Detalles: el ejemplo `{{así}}` de la página Documentos no es un marcador válido; el docstring de `fill_docx` sobre la firma vacía es impreciso; la lista de marcadores solo se ve en el diálogo de subida | Cosmético / claridad | Cambiar el ejemplo por `{{nombre}}`, corregir el docstring, mostrar los marcadores también en cada tarjeta |

## Técnicos (diferidos de las revisiones del Plan 2, 2026-10-29)

Detalle de cada uno en el ledger del Plan 2 (`.superpowers/sdd/2026-10-29-prorrogas-plan2-invitacion-solicitud-decision/progress.md`, no versionado).

| # | Pendiente | Efecto | Arreglo propuesto |
|---|---|---|---|
| D2 | Si `grant_role` choca por una carrera (IntegrityError), su rollback interno descarta la unión mientras `join()` responde éxito | Raro; el estudiante tendría que escanear otra vez | Atrapar la carrera antes de llamar `grant_role`, o volver a verificar después |
| D3 | `_usable(lock=True)` sin `populate_existing()`; `consume_invitation` hace `db.rollback()` dentro del servicio | Una invitación ya cargada podría consumirse dos veces en una transacción; el llamador pierde trabajo pendiente | `populate_existing()` y lanzar sin rollback |
| D5 | Los tokens viajan en la URL (logs de acceso) y las páginas de unirse no mandan `Cache-Control: no-store` | Un token puede quedar en un log o en la caché del navegador | Encabezado `no-store` en `/prorrogas/unirse*`; filtrar `t=` del log de acceso |
| D7 | Un PDF puede quedar huérfano en disco si falla la imagen de la firma o el flush después de escribirlo | Archivo sin fila; la ruta es determinista y la versión la protege la BD | Escribir el PDF al final, o borrar en el error |
| D8 | `ProrrogaJoin.user_id` y `via` aceptan NULL | Una fila sin dueño pasaría el CHECK | `nullable=False` en una migración |
| D9 | `institutional_email` lanza `ValueError` con un control inválido; un `doc_type` desconocido da `KeyError` en `build_values`; `control_number` no pasa por `clean_text` | Errores de programación con 500 en vez de `ServiceError` | Validar y lanzar `ServiceError` |
| D10 | Bajar la base más allá de `p1r2o3r4g001` falla (`drop_index` de tablas que `pr20261030a` ya borró) | Solo afecta un downgrade completo | `DROP TABLE IF EXISTS … CASCADE` en ese downgrade, o documentarlo |
| D14 | La lista de pendientes hace una consulta por fila (`DocumentService.current`) | Bien para decenas; lento con cientos | Una sola consulta de los `formato_solicitud` vigentes |
| D15 | `lookup` muestra el nombre como nombre-paterno-materno | Solo visual | Orden oficial |
| D16 | El README de la app todavía describe el modelo de datos y la instalación del fork | Documentación engañosa | Reescribir esas secciones |
| D17 | Detalles de código: líneas en blanco sueltas en `ENDPOINT_MAP` (`itcj2/templates.py`); `pages/router.py` sin salto final; `_AVISOS[kind]` fuera del `try` en `notify`; un `DOMAIN` con `/` final duplicaría la diagonal | Cosmético / frágil | Uno por uno, cuando se toque el archivo |
| D18 | Prórrogas no tiene pruebas de navegador | QR, firma, modal y refresco solo se han revisado a mano o leyendo el código. El repo ya tiene Playwright en `tests/e2e/` para otras apps | Ligado a H4; agregar `tests/e2e/prorrogas_tec/` |
| D19 | Huecos de prueba: QR sin sesión con token vencido; segundo escaneo; LibreOffice real con imagen de firma; log `[PRORROGAS-LINK]`; escape HTML del correo; error de Graph; PDF de otra solicitud → 404; la lista excluye resueltas; el estudiante recibe 403 en lista/detalle/PDF | Regresiones sin red | Agregarlas al tocar cada módulo |
| D20 | Dos huecos de tiempo en `solicitudes.js`: si la pestaña se oculta con una regeneración del QR en vuelo, el éxito vuelve a armar el temporizador; una respuesta tardía de la lista puede regresar un momento una fila ya decidida | Se corrigen solos en el siguiente refresco | Revisar `document.hidden` antes de re-armar; descartar respuestas viejas con un contador |
| D21 | `normalize_control` trata `L12345678` y `12345678` como números distintos | Las cuentas se guardan sin la L: si la secretaria la escribe al invitar, la app responde que no hay cuenta y manda al alumno a Centro de Cómputo sin razón | Buscar las dos formas en `lookup`/`invite` |

## Técnicos (Plan 5, 2026-11-09)

| # | Pendiente | Efecto | Arreglo propuesto |
|---|---|---|---|
| R2 | Un recordatorio automático fallido no se reintenta hasta el siguiente umbral (2026-11-09) | El alumno puede quedarse sin el aviso de ese umbral; la secretaria ve el aviso de correo fallido en el expediente | Reintentar en la siguiente corrida si el último evento fue `correo_no_enviado` |
| R3 | Si el commit falla tras enviar un recordatorio, el correo puede duplicarse (2026-11-09) | Un aviso repetido en un caso raro | Registrar el envío antes del correo o aceptarlo |
| R5 | Un recibo viejo que cubre un pago a medias y es el último vigente no tiene botón Anular en Caja (2026-11-09) | Solo pasa con capturas anteriores a Caja o del Excel; Caja no puede corregirlo desde su pantalla | Si aparece, mostrar `Anular` también en la fila parcial |

## Técnicos (Plan 6)

| # | Pendiente | Efecto | Arreglo propuesto |
|---|---|---|---|
| C1 | Un recibo que cubrió dos pagos: al anularlo el aviso solo menciona el último (2026-11-09) | Solo afecta capturas viejas | Mencionar los dos pagos en el aviso |
| C2 | Filas históricas ya pagadas muestran "Falta subir recibo" para siempre (2026-11-09) | La spec no distingue histórico | Decidido (2026-11-09): distinguir el origen `excel` en la spec y en Caja |
| C3 | Esc y clic en el fondo cierran el modal de Caja y pierden un formulario a medias, igual que el canvas (2026-11-09) | Se pierde lo tecleado | Confirmar antes de cerrar si hay un formulario abierto |
| C4 | Rehacer el plan tras anular el único recibo deja el escaneo en la parcialidad reemplazada, sin verse (2026-11-09) | El recibo subido no aparece en el plan nuevo | Reasignar el escaneo a la parcialidad nueva o avisar |

## Técnicos (diferidos de las revisiones del Plan 3, 2026-10-29)

Detalle en el ledger del Plan 3 (`.superpowers/sdd/2026-10-29-prorrogas-plan3-estudiantes-pagos/progress.md`, no versionado).

| # | Pendiente | Efecto | Arreglo propuesto |
|---|---|---|---|
| P1 | `POST /estudiantes/{id}/plan` valida los montos antes de buscar la solicitud | Un monto malo para una solicitud que no existe da 400 en vez de 404/409 | Pasar los montos crudos al servicio, que ya valida en orden |
| P2 | `/estudiantes/reparto` puede sugerir una parcialidad de $0 si el total tiene menos pesos que parcialidades | Solo la sugerencia; confirmar la rechaza | `plazos_invalidos` cuando total < n |
| P3 | Huecos de prueba del plan: `monto_invalido` en el servicio, 403 de `/reparto` | Regresiones sin red | Agregarlas en `test_plan.py` |
| P4 | Huecos de prueba de recibos: `no_aceptada`, `motivo_requerido`, recibo igual al saldo, fecha anterior a la solicitud, el respaldo por `IntegrityError` | Regresiones sin red | Agregarlas en `test_payments.py` |
| P5 | Firma: las pruebas no revisan `template_id`, el evento `documento_firmado` ni la fila de firma; faltan `no_firmable`, documento de otra solicitud y recibos anulados en `/estado`; `sign()` depende del candado de quien la llama (falta decirlo en el docstring); `/estado` repite consultas | Regresiones sin red; poca carga | Pruebas y una línea de docstring |
| P6 | La exportación de adeudos no toma candado; faltan pruebas de 24 h exactas, 403 de recordar/desbloqueo y del Excel (formato de dinero, fecha, fila vacía, A2/A5) | Dos exportaciones a la vez: gana la última marca | Candado por fila o aceptar; agregar pruebas |
| P7 | Búsqueda de estudiantes: `%` y `_` funcionan como comodines y no ignora acentos (PEÑA ≠ pena) | Solo búsquedas raras de la secretaria | `ilike(..., escape="\\")` y `unaccent` si hace falta |
| P8 | Pestaña Estudiantes: la fila es un `div role=button` con un botón adentro; el foco no entra al panel al abrirlo; `filename*=` no se lee; lo tecleado durante el reparto se sobrescribe; con base ≤ 0 Confirmar queda activo; `cents()` y `pesos()` usan `parseFloat`; el selector queda en blanco si `actual` no está en la lista | Accesibilidad y detalles visuales | Uno por uno al tocar `estudiantes.js` |
| P9 | *Mi prórroga*: el listener de `resize` de la firma nunca se quita; Firmar se reactiva un instante tras firmar; sin guarda si falta `cuenta`; el 409 al firmar solo usa `alert` | Fuga pequeña y detalles | `canvas.isConnected` → quitar el listener; no reactivar tras éxito |
| P10 | Detalles: línea larga en `test_schema.py`; docstring del CLI dice "12 permisos"; sin pruebas de los CHECK (número, monto, total); imports a media del archivo en pruebas; `test_periodos` débil; el aside "`# shortcut`" en `flows/secretaria_estudiantes.md` | Cosmético | Al tocar cada archivo |
| P12 | La decisión de la secretaria (Plan 2) no muestra adeudos de semestres anteriores | Puede aceptar a alguien que debe otra prórroga | Decidido (2026-11-09): mostrar el saldo pendiente en el modal de revisión |
| P13 | El candado de la solicitud se mantiene mientras LibreOffice genera la carta (plan y firma), igual que en `decide` | A esta escala no importa | Generar fuera del candado si un día hay carga |

## Técnicos (diferidos de las revisiones del Plan 4, 2026-10-29)

Detalle en el ledger del Plan 4 (`.superpowers/sdd/2026-10-29-prorrogas-plan4-historico-estadisticas/progress.md`, no versionado).

| # | Pendiente | Efecto | Arreglo propuesto |
|---|---|---|---|
| E1 | La `ref` depende del renglón del original, y no se rechazan dos solicitudes del mismo número de control en el mismo semestre | Si alguien inserta o borra renglones del original después de importar y vuelve a limpiar, reimportar duplica solicitudes (la guía lo advierte) | Rechazar en `import-excel` una solicitud `excel` cuyo (control, semestre) ya existe con otra `ref` |
| E2 | Normalizadores: `"1..500"` da 1,500.00 porque se tolera el grupo vacío; las fechas largas no exigen año ≥ 2000; las comas entre partes de una celda dan `importe ilegible`; un primer grupo con cero a la izquierda (`"0,500"`) se lee como 500; `origen` apunta a la columna de fecha también en problemas de importe o bandera | Casos raros (ninguno salió en el archivo real) | Uno por uno al tocar `normaliza.py` / `hojas.py` |
| E3 | Archivo limpio: `"1,550.00"` como texto en `monto` se rechaza sin decir que van solo dígitos; ordenar a mano por monto o nombre rechaza la `ref` sin explicar por qué | Mensaje confuso al revisar | Mensajes más claros en `_validar` |
| E4 | Estadísticas: una etiqueta como "Verano 2024" se ordena como segundo semestre; `pct` redondea al par; la carrera del CSV no se neutraliza contra `=` (los nombres solo los captura un admin). Huecos de prueba: vence hoy, mezcla de semestres, cuerpo del CSV, alcance vacío, cobertura en cero o desordenada | Menor | Al tocar `stats_service.py` |
| E5 | La prueba de `sin_semestre` del plan no revisa que no cambie nada | Menor | Una aserción |

## Técnicos (rediseño de los correos, 2026-11-10)

Diseño aprobado en el lienzo "Correos de Prórrogas" (artifact privado del usuario).

| # | Pendiente | Efecto | Arreglo propuesto |
|---|---|---|---|
| N2 | Nadie ha visto los correos nuevos (también "Tu pago quedó registrado" y "Terminaste de pagar", y el logo incrustado por `cid`) en un Outlook ni en un celular de verdad | Solo se revisaron en el lienzo; Outlook de escritorio pinta cuadradas las esquinas y puede mover espacios | Mandarse un recordatorio y una carta lista con el buzón conectado (H2) y revisarlos en Outlook web, escritorio y celular |

## Solo de desarrollo

- Cuenta de prueba `secretaria.prorrogas` / `Prorrogas#2026` (rol `secretaria`, más el mismo acceso que el usuario 7636 en las otras apps: `instance/tmp/mirror_access.py --apply`). Se recrea con `docker compose -f docker/compose/docker-compose.dev.yml exec backend python instance/tmp/create_test_secretary.py`. No va a producción.
- Cuentas de las pruebas de humo de los planes 2 y 3: usuarios 13152 (control `99999901`) y 31569 (control `B99189658`). Sus solicitudes ya no existen en la base.
- Personal y alumnos ficticios de Caja: `caja.prueba`, `secretaria.prueba`, `lector.prueba` y alumnos `99999903` a `99999907`. Los crea y borra `instance/tmp/caja_prueba.py` (`--crear`/`--borrar`); las claves están en `instance/tmp/usuarios_prueba.txt`.
- Alumno de prueba `99000001` (`instance/tmp/estudiante_prueba.py`): rompe `tests/fastapi/titulatec/test_enrollment_request_service.py::test_create_deja_la_solicitud_en_revision_sin_token_ni_correo[sin-cuenta]`, que da por hecho que ese número no tiene cuenta. Arreglo: cambiarle el control a `99999902` (es una escritura en la base).
- `docker/nginx/nginx.dev.conf` cachea `/static/prorrogas_tec/` una hora: tras cambiar CSS o JS hay que recargar con Ctrl+F5.
