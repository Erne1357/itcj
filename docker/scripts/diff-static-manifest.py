#!/usr/bin/env python3
"""docker/scripts/diff-static-manifest.py

Compara dos manifiestos de estaticos y notifica al servidor los archivos
que cambiaron.

Uso:
    python3 diff-static-manifest.py \\
        --old-manifest old.json \\
        --new-manifest new.json \\
        --notify-url http://localhost:8080/api/core/v1/deploy/static-update

El script:
1. Compara los hashes de cada archivo entre el manifiesto viejo y nuevo
2. Identifica archivos nuevos, modificados o eliminados
3. Envia POST al servidor con la lista de archivos afectados
4. El servidor emite un evento WebSocket a los clientes conectados
"""
import argparse
import json
import os
import sys
import urllib.request
import urllib.error


def load_manifest(path):
    """Carga un manifiesto desde archivo o stdin."""
    if path == '-':
        return json.load(sys.stdin)
    with open(path) as f:
        return json.load(f)


def diff_manifests(old, new):
    """Compara dos manifiestos y retorna los archivos que cambiaron.

    Returns:
        dict con keys: added, modified, removed
    """
    changed = {
        'added': [],
        'modified': [],
        'removed': []
    }

    all_apps = set(old.keys()) | set(new.keys())

    for app in all_apps:
        old_files = old.get(app, {})
        new_files = new.get(app, {})

        # Ignorar el hash de directorio
        old_files = {k: v for k, v in old_files.items() if k != '__dir_hash__'}
        new_files = {k: v for k, v in new_files.items() if k != '__dir_hash__'}

        all_files = set(old_files.keys()) | set(new_files.keys())

        for filename in all_files:
            full_path = f"{app}/{filename}"
            old_hash = old_files.get(filename)
            new_hash = new_files.get(filename)

            if old_hash is None and new_hash is not None:
                changed['added'].append(full_path)
            elif old_hash is not None and new_hash is None:
                changed['removed'].append(full_path)
            elif old_hash != new_hash:
                changed['modified'].append(full_path)

    return changed


def notify_server(url, changed_files, deploy_key):
    """Envia la lista de archivos cambiados al servidor."""
    # Combinar todos los cambios en una sola lista
    all_changed = changed_files['added'] + changed_files['modified']

    if not all_changed:
        return None

    payload = json.dumps({
        'changed': all_changed,
        'removed': changed_files['removed'],
        'deploy_key': deploy_key
    }).encode('utf-8')

    req = urllib.request.Request(
        url,
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST'
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        print(f"ERROR: HTTP {e.code} - {e.reason}")
        return None
    except urllib.error.URLError as e:
        print(f"ERROR: No se pudo conectar al servidor: {e.reason}")
        return None
    except Exception as e:
        print(f"ERROR: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description='Compara manifiestos de estaticos y notifica cambios'
    )
    parser.add_argument(
        '--old-manifest',
        required=True,
        help='Ruta al manifiesto anterior (o - para stdin)'
    )
    parser.add_argument(
        '--new-manifest',
        required=True,
        help='Ruta al manifiesto nuevo'
    )
    parser.add_argument(
        '--notify-url',
        required=True,
        help='URL del endpoint de notificacion'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Solo mostrar cambios sin notificar'
    )
    args = parser.parse_args()

    # Cargar manifiestos
    try:
        old = load_manifest(args.old_manifest)
    except FileNotFoundError:
        print("WARN: Manifiesto anterior no encontrado, asumiendo vacio")
        old = {}
    except json.JSONDecodeError as e:
        print(f"ERROR: Manifiesto anterior invalido: {e}")
        old = {}

    try:
        new = load_manifest(args.new_manifest)
    except FileNotFoundError:
        print(f"ERROR: Manifiesto nuevo no encontrado: {args.new_manifest}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: Manifiesto nuevo invalido: {e}")
        sys.exit(1)

    # Comparar
    changed = diff_manifests(old, new)

    total = len(changed['added']) + len(changed['modified']) + len(changed['removed'])

    if total == 0:
        print(">>> No hubo cambios en archivos estaticos.")
        return

    # Mostrar resumen
    print(f">>> Cambios detectados en archivos estaticos ({total} total):")

    if changed['added']:
        print(f"    Nuevos ({len(changed['added'])}):")
        for f in sorted(changed['added'])[:10]:
            print(f"      + {f}")
        if len(changed['added']) > 10:
            print(f"      ... y {len(changed['added']) - 10} mas")

    if changed['modified']:
        print(f"    Modificados ({len(changed['modified'])}):")
        for f in sorted(changed['modified'])[:10]:
            print(f"      ~ {f}")
        if len(changed['modified']) > 10:
            print(f"      ... y {len(changed['modified']) - 10} mas")

    if changed['removed']:
        print(f"    Eliminados ({len(changed['removed'])}):")
        for f in sorted(changed['removed'])[:10]:
            print(f"      - {f}")
        if len(changed['removed']) > 10:
            print(f"      ... y {len(changed['removed']) - 10} mas")

    # Notificar
    if args.dry_run:
        print(">>> Modo dry-run: no se notificara al servidor")
        return

    deploy_key = os.environ.get('DEPLOY_SECRET', '')

    print(f">>> Notificando al servidor: {args.notify_url}")
    status = notify_server(args.notify_url, changed, deploy_key)

    if status:
        print(f">>> Notificacion enviada exitosamente (HTTP {status})")
    else:
        print("WARN: No se pudo notificar al servidor (el deploy continua)")


if __name__ == '__main__':
    main()
