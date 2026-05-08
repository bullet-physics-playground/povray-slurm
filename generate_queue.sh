#!/usr/bin/env bash

usage() {
  echo "Usage: $0 <frames> [name] [priority]"
  echo ""
  echo "Arguments:"
  echo "  frames    Number of frames to generate"
  echo "  name      Job name (default: 'render <frames>f')"
  echo "  priority  Job priority, higher = more urgent (default: 0)"
  exit 1
}

FRAMES=${1:?$(usage)}
NAME=${2:-"render ${FRAMES}f"}
PRIORITY=${3:-0}

JOB_ID=$(python3 db.py job-create "$NAME" "$PRIORITY" "$FRAMES")
echo "Job $JOB_ID created: $NAME (priority $PRIORITY) — $FRAMES frames"

echo ""
echo "Submit workers with:"
echo "  sbatch dynamic_ws.slurm"
