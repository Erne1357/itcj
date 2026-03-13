// itcj2/apps/helpdesk/static/js/warehouse/entries.js

const WarehouseEntries = (function () {
    'use strict';

    const API = '/api/warehouse/v2';
    let currentPage = 1;
    let totalPages = 1;

    async function loadProducts() {
        try {
            const res = await fetch(`${API}/products?per_page=200`);
            const d = await res.json();
            const opts = (d.products || []).map(p =>
                `<option value="${p.id}">${p.code} — ${p.name}</option>`).join('');
            document.getElementById('productFilter').insertAdjacentHTML('beforeend', opts);
            document.getElementById('entryProduct').innerHTML =
                '<option value="">Selecciona un producto...</option>' + opts;
        } catch (e) { console.error(e); }
    }

    async function load(page) {
        page = page || currentPage;
        currentPage = page;

        const productId = document.getElementById('productFilter').value;
        const includeVoided = document.getElementById('includeVoided').checked;

        const params = new URLSearchParams({ page, per_page: 20 });
        if (productId) params.set('product_id', productId);
        if (includeVoided) params.set('include_voided', 'true');

        document.getElementById('entriesContainer').innerHTML =
            '<div class="text-center py-5"><div class="spinner-border text-primary" role="status"></div></div>';

        try {
            const res = await fetch(`${API}/stock-entries?${params}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const d = await res.json();
            totalPages = d.pages || 1;
            renderEntries(d.entries || []);
            renderPagination(d.total || 0, d.page || 1, d.pages || 1);
        } catch (err) {
            document.getElementById('entriesContainer').innerHTML =
                '<div class="alert alert-danger m-3">Error al cargar las entradas.</div>';
        }
    }

    function renderEntries(entries) {
        if (!entries.length) {
            document.getElementById('entriesContainer').innerHTML =
                '<div class="text-center py-5 text-muted"><i class="fas fa-inbox fa-3x mb-3"></i><p>Sin entradas.</p></div>';
            return;
        }
        const rows = entries.map(e => {
            const pct = e.quantity_original > 0
                ? Math.round((e.quantity_remaining / e.quantity_original) * 100) : 0;
            let statusBadge = '<span class="badge bg-success">Disponible</span>';
            if (e.voided) statusBadge = '<span class="badge bg-secondary">Anulada</span>';
            else if (e.is_exhausted) statusBadge = '<span class="badge bg-dark">Agotada</span>';
            else if (pct < 30) statusBadge = '<span class="badge bg-warning text-dark">Bajo</span>';

            return `
                <tr class="${e.voided ? 'table-secondary text-muted' : ''}">
                    <td><code>${e.purchase_folio || '—'}</code></td>
                    <td><small>${e.purchase_date}</small></td>
                    <td>
                        <div class="d-flex align-items-center gap-2">
                            <div class="progress flex-grow-1" style="height:8px; min-width:60px;">
                                <div class="progress-bar" style="width:${pct}%"></div>
                            </div>
                            <small>${e.quantity_remaining}/${e.quantity_original}</small>
                        </div>
                    </td>
                    <td>$${parseFloat(e.unit_cost || 0).toFixed(2)}</td>
                    <td>${e.supplier || '—'}</td>
                    <td>${statusBadge}</td>
                    <td>
                        ${!e.voided && !e.is_exhausted
                            ? `<button class="btn btn-sm btn-outline-danger" onclick="WarehouseEntries.voidEntry(${e.id})">
                                <i class="fas fa-ban"></i>
                               </button>`
                            : ''}
                    </td>
                </tr>`;
        }).join('');

        document.getElementById('entriesContainer').innerHTML = `
            <div class="table-responsive">
                <table class="table table-hover mb-0">
                    <thead class="table-light">
                        <tr>
                            <th>Folio</th><th>Fecha</th><th>Restante/Original</th>
                            <th>Costo Unit.</th><th>Proveedor</th><th>Estado</th><th></th>
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
            `Página ${page} de ${pages} (${total} entradas)`;
        document.getElementById('btnPrev').disabled = page <= 1;
        document.getElementById('btnNext').disabled = page >= pages;
    }

    function prevPage() { if (currentPage > 1) load(currentPage - 1); }
    function nextPage() { if (currentPage < totalPages) load(currentPage + 1); }

    async function save() {
        const body = {
            product_id: parseInt(document.getElementById('entryProduct').value),
            quantity: parseFloat(document.getElementById('entryQty').value),
            unit_cost: parseFloat(document.getElementById('entryCost').value) || 0,
            purchase_folio: document.getElementById('entryFolio').value.trim() || null,
            supplier: document.getElementById('entrySupplier').value.trim() || null,
            purchase_date: document.getElementById('entryDate').value,
            notes: document.getElementById('entryNotes').value.trim() || null,
        };
        if (!body.product_id || !body.quantity || !body.purchase_date) {
            HelpdeskUtils.showToast('Completa los campos obligatorios.', 'warning');
            return;
        }
        try {
            const res = await fetch(`${API}/stock-entries`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            if (!res.ok) throw new Error((await res.json()).detail?.message || 'Error');
            bootstrap.Modal.getInstance(document.getElementById('entryModal')).hide();
            HelpdeskUtils.showToast('Entrada registrada exitosamente.', 'success');
            load(1);
        } catch (err) { HelpdeskUtils.showToast(err.message, 'danger'); }
    }

    function voidEntry(id) {
        document.getElementById('voidEntryId').value = id;
        document.getElementById('voidReason').value = '';
        new bootstrap.Modal(document.getElementById('voidModal')).show();
    }

    async function confirmVoid() {
        const id = document.getElementById('voidEntryId').value;
        const reason = document.getElementById('voidReason').value.trim();
        if (!reason) { HelpdeskUtils.showToast('La razón es obligatoria.', 'warning'); return; }
        try {
            const res = await fetch(`${API}/stock-entries/${id}/void`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ reason }),
            });
            if (!res.ok) throw new Error((await res.json()).detail?.message || 'Error al anular');
            bootstrap.Modal.getInstance(document.getElementById('voidModal')).hide();
            HelpdeskUtils.showToast('Entrada anulada.', 'success');
            load(currentPage);
        } catch (err) { HelpdeskUtils.showToast(err.message, 'danger'); }
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.getElementById('entryDate').value = new Date().toISOString().split('T')[0];
        loadProducts();
        load(1);
    });

    return { load, prevPage, nextPage, save, voidEntry, confirmVoid };
})();
