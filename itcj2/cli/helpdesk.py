#!/usr/bin/env python3
"""
Comandos CLI de Helpdesk para itcj2 — sin Flask context.
Equivalente a itcj/apps/helpdesk/commands.py.
"""
import csv
import os
from datetime import date
from pathlib import Path

import click

PROJECT_ROOT = Path(__file__).parent.parent.parent

# ==================== MAPEO DE DEPARTAMENTOS ====================
DEPARTMENT_MAPPING = {
    "CENTRO DE COMPUTO": "comp_center",
    "CENTRO DE INFORMACION": "info_resources",
    "CIENCIAS BASICAS": "basic_sciences",
    "COMUNICACIÓN": "comms_diffusion",
    "DESARROLLO ACADEMICO": "academic_dev",
    "DIRECCION": "direction",
    "DIRECCION ": "direction",
    "DIV. EST. PROF": "prof_studies_div",
    "ECONOMICO ADMINISTARTIVO": "eco_admin_sci",
    "EDUCACION A DISTANCIA": "basic_sciences",
    "ELECTRICA-ELECTRONICA": "elec_electronics",
    "INGENIERIA INDUSTRIAL": "industrial_eng",
    "MANTENIMIENTO": "equipment_maint",
    "METAL MECANICA": "metal_mechanics",
    "METALMECANICA": "metal_mechanics",
    "METALMECANICA ": "metal_mechanics",
    "METALMECANICA TALLER": "metal_mechanics",
    "PLANEACION": "planning",
    "POSGRADO": "postgrad_research",
    "RECURSOS FINANCIEROS": "financial_resources",
    "RECURSOS MATERIALES ": "mat_services",
    "SERVICIOS ESCOLARES": "school_services",
    "SISTEMAS": "sys_computing",
    "SUBDIRECCION": "sub_planning",
    "SUBDIRECCION ACADEMICA": "sub_academic",
    "SUBDIRECCION ADMINISTRATIVA": "sub_admin_services",
    "VINCULACION": "tech_management",
    "SERVICIO SOCIAL": "tech_management",
    "SERVICIO MEDICO": "school_services",
    "CALIDAD": "direction",
    "MECATRONICA": "elec_electronics",
    "AUDITORIO": "comms_diffusion",
    "GIMNACIO": "extracurricular_act",
    "TITULACION": "prof_studies_div",
    "800´S": "industrial_eng",
    "INDUSTRIAL": "industrial_eng",
    "INDUSTRIAL ": "industrial_eng",
    "LABORATORIO DE ELECTRICA": "elec_electronics",
    "DELEGACIÓN SINDICAL": "union_delegation",
    "SINDICATO": "union_delegation",
}

IGNORE_DEPARTMENTS = ["GUILLOT", "GUILLOT "]


def normalize_storage(storage_str):
    storage_str = str(storage_str).strip().upper()
    if "TERA" in storage_str:
        return 1000
    try:
        return int(float(storage_str))
    except Exception:
        return 500


def normalize_ram(ram_str):
    try:
        return int(float(str(ram_str).strip()))
    except Exception:
        return 4


def determine_group_type(location_name):
    location_upper = location_name.upper()
    if any(word in location_upper for word in ["LABORATORIO", "LAB", "TALLER"]):
        return "LABORATORY"
    elif any(word in location_upper for word in ["SALA", "SALON", "AULA"]):
        return "CLASSROOM"
    elif any(word in location_upper for word in ["CUBICULO", "CUBÍCULO", "OFICINA", "JEFATURA"]):
        return "OFFICE"
    return "CLASSROOM"


@click.command("load-inventory-csv")
def load_inventory_csv():
    """
    Carga el inventario desde CSV y crea equipos y grupos.

    Lee database/CSV/inventario.csv y crea grupos + items de inventario.
    """
    from itcj2.apps.helpdesk.models import (
        InventoryCategory,
        InventoryGroup,
        InventoryGroupCapacity,
        InventoryItem,
    )
    from itcj2.core.models import Department
    from itcj2.database import SessionLocal

    csv_path = PROJECT_ROOT / "database" / "CSV" / "inventario.csv"

    if not csv_path.exists():
        click.echo(click.style(f"❌ Archivo no encontrado: {csv_path}", fg="red"))
        return

    click.echo(click.style("🚀 Iniciando carga de inventario desde CSV...", fg="cyan", bold=True))
    click.echo(f"📂 Archivo: {csv_path}")

    stats = {"total_rows": 0, "ignored": 0, "groups_created": 0, "items_created": 0, "errors": 0}
    created_groups = {}
    serial_counter = 1

    try:
        with SessionLocal() as db:
            computer_category = db.query(InventoryCategory).filter_by(code="computer").first()
            if not computer_category:
                click.echo(
                    click.style(
                        '❌ Categoría "computer" no encontrada. Ejecuta primero las migraciones.',
                        fg="red",
                    )
                )
                return

            click.echo(f"✅ Categoría encontrada: {computer_category.name} (ID: {computer_category.id})")

            with open(csv_path, "r", encoding="utf-8-sig") as csvfile:
                reader = csv.DictReader(csvfile, delimiter=";")
                click.echo("\n📊 Procesando registros...\n")

                for row in reader:
                    stats["total_rows"] += 1
                    try:
                        dept_name = row.get("DEPARTAMENTO", "").strip()
                        location = row.get("UBICACIÓN", "").strip() or row.get("UBICACION", "").strip()
                        quantity = int(row.get("CANTIDAD", "1").strip() or "1")
                        brand = row.get("MARCA", "").strip()
                        model = row.get("MODELO", "").strip()
                        storage = row.get("DISCO DURO ", "").strip() or row.get("DISCO DURO", "").strip()
                        ram = row.get("RAM (GB)", "").strip()

                        if not dept_name or dept_name in IGNORE_DEPARTMENTS:
                            stats["ignored"] += 1
                            continue

                        dept_code = DEPARTMENT_MAPPING.get(dept_name.upper())
                        if not dept_code:
                            click.echo(
                                click.style(
                                    f"⚠️  Fila {stats['total_rows']}: Departamento no mapeado: {dept_name}",
                                    fg="yellow",
                                )
                            )
                            stats["ignored"] += 1
                            continue

                        department = db.query(Department).filter_by(code=dept_code).first()
                        if not department:
                            click.echo(
                                click.style(
                                    f"❌ Fila {stats['total_rows']}: Departamento no encontrado: {dept_code}",
                                    fg="red",
                                )
                            )
                            stats["errors"] += 1
                            continue

                        storage_gb = normalize_storage(storage)
                        ram_gb = normalize_ram(ram)
                        specifications = {
                            "processor": "N/A",
                            "ram": str(ram_gb),
                            "storage": str(storage_gb),
                            "storage_type": "HDD",
                            "os": "Windows",
                        }

                        group = None
                        if quantity > 1 and location:
                            group_key = (dept_code, location.upper())
                            if group_key in created_groups:
                                group = created_groups[group_key]
                            else:
                                group_code = f"{dept_code.upper()}-{location.replace(' ', '-')[:20]}"
                                group = InventoryGroup(
                                    name=location,
                                    code=group_code,
                                    department_id=department.id,
                                    group_type=determine_group_type(location),
                                    description=f"Grupo creado desde CSV - {location}",
                                    created_by_id=10,
                                )
                                db.add(group)
                                db.flush()
                                capacity = InventoryGroupCapacity(
                                    group_id=group.id,
                                    category_id=computer_category.id,
                                    max_capacity=quantity + 5,
                                )
                                db.add(capacity)
                                created_groups[group_key] = group
                                stats["groups_created"] += 1
                                click.echo(
                                    click.style(
                                        f"✨ Grupo creado: {location} (capacidad: {quantity} equipos)",
                                        fg="green",
                                    )
                                )

                        for _ in range(quantity):
                            inventory_number = f"COMP-2022-{stats['items_created'] + 1:04d}"
                            serial_number = f"ITCJ-2022-{serial_counter:06d}"
                            serial_counter += 1
                            item = InventoryItem(
                                inventory_number=inventory_number,
                                category_id=computer_category.id,
                                brand=brand or "N/A",
                                model=model or "N/A",
                                serial_number=serial_number,
                                specifications=specifications,
                                department_id=department.id,
                                group_id=group.id if group else None,
                                location_detail=location if quantity == 1 else None,
                                status="ACTIVE",
                                acquisition_date=date.today(),
                                registered_by_id=10,
                            )
                            db.add(item)
                            stats["items_created"] += 1

                        if stats["items_created"] % 50 == 0:
                            db.flush()
                            click.echo(f"💾 Progreso: {stats['items_created']} equipos creados")

                    except Exception as e:
                        stats["errors"] += 1
                        click.echo(
                            click.style(f"❌ Error en fila {stats['total_rows']}: {str(e)}", fg="red")
                        )
                        continue

            db.commit()

        click.echo("\n" + "=" * 60)
        click.echo(click.style("✅ PROCESO COMPLETADO", fg="green", bold=True))
        click.echo("=" * 60)
        click.echo(f"📊 Total de filas procesadas: {stats['total_rows']}")
        click.echo(f"✨ Grupos creados: {stats['groups_created']}")
        click.echo(f"💻 Equipos creados: {stats['items_created']}")
        click.echo(f"⏭️  Registros ignorados: {stats['ignored']}")
        click.echo(f"❌ Errores: {stats['errors']}")
        click.echo("=" * 60)

    except Exception as e:
        click.echo(click.style(f"\n❌ ERROR CRÍTICO: {str(e)}", fg="red", bold=True))
        raise


@click.group("helpdesk")
def helpdesk_cli():
    """Comandos CLI del módulo Helpdesk."""


helpdesk_cli.add_command(load_inventory_csv)
