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

- `.tt-table-wrap` — `overflow-x: auto` para tablas anchas (`titulatec.css:466-469`).
- `.tt-kanban` — ya trae su propio `overflow-x: auto` (`titulatec.css:510`).

Complementos verificables en la misma pasada:

- Ningún texto se corta ni se solapa (sin `overflow: hidden` que amputa contenido real).
- Los objetivos táctiles del alumno miden ≥ 40×40 px efectivos en viewport móvil.
- El drawer admin (`<992px`) abre, cierra y atrapa el foco; el contenido de debajo no hace scroll.
- Nada depende de `:hover` para ser alcanzable: el CSS ya aísla el hover con
  `@media (hover: hover) and (pointer: fine)` (`titulatec.css:103,267`) — respétalo.

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
| 1920 × 1080 | Monitor grande | El contenido se **centra con ancho cómodo**, no se estira de borde a borde |

---

## Estado actual (verificado 2026-09-01)

**Lo que ya está bien:**

- El alumno usa `.tt-shell` (`student/base_student.html:33`), que a `min-width: 992px` se convierte en
  rail lateral de 256px + `.tt-canvas-inner` centrado a 920px (1000px desde 1280px), con la shell
  limitada a 1180px (`titulatec.css:428-453`). Es un layout de escritorio propio, no un móvil estirado.
- El admin pasa el sidebar a drawer off-canvas + topbar con hamburguesa bajo 992px
  (`titulatec.css:471-489`), y `.tt-admin .main` lleva `min-width: 0`, que es lo que evita que un hijo
  ancho reviente el flex.
- El kanban tiene su propio scroll horizontal.

**Deuda conocida:**

1. **`.tt-mobile` (`titulatec.css:186-189`) es CSS muerto**: `max-width: 430px` y **cero** usos en
   templates o JS. Borrarlo — mientras exista, invita a que alguien lo aplique y produzca exactamente
   la columna angosta centrada que este contrato prohíbe.
2. **Tres tablas sin `.tt-table-wrap`**: `partials/import_preview.html` (la más ancha de la app: 6
   inputs por fila), `partials/appointments_calendar.html` y `partials/cohort_days_calendar.html`.
   Solo lo usan `admin/cohorts.html`, `admin/processes.html` y `partials/cohort_students_table.html`.
3. **Un solo breakpoint** (992px, más el ajuste de 1280 para el canvas del alumno). No hay nada
   pensado entre 360 y 992 (el rango de tablet y móvil grande) ni por encima de 1280.

---

## Al construir

1. Empieza por el viewport donde vive la audiencia de la vista, pero **no cierres la vista** sin
   abrirla en los seis tamaños.
2. Tabla ancha → envuélvela en `.tt-table-wrap`. Rejilla de ancho fijo (kanban, calendario) →
   dale su propio `overflow-x: auto`.
3. Contenedor flex cuyo hijo pueda ser ancho → `min-width: 0` en el hijo. Es la causa número uno de
   desbordes en flex, y ya está aplicado en `.tt-admin .main` y `.tt-main`.
4. En pantallas grandes, el contenido del alumno se **centra** con un ancho de lectura cómodo. No se
   estira. Las columnas se ganan (`.tt-dash-grid` a 2 columnas desde 992px), no se estiran.
5. Reutiliza las primitivas antes de escribir un `@media` nuevo. Un breakpoint nuevo es una decisión
   del design system, no un parche local.

## Al verificar

E2E: `tests/e2e/titulatec/responsive.spec.js` recorre la matriz de viewports contra la lista de vistas
de las dos audiencias y asserta el invariante duro. Una vista nueva se **añade a esa lista** en el
mismo commit que la crea. Es lo que convierte este documento en algo que no se erosiona.
