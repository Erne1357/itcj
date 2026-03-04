# Imagen ligera de pgBouncer con soporte SCRAM-SHA-256
# Alpine 3.19 → pgBouncer 1.21.0
FROM alpine:3.19

RUN apk add --no-cache pgbouncer su-exec tzdata \
    && adduser -D -H -s /sbin/nologin pgb \
    && mkdir -p /tmp/pgbouncer \
    && chown pgb:pgb /tmp/pgbouncer

COPY entrypoint.sh /scripts/entrypoint.sh
RUN chmod +x /scripts/entrypoint.sh

ENTRYPOINT ["/bin/sh", "/scripts/entrypoint.sh"]
