#!/usr/bin/env bash
#
# Stop the TELUQ Inscriptions Explorer started by start.sh.
#
set -euo pipefail

PID_FILE=".streamlit.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "No PID file found ($PID_FILE)."
  echo "Nothing to stop (or it was not started with ./start.sh)."
  exit 1
fi

PID=$(cat "$PID_FILE")

if ps -p "$PID" > /dev/null 2>&1; then
  echo "Stopping Streamlit (PID $PID)..."
  kill "$PID" 2>/dev/null || true

  # Wait up to 5 seconds for graceful shutdown
  for i in {1..5}; do
    if ! ps -p "$PID" > /dev/null 2>&1; then
      break
    fi
    sleep 1
  done

  if ps -p "$PID" > /dev/null 2>&1; then
    echo "Process did not exit, force killing..."
    kill -9 "$PID" 2>/dev/null || true
    sleep 1
  fi

  echo "Stopped."
else
  echo "Process $PID is not running."
fi

rm -f "$PID_FILE"
