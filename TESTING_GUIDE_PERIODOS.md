# Guía de Pruebas - Sistema de Períodos Académicos AgendaTec

## 📋 Índice
1. [Prerequisitos](#prerequisitos)
2. [Fase 1: Preparación y Migraciones](#fase-1-preparación-y-migraciones)
3. [Fase 2: APIs Backend](#fase-2-apis-backend)
4. [Fase 3: Validaciones Backend](#fase-3-validaciones-backend)
5. [Fase 4: Interfaz Admin](#fase-4-interfaz-admin)
6. [Fase 5: Interfaz Estudiantes](#fase-5-interfaz-estudiantes)
7. [Fase 6: Integración Completa](#fase-6-integración-completa)
8. [Checklist Final](#checklist-final)

---

## Prerequisitos

### Verificar entorno
```bash
# 1. Verificar que Redis está corriendo
docker-compose up -d redis
# O verificar conexión:
redis-cli ping  # Debe responder: PONG

# 2. Verificar base de datos PostgreSQL
psql -U tu_usuario -d tu_database -c "SELECT version();"

# 3. Verificar rama de git
git branch  # Debe estar en: feature/agendatec-periodos

# 4. Verificar commits
git log --oneline -7
```

**Commits esperados:**
- `feat(agendatec): Períodos académicos - Fase 7 (Migración y Datos)`
- `feat(agendatec): Períodos académicos - Fase 6 (Frontend Estudiantes)`
- `feat(agendatec): Períodos académicos - Fase 5 (Pantallas Admin)`
- `feat(agendatec): Períodos académicos - Fase 4 (Validaciones Backend)`
- `feat(agendatec): Agregar API REST completa para gestión de períodos`
- `feat(agendatec): Implementar sistema de períodos académicos dinámicos`

---

## Fase 1: Preparación y Migraciones

### 1.1 Aplicar migraciones de base de datos

```bash
# Con Redis corriendo, aplicar migraciones
flask db upgrade
```

**✅ Verificar:**
- Comando ejecuta sin errores
- Tablas creadas:
  - `core_academic_periods`
  - `agendatec_period_enabled_days`
- Columna agregada:
  - `agendatec_requests.period_id` (nullable, FK a academic_periods)

**🔍 SQL de verificación:**
```sql
-- Verificar tabla de períodos
\d core_academic_periods;

-- Verificar tabla de días habilitados
\d agendatec_period_enabled_days;

-- Verificar columna period_id en requests
\d agendatec_requests;
```

### 1.2 Ejecutar scripts SQL de permisos

```bash
# Ubicar los archivos SQL
ls database/DML/agendatec/periodos/

# Ejecutar permisos
psql -U tu_usuario -d tu_database -f database/DML/agendatec/periodos/01_insert_permissions_periods.sql
psql -U tu_usuario -d tu_database -f database/DML/agendatec/periodos/02_insert_role_permissions_periods.sql
```

**✅ Verificar:**
- Mensajes: "Permisos del módulo PERIODS creados correctamente"
- "Permisos de PERIODS asignados al rol ADMIN correctamente"

**🔍 SQL de verificación:**
```sql
-- Verificar permisos creados
SELECT code, name
FROM core_permissions
WHERE code LIKE 'agendatec.periods%'
ORDER BY code;
```

**Permisos esperados (9 en total):**
- `agendatec.periods.page.list`
- `agendatec.periods.page.edit`
- `agendatec.periods.api.read`
- `agendatec.periods.api.create`
- `agendatec.periods.api.update`
- `agendatec.periods.api.delete`
- `agendatec.periods.api.activate`
- `agendatec.periods.api.read_days`
- `agendatec.periods.api.update_days`

### 1.3 Crear períodos iniciales

```bash
# Ejecutar comando de seeding
flask seed-periods
```

**✅ Verificar output esperado:**
```
🗓️  Iniciando creación de períodos académicos...

📅 Creando período: Ago-Dic 2025
   ✓ Período creado (ID: 1)
   ✓ Días habilitados: 25-Ago, 26-Ago, 27-Ago

📦 Migrando X solicitudes existentes...
   ✓ Solicitudes migradas al período "Ago-Dic 2025"

📅 Creando período: Ene-Jun 2026
   ✓ Período creado (ID: 2) - ACTIVO
   ✓ Días habilitados: 26-Ene, 27-Ene, 28-Ene

============================================================
✅ Períodos académicos creados exitosamente
============================================================
```

**🔍 SQL de verificación:**
```sql
-- Verificar períodos creados
SELECT id, name, status, start_date, end_date, student_admission_deadline
FROM core_academic_periods
ORDER BY id;

-- Verificar días habilitados
SELECT p.name, ped.day
FROM agendatec_period_enabled_days ped
JOIN core_academic_periods p ON p.id = ped.period_id
ORDER BY ped.day;

-- Verificar migración de solicitudes
SELECT period_id, COUNT(*)
FROM agendatec_requests
GROUP BY period_id;
```

**Resultado esperado:**
- Período 1: "Ago-Dic 2025", INACTIVE, con todas las solicitudes antiguas
- Período 2: "Ene-Jun 2026", ACTIVE, sin solicitudes aún

### 1.4 Listar períodos con comando Flask

```bash
flask list-periods
```

**✅ Verificar output esperado:**
```
📋 Períodos Académicos:

🟢 Ene-Jun 2026 (ID: 2)
   Estado: ACTIVE
   Rango: 2026-01-19 → 2026-06-12
   Admisión hasta: 2026-01-27 18:00:00-07:00
   Días habilitados: 3
   Solicitudes: 0

⚪ Ago-Dic 2025 (ID: 1)
   Estado: INACTIVE
   Rango: 2025-08-19 → 2025-12-13
   Admisión hasta: 2025-08-27 18:00:00-07:00
   Días habilitados: 3
   Solicitudes: X
```

---

## Fase 2: APIs Backend

### 2.1 API: Listar períodos

**Request:**
```bash
curl -X GET http://localhost:5000/api/agendatec/v1/periods \
  -H "Cookie: itcj_token=TU_TOKEN_ADMIN" \
  | jq
```

**✅ Verificar respuesta:**
```json
{
  "items": [
    {
      "id": 2,
      "name": "Ene-Jun 2026",
      "start_date": "2026-01-19",
      "end_date": "2026-06-12",
      "student_admission_deadline": "2026-01-27T18:00:00-07:00",
      "status": "ACTIVE",
      "request_count": 0
    },
    {
      "id": 1,
      "name": "Ago-Dic 2025",
      "start_date": "2025-08-19",
      "end_date": "2025-12-13",
      "student_admission_deadline": "2025-08-27T18:00:00-07:00",
      "status": "INACTIVE",
      "request_count": X
    }
  ]
}
```

### 2.2 API: Obtener período activo (público)

**Request:**
```bash
curl -X GET http://localhost:5000/api/agendatec/v1/periods/active | jq
```

**✅ Verificar respuesta:**
```json
{
  "period": {
    "id": 2,
    "name": "Ene-Jun 2026",
    "start_date": "2026-01-19",
    "end_date": "2026-06-12",
    "student_admission_deadline": "2026-01-27T18:00:00-07:00",
    "status": "ACTIVE",
    "is_student_window_open": true
  },
  "enabled_days": [
    "2026-01-26",
    "2026-01-27",
    "2026-01-28"
  ]
}
```

### 2.3 API: Crear nuevo período

**Request:**
```bash
curl -X POST http://localhost:5000/api/agendatec/v1/periods \
  -H "Cookie: itcj_token=TU_TOKEN_ADMIN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Verano 2026",
    "start_date": "2026-06-15",
    "end_date": "2026-08-07",
    "student_admission_deadline": "2026-06-20T18:00:00-07:00",
    "status": "INACTIVE"
  }' | jq
```

**✅ Verificar respuesta:**
```json
{
  "ok": true,
  "period": {
    "id": 3,
    "name": "Verano 2026",
    ...
  }
}
```

### 2.4 API: Configurar días habilitados

**Request:**
```bash
curl -X POST http://localhost:5000/api/agendatec/v1/periods/3/enabled-days \
  -H "Cookie: itcj_token=TU_TOKEN_ADMIN" \
  -H "Content-Type: application/json" \
  -d '{
    "days": ["2026-06-16", "2026-06-17", "2026-06-18"]
  }' | jq
```

**✅ Verificar respuesta:**
```json
{
  "ok": true,
  "period_id": 3,
  "enabled_days_count": 3,
  "days": [
    {"id": X, "day": "2026-06-16"},
    {"id": X, "day": "2026-06-17"},
    {"id": X, "day": "2026-06-18"}
  ]
}
```

### 2.5 API: Activar período

**Request:**
```bash
curl -X POST http://localhost:5000/api/agendatec/v1/periods/3/activate \
  -H "Cookie: itcj_token=TU_TOKEN_ADMIN" | jq
```

**✅ Verificar respuesta:**
```json
{
  "ok": true,
  "period": {
    "id": 3,
    "name": "Verano 2026",
    "status": "ACTIVE"
  },
  "previous_period": {
    "id": 2,
    "name": "Ene-Jun 2026",
    "status": "INACTIVE"
  }
}
```

**🔍 Verificar cambio en DB:**
```sql
SELECT id, name, status FROM core_academic_periods;
```
- Solo el período 3 debe tener status='ACTIVE'

### 2.6 API: Estadísticas de período

**Request:**
```bash
curl -X GET http://localhost:5000/api/agendatec/v1/periods/1/stats \
  -H "Cookie: itcj_token=TU_TOKEN_ADMIN" | jq
```

**✅ Verificar respuesta:**
```json
{
  "period_id": 1,
  "period_name": "Ago-Dic 2025",
  "total_requests": X,
  "pending_requests": X,
  "resolved_requests": X,
  "enabled_days_count": 3,
  "enabled_days": [
    "2025-08-25",
    "2025-08-26",
    "2025-08-27"
  ]
}
```

---

## Fase 3: Validaciones Backend

### 3.1 Validación: UNA solicitud por estudiante por período

**Escenario:** Estudiante con solicitud PENDING en período activo

**Test 1: Intento de crear segunda solicitud**
```bash
# Login como estudiante que ya tiene una solicitud PENDING
# Intentar crear una nueva solicitud
curl -X POST http://localhost:5000/api/agendatec/v1/requests \
  -H "Cookie: itcj_token=TU_TOKEN_ESTUDIANTE" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "APPOINTMENT",
    "program_id": 1,
    "slot_id": 123,
    "description": "Solicitud de alta"
  }' | jq
```

**✅ Verificar respuesta (debe rechazar):**
```json
{
  "error": "already_has_request_in_period",
  "message": "Ya tienes una solicitud en el período 'Ene-Jun 2026'.",
  "existing_request_id": X,
  "existing_request_status": "PENDING"
}
```
**Status Code:** 409 Conflict

**Test 2: Estudiante con solicitud CANCELED puede crear otra**
```sql
-- Cambiar solicitud a CANCELED
UPDATE agendatec_requests SET status = 'CANCELED' WHERE id = X;
```
```bash
# Intentar crear nueva solicitud
# Ahora SÍ debe permitirlo
```

**✅ Verificar:** Status 200 OK, solicitud creada correctamente

### 3.2 Validación: Días habilitados dinámicos

**Test 1: Intentar crear solicitud en día NO habilitado**
```bash
curl -X POST http://localhost:5000/api/agendatec/v1/requests \
  -H "Cookie: itcj_token=TU_TOKEN_ESTUDIANTE" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "APPOINTMENT",
    "program_id": 1,
    "slot_id": 999,
    "description": "Solicitud"
  }' | jq
# Donde slot_id corresponde a un día NO habilitado
```

**✅ Verificar respuesta:**
```json
{
  "error": "day_not_enabled",
  "message": "El día seleccionado no está habilitado para este período",
  "enabled_days": ["2026-01-26", "2026-01-27", "2026-01-28"]
}
```
**Status Code:** 400 Bad Request

### 3.3 Validación: No hay período activo

**Test:**
```sql
-- Desactivar todos los períodos
UPDATE core_academic_periods SET status = 'INACTIVE';
```
```bash
# Intentar crear solicitud
curl -X POST http://localhost:5000/api/agendatec/v1/requests \
  -H "Cookie: itcj_token=TU_TOKEN_ESTUDIANTE" \
  -H "Content-Type: application/json" \
  -d '{...}' | jq
```

**✅ Verificar respuesta:**
```json
{
  "error": "no_active_period",
  "message": "No hay un período académico activo"
}
```
**Status Code:** 503 Service Unavailable

### 3.4 Validación: Cancelación - Período cerrado

**Test:**
```sql
-- Activar período y cerrarlo (cambiar a ARCHIVED)
UPDATE core_academic_periods SET status = 'ARCHIVED' WHERE id = 2;
```
```bash
# Login como estudiante con solicitud PENDING en ese período
# Intentar cancelar la solicitud
curl -X PATCH http://localhost:5000/api/agendatec/v1/requests/X/cancel \
  -H "Cookie: itcj_token=TU_TOKEN_ESTUDIANTE" | jq
```

**✅ Verificar respuesta:**
```json
{
  "error": "period_closed",
  "message": "No se puede cancelar porque el período 'Ene-Jun 2026' ya cerró."
}
```
**Status Code:** 403 Forbidden

### 3.5 Validación: Cancelación - Cita ya pasó

**Test:**
```sql
-- Crear un slot en el pasado para testing
INSERT INTO agendatec_time_slots (coordinator_id, day, start_time, end_time, is_booked)
VALUES (1, '2025-01-15', '09:00', '09:30', true);

-- Crear appointment en el pasado
INSERT INTO agendatec_appointments (request_id, student_id, program_id, coordinator_id, slot_id, status)
VALUES (X, Y, 1, 1, SLOT_ID_DEL_PASADO, 'SCHEDULED');
```
```bash
# Intentar cancelar
curl -X PATCH http://localhost:5000/api/agendatec/v1/requests/X/cancel \
  -H "Cookie: itcj_token=TU_TOKEN_ESTUDIANTE" | jq
```

**✅ Verificar respuesta:**
```json
{
  "error": "appointment_time_passed",
  "message": "No se puede cancelar porque la cita ya pasó."
}
```
**Status Code:** 403 Forbidden

---

## Fase 4: Interfaz Admin

### 4.1 Pantalla: Gestión de Períodos

**Navegación:**
1. Login como admin: http://localhost:5000/login
2. Ir a: http://localhost:5000/agendatec/admin/periods

**✅ Verificar elementos visuales:**
- [ ] Título: "Períodos Académicos"
- [ ] Filtro por estado (ACTIVE/INACTIVE/ARCHIVED)
- [ ] Botón "Nuevo Período"
- [ ] Tabla con columnas:
  - Nombre
  - Inicio
  - Fin
  - Fecha Límite Admisión
  - Estado (badge de color)
  - Solicitudes (count)
  - Acciones (botones)

**Test 1: Crear nuevo período**
1. Click en "Nuevo Período"
2. Modal se abre
3. Llenar formulario:
   - Nombre: "Test Período"
   - Fecha inicio: 2027-01-19
   - Fecha fin: 2027-06-12
   - Fecha límite: 2027-01-25
   - Hora límite: 18:00
   - Estado: INACTIVE
4. Click "Guardar"

**✅ Verificar:**
- [ ] Modal se cierra
- [ ] Mensaje de éxito
- [ ] Tabla se recarga automáticamente
- [ ] Nuevo período aparece en la lista

**Test 2: Editar período**
1. Click en botón "Editar" (ícono lápiz) de un período INACTIVE
2. Modal se abre con datos prellenados
3. Cambiar nombre: "Test Período Editado"
4. Click "Guardar"

**✅ Verificar:**
- [ ] Cambio se refleja en la tabla
- [ ] Mensaje de éxito

**Test 3: Ver detalles**
1. Click en botón "Ver detalles" (ícono ojo)
2. Modal se abre

**✅ Verificar información mostrada:**
- [ ] Nombre, estado, fechas
- [ ] Estadísticas: Total solicitudes, Pendientes, Resueltas
- [ ] Días habilitados (badges)

**Test 4: Activar período**
1. Tener un período INACTIVE con días habilitados
2. Click en botón "Activar" (ícono check verde)
3. Confirmar en diálogo

**✅ Verificar:**
- [ ] Período cambia a ACTIVE
- [ ] Período anterior pasa a INACTIVE
- [ ] Badge de estado se actualiza
- [ ] Mensaje de éxito

**Test 5: Eliminar período**
1. Crear período sin solicitudes
2. Click en botón "Eliminar" (ícono basura rojo)
3. Confirmar eliminación

**✅ Verificar:**
- [ ] Período desaparece de la tabla
- [ ] Mensaje de éxito

**Test 6: Intentar eliminar período con solicitudes**
1. Click en "Eliminar" de período con solicitudes
2. Confirmar

**✅ Verificar:**
- [ ] Error amigable: "No se puede eliminar, tiene solicitudes asociadas"
- [ ] Período NO se elimina

### 4.2 Pantalla: Configurar Días Habilitados

**Navegación:**
1. En la tabla de períodos, click en "Configurar días" (ícono calendario)
2. URL: http://localhost:5000/agendatec/admin/periods/2/days

**✅ Verificar elementos visuales:**
- [ ] Botón "Volver a Períodos"
- [ ] Título: "Configurar Días Habilitados"
- [ ] Subtítulo con nombre del período
- [ ] Calendario inline de Flatpickr
- [ ] Panel derecho: "Días Seleccionados (X)"
- [ ] Botón "Limpiar Todo"
- [ ] Botón "Guardar Cambios"
- [ ] Card de estadísticas

**Test 1: Seleccionar días en calendario**
1. Click en varios días del calendario
2. Días se resaltan en azul

**✅ Verificar:**
- [ ] Días aparecen en lista "Días Seleccionados"
- [ ] Contador se actualiza
- [ ] Formato: "mié, 26 de ene de 2026"
- [ ] Cada día tiene botón "Eliminar"

**Test 2: Eliminar día individual**
1. Click en botón basura de un día seleccionado

**✅ Verificar:**
- [ ] Día desaparece de la lista
- [ ] Calendario se actualiza (día se desmarca)
- [ ] Contador disminuye

**Test 3: Limpiar todos los días**
1. Tener varios días seleccionados
2. Click en "Limpiar Todo"
3. Confirmar

**✅ Verificar:**
- [ ] Todos los días desaparecen
- [ ] Calendario se limpia
- [ ] Contador muestra 0
- [ ] Mensaje: "No hay días seleccionados"

**Test 4: Guardar cambios**
1. Seleccionar 3 días
2. Click en "Guardar Cambios"

**✅ Verificar:**
- [ ] Mensaje de éxito: "Días guardados correctamente"
- [ ] Estadísticas se actualizan
- [ ] Advertencia si se intenta salir sin guardar (beforeunload)

**Test 5: Restricción de rango de fechas**
1. Verificar que el calendario:

**✅ Verificar:**
- [ ] minDate = start_date del período
- [ ] maxDate = end_date del período
- [ ] No se pueden seleccionar fechas fuera del rango
- [ ] Fechas deshabilitadas se ven grises

**Test 6: Guardar sin días (eliminar todos)**
1. Limpiar todos los días
2. Click en "Guardar Cambios"
3. Confirmar advertencia

**✅ Verificar:**
- [ ] Alerta de confirmación: "Vas a eliminar TODOS los días"
- [ ] Si confirma: días se guardan (vacío)
- [ ] Estudiantes no podrán crear solicitudes

---

## Fase 5: Interfaz Estudiantes

### 5.1 Pantalla: Nueva Solicitud

**Navegación:**
1. Login como estudiante
2. Ir a: http://localhost:5000/agendatec/student/new-request

**✅ Verificar carga inicial:**
- [ ] Mensaje: "Cargando días habilitados..."
- [ ] Después de 1-2 seg: botones de días aparecen dinámicamente
- [ ] Cantidad de botones = días habilitados en período activo
- [ ] Formato de botón:
  ```
  [  lun  ]
  [  26   ]
  [ ene   ]
  ```

**Test 1: Flujo completo de solicitud**
1. Seleccionar tipo: "Alta"
2. Seleccionar carrera
3. Llenar formulario (materia, horario)
4. Click "Confirmar detalles"
5. **Verificar días mostrados:**

**✅ Verificar:**
- [ ] Solo aparecen días habilitados del período activo
- [ ] Si período activo = Ene-Jun 2026, muestra: 26, 27, 28 ene
- [ ] NO muestra días hardcodeados (25, 26, 27 ago)
- [ ] Días formateados correctamente en español

6. Seleccionar un día
7. Seleccionar horario
8. Click "Confirmar y Agendar"

**✅ Verificar:**
- [ ] Solicitud se crea correctamente
- [ ] Mensaje de éxito
- [ ] Redirige a "Mis solicitudes"

**Test 2: No hay período activo**
1. Desactivar todos los períodos:
   ```sql
   UPDATE core_academic_periods SET status = 'INACTIVE';
   ```
2. Recargar página de nueva solicitud

**✅ Verificar:**
- [ ] Mensaje de error: "No hay período activo disponible. Contacta al administrador."
- [ ] NO aparecen botones de días
- [ ] Flujo se deshabilita

**Test 3: Intento de segunda solicitud en mismo período**
1. Crear solicitud APPOINTMENT exitosamente
2. Intentar crear otra solicitud (misma página o refrescar)
3. Llenar formulario y enviar

**✅ Verificar:**
- [ ] Toast de error: "Ya tienes una solicitud activa en este período"
- [ ] Status 409
- [ ] Solicitud NO se crea

**Test 4: Estudiante con solicitud CANCELED puede crear otra**
1. Tener solicitud en estado CANCELED
2. Crear nueva solicitud

**✅ Verificar:**
- [ ] Solicitud se crea exitosamente
- [ ] No hay error de "ya tienes solicitud"

### 5.2 Pantalla: Mis Solicitudes

**Navegación:**
1. Login como estudiante
2. Ir a: http://localhost:5000/agendatec/student/requests

**Test: Ver solicitud activa**

**✅ Verificar:**
- [ ] Solicitud activa muestra período correcto
- [ ] Información de cita con fecha/hora correcta
- [ ] Estado de solicitud visible

**Test: Cancelar solicitud**
1. Click en "Cancelar solicitud"
2. Confirmar

**✅ Verificar:**
- [ ] Solicitud cambia a CANCELED
- [ ] Mensaje de éxito
- [ ] Slot se libera (is_booked = false)

---

## Fase 6: Integración Completa

### 6.1 Escenario: Cambio de semestre

**Objetivo:** Simular el cambio de período académico entre semestres

**Paso 1: Período activo actual (Ene-Jun 2026)**
- Estudiante A crea solicitud APPOINTMENT
- Estudiante B crea solicitud DROP
- Coordinador responde algunas solicitudes

**Paso 2: Cerrar período actual**
```bash
# Como admin
flask activate-period 4  # Activar siguiente período
```

O desde interfaz:
1. Login como admin
2. Ir a /agendatec/admin/periods
3. Click "Activar" en período siguiente

**✅ Verificar:**
- [ ] Período actual pasa a INACTIVE
- [ ] Nuevo período pasa a ACTIVE
- [ ] Solicitudes del período anterior NO desaparecen
- [ ] Mantienen su period_id original

**Paso 3: Nuevo período activo**
1. Configurar días habilitados (e.g., 10, 11, 12 ago 2027)
2. Login como estudiante C (nuevo)
3. Intentar crear solicitud

**✅ Verificar:**
- [ ] Ve días del nuevo período (10, 11, 12 ago)
- [ ] NO ve días del período anterior
- [ ] Puede crear solicitud exitosamente
- [ ] Solicitud tiene period_id del nuevo período

**Paso 4: Estudiante A (del período anterior)**
1. Login como Estudiante A
2. Ir a "Mis solicitudes"

**✅ Verificar:**
- [ ] Ve su solicitud anterior en "Historial"
- [ ] Puede crear NUEVA solicitud en el período actual
- [ ] Tiene 1 solicitud por cada período

### 6.2 Escenario: Coordinador - Vista por período

**Test:**
1. Login como coordinador
2. Ir a dashboard coordinador
3. Verificar estadísticas

**✅ Verificar:**
- [ ] Dashboard usa días habilitados del período activo
- [ ] No usa ALLOWED_DAYS hardcodeado
- [ ] Estadísticas correctas
- [ ] Lista de citas filtra por período actual

### 6.3 Escenario: Admin - Reportes

**Test:**
1. Login como admin
2. Ir a reportes/estadísticas

**✅ Verificar:**
- [ ] Puede filtrar por período
- [ ] Exportar datos incluye period_id
- [ ] Reportes históricos funcionan

---

## Checklist Final

### ✅ Base de Datos
- [ ] Migración aplicada exitosamente
- [ ] Tablas `core_academic_periods` y `agendatec_period_enabled_days` existen
- [ ] Columna `period_id` en `agendatec_requests` (nullable, FK)
- [ ] Permisos del módulo periods creados (9 permisos)
- [ ] Períodos iniciales creados (Ago-Dic 2025, Ene-Jun 2026)
- [ ] Solicitudes existentes migradas al primer período

### ✅ APIs Backend (Fase 3)
- [ ] GET /periods - Lista períodos ✓
- [ ] POST /periods - Crea período ✓
- [ ] GET /periods/:id - Obtiene período ✓
- [ ] PATCH /periods/:id - Actualiza período ✓
- [ ] DELETE /periods/:id - Elimina período (sin solicitudes) ✓
- [ ] POST /periods/:id/activate - Activa período ✓
- [ ] GET /periods/active - Obtiene período activo (público) ✓
- [ ] GET /periods/:id/enabled-days - Lista días habilitados ✓
- [ ] POST /periods/:id/enabled-days - Configura días habilitados ✓
- [ ] GET /periods/:id/stats - Estadísticas del período ✓

### ✅ Validaciones Backend (Fase 4)
- [ ] routes/api/requests.py usa días dinámicos
- [ ] Validación: UNA solicitud por estudiante por período (excluye CANCELED)
- [ ] Validación: day_not_enabled si día no está habilitado
- [ ] Validación: no_active_period si no hay período activo
- [ ] Validación cancelación: period_closed si período cerró
- [ ] Validación cancelación: appointment_time_passed si cita pasó
- [ ] routes/api/slots.py usa días dinámicos
- [ ] routes/api/availability.py usa días dinámicos
- [ ] routes/api/coord.py usa días dinámicos
- [ ] ALLOWED_DAYS eliminado de todos los archivos backend

### ✅ Interfaz Admin (Fase 5)
- [ ] Página /admin/periods funciona
- [ ] Tabla muestra todos los períodos
- [ ] Filtro por estado funciona
- [ ] Modal crear período funciona
- [ ] Modal editar período funciona
- [ ] Modal ver detalles con estadísticas funciona
- [ ] Botón activar período funciona
- [ ] Botón eliminar período funciona (con validación)
- [ ] Navegación a configurar días funciona
- [ ] Página /admin/periods/:id/days funciona
- [ ] Calendario Flatpickr se carga correctamente
- [ ] Selección múltiple de días funciona
- [ ] Guardar días habilitados funciona
- [ ] Restricción de rango de fechas funciona
- [ ] Estadísticas en tiempo real funcionan

### ✅ Interfaz Estudiantes (Fase 6)
- [ ] Botones de días se generan dinámicamente
- [ ] Solo muestra días del período activo
- [ ] Formato de fechas en español mexicano
- [ ] Mensajes de error actualizados:
  - already_has_request_in_period
  - no_active_period
  - day_not_enabled
- [ ] Flujo completo de crear solicitud funciona
- [ ] Restricción: una solicitud por período funciona
- [ ] Cancelación con validaciones funciona

### ✅ Comandos Flask (Fase 7)
- [ ] flask seed-periods funciona
- [ ] flask activate-period <id> funciona
- [ ] flask list-periods funciona
- [ ] Comandos registrados en itcj/__init__.py

### ✅ Integración Completa
- [ ] Cambio de período académico funciona end-to-end
- [ ] Estudiantes ven días correctos según período activo
- [ ] Coordinadores ven citas del período actual
- [ ] Admin puede gestionar múltiples períodos
- [ ] Migración de datos históricos preservada
- [ ] No hay referencias a ALLOWED_DAYS hardcodeado

---

## 📝 Notas para el Usuario

### Comandos útiles durante testing

```bash
# Ver logs de Flask
tail -f logs/flask.log

# Ver queries SQL (si está habilitado)
export SQLALCHEMY_ECHO=True

# Verificar período activo rápidamente
flask list-periods

# Reiniciar períodos (⚠️ CUIDADO: borra datos)
flask db downgrade
flask db upgrade
flask seed-periods

# Ver estado de Redis
redis-cli
> KEYS slot_hold:*
> GET slot_hold:123
```

### Problemas comunes y soluciones

**Problema:** Migración falla con error de Redis
```
Solution: Iniciar Redis primero
docker-compose up -d redis
```

**Problema:** Permisos no aplicados correctamente
```
Solution: Ejecutar scripts SQL manualmente
psql -U user -d db -f database/DML/agendatec/periodos/01_insert_permissions_periods.sql
```

**Problema:** Estudiantes no ven días
```
Solution: Verificar período activo y días habilitados
flask list-periods
curl http://localhost:5000/api/agendatec/v1/periods/active
```

**Problema:** Días hardcodeados aún aparecen
```
Solution: Limpiar caché del navegador (Ctrl+Shift+R)
Verificar que request.js fue actualizado
```

---

## 🎯 Criterios de Aceptación Final

El sistema de períodos académicos está completo cuando:

1. ✅ Se puede crear un nuevo período académico desde la interfaz admin
2. ✅ Se pueden configurar días habilitados usando el calendario visual
3. ✅ Los estudiantes solo ven días del período activo actual
4. ✅ Un estudiante solo puede tener UNA solicitud activa por período
5. ✅ No se puede cancelar solicitud si el período cerró o la cita pasó
6. ✅ Se puede cambiar de período activo sin perder datos históricos
7. ✅ NO existen referencias a ALLOWED_DAYS hardcodeado
8. ✅ Todas las APIs responden correctamente con validaciones
9. ✅ Comandos Flask funcionan para gestión de períodos
10. ✅ La aplicación es reutilizable semestre tras semestre

---

**Fecha de creación:** 2026-01-09
**Versión:** 1.0
**Autor:** Claude Code Assistant
**Proyecto:** AgendaTec - Sistema de Períodos Académicos
