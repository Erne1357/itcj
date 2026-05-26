/**
 * categories_tab.js
 * Tab "Categorías y Campos" del panel de Configuración.
 *
 * Responsabilidades:
 *  - Lista de categorías por área (DESARROLLO / SOPORTE) con drag-drop de reordenamiento.
 *  - CRUD: crear, editar (nombre/descripción), toggle activa, soft-delete.
 *  - Abrir el field_template_builder para editar campos personalizados.
 *  - Toggle "mostrar inactivas".
 *  - Lazy init: carga datos solo la primera vez que el tab es visible.
 */
(function () {
    'use strict';

    // === ESTADO ===
    let initialized = false;
    let statsMap = {};          // id → {tickets_count, active_tickets_count}
    let categoriesData = {      // área → array de categorías
        DESARROLLO: [],
        SOPORTE: [],
    };
    let showInactive = false;
    let sortableInstances = {}; // área → instancia Sortable

    // === CONSTANTES ===
    const AREAS = ['DESARROLLO', 'SOPORTE'];
    const AREA_LABELS = { DESARROLLO: 'Desarrollo', SOPORTE: 'Soporte' };
    const AREA_ICONS = { DESARROLLO: 'fas fa-code', SOPORTE: 'fas fa-wrench' };
    const AREA_COLORS = { DESARROLLO: 'primary', SOPORTE: 'info' };
    const API = window.HelpdeskUtils.api;

    // === HELPERS ===
    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function extractError(data, fallback) {
        if (typeof data === 'string') return data || fallback;
        if (!data || typeof data !== 'object') return fallback;
        const v = data.error || data.message || data.detail;
        if (typeof v === 'string') return v || fallback;
        return fallback;
    }

    async function apiErrorMsg(res, fallback) {
        try {
            const d = await res.json();
            return extractError(d, fallback);
        } catch (_) {
            return `${fallback} (HTTP ${res.status})`;
        }
    }

    // === INIT ===
    document.addEventListener('config:tab-shown', function (e) {
        if (e.detail && e.detail.tab === '#categorias') {
            if (!initialized) {
                initialized = true;
                initCategoriesTab();
            }
        }
    });

    // También carga si el tab ya está activo al cargar la página
    document.addEventListener('DOMContentLoaded', function () {
        const hash = window.location.hash || '#categorias';
        if (hash === '#categorias') {
            if (!initialized) {
                initialized = true;
                initCategoriesTab();
            }
        }
    });

    function initCategoriesTab() {
        renderShell();
        bindTabControls();
        loadAll();
    }

    // === RENDER SHELL ===
    function renderShell() {
        const root = document.getElementById('categorias-root');
        if (!root) return;

        root.innerHTML = `
            <div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
                <h5 class="mb-0 fw-semibold">
                    <i class="fas fa-tags me-2 text-primary"></i>Categorías de Tickets
                </h5>
                <div class="d-flex align-items-center gap-2 flex-wrap">
                    <div class="form-check form-switch mb-0">
                        <input class="form-check-input" type="checkbox" id="toggle-inactive-cats"
                               role="switch" ${showInactive ? 'checked' : ''}>
                        <label class="form-check-label small text-muted" for="toggle-inactive-cats">
                            Mostrar inactivas
                        </label>
                    </div>
                </div>
            </div>

            <div class="row g-3" id="categories-areas-grid">
                ${AREAS.map(area => `
                    <div class="col-12 col-xl-6">
                        <div class="card border-0 shadow-sm h-100">
                            <div class="card-header bg-${AREA_COLORS[area]} bg-opacity-10 border-0 d-flex justify-content-between align-items-center">
                                <h6 class="mb-0 fw-semibold text-${AREA_COLORS[area]}">
                                    <i class="${AREA_ICONS[area]} me-2"></i>${AREA_LABELS[area]}
                                </h6>
                                <button class="btn btn-sm btn-${AREA_COLORS[area]}" id="btn-new-cat-${area}"
                                        title="Nueva categoría en ${AREA_LABELS[area]}">
                                    <i class="fas fa-plus me-1"></i><span class="d-none d-sm-inline">Nueva</span>
                                </button>
                            </div>
                            <div class="card-body p-2">
                                <div id="cat-list-${area}" class="cat-sortable-list">
                                    <div class="text-center py-4 text-muted small">
                                        <div class="spinner-border spinner-border-sm" role="status"></div>
                                        Cargando...
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                `).join('')}
            </div>
        `;
    }

    // === BIND CONTROLS ===
    function bindTabControls() {
        const root = document.getElementById('categorias-root');
        if (!root) return;

        root.addEventListener('change', function (e) {
            if (e.target.id === 'toggle-inactive-cats') {
                showInactive = e.target.checked;
                renderAllAreas();
            }
        });

        AREAS.forEach(function (area) {
            const btn = document.getElementById('btn-new-cat-' + area);
            if (btn) {
                btn.addEventListener('click', function () { openCreateModal(area); });
            }
        });
    }

    // === CARGA DE DATOS ===
    async function loadAll() {
        try {
            const [catRes, statsRes] = await Promise.all([
                API.request('/categories?include_inactive=true'),
                API.request('/categories/stats'),
            ]);

            // Mapear stats por id
            statsMap = {};
            (statsRes.categories || []).forEach(function (s) {
                statsMap[s.id] = s;
            });

            // Almacenar por área
            AREAS.forEach(function (area) {
                categoriesData[area] = catRes.grouped[area] || [];
            });

            renderAllAreas();
        } catch (err) {
            console.error('Error loading categories:', err);
            HelpdeskUtils.showToast('Error al cargar categorías: ' + (err.message || ''), 'error');
            AREAS.forEach(function (area) {
                const list = document.getElementById('cat-list-' + area);
                if (list) {
                    list.innerHTML = '<div class="text-danger small p-2">Error al cargar</div>';
                }
            });
        }
    }

    async function reloadAll() {
        AREAS.forEach(function (area) {
            const list = document.getElementById('cat-list-' + area);
            if (list) {
                list.innerHTML = `
                    <div class="text-center py-3 text-muted small">
                        <div class="spinner-border spinner-border-sm me-1" role="status"></div>
                        Actualizando...
                    </div>`;
            }
        });
        initialized = false; // permitir recarga
        initialized = true;
        await loadAll();
    }

    // === RENDER ÁREAS ===
    function renderAllAreas() {
        AREAS.forEach(renderArea);
        initSortables();
    }

    function renderArea(area) {
        const list = document.getElementById('cat-list-' + area);
        if (!list) return;

        const cats = (categoriesData[area] || []).filter(function (c) {
            return showInactive ? true : c.is_active;
        });

        if (!cats.length) {
            list.innerHTML = `
                <div class="text-center py-4 text-muted small">
                    <i class="fas fa-inbox fa-2x mb-2 opacity-50"></i><br>
                    ${showInactive ? 'Sin categorías' : 'Sin categorías activas'}
                </div>`;
            return;
        }

        list.innerHTML = cats.map(function (cat) {
            const stats = statsMap[cat.id] || {};
            const ticketCount = stats.tickets_count != null ? stats.tickets_count : '—';
            const activeCount = stats.active_tickets_count != null ? stats.active_tickets_count : '—';
            const hasTemplate = cat.field_template && cat.field_template.enabled;
            const inactiveClass = cat.is_active ? '' : 'cat-row--inactive';

            return `
                <div class="category-row ${inactiveClass}" data-id="${cat.id}" data-area="${escapeHtml(area)}">
                    <span class="drag-handle" title="Arrastrar para reordenar">
                        <i class="fas fa-grip-vertical"></i>
                    </span>
                    <div class="cat-row-info">
                        <span class="cat-row-name">${escapeHtml(cat.name)}</span>
                        <span class="badge bg-secondary bg-opacity-75 cat-row-code">${escapeHtml(cat.code)}</span>
                        ${hasTemplate
                            ? '<span class="badge bg-success bg-opacity-75 ms-1" title="Tiene campos personalizados"><i class="fas fa-list-ul"></i></span>'
                            : ''}
                        ${!cat.is_active
                            ? '<span class="badge bg-warning text-dark ms-1">Inactiva</span>'
                            : ''}
                    </div>
                    <div class="cat-row-stats text-muted small">
                        <span title="Total tickets"><i class="fas fa-ticket-alt me-1"></i>${ticketCount}</span>
                        <span class="ms-2" title="Tickets activos"><i class="fas fa-circle-notch me-1 text-warning"></i>${activeCount}</span>
                    </div>
                    <div class="cat-row-actions">
                        <div class="form-check form-switch mb-0" title="${cat.is_active ? 'Desactivar' : 'Activar'}">
                            <input class="form-check-input cat-toggle" type="checkbox"
                                   data-id="${cat.id}" data-area="${escapeHtml(area)}"
                                   ${cat.is_active ? 'checked' : ''}>
                        </div>
                        <button class="btn btn-sm btn-outline-primary cat-btn-fields" title="Editar campos personalizados"
                                data-id="${cat.id}" data-name="${escapeHtml(cat.name)}" data-area="${escapeHtml(area)}">
                            <i class="fas fa-list-ul"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-secondary cat-btn-edit" title="Editar nombre y descripción"
                                data-id="${cat.id}">
                            <i class="fas fa-pencil-alt"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-danger cat-btn-delete" title="Eliminar categoría"
                                data-id="${cat.id}" data-name="${escapeHtml(cat.name)}">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </div>`;
        }).join('');

        // Bind row actions
        bindRowActions(list, area);
    }

    function bindRowActions(list, area) {
        // Toggle activa
        list.querySelectorAll('.cat-toggle').forEach(function (chk) {
            chk.addEventListener('change', function () {
                handleToggle(parseInt(chk.dataset.id), chk.checked, chk);
            });
        });

        // Editar campos
        list.querySelectorAll('.cat-btn-fields').forEach(function (btn) {
            btn.addEventListener('click', function () {
                if (window.FieldTemplateBuilder) {
                    FieldTemplateBuilder.open(
                        parseInt(btn.dataset.id),
                        btn.dataset.name,
                        btn.dataset.area
                    );
                }
            });
        });

        // Editar básico
        list.querySelectorAll('.cat-btn-edit').forEach(function (btn) {
            btn.addEventListener('click', function () {
                const id = parseInt(btn.dataset.id);
                const cat = findCatById(id);
                if (cat) openEditModal(cat);
            });
        });

        // Eliminar
        list.querySelectorAll('.cat-btn-delete').forEach(function (btn) {
            btn.addEventListener('click', function () {
                handleDelete(parseInt(btn.dataset.id), btn.dataset.name, area);
            });
        });
    }

    function findCatById(id) {
        for (const area of AREAS) {
            const found = (categoriesData[area] || []).find(function (c) { return c.id === id; });
            if (found) return found;
        }
        return null;
    }

    // === SORTABLE ===
    function initSortables() {
        if (typeof Sortable === 'undefined') return;

        AREAS.forEach(function (area) {
            const list = document.getElementById('cat-list-' + area);
            if (!list) return;

            if (sortableInstances[area]) {
                sortableInstances[area].destroy();
            }

            sortableInstances[area] = Sortable.create(list, {
                handle: '.drag-handle',
                animation: 150,
                ghostClass: 'cat-row--ghost',
                onEnd: function () { handleReorder(area); },
            });
        });
    }

    async function handleReorder(area) {
        const list = document.getElementById('cat-list-' + area);
        if (!list) return;

        const rows = list.querySelectorAll('.category-row[data-id]');
        const order = Array.from(rows).map(function (row, idx) {
            return { id: parseInt(row.dataset.id), display_order: idx + 1 };
        });

        try {
            await API.request('/categories/reorder', {
                method: 'POST',
                body: JSON.stringify({ area: area, order: order }),
            });
            // Actualiza display_order local
            order.forEach(function (item) {
                const cat = findCatById(item.id);
                if (cat) cat.display_order = item.display_order;
            });
        } catch (err) {
            HelpdeskUtils.showToast('Error al reordenar: ' + (err.message || ''), 'error');
        }
    }

    // === ACCIONES ===
    async function handleToggle(id, isActive, checkbox) {
        const original = !isActive;
        checkbox.disabled = true;

        try {
            const res = await fetch('/api/help-desk/v2/categories/' + id + '/toggle', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ is_active: isActive }),
            });
            if (!res.ok) {
                const msg = await apiErrorMsg(res, 'Error al cambiar estado');
                HelpdeskUtils.showToast(msg, 'error');
                checkbox.checked = original;
                return;
            }
            const data = await res.json();
            const cat = findCatById(id);
            if (cat) cat.is_active = isActive;
            HelpdeskUtils.showToast(data.message || (isActive ? 'Categoría activada' : 'Categoría desactivada'), 'success');

            // Re-render el área para reflejar el cambio visual
            const area = checkbox.dataset.area || findAreaById(id);
            if (area) renderArea(area);
        } catch (err) {
            HelpdeskUtils.showToast('Error de conexión', 'error');
            checkbox.checked = original;
        } finally {
            checkbox.disabled = false;
        }
    }

    function findAreaById(id) {
        for (const area of AREAS) {
            if ((categoriesData[area] || []).some(function (c) { return c.id === id; })) {
                return area;
            }
        }
        return null;
    }

    async function handleDelete(id, name, area) {
        const stats = statsMap[id] || {};
        if ((stats.tickets_count || 0) > 0) {
            HelpdeskUtils.showToast(
                `No se puede eliminar "${escapeHtml(name)}" — tiene ${stats.tickets_count} ticket(s) asociado(s).`,
                'warning'
            );
            return;
        }

        const confirmed = await HelpdeskUtils.confirmDialog(
            'Eliminar categoría',
            `¿Eliminar la categoría <strong>${escapeHtml(name)}</strong>? Esta acción es irreversible.`,
            'Eliminar',
            'Cancelar'
        );
        if (!confirmed) return;

        try {
            const res = await fetch('/api/help-desk/v2/categories/' + id, { method: 'DELETE' });
            if (!res.ok) {
                const msg = await apiErrorMsg(res, 'Error al eliminar');
                HelpdeskUtils.showToast(msg, 'error');
                return;
            }
            HelpdeskUtils.showToast('Categoría eliminada', 'success');
            // Eliminar local y re-render
            categoriesData[area] = (categoriesData[area] || []).filter(function (c) { return c.id !== id; });
            renderArea(area);
        } catch (err) {
            HelpdeskUtils.showToast('Error de conexión', 'error');
        }
    }

    // === MODAL CREAR ===
    function openCreateModal(area) {
        const modal = document.getElementById('modal-cat-create');
        if (!modal) return;

        modal.querySelector('#cat-create-area').value = area;
        modal.querySelector('#cat-create-code').value = '';
        modal.querySelector('#cat-create-name').value = '';
        modal.querySelector('#cat-create-description').value = '';
        modal.querySelector('#cat-create-area-label').textContent = AREA_LABELS[area];
        modal.querySelector('.modal-title-area').textContent = AREA_LABELS[area];

        // Reset errores
        modal.querySelectorAll('.is-invalid').forEach(function (el) { el.classList.remove('is-invalid'); });
        modal.querySelectorAll('.invalid-feedback').forEach(function (el) { el.textContent = ''; });

        const bsModal = bootstrap.Modal.getOrCreateInstance(modal);
        bsModal.show();
    }

    // === MODAL EDITAR ===
    function openEditModal(cat) {
        const modal = document.getElementById('modal-cat-edit');
        if (!modal) return;

        modal.querySelector('#cat-edit-id').value = cat.id;
        modal.querySelector('#cat-edit-name').value = cat.name || '';
        modal.querySelector('#cat-edit-description').value = cat.description || '';
        modal.querySelector('.modal-title-cat-name').textContent = cat.name;

        modal.querySelectorAll('.is-invalid').forEach(function (el) { el.classList.remove('is-invalid'); });
        modal.querySelectorAll('.invalid-feedback').forEach(function (el) { el.textContent = ''; });

        const bsModal = bootstrap.Modal.getOrCreateInstance(modal);
        bsModal.show();
    }

    // === BIND MODALES (se ejecuta cuando el DOM está listo) ===
    document.addEventListener('DOMContentLoaded', function () {
        bindCreateModal();
        bindEditModal();
    });

    function bindCreateModal() {
        const modal = document.getElementById('modal-cat-create');
        if (!modal) return;

        // Evitar listeners duplicados
        if (modal.dataset.listenerBound) return;
        modal.dataset.listenerBound = '1';

        const btnSave = modal.querySelector('#btn-cat-create-save');
        if (!btnSave) return;

        btnSave.addEventListener('click', async function () {
            const area = modal.querySelector('#cat-create-area').value;
            const code = modal.querySelector('#cat-create-code').value.trim();
            const name = modal.querySelector('#cat-create-name').value.trim();
            const description = modal.querySelector('#cat-create-description').value.trim();

            let valid = true;

            // Validación básica
            const codeInput = modal.querySelector('#cat-create-code');
            const nameInput = modal.querySelector('#cat-create-name');

            codeInput.classList.remove('is-invalid');
            nameInput.classList.remove('is-invalid');

            if (!code) {
                codeInput.classList.add('is-invalid');
                codeInput.nextElementSibling.textContent = 'El código es requerido';
                valid = false;
            }
            if (!name) {
                nameInput.classList.add('is-invalid');
                nameInput.nextElementSibling.textContent = 'El nombre es requerido';
                valid = false;
            }
            if (!valid) return;

            btnSave.disabled = true;

            try {
                const res = await fetch('/api/help-desk/v2/categories', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ area, code, name, description: description || null }),
                });

                if (!res.ok) {
                    const msg = await apiErrorMsg(res, 'Error al crear categoría');
                    HelpdeskUtils.showToast(msg, 'error');
                    return;
                }

                const data = await res.json();
                HelpdeskUtils.showToast('Categoría creada exitosamente', 'success');
                bootstrap.Modal.getInstance(modal).hide();

                // Agrega a datos locales y re-renderiza
                categoriesData[area].push(data.category);
                statsMap[data.category.id] = { tickets_count: 0, active_tickets_count: 0 };
                renderArea(area);
            } catch (err) {
                HelpdeskUtils.showToast('Error de conexión', 'error');
            } finally {
                btnSave.disabled = false;
            }
        });
    }

    function bindEditModal() {
        const modal = document.getElementById('modal-cat-edit');
        if (!modal) return;

        if (modal.dataset.listenerBound) return;
        modal.dataset.listenerBound = '1';

        const btnSave = modal.querySelector('#btn-cat-edit-save');
        if (!btnSave) return;

        btnSave.addEventListener('click', async function () {
            const id = parseInt(modal.querySelector('#cat-edit-id').value);
            const name = modal.querySelector('#cat-edit-name').value.trim();
            const description = modal.querySelector('#cat-edit-description').value.trim();

            const nameInput = modal.querySelector('#cat-edit-name');
            nameInput.classList.remove('is-invalid');

            if (!name) {
                nameInput.classList.add('is-invalid');
                nameInput.nextElementSibling.textContent = 'El nombre es requerido';
                return;
            }

            btnSave.disabled = true;

            try {
                const res = await fetch('/api/help-desk/v2/categories/' + id, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name, description: description || null }),
                });

                if (!res.ok) {
                    const msg = await apiErrorMsg(res, 'Error al actualizar categoría');
                    HelpdeskUtils.showToast(msg, 'error');
                    return;
                }

                const data = await res.json();
                HelpdeskUtils.showToast('Categoría actualizada', 'success');
                bootstrap.Modal.getInstance(modal).hide();

                // Actualizar local
                const cat = findCatById(id);
                if (cat) {
                    cat.name = data.category.name;
                    cat.description = data.category.description;
                    const area = findAreaById(id);
                    if (area) renderArea(area);
                }
            } catch (err) {
                HelpdeskUtils.showToast('Error de conexión', 'error');
            } finally {
                btnSave.disabled = false;
            }
        });
    }

    // === Notificado desde FieldTemplateBuilder cuando guarda ===
    document.addEventListener('field-template:saved', function (e) {
        const { categoryId, fieldTemplate } = e.detail || {};
        if (!categoryId) return;
        const cat = findCatById(categoryId);
        if (cat) {
            cat.field_template = fieldTemplate;
            const area = findAreaById(categoryId);
            if (area) renderArea(area);
        }
    });

})();
