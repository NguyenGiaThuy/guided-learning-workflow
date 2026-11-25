#!/bin/sh
# Start learning.py with the first interpreter that works and is new enough.
# python3 may be the Windows Store stub, so each candidate is tested before use.
dir=$(dirname "$0")
for py in python python3; do
  if "$py" -c 'import sys; sys.exit(sys.version_info < (3, 9))' >/dev/null 2>&1; then
    exec "$py" "$dir/learning.py" "$@"
  fi
done
echo "guided-learning: Python 3.9 or newer was not found, neither as python nor as python3." >&2
exit 127
