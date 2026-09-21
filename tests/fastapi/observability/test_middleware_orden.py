"""Orden de los middleware de usuario de la app real.

`add_middleware` inserta en el índice 0 de `user_middleware`: el ÚLTIMO
registrado queda el más EXTERNO. `ObservabilityMiddleware` tiene que ser ese,
para cronometrar también el trabajo de `JWTMiddleware` y ver las excepciones
que salgan de él. "El más externo" se lee siempre como "el más externo DE LOS
DE USUARIO": `ServerErrorMiddleware` lo envuelve por encima (plan §9.15).

No depende de BD: `create_app()` solo arma routers y middleware.
"""
from itcj2.main import create_app
from itcj2.middleware import JWTMiddleware
from itcj2.observability.middleware import ObservabilityMiddleware


def test_observability_is_the_outermost_user_middleware():
    classes = [m.cls for m in create_app().user_middleware]

    assert classes[0] is ObservabilityMiddleware
    # Registrado dos veces emitiría dos líneas-resumen por petición.
    assert classes.count(ObservabilityMiddleware) == 1
    # Por fuera del JWT: su tiempo cuenta en duration_ms.
    assert JWTMiddleware in classes[1:]
