"""
Páginas del Almacén (Warehouse) integradas en Help-Desk.

Rutas:
  GET /help-desk/warehouse/dashboard   → Dashboard del almacén
  GET /help-desk/warehouse/products    → Catálogo de productos
  GET /help-desk/warehouse/categories  → Categorías y subcategorías
  GET /help-desk/warehouse/entries     → Entradas de stock (FIFO)
  GET /help-desk/warehouse/movements   → Historial de movimientos
  GET /help-desk/warehouse/reports     → Reportes del almacén

Las vistas de listado (products/entries/movements) siguen el patrón canónico
HTMX: una sola URL sirve la PÁGINA completa (render server-side) o solo el
FRAGMENTO de resultados cuando llega ``HX-Request`` sin ``HX-Boosted`` (filtros
y paginación), replicando los filtros de la API ``/api/warehouse/v2/*``.
"""
import logging

from fastapi import APIRouter, Depends, Request

from itcj2.apps.helpdesk.pages.nav import render_helpdesk
from itcj2.apps.helpdesk.utils.warehouse_auth import require_warehouse_page

logger = logging.getLogger("itcj2.apps.helpdesk.pages.warehouse")

router = APIRouter(prefix="/warehouse", tags=["helpdesk-pages-warehouse"])


def _page_param(request: Request) -> int:
    try:
        return max(1, int(request.query_params.get("page", "1")))
    except (ValueError, TypeError):
        return 1


@router.get("/dashboard", name="helpdesk.pages.warehouse.dashboard")
async def dashboard(
    request: Request,
    user: dict = Depends(require_warehouse_page("warehouse.page.dashboard")),
):
    """Dashboard del almacén: métricas globales y productos bajo punto de restock."""
    return render_helpdesk(request, "helpdesk/warehouse/dashboard.html", {
        "active_page": "warehouse_dashboard",
    })


# ── Productos ───────────────────────────────────────────────────────────────
# Filtro de stock (fuente única para el filtro server-side). El color de cada
# estado lo dan clases de Bootstrap en el fragmento; aquí solo etiquetas.
_PRODUCT_STOCK_OPTIONS = [
    ("", "Todo el stock"),
    ("low", "Stock bajo"),
    ("ok", "Stock OK"),
]


def _query_products_ctx(request: Request, user: dict) -> dict:
    """Consulta el catálogo de productos del almacén para la vista.

    Reusada por la PÁGINA (render completo) y el PARTIAL HTMX (fragmento).
    Aplica los filtros de la barra (search/category/stock) server-side y pagina.
    El scope por ``department_code`` replica ``resolve_dept_code`` del endpoint
    API ``GET /products`` (admin ve todos los departamentos; el resto solo el
    suyo). El filtro de stock usa ``is_below_restock`` (calculado tras enriquecer
    con el stock disponible, igual que la API).
    """
    from itcj2.apps.warehouse.models.category import WarehouseCategory
    from itcj2.apps.warehouse.models.product import WarehouseProduct
    from itcj2.apps.warehouse.models.subcategory import WarehouseSubcategory
    from itcj2.apps.warehouse.services.utils import (
        enrich_product,
        get_stock_totals,
        resolve_dept_code,
    )
    from itcj2.database import SessionLocal
    from sqlalchemy import or_

    p = request.query_params
    search = (p.get("search", "") or "").strip() or None
    category = (p.get("category", "") or "").strip() or None
    stock = (p.get("stock", "") or "").strip() or None
    page = _page_param(request)
    per_page = 20

    _db = SessionLocal()
    try:
        department_code = resolve_dept_code(_db, user, None)

        q = _db.query(WarehouseProduct).filter(WarehouseProduct.is_active.is_(True))
        if department_code is not None:
            q = q.filter(WarehouseProduct.department_code == department_code)
        if category and category.isdigit():
            q = q.join(
                WarehouseSubcategory,
                WarehouseSubcategory.id == WarehouseProduct.subcategory_id,
            ).filter(WarehouseSubcategory.category_id == int(category))
        if search:
            term = f"%{search}%"
            q = q.filter(
                WarehouseProduct.name.ilike(term) | WarehouseProduct.code.ilike(term)
            )

        products = q.order_by(WarehouseProduct.name).all()
        stock_map = get_stock_totals(_db, [pr.id for pr in products])
        enriched = [enrich_product(pr, stock_map) for pr in products]

        if stock == "low":
            enriched = [e for e in enriched if e["is_below_restock"]]
        elif stock == "ok":
            enriched = [e for e in enriched if not e["is_below_restock"]]

        total = len(enriched)
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, total_pages)
        items = enriched[(page - 1) * per_page:(page - 1) * per_page + per_page]

        cat_q = _db.query(WarehouseCategory).filter(WarehouseCategory.is_active.is_(True))
        if department_code is not None:
            cat_q = cat_q.filter(or_(
                WarehouseCategory.department_code == department_code,
                WarehouseCategory.department_code.is_(None),
            ))
        categories = cat_q.order_by(WarehouseCategory.name).all()
        categories_data = [{"id": c.id, "name": c.name} for c in categories]
    finally:
        _db.close()

    return {
        "products": items,
        "total": total,
        "current_page": page,
        "total_pages": total_pages,
        "categories": categories_data,
        "f_search": search or "",
        "f_category": category or "",
        "f_stock": stock or "",
    }


@router.get("/products", name="helpdesk.pages.warehouse.products")
async def products(
    request: Request,
    user: dict = Depends(require_warehouse_page("warehouse.page.products")),
):
    """Catálogo de productos del almacén con stock actual.

    Una sola URL sirve dos representaciones (patrón canónico HTMX):
      - petición normal o boosteada → PÁGINA completa (tabla server-side).
      - petición HTMX no-boost (filtros/paginación) → solo el FRAGMENTO de
        resultados (#hd-products-results) + contador OOB.
    """
    from itcj2.templates import render

    ctx = _query_products_ctx(request, user)

    is_htmx = request.headers.get("hx-request") == "true"
    is_boost = request.headers.get("hx-boosted") == "true"
    if is_htmx and not is_boost:
        ctx["oob"] = True
        return render(request, "helpdesk/warehouse/_products_results.html", ctx)

    category_options = [("", "Todas las categorías")] + [
        (str(c["id"]), c["name"]) for c in ctx["categories"]
    ]
    filter_fields = [{
        "name": "category", "label": "Categoría", "icon": "fa-tag",
        "col": "col-6 col-md-3", "selected": ctx["f_category"], "options": category_options,
    }, {
        "name": "stock", "label": "Stock", "icon": "fa-cubes",
        "col": "col-6 col-md-2", "selected": ctx["f_stock"], "options": _PRODUCT_STOCK_OPTIONS,
    }]

    ctx.update({
        "active_page": "warehouse_products",
        "filter_fields": filter_fields,
    })
    return render_helpdesk(request, "helpdesk/warehouse/products.html", ctx)


@router.get("/categories", name="helpdesk.pages.warehouse.categories")
async def categories(
    request: Request,
    user: dict = Depends(require_warehouse_page("warehouse.page.categories")),
):
    """Gestión de categorías y subcategorías del almacén."""
    return render_helpdesk(request, "helpdesk/warehouse/categories.html", {
        "active_page": "warehouse_categories",
    })


# ── Entradas de stock ───────────────────────────────────────────────────────
# Filtro de vigencia (fuente única). El color lo dan clases de Bootstrap.
_ENTRY_VOIDED_OPTIONS = [
    ("", "Solo vigentes"),
    ("all", "Incluir anuladas"),
]


def _query_entries_ctx(request: Request, user: dict) -> dict:
    """Consulta las entradas de stock (lotes FIFO) para la vista.

    Reusada por la PÁGINA (render completo) y el PARTIAL HTMX (fragmento).
    Aplica los filtros de la barra (product/voided) server-side y pagina,
    replicando exactamente ``GET /stock-entries`` (mismo servicio y scope por
    ``department_code``).
    """
    from itcj2.apps.warehouse.models.product import WarehouseProduct
    from itcj2.apps.warehouse.services.stock_service import list_entries
    from itcj2.apps.warehouse.services.utils import resolve_dept_code
    from itcj2.database import SessionLocal

    p = request.query_params
    product = (p.get("product", "") or "").strip() or None
    voided = (p.get("voided", "") or "").strip() or None
    page = _page_param(request)
    per_page = 20
    pid = int(product) if product and product.isdigit() else None
    include_voided = voided in ("all", "1", "true")

    _db = SessionLocal()
    try:
        department_code = resolve_dept_code(_db, user, None)
        result = list_entries(
            _db,
            product_id=pid,
            department_code=department_code,
            include_voided=include_voided,
            page=page,
            per_page=per_page,
        )
        entries_data = [{
            "id": e.id,
            "product_code": e.product.code if e.product else None,
            "product_name": e.product.name if e.product else None,
            "purchase_folio": e.purchase_folio,
            "purchase_date": e.purchase_date.isoformat() if e.purchase_date else None,
            "quantity_original": e.quantity_original,
            "quantity_remaining": e.quantity_remaining,
            "unit_cost": e.unit_cost,
            "supplier": e.supplier,
            "is_exhausted": e.is_exhausted,
            "voided": e.voided,
        } for e in result.items]
        total = result.total
        total_pages = max(1, result.pages)
        current_page = result.page

        prod_q = _db.query(WarehouseProduct).filter(WarehouseProduct.is_active.is_(True))
        if department_code is not None:
            prod_q = prod_q.filter(WarehouseProduct.department_code == department_code)
        products_list = prod_q.order_by(WarehouseProduct.name).all()
        products_data = [
            {"id": pr.id, "code": pr.code, "name": pr.name} for pr in products_list
        ]
    finally:
        _db.close()

    return {
        "entries": entries_data,
        "total": total,
        "current_page": current_page,
        "total_pages": total_pages,
        "products": products_data,
        "f_product": product or "",
        "f_voided": voided or "",
    }


@router.get("/entries", name="helpdesk.pages.warehouse.entries")
async def entries(
    request: Request,
    user: dict = Depends(require_warehouse_page("warehouse.page.entries")),
):
    """Registro de entradas de stock (lotes FIFO).

    Una sola URL sirve dos representaciones (patrón canónico HTMX):
      - petición normal o boosteada → PÁGINA completa (tabla server-side).
      - petición HTMX no-boost (filtros/paginación) → solo el FRAGMENTO de
        resultados (#hd-entries-results) + contador OOB.
    """
    from itcj2.templates import render

    ctx = _query_entries_ctx(request, user)

    is_htmx = request.headers.get("hx-request") == "true"
    is_boost = request.headers.get("hx-boosted") == "true"
    if is_htmx and not is_boost:
        ctx["oob"] = True
        return render(request, "helpdesk/warehouse/_entries_results.html", ctx)

    product_options = [("", "Todos los productos")] + [
        (str(pr["id"]), f'{pr["code"]} — {pr["name"]}') for pr in ctx["products"]
    ]
    filter_fields = [{
        "name": "product", "label": "Producto", "icon": "fa-cube",
        "col": "col-12 col-md-4", "selected": ctx["f_product"], "options": product_options,
    }, {
        "name": "voided", "label": "Estado", "icon": "fa-filter",
        "col": "col-6 col-md-3", "selected": ctx["f_voided"], "options": _ENTRY_VOIDED_OPTIONS,
    }]

    ctx.update({
        "active_page": "warehouse_entries",
        "filter_fields": filter_fields,
    })
    return render_helpdesk(request, "helpdesk/warehouse/entries.html", ctx)


# ── Movimientos ─────────────────────────────────────────────────────────────
# Tipos de movimiento y app de origen (fuente única para los filtros).
_MOVEMENT_TYPE_OPTIONS = [
    ("", "Todos los tipos"),
    ("ENTRY", "Entrada"),
    ("CONSUMED", "Consumo"),
    ("ADJUSTED_IN", "Ajuste +"),
    ("ADJUSTED_OUT", "Ajuste -"),
    ("RETURNED", "Devolución"),
    ("VOIDED", "Anulado"),
]
_MOVEMENT_APP_OPTIONS = [
    ("", "Todas las apps"),
    ("helpdesk", "Help-Desk"),
    ("maint", "Mantenimiento"),
]


def _query_movements_ctx(request: Request, user: dict) -> dict:
    """Consulta el historial de movimientos del almacén para la vista.

    Reusada por la PÁGINA (render completo) y el PARTIAL HTMX (fragmento).
    Aplica los filtros de la barra (product/type/app) server-side y pagina,
    replicando exactamente ``GET /movements`` (mismo query y scope por
    ``department_code``).
    """
    from itcj2.apps.warehouse.models.movement import WarehouseMovement
    from itcj2.apps.warehouse.models.product import WarehouseProduct
    from itcj2.apps.warehouse.services.utils import resolve_dept_code
    from itcj2.database import SessionLocal
    from itcj2.models.base import paginate

    p = request.query_params
    product = (p.get("product", "") or "").strip() or None
    mtype = (p.get("type", "") or "").strip() or None
    app = (p.get("app", "") or "").strip() or None
    page = _page_param(request)
    per_page = 30
    pid = int(product) if product and product.isdigit() else None

    _db = SessionLocal()
    try:
        department_code = resolve_dept_code(_db, user, None)

        query = _db.query(WarehouseMovement)
        if department_code:
            query = query.join(
                WarehouseProduct, WarehouseProduct.id == WarehouseMovement.product_id
            ).filter(WarehouseProduct.department_code == department_code)
        if pid:
            query = query.filter(WarehouseMovement.product_id == pid)
        if mtype:
            query = query.filter(WarehouseMovement.movement_type == mtype.upper())
        if app:
            query = query.filter(WarehouseMovement.source_app == app)

        query = query.order_by(WarehouseMovement.performed_at.desc())
        result = paginate(query, page=page, per_page=per_page)

        prod_ids = {m.product_id for m in result.items}
        pmap = {}
        if prod_ids:
            for row in (
                _db.query(WarehouseProduct.id, WarehouseProduct.code, WarehouseProduct.name)
                .filter(WarehouseProduct.id.in_(prod_ids))
                .all()
            ):
                pmap[row.id] = {"code": row.code, "name": row.name}

        movements_data = [{
            "id": m.id,
            "product_id": m.product_id,
            "product_code": pmap.get(m.product_id, {}).get("code"),
            "product_name": pmap.get(m.product_id, {}).get("name"),
            "movement_type": m.movement_type,
            "quantity": m.quantity,
            "source_app": m.source_app,
            "source_ticket_id": m.source_ticket_id,
            "performed_at": m.performed_at.isoformat() if m.performed_at else None,
            "notes": m.notes,
        } for m in result.items]
        total = result.total
        total_pages = max(1, result.pages)
        current_page = result.page

        prod_q = _db.query(WarehouseProduct).filter(WarehouseProduct.is_active.is_(True))
        if department_code is not None:
            prod_q = prod_q.filter(WarehouseProduct.department_code == department_code)
        products_list = prod_q.order_by(WarehouseProduct.name).all()
        products_data = [
            {"id": pr.id, "code": pr.code, "name": pr.name} for pr in products_list
        ]
    finally:
        _db.close()

    return {
        "movements": movements_data,
        "total": total,
        "current_page": current_page,
        "total_pages": total_pages,
        "products": products_data,
        "f_product": product or "",
        "f_type": mtype or "",
        "f_app": app or "",
    }


@router.get("/movements", name="helpdesk.pages.warehouse.movements")
async def movements(
    request: Request,
    user: dict = Depends(require_warehouse_page("warehouse.page.movements")),
):
    """Historial completo de movimientos del almacén.

    Una sola URL sirve dos representaciones (patrón canónico HTMX):
      - petición normal o boosteada → PÁGINA completa (tabla server-side).
      - petición HTMX no-boost (filtros/paginación) → solo el FRAGMENTO de
        resultados (#hd-movements-results) + contador OOB.
    """
    from itcj2.templates import render

    ctx = _query_movements_ctx(request, user)

    is_htmx = request.headers.get("hx-request") == "true"
    is_boost = request.headers.get("hx-boosted") == "true"
    if is_htmx and not is_boost:
        ctx["oob"] = True
        return render(request, "helpdesk/warehouse/_movements_results.html", ctx)

    product_options = [("", "Todos los productos")] + [
        (str(pr["id"]), f'{pr["code"]} — {pr["name"]}') for pr in ctx["products"]
    ]
    filter_fields = [{
        "name": "product", "label": "Producto", "icon": "fa-cube",
        "col": "col-12 col-md-4", "selected": ctx["f_product"], "options": product_options,
    }, {
        "name": "type", "label": "Tipo", "icon": "fa-exchange-alt",
        "col": "col-6 col-md-3", "selected": ctx["f_type"], "options": _MOVEMENT_TYPE_OPTIONS,
    }, {
        "name": "app", "label": "App", "icon": "fa-th-large",
        "col": "col-6 col-md-3", "selected": ctx["f_app"], "options": _MOVEMENT_APP_OPTIONS,
    }]

    ctx.update({
        "active_page": "warehouse_movements",
        "filter_fields": filter_fields,
    })
    return render_helpdesk(request, "helpdesk/warehouse/movements.html", ctx)


@router.get("/reports", name="helpdesk.pages.warehouse.reports")
async def reports(
    request: Request,
    user: dict = Depends(require_warehouse_page("warehouse.page.reports")),
):
    """Reportes del almacén: consumo, movimientos y valoración de inventario."""
    return render_helpdesk(request, "helpdesk/warehouse/reports.html", {
        "active_page": "warehouse_reports",
    })
