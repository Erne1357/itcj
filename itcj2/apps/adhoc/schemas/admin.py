"""Schemas Pydantic v2 de la **administración** de la app Adhoc (Calidad).

Cubre dos superficies pequeñas del panel de control:

* ``/mail-config`` — el interruptor global de correo del SGC (singleton).
* ``/users``       — el módulo **recortado** de usuarios (decisión D8 del plan).

Sobre el recorte de ``/users``: el legacy daba de alta usuarios y cambiaba
contraseñas desde esta pantalla, **sin autenticación y con ``role_id=4``
hardcodeado** (que en la BD real es ``admin``) — una escalada de privilegios
trivial. Aquí solo se listan los usuarios que ya tienen acceso a Calidad y se
les asigna el rol de la app y sus áreas. El alta de personas, las contraseñas y
la revocación de acceso viven en ``/itcj/config``, que es el dueño del core.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from itcj2.apps.adhoc.schemas.common import AdhocSchema

__all__ = [
    "AdhocAppRole",
    "ADHOC_APP_ROLES",
    "MailConfigOut",
    "MailConfigUpdate",
    "AdhocUserAreaOut",
    "AdhocUserOut",
    "AssignAppRoleIn",
    "AssignAreasIn",
]


# ==========================================================================
# Roles de la app
# ==========================================================================

#: Los 5 roles que ``database/DML/adhoc/init/01_insert_roles.sql`` y
#: ``03_insert_role_permission.sql`` reconocen para Calidad. ``admin`` es el rol
#: global del core (no lo crea el DML de adhoc, solo le asigna los 82 permisos);
#: los otros 4 nacen con este DML.
#:
#: Vocabulario cerrado igual que los de ``utils/constants.py``, pero declarado
#: aquí porque no tiene respaldo en un ``CheckConstraint``: lo respalda la
#: matriz de ``core_role_permissions``. Asignar un rol fuera de esta lista daría
#: un usuario con acceso a la app y **cero permisos** — 403 en las 26 páginas.
AdhocAppRole = Literal[
    "admin", "consult", "supervisor_doc", "supervisor_inc", "supervisor_prog",
]
ADHOC_APP_ROLES: tuple[str, ...] = (
    "admin", "consult", "supervisor_doc", "supervisor_inc", "supervisor_prog",
)


# ==========================================================================
# Configuración de correo
# ==========================================================================

class MailConfigOut(BaseModel):
    """Estado del interruptor global de correo (``adhoc_mail_config``, id=1)."""

    model_config = ConfigDict(from_attributes=True)

    is_enabled: bool
    updated_at: Optional[datetime] = None


class MailConfigUpdate(AdhocSchema):
    """``PUT /mail-config`` — solo se puede prender y apagar.

    El legacy también guardaba ``sender_name``/``sender_email``; son columnas
    muertas (el remitente sale del buzón Graph conectado) y no existen en el
    modelo nuevo.
    """

    is_enabled: bool


# ==========================================================================
# Usuarios
# ==========================================================================

class AdhocUserAreaOut(BaseModel):
    """Área de Calidad asignada a un usuario."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    color: Optional[str] = None
    is_active: bool = True


class AdhocUserOut(BaseModel):
    """Un usuario con acceso a Calidad, con su rol de app y sus áreas.

    ``roles`` es una **lista** aunque ``PUT /users/{id}/app-role`` asigne uno
    solo: ``core_user_app_roles`` es (user, app, role) y admite varias filas, así
    que un usuario provisionado a mano desde ``/itcj/config`` puede traer más de
    uno. Mostrar solo el primero escondería la realidad de la BD.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: Optional[str] = None
    control_number: Optional[str] = None
    email: Optional[str] = None
    first_name: str
    last_name: str
    middle_name: Optional[str] = None
    full_name: str
    is_active: bool = True
    roles: list[str] = Field(default_factory=list)
    areas: list[AdhocUserAreaOut] = Field(default_factory=list)


class AssignAppRoleIn(AdhocSchema):
    """``PUT /users/{id}/app-role`` — fija el rol del usuario dentro de Calidad.

    Reemplaza **todas** las filas de ``core_user_app_roles`` del par
    (usuario, adhoc) por una sola. No revoca el acceso: para eso está
    ``/itcj/config``, que es el dueño del provisioning del core.
    """

    role: AdhocAppRole


class AssignAreasIn(AdhocSchema):
    """``PUT /users/{id}/areas`` — reemplaza las áreas del usuario.

    Lista vacía = quitarle todas las áreas (operación legítima, no un error).
    """

    area_ids: list[int] = Field(default_factory=list)

    @field_validator("area_ids")
    @classmethod
    def _dedupe(cls, values: list[int]) -> list[int]:
        return list(dict.fromkeys(values))
