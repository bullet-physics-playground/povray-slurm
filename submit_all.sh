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

[ "$1" = "-h" ] || [ "$1" = "--help" ] && usage

FRAMES=${1:-120}
WIDTH=${2:-1280}
HEIGHT=${3:-720}

mkdir -p logs frames

rm -f frames/*.png

echo "$FRAMES" > .frames

sed -e "s/FRAME_COUNT/$FRAMES/" \
    -e "s/WIDTH_VAL/$WIDTH/" \
    -e "s/HEIGHT_VAL/$HEIGHT/" \
    animation.ini > animation_render.ini

./generate_queue.sh "$FRAMES"

BENCH=$(sbatch benchmark.slurm | awk '{print $4}')
echo "Benchmark job: $BENCH"

JOB=$(sbatch --dependency=afterok:$BENCH --array=1-$FRAMES --nodes=1 frame.slurm | awk '{print $4}')
echo "Frame rendering job: $JOB"

FFMPEG=$(sbatch --dependency=afterok:$JOB ffmpeg.slurm | awk '{print $4}')
echo "FFmpeg job: $FFMPEG"
