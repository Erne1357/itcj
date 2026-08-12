/**
 * Flujo compartido "Crear usuario inactivo" — registra personal sin cuenta
 * previa (username autogenerado, password temporal) para poder asignarle
 * equipo de inventario en el acto. Extraído de item_create.js (registro de
 * equipo) para reutilizarse también en verification.js (reasignación durante
 * la verificación física) — ambas páginas exigen el mismo permiso de fondo
 * (helpdesk.inventory.api.create vía POST /api/core/v2/users/create-inactive).
 *
 * Opera sobre el modal #createInactiveUserModal, que cada template clona con
 * los MISMOS ids (inactive-first-name, inactive-last-name, inactive-middle-name,
 * inactive-username, inactive-email, username-hint, btn-next-username,
 * create-inactive-user-form, btn-confirm-inactive-user) — es un widget
 * autocontenido, no un componente Jinja compartido.
 *
 * Uso:
 *   window.HelpdeskInactiveUser.init({
 *     getDepartmentId: () => 12,      // depto al que se vincula el nuevo usuario
 *     onCreated: (user) => { ... },   // user = {id, full_name, username, email, is_active:false}
 *   });
 *
 * Si #btn-create-inactive-user no existe en la página (el usuario no tiene el
 * permiso helpdesk.inventory.api.create y el caller no renderizó el botón),
 * init() no hace nada.
 */
(function () {
    'use strict';

    function _normalizeStr(s) {
        return (s || '').toLowerCase()
            .normalize('NFD').replace(/[̀-ͯ]/g, '')
            .replace(/[^a-z0-9]/g, '');
    }

    function _generateUsernameCandidates(firstName, lastName, middleName) {
        const fn = _normalizeStr(firstName.trim().split(/\s+/)[0]);
        const fn2 = _normalizeStr((firstName.trim().split(/\s+/)[1] || ''));
        const ln = _normalizeStr(lastName.trim().split(/\s+/)[0]);
        const ln2 = _normalizeStr(middleName ? middleName.trim().split(/\s+/)[0] : '');

        const candidates = [];
        if (fn && ln) candidates.push(fn[0] + ln);
        if (fn && ln2) candidates.push(fn[0] + ln2);
        if (fn2 && ln) candidates.push(fn2[0] + ln);
        if (fn && ln) candidates.push(fn + ln);
        return candidates.filter((v, i, a) => v.length > 1 && a.indexOf(v) === i);
    }

    function init(options) {
        const opts = options || {};
        const getDepartmentId = typeof opts.getDepartmentId === 'function' ? opts.getDepartmentId : () => null;
        const onCreated = typeof opts.onCreated === 'function' ? opts.onCreated : function () {};

        const btnOpen = document.getElementById('btn-create-inactive-user');
        if (!btnOpen) return;

        const modalEl = document.getElementById('createInactiveUserModal');
        const bsModal = () => bootstrap.Modal.getOrCreateInstance(modalEl);

        let usernameCandidates = [];
        let usernameIndex = 0;

        btnOpen.addEventListener('click', () => {
            usernameCandidates = [];
            usernameIndex = 0;
            document.getElementById('inactive-first-name').value = '';
            document.getElementById('inactive-last-name').value = '';
            document.getElementById('inactive-middle-name').value = '';
            document.getElementById('inactive-username').value = '';
            document.getElementById('inactive-email').value = '';
            document.getElementById('username-hint').textContent = 'Generado automáticamente. Puedes editarlo si hay conflicto.';
            bsModal().show();
        });

        ['inactive-first-name', 'inactive-last-name', 'inactive-middle-name'].forEach(id => {
            document.getElementById(id).addEventListener('input', () => {
                const fn = document.getElementById('inactive-first-name').value;
                const ln = document.getElementById('inactive-last-name').value;
                const mn = document.getElementById('inactive-middle-name').value;
                if (fn && ln) {
                    usernameCandidates = _generateUsernameCandidates(fn, ln, mn);
                    usernameIndex = 0;
                    document.getElementById('inactive-username').value = usernameCandidates[0] || '';
                }
            });
        });

        document.getElementById('btn-next-username').addEventListener('click', () => {
            if (usernameCandidates.length === 0) return;
            usernameIndex = (usernameIndex + 1) % usernameCandidates.length;
            const next = usernameCandidates[usernameIndex];
            document.getElementById('inactive-username').value = next || '';
            if (usernameIndex === 0) {
                document.getElementById('username-hint').textContent = 'Volviste al inicio. Edítalo manualmente si ninguno funciona.';
            } else {
                document.getElementById('username-hint').textContent = `Variante ${usernameIndex + 1} de ${usernameCandidates.length}`;
            }
        });

        async function handleSubmit(e) {
            e.preventDefault();

            const deptId = parseInt(getDepartmentId(), 10);
            if (!deptId) { showToast('Selecciona primero el departamento del equipo.', 'error'); return; }

            const firstName = document.getElementById('inactive-first-name').value.trim();
            const lastName = document.getElementById('inactive-last-name').value.trim();
            const middleName = document.getElementById('inactive-middle-name').value.trim();
            const username = document.getElementById('inactive-username').value.trim();
            const email = document.getElementById('inactive-email').value.trim();

            if (!firstName || !lastName || !username) {
                showToast('Nombre, apellido y username son obligatorios.', 'error');
                return;
            }

            const btn = document.getElementById('btn-confirm-inactive-user');
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Creando...';

            try {
                const res = await fetch('/api/core/v2/users/create-inactive', {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        first_name: firstName, last_name: lastName,
                        middle_name: middleName || null, email: email || null,
                        username, department_id: deptId,
                    }),
                });

                const data = await res.json();

                if (res.status === 409) {
                    const nextIdx = (usernameIndex + 1) % (usernameCandidates.length || 1);
                    const nextUser = usernameCandidates[nextIdx];
                    if (nextUser && nextUser !== username) {
                        usernameIndex = nextIdx;
                        document.getElementById('inactive-username').value = nextUser;
                        document.getElementById('username-hint').textContent =
                            `"${username}" ya está en uso. Prueba con "${nextUser}" u edítalo.`;
                    } else {
                        document.getElementById('username-hint').textContent =
                            `"${username}" ya está en uso. Edítalo manualmente.`;
                    }
                    btn.disabled = false;
                    btn.innerHTML = '<i class="fas fa-save"></i> Crear usuario';
                    return;
                }

                if (!res.ok) throw new Error((data && data.error) || 'Error al crear usuario');

                const newUser = data.data;
                bsModal().hide();
                showToast(`Usuario ${newUser.full_name} creado. Se seleccionó automáticamente.`, 'success');
                onCreated(newUser);
            } catch (err) {
                showToast(err.message, 'error');
            } finally {
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-save"></i> Crear usuario';
            }
        }

        document.getElementById('create-inactive-user-form').addEventListener('submit', handleSubmit);
    }

    window.HelpdeskInactiveUser = { init: init };
})();
