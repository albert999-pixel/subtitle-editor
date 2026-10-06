#!/bin/bash
cd "$(dirname "$0")" || exit 1
if command -v python3.11 >/dev/null 2>&1; then
  python3.11 scripts/manage.py install
else
  echo "Install Python 3.11 from https://www.python.org/downloads/ then try again."
  exit 1
fi
result=$?
read -r -p "Press Enter to close..."
exit "$result"
