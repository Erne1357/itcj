# UI · Movimiento, skeletons y micro-interacciones

> **Convención de la app.** Estas primitivas son del design system de TitulaTec.
> **Toda pestaña/vista nueva las reutiliza** (no se reinventan por página). Estilo:
> **sutil y profesional**. Definidas en `static/css/titulatec.css` (secciones MOTION /
> SKELETONS) + `static/js/shared/titulatec-utils.js`. Respetan `prefers-reduced-motion`.

## Curvas de easing (tokens)

Las easings nativas de CSS son flojas. Usa los tokens (filosofía de Emil Kowalski):

| Token | Valor | Para |
|---|---|---|
| `--tt-ease-out` | `cubic-bezier(0.23,1,0.32,1)` | Entradas/salidas y micro-interacciones UI (lo normal). |
| `--tt-ease-in-out` | `cubic-bezier(0.77,0,0.175,1)` | Movimiento/morph en pantalla. |
| `--tt-ease-drawer` | `cubic-bezier(0.32,0.72,0,1)` | Tipo iOS (drawers). |

Reglas: **nunca `ease-in`** en UI (se siente lento); **nunca `transition: all`** (propiedad
exacta); animar solo `transform`/`opacity`; duraciones **< 300ms** (press 100–160ms, dropdown
150–250ms); **nunca desde `scale(0)`** (parte de `.96`–`.98` + opacidad).

## Qué hay disponible

| Primitiva | Cómo se usa | Notas |
|---|---|---|
| **Entrada de página** | clase `tt-anim-in` en el contenedor | En admin ya viene **gratis**: `base_admin.html` envuelve `admin_main` en `tt-anim-in`. En vistas de alumno, añádela al bloque principal. |
| **Entrada de parciales HTMX** | **automática, pero solo si cambió de vista** | `titulatec-utils.js` re-dispara `tt-anim-in` en el destino de cada `htmx:afterSwap` **salvo** que el destino declare `data-tt-view` y su valor sea el mismo antes y después del swap. Ver «La puerta `data-tt-view`». |
| **Entrada de un ítem concreto** | clase `tt-enter` (la pone JS, no la escribas en el template) | Fundido de opacidad de .18 s para la fila/tarjeta que **realmente** acaba de aparecer. `processes.js` la aplica comparando ids antes/después del swap. Sin desplazamiento, sin stagger, sin salida. |
| **Stagger en listas** | clase `tt-stagger` en el contenedor | Sus hijos directos entran escalonados (delays .03–.30s). Para listas/tarjetas. |
| **Indicador de carga** | `.tt-ind-host` en el contenedor + `.tt-ind tt-ind--overlay htmx-indicator` en el indicador, referenciado por `hx-indicator="#id"` | Aparece **solo** si la petición supera `--tt-ind-delay` (300 ms), y aun entonces **reserva 0 px**: es overlay. Ver «El indicador de carga». |
| **Skeleton** | macro `skel_rows(n)` / `skel_card()` / `skel_line(w)` | Placeholder para una región que **nace vacía** y se puebla por HTMX. Para una región que ya tiene contenido y solo se recarga, el indicador correcto es el overlay de arriba, no un esqueleto. Hoy **ningún template lo usa**. |
| **Botón ocupado** | **automático** | El emisor recibe `.htmx-request`. `pointer-events:none` es **inmediato** (defensa anti doble-clic); el spinner y el atenuado esperan a `--tt-ind-delay`. |
| **Hover lift** | clase `tt-hover-lift` | Eleva tarjetas/filas al cursor. **Gateado tras `@media (hover:hover) and (pointer:fine)`** → sin falso hover pegado en touch (alumno). Tablas: `table-hover` de Bootstrap. |
| **Press (feedback al tacto)** | automático en `.btn`, `a.tt-card`, filas `a.tt-hover-lift`, bottomnav | `:active` escala sutil (`.97`/`.985`/`.92`). `scale()` también escala el contenido. Para otros elementos clicables, añade `tt-pressable`. |
| **Toast** | `TitulaTecUtils.showToast` | Entra/sale desde el borde derecho (consistencia espacial) con `--tt-ease-out`, transición (no keyframes) → interrumpible al apilar. |
| **Modal de confirmación** | `TitulaTecUtils.confirmDialog` | Centrado (origin center), escala desde `.96` + opacidad, `--tt-ease-out` ~220ms. |

## La puerta `data-tt-view` (si algo no cambia, que no se mueva)

Decision del usuario (2026-09-02): *«si el contenido de la petición no cambia, aun así recarga
todo con las animaciones y se ve raro que se muevan cosas sin haber cambiado nada»*.

`titulatec-utils.js` compara el atributo `data-tt-view` del destino **antes y después** del swap:

| Antes | Después | Qué pasa |
|---|---|---|
| `processes` | `processes` | **no** se re-anima (filtro de la propia página) |
| `documents` | `processes` | se re-anima (cambio de pestaña) |
| ausente | cualquiera | se re-anima — comportamiento histórico intacto |

- En admin lo declara cada plantilla con `{% block admin_view %}nombre{% endblock %}`;
  `base_admin.html` lo escribe en `#tt-admin-content`. **Una pestaña nueva que no lo declare se
  re-animará en cada swap**: es el fallback, no un error, pero decláralo.
- Con `morph:outerHTML` Idiomorph conserva el nodo y le sincroniza los atributos, así que la
  comparación es de verdad vista-contra-vista.
- Con `innerHTML` el destino no se reemplaza y su `data-tt-view` no cambia nunca: ponerlo ahí
  significa, a propósito, «esta región no re-anima» (así está `#docs-body`).
- **Un valor CONSTANTE dice lo mismo con `morph:outerHTML`.** Es lo que hace `#appt-shell`
  (`appointments-shell`): la agenda de Citas se re-swappea entera en cada interacción —calendario,
  día, alumno, filtros— y ninguna de esas es un cambio de vista. El shell nunca se re-anima; lo que
  se anima es la zona que de verdad cambió, con `data-tt-fade-key` (abajo).

Cuando el listado sí cambia, lo que se anima es **solo lo que entró**: quien reconstruya una lista
por HTMX debe dar **id estable** a cada ítem (`id="proc-row-{{ r.id }}"`) para que Idiomorph
reutilice los supervivientes y el JS pueda marcar los nuevos con `tt-enter`.

### `data-tt-fade-key` — cuando la región no es una lista

`tt-enter` por ids sirve para listas: hay ítems y se comparan. Para una región que **no** es una
lista (un calendario, un panel de detalle, una barra lateral) hace falta decir de otra forma «esto
es otro contenido». Eso es `data-tt-fade-key`: una clave de contenido en el elemento, que el JS
compara antes/después del swap y, si cambió, marca con `.tt-enter` (solo opacidad, .18 s).

```html
<section id="appt-agenda"  data-tt-fade-key="{{ zone }}|{{ day }}|{{ cal.month_value }}">…</section>
<aside   id="appt-pending" data-tt-fade-key="pending:{{ pending_count }}">…</aside>
<section id="appt-detail"  data-tt-fade-key="detail:{{ detail.process.id }}">…</section>
```

Reglas: el elemento **necesita `id`** (es la identidad con la que se busca su clave previa), y la
clave debe contener **todo lo que cambia el contenido y nada más** — meterle un contador que sube
solo haría animar en cada swap, que es el defecto que esto viene a arreglar. Lo implementa
`static/js/admin/appointments.js`; medido en Chromium 149: pulsar al alumno que ya está abierto da
**0 animaciones y 16/16 los mismos nodos**, y navegar de mes anima **una sola** región
(`appt-agenda`) mientras «Por agendar» se queda con el mismo nodo y se mueve **0 px**.

## El indicador de carga

Son **dos** problemas distintos y hacen falta las dos mitades:

1. **que no aparezca cuando no hace falta** → el retardo `--tt-ind-delay`;
2. **que cuando aparezca no empuje nada** → el overlay `tt-ind--overlay`.

Medido en Chromium 149 antes de arreglarlo (900 ms de latencia artificial sobre las peticiones
reales de la app):

| Vista | Antes | Después |
|---|---|---|
| Documentos, petición de ~160 ms | el skeleton vivía 150–192 ms y reservaba 24 px | **no aparece**, 0 px |
| Documentos, petición de +900 ms | aparecía a +331 ms y reservaba 24 px · CLS 0.024 | aparece a +341 ms · **0 px · CLS 0** |
| Citas, petición de ~86 ms | igual, con 341.8 px de esqueleto | **no aparece**, 0 px |
| Citas, petición de +900 ms | aparecía a +339 ms y empujaba 341.8 px · **CLS 0.318** | aparece a +345 ms · **0 px · CLS 0** |
| Citas (shell nuevo), +900 ms | — | aparece a **+373 ms**, vive 711 ms · **CLS 0** |

### Mitad 1 · el retardo

Una petición de la red local se resuelve en 60–190 ms. Enseñar el indicador al instante producía un
parpadeo (aparece y desaparece). Ahora nada aparece antes de `--tt-ind-delay`.

| Token | Valor | Para |
|---|---|---|
| `--tt-ind-delay` | `300ms` | cuánto tarda un indicador en aparecer |
| `--tt-ind-fade` | `160ms` | cuánto dura su fundido de entrada |

**Por qué esto lleva JS y no es CSS puro.** Para no reservar alto, un indicador oculto tiene que
estar en `display: none`; y un elemento en `display: none` tiene **terminadas** sus animaciones
(CSS Animations 1), así que una animación retrasada nunca llega a devolverlo a `block`. Medido en
Chromium 149: con ese enfoque el indicador se quedaba oculto para siempre. La puerta es por tanto
una clase, `.tt-ind-on`, que `titulatec-utils.js` añade a todo lo que lleve `.htmx-request` cuando
vence el retardo y retira al terminar la petición. **El CSS solo mira `.tt-ind-on`.**

Consecuencias que hay que conocer:

- El único botón HTMX del alumno (`student/documents.html`, envío de fase 1) tarda ahora 300 ms en
  mostrar su spinner. Es lo buscado, no un bug.
- `--tt-ind-delay` es la **fuente única**: el JS lo lee del `:root`. Cambiar el token mueve las dos
  mitades a la vez.
- El retardo solo evita que aparezca sin necesidad; que no reserve alto **cuando por fin aparece**
  lo resuelve la segunda mitad.

### Mitad 2 · el overlay

El indicador vive **fuera del flujo**, así que ocupa 0 px pase lo que pase con su contenido, y de
paso vela la región rancia mientras llega la nueva (y la hace no-pulsable, que es lo correcto: esos
datos ya no valen).

```html
<div class="tt-ind-host">                              <!-- ancla de posicionamiento -->
  <div id="mi-skel" class="tt-ind tt-ind--overlay htmx-indicator"
       role="status" aria-live="polite">
    <span class="tt-ind-badge"><span class="tt-spinner"></span>Cargando…</span>
  </div>
  <div id="mi-body">{% include "..._body.html" %}</div> <!-- la región que recarga -->
</div>
```

- **`.tt-ind-host` es obligatorio**: sin un ancestro posicionado, el `inset: 0` se resuelve contra
  un contenedor ajeno. Envuélvelo alrededor de **exactamente** lo que se queda rancio.
- **Con `morph:outerHTML` el host y el indicador tienen que quedar FUERA del nodo que se
  reemplaza.** Si el host entra al swap se pierde el ancla de posicionamiento a media petición; si
  entra el indicador, se destruye estando visible. En Citas el host envuelve `#appt-skel` +
  `#appt-shell`, y el swap sustituye solo el segundo: verificado en navegador con 900 ms de
  latencia — tras el swap el indicador sigue vivo, sigue dentro del host y sigue fuera del shell.
  (En Documentos la barra de filtros vive dentro del parcial que se reemplaza, así que entra en el
  velo: es consecuencia del markup de esa vista, no de la primitiva.)
- **Nada de `style=` inline en el indicador**: gana al fundido de `--tt-ind-fade`.
- El distintivo (`.tt-ind-badge`) sirve para **cualquier** forma de región —tabla, kanban,
  calendario, dos columnas—, que es justo lo que un esqueleto no puede hacer. Es `sticky`, así que
  sigue a la vista si la región es más alta que la ventana.
- Lo fija `tests/fastapi/titulatec/test_documents_inbox.py`, que barre las plantillas y exige el
  contrato (overlay + host + sin `style` + `hx-indicator` con destino real).

## Ejemplo · región que recarga por HTMX

El markup del host y del overlay está arriba («Mitad 2»). Lo que falta es el disparador:

```html
{# el control que dispara la recarga apunta el indicador #}
<select hx-get="/..." hx-target="#mi-body" hx-indicator="#mi-skel">...</select>
```

Sin `hx-indicator` el emisor se marca a sí mismo (`.htmx-request`) y solo se ve el spinner del
botón; con él, además, se vela la región. Las dos cosas pasan por el mismo retardo.

## Checklist al crear una pestaña nueva

- [ ] Contenedor con `tt-anim-in` (admin: gratis vía `base_admin`; alumno: añadir).
- [ ] **`{% block admin_view %}`** declarado en la plantilla admin (si no, la vista se re-anima en
      cada filtro).
- [ ] **Id estable en cada ítem** de una lista que se reconstruya por HTMX (`proc-row-{id}`), para
      que el morph reutilice los supervivientes.
- [ ] Región que se re-swappea entera y **no** es una lista → `data-tt-fade-key` con la clave de su
      contenido, y `data-tt-view` CONSTANTE en el shell para que no se re-anime completo.
- [ ] Listas/tarjetas en grid → `tt-stagger` (+ `tt-hover-lift` en ítems clicables).
- [ ] Regiones que recargan por HTMX → `.tt-ind-host` + indicador `tt-ind--overlay` +
      `hx-indicator`. Sale gratis con retardo y con 0 px de salto: no lo escondas tú a mano ni le
      pongas `style=`.
- [ ] Botones de acción async → nada que hacer (spinner automático, y ya retrasado).
- [ ] No agregues animaciones one-off: si falta una primitiva, **añádela aquí** y reúsala.

## Referencias

- CSS: `static/css/titulatec.css` → secciones `MOTION / ANIMACIÓN`, `SKELETONS`, `MENOS MOVIMIENTO`.
- JS: `static/js/shared/titulatec-utils.js` → puerta `data-tt-view` (`htmx:beforeSwap`/`afterSwap`) y puerta de indicadores `.tt-ind-on` (`htmx:beforeRequest`/`afterRequest`).
- JS: `static/js/admin/processes.js` → marcado de `tt-enter` sobre lo realmente nuevo (por ids).
- JS: `static/js/admin/appointments.js` → `data-tt-fade-key` (por clave de contenido) + visor y
  modal de Citas.
- CSS: `static/css/titulatec.css` → bloque «INDICADOR DE CARGA COMO OVERLAY» (`tt-ind-host`,
  `tt-ind--overlay`, `tt-ind-badge`).
- Tests: `tests/fastapi/titulatec/test_documents_inbox.py` → contrato de markup del indicador.
- Macros: `templates/titulatec/_macros.html` → `skel_line`, `skel_card`, `skel_rows`.
- Versionado: al tocar CSS/JS, **bumpea `STATIC_VERSION`** en `itcj2/config.py` (gotcha #4) o el `?v` no cambia y el browser sirve caché vieja.
