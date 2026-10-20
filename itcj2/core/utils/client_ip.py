"""IP real del cliente cuando la app corre detrás de nginx.

`request.client.host` es la IP del PEER TCP directo. Con nginx delante, ese peer
es siempre nginx, así que todo internet acaba compartiendo una sola dirección:
el rate limit por IP del login (``rl:login:ip:{ip}``) contaba en un único cubo
para todos los visitantes, lo que a la vez lo hace inservible como defensa y
convierte a cualquiera en capaz de agotarlo para los demás.

Se prefiere **`X-Real-IP`** y no `X-Forwarded-For`, y el orden importa:

- nginx lo fija con ``proxy_set_header X-Real-IP $remote_addr``
  (`docker/nginx/nginx.dev.conf:94`, `nginx.prod.conf:124`). `proxy_set_header`
  **sobrescribe**, así que un cliente no puede falsificarlo a través de nuestro
  nginx.
- `X-Forwarded-For` se construye con ``$proxy_add_x_forwarded_for``, que
  **añade** el peer a lo que el cliente mandara. Un cliente que envíe
  ``X-Forwarded-For: 1.2.3.4`` produce ``1.2.3.4, <ip real>``: la entrada de la
  IZQUIERDA es del atacante. Por eso, si hay que caer a XFF, se toma la de la
  **derecha**, que es la que puso nuestro propio proxy.

Esto presupone que al backend solo se llega por nginx. Hoy se cumple: el puerto
8001 no está publicado al host en ningún compose (`docker/compose/*.yml`), solo
existe dentro de la red de Docker. Si alguna vez se expone directo, estas
cabeceras pasan a ser falsificables y hay que introducir una lista de proxies de
confianza.
"""
from __future__ import annotations


def client_ip(request) -> str:
    """IP del cliente final. Nunca lanza; devuelve 'unknown' si no la puede determinar."""
    real = request.headers.get("X-Real-IP")
    if real:
        real = real.strip()
        if real:
            return real

    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        # La de más a la derecha es la que añadió nuestro proxy; las de la
        # izquierda pueden venir del cliente. Ver docstring del módulo.
        parts = [p.strip() for p in fwd.split(",") if p.strip()]
        if parts:
            return parts[-1]

    return request.client.host if request.client else "unknown"
