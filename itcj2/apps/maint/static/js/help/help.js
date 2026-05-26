/* itcj2/apps/maint/static/js/help/help.js
   Manual de Mantenimiento:
   - TOC dinámico generado desde <h2 id="...">
   - Scroll-spy compensa el header sticky
   - Lightbox con zoom (rueda + botones + teclas) y pan (drag + pinch en touch)
   - Collapse del TOC en móvil
*/

document.addEventListener('DOMContentLoaded', () => {

    const content = document.getElementById('mnHelpContent');
    const tocList = document.getElementById('mnHelpTocList');
    const tocToggle = document.getElementById('mnHelpTocToggle');
    if (!content || !tocList) return;

    // ────────────────────────────────────────────────────────────────────
    // TOC dinámico
    // ────────────────────────────────────────────────────────────────────
    const sections = Array.from(content.querySelectorAll('section.mn-help-section[id]'));
    sections.forEach((sec) => {
        const heading = sec.querySelector('h2');
        if (!heading) return;
        const a = document.createElement('a');
        a.href = `#${sec.id}`;
        a.textContent = heading.textContent.trim();
        a.dataset.section = sec.id;
        tocList.appendChild(a);
    });

    const tocLinks = Array.from(tocList.querySelectorAll('a'));
    const setActive = (id) => {
        tocLinks.forEach((l) => l.classList.toggle('is-active', l.dataset.section === id));
    };

    if ('IntersectionObserver' in window) {
        const observer = new IntersectionObserver((entries) => {
            const visible = entries
                .filter((e) => e.isIntersecting)
                .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
            if (visible.length > 0) {
                setActive(visible[0].target.id);
            }
        }, {
            rootMargin: '-120px 0px -55% 0px',
            threshold: 0,
        });
        sections.forEach((s) => observer.observe(s));
    }

    tocLinks.forEach((link) => {
        link.addEventListener('click', (ev) => {
            const id = link.dataset.section;
            const target = document.getElementById(id);
            if (!target) return;
            ev.preventDefault();
            target.scrollIntoView({ behavior: 'smooth', block: 'start' });
            history.replaceState(null, '', `#${id}`);
            if (window.matchMedia('(max-width: 991.98px)').matches) {
                tocList.classList.remove('is-open');
                if (tocToggle) tocToggle.setAttribute('aria-expanded', 'false');
            }
        });
    });

    if (tocToggle) {
        tocToggle.addEventListener('click', () => {
            const open = tocList.classList.toggle('is-open');
            tocToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
        });
    }

    // ────────────────────────────────────────────────────────────────────
    // Lightbox con zoom y pan
    // ────────────────────────────────────────────────────────────────────
    const lightbox = document.getElementById('mnHelpLightbox');
    const stage = document.getElementById('mnHelpLightboxStage');
    const lightboxImg = document.getElementById('mnHelpLightboxImg');
    const lightboxCaption = document.getElementById('mnHelpLightboxCaption');
    const lightboxClose = document.getElementById('mnHelpLightboxClose');
    const zoomIn = document.getElementById('mnHelpZoomIn');
    const zoomOut = document.getElementById('mnHelpZoomOut');
    const zoomReset = document.getElementById('mnHelpZoomReset');
    const zoomLevel = document.getElementById('mnHelpZoomLevel');

    // Estado de transformación: scale relativo al tamaño "fit" (1.0 = imagen ajustada al stage)
    // tx/ty en px del sistema del stage (origen 0,0 = top-left del stage).
    // baseW/baseH = tamaño de la imagen al ajustar a stage (scale=1).
    const ZOOM_MIN = 1;
    const ZOOM_MAX = 6;
    const ZOOM_STEP = 0.4;
    const PAN_MARGIN = 40;         // px que mantienen visibles al hacer pan
    const state = { scale: 1, tx: 0, ty: 0, baseW: 0, baseH: 0 };

    const stageRect = () => stage.getBoundingClientRect();

    /**
     * Clampa tx/ty para que la imagen no se salga totalmente del stage.
     * Permite arrastrar hasta que solo queden PAN_MARGIN px visibles por lado.
     */
    const clampPan = () => {
        const r = stageRect();
        const w = state.baseW * state.scale;
        const h = state.baseH * state.scale;
        // Si la imagen es más chica que el stage, no permitir que salga del borde
        const minTx = w >= r.width ? r.width - w - PAN_MARGIN : -PAN_MARGIN;
        const maxTx = w >= r.width ? PAN_MARGIN : r.width - w + PAN_MARGIN;
        const minTy = h >= r.height ? r.height - h - PAN_MARGIN : -PAN_MARGIN;
        const maxTy = h >= r.height ? PAN_MARGIN : r.height - h + PAN_MARGIN;
        state.tx = Math.min(maxTx, Math.max(minTx, state.tx));
        state.ty = Math.min(maxTy, Math.max(minTy, state.ty));
    };

    const applyTransform = () => {
        if (!lightboxImg) return;
        clampPan();
        lightboxImg.style.transform = `translate(${state.tx}px, ${state.ty}px) scale(${state.scale})`;
        if (zoomLevel) zoomLevel.textContent = `${Math.round(state.scale * 100)}%`;
        if (zoomIn) zoomIn.disabled = state.scale >= ZOOM_MAX - 0.001;
        if (zoomOut) zoomOut.disabled = state.scale <= ZOOM_MIN + 0.001;
    };

    /**
     * Ajusta la imagen al stage manteniendo aspect ratio (sin estirarla más allá
     * de su tamaño natural). Centra con tx/ty. Llamado en open + resize.
     */
    const fitImageToStage = () => {
        if (!lightboxImg || !stage) return;
        const iw = lightboxImg.naturalWidth;
        const ih = lightboxImg.naturalHeight;
        if (!iw || !ih) return;
        const r = stageRect();
        if (r.width === 0 || r.height === 0) return;
        const fit = Math.min(r.width / iw, r.height / ih, 1);
        state.baseW = iw * fit;
        state.baseH = ih * fit;
        lightboxImg.style.width = `${state.baseW}px`;
        lightboxImg.style.height = `${state.baseH}px`;
        state.scale = 1;
        state.tx = (r.width - state.baseW) / 2;
        state.ty = (r.height - state.baseH) / 2;
        applyTransform();
    };

    const resetTransform = () => {
        fitImageToStage();
    };

    /**
     * Zoom centrado en un punto del stage. Mantiene ese punto bajo el cursor
     * estable. Como la imagen está en (0,0) del stage con transform-origin 0 0,
     * las coordenadas del cursor relativas al stage coinciden con el espacio
     * de transform — el cálculo es directo y funciona para imágenes de
     * cualquier tamaño.
     */
    const zoomAt = (deltaScale, anchorX, anchorY) => {
        const newScale = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, state.scale + deltaScale));
        if (newScale === state.scale) return;
        const ratio = newScale / state.scale;
        state.tx = anchorX - (anchorX - state.tx) * ratio;
        state.ty = anchorY - (anchorY - state.ty) * ratio;
        state.scale = newScale;
        // Si volvimos a 1, recentrar para evitar quedar pegado a un borde
        if (Math.abs(state.scale - ZOOM_MIN) < 0.001) {
            const r = stageRect();
            state.tx = (r.width - state.baseW) / 2;
            state.ty = (r.height - state.baseH) / 2;
        }
        applyTransform();
    };

    const openLightbox = (src, caption) => {
        lightboxCaption.textContent = caption || '';
        lightboxImg.alt = caption || '';
        // Reset state antes de cargar
        state.scale = 1;
        state.tx = 0;
        state.ty = 0;
        state.baseW = 0;
        state.baseH = 0;
        lightbox.classList.add('is-open');
        lightbox.setAttribute('aria-hidden', 'false');
        document.body.style.overflow = 'hidden';
        // Esperar a que la imagen cargue para medir naturalWidth/Height
        const onReady = () => {
            // doble rAF para que el stage ya tenga su tamaño tras display:flex
            requestAnimationFrame(() => requestAnimationFrame(fitImageToStage));
        };
        if (lightboxImg.src === src && lightboxImg.complete && lightboxImg.naturalWidth) {
            onReady();
        } else {
            lightboxImg.onload = onReady;
            lightboxImg.src = src;
        }
    };

    const closeLightbox = () => {
        lightbox.classList.remove('is-open');
        lightbox.setAttribute('aria-hidden', 'true');
        lightboxImg.onload = null;
        lightboxImg.src = '';
        lightboxImg.style.width = '';
        lightboxImg.style.height = '';
        document.body.style.overflow = '';
        state.scale = 1;
        state.tx = 0;
        state.ty = 0;
        state.baseW = 0;
        state.baseH = 0;
        if (zoomLevel) zoomLevel.textContent = '100%';
    };

    // Re-ajustar al cambiar tamaño de viewport mientras está abierto
    window.addEventListener('resize', () => {
        if (lightbox.classList.contains('is-open')) fitImageToStage();
    });

    // Click en imagen del manual abre lightbox
    content.querySelectorAll('img.mn-help-img').forEach((img) => {
        img.addEventListener('click', () => {
            const fig = img.closest('figure');
            const cap = fig ? (fig.querySelector('figcaption')?.textContent || '').trim() : img.alt;
            openLightbox(img.src, cap);
        });
    });

    lightboxClose?.addEventListener('click', closeLightbox);

    // Cierre por click-fuera de imagen:
    // - target debe NO ser la imagen ni un descendiente de controles/close/caption
    // - distinguir click de drag: si el mouse se movió >5px entre mousedown y
    //   mouseup, fue pan, no click → no cerrar
    const CLICK_DRAG_THRESHOLD = 5;
    let mouseDownPos = null;

    const isInteractiveTarget = (el) => {
        if (!el) return false;
        return !!el.closest(
            '.mn-help-lightbox-img-wrap, ' +
            '.mn-help-lightbox-controls, ' +
            '.mn-help-lightbox-close'
        ) || el === lightboxImg;
    };

    lightbox?.addEventListener('mousedown', (ev) => {
        mouseDownPos = { x: ev.clientX, y: ev.clientY };
    });

    lightbox?.addEventListener('click', (ev) => {
        if (isInteractiveTarget(ev.target)) return;
        if (mouseDownPos) {
            const dx = ev.clientX - mouseDownPos.x;
            const dy = ev.clientY - mouseDownPos.y;
            mouseDownPos = null;
            if (Math.hypot(dx, dy) > CLICK_DRAG_THRESHOLD) return;
        }
        closeLightbox();
    });

    // ─── Botones de zoom ───────────────────────────────────────────────
    // Anchor en el centro de la imagen actualmente visible — no del stage.
    // Así al hacer zoom con botón la imagen no se desplaza fuera del viewport.
    const imageCenter = () => ({
        x: state.tx + (state.baseW * state.scale) / 2,
        y: state.ty + (state.baseH * state.scale) / 2,
    });

    zoomIn?.addEventListener('click', () => {
        const c = imageCenter();
        zoomAt(ZOOM_STEP, c.x, c.y);
    });
    zoomOut?.addEventListener('click', () => {
        const c = imageCenter();
        zoomAt(-ZOOM_STEP, c.x, c.y);
    });
    zoomReset?.addEventListener('click', resetTransform);

    // ─── Wheel zoom (zoom hacia el cursor) ─────────────────────────────
    stage?.addEventListener('wheel', (ev) => {
        if (!lightbox.classList.contains('is-open')) return;
        ev.preventDefault();
        const r = stage.getBoundingClientRect();
        const ax = ev.clientX - r.left;
        const ay = ev.clientY - r.top;
        const delta = -Math.sign(ev.deltaY) * ZOOM_STEP;
        zoomAt(delta, ax, ay);
    }, { passive: false });

    // ─── Drag para pan ─────────────────────────────────────────────────
    let dragging = false;
    let dragStart = { x: 0, y: 0, tx: 0, ty: 0 };

    const startDrag = (clientX, clientY) => {
        if (state.scale <= 1) return;  // no tiene sentido pan en 100%
        dragging = true;
        dragStart = { x: clientX, y: clientY, tx: state.tx, ty: state.ty };
        stage.classList.add('is-panning');
    };
    const moveDrag = (clientX, clientY) => {
        if (!dragging) return;
        state.tx = dragStart.tx + (clientX - dragStart.x);
        state.ty = dragStart.ty + (clientY - dragStart.y);
        applyTransform();
    };
    const endDrag = () => {
        dragging = false;
        stage.classList.remove('is-panning');
    };

    stage?.addEventListener('mousedown', (ev) => startDrag(ev.clientX, ev.clientY));
    window.addEventListener('mousemove', (ev) => moveDrag(ev.clientX, ev.clientY));
    window.addEventListener('mouseup', endDrag);

    // ─── Touch: pan con un dedo, pinch zoom con dos dedos ──────────────
    let pinchStartDist = 0;
    let pinchStartScale = 1;
    let pinchAnchor = { x: 0, y: 0 };

    const touchDist = (t1, t2) => Math.hypot(t1.clientX - t2.clientX, t1.clientY - t2.clientY);
    const touchMid = (t1, t2, rect) => ({
        x: (t1.clientX + t2.clientX) / 2 - rect.left,
        y: (t1.clientY + t2.clientY) / 2 - rect.top,
    });

    stage?.addEventListener('touchstart', (ev) => {
        if (ev.touches.length === 1) {
            startDrag(ev.touches[0].clientX, ev.touches[0].clientY);
        } else if (ev.touches.length === 2) {
            ev.preventDefault();
            endDrag();
            pinchStartDist = touchDist(ev.touches[0], ev.touches[1]);
            pinchStartScale = state.scale;
            pinchAnchor = touchMid(ev.touches[0], ev.touches[1], stage.getBoundingClientRect());
        }
    }, { passive: false });

    stage?.addEventListener('touchmove', (ev) => {
        if (ev.touches.length === 1 && dragging) {
            ev.preventDefault();
            moveDrag(ev.touches[0].clientX, ev.touches[0].clientY);
        } else if (ev.touches.length === 2) {
            ev.preventDefault();
            const d = touchDist(ev.touches[0], ev.touches[1]);
            if (pinchStartDist === 0) return;
            const targetScale = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, pinchStartScale * (d / pinchStartDist)));
            const delta = targetScale - state.scale;
            zoomAt(delta, pinchAnchor.x, pinchAnchor.y);
        }
    }, { passive: false });

    stage?.addEventListener('touchend', () => {
        endDrag();
        pinchStartDist = 0;
    });

    // ─── Doble click para alternar zoom 1x ↔ 2.5x en el punto ──────────
    stage?.addEventListener('dblclick', (ev) => {
        const r = stage.getBoundingClientRect();
        const ax = ev.clientX - r.left;
        const ay = ev.clientY - r.top;
        if (state.scale > 1.01) {
            resetTransform();
        } else {
            zoomAt(1.5, ax, ay);
        }
    });

    // ─── Atajos de teclado dentro del lightbox ─────────────────────────
    document.addEventListener('keydown', (ev) => {
        if (!lightbox.classList.contains('is-open')) return;
        if (ev.key === 'Escape') {
            closeLightbox();
        } else if (ev.key === '+' || ev.key === '=') {
            const c = imageCenter();
            zoomAt(ZOOM_STEP, c.x, c.y);
        } else if (ev.key === '-') {
            const c = imageCenter();
            zoomAt(-ZOOM_STEP, c.x, c.y);
        } else if (ev.key === '0') {
            resetTransform();
        }
    });

    // ────────────────────────────────────────────────────────────────────
    // Hash al cargar
    // ────────────────────────────────────────────────────────────────────
    if (window.location.hash) {
        const target = document.getElementById(window.location.hash.slice(1));
        if (target) {
            setTimeout(() => target.scrollIntoView({ behavior: 'instant', block: 'start' }), 50);
        }
    }
});
