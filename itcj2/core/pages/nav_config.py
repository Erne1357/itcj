"""
Registro de páginas y render del shell de configuración (/itcj/config).

Contrato C1 del plan core-config-revamp: espejo de
itcj2/apps/helpdesk/pages/nav.py (HD_PAGE_MODULES / ENDPOINT_TO_ACTIVE_PAGE /
render_helpdesk) adaptado al shell de config:

  - CONFIG_PAGE_MODULES: page_key -> módulos JS. Una entrada aquí = página
    MIGRADA al controller window.ConfigPage (navegable por hx-boost). Lista
    vacía = página migrada sin JS propio.
  - ENDPOINT_TO_PAGE: patrón de URL -> page_key (las 12 páginas de config.py).
    Es la fuente de verdad del boost island: un link del sidebar solo lleva
    hx-boost si su URL resuelve a un page_key registrado en CONFIG_PAGE_MODULES
    Y la página ACTUAL también está registrada (origen y destino migrados).
  - render_config(): wrapper de render() que inyecta el contexto del shell.
"""
from __future__ import annotations

import re

import markupsafe
from fastapi import Request
from fastapi.responses import HTMLResponse

from itcj2.templates import render, sv

# Kill-switch global del boost (rollback instantáneo a navegación clásica).
CONFIG_BOOST_ENABLED = True

# page_key -> módulos JS del registry cliente (ConfigPage). Solo páginas
# MIGRADAS. Rutas relativas se sirven desde /static/core/ y se versionan con
# sv(); URLs http(s):// (CDN) se pasan tal cual. Orden = orden de carga.
CONFIG_PAGE_MODULES: dict[str, list[str]] = {}

# Patrón de URL -> page_key. Cubre las 12 páginas HTML de core/pages/config.py
# (los endpoints AJAX/OAuth de email NO son páginas y no van aquí).
ENDPOINT_TO_PAGE: dict[str, str] = {
    "/itcj/config": "index",
    "/itcj/config/apps": "apps",
    "/itcj/config/roles": "roles",
    "/itcj/config/apps/{app_key}/permissions": "permissions",
    "/itcj/config/themes": "themes",
    "/itcj/config/email": "email",
    "/itcj/config/system/tasks": "tasks",
    "/itcj/config/users": "users",
    "/itcj/config/users/{user_id}": "user_detail",
    "/itcj/config/departments": "departments",
    "/itcj/config/departments/{department_id}": "department_detail",
    "/itcj/config/positions/{position_id}": "position_detail",
}

# page_key -> entrada activa del sidebar. Sustituye a los 12
# `{% set sidebar_active %}` de los templates (se retiran en Task 2).
SIDEBAR_BY_PAGE: dict[str, str] = {
    "index": "dashboard",
    "apps": "apps",
    "permissions": "apps",  # permisos no tiene entrada propia: resalta Apps
    "roles": "roles",
    "themes": "themes",
    "email": "email",
    "tasks": "tasks",
    "users": "users",
    "user_detail": "users",
    "departments": "departments",
    "department_detail": "departments",
    "position_detail": "departments",
}


def _url_template_to_regex(template: str) -> "re.Pattern[str]":
    """'/a/{id}/b' -> ^/a/[^/]+/b$ (mismo helper que helpdesk nav.py:199)."""
    parts = re.split(r"\{[^}]+\}", template)
    return re.compile("^" + "[^/]+".join(re.escape(p) for p in parts) + "$")


_URL_PATTERNS: list[tuple["re.Pattern[str]", str]] | None = None


def _url_patterns() -> list[tuple["re.Pattern[str]", str]]:
    """(regex, page_key) ordenados: URLs literales antes que las de placeholder."""
    global _URL_PATTERNS
    if _URL_PATTERNS is None:
        ordered = sorted(
            ENDPOINT_TO_PAGE.items(), key=lambda kv: ("{" in kv[0], -kv[0].count("/"))
        )
        _URL_PATTERNS = [(_url_template_to_regex(u), p) for u, p in ordered]
    return _URL_PATTERNS


def url_to_page(url: str) -> str | None:
    """Resuelve una URL de config concreta -> page_key (o None). Ignora query/fragment."""
    if not url:
        return None
    path = url.split("#", 1)[0].split("?", 1)[0]
    for pattern, page_key in _url_patterns():
        if pattern.match(path):
            return page_key
    return None


def is_boostable_url(url: str) -> bool:
    """True si url apunta a una página de config MIGRADA y el boost está activo."""
    if not CONFIG_BOOST_ENABLED:
        return False
    page = url_to_page(url)
    return page is not None and page in CONFIG_PAGE_MODULES


def boost_urls_regex() -> str:
    """Alternación regex de las URLs migradas, para el cliente (data-cfg-boost-urls).

    ConfigPage.navigate() la usa como whitelist: destino que no matchea ->
    recarga completa (páginas no migradas navegan clásico).
    """
    if not CONFIG_BOOST_ENABLED:
        return ""
    return "|".join(
        _url_template_to_regex(tmpl).pattern
        for tmpl, page in ENDPOINT_TO_PAGE.items()
        if page in CONFIG_PAGE_MODULES
    )


def _module_url(path: str) -> str:
    """URL final de un módulo: CDN tal cual; estático local versionado con sv()."""
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"/static/core/{path}?v={sv('core', path)}"


def _modules_attr(page_key: str) -> str:
    """Valor de data-cfg-modules: URLs de módulos separadas por '|'."""
    return "|".join(_module_url(p) for p in CONFIG_PAGE_MODULES.get(page_key, []))


_BOOST_ATTR = markupsafe.Markup('hx-boost="true"')
_EMPTY = markupsafe.Markup("")


def render_config(
    request: Request,
    template_name: str,
    page_key: str,
    ctx: dict | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """Renderiza una página de config inyectando el contexto del shell (C1).

    Inyecta:
      - cfg_page / cfg_modules / cfg_boost_urls -> atributos data-cfg-* de #cfgMain
      - cfg_boost: True solo si la página ACTUAL está migrada (boost island)
      - cfg_boost_attr(url): Markup 'hx-boost="true"' o '' por-link del sidebar
      - cfg_data: dict {sufijo-data-attr: valor} -> data-* extra en #cfgMain
        (constantes de servidor para el JS; sustituye a <script>const X=...</script>)
      - sidebar_active: derivado del page_key (los templates ya no lo setean)
    """
    boost_active = CONFIG_BOOST_ENABLED and page_key in CONFIG_PAGE_MODULES

    def cfg_boost_attr(url: str) -> markupsafe.Markup:
        return _BOOST_ATTR if boost_active and is_boostable_url(url) else _EMPTY

    merged = dict(ctx or {})
    merged.setdefault("cfg_data", {})
    merged.update(
        {
            "cfg_page": page_key,
            "cfg_modules": _modules_attr(page_key),
            "cfg_boost": boost_active,
            "cfg_boost_urls": boost_urls_regex(),
            "cfg_boost_attr": cfg_boost_attr,
            "sidebar_active": SIDEBAR_BY_PAGE.get(page_key, ""),
        }
    )
    return render(request, template_name, merged, status_code)
