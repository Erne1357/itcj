"""
Servicio para registro masivo de equipos de inventario
"""
from datetime import datetime, date, timedelta
import logging
import re

from sqlalchemy.orm import Session

from itcj2.apps.helpdesk.models.inventory_item import InventoryItem
from itcj2.apps.helpdesk.models.inventory_category import InventoryCategory
from itcj2.apps.helpdesk.models.inventory_history import InventoryHistory
from itcj2.core.models.department import Department

logger = logging.getLogger(__name__)


class InventoryBulkService:
    """Servicio para operaciones de registro masivo"""

    @staticmethod
    def get_next_inventory_number(db: Session, category_id: int, year: int = None) -> str:
        """
        Genera el siguiente número de inventario para una categoría.
        Formato: PREFIX-YYYY-NNNN
        """
        if year is None:
            year = datetime.now().year

        category = db.get(InventoryCategory, category_id)
        if not category:
            raise ValueError(f"Categoría {category_id} no encontrada")

        prefix = category.inventory_prefix
        year_str = str(year)

        last_item = db.query(InventoryItem).filter(
            InventoryItem.category_id == category_id,
            InventoryItem.inventory_number.like(f"{prefix}-{year_str}-%")
        ).order_by(InventoryItem.inventory_number.desc()).first()

        if last_item:
            parts = last_item.inventory_number.split('-')
            if len(parts) == 3:
                last_num = int(parts[2])
                next_num = last_num + 1
            else:
                next_num = 1
        else:
            next_num = 1

        return f"{prefix}-{year_str}-{next_num:04d}"

    @staticmethod
    def parse_serial_list(raw_text: str, separator: str = "auto") -> list[str]:
        """
        Parsea una lista de seriales de texto plano.
        Retorna lista de strings limpios (sin vacíos ni espacios extra).

        Separadores soportados:
          "comma"     → ,
          "semicolon" → ;
          "space"     → espacio/tabs
          "newline"   → salto de línea (\\n)
          "auto"      → detecta el separador más común en el texto
        """
        if not raw_text or not raw_text.strip():
            return []

        text = raw_text.strip()

        if separator == "auto":
            counts = {
                "\n": text.count("\n"),
                ",": text.count(","),
                ";": text.count(";"),
            }
            best = max(counts, key=counts.get)
            if counts[best] > 0:
                separator = {"\\n": "newline", ",": "comma", ";": "semicolon"}[best] if best != "\n" else "newline"
                separator_char = best
            else:
                separator = "space"
                separator_char = None
        else:
            separator_char = None

        if separator == "comma":
            parts = text.split(",")
        elif separator == "semicolon":
            parts = text.split(";")
        elif separator == "space":
            parts = re.split(r'\s+', text)
        elif separator == "newline":
            parts = text.splitlines()
        elif separator_char is not None:
            parts = text.split(separator_char)
        else:
            parts = re.split(r'\s+', text)

        return [p.strip() for p in parts if p.strip()]

    @staticmethod
    def validate_bulk_serials(db: Session, data: dict) -> dict:
        """
        Valida las listas de seriales antes de un registro masivo.
        Verifica duplicados dentro de cada lista y contra la BD.

        data keys: supplier_serial_list, itcj_serial_list, id_tecnm_list, serial_separator
        """
        separator = data.get("serial_separator", "newline")
        result = {
            "valid": True,
            "warnings": [],
            "errors": [],
            "counts": {},
        }

        serial_fields = [
            ("supplier_serial_list", "supplier_serial", "Serial proveedor"),
            ("itcj_serial_list", "itcj_serial", "Serial ITCJ"),
            ("id_tecnm_list", "id_tecnm", "ID TecNM"),
        ]

        for list_key, db_field, label in serial_fields:
            raw = data.get(list_key, "")
            if not raw:
                result["counts"][list_key] = 0
                continue

            parsed = InventoryBulkService.parse_serial_list(raw, separator)
            result["counts"][list_key] = len(parsed)

            seen = set()
            dupes_in_list = []
            for val in parsed:
                if val in seen:
                    dupes_in_list.append(val)
                seen.add(val)

            if dupes_in_list:
                result["valid"] = False
                result["errors"].append({
                    "field": list_key,
                    "message": f"{label}: duplicados en la lista: {dupes_in_list}",
                })

            if parsed:
                existing = db.query(InventoryItem).filter(
                    getattr(InventoryItem, db_field).in_(parsed)
                ).all()
                if existing:
                    dupes_in_db = [getattr(e, db_field) for e in existing]
                    result["valid"] = False
                    result["errors"].append({
                        "field": list_key,
                        "message": f"{label}: ya existen en BD: {dupes_in_db}",
                        "details": [
                            {"serial": getattr(e, db_field), "inventory_number": e.inventory_number}
                            for e in existing
                        ],
                    })

        return result

    @staticmethod
    def bulk_create_items(db: Session, data: dict, registered_by_id: int) -> list:
        """
        Crea múltiples equipos con las mismas especificaciones base.
        Los seriales se asignan posicionalmente desde las listas.

        data keys:
          category_id, brand, model, specifications, acquisition_date,
          warranty_expiration, maintenance_frequency_days, notes,
          department_id,          (departamento por defecto para todos)
          quantity,               (número de equipos, alternativa a items)
          items,                  (overrides por posición: department_id, location_detail, etc.)
          supplier_serial_list,   (texto con seriales de proveedor)
          itcj_serial_list,       (texto con seriales ITCJ)
          id_tecnm_list,          (texto con IDs TecNM)
          serial_separator        (separador de las listas)
        """
        try:
            created_items = []
            cc_department = db.query(Department).filter_by(code='comp_center').first()

            if not cc_department:
                raise ValueError("Departamento del Centro de Cómputo (comp_center) no encontrado")

            category = db.get(InventoryCategory, data['category_id'])
            if not category:
                raise ValueError(f"Categoría {data['category_id']} no encontrada")

            acquisition_date = None
            if data.get('acquisition_date'):
                acquisition_date = date.fromisoformat(data['acquisition_date'])

            warranty_expiration = None
            if data.get('warranty_expiration'):
                warranty_expiration = date.fromisoformat(data['warranty_expiration'])

            next_maintenance_date = None
            if data.get('maintenance_frequency_days') and acquisition_date:
                next_maintenance_date = acquisition_date + timedelta(days=data['maintenance_frequency_days'])

            # Determinar lista de items/overrides
            items_overrides = data.get('items') or []
            quantity = data.get('quantity')
            if not items_overrides and quantity:
                items_overrides = [{} for _ in range(int(quantity))]
            if not items_overrides:
                raise ValueError("Se requiere 'items' o 'quantity' para el registro masivo")

            # Parsear listas de seriales
            separator = data.get('serial_separator', 'newline')
            supplier_serials = InventoryBulkService.parse_serial_list(
                data.get('supplier_serial_list', ''), separator
            )
            itcj_serials = InventoryBulkService.parse_serial_list(
                data.get('itcj_serial_list', ''), separator
            )
            id_tecnm_parsed = InventoryBulkService.parse_serial_list(
                data.get('id_tecnm_list', ''), separator
            )

            n = len(items_overrides)
            for list_name, lst in [
                ("supplier_serial_list", supplier_serials),
                ("itcj_serial_list", itcj_serials),
                ("id_tecnm_list", id_tecnm_parsed),
            ]:
                if lst and len(lst) != n:
                    logger.warning(
                        f"bulk_create: '{list_name}' tiene {len(lst)} entradas pero se crean {n} equipos"
                    )

            default_department_id = data.get('department_id')

            for i, item_data in enumerate(items_overrides):
                inventory_number = InventoryBulkService.get_next_inventory_number(db, data['category_id'])

                department_id = item_data.get('department_id') or default_department_id
                status = 'ACTIVE'

                if not department_id:
                    department_id = cc_department.id
                    status = 'PENDING_ASSIGNMENT'

                s_serial = supplier_serials[i] if i < len(supplier_serials) else None
                i_serial = itcj_serials[i] if i < len(itcj_serials) else None
                t_id = id_tecnm_parsed[i] if i < len(id_tecnm_parsed) else None

                item = InventoryItem(
                    inventory_number=inventory_number,
                    category_id=data['category_id'],
                    brand=data.get('brand'),
                    model=data.get('model'),
                    supplier_serial=s_serial,
                    itcj_serial=i_serial,
                    id_tecnm=t_id,
                    specifications=data.get('specifications'),
                    department_id=department_id,
                    assigned_to_user_id=item_data.get('assigned_to_user_id'),
                    group_id=item_data.get('group_id'),
                    location_detail=item_data.get('location_detail'),
                    status=status,
                    acquisition_date=acquisition_date,
                    warranty_expiration=warranty_expiration,
                    maintenance_frequency_days=data.get('maintenance_frequency_days'),
                    next_maintenance_date=next_maintenance_date,
                    notes=data.get('notes'),
                    registered_by_id=registered_by_id,
                    is_active=True
                )

                db.add(item)
                db.flush()

                history = InventoryHistory(
                    item_id=item.id,
                    event_type='REGISTERED',
                    old_value=None,
                    new_value={
                        'inventory_number': item.inventory_number,
                        'category_id': item.category_id,
                        'status': item.status,
                        'department_id': item.department_id,
                    },
                    notes='Equipo registrado mediante registro masivo',
                    performed_by_id=registered_by_id
                )
                db.add(history)
                created_items.append(item)

            db.commit()
            logger.info(f"Registro masivo: {len(created_items)} equipos creados por usuario {registered_by_id}")

            return created_items

        except Exception as e:
            db.rollback()
            logger.error(f"Error en registro masivo: {str(e)}")
            raise
