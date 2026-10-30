"""API de la secretaria: pestaña Estadísticas. Rutas bajo ``/api/prorrogas/v2/estadisticas``."""
from fastapi import APIRouter, Response

from itcj2.apps.prorrogas_tec.services.stats_service import StatsService
from itcj2.core.utils.timezone import db_now
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["prorrogas_tec-estadisticas"])

_STATS = ["prorrogas_tec.stats.api.read"]


@router.get("/semestres", name="prorrogas_tec.api.estadisticas.semestres")
def semestres(db: DbSession, user: dict = require_perms("prorrogas_tec", _STATS)):
    return StatsService.semestres(db)


@router.get("", name="prorrogas_tec.api.estadisticas.resumen")
def resumen(db: DbSession, semestre: str | None = None, user: dict = require_perms("prorrogas_tec", _STATS)):
    return StatsService.resumen(db, semestre, db_now().date())


@router.get("/detalle.csv", name="prorrogas_tec.api.estadisticas.csv")
def detalle_csv(db: DbSession, semestre: str | None = None, user: dict = require_perms("prorrogas_tec", _STATS)):
    texto = StatsService.csv(db, semestre, db_now().date())
    return Response(content=texto.encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="estadisticas-prorrogas.csv"'})
