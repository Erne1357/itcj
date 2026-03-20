// itcj2/apps/helpdesk/static/js/warehouse/products.js

const WarehouseProducts = (function () {
    'use strict';

    const API = '/api/warehouse/v2';
    let currentPage = 1;
    let totalPages = 1;
    let editingId = null;

    async function loadCategories() {
        try {
            const res = await fetch(`${API}/categories?with_subcategories=true`);
            const d = await res.json();
            const catFilter = document.getElementById('categoryFilter');
            const subcatSelect = document.getElementById('prodSubcategory');

            d.categories?.forEach(c => {
                catFilter.insertAdjacentHTML('beforeend',
                    `<option value="${c.id}">${c.name}</option>`);
                c.subcategories?.forEach(s => {
                    subcatSelect.insertAdjacentHTML('beforeend',
                        `<option value="${s.id}">[${c.name}] ${s.name}</option>`);
                });
            });
        } catch (e) { console.error('Error loading categories', e); }
    }

    async function load(page) {
        page = page || currentPage;
        currentPage = page;

        const search = document.getElementById('searchInput').value.trim();
        const category = document.getElementById('categoryFilter').value;
        const stockF = document.getElementById('stockFilter').value;

        const params = new URLSearchParams({ page, per_page: 20, include_stock: true });
        if (search) params.set('search', search);
        if (category) params.set('category_id', category);
        if (stockF === 'low') params.set('below_restock', 'true');

        document.getElementById('productsContainer').innerHTML = `
            <div class="text-center py-5">
                <div class="spinner-border text-primary" role="status"></div>
                <p class="text-muted mt-2">Cargando...</p>
            </div>`;

        try {
            const res = await fetch(`${API}/products?${params}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const d = await res.json();
            totalPages = d.pages || 1;
            console.log('Products loaded', d);
            renderProducts(d.products || []);
            renderPagination(d.total || 0, d.page || 1, d.pages || 1);
        } catch (err) {
            document.getElementById('productsContainer').innerHTML =
                '<div class="alert alert-danger m-3">Error al cargar los productos.</div>';
        }
    }

    function renderProducts(products) {
        if (!products.length) {
            document.getElementById('productsContainer').innerHTML = `
                <div class="text-center py-5 text-muted">
                    <i class="fas fa-cube fa-3x mb-3"></i>
                    <p>No se encontraron productos.</p>
                </div>`;
            return;
        }

        const rows = products.map(p => {
            const stock = p.total_stock ?? 0;
            const below = p.is_below_restock;
            const stockBadge = below
                ? `<span class="badge bg-danger">${stock}</span>`
                : `<span class="badge bg-success">${stock}</span>`;
            return `
                <tr>
                    <td><code>${p.code || '-'}</code></td>
                    <td>
                        <strong>${p.name}</strong>
                        ${p.description ? `<br><small class="text-muted">${p.description.substring(0,60)}</small>` : ''}
                    </td>
                    <td>${p.category_name || '-'}[ ${p.subcategory_name || '-'} ]</td>
                    <td>${stockBadge} <small class="text-muted">${p.unit_of_measure || ''}</small></td>
                    <td>${p.department_code || '<span class="text-muted">—</span>'}</td>
                    <td>
                        <button class="btn btn-sm btn-outline-primary" onclick="WarehouseProducts.showStock(${p.id}, '${p.name}')">
                            <i class="fas fa-boxes"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-secondary" onclick="WarehouseProducts.edit(${p.id})">
                            <i class="fas fa-edit"></i>
                        </button>
                    </td>
                </tr>`;
        }).join('');

        document.getElementById('productsContainer').innerHTML = `
            <div class="table-responsive">
                <table class="table table-hover mb-0">
                    <thead class="table-light">
                        <tr>
                            <th>Código</th><th>Nombre</th><th>Categoría</th>
                            <th>Stock</th><th>Dept.</th><th></th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>`;
    }

    function renderPagination(total, page, pages) {
        const pag = document.getElementById('pagination');
        pag.classList.remove('d-none');
        document.getElementById('paginationInfo').textContent =
            `Página ${page} de ${pages} (${total} productos)`;
        document.getElementById('btnPrev').disabled = page <= 1;
        document.getElementById('btnNext').disabled = page >= pages;
    }

    function prevPage() { if (currentPage > 1) load(currentPage - 1); }
    function nextPage() { if (currentPage < totalPages) load(currentPage + 1); }

    function reset() {
        document.getElementById('searchInput').value = '';
        document.getElementById('categoryFilter').value = '';
        document.getElementById('stockFilter').value = '';
        load(1);
    }

    async function showStock(productId, name) {
        document.getElementById('stockDetailBody').innerHTML =
            '<div class="text-center py-4"><div class="spinner-border text-primary" role="status"></div></div>';
        new bootstrap.Modal(document.getElementById('stockDetailModal')).show();

        try {
            const res = await fetch(`${API}/stock-entries?product_id=${productId}&per_page=20`);
            const d = await res.json();
            const entries = d.entries || [];

            const rows = entries.map(e => `
                <tr>
                    <td>${e.purchase_folio || '-'}</td>
                    <td>${e.purchase_date}</td>
                    <td>${e.quantity_remaining} / ${e.quantity_original}</td>
                    <td>$${parseFloat(e.unit_cost || 0).toFixed(2)}</td>
                    <td>${e.supplier || '-'}</td>
                    <td>${e.is_exhausted
                        ? '<span class="badge bg-secondary">Agotado</span>'
                        : '<span class="badge bg-success">Disponible</span>'}</td>
                </tr>`).join('');

            document.getElementById('stockDetailBody').innerHTML = entries.length
                ? `<h6 class="mb-3"><i class="fas fa-cube me-2"></i>${name} — Lotes</h6>
                   <div class="table-responsive">
                     <table class="table table-sm table-hover">
                       <thead class="table-light">
                         <tr><th>Folio</th><th>Fecha</th><th>Restante/Original</th><th>Costo Unit.</th><th>Proveedor</th><th>Estado</th></tr>
                       </thead>
                       <tbody>${rows}</tbody>
                     </table>
                   </div>`
                : '<p class="text-muted text-center py-4">No hay entradas de stock para este producto.</p>';
        } catch (e) {
            document.getElementById('stockDetailBody').innerHTML =
                '<div class="alert alert-danger">Error al cargar el detalle de stock.</div>';
        }
    }

    async function edit(productId) {
        editingId = productId;
        document.getElementById('productModalTitle').innerHTML =
            '<i class="fas fa-edit me-2"></i>Editar Producto';
        try {
            const res = await fetch(`${API}/products/${productId}`);
            const p = await res.json();
            document.getElementById('prodName').value = p.name || '';
            document.getElementById('prodUnit').value = p.unit_of_measure || '';
            document.getElementById('prodLeadTime').value = p.lead_time_days || 7;
            document.getElementById('prodDept').value = p.department_code || '';
            document.getElementById('prodDesc').value = p.description || '';
            if (p.subcategory_id) document.getElementById('prodSubcategory').value = p.subcategory_id;
        } catch (e) {
            console.error('Error loading product', e);
        }
        new bootstrap.Modal(document.getElementById('productModal')).show();
    }

    async function save() {
        const body = {
            name: document.getElementById('prodName').value.trim(),
            unit_of_measure: document.getElementById('prodUnit').value.trim(),
            lead_time_days: parseInt(document.getElementById('prodLeadTime').value) || 7,
            subcategory_id: parseInt(document.getElementById('prodSubcategory').value) || null,
            department_code: document.getElementById('prodDept').value.trim() || null,
            description: document.getElementById('prodDesc').value.trim() || null,
        };

        if (!body.name || !body.unit_of_measure || !body.subcategory_id) {
            HelpdeskUtils.showToast('Completa los campos obligatorios.', 'warning');
            return;
        }

        const method = editingId ? 'PATCH' : 'POST';
        const url = editingId ? `${API}/products/${editingId}` : `${API}/products`;

        try {
            const res = await fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail?.message || err.detail || 'Error al guardar');
            }
            bootstrap.Modal.getInstance(document.getElementById('productModal')).hide();
            HelpdeskUtils.showToast('Producto guardado.', 'success');
            editingId = null;
            load(1);
        } catch (err) {
            HelpdeskUtils.showToast(err.message, 'danger');
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.getElementById('productModal').addEventListener('hidden.bs.modal', function () {
            editingId = null;
            document.getElementById('productModalTitle').innerHTML =
                '<i class="fas fa-cube me-2"></i>Nuevo Producto';
            document.getElementById('prodName').value = '';
            document.getElementById('prodUnit').value = '';
            document.getElementById('prodLeadTime').value = 7;
            document.getElementById('prodSubcategory').value = '';
            document.getElementById('prodDept').value = 'comp_center';
            document.getElementById('prodDesc').value = '';
        });
        loadCategories();
        load(1);
    });

    return { load, reset, prevPage, nextPage, showStock, edit, save };
})();
