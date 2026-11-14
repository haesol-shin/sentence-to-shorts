#!/bin/sh
# Start the installed app with the bundled interpreter and package folder. The probe checks
# that the tar keeps this file executable and that no interpreter from PATH is used.
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHONPATH="$here/site-packages${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPATH
exec "$here/python/bin/python3.11" "$here/launcher.py" "$@"
