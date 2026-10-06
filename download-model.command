#!/bin/bash
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  echo "Run install.command first."
  result=1
else
  .venv/bin/python scripts/manage.py download-model
  result=$?
fi
read -r -p "Press Enter to close..."
exit "$result"
