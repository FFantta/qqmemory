#!/bin/zsh
set -e
cd -- "${0:A:h:h}"
export PYTHONPYCACHEPREFIX="${TMPDIR:-/tmp}/qqmemory-pycache"
exec ./runtime/qmemory-venv/bin/python scripts/serve-memory.py --port 17890
