"""Oficio de asignación de sinodales (PDF al vuelo) -- spec fase 4 §12, R-C y R-F.

Se genera con WeasyPrint cada vez que se pide; nunca se guarda. Todo lo que
pinta la plantilla (`oficios/asignacion_sinodales.html`) llega precalculado en
`context`: la plantilla no decide nada.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from itcj2.apps.titulatec.utils.dates_es import MESES
from itcj2.core.utils.timezone import db_now

NO_SYNODALS_MSG = "Este proceso todavía no tiene sinodales asignados."

# Pie del oficio (constantes del instituto). Dominio institucional
# `cdjuarez.tecnm.mx` (ruling R7): el oficio real trae la errata «cdjurez», que
# no se copia a un documento oficial.
FOOTER_ADDRESS = ("Av. Tecnológico #1340 Fracc. El Crucero C.P. 32500 "
                  "Ciudad Juárez, Chihuahua.")
FOOTER_CONTACT = ("Tel. 656-688-2500 ext. 2001 direccion@cdjuarez.tecnm.mx - "
                  "www.cdjuarez.tecnm.mx")

DEFAULT_ADDRESSEE_CODE = "head_prof_studies_div"
DEFAULT_ATTN_CODE = "head_titulacion"

_TEMPLATE_NAME = "titulatec/oficios/asignacion_sinodales.html"


def _full_name(user) -> str:
    return " ".join(p for p in (user.first_name, user.last_name, user.middle_name) if p)


def _date_label(d) -> str:
    """'17/Marzo/2026' (dd/Mes/aaaa, mes capitalizado)."""
    return f"{d.day:02d}/{MESES[d.month].capitalize()}/{d.year}"


class OficioService:

    @staticmethod
    def holder(db: Session, position_code: str | None,
               title: str | None = None) -> dict | None:
        """Ocupante VIGENTE del puesto: `{"name", "title"}`, o None si el
        puesto no existe o está vacante (la línea del oficio va en blanco,
        aunque haya título personalizado).

        `title` (hallazgo 17): el título que fija el departamento en sus
        ajustes del oficio; vacío o None = el título del puesto en el
        organigrama (que usa nombres neutros como «Jefe(a) del
        Departamento de …» y no siempre coincide con el oficio real).
        """
        if not position_code:
            return None
        from itcj2.core.models.position import Position, UserPosition
        from itcj2.core.models.user import User
        from itcj2.core.services.authz_service import _active_position_filter

        fila = (db.query(User, Position.title)
                .join(UserPosition, UserPosition.user_id == User.id)
                .join(Position, Position.id == UserPosition.position_id)
                .filter(Position.code == position_code, _active_position_filter())
                .order_by(UserPosition.id.desc())
                .first())
        if fila is None:
            return None
        user, titulo_puesto = fila
        propio = " ".join(str(title or "").split())
        return {"name": _full_name(user), "title": propio or titulo_puesto}

    @staticmethod
    def department_frame(db: Session, process) -> dict:
        """Marco institucional compartido por el oficio y el Anexo III: `department`
        (None sin carrera mapeada), `settings`, `header`, `addressee`, `attn` y
        `signer` (jefe `head_{depto}`)."""
        from itcj2.apps.titulatec.models import DepartmentSettings, ProgramDepartment
        from itcj2.core.models.department import Department

        mapeo = db.get(ProgramDepartment, process.program_id) if process.program_id else None
        depto = db.get(Department, mapeo.department_id) if mapeo else None
        ajustes = db.get(DepartmentSettings, depto.id) if depto else None

        encabezado = (ajustes.oficio_header if ajustes and ajustes.oficio_header
                      else (f"Departamento de {depto.name}" if depto else ""))
        destinatario = OficioService.holder(
            db, ajustes.addressee_position_code if ajustes else DEFAULT_ADDRESSEE_CODE,
            title=ajustes.addressee_title if ajustes else None)
        atencion = OficioService.holder(
            db, ajustes.attn_position_code if ajustes else DEFAULT_ATTN_CODE,
            title=ajustes.attn_title if ajustes else None)
        firmante = OficioService.holder(db, f"head_{depto.code}") if depto else None
        return {"department": depto, "settings": ajustes, "header": encabezado,
                "addressee": destinatario, "attn": atencion, "signer": firmante}

    @staticmethod
    def context(db: Session, process) -> dict:
        """Todas las piezas del oficio (spec §12). `ValueError(NO_SYNODALS_MSG)`
        sin sinodales vigentes."""
        from itcj2.apps.titulatec.services.synodal_service import SynodalService

        sinodales = SynodalService.active_for_process(db, process.id)
        if not sinodales:
            raise ValueError(NO_SYNODALS_MSG)

        base = SynodalService._notice_base(db, process)
        marco = OficioService.department_frame(db, process)
        encabezado = marco["header"]
        destinatario = marco["addressee"]
        atencion = marco["attn"]
        firmante = marco["signer"]

        fecha = SynodalService.last_change_at(db, process.id) or db_now()
        alumno = base["alumno"] or ""
        return {
            "header": encabezado,
            "date_label": _date_label(fecha),
            "addressee": destinatario,
            "attn": atencion,
            "signer": firmante,
            "student_name": alumno.title(),
            "control_number": base["control"] or "",
            "program_name": base["carrera"] or "",
            "option_label": base["opcion"] or "",
            "project_title": (base["titulo"] or "").upper(),
            "synodals": [{
                "role_label": s["role_label"],
                "name": (s["name"] or "").upper(),
                "academic_degree": (s["academic_degree"] or "").upper(),
                "license": s["professional_license"] or "",
            } for s in sinodales],
            "footer_address": FOOTER_ADDRESS,
            "footer_contact": FOOTER_CONTACT,
        }

    @staticmethod
    def render_pdf(db: Session, process) -> bytes:
        from weasyprint import HTML

        from itcj2.apps.titulatec.pages.nav import titulatec_templates
        from itcj2.apps.titulatec.utils.certificate_pdf import CORE_STATIC_DIR

        ctx = OficioService.context(db, process)
        html = titulatec_templates.get_template(_TEMPLATE_NAME).render(**ctx)
        return HTML(string=html, base_url=str(CORE_STATIC_DIR)).write_pdf()

    @staticmethod
    def filename(db: Session, process) -> str:
        from itcj2.core.models.user import User

        alumno = db.get(User, process.student_id)
        control = (alumno.control_number if alumno and alumno.control_number
                   else f"proceso{process.id}")
        return f"{control}_OFICIO_SINODALES.pdf"
