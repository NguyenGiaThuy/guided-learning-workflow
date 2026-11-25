#!/bin/sh
# Start learning.py with the first working interpreter. python3 may be the
# Windows Store stub, so each candidate is tested before use.
dir=$(dirname "$0")
for py in python python3; do
  if "$py" -c '' >/dev/null 2>&1; then
    exec "$py" "$dir/learning.py" "$@"
  fi
done
echo "python not found" >&2
exit 127
