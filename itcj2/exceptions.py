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

    El exception handler muestra la página de error 403. El destino del botón
    depende de ``has_app_access``:

    - ``False`` (sin acceso a la app): botón al panel core y, dentro del
      iframe del dashboard, cierra la ventana de la app (no hay "inicio" de
      la app al cual volver).
    - ``True`` (tiene acceso a la app pero le falta el permiso/rol de esta
      página concreta): botón al "inicio" de la app, navegando dentro del
      iframe (sigue en la app).
    """

    def __init__(self, *, has_app_access: bool = False) -> None:
        self.has_app_access = has_app_access
        super().__init__()
