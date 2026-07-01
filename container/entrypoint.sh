#!/usr/bin/env bash
set -euo pipefail

# Ensure state directories exist
mkdir -p /state/runs/accepted /state/runs/launchers /state/runs/config

# Add app directory to Python path
export PYTHONPATH=/app

# Start FastAPI server
exec python3 -m uvicorn backend.main:app \
  --host 0.0.0.0 \
  --port 3100 \
  --log-level info
