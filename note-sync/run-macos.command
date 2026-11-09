#!/bin/zsh
set -e

SCRIPT_DIR="${0:A:h}"
export PYTHONPATH="$SCRIPT_DIR/src"
export PYTHONPYCACHEPREFIX="${TMPDIR:-/tmp}/notesync-pycache"
export TK_SILENCE_DEPRECATION=1
exec /usr/bin/python3 -m notesync
