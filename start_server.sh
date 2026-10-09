#!/usr/bin/env bash
# Real Estate CRM - FastAPI Server Starter
cd "$(dirname "$0")"
export PYTHONPATH=src/backend
echo "Starting RECRM FastAPI server on http://localhost:8000..."
exec .venv/bin/python src/backend/run.py

