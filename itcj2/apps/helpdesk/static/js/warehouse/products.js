// itcj2/apps/helpdesk/static/js/warehouse/products.js
//
// Isla de cliente de la vista de PRODUCTOS del almacén. La lista, los filtros y
// la paginación se renderizan SERVER-SIDE (HTMX partial #hd-products-results);
// aquí solo quedan los bits genuinamente de cliente: el modal Crear/Editar (BS5),
// el modal de detalle de stock, y la delegación de los botones de las filas.
// Tras una mutación se dispara `refresh` sobre el form de filtros → HTMX recarga
// el fragmento con los filtros vigentes.

const WarehouseProducts = (function () {
    'use strict';

    const API = '/api/warehouse/v2';
    let editingId = null;
    let _onProductModalHidden = null;
    let _resultsDelegate = null;
    let _clearHandler = null;

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = String(text == null ? '' : text);
        return div.innerHTML;
    }

    // Recarga el fragmento server-side manteniendo los filtros vigentes.
    function refreshResults() {
        const form = document.getElementById('hd-filter-form');
        if (form && window.htmx) window.htmx.trigger(form, 'refresh');
    }

    // Puebla SOLO el select de subcategorías del modal (los filtros ya son server-side).
    async function loadSubcategories() {
        const subcatSelect = document.getElementById('prodSubcategory');
        if (!subcatSelect) return;
        try {
            const res = await fetch(`${API}/categories?with_subcategories=true`);
            const d = await res.json();
            (d.categories || []).forEach(c => {
                (c.subcategories || []).forEach(s => {
                    const opt = document.createElement('option');
                    opt.value = s.id;
                    opt.textContent = `[${c.name}] ${s.name}`;
                    subcatSelect.appendChild(opt);
                });
            });
        } catch (e) { console.error('Error loading subcategories', e); }
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
                    <td>${escapeHtml(e.purchase_folio || '-')}</td>
                    <td>${escapeHtml(e.purchase_date || '')}</td>
                    <td>${escapeHtml(e.quantity_remaining)} / ${escapeHtml(e.quantity_original)}</td>
                    <td>$${parseFloat(e.unit_cost || 0).toFixed(2)}</td>
                    <td>${escapeHtml(e.supplier || '-')}</td>
                    <td>${e.is_exhausted
                        ? '<span class="badge bg-secondary">Agotado</span>'
                        : '<span class="badge bg-success">Disponible</span>'}</td>
                </tr>`).join('');

            document.getElementById('stockDetailBody').innerHTML = entries.length
                ? `<h6 class="mb-3"><i class="fas fa-cube me-2"></i>${escapeHtml(name)} — Lotes</h6>
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
            const body = await res.json();
            const p = body.product || body;
            document.getElementById('prodName').value = p.name || '';
            document.getElementById('prodUnit').value = p.unit_of_measure || '';
            document.getElementById('prodLeadTime').value = p.restock_lead_time_days || p.lead_time_days || 7;
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
            restock_lead_time_days: parseInt(document.getElementById('prodLeadTime').value) || 7,
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
            refreshResults();
        } catch (err) {
            HelpdeskUtils.showToast(err.message, 'danger');
        }
    }

    function init() {
        editingId = null;

        // Limpiar opciones del select de subcategorías (evita duplicados al revisitar).
        const subcatSelect = document.getElementById('prodSubcategory');
        if (subcatSelect) {
            while (subcatSelect.options.length > 1) subcatSelect.remove(1);
        }

        _onProductModalHidden = function () {
            editingId = null;
            document.getElementById('productModalTitle').innerHTML =
                '<i class="fas fa-cube me-2"></i>Nuevo Producto';
            document.getElementById('prodName').value = '';
            document.getElementById('prodUnit').value = '';
            document.getElementById('prodLeadTime').value = 7;
            document.getElementById('prodSubcategory').value = '';
            document.getElementById('prodDept').value = 'comp_center';
            document.getElementById('prodDesc').value = '';
        };
        const prodModal = document.getElementById('productModal');
        if (prodModal) prodModal.addEventListener('hidden.bs.modal', _onProductModalHidden);

        // Botones de acción (server-rendered en cada fila) → delegación en el
        // contenedor de resultados (sobrevive a los swaps HTMX del fragmento).
        const results = document.getElementById('hd-products-results');
        _resultsDelegate = function (ev) {
            const btn = ev.target.closest('[data-action]');
            if (!btn) return;
            const id = parseInt(btn.dataset.productId, 10);
            if (!id) return;
            if (btn.dataset.action === 'stock') showStock(id, btn.dataset.productName || '');
            else if (btn.dataset.action === 'edit') edit(id);
        };
        if (results) results.addEventListener('click', _resultsDelegate);

        // Botón Limpiar del filter_bar → reset de selects/búsqueda + recarga.
        const clearBtn = document.getElementById('btnClearFilters');
        if (clearBtn) {
            _clearHandler = function () {
                const form = document.getElementById('hd-filter-form');
                if (form) form.querySelectorAll('select').forEach((s) => { s.value = ''; });
                const search = document.getElementById('searchInput');
                if (search) search.value = '';
                refreshResults();
            };
            clearBtn.addEventListener('click', _clearHandler);
        }

        loadSubcategories();
    }

    function destroy() {
        const prodModal = document.getElementById('productModal');
        if (prodModal && _onProductModalHidden) {
            prodModal.removeEventListener('hidden.bs.modal', _onProductModalHidden);
        }
        const results = document.getElementById('hd-products-results');
        if (results && _resultsDelegate) results.removeEventListener('click', _resultsDelegate);

        const clearBtn = document.getElementById('btnClearFilters');
        if (clearBtn && _clearHandler) clearBtn.removeEventListener('click', _clearHandler);

        _onProductModalHidden = null;
        _resultsDelegate = null;
        _clearHandler = null;
        editingId = null;
    }

    window.WarehouseProducts = { showStock, edit, save };
    window.HelpdeskPage.page('warehouse_products', { init: init, destroy: destroy });

    return { showStock, edit, save };
})();
