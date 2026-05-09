#!/usr/bin/env bash

usage() {
  echo "Usage: $0 [FRAMES] [WIDTH] [HEIGHT]"
  echo ""
  echo "Arguments:"
  echo "  FRAMES   Number of frames (default: 120)"
  echo "  WIDTH   Image width in pixels (default: 1280)"
  echo "  HEIGHT  Image height in pixels (default: 720)"
  echo ""
  echo "Examples:"
  echo "  $0                # 120 frames at 1280x720"
  echo "  $0 60             # 60 frames at 1280x720"
  echo "  $0 60 640 480    # 60 frames at 640x480"
  echo "  $0 240 1920 1080 # 240 frames at 1920x1080"
  exit 1
}

check() {
  if [ $? -eq 0 ]; then
    printf '\033[32m\xe2\x9c\x93\033[0m %s\n' "$1"
  else
    printf '\033[31m\xe2\x9c\x97\033[0m %s\n' "$1"
    exit 1
  fi
}

[ "$1" = "-h" ] || [ "$1" = "--help" ] && usage

FRAMES=${1:-120}
WIDTH=${2:-1280}
HEIGHT=${3:-720}

mkdir -p logs

JOB_ID=$(python3 db.py job-create "render ${FRAMES}f ${WIDTH}x${HEIGHT}" 0 "$FRAMES" "$WIDTH" "$HEIGHT")
check "Created job"

JOB_DIR=$(python3 db.py job-info "$JOB_ID" | python3 -c "import json,sys; print(json.load(sys.stdin).get('output_dir','frames'))")
check "Got job info"

mkdir -p "$JOB_DIR"
check "Created output directory"

rm -f "$JOB_DIR"/*.png
check "Cleaned output directory"

sed -e "s/FRAME_COUNT/$FRAMES/" \
    -e "s/WIDTH_VAL/$WIDTH/" \
    -e "s/HEIGHT_VAL/$HEIGHT/" \
    animation.ini > animation_render.ini
check "Generated animation.ini"

echo "Created job $JOB_ID (priority 0) — $FRAMES frames"

BENCH=$(sbatch benchmark.slurm | awk '{print $4}')
check "Submitted benchmark job"
echo "Benchmark job: $BENCH"

JOB=$(sbatch --dependency=afterok:$BENCH --array=1-$FRAMES --nodes=1 --export=JOB_ID=$JOB_ID frame.slurm | awk '{print $4}')
check "Submitted frame rendering job"
echo "Frame rendering job: $JOB"

FFMPEG=$(sbatch --dependency=afterany:$JOB ffmpeg.slurm | awk '{print $4}')
check "Submitted ffmpeg job"
echo "FFmpeg job: $FFMPEG"
