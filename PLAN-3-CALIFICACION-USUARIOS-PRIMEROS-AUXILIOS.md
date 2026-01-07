# PLAN DE IMPLEMENTACIÓN #3: CALIFICACIÓN DE USUARIOS + PRIMEROS AUXILIOS

**Proyecto:** Sistema Helpdesk - ITCJ
**Fecha:** 2026-01-06
**Autor:** Análisis de sistema actual + propuesta técnica
**Prioridad:** Alta
**Complejidad:** Alta

---

## 📋 RESUMEN EJECUTIVO

Implementar un **sistema dual** que combine:

1. **Primeros Auxilios (First Aid):** Checklists obligatorios antes de crear un ticket para descartar problemas simples que el usuario puede resolver por sí mismo
2. **Calificación de Confiabilidad del Usuario:** Sistema de scoring que penaliza a usuarios que reportan problemas sin verificar el checklist correctamente

**Problema actual:**
- Usuarios crean tickets por problemas triviales (cable desconectado, equipo apagado, etc.)
- No hay forma de saber si un usuario es confiable o tiende a reportar urgencias que no lo son
- Pérdida de tiempo del personal técnico atendiendo problemas que el usuario podría resolver

**Solución propuesta:**
- **Checklist obligatorio** antes de crear ticket, configurable por categoría
- **Guías detalladas** expandibles con instrucciones paso a paso (con imágenes)
- **Sistema de scoring** del usuario basado en:
  - Si reportó problema que coincide con checklist que marcó como verificado
  - Si exagera la urgencia (URGENTE para cosas simples)
  - Historial de tickets resueltos exitosamente vs fallidos
- **Badge de confiabilidad** visible para técnicos (🟢 Confiable, 🟡 Normal, 🔴 No Confiable)
- **Sistema informativo, no bloqueante:** Usuarios con baja calificación pueden seguir creando tickets

---

## 🎯 OBJETIVOS

### Objetivos principales:
1. **Reducir 40% de tickets triviales** mediante auto-diagnóstico
2. **Educar a usuarios** en solución de problemas básicos
3. **Identificar usuarios confiables** para priorización inteligente
4. **Forzar atención del usuario** mediante checklist obligatorio
5. **Mejorar asignación de prioridades** basada en confiabilidad

### Objetivos secundarios:
- Base de conocimiento de soluciones simples (guías de primeros auxilios)
- Métricas de problemas más comunes para mejorar checklists
- Gamificación: usuarios con buena calificación obtienen respuesta más rápida

---

## 🏗️ ARQUITECTURA DE LA SOLUCIÓN

### Componentes nuevos a crear:

```
apps/helpdesk/
├── models/
│   ├── user_reliability_score.py         [NUEVO] Calificación del usuario
│   ├── first_aid_checklist.py            [NUEVO] Checklists por categoría
│   ├── first_aid_checklist_item.py       [NUEVO] Items del checklist
│   ├── first_aid_guide.py                [NUEVO] Guías detalladas
│   ├── ticket_first_aid_response.py      [NUEVO] Respuestas del usuario
│   └── ticket.py                         [MODIFICAR] Relaciones
│
├── services/
│   ├── user_reliability_service.py       [NUEVO] Lógica de scoring
│   ├── first_aid_service.py              [NUEVO] Lógica de checklists
│   └── ticket_service.py                 [MODIFICAR] Integración
│
├── routes/
│   ├── api/
│   │   ├── first_aid.py                  [NUEVO] API checklists
│   │   └── user_reliability.py           [NUEVO] API scoring
│   └── pages/
│       ├── admin_first_aid.py            [NUEVO] Configuración admin
│       └── user.py                       [MODIFICAR] Integración
│
├── templates/helpdesk/
│   ├── user/
│   │   ├── first_aid_checklist.html      [NUEVO] Modal checklist
│   │   └── create_ticket.html            [MODIFICAR] Integración
│   └── admin/
│       ├── first_aid_management.html     [NUEVO] CRUD checklists
│       └── first_aid_guides.html         [NUEVO] Editor de guías
│
└── static/
    ├── js/
    │   ├── first_aid_checklist.js        [NUEVO]
    │   └── reliability_badge.js          [NUEVO]
    ├── css/
    │   └── first_aid.css                 [NUEVO]
    └── images/
        └── guides/                       [NUEVO] Imágenes de guías
```

---

## 💾 MODELOS DE BASE DE DATOS

### 1. UserReliabilityScore (Calificación del usuario)

**Tabla:** `helpdesk_user_reliability_scores`

```python
class UserReliabilityScore(db.Model):
    """
    Sistema de calificación de confiabilidad del usuario.
    Se actualiza automáticamente basado en comportamiento histórico.
    """
    __tablename__ = 'helpdesk_user_reliability_scores'

    # Identificación (one-to-one con User)
    user_id = db.Column(db.BigInteger, db.ForeignKey('core_users.id'), primary_key=True)

    # Score principal (0-100)
    reliability_score = db.Column(db.Integer, default=75, nullable=False)
    # 90-100: Excelente (🟢)
    # 70-89:  Bueno (🟢)
    # 50-69:  Normal (🟡)
    # 30-49:  Bajo (🟠)
    # 0-29:   Muy Bajo (🔴)

    # Componentes del score
    false_positive_count = db.Column(db.Integer, default=0, nullable=False)
    # Tickets resueltos donde el problema era del checklist que marcó como verificado

    exaggerated_urgency_count = db.Column(db.Integer, default=0, nullable=False)
    # Tickets marcados URGENTE/ALTA que resultaron ser BAJA/MEDIA

    successful_tickets_count = db.Column(db.Integer, default=0, nullable=False)
    # Tickets resueltos exitosamente (RESOLVED_SUCCESS)

    total_tickets_count = db.Column(db.Integer, default=0, nullable=False)
    # Total de tickets creados

    checklist_skip_attempts = db.Column(db.Integer, default=0, nullable=False)
    # Intentos de saltarse el checklist (si aplicamos validación estricta)

    # Timestamps
    last_calculated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Notas administrativas
    admin_notes = db.Column(db.Text, nullable=True)
    is_manually_adjusted = db.Column(db.Boolean, default=False, nullable=False)
    # Si admin ajustó manualmente el score

    # Relaciones
    user = db.relationship('User', backref=db.backref('reliability_score', uselist=False))

    # Métodos
    @property
    def reliability_level(self):
        """Retorna nivel textual basado en score"""
        if self.reliability_score >= 90:
            return 'EXCELLENT'
        elif self.reliability_score >= 70:
            return 'GOOD'
        elif self.reliability_score >= 50:
            return 'NORMAL'
        elif self.reliability_score >= 30:
            return 'LOW'
        else:
            return 'VERY_LOW'

    @property
    def reliability_badge(self):
        """Retorna emoji/color para UI"""
        level = self.reliability_level
        badges = {
            'EXCELLENT': {'emoji': '🟢', 'color': 'success', 'label': 'Excelente'},
            'GOOD': {'emoji': '🟢', 'color': 'success', 'label': 'Bueno'},
            'NORMAL': {'emoji': '🟡', 'color': 'warning', 'label': 'Normal'},
            'LOW': {'emoji': '🟠', 'color': 'warning', 'label': 'Bajo'},
            'VERY_LOW': {'emoji': '🔴', 'color': 'danger', 'label': 'Muy Bajo'}
        }
        return badges[level]

    @property
    def false_positive_rate(self):
        """Porcentaje de falsos positivos"""
        if self.total_tickets_count == 0:
            return 0.0
        return (self.false_positive_count / self.total_tickets_count) * 100

    @property
    def success_rate(self):
        """Porcentaje de tickets exitosos"""
        if self.total_tickets_count == 0:
            return 100.0  # Nuevo usuario, benefit of the doubt
        return (self.successful_tickets_count / self.total_tickets_count) * 100

    def recalculate_score(self):
        """
        Recalcula el score de confiabilidad basado en componentes.

        Fórmula:
        - Base: 75 puntos
        - +1 punto por cada 2 tickets exitosos
        - -5 puntos por cada falso positivo
        - -3 puntos por cada urgencia exagerada
        - -2 puntos por cada intento de skip checklist
        - Máx: 100, Mín: 0
        """
        if self.is_manually_adjusted:
            return  # No recalcular si admin ajustó manualmente

        base_score = 75

        # Bonificación por éxito
        success_bonus = min(20, (self.successful_tickets_count // 2))

        # Penalizaciones
        false_positive_penalty = self.false_positive_count * 5
        exaggerated_penalty = self.exaggerated_urgency_count * 3
        skip_penalty = self.checklist_skip_attempts * 2

        # Calcular score final
        new_score = base_score + success_bonus - false_positive_penalty - exaggerated_penalty - skip_penalty

        # Limitar a rango [0, 100]
        self.reliability_score = max(0, min(100, new_score))
        self.last_calculated_at = datetime.utcnow()
```

### 2. FirstAidChecklist (Checklists por categoría)

**Tabla:** `helpdesk_first_aid_checklists`

```python
class FirstAidChecklist(db.Model):
    """
    Checklist de primeros auxilios asociado a una categoría de ticket.
    Cada categoría puede tener un checklist configurable.
    """
    __tablename__ = 'helpdesk_first_aid_checklists'

    id = db.Column(db.Integer, primary_key=True)

    # Categoría asociada (one-to-one)
    category_id = db.Column(db.Integer, db.ForeignKey('helpdesk_categories.id'), unique=True, nullable=False)

    # Configuración
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    # Ejemplo: "Verificaciones básicas antes de reportar problema de internet"

    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_required = db.Column(db.Boolean, default=True, nullable=False)
    # Si es False, el checklist es opcional (solo informativo)

    # Mensaje introductorio
    intro_message = db.Column(db.Text, nullable=True)
    # Ejemplo: "Antes de crear el ticket, verifica estos puntos básicos que podrían resolver tu problema:"

    # Orden de visualización
    display_order = db.Column(db.Integer, default=0, nullable=False)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by_id = db.Column(db.BigInteger, db.ForeignKey('core_users.id'), nullable=True)

    # Relaciones
    category = db.relationship('Category', backref=db.backref('first_aid_checklist', uselist=False))
    items = db.relationship('FirstAidChecklistItem', backref='checklist', lazy='dynamic',
                           order_by='FirstAidChecklistItem.display_order')
    created_by = db.relationship('User')

    # Métodos
    @property
    def total_items(self):
        return self.items.count()

    @property
    def active_items(self):
        return self.items.filter_by(is_active=True).all()
```

### 3. FirstAidChecklistItem (Items del checklist)

**Tabla:** `helpdesk_first_aid_checklist_items`

```python
class FirstAidChecklistItem(db.Model):
    """
    Item individual de un checklist de primeros auxilios.
    Cada item representa una verificación que el usuario debe hacer.
    """
    __tablename__ = 'helpdesk_first_aid_checklist_items'

    id = db.Column(db.Integer, primary_key=True)

    # Checklist al que pertenece
    checklist_id = db.Column(db.Integer, db.ForeignKey('helpdesk_first_aid_checklists.id'), nullable=False)

    # Contenido del item
    text = db.Column(db.String(255), nullable=False)
    # Ejemplo: "¿El cable de red está conectado correctamente?"

    description = db.Column(db.Text, nullable=True)
    # Descripción adicional corta

    # Asociación con guía detallada
    guide_id = db.Column(db.Integer, db.ForeignKey('helpdesk_first_aid_guides.id'), nullable=True)
    # Si tiene guía, mostrar botón "Más información"

    # Configuración
    is_required = db.Column(db.Boolean, default=True, nullable=False)
    # Si es True, el usuario DEBE marcar este checkbox

    is_active = db.Column(db.Boolean, default=True, nullable=False)
    display_order = db.Column(db.Integer, default=0, nullable=False)

    # Tracking de efectividad
    times_checked = db.Column(db.Integer, default=0, nullable=False)
    # Cuántas veces los usuarios marcaron este item

    times_was_actual_problem = db.Column(db.Integer, default=0, nullable=False)
    # Cuántas veces el problema ERA este item (falso positivo del usuario)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    guide = db.relationship('FirstAidGuide', backref='checklist_items')

    # Métodos
    @property
    def false_positive_rate(self):
        """Tasa de falsos positivos para este item"""
        if self.times_checked == 0:
            return 0.0
        return (self.times_was_actual_problem / self.times_checked) * 100

    @property
    def is_problematic_item(self):
        """Indica si este item es problemático (muchos falsos positivos)"""
        return self.false_positive_rate > 20  # Más del 20% de falsos positivos
```

### 4. FirstAidGuide (Guías detalladas)

**Tabla:** `helpdesk_first_aid_guides`

```python
class FirstAidGuide(db.Model):
    """
    Guía detallada con instrucciones paso a paso para verificar un item del checklist.
    Incluye texto, imágenes, videos (opcional).
    """
    __tablename__ = 'helpdesk_first_aid_guides'

    id = db.Column(db.Integer, primary_key=True)

    # Identificación
    title = db.Column(db.String(200), nullable=False)
    # Ejemplo: "Cómo verificar que el cable de red esté bien conectado"

    slug = db.Column(db.String(100), unique=True, nullable=False)
    # URL-friendly: "verificar-cable-red"

    # Contenido
    content = db.Column(db.Text, nullable=False)
    # HTML/Markdown con instrucciones paso a paso

    summary = db.Column(db.String(500), nullable=True)
    # Resumen breve para mostrar en tooltip

    # Media
    featured_image = db.Column(db.String(255), nullable=True)
    # Ruta a imagen principal: /static/images/guides/cable-ethernet.jpg

    images = db.Column(db.JSON, nullable=True)
    # Array de rutas a imágenes adicionales
    # Ejemplo: ["/static/images/guides/step1.jpg", "/static/images/guides/step2.jpg"]

    video_url = db.Column(db.String(255), nullable=True)
    # URL de video (YouTube, Vimeo) o local

    # Configuración
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    view_count = db.Column(db.Integer, default=0, nullable=False)
    helpful_count = db.Column(db.Integer, default=0, nullable=False)
    not_helpful_count = db.Column(db.Integer, default=0, nullable=False)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by_id = db.Column(db.BigInteger, db.ForeignKey('core_users.id'), nullable=True)

    # Relaciones
    created_by = db.relationship('User')

    # Métodos
    @property
    def helpfulness_ratio(self):
        """Ratio de útil vs no útil"""
        total = self.helpful_count + self.not_helpful_count
        if total == 0:
            return None
        return (self.helpful_count / total) * 100
```

### 5. TicketFirstAidResponse (Respuestas del usuario)

**Tabla:** `helpdesk_ticket_first_aid_responses`

```python
class TicketFirstAidResponse(db.Model):
    """
    Registro de las respuestas del usuario al checklist de primeros auxilios.
    Se guarda al crear el ticket para poder validar más tarde.
    """
    __tablename__ = 'helpdesk_ticket_first_aid_responses'

    id = db.Column(db.BigInteger, primary_key=True)

    # Ticket asociado
    ticket_id = db.Column(db.BigInteger, db.ForeignKey('helpdesk_tickets.id'), unique=True, nullable=False)

    # Checklist usado
    checklist_id = db.Column(db.Integer, db.ForeignKey('helpdesk_first_aid_checklists.id'), nullable=False)

    # Respuestas (JSON)
    responses = db.Column(db.JSON, nullable=False)
    # Formato:
    # {
    #     "item_123": {
    #         "checked": true,
    #         "text": "¿El cable de red está conectado?",
    #         "timestamp": "2026-01-06T10:30:00"
    #     },
    #     "item_124": {
    #         "checked": true,
    #         "text": "¿La computadora está encendida?",
    #         "timestamp": "2026-01-06T10:30:15"
    #     }
    # }

    # Tiempo que tardó en completar el checklist (segundos)
    completion_time_seconds = db.Column(db.Integer, nullable=True)
    # Si completó en < 5 segundos, probablemente no leyó (sospechoso)

    # Guías consultadas
    guides_viewed = db.Column(db.JSON, nullable=True)
    # Array de guide_ids que el usuario abrió

    # Validación posterior
    was_validated = db.Column(db.Boolean, default=False, nullable=False)
    validation_result = db.Column(db.String(20), nullable=True)
    # Valores: CORRECT, FALSE_POSITIVE, NOT_VALIDATED

    false_positive_item_ids = db.Column(db.JSON, nullable=True)
    # Array de item_ids que resultaron ser el problema real

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    validated_at = db.Column(db.DateTime, nullable=True)
    validated_by_id = db.Column(db.BigInteger, db.ForeignKey('core_users.id'), nullable=True)

    # Relaciones
    ticket = db.relationship('Ticket', backref=db.backref('first_aid_response', uselist=False))
    checklist = db.relationship('FirstAidChecklist')
    validated_by = db.relationship('User')

    # Índices
    __table_args__ = (
        db.Index('idx_first_aid_responses_ticket', 'ticket_id'),
        db.Index('idx_first_aid_responses_validation', 'was_validated', 'validation_result'),
    )

    # Métodos
    @property
    def items_checked_count(self):
        """Cantidad de items marcados como verificados"""
        return sum(1 for item in self.responses.values() if item.get('checked'))

    @property
    def completed_too_fast(self):
        """Indica si completó el checklist sospechosamente rápido"""
        if not self.completion_time_seconds:
            return False
        # Menos de 2 segundos por item es sospechoso
        items_count = len(self.responses)
        minimum_time = items_count * 2
        return self.completion_time_seconds < minimum_time

    @property
    def suspicious_activity(self):
        """Detecta actividad sospechosa"""
        return self.completed_too_fast or (self.items_checked_count == 0)
```

### 6. Modificaciones a Ticket (modelo existente)

```python
class Ticket(db.Model):
    # ... campos existentes ...

    # NUEVOS CAMPOS
    first_aid_completed = db.Column(db.Boolean, default=False, nullable=False)
    # Indica si pasó por el checklist de primeros auxilios

    first_aid_skipped = db.Column(db.Boolean, default=False, nullable=False)
    # Si el checklist no era aplicable o se saltó por alguna razón válida

    # NUEVA RELACIÓN (ya definida en TicketFirstAidResponse)
    # first_aid_response -> acceso a las respuestas del checklist
```

---

## 🔧 SERVICIOS (Lógica de negocio)

### 1. FirstAidService

**Archivo:** `apps/helpdesk/services/first_aid_service.py`

```python
class FirstAidService:
    """Servicio para gestionar checklists de primeros auxilios"""

    @staticmethod
    def get_checklist_for_category(category_id):
        """
        Obtiene el checklist activo para una categoría.

        Returns:
            {
                'has_checklist': bool,
                'checklist': {
                    'id': int,
                    'name': str,
                    'intro_message': str,
                    'is_required': bool,
                    'items': [
                        {
                            'id': int,
                            'text': str,
                            'description': str,
                            'is_required': bool,
                            'has_guide': bool,
                            'guide_id': int | None
                        },
                        ...
                    ]
                } | None
            }
        """
        checklist = FirstAidChecklist.query.filter_by(
            category_id=category_id,
            is_active=True
        ).first()

        if not checklist:
            return {'has_checklist': False, 'checklist': None}

        items_data = [
            {
                'id': item.id,
                'text': item.text,
                'description': item.description,
                'is_required': item.is_required,
                'has_guide': item.guide_id is not None,
                'guide_id': item.guide_id
            }
            for item in checklist.active_items
        ]

        return {
            'has_checklist': True,
            'checklist': {
                'id': checklist.id,
                'name': checklist.name,
                'intro_message': checklist.intro_message,
                'is_required': checklist.is_required,
                'items': items_data
            }
        }

    @staticmethod
    def get_guide(guide_id):
        """
        Obtiene una guía detallada.

        Returns:
            {
                'id': int,
                'title': str,
                'content': str,  # HTML/Markdown
                'featured_image': str,
                'images': [str],
                'video_url': str
            }
        """
        guide = FirstAidGuide.query.get(guide_id)
        if not guide or not guide.is_active:
            raise ValueError("Guía no encontrada")

        # Incrementar contador de vistas
        guide.view_count += 1
        db.session.commit()

        return {
            'id': guide.id,
            'title': guide.title,
            'summary': guide.summary,
            'content': guide.content,
            'featured_image': guide.featured_image,
            'images': guide.images or [],
            'video_url': guide.video_url
        }

    @staticmethod
    def save_checklist_response(ticket_id, checklist_id, responses, completion_time, guides_viewed=None):
        """
        Guarda las respuestas del usuario al checklist.

        Args:
            ticket_id: ID del ticket creado
            checklist_id: ID del checklist usado
            responses: Dict con respuestas por item_id
                {
                    "item_123": {"checked": true, "text": "...", "timestamp": "..."},
                    ...
                }
            completion_time: Segundos que tardó
            guides_viewed: Array de guide_ids consultados

        Returns:
            TicketFirstAidResponse
        """
        response_record = TicketFirstAidResponse(
            ticket_id=ticket_id,
            checklist_id=checklist_id,
            responses=responses,
            completion_time_seconds=completion_time,
            guides_viewed=guides_viewed or []
        )
        db.session.add(response_record)

        # Actualizar contadores de items
        for item_id_str, response_data in responses.items():
            if response_data.get('checked'):
                item_id = int(item_id_str.replace('item_', ''))
                item = FirstAidChecklistItem.query.get(item_id)
                if item:
                    item.times_checked += 1

        db.session.commit()
        return response_record

    @staticmethod
    def validate_checklist_response(ticket_id, was_false_positive, false_positive_item_ids=None, validated_by_id=None):
        """
        Valida si el usuario respondió correctamente el checklist.
        Llamado por el técnico al resolver el ticket.

        Args:
            ticket_id: ID del ticket
            was_false_positive: Bool, si el problema era del checklist
            false_positive_item_ids: Array de item_ids que eran el problema
            validated_by_id: ID del técnico que valida

        Updates:
            - TicketFirstAidResponse.validation_result
            - FirstAidChecklistItem.times_was_actual_problem
            - UserReliabilityScore (penalización si fue falso positivo)
        """
        response = TicketFirstAidResponse.query.filter_by(ticket_id=ticket_id).first()
        if not response:
            return  # Ticket sin checklist

        response.was_validated = True
        response.validated_at = datetime.utcnow()
        response.validated_by_id = validated_by_id

        if was_false_positive:
            response.validation_result = 'FALSE_POSITIVE'
            response.false_positive_item_ids = false_positive_item_ids or []

            # Actualizar contadores de items
            for item_id in (false_positive_item_ids or []):
                item = FirstAidChecklistItem.query.get(item_id)
                if item:
                    item.times_was_actual_problem += 1

            # Penalizar al usuario
            ticket = Ticket.query.get(ticket_id)
            UserReliabilityService.record_false_positive(ticket.requester_id)

        else:
            response.validation_result = 'CORRECT'
            # Bonificar al usuario (opcional)
            ticket = Ticket.query.get(ticket_id)
            UserReliabilityService.record_successful_ticket(ticket.requester_id)

        db.session.commit()
```

### 2. UserReliabilityService

**Archivo:** `apps/helpdesk/services/user_reliability_service.py`

```python
class UserReliabilityService:
    """Servicio para gestionar la calificación de confiabilidad de usuarios"""

    @staticmethod
    def get_or_create_score(user_id):
        """
        Obtiene o crea el registro de confiabilidad de un usuario.

        Returns:
            UserReliabilityScore
        """
        score = UserReliabilityScore.query.get(user_id)
        if not score:
            score = UserReliabilityScore(user_id=user_id)
            db.session.add(score)
            db.session.commit()
        return score

    @staticmethod
    def get_user_reliability(user_id):
        """
        Obtiene información completa de confiabilidad del usuario.

        Returns:
            {
                'score': int,
                'level': str,
                'badge': dict,
                'statistics': {
                    'total_tickets': int,
                    'successful_tickets': int,
                    'false_positives': int,
                    'exaggerated_urgencies': int,
                    'success_rate': float,
                    'false_positive_rate': float
                },
                'recent_activity': [...]
            }
        """
        score_record = UserReliabilityService.get_or_create_score(user_id)

        return {
            'score': score_record.reliability_score,
            'level': score_record.reliability_level,
            'badge': score_record.reliability_badge,
            'statistics': {
                'total_tickets': score_record.total_tickets_count,
                'successful_tickets': score_record.successful_tickets_count,
                'false_positives': score_record.false_positive_count,
                'exaggerated_urgencies': score_record.exaggerated_urgency_count,
                'success_rate': score_record.success_rate,
                'false_positive_rate': score_record.false_positive_rate
            }
        }

    @staticmethod
    def record_false_positive(user_id):
        """
        Registra un falso positivo (usuario marcó checklist pero era ese el problema).
        """
        score = UserReliabilityService.get_or_create_score(user_id)
        score.false_positive_count += 1
        score.recalculate_score()
        db.session.commit()

    @staticmethod
    def record_exaggerated_urgency(user_id):
        """
        Registra una urgencia exagerada (ticket marcado URGENTE resultó ser BAJA).
        """
        score = UserReliabilityService.get_or_create_score(user_id)
        score.exaggerated_urgency_count += 1
        score.recalculate_score()
        db.session.commit()

    @staticmethod
    def record_successful_ticket(user_id):
        """
        Registra un ticket exitoso (resolved successfully).
        """
        score = UserReliabilityService.get_or_create_score(user_id)
        score.successful_tickets_count += 1
        score.total_tickets_count += 1
        score.recalculate_score()
        db.session.commit()

    @staticmethod
    def record_ticket_created(user_id):
        """
        Registra que el usuario creó un ticket.
        """
        score = UserReliabilityService.get_or_create_score(user_id)
        score.total_tickets_count += 1
        db.session.commit()

    @staticmethod
    def adjust_score_manually(user_id, new_score, admin_id, reason):
        """
        Permite a un admin ajustar manualmente el score de un usuario.

        Args:
            user_id: ID del usuario
            new_score: Nuevo score (0-100)
            admin_id: ID del admin que hace el ajuste
            reason: Razón del ajuste
        """
        score = UserReliabilityService.get_or_create_score(user_id)
        score.reliability_score = max(0, min(100, new_score))
        score.is_manually_adjusted = True
        score.admin_notes = f"[{datetime.utcnow()}] Ajustado por admin {admin_id}: {reason}"
        db.session.commit()

    @staticmethod
    def get_reliability_distribution():
        """
        Obtiene distribución de scores para analytics.

        Returns:
            {
                'EXCELLENT': count,
                'GOOD': count,
                'NORMAL': count,
                'LOW': count,
                'VERY_LOW': count
            }
        """
        scores = UserReliabilityScore.query.all()
        distribution = {
            'EXCELLENT': 0,
            'GOOD': 0,
            'NORMAL': 0,
            'LOW': 0,
            'VERY_LOW': 0
        }

        for score in scores:
            distribution[score.reliability_level] += 1

        return distribution

    @staticmethod
    def get_low_reliability_users(threshold=50, limit=50):
        """
        Obtiene usuarios con baja confiabilidad para revisión administrativa.

        Returns:
            [
                {
                    'user': User,
                    'score': int,
                    'level': str,
                    'false_positives': int,
                    'total_tickets': int
                },
                ...
            ]
        """
        low_scores = UserReliabilityScore.query.filter(
            UserReliabilityScore.reliability_score < threshold
        ).order_by(
            UserReliabilityScore.reliability_score.asc()
        ).limit(limit).all()

        return [
            {
                'user': score.user,
                'score': score.reliability_score,
                'level': score.reliability_level,
                'false_positives': score.false_positive_count,
                'total_tickets': score.total_tickets_count
            }
            for score in low_scores
        ]
```

---

## 🌐 RUTAS Y API

### API Endpoints - First Aid

**Archivo:** `apps/helpdesk/routes/api/first_aid.py`

```python
# GET /api/help-desk/v1/first-aid/checklist/:category_id
@first_aid_bp.route('/checklist/<int:category_id>', methods=['GET'])
@api_app_required('helpdesk', perms=['helpdesk.first_aid.api.read'])
def get_checklist_for_category(category_id):
    """Obtiene el checklist para una categoría específica"""
    data = FirstAidService.get_checklist_for_category(category_id)
    return jsonify(data), 200

# GET /api/help-desk/v1/first-aid/guide/:guide_id
@first_aid_bp.route('/guide/<int:guide_id>', methods=['GET'])
@api_app_required('helpdesk', perms=['helpdesk.first_aid.api.read'])
def get_guide(guide_id):
    """Obtiene una guía detallada"""
    try:
        guide = FirstAidService.get_guide(guide_id)
        return jsonify(guide), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 404

# POST /api/help-desk/v1/first-aid/save-response
@first_aid_bp.route('/save-response', methods=['POST'])
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.create'])
def save_checklist_response():
    """
    Guarda respuestas del checklist al crear ticket.

    Body:
    {
        "ticket_id": 123,
        "checklist_id": 5,
        "responses": {
            "item_10": {"checked": true, "text": "...", "timestamp": "..."},
            "item_11": {"checked": false, "text": "...", "timestamp": "..."}
        },
        "completion_time": 45,  // segundos
        "guides_viewed": [3, 7]
    }
    """
    data = request.get_json()
    response_record = FirstAidService.save_checklist_response(
        ticket_id=data['ticket_id'],
        checklist_id=data['checklist_id'],
        responses=data['responses'],
        completion_time=data['completion_time'],
        guides_viewed=data.get('guides_viewed')
    )
    return jsonify({'success': True, 'id': response_record.id}), 201

# POST /api/help-desk/v1/first-aid/validate-response/:ticket_id
@first_aid_bp.route('/validate-response/<int:ticket_id>', methods=['POST'])
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.resolve'])
def validate_checklist_response(ticket_id):
    """
    Valida respuestas del checklist (llamado por técnico al resolver).

    Body:
    {
        "was_false_positive": true,
        "false_positive_item_ids": [10, 11]
    }
    """
    user_id = session.get('user_id')
    data = request.get_json()

    FirstAidService.validate_checklist_response(
        ticket_id=ticket_id,
        was_false_positive=data['was_false_positive'],
        false_positive_item_ids=data.get('false_positive_item_ids'),
        validated_by_id=user_id
    )

    return jsonify({'success': True}), 200
```

### API Endpoints - User Reliability

**Archivo:** `apps/helpdesk/routes/api/user_reliability.py`

```python
# GET /api/help-desk/v1/reliability/user/:user_id
@reliability_bp.route('/user/<int:user_id>', methods=['GET'])
@api_app_required('helpdesk', perms=['helpdesk.reliability.api.read'])
def get_user_reliability(user_id):
    """Obtiene información de confiabilidad de un usuario"""
    data = UserReliabilityService.get_user_reliability(user_id)
    return jsonify(data), 200

# GET /api/help-desk/v1/reliability/distribution
@reliability_bp.route('/distribution', methods=['GET'])
@api_app_required('helpdesk', perms=['helpdesk.reliability.api.read.all'])
def get_reliability_distribution():
    """Obtiene distribución de scores (solo admin)"""
    data = UserReliabilityService.get_reliability_distribution()
    return jsonify(data), 200

# GET /api/help-desk/v1/reliability/low-users
@reliability_bp.route('/low-users', methods=['GET'])
@api_app_required('helpdesk', perms=['helpdesk.reliability.api.read.all'])
def get_low_reliability_users():
    """Obtiene usuarios con baja confiabilidad (solo admin)"""
    threshold = request.args.get('threshold', 50, type=int)
    limit = request.args.get('limit', 50, type=int)

    users = UserReliabilityService.get_low_reliability_users(threshold, limit)
    return jsonify(users), 200

# POST /api/help-desk/v1/reliability/adjust/:user_id
@reliability_bp.route('/adjust/<int:user_id>', methods=['POST'])
@api_app_required('helpdesk', perms=['helpdesk.reliability.api.manage'])
def adjust_user_score(user_id):
    """
    Ajusta manualmente el score de un usuario (solo admin).

    Body:
    {
        "new_score": 75,
        "reason": "Usuario reportó problema legítimo de infraestructura"
    }
    """
    admin_id = session.get('user_id')
    data = request.get_json()

    UserReliabilityService.adjust_score_manually(
        user_id=user_id,
        new_score=data['new_score'],
        admin_id=admin_id,
        reason=data['reason']
    )

    return jsonify({'success': True}), 200
```

---

## 🎨 TEMPLATES Y UI

### 1. first_aid_checklist_modal.html

Modal que aparece ANTES de mostrar el formulario de crear ticket.

```html
<!-- Modal de Primeros Auxilios -->
<div class="modal fade" id="firstAidModal" data-bs-backdrop="static" data-bs-keyboard="false">
    <div class="modal-dialog modal-lg">
        <div class="modal-content">
            <div class="modal-header bg-warning">
                <h5 class="modal-title">
                    <i class="fas fa-first-aid"></i>
                    Primeros Auxilios - Verificaciones Previas
                </h5>
            </div>

            <div class="modal-body">
                <!-- Mensaje introductorio -->
                <div class="alert alert-info">
                    <strong>¡Espera!</strong> Antes de crear tu ticket, verifica estos puntos.
                    Muchos problemas se pueden resolver rápidamente siguiendo estas verificaciones.
                </div>

                <p id="checklist-intro-message" class="mb-4">
                    <!-- Mensaje dinámico del checklist -->
                </p>

                <!-- Checklist Items -->
                <form id="first-aid-form">
                    <div id="checklist-items-container">
                        <!-- Items cargados dinámicamente -->
                    </div>

                    <!-- Advertencia si completa muy rápido -->
                    <div id="warning-too-fast" class="alert alert-warning" style="display: none;">
                        <i class="fas fa-exclamation-triangle"></i>
                        Por favor tómate el tiempo necesario para verificar cada punto correctamente.
                    </div>
                </form>
            </div>

            <div class="modal-footer">
                <div class="text-muted small flex-grow-1">
                    <i class="fas fa-info-circle"></i>
                    Marca solo los items que <strong>SÍ verificaste</strong>.
                    Si marcas algo sin verificar, afectará tu calificación de confiabilidad.
                </div>
                <button type="button" class="btn btn-secondary" onclick="skipChecklist()">
                    Saltar (No Aplica)
                </button>
                <button type="button" class="btn btn-primary" id="btn-continue-to-ticket" disabled>
                    Continuar con el Ticket
                    <i class="fas fa-arrow-right"></i>
                </button>
            </div>
        </div>
    </div>
</div>

<!-- Template para item de checklist -->
<template id="checklist-item-template">
    <div class="checklist-item mb-3 p-3 border rounded">
        <div class="form-check">
            <input class="form-check-input" type="checkbox" id="item-{ID}" data-item-id="{ID}">
            <label class="form-check-label" for="item-{ID}">
                <strong>{TEXT}</strong>
            </label>
        </div>

        <!-- Descripción adicional -->
        <p class="text-muted small mb-2 ms-4">{DESCRIPTION}</p>

        <!-- Botón "Más información" si tiene guía -->
        <div class="ms-4">
            <button type="button" class="btn btn-sm btn-outline-info" onclick="showGuide({GUIDE_ID})">
                <i class="fas fa-book-open"></i>
                Más información - ¿Cómo verificar esto?
            </button>
        </div>
    </div>
</template>

<!-- Modal de guía detallada -->
<div class="modal fade" id="guideModal">
    <div class="modal-dialog modal-xl">
        <div class="modal-content">
            <div class="modal-header">
                <h5 class="modal-title" id="guide-title"></h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
                <!-- Imagen destacada -->
                <img id="guide-featured-image" class="img-fluid mb-3" style="max-height: 300px;">

                <!-- Contenido -->
                <div id="guide-content"></div>

                <!-- Galería de imágenes -->
                <div id="guide-images-gallery" class="row mt-3"></div>

                <!-- Video (si existe) -->
                <div id="guide-video-container" class="mt-3"></div>
            </div>
            <div class="modal-footer">
                <button type="button" class="btn btn-success" onclick="markAsHelpful()">
                    <i class="fas fa-thumbs-up"></i> Útil
                </button>
                <button type="button" class="btn btn-outline-secondary" onclick="markAsNotHelpful()">
                    <i class="fas fa-thumbs-down"></i> No útil
                </button>
                <button type="button" class="btn btn-primary" data-bs-dismiss="modal">Cerrar</button>
            </div>
        </div>
    </div>
</div>
```

### 2. Modificar create_ticket.html

Integrar el flujo del checklist antes de mostrar el formulario.

```html
<!-- Al principio del template -->
<div id="first-aid-required-message" class="alert alert-warning" style="display: none;">
    <i class="fas fa-hand-paper"></i>
    <strong>Verificaciones de Primeros Auxilios requeridas.</strong>
    <p class="mb-0">
        Para esta categoría de problema, primero debes verificar algunos puntos básicos.
        Esto nos ayuda a resolver tu problema más rápido.
    </p>
</div>

<!-- Badge de confiabilidad del usuario (opcional, solo para auto-conocimiento) -->
<div id="user-reliability-badge" class="mb-3" style="display: none;">
    <div class="alert alert-light border">
        <strong>Tu calificación de confiabilidad:</strong>
        <span id="reliability-badge-content"></span>
        <button class="btn btn-sm btn-link" onclick="showReliabilityInfo()">
            ¿Qué es esto?
        </button>
    </div>
</div>
```

### 3. Badge de confiabilidad en ticket_detail.html (para técnicos)

Mostrar el badge del usuario requester en el detalle del ticket.

```html
<!-- En la sección de información del solicitante -->
<div class="card mb-3">
    <div class="card-header">
        <i class="fas fa-user"></i> Solicitante
    </div>
    <div class="card-body">
        <p><strong>Nombre:</strong> {{ ticket.requester.full_name }}</p>
        <p><strong>Departamento:</strong> {{ ticket.requester_department.name }}</p>

        <!-- NUEVO: Badge de confiabilidad -->
        {% if current_user_roles contains 'tech_' or 'admin' %}
        <div class="mt-2">
            <strong>Confiabilidad:</strong>
            <span class="badge bg-{{ requester_reliability.badge.color }} reliability-badge"
                  data-bs-toggle="tooltip"
                  title="Score: {{ requester_reliability.score }}/100 | Tickets exitosos: {{ requester_reliability.statistics.success_rate }}%">
                {{ requester_reliability.badge.emoji }} {{ requester_reliability.badge.label }}
            </span>

            <!-- Información adicional si es baja confiabilidad -->
            {% if requester_reliability.level in ['LOW', 'VERY_LOW'] %}
            <div class="alert alert-warning mt-2 small">
                <i class="fas fa-exclamation-triangle"></i>
                <strong>Nota:</strong> Este usuario tiene
                {{ requester_reliability.statistics.false_positives }} falsos positivos
                en {{ requester_reliability.statistics.total_tickets }} tickets.
                Verificar con cuidado las verificaciones de primeros auxilios.
            </div>
            {% endif %}
        </div>
        {% endif %}
    </div>
</div>

<!-- Sección de respuestas de primeros auxilios (para técnicos) -->
{% if ticket.first_aid_response and current_user_roles contains 'tech_' %}
<div class="card mb-3">
    <div class="card-header">
        <i class="fas fa-first-aid"></i>
        Respuestas de Primeros Auxilios
        {% if ticket.first_aid_response.suspicious_activity %}
        <span class="badge bg-danger ms-2">
            <i class="fas fa-exclamation-triangle"></i> Actividad Sospechosa
        </span>
        {% endif %}
    </div>
    <div class="card-body">
        <p class="text-muted small mb-2">
            Tiempo de completado: {{ ticket.first_aid_response.completion_time_seconds }}s
            {% if ticket.first_aid_response.completed_too_fast %}
            <span class="badge bg-warning">⚠️ Muy rápido</span>
            {% endif %}
        </p>

        <h6>Items verificados por el usuario:</h6>
        <ul id="first-aid-responses-list">
            <!-- Cargado via JavaScript -->
        </ul>

        <!-- Formulario de validación (al resolver) -->
        {% if ticket.status in ['IN_PROGRESS'] and not ticket.first_aid_response.was_validated %}
        <hr>
        <div class="bg-light p-3 rounded">
            <h6>¿El problema era alguno de estos items que el usuario marcó?</h6>
            <form id="validate-first-aid-form">
                <div class="form-check">
                    <input type="radio" name="was_false_positive" value="false" class="form-check-input" id="correct">
                    <label class="form-check-label" for="correct">
                        No, el usuario verificó correctamente
                    </label>
                </div>
                <div class="form-check">
                    <input type="radio" name="was_false_positive" value="true" class="form-check-input" id="false-positive">
                    <label class="form-check-label" for="false-positive">
                        Sí, el problema ERA uno de los items del checklist
                    </label>
                </div>

                <div id="false-positive-items-selection" style="display: none;" class="mt-3">
                    <label class="form-label">¿Cuál(es) item(s)?</label>
                    <div id="false-positive-items-checkboxes">
                        <!-- Generado dinámicamente -->
                    </div>
                </div>

                <button type="button" class="btn btn-primary mt-3" onclick="submitFirstAidValidation()">
                    Guardar Validación
                </button>
            </form>
        </div>
        {% endif %}

        <!-- Resultado de validación (si ya fue validado) -->
        {% if ticket.first_aid_response.was_validated %}
        <div class="alert alert-{{ 'danger' if ticket.first_aid_response.validation_result == 'FALSE_POSITIVE' else 'success' }} mt-3">
            <strong>Validación:</strong>
            {% if ticket.first_aid_response.validation_result == 'FALSE_POSITIVE' %}
            El usuario NO verificó correctamente. El problema era del checklist.
            {% else %}
            El usuario verificó correctamente.
            {% endif %}
        </div>
        {% endif %}
    </div>
</div>
{% endif %}
```

---

## 📊 DASHBOARD DE ANALYTICS (Admin)

### Métricas de Primeros Auxilios

**Ubicación:** `/help-desk/admin/analytics/first-aid`

**KPIs:**
1. % de tickets que pasaron por checklist
2. % de falsos positivos (usuarios que no verificaron bien)
3. Items del checklist con mayor tasa de falsos positivos
4. Guías más consultadas
5. Usuarios con más falsos positivos
6. Reducción de tickets triviales desde implementación

**Gráficas:**
- Timeline de tickets con/sin checklist
- Distribución de confiabilidad de usuarios (pie chart)
- Items problemáticos del checklist (bar chart)
- Evolución del score promedio de usuarios

### Dashboard de Confiabilidad de Usuarios

**Ubicación:** `/help-desk/admin/users/reliability`

**Tabla de usuarios:**
| Usuario | Score | Nivel | Tickets Totales | Falsos Positivos | Tasa Éxito | Acciones |
|---------|-------|-------|-----------------|------------------|------------|----------|
| Juan P. | 45 🔴 | Bajo | 15 | 6 | 60% | Ver / Ajustar |
| Ana G. | 92 🟢 | Excelente | 23 | 0 | 100% | Ver |

**Acciones:**
- Ver detalle de usuario
- Ajustar score manualmente
- Ver historial de validaciones

---

## 👤 FLUJOS DE USUARIO

### Escenario 1: Usuario crea ticket con checklist

1. Usuario selecciona categoría "Problemas de Internet"
2. **Sistema detecta** que hay checklist de primeros auxilios
3. **Antes de mostrar formulario**, abre modal:
   ```
   🚑 Primeros Auxilios - Verificaciones Previas

   ¡Espera! Antes de crear tu ticket, verifica estos puntos básicos:

   ☐ ¿El cable de red está conectado correctamente?
      [Más información - ¿Cómo verificar esto?]

   ☐ ¿La computadora está encendida?
      [Más información]

   ☐ ¿El LED del puerto de red está encendido?
      [Más información]

   ☐ ¿Otros compañeros tienen internet?
      [Más información]
   ```
4. Usuario hace clic en **"Más información"** del cable
5. Abre modal con guía detallada:
   - Foto del cable ethernet
   - Instrucción paso a paso
   - "Verifica que el cable esté firmemente insertado..."
   - Foto mostrando LED verde encendido
6. Usuario lee, marca "Útil"
7. Regresa al checklist, marca ✅ el primer item
8. Marca los demás items (tarda 30 segundos total)
9. Clic en **"Continuar con el Ticket"**
10. **Ahora sí** muestra el formulario normal de crear ticket
11. Usuario llena título, descripción, etc.
12. Al enviar, sistema guarda:
    - Ticket normal
    - TicketFirstAidResponse con respuestas del checklist
    - Tiempo de completado: 30s
    - Guías vistas: [5]

### Escenario 2: Técnico detecta falso positivo

1. Técnico recibe ticket: "No tengo internet"
2. Ve información del usuario:
   ```
   Solicitante: Juan Pérez
   Confiabilidad: 🟡 Normal (Score: 65/100)
   ```
3. Lee respuestas de primeros auxilios:
   ```
   ✅ ¿El cable de red está conectado? - Marcado como verificado
   ✅ ¿La computadora está encendida? - Marcado como verificado
   ✅ ¿El LED del puerto está encendido? - Marcado como verificado
   ```
4. Técnico va al sitio
5. **Descubre que el cable NO estaba conectado** 🤦
6. Conecta cable, problema resuelto
7. Al marcar ticket como RESOLVED_SUCCESS, llena formulario:
   ```
   ¿El problema era alguno de los items del checklist?
   ⚪ No, el usuario verificó correctamente
   ⦿ Sí, el problema ERA uno de los items

   ¿Cuál(es)?
   ☑ Cable de red desconectado
   ☐ Computadora apagada
   ☐ LED apagado
   ```
8. Sistema registra falso positivo
9. **Penalización automática** a Juan Pérez:
   - `false_positive_count`: 0 → 1
   - `reliability_score`: 65 → 60 (−5 puntos)
   - Nivel: 🟡 Normal → 🟡 Normal (aún en rango)
10. Item del checklist actualizado:
    - `times_checked`: +1
    - `times_was_actual_problem`: +1
    - `false_positive_rate`: Ahora 15%

### Escenario 3: Usuario con baja confiabilidad

1. Usuario "Pedro Martínez" tiene score de 35 🔴 (Bajo)
   - 8 falsos positivos en 12 tickets
2. Crea nuevo ticket con prioridad "URGENTE"
3. Sistema asigna a técnico con nota informativa:
   ```
   ⚠️ Este usuario tiene baja confiabilidad (35/100)
   Historial: 8 falsos positivos en 12 tickets

   Recomendación: Verificar urgencia antes de priorizar
   ```
4. Técnico ve y **NO prioriza** el ticket inmediatamente
5. Lo atiende en orden normal
6. Resulta que SÍ era urgente (servidor caído)
7. Técnico marca validación como "CORRECT"
8. Sistema **bonifica** a Pedro:
   - `successful_tickets_count`: +1
   - `total_tickets_count`: +1
   - `reliability_score`: 35 → 36 (+1 punto por ticket exitoso)
9. Poco a poco, Pedro puede recuperar su score

### Escenario 4: Admin ajusta score manualmente

1. Admin revisa lista de baja confiabilidad
2. Ve que "María López" tiene score 48 🟠
3. Investiga: sus 4 falsos positivos fueron por problemas de infraestructura, no su culpa
4. Decide ajustar manualmente:
   ```
   Nuevo score: 75
   Razón: "Los falsos positivos fueron por problema de switch defectuoso, no error del usuario"
   ```
5. Sistema actualiza:
   - `reliability_score`: 48 → 75
   - `is_manually_adjusted`: true
   - `admin_notes`: "Ajustado por admin..."
6. María ahora tiene 🟢 Bueno
7. El score ya NO se recalcula automáticamente (respeta ajuste admin)

---

## 🔒 SEGURIDAD Y VALIDACIONES

### Validaciones:

1. **Checklist obligatorio:**
   - Si categoría tiene checklist requerido, NO permitir crear ticket sin pasarlo
   - Frontend valida, backend también valida en `create_ticket`

2. **Tiempo mínimo:**
   - Si usuario completa en < 2 segundos por item, marcar como sospechoso
   - Mostrar advertencia pero permitir continuar

3. **Integridad de validación:**
   - Solo técnicos pueden validar respuestas de checklist
   - Solo durante resolución del ticket
   - Una sola validación por ticket

4. **Ajuste manual de score:**
   - Solo admins
   - Requiere razón (mínimo 20 caracteres)
   - Se registra en admin_notes con timestamp

### Rate Limiting:

- Usuario no puede crear más de 10 tickets por día si tiene score < 30

---

## 📅 PLAN DE IMPLEMENTACIÓN POR FASES

### Fase 1: Base de datos (2 días)
- [ ] Crear 5 nuevas tablas
- [ ] Migrar modelos existentes
- [ ] Generar datos de prueba (checklists, guías)

### Fase 2: Servicios (3 días)
- [ ] FirstAidService
- [ ] UserReliabilityService
- [ ] Integración con TicketService
- [ ] Tests unitarios

### Fase 3: API REST (2 días)
- [ ] Endpoints de checklists
- [ ] Endpoints de guías
- [ ] Endpoints de confiabilidad
- [ ] Validaciones

### Fase 4: Admin - Configuración de checklists (3 días)
- [ ] CRUD de checklists
- [ ] CRUD de items
- [ ] Editor de guías con upload de imágenes
- [ ] Preview de checklist

### Fase 5: Frontend - Modal de primeros auxilios (3 días)
- [ ] Modal de checklist
- [ ] Modal de guías
- [ ] JavaScript de interacción
- [ ] Tracking de tiempo
- [ ] Integración con crear ticket

### Fase 6: Frontend - Sistema de confiabilidad (2 días)
- [ ] Badges de confiabilidad
- [ ] Vista de validación para técnicos
- [ ] Dashboard de analytics
- [ ] Métricas y gráficas

### Fase 7: Lógica de penalización/bonificación (2 días)
- [ ] Integración en resolve ticket
- [ ] Cálculo automático de scores
- [ ] Notificaciones a usuarios
- [ ] Testing de fórmulas

### Fase 8: Testing y refinamiento (3 días)
- [ ] Testing E2E de flujos
- [ ] Pruebas de cálculo de score
- [ ] Optimización de queries
- [ ] Corrección de bugs

**Total estimado:** 20-25 días de desarrollo

---

## ⚠️ RIESGOS Y MITIGACIONES

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|--------------|---------|------------|
| Usuarios se molestan por checklist | Alta | Alto | Comunicar beneficios, hacer opcional al inicio |
| Falsos negativos en validación | Media | Alto | Capacitar a técnicos, permitir corrección |
| Gaming del sistema | Media | Medio | Detectar patrones sospechosos (tiempo muy rápido) |
| Usuarios con score bajo se ofenden | Alta | Medio | Sistema informativo no bloqueante, permitir recuperación |
| Checklists desactualizados | Media | Medio | Revisión trimestral, feedback de técnicos |

---

## 🎯 CRITERIOS DE ÉXITO

- ✅ Reducción del 40% en tickets triviales en 3 meses
- ✅ 80%+ de usuarios completan checklist sin quejas
- ✅ 70%+ de usuarios califican guías como "útiles"
- ✅ Tasa de falsos positivos < 10% global
- ✅ Técnicos reportan mejora en calidad de tickets
- ✅ Score promedio de usuarios > 65

---

**Fin del documento de planificación #3**
