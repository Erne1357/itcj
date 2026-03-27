'use strict';
(function () {

    const API_BASE = '/api/help-desk/v2/inventory';

    const el = {
        reasonInput:   document.getElementById('reason-input'),
        reasonChars:   document.getElementById('reason-chars'),
        itemSearch:    document.getElementById('item-search-input'),
        searchResults: document.getElementById('items-search-results'),
        selectedList:  document.getElementById('selected-items-list'),
        itemsCount:    document.getElementById('items-count'),
        summaryCount:  document.getElementById('summary-items-count'),
        docInput:      document.getElementById('document-input'),
        btnDraft:      document.getElementById('btn-save-draft'),
        btnSubmit:     document.getElementById('btn-save-submit'),
    };

    // Selected items: Map<item_id, { item, notes }>
    const selectedItems = new Map();
    let searchTimer = null;

    // ── Reason counter ────────────────────────────────────────────────────────
    el.reasonInput.addEventListener('input', () => {
        const len = el.reasonInput.value.length;
        el.reasonChars.textContent = len;
        updateButtons();
    });

    // ── Item search ───────────────────────────────────────────────────────────
    el.itemSearch.addEventListener('input', () => {
        clearTimeout(searchTimer);
        const q = el.itemSearch.value.trim();
        if (!q) { hideResults(); return; }
        searchTimer = setTimeout(() => searchItems(q), 300);
    });

    el.itemSearch.addEventListener('keydown', e => {
        if (e.key === 'Escape') hideResults();
    });

    document.addEventListener('click', e => {
        if (!el.itemSearch.contains(e.target) && !el.searchResults.contains(e.target)) {
            hideResults();
        }
    });

    async function searchItems(q) {
        try {
            const res = await fetch(`${API_BASE}/items?search=${encodeURIComponent(q)}&per_page=10`, {
                headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` }
            });
            if (!res.ok) return;
            const json = await res.json();
            const items = json.data || [];
            renderResults(items);
        } catch (_) {
            hideResults();
        }
    }

    function renderResults(items) {
        if (!items.length) {
            el.searchResults.innerHTML = `<div class="search-result-item text-muted small">Sin resultados</div>`;
            el.searchResults.style.display = 'block';
            return;
        }
        el.searchResults.innerHTML = items.map(item => {
            if (selectedItems.has(item.id)) return '';
            const serial = item.itcj_serial || item.supplier_serial || '—';
            return `<div class="search-result-item" data-id="${item.id}" data-json='${JSON.stringify({
                id: item.id,
                inventory_number: item.inventory_number,
                brand: item.brand,
                model: item.model,
                supplier_serial: item.supplier_serial,
                itcj_serial: item.itcj_serial,
                department: item.department ? item.department.name : null,
            }).replace(/'/g, '&#39;')}'>
                <span class="font-weight-bold">${item.inventory_number}</span>
                <span class="text-muted small ml-1">${item.brand || ''} ${item.model || ''}</span>
                <span class="float-right text-muted small">${serial}</span>
            </div>`;
        }).join('') || `<div class="search-result-item text-muted small">Todos los resultados ya están seleccionados</div>`;
        el.searchResults.style.display = 'block';

        el.searchResults.querySelectorAll('.search-result-item[data-id]').forEach(row => {
            row.addEventListener('click', () => {
                const item = JSON.parse(row.dataset.json);
                addItem(item);
                el.itemSearch.value = '';
                hideResults();
            });
        });
    }

    function hideResults() {
        el.searchResults.style.display = 'none';
        el.searchResults.innerHTML = '';
    }

    // ── Selected items list ───────────────────────────────────────────────────
    function addItem(item) {
        if (selectedItems.has(item.id)) return;
        selectedItems.set(item.id, { item, notes: '' });
        renderSelectedList();
        updateButtons();
    }

    function removeItem(id) {
        selectedItems.delete(id);
        renderSelectedList();
        updateButtons();
    }

    function renderSelectedList() {
        if (!selectedItems.size) {
            el.selectedList.innerHTML = '';
            el.itemsCount.textContent = '0';
            el.summaryCount.textContent = '0';
            return;
        }
        el.itemsCount.textContent = selectedItems.size;
        el.summaryCount.textContent = selectedItems.size;

        el.selectedList.innerHTML = Array.from(selectedItems.values()).map(({ item, notes }) => {
            const serial = item.itcj_serial || item.supplier_serial || '—';
            const dept   = item.department || '—';
            return `<div class="item-row" data-id="${item.id}">
                <div class="d-flex justify-content-between align-items-start">
                    <div>
                        <span class="font-weight-bold">${item.inventory_number}</span>
                        <span class="text-muted small ml-2">${item.brand || ''} ${item.model || ''}</span>
                        <br>
                        <small class="text-muted">Serial: ${serial} &bull; Depto: ${dept}</small>
                    </div>
                    <span class="remove-btn ml-2" data-remove="${item.id}" title="Quitar">
                        <i class="fas fa-times-circle"></i>
                    </span>
                </div>
                <div class="mt-2">
                    <input type="text" class="form-control form-control-sm item-notes"
                           data-item-id="${item.id}"
                           placeholder="Notas opcionales para este equipo..."
                           value="${notes}">
                </div>
            </div>`;
        }).join('');

        el.selectedList.querySelectorAll('[data-remove]').forEach(btn => {
            btn.addEventListener('click', () => removeItem(parseInt(btn.dataset.remove)));
        });
        el.selectedList.querySelectorAll('.item-notes').forEach(input => {
            input.addEventListener('input', () => {
                const id = parseInt(input.dataset.itemId);
                const entry = selectedItems.get(id);
                if (entry) entry.notes = input.value;
            });
        });
    }

    // ── Buttons state ─────────────────────────────────────────────────────────
    function updateButtons() {
        const hasReason = el.reasonInput.value.trim().length >= 5;
        const hasItems  = selectedItems.size > 0;
        el.btnDraft.disabled  = !(hasReason && hasItems);
        el.btnSubmit.disabled = !(hasReason && hasItems);
    }

    // ── Save ──────────────────────────────────────────────────────────────────
    async function save(andSubmit) {
        const reason = el.reasonInput.value.trim();
        if (!reason || selectedItems.size === 0) return;

        el.btnDraft.disabled  = true;
        el.btnSubmit.disabled = true;

        try {
            // Build notes map: { item_id: notes }
            const notesMap = {};
            Array.from(selectedItems.values()).forEach(({ item, notes }) => {
                if (notes) notesMap[item.id] = notes;
            });

            // Single POST: create request with items included
            const createRes = await fetch(`${API_BASE}/retirement-requests`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${localStorage.getItem('access_token')}` },
                body: JSON.stringify({
                    reason,
                    item_ids: Array.from(selectedItems.keys()),
                    notes_map: notesMap,
                }),
            });
            if (!createRes.ok) {
                const err = await createRes.json();
                throw new Error(err.detail || 'Error al crear la solicitud');
            }
            const created = await createRes.json();
            const reqId = created.data.id;

            // Attach document if provided
            const docFile = el.docInput.files[0];
            if (docFile) {
                const fd = new FormData();
                fd.append('file', docFile);
                await fetch(`${API_BASE}/retirement-requests/${reqId}/attach`, {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` },
                    body: fd,
                });
            }

            // Submit if requested
            if (andSubmit) {
                const submitRes = await fetch(`${API_BASE}/retirement-requests/${reqId}/submit`, {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` },
                });
                if (!submitRes.ok) {
                    const err = await submitRes.json();
                    throw new Error(err.detail || 'Error al enviar la solicitud');
                }
            }

            window.location.href = `/help-desk/inventory/retirement-requests/${reqId}`;

        } catch (err) {
            showToast('Error: ' + err.message, 'error');
            el.btnDraft.disabled  = false;
            el.btnSubmit.disabled = false;
            updateButtons();
        }
    }

    // ── Pre-load items from URL query params ──────────────────────────────────
    async function preloadItemsFromUrl() {
        const params = new URLSearchParams(window.location.search);

        // Single item: ?item_id=X
        const singleId = params.get('item_id');
        // Multiple items: ?item_ids=1,2,3
        const multiIds = params.get('item_ids');

        const ids = [];
        if (singleId) ids.push(singleId);
        if (multiIds) multiIds.split(',').forEach(id => { if (id.trim()) ids.push(id.trim()); });

        if (!ids.length) return;

        await Promise.all(ids.map(async (itemId) => {
            try {
                const res = await fetch(`${API_BASE}/items/${itemId}`, {
                    headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` }
                });
                if (!res.ok) return;
                const json = await res.json();
                const item = json.data;
                if (!item) return;
                addItem({
                    id: item.id,
                    inventory_number: item.inventory_number,
                    brand: item.brand,
                    model: item.model,
                    supplier_serial: item.supplier_serial,
                    itcj_serial: item.itcj_serial,
                    department: item.department ? item.department.name : null,
                });
            } catch (_) { /* ignore */ }
        }));
    }

    // ── Init ──────────────────────────────────────────────────────────────────
    function init() {
        el.btnDraft.addEventListener('click',  () => save(false));
        el.btnSubmit.addEventListener('click', () => save(true));
        updateButtons();
        preloadItemsFromUrl();
    }

    document.addEventListener('DOMContentLoaded', init);

})();
