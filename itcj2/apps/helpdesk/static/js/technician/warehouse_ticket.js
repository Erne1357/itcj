// itcj2/apps/helpdesk/static/js/technician/warehouse_ticket.js
// TicketWarehouse module — search, select and consume warehouse materials when resolving a ticket

const TicketWarehouse = (function () {
    'use strict';
    const API_W = '/api/warehouse/v2';
    let _materials = [];
    let _debounceTimer = null;

    function searchProducts(query) {
        clearTimeout(_debounceTimer);
        const sugg = document.getElementById('warehouseProductSuggestions');
        if (!query || query.length < 2) { sugg.style.display = 'none'; return; }
        _debounceTimer = setTimeout(async () => {
            try {
                const res = await fetch(`${API_W}/products/available?search=${encodeURIComponent(query)}&per_page=10`);
                const d = await res.json();
                const products = d.products || [];
                if (!products.length) { sugg.style.display = 'none'; return; }
                sugg.innerHTML = products.map(p =>
                    `<a href="#" class="list-group-item list-group-item-action py-2"
                       onclick="TicketWarehouse.selectProduct(${p.id}, '${(p.code||'').replace(/'/g,"\\'")}', '${p.name.replace(/'/g,"\\'")}', '${(p.unit_of_measure||'').replace(/'/g,"\\'")}', ${p.total_stock||0}); return false;">
                        <strong>${p.code || ''}</strong> — ${p.name}
                        <span class="badge bg-success float-end">${p.total_stock} ${p.unit_of_measure}</span>
                    </a>`
                ).join('');
                sugg.style.display = 'block';
            } catch (e) { console.error(e); }
        }, 300);
    }

    function selectProduct(id, code, name, unit, stock) {
        document.getElementById('warehouseProductSearch').value = '';
        document.getElementById('warehouseProductSuggestions').style.display = 'none';
        if (_materials.find(m => m.product_id === id)) return;
        _materials.push({ product_id: id, code, product_name: name, unit_of_measure: unit, quantity: 1, available: stock });
        renderMaterials();
    }

    function renderMaterials() {
        const list = document.getElementById('warehouseMaterialsList');
        const noMsg = document.getElementById('noMaterialsMsg');
        if (!_materials.length) {
            if (noMsg) noMsg.style.display = '';
            list.innerHTML = '<div class="text-center text-muted py-2 small" id="noMaterialsMsg"><i class="fas fa-plus-circle me-1"></i>Sin materiales agregados</div>';
            return;
        }
        if (noMsg) noMsg.style.display = 'none';
        list.innerHTML = _materials.map((m, i) => `
            <div class="d-flex align-items-center gap-2 mb-2 p-2 border rounded">
                <div class="flex-grow-1">
                    <strong>${m.code || ''}</strong> ${m.product_name}
                    <small class="text-muted d-block">Disponible: ${m.available} ${m.unit_of_measure}</small>
                </div>
                <input type="number" class="form-control form-control-sm" style="width:80px;"
                    value="${m.quantity}" min="0.01" step="0.01"
                    onchange="TicketWarehouse.updateQty(${i}, this.value)">
                <span class="text-muted small">${m.unit_of_measure}</span>
                <button class="btn btn-sm btn-outline-danger py-0" onclick="TicketWarehouse.removeMaterial(${m.product_id})">
                    <i class="fas fa-times"></i>
                </button>
            </div>`).join('');
    }

    function updateQty(index, value) {
        if (_materials[index]) _materials[index].quantity = parseFloat(value) || 1;
    }

    function removeMaterial(productId) {
        _materials = _materials.filter(m => m.product_id !== productId);
        renderMaterials();
    }

    async function consumeAll(ticketId) {
        if (!_materials.length) return;
        for (const m of _materials) {
            try {
                const res = await fetch(`${API_W}/consume`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        product_id: m.product_id,
                        quantity: m.quantity,
                        source_app: 'helpdesk',
                        source_ticket_id: ticketId,
                        notes: 'Consumo al resolver ticket',
                    }),
                });
                if (!res.ok) {
                    const err = await res.json();
                    const msg = err.detail?.message || err.detail || 'Error';
                    HelpdeskUtils.showToast(`Advertencia almacén: ${m.product_name} - ${msg}`, 'warning');
                }
            } catch (e) { console.error('Error consumiendo material:', e); }
        }
    }

    function getMaterials() { return [..._materials]; }
    function reset() { _materials = []; renderMaterials(); }

    return { searchProducts, selectProduct, updateQty, removeMaterial, consumeAll, getMaterials, reset };
})();
