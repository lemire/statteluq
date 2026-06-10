#!/usr/bin/env bash
#
# Restart the TELUQ Inscriptions Explorer.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"$SCRIPT_DIR/stop.sh" || true
"$SCRIPT_DIR/start.sh"
