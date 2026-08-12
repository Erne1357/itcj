// itcj2/apps/helpdesk/static/js/warehouse/entries.js
//
// Isla de cliente de la vista de ENTRADAS de stock del almacén. La lista, los
// filtros y la paginación se renderizan SERVER-SIDE (HTMX partial
// #hd-entries-results); aquí solo quedan los bits de cliente: el modal Nueva
// Entrada (BS5), el modal Anular, la delegación de los botones de anular y las
// barras de progreso data-driven. Tras una mutación se dispara `refresh` sobre
// el form de filtros → HTMX recarga el fragmento.

const WarehouseEntries = (function () {
    'use strict';

    const API = '/api/warehouse/v2';
    let _resultsDelegate = null;
    let _clearHandler = null;
    let _barsHandler = null;

    function refreshResults() {
        const form = document.getElementById('hd-filter-form');
        if (form && window.htmx) window.htmx.trigger(form, 'refresh');
    }

    // Aplica el ancho (data-driven) a las barras de progreso de las filas. Se
    // re-aplica tras cada swap HTMX porque el fragmento se re-renderiza.
    function applyBars() {
        document.querySelectorAll('#hd-entries-results [data-hd-width]').forEach((bar) => {
            const w = parseInt(bar.getAttribute('data-hd-width'), 10) || 0;
            bar.style.width = Math.max(0, Math.min(100, w)) + '%';
        });
    }

    // Puebla SOLO el select de producto del modal (el filtro ya es server-side).
    async function loadProductsForModal() {
        const sel = document.getElementById('entryProduct');
        if (!sel) return;
        try {
            const res = await fetch(`${API}/products?per_page=200`);
            const d = await res.json();
            sel.innerHTML = '<option value="">Selecciona un producto...</option>';
            (d.products || []).forEach(p => {
                const opt = document.createElement('option');
                opt.value = p.id;
                opt.textContent = `${p.code} — ${p.name}`;
                sel.appendChild(opt);
            });
        } catch (e) { console.error(e); }
    }

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
            refreshResults();
        } catch (err) { HelpdeskUtils.showToast(err.message, 'danger'); }
    }

    function voidEntry(id) {
        document.getElementById('voidEntryId').value = id;
        document.getElementById('voidReason').value = '';
        bootstrap.Modal.getOrCreateInstance(document.getElementById('voidModal')).show();
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
            refreshResults();
        } catch (err) { HelpdeskUtils.showToast(err.message, 'danger'); }
    }

    function init() {
        const entryDate = document.getElementById('entryDate');
        if (entryDate) entryDate.value = new Date().toISOString().split('T')[0];

        // Botones Anular (server-rendered) → delegación en el contenedor.
        const results = document.getElementById('hd-entries-results');
        _resultsDelegate = function (ev) {
            const btn = ev.target.closest('[data-action="void"]');
            if (!btn) return;
            const id = parseInt(btn.dataset.entryId, 10);
            if (id) voidEntry(id);
        };
        if (results) results.addEventListener('click', _resultsDelegate);

        // Re-aplicar barras tras cada settle HTMX (filtro/paginación).
        _barsHandler = function () { applyBars(); };
        document.body.addEventListener('htmx:afterSettle', _barsHandler);
        applyBars();

        // Botón Limpiar del filter_bar.
        const clearBtn = document.getElementById('btnClearFilters');
        if (clearBtn) {
            _clearHandler = function () {
                const form = document.getElementById('hd-filter-form');
                if (form) form.querySelectorAll('select').forEach((s) => { s.value = ''; });
                refreshResults();
            };
            clearBtn.addEventListener('click', _clearHandler);
        }

        loadProductsForModal();
    }

    function destroy() {
        const results = document.getElementById('hd-entries-results');
        if (results && _resultsDelegate) results.removeEventListener('click', _resultsDelegate);
        if (_barsHandler) document.body.removeEventListener('htmx:afterSettle', _barsHandler);
        const clearBtn = document.getElementById('btnClearFilters');
        if (clearBtn && _clearHandler) clearBtn.removeEventListener('click', _clearHandler);
        _resultsDelegate = null;
        _clearHandler = null;
        _barsHandler = null;
    }

    window.WarehouseEntries = { save, voidEntry, confirmVoid };
    window.HelpdeskPage.page('warehouse_entries', { init: init, destroy: destroy });

    return { save, voidEntry, confirmVoid };
})();
