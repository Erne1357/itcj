/**
 * desktop-grid.js — iconos del escritorio.
 *
 * Los tiles los pinta el servidor en su lugar final (CSS grid): aquí solo va el
 * comportamiento, con delegación en `#desktop-grid` (un listener por tipo de
 * evento, nunca re-agregados). Clic selecciona; doble clic o Enter abre; con
 * el dedo (pointerType touch) abre con un toque. La Papelera solo se selecciona.
 */
(function () {
  'use strict';

  const D = window.ItcjDesktop = window.ItcjDesktop || {};

  class DesktopGrid {
    constructor(opts) {
      this.wm = (opts && opts.wm) || D.wm;
      this.grid = document.getElementById('desktop-grid');
      this.lastPointerType = 'mouse';
      if (this.grid) this._bind();
    }

    _tile(target) {
      const tile = target && target.closest ? target.closest('.desktop-icon[data-app]') : null;
      return tile && this.grid.contains(tile) ? tile : null;
    }

    select(tile) {
      this.grid.querySelectorAll('.desktop-icon.selected').forEach((t) => {
        if (t !== tile) {
          t.classList.remove('selected');
          t.removeAttribute('aria-pressed');
        }
      });
      if (tile) {
        tile.classList.add('selected');
        tile.setAttribute('aria-pressed', 'true');
      }
    }

    openTile(tile) {
      const key = tile && tile.dataset.app;
      if (!key || key === 'papelera' || tile.classList.contains('is-decorative')) return;
      if (window.desktop && typeof window.desktop.openApplication === 'function') {
        window.desktop.openApplication(key);
      } else if (this.wm) {
        this.wm.open(key);
      }
    }

    _bind() {
      this.grid.addEventListener('pointerdown', (e) => { this.lastPointerType = e.pointerType || 'mouse'; });

      this.grid.addEventListener('click', (e) => {
        const tile = this._tile(e.target);
        this.select(tile);
        if (tile && this.lastPointerType === 'touch') this.openTile(tile);
      });

      this.grid.addEventListener('dblclick', (e) => {
        const tile = this._tile(e.target);
        if (!tile) return;
        e.preventDefault();
        if (this.lastPointerType !== 'touch') this.openTile(tile);   // con el dedo ya abrió el primer toque
      });

      this.grid.addEventListener('keydown', (e) => {
        const tile = this._tile(e.target);
        if (!tile) return;
        if (e.key === 'Enter') {
          e.preventDefault();
          this.select(tile);
          this.openTile(tile);
        } else if (e.key === ' ') {
          e.preventDefault();
          this.select(tile);
        }
      });

      this.grid.addEventListener('focusin', (e) => {
        const tile = this._tile(e.target);
        if (tile) this.select(tile);
      });

      // Arrastrar una imagen del tile no debe "sacarla" del escritorio.
      this.grid.addEventListener('dragstart', (e) => e.preventDefault());
    }
  }

  D.DesktopGrid = DesktopGrid;
})();
