"""Contexto compartido de las páginas de *trabajo* de Calidad.

"Trabajo" = incidencias, eventos de programa, sus tareas y la pantalla de
asignación de responsables. Son las seis páginas que en el legacy vivían en
``routes/pages/incidents.py`` y ``routes/pages/programs.py`` y que compartían el
90 % del contexto (categorías, áreas, procesos y usuarios) copiado y pegado
cinco veces con criterios distintos: unas rutas filtraban ``is_active=True`` y
otras no, y todas mandaban ``User.query.all()`` a la plantilla para que Jinja
armara ``<option>`` **como HTML crudo dentro de un template literal**
(``htmlUsers``), que era el peor de los siete vectores de XSS del frontend.

Aquí ese contexto se calcula **una sola vez**, se devuelve como estructuras de
datos planas y viaja al navegador dentro del bloque ``page_data_script()``
(``|tojson``), nunca como markup.

Desde B4 hay una séptima página y un tercer padre para
:func:`tasks_page_context`: ``/adhoc/documentos/{id}/tareas``
(``pages/documents.py``), que el legacy nunca tuvo. Vive aquí y no en su módulo
por lo mismo que las otras dos: es el MISMO template.

Este módulo **no expone ``router``** a propósito: no es un módulo de páginas,
es la capa de contexto que consumen ``pages/incidents.py``,
``pages/programs.py`` y ``pages/documents.py``. La fase de cableado no tiene que
incluirlo.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy.orm import Session

from itcj2.apps.adhoc.utils.constants import (
    APP_KEY,
    PRIORITIES,
    TASK_STATUS_COMPLETED,
    TASK_STATUSES,
)

logger = logging.getLogger(__name__)

__all__ = [
    "APP_KEY",
    "TASK_WRITE_PERMS",
    "TASK_UNFINISHED_STATUSES",
    "TASKS_PAGE_PERM",
    "columns_without_tasks",
    "catalog_options",
    "assignable_users",
    "picker_users",
    "granted",
    "page_context",
    "parent_folio",
    "tasks_page_context",
    "task_assignee_ids",
    "task_notified_ids",
    "safe_return_to",
]

#: Permisos de escritura de la pantalla de tareas. Solo ocultan botones: el gate
#: real vive en ``require_perms`` de ``/api/adhoc/v2/tasks``.
TASK_WRITE_PERMS = (
    "adhoc.tasks.api.create",
    "adhoc.tasks.api.update",
    "adhoc.tasks.api.delete",
    "adhoc.tasks.api.assign",
)

#: Estados en los que la tarea **todavía espera a alguien**. Es el criterio de
#: ruido del aviso de atasco (B5): una tarea que ya se terminó no está atascada
#: aunque su responsable ya no entre a Calidad —está hecha—, y marcarla
#: bloqueada sería mentir sobre trabajo cerrado. Medido contra la base real:
#: 684 tareas, 453 ``'Completada'``; de esas, 184 tienen hoy algún responsable
#: sin acceso. Sin este filtro el aviso saldría en 273 filas y las 57 que de
#: verdad están paradas se perderían dentro.
#:
#: Se deriva del vocabulario (:data:`TASK_STATUSES` menos el único estado
#: terminal, :data:`TASK_STATUS_COMPLETED`) y no se escribe a mano: es la misma
#: fuente que llena el ``<select>`` de estatus de esta pantalla, así que un
#: estado nuevo entra en los dos sitios a la vez.
#:
#: ⚠️ **No es :data:`TASK_OPEN_STATUSES`**, y la diferencia importa: aquella son
#: las tareas abiertas *para su ejecutor* (``Pendiente``, ``Rechazada``,
#: ``En Proceso``) y es el filtro del tablero del dashboard. Deja fuera
#: ``En Revisión`` y ``En Espera``, que son exactamente los dos estados de las
#: tareas de un flujo documental —la tarea 683 del documento 202, la que
#: destapó todo esto, está ``'En Revisión'``—. Cablear aquella aquí apagaría el
#: aviso justo donde nació.
TASK_UNFINISHED_STATUSES: tuple[str, ...] = tuple(
    estado for estado in TASK_STATUSES if estado != TASK_STATUS_COMPLETED
)

#: Permiso de la PÁGINA de tareas. No es de escritura y por eso no está en
#: :data:`TASK_WRITE_PERMS`: aquí sirve de gate del botón "Tareas" de la fila,
#: cuyo destino (``/adhoc/{incidencias|programas}/{id}/tareas``) sí lo exige.
TASKS_PAGE_PERM = "adhoc.tasks.page.list"

#: Tope de usuarios que se serializan al ``page_data``. El picker filtra en
#: cliente, así que la lista entera viaja en el HTML; sin tope, una plantilla de
#: 8 000 usuarios pesaría megas. El SGC trabaja con la plantilla administrativa,
#: no con el alumnado, así que 500 sobra de largo.
MAX_USERS = 500


# ==========================================================================
# Catálogos
# ==========================================================================

def _named_rows(rows: Iterable[Any]) -> list[dict]:
    """``[{'id': …, 'name': …, 'color': …}]`` — solo campos serializables."""
    out: list[dict] = []
    for row in rows or []:
        item = {"id": row.id, "name": row.name}
        color = getattr(row, "color", None)
        if color:
            item["color"] = color
        out.append(item)
    return out


def catalog_options(db: Session, *, category_model: str) -> dict[str, list[dict]]:
    """Categorías + áreas + procesos, listos para los ``<select>``.

    ``category_model`` es el nombre de la clase del catálogo de categorías del
    dominio (``AdhocIncidentCategory`` o ``AdhocProgramCategory``): es lo único
    que cambia entre incidencias y eventos de programa.

    Las **áreas se filtran a las activas** (``is_active=True``). En el legacy la
    columna era nullable y las rutas de página mandaban ``Area.query.all()`` sin
    filtro mientras la API sí filtraba, así que un área dada de baja seguía
    ofreciéndose en el formulario.
    """
    from itcj2.apps.adhoc import models as adhoc_models
    from itcj2.apps.adhoc.services.catalog_service import AdhocCatalogService

    categories = AdhocCatalogService.list_items(db, getattr(adhoc_models, category_model))
    areas = AdhocCatalogService.list_items(db, adhoc_models.AdhocArea, is_active=True)
    processes = AdhocCatalogService.list_items(db, adhoc_models.AdhocProcess)

    return {
        "categories": _named_rows(categories),
        "areas": _named_rows(areas),
        "processes": _named_rows(processes),
    }


# ==========================================================================
# Usuarios asignables
# ==========================================================================

def _picker_rows(db: Session, criterios: Sequence[Any], *,
                 limite: Optional[int] = None) -> list[dict]:
    """Usuarios con la forma que consume ``shared/user-picker.js``.

    ``criterios`` es lo ÚNICO que separa a los dos conjuntos que la pantalla de
    asignación maneja: quién puede ser responsable hoy (:func:`assignable_users`)
    y quién ya lo es sin poder serlo (:func:`picker_users`). El resto —el nombre
    compuesto, el puesto vigente, el departamento y la deduplicación del join—
    sale de aquí para los dos, y tiene que salir del mismo sitio: si al usuario
    marcado "sin acceso" se le resolviera el nombre con otra query, la única
    ficha de la lista que exige una decisión sería también la que se ve
    distinta.
    """
    from itcj2.core.models.department import Department
    from itcj2.core.models.position import Position, UserPosition
    from itcj2.core.models.user import User

    rows = (
        db.query(
            User.id,
            User.first_name,
            User.last_name,
            User.middle_name,
            User.email,
            Position.title.label("position_title"),
            Department.name.label("department_name"),
        )
        .outerjoin(
            UserPosition,
            (UserPosition.user_id == User.id) & (UserPosition.is_active.is_(True)),
        )
        .outerjoin(
            Position,
            (Position.id == UserPosition.position_id) & (Position.is_active.is_(True)),
        )
        .outerjoin(Department, Department.id == Position.department_id)
        .filter(*criterios)
        .order_by(User.last_name.asc(), User.first_name.asc(), User.id.asc())
        .all()
    )

    out: list[dict] = []
    seen: set[int] = set()
    for row in rows:
        # Un usuario con dos puestos vigentes aparece dos veces en el join.
        if row.id in seen:
            continue
        seen.add(row.id)
        nombre = " ".join(
            part for part in (row.first_name, row.last_name, row.middle_name) if part
        ).strip()
        out.append({
            "id": row.id,
            "full_name": nombre or f"#{row.id}",
            "email": row.email,
            "position": row.position_title,
            "department": row.department_name,
        })
        if limite is not None and len(out) >= limite:
            break
    return out


def assignable_users(db: Session) -> list[dict]:
    """Usuarios que pueden ser responsables o validadores dentro de Calidad.

    El criterio es **el mismo que deja entrar a la app**
    (``users_with_assignment_select``, las cuatro vías de ``require_app``:
    rol o permiso directo, rol o permiso heredado de un puesto vigente), no
    ``User.query.all()`` como hacía el legacy — que ofrecía los ~20 000 usuarios
    del padrón, alumnado incluido, para ser responsable de una incidencia del
    SGC.

    No se usa ``UserAdminService.list_users`` aquí a propósito: aquella solo ve
    los accesos **directos** (``core_user_app_roles``) porque su pantalla
    escribe en esa tabla, y dejaría fuera a quien entra por puesto.

    Devuelve dicts planos con la forma que consume ``shared/user-picker.js``
    (``id``, ``full_name``, ``email``, ``position``, ``department``).
    """
    from itcj2.core.models.user import User
    from itcj2.core.services.authz_service import users_with_assignment_select

    return _picker_rows(
        db,
        (
            User.is_active.is_(True),
            User.id.in_(users_with_assignment_select(db, APP_KEY)),
        ),
        limite=MAX_USERS,
    )


def picker_users(db: Session,
                 selected_ids: Optional[Sequence[int]] = None) -> list[dict]:
    """Lo asignable **más** lo ya asignado que dejó de serlo, marcado.

    Las dos listas de la pantalla de asignación —a quién se puede marcar y a
    quién ya está marcado— salen del MISMO criterio de acceso, y esa es
    justamente la razón por la que se cruzan mal: al responsable que perdió el
    acceso lo excluye ``assignable_users`` por el mismo motivo por el que el
    aviso de atasco lo señala en la pantalla anterior. El picker no lo
    encontraba en ``users`` y caía a su respaldo, así que el supervisor que
    acababa de leer un nombre en la fila "Bloqueada" llegaba aquí y veía la
    ficha ``#24055``: un número, sin nombre ni departamento, en la pantalla que
    el propio aviso le decía que usara para arreglarlo. Y como
    ``getSelection()`` no distingue una ficha de otra, marcar un sustituto y
    guardar mandaba ``user_ids: [24055, nuevo]`` — la tarea volvía con el aviso
    puesto, degradado a "1 de los 2 responsables no puede entrar".

    Aquí los dos conjuntos los concilia el servidor, que es quien conoce los
    dos: los seleccionados que ``assignable_users`` no trae se resuelven con su
    nombre real y viajan con ``without_access: True``. El JS **no vuelve a
    decidir** quién tiene acceso: pinta la marca que recibe, y con ella quitar a
    esa persona pasa a ser una acción evidente en vez de un descubrimiento.

    Van al PRINCIPIO de la lista a propósito. La lista está ordenada por
    apellido y se recorre buscando a quien añadir; el que ya no puede entrar no
    se busca —se retira—, así que es lo único de esta pantalla que pide una
    decisión antes de cualquier otra cosa.

    No se les aplica el tope de ``MAX_USERS``: ese límite es de cuánto se
    serializa al HTML, no una regla de acceso, y son como mucho tantos como
    responsables tenga la tarea.
    """
    from itcj2.core.models.user import User

    asignables = assignable_users(db)
    conocidos = {fila["id"] for fila in asignables}
    faltantes = [
        uid for uid in dict.fromkeys(selected_ids or []) if uid not in conocidos
    ]
    if not faltantes:
        return asignables

    por_id = {fila["id"]: fila for fila in _picker_rows(db, (User.id.in_(faltantes),))}
    extras: list[dict] = []
    for uid in faltantes:
        # Un id sin fila en `core_users` no debería existir (la asociación es
        # FK), pero si existiera, la ficha con su número es mejor que perderlo
        # en silencio de la selección al guardar.
        fila = por_id.get(uid) or {
            "id": uid, "full_name": f"#{uid}", "email": None,
            "position": None, "department": None,
        }
        fila["without_access"] = True
        extras.append(fila)
    return extras + asignables


# ==========================================================================
# Permisos (solo para ocultar botones)
# ==========================================================================

def granted(db: Session, user: Optional[dict], codes: Sequence[str]) -> dict[str, bool]:
    """``{code: bool}`` para los permisos de *escritura* de una pantalla.

    Sirve **solo para ocultar botones**: el gate real lo ponen
    ``require_page_app`` en la página y ``require_perms`` en la API. Un fallo al
    calcular permisos devuelve todo en ``False`` (fail-closed): enseñar un botón
    que después responde 403 es peor que no enseñarlo.

    El admin global del JWT (``role == "admin"``) ve todos los botones, igual
    que ``require_perms`` lo deja pasar por diseño.
    """
    codigos = list(codes or [])
    if not user:
        return {code: False for code in codigos}
    if user.get("role") == "admin":
        return {code: True for code in codigos}

    from itcj2.core.services.authz_cache import cached_perms

    try:
        efectivos = cached_perms(db, int(user["sub"]), APP_KEY)
    except Exception as exc:  # pragma: no cover — depende del estado de la BD
        logger.warning("adhoc: no se pudieron calcular permisos de UI (%s)", exc)
        return {code: False for code in codigos}

    return {code: code in efectivos for code in codigos}


def columns_without_tasks(columns: Sequence[dict], *, can_open: bool) -> list[dict]:
    """Las columnas de la tabla de trabajo, sin la de "Tareas" si no se abre.

    ``pages/documents.py`` cierra el mismo callejón emitiendo ``tasks_url`` solo
    con permiso, y con eso basta allí porque ``documents-panel.js`` pinta el
    botón dentro de un ``if (this.tasksUrl)``. Aquí no: en las dos listas de
    trabajo "Tareas" es una COLUMNA entera y ``work/work-items.js`` la rellena
    siempre (``renderCell`` → ``tasksButton``), así que apagar solo la URL
    dejaría el icono en las 25 filas de la página y el clic no haría nada
    —``goToTasks`` sale sin navegar—. Un botón mudo no es mejor que uno que
    lleva a la pantalla de prohibido: en los dos casos el usuario se queda
    esperando algo que no va a pasar.

    El JS lee las claves de columna del ``<thead>`` (``readColumns``), que se
    pinta desde esta misma lista, así que quitarla aquí quita encabezado, fila
    de filtros y celda a la vez, sin tocar el módulo.
    """
    return [col for col in columns if can_open or col.get("key") != "tasks"]


# ==========================================================================
# Identidad del expediente
# ==========================================================================

def parent_folio(parent: Any, parent_type: str) -> Optional[str]:
    """Cómo se identifica el expediente en la cabecera de sus tareas.

    Incidencia y evento de programa tienen una columna ``folio`` y se devuelve
    tal cual (nullable: ``adhoc/work/tasks.html`` ya cae al título con
    ``parent.folio or parent.title``).

    **Un documento no tiene folio.** Tiene ``code`` —nullable— y ``version``, y
    su identidad en el SGC son los dos juntos: ``code`` nombra la *cadena* de
    versiones y el flujo de aprobación corre sobre **una** de ellas. El caso que
    destapó esto es el documento 202: código ``052``, versión ``4.0``, y hay dos
    documentos más con el mismo ``052`` (v2.0 y v3.0, ya obsoletos). Una
    cabecera que dijera solo "052" nombraría igual las tres pantallas de tareas.
    Se pinta ``"052 v4.0"``, con el mismo token ``v{version}`` que ya usan las
    dos listas de documentos y el historial de versiones.

    Sin ``code`` se emite ``"Sin código v4.0"`` y no ``None``: dejar caer el
    fallback del template pondría el título del documento en el hueco del folio
    **y** en el subtítulo, repetido, y de paso perdería la versión, que es el
    único dato que aquí sí distingue un expediente de otro. "Sin código" es la
    misma palabra que ya usa ``documents-panel.js`` cuando le falta el código.
    Hoy los 203 documentos traen código, así que es una rama defensiva —pero la
    columna es nullable y el alta no lo exige, así que puede darse mañana.

    Se resuelve aquí y no en la ruta llamante para que las tres pantallas de
    tareas sigan compartiendo un solo contexto, que es la razón de ser de este
    módulo.
    """
    if parent_type != "document":
        return getattr(parent, "folio", None)

    codigo = (getattr(parent, "code", None) or "").strip() or "Sin código"
    version = (getattr(parent, "version", None) or "").strip()
    return f"{codigo} v{version}" if version else codigo


# ==========================================================================
# Contexto base de página
# ==========================================================================

def page_context(db: Session, user: Optional[dict], **extra: Any) -> dict:
    """Contexto mínimo que TODA página de esta sección debe pasar a ``render_adhoc``.

    Hoy es el ``nav`` filtrado por permisos (regla 6 de las de templates), más
    lo que aporte cada página. Existe para que añadir algo transversal al shell
    no obligue a tocar las siete páginas.
    """
    from itcj2.apps.adhoc.pages.nav import nav_for_user

    ctx: dict = {"nav": nav_for_user(db, user), "today": date.today().isoformat()}
    ctx.update(extra)
    return ctx


def tasks_page_context(
    db: Session,
    user: Optional[dict],
    *,
    parent: Any,
    parent_type: str,
    back_url: str,
    parent_label: str,
) -> dict:
    """Contexto de ``adhoc/work/tasks.html`` — **idéntico para los tres padres**.

    En el legacy los dos consumidores del mismo template pasaban contextos
    distintos: la ruta de programas añadía un ``notified_map`` que la plantilla
    nunca leía, y la de incidencias no lo pasaba. Aquí hay una sola función, así
    que las pantallas no pueden divergir.

    El tercer padre es el **documento** (``/adhoc/documentos/{id}/tareas``), que
    hasta hoy no tenía pantalla: las tareas de aprobación de un documento solo
    se veían en el tablero personal de cada validador, así que nadie podía mirar
    el avance del flujo ni destrabar un paso cuyos asignados ya no entran a la
    app. Dos cosas suyas se resuelven aquí para no partir el contexto en dos:

    * su identidad no es un ``folio`` sino ``code`` + ``version``
      (:func:`parent_folio`), y
    * es el único de los tres cuyas tareas pertenecen a un **paso** del flujo,
      de donde sale ``show_step_column``.

    El aviso de atasco (``show_access_warning`` y sus dos reglas) sale también
    de aquí, y por eso lo ven las tres pantallas: ver el comentario del
    ``page_data``.
    """
    permisos = granted(db, user, TASK_WRITE_PERMS)
    folio = parent_folio(parent, parent_type)

    page_data = {
        "statuses": list(TASK_STATUSES),
        "priorities": list(PRIORITIES),
        "parent_type": parent_type,
        "parent_id": parent.id,
        "parent_title": parent.title,
        "parent_folio": folio,
        "parent_status": parent.status,
        "api": "/api/adhoc/v2/tasks",
        "table_id": "adhoc-table-tasks",
        "assign_url": "/adhoc/asignaciones",
        "back_url": back_url,
        "users": assignable_users(db),
        # Bandera explícita, no un `parent_type === 'document'` suelto repetido
        # en la plantilla y en el JS: la columna "Paso" existe porque SOLO las
        # tareas de documento cuelgan de un `flow_step` (`AdhocTask.flow_step`;
        # `serialize_task` emite `flow_step: null` para las otras dos). Quién
        # pinta la columna lo decide el servidor una vez, igual que quién puede
        # leer el hilo o quién tiene acceso a la app: la regla se escribe una
        # sola vez y la UI la obedece.
        "show_step_column": parent_type == "document",
        # Aviso de atasco: la tarea cuyos responsables ya no pueden entrar a
        # Calidad no la puede atender nadie. B4 lo encendió solo en la pantalla
        # de documento con un `parent_type === 'document'` escrito en el JS;
        # aquí pasa a ser lo que dice el servidor, y lo dice para las TRES: el
        # atasco no es un problema del ciclo documental, es de la tarea. Las
        # paradas de verdad son 57 —43 de incidencia, 13 de programa, 1 de
        # documento— y 56 de ellas viven justo en las dos pantallas que hasta
        # hoy se callaban.
        #
        # QUIÉN no tiene acceso lo dice cada fila del API
        # (`assignees_without_access`, con `users_with_assignment_select`); esto
        # son las dos reglas que deciden CUÁNDO esa lista significa algo:
        #
        #  · `unfinished_statuses` — el criterio de ruido. Solo una tarea que
        #    sigue esperando a alguien puede estar atascada (ver
        #    `TASK_UNFINISHED_STATUSES`).
        #  · `all_assignees_required` — si perder a ALGUNOS ya la para. En un
        #    documento sí: el paso solo avanza cuando aprueban todos los
        #    asignados (`task_workflow_service._record_decision` cuenta contra
        #    `len(assignees)`). En una incidencia o un evento **no**: cualquiera
        #    de sus responsables puede terminarla o cerrarla él solo (rama A de
        #    `workflow_action`), así que mientras quede uno operativo la tarea
        #    no está parada y pintarla en ámbar afirmaría algo falso — son 32
        #    filas hoy. Ahí el aviso se reserva al caso en que no queda ninguno.
        #
        # Las dos van en el `page_data` y no en el JS por lo mismo que
        # `show_step_column`: son reglas de negocio, y el sitio donde ya viven
        # el vocabulario de estados y la máquina de flujo es el servidor.
        "show_access_warning": True,
        "unfinished_statuses": list(TASK_UNFINISHED_STATUSES),
        "all_assignees_required": parent_type == "document",
        "can": {
            "create": permisos["adhoc.tasks.api.create"],
            "update": permisos["adhoc.tasks.api.update"],
            "delete": permisos["adhoc.tasks.api.delete"],
            "assign": permisos["adhoc.tasks.api.assign"],
        },
        "labels": {"parent": parent_label},
    }

    articulo = "la" if parent_label.endswith("a") else "el"

    return {
        **page_context(db, user),
        "page_data": page_data,
        "page_title": f"Tareas de {articulo} {parent_label}",
        "parent": {
            "id": parent.id,
            "folio": folio,
            "title": parent.title,
            "status": parent.status,
        },
        "parent_type": parent_type,
        "parent_label": parent_label,
        "back_url": back_url,
        # Las dos banderas que la PLANTILLA lee con `{% if %}` se repiten aquí
        # arriba por comodidad de Jinja, pero derivadas de `page_data`, nunca
        # recalculadas: un `{% if %}` que dijera una cosa y el JS otra es
        # exactamente la divergencia que este módulo existe para impedir.
        "can_create": page_data["can"]["create"],
        "show_step_column": page_data["show_step_column"],
    }


# ==========================================================================
# Selección actual de la pantalla de asignación
# ==========================================================================

def task_assignee_ids(db: Session, task_id: int) -> list[int]:
    """Ids de los responsables actuales de la tarea, en orden estable."""
    from itcj2.apps.adhoc.models import adhoc_task_assignees

    rows = db.execute(
        adhoc_task_assignees.select()
        .where(adhoc_task_assignees.c.task_id == task_id)
        .order_by(adhoc_task_assignees.c.user_id)
    ).fetchall()
    return [row.user_id for row in rows]


def task_notified_ids(db: Session, task_id: int) -> list[int]:
    """Ids marcados para el aviso de vencimiento de la tarea.

    El legacy resolvía esto con una consulta a pelo repetida en dos rutas de
    página (``programs.py:56`` y su gemela), y la de incidencias directamente
    **no lo hacía**: abrir "Notificar atraso" desde una incidencia mostraba los
    responsables en vez de los ya notificados.
    """
    from itcj2.apps.adhoc.models import adhoc_task_assignees

    rows = db.execute(
        adhoc_task_assignees.select()
        .where(
            adhoc_task_assignees.c.task_id == task_id,
            adhoc_task_assignees.c.notified_overdue.is_(True),
        )
        .order_by(adhoc_task_assignees.c.user_id)
    ).fetchall()
    return [row.user_id for row in rows]


# ==========================================================================
# Vuelta segura
# ==========================================================================

def safe_return_to(value: Optional[str], fallback: str) -> str:
    """Valida el ``?return_to=`` de la pantalla de asignación.

    Solo se acepta una ruta **relativa dentro de la propia app** (``/adhoc/…``).
    Cualquier otra cosa —URL absoluta, ``//host`` protocol-relative, ``\\host``,
    o una ruta de otra app— cae al *fallback*. Sin esto la pantalla sería un
    redirector abierto: el legacy usaba ``history.back()``, que no se puede
    forzar desde fuera, así que introducir un parámetro de vuelta introduce un
    riesgo que hay que cerrar aquí.
    """
    ruta = (value or "").strip()
    if not ruta:
        return fallback
    # "//evil.com" y "/\evil.com" son URLs de host en los navegadores.
    if not ruta.startswith("/") or ruta.startswith("//") or ruta.startswith("/\\"):
        return fallback
    if not (ruta == "/adhoc" or ruta.startswith("/adhoc/")):
        return fallback
    return ruta
