// itcj2/core/static/js/config/organization/departments.js
// Árbol organizacional interactivo. Módulo ConfigPage (patrón C2): IIFE + register.
// Envelope-agnóstico: branch por response.ok; lee result.data / result.error.
(function () {
    'use strict';

    const API = '/api/core/v2';

    const esc = (window.ConfigUtils && window.ConfigUtils.escapeHtml) || function (s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
    };

    function toast(msg, type) {
        if (window.ConfigUtils && window.ConfigUtils.showToast) {
            window.ConfigUtils.showToast(msg, type || 'success');
        } else {
            (type === 'danger' ? console.error : console.log)(msg);
        }
    }

    // Estado por activación de página; se recrea en cada init (A→B→A recrea nodos).
    let S = null;

    function init() {
        S = {
            tree: [],
            byId: new Map(),
            expanded: new Set(),
            editing: null,          // nodo en edición (Task 3)
            createModal: null,
            editModal: null,
            searchTimer: null,
        };
        const createEl = document.getElementById('createDepartmentModal');
        if (createEl) S.createModal = new bootstrap.Modal(createEl);
        const editEl = document.getElementById('editDepartmentModal'); // Task 3
        if (editEl) S.editModal = new bootstrap.Modal(editEl);

        const search = document.getElementById('deptTreeSearch');
        if (search) search.addEventListener('input', onSearchInput);
        const treeEl = document.getElementById('deptTree');
        if (treeEl) treeEl.addEventListener('click', onTreeClick);
        const createForm = document.getElementById('createDepartmentForm');
        if (createForm) createForm.addEventListener('submit', onCreateSubmit);
        const editForm = document.getElementById('editDepartmentForm'); // Task 3
        if (editForm) editForm.addEventListener('submit', onEditSubmit);
        const newRootBtn = document.getElementById('newRootDeptBtn');
        if (newRootBtn) newRootBtn.addEventListener('click', () => openCreateModal(null));

        loadTree();
    }

    function destroy() {
        if (S && S.searchTimer) clearTimeout(S.searchTimer);
        S = null;
        // Los listeners viven en nodos del content root: el morph los descarta.
    }

    // === CARGA =============================================================
    async function loadTree() {
        const cont = document.getElementById('deptTree');
        if (!cont) return;
        cont.innerHTML = '<div class="text-center py-5"><div class="spinner-border" role="status"></div></div>';
        try {
            const res = await fetch(`${API}/departments/tree`);
            const result = await res.json();
            if (!res.ok) throw new Error(result.error || 'Error al cargar el árbol');
            S.tree = result.data || [];
            S.byId.clear();
            (function index(nodes) {
                nodes.forEach(n => { S.byId.set(n.id, n); index(n.children || []); });
            })(S.tree);
            if (S.expanded.size === 0) S.tree.forEach(n => S.expanded.add(n.id)); // raíces abiertas
            renderTree();
        } catch (err) {
            console.error('Error loading tree:', err);
            cont.innerHTML = '<div class="alert alert-danger mb-0">Error al cargar la estructura organizacional</div>';
        }
    }

    // === RENDER ============================================================
    function renderTree() {
        const cont = document.getElementById('deptTree');
        if (!cont || !S) return;
        const q = (document.getElementById('deptTreeSearch')?.value || '').toLowerCase().trim();
        const visible = q ? computeSearchSets(q) : null;
        if (S.tree.length === 0) {
            cont.innerHTML = '<div class="text-center py-5 text-muted">No hay departamentos registrados</div>';
            return;
        }
        const html = S.tree.map(n => renderNode(n, visible)).join('');
        cont.innerHTML = html || '<div class="text-center py-4 text-muted">Sin resultados para la búsqueda</div>';
    }

    // matches + ancestros visibles; ancestros de un match se auto-expanden.
    function computeSearchSets(q) {
        const show = new Set(), open = new Set();
        function walk(node, ancestors) {
            const hit = node.name.toLowerCase().includes(q) ||
                        (node.code || '').toLowerCase().includes(q);
            if (hit) {
                show.add(node.id);
                ancestors.forEach(a => { show.add(a); open.add(a); });
            }
            (node.children || []).forEach(c => walk(c, ancestors.concat(node.id)));
        }
        S.tree.forEach(n => walk(n, []));
        return { show, open };
    }

    function renderNode(node, visible) {
        if (visible && !visible.show.has(node.id)) return '';
        const children = node.children || [];
        const isOpen = visible ? visible.open.has(node.id) : S.expanded.has(node.id);
        const chevron = children.length
            ? `<button type="button" class="btn btn-sm btn-link dept-chevron p-0"
                       data-tree-action="toggle" data-dept-id="${node.id}"
                       aria-expanded="${isOpen}" title="${isOpen ? 'Colapsar' : 'Expandir'}">
                   <i class="bi ${isOpen ? 'bi-chevron-down' : 'bi-chevron-right'}"></i>
               </button>`
            : '<span class="dept-chevron-spacer"></span>';
        const badges = [
            node.is_official ? '<span class="badge text-bg-warning dept-badge-official">Oficial</span>' : '',
            `<span class="badge text-bg-light border">Nivel ${node.depth}</span>`,
            `<span class="badge text-bg-secondary">${node.positions_count} puestos</span>`,
            children.length ? `<span class="badge text-bg-info">${children.length} sub</span>` : '',
            node.is_active ? '' : '<span class="badge text-bg-dark">Inactivo</span>',
        ].filter(Boolean).join(' ');
        const head = node.head
            ? `<small class="text-muted d-none d-lg-inline"><i class="bi bi-person-badge me-1"></i>${esc(node.head.name)}</small>`
            : '';
        return `
        <div class="dept-node" data-node-id="${node.id}">
            <div class="dept-node-row d-flex align-items-center flex-wrap gap-2">
                ${chevron}
                <i class="${esc(node.icon || 'bi-building')} text-primary"></i>
                <span class="dept-node-name fw-semibold">${esc(node.name)}</span>
                <code class="small text-muted">${esc(node.code)}</code>
                ${badges}
                ${head}
                <span class="dept-node-actions ms-auto d-flex gap-1">
                    <button type="button" class="btn btn-sm btn-outline-primary" title="Ver detalle"
                            data-tree-action="detail" data-dept-id="${node.id}"><i class="bi bi-box-arrow-in-right"></i></button>
                    <button type="button" class="btn btn-sm btn-outline-success" title="Crear sub-departamento"
                            data-tree-action="create-child" data-dept-id="${node.id}"><i class="bi bi-plus-lg"></i></button>
                    <button type="button" class="btn btn-sm btn-outline-secondary" title="Editar"
                            data-tree-action="edit" data-dept-id="${node.id}"><i class="bi bi-pencil"></i></button>
                    <button type="button" class="btn btn-sm btn-outline-danger" title="Desactivar"
                            data-tree-action="deactivate" data-dept-id="${node.id}" ${node.is_active ? '' : 'disabled'}><i class="bi bi-slash-circle"></i></button>
                </span>
            </div>
            <div class="dept-node-children ${isOpen ? '' : 'd-none'}">
                ${children.map(c => renderNode(c, visible)).join('')}
            </div>
        </div>`;
    }

    // === EVENTOS ===========================================================
    function onSearchInput() {
        if (!S) return;
        clearTimeout(S.searchTimer);
        S.searchTimer = setTimeout(renderTree, 200);
    }

    function onTreeClick(e) {
        const btn = e.target.closest('[data-tree-action]');
        if (!btn || !S) return;
        const id = parseInt(btn.dataset.deptId, 10);
        const node = S.byId.get(id);
        if (!node) return;
        switch (btn.dataset.treeAction) {
            case 'toggle':
                if (S.expanded.has(id)) S.expanded.delete(id); else S.expanded.add(id);
                renderTree();
                break;
            case 'detail':
                window.ConfigPage.navigate(`/itcj/config/departments/${id}`);
                break;
            case 'create-child':
                openCreateModal(id);
                break;
            case 'edit':
                openEditModal(node);
                break;
            case 'deactivate':
                deactivate(node);
                break;
        }
    }

    // === SELECTOR DE PADRE (Task 2 lo consume; definido aquí) =============
    /**
     * Llena un <select> con el árbol activo completo, indentado por profundidad.
     * options: { excludeSubtreeOf: id|null, selectedId: id|null, allowRoot: bool }
     * excludeSubtreeOf usa GET /departments/{id}/subtree (anti-ciclo en edición).
     */
    async function loadParentOptions(selectEl, opts) {
        const o = opts || {};
        const res = await fetch(`${API}/departments/parent-options`);
        const result = await res.json();
        if (!res.ok) throw new Error(result.error || 'Error al cargar opciones de padre');
        let excluded = new Set();
        if (o.excludeSubtreeOf != null) {
            const sres = await fetch(`${API}/departments/${o.excludeSubtreeOf}/subtree`);
            const sresult = await sres.json();
            if (sres.ok && sresult.data) excluded = new Set(sresult.data.department_ids || []);
        }
        selectEl.innerHTML = '';
        const first = document.createElement('option');
        first.value = '';
        first.textContent = o.allowRoot ? '— Sin padre (raíz) —' : 'Selecciona un departamento…';
        selectEl.appendChild(first);
        (result.data || []).forEach(d => {
            if (excluded.has(d.id)) return;
            const depth = (d.depth != null) ? d.depth : (S.byId.get(d.id) ? S.byId.get(d.id).depth : 0);
            const opt = document.createElement('option');
            opt.value = d.id;
            opt.textContent = `${'─'.repeat(depth)}${depth ? ' ' : ''}${d.name}`;
            if (o.selectedId === d.id) opt.selected = true;
            selectEl.appendChild(opt);
        });
    }

    // === CREAR (completo en Task 2) / EDITAR y DESACTIVAR (Task 3) ========
    async function openCreateModal(parentId) {
        const form = document.getElementById('createDepartmentForm');
        if (form) form.reset();
        try {
            await loadParentOptions(document.getElementById('deptParent'),
                { selectedId: parentId, allowRoot: true });
        } catch (err) {
            console.error(err);
            toast('Error al cargar los departamentos padre', 'danger');
        }
        if (S.createModal) S.createModal.show();
    }

    async function onCreateSubmit(e) {
        e.preventDefault();
        const formData = new FormData(e.target);
        const parentRaw = formData.get('parent_id');
        const payload = {
            code: (formData.get('code') || '').trim(),
            name: (formData.get('name') || '').trim(),
            description: (formData.get('description') || '').trim() || null,
            parent_id: parentRaw ? parseInt(String(parentRaw), 10) : null,
            icon_class: (formData.get('icon_class') || '').trim() || null,
        };
        const submitBtn = e.target.querySelector('button[type="submit"]');
        if (submitBtn) submitBtn.disabled = true;
        try {
            const res = await fetch(`${API}/departments`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const result = await res.json();
            if (!res.ok) {
                toast(result.error || 'Error al crear el departamento', 'danger');
                return;
            }
            toast('Departamento creado correctamente');
            if (S.createModal) S.createModal.hide();
            e.target.reset();
            if (payload.parent_id) S.expanded.add(payload.parent_id); // mostrar al hijo nuevo
            await loadTree();
        } catch (err) {
            console.error('Error creating department:', err);
            toast('Error de conexión', 'danger');
        } finally {
            if (submitBtn) submitBtn.disabled = false;
        }
    }

    // Stubs completados en Task 3 (edit modal + política D4).
    function openEditModal(node) { toast('Edición disponible próximamente', 'info'); }
    function onEditSubmit(e) { e.preventDefault(); }
    function deactivate(node) { toast('Desactivación disponible próximamente', 'info'); }

    window.ConfigPage.register('departments', { init: init, destroy: destroy });
})();
