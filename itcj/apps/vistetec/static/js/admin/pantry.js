(function () {
    'use strict';

    const API_BASE = '/api/vistetec/v1/pantry';
    let currentPage = 1;
    let currentCategory = '';
    let currentSearch = '';

    // ==================== INIT ====================

    document.addEventListener('DOMContentLoaded', () => {
        loadStock();
        loadItems();
        loadCategories();
        setupEventListeners();
    });

    function setupEventListeners() {
        document.getElementById('filterCategory').addEventListener('change', () => {
            currentCategory = document.getElementById('filterCategory').value;
            currentPage = 1;
            loadItems();
        });

        document.getElementById('searchInput').addEventListener('input', debounce(() => {
            currentSearch = document.getElementById('searchInput').value.trim();
            currentPage = 1;
            loadItems();
        }, 400));

        document.getElementById('btnNewItem').addEventListener('click', openNewItemModal);
        document.getElementById('btnSaveItem').addEventListener('click', saveItem);
        document.getElementById('btnSaveStockIn').addEventListener('click', saveStockIn);
        document.getElementById('btnSaveStockOut').addEventListener('click', saveStockOut);
    }

    // ==================== STOCK SUMMARY ====================

    async function loadStock() {
        try {
            const res = await fetch(`${API_BASE}/stock`);
            if (!res.ok) return;
            const data = await res.json();

            document.getElementById('statTotalItems').textContent = data.total_items;
            document.getElementById('statTotalStock').textContent = data.total_stock;
            document.getElementById('statLowStock').textContent = data.low_stock_count;
        } catch (err) {
            console.error('Error cargando stock:', err);
        }
    }

    // ==================== ITEMS ====================

    async function loadItems() {
        const container = document.getElementById('itemsTableBody');
        const loading = document.getElementById('loadingState');
        const empty = document.getElementById('emptyState');

        loading.classList.remove('d-none');
        empty.classList.add('d-none');
        container.innerHTML = '';

        try {
            const params = new URLSearchParams({
                page: currentPage,
                per_page: 15,
                is_active: 'true',
            });
            if (currentCategory) params.set('category', currentCategory);
            if (currentSearch) params.set('search', currentSearch);

            const res = await fetch(`${API_BASE}/items?${params}`);
            if (!res.ok) throw new Error('Error cargando items');
            const data = await res.json();

            loading.classList.add('d-none');

            if (data.items.length === 0) {
                empty.classList.remove('d-none');
                document.getElementById('paginationNav').classList.add('d-none');
                return;
            }

            data.items.forEach(item => {
                container.insertAdjacentHTML('beforeend', renderItemRow(item));
            });

            renderPagination(data);
        } catch (err) {
            loading.classList.add('d-none');
            VisteTecUtils.showToast('Error cargando artículos', 'danger');
        }
    }

    function renderItemRow(item) {
        const stockClass = item.current_stock <= 5 ? 'stock-low' : 'stock-ok';
        const categoryColors = {
            enlatados: 'bg-warning-subtle text-warning',
            granos: 'bg-success-subtle text-success',
            higiene: 'bg-info-subtle text-info',
            mascotas: 'bg-primary-subtle text-primary',
        };
        const catClass = categoryColors[item.category] || 'bg-secondary-subtle text-secondary';

        return `
            <tr>
                <td class="fw-medium">${escapeHtml(item.name)}</td>
                <td>
                    ${item.category
                        ? `<span class="badge category-badge ${catClass}">${escapeHtml(item.category)}</span>`
                        : '<span class="text-muted">-</span>'
                    }
                </td>
                <td>${escapeHtml(item.unit || 'pzas')}</td>
                <td class="${stockClass} stock-badge fw-bold">${item.current_stock}</td>
                <td>
                    <div class="d-flex gap-1">
                        <button class="btn btn-sm btn-outline-success btn-action" onclick="window._pantryStockIn(${item.id}, '${escapeHtml(item.name)}')" title="Entrada">
                            <i class="bi bi-plus-circle"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-warning btn-action" onclick="window._pantryStockOut(${item.id}, '${escapeHtml(item.name)}', ${item.current_stock})" title="Salida">
                            <i class="bi bi-dash-circle"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-secondary btn-action" onclick="window._pantryEditItem(${item.id})" title="Editar">
                            <i class="bi bi-pencil"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-danger btn-action" onclick="window._pantryDeleteItem(${item.id}, '${escapeHtml(item.name)}')" title="Desactivar">
                            <i class="bi bi-trash"></i>
                        </button>
                    </div>
                </td>
            </tr>`;
    }

    function renderPagination(data) {
        const nav = document.getElementById('paginationNav');
        const container = document.getElementById('pagination');

        if (data.pages <= 1) {
            nav.classList.add('d-none');
            return;
        }

        nav.classList.remove('d-none');
        let html = '';

        if (data.has_prev) {
            html += `<li class="page-item"><a class="page-link" href="#" onclick="window._pantryGoPage(${data.page - 1}); return false;">&laquo;</a></li>`;
        }
        for (let i = 1; i <= data.pages; i++) {
            html += `<li class="page-item ${i === data.page ? 'active' : ''}">
                <a class="page-link" href="#" onclick="window._pantryGoPage(${i}); return false;">${i}</a>
            </li>`;
        }
        if (data.has_next) {
            html += `<li class="page-item"><a class="page-link" href="#" onclick="window._pantryGoPage(${data.page + 1}); return false;">&raquo;</a></li>`;
        }

        container.innerHTML = html;
    }

    async function loadCategories() {
        try {
            const res = await fetch(`${API_BASE}/categories`);
            if (!res.ok) return;
            const categories = await res.json();

            const select = document.getElementById('filterCategory');
            categories.forEach(cat => {
                const opt = document.createElement('option');
                opt.value = cat;
                opt.textContent = cat.charAt(0).toUpperCase() + cat.slice(1);
                select.appendChild(opt);
            });
        } catch (err) {
            console.error('Error cargando categorías:', err);
        }
    }

    // ==================== CRUD MODALS ====================

    function openNewItemModal() {
        document.getElementById('itemModalTitle').textContent = 'Nuevo artículo';
        document.getElementById('itemForm').reset();
        document.getElementById('itemId').value = '';
        const modal = new bootstrap.Modal(document.getElementById('itemModal'));
        modal.show();
    }

    async function saveItem() {
        const itemId = document.getElementById('itemId').value;
        const name = document.getElementById('itemName').value.trim();
        const category = document.getElementById('itemCategory').value;
        const unit = document.getElementById('itemUnit').value;

        if (!name) {
            VisteTecUtils.showToast('El nombre es requerido', 'warning');
            return;
        }

        const data = { name, category: category || null, unit: unit || null };
        const url = itemId ? `${API_BASE}/items/${itemId}` : `${API_BASE}/items`;
        const method = itemId ? 'PUT' : 'POST';

        try {
            const res = await fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            });
            const result = await res.json();

            if (!res.ok) {
                VisteTecUtils.showToast(result.error || 'Error', 'danger');
                return;
            }

            bootstrap.Modal.getInstance(document.getElementById('itemModal')).hide();
            VisteTecUtils.showToast(result.message, 'success');
            loadItems();
            loadStock();
            loadCategories();
        } catch (err) {
            VisteTecUtils.showToast('Error de conexión', 'danger');
        }
    }

    // ==================== STOCK IN/OUT ====================

    function openStockInModal(itemId, itemName) {
        document.getElementById('stockInItemId').value = itemId;
        document.getElementById('stockInItemName').textContent = itemName;
        document.getElementById('stockInQuantity').value = 1;
        const modal = new bootstrap.Modal(document.getElementById('stockInModal'));
        modal.show();
    }

    async function saveStockIn() {
        const itemId = parseInt(document.getElementById('stockInItemId').value);
        const quantity = parseInt(document.getElementById('stockInQuantity').value);

        if (!quantity || quantity <= 0) {
            VisteTecUtils.showToast('La cantidad debe ser mayor a 0', 'warning');
            return;
        }

        try {
            const res = await fetch(`${API_BASE}/stock/in`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ item_id: itemId, quantity }),
            });
            const result = await res.json();

            if (!res.ok) {
                VisteTecUtils.showToast(result.error || 'Error', 'danger');
                return;
            }

            bootstrap.Modal.getInstance(document.getElementById('stockInModal')).hide();
            VisteTecUtils.showToast('Entrada registrada', 'success');
            loadItems();
            loadStock();
        } catch (err) {
            VisteTecUtils.showToast('Error de conexión', 'danger');
        }
    }

    function openStockOutModal(itemId, itemName, currentStock) {
        document.getElementById('stockOutItemId').value = itemId;
        document.getElementById('stockOutItemName').textContent = itemName;
        document.getElementById('stockOutMax').textContent = currentStock;
        document.getElementById('stockOutQuantity').value = 1;
        document.getElementById('stockOutQuantity').max = currentStock;
        const modal = new bootstrap.Modal(document.getElementById('stockOutModal'));
        modal.show();
    }

    async function saveStockOut() {
        const itemId = parseInt(document.getElementById('stockOutItemId').value);
        const quantity = parseInt(document.getElementById('stockOutQuantity').value);

        if (!quantity || quantity <= 0) {
            VisteTecUtils.showToast('La cantidad debe ser mayor a 0', 'warning');
            return;
        }

        try {
            const res = await fetch(`${API_BASE}/stock/out`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ item_id: itemId, quantity }),
            });
            const result = await res.json();

            if (!res.ok) {
                VisteTecUtils.showToast(result.error || 'Error', 'danger');
                return;
            }

            bootstrap.Modal.getInstance(document.getElementById('stockOutModal')).hide();
            VisteTecUtils.showToast('Salida registrada', 'success');
            loadItems();
            loadStock();
        } catch (err) {
            VisteTecUtils.showToast('Error de conexión', 'danger');
        }
    }

    // ==================== EDIT / DELETE ====================

    async function editItem(itemId) {
        try {
            const res = await fetch(`${API_BASE}/items/${itemId}`);
            if (!res.ok) return;
            const item = await res.json();

            document.getElementById('itemModalTitle').textContent = 'Editar artículo';
            document.getElementById('itemId').value = item.id;
            document.getElementById('itemName').value = item.name;
            document.getElementById('itemCategory').value = item.category || '';
            document.getElementById('itemUnit').value = item.unit || '';

            const modal = new bootstrap.Modal(document.getElementById('itemModal'));
            modal.show();
        } catch (err) {
            VisteTecUtils.showToast('Error cargando artículo', 'danger');
        }
    }

    async function deleteItem(itemId, itemName) {
        const confirmed = await VisteTecUtils.confirmModal(
            '¿Desactivar artículo?',
            `Se desactivará "${itemName}" del inventario. Los datos históricos se mantendrán.`
        );

        if (!confirmed) return;

        try {
            const res = await fetch(`${API_BASE}/items/${itemId}`, { method: 'DELETE' });
            const result = await res.json();

            if (!res.ok) {
                VisteTecUtils.showToast(result.error || 'Error', 'danger');
                return;
            }

            VisteTecUtils.showToast('Artículo desactivado', 'success');
            loadItems();
            loadStock();
        } catch (err) {
            VisteTecUtils.showToast('Error de conexión', 'danger');
        }
    }

    // ==================== UTILS ====================

    function debounce(fn, ms) {
        let timer;
        return function (...args) {
            clearTimeout(timer);
            timer = setTimeout(() => fn.apply(this, args), ms);
        };
    }

    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // ==================== GLOBAL HANDLERS ====================

    window._pantryGoPage = function (page) {
        currentPage = page;
        loadItems();
    };

    window._pantryStockIn = openStockInModal;
    window._pantryStockOut = openStockOutModal;
    window._pantryEditItem = editItem;
    window._pantryDeleteItem = deleteItem;
})();
