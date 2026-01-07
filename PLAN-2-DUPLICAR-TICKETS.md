# PLAN DE IMPLEMENTACIÓN #2: DUPLICACIÓN DE TICKETS

**Proyecto:** Sistema Helpdesk - ITCJ
**Fecha:** 2026-01-06
**Autor:** Análisis de sistema actual + propuesta técnica
**Prioridad:** Media
**Complejidad:** Baja-Media

---

## 📋 RESUMEN EJECUTIVO

Implementar funcionalidad de "Duplicar Ticket" que permita a los usuarios crear rápidamente un nuevo ticket basado en uno existente, pre-llenando todos los campos relevantes. Esta función es especialmente útil para problemas recurrentes que requieren la misma información.

**Problema actual:**
- Problemas recurrentes requieren que el usuario vuelva a llenar todo el formulario desde cero
- Pérdida de tiempo escribiendo la misma descripción, seleccionando la misma categoría, etc.
- Frustración del usuario al tener que reportar el mismo problema múltiples veces

**Solución propuesta:**
- Botón "Duplicar" en tickets resueltos/cerrados
- Redirección a formulario de creación con datos pre-llenados
- Tracking opcional de relación entre tickets (ticket original → duplicados)
- Indicador visual de que es un ticket duplicado
- Historial de duplicaciones para análisis de problemas recurrentes

---

## 🎯 OBJETIVOS

### Objetivos principales:
1. **Reducir tiempo de creación de tickets** en problemas recurrentes
2. **Mejorar experiencia del usuario** eliminando tareas repetitivas
3. **Mantener consistencia** en la descripción de problemas similares
4. **Identificar problemas recurrentes** para análisis de root cause

### Objetivos secundarios:
- Detectar patrones de problemas frecuentes por categoría
- Métricas de tickets duplicados para identificar áreas problemáticas
- Facilitar reportes de problemas periódicos (ej: "Licencia vencida cada año")

---

## 🏗️ ARQUITECTURA DE LA SOLUCIÓN

### Componentes a modificar/crear:

```
apps/helpdesk/
├── models/
│   └── ticket.py                      [MODIFICAR] Agregar campos de duplicación
│
├── services/
│   └── ticket_duplicate_service.py    [NUEVO] Lógica de duplicación
│
├── routes/
│   ├── api/
│   │   └── tickets/
│   │       └── base.py                [MODIFICAR] Endpoint de duplicación
│   └── pages/
│       └── user.py                    [MODIFICAR] Ruta de duplicación
│
├── templates/helpdesk/user/
│   ├── ticket_detail.html             [MODIFICAR] Botón duplicar
│   └── create_ticket.html             [MODIFICAR] Modo duplicación
│
└── static/
    └── js/
        ├── ticket_detail.js           [MODIFICAR] Lógica botón duplicar
        └── create_ticket.js           [MODIFICAR] Pre-llenado de datos
```

---

## 💾 MODIFICACIONES A BASE DE DATOS

### Opción A: Campos simples (Recomendado para MVP)

Agregar campos al modelo `Ticket` existente para tracking básico:

```python
class Ticket(db.Model):
    # ... campos existentes ...

    # NUEVOS CAMPOS
    duplicated_from_id = db.Column(db.BigInteger,
                                    db.ForeignKey('helpdesk_tickets.id'),
                                    nullable=True)
    # ID del ticket original del cual fue duplicado este ticket

    duplication_count = db.Column(db.Integer, default=0, nullable=False)
    # Cantidad de veces que este ticket ha sido duplicado

    # NUEVA RELACIÓN
    duplicated_from = db.relationship('Ticket',
                                      remote_side=[id],
                                      foreign_keys=[duplicated_from_id],
                                      backref='duplicates')
    # Permite acceder al ticket original y a todos sus duplicados

    # NUEVAS PROPIEDADES
    @property
    def is_duplicate(self):
        """Indica si este ticket es duplicado de otro"""
        return self.duplicated_from_id is not None

    @property
    def is_frequently_duplicated(self):
        """Indica si este ticket se ha duplicado muchas veces (problema recurrente)"""
        return self.duplication_count >= 3

    @property
    def duplication_chain(self):
        """Obtiene todos los tickets en la cadena de duplicación"""
        chain = []
        current = self.duplicated_from
        while current:
            chain.append(current)
            current = current.duplicated_from
        chain.reverse()
        chain.append(self)
        chain.extend(self.duplicates)
        return chain
```

**Migración SQL:**
```sql
-- Agregar campos a la tabla existente
ALTER TABLE helpdesk_tickets
ADD COLUMN duplicated_from_id BIGINT REFERENCES helpdesk_tickets(id) ON DELETE SET NULL,
ADD COLUMN duplication_count INTEGER NOT NULL DEFAULT 0;

-- Crear índice para mejorar performance
CREATE INDEX idx_tickets_duplicated_from ON helpdesk_tickets(duplicated_from_id);
CREATE INDEX idx_tickets_duplication_count ON helpdesk_tickets(duplication_count) WHERE duplication_count > 0;
```

### Opción B: Tabla de relaciones (Para tracking avanzado)

Si quieres tracking más detallado de duplicaciones:

**Nueva tabla:** `helpdesk_ticket_duplications`

```python
class TicketDuplication(db.Model):
    """
    Tabla para trackear relaciones de duplicación con metadatos.
    Útil para análisis de problemas recurrentes.
    """
    __tablename__ = 'helpdesk_ticket_duplications'

    id = db.Column(db.BigInteger, primary_key=True)

    # Relación
    original_ticket_id = db.Column(db.BigInteger,
                                   db.ForeignKey('helpdesk_tickets.id'),
                                   nullable=False)
    duplicate_ticket_id = db.Column(db.BigInteger,
                                    db.ForeignKey('helpdesk_tickets.id'),
                                    nullable=False)

    # Metadata
    duplicated_by_id = db.Column(db.BigInteger,
                                 db.ForeignKey('core_users.id'),
                                 nullable=False)
    duplicated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Diferencias (opcional)
    modified_fields = db.Column(db.JSON, nullable=True)
    # Ejemplo: {"description": true, "priority": true, "location": false}

    # Relaciones
    original_ticket = db.relationship('Ticket',
                                      foreign_keys=[original_ticket_id],
                                      backref='duplication_records')
    duplicate_ticket = db.relationship('Ticket',
                                       foreign_keys=[duplicate_ticket_id])
    duplicated_by = db.relationship('User')

    # Constraint: No duplicar duplicaciones
    __table_args__ = (
        db.UniqueConstraint('original_ticket_id', 'duplicate_ticket_id',
                           name='uq_ticket_duplication'),
        db.Index('idx_duplications_original', 'original_ticket_id'),
        db.Index('idx_duplications_duplicate', 'duplicate_ticket_id'),
    )
```

**Recomendación:** Empezar con **Opción A** (campos simples) para MVP, migrar a Opción B si se necesita análisis más profundo.

---

## 🔧 SERVICIOS (Lógica de negocio)

### TicketDuplicateService

**Archivo:** `apps/helpdesk/services/ticket_duplicate_service.py`

```python
class TicketDuplicateService:
    """Servicio para gestionar duplicación de tickets"""

    # Campos que SE duplican
    DUPLICABLE_FIELDS = [
        'area',
        'category_id',
        'title',
        'description',
        'location',
        'office_document_folio',
        'custom_fields',
        'priority',
    ]

    # Campos que NO se duplican (se resetean)
    NON_DUPLICABLE_FIELDS = [
        'id',
        'ticket_number',
        'status',
        'assigned_to_user_id',
        'assigned_to_team',
        'resolution_notes',
        'resolved_at',
        'resolved_by_id',
        'rating_attention',
        'rating_speed',
        'rating_efficiency',
        'rating_comment',
        'time_invested_minutes',
        'closed_at',
        'created_at',
        'updated_at',
    ]

    @staticmethod
    def can_duplicate_ticket(ticket_id, user_id):
        """
        Verifica si un ticket puede ser duplicado por el usuario.

        Reglas:
        - Solo el requester puede duplicar su propio ticket
        - El ticket debe estar en estado RESOLVED_* o CLOSED
        - No se pueden duplicar tickets cancelados

        Returns:
            {
                'can_duplicate': bool,
                'reason': str | None  # Si no puede, explicación
            }
        """
        ticket = Ticket.query.get(ticket_id)
        if not ticket:
            return {'can_duplicate': False, 'reason': 'Ticket no encontrado'}

        # Solo el requester puede duplicar
        if ticket.requester_id != user_id:
            return {'can_duplicate': False, 'reason': 'Solo el solicitante puede duplicar este ticket'}

        # Estados permitidos
        allowed_statuses = ['RESOLVED_SUCCESS', 'RESOLVED_FAILED', 'CLOSED']
        if ticket.status not in allowed_statuses:
            return {
                'can_duplicate': False,
                'reason': f'Solo se pueden duplicar tickets resueltos o cerrados. Estado actual: {ticket.status}'
            }

        # No duplicar tickets cancelados
        if ticket.status == 'CANCELED':
            return {'can_duplicate': False, 'reason': 'No se pueden duplicar tickets cancelados'}

        return {'can_duplicate': True, 'reason': None}

    @staticmethod
    def get_duplicate_data(ticket_id, user_id):
        """
        Obtiene los datos del ticket original para pre-llenar el formulario.

        Returns:
            {
                'can_duplicate': bool,
                'original_ticket': {
                    'id': int,
                    'ticket_number': str,
                    'title': str,
                    'status': str,
                    ...
                },
                'duplicate_data': {
                    'area': str,
                    'category_id': int,
                    'title': str,
                    'description': str,
                    'location': str,
                    'priority': str,
                    'custom_fields': dict,
                    ...
                }
            }

        Raises:
            ValueError si no se puede duplicar
        """
        # Verificar permisos
        can_duplicate = TicketDuplicateService.can_duplicate_ticket(ticket_id, user_id)
        if not can_duplicate['can_duplicate']:
            raise ValueError(can_duplicate['reason'])

        ticket = Ticket.query.get(ticket_id)

        # Extraer datos duplicables
        duplicate_data = {}
        for field in TicketDuplicateService.DUPLICABLE_FIELDS:
            if hasattr(ticket, field):
                duplicate_data[field] = getattr(ticket, field)

        # Modificar título para indicar que es duplicado
        if duplicate_data.get('title'):
            # Evitar múltiples "[DUPLICADO]" si ya es un duplicado
            if not duplicate_data['title'].startswith('[DUPLICADO]'):
                duplicate_data['title'] = f"[DUPLICADO] {duplicate_data['title']}"

        # Agregar nota al inicio de la descripción
        if duplicate_data.get('description'):
            duplicate_data['description'] = (
                f"📋 **Ticket duplicado de #{ticket.ticket_number}**\n\n"
                f"---\n\n"
                f"{duplicate_data['description']}"
            )

        # Equipos: NO duplicar automáticamente, usuario debe seleccionar de nuevo
        # (El equipo podría haber cambiado desde el ticket original)
        duplicate_data['inventory_item_ids'] = []

        return {
            'can_duplicate': True,
            'original_ticket': {
                'id': ticket.id,
                'ticket_number': ticket.ticket_number,
                'title': ticket.title,
                'status': ticket.status,
                'category': ticket.category.name if ticket.category else None,
                'created_at': ticket.created_at.isoformat(),
                'resolved_at': ticket.resolved_at.isoformat() if ticket.resolved_at else None,
            },
            'duplicate_data': duplicate_data
        }

    @staticmethod
    def create_duplicate(original_ticket_id, user_id, modifications=None):
        """
        Crea un nuevo ticket como duplicado del original.

        Args:
            original_ticket_id: ID del ticket a duplicar
            user_id: Usuario que crea el duplicado
            modifications: Dict con campos modificados por el usuario antes de crear
                          Ejemplo: {"description": "Nueva descripción...", "priority": "ALTA"}

        Returns:
            {
                'ticket': Ticket,  # Nuevo ticket creado
                'original': Ticket  # Ticket original
            }

        Raises:
            ValueError si no se puede duplicar
        """
        # Obtener datos
        duplicate_info = TicketDuplicateService.get_duplicate_data(original_ticket_id, user_id)
        duplicate_data = duplicate_info['duplicate_data']

        # Aplicar modificaciones del usuario
        if modifications:
            for key, value in modifications.items():
                if key in TicketDuplicateService.DUPLICABLE_FIELDS:
                    duplicate_data[key] = value

        # Crear ticket usando el servicio existente
        new_ticket_data = {
            **duplicate_data,
            'requester_id': user_id,
            'created_by_user_id': user_id,
            'duplicated_from_id': original_ticket_id,  # Marcar relación
        }

        # Usar ticket_service.create_ticket
        new_ticket = TicketService.create_ticket(**new_ticket_data)

        # Incrementar contador de duplicaciones en original
        original_ticket = Ticket.query.get(original_ticket_id)
        original_ticket.duplication_count += 1

        db.session.commit()

        # Registrar en StatusLog
        StatusLogService.log_event(
            ticket_id=new_ticket.id,
            event_type='CREATED_AS_DUPLICATE',
            notes=f"Ticket duplicado de #{original_ticket.ticket_number}",
            changed_by_id=user_id
        )

        # Notificación opcional al usuario
        notification_helper.send_notification(
            user_id=user_id,
            type='TICKET_DUPLICATED',
            title='Ticket duplicado creado',
            body=f'Se creó el ticket {new_ticket.ticket_number} como duplicado de #{original_ticket.ticket_number}',
            data={
                'ticket_id': new_ticket.id,
                'url': f'/help-desk/user/tickets/{new_ticket.id}'
            }
        )

        return {
            'ticket': new_ticket,
            'original': original_ticket
        }

    @staticmethod
    def get_duplication_analytics(category_id=None, department_id=None, days=30):
        """
        Obtiene métricas de duplicación para análisis.

        Returns:
            {
                'total_duplicates': int,
                'most_duplicated_tickets': [
                    {
                        'ticket': Ticket,
                        'duplication_count': int,
                        'last_duplicate_date': datetime
                    },
                    ...
                ],
                'duplication_by_category': {
                    'category_name': count,
                    ...
                },
                'avg_time_between_duplicates': float  # días
            }
        """
        # Query para tickets duplicados en el período
        query = Ticket.query.filter(
            Ticket.duplicated_from_id.isnot(None),
            Ticket.created_at >= datetime.utcnow() - timedelta(days=days)
        )

        if category_id:
            query = query.filter_by(category_id=category_id)

        if department_id:
            query = query.filter_by(requester_department_id=department_id)

        duplicates = query.all()

        # Calcular métricas
        total_duplicates = len(duplicates)

        # Tickets más duplicados
        most_duplicated = Ticket.query.filter(
            Ticket.duplication_count > 0
        ).order_by(
            Ticket.duplication_count.desc()
        ).limit(10).all()

        # Duplicaciones por categoría
        duplication_by_category = {}
        for ticket in duplicates:
            cat_name = ticket.category.name if ticket.category else 'Sin categoría'
            duplication_by_category[cat_name] = duplication_by_category.get(cat_name, 0) + 1

        return {
            'total_duplicates': total_duplicates,
            'most_duplicated_tickets': [
                {
                    'ticket': t,
                    'duplication_count': t.duplication_count,
                    'last_duplicate': max([d.created_at for d in t.duplicates]) if t.duplicates else None
                }
                for t in most_duplicated
            ],
            'duplication_by_category': duplication_by_category,
        }
```

---

## 🌐 RUTAS Y API

### API Endpoints

**Archivo:** `apps/helpdesk/routes/api/tickets/base.py` (modificar)

```python
# GET /api/help-desk/v1/tickets/:id/duplicate-data
# Obtiene datos para duplicar un ticket
@tickets_bp.route('/<int:ticket_id>/duplicate-data', methods=['GET'])
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.read.own'])
def get_duplicate_data(ticket_id):
    """
    Retorna los datos del ticket para pre-llenar el formulario de duplicación.

    Response:
    {
        "can_duplicate": true,
        "original_ticket": {
            "id": 123,
            "ticket_number": "TK-2025-0042",
            "title": "Problema con impresora",
            "status": "CLOSED"
        },
        "duplicate_data": {
            "area": "SOPORTE",
            "category_id": 5,
            "title": "[DUPLICADO] Problema con impresora",
            "description": "📋 **Ticket duplicado de #TK-2025-0042**\n\n---\n\nLa impresora no imprime...",
            "location": "Oficina 301",
            "priority": "MEDIA",
            "custom_fields": {...}
        }
    }
    """
    user_id = session.get('user_id')

    try:
        data = TicketDuplicateService.get_duplicate_data(ticket_id, user_id)
        return jsonify(data), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

# POST /api/help-desk/v1/tickets/:id/duplicate
# Crea un ticket duplicado
@tickets_bp.route('/<int:ticket_id>/duplicate', methods=['POST'])
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.create'])
def duplicate_ticket(ticket_id):
    """
    Crea un nuevo ticket como duplicado del especificado.

    Body (opcional):
    {
        "modifications": {
            "description": "Descripción modificada...",
            "priority": "ALTA",
            "location": "Nueva ubicación"
        }
    }

    Response:
    {
        "success": true,
        "ticket": {
            "id": 456,
            "ticket_number": "TK-2025-0089",
            "title": "[DUPLICADO] Problema con impresora",
            "status": "PENDING",
            "duplicated_from": "TK-2025-0042"
        }
    }
    """
    user_id = session.get('user_id')
    data = request.get_json() or {}
    modifications = data.get('modifications')

    try:
        result = TicketDuplicateService.create_duplicate(
            original_ticket_id=ticket_id,
            user_id=user_id,
            modifications=modifications
        )

        return jsonify({
            'success': True,
            'ticket': {
                'id': result['ticket'].id,
                'ticket_number': result['ticket'].ticket_number,
                'title': result['ticket'].title,
                'status': result['ticket'].status,
                'duplicated_from': result['original'].ticket_number
            }
        }), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

# GET /api/help-desk/v1/tickets/:id/duplicates
# Lista todos los duplicados de un ticket
@tickets_bp.route('/<int:ticket_id>/duplicates', methods=['GET'])
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.read.own'])
def get_ticket_duplicates(ticket_id):
    """
    Retorna todos los tickets duplicados de este ticket.

    Response:
    {
        "original": {...},
        "duplicates": [
            {
                "id": 456,
                "ticket_number": "TK-2025-0089",
                "title": "[DUPLICADO] ...",
                "status": "PENDING",
                "created_at": "2025-01-05T10:30:00",
                "requester": "Juan Pérez"
            },
            ...
        ],
        "duplication_count": 3
    }
    """
    ticket = Ticket.query.get_or_404(ticket_id)
    user_id = session.get('user_id')

    # Verificar permisos
    if not TicketService.can_user_view_ticket(ticket, user_id):
        return jsonify({'error': 'No autorizado'}), 403

    duplicates_data = [
        {
            'id': dup.id,
            'ticket_number': dup.ticket_number,
            'title': dup.title,
            'status': dup.status,
            'created_at': dup.created_at.isoformat(),
            'requester': dup.requester.full_name if dup.requester else None
        }
        for dup in ticket.duplicates
    ]

    return jsonify({
        'original': {
            'id': ticket.id,
            'ticket_number': ticket.ticket_number,
            'title': ticket.title,
        },
        'duplicates': duplicates_data,
        'duplication_count': ticket.duplication_count
    }), 200
```

### Páginas HTML

**Archivo:** `apps/helpdesk/routes/pages/user.py` (modificar)

```python
# GET /help-desk/user/tickets/:id/duplicate
# Página de crear ticket con datos pre-llenados
@user_bp.route('/user/tickets/<int:ticket_id>/duplicate', methods=['GET'])
@page_app_required('helpdesk', perms=['helpdesk.tickets.page.create'])
def duplicate_ticket_page(ticket_id):
    """
    Redirige a la página de crear ticket con parámetro de duplicación.
    El frontend cargará los datos via API.
    """
    user_id = session.get('user_id')

    # Verificar que puede duplicar
    can_duplicate = TicketDuplicateService.can_duplicate_ticket(ticket_id, user_id)
    if not can_duplicate['can_duplicate']:
        flash(can_duplicate['reason'], 'error')
        return redirect(url_for('helpdesk_user.ticket_detail', ticket_id=ticket_id))

    # Redirigir a crear con parámetro
    return redirect(url_for('helpdesk_user.create_ticket', duplicate_from=ticket_id))
```

---

## 🎨 TEMPLATES Y UI

### 1. Modificar ticket_detail.html

Agregar botón "Duplicar" en la sección de acciones del ticket.

**Ubicación:** Junto a los botones de "Cancelar", "Calificar", etc.

```html
<!-- En templates/helpdesk/user/ticket_detail.html -->

<div class="ticket-actions">
    <!-- Botones existentes: Cancelar, Calificar, etc. -->

    <!-- NUEVO: Botón Duplicar -->
    {% if ticket.status in ['RESOLVED_SUCCESS', 'RESOLVED_FAILED', 'CLOSED'] and
          ticket.requester_id == current_user.id %}
    <button id="btn-duplicate-ticket"
            class="btn btn-outline-secondary"
            data-ticket-id="{{ ticket.id }}">
        <i class="fas fa-copy"></i> Duplicar Ticket
    </button>
    {% endif %}
</div>

<!-- Badge de duplicado (si este ticket es un duplicado) -->
{% if ticket.is_duplicate %}
<div class="alert alert-info mb-3">
    <i class="fas fa-clone"></i>
    Este ticket es un duplicado de
    <a href="{{ url_for('helpdesk_user.ticket_detail', ticket_id=ticket.duplicated_from.id) }}">
        {{ ticket.duplicated_from.ticket_number }}
    </a>
</div>
{% endif %}

<!-- Sección de duplicados (si este ticket ha sido duplicado) -->
{% if ticket.duplication_count > 0 %}
<div class="card mb-3">
    <div class="card-header">
        <i class="fas fa-clone"></i>
        Tickets Duplicados ({{ ticket.duplication_count }})
    </div>
    <div class="card-body">
        <p class="text-muted mb-2">
            Este ticket ha sido duplicado {{ ticket.duplication_count }} veces.
            Esto puede indicar un problema recurrente.
        </p>
        <div id="duplicates-list">
            <!-- Cargado via AJAX -->
            <div class="spinner-border spinner-border-sm" role="status"></div>
            Cargando duplicados...
        </div>
    </div>
</div>
{% endif %}
```

### 2. Modificar create_ticket.html

Agregar banner informativo y lógica de pre-llenado cuando viene de duplicación.

```html
<!-- En templates/helpdesk/user/create_ticket.html -->

<!-- NUEVO: Banner de duplicación -->
<div id="duplication-banner" class="alert alert-warning" style="display: none;">
    <div class="d-flex align-items-center">
        <i class="fas fa-clone fa-2x me-3"></i>
        <div class="flex-grow-1">
            <h5 class="mb-1">Duplicando Ticket</h5>
            <p class="mb-0">
                Estás creando un ticket basado en
                <strong id="original-ticket-number"></strong>.
                Los campos se han pre-llenado con la información del ticket original.
                Puedes modificar cualquier campo antes de crear el ticket.
            </p>
        </div>
        <button type="button" class="btn-close" onclick="cancelDuplication()"></button>
    </div>
</div>

<!-- Formulario existente -->
<form id="create-ticket-form">
    <!-- Campos existentes... -->

    <!-- Campo oculto para tracking -->
    <input type="hidden" id="duplicated-from-id" name="duplicated_from_id" value="">
</form>
```

### 3. JavaScript para duplicación

**Archivo:** `static/js/ticket_detail.js` (modificar)

```javascript
// Botón duplicar
document.getElementById('btn-duplicate-ticket')?.addEventListener('click', async function() {
    const ticketId = this.dataset.ticketId;

    // Confirmar con el usuario
    const confirmed = await Swal.fire({
        title: '¿Duplicar este ticket?',
        html: `
            Se abrirá el formulario de crear ticket con los datos pre-llenados.<br>
            <small class="text-muted">Podrás modificar cualquier campo antes de crear el ticket.</small>
        `,
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Sí, duplicar',
        cancelButtonText: 'Cancelar'
    });

    if (confirmed.isConfirmed) {
        // Redirigir a crear ticket con parámetro
        window.location.href = `/help-desk/user/create?duplicate_from=${ticketId}`;
    }
});

// Cargar lista de duplicados via AJAX
if (document.getElementById('duplicates-list')) {
    loadDuplicates();
}

async function loadDuplicates() {
    const ticketId = /* obtener del DOM */;
    const response = await fetch(`/api/help-desk/v1/tickets/${ticketId}/duplicates`);
    const data = await response.json();

    const container = document.getElementById('duplicates-list');
    if (data.duplicates.length === 0) {
        container.innerHTML = '<p class="text-muted mb-0">No hay duplicados todavía.</p>';
        return;
    }

    // Renderizar lista
    const html = `
        <ul class="list-group">
            ${data.duplicates.map(dup => `
                <li class="list-group-item d-flex justify-content-between align-items-center">
                    <div>
                        <a href="/help-desk/user/tickets/${dup.id}">
                            ${dup.ticket_number}
                        </a>
                        <small class="text-muted d-block">${dup.title}</small>
                    </div>
                    <span class="badge bg-${getStatusColor(dup.status)}">
                        ${dup.status}
                    </span>
                </li>
            `).join('')}
        </ul>
    `;
    container.innerHTML = html;
}
```

**Archivo:** `static/js/create_ticket.js` (modificar)

```javascript
// Al cargar la página, verificar si es duplicación
window.addEventListener('DOMContentLoaded', async function() {
    const urlParams = new URLSearchParams(window.location.search);
    const duplicateFrom = urlParams.get('duplicate_from');

    if (duplicateFrom) {
        await loadDuplicateData(duplicateFrom);
    }
});

async function loadDuplicateData(ticketId) {
    try {
        // Mostrar spinner
        showLoadingOverlay('Cargando datos del ticket...');

        // Obtener datos via API
        const response = await fetch(`/api/help-desk/v1/tickets/${ticketId}/duplicate-data`);
        const data = await response.json();

        if (!data.can_duplicate) {
            Swal.fire('Error', data.error || 'No se puede duplicar este ticket', 'error');
            window.location.href = '/help-desk/user/my-tickets';
            return;
        }

        // Mostrar banner informativo
        const banner = document.getElementById('duplication-banner');
        document.getElementById('original-ticket-number').textContent = data.original_ticket.ticket_number;
        banner.style.display = 'block';

        // Pre-llenar formulario
        const duplicateData = data.duplicate_data;

        // Área
        if (duplicateData.area) {
            document.getElementById('area').value = duplicateData.area;
            // Trigger change event para cargar categorías
            document.getElementById('area').dispatchEvent(new Event('change'));
        }

        // Esperar a que carguen las categorías
        await new Promise(resolve => setTimeout(resolve, 500));

        // Categoría
        if (duplicateData.category_id) {
            document.getElementById('category_id').value = duplicateData.category_id;
            // Trigger change para cargar campos personalizados
            document.getElementById('category_id').dispatchEvent(new Event('change'));
        }

        // Esperar campos personalizados
        await new Promise(resolve => setTimeout(resolve, 500));

        // Título
        if (duplicateData.title) {
            document.getElementById('title').value = duplicateData.title;
        }

        // Descripción
        if (duplicateData.description) {
            document.getElementById('description').value = duplicateData.description;
        }

        // Ubicación
        if (duplicateData.location) {
            document.getElementById('location').value = duplicateData.location;
        }

        // Prioridad
        if (duplicateData.priority) {
            document.getElementById('priority').value = duplicateData.priority;
        }

        // Folio (si existe)
        if (duplicateData.office_document_folio) {
            document.getElementById('office_document_folio').value = duplicateData.office_document_folio;
        }

        // Campos personalizados
        if (duplicateData.custom_fields) {
            fillCustomFields(duplicateData.custom_fields);
        }

        // Guardar ID original en campo oculto
        document.getElementById('duplicated-from-id').value = ticketId;

        hideLoadingOverlay();

        // Mensaje de confirmación
        Swal.fire({
            title: 'Datos cargados',
            text: 'Revisa y modifica los campos según necesites, luego haz clic en "Crear Ticket"',
            icon: 'success',
            timer: 3000
        });

    } catch (error) {
        console.error('Error cargando datos de duplicación:', error);
        Swal.fire('Error', 'No se pudieron cargar los datos del ticket', 'error');
    }
}

function fillCustomFields(customFields) {
    // Iterar sobre campos personalizados y llenarlos
    for (const [fieldName, fieldValue] of Object.entries(customFields)) {
        const input = document.querySelector(`[name="custom_fields[${fieldName}]"]`);
        if (input) {
            if (input.type === 'checkbox') {
                input.checked = fieldValue;
            } else {
                input.value = fieldValue;
            }
        }
    }
}

function cancelDuplication() {
    // Limpiar formulario y ocultar banner
    document.getElementById('duplication-banner').style.display = 'none';
    document.getElementById('duplicated-from-id').value = '';
    // Opcionalmente limpiar campos
}
```

---

## 👤 FLUJO DE USUARIO

### Escenario 1: Duplicar ticket de problema recurrente

1. **Usuario tiene problema con impresora** (ya reportado antes)
2. Va a "Mis Tickets" y abre el ticket anterior **TK-2025-0042** (ya resuelto)
3. Ve botón **"Duplicar Ticket"** debajo del título
4. Hace clic, aparece confirmación:
   > "¿Duplicar este ticket? Se abrirá el formulario con los datos pre-llenados."
5. Confirma
6. **Redirige a crear ticket** con:
   - Área: SOPORTE ✓
   - Categoría: Problemas con Impresora ✓
   - Título: `[DUPLICADO] Problema con impresora en Oficina 301` ✓
   - Descripción: ✓
     ```
     📋 **Ticket duplicado de #TK-2025-0042**
     ---
     La impresora HP LaserJet de la oficina 301 no imprime documentos...
     ```
   - Ubicación: Oficina 301 ✓
   - Prioridad: MEDIA ✓
7. **Usuario modifica** solo lo necesario:
   - Cambia fecha en la descripción
   - Agrega: "Ahora tampoco escanea"
8. Clic en **"Crear Ticket"**
9. Sistema crea **TK-2026-0001**:
   - `duplicated_from_id = 42` (el ticket original)
   - Status: PENDING
10. Ticket original (`TK-2025-0042`):
    - `duplication_count` aumenta de 0 a 1
11. **Notificación a secretaria/admin** como cualquier ticket nuevo
12. Usuario ve confirmación:
    > "✅ Ticket TK-2026-0001 creado exitosamente (duplicado de #TK-2025-0042)"

**Tiempo ahorrado:** De 3-5 minutos a 30 segundos

### Escenario 2: Ver historial de duplicaciones (Admin/Técnico)

1. **Técnico** ve ticket **TK-2025-0042** (problema con impresora)
2. En el detalle del ticket, ve banner:
   ```
   🔁 Tickets Duplicados (3)
   Este ticket ha sido duplicado 3 veces. Esto puede indicar un problema recurrente.
   ```
3. Expande sección, ve lista:
   - TK-2025-0089 - PENDING - 2025-12-10
   - TK-2025-0134 - RESOLVED_SUCCESS - 2025-12-18
   - TK-2026-0001 - ASSIGNED - 2026-01-06 ← Más reciente
4. **Detecta patrón:** Problema cada ~10 días
5. **Decisión:** Cambiar impresora en lugar de seguir reparando
6. Crea ticket de cambio de equipo

### Escenario 3: Reporte de problemas recurrentes (Dashboard Admin)

1. **Admin** entra a dashboard de métricas
2. Ve sección "Problemas Recurrentes"
3. Gráfica de barras muestra:
   - "Problema con impresora Oficina 301" - 3 duplicaciones
   - "Internet lento Lab-Computo-2" - 5 duplicaciones
   - "Proyector no enciende Aula-A1" - 2 duplicaciones
4. Clic en "Internet lento Lab-Computo-2"
5. Ve cadena de 5 tickets duplicados
6. **Identifica root cause:** Switch defectuoso
7. **Acción:** Solicitar reemplazo de infraestructura

---

## 📊 MÉTRICAS Y REPORTES

### Dashboard de Duplicaciones (Admin)

**Ubicación:** `/help-desk/admin/analytics/duplications`

**Métricas a mostrar:**

1. **KPIs generales:**
   - Total de tickets duplicados este mes
   - % de tickets que son duplicados (vs tickets nuevos)
   - Promedio de días entre duplicaciones
   - Tickets con 3+ duplicaciones (problemas crónicos)

2. **Top 10 tickets más duplicados:**
   Tabla con:
   - Número de ticket original
   - Título
   - Categoría
   - Cantidad de duplicaciones
   - Última duplicación
   - Botón "Ver cadena"

3. **Duplicaciones por categoría:**
   Gráfica de pastel mostrando qué categorías tienen más duplicaciones

4. **Timeline de duplicaciones:**
   Gráfica de línea mostrando duplicaciones por día/semana

5. **Usuarios que más duplican:**
   ¿Hay usuarios que abusan de la función? O ¿usuarios con problemas recurrentes?

### Exportación de datos

- **CSV de problemas recurrentes:** Lista de tickets con 2+ duplicaciones
- **Reporte de análisis:** PDF con recomendaciones de root cause

---

## 🔒 SEGURIDAD Y VALIDACIONES

### Validaciones de backend:

1. **Permisos de duplicación:**
   - Solo el requester puede duplicar su propio ticket
   - Solo tickets resueltos/cerrados
   - No tickets cancelados

2. **Limitaciones:**
   - Máximo 5 duplicaciones por usuario por día (prevenir spam)
   - No duplicar tickets ya duplicados directamente (evitar cadenas infinitas)
   - Validar que campos modificados sean válidos

3. **Integridad de datos:**
   - No duplicar archivos adjuntos (usuario debe subir nuevos si es necesario)
   - No duplicar calificaciones ni resoluciones
   - Limpiar campos de tracking (assigned_to, status, etc.)

### Auditoría:

- Registrar en `StatusLog` el evento de creación por duplicación
- Mantener referencia bidireccional (original ← duplicados)
- Tracking de modificaciones entre original y duplicado

---

## 🧪 CASOS DE PRUEBA

### Casos positivos:

1. ✅ Usuario duplica su propio ticket resuelto
2. ✅ Modificar campos antes de crear ticket duplicado
3. ✅ Ver lista de duplicados en ticket original
4. ✅ Navegar entre original y duplicados
5. ✅ Duplicar ticket con campos personalizados
6. ✅ Duplicar ticket sin equipos asociados

### Casos negativos:

1. ❌ Intentar duplicar ticket de otro usuario → 403 Forbidden
2. ❌ Duplicar ticket en estado PENDING → Error "Solo resueltos"
3. ❌ Duplicar ticket cancelado → Error
4. ❌ Exceder límite de duplicaciones diarias → Rate limit error
5. ❌ Duplicar ticket sin permisos → 403

### Casos edge:

1. 🔸 Duplicar ticket que ya es un duplicado (debería funcionar, pero mostrar advertencia)
2. 🔸 Original tiene attachment, duplicado no → OK, no copiar archivos
3. 🔸 Categoría del original ya no existe → Error al cargar datos
4. 🔸 Campos personalizados cambiaron en la categoría → Adaptar a nueva estructura

---

## 📅 PLAN DE IMPLEMENTACIÓN POR FASES

### Fase 1: Base de datos (1 día)
- [ ] Crear migración para agregar campos a `Ticket`
- [ ] Modificar modelo `Ticket` con nuevas relaciones
- [ ] Generar datos de prueba

### Fase 2: Servicios (2 días)
- [ ] Crear `TicketDuplicateService`
- [ ] Métodos: `can_duplicate`, `get_duplicate_data`, `create_duplicate`
- [ ] Método de analytics: `get_duplication_analytics`
- [ ] Tests unitarios

### Fase 3: API REST (1 día)
- [ ] Endpoint GET `/:id/duplicate-data`
- [ ] Endpoint POST `/:id/duplicate`
- [ ] Endpoint GET `/:id/duplicates`
- [ ] Validaciones y manejo de errores

### Fase 4: Frontend - Botón duplicar (2 días)
- [ ] Modificar `ticket_detail.html` con botón
- [ ] JavaScript para confirmación y redirección
- [ ] Sección de "Tickets Duplicados" en detalle
- [ ] CSS para badges y alertas

### Fase 5: Frontend - Pre-llenado formulario (2 días)
- [ ] Modificar `create_ticket.html` con banner de duplicación
- [ ] JavaScript para cargar datos via API
- [ ] Lógica de pre-llenado de campos personalizados
- [ ] Manejo de errores y loading states

### Fase 6: Analytics y reportes (2 días)
- [ ] Dashboard de duplicaciones para admin
- [ ] Métricas de problemas recurrentes
- [ ] Gráficas y visualizaciones
- [ ] Exportación CSV

### Fase 7: Testing (1 día)
- [ ] Testing E2E del flujo completo
- [ ] Pruebas de permisos
- [ ] Pruebas de rate limiting
- [ ] Corrección de bugs

### Fase 8: Documentación (medio día)
- [ ] Documentar API en README
- [ ] Manual de usuario
- [ ] Casos de uso

**Total estimado:** 10-12 días de desarrollo

---

## ⚠️ RIESGOS Y MITIGACIONES

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|--------------|---------|------------|
| Usuarios duplican sin modificar nada | Alta | Bajo | Agregar confirmación "¿Los datos siguen siendo correctos?" |
| Spam de duplicaciones | Media | Medio | Rate limiting (5 por día) |
| Confusión entre original y duplicado | Media | Bajo | Badges claros, referencias bidireccionales |
| Performance con muchas duplicaciones | Baja | Medio | Índices en BD, paginación en listas |
| Categoría eliminada tras duplicar | Baja | Alto | Validación al cargar datos, error claro |

---

## 🎯 CRITERIOS DE ÉXITO

- ✅ 80% de usuarios encuentra útil la función (encuesta)
- ✅ Reducción del 30% en tiempo de creación de tickets recurrentes
- ✅ Identificación de al menos 5 problemas recurrentes en primer mes
- ✅ 0 errores críticos en producción
- ✅ Tiempo de carga de datos < 1 segundo
- ✅ Uso de la función en 15%+ de tickets resueltos

---

## 💡 EXTENSIONES FUTURAS

1. **Duplicación masiva:**
   - Botón "Crear 5 tickets iguales" para reportes de múltiples equipos con mismo problema

2. **Templates de tickets:**
   - Guardar como template (más allá de duplicar un ticket específico)
   - Biblioteca de templates personales

3. **Sugerencias automáticas:**
   - Al crear ticket, sugerir "¿Es similar a TK-2025-0042?" si detecta coincidencias

4. **Smart duplicate:**
   - AI que actualiza automáticamente fechas en la descripción
   - Detecta campos que probablemente cambiaron

5. **Integración con analytics:**
   - Alertas automáticas: "Este problema se ha reportado 5 veces, ¿investigar root cause?"

---

**Fin del documento de planificación #2**
