#!/usr/bin/env bash

#SBATCH --job-name=pov_ffmpeg
#SBATCH --time=00:10:00
#SBATCH --output=logs/ffmpeg.out
#SBATCH --nodes=1

JOB_ID=${JOB_ID:-$(python3 db.py current-job | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('id',''))" 2>/dev/null)}

if [ -n "$JOB_ID" ]; then
  read JID FNAME TFRAMES OUT_DIR JNAME PRIO <<< "$(python3 db.py frame-info "${JOB_ID}:1" 2>/dev/null)"
  if [ -d "$OUT_DIR" ]; then
    ffmpeg -y -framerate 30 -i "$OUT_DIR/frame_%04d.png" -c:v libx264 -pix_fmt yuv420p "output_job${JOB_ID}.mp4"
    exit 0
  fi
fi

for d in frames/*/; do
  if ls "$d"frame_*.png &>/dev/null 2>&1; then
    JOB_ID=$(basename "$d" | sed 's/^job_\([0-9]*\)_.*/\1/')
    ffmpeg -y -framerate 30 -i "${d}frame_%04d.png" -c:v libx264 -pix_fmt yuv420p "output_job${JOB_ID}.mp4"
    exit 0
  fi
done
ffmpeg -y -framerate 30 -i "frames/frame_%04d.png" -c:v libx264 -pix_fmt yuv420p output.mp4
