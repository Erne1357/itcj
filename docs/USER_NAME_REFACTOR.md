# Refactor del Campo `full_name` en el Modelo User

## Resumen del Cambio

Se ha refactorizado el modelo `User` para separar el campo `full_name` en tres campos individuales:
- `first_name` (TEXT, NOT NULL): Nombre(s) de la persona
- `last_name` (TEXT, NOT NULL): Apellido paterno
- `middle_name` (TEXT, NULLABLE): Apellido materno (opcional)

## Motivación

1. **Normalización de datos**: Permite búsquedas y ordenamientos más precisos por apellido o nombre
2. **Estándares institucionales**: Alinea con formatos de documentos oficiales
3. **Flexibilidad**: Facilita reportes y exportaciones con formato específico

## Implementación Técnica

### 1. Modelo User (`itcj/core/models/user.py`)

```python
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy import func, case

class User(db.Model):
    # ... otros campos ...
    
    first_name = db.Column(db.Text, nullable=False)
    last_name = db.Column(db.Text, nullable=False)
    middle_name = db.Column(db.Text, nullable=True)
    
    @hybrid_property
    def full_name(self):
        """Nombre completo calculado (Python)"""
        if self.middle_name:
            return f"{self.last_name} {self.middle_name} {self.first_name}"
        return f"{self.last_name} {self.first_name}"
    
    @full_name.expression
    def full_name(cls):
        """Expresión SQL para consultas"""
        return case(
            (cls.middle_name.isnot(None), 
             func.concat(cls.last_name, ' ', cls.middle_name, ' ', cls.first_name)),
            else_=func.concat(cls.last_name, ' ', cls.first_name)
        )
```

### 2. Hybrid Property

La propiedad `full_name` ahora es una **hybrid property** de SQLAlchemy que:

- **En Python**: Calcula el nombre completo concatenando las partes
- **En SQL**: Genera expresión SQL para queries, filtros y ordenamiento

Esto permite seguir usando:
```python
# Queries
User.query.order_by(User.full_name.asc()).all()
User.query.filter(User.full_name.ilike('%Juan%')).all()

# Acceso a instancia
user = User.query.first()
print(user.full_name)  # "GARCÍA LÓPEZ JUAN CARLOS"
```

### 3. Migración (`migrations/versions/split_fullname_to_parts.py`)

La migración automática:
1. Agrega las nuevas columnas temporalmente como nullable
2. Lee CSV de activos para mapear estudiantes
3. Mapea usuarios administrativos con diccionario manual
4. Convierte columnas a NOT NULL si todo fue mapeado exitosamente
5. **Elimina la columna `full_name` de la base de datos**

### 4. Scripts SQL de Inserción

Actualizados para usar el nuevo formato:

```sql
-- Antes
INSERT INTO core_users (username, full_name, ...) VALUES
('mruiz', 'Mario Macario Ruiz Grijalva', ...);

-- Ahora
INSERT INTO core_users (username, first_name, last_name, middle_name, ...) VALUES
('mruiz', 'MARIO MACARIO', 'RUIZ', 'GRIJALVA', ...);
```

## Cambios en APIs

### API de Creación de Usuarios

El endpoint `POST /api/core/v1/users` ahora acepta ambos formatos:

```json
// Formato nuevo (recomendado)
{
  "first_name": "JUAN CARLOS",
  "last_name": "GARCÍA",
  "middle_name": "LÓPEZ",
  "email": "juan.gl@example.com",
  "user_type": "staff",
  "username": "jgarcia",
  "password": "temp123"
}

// Formato antiguo (retrocompatible)
{
  "full_name": "Juan Carlos García López",
  "email": "juan.gl@example.com",
  "user_type": "staff",
  "username": "jgarcia",
  "password": "temp123"
}
```

El backend automáticamente separa `full_name` en las tres partes si es necesario.

### Respuestas de API

Todas las respuestas siguen incluyendo `full_name` como campo calculado:

```json
{
  "id": 123,
  "first_name": "JUAN CARLOS",
  "last_name": "GARCÍA",
  "middle_name": "LÓPEZ",
  "full_name": "GARCÍA LÓPEZ JUAN CARLOS",
  "username": "jgarcia",
  "email": "juan.gl@example.com"
}
```

## Archivos Modificados

### Backend (Python)
- ✅ `itcj/core/models/user.py` - Modelo con hybrid property
- ✅ `itcj/core/routes/api/users.py` - API con retrocompatibilidad
- ✅ `itcj/apps/agendatec/routes/api/admin.py` - Coordinadores con nombres separados
- ✅ `migrations/versions/split_fullname_to_parts.py` - Migración y eliminación de columna

### SQL
- ✅ `database/DML/core/07_insert_user.sql` - Usuarios del sistema
- ✅ `database/DML/helpdesk/08_insert_technician_user.sql` - Técnicos

### Frontend (JavaScript/Templates)
- ℹ️ No requieren cambios - continúan usando `full_name` como string

## Compatibilidad

### ✅ Compatible
- Todos los templates Jinja2 (`user.full_name`)
- Todos los archivos JavaScript (reciben `full_name` del API)
- Queries de SQLAlchemy con `User.full_name`
- Ordenamiento y filtros por nombre completo

### ⚠️ Requiere Actualización
- Código que intente asignar directamente: ~~`user.full_name = "Nuevo Nombre"`~~
- Debe usar: `user.first_name = "NOMBRE"`, `user.last_name = "APELLIDO"`, etc.

## Convención de Nombres

### Formato Esperado
- **Nombres**: En MAYÚSCULAS
- **Orden**: `APELLIDO_PATERNO APELLIDO_MATERNO NOMBRE(S)`
- **Ejemplo**: `GARCÍA LÓPEZ JUAN CARLOS`

### Separación desde `full_name`
Si se recibe un nombre completo como string, se separa así:
- Si tiene 3+ palabras: las últimas 2 son apellidos, el resto nombre(s)
- Si tiene 2 palabras: primera = nombre, segunda = apellido paterno

## Próximos Pasos

1. ✅ Ejecutar migración: `flask db upgrade`
2. ✅ Ejecutar scripts SQL de inserción actualizados
3. ✅ Verificar que todos los usuarios tienen nombres correctamente separados
4. ℹ️ Actualizar documentación de API si es necesario
5. ℹ️ Comunicar cambios al equipo de desarrollo

## Rollback

Si es necesario revertir:
```bash
flask db downgrade -1
```

Esto recreará la columna `full_name` concatenando las partes automáticamente.

## Soporte

Para dudas o problemas, consultar:
- Documentación del modelo: `itcj/core/models/user.py`
- Migración: `migrations/versions/split_fullname_to_parts.py`
- Tests: (pendiente agregar tests específicos)
