# Prórrogas · Plan 5: proceso completo, bloques 1 a 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cerrar 22 de los 28 puntos que le faltan a Prórrogas: reglas, avisos, referencia bancaria y roles. Cajas (22 a 26) queda para un plan propio cuando exista su diseño, y el rol Jefe (31) se pospuso.

**Architecture:** Casi todo vive en `itcj2/apps/prorrogas_tec`. Lo compartido se toca en tres sitios, solo agregando: adjunto opcional en `graph_send_mail`, una línea en el `include` de Celery y dos paquetes de fuentes en el Dockerfile. Hay una sola migración, al inicio, y un solo archivo de semillas que se aplica al final.

**Tech Stack:** FastAPI, SQLAlchemy 2, Postgres, Alembic, Celery con `DatabaseScheduler`, Jinja, JS sin framework, pytest contra el Postgres de dev dentro de un savepoint.

**Spec:** `reports/Faltantes del módulo de prórrogas.md` (auditoría en `bfa679a8`; sin commit, solo en el disco). Lo que un ejecutor necesita de ahí está copiado abajo y en cada tarea.

## Global Constraints

**Decisiones del usuario**
- Una sola solicitud por alumno y semestre, aunque se rechace o cancele. Cuentan también las del Excel de ese semestre.
- La invitación no crea cuentas. Liga, login con credenciales institucionales, pantalla Aceptar. Sin credenciales: Centro de Cómputo.
- Plan nuevo: 1 o 2 pagos. Solo se rehace si no tiene pagos ni parcialidades vencidas.
- Recordatorios automáticos a 5, 1 y 0 días; ninguno después del vencimiento; si el plan se confirma tarde, solo los que queden.
- Referencia bancaria: PDF. Se puede capturar el monto sin ella.
- Aceptada sin plan al terminar el semestre: la cierra la secretaria con motivo escrito; queda en el historial.
- Rol `admin` de la app: solo lectura. Admin global: escritura para emergencias. Los lectores no ven Documentos ni Configuración y no exportan la lista con bloqueo.
- El rol Jefe (punto 31) queda fuera de este plan por decisión del usuario: no crees el rol ni ligues puestos.
- Excel de impagos: fecha de exportación, No. de control, Nombre, Carrera, Monto debido (saldo total).

**Seguridad y datos**
- `database/`, `instance/tmp/excel/` e `instance/tmp/prorrogas_ejemplos/` tienen datos reales: nunca hagas grep sobre ellos ni los copies. Excluye `database/` de todo grep; abre las semillas solo por ruta exacta. Las pruebas usan datos inventados.
- Toda escritura en una base (`alembic upgrade`, `init-prorrogas`) y toda descarga (`docker compose build`) espera el visto bueno del usuario. Están marcadas **GATE**: detente y pregunta.
- No toques otras apps. `base.css` de secretaría es solo de Prórrogas y su bloque "Ancho completo" va al final. No cambies `itcj2/core/utils/docx_pdf.py` ni `sv()`.

**Git y comandos**
- Nunca `git add -A` ni `git add .`: agrega las rutas de **Files**. Nunca agregues `reports/`, `research_notes/`, los dotfiles del sandbox ni `database/`. No hagas push ni merge.
- **COMMIT** significa:
  ```bash
  git add -- <rutas de Files>
  GIT_AUTHOR_NAME=Deig0l GIT_AUTHOR_EMAIL=deigolsalazar@gmail.com GIT_COMMITTER_NAME=Deig0l GIT_COMMITTER_EMAIL=deigolsalazar@gmail.com git commit -m "<mensaje>" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
  ```
- **PYT \<ruta\>** significa (la palabra `docker` va primero, sin `cd` ni tuberías):
  ```bash
  docker compose -f /home/deigol/repos/itcj/docker/compose/docker-compose.dev.yml exec backend python -m pytest <ruta> -q --no-header --tb=short -p no:cacheprovider -W ignore
  ```
- Trabaja en `/home/deigol/repos/itcj`, rama `feature/core-prorrogas`, sin worktree: el contenedor monta ese directorio y `database/` no viaja con git.
- Rutas cortas: `APP/` = `itcj2/apps/prorrogas_tec/`; `T/` = `tests/fastapi/prorrogas_tec/`; `TPL/` = `APP/templates/prorrogas_tec/`; `JS/` = `APP/static/js/`.
- Copy en español, sin cambiar el tono de cada pantalla. Texto del servidor en JS, siempre con `textContent`.
- Sin pruebas automáticas de JS: cada cambio de pantalla termina con su prueba de página y su revisión en navegador en la Task 19.

## Review Focus

1. El alumno ya tiene una fila del Excel en el semestre, sin cuenta ligada: no puede pedir otra (Task 2).
2. El correo de un recordatorio no sale: no debe bloquear 24 horas el reintento (Task 6).
3. La tarea de recordatorios corre dos veces el mismo día: no repite (Task 11).
4. Un archivo con nombre `.pdf` que no es PDF, uno de más de 5 MB o la referencia de otro alumno: se rechaza (Task 12).
5. Un lector abre una pestaña que no le toca o llama directo a una API de escritura: 403 (Tasks 15 y 17).

---

## Bloque 0 · Base

### Task 1: Esquema en una sola migración

Una migración para todo el plan: así hay un solo GATE de base de datos.

**Files:**
- Create: `migrations/versions/pr20261109a_prorrogas_plan5.py`
- Modify: `APP/models/request.py`, `APP/models/plan.py`, `APP/services/request_service.py:106`
- Test: `T/test_schema.py`

**Interfaces:**
- Produces: estado `cerrada_sin_plan`; `ProrrogaRequest.reference_path: Text`, `.reference_uploaded_at: DateTime`; `ProrrogaInstallment.last_reminder_days: SmallInteger`; índice `uq_prorrogas_requests_semestre`.

- [ ] **Step 1: Pruebas.** En `test_schema.py` reemplaza `test_una_sola_solicitud_abierta_por_semestre` y borra `test_una_rechazada_no_cuenta_como_abierta`:

```python
def test_una_sola_solicitud_por_semestre(db_session, make_user, periodo):  # aunque la primera se rechazara
    u = make_user(control_number="99100001")
    db_session.add(_solicitud(u, periodo, status="rechazada"))
    db_session.flush()
    db_session.add(_solicitud(u, periodo))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_cerrada_sin_plan_es_un_estado_valido(db_session, make_user, periodo):
    db_session.add(_solicitud(make_user(control_number="99100004"), periodo, status="cerrada_sin_plan"))
    db_session.flush()


def test_columnas_del_plan_5():
    t = Base.metadata.tables
    assert {"reference_path", "reference_uploaded_at"} <= set(t["prorrogas_requests"].c.keys())
    assert "last_reminder_days" in t["prorrogas_installments"].c
```

- [ ] **Step 2:** `PYT T/test_schema.py`. Esperado: FALLAN las tres.
- [ ] **Step 3: Modelos.** `STATUSES` suma `"cerrada_sin_plan"` y el CHECK `ck_prorrogas_requests_status` también. El índice `uq_prorrogas_requests_abierta` se sustituye por `Index("uq_prorrogas_requests_semestre", "student_id", "period_id", unique=True, postgresql_where=text("origin = 'app'"))`. Agrega `reference_path = Column(Text)`, `reference_uploaded_at = Column(DateTime)` a la solicitud y `last_reminder_days = Column(SmallInteger)` a la parcialidad. En `request_service.py:106` cambia el nombre del índice comparado.
- [ ] **Step 4: Migración** (a mano, igual que `pr20261101a`): `revision="pr20261109a"`, `down_revision="pr20261108a"`. Upgrade: `drop_index` del viejo, `create_index` del nuevo, `drop_constraint` y `create_check_constraint` del estado, tres `add_column`. Downgrade inverso; su docstring advierte que falla si hay filas `cerrada_sin_plan` o dos solicitudes de un alumno en un semestre.
- [ ] **Step 5: GATE. Pide permiso y aplica.** Antes, verifica que no haya duplicados (el 2026-11-08 había 0):

```bash
docker compose -f /home/deigol/repos/itcj/docker/compose/docker-compose.dev.yml exec backend python -c "from sqlalchemy import text; from itcj2.database import SessionLocal; d=SessionLocal(); print(d.execute(text(\"select count(*) from (select student_id, period_id from prorrogas_requests where origin='app' and period_id is not null group by 1,2 having count(*)>1) t\")).scalar())"
docker compose -f /home/deigol/repos/itcj/docker/compose/docker-compose.dev.yml exec backend alembic -c migrations/alembic.ini upgrade head
```

Si el primer comando no imprime 0, detente y pregunta.

- [ ] **Step 6:** `PYT T/`. Esperado: todo pasa.
- [ ] **Step 7:** **COMMIT** `feat(prorrogas): esquema del Plan 5 (una solicitud por semestre, referencia, cierre y recordatorios)`

---

## Bloque 1 · Reglas

### Task 2: Una sola solicitud por semestre (punto 4)

**Files:**
- Modify: `APP/services/request_service.py`, `JS/estudiante/solicitud.js:73-75`, `JS/estudiante/mi_prorroga.js`, `TPL/estudiante/mi_prorroga.html`, `APP/docs/flows/estudiante_solicitud.md`
- Test: `T/test_student_requests.py`

**Interfaces:**
- Produces: `RequestService.access` devuelve el código `"ya_solicito"`, que sustituye a `"solicitud_abierta"`.

- [ ] **Step 1: Pruebas.** En `test_student_requests.py` borra `test_tras_cancelar_hay_que_unirse_otra_vez` y `test_union_mientras_estaba_pendiente_no_sirve_tras_cancelar`, cambia a `"ya_solicito"` las líneas 64, 141 y 192, y agrega:

```python
def test_tras_cancelar_ya_no_puede_pedir_otra(db_session, alumno_unido, make_program, firma_png):
    from itcj2.apps.prorrogas_tec.models.invitation import ProrrogaJoin
    from itcj2.core.utils.timezone import db_now
    prog = make_program("Ingeniería de Prueba", "licenciatura")
    req = _crear(db_session, alumno_unido, prog, firma_png)
    RequestService.cancel(db_session, req.id, alumno_unido.id)
    db_session.add(ProrrogaJoin(user_id=alumno_unido.id, via="qr", joined_at=db_now()))  # ni volviendo a unirse
    db_session.flush()
    with pytest.raises(ServiceError) as e:
        _crear(db_session, alumno_unido, prog, firma_png)
    assert e.value.code == "ya_solicito" and e.value.status == 409


def test_tras_rechazo_ya_no_puede_pedir_otra(db_session, alumno_unido, make_program, firma_png, secretaria, avisos):
    req = _crear(db_session, alumno_unido, make_program("Ingeniería de Prueba", "licenciatura"), firma_png)
    RequestService.decide(db_session, req.id, secretaria.id, aceptar=False, comentario="No procede")
    assert RequestService.access(db_session, alumno_unido.id)[1] == "ya_solicito"


def test_la_importada_del_excel_del_semestre_cuenta(db_session, alumno_unido, periodo_hoy, make_historica):  # Review Focus 1
    make_historica(periodo=periodo_hoy, control_number=alumno_unido.control_number)
    assert RequestService.access(db_session, alumno_unido.id)[1] == "ya_solicito"


def test_la_de_otro_semestre_no_cuenta(db_session, alumno_unido, periodo, make_historica):
    make_historica(periodo=periodo, control_number=alumno_unido.control_number)
    assert RequestService.access(db_session, alumno_unido.id)[1] is None
```

- [ ] **Step 2:** `PYT T/test_student_requests.py`. Esperado: FALLAN las nuevas.
- [ ] **Step 3: `access`.** Tras obtener la ventana: si existe una solicitud del `period.id` con `student_id == user_id` o con `origin == "excel"` y `control_number` igual al del usuario, devuelve `(period, "ya_solicito")`. Si no, `sin_acceso` depende solo de una unión dentro de la ventana; se quita el filtro por `ultima.updated_at`. `_ABIERTA` pasa a `_YA_SOLICITO = ("ya_solicito", "Ya usaste tu solicitud de este semestre.")`.
- [ ] **Step 4: Pantallas.**
  - `solicitud.js`: la última rama dice `"Ya usaste tu solicitud de este semestre."`.
  - `mi_prorroga.js`: borra la rama que agrega `mp-ahora` y deja la condición de `sin_acceso` como `d.motivo === "sin_acceso"`.
  - `mi_prorroga.html`: borra `<template id="mp-ahora">`.
  - Cancelar: `confirm("¿Cancelar esta solicitud? Ya no podrás pedir otra este semestre.")` y hint `"¿Ya no la necesitas? Puedes cancelarla mientras esté pendiente, pero ya no podrás pedir otra este semestre."`.
- [ ] **Step 5: Doc.** En `estudiante_solicitud.md`: fila `ya_solicito`, `sin_acceso` = "sin unión dentro del periodo" y precondición sin "posterior al último cambio".
- [ ] **Step 6:** `PYT T/`. Esperado: todo pasa.
- [ ] **Step 7:** **COMMIT** `feat(prorrogas): una sola solicitud por semestre, aunque se rechace o cancele`

### Task 3: La invitación no crea cuentas y pasa por Aceptar (puntos 7 y 8)

**Files:**
- Modify: `APP/services/invitation_service.py`, `APP/api/invitations.py`, `APP/pages/join.py`, `JS/secretaria/solicitudes.js`, `TPL/secretaria/solicitudes.html`, `APP/docs/flows/estudiante_solicitud.md`
- Delete: `TPL/estudiante/crea_nip.html`
- Test: `T/test_invitations.py`, `T/test_join_pages.py`

**Interfaces:**
- Produces: `invite(db, *, raw_control, email, actor_id, now=None) -> tuple[ProrrogaInvitation, str, bool]`; `invitation_service.SIN_NIP: str`.

- [ ] **Step 1: Pruebas de servicio.** En `test_invitations.py` borra `test_invitar_crea_cuenta_de_posgrado_sin_nip` y `test_nip_inicial`; `test_lookup_de_doctorado_sin_cuenta` afirma `not out["existe"] and out["requiere_correo"] and "requiere_datos" not in out`. Sustituye el parametrizado:

```python
@pytest.mark.parametrize("kwargs, code", [
    ({"raw_control": "D99200005", "email": "x@example.invalid"}, "sin_cuenta"),
    ({"raw_control": "123", "email": None}, "control_invalido"),
])
def test_invitaciones_invalidas(db_session, secretaria, enviar_correo, kwargs, code):
    with pytest.raises(ServiceError) as e:
        inv.invite(db_session, actor_id=secretaria.id, **kwargs)
    assert e.value.code == code


def test_invitar_sin_cuenta_manda_a_centro_de_computo(db_session, secretaria, enviar_correo):
    from itcj2.core.models.user import User
    with pytest.raises(ServiceError) as e:
        inv.invite(db_session, raw_control="D99200003", email="p@example.invalid", actor_id=secretaria.id)
    assert e.value.status == 404 and "Centro de Cómputo" in e.value.message
    assert db_session.query(User).filter_by(control_number="D99200003").first() is None and enviar_correo.calls == []


def test_doctorado_sin_correo_lo_pide(db_session, secretaria, make_user, enviar_correo):
    make_user(control_number="D99200004").email = ""
    with pytest.raises(ServiceError) as e:
        inv.invite(db_session, raw_control="D99200004", email=None, actor_id=secretaria.id)
    assert e.value.code == "correo_requerido"
```

- [ ] **Step 2: Pruebas de página.** En `test_join_pages.py` borra `test_invitacion_de_cuenta_nueva_pide_crear_nip_y_luego_login`, `test_nip_distinto_vuelve_a_mostrar_el_formulario`, `test_cuenta_creada_y_reinvitada_si_crea_nip` y `test_cuenta_existente_sin_nip_no_ve_crea_nip`. Agrega:

```python
def test_invitacion_con_sesion_pregunta_y_al_aceptar_une(client_as, secretaria, make_user, enviar_correo, db_session):
    u = make_user(control_number="99300011")
    _, token, _ = inv.invite(db_session, raw_control="99300011", email=None, actor_id=secretaria.id)
    c, url = client_as(u), f"/prorrogas/unirse/invitacion/{token}"
    r = c.get(url, follow_redirects=False)
    assert r.status_code == 200 and "Aceptar y continuar" in r.text and "99300011" in r.text
    assert db_session.query(ProrrogaJoin).filter_by(user_id=u.id).count() == 0  # ver la pregunta no une
    r = c.post(url, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/prorrogas/estudiante/solicitud"
    assert db_session.query(ProrrogaJoin).filter_by(user_id=u.id, via="invitacion").count() == 1


def test_cuenta_sin_nip_va_a_centro_de_computo(client, secretaria, make_user, enviar_correo, db_session):
    make_user(control_number="99300009")
    _, token, _ = inv.invite(db_session, raw_control="99300009", email=None, actor_id=secretaria.id)
    r = client.get(f"/prorrogas/unirse/invitacion/{token}", follow_redirects=False)
    assert r.status_code == 403 and "Centro de Cómputo" in r.text
```

- [ ] **Step 3:** `PYT T/test_invitations.py T/test_join_pages.py`. Esperado: FALLAN.
- [ ] **Step 4: Servicio.** `invite` con la firma de arriba; sin cuenta lanza `ServiceError("sin_cuenta", "No hay cuenta con ese número. El alumno debe acudir a Centro de Cómputo para que lo den de alta.", status=404)`. `lookup` deja de devolver `requiere_datos`. Borra `set_initial_nip`, `can_set_initial_nip`, `SIN_INVITACION_DE_ALTA`, `_NIP` y los imports que queden huérfanos. Agrega `SIN_NIP = "Tu cuenta todavía no tiene NIP. Acude a Centro de Cómputo para que te lo den."`. La columna `user_created` se queda (filas viejas).
- [ ] **Step 5: `join.py`.** Borra `_nip_form` y `unirse_crear_nip`.
  - `GET /invitacion/{token}`: valida; sin sesión y sin `password_hash`, `_error(request, inv.SIN_NIP, 403)`; sin sesión con NIP, `_login`; con otra cuenta, `_error(request, "Esta invitación es de otra cuenta.", 403)`; si no, `unirse_aceptar.html` con `token`, `nombre` y `control`.
  - `POST /invitacion/{token}` (nuevo `unirse_invitacion_aceptar`): sin sesión, `_login`; `inv.consume_invitation`; `_redirect(SOLICITUD)`.
- [ ] **Step 6: API y pantalla.** `InvitationIn` solo `control_number` y `correo`. En `solicitudes.html` borra `#invDatos`. En `solicitudes.js` borra `loadPrograms` y su llamada, y el bloque `requiere_datos`; sin cuenta: `"No hay cuenta con ese número: debe acudir a Centro de Cómputo."` y `$("invSend").disabled = !r.data.existe`.
- [ ] **Step 7: Doc.** En `estudiante_solicitud.md` quita las filas de NIP (líneas 56 y 57) y describe el paso Aceptar en 1b.
- [ ] **Step 8:** `PYT T/`. Esperado: todo pasa.
- [ ] **Step 9:** **COMMIT** `feat(prorrogas): la invitacion no crea cuentas y pasa por la pantalla Aceptar`

### Task 4: Tope de pagos, plan vencido y Excel (puntos 3, 27 y 28)

**Files:**
- Modify: `APP/services/formatting.py:20`, `APP/services/plan_service.py`, `APP/services/students_service.py:32-34,140,224-241`, `APP/docs/flows/secretaria_estudiantes.md`
- Test: `T/test_plan.py`, `T/test_students_api.py`, `T/test_students_actions.py`

**Interfaces:**
- Produces: `formatting.MAX_PAGOS_PLAN = 2`. `MAX_PAGOS` sigue en 3: lo usa `split_amount` para la muestra de `carta_compromiso_3` del catálogo.

- [ ] **Step 1: Pruebas.** En `test_plan.py` agrega `DOS = [(D("1825"), date(2091, 2, 1)), (D("1825"), date(2091, 4, 1))]` y úsalo donde `TRES` era un plan válido (`carta_compromiso_2`, `pago2_monto == "$1,825.00"`). `test_reparto_por_omision` usa `n=2` y `test_api_reparto` espera `["1825.00", "1825.00"]` con `n=2` y `plazos_invalidos` con `n=3`. Agrega:

```python
def test_plan_nuevo_no_admite_tres_pagos(db_session, aceptada, secretaria, avisos):
    with pytest.raises(ServiceError) as e:
        PlanService.confirm(db_session, aceptada.id, secretaria.id, total=D("3650"), parcialidades=TRES, now=date(2026, 11, 1))
    assert e.value.code == "plazos_invalidos"


def test_plan_con_pago_vencido_no_se_rehace(db_session, aceptada, secretaria, con_plan, avisos):
    con_plan(aceptada, [("1000.00", date(2026, 10, 1))])
    with pytest.raises(ServiceError) as e:
        PlanService.confirm(db_session, aceptada.id, secretaria.id, total=D("1000"),
                            parcialidades=[(D("1000"), date(2091, 2, 1))], now=date(2026, 11, 1))
    assert e.value.code == "con_vencidos" and e.value.status == 409
```

En `test_students_api.py`, dentro de `test_plan_editable_solo_sin_pagos_y_en_el_semestre`, el plan vence el `date(2091, 6, 20)` para que el 20 de junio siga editable. Agrega:

```python
def test_plan_vencido_no_es_editable(db_session, aceptada, con_plan):
    con_plan(aceptada, [("1000.00", date(2091, 2, 1))])
    assert StudentsService.expediente(db_session, aceptada.id, date(2091, 3, 1))["plan"]["editable"] is False
```

En `test_excel_de_adeudos_se_explica_solo` sustituye el assert de encabezados:

```python
    assert [c.value for c in ws[7]] == ["No. de control", "Nombre", "Carrera", "Monto debido"]
    fila = next(r for r in ws.iter_rows(min_row=8, values_only=True) if r[0] == aceptada.control_number)
    assert float(fila[3]) == 1300.0  # saldo total
```

- [ ] **Step 2:** `PYT T/test_plan.py T/test_students_api.py T/test_students_actions.py`. Esperado: FALLAN.
- [ ] **Step 3: Tope.** `MAX_PAGOS_PLAN = 2`; `plan_service.py` lo usa en sus tres sitios.
- [ ] **Step 4: Vencido.** En `confirm`, tras el chequeo de pagos: si `cuenta.situacion == "atrasada"`, `ServiceError("con_vencidos", "Este plan tiene pagos vencidos: ya no se puede modificar.", status=409)`. En `expediente`, `editable` suma `and c.situacion != "atrasada"`.
- [ ] **Step 5: Excel.** `_COLUMNAS = [("No. de control", 16), ("Nombre", 36), ("Carrera", 36), ("Monto debido", 16)]`; fila `[control, nombre, carrera, c.saldo]`; texto en columnas 1 a 3; dinero en la 4; sin formato de fecha; `auto_filter.ref = f"A7:D{...}"`.
- [ ] **Step 6: Doc.** `secretaria_estudiantes.md`: "4 columnas" y regla de Modificar plan.
- [ ] **Step 7:** `PYT T/`. Esperado: todo pasa.
- [ ] **Step 8:** **COMMIT** `feat(prorrogas): plan de 1 o 2 pagos, no se rehace vencido y Excel solo con lo pedido`

### Task 5: Fuentes de las cartas (punto 18)

Las plantillas usan Noto Sans y Montserrat; `Geomanist Medium` aparece solo en el pie de `carta_compromiso_2.docx`, y es una fuente comercial. El 2026-11-08 ningún `.docx` bajo `itcj2/` fuera de Prórrogas usaba estas fuentes.

**Files:**
- Modify: `docker/backend/Dockerfile.fastapi:8-10`, `APP/documents/defaults/carta_compromiso_2.docx`
- Test: `T/test_default_templates.py`

- [ ] **Step 1: Prueba.**

```python
def test_las_cartas_no_piden_una_fuente_comercial():
    from zipfile import ZipFile
    from itcj2.apps.prorrogas_tec.documents.catalog import DEFAULTS_DIR
    for docx in DEFAULTS_DIR.glob("*.docx"):
        z = ZipFile(docx)
        for n in z.namelist():
            if n.startswith("word/") and n.endswith(".xml") and n != "word/fontTable.xml":
                assert b"Geomanist" not in z.read(n), (docx.name, n)
```

- [ ] **Step 2:** `PYT T/test_default_templates.py`. Esperado: FALLA por `footer1.xml`.
- [ ] **Step 3: Plantilla.** Reescribe el `.docx` con `zipfile`, cambiando `Geomanist Medium` por `Montserrat Medium` en `word/footer1.xml` y conservando el resto de las entradas tal cual.
- [ ] **Step 4: Dockerfile.** Agrega `fonts-noto-core fonts-montserrat` junto a `fonts-dejavu-core`.
- [ ] **Step 5:** `PYT T/test_default_templates.py`. Esperado: pasa.
- [ ] **Step 6: GATE (descarga paquetes).** Pide permiso para `docker compose -f /home/deigol/repos/itcj/docker/compose/docker-compose.dev.yml build backend` o deja que el usuario lo corra. Luego `... exec backend fc-match "Montserrat Medium"` debe imprimir Montserrat, y `fc-match "Noto Sans"`, Noto Sans. Si apt no encuentra un paquete, detente y repórtalo. Comparar el acomodo de las cartas lo hace una persona.
- [ ] **Step 7:** **COMMIT** `fix(prorrogas): la imagen trae las fuentes de las cartas`

---

## Bloque 2 · Avisos

### Task 6: Un correo que falla se nota (punto 10)

**Files:**
- Modify: `APP/services/notify.py`, `APP/services/events.py`, `APP/services/students_service.py`, `APP/services/invitation_service.py`, `APP/api/invitations.py`, `APP/api/requests_admin.py`, `JS/secretaria/estudiantes.js`, `JS/secretaria/solicitudes.js`, `TPL/secretaria/solicitudes.html`
- Test: `T/conftest.py`, `T/test_notify.py`, `T/test_students_actions.py`, `T/test_students_api.py`, `T/test_invitations.py`

**Interfaces:**
- Produces:
  - `notify_student(...) -> bool`: `True` si el correo salió o si la solicitud no tiene correo (basta el aviso en la plataforma).
  - `events.last_mail_failed(db, request_id: int) -> bool`: el evento más nuevo de la solicitud es `correo_no_enviado`.
  - Clave `correo_enviado: bool` en `expediente` y en la respuesta de `decidir`.
  - `invitation_service.invitation_link(token: str) -> str`.
  - Fixture `avisos` con `.kw` (extras de cada llamada) y que devuelve `True`.

- [ ] **Step 1: Fixture.** `avisos` guarda `(kind, req.id, link)` en `.calls`, los extras en `.kw` y devuelve `True`.
- [ ] **Step 2: Pruebas.**

```python
# test_notify.py
def test_si_el_correo_falla_queda_en_el_historial(db_session, solicitud, monkeypatch):
    from itcj2.apps.prorrogas_tec.models.event import ProrrogaEvent
    from itcj2.apps.prorrogas_tec.services.events import last_mail_failed
    monkeypatch.setattr(msgraph_mail, "acquire_token_silent", lambda app: None)
    assert notify.notify_student(db_session, solicitud, kind="aceptada", link="/prorrogas/estudiante") is False
    db_session.flush()
    ev = db_session.query(ProrrogaEvent).filter_by(request_id=solicitud.id, event_type="correo_no_enviado").one()
    assert ev.payload == {"aviso": "aceptada"} and last_mail_failed(db_session, solicitud.id)


def test_sin_correo_capturado_basta_el_aviso(db_session, solicitud):
    solicitud.email = None
    assert notify.notify_student(db_session, solicitud, kind="aceptada", link="/prorrogas/estudiante") is True


# test_students_actions.py
def test_recordatorio_que_no_sale_no_bloquea_24h(db_session, aceptada, secretaria, con_plan, monkeypatch):  # Review Focus 2
    from itcj2.apps.prorrogas_tec.services import notify
    con_plan(aceptada, [("1000.00", date(2091, 5, 1))])
    monkeypatch.setattr(notify, "send_email", lambda **k: False)
    with pytest.raises(ServiceError) as e:
        StudentsService.remind(db_session, aceptada.id, secretaria.id, now=AHORA)
    assert e.value.code == "correo_no_salio" and e.value.status == 502
    db_session.refresh(aceptada)
    assert aceptada.last_reminded_at is None
    monkeypatch.setattr(notify, "send_email", lambda **k: True)
    StudentsService.remind(db_session, aceptada.id, secretaria.id, now=AHORA)
    assert aceptada.last_reminded_at is not None


# test_students_api.py
def test_expediente_avisa_si_el_ultimo_correo_fallo(db_session, aceptada):
    from itcj2.apps.prorrogas_tec.services.events import log_event
    dia = date(2091, 2, 1)
    assert StudentsService.expediente(db_session, aceptada.id, dia)["correo_enviado"] is True
    log_event(db_session, event_type="correo_no_enviado", request_id=aceptada.id, payload={"aviso": "carta_lista"})
    db_session.flush()
    assert StudentsService.expediente(db_session, aceptada.id, dia)["correo_enviado"] is False


# test_invitations.py
def test_api_si_el_correo_no_sale_devuelve_la_liga(client_as, secretaria, make_user, monkeypatch):
    from itcj2.apps.prorrogas_tec.services import notify
    make_user(control_number="99200020")
    monkeypatch.setattr(notify, "send_email", lambda **k: False)
    d = client_as(secretaria).post("/api/prorrogas/v2/invitaciones", json={"control_number": "99200020"}).json()
    assert d["enviado"] is False and "/prorrogas/unirse/invitacion/" in d["liga"]


def test_api_si_el_correo_sale_no_hay_liga(client_as, secretaria, make_user, enviar_correo):
    make_user(control_number="99200021")
    d = client_as(secretaria).post("/api/prorrogas/v2/invitaciones", json={"control_number": "99200021"}).json()
    assert d["enviado"] is True and "liga" not in d
```

- [ ] **Step 3:** `PYT` sobre esos archivos. Esperado: FALLAN.
- [ ] **Step 4: `notify_student`.** Devuelve el `bool` de la interfaz; si `send_email` falla, `log_event(event_type="correo_no_enviado", request_id=req.id, payload={"aviso": kind})`. Sigue sin lanzar. Quien llama ya hace `db.commit()` después. `EVENT_TYPES` suma `correo_no_enviado`.
- [ ] **Step 5: `remind`.** Sin candados durante Graph: guarda `previo = req.last_reminded_at`, pone `ts` y hace commit. Tras `notify_student`: si salió, `log_event("recordatorio_enviado")`; si no, restaura `previo`. Commit. Si no salió, `ServiceError("correo_no_salio", "El recordatorio no salió: revisa la conexión del correo en /itcj/config/email.", status=502)`.
- [ ] **Step 6: Decisión y expediente.** `expediente` agrega `"correo_enviado": not last_mail_failed(db, req.id)`; `decidir` devuelve `{**request_out, "correo_enviado": ...}`.
- [ ] **Step 7: Invitación.** `invitation_link(token)` arma la liga (la usa `invite`). La API agrega `liga` solo si `enviado` es falso.
- [ ] **Step 8: Pantallas.**
  - `estudiantes.js`: `HIST.correo_no_enviado = "Correo sin enviar"`; en `apply`, tras `render`, si `r.data.correo_enviado === false` muestra en `estMsg`: `"Se guardó, pero el correo al estudiante no salió. Avísale por otro medio."`.
  - `solicitudes.js`: mismo texto como toast tras decidir; si la invitación trae `liga`, muestra junto a `invError` un botón `Copiar liga` (`#invCopiar`, oculto por defecto) que usa `navigator.clipboard.writeText`.
- [ ] **Step 9:** `PYT T/`. Esperado: todo pasa.
- [ ] **Step 10:** **COMMIT** `feat(prorrogas): un correo que falla se avisa en pantalla y queda en el historial`

### Task 7: Carta en PDF adjunta (punto 11)

**Files:**
- Modify: `itcj2/core/utils/msgraph_mail.py:265-293`, `APP/services/notify.py`, `APP/services/request_service.py`
- Test: `T/test_notify.py`, `T/test_decision.py`

**Interfaces:**
- Produces: `graph_send_mail(..., save_to_sent=True, attachments: list[tuple[str, bytes]] | None = None)`; `send_email(..., attachments=None)`; `notify_student(..., attachments=None)`.

- [ ] **Step 1: Pruebas.**

```python
# test_notify.py
def _post_falso(monkeypatch):
    sent = {}
    monkeypatch.setattr(msgraph_mail.requests, "post",
                        lambda url, headers, json, timeout: sent.update(json) or SimpleNamespace(status_code=202))
    return sent


def test_sin_adjuntos_el_envio_no_cambia(monkeypatch):  # lo comparten AgendaTec, Mantenimiento y TitulaTec
    sent = _post_falso(monkeypatch)
    msgraph_mail.graph_send_mail("t", "s", "<p>", ["a@example.invalid"])
    assert "attachments" not in sent["message"]


def test_con_adjunto_va_en_base64(monkeypatch):
    import base64
    sent = _post_falso(monkeypatch)
    msgraph_mail.graph_send_mail("t", "s", "<p>", ["a@example.invalid"], attachments=[("c.pdf", b"%PDF")])
    a, = sent["message"]["attachments"]
    assert a["@odata.type"] == "#microsoft.graph.fileAttachment" and a["name"] == "c.pdf"
    assert a["contentType"] == "application/pdf" and base64.b64decode(a["contentBytes"]) == b"%PDF"


# test_decision.py
@pytest.mark.parametrize("aceptar, tipo", [(True, "carta_aceptacion"), (False, "carta_rechazo")])
def test_la_decision_adjunta_la_carta(db_session, solicitud, secretaria, monkeypatch, aceptar, tipo):
    from itcj2.apps.prorrogas_tec.services import notify
    enviados = []
    monkeypatch.setattr(notify, "send_email", lambda **k: enviados.append(k) or True)
    RequestService.decide(db_session, solicitud.id, secretaria.id, aceptar=aceptar, comentario="Motivo de prueba")
    nombre, pdf = enviados[0]["attachments"][0]
    assert nombre.endswith(f"-{tipo}.pdf") and pdf.startswith(b"%PDF")
```

- [ ] **Step 2:** `PYT T/test_notify.py T/test_decision.py`. Esperado: FALLAN.
- [ ] **Step 3: Implementa.** En `graph_send_mail`, `message["attachments"]` solo si hay adjuntos. `send_email` y `notify_student` los pasan. En `request_service.py`, `_carta_adjunta(db, req, tipo) -> list[tuple[str, bytes]] | None` busca el documento vigente y usa `DocumentService.read_pdf`, con nombre `f"{doc.context['folio']}-{doc.doc_type}.pdf"`. Si falla, registra el error y devuelve `None`: el aviso sale sin adjunto.
- [ ] **Step 4:** `PYT T/`. Esperado: todo pasa.
- [ ] **Step 5:** **COMMIT** `feat(prorrogas): las cartas de aceptacion y rechazo van adjuntas en PDF`

### Task 8: Campana en Mi prórroga (punto 12)

Se reutiliza `AppNotificationFAB`. No se carga Bootstrap, porque pisaría el estilo del alumno: `.btn` y `.badge` ya existen ahí con otro significado.

**Files:**
- Modify: `TPL/estudiante/_base.html`, `APP/static/css/estudiante/base.css`
- Test: `T/test_student_pages.py`

- [ ] **Step 1: Prueba.**

```python
def test_mi_prorroga_trae_la_campana(client_as, alumno_unido):
    page = client_as(alumno_unido).get("/prorrogas/estudiante").text
    assert "app-fab-widget.js" in page and "new AppNotificationFAB('prorrogas_tec'" in page
```

- [ ] **Step 2:** `PYT T/test_student_pages.py`. Esperado: FALLA.
- [ ] **Step 3: Plantilla.** En `<head>`, `bootstrap-icons@1.11.3` (misma URL de `titulatec/base.html`) y `/static/core/css/notifications/notifications.css?v={{ sv('core', 'css/notifications/notifications.css') }}`. Antes de `</body>`, `/static/core/js/notifications/app-fab-widget.js?v=...` y `new AppNotificationFAB('prorrogas_tec', '/api/core/v2', { color: '#652F2A', colorDark: '#4f2420' })` dentro de `try`.
- [ ] **Step 4: CSS.** Bajo `[id^="notifFab-"], [id^="notifPanel-"]` agrega solo las utilidades que usa el widget (`d-flex`, `align-items-center`, `justify-content-center`, `fs-1`, `fs-4`, `fw-semibold`, `small`, `text-center`, `text-muted`, `mt-2`, `ms-2`, `mb-0`, `py-4`, `rounded-pill`, `text-bg-danger`, `bg-primary`) y neutraliza `.btn` y `.badge`, incluido `.badge::before`.
- [ ] **Step 5:** `PYT T/`. Esperado: todo pasa.
- [ ] **Step 6:** **COMMIT** `feat(prorrogas): campana de avisos en Mi prorroga`

### Task 9: Un solo aviso con fechas, montos y firma (punto 15)

**Files:**
- Modify: `APP/services/plan_service.py:98-99`, `TPL/email/carta_lista.html`, `TPL/email/plan_modificado.html`
- Create: `TPL/email/_pagos.html`
- Test: `T/test_plan.py`

**Interfaces:**
- Consumes: `avisos.kw` (Task 6).

- [ ] **Step 1: Pruebas.**

```python
def test_el_aviso_del_plan_lleva_fechas_y_montos(db_session, aceptada, secretaria, avisos):
    PlanService.confirm(db_session, aceptada.id, secretaria.id, total=D("3650"), parcialidades=DOS, now=date(2026, 11, 1))
    kw = avisos.kw[0]
    assert "$1,825.00 el 01 de febrero de 2091" in kw["body"] and kw["context"]["total"] == "$3,650.00"
    assert [p["etiqueta"] for p in kw["context"]["pagos"]] == ["Pago 1/2", "Pago 2/2"]


@pytest.mark.parametrize("plantilla", ["carta_lista.html", "plan_modificado.html"])
def test_el_correo_del_plan_lista_los_pagos(plantilla):
    from itcj2.templates import templates
    html = templates.env.get_template(f"prorrogas_tec/email/{plantilla}").render(
        folio="PR-1", link="x", total="$10.00", pagos=[{"etiqueta": "Pago único", "fecha": "01 de mayo de 2091", "monto": "$10.00"}])
    assert "Pago único" in html and "01 de mayo de 2091" in html and "Firmar mi carta" in html
```

- [ ] **Step 2:** `PYT T/test_plan.py`. Esperado: FALLAN.
- [ ] **Step 3: Implementa.** `confirm` arma `pagos = [{"etiqueta": "Pago único" si es uno, si no f"Pago {i}/{n}", "fecha": fecha_larga(f), "monto": pesos(m)}]` y llama a `notify_student` con `body = " · ".join(f"{monto} el {fecha}") + ". Firma tu carta compromiso en Mi prórroga."` y `context={"total": pesos(total), "pagos": pagos}`. `_pagos.html` es la lista con el total; ambas plantillas la incluyen y su botón dice `Firmar mi carta`.
- [ ] **Step 4:** `PYT T/`. Esperado: todo pasa.
- [ ] **Step 5:** **COMMIT** `feat(prorrogas): el aviso del plan lleva fechas, montos y boton para firmar`

### Task 10: Firma pendiente a la vista (punto 16)

Se muestra y se recuerda, sin bloquear pagos.

**Files:**
- Modify: `APP/services/students_service.py`, `APP/services/notify.py`, `APP/services/events.py`, `APP/api/students_admin.py`, `JS/secretaria/estudiantes.js`, `TPL/secretaria/estudiantes.html`
- Create: `TPL/email/firma_pendiente.html`
- Test: `T/test_students_actions.py`

**Interfaces:**
- Produces: `StudentsService.remind_pending(db, request_id: int, actor_id: int, que: str, *, now=None) -> ProrrogaRequest`, con `_PENDIENTES = {"firma": "firma_pendiente"}`; `POST /estudiantes/{id}/recordar-pendiente` con `{"que": "firma"}`; filtro `por_firmar`; campo `por_firmar: bool` en cada fila.

- [ ] **Step 1: Pruebas.**

```python
API = "/api/prorrogas/v2/estudiantes"


def _carta(db, req, firmada=False):
    from itcj2.apps.prorrogas_tec.models.document import ProrrogaDocument
    d = ProrrogaDocument(request_id=req.id, doc_type="carta_compromiso_1", version=1, context={}, file_path="x.pdf",
                         sha256="0" * 64, signed_at=AHORA if firmada else None)
    db.add(d)
    db.flush()
    return d


def test_filtro_y_marca_de_firma_pendiente(client_as, secretaria, db_session, periodo, aceptada, make_aceptada):
    _carta(db_session, aceptada)
    _carta(db_session, make_aceptada(), firmada=True)
    d = client_as(secretaria).get(f"{API}?period_id={periodo.id}&filtro=por_firmar&per_page=100").json()
    assert [i["id"] for i in d["items"]] == [aceptada.id] and d["items"][0]["por_firmar"] is True
    assert d["conteos"]["por_firmar"] == 1


def test_recordar_firma_una_vez_al_dia(db_session, aceptada, secretaria, avisos):
    _carta(db_session, aceptada)
    StudentsService.remind_pending(db_session, aceptada.id, secretaria.id, "firma", now=AHORA)
    assert avisos.calls[0][0] == "firma_pendiente"
    with pytest.raises(ServiceError) as e:
        StudentsService.remind_pending(db_session, aceptada.id, secretaria.id, "firma", now=AHORA + timedelta(hours=23))
    assert e.value.code == "ya_recordado"
    StudentsService.remind_pending(db_session, aceptada.id, secretaria.id, "firma", now=AHORA + timedelta(hours=25))
    assert len(avisos.calls) == 2


def test_no_recuerda_si_ya_firmo(db_session, aceptada, secretaria, avisos):
    _carta(db_session, aceptada, firmada=True)
    with pytest.raises(ServiceError) as e:
        StudentsService.remind_pending(db_session, aceptada.id, secretaria.id, "firma", now=AHORA)
    assert e.value.code == "no_aplica"
```

- [ ] **Step 2:** `PYT T/test_students_actions.py`. Esperado: FALLAN.
- [ ] **Step 3: Lista.** `listar` obtiene en una consulta los `request_id` con `carta_compromiso_%` vigente sin firmar; agrega conteo, filtro y campo. `FILTROS` suma `por_firmar`.
- [ ] **Step 4: Recordatorio.** `remind_pending` valida `que` (`ServiceError("que_invalido", ..., 400)`) y que aplique (`no_aplica`, 409). El límite de 24 h sale del último evento `recordatorio_pendiente` con ese `que`; asigna `log_event(...).created_at = ts` para respetar el reloj inyectado. Si no sale el correo, `correo_no_salio` (502) sin registrar el evento. `_AVISOS["firma_pendiente"] = ("Te falta firmar tu carta compromiso", "firma_pendiente.html")`, cuerpo `"Entra a Mi prórroga para firmarla."`. `EVENT_TYPES` suma `recordatorio_pendiente`.
- [ ] **Step 5: API y pantalla.** Ruta con permiso `_REMIND`, devuelve el expediente. `estudiantes.html`: botón `Por firmar` con `data-f="por_firmar"`. `estudiantes.js`: `FILTROS` lo suma; `est-tag` `"Falta firma"`; en `situacionCard`, si `x.carta && !x.carta.firmada`, botón `Recordar firma`; `HIST.recordatorio_pendiente`.
- [ ] **Step 6:** `PYT T/`. Esperado: todo pasa.
- [ ] **Step 7:** **COMMIT** `feat(prorrogas): firma pendiente en la lista, con filtro y recordatorio`

### Task 11: Recordatorios automáticos (punto 19)

**Files:**
- Create: `APP/services/reminder_service.py`, `itcj2/tasks/prorrogas_tasks.py`, `database/DML/prorrogas_tec/08_insert_plan5.sql` (fuera de git)
- Modify: `itcj2/celery_app.py` (`include`), `itcj2/cli/prorrogas.py` (`_DML_FILES`), `APP/services/students_service.py`, `TPL/email/recordatorio.html`, `T/test_permissions_contract.py`
- Test: `T/test_reminders.py`

**Interfaces:**
- Consumes: `notify_student -> bool` (Task 6); `ProrrogaInstallment.last_reminder_days` (Task 1).
- Produces: `ReminderService.run(db, today: date) -> dict` con `{"enviados": int, "fallidos": int}`; tarea Celery `prorrogas.payment_reminders`.

- [ ] **Step 1: Pruebas** (`T/test_reminders.py`; 2091 evita choques con datos de dev):

```python
from datetime import date, timedelta

import pytest

from itcj2.apps.prorrogas_tec.models.plan import ProrrogaInstallment
from itcj2.apps.prorrogas_tec.services import notify
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.reminder_service import ReminderService
from itcj2.apps.prorrogas_tec.services.students_service import StudentsService

HOY = date(2091, 5, 1)


def _plan(con_plan, req, dias, pagos=()):
    return con_plan(req, [("1000.00", HOY + timedelta(days=dias))], pagos=pagos)


@pytest.mark.parametrize("dias, sale", [(5, True), (1, True), (0, True), (3, False), (-1, False)])
def test_sale_a_5_1_y_0_dias(db_session, aceptada, con_plan, avisos, dias, sale):
    _plan(con_plan, aceptada, dias)
    assert ReminderService.run(db_session, HOY) == {"enviados": int(sale), "fallidos": 0}


def test_dos_corridas_el_mismo_dia_no_repiten(db_session, aceptada, con_plan, avisos):  # Review Focus 3
    _plan(con_plan, aceptada, 5)
    ReminderService.run(db_session, HOY)
    ReminderService.run(db_session, HOY)
    assert len(avisos.calls) == 1


def test_cada_umbral_sale_una_vez(db_session, aceptada, con_plan, avisos):
    _plan(con_plan, aceptada, 5)
    for d in range(6):
        ReminderService.run(db_session, HOY + timedelta(days=d))
    assert len(avisos.calls) == 3


def test_pago_cubierto_no_recibe(db_session, aceptada, con_plan, avisos):
    _plan(con_plan, aceptada, 1, pagos=["1000.00"])
    assert ReminderService.run(db_session, HOY)["enviados"] == 0


def test_historica_sin_semestre_queda_fuera(db_session, make_historica, avisos):
    make_historica(parcialidades=(("1000.00", HOY),))
    assert ReminderService.run(db_session, HOY)["enviados"] == 0


def test_si_el_correo_falla_no_se_marca(db_session, aceptada, con_plan, monkeypatch):
    _plan(con_plan, aceptada, 0)
    monkeypatch.setattr(notify, "notify_student", lambda *a, **k: False)
    assert ReminderService.run(db_session, HOY) == {"enviados": 0, "fallidos": 1}
    assert db_session.query(ProrrogaInstallment).filter_by(request_id=aceptada.id).one().last_reminder_days is None


def test_el_boton_manual_excluye_historicas_sin_semestre(db_session, make_historica, secretaria):
    h = make_historica(parcialidades=(("1000.00", date(2091, 5, 1)),))
    h.email = "x@example.invalid"
    with pytest.raises(ServiceError) as e:
        StudentsService.remind(db_session, h.id, secretaria.id, now=HOY)
    assert e.value.code == "sin_semestre"
```

- [ ] **Step 2:** `PYT T/test_reminders.py`. Esperado: FALLA el import.
- [ ] **Step 3: `ReminderService`.** Llama a `notify.notify_student` por módulo, para que las pruebas lo parchen. Busca parcialidades vigentes con `due_date` en `today + (5, 1, 0)` de solicitudes `aceptada`, con `period_id` y con `student_id` o `email`. Omite si `p.estado == "pagada"` o si `last_reminder_days` no es `None` y es `<= dias`. Por cada una: `notify_student(kind="recordatorio", link="/prorrogas/estudiante", body=..., context={saldo, proxima_fecha, proxima_monto, "vencido": False})`; si salió, marca `last_reminder_days = dias`. `db.commit()` por parcialidad para que un fallo no pierda los anteriores.
- [ ] **Step 4: Botón manual.** En `remind`, tras `sin_destinatario`: `req.period_id is None` lanza `ServiceError("sin_semestre", "Esta prórroga histórica no tiene semestre en el sistema.", status=409)`. `_puede_recordar` suma `req.period_id is not None`.
- [ ] **Step 5: Correo.** `recordatorio.html` agrega `<p>Acude a Caja con tu folio para pagar.</p>`.
- [ ] **Step 6: Tarea.** `prorrogas_tasks.py` copia la forma de `titulatec.email_reminders`: `@celery_app.task(bind=True, base=LoggedTask, name="prorrogas.payment_reminders", soft_time_limit=540, time_limit=600)`, con `SessionLocal()` y `db_now().date()`, más `TASK_DEFINITIONS`. Agrega el módulo a `include`.
- [ ] **Step 7: Semilla** (`08_insert_plan5.sql`; forma de `database/DML/titulatec/sii_2026_09/16_insert_sii_sweep_task.sql`): fila en `core_task_definitions` (`app_name='prorrogas_tec'`, `category='notification'`) y en `core_periodic_tasks` (`'Prórrogas: recordatorios de pago'`, cron `0 8 * * *`). Suma el archivo a `_DML_FILES` y una prueba en el contrato (con el mismo `skipif`) que afirma `"prorrogas.payment_reminders"` en el archivo.
- [ ] **Step 8:** `PYT T/`. Esperado: todo pasa.
- [ ] **Step 9:** **COMMIT** (sin `database/`) `feat(prorrogas): recordatorios automaticos a 5, 1 y 0 dias`

---

## Bloque 3 · Referencia bancaria y cierre

### Task 12: El alumno sube su referencia (puntos 6 y 14)

**Files:**
- Create: `APP/services/reference_service.py`
- Modify: `APP/api/student.py`, `APP/services/request_service.py` (`request_out`), `APP/services/events.py`, `APP/services/notify.py:26`, `TPL/email/decision_aceptada.html`, `TPL/estudiante/solicitud.html`, `TPL/estudiante/unirse_aceptar.html:20`, `JS/estudiante/solicitud.js`, `JS/estudiante/mi_prorroga.js:75`, `APP/documents/defaults/carta_aceptacion.docx`
- Test: `T/test_referencia.py`, `T/test_notify.py`

**Interfaces:**
- Consumes: `reference_path`, `reference_uploaded_at` (Task 1).
- Produces: `ReferenceService.MAX_BYTES = 5 * 1024 * 1024`; `ReferenceService.save(db, req: ProrrogaRequest, data: bytes, actor_id: int, *, now=None) -> ProrrogaRequest`; `ReferenceService.read(req) -> bytes`; `request_out` con `"referencia": iso | None`.

- [ ] **Step 1: Pruebas** (`T/test_referencia.py`):

```python
from io import BytesIO

import pytest

from itcj2.core.utils.timezone import db_now
from tests.fastapi.prorrogas_tec.conftest import STUDENT_PERMS

API = "/api/prorrogas/v2/estudiante/solicitudes"
PDF = b"%PDF-1.4 referencia de prueba"


@pytest.fixture()
def duena(db_session, solicitud, grant, make_role):
    from itcj2.core.models.user import User
    u = db_session.get(User, solicitud.student_id)
    grant(u, make_role("student", STUDENT_PERMS))
    return u


def _subir(c, rid, data=PDF):
    return c.post(f"{API}/{rid}/referencia", files={"archivo": ("r.pdf", BytesIO(data), "application/pdf")})


def test_sube_y_baja_su_referencia(client_as, duena, solicitud):
    c = client_as(duena)
    r = _subir(c, solicitud.id)
    assert r.status_code == 200 and r.json()["referencia"]
    assert c.get(f"{API}/{solicitud.id}/referencia.pdf").content == PDF


@pytest.mark.parametrize("data, code", [
    (b"", "referencia_invalida"),
    (b"MZ no soy un pdf", "referencia_invalida"),
    (b"%PDF-" + b"0" * (5 * 1024 * 1024), "referencia_muy_grande"),
])
def test_archivo_rechazado(client_as, duena, solicitud, data, code):  # Review Focus 4
    r = _subir(client_as(duena), solicitud.id, data)
    assert r.status_code == 400 and r.json()["error"] == code


def test_referencia_ajena_no_existe(client_as, estudiante, solicitud):  # Review Focus 4
    c = client_as(estudiante)
    assert _subir(c, solicitud.id).status_code == 404
    assert c.get(f"{API}/{solicitud.id}/referencia.pdf").status_code == 404


def test_con_plan_ya_no_se_cambia(client_as, duena, solicitud, db_session):
    solicitud.plan_confirmed_at = db_now()
    db_session.flush()
    r = _subir(client_as(duena), solicitud.id)
    assert r.status_code == 409 and r.json()["error"] == "referencia_fija"
```

En `test_notify.py`:

```python
def test_la_aceptacion_ya_no_manda_a_acordar_el_monto():
    from itcj2.templates import templates
    html = templates.env.get_template("prorrogas_tec/email/decision_aceptada.html").render(folio="PR-1", link="x")
    assert "Acude" not in html and "referencia bancaria" in html
    assert "Acude" not in notify._CUERPOS["aceptada"]
```

- [ ] **Step 2:** `PYT T/test_referencia.py T/test_notify.py`. Esperado: FALLAN.
- [ ] **Step 3: Servicio.** Vacío o sin `%PDF-` al inicio: `referencia_invalida` ("La referencia debe ser un PDF."). Más de `MAX_BYTES`: `referencia_muy_grande` ("La referencia no puede pasar de 5 MB."), ambos 400. Solo con estado `pendiente` o `aceptada`. Con `plan_confirmed_at`: `referencia_fija` (409, "Tu plan ya está armado: la referencia ya no se puede cambiar."). Ruta `referencias/{period_id}/{id}-{sha12}.pdf` con `storage.write_atomic`. Evento `referencia_subida`.
- [ ] **Step 4: API.** `POST /solicitudes/{id}/referencia` (permiso `_CREATE`, `archivo: UploadFile = File(...)`, lee `archivo.file.read(MAX_BYTES + 1)`) y `GET /solicitudes/{id}/referencia.pdf` (permiso `_READ`). Ambas filtran por `student_id` del usuario; si no, 404. Devuelve `request_out`.
- [ ] **Step 5: Pantallas.**
  - `solicitud.html`: nueva sección 4 `Tu referencia bancaria (PDF)` con `<input type="file" accept="application/pdf" id="sol-referencia">`; firma pasa a 5.
  - `solicitud.js`: tras el `POST` correcto y antes de redirigir, si hay archivo lo sube; un fallo no detiene la redirección.
  - `mi_prorroga.js`: en `pendiente` o `aceptada` sin plan, `seccionReferencia(s)`: si falta, tarjeta `Sube tu referencia bancaria` con input y botón; si existe, `Referencia subida el …` con enlace.
  - `unirse_aceptar.html:20`: `Subir tu referencia bancaria`.
- [ ] **Step 6: Texto (punto 14).** Copia exacta para `_CUERPOS["aceptada"]`, `decision_aceptada.html` y `mi_prorroga.js:75`: `La secretaria armará tu plan de pagos con base en tu referencia bancaria. Te avisaremos cuando esté listo.` En `carta_aceptacion.docx`, con python-docx dentro del contenedor, sustituye el párrafo `Para continuar, acuda a la Subdirección…` por `Para continuar, suba su referencia bancaria en Mi prórroga, si aún no lo ha hecho; con ella se armará su plan de pagos y se emitirá su carta compromiso.` Deja el texto en el primer run y vacía los demás.
- [ ] **Step 7:** `PYT T/`. Esperado: todo pasa, incluida `test_default_templates`.
- [ ] **Step 8:** **COMMIT** `feat(prorrogas): el alumno sube su referencia bancaria y deja de acudir a acordar el monto`

### Task 13: La secretaria ve la referencia y la recuerda (punto 13)

**Files:**
- Modify: `APP/api/students_admin.py`, `APP/services/students_service.py`, `APP/services/notify.py`, `JS/secretaria/estudiantes.js`
- Create: `TPL/email/referencia_pendiente.html`
- Test: `T/test_students_actions.py`

**Interfaces:**
- Consumes: `ReferenceService.read` (Task 12); `remind_pending` (Task 10).
- Produces: `GET /estudiantes/{id}/referencia.pdf`; `_PENDIENTES["referencia"] = "referencia_pendiente"`.

- [ ] **Step 1: Pruebas.**

```python
def test_secretaria_abre_la_referencia(client_as, secretaria, db_session, aceptada):
    from itcj2.apps.prorrogas_tec.services.reference_service import ReferenceService
    url = f"{API}/{aceptada.id}/referencia.pdf"
    assert client_as(secretaria).get(url).status_code == 404
    ReferenceService.save(db_session, aceptada, b"%PDF-1.4 x", aceptada.student_id)
    assert client_as(secretaria).get(url).content == b"%PDF-1.4 x"


def test_recordar_referencia_solo_si_falta(db_session, aceptada, secretaria, avisos):
    from itcj2.apps.prorrogas_tec.services.reference_service import ReferenceService
    StudentsService.remind_pending(db_session, aceptada.id, secretaria.id, "referencia", now=AHORA)
    assert avisos.calls[0][0] == "referencia_pendiente"
    ReferenceService.save(db_session, aceptada, b"%PDF-1.4 x", aceptada.student_id)
    with pytest.raises(ServiceError) as e:
        StudentsService.remind_pending(db_session, aceptada.id, secretaria.id, "referencia", now=AHORA + timedelta(days=2))
    assert e.value.code == "no_aplica"
```

- [ ] **Step 2:** `PYT T/test_students_actions.py`. Esperado: FALLAN.
- [ ] **Step 3: Implementa.** Ruta con `_READ` y 404 `no_encontrada` si no hay referencia. `_AVISOS["referencia_pendiente"] = ("Falta tu referencia bancaria", "referencia_pendiente.html")`, cuerpo `"Súbela en Mi prórroga para que armen tu plan de pagos."`.
- [ ] **Step 4: Pantalla.** En `planForm`, junto a `Total del adeudo`: enlace `Ver referencia` (`target="_blank"`) o texto `Sin referencia` con botón `Recordar referencia`. En `solPane`, fila `Referencia` igual. El monto se puede capturar sin ella. `HIST.referencia_subida = "Referencia bancaria subida"`.
- [ ] **Step 5:** `PYT T/`. Esperado: todo pasa.
- [ ] **Step 6:** **COMMIT** `feat(prorrogas): la secretaria ve la referencia junto al total y puede recordarla`

### Task 14: Cierre de aceptadas sin plan (punto 17)

No avisa al alumno: el proceso no lo pide.

**Files:**
- Modify: `APP/services/students_service.py`, `APP/services/events.py`, `APP/api/students_admin.py`, `JS/secretaria/estudiantes.js`, `TPL/secretaria/estudiantes.html`, `JS/estudiante/mi_prorroga.js:40-44`, `APP/docs/flows/secretaria_estudiantes.md`
- Test: `T/test_students_actions.py`

**Interfaces:**
- Produces: `StudentsService.close_without_plan(db, request_id: int, actor_id: int, motivo: str, *, now=None) -> ProrrogaRequest`; `POST /estudiantes/{id}/cerrar-sin-plan` con `{"motivo": str}`; filtro y campo `pendiente_cierre`; `plan.cerrable: bool`.

- [ ] **Step 1: Pruebas.**

```python
MOTIVO_CIERRE = "No trajo su referencia a tiempo."


def test_cerrar_sin_plan(db_session, aceptada, secretaria):
    from itcj2.apps.prorrogas_tec.models.event import ProrrogaEvent
    req = StudentsService.close_without_plan(db_session, aceptada.id, secretaria.id, MOTIVO_CIERRE, now=date(2091, 6, 21))
    assert req.status == "cerrada_sin_plan"
    ev = db_session.query(ProrrogaEvent).filter_by(request_id=aceptada.id, event_type="cerrada_sin_plan").one()
    assert ev.payload == {"motivo": MOTIVO_CIERRE}


@pytest.mark.parametrize("motivo, dia, code", [
    ("corto", date(2091, 6, 21), "motivo_invalido"),
    (MOTIVO_CIERRE, date(2091, 6, 20), "semestre_en_curso"),
])
def test_cierre_invalido(db_session, aceptada, secretaria, motivo, dia, code):
    with pytest.raises(ServiceError) as e:
        StudentsService.close_without_plan(db_session, aceptada.id, secretaria.id, motivo, now=dia)
    assert e.value.code == code


def test_con_plan_no_se_cierra(db_session, aceptada, secretaria, con_plan):
    con_plan(aceptada, [("1000.00", date(2091, 5, 1))])
    with pytest.raises(ServiceError) as e:
        StudentsService.close_without_plan(db_session, aceptada.id, secretaria.id, MOTIVO_CIERRE, now=date(2091, 6, 21))
    assert e.value.code == "con_plan"


def test_lista_marca_pendientes_de_cierre(db_session, periodo, aceptada):
    ver = lambda dia: StudentsService.listar(db_session, periodo.id, filtro="pendiente_cierre", today=dia)  # noqa: E731
    d = ver(date(2091, 6, 21))
    assert [i["id"] for i in d["items"]] == [aceptada.id] and d["conteos"]["pendiente_cierre"] == 1
    assert ver(date(2091, 6, 20))["items"] == []
```

- [ ] **Step 2:** `PYT T/test_students_actions.py`. Esperado: FALLAN.
- [ ] **Step 3: Servicio.** Usa `_bloquear`. `motivo` de 10 a 1000 caracteres, sin espacios a los lados. `c.total is not None`: `con_plan` (409). `req.period_id is None` o `today <= period.end_date`: `semestre_en_curso` (409). Evento `cerrada_sin_plan` con `{"motivo": motivo}`. En `listar`, `pendiente_cierre = c.situacion == "sin_plan" and today > period.end_date`. En `expediente`, `plan.cerrable` con la misma regla.
- [ ] **Step 4: API.** Permiso `_PLAN`. Responde `{"ok": True}`, porque una solicitud cerrada ya no tiene expediente en Estudiantes.
- [ ] **Step 5: Pantallas.** Filtro `Por cerrar` (`data-f="pendiente_cierre"`). Pill `Cerrar sin plan` en la fila. Si `plan.cerrable`, tarjeta con `<textarea>` y botón `Cerrar sin plan`; al confirmar, cierra el modal y recarga la lista. En `ESTADO` de Mi prórroga: `cerrada_sin_plan: ["Cerrada", "t-neutral", "Esta prórroga se cerró sin plan de pagos"]`.
- [ ] **Step 6:** `PYT T/`. Esperado: todo pasa.
- [ ] **Step 7:** **COMMIT** `feat(prorrogas): cerrar con motivo las aceptadas sin plan al terminar el semestre`

---

## Bloque 4 · Roles y consulta

### Task 15: Pestañas por permiso y entrada por rol (puntos 20 y 30)

Las páginas rechazan hoy a un admin global sin rol, y `require_page_app` es compartida: el acceso propio vive en Prórrogas.

**Files:**
- Create: `APP/services/access.py`
- Modify: `APP/pages/secretaria.py`, `APP/pages/landing.py`, `TPL/secretaria/_base.html`, `database/DML/prorrogas_tec/08_insert_plan5.sql` (fuera de git)
- Test: `T/conftest.py`, `T/test_secretaria_pages.py`, `T/test_permissions_contract.py:36`

**Interfaces:**
- Produces:
  - `access.perms_of(db, user: dict) -> set[str]`: el admin global devuelve `{"*"}`, sin depender de que las semillas ya estén aplicadas.
  - `access.require_tab(code: str)`: dependencia que deja los permisos en `request.state.prorrogas_perms`.
  - Códigos `prorrogas_tec.secretaria.page.{estadisticas,solicitudes,estudiantes,documentos,configuracion}`, escritos literales en `TABS` para que los vea la prueba de contrato. `...page.consulta` se siembra aquí y entra a `TABS` en la Task 18.
  - `LECTOR_PERMS` y fixture `lector` en `conftest.py`.

- [ ] **Step 1: Fixtures.** `SECRETARIA_PERMS` suma los seis códigos de página, incluido `...page.consulta`. Agrega:

```python
LECTOR_PERMS = [
    "prorrogas_tec.secretaria.page.estadisticas", "prorrogas_tec.secretaria.page.solicitudes",
    "prorrogas_tec.secretaria.page.estudiantes", "prorrogas_tec.secretaria.page.consulta",
    "prorrogas_tec.requests.api.read.all", "prorrogas_tec.stats.api.read",
]


@pytest.fixture()
def lector(make_user, make_role, grant):
    user = make_user(first_name="LECTOR", last_name="PRUEBA")
    # No uses "admin": las pruebas ven el rol real de dev, con escritura hasta aplicar la semilla.
    grant(user, make_role("lector_prueba", LECTOR_PERMS))
    return user
```

- [ ] **Step 2: Pruebas** (`test_secretaria_pages.py`):

```python
def test_lector_solo_ve_sus_pestanas(client_as, lector):
    page = client_as(lector).get(f"{BASE}/estadisticas").text
    assert f'href="{BASE}/estudiantes"' in page
    assert f'href="{BASE}/documentos"' not in page and f'href="{BASE}/configuracion"' not in page


@pytest.mark.parametrize("tab", ["documentos", "configuracion"])
def test_lector_no_abre_lo_que_no_le_toca(client_as, lector, tab):  # Review Focus 5
    assert client_as(lector).get(f"{BASE}/{tab}", follow_redirects=False).status_code == 403


def test_raiz_lleva_a_la_primera_pestana_permitida(client_as, make_user, make_role, grant):
    u = make_user()
    grant(u, make_role("solo_stats", ["prorrogas_tec.secretaria.page.estadisticas"]))
    r = client_as(u).get(BASE, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == f"{BASE}/estadisticas"


def test_admin_global_entra_sin_rol_en_la_app(client_as, make_user):
    c = client_as(make_user(first_name="GLOBAL", last_name="ADMIN"), role="admin")
    assert c.get(f"{BASE}/documentos").status_code == 200
    r = c.get("/prorrogas/", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == BASE
```

- [ ] **Step 3:** `PYT T/test_secretaria_pages.py`. Esperado: FALLAN.
- [ ] **Step 4: `access.py`.** Usa `is_global_admin`, `cached_has_assignment` y `cached_perms`, y `PageLoginRequired`/`PageForbidden` de `itcj2.exceptions`, con el mismo orden de chequeos que `require_page_app`, salvo que `{"*"}` pasa cualquier pestaña.
- [ ] **Step 5: `secretaria.py`.** `TABS` lleva `(clave, etiqueta, permiso)`. Cada ruta usa `dependencies=[Depends(require_tab(...))]` y se quita la dependencia del router y `_VIEW`. `_contexto(request, active, title)` entrega las pestañas permitidas (`"*" in perms or codigo in perms`) y `perms`. `secretaria_home` exige sesión (`PageLoginRequired`) y redirige a la primera permitida en `("solicitudes", "estudiantes", "estadisticas", "documentos", "configuracion")`; si no hay ninguna, `PageForbidden`. La plantilla sigue recibiendo pares; ajusta el `for` si hace falta.
- [ ] **Step 6: Entrada.** Un admin global sin rol va a `/prorrogas/secretaria`. En el contrato, `test_el_censo_no_esta_vacio` usa `prorrogas_tec.secretaria.page.estudiantes`.
- [ ] **Step 7: Semilla.** En `08_insert_plan5.sql`: los seis permisos y su asignación a `secretaria`.
- [ ] **Step 8:** `PYT T/`. Esperado: todo pasa.
- [ ] **Step 9:** **COMMIT** (sin `database/`) `feat(prorrogas): un permiso por pestana y entrada segun el rol`

### Task 16: Las pantallas respetan los permisos (puntos 21 y 30)

**Files:**
- Modify: `TPL/secretaria/_base.html`, `JS/secretaria/solicitudes.js`, `JS/secretaria/estudiantes.js`, `JS/secretaria/documentos.js`, `JS/secretaria/configuracion.js`
- Test: `T/test_secretaria_pages.py`

**Interfaces:**
- Consumes: `perms` en el contexto (Task 15).
- Produces: `<body class="sec" data-perms="...">`.

- [ ] **Step 1: Prueba.**

```python
def test_la_pagina_publica_los_permisos_del_usuario(client_as, lector):
    page = client_as(lector).get(f"{BASE}/estudiantes").text
    assert "prorrogas_tec.requests.api.read.all" in page and "prorrogas_tec.payments.api.record" not in page
```

- [ ] **Step 2:** `PYT T/test_secretaria_pages.py`. Esperado: FALLA.
- [ ] **Step 3: Plantilla.** `data-perms="{{ perms|join(' ') }}"`.
- [ ] **Step 4: Motivo del 403.** En el `api()` de los cuatro JS: si `status === 403` y no hay `message`, `"No tienes permiso para esta acción."`.
- [ ] **Step 5: Ocultar.** En cada JS, `const perms = (document.body.dataset.perms || "").split(" "); const can = (p) => perms.includes("*") || perms.includes(p);`.

| Pantalla | Condición | Qué se oculta |
|---|---|---|
| `solicitudes.js` | `prorrogas_tec.invitations.api.create` | `#solSide` (agrega `.sol-side[hidden]{display:none}`) y las llamadas `regenQr()`, `loadToday()`, también dentro de `refresh` y `visibilitychange` |
| `solicitudes.js` | `prorrogas_tec.requests.api.decide` | Aceptar y Rechazar del modal |
| `estudiantes.js` | `prorrogas_tec.plans.api.manage` | `planForm`, `Modificar plan`, cierre sin plan |
| `estudiantes.js` | `prorrogas_tec.payments.api.record` / `.void` | Formulario de recibo / `Anular` |
| `estudiantes.js` | `prorrogas_tec.students.api.remind` | Recordar (fila y modal), Recordar firma y referencia |
| `estudiantes.js` | `prorrogas_tec.students.api.export` | `#estExport`, `Avisar desbloqueo` |

- [ ] **Step 6:** `PYT T/`. Esperado: todo pasa.
- [ ] **Step 7:** **COMMIT** `feat(prorrogas): cada rol solo ve lo que puede hacer`

### Task 17: Admin de solo lectura (punto 29)

**Files:**
- Modify: `database/DML/prorrogas_tec/08_insert_plan5.sql` (fuera de git), `APP/docs/README.md`, `APP/pages/landing.py`
- Test: `T/test_secretaria_pages.py`

**Interfaces:**
- Consumes: `lector`, `LECTOR_PERMS` (Task 15).

- [ ] **Step 1: Pruebas.**

```python
@pytest.mark.parametrize("ruta, cuerpo", [
    ("/api/prorrogas/v2/estudiantes/{id}/plan", {"total": "1000", "parcialidades": []}),
    ("/api/prorrogas/v2/estudiantes/{id}/recibos", {"folio": "X", "fecha": "2091-01-20", "monto": "1"}),
    ("/api/prorrogas/v2/estudiantes/{id}/recordar", {}),
    ("/api/prorrogas/v2/solicitudes/{id}/decision", {"aceptar": False, "comentario": "x"}),
    ("/api/prorrogas/v2/invitaciones/qr", None),
])
def test_lector_no_escribe(client_as, lector, aceptada, ruta, cuerpo):  # Review Focus 5
    assert client_as(lector).post(ruta.format(id=aceptada.id), json=cuerpo).status_code == 403


def test_lector_si_consulta(client_as, lector, aceptada):
    assert client_as(lector).get(f"/api/prorrogas/v2/estudiantes/{aceptada.id}").status_code == 200
```

- [ ] **Step 2:** `PYT T/test_secretaria_pages.py`. Esperado: pasan si Task 15 está bien; si fallan, corrige ahí.
- [ ] **Step 3: Semilla** (va al final de `_DML_FILES` para ganarle a lo que otorgan 02, 04, 05, 06 y 07):
  - `admin` recibe los seis códigos de `LECTOR_PERMS`.
  - `DELETE FROM core_role_permissions WHERE role_id = v_role_admin AND perm_id IN (SELECT id FROM core_permissions WHERE app_id = v_app_id AND code NOT IN (<LECTOR_PERMS>))`. Solo toca permisos de Prórrogas.
- [ ] **Step 4: Doc.** Agrega a `APP/docs/README.md` qué ve cada rol: `secretaria`, `admin` y admin global. En `APP/pages/landing.py`, corrige el comentario de `admin` en `_ROLE_HOME`: ya es solo lectura.
- [ ] **Step 5:** `PYT T/`. Esperado: todo pasa.
- [ ] **Step 6:** **COMMIT** (sin `database/`) `feat(prorrogas): admin de la app en solo lectura`

### Task 18: Consulta de todas las solicitudes (punto 32)

Sin canvas: usa el aspecto de la lista de Estudiantes. Si el usuario diseña esta vista antes de llegar aquí, usa su diseño.

**Files:**
- Create: `TPL/secretaria/consulta.html`, `JS/secretaria/consulta.js`
- Modify: `APP/services/request_service.py`, `APP/services/students_service.py`, `APP/api/requests_admin.py`, `APP/pages/secretaria.py`, `TPL/secretaria/_base.html`, `APP/static/css/secretaria/base.css`
- Test: `T/test_consulta.py`, `T/test_secretaria_pages.py`

**Interfaces:**
- Produces:
  - `RequestService.search(db, *, estado=None, semestre=None, q=None, page=1, per_page=25) -> dict` con `{"items", "total", "page", "per_page", "semestres"}`.
  - `StudentsService.historial(db, request_id: int) -> list[dict]` (extraído de `expediente`).
  - `GET /solicitudes/todas`, registrada **antes** de `/{request_id}`.

- [ ] **Step 1: Pruebas** (`T/test_consulta.py`):

```python
from urllib.parse import quote

API = "/api/prorrogas/v2/solicitudes"


def _ids(r):
    return [i["id"] for i in r.json()["items"]]


def test_filtra_por_estado(client_as, lector, make_aceptada, solicitud, db_session):
    rechazada = make_aceptada()
    rechazada.status = "rechazada"
    db_session.flush()
    ids = _ids(client_as(lector).get(f"{API}/todas?estado=rechazada&per_page=100"))
    assert rechazada.id in ids and solicitud.id not in ids


def test_incluye_historicas_sin_semestre(client_as, lector, make_historica):
    h = make_historica(control_number="99420999")
    r = client_as(lector).get(f"{API}/todas?q=99420999")
    assert _ids(r) == [h.id] and r.json()["items"][0]["semestre"] == "enero – junio 2089"


def test_filtra_por_semestre(client_as, lector, aceptada):
    r = client_as(lector).get(f"{API}/todas?semestre={quote('enero – junio 2091')}&per_page=100")
    assert aceptada.id in _ids(r) and "enero – junio 2091" in r.json()["semestres"]


def test_estado_invalido(client_as, lector):
    r = client_as(lector).get(f"{API}/todas?estado=xyz")
    assert r.status_code == 400 and r.json()["error"] == "estado_invalido"


def test_limites_de_paginacion(client_as, lector):
    assert client_as(lector).get(f"{API}/todas?per_page=500").json()["per_page"] == 100


def test_detalle_trae_historial(client_as, lector, aceptada, db_session):
    from itcj2.apps.prorrogas_tec.services.events import log_event
    log_event(db_session, event_type="solicitud_aceptada", request_id=aceptada.id)
    db_session.flush()
    assert client_as(lector).get(f"{API}/{aceptada.id}").json()["historial"][0]["tipo"] == "solicitud_aceptada"
```

En `test_secretaria_pages.py`:

```python
def test_pestana_consulta(client_as, lector):
    page = client_as(lector).get(f"{BASE}/consulta").text
    for texto in ("Consulta", "consulta.js"):
        assert texto in page
```

- [ ] **Step 2:** `PYT T/test_consulta.py T/test_secretaria_pages.py`. Esperado: FALLAN.
- [ ] **Step 3: Servicio.** `search` usa `STATUSES` para validar y `ilike` sobre `control_number` y `student_name`. Orden `created_at desc, id desc`. `semestres` son los `period_label` distintos. `per_page` entre 1 y 100. Cada item: `id, folio, control, nombre, carrera, semestre, estado, origen, creada`.
- [ ] **Step 4: API.** `/todas` con `_READ`. `ver` agrega `"historial": StudentsService.historial(db, req.id)`. Si `students_service` ya importa `request_service`, importa `StudentsService` dentro de la función.
- [ ] **Step 5: Página.** `TABS` suma `("consulta", "Consulta", "prorrogas_tec.secretaria.page.consulta")` después de Estudiantes, con ícono de lupa en `_base.html`. La plantilla es `<section class="cst">` y reutiliza `.est-bar`, `.est-row`, `.est-pill` y un `<dialog>`. `consulta.js` trae filtros de estado y semestre, búsqueda con espera de 300 ms, paginación y modal con datos, enlaces a `/solicitudes/{id}/documentos/{doc}.pdf` e historial. `body.sec .sec-main > .cfg` tiene su regla en el bloque final de `base.css`: agrega ahí la de `.cst`.
- [ ] **Step 6: Barra.** Agrega `consulta` tras `estadisticas` en el orden de `secretaria_home`. Con seis pestañas, sube el corte de `.sec-topnav` de 900 a 1020 px y confirma sin scroll horizontal en 1030 y 900 px.
- [ ] **Step 7:** `PYT T/`. Esperado: todo pasa.
- [ ] **Step 8:** **COMMIT** `feat(prorrogas): pestana Consulta con todas las solicitudes y su historial`

### Task 19: Cierre del plan

**Files:**
- Modify: `APP/docs/PENDIENTES.md`
- Create: `APP/docs/flows/secretaria_consulta.md`

- [ ] **Step 1: Suite.** `PYT T/`, y `PYT tests/fastapi/core`. Esperado: todo pasa. Si `tests/fastapi/core` falla por algo ajeno a este plan, repórtalo sin arreglarlo.
- [ ] **Step 2: GATE. Pide permiso y aplica las semillas en dev** con `init-prorrogas`, y confirma con conteos:

```bash
docker compose -f /home/deigol/repos/itcj/docker/compose/docker-compose.dev.yml exec backend python -m itcj2.cli.main prorrogas init-prorrogas
```

Verifica: `admin` con 6 permisos de Prórrogas y 1 fila `prorrogas.payment_reminders` en `core_periodic_tasks`.

- [ ] **Step 3: Revisión en navegador** con datos de prueba, en escritorio y a 390 px: Solicitudes como lector (sin QR ni decisiones), Estudiantes (filtros nuevos, firma, referencia, cierre), Mi prórroga (campana, subida), invitación (pantalla Aceptar) y Consulta. Sin datos reales en capturas ni artefactos.
- [ ] **Step 4: Docs.** `secretaria_consulta.md` con el formato de los demás flujos. Marca en `PENDIENTES.md` cada punto cerrado con **[hecho]**, fecha y commit, y agrega lo que requiere a una persona: copiar `08_insert_plan5.sql` a producción, conectar el buzón (H2), reconstruir la imagen y revisar las cartas.
- [ ] **Step 5:** **COMMIT** `docs(prorrogas): Plan 5 terminado, flujo de Consulta y pendientes al dia`
