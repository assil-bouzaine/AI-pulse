#!/usr/bin/env sh
# One-click AI Pulse for macOS / Linux:  ./run.sh   (first time: chmod +x run.sh)
# First run creates the virtual environment; every run opens the site when done.
set -e
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
    echo "First run: setting up Python environment, this takes a minute..."
    python3 -m venv .venv
    .venv/bin/python -m pip install --quiet -r requirements.txt
fi

exec .venv/bin/python -m ai_pulse --open "$@"
