#!/usr/bin/env bash
# Daily pipeline: fetch → update Elo/Poisson → write predictions
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}/src:${PYTHONPATH:-}"

echo "[$(date -Iseconds)] SoccerAN daily update starting..."
python -m socceran fetch
python -m socceran update
python -m socceran predict
echo "[$(date -Iseconds)] Done. See out/"
