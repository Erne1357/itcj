/* ============================================================
   AgendaTec — Help page
   - Dynamic TOC + scroll-spy
   - Lightbox with zoom + pan
   ============================================================ */
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', () => {
    measureLayout();
    initToc();
    initLightbox();
    initHeroCollapse();
    initLayoutObservers();
    window.addEventListener('resize', measureLayout);
  });

  // ResizeObserver: actualiza --at-hero-h en cada frame de transición para
  // que el TOC siga al hero durante la animación de colapso/expansión.
  function initLayoutObservers() {
    const hero = document.querySelector('.at-help-hero');
    if (!hero || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => measureLayout());
    ro.observe(hero);
  }

  // === Hero collapse on stick =================================
  function initHeroCollapse() {
    const sentinel = document.querySelector('.at-help-sentinel');
    const hero = document.querySelector('.at-help-hero');
    if (!sentinel || !hero) return;

    const navbar = document.querySelector('nav.navbar.sticky-top');
    const navH = navbar ? navbar.offsetHeight : 56;

    // Cuando el sentinel sale del viewport por arriba, el hero ya está pegado.
    const observer = new IntersectionObserver(([entry]) => {
      const stuck = !entry.isIntersecting && entry.boundingClientRect.top < navH;
      hero.classList.toggle('is-compact', stuck);
      // Re-medir altura del hero al cambiar de modo para que TOC siga al hero.
      requestAnimationFrame(measureLayout);
    }, {
      root: null,
      // Margen negativo arriba = altura del navbar — dispara al pegarse.
      rootMargin: `-${navH}px 0px 0px 0px`,
      threshold: [0, 1],
    });

    observer.observe(sentinel);
  }

  // === Layout vars (navbar + hero heights) =================
  function measureLayout() {
    const shell = document.querySelector('.at-help-shell');
    const navbar = document.querySelector('nav.navbar.sticky-top');
    const hero = document.querySelector('.at-help-hero');
    if (!shell) return;
    if (navbar) {
      shell.style.setProperty('--at-navbar-h', navbar.offsetHeight + 'px');
    }
    if (hero) {
      shell.style.setProperty('--at-hero-h', hero.offsetHeight + 'px');
    }
  }

  // === TOC ===================================================
  function initToc() {
    const content = document.getElementById('atHelpContent');
    const tocList = document.getElementById('atHelpTocList');
    const toc = document.getElementById('atHelpToc');
    if (!content || !tocList || !toc) return;

    const sections = content.querySelectorAll('section.at-help-section[id]');
    if (!sections.length) {
      toc.style.display = 'none';
      return;
    }

    sections.forEach((sec) => {
      const titleEl = sec.querySelector('.at-help-section__title');
      const text = (titleEl?.dataset.tocLabel || titleEl?.textContent || sec.id)
        .replace(/\s+/g, ' ')
        .trim();
      const a = document.createElement('a');
      a.href = `#${sec.id}`;
      a.textContent = text;
      a.dataset.target = sec.id;
      tocList.appendChild(a);
    });

    // Scroll-spy
    const links = new Map();
    tocList.querySelectorAll('a').forEach((a) => links.set(a.dataset.target, a));

    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        const link = links.get(entry.target.id);
        if (!link) return;
        if (entry.isIntersecting) {
          tocList.querySelectorAll('a.is-active').forEach((el) => el.classList.remove('is-active'));
          link.classList.add('is-active');
        }
      });
    }, {
      rootMargin: '-140px 0px -55% 0px',
      threshold: 0.01,
    });

    sections.forEach((sec) => observer.observe(sec));

    // Click → smooth scroll + cierra accordion en mobile
    tocList.addEventListener('click', (e) => {
      const a = e.target.closest('a');
      if (!a) return;
      e.preventDefault();
      const target = document.getElementById(a.dataset.target);
      if (target) {
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
      if (window.matchMedia('(max-width: 991.98px)').matches) {
        toc.dataset.open = 'false';
      }
    });

    // Mobile toggle
    const toggle = document.getElementById('atHelpTocToggle');
    if (toggle) {
      toggle.addEventListener('click', () => {
        const isOpen = toc.dataset.open === 'true';
        toc.dataset.open = isOpen ? 'false' : 'true';
        toggle.setAttribute('aria-expanded', String(!isOpen));
      });
    }
  }

  // === Lightbox ==============================================
  function initLightbox() {
    const lightbox = document.getElementById('atHelpLightbox');
    const stage = document.getElementById('atHelpLightboxStage');
    const img = document.getElementById('atHelpLightboxImg');
    const caption = document.getElementById('atHelpLightboxCaption');
    const zoomLevel = document.getElementById('atHelpZoomLevel');
    const btnClose = document.getElementById('atHelpLightboxClose');
    const btnIn = document.getElementById('atHelpZoomIn');
    const btnOut = document.getElementById('atHelpZoomOut');
    const btnReset = document.getElementById('atHelpZoomReset');

    if (!lightbox || !stage || !img) return;

    const state = { scale: 1, tx: 0, ty: 0, baseW: 0, baseH: 0 };
    const MIN = 1;
    const MAX = 6;
    const STEP = 0.2;

    let dragging = false;
    let lastX = 0;
    let lastY = 0;

    const applyTransform = () => {
      img.style.transform = `translate(${state.tx}px, ${state.ty}px) scale(${state.scale})`;
      if (zoomLevel) zoomLevel.textContent = `${Math.round(state.scale * 100)}%`;
    };

    const clamp = () => {
      // Mantener parte de la imagen dentro del stage
      const stageRect = stage.getBoundingClientRect();
      const w = state.baseW * state.scale;
      const h = state.baseH * state.scale;
      const maxX = Math.max(0, (w - stageRect.width) / 2);
      const maxY = Math.max(0, (h - stageRect.height) / 2);
      state.tx = Math.min(maxX, Math.max(-maxX, state.tx));
      state.ty = Math.min(maxY, Math.max(-maxY, state.ty));
    };

    const fit = () => {
      const stageRect = stage.getBoundingClientRect();
      const ratio = Math.min(stageRect.width / img.naturalWidth, stageRect.height / img.naturalHeight, 1);
      state.baseW = img.naturalWidth * ratio;
      state.baseH = img.naturalHeight * ratio;
      img.style.width = `${state.baseW}px`;
      img.style.height = `${state.baseH}px`;
    };

    const open = (src, alt, captionText) => {
      img.src = src;
      img.alt = alt || '';
      caption.textContent = captionText || '';
      state.scale = 1;
      state.tx = 0;
      state.ty = 0;
      lightbox.classList.add('is-open');
      lightbox.setAttribute('aria-hidden', 'false');
      document.body.style.overflow = 'hidden';
      img.onload = () => {
        fit();
        applyTransform();
      };
      if (img.complete) {
        fit();
        applyTransform();
      }
    };

    const close = () => {
      lightbox.classList.remove('is-open');
      lightbox.setAttribute('aria-hidden', 'true');
      document.body.style.overflow = '';
    };

    const setScale = (next, originX, originY) => {
      const prev = state.scale;
      const target = Math.max(MIN, Math.min(MAX, next));
      if (target === prev) return;

      if (originX != null && originY != null) {
        // Mantener punto bajo cursor estable
        const rect = stage.getBoundingClientRect();
        const cx = originX - rect.left - rect.width / 2;
        const cy = originY - rect.top - rect.height / 2;
        const k = target / prev;
        state.tx = (state.tx - cx) * k + cx;
        state.ty = (state.ty - cy) * k + cy;
      }

      state.scale = target;
      clamp();
      applyTransform();
    };

    // Bind clicks on figures
    document.querySelectorAll('.at-help-img').forEach((el) => {
      el.addEventListener('click', () => {
        const figure = el.closest('figure');
        const cap = figure?.querySelector('figcaption')?.textContent || '';
        open(el.currentSrc || el.src, el.alt, cap);
      });
    });

    btnClose?.addEventListener('click', close);
    lightbox.addEventListener('click', (e) => {
      if (e.target === lightbox || e.target === stage) close();
    });

    document.addEventListener('keydown', (e) => {
      if (!lightbox.classList.contains('is-open')) return;
      if (e.key === 'Escape') close();
      if (e.key === '+' || e.key === '=') setScale(state.scale + STEP);
      if (e.key === '-' || e.key === '_') setScale(state.scale - STEP);
      if (e.key === '0') {
        state.scale = 1;
        state.tx = 0;
        state.ty = 0;
        applyTransform();
      }
    });

    btnIn?.addEventListener('click', () => setScale(state.scale + STEP));
    btnOut?.addEventListener('click', () => setScale(state.scale - STEP));
    btnReset?.addEventListener('click', () => {
      state.scale = 1;
      state.tx = 0;
      state.ty = 0;
      applyTransform();
    });

    // Wheel zoom
    stage.addEventListener('wheel', (e) => {
      e.preventDefault();
      const delta = e.deltaY > 0 ? -STEP : STEP;
      setScale(state.scale + delta, e.clientX, e.clientY);
    }, { passive: false });

    // Double-click toggle
    stage.addEventListener('dblclick', (e) => {
      if (state.scale === 1) {
        setScale(2.5, e.clientX, e.clientY);
      } else {
        state.scale = 1;
        state.tx = 0;
        state.ty = 0;
        applyTransform();
      }
    });

    // Drag to pan
    stage.addEventListener('mousedown', (e) => {
      if (state.scale <= 1) return;
      dragging = true;
      lastX = e.clientX;
      lastY = e.clientY;
      stage.style.cursor = 'grabbing';
    });

    window.addEventListener('mousemove', (e) => {
      if (!dragging) return;
      const dx = e.clientX - lastX;
      const dy = e.clientY - lastY;
      lastX = e.clientX;
      lastY = e.clientY;
      state.tx += dx;
      state.ty += dy;
      clamp();
      applyTransform();
    });

    window.addEventListener('mouseup', () => {
      dragging = false;
      stage.style.cursor = '';
    });

    // Touch pinch (basic)
    let touchStart = null;
    stage.addEventListener('touchstart', (e) => {
      if (e.touches.length === 2) {
        touchStart = {
          dist: Math.hypot(
            e.touches[0].clientX - e.touches[1].clientX,
            e.touches[0].clientY - e.touches[1].clientY,
          ),
          scale: state.scale,
        };
      } else if (e.touches.length === 1 && state.scale > 1) {
        touchStart = { x: e.touches[0].clientX, y: e.touches[0].clientY, panning: true };
      }
    }, { passive: true });

    stage.addEventListener('touchmove', (e) => {
      if (!touchStart) return;
      if (e.touches.length === 2 && 'dist' in touchStart) {
        const newDist = Math.hypot(
          e.touches[0].clientX - e.touches[1].clientX,
          e.touches[0].clientY - e.touches[1].clientY,
        );
        const ratio = newDist / touchStart.dist;
        setScale(touchStart.scale * ratio);
      } else if (e.touches.length === 1 && touchStart.panning) {
        const dx = e.touches[0].clientX - touchStart.x;
        const dy = e.touches[0].clientY - touchStart.y;
        touchStart.x = e.touches[0].clientX;
        touchStart.y = e.touches[0].clientY;
        state.tx += dx;
        state.ty += dy;
        clamp();
        applyTransform();
      }
    }, { passive: true });

    stage.addEventListener('touchend', (e) => {
      if (e.touches.length === 0) touchStart = null;
    });

    // Resize → re-fit
    window.addEventListener('resize', () => {
      if (lightbox.classList.contains('is-open')) {
        fit();
        clamp();
        applyTransform();
      }
    });
  }
})();
