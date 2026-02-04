# itcj/core/models/theme.py
from itcj.core.extensions import db
from sqlalchemy.dialects.postgresql import JSONB


class Theme(db.Model):
    """
    Modelo para gestionar temáticas visuales del sistema.
    Permite configurar decoraciones, colores y estilos que se aplican globalmente.
    """
    __tablename__ = "core_themes"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)

    # Fechas de activación automática (día/mes, se repiten anualmente)
    start_day = db.Column(db.Integer, nullable=True)    # 1-31
    start_month = db.Column(db.Integer, nullable=True)  # 1-12
    end_day = db.Column(db.Integer, nullable=True)      # 1-31
    end_month = db.Column(db.Integer, nullable=True)    # 1-12

    # Estado manual
    is_manually_active = db.Column(db.Boolean, nullable=False, default=False)
    is_enabled = db.Column(db.Boolean, nullable=False, default=True)  # Permite deshabilitar sin eliminar

    # Prioridad (menor número = mayor prioridad)
    priority = db.Column(db.Integer, nullable=False, default=100)

    # Configuración de colores (JSON)
    # Ejemplo: {"primary": "#ff0000", "secondary": "#00ff00", "accent": "#ffffff"}
    colors = db.Column(JSONB, nullable=False, default=dict)

    # CSS personalizado
    custom_css = db.Column(db.Text, nullable=False, default='')

    # Configuración de decoraciones (JSON)
    # Ejemplo: {"snowflakes": {"enabled": true, "count": 30}, "lights": {"enabled": true}}
    decorations = db.Column(JSONB, nullable=False, default=dict)

    # Archivos CSS/JS asociados (rutas relativas desde static/)
    css_file = db.Column(db.String(255), nullable=True)
    js_file = db.Column(db.String(255), nullable=True)

    # Preview/thumbnail
    preview_image = db.Column(db.String(255), nullable=True)

    # Auditoría
    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now(), nullable=False)
    created_by_id = db.Column(db.BigInteger, db.ForeignKey("core_users.id", ondelete="SET NULL"), nullable=True)

    # Relaciones
    created_by = db.relationship("User", backref="created_themes", foreign_keys=[created_by_id])

    def is_date_active(self):
        """Verifica si la temática está activa por fechas (día/mes anual)."""
        if not all([self.start_day, self.start_month, self.end_day, self.end_month]):
            return False

        from datetime import datetime
        today = datetime.now()
        current_day = today.day
        current_month = today.month

        # Crear tuplas para comparación (mes, día)
        start = (self.start_month, self.start_day)
        end = (self.end_month, self.end_day)
        current = (current_month, current_day)

        # Manejar caso que cruza fin de año (ej: 15 dic - 6 ene)
        if start > end:
            return current >= start or current <= end
        else:
            return start <= current <= end

    def is_active(self):
        """Verifica si la temática está activa (manual o por fechas)."""
        if not self.is_enabled:
            return False
        return self.is_manually_active or self.is_date_active()

    def get_date_range_display(self):
        """Retorna el rango de fechas en formato legible."""
        if not all([self.start_day, self.start_month, self.end_day, self.end_month]):
            return None

        months = ['', 'Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
                  'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
        return f"{self.start_day} {months[self.start_month]} - {self.end_day} {months[self.end_month]}"

    def to_dict(self, include_full=False):
        """Serializa el modelo a diccionario."""
        data = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "start_day": self.start_day,
            "start_month": self.start_month,
            "end_day": self.end_day,
            "end_month": self.end_month,
            "date_range_display": self.get_date_range_display(),
            "is_manually_active": self.is_manually_active,
            "is_enabled": self.is_enabled,
            "is_active": self.is_active(),
            "is_date_active": self.is_date_active(),
            "priority": self.priority,
            "preview_image": self.preview_image,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

        if include_full:
            data.update({
                "colors": self.colors or {},
                "custom_css": self.custom_css or "",
                "decorations": self.decorations or {},
                "css_file": self.css_file,
                "js_file": self.js_file,
            })

        return data

    def __repr__(self):
        status = "active" if self.is_active() else "inactive"
        return f"<Theme {self.id} '{self.name}' ({status})>"
