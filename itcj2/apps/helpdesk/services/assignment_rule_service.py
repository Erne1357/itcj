"""
Servicio de reglas de asignacion automatica (CRUD + catalogos + validaciones).
No commitea: el endpoint audita y commitea (patron de api/config/).
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from itcj2.apps.helpdesk.models.area import Area
from itcj2.apps.helpdesk.models.assignment_rule import AssignmentRule
from itcj2.apps.helpdesk.models.category import Category
from itcj2.apps.helpdesk.models.priority import Priority
from itcj2.core.models.user import User


def _techs(db: Session, area: str) -> list:
    from itcj2.apps.helpdesk.services.assignment_service import get_technicians_by_area
    return get_technicians_by_area(db, area)


class AssignmentRuleService:
    @staticmethod
    def catalogs(db: Session) -> dict:
        areas = db.query(Area).filter_by(is_active=True).order_by(Area.display_order, Area.id).all()
        cats = (db.query(Category).filter_by(is_active=True)
                .order_by(Category.area, Category.display_order, Category.name).all())
        prios = (db.query(Priority).filter_by(is_active=True)
                 .order_by(Priority.display_order, Priority.id).all())
        return {
            "areas": [{"code": a.code, "label": a.label} for a in areas],
            "categories": [{"id": c.id, "area": c.area, "name": c.name} for c in cats],
            "priorities": [{"code": p.code, "label": p.label} for p in prios],
            "technicians_by_area": {
                a.code: [{"id": u.id, "name": u.full_name} for u in _techs(db, a.code)]
                for a in areas
            },
        }

    @staticmethod
    def list_rules(db: Session) -> list[dict]:
        rules = db.query(AssignmentRule).order_by(AssignmentRule.area, AssignmentRule.id).all()
        if not rules:
            return []
        elig = {a: {u.id for u in _techs(db, a)} for a in {r.area for r in rules}}
        ids = {i for r in rules for i in (r.technician_ids or [])}
        ids |= {r.last_assigned_user_id for r in rules if r.last_assigned_user_id}
        names = {u.id: u.full_name for u in db.query(User).filter(User.id.in_(ids)).all()}
        cat_ids = {r.category_id for r in rules if r.category_id}
        cat_names = {c.id: c.name for c in db.query(Category).filter(Category.id.in_(cat_ids)).all()}
        out = []
        for r in rules:
            d = r.to_dict()
            d["category_name"] = cat_names.get(r.category_id)
            d["technicians"] = [
                {"id": i, "name": names.get(i, str(i)), "eligible": i in elig[r.area]}
                for i in (r.technician_ids or [])
            ]
            d["last_assigned_name"] = names.get(r.last_assigned_user_id)
            out.append(d)
        return out

    @staticmethod
    def _validate(db: Session, area, category_id, priority, technician_ids, exclude_id=None):
        if not db.query(Area).filter_by(code=area, is_active=True).first():
            raise HTTPException(400, "Área inválida o inactiva")
        if category_id is not None:
            cat = db.get(Category, category_id)
            if not cat or not cat.is_active:
                raise HTTPException(400, "Categoría inválida o inactiva")
            if cat.area != area:
                raise HTTPException(400, "La categoría no pertenece al área")
        if priority is not None and not db.query(Priority).filter_by(
                code=priority, is_active=True).first():
            raise HTTPException(400, "Prioridad inexistente")
        if len(set(technician_ids)) != len(technician_ids):
            raise HTTPException(400, "Técnicos duplicados")
        valid = {u.id for u in _techs(db, area)}
        if any(i not in valid for i in technician_ids):
            raise HTTPException(400, "Todos los técnicos deben estar activos y ser del área")
        # La terna con NULL no la atrapa un UNIQUE de Postgres: se valida aqui.
        q = db.query(AssignmentRule.id).filter(
            AssignmentRule.area == area,
            AssignmentRule.category_id.is_(None) if category_id is None
            else AssignmentRule.category_id == category_id,
            AssignmentRule.priority.is_(None) if priority is None
            else AssignmentRule.priority == priority,
        )
        if exclude_id is not None:
            q = q.filter(AssignmentRule.id != exclude_id)
        if q.first():
            raise HTTPException(409, "Ya existe una regla para esa área, categoría y prioridad")

    @staticmethod
    def create_rule(db: Session, data: dict, user_id: int) -> AssignmentRule:
        AssignmentRuleService._validate(
            db, data["area"], data.get("category_id"), data.get("priority"), data["technician_ids"])
        rule = AssignmentRule(
            area=data["area"], category_id=data.get("category_id"), priority=data.get("priority"),
            strategy=data["strategy"], technician_ids=list(data["technician_ids"]),
            is_active=True, created_by_id=user_id, updated_by_id=user_id,
        )
        db.add(rule)
        db.flush()
        return rule

    @staticmethod
    def update_rule(db: Session, rule_id: int, data: dict, user_id: int) -> AssignmentRule:
        """`data` trae solo los campos enviados; category_id/priority aceptan None (= toda/cualquiera)."""
        rule = db.get(AssignmentRule, rule_id)
        if not rule:
            raise HTTPException(404, "Regla no encontrada")
        data = {k: v for k, v in data.items()
                if v is not None or k in ("category_id", "priority")}
        keys = ("area", "category_id", "priority", "technician_ids")
        # Solo activar/desactivar o cambiar el reparto no revalida: una regla con un
        # técnico que perdió el rol debe poder apagarse sin editarla primero.
        if any(k in data for k in keys):
            merged = {k: data.get(k, getattr(rule, k)) for k in keys}
            AssignmentRuleService._validate(
                db, merged["area"], merged["category_id"], merged["priority"],
                list(merged["technician_ids"]), exclude_id=rule.id)
        for k, v in data.items():
            setattr(rule, k, list(v) if k == "technician_ids" else v)
        rule.updated_by_id = user_id
        db.flush()
        return rule

    @staticmethod
    def delete_rule(db: Session, rule_id: int) -> None:
        rule = db.get(AssignmentRule, rule_id)
        if not rule:
            raise HTTPException(404, "Regla no encontrada")
        db.delete(rule)
        db.flush()
