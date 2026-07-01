#!/usr/bin/env bash
set -euo pipefail

# Ensure state directories exist
mkdir -p /state/runs/accepted /state/runs/launchers /state/runs/config

# Start FastAPI server
exec python -m uvicorn backend.main:app \
	--host 0.0.0.0 \
	--port 3100 \
	--log-level info
