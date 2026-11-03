/* Credencial del alumno: volteo al QR, reloj vivo, cuenta regresiva del código y
   brillo que sigue la inclinación del teléfono. El QR lo trae HTMX (#cc-qr);
   aquí solo se vigila su edad: un código vencido nunca queda a la vista. */
document.addEventListener('DOMContentLoaded', () => {
    const page = document.getElementById('cs-page');
    if (!page) return;

    const card = document.getElementById('cc-card-full');
    const front = document.getElementById('cc-front');
    const back = document.getElementById('cc-back');
    const flipBtn = document.getElementById('cc-flip');
    const flipLabel = document.getElementById('cc-flip-label');
    const qr = document.getElementById('cc-qr');
    const ringBar = document.getElementById('cc-ring-bar');
    const ringSec = document.getElementById('cc-ring-sec');
    const qrStatus = document.getElementById('cc-qr-status');
    const clocks = document.querySelectorAll('[data-cc-clock]');

    const TTL = Number(page.dataset.ttl) || 60;
    const REFRESH = Number(page.dataset.refresh) || 30;
    const RETRY_MS = 5000;
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

    // === RELOJ ===
    let fmt;
    try {
        fmt = new Intl.DateTimeFormat('es-MX', {
            hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
            timeZone: page.dataset.tz,
        });
    } catch (e) {  // zona desconocida para el navegador: hora local
        fmt = new Intl.DateTimeFormat('es-MX', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
    }

    // === QR: EDAD, ESTADOS Y REINTENTO ===
    // Date.now() y no performance.now(): este último se congela con el teléfono dormido
    // y haría pasar por vigente un código viejo.
    let receivedAt = 0;
    let retryTimer = 0;

    const codeAge = () => (receivedAt ? (Date.now() - receivedAt) / 1000 : Infinity);

    function setQrState(state, msg) {
        if (!qr) return;
        qr.classList.toggle('is-stale', state === 'stale');
        qr.classList.toggle('is-expired', state === 'expired');
        if (msg) qr.dataset.msg = msg;
        else delete qr.dataset.msg;
        if (qrStatus) qrStatus.textContent = msg || 'Escanea para verificar';
    }

    function refreshQr() {
        if (qr && window.htmx) window.htmx.trigger(qr, 'cc:refresh');
    }

    function scheduleRetry() {
        clearTimeout(retryTimer);
        retryTimer = setTimeout(refreshQr, RETRY_MS);
    }

    function paintRing(left) {
        if (!ringBar) return;
        ringSec.textContent = String(Math.ceil(left));
        // Se apunta a donde debe estar en el siguiente segundo; la transición de 1 s lo une.
        const next = Math.max(0, left - 1) / REFRESH;
        ringBar.style.strokeDashoffset = String(100 - next * 100);
    }

    function tick() {
        const text = fmt.format(new Date());
        clocks.forEach((el) => { el.textContent = text; });
        if (!qr || !receivedAt) return;

        const age = codeAge();
        if (age >= TTL) {
            setQrState('expired', navigator.onLine === false ? 'Sin conexión. Reintentando…' : 'Código vencido. Reintentando…');
            paintRing(0);
            return;
        }
        paintRing(Math.max(0, REFRESH - age));
        // El sondeo de HTMX se pausa con la pestaña oculta: si se pasó, se pide ya.
        if (age > REFRESH + 3 && !qr.classList.contains('is-stale')) refreshQr();
    }

    if (qr) {
        qr.addEventListener('htmx:afterSwap', () => {
            if (!qr.querySelector('.cc-qr__code')) return;
            receivedAt = Date.now();
            clearTimeout(retryTimer);
            setQrState('ok');
            ringBar.classList.add('is-reset');
            paintRing(REFRESH + 1);
            void ringBar.getBoundingClientRect();  // aplica el reinicio sin animarlo
            ringBar.classList.remove('is-reset');
            paintRing(REFRESH);
        });

        const onError = (evt) => {
            const status = evt.detail && evt.detail.xhr ? evt.detail.xhr.status : 0;
            if (status === 409) { setQrState('expired', 'Foto pendiente: acude a Servicios Escolares.'); return; }
            if (status === 403) { setQrState('expired', 'Credencial no vigente.'); return; }
            const msg = navigator.onLine === false ? 'Sin conexión. Reintentando…' : 'Reintentando…';
            setQrState(codeAge() < TTL ? 'stale' : 'expired', msg);
            if (codeAge() >= TTL) paintRing(0);  // también en la 1.ª carga: el anillo no promete tiempo
            scheduleRetry();
        };
        qr.addEventListener('htmx:responseError', onError);
        qr.addEventListener('htmx:sendError', onError);
        qr.addEventListener('htmx:timeout', onError);

        window.addEventListener('offline', () => {
            if (codeAge() < TTL) setQrState('stale', 'Sin conexión. Reintentando…');
        });
        window.addEventListener('online', refreshQr);
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible' && codeAge() > REFRESH - 2) refreshQr();
        });
    }

    tick();
    setInterval(tick, 1000);

    // === BRILLO CON INCLINACIÓN ===
    // Android/escritorio entregan deviceorientation sin pedir permiso; iOS 13+ exige
    // pedirlo dentro de un toque, así que se pide en el primero.
    const Orientation = window.DeviceOrientationEvent;
    const needsPermission = !!(Orientation && typeof Orientation.requestPermission === 'function');
    let frame = 0;
    let tx = 0;
    let ty = 0;

    function onOrient(e) {
        if (e.gamma == null || e.beta == null || !card) return;
        tx = Math.max(-1, Math.min(1, e.gamma / 30));
        ty = Math.max(-1, Math.min(1, (e.beta - 45) / 30));
        if (!card.classList.contains('has-tilt')) card.classList.add('has-tilt');
        if (frame) return;
        frame = requestAnimationFrame(() => {
            frame = 0;
            card.style.setProperty('--cc-tx', tx.toFixed(3));
            card.style.setProperty('--cc-ty', ty.toFixed(3));
        });
    }

    function startTilt() {
        window.addEventListener('deviceorientation', onOrient);
    }

    // Con movimiento reducido el brillo es estático: ni se escucha ni se pide permiso.
    if (card && Orientation && !reduceMotion.matches) {
        if (needsPermission) {
            document.addEventListener('click', () => {
                Orientation.requestPermission()
                    .then((state) => { if (state === 'granted') startTilt(); })
                    .catch(() => {});  // sin permiso: se queda la deriva lenta
            }, { once: true });
        } else {
            startTilt();
        }
    }

    // === VOLTEO ===
    if (!card || !flipBtn) return;
    const flipIcon = flipBtn.querySelector('.bi');

    function setFlipped(on) {
        card.classList.toggle('is-flipped', on);
        front.inert = on;
        back.inert = !on;
        flipLabel.textContent = on ? 'Mostrar credencial' : 'Mostrar QR';
        flipIcon.className = on ? 'bi bi-person-vcard' : 'bi bi-qr-code';
        if (on && codeAge() > REFRESH) refreshQr();
    }

    flipBtn.addEventListener('click', () => setFlipped(!card.classList.contains('is-flipped')));
    card.addEventListener('click', () => setFlipped(!card.classList.contains('is-flipped')));
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && card.classList.contains('is-flipped')) setFlipped(false);
    });
});
