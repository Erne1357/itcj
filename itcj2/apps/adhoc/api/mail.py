"""API v2 del interruptor global de correo de Calidad.

Router **sin prefijo**: lo pone el padre en la fase de cableado
(``adhoc_router.include_router(mail_router, prefix="/mail-config")``), así que
las URLs finales son ``GET`` y ``PUT /api/adhoc/v2/mail-config``.

Dos correcciones respecto del legacy (``api_tasks.py:504-544``):

1. **El ``GET`` no escribe.** El legacy hacía ``db.session.add()`` +
   ``commit()`` dentro del ``GET /api/mail/config`` para autocrear la fila —
   un método seguro con efecto de escritura, que en itcj2 rompería cualquier
   caché o réplica de solo lectura. La fila ``id=1`` la siembra
   ``database/DML/adhoc/init/05_seed_catalogs.sql``.
2. **Las dos rutas exigen permiso.** En el legacy eran anónimas: cualquiera
   podía apagar el correo de todo el SGC con un ``curl``.

El ``PUT`` sí puede crear la fila si falta: no es un método seguro, y la
alternativa —dejar el panel muerto hasta que alguien corra el DML— es peor.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from itcj2.apps.adhoc.schemas.admin import MailConfigUpdate
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["adhoc-mail"])
logger = logging.getLogger(__name__)

__all__ = ["router"]


@router.get("")
def get_mail_config(
    request: Request,
    user: dict = require_perms("adhoc", ["adhoc.mail.api.read"]),
    db: DbSession = None,
):
    """Lee el estado del correo de Calidad. **Solo lectura.**

    Si la fila singleton no existe se responde 503 con un mensaje accionable en
    vez de crearla al vuelo: que falte significa que el DML de la app no se ha
    corrido, y taparlo aquí escondería un despliegue incompleto.
    """
    from itcj2.apps.adhoc.schemas.admin import MailConfigOut
    from itcj2.apps.adhoc.schemas.common import ok_item
    from itcj2.apps.adhoc.services.user_admin_service import MailConfigService

    cfg = MailConfigService.get(db)
    if cfg is None:
        raise HTTPException(
            status_code=503,
            detail="La configuración de correo de Calidad no está inicializada; "
                   "ejecuta database/DML/adhoc/init/05_seed_catalogs.sql",
        )

    return ok_item(MailConfigOut.model_validate(cfg, from_attributes=True).model_dump())


@router.put("")
def update_mail_config(
    payload: MailConfigUpdate,
    user: dict = require_perms("adhoc", ["adhoc.mail.api.update"]),
    db: DbSession = None,
):
    """Prende o apaga el envío de correo de Calidad.

    Es el gate que consulta ``email_helper`` antes de cada envío: con
    ``is_enabled=false`` los 10 puntos de disparo siguen registrando la
    notificación in-app y se saltan el correo.
    """
    from itcj2.apps.adhoc.schemas.admin import MailConfigOut
    from itcj2.apps.adhoc.schemas.common import ok_item
    from itcj2.apps.adhoc.services.user_admin_service import MailConfigService

    cfg = MailConfigService.set_enabled(db, payload.is_enabled)
    logger.info("[adhoc] Correo de Calidad actualizado por el usuario %s", user.get("sub"))

    return ok_item(MailConfigOut.model_validate(cfg, from_attributes=True).model_dump())
