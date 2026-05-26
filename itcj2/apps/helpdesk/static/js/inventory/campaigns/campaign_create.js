'use strict';
(function () {

    const API_BASE = '/api/help-desk/v2/inventory/campaigns';

    const el = {
        form:       document.getElementById('campaign-create-form'),
        dept:       document.getElementById('department-select'),
        title:      document.getElementById('title-input'),
        period:     document.getElementById('period-select'),
        notes:      document.getElementById('notes-input'),
        error:      document.getElementById('form-error'),
        submit:     document.getElementById('btn-submit'),
        deptAlert:  document.getElementById('dept-campaign-alert'),
        deptMsg:    document.getElementById('dept-campaign-msg'),
    };

    async function checkActiveCampaign(deptId) {
        if (!deptId || !el.deptAlert) return;
        el.deptAlert.classList.add('d-none');
        try {
            const res = await fetch(`${API_BASE}?department_id=${deptId}&status=OPEN&per_page=1`);
            const data = await res.json();
            if (data.success && data.total > 0) {
                const c = data.campaigns[0];
                el.deptMsg.textContent = ` Ya existe una campaña activa (${c.folio}). Ciérrala antes de crear una nueva.`;
                el.deptAlert.classList.remove('d-none');
            }
        } catch (_) { /* silencioso */ }
    }

    async function handleSubmit(e) {
        e.preventDefault();
        el.error.classList.add('d-none');

        const deptId = parseInt(el.dept.value, 10);
        const title  = el.title.value.trim();

        if (!deptId) {
            showError('Selecciona un departamento.');
            return;
        }
        if (title.length < 5) {
            showError('El título debe tener al menos 5 caracteres.');
            return;
        }

        const body = { department_id: deptId, title };
        if (el.period && el.period.value) body.academic_period_id = parseInt(el.period.value, 10);
        if (el.notes && el.notes.value.trim()) body.notes = el.notes.value.trim();

        el.submit.disabled = true;
        el.submit.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Creando...';

        try {
            const res = await fetch(API_BASE, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await res.json();
            if (!data.success) throw new Error(data.error || 'Error al crear la campaña');
            window.location = `/help-desk/inventory/campaigns/${data.data.id}`;
        } catch (err) {
            showError(err.message);
            el.submit.disabled = false;
            el.submit.innerHTML = '<i class="fas fa-save"></i> Crear Campaña';
        }
    }

    function showError(msg) {
        el.error.textContent = msg;
        el.error.classList.remove('d-none');
    }

    function init() {
        if (el.dept) {
            el.dept.addEventListener('change', () => checkActiveCampaign(el.dept.value));
        }
        if (el.form) {
            el.form.addEventListener('submit', handleSubmit);
        }
    }

    document.addEventListener('DOMContentLoaded', init);

})();
