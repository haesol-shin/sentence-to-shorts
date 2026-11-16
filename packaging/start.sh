#!/bin/sh
# Start the installed app with the bundled interpreter. No Python from PATH is used, and
# the script calls no external command, so it also runs with an empty PATH.
set -eu
case "$0" in
  */*) here=${0%/*} ;;
  *) here=. ;;
esac
here=$(cd "$here" && pwd)
exec "$here/python/bin/python3.11" "$here/launch.py" "$@"
