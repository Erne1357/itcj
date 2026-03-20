"""
Excepciones personalizadas para rutas de páginas HTML en FastAPI.

Las excepciones de páginas generan respuestas de redirección en lugar de
JSON de error, manteniendo la experiencia de navegación web.
Los handlers se registran en itcj2/main.py.
"""


class PageLoginRequired(Exception):
    """Se lanza cuando una página requiere autenticación y el usuario no está logueado.

    El exception handler redirige a /itcj/login.
    """


class PageForbidden(Exception):
    """Se lanza cuando el usuario no tiene los permisos requeridos para una página.

    El exception handler redirige al dashboard o muestra página de error.
    """
