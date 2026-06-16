# Shell del alumno — convención de chrome (mobile-first, embebible)

> Toda vista nueva del alumno usa **este** shell. No reinventes appbar/nav ni vuelvas a
> centrar a 430px. Reutiliza tokens `--tt-*` y los componentes ya hechos. Trazabilidad y
> matriz de modos en [docs/flows/xcut_student_shell_embed.md](../flows/xcut_student_shell_embed.md).

## Regla de oro

Una vista del alumno **extiende `student/base_student.html`** (nunca `base.html` directo) y
solo llena bloques. El shell resuelve **standalone vs embebido** y **móvil vs desktop** sin que
la vista haga nada: misma plantilla para los tres modos.

```jinja
{% extends "titulatec/student/base_student.html" %}
{% block student_title %}Mi vista · TitulaTec{% endblock %}
{% block student_active %}docs{% endblock %}          {# home | docs | cita | perfil #}
{% block student_appbar_title %}Título corto{% endblock %}
{% block student_appbar_sub %}<div style="font-size:.75rem;color:var(--tt-mute)">Subtítulo</div>{% endblock %}
{% block student_appbar_left %}                         {# sub-página: chevron al dashboard #}
  <a href="/titulatec/student/dashboard" class="tt-iconbtn" aria-label="Volver"><i class="bi bi-chevron-left"></i></a>
{% endblock %}
{% block student_body %}
  <div class="p-3 p-lg-4"> … contenido … </div>
{% endblock %}
{% block student_scripts %}<script> … HTMX listeners … </script>{% endblock %}
```

## Qué da el shell (no lo repliques)

- **Appbar** sticky con safe-area. Slot izquierdo (`student_appbar_left`), título/subtítulo, hamburguesa.
- **Drawer** (móvil) y **rail** (desktop ≥992px) con la misma `student_nav` (macro en `_macros.html`),
  tematizados con `--app-primary*` (ink/ámbar). Footer con usuario + cerrar sesión.
- **Embebido** (`body.in-mobile-iframe`, lo pone `mobile-app-shell.js`): botón ← al shell en la raíz,
  Perfil oculto, FAB de notificaciones suprimido. Standalone: lo contrario.
- **Canvas** centrado en desktop (`.tt-canvas-inner`); usa `.tt-dash-grid` para 2 columnas donde aporte.
- Cerrar sesión (`[data-tt-logout]` / `#sidebarLogout`) ya cableado (postMessage al shell si embebido).

## Reglas

1. **No** pongas `.tt-bottomnav` ni un marco `.tt-mobile` propio. El bottomnav embebido lo da el shell.
2. **Raíz** del alumno (dashboard) → `student_appbar_left` con `#mobileBackToDashboard`. **Sub-páginas**
   → chevron a `/titulatec/student/dashboard`. Nunca los dos a la vez.
3. Nav nueva → edita `student_nav` (una sola fuente para drawer y rail). Item solo-standalone →
   clase `tt-standalone-only`.
4. Notificación in-app → `services/notify.notify_student(...)` (no toques el shell ni el FAB).
5. Animación/skeletons → primitivas existentes ([ui_motion.md](ui_motion.md)). Estado vacío → `.tt-empty`.
6. Al tocar CSS/JS, bumpear `STATIC_VERSION` en `itcj2/config.py` (gotcha #4).
