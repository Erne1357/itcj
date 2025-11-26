# Configuración de Notificaciones - Help Desk

Este documento describe la configuración de notificaciones para la aplicación Help Desk.

## Arquitectura de Notificaciones

Las notificaciones de Help Desk utilizan el sistema centralizado de notificaciones de ITCJ Core:
- **Servicio**: `itcj.core.services.notification_service.NotificationService`
- **Helper**: `itcj.apps.helpdesk.services.notification_helper.HelpdeskNotificationHelper`
- **APIs**: `/api/core/v1/notifications/*`
- **Transporte**: SSE (Server-Sent Events) para actualizaciones en tiempo real

## Permisos Requeridos

### Notificaciones (Sistema Core)

Las notificaciones **NO requieren permisos específicos**. El acceso se controla a nivel de usuario:
- Cada usuario solo puede ver sus propias notificaciones
- Las APIs usan `@api_auth_required` (autenticación, no autorización)
- El filtrado por usuario se realiza automáticamente en el backend

### Roles de Help Desk

Los siguientes roles existen en Help Desk:
- **admin** - Administrador del sistema
- **secretary** - Secretaria (asigna tickets)
- **tech_desarrollo** - Técnico de Desarrollo
- **tech_soporte** - Técnico de Soporte
- **department_head** - Jefe de Departamento
- **staff** - Usuario final (solicitante)

## Tipos de Notificaciones y Destinatarios

### 1. TICKET_CREATED - Ticket Creado
**Ubicación**: `routes/api/tickets/base.py:134-142`

**Quién la recibe**:
- ✅ **secretary** - Secretarias
- ✅ **admin** - Administradores

**Cuándo**: Se crea un nuevo ticket

**Datos**:
```json
{
  "ticket_id": 123,
  "url": "/help-desk/secretary/tickets/123",
  "priority": "URGENTE",
  "area": "DESARROLLO",
  "requester": "Juan Pérez"
}
```

---

### 2. TICKET_ASSIGNED - Ticket Asignado
**Ubicación**: `routes/api/assignments.py:62-73`

**Quién la recibe**:
- ✅ **Técnico asignado** (tech_desarrollo o tech_soporte)

**Cuándo**: La secretaria asigna un ticket a un técnico específico

**Datos**:
```json
{
  "ticket_id": 123,
  "url": "/help-desk/technician/tickets/123",
  "priority": "ALTA",
  "area": "DESARROLLO"
}
```

---

### 3. TICKET_REASSIGNED - Ticket Reasignado
**Ubicación**: `routes/api/assignments.py:126-146`

**Quién la recibe**:
- ✅ **Nuevo técnico asignado**
- ✅ **Técnico anterior** (si existía)

**Cuándo**: Se reasigna un ticket a otro técnico

**Datos**:
```json
{
  "ticket_id": 123,
  "url": "/help-desk/technician/tickets/123",
  "priority": "MEDIA"
}
```

---

### 4. TICKET_IN_PROGRESS - Ticket en Progreso (Auto-asignación)
**Ubicación**:
- `routes/api/assignments.py:183-196` (Auto-asignación)
- `routes/api/tickets/base.py:290-297` (Cambio de estado)

**Quién la recibe**:
- ✅ **Solicitante** (requester)

**Cuándo**: Un técnico toma el ticket del pool o marca como "en progreso"

**Datos**:
```json
{
  "ticket_id": 123,
  "url": "/help-desk/user/tickets/123",
  "technician": "Carlos Méndez"
}
```

---

### 5. TICKET_RESOLVED - Ticket Resuelto
**Ubicación**: `routes/api/tickets/base.py:349-356`

**Quién la recibe**:
- ✅ **Solicitante** (requester)

**Cuándo**: El técnico marca el ticket como resuelto

**Datos**:
```json
{
  "ticket_id": 123,
  "url": "/help-desk/user/tickets/123",
  "resolution_status": "RESOLVED_SUCCESS"
}
```

---

### 6. TICKET_RATED - Ticket Calificado
**Ubicación**: `routes/api/tickets/base.py:431-438`

**Quién la recibe**:
- ✅ **Técnico asignado**

**Cuándo**: El solicitante califica el servicio

**Datos**:
```json
{
  "ticket_id": 123,
  "url": "/help-desk/technician/tickets/123",
  "rating_attention": 5,
  "rating_speed": 4,
  "rating_efficiency": 5
}
```

---

### 7. TICKET_CANCELED - Ticket Cancelado
**Ubicación**: `routes/api/tickets/base.py:479-486`

**Quién la recibe**:
- ✅ **Técnico asignado** (si existe)

**Cuándo**: El solicitante cancela el ticket

**Datos**:
```json
{
  "ticket_id": 123,
  "url": "/help-desk/technician/tickets/123"
}
```

---

### 8. TICKET_COMMENT - Nuevo Comentario
**Ubicación**:
- `routes/api/comments.py:128-137`
- `routes/api/tickets/comments.py:108-119`

**Quién la recibe**:
- ✅ **Solicitante** (si no es el autor)
- ✅ **Técnico asignado** (si no es el autor)
- ✅ **Colaboradores** (si no es el autor y el comentario no es interno)

**Cuándo**: Se agrega un comentario al ticket

**Datos**:
```json
{
  "ticket_id": 123,
  "url": "/help-desk/user/tickets/123#comment-456",
  "comment_id": 456,
  "author": "María López"
}
```

---

## Matriz de Notificaciones por Rol

| Tipo de Notificación | admin | secretary | tech_* | staff | dept_head |
|----------------------|-------|-----------|--------|-------|-----------|
| TICKET_CREATED       | ✅    | ✅        | ❌     | ❌    | ❌        |
| TICKET_ASSIGNED      | ❌    | ❌        | ✅     | ❌    | ❌        |
| TICKET_REASSIGNED    | ❌    | ❌        | ✅     | ❌    | ❌        |
| TICKET_IN_PROGRESS   | ❌    | ❌        | ❌     | ✅    | ❌        |
| TICKET_RESOLVED      | ❌    | ❌        | ❌     | ✅    | ❌        |
| TICKET_RATED         | ❌    | ❌        | ✅     | ❌    | ❌        |
| TICKET_CANCELED      | ❌    | ❌        | ✅     | ❌    | ❌        |
| TICKET_COMMENT       | ⚡    | ⚡        | ⚡     | ⚡    | ⚡        |

**Leyenda**:
- ✅ Siempre recibe
- ❌ Nunca recibe
- ⚡ Recibe si está involucrado (solicitante, técnico, o colaborador)

---

## Configuración de Widgets

### Dashboard Principal (`/dashboard`)
- **Widget**: Mini panel desplegable con campana
- **Badge global**: Suma de todas las notificaciones no leídas
- **Badges por app**: AgendaTec, Help Desk

### Perfil (`/profile`)
- **Vista**: Tab completo de notificaciones
- **Filtros**: Por app, por estado (leídas/no leídas), por fecha
- **Actualización**: Tiempo real via SSE

### Base de Help Desk (`/help-desk/*`)
- **Widget**: FAB flotante (esquina inferior derecha)
- **Solo notificaciones**: De Help Desk
- **Tabs**: Recientes (8), Historial (scroll infinito)

---

## Iconos y Colores por Tipo

```javascript
const notificationStyles = {
  TICKET_CREATED: {
    icon: 'bi-headset',
    color: 'primary'  // Azul
  },
  TICKET_ASSIGNED: {
    icon: 'bi-person-check',
    color: 'success'  // Verde
  },
  TICKET_REASSIGNED: {
    icon: 'bi-arrow-repeat',
    color: 'warning'  // Amarillo
  },
  TICKET_IN_PROGRESS: {
    icon: 'bi-play-circle',
    color: 'info'  // Cyan
  },
  TICKET_RESOLVED: {
    icon: 'bi-check-circle',
    color: 'success'  // Verde
  },
  TICKET_RATED: {
    icon: 'bi-star-fill',
    color: 'warning'  // Amarillo
  },
  TICKET_CANCELED: {
    icon: 'bi-x-circle',
    color: 'danger'  // Rojo
  },
  TICKET_COMMENT: {
    icon: 'bi-chat-dots',
    color: 'secondary'  // Gris
  }
}
```

---

## Verificación de Configuración

### Checklist de Implementación

- [x] NotificationService creado en core
- [x] HelpdeskNotificationHelper creado
- [x] 9 puntos de integración implementados
- [x] SSE endpoint configurado
- [x] Redis pub/sub configurado
- [x] Widget de dashboard agregado
- [x] FAB widget de helpdesk agregado
- [x] Filtros en perfil implementados
- [x] Badges en tiempo real funcionando

### Comandos de Verificación

```bash
# 1. Verificar que Redis está corriendo
redis-cli ping
# Debe retornar: PONG

# 2. Verificar endpoint SSE
curl -H "Authorization: Bearer <token>" \
  http://localhost:5000/api/core/v1/notifications/stream

# 3. Verificar conteos
curl -H "Authorization: Bearer <token>" \
  http://localhost:5000/api/core/v1/notifications/unread-counts

# 4. Crear notificación de prueba (Python shell)
from itcj.core.services.notification_service import NotificationService
NotificationService.create(
    user_id=1,
    app_name='helpdesk',
    type='TICKET_CREATED',
    title='Test Notification',
    body='This is a test'
)
```

---

## Solución de Problemas

### Las notificaciones no llegan en tiempo real
1. Verificar que Redis está corriendo
2. Verificar que el endpoint SSE está activo
3. Revisar logs del navegador (Console)
4. Verificar que el token JWT es válido

### Los badges no se actualizan
1. Verificar que `NotificationSSEClient` se inicializó
2. Revisar logs de conexión SSE en Console
3. Verificar que `updateDesktopBadges()` se está llamando

### Notificaciones duplicadas
1. Verificar que solo hay una instancia de SSE client
2. Revisar que no se están creando notificaciones duplicadas en el backend

---

## Referencias

- **Sistema Core**: `itcj/core/services/notification_service.py`
- **Helper**: `itcj/apps/helpdesk/services/notification_helper.py`
- **Cliente SSE**: `itcj/core/static/js/notifications/sse-client.js`
- **Widget Dashboard**: `itcj/core/static/js/dashboard/notification-widget.js`
- **Widget FAB**: `itcj/core/static/js/notifications/app-fab-widget.js`
