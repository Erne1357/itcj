/**
 * auto_assign_tab.js
 * Tab "Asignación automática" del panel de Configuración: switch maestro del
 * motor + reglas (área / categoría / prioridad -> técnicos y reparto).
 * Lazy init: carga datos solo la primera vez que el tab #autoasig es visible.
 */
(function () {
    'use strict';

    // === ESTADO ===
    let initialized = false;
    let busy = false;
    let enabled = false;
    let rules = [];
    let catalogs = { areas: [], categories: [], priorities: [], technicians_by_area: {} };
    let editingRuleId = null;

    // === CONSTANTES ===
    const API = '/api/help-desk/v2/config/auto-assign';
    const STRATEGY_LABEL = { round_robin: 'Turnos', least_loaded: 'Menor carga' };

    // === HELPERS ===
    function escapeHtml(str) {
        if (str === null || str === undefined) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    async function apiErrorMsg(res, fallback) {
        try {
            const d = await res.json();
            const v = d.error || d.message || d.detail;
            if (typeof v === 'string' && v) return v;
            if (Array.isArray(v)) {
                return v.map(function (e) { return (e && e.msg) ? e.msg : String(e); }).join('; ') || fallback;
            }
            return fallback;
        } catch (_) {
            return fallback + ' (HTTP ' + res.status + ')';
        }
    }

    function toast(msg, type) {
        if (window.HelpdeskUtils) window.HelpdeskUtils.showToast(msg, type);
    }

    function labelOf(list, code) {
        const f = list.find(function (x) { return x.code === code; });
        return f ? f.label : code;
    }

    function request(method, url, payload) {
        const opts = { method: method, credentials: 'same-origin' };
        if (payload !== undefined) {
            opts.headers = { 'Content-Type': 'application/json' };
            opts.body = JSON.stringify(payload);
        }
        return fetch(url, opts);
    }

    // === TEARDOWN (morph-safe) ===
    document.addEventListener('config:teardown', function () {
        initialized = false;
        busy = false;
        enabled = false;
        rules = [];
        editingRuleId = null;
        const modalEl = document.getElementById('modal-assign-rule');
        if (modalEl && window.bootstrap) {
            const inst = bootstrap.Modal.getInstance(modalEl);
            if (inst) inst.hide();
        }
    });

    // === INIT (lazy por config:tab-shown) ===
    document.addEventListener('config:tab-shown', function (e) {
        if (e.detail && e.detail.tab === '#autoasig' && !initialized) {
            initialized = true;
            bindModal();
            loadData();
        }
    });

    // === CARGA ===
    async function loadData() {
        const root = document.getElementById('autoasig-root');
        if (!root) return;
        if (!rules.length) {
            root.innerHTML = '<div class="text-center text-muted py-4"><i class="fas fa-spinner fa-spin me-2"></i>Cargando...</div>';
        }
        try {
            const res = await request('GET', API);
            if (!res.ok) {
                root.innerHTML = '<div class="alert alert-danger mb-0">' +
                    escapeHtml(await apiErrorMsg(res, 'Error al cargar las reglas')) + '</div>';
                initialized = false;
                return;
            }
            const body = await res.json();
            enabled = !!body.data.enabled;
            rules = body.data.rules || [];
            catalogs = body.data.catalogs || catalogs;
            render();
        } catch (_) {
            root.innerHTML = '<div class="alert alert-danger mb-0">Error de conexión</div>';
            initialized = false;
        }
    }

    // === RENDER ===
    function technicianCell(rule) {
        const list = (rule.technicians || []).map(function (t, i) {
            return '<li class="' + (t.eligible ? '' : 'text-muted') + '">' + (i + 1) + '. ' +
                (t.eligible
                    ? escapeHtml(t.name)
                    : '<s>' + escapeHtml(t.name) + '</s> <span class="badge text-bg-warning">no disponible</span>') +
                '</li>';
        }).join('');
        return '<ol class="list-unstyled mb-0 small">' + list + '</ol>';
    }

    function ruleRow(r) {
        return '<tr' + (r.is_active ? '' : ' class="text-muted"') + '>' +
            '<td>' + escapeHtml(labelOf(catalogs.areas, r.area)) + '</td>' +
            '<td>' + (r.category_id ? escapeHtml(r.category_name) : '<em>Toda el área</em>') + '</td>' +
            '<td>' + (r.priority ? escapeHtml(labelOf(catalogs.priorities, r.priority)) : '<em>Cualquiera</em>') + '</td>' +
            '<td>' + escapeHtml(STRATEGY_LABEL[r.strategy] || r.strategy) + '</td>' +
            '<td>' + technicianCell(r) + '</td>' +
            '<td>' + (r.last_assigned_name ? escapeHtml(r.last_assigned_name) : '<span class="text-muted">&mdash;</span>') + '</td>' +
            '<td class="text-center"><div class="form-check form-switch d-inline-block m-0">' +
            '<input class="form-check-input rule-active-switch" type="checkbox" role="switch" data-rule-id="' + escapeHtml(r.id) + '"' +
            ' aria-label="Regla activa"' + (r.is_active ? ' checked' : '') + '></div></td>' +
            '<td class="text-nowrap">' +
            '<button class="btn btn-sm btn-outline-primary me-1 btn-rule-edit" data-rule-id="' + escapeHtml(r.id) + '" title="Editar">' +
            '<i class="fas fa-edit"></i><span class="d-none d-sm-inline"> Editar</span></button>' +
            '<button class="btn btn-sm btn-outline-danger btn-rule-delete" data-rule-id="' + escapeHtml(r.id) + '" title="Borrar">' +
            '<i class="fas fa-trash"></i><span class="d-none d-sm-inline"> Borrar</span></button>' +
            '</td></tr>';
    }

    function render() {
        const root = document.getElementById('autoasig-root');
        if (!root) return;
        const rows = rules.length
            ? rules.map(ruleRow).join('')
            : '<tr><td colspan="8" class="text-center text-muted">Sin reglas. Crea la primera con &laquo;Nueva regla&raquo;.</td></tr>';
        root.innerHTML =
            '<div class="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-3">' +
            '<div class="form-check form-switch m-0">' +
            '<input class="form-check-input" type="checkbox" role="switch" id="autoasig-master"' + (enabled ? ' checked' : '') + '>' +
            '<label class="form-check-label fw-semibold" for="autoasig-master">Motor de asignación automática activo</label>' +
            '<div class="text-muted small">Solo asigna tickets nuevos al crearse; los que no coincidan con ninguna regla quedan en la cola.</div></div>' +
            '<button class="btn btn-primary btn-sm" id="btn-rule-new"><i class="fas fa-plus"></i><span class="d-none d-sm-inline"> Nueva regla</span></button>' +
            '</div>' +
            '<div class="table-responsive"><table class="table align-middle mb-0">' +
            '<thead><tr><th>Área</th><th>Categoría</th><th>Prioridad</th><th>Reparto</th><th>Técnicos (en orden)</th>' +
            '<th>Último asignado</th><th class="text-center">Activa</th><th></th></tr></thead>' +
            '<tbody>' + rows + '</tbody></table></div>';

        document.getElementById('autoasig-master').addEventListener('change', onMasterChange);
        document.getElementById('btn-rule-new').addEventListener('click', function () { openModal(null); });
        root.querySelectorAll('.rule-active-switch').forEach(function (sw) {
            sw.addEventListener('change', onActiveChange);
        });
        root.querySelectorAll('.btn-rule-edit').forEach(function (b) {
            b.addEventListener('click', function () { openModal(Number(b.dataset.ruleId)); });
        });
        root.querySelectorAll('.btn-rule-delete').forEach(function (b) {
            b.addEventListener('click', function () { onDelete(Number(b.dataset.ruleId)); });
        });
    }

    function setRootDisabled(disabled) {
        document.querySelectorAll('#autoasig-root input, #autoasig-root button').forEach(function (el) {
            el.disabled = disabled;
        });
    }

    // === ACCIONES DE LA TABLA ===
    async function onMasterChange(e) {
        const sw = e.target;
        const wanted = sw.checked;
        if (busy) { sw.checked = !wanted; return; }
        busy = true;
        setRootDisabled(true);
        try {
            const res = await request('PATCH', API + '/settings', { enabled: wanted });
            if (!res.ok) {
                sw.checked = !wanted;
                toast(await apiErrorMsg(res, 'No se pudo cambiar el estado del motor'), 'error');
                return;
            }
            enabled = wanted;
            toast(wanted ? 'Motor activado' : 'Motor desactivado', 'success');
        } catch (_) {
            sw.checked = !wanted;
            toast('Error de conexión', 'error');
        } finally {
            busy = false;
            setRootDisabled(false);
        }
    }

    async function onActiveChange(e) {
        const sw = e.target;
        const wanted = sw.checked;
        if (busy) { sw.checked = !wanted; return; }
        busy = true;
        setRootDisabled(true);
        try {
            const res = await request('PATCH', API + '/rules/' + sw.dataset.ruleId, { is_active: wanted });
            if (!res.ok) {
                sw.checked = !wanted;
                toast(await apiErrorMsg(res, 'No se pudo actualizar la regla'), 'error');
                return;
            }
            const r = rules.find(function (x) { return String(x.id) === sw.dataset.ruleId; });
            if (r) r.is_active = wanted;
            toast(wanted ? 'Regla activada' : 'Regla desactivada', 'success');
            render();
        } catch (_) {
            sw.checked = !wanted;
            toast('Error de conexión', 'error');
        } finally {
            busy = false;
            setRootDisabled(false);
        }
    }

    async function onDelete(id) {
        if (busy) return;
        const ok = await window.HelpdeskUtils.confirmDialog(
            'Borrar regla',
            '¿Borrar esta regla de asignación? Los tickets nuevos que le correspondían quedarán en la cola.',
            'Borrar', 'Cancelar');
        if (!ok) return;
        busy = true;
        setRootDisabled(true);
        try {
            const res = await request('DELETE', API + '/rules/' + id);
            if (!res.ok) {
                toast(await apiErrorMsg(res, 'No se pudo borrar la regla'), 'error');
                return;
            }
            toast('Regla borrada', 'success');
            busy = false;
            await loadData();
        } catch (_) {
            toast('Error de conexión', 'error');
        } finally {
            busy = false;
            setRootDisabled(false);
        }
    }

    // === MODAL ===
    function bindModal() {
        const modal = document.getElementById('modal-assign-rule');
        if (!modal || modal.dataset.assignRuleBound) return;
        modal.dataset.assignRuleBound = '1';
        document.getElementById('assign-rule-area').addEventListener('change', function () {
            fillCategories(this.value, null);
            fillTechnicians(this.value, []);
        });
        document.getElementById('btn-assign-rule-save').addEventListener('click', saveRule);
    }

    function fillAreas(selected) {
        document.getElementById('assign-rule-area').innerHTML = catalogs.areas.map(function (a) {
            return '<option value="' + escapeHtml(a.code) + '"' + (a.code === selected ? ' selected' : '') + '>' + escapeHtml(a.label) + '</option>';
        }).join('');
    }

    function fillCategories(area, selected) {
        const opts = ['<option value="">Toda el área</option>'].concat(
            catalogs.categories.filter(function (c) { return c.area === area; }).map(function (c) {
                return '<option value="' + escapeHtml(c.id) + '"' + (c.id === selected ? ' selected' : '') + '>' + escapeHtml(c.name) + '</option>';
            }));
        document.getElementById('assign-rule-category').innerHTML = opts.join('');
    }

    function fillPriorities(selected) {
        const opts = ['<option value="">Cualquiera</option>'].concat(
            catalogs.priorities.map(function (p) {
                return '<option value="' + escapeHtml(p.code) + '"' + (p.code === selected ? ' selected' : '') + '>' + escapeHtml(p.label) + '</option>';
            }));
        document.getElementById('assign-rule-priority').innerHTML = opts.join('');
    }

    function fillTechnicians(area, selectedIds) {
        const techs = (catalogs.technicians_by_area[area] || []).slice()
            .sort(function (a, b) { return a.name.localeCompare(b.name, 'es'); });
        const box = document.getElementById('assign-rule-technicians');
        if (!techs.length) {
            box.innerHTML = '<span class="text-muted small">No hay técnicos activos en esta área.</span>';
            return;
        }
        box.innerHTML = techs.map(function (t) {
            return '<div class="form-check">' +
                '<input class="form-check-input assign-rule-tech" type="checkbox" id="assign-rule-tech-' + escapeHtml(t.id) + '" value="' + escapeHtml(t.id) + '"' +
                (selectedIds.indexOf(t.id) !== -1 ? ' checked' : '') + '>' +
                '<label class="form-check-label" for="assign-rule-tech-' + escapeHtml(t.id) + '">' + escapeHtml(t.name) + '</label></div>';
        }).join('');
    }

    function showModalError(msg) {
        const el = document.getElementById('assign-rule-error');
        el.textContent = msg || '';
        el.classList.toggle('d-none', !msg);
    }

    function openModal(ruleId) {
        editingRuleId = ruleId;
        const rule = ruleId ? rules.find(function (r) { return r.id === ruleId; }) : null;
        const area = rule ? rule.area : (catalogs.areas[0] ? catalogs.areas[0].code : '');
        document.getElementById('assign-rule-title').textContent = rule ? 'Editar regla' : 'Nueva regla';
        fillAreas(area);
        fillCategories(area, rule ? rule.category_id : null);
        fillPriorities(rule ? rule.priority : null);
        fillTechnicians(area, rule ? rule.technician_ids : []);
        document.getElementById(rule && rule.strategy === 'least_loaded'
            ? 'assign-rule-strategy-ll' : 'assign-rule-strategy-rr').checked = true;
        showModalError('');
        bootstrap.Modal.getOrCreateInstance(document.getElementById('modal-assign-rule')).show();
    }

    async function saveRule() {
        if (busy) return;
        const catVal = document.getElementById('assign-rule-category').value;
        const prioVal = document.getElementById('assign-rule-priority').value;
        const technicianIds = Array.prototype.map.call(
            document.querySelectorAll('#assign-rule-technicians .assign-rule-tech:checked'),
            function (c) { return Number(c.value); });
        if (!technicianIds.length) {
            showModalError('Selecciona al menos un técnico.');
            return;
        }
        const payload = {
            area: document.getElementById('assign-rule-area').value,
            category_id: catVal ? Number(catVal) : null,
            priority: prioVal || null,
            strategy: document.querySelector('input[name="assign-rule-strategy"]:checked').value,
            technician_ids: technicianIds,
        };
        const btn = document.getElementById('btn-assign-rule-save');
        busy = true;
        btn.disabled = true;
        showModalError('');
        try {
            const res = editingRuleId
                ? await request('PATCH', API + '/rules/' + editingRuleId, payload)
                : await request('POST', API + '/rules', payload);
            if (!res.ok) {
                showModalError(await apiErrorMsg(res, 'No se pudo guardar la regla'));
                return;
            }
            bootstrap.Modal.getOrCreateInstance(document.getElementById('modal-assign-rule')).hide();
            toast(editingRuleId ? 'Regla actualizada' : 'Regla creada', 'success');
            busy = false;
            await loadData();
        } catch (_) {
            showModalError('Error de conexión');
        } finally {
            busy = false;
            btn.disabled = false;
        }
    }
})();
