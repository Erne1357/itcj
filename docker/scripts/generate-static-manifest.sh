#!/usr/bin/env bash
# docker/scripts/generate-static-manifest.sh
#
# Genera static-manifest.json con el hash MD5 (primeros 8 chars) de cada
# archivo estatico, agrupado por app.
#
# Uso: bash docker/scripts/generate-static-manifest.sh
set -euo pipefail

# Detectar directorio del proyecto
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_DIR"

MANIFEST="static-manifest.json"

python3 << 'PYEOF'
import hashlib
import json
import os

apps = {
    'core':      'itcj/core/static',
    'agendatec': 'itcj/apps/agendatec/static',
    'helpdesk':  'itcj/apps/helpdesk/static',
    'vistetec':  'itcj/apps/vistetec/static',
}

manifest = {}

for app, base_dir in apps.items():
    manifest[app] = {}
    if not os.path.isdir(base_dir):
        continue
    for root, _, files in os.walk(base_dir):
        for f in sorted(files):
            # Ignorar archivos ocultos y de sistema
            if f.startswith('.'):
                continue
            filepath = os.path.join(root, f)
            # Ruta relativa desde el directorio static de la app
            rel = os.path.relpath(filepath, base_dir)
            try:
                with open(filepath, 'rb') as fh:
                    h = hashlib.md5(fh.read()).hexdigest()[:8]
                manifest[app][rel.replace(os.sep, '/')] = h
            except Exception as e:
                print(f"WARN: No se pudo hashear {filepath}: {e}")

# Hash por app (hash de todos los hashes del directorio)
for app in apps:
    if manifest[app]:
        combined = ''.join(sorted(manifest[app].values()))
        manifest[app]['__dir_hash__'] = hashlib.md5(combined.encode()).hexdigest()[:8]

with open('static-manifest.json', 'w') as f:
    json.dump(manifest, f, indent=2, sort_keys=True)

total_files = sum(len(v) - 1 for v in manifest.values() if v)  # -1 por __dir_hash__
print(f"Manifest generado: {total_files} archivos estaticos")
for app in sorted(apps.keys()):
    count = len(manifest[app]) - 1 if manifest[app] else 0
    dir_hash = manifest[app].get('__dir_hash__', 'N/A')
    print(f"  - {app}: {count} archivos (hash: {dir_hash})")
PYEOF

echo ">>> Archivo generado: $MANIFEST"
