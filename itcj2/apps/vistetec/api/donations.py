"""
Donations API v2 — 8 endpoints.
Fuente: itcj/apps/vistetec/routes/api/donations.py
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from sqlalchemy import or_
from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.vistetec.schemas.donations import GarmentDonationBody, PantryDonationBody

router = APIRouter(tags=["vistetec-donations"])
logger = logging.getLogger(__name__)


@router.get("/search-donors")
def search_donors(
    q: str = "",
    user: dict = require_perms("vistetec", ["vistetec.donations.api.register"]),
    db: DbSession = None,
):
    """Busca estudiantes/usuarios para asignar como donantes."""
    from itcj.core.models.user import User

    q = q.strip()
    if len(q) < 2:
        return []

    users = (
        User.query.filter(
            User.is_active == True,
            or_(
                User.control_number.ilike(f"%{q}%"),
                User.first_name.ilike(f"%{q}%"),
                User.last_name.ilike(f"%{q}%"),
            ),
        )
        .limit(10)
        .all()
    )

    return [
        {
            "id": u.id,
            "name": u.full_name,
            "control_number": u.control_number,
        }
        for u in users
    ]


@router.get("")
def list_donations(
    page: int = 1,
    per_page: int = 20,
    type: Optional[str] = None,
    user: dict = require_perms("vistetec", ["vistetec.donations.api.view_all"]),
    db: DbSession = None,
):
    """Lista todas las donaciones."""
    from itcj.apps.vistetec.services import donation_service

    return donation_service.get_donations(
        donation_type=type,
        page=page,
        per_page=per_page,
    )


@router.get("/my-donations")
def list_my_donations(
    page: int = 1,
    per_page: int = 20,
    user: dict = require_perms("vistetec", ["vistetec.donations.api.view_own"]),
    db: DbSession = None,
):
    """Lista mis donaciones como donante."""
    from itcj.apps.vistetec.services import donation_service

    return donation_service.get_my_donations(
        user_id=user["sub"],
        page=page,
        per_page=per_page,
    )


@router.get("/stats")
def get_donation_stats(
    mine: bool = False,
    user: dict = require_perms("vistetec", ["vistetec.donations.api.stats"]),
    db: DbSession = None,
):
    """Estadísticas de donaciones. Con mine=true retorna solo las propias."""
    from itcj.apps.vistetec.services import donation_service

    donor_id = user["sub"] if mine else None
    return donation_service.get_donation_stats(donor_id=donor_id)


@router.get("/top-donors")
def get_top_donors(
    limit: int = 10,
    user: dict = require_perms("vistetec", ["vistetec.donations.api.stats"]),
    db: DbSession = None,
):
    """Top donadores."""
    from itcj.apps.vistetec.services import donation_service

    return donation_service.get_top_donors(limit=limit)


@router.get("/recent")
def get_recent_donations(
    limit: int = 10,
    user: dict = require_perms("vistetec", ["vistetec.donations.api.view_all"]),
    db: DbSession = None,
):
    """Donaciones más recientes."""
    from itcj.apps.vistetec.services import donation_service

    donations = donation_service.get_recent_donations(limit=limit)
    return [d.to_dict(include_relations=True) for d in donations]


@router.post("/garment", status_code=201)
def register_garment_donation(
    body: GarmentDonationBody,
    user: dict = require_perms("vistetec", ["vistetec.donations.api.register"]),
    db: DbSession = None,
):
    """Registra una donación de prenda (existente o nueva)."""
    from itcj.apps.vistetec.services import donation_service

    if not body.garment_id and not body.garment:
        raise HTTPException(
            400,
            detail={"error": "missing_garment", "message": "Se requiere garment_id o datos de prenda"},
        )

    try:
        registered_by_id = user["sub"]

        if body.garment_id:
            donation = donation_service.register_garment_donation(
                registered_by_id=registered_by_id,
                garment_id=body.garment_id,
                donor_id=body.donor_id,
                donor_name=body.donor_name,
                notes=body.notes,
            )
        else:
            garment_data = body.garment.model_dump()
            donation = donation_service.register_new_garment_donation(
                registered_by_id=registered_by_id,
                garment_data=garment_data,
                donor_id=body.donor_id,
                donor_name=body.donor_name,
                notes=body.notes,
            )

        logger.info(f"Donación de prenda registrada por usuario {registered_by_id}")
        return {
            "message": "Donación registrada exitosamente",
            "donation": donation.to_dict(include_relations=True),
        }
    except ValueError as e:
        raise HTTPException(400, detail={"error": "validation_error", "message": str(e)})


@router.post("/pantry", status_code=201)
def register_pantry_donation(
    body: PantryDonationBody,
    user: dict = require_perms("vistetec", ["vistetec.donations.api.register"]),
    db: DbSession = None,
):
    """Registra una donación de despensa."""
    from itcj.apps.vistetec.services import donation_service

    try:
        registered_by_id = user["sub"]
        donation = donation_service.register_pantry_donation(
            registered_by_id=registered_by_id,
            pantry_item_id=body.pantry_item_id,
            quantity=body.quantity,
            donor_id=body.donor_id,
            donor_name=body.donor_name,
            campaign_id=body.campaign_id,
            notes=body.notes,
        )
        logger.info(f"Donación de despensa registrada por usuario {registered_by_id}")
        return {
            "message": "Donación registrada exitosamente",
            "donation": donation.to_dict(include_relations=True),
        }
    except ValueError as e:
        raise HTTPException(400, detail={"error": "validation_error", "message": str(e)})


@router.get("/{donation_id}")
def get_donation(
    donation_id: int,
    user: dict = require_perms("vistetec", ["vistetec.donations.api.view_all"]),
    db: DbSession = None,
):
    """Obtiene una donación por ID."""
    from itcj.apps.vistetec.services import donation_service

    donation = donation_service.get_donation_by_id(donation_id)
    if not donation:
        raise HTTPException(404, detail={"error": "not_found", "message": "Donación no encontrada"})
    return donation.to_dict(include_relations=True)
