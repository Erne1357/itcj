# AgendaTec — Catálogo de Componentes UI

Guía de referencia para el sistema de diseño de AgendaTec.
Onboarding objetivo: 10 minutos para un dev nuevo.

---

## 1. Tokens `--at-*`

Definidos en `base.css`. NUNCA hardcodear colores hex en archivos consumidores.
Usar siempre `var(--at-*)`.

### Colores

| Token | Valor | Uso típico |
|---|---|---|
| `--at-primary` | `#0d6efd` | Botones CTA, links, borde activo |
| `--at-primary-hover` | `#0a58ca` | Estado hover de botón primary |
| `--at-primary-50` | `#e7f1ff` | Fondo muy sutil azul |
| `--at-primary-100` | `#cfe2ff` | Fondo de slot seleccionado (self-hold) |
| `--at-primary-900` | `#052c65` | Texto sobre fondo primary |
| `--at-success` | `#198754` | Éxito, confirmación |
| `--at-success-bg` | `#d1e7dd` | Fondo de chip/badge success |
| `--at-warning` | `#ffc107` | Advertencia, pendientes |
| `--at-warning-bg` | `#ffe9b3` | Fondo de estado reservado |
| `--at-danger` | `#dc3545` | Error, acción destructiva |
| `--at-danger-bg` | `#f8d7da` | Fondo de no-show |
| `--at-info` | `#0dcaf0` | Información secundaria |
| `--at-surface` | `#ffffff` | Fondo de card/panel |
| `--at-surface-subtle` | `#f8f9fa` | Fondo de card header |
| `--at-surface-active` | `#f0f2f4` | Fondo activo/hover |
| `--at-text` | `#212529` | Texto principal |
| `--at-text-muted` | `#6c757d` | Texto secundario |
| `--at-text-disabled` | `#adb5bd` | Texto inactivo |
| `--at-border` | `#dee2e6` | Borde estándar |
| `--at-border-subtle` | `#eef0f2` | Borde sutil entre secciones |

### Tokens de slot (dominio AgendaTec)

| Token | Estado | Descripción |
|---|---|---|
| `--at-slot-available-*` | Libre | Sin reserva |
| `--at-slot-reserved-*` | Reservado | Hold por otro usuario (amarillo) |
| `--at-slot-held-self-*` | Seleccionado | Hold propio (azul) |
| `--at-slot-taken-*` | Atendida | Cita resuelta (verde) |
| `--at-slot-no-show-*` | No asistió | No-show / no resuelta (rojo) |
| `--at-slot-disabled-*` | No disponible | Deshabilitado (gris) |

Cada estado tiene `-bg`, `-border` y `-text`.

### Spacing

| Token | Valor | Aprox. |
|---|---|---|
| `--at-space-1` | `0.25rem` | 4px |
| `--at-space-2` | `0.5rem` | 8px |
| `--at-space-3` | `0.75rem` | 12px |
| `--at-space-4` | `1rem` | 16px |
| `--at-space-5` | `1.5rem` | 24px |
| `--at-space-6` | `2rem` | 32px |
| `--at-space-7` | `3rem` | 48px |

### Tipografía

| Token | Valor | Uso |
|---|---|---|
| `--at-text-xs` | `0.7rem` | Labels uppercase en KPIs |
| `--at-text-sm` | `0.75rem` | Badges, period-badge |
| `--at-text-base` | `0.875rem` | Cuerpo de tabla |
| `--at-text-md` | `1rem` | Texto de tarjeta |
| `--at-text-lg` | `1.125rem` | Subtítulos |
| `--at-text-xl` | `1.5rem` | Iconos grandes |
| `--at-text-2xl` | `1.8rem` | Valor de KPI |

### Motion

| Token | Valor | Uso |
|---|---|---|
| `--at-duration-fast` | `120ms` | Hover, focus |
| `--at-duration-base` | `180ms` | Fade-in de página, modales |
| `--at-duration-slow` | `280ms` | Transiciones largas |
| `--at-ease-out` | `cubic-bezier(0.16,1,0.3,1)` | Entrada de elementos |
| `--at-ease-standard` | `cubic-bezier(0.4,0,0.2,1)` | Transiciones de estado |

### Z-index

| Token | Valor | Uso |
|---|---|---|
| `--at-z-sticky` | `1020` | Navbar sticky |
| `--at-z-dropdown` | `1050` | Dropdowns |
| `--at-z-modal` | `1060` | Modales Bootstrap |
| `--at-z-toast` | `1080` | Toasts de Undo |

---

## 2. Componentes `.at-*`

Definidos en `components.css`. Conviven con Bootstrap sin sobreescribir sus clases.

### `.at-card`

Card unificada sin borde (usa sombra).

```html
<div class="at-card">
  <div class="card-body">
    <h5 class="card-title">Título</h5>
    <p>Contenido</p>
  </div>
</div>

<!-- Variante con borde -->
<div class="at-card at-card--bordered">...</div>

<!-- Variante con hover lift -->
<div class="at-card at-card--hover">...</div>
```

### `.at-card-header`

Header de card con fondo sutil.

```html
<div class="at-card">
  <div class="at-card-header">
    <h6 class="mb-0">Título del panel</h6>
  </div>
  <div class="card-body">...</div>
</div>
```

### `.at-kpi` / `.at-kpi__label` / `.at-kpi__value`

Tile de indicador clave.

```html
<div class="at-kpi at-kpi--accent">
  <div class="at-kpi__label">
    <i class="bi bi-calendar-check me-1" aria-hidden="true"></i> Citas
  </div>
  <div class="at-kpi__value" id="kpiValue">42</div>
</div>
```

Variantes de borde izquierdo: `.at-kpi--accent` (azul), `.at-kpi--success` (verde), `.at-kpi--warning` (amarillo).

### `.at-stat-label`

Alias de `.at-kpi__label` para etiquetas sueltas fuera de KPIs.

```html
<div class="at-stat-label">Horarios totales</div>
<div class="at-kpi__value" id="kpiTotal">—</div>
```

### `.at-period-badge`

Badge de período académico (nowrap + fuente pequeña).

```html
<div class="badge bg-primary px-2 py-1 at-period-badge" id="currentPeriod">
  <i class="bi bi-calendar3" aria-hidden="true"></i>
  <span id="periodName">Ene-Jun 2026</span>
</div>
```

### `.at-empty`

Estado vacío estandarizado: icono + título + mensaje + CTA opcional.

```html
<div class="at-empty">
  <div class="at-empty__icon" aria-hidden="true">
    <i class="bi bi-inbox"></i>
  </div>
  <p class="at-empty__title">Sin solicitudes</p>
  <p class="at-empty__message">No tienes solicitudes activas en este período.</p>
  <div class="at-empty__cta">
    <a href="/agendatec/student/request" class="btn btn-primary btn-sm">
      <i class="bi bi-plus-circle me-1" aria-hidden="true"></i> Crear solicitud
    </a>
  </div>
</div>
```

### `.at-skeleton`

Placeholder animado (shimmer) para estados de carga.

```html
<!-- Línea de texto -->
<span class="at-skeleton at-skeleton--line" style="width:70%"></span>

<!-- Título -->
<span class="at-skeleton at-skeleton--title"></span>

<!-- Fila de tabla (generada por JS) -->
<!-- Usar AgendaTec.Skeleton.tableRows(n, cols) en vez de HTML manual -->
```

### `.at-status-dot`

Indicador de conexión socket (verde/ámbar/rojo).

```html
<!-- Montado automáticamente por AgendaTec.SocketStatus.mount() -->
<!-- No instanciar manualmente en HTML -->
```

### `.at-icon-circle`

Círculo de icono con fondo semántico.

```html
<div class="at-icon-circle at-icon-circle--success" aria-hidden="true">
  <i class="bi bi-check-circle"></i>
</div>
<div class="at-icon-circle at-icon-circle--danger" aria-hidden="true">
  <i class="bi bi-calendar-x"></i>
</div>
<div class="at-icon-circle at-icon-circle--warning" aria-hidden="true">
  <i class="bi bi-calendar-event"></i>
</div>
```

Variantes: `--success`, `--danger`, `--info`, `--warning`, `--primary`.
Tamaños: sin modificador (3.5rem), `--sm` (2.5rem), `--lg` (4.5rem).

### `.at-icon-md` / `.at-icon-lg`

Sizing de icono en contexto inline.

```html
<i class="bi bi-person-badge at-icon-md" aria-hidden="true"></i>
```

### `.at-legend-dot`

Punto de leyenda (reemplaza divs 10x10 inline).

```html
<span class="at-legend-dot at-legend-dot--available" aria-hidden="true"></span> Libre
<span class="at-legend-dot at-legend-dot--reserved" aria-hidden="true"></span> Reservado
<span class="at-legend-dot at-legend-dot--held-self" aria-hidden="true"></span> Seleccionado
<span class="at-legend-dot at-legend-dot--taken" aria-hidden="true"></span> Atendida
<span class="at-legend-dot at-legend-dot--no-show" aria-hidden="true"></span> No asistió
<span class="at-legend-dot at-legend-dot--disabled" aria-hidden="true"></span> No disponible
```

### `.at-slot` — Chip de slot de horario

```html
<!-- Slot disponible -->
<button class="at-slot" aria-label="10:30 a 10:40 — disponible">10:30</button>

<!-- Slot con countdown visible -->
<button class="at-slot at-slot--held-self">
  10:30 <span class="at-slot__countdown">0:38</span>
</button>

<!-- Slot tomado (no clickeable) -->
<button class="at-slot at-slot--taken" disabled>10:40</button>
```

Estados: sin modifier (libre), `--reserved`, `--held-self`, `--taken`, `--no-show`, `--disabled`.

### `.at-sr-only`

Oculto visualmente, disponible para lectores de pantalla.

```html
<label class="at-sr-only" for="fltFrom">Desde</label>
<input id="fltFrom" type="date" ...>
```

### `.at-drag-handle`

Cursor grab para elementos arrastrables.

```html
<span class="at-drag-handle" draggable="true">
  <i class="bi bi-grip-vertical" aria-hidden="true"></i>
</span>
```

### `.at-log-output`

Preformatted output scrollable (encuestas).

```html
<pre class="at-log-output" aria-live="polite">Resultado aquí...</pre>
```

### `.at-scroll-md`

Scroll vertical con altura máxima.

```html
<div class="at-scroll-md">
  <!-- Lista larga -->
</div>
```

### `.at-period-divider`

Separador de período en listas cronológicas.

```html
<div class="at-period-divider">
  <span>Ene-Jun 2026</span>
  <span class="at-period-divider__badge">Activo</span>
</div>
<div class="at-period-divider at-period-divider--past">
  Ago-Dic 2025
</div>
```

### Clases de columna para `<th>`

```html
<th scope="col" class="at-col-actions">Acciones</th>     <!-- 120px -->
<th scope="col" class="at-col-actions-lg">Acciones</th>  <!-- 200px -->
<th scope="col" class="at-col-id">ID</th>                <!-- 80px -->
```

### Chart hosts

```html
<!-- Usar estas clases en el host del canvas (no inline styles) -->
<div class="at-chart-host">
  <canvas id="myChart"></canvas>
  <!-- JS agrega at-chart-host--empty cuando no hay datos -->
</div>
```

### `.at-toast-container`

Container de toast de Undo posicionado fijo.

```html
<!-- Generado por JS — no instanciar manualmente -->
<div class="position-fixed bottom-0 end-0 p-3 at-toast-container">...</div>
```

---

## 3. Helpers JS

Todos expuestos bajo `window.AgendaTec.*` via IIFEs en `static/js/shared/`.

### `AgendaTec.Format`

Definido en `format.js`.

```javascript
// Parsear fecha ISO sin desfase de timezone
AgendaTec.Format.parseISODate("2026-05-19")  // => Date

// Formatear día para selectores ("Lun 25 Ago")
AgendaTec.Format.formatDayLabel("2026-05-19")        // => "Lun 25 May"
AgendaTec.Format.formatDayLabelShort("2026-05-19")   // => "25 May"
AgendaTec.Format.formatDayLabelLong("2026-05-19")    // => "Martes 19 de Mayo"

// Formatear hora (recorta segundos)
AgendaTec.Format.formatTime("10:30:00")  // => "10:30"
AgendaTec.Format.formatTimeRange("10:30", "10:40")  // => "10:30 - 10:40"

// Escape HTML (siempre usar al insertar strings del server en innerHTML)
AgendaTec.Format.escapeHtml("<script>alert(1)</script>")  // => "&lt;script&gt;..."

// Debounce para eventos de socket o inputs
const onSearch = AgendaTec.Format.debounce(handleSearch, 300);
```

### `AgendaTec.Skeleton`

Definido en `skeleton.js`.

```javascript
// Filas de tabla con shimmer (para insertar en tbody durante fetch)
tbody.innerHTML = AgendaTec.Skeleton.tableRows(5, 4);
// Con columna de acciones al final:
tbody.innerHTML = AgendaTec.Skeleton.tableRows(5, 4, { withActions: true });

// Cards apilados
container.innerHTML = AgendaTec.Skeleton.cards(3);

// KPI tiles placeholder
kpisEl.innerHTML = AgendaTec.Skeleton.kpis(4);

// Línea simple
valueEl.innerHTML = AgendaTec.Skeleton.line("60%");
```

### `AgendaTec.TableCard`

Definido en `table-card.js`.

```javascript
// Sincronizar labels de columna a celdas (llamar post-render dinámico)
const table = document.querySelector("table[data-at-table='card']");
AgendaTec.TableCard.syncLabels(table);

// Auto-observar mutaciones en tbody (para tablas con actualización continua)
AgendaTec.TableCard.observe(table);
// Nota: autoInit() ya corre al DOMContentLoaded para todas las tablas marcadas.
// Solo llamar observe() manualmente para tablas creadas después del DOMContentLoaded.
```

### `AgendaTec.SocketStatus`

Definido en `socket-status.js`.

```javascript
// Montar indicador junto al anchor (ejecutar en DOMContentLoaded)
const indicator = AgendaTec.SocketStatus.mount({
  anchor: "#currentPeriod",   // selector o HTMLElement
  label: true,                // mostrar texto "Conectado" (default true)
  socket: window.__reqSocket  // opcional; auto-detecta __reqSocket si omite
});

// Control manual del estado (raramente necesario)
indicator.setState("connected");     // dot verde
indicator.setState("reconnecting");  // dot ámbar + pulse
indicator.setState("disconnected");  // dot rojo

// Desmontar si la página se destruye
indicator.destroy();
```

### `showToast(message, type)`

Función global definida en `toast.js` (cargada en `base.html`).

```javascript
showToast("Guardado correctamente", "success");
showToast("Error al conectar", "error");
showToast("Sin citas para hoy", "warning");
showToast("Cargando...", "info");
```

Tipos: `"success"`, `"error"` / `"danger"`, `"warning"`, `"info"`.

---

## 4. Patrón tabla → cards en mobile

### Marcado HTML

```html
<table class="table table-sm align-middle" data-at-table="card">
  <thead>
    <tr>
      <th scope="col" data-at-label="Nombre">Nombre</th>
      <th scope="col" data-at-label="Estado">Estado</th>
      <th scope="col" class="at-col-actions">Acciones</th>
    </tr>
  </thead>
  <tbody id="myTableBody">
    <!-- filas vía JS -->
  </tbody>
</table>
```

El atributo `data-at-label` en `<th>` es el label que aparece como prefijo en mobile.
Si el `<th>` no tiene `data-at-label`, se usa su `textContent`.
Columnas de acciones sin label: `data-at-label=""`.

### Sincronización post-render dinámico

```javascript
async function renderRows(items) {
  const tbody = document.getElementById("myTableBody");
  tbody.innerHTML = items.map(renderRow).join("");

  // Sincronizar labels para el modo card (SIEMPRE llamar post-render)
  const table = tbody.closest("table");
  if (table) AgendaTec.TableCard.syncLabels(table);
}
```

El `TableCard.observe()` se auto-ejecuta al DOMContentLoaded para tablas
ya en el DOM. Para tablas generadas después, llamar `observe()` manualmente.

### Comportamiento CSS en < 768px

- El `<thead>` se oculta.
- Cada `<tr>` se convierte en card con borde y sombra.
- Cada `<td>` muestra el label como prefijo (via `::before` con `content: attr(data-at-label)`).
- Celdas sin label (acciones) se alinean al final con borde superior sutil.

---

## 5. Animaciones

### `.at-fade-in`

Entrada de opacidad + translateY en 180ms. Aplicado automáticamente al `<main>`
por `page-enter.js` al DOMContentLoaded si el elemento aún no tiene la clase.

```html
<!-- En el wrapper del contenido de la página (opcional, page-enter.js lo hace) -->
<div class="at-fade-in row g-3">
  ...
</div>
```

### `.at-stagger`

Aplica fade-in con delay incremental a hijos directos (hasta 8 items).

```html
<div class="at-stagger" id="reminderList">
  <div>Item 1 (delay 30ms)</div>
  <div>Item 2 (delay 60ms)</div>
  <div>Item 3 (delay 90ms)</div>
</div>
```

### `.at-step-enter` / `.at-step-exit`

Transición horizontal entre steps del wizard (student/new_request).

### `prefers-reduced-motion`

`base.css` sobrescribe todas las duraciones a `0.01ms` cuando el usuario prefiere
movimiento reducido. Las animaciones usan CSS variables, por lo que el respect
es automático — no requiere lógica JS.

---

## 6. Convenciones obligatorias

1. **Nunca hardcodear hex** en archivos CSS consumidores. Usar `var(--at-*)`.
2. **Prefijo `at-`** para toda clase nueva del sistema de diseño.
3. **No override de clases Bootstrap** (p.ej., no redefinir `.btn`, `.card`, `.modal`).
4. **`aria-hidden="true"`** en todos los `<i class="bi ...">` decorativos.
5. **`scope="col"`** en todos los `<th>` de tablas de datos.
6. **`escapeHtml()`** siempre al insertar strings del servidor en `innerHTML`.
7. **`showToast()`** para feedback (nunca `alert()`).
8. **Skeleton antes de fetch** — insertar `AgendaTec.Skeleton.*` en el contenedor
   antes de la llamada async, no después.

---

## 7. Cómo extender el sistema de diseño

### Agregar token nuevo

1. Editar `base.css` dentro del bloque `:root { }`.
2. Seguir la convención `--at-{categoria}-{variante}`.
3. Bumpear `STATIC_VERSION` en `itcj2/config.py`.

```css
/* base.css */
:root {
  /* ... tokens existentes ... */

  /* Nuevo token de color para estado "en progreso" */
  --at-in-progress-bg:     #fff3cd;
  --at-in-progress-border: #ffc107;
  --at-in-progress-text:   #856404;
}
```

### Agregar componente nuevo

1. Editar `components.css` — agregar sección con comentario de bloque.
2. Consumir solo tokens `var(--at-*)`, sin valores hardcoded.
3. Bumpear `STATIC_VERSION`.

```css
/* components.css */

/* =============================================================================
   Mi componente nuevo
   ============================================================================= */
.at-mi-componente {
  background: var(--at-surface-subtle);
  border: 1px solid var(--at-border);
  border-radius: var(--at-radius-md);
  padding: var(--at-space-3) var(--at-space-4);
}
```

### Agregar variante semántica de componente existente

```css
/* Variante de kpi para estado "en progreso" */
.at-kpi--in-progress {
  border-left: 3px solid var(--at-in-progress-border);
}
```

### Bumpear STATIC_VERSION

Tras cualquier cambio en CSS o JS estáticos:

```bash
# Editar itcj2/config.py — incrementar STATIC_VERSION
STATIC_VERSION = "1.0.1111308"  # o el siguiente número
```

Esto invalida el cache de navegadores (el helper `sv()` en Jinja2 lo agrega
como query string `?v=` en cada `<link>` y `<script>`).
