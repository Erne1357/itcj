# UI · Movimiento, skeletons y micro-interacciones

> **Convención de la app.** Estas primitivas son del design system de TitulaTec.
> **Toda pestaña/vista nueva las reutiliza** (no se reinventan por página). Estilo:
> **sutil y profesional**. Definidas en `static/css/titulatec.css` (secciones MOTION /
> SKELETONS) + `static/js/shared/titulatec-utils.js`. Respetan `prefers-reduced-motion`.

## Qué hay disponible

| Primitiva | Cómo se usa | Notas |
|---|---|---|
| **Entrada de página** | clase `tt-anim-in` en el contenedor | En admin ya viene **gratis**: `base_admin.html` envuelve `admin_main` en `tt-anim-in`. En vistas de alumno, añádela al bloque principal. |
| **Entrada de parciales HTMX** | **automática** | `titulatec-utils.js` re-dispara `tt-anim-in` en el destino de cada `htmx:afterSwap`. No hay que hacer nada. |
| **Stagger en listas** | clase `tt-stagger` en el contenedor | Sus hijos directos entran escalonados (delays .03–.30s). Para listas/tarjetas. |
| **Skeleton de carga** | macro `skel_rows(n)` / `skel_card()` / `skel_line(w)` dentro de un `id` con clase `htmx-indicator`, referenciado por `hx-indicator="#id"` | Visible **solo** durante la petición HTMX. Ver ejemplo abajo. |
| **Botón ocupado** | **automático** | El emisor de una petición HTMX recibe `.htmx-request`; CSS añade spinner + `pointer-events:none` a `button`/`.btn`. Evita doble click sin JS. |
| **Hover lift** | clase `tt-hover-lift` | Eleva/realza tarjetas y filas de lista al pasar el cursor. (Tablas: usa `table-hover` de Bootstrap.) |
| **Press** | automático en `.btn` | `:active` baja 1px. |

## Ejemplo · skeleton para una región que recarga por HTMX

```html
{% from "titulatec/_macros.html" import skel_rows %}

{# indicador: visible solo mientras dura la petición #}
<div id="mi-skel" class="htmx-indicator">{{ skel_rows(5) }}</div>

{# región que se reemplaza #}
<div id="mi-body">{% include "..._body.html" %}</div>

{# el control que dispara la recarga apunta el indicador #}
<select hx-get="/..." hx-target="#mi-body" hx-indicator="#mi-skel">...</select>
```

## Checklist al crear una pestaña nueva

- [ ] Contenedor con `tt-anim-in` (admin: gratis vía `base_admin`; alumno: añadir).
- [ ] Listas/tarjetas en grid → `tt-stagger` (+ `tt-hover-lift` en ítems clicables).
- [ ] Regiones que cargan/recargan por HTMX → skeleton (`skel_rows`) + `hx-indicator`.
- [ ] Botones de acción async → nada que hacer (spinner automático por `.htmx-request`).
- [ ] No agregues animaciones one-off: si falta una primitiva, **añádela aquí** y reúsala.

## Referencias

- CSS: `static/css/titulatec.css` → secciones `MOTION / ANIMACIÓN`, `SKELETONS`, `MENOS MOVIMIENTO`.
- JS: `static/js/shared/titulatec-utils.js` → listener `htmx:afterSwap`.
- Macros: `templates/titulatec/_macros.html` → `skel_line`, `skel_card`, `skel_rows`.
- Versionado: al tocar CSS/JS, **bumpea `STATIC_VERSION`** en `itcj2/config.py` (gotcha #4) o el `?v` no cambia y el browser sirve caché vieja.
