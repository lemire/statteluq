#!/usr/bin/env bash
#
# Start the TELUQ Inscriptions Explorer (Streamlit) using uv.
# Runs in the background and records the PID.
#
set -euo pipefail

PID_FILE=".streamlit.pid"
LOG_FILE=".streamlit.log"
PORT="${PORT:-8501}"

# Check if already running
if [[ -f "$PID_FILE" ]]; then
  PID=$(cat "$PID_FILE")
  if ps -p "$PID" > /dev/null 2>&1; then
    echo "Streamlit is already running (PID $PID)."
    echo "URL: http://localhost:$PORT"
    echo "Use ./stop.sh or ./restart.sh"
    exit 0
  else
    echo "Removing stale PID file."
    rm -f "$PID_FILE"
  fi
fi

echo "Starting statteluq with uv (port $PORT)..."

# Ensure uv is available
if ! command -v uv >/dev/null 2>&1; then
  echo "Error: 'uv' not found in PATH."
  echo "Install uv: https://docs.astral.sh/uv/getting-started/installation/"
  exit 1
fi

# Run via uv (creates/syncs .venv automatically on first use)
uv run -- \
  streamlit run app.py \
    --server.port "$PORT" \
    --server.headless true \
    --server.address 0.0.0.0 \
    > "$LOG_FILE" 2>&1 &

PID=$!
echo "$PID" > "$PID_FILE"

echo "Started (PID $PID)"
echo "Logs: $LOG_FILE"
echo "URL:  http://localhost:$PORT"
echo
echo "Stop with: ./stop.sh"
echo "Restart:   ./restart.sh"
