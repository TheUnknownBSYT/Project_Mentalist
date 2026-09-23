#!/bin/bash
cd -- "$(dirname -- "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  echo 'Python 3.10+ is needed for market fetching. You can still open index.html directly.'
  read -r -p 'Press Enter to close.'
  exit 1
fi
python3 server.py --open
read -r -p 'Press Enter to close.'
