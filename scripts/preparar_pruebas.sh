#!/usr/bin/env bash
# Descarga las respuestas grabadas de supermercapy 0.1.0 (la versión fijada en
# pyproject.toml) para las pruebas de integración sin red.
set -euo pipefail
destino="$(cd "$(dirname "$0")/.." && pwd)/tests/.supermercapy"
if [ -d "$destino/.git" ]; then
  echo "ya está en $destino"
  exit 0
fi
git -c advice.detachedHead=false clone --quiet --depth 1 --branch v0.1.0 https://github.com/jtayped/supermercapy.git "$destino"
echo "respuestas grabadas en $destino"
