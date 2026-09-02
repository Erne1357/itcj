# Contrato responsive de TitulaTec

> Regla del proyecto, no una preferencia estética. **Toda vista nueva o modificada de TitulaTec
> cumple este contrato antes de darse por hecha.** Complementa
> [`student_shell.md`](student_shell.md) (chrome del alumno) y [`ui_motion.md`](ui_motion.md).

## Las dos audiencias

| | Alumno | Administrativos (Servicios Escolares / Titulaciones) |
|---|---|---|
| Diseño base | **Mobile-first**: el CSS sin media query es el móvil | **Desktop-first en densidad**: tablas, master-detail, kanban |
| Obligación en la otra punta | **Debe verse bien en escritorio**, con layout propio — no un móvil estirado ni una columna angosta centrada en una pantalla vacía | **Debe funcionar en móvil y tablet**: drawer, apilado, scroll contenido |
| Uso real | El teléfono es el dispositivo principal; el escritorio pasa (laboratorio, casa) | El escritorio es el principal; el teléfono pasa (ventanilla, revisión sobre la marcha) |

Ninguna de las dos puede romperse en la punta que "no es la suya". Que una audiencia sea
secundaria en un tamaño **no la exime**: la exime de estar *optimizada*, no de ser *usable*.

---

## Invariante duro (esto es lo que se prueba)

En **toda** vista, en **todo** viewport de la matriz de abajo:

```js
document.documentElement.scrollWidth <= window.innerWidth   // el BODY nunca hace scroll horizontal
```

Si un contenido es legítimamente más ancho que la pantalla (tabla de muchas columnas, calendario
mensual, tablero kanban), **el scroll horizontal vive dentro de ese contenedor**, nunca en la página.
El patrón ya existe en el design system:

- `.tt-table-wrap` — `overflow-x: auto` para tablas anchas (`titulatec.css:501-502`).
- `.tt-kanban` — ya trae su propio `overflow-x: auto` (`titulatec.css:543`).

Complementos verificables en la misma pasada:

- Ningún texto se corta ni se solapa (sin `overflow: hidden` que amputa contenido real).
- Los objetivos táctiles del alumno miden ≥ 40×40 px efectivos en viewport móvil.
- El drawer admin (`<992px`) abre, cierra y atrapa el foco; el contenido de debajo no hace scroll.
- Nada depende de `:hover` para ser alcanzable: el CSS ya aísla el hover con
  `@media (hover: hover) and (pointer: fine)` (`titulatec.css:107,272,597,781`) — respétalo.

---

## Matriz de viewports

Se prueban **seis**. Los tres primeros son obligatorios para vistas de alumno; los tres últimos para
vistas admin; **ambas audiencias se prueban en los seis** (esa es justo la parte que se salta y la
que produce las regresiones).

| Viewport | Perfil | Qué debe pasar |
|---|---|---|
| 360 × 740 | Móvil chico (el peor caso real) | Alumno: layout base. Admin: drawer + tablas con scroll propio |
| 390 × 844 | Móvil de referencia | Igual |
| 768 × 1024 | Tablet vertical | Todavía **bajo** el breakpoint de 992: admin sigue en drawer |
| 1280 × 800 | Laptop | Alumno: rail + canvas. Admin: sidebar fijo + contenido |
| 1440 × 900 | Escritorio común | Sin franjas muertas ni contenido estirado a lo bruto |
| 1920 × 1080 | Monitor grande | **Alumno: la caja ocupa la ventana entera** (rail pegado al borde), y lo que se topa es la **prosa** (~70ch). Admin: `#tt-admin-content` sigue centrado a 1240px |

---

## Estado actual (verificado 2026-09-01)

**Lo que ya está bien:**

- El alumno usa `.tt-shell` (`student/base_student.html:33`), que a `min-width: 992px` se convierte en
  rail lateral de 256px + canvas **a pantalla completa** (`titulatec.css:441-486`, los tres bloques
  992 · 1280 · 1600). Es un layout de escritorio propio, no un móvil estirado.
- El admin pasa el sidebar a drawer off-canvas + topbar con hamburguesa bajo 992px
  (`titulatec.css:504`, bloque `@media (max-width: 991.98px)`), y `.tt-admin .main` lleva
  `min-width: 0`, que es lo que evita que un hijo ancho reviente el flex.
- El kanban tiene su propio scroll horizontal.

**Saldado el 2026-09-01** (auditoría de 156 combinaciones vista x viewport, 25 vistas):

- El invariante duro **se cumple en las 156**: 0 desbordes de página. Los 5 que había estaban todos en
  admin a 360/390 (`div.ms-auto` de la barra de filtros de procesos, `div.text-end` del detalle) y su
  causa raíz era `.min-w-0`, una clase escrita en **14 templates que no existía en ningún lado** — la
  regla 3 de este documento como clase fantasma. Ahora existe, y esos contenedores llevan `flex-wrap`.
- **`.tt-mobile` eliminado.** Era `max-width: 430px` con cero usos (solo la usa
  `design_handoff_titulatec/`, que tiene su propia copia de este CSS).
- **Seis primitivas del design system se usaban sin tener una sola regla CSS**: `tt-kpis`/`tt-kpi`,
  `tt-funnel`, `tt-tabs`, `tt-search`, `tt-doc-stage`, más `tt-progress`, `tt-table-cards`,
  `tt-pill--idle-*`, `col-scroll` y `health`. Se notaba sobre todo **en pantalla grande**, donde los
  KPIs debían desplegarse en horizontal y salían como enlaces azules apilados en la esquina. Escritas.
- **Nuevo breakpoint de 1280 para admin**: `#tt-admin-content` se limita a 1240px y se centra. Antes no
  existía equivalente admin de `.tt-canvas-inner` y el contenido se estiraba de borde a borde.
- **`.tt-table-cards`**: el markup móvil (con `data-label` por celda) ya estaba escrito en 2 templates y
  la regla nunca; los nombres se cortaban a media palabra. Escrita bajo 768px.
- **`.tt-pane`** sustituye los `style="max-width:520px"` inline, que además no centraban.

**Cambio de contrato del 2026-09-02 — el alumno a pantalla completa:**

Hasta esta fecha este documento decía, para 1920, que el contenido *"se **centra con ancho cómodo**,
no se estira"*. **Ya no.** Decisión del usuario: a 1920 la shell topada a 1180px dejaba ~370px de
franja muerta a cada lado, y eso se leía como una app rota, no como respiro.

| | Antes | Ahora |
|---|---|---|
| `.tt-shell` (≥992) | `max-width: 1180px; margin: 0 auto` | `max-width: none` — el rail queda pegado al borde izquierdo |
| `.tt-canvas-inner` | `max-width: 920px` (1000px ≥1280) centrado | sin tope; `padding-inline: clamp(20px, 2.4vw, 44px)` — el gutter **crece con la ventana** en vez de convertirse en franja muerta |
| Tope de lectura | implícito (lo daba la caja) | **explícito**: `.tt-prose { max-width: 70ch }` + `.tt-stu .tt-canvas-inner p` lo hereda ≥992px |

El matiz importa: **estirar la caja sin topar el párrafo produce líneas de ~200 caracteres**, que es
ilegible. El tope se mueve de la caja a la prosa, no desaparece. Medido a 1920: ventana 1920 · rail
256 · canvas 1664 · columnas 755+755 · **párrafo 639px**.

**Breakpoint nuevo: 1600px (alumno).** Es una decisión del design system, no un parche local (regla 5
de "Al construir"), y por eso está documentada aquí. A pantalla completa, la rejilla `1.05fr / .95fr`
dejaba la columna A en ~810px para un contenido cuya prosa se topa a ~590px: media tarjeta vacía.
Desde 1600px las dos columnas valen lo mismo (`1fr / 1fr`), el gutter sube a 32px y el padding del
canvas a `clamp(36px, 3.2vw, 76px)`: el aire se reparte **fuera** de las tarjetas. Breakpoints del
alumno hoy: **992 · 1280 · 1600**. El admin conserva el suyo (1280, `#tt-admin-content` a 1240px):
ahí la audiencia y el problema son otros — densidad de tabla, no lectura.

**Verificado en navegador (2026-09-02)**: 30 combinaciones (5 vistas de alumno × los 6 viewports),
0 desbordes; y el caso **embebido** (iframe del shell mobile del core) a 390/1440/1920, también sin
desbordes, con `body.in-mobile-iframe` puesto, Perfil oculto y FAB suprimido.

**Deuda que queda:**

1. **Tres tablas sin `.tt-table-wrap`**: `partials/import_preview.html` (la más ancha de la app: 6
   inputs por fila), `partials/appointments_calendar.html` y `partials/cohort_days_calendar.html`.
   Hoy no desbordan, pero dependen de que su contenido no crezca.
2. **Nada pensado entre 768 y 992** (el rango de tablet apaisada y móvil grande): ahí el admin sigue en
   drawer y el alumno en columna, sin layout propio.
3. **El FAB de notificaciones del alumno** se pinta con `#0F172A`, el mismo `--tt-ink` de `.tt-btn-ink`,
   y se superpone al CTA en `student_formato_b`. Requiere decisión de diseño (recolorear, o mover la
   campana al appbar en standalone y eliminar el FAB).

---

## Al construir

1. Empieza por el viewport donde vive la audiencia de la vista, pero **no cierres la vista** sin
   abrirla en los seis tamaños.
2. Tabla ancha → envuélvela en `.tt-table-wrap`. Rejilla de ancho fijo (kanban, calendario) →
   dale su propio `overflow-x: auto`.
3. Contenedor flex cuyo hijo pueda ser ancho → `min-width: 0` en el hijo. Es la causa número uno de
   desbordes en flex, y ya está aplicado en `.tt-admin .main` y `.tt-main`.
4. En pantallas grandes, el alumno ocupa **toda la ventana**: la caja no se topa, la **prosa** sí
   (`.tt-prose`, ~70ch; dentro del canvas del alumno los `p` lo heredan). Las columnas se ganan
   (`.tt-dash-grid` a 2 columnas desde 992px, iguales desde 1600px), no se estiran. Si una tarjeta
   queda medio vacía en 1920, el arreglo es repartir el gutter o ganar una columna, **no** volver a
   centrar la caja.
5. Reutiliza las primitivas antes de escribir un `@media` nuevo. Un breakpoint nuevo es una decisión
   del design system, no un parche local.

## Al verificar

> **Corregido el 2026-09-02.** Hasta hoy esta sección decía que
> `tests/e2e/titulatec/responsive.spec.js` recorría la matriz y asertaba el invariante. **Ese
> archivo no existe** — `tests/e2e/` tiene `core/`, `helpdesk/` y `agendatec/`, no `titulatec/`.
> El documento se estaba apoyando en una red que nunca se tendió, que es la peor forma de
> erosionarse: la de creer que algo está cubierto. Esto es lo que hay de verdad.

**Hoy (manual).** El invariante se comprueba a mano con Playwright contra el entorno de dev,
recorriendo la matriz de seis viewports y evaluando `document.documentElement.scrollWidth <=
window.innerWidth` en cada vista. Es lo que se hizo el 2026-09-01 (156 combinaciones, admin +
alumno) y el 2026-09-02 (30 del alumno + el caso embebido). **Manual significa que caduca**: vale
para el commit en el que se corrió y para ninguno más.

**Lo que sí está automatizado** son las anclas y las reglas que no necesitan navegador, en
`tests/fastapi/titulatec/`:

| Qué fija | Dónde |
|---|---|
| `main[data-tt-page]` presente en cada vista de alumno | `test_student_dashboard_html.py` |
| `#tt-fase-actual`, `[data-tt-cta]`, `#tt-acc-btn-N` / `#tt-acc-panel-N` | idem |
| Que ninguna fase que no toca ofrezca una acción, en las 9 posiciones | idem |
| Que el swap admin no duplique `#tt-admin-content` | `test_admin_nav_swap.py` |

Sin esas anclas el E2E no tendría a qué agarrarse, así que el trabajo previo ya está hecho.

**Lo que falta (deuda declarada, no una promesa del documento).** Escribir
`tests/e2e/titulatec/responsive.spec.js`: matriz de seis viewports × lista de vistas de las dos
audiencias, un assert del invariante duro por combinación. El patrón de autenticación ya está
resuelto en `tests/e2e/helpdesk/` (se acuña el JWT **dentro** del contenedor con
`docker exec` y se pone la cookie `itcj_token`); Playwright ya vive en `tests/e2e/node_modules`.
Mientras ese archivo no exista, **el que toca una vista es quien la abre en los seis tamaños** — y
esta sección no puede decir lo contrario.
