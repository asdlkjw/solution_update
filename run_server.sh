#!/bin/bash

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    uv venv
fi

echo "Installing dependencies..."
uv pip install -e .

echo "Starting Sisyphus server..."
uv run uvicorn app.main:app --host 0.0.0.0 --port 6888 --reload
