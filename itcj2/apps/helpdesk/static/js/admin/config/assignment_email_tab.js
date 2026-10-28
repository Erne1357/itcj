/**
 * assignment_email_tab.js
 * Tab "Correo" del panel de Configuración: qué técnicos reciben correo
 * cuando se les asigna un ticket + estado del buzón de la app.
 * Lazy init: carga datos solo la primera vez que el tab #correo es visible.
 */
(function () {
    'use strict';

    // === ESTADO ===
    let initialized = false;
    let busy = false;
    let technicians = [];

    // === CONSTANTES ===
    const API = '/api/help-desk/v2/config/assignment-email';
    const AREA_LABEL = { DESARROLLO: 'Desarrollo', SOPORTE: 'Soporte' };

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

    // === TEARDOWN (morph-safe) ===
    document.addEventListener('config:teardown', function () {
        initialized = false;
        busy = false;
        technicians = [];
    });

    // === INIT (lazy por config:tab-shown) ===
    document.addEventListener('config:tab-shown', function (e) {
        if (e.detail && e.detail.tab === '#correo' && !initialized) {
            initialized = true;
            loadData();
        }
    });

    // === CARGA ===
    async function loadData() {
        const root = document.getElementById('correo-root');
        if (!root) return;
        root.innerHTML = '<div class="text-center text-muted py-4"><i class="fas fa-spinner fa-spin me-2"></i>Cargando...</div>';
        try {
            const res = await fetch(API, { credentials: 'same-origin' });
            if (!res.ok) {
                root.innerHTML = '<div class="alert alert-danger mb-0">' +
                    escapeHtml(await apiErrorMsg(res, 'Error al cargar la configuración de correo')) + '</div>';
                initialized = false;
                return;
            }
            const body = await res.json();
            technicians = body.data.technicians || [];
            render(body.data);
        } catch (_) {
            root.innerHTML = '<div class="alert alert-danger mb-0">Error de conexión</div>';
            initialized = false;
        }
    }

    // === RENDER ===
    function mailboxCard(data) {
        if (data.connected) {
            const acc = data.account || {};
            return '<div class="alert alert-success d-flex align-items-center gap-2 mb-3">' +
                '<i class="fas fa-check-circle"></i><div>Buzón conectado: <strong>' +
                escapeHtml(acc.username || acc.name || '') + '</strong>' +
                (acc.name && acc.username ? ' <span class="text-muted">(' + escapeHtml(acc.name) + ')</span>' : '') +
                '</div></div>';
        }
        return '<div class="alert alert-warning d-flex align-items-center gap-2 mb-3">' +
            '<i class="fas fa-exclamation-triangle"></i><div>El buzón de Help Desk no está conectado, no se enviará ningún correo. ' +
            (data.config_url
                ? '<a href="' + escapeHtml(data.config_url) + '" class="alert-link">Conectar buzón</a>'
                : '') +
            '</div></div>';
    }

    function render(data) {
        const root = document.getElementById('correo-root');
        if (!root) return;
        let rows;
        if (!technicians.length) {
            rows = '<tr><td colspan="4" class="text-center text-muted">Sin técnicos activos</td></tr>';
        } else {
            rows = technicians.map(function (t) {
                const areas = (t.areas || []).map(function (a) {
                    return '<span class="badge text-bg-secondary me-1">' + escapeHtml(AREA_LABEL[a] || a) + '</span>';
                }).join('');
                const noMail = !t.email;
                return '<tr>' +
                    '<td>' + escapeHtml(t.name) + '</td>' +
                    '<td>' + areas + '</td>' +
                    '<td>' + (noMail
                        ? '<span class="text-muted small">Sin correo registrado</span>'
                        : escapeHtml(t.email)) + '</td>' +
                    '<td class="text-center"><div class="form-check form-switch d-inline-block m-0">' +
                    '<input class="form-check-input assign-email-switch" type="checkbox" role="switch" ' +
                    'data-user-id="' + escapeHtml(t.id) + '" aria-label="Enviar correo al asignar a ' + escapeHtml(t.name) + '"' +
                    (t.enabled ? ' checked' : '') + (noMail ? ' disabled' : '') + '></div></td>' +
                    '</tr>';
            }).join('');
        }
        root.innerHTML = mailboxCard(data) +
            '<p class="text-muted small">Los técnicos marcados reciben un correo cuando se les asigna un ticket (a ellos, no al equipo).</p>' +
            '<div class="table-responsive"><table class="table align-middle mb-0">' +
            '<thead><tr><th>Técnico</th><th>Área</th><th>Correo</th><th class="text-center">Enviar al asignar</th></tr></thead>' +
            '<tbody>' + rows + '</tbody></table></div>';

        root.querySelectorAll('.assign-email-switch').forEach(function (sw) {
            sw.addEventListener('change', onSwitchChange);
        });
    }

    // === ACCIONES ===
    function setSwitchesDisabled(disabled) {
        document.querySelectorAll('#correo-root .assign-email-switch').forEach(function (sw) {
            const t = technicians.find(function (x) { return String(x.id) === sw.dataset.userId; });
            sw.disabled = disabled || !(t && t.email);
        });
    }

    async function onSwitchChange(e) {
        const sw = e.target;
        if (busy) { sw.checked = !sw.checked; return; }
        const id = Number(sw.dataset.userId);
        const tech = technicians.find(function (x) { return x.id === id; });
        if (!tech) return;
        const wanted = sw.checked;

        // Conjunto completo con el cambio aplicado
        const ids = technicians
            .filter(function (x) { return x.id === id ? wanted : x.enabled; })
            .map(function (x) { return x.id; });

        busy = true;
        setSwitchesDisabled(true);
        try {
            const res = await fetch(API, {
                method: 'PUT',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_ids: ids }),
            });
            if (!res.ok) {
                sw.checked = !wanted;
                toast(await apiErrorMsg(res, 'No se pudo guardar el cambio'), 'error');
                return;
            }
            tech.enabled = wanted;
            // showToast pinta por innerHTML: el nombre va escapado.
            toast((wanted ? 'Se enviará correo a ' : 'Ya no se enviará correo a ') + escapeHtml(tech.name), 'success');
        } catch (_) {
            sw.checked = !wanted;
            toast('Error de conexión', 'error');
        } finally {
            busy = false;
            setSwitchesDisabled(false);
        }
    }
})();
