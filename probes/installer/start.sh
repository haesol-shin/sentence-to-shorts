#!/bin/sh
# Start the installed app with the bundled environment. The probe checks that the tar
# archive keeps this file executable and that the interpreter is the installed one.
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$here/env/bin/python" "$here/launcher.py" "$@"
